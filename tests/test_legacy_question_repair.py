import copy
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import generate_event_deep_dives as pipeline
import refresh_card_stories as cards
from deep_dive.analyze_event import ReviewedQuestions
from deep_dive.models import BinaryQuestion, EventAnalysis, QuestionRepairDraft
from deep_dive.save_analysis import save_analysis
from pydantic import ValidationError
from test_analysis_evidence import draft_data, research_bundle, NOW
from test_question_completeness import CHECKS, LONG_QUESTION, TRUNCATED_EVENT_513, TRUNCATED_EVENT_517, TRUNCATED_EVENT_518


def cached(text):
    analysis = draft_data(False)
    analysis['editorial_review'] = {'revision': 2, **CHECKS}
    analysis['binary_questions'][0]['question'] = text
    return {'event_id': 213, 'status': 'ready', 'generated_at': NOW.isoformat(),
            'analysis': analysis, 'research': {**research_bundle(False).model_dump(mode='json'), 'editorial_revision': 1}}


def editor(row):
    question = {**row['analysis']['binary_questions'][0], 'question': LONG_QUESTION}
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(output_parsed=ReviewedQuestions(
        binary_questions=[BinaryQuestion.model_validate(question)], **CHECKS))
    return client


class LegacyQuestionRepairTests(unittest.TestCase):
    def test_tolerant_read_preserves_copy_but_cannot_save_incomplete_question(self):
        for text in (TRUNCATED_EVENT_513, TRUNCATED_EVENT_517, TRUNCATED_EVENT_518, LONG_QUESTION):
            with self.subTest(text=text):
                data = cached(text)['analysis']
                original = copy.deepcopy(data)
                repair = QuestionRepairDraft.model_validate(data)
                self.assertEqual(repair.binary_questions[0].question, text)
                self.assertEqual(data, original)
                if text != LONG_QUESTION:
                    with self.assertRaises(ValidationError):
                        EventAnalysis.model_validate(repair.model_dump(mode='json'))
                    db = Mock()
                    with self.assertRaises(ValueError):
                        save_analysis(db, research_bundle(False), repair)
                    self.assertEqual(db.mock_calls, [])
                else:
                    self.assertEqual(repair.model_dump(), EventAnalysis.model_validate(data).model_dump())
        bad = cached(TRUNCATED_EVENT_517)['analysis']
        bad['binary_questions'][0]['choice_labels']['yes'] = None
        with self.assertRaises(ValidationError):
            QuestionRepairDraft.model_validate(bad)

    def test_cached_pipeline_repairs_fragments_without_research_or_touching_valid_ballots(self):
        for text in (TRUNCATED_EVENT_513, TRUNCATED_EVENT_517, TRUNCATED_EVENT_518, LONG_QUESTION):
            with self.subTest(text=text):
                row = cached(text)
                original = copy.deepcopy(row)
                event = {'id': 213, 'created_at': NOW.isoformat(), 'enough_data': True,
                         'is_visible': True, 'numeric_data': []}
                client, db = editor(row), Mock()
                def table(name):
                    query = Mock()
                    for method in ('select', 'gte', 'lte', 'order', 'in_'):
                        getattr(query, method).return_value = query
                    query.execute.return_value.data = [event] if name == 'events' else [row]
                    return query
                db.table.side_effect = table
                with ExitStack() as stack:
                    stack.enter_context(patch.dict(os.environ, {'SUPABASE_URL': 'https://example.invalid', 'SUPABASE_KEY': 'test', 'OPENAI_API_KEY': 'test'}))
                    stack.enter_context(patch.object(sys, 'argv', ['generate_event_deep_dives.py']))
                    patches = {'create_client': db, 'OpenAI': client, 'budget_client': client,
                               'country_eligible': True, 'balanced_event': True,
                               'event_thresholds': {213: 0}, 'current_score': 100,
                               'enforce_previous_year_gate': [], 'refresh_cover_questions': None,
                               'refresh_event_covers': None, 'refresh_background_contexts': [],
                               'publish_ready_events': None}
                    for name, value in patches.items():
                        stack.enter_context(patch.object(pipeline, name, return_value=value))
                    stack.enter_context(patch.object(pipeline, 'ECONOMY_MODE', False))
                    research = stack.enter_context(patch.object(pipeline, 'research_event'))
                    analyze = stack.enter_context(patch.object(pipeline, 'analyze_event'))
                    save = stack.enter_context(patch.object(pipeline, 'save_analysis'))
                    pipeline.main()
                    research.assert_not_called()
                    analyze.assert_not_called()
                    if text == LONG_QUESTION:
                        client.responses.parse.assert_not_called()
                        save.assert_not_called()
                    else:
                        client.responses.parse.assert_called_once()
                        save.assert_called_once()
                        repaired = save.call_args.args[2]
                        self.assertIs(type(repaired), EventAnalysis)
                        self.assertEqual(repaired.binary_questions[0].question, LONG_QUESTION)
                        self.assertTrue(save.call_args.kwargs['preserve_card_fields'])
                        for key in ('background', 'event_explanation', 'data_story', 'charts'):
                            self.assertEqual(repaired.model_dump(mode='json')[key], original['analysis'][key])
                        self.assertIn(text, client.responses.parse.call_args.kwargs['input'][-1]['content'])
                self.assertEqual(row, original)

    def test_card_refresh_repairs_qualitative_fragment_and_skips_valid_copy(self):
        for text in (TRUNCATED_EVENT_517, LONG_QUESTION):
            row = cached(text)
            row['analysis']['card_headline'] = 'Saved headline'
            original = copy.deepcopy(row)
            client, db = editor(row), Mock()
            write = db.table.return_value.update.return_value
            write.eq.return_value = write
            write.execute.return_value.data = [{'event_id': 213}]
            with patch.object(cards, 'read_all', return_value=[row]):
                cards.refresh_tradeoffs(db, client, 'test-model', [213])
            self.assertEqual(row, original)
            if text == LONG_QUESTION:
                client.responses.parse.assert_not_called()
                db.table.assert_not_called()
            else:
                client.responses.parse.assert_called_once()
                updated = db.table.return_value.update.call_args.args[0]['analysis']
                self.assertEqual(updated['binary_questions'][0]['question'], LONG_QUESTION)
                for key in ('card_headline', 'charts', 'data_story', 'background', 'event_explanation'):
                    self.assertEqual(updated[key], original['analysis'][key])
                self.assertEqual(EventAnalysis.model_validate(updated).binary_questions[0].question, LONG_QUESTION)


if __name__ == '__main__':
    unittest.main()

"""Ballot copy must survive generation, review and both storage layouts intact."""
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from deep_dive.analyze_event import ReviewedQuestions, analyze_event, complete_question_text
from deep_dive.models import BinaryQuestion, EventAnalysis, MAX_QUESTION_CHARACTERS, AnswerLabels, MAX_ANSWER_LABEL_CHARACTERS
from pydantic import ValidationError
from deep_dive.save_analysis import save_analysis
from popularity import question_ids
from audit_voting_questions import audit_questions
from deep_dive.question_style import ANSWER_LABEL_RULES
from generate_event_briefs import BriefDraft, review_one_brief, review_independent_briefs
from test_analysis_evidence import draft_data, research_bundle, NOW, SOURCE_A, SOURCE_B


LONG_QUESTION = (
    "Yerel ölçümde gözlenen artış, belediyenin yeni hizmet kararının daha fazla kişiye "
    "ulaştığını mı gösteriyor, yoksa önceki dönemde karşılanamayan talebin etkisini mi yansıtıyor?"
)
TRUNCATED_EVENT_517 = (
    "Yaş ve prim gününe göre farklılaştırma uygulanırsa, düzenleme emekliler arasındaki gelir farklarını,"
)
TRUNCATED_EVENT_518 = (
    "Şüphelinin yakalanması, soruşturmanın odağını saldırıların koşullarını açıklığa kavuşturmaya kaydırı"
)
TRUNCATED_EVENT_513 = (
    "Bu yatırım taahhüdü, Türkiye’de içerik üretimini ve sektöre yeni katılımları belirgin biçimde geniş "
)
LONG_LABELS = {
    "yes": "Daha fazla kişiye ulaşıldığını gösteriyor",
    "no": "Önceki dönemde karşılanamayan talebi yansıtıyor",
    "unsure": "İki etkiyi ayırmak için daha fazla veri gerekiyor",
}
CHECKS = dict(event_specific=True, matches_displayed_evidence=True,
              evidence_relevant=True, not_factual_recall=True, tradeoff_present=True,
              balanced_choices=True, non_normative=True, substantive_disagreement=True,
              question_intent="event_implication")


class QuestionCompletenessTests(unittest.TestCase):
    def test_short_and_long_complete_answer_labels_are_preserved(self):
        for labels in ({"yes": "Evet", "no": "Hayır", "unsure": "Belirsiz"}, LONG_LABELS):
            with self.subTest(labels=labels):
                self.assertEqual(AnswerLabels.model_validate(labels).model_dump(), labels)
        self.assertTrue(all(len(label) > 24 for label in LONG_LABELS.values()))

    def test_answer_label_safety_bound_rejects_instead_of_truncating(self):
        for key in ("yes", "no", "unsure"):
            with self.subTest(key=key):
                labels = {**LONG_LABELS, key: "a" * MAX_ANSWER_LABEL_CHARACTERS}
                self.assertEqual(AnswerLabels.model_validate(labels).model_dump(), labels)
                self.assertEqual(AnswerLabels.model_json_schema()["properties"][key]["maxLength"],
                                 MAX_ANSWER_LABEL_CHARACTERS)
                with self.assertRaises(ValidationError):
                    AnswerLabels.model_validate({**labels, key: labels[key] + "a"})

    def test_event_517_incomplete_text_is_rejected_by_all_generation_schemas(self):
        self.assertEqual(len(TRUNCATED_EVENT_517), 100)
        self.assertFalse(complete_question_text(TRUNCATED_EVENT_517))
        draft = draft_data(numeric=False)
        draft["editorial_review"] = CHECKS
        draft["binary_questions"][0]["question"] = TRUNCATED_EVENT_517
        for model, payload in (
            (BinaryQuestion, draft["binary_questions"][0]),
            (EventAnalysis, draft),
            (ReviewedQuestions, {"binary_questions": draft["binary_questions"], **CHECKS}),
            (BriefDraft, {"event_id": 213, "evidence_article_ids": [1, 2], "analysis": draft}),
        ):
            with self.subTest(model=model.__name__), self.assertRaises(ValidationError):
                model.model_validate(payload)

    def test_read_only_audit_identifies_three_live_examples_and_preserves_input(self):
        rows = [{"event_id": event_id, "questions": [{"question": text}]} for event_id, text in
                [(517, TRUNCATED_EVENT_517), (518, TRUNCATED_EVENT_518),
                 (513, TRUNCATED_EVENT_513), (511, LONG_QUESTION)]]
        rows[2]["questions"][0]["choice_labels"] = {
            "yes": "Evet; daha fazla yapımın", "no": "Hayır; etkinin sınırlı", "unsure": "Sonuçlar için erken"}
        original = copy.deepcopy(rows)
        report = audit_questions({"events": rows})
        self.assertEqual([item["event_id"] for item in report["findings"]], [513, 517, 518])
        self.assertTrue(all(item["characters"] == 100 for item in report["findings"]))
        self.assertEqual(rows, original)
        self.assertEqual(audit_questions({"events": rows}), report)
        self.assertEqual(len(audit_questions({"events": rows}, [513])["findings"]), 1)
        self.assertEqual(audit_questions([{"event_id": 513, "analysis": {"binary_questions": rows[2]["questions"]}}])["findings"], report["findings"][:1])
        with self.assertRaises(ValidationError):
            BinaryQuestion.model_validate({**draft_data(False)["binary_questions"][0], "question": TRUNCATED_EVENT_513})

    def test_event_518_mid_word_truncation_is_rejected(self):
        self.assertEqual(len(TRUNCATED_EVENT_518), 100)
        self.assertFalse(complete_question_text(TRUNCATED_EVENT_518))
        payload = draft_data(numeric=False)["binary_questions"][0]
        with self.assertRaises(ValidationError):
            BinaryQuestion.model_validate({**payload, "question": TRUNCATED_EVENT_518})

    def test_independent_brief_cannot_publish_event_517_truncation(self):
        draft = draft_data(numeric=False)
        draft["editorial_review"] = CHECKS
        draft["binary_questions"][0]["question"] = TRUNCATED_EVENT_517
        response = {"events": [{"event_id": 213, "evidence_article_ids": [1, 2], "analysis": draft}]}
        client, db = Mock(), Mock()
        client.responses.parse.side_effect = lambda **kwargs: SimpleNamespace(
            output_parsed=kwargs["text_format"].model_validate(response))
        with self.assertRaises(ValidationError):
            review_one_brief(client, db, {"event_id": 213, "articles": []},
                             NOW)
        self.assertEqual(db.mock_calls, [])

    def test_incomplete_middle_brief_does_not_block_valid_independent_stories(self):
        payloads = {event_id: {"event_id": event_id, "articles": [
            {"id": index, "source": source, "title": "Kaynak haberi",
             "description": "Kaynağın yayımladığı özgün açıklama.",
             "url": url, "published_at": NOW.isoformat()}
            for index, source, url in [(1, "Birinci", SOURCE_A), (2, "İkinci", SOURCE_B)]
        ]} for event_id in (1, 2, 3)}
        client, db = Mock(), Mock()
        drafts = iter((1, 2, 3))
        def parsed(**kwargs):
            event_id = next(drafts)
            analysis = draft_data(numeric=False)
            analysis["event_id"] = event_id
            analysis["editorial_review"] = CHECKS
            analysis["binary_questions"][0]["choice_labels"] = LONG_LABELS
            self.assertIn(ANSWER_LABEL_RULES, kwargs["input"][0]["content"])
            analysis["binary_questions"][0]["question"] = TRUNCATED_EVENT_517 if event_id == 2 else LONG_QUESTION
            return SimpleNamespace(output_parsed=kwargs["text_format"].model_validate({"events": [{
                "event_id": event_id, "evidence_article_ids": [1, 2], "analysis": analysis}]}))
        client.responses.parse.side_effect = parsed
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        with self.assertRaisesRegex(RuntimeError, r"\[2\]"):
            review_independent_briefs(client, db, payloads, NOW)
        self.assertEqual(client.responses.parse.call_count, 3)
        writes = db.table.return_value.upsert.call_args_list
        self.assertEqual([call.args[0]["event_id"] for call in writes], [1, 3])
        self.assertTrue(all(call.args[0]["status"] == "ready" for call in writes))
        self.assertTrue(all(call.args[0]["data_questions"][0]["choice_labels"] == LONG_LABELS for call in writes))

    def test_save_rechecks_mutated_model_before_any_database_access(self):
        analysis = EventAnalysis.model_validate(draft_data(numeric=False))
        analysis.binary_questions[0].question = TRUNCATED_EVENT_517
        db = Mock()
        with self.assertRaisesRegex(ValueError, "incomplete voting question"):
            save_analysis(db, research_bundle(False), analysis)
        self.assertEqual(db.mock_calls, [])

    def test_complete_question_exceeds_old_character_and_word_quotas(self):
        self.assertGreater(len(LONG_QUESTION), 100)
        self.assertGreater(len(LONG_QUESTION.split()), 14)
        self.assertTrue(complete_question_text(LONG_QUESTION))
        self.assertEqual(BinaryQuestion.model_json_schema()["properties"]["question"]["maxLength"],
                         MAX_QUESTION_CHARACTERS)

    def test_resource_guard_rejects_oversized_copy_without_truncation(self):
        payload = draft_data()["binary_questions"][0]
        at_limit = "a" * (MAX_QUESTION_CHARACTERS - 1) + "?"
        question = BinaryQuestion.model_validate({**payload, "question": at_limit})
        self.assertEqual(question.question, at_limit)
        self.assertTrue(complete_question_text(at_limit))
        oversized = "a" + at_limit
        self.assertFalse(complete_question_text(oversized))
        with self.assertRaises(ValidationError):
            BinaryQuestion.model_validate({**payload, "question": oversized})

    def test_incomplete_questions_are_still_rejected(self):
        for text in (None, "", "?", LONG_QUESTION[:-1], "Karar…?", "Karar...?",
                     "Hız mı? Kapsam mı?", "Hangi tercih ağır bas?",
                     "Hangi karar öncelikli ol?", "Hangisini tercih ed?"):
            with self.subTest(text=text):
                self.assertFalse(complete_question_text(text))

    def test_full_question_survives_numeric_and_qualitative_generation_and_storage(self):
        for numeric in (True, False):
            for legacy_storage in (True, False):
                with self.subTest(numeric=numeric, legacy_storage=legacy_storage):
                    research = research_bundle(numeric)
                    draft = draft_data(numeric)
                    draft["binary_questions"][0]["question"] = LONG_QUESTION
                    draft["binary_questions"][0]["choice_labels"] = LONG_LABELS
                    question = BinaryQuestion.model_validate(draft["binary_questions"][0])
                    reviewed = ReviewedQuestions(binary_questions=[question], **CHECKS)
                    client = Mock()
                    def parsed(**kwargs):
                        model = kwargs["text_format"]
                        return SimpleNamespace(output_parsed=reviewed if model is ReviewedQuestions
                                               else model.model_validate(draft))
                    client.responses.parse.side_effect = parsed
                    analysis = analyze_event(client, "test-model", research)
                    self.assertEqual(client.responses.parse.call_count, 2)
                    for call in client.responses.parse.call_args_list:
                        self.assertIn("no character or", call.kwargs["input"][0]["content"])
                        self.assertIn(ANSWER_LABEL_RULES, call.kwargs["input"][0]["content"])
                    self.assertEqual(analysis.binary_questions[0].question, LONG_QUESTION)
                    self.assertEqual(EventAnalysis.model_validate_json(analysis.model_dump_json()), analysis)
                    before_ids = question_ids(analysis.model_dump(mode="json"))
                    db = Mock()
                    table = db.table.return_value
                    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
                    if legacy_storage:
                        table.upsert.return_value.execute.side_effect = [RuntimeError("legacy columns"), Mock()]
                    save_analysis(db, research, analysis)
                    rows = [call.args[0] for call in table.upsert.call_args_list]
                    self.assertEqual(len(rows), 2 if legacy_storage else 1)
                    self.assertEqual(rows[0]["data_questions"][0]["question"], LONG_QUESTION)
                    for row in rows:
                        self.assertEqual(row["status"], "ready")
                        self.assertEqual(row["analysis"]["binary_questions"][0]["question"], LONG_QUESTION)
                        self.assertEqual(row["analysis"]["binary_questions"][0]["choice_labels"], LONG_LABELS)
                        self.assertEqual(question_ids(row["analysis"]), before_ids)
                    table.update.assert_called_once()
                    self.assertTrue(table.update.call_args.args[0]["enough_data"])


if __name__ == "__main__":
    unittest.main()

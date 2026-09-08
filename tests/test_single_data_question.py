import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import generate_event_deep_dives as pipeline
from deep_dive.analyze_event import ReviewedQuestions, review_questions
from deep_dive.models import BinaryQuestion, EventAnalysis, ResearchBundle, NumericSeries, Chart, DataStory
from pipeline_visibility import valid_questions
from popularity import question_ids


QUESTION = {
    "id": "q1", "question": "Bu artış ne gösteriyor?",
    "question_type": "metric", "data_anchor": "2025: %10; 2026: %12.",
    "why_it_matters": "Değişimin kapsamını anlamak için.",
    "choice_labels": {"yes": "Artış hızlandı", "no": "Artış yavaşladı", "unsure": "Veri yetmiyor"},
}


def research():
    return ResearchBundle(
        event_id=1, event_title="Ölçüm sonuçları", problem_supported=False,
        central_problem="", problem_evidence=[], background="Arka plan.",
        event_explanation="Ölçüm yayımlandı.", evidence=[], metric_candidates=[],
        numeric_series=[], open_questions=[],
    )


class SingleQuestionTests(unittest.TestCase):
    def test_generation_schema_has_one_metric_and_no_additional_prompts(self):
        question = BinaryQuestion.model_validate(QUESTION)
        self.assertEqual(ReviewedQuestions(binary_questions=[question], event_specific=True, matches_displayed_evidence=True, evidence_relevant=True, not_factual_recall=True, question_intent="event_implication").binary_questions, [question])
        for questions in ([], [question, question]):
            with self.assertRaises(ValidationError):
                ReviewedQuestions(binary_questions=questions)
        for kind in ("reaction", "priority"):
            with self.assertRaises(ValidationError):
                BinaryQuestion.model_validate({**QUESTION, "question_type": kind})
        with self.assertRaises(ValidationError):
            BinaryQuestion.model_validate({**QUESTION, "data_anchor": ""})
        fields = EventAnalysis.model_fields
        self.assertNotIn("normative_question", fields)
        self.assertNotIn("cross_group_question", fields)

    def test_review_accepts_one_data_question_and_rejects_empty_or_duplicate_answers(self):
        question = BinaryQuestion.model_validate(QUESTION)
        client = Mock()
        reviewed = ReviewedQuestions(binary_questions=[question], event_specific=True, matches_displayed_evidence=True, evidence_relevant=True, not_factual_recall=True, question_intent="event_implication")
        client.responses.parse.return_value = SimpleNamespace(output_parsed=reviewed)
        self.assertEqual(review_questions(client, "test-model", research(), [question]), [question])
        with self.assertRaises(ValidationError):
            review_questions(client, "test-model", research(), [question, question])
        for changes in (
            {"data_anchor": "   "},
            {"choice_labels": {"yes": "Aynı", "no": " aynı ", "unsure": "Veri yetmiyor"}},
        ):
            bad = BinaryQuestion.model_validate({**QUESTION, **changes})
            client.responses.parse.return_value = SimpleNamespace(
                output_parsed=ReviewedQuestions(binary_questions=[bad], event_specific=True, matches_displayed_evidence=True, evidence_relevant=True, not_factual_recall=True, question_intent="event_implication"))
            with self.assertRaises(ValueError):
                review_questions(client, "test-model", research(), [question])

    def test_review_is_bound_to_first_display_and_rejects_generic_or_unrelated_question(self):
        question = BinaryQuestion.model_validate(QUESTION)
        client = Mock()
        chart = {"chart_type": "metric", "title": "Proje kapasitesi", "unit": "kişi", "points": [{"label": "Kapasite", "value": 120}]}
        client.responses.parse.return_value = SimpleNamespace(output_parsed=ReviewedQuestions(
            binary_questions=[question], event_specific=True, matches_displayed_evidence=True, evidence_relevant=True, not_factual_recall=True, question_intent="event_implication"))
        review_questions(client, "test-model", research(), [question], [chart])
        prompt = client.responses.parse.call_args.kwargs["input"]
        import json
        self.assertEqual(json.loads(prompt[-1]["content"])["first_chart"], [chart])
        for flags in ({"event_specific": False}, {"matches_displayed_evidence": False},
                      {"evidence_relevant": False}, {"not_factual_recall": False}):
            client.responses.parse.return_value = SimpleNamespace(output_parsed=ReviewedQuestions(binary_questions=[question], **({"event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True} | flags)))
            with self.assertRaises(ValueError):
                review_questions(client, "test-model", research(), [question], [chart])

    def test_one_point_schema_keeps_observation_flags_and_rejects_coercion(self):
        from numeric_data_quality import valid_numeric_data
        data = {"name": "Proje kapasitesi", "unit": "kişi", "comparison_axis": "Proje", "ordered": False,
                "part_of_whole": False, "source_name": "Kurum", "source_url": "https://example.org/project",
                "methodology_note": "Açıklanan kapasite.", "points": [{"label": "Kapasite", "value": 120, "group": ""}]}
        self.assertTrue(valid_numeric_data([NumericSeries.model_validate(data).model_dump()]))
        forecast = copy.deepcopy(data)
        forecast["points"][0]["is_forecast"] = True
        self.assertFalse(valid_numeric_data([NumericSeries.model_validate(forecast).model_dump()]))
        for value in (True, "120", float("nan")):
            bad = copy.deepcopy(data)
            bad["points"][0]["value"] = value
            with self.assertRaises(ValidationError):
                NumericSeries.model_validate(bad)
        Chart.model_validate({"chart_type": "metric", "title": "Kapasite", "unit": "kişi", "x_label": "Proje", "y_label": "Kişi",
                              "points": data["points"], "insight": "Kapasite tek başına talebi göstermez.", "source_urls": [data["source_url"]]})

    def test_gate_accepts_single_and_legacy_metric_without_reindexing(self):
        legacy = {"binary_questions": [
            {"question": "Ne hissettin?", "question_type": "reaction"},
            {"question": "Önce hangi adım?", "question_type": "priority"},
            {**QUESTION, "id": "q3"},
        ]}
        before = copy.deepcopy(legacy)
        ids = question_ids(legacy)
        self.assertTrue(valid_questions(legacy))
        self.assertEqual(legacy, before)
        self.assertEqual(question_ids(legacy), ids)
        self.assertTrue(any(qid.endswith("_2") for qid in ids))
        self.assertTrue(valid_questions({"binary_questions": [QUESTION]}))
        for value in (None, [], {"binary_questions": [QUESTION, QUESTION]},
                      {"binary_questions": [{**QUESTION, "data_anchor": " "}]},
                      {"binary_questions": [{**QUESTION, "question_type": "reaction"}]},
                      {"binary_questions": [QUESTION, QUESTION, QUESTION]}):
            self.assertFalse(valid_questions(value))

    def test_normal_pipeline_preserves_ready_legacy_and_single_ballots(self):
        now = datetime.now(timezone.utc)
        points = [{"label": str(now.year - 1), "value": 10},
                  {"label": str(now.year), "value": 12}]
        numeric = [{"ordered": True, "source_url": "https://example.org/data", "points": points}]
        chart = {"chart_type": "line", "source_urls": ["https://example.org/data"], "points": points}
        for revision, questions in (
            (2, [{"question": "Ne hissettin?", "question_type": "reaction"},
                 {"question": "Önce hangi adım?", "question_type": "priority"},
                 {**QUESTION, "id": "q3"}]),
            (3, [QUESTION]),
        ):
            with self.subTest(revision=revision):
                event = {"id": 1, "created_at": now.isoformat(), "enough_data": True,
                         "is_visible": True, "numeric_data": numeric, "source_count": 2,
                         "popularity_score": 100, "popularity_updated_at": now.isoformat()}
                analysis = {"schema_version": 2, "question_revision": revision,
                            "binary_questions": copy.deepcopy(questions), "charts": [chart], "editorial_review": {"revision": 2, "question_intent": "event_implication", "event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True}}
                rows = [{"event_id": 1, "status": "ready", "analysis": analysis}]
                original = copy.deepcopy(rows)
                db = Mock()

                def table(name):
                    query = Mock()
                    for method in ("select", "gte", "lte", "order", "in_", "limit"):
                        getattr(query, method).return_value = query
                    query.execute.return_value = SimpleNamespace(
                        data=[event] if name == "events" else rows if name == "event_analyses" else [])
                    return query

                db.table.side_effect = table
                with patch.dict(os.environ, {"SUPABASE_URL": "https://example.invalid",
                                             "SUPABASE_KEY": "test", "OPENAI_API_KEY": "test"}), \
                     patch.object(sys, "argv", ["generate_event_deep_dives.py"]), \
                     patch.object(pipeline, "create_client", return_value=db), \
                     patch.object(pipeline, "OpenAI"), \
                     patch.object(pipeline, "refresh_cover_questions"), \
                     patch.object(pipeline, "refresh_event_covers"), \
                     patch.object(pipeline, "publish_ready_events"), \
                     patch.object(pipeline, "research_event") as do_research, \
                     patch.object(pipeline, "analyze_event") as analyze, \
                     patch.object(pipeline, "review_questions") as review, \
                     patch.object(pipeline, "save_analysis") as save:
                    pipeline.main()
                    for call in (do_research, analyze, review, save):
                        call.assert_not_called()
                self.assertEqual(rows, original)
                # A formerly ready file must be re-researched after a policy upgrade.
                analysis["editorial_review"] = None
                with patch.dict(os.environ, {"SUPABASE_URL": "https://example.invalid", "SUPABASE_KEY": "test", "OPENAI_API_KEY": "test"}), \
                     patch.object(sys, "argv", ["generate_event_deep_dives.py"]), \
                     patch.object(pipeline, "create_client", return_value=db), \
                     patch.object(pipeline, "OpenAI"), \
                     patch.object(pipeline, "refresh_cover_questions"), \
                     patch.object(pipeline, "refresh_event_covers"), \
                     patch.object(pipeline, "publish_ready_events"), \
                     patch.object(pipeline, "load_event", return_value={"event": event, "articles": []}), \
                     patch.object(pipeline, "research_event", side_effect=RuntimeError("stop before network")) as fresh:
                    with self.assertRaisesRegex(RuntimeError, "1 deep dives failed"):
                        pipeline.main()
                    fresh.assert_called_once()



if __name__ == "__main__":
    unittest.main()

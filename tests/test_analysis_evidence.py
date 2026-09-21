import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from deep_dive.analysis_evidence import analysis_output_model, materialize_analysis
from deep_dive.analyze_event import analyze_event
from deep_dive.models import ResearchBundle
from numeric_data_quality import valid_analysis_timeline


NOW = datetime.now(timezone.utc)
YEAR = NOW.year
SOURCE_A = "https://example.org/evidence?version=1&scope=local"
SOURCE_B = "https://other.example.net/report"


def research_bundle(numeric=True):
    series = {
        "name": "Yerel ölçüm", "unit": "bin kişi", "comparison_axis": "Yıl",
        "ordered": True, "part_of_whole": False,
        "points": [
            {"label": str(YEAR - 2), "value": 1.125, "group": "Yerel"},
            {"label": str(YEAR - 1), "value": 0.0, "group": "Yerel"},
            {"label": str(YEAR), "value": 3.875, "group": "Yerel"},
        ],
        "source_name": "Yerel kurum", "source_url": SOURCE_A,
        "methodology_note": "Aynı kapsam ve ölçüm yöntemi.",
    }
    other_scope = {
        **series, "name": "Ulusal ölçüm",
        "points": [
            {"label": str(YEAR - 1), "value": 200.0, "group": "Ulusal"},
            {"label": str(YEAR), "value": 300.0, "group": "Ulusal"},
        ],
    }
    return ResearchBundle.model_validate({
        "event_id": 213, "event_title": "Yeni ölçüm yayımlandı",
        "problem_supported": False, "central_problem": "", "problem_evidence": [],
        "background": "Ölçüm yöntemi önceki dönemde belirlendi.",
        "event_explanation": "Kurum yeni ölçüm sonuçlarını yayımladı.",
        "evidence": [
            {"title": "Ölçüm raporu", "finding": "Yeni sonuçlar yayımlandı.",
             "publisher": "Yerel kurum", "url": SOURCE_A,
             "published_at": NOW.isoformat(), "evidence_type": "official"},
            {"title": "Yöntem raporu", "finding": "Yöntem önceki dönemle aynı.",
             "publisher": "Diğer kurum", "url": SOURCE_B,
             "published_at": NOW.isoformat(), "evidence_type": "research"},
        ],
        "metric_candidates": [], "numeric_series": [series, other_scope] if numeric else [],
        "open_questions": [],
    })


def draft_data(numeric=True):
    return {
        "evidence_mode": "numeric" if numeric else "qualitative",
        "editorial_review": None, "schema_version": 2, "question_revision": 3,
        "event_id": 213, "title": "Yeni ölçüm yayımlandı", "generated_at": NOW.isoformat(),
        "background": {"title": "Arka plan", "narration": "Önceki yöntem korundu.",
                       "source_urls": [SOURCE_B]},
        "event_explanation": {"title": "Ne oldu?", "narration": "Yeni rapor yayımlandı.",
                              "source_urls": [SOURCE_A]},
        "data_story": {"headline": "Yeni sonuçlar", "baseline": "Önceki dönem.",
                       "key_metrics": [], "hidden_patterns": [],
                       "what_to_watch_next": ["Bir sonraki rapor."],
                       "limitations": ["Sonuçlar tek başına nedenleri açıklamaz."]},
        "charts": [{"source_series": "series_0", "point_indices": [1, 2],
                    "chart_type": "line", "title": "Yerel ölçüm",
                    "x_label": "Takvim dönemi", "y_label": "Kişi",
                    "insight": "Değişim tek başına neden göstermez."}] if numeric else [],
        "binary_questions": [{"id": "q1", "question": "Yerel hizmetlerde hız mı, kapsam mı öncelikli olmalı?",
                              "data_anchor": "Yeni rapor tek başına nedenleri açıklamaz.",
                              "why_it_matters": "Kaynakların dağılımını etkiler.",
                              "question_type": "metric" if numeric else "event",
                              "choice_labels": {"yes": "Hız", "no": "Kapsam", "unsure": "Koşula bağlı"}}],
    }


class AnalysisEvidenceTests(unittest.TestCase):
    def test_section_sources_accept_exact_evidence_and_reject_invented_or_empty_sources(self):
        research = research_bundle()
        output_model = analysis_output_model(research)
        output_model.model_validate(draft_data())
        for sources in ([], ["https://invented.example/report"],
                        [SOURCE_A.replace("scope=local", "scope=global")], [""]):
            with self.subTest(sources=sources):
                data = draft_data()
                data["event_explanation"]["source_urls"] = sources
                with self.assertRaises(ValueError):
                    output_model.model_validate(data)

    def test_hydration_keeps_exact_source_points_units_urls_and_time_order(self):
        research = research_bundle()
        before = research.model_dump(mode="json")
        data = draft_data()
        data["charts"][0]["point_indices"] = [2, 1]
        result = materialize_analysis(analysis_output_model(research).model_validate(data), research)
        chart = result.charts[0]
        source = research.numeric_series[0]
        self.assertEqual(chart.points, [source.points[1], source.points[2]])
        self.assertEqual(chart.unit, source.unit)
        self.assertEqual(chart.source_urls, [source.source_url])
        self.assertEqual(chart.x_label, source.comparison_axis)
        self.assertEqual(research.model_dump(mode="json"), before)
        self.assertTrue(valid_analysis_timeline(result.model_dump(mode="json"), before["numeric_series"], NOW))

    def test_selection_is_bound_to_one_scope_even_when_source_url_and_unit_match(self):
        research = research_bundle()
        data = draft_data()
        data["charts"][0].update(source_series="series_1", point_indices=[0, 1])
        result = materialize_analysis(analysis_output_model(research).model_validate(data), research)
        self.assertEqual(result.charts[0].points, research.numeric_series[1].points)
        self.assertEqual([point.value for point in result.charts[0].points], [200.0, 300.0])

    def test_bad_series_and_point_selections_cannot_be_materialized(self):
        research = research_bundle()
        output_model = analysis_output_model(research)
        for patch in ({"source_series": "series_99"}, {"point_indices": []},
                      {"point_indices": [-1, 1]}, {"point_indices": [1, 3]},
                      {"point_indices": [1, 1]}, {"point_indices": [True, 2]},
                      {"point_indices": [1.5, 2]}, {"point_indices": ["1", 2]}):
            with self.subTest(patch=patch):
                data = draft_data()
                data["charts"][0].update(patch)
                with self.assertRaises(ValueError):
                    materialize_analysis(output_model.model_validate(data), research)

    def test_hydration_defends_against_invalid_indices_after_schema_validation(self):
        research = research_bundle()
        valid_draft = analysis_output_model(research).model_validate(draft_data())
        for indices in ([True, 2], [-1, 1], [1, 3], [1, 1]):
            with self.subTest(indices=indices):
                draft = valid_draft.model_copy(deep=True)
                draft.charts[0].point_indices = indices
                with self.assertRaises(ValueError):
                    materialize_analysis(draft, research)

    def test_sourced_timeline_subset_still_requires_prior_year_baseline(self):
        research = research_bundle()
        data = draft_data()
        data["charts"][0]["point_indices"] = [0, 2]
        with self.assertRaisesRegex(ValueError, rf"{YEAR - 1}.*baseline"):
            materialize_analysis(analysis_output_model(research).model_validate(data), research)

    def test_one_dated_metric_remains_valid_without_forcing_a_timeline(self):
        research = research_bundle()
        data = draft_data()
        data["charts"][0].update(chart_type="metric", point_indices=[2])
        result = materialize_analysis(analysis_output_model(research).model_validate(data), research)
        self.assertEqual(result.charts[0].points, [research.numeric_series[0].points[2]])
        self.assertTrue(valid_analysis_timeline(result.model_dump(mode="json"),
                                              research.model_dump(mode="json")["numeric_series"], NOW))

    def test_qualitative_story_requires_no_chart_and_preserves_sourced_sections(self):
        research = research_bundle(numeric=False)
        data = draft_data(numeric=False)
        result = materialize_analysis(analysis_output_model(research).model_validate(data), research)
        self.assertEqual(result.evidence_mode, "qualitative")
        self.assertEqual(result.charts, [])
        self.assertEqual(result.data_story.key_metrics, [])
        self.assertEqual(result.background.source_urls, [SOURCE_B])
        self.assertEqual(result.event_explanation.source_urls, [SOURCE_A])
        self.assertTrue(valid_analysis_timeline(result.model_dump(mode="json"), [], NOW))

    def test_analysis_retries_missing_baseline_and_reviews_only_materialized_source_values(self):
        research = research_bundle()
        rejected = draft_data()
        rejected["charts"][0]["point_indices"] = [0, 2]
        drafts = iter([rejected, draft_data()])
        client = Mock()
        client.responses.parse.side_effect = lambda **kwargs: SimpleNamespace(
            output_parsed=kwargs["text_format"].model_validate(next(drafts)))
        with patch("deep_dive.analyze_event.review_questions", side_effect=lambda *args, **kwargs: args[3]) as review:
            result = analyze_event(client, "test-model", research)
        self.assertEqual(client.responses.parse.call_count, 2)
        review.assert_called_once()
        reviewed_charts = review.call_args.args[4]
        self.assertEqual(reviewed_charts, result.charts)
        self.assertEqual(reviewed_charts[0].points, research.numeric_series[0].points[1:])
        self.assertEqual(reviewed_charts[0].source_urls, [SOURCE_A])
        self.assertEqual(reviewed_charts[0].unit, "bin kişi")
        retry_messages = client.responses.parse.call_args_list[1].kwargs["input"]
        self.assertIn(f"{YEAR - 1} baseline", retry_messages[0]["content"])
        self.assertIn("point_indices [1]", retry_messages[0]["content"])
        repair_message = next(message["content"] for message in retry_messages
                              if message["content"].startswith("Rejected draft for repair"))
        self.assertEqual(json.loads(repair_message.split(": ", 1)[1])["charts"][0]["point_indices"], [0, 2])

    def test_structurally_sourced_analysis_still_fails_when_editorial_review_rejects_both_drafts(self):
        research = research_bundle()
        client = Mock()
        client.responses.parse.side_effect = lambda **kwargs: SimpleNamespace(
            output_parsed=kwargs["text_format"].model_validate(draft_data()))
        with patch("deep_dive.analyze_event.review_questions",
                   side_effect=ValueError("Editorial review rejected unrelated evidence")) as review:
            with self.assertRaisesRegex(ValueError, "Editorial review rejected"):
                analyze_event(client, "test-model", research)
        self.assertEqual(client.responses.parse.call_count, 2)
        self.assertEqual(review.call_count, 2)


if __name__ == "__main__":
    unittest.main()

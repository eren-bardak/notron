import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from numeric_data_quality import point_year, valid_analysis_timeline, valid_numeric_data
from pipeline_visibility import enforce_previous_year_gate, ready_event_ids

NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def series(labels=("2024", "2025")):
    return {"ordered": True, "source_url": "https://example.org/data",
            "points": [{"label": label, "value": i, "group": ""} for i, label in enumerate(labels)]}


def analysis(data):
    return {"editorial_review": {"revision": 1, "event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True}, "binary_questions": [{"question": "A?"}, {"question": "B?"}, {"question": "C?", "question_type": "metric", "data_anchor": "2025: 1"}],
            "charts": [{"chart_type": "line", "source_urls": [data["source_url"]],
                        "points": copy.deepcopy(data["points"])}]}


class NumericDataQualityTests(unittest.TestCase):
    def test_calendar_labels_are_exact_not_incidental_year_mentions(self):
        for label in ("2025", "2025-03", "2025-03-18", "2025-03-18T12:30:00Z", "Q1 2025", "2025 Q4", "Ocak 2025", "2025 September", "2025 2. çeyrek"):
            with self.subTest(label=label):
                self.assertEqual(point_year(label), 2025)
        for label in (None, 2025, "published 2025", "2024–2025", "2025 forecast", "2025 (tahmin)", "2025-13", "2025-02-29", "Q5 2025", "https://example.org/2025"):
            with self.subTest(label=label):
                self.assertIsNone(point_year(label))

    def test_baseline_changes_at_calendar_year_rollover_and_zero_counts(self):
        data = series(("2025", "2026"))  # 2025's observed value is zero.
        self.assertTrue(valid_numeric_data([data], NOW))
        self.assertTrue(valid_numeric_data([data], datetime(2027, 1, 1, tzinfo=timezone.utc)))
        self.assertFalse(valid_numeric_data([data], datetime(2028, 1, 1, tzinfo=timezone.utc)))
        stale = series(("2023", "2024"))
        stale["source_url"] = "https://example.org/2025"
        stale["methodology_note"] = "Published in 2025"
        self.assertFalse(valid_numeric_data([stale], NOW))

    def test_every_time_series_needs_usable_observed_previous_year_data(self):
        good = series()
        self.assertTrue(valid_numeric_data([good], NOW))
        self.assertFalse(valid_numeric_data([good, series(("2022", "2023"))], NOW))
        self.assertFalse(valid_numeric_data([{**good, "source_url": "https://"}], NOW))
        for value in (None, True, "1", float("inf"), float("nan"), 10 ** 400):
            bad = series()
            bad["points"][1]["value"] = value
            self.assertFalse(valid_numeric_data([bad], NOW))
        for marker in ({"is_projection": True}, {"is_forecast": True}, {"observation_type": "forecast"}):
            bad = series()
            bad["points"][1].update(marker)
            self.assertFalse(valid_numeric_data([bad], NOW))
        malformed = series()
        malformed["points"][1]["group"] = []
        self.assertFalse(valid_numeric_data([malformed], NOW))

    def test_categories_need_no_timeline_but_malformed_evidence_is_rejected(self):
        for value in (None, {}, "2025", [None], [{"points": {}}], [series(("A", "B"))]):
            self.assertFalse(valid_numeric_data(value, NOW))
        inferred = series()
        inferred["ordered"] = False
        self.assertTrue(valid_numeric_data([inferred], NOW))
        category = {"source_url": "https://example.org/categories", "ordered": False,
                    "points": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}
        self.assertTrue(valid_numeric_data([category], NOW))
        self.assertTrue(valid_numeric_data([series(), category], NOW))

    def test_displayed_chart_must_retain_the_exact_sourced_baseline(self):
        data = series()
        display = analysis(data)
        self.assertTrue(valid_analysis_timeline(display, [data], NOW))
        self.assertFalse(valid_analysis_timeline({"charts": []}, [data], NOW))
        for changes in ({"label": "2026"}, {"value": 50}, {"is_projection": True}, {"group": "invented"}):
            invalid = copy.deepcopy(display)
            invalid["charts"][0]["points"][1].update(changes)
            self.assertFalse(valid_analysis_timeline(invalid, [data], NOW))
        wrong_source = copy.deepcopy(display)
        wrong_source["charts"][0]["source_urls"] = ["https://different.org/data"]
        self.assertFalse(valid_analysis_timeline(wrong_source, [data], NOW))
        additional_bad_chart = copy.deepcopy(display)
        additional_bad_chart["charts"].append({**display["charts"][0], "points": series(("2022", "2023"))["points"]})
        self.assertFalse(valid_analysis_timeline(additional_bad_chart, [data], NOW))

    def test_single_values_and_categories_match_all_source_values_and_units(self):
        for points in ([{"label": "Proje kapasitesi", "value": 0}],
                       [{"label": "A", "value": 35}, {"label": "B", "value": 65}]):
            data = {"unit": "%", "ordered": False, "source_url": "https://example.org/current", "points": points}
            chart = {"chart_type": "metric" if len(points) == 1 else "bars", "unit": "%",
                     "source_urls": [data["source_url"]], "points": points}
            self.assertTrue(valid_numeric_data([data], NOW))
            self.assertTrue(valid_analysis_timeline({"charts": [chart]}, [data], NOW))
            for patch in ({"value": 999}, {"group": "invented"}, {"is_forecast": True}, {"value": None}):
                bad = copy.deepcopy(chart)
                bad["points"][0].update(patch)
                self.assertFalse(valid_analysis_timeline({"charts": [bad]}, [data], NOW))
            self.assertFalse(valid_analysis_timeline({"charts": [{**chart, "unit": "adet"}]}, [data], NOW))
            self.assertFalse(valid_numeric_data([{**data, "points": [{**points[0], "is_forecast": True}]}], NOW))
        data = series()
        display = analysis(data)
        display["charts"][0]["points"][0]["value"] = 999  # Even non-baseline points must match.
        self.assertFalse(valid_analysis_timeline(display, [data], NOW))

    def test_single_dated_value_is_not_a_trend_and_unrelated_scopes_cannot_mix(self):
        point = {"label": "2026", "value": 0.00042}
        data = {"ordered": False, "comparison_axis": "Yıl", "source_url": "https://example.org/data", "points": [point]}
        chart = {"chart_type": "metric", "x_label": "Yıl", "source_urls": [data["source_url"]], "points": [point]}
        self.assertTrue(valid_analysis_timeline({"charts": [chart]}, [data], NOW))
        first = {**data, "comparison_axis": "Şehir", "points": [{"label": "A", "value": 10}, {"label": "B", "value": 20}]}
        second = {**first, "points": [{"label": "A", "value": 20}, {"label": "B", "value": 30}]}
        mixed = {**chart, "chart_type": "bars", "x_label": "Şehir", "points": [first["points"][0], second["points"][1]]}
        self.assertFalse(valid_analysis_timeline({"charts": [mixed]}, [first, second], NOW))

    def test_cached_ready_event_is_demoted_before_research_and_cannot_publish(self):
        class DB:
            def __init__(self): self.writes = []
            def table(self, name): self.name = name; return self
            def update(self, values): self.values = values; return self
            def eq(self, key, value): self.filter = (key, value); return self
            def execute(self):
                self.writes.append((self.name, self.values, self.filter))
                return SimpleNamespace(data=[])
        db = DB()
        data = series(("2023", "2024"))
        events = [{"id": 1, "created_at": NOW.isoformat(), "enough_data": True, "is_visible": True,
                   "numeric_data": [data], "source_count": 3, "popularity_score": 100,
                   "popularity_updated_at": NOW.isoformat()}]
        saved = [{"event_id": 1, "status": "ready", "analysis": analysis(data)}]
        self.assertEqual(enforce_previous_year_gate(db, events, saved, NOW), [1])
        self.assertEqual(db.writes[0], ("events", {"enough_data": False, "is_visible": False}, ("id", 1)))
        self.assertEqual(db.writes[1], ("event_analyses", {"status": "insufficient_data"}, ("event_id", 1)))
        self.assertEqual(ready_event_ids(events, saved, NOW), [])
        self.assertEqual(enforce_previous_year_gate(db, events, saved, NOW), [1])
        self.assertEqual(len(db.writes), 2)  # Repeat validation does not rewrite unchanged flags.


if __name__ == "__main__":
    unittest.main()

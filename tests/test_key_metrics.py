import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from deep_dive.key_metrics import grounded_key_metrics, with_key_metrics
from deep_dive.models import DataStory


def metric(label="Hizmet verilen hane", value=2400):
    return dict(label=label, value=value, unit="hane", time_scope="Eylül 2026",
                geography="Örnek ilçe", why_it_matters="Haberde açıklanan hizmetin kapsamını gösterir.",
                source_name="Örnek rapor", source_url="https://example.org/report", trend="unknown")


def research(metrics):
    return dict(metric_candidates=metrics, evidence=[{"url": "https://example.org/report"}], numeric_series=[])


class KeyMetricTests(unittest.TestCase):
    def test_optional_without_filler(self):
        for selected in (None, [], "invalid"):
            self.assertEqual(grounded_key_metrics(selected, research([metric()])), [])

    def test_changed_fact_or_provenance_is_omitted(self):
        original = metric()
        for key, value in (("value", 999), ("time_scope", "2024"), ("geography", "Başka ilçe"),
                           ("unit", "%"), ("source_url", "https://example.org/other"),
                           ("comparison_value", 22), ("why_it_matters", "Desteklenmeyen yorum")):
            self.assertEqual(grounded_key_metrics([{**original, key: value}], research([original])), [])

    def test_invalid_values_never_leak(self):
        for key, value in (("value", True), ("value", "2"), ("value", float("nan")),
                           ("value", float("inf")), ("delta_percent", float("inf")),
                           ("comparison_value", True), ("source_url", "javascript:alert(1)"),
                           ("time_scope", " ")):
            item = {**metric(), key: value}
            self.assertEqual(grounded_key_metrics([item], research([item])), [])
        for value in (0, -12, 0.004):
            item = metric(value=value)
            self.assertEqual(grounded_key_metrics([item], research([item]))[0]["value"], value)
        self.assertEqual(grounded_key_metrics([metric()], {"metric_candidates": None}), [])
        self.assertEqual(grounded_key_metrics([metric()], {"metric_candidates": [metric()], "evidence": None}), [])

    def test_distinct_selection_and_limit(self):
        items = [metric(label=f"Ölçüm {i}", value=i) for i in range(5)]
        selected = [items[0], items[0], *items[1:]]
        kept = grounded_key_metrics(selected, research(items))
        self.assertEqual([item["value"] for item in kept], [0, 1, 2])

    def test_legacy_cache_is_compatible_and_ballots_unchanged(self):
        items = [metric(label=f"Ölçüm {i}") for i in range(6)]
        old = dict(data_story=dict(headline="Başlık", baseline="Dönem", key_metrics=items,
                                  hidden_patterns=[], what_to_watch_next=["Gelişmeler"], limitations=["Kapsam"]),
                   binary_questions=[{"id": "q1", "question": "Korunmalı mı?"}], charts=[{"points": [1]}],
                   editorial_review={"revision": 2}, image_selection={"url": "image"}, cover_question="Kapak")
        snapshot = copy.deepcopy(old)
        updated = with_key_metrics(old, research(items))
        self.assertEqual(len(DataStory.model_validate(updated["data_story"]).key_metrics), 3)
        self.assertEqual(old, snapshot)
        for key in ("binary_questions", "charts", "editorial_review", "image_selection", "cover_question"):
            self.assertEqual(updated[key], old[key])
        updated = with_key_metrics(old, research([]))
        self.assertEqual(DataStory.model_validate(updated["data_story"]).key_metrics, [])


if __name__ == "__main__":
    unittest.main()

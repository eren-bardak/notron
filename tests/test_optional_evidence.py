import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import unittest
from datetime import datetime, timezone
from numeric_data_quality import valid_analysis_timeline, valid_numeric_data, has_event_evidence
from pipeline_visibility import ready_event_ids


class OptionalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 15, 16, tzinfo=timezone.utc)
        self.analysis = {
            "evidence_mode": "qualitative", "charts": [], "data_story": {"key_metrics": []},
            "background": {"narration": "Kararın önceki aşamaları kaynaklarda açıklanıyor.", "source_urls": ["https://source-one.example/news/1"]},
            "event_explanation": {"narration": "Yeni karar açıklandı; etkileri henüz kesinleşmedi.", "source_urls": ["https://source-two.example/news/2"]},
            "binary_questions": [{"question_type": "event", "question": "Bu kararda hız mı, daha geniş uzlaşma mı öncelikli olmalı?", "data_anchor": "Karar açıklandı; uygulama süreci henüz belli değil."}],
            "editorial_review": {"revision": 2, "event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True, "question_intent": "event_implication"},
        }

    def test_sourced_story_can_publish_without_measurements(self):
        self.assertFalse(valid_numeric_data([]))
        self.assertTrue(valid_analysis_timeline(self.analysis, [], self.now))
        event = {"id": 1, "created_at": self.now.isoformat(), "source_count": 2, "enough_data": True, "numeric_data": [], "popularity_score": 10, "popularity_updated_at": self.now.isoformat()}
        rows = [{"event_id": 1, "status": "ready", "analysis": self.analysis}]
        self.assertEqual(ready_event_ids([event], rows, self.now), [1])
        event["source_count"] = 1
        self.assertEqual(ready_event_ids([event], rows, self.now), [])

    def test_missing_sources_or_question_cannot_pass(self):
        for field in ("background", "event_explanation"):
            invalid = copy.deepcopy(self.analysis)
            invalid[field]["source_urls"] = []
            self.assertFalse(valid_analysis_timeline(invalid, [], self.now))
        invalid = copy.deepcopy(self.analysis)
        invalid["event_explanation"]["source_urls"] = invalid["background"]["source_urls"]
        self.assertFalse(valid_analysis_timeline(invalid, [], self.now))
        invalid["binary_questions"] = []
        self.assertFalse(valid_analysis_timeline(invalid, [], self.now))

    def test_qualitative_mode_cannot_bypass_bad_numeric_values(self):
        invalid = copy.deepcopy(self.analysis)
        invalid["charts"] = [{"points": [{"label": "X", "value": 500}]}]
        self.assertFalse(valid_analysis_timeline(invalid, [], self.now))
        invalid = copy.deepcopy(self.analysis)
        invalid["data_story"]["key_metrics"] = [{"value": 500}]
        self.assertFalse(valid_analysis_timeline(invalid, [], self.now))
        self.assertFalse(valid_analysis_timeline(self.analysis, [{"points": []}], self.now))
        self.assertFalse(valid_analysis_timeline({}, [], self.now))

    def test_cached_research_requires_two_source_domains(self):
        research = {"background": "Context", "event_explanation": "Development", "evidence": [{"url": "https://a.example/1", "finding": "Fact"}, {"url": "https://b.example/2", "finding": "Attributed fact"}]}
        self.assertTrue(has_event_evidence(research))
        research["evidence"][1]["url"] = "https://www.a.example/2"
        self.assertFalse(has_event_evidence(research))

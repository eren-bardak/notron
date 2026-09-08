import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pipeline_visibility import ready_event_ids


class PublicationTests(unittest.TestCase):
    def test_ranked_candidates_wait_for_complete_research(self):
        now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
        def event(i, **changes):
            return {"id": i, "created_at": now.isoformat(), "enough_data": True,
                    "problem_supported": True, "numeric_data": [{"ordered": True, "source_url":"https://example.org/data", "points": [{"label":"2024", "value":1}, {"label":"2025", "value":2}]}],
                    "source_count": 2, "popularity_score": 100-i, "popularity_updated_at": now.isoformat(), **changes}
        events = [event(1), event(2, numeric_data=[]), event(3), event(4),
                  event(5, created_at=(now-timedelta(hours=37)).isoformat()),
                  event(6, created_at=(now+timedelta(minutes=1)).isoformat()),
                  event(7, source_count=1), event(8, problem_supported=False),
                  event(9), event(10, created_at=(now-timedelta(hours=36)).isoformat()),
                  event(11, created_at=None)]
        analyses = [{"event_id": i, "status": "ready", "analysis": {"editorial_review": {"revision": 1, "event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True}, "binary_questions": [{"question":"A?"},{"question":"B?"},{"question":"C?", "question_type":"metric", "data_anchor":"2025: 2"}],
                     "charts": [{"chart_type":"line", "source_urls":["https://example.org/data"], "points":[{"label":"2024", "value":1}, {"label":"2025", "value":2}]}]}}
                    for i in [1,2,3,5,6,7,8,9,10]]
        analyses[2]["analysis"]["binary_questions"] = [1,2]
        self.assertEqual(ready_event_ids(events, analyses, now), [1,8,9,10])
        self.assertEqual(ready_event_ids(events, analyses, now, limit=2), [1,8])

    def test_event_with_sourced_comparison_can_publish_without_time_series(self):
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        points = [{"label": "Proje kapasitesi", "value": 120}, {"label": "Başvuru", "value": 400}]
        data = {"ordered": False, "source_url": "https://example.org/project", "unit": "kişi", "points": points}
        event = {"id": 20, "created_at": now.isoformat(), "enough_data": True, "source_count": 2,
                 "numeric_data": [data], "popularity_score": 100, "popularity_updated_at": now.isoformat()}
        analysis = {"editorial_review": {"revision": 1, "event_specific": True, "matches_displayed_evidence": True, "evidence_relevant": True, "not_factual_recall": True}, "binary_questions": [{"question": "Bu projenin kapasitesi başvuruyu karşılıyor mu?", "question_type": "metric", "data_anchor": "120 kişilik kapasite; 400 başvuru."}],
                    "charts": [{"chart_type": "bars", "unit": "kişi", "source_urls": [data["source_url"]], "points": points}]}
        self.assertEqual(ready_event_ids([event], [{"event_id": 20, "status": "ready", "analysis": analysis}], now), [20])


if __name__ == "__main__":
    unittest.main()

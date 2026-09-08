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
                    "problem_supported": True, "numeric_data": [{"source_url":"https://example.org/data", "points": [{"value":1}, {"value":2}]}],
                    "source_count": 2, "popularity_score": 100-i, "popularity_updated_at": now.isoformat(), **changes}
        events = [event(1), event(2, numeric_data=[]), event(3), event(4),
                  event(5, created_at=(now-timedelta(hours=37)).isoformat()),
                  event(6, created_at=(now+timedelta(minutes=1)).isoformat()),
                  event(7, source_count=1), event(8, problem_supported=False),
                  event(9), event(10, created_at=(now-timedelta(hours=36)).isoformat()),
                  event(11, created_at=None)]
        analyses = [{"event_id": i, "status": "ready", "analysis": {"binary_questions": [{"question":"A?"},{"question":"B?"},{"question":"C?"}]}}
                    for i in [1,2,3,5,6,7,8,9,10]]
        analyses[2]["analysis"]["binary_questions"] = [1,2]
        self.assertEqual(ready_event_ids(events, analyses, now), [1,8,9,10])
        self.assertEqual(ready_event_ids(events, analyses, now, limit=2), [1,8])


if __name__ == "__main__":
    unittest.main()

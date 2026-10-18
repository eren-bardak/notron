import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from popularity import display_threshold, event_thresholds


class AdaptiveFeedTests(unittest.TestCase):
    def test_threshold_tracks_inventory_and_score_distribution(self):
        self.assertLess(display_threshold([4, 1]), 1)
        self.assertEqual(display_threshold([]), .25)
        self.assertEqual(display_threshold([float('nan'), float('inf'), -1, 0]), .25)
        self.assertEqual(display_threshold([20] * 36), 5)
        scores = [4 - i / 10 for i in range(24)]
        self.assertEqual(display_threshold(scores), scores[17] * .9)

    def test_sparse_category_retains_lower_scoring_coverage(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        rows = [{'id': i, 'category': 'politics', 'popularity_score': 20,
                 'popularity_updated_at': now.isoformat()} for i in range(36)]
        rows.append({'id': 100, 'category': 'sports', 'popularity_score': .6,
                     'popularity_updated_at': now.isoformat()})
        thresholds = event_thresholds(rows, now)
        self.assertEqual(thresholds[0], 5)
        self.assertLess(thresholds[100], .6)


if __name__ == '__main__':
    unittest.main()

import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from popularity import display_threshold,event_thresholds

class AdaptiveFeedTests(unittest.TestCase):
    def test_valid_small_category_is_not_erased_by_agenda_floor(self):
        now=datetime(2026,10,19,tzinfo=timezone.utc)
        row={'id':1,'category':'sports','popularity_score':.8,'popularity_updated_at':now.isoformat()}
        self.assertLess(event_thresholds([row],now)[1],.8)
        self.assertEqual(display_threshold([.8]),2)

    def test_sparse_and_dense_score_distributions(self):
        self.assertEqual(display_threshold([]),2)
        self.assertEqual(display_threshold([float('nan'),float('inf'),0,-1]),2)
        self.assertEqual(display_threshold([4,1]),2)
        self.assertEqual(display_threshold([20]*38),19)
        values=list(range(38,0,-1))
        threshold=display_threshold(values)
        self.assertGreater(threshold,20)
        self.assertLess(sum(value>=threshold for value in values),15)
        self.assertGreater(sum(value>=threshold for value in values),3)

    def test_sparse_category_has_its_own_boundary(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        rows=[{'id':i,'category':'politics','popularity_score':40-i/2,'popularity_updated_at':now.isoformat()} for i in range(36)]
        rows.append({'id':100,'category':'sports','popularity_score':3,'popularity_updated_at':now.isoformat()})
        thresholds=event_thresholds(rows,now)
        self.assertGreater(thresholds[1],20)
        self.assertLess(thresholds[100],3)

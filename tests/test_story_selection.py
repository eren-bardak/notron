import sys
import unittest
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from story_selection import select_category_candidates, MAX_SELECTED_EVENTS
from event_catalog import CATEGORY_IDS

class CategorySelectionTests(unittest.TestCase):
    def test_ten_independently_in_every_category_including_general(self):
        categories = sorted(CATEGORY_IDS | {'general'})
        events = [{'id': c * 100 + i, 'category': category}
                  for c, category in enumerate(categories) for i in range(15)]
        selected = select_category_candidates(events, lambda e: e['id'])
        self.assertEqual(len(selected), MAX_SELECTED_EVENTS)
        self.assertEqual(Counter(e['category'] for e in selected), {c: 10 for c in categories})
        self.assertEqual(len({e['category'] for e in selected[:7]}), 7)
        for c in categories:
            self.assertEqual([e['id'] for e in selected if e['category'] == c],
                             [e['id'] for e in events if e['category'] == c][:10])

    def test_sparse_categories_are_not_padded_or_starved(self):
        events = [{'id': i, 'category': 'finance'} for i in range(20)]
        events.append({'id': 30, 'category': 'sports'})
        selected = select_category_candidates(events, lambda e: e['id'])
        self.assertEqual(len(selected), 11)
        self.assertEqual(selected[1]['id'], 30)

    def test_duplicates_do_not_consume_capacity(self):
        event = {'id': 1, 'category': 'politics'}
        self.assertEqual(select_category_candidates([event, event], lambda e: e['id']), [event])

    def test_aliases_share_the_same_limit(self):
        events = [{'id': i, 'category': 'economy' if i % 2 else 'finance'} for i in range(20)]
        self.assertEqual(len(select_category_candidates(events, lambda e: e['id'])), 10)

    def test_legacy_unknown_categories_match_ledger_general_bucket(self):
        events = [{'id': i, 'category': None, 'title': 'Futbol' if i % 2 else 'Enflasyon'}
                  for i in range(20)]
        self.assertEqual(len(select_category_candidates(events, lambda e: e['id'])), 10)

    def test_migration_changes_selection_only(self):
        sql = (Path(__file__).resolve().parents[1] / 'backend/category_limits_migration.sql').read_text()
        self.assertIn('pg_get_functiondef', sql)
        self.assertNotIn('update public.notron_daily_batches', sql)
        self.assertNotIn('1500000', sql)
        self.assertNotIn('3250000', sql)
        self.assertIn('having count(*) > 10', sql)

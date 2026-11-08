"""Offline regressions for stale X caches and event-local review failures."""
import copy
import io
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from x_engagement import XEngagement, parse_engagement, combined_x_points
from x_relevance import XRelevance, EventPostReview, apply_review, usable_cache
from x_signals import build_query
import update_event_popularity_v02 as popularity_update

NOW = datetime.now(timezone.utc)
TERMS = ['SPK', 'başkan']
EVENT = {'id': 1, 'title': 'SPK başkanı değişti', 'summary': 'Resmi Gazete kararı.',
         'category': 'finance', 'created_at': NOW.isoformat(),
         'data': {'x_query_terms': TERMS}}


def sample(terms=TERMS, posts=False):
    rows = [{'id': '1', 'text': 'SPK başkanı görevden alındı.',
             'created_at': (NOW - timedelta(hours=1)).isoformat(),
             'public_metrics': {'like_count': 2000, 'retweet_count': 2,
                                'reply_count': 1, 'quote_count': 0}}] if posts else []
    return parse_engagement({'data': rows, 'meta': {'result_count': len(rows)}},
                            build_query(terms, broad=True), NOW - timedelta(hours=24), NOW, NOW)


def decision(quote='SPK başkanı görevden alındı'):
    return EventPostReview.model_validate({'decisions': [
        {'id': '1', 'related': True, 'evidence_quote': quote}]})


class CacheIsolationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.network = patch('requests.sessions.Session.request',
                             side_effect=AssertionError('Offline test attempted network'))
        self.network.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.network.stop)

    def test_stale_empty_cache_is_unavailable_and_next_event_is_reviewed(self):
        client = Mock()
        reviewer = XRelevance(Mock(), NOW, client)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(reviewer.review(EVENT, sample(['eski', 'konu']), allow_paid=False))
            accepted = reviewer.review({**EVENT, 'id': 2}, sample(), allow_paid=False)
        self.assertEqual(accepted['semantic_review']['event_id'], 2)
        self.assertEqual(accepted['semantic_review']['reviewer'], 'empty_sample')
        self.assertEqual(accepted['points'], 0)
        self.assertFalse(reviewer.disabled)
        self.assertEqual(client.mock_calls, [])
        self.assertIn('"event_id": 1', output.getvalue())
        self.assertIn('query_mismatch', output.getvalue())

    def test_stale_reviewed_cache_cannot_bypass_query_validation(self):
        old = apply_review(EVENT, sample(), [], NOW)
        changed = copy.deepcopy(EVENT)
        changed['data']['x_query_terms'] = ['yeni', 'konu']
        # Existing review hash intentionally does not include query terms.
        self.assertIsNone(XRelevance(Mock(), NOW).review(changed, old, allow_paid=False))
        self.assertIsNone(usable_cache(changed, old))
        self.assertEqual(combined_x_points(None, old, changed['data']['x_query_terms'], NOW), 0)

    def test_bad_cache_shapes_and_missing_terms_are_event_local(self):
        bad_signals = [sample(['eski', 'konu'], posts=True),
                       {**sample(), 'posts': None}, {**sample(), 'posts': [None]},
                       {**sample(), 'semantic_review': []},
                       {**sample(), 'window_start': 'not a date'},
                       {**sample(posts=True), 'posts': sample(posts=True)['posts'] * 2}]
        reviewer = XRelevance(Mock(), NOW, Mock())
        for bad in bad_signals:
            with self.subTest(signal=bad):
                self.assertIsNone(reviewer.review(EVENT, bad))
                self.assertFalse(reviewer.disabled)
        self.assertIsNone(reviewer.review({**EVENT, 'data': {}}, sample()))
        self.assertIsNotNone(reviewer.review(EVENT, sample(), allow_paid=False))
        self.assertEqual(reviewer.client.mock_calls, [])

    def test_malformed_pagination_cache_is_not_passed_to_paid_measurement(self):
        for changes in ({'pages_fetched': '3'}, {'pages_fetched': None},
                        {'pages_fetched': True}, {'requested_pages': 99},
                        {'search_complete': []}):
            with self.subTest(changes=changes):
                bad = {**sample(), 'relevance_revision': 4, 'search_complete': False,
                       'stop_reason': 'page_limit', 'pages_fetched': 3, **changes}
                previous = usable_cache(EVENT, bad)
                self.assertIsNone(previous)
                # No token or run ID: exercise cache eligibility without API work.
                get = Mock()
                self.assertIsNone(XEngagement(Mock(), NOW, get).measure(TERMS, previous))
                get.assert_not_called()

    def test_invalid_model_decisions_do_not_disable_other_events(self):
        client = Mock()
        client.responses.parse.side_effect = [Mock(output_parsed=decision('invented quote')),
                                             Mock(output_parsed=decision())]
        reviewer = XRelevance(Mock(), NOW, client)
        with patch.dict(os.environ, {'NOTRON_RUN_ID': 'offline-fixture'}):
            self.assertIsNone(reviewer.review(EVENT, sample(posts=True)))
            self.assertFalse(reviewer.disabled)
            self.assertIsNotNone(reviewer.review({**EVENT, 'id': 2}, sample(posts=True)))
        self.assertEqual(client.responses.parse.call_count, 2)

    def test_provider_failure_still_disables_paid_reviews(self):
        client = Mock()
        client.responses.parse.side_effect = RuntimeError('provider unavailable')
        reviewer = XRelevance(Mock(), NOW, client)
        with patch.dict(os.environ, {'NOTRON_RUN_ID': 'offline-fixture'}):
            self.assertIsNone(reviewer.review(EVENT, sample(posts=True)))
            self.assertTrue(reviewer.disabled)
            self.assertIsNone(reviewer.review({**EVENT, 'id': 2}, sample(posts=True)))
        self.assertEqual(client.responses.parse.call_count, 1)

    def test_unexpected_validation_failure_is_not_swallowed(self):
        signal = sample()
        with patch('x_relevance.parse_engagement', side_effect=RuntimeError('unexpected failure')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected failure'):
                usable_cache(EVENT, signal)

    def run_popularity(self, read_error=None, write_error=None):
        events = [copy.deepcopy(EVENT), {**copy.deepcopy(EVENT), 'id': 2}]
        events[0]['data']['x_engagement_signal'] = sample(['eski', 'konu'])
        events[1]['data']['x_engagement_signal'] = sample()
        db = Mock()
        db.table.return_value.update.return_value.eq.return_value.execute.side_effect = write_error
        def read(db, table, *args, **kwargs):
            if read_error:
                raise read_error
            return events if table == 'events' else []
        def score(*args):
            return {'score': 5, 'community_score': 0, 'source_count': 2,
                    'side_sources': {'left': ['a'], 'right': ['b'], 'center': []},
                    'writer_count': 0, 'micro_count': 0, 'vote_count': 0}
        with ExitStack() as stack:
            for name, replacement in {
                'load_dotenv': Mock(), 'create_client': Mock(return_value=db),
                'read_all': Mock(side_effect=read), 'country_eligible': Mock(return_value=True),
                'score_event': Mock(side_effect=score), 'fetch_trends': Mock(return_value=[]),
                'event_trend_bonus': Mock(return_value=None), 'balanced_event': Mock(return_value=True),
                'current_editorial': Mock(return_value=True), 'publication_quality': Mock(return_value=True),
                'YouTubeFeeds': Mock(), 'XEngagement': Mock(),
            }.items():
                stack.enter_context(patch.object(popularity_update, name, replacement))
            popularity_update.YouTubeFeeds.return_value.activity.return_value = None
            stack.enter_context(patch.dict(os.environ, {'SUPABASE_URL': 'offline',
                'SUPABASE_KEY': 'offline', 'NOTRON_X_PHASE': 'deferred'}))
            popularity_update.main()
            popularity_update.XEngagement.return_value.measure.assert_not_called()
            self.assertEqual(popularity_update.YouTubeFeeds.return_value.activity.call_count, 2)
        return db, events

    def test_popularity_writes_both_events_and_continues_youtube_without_paid_x(self):
        db, events = self.run_popularity()
        updates = [call.args[0] for call in db.table.return_value.update.call_args_list]
        self.assertEqual(len(updates), 2)
        self.assertEqual([row['popularity_score'] for row in updates], [5, 5])
        self.assertEqual([row['data']['popularity_components']['x'] for row in updates], [0, 0])
        # Preserve rejected evidence for diagnosis; do not fabricate a measurement.
        self.assertEqual(updates[0]['data']['x_engagement_signal'], events[0]['data']['x_engagement_signal'])
        self.assertNotIn('semantic_review', updates[0]['data']['x_engagement_signal'])
        self.assertEqual(updates[1]['data']['x_engagement_signal']['semantic_review']['event_id'], 2)

    def test_database_read_failure_still_stops_batch(self):
        with self.assertRaisesRegex(RuntimeError, 'database read unavailable'):
            self.run_popularity(read_error=RuntimeError('database read unavailable'))

    def test_database_write_failure_still_stops_batch(self):
        with self.assertRaisesRegex(RuntimeError, 'database write unavailable'):
            self.run_popularity(write_error=RuntimeError('database write unavailable'))


if __name__ == '__main__':
    unittest.main()

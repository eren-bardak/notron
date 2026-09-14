import sys
import unittest
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from google_trends import FEED_URL, event_trend_bonus, fetch_trends, parse_trends, traffic_floor
from popularity import POLICY, current_score
import update_event_popularity_v02 as runner

NOW = datetime(2026, 9, 14, 6, tzinfo=timezone.utc)
ARTICLE_URL = 'https://www.example.org/haber/okullar-acildi'


def feed(at='Sun, 13 Sep 2026 23:00:00 -0700', volume='2000+'):
    return f'''<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>
        <title>meb</title><pubDate>{at}</pubDate><ht:approx_traffic>{volume}</ht:approx_traffic>
        <ht:news_item><ht:news_item_url>{ARTICLE_URL}?utm_source=google</ht:news_item_url></ht:news_item>
        </item></channel></rss>'''.encode()


def article(url=ARTICLE_URL, hours=0):
    return {'id': 1, 'source': 'A', 'title': 'MEB: Okullar açıldı', 'url': url,
            'published_at': (NOW - timedelta(hours=hours)).isoformat()}


class GoogleTrendsTests(unittest.TestCase):
    def test_live_feed_shape_preserves_approximation_and_converts_timezone(self):
        trend = parse_trends(feed(), NOW)[0]
        self.assertEqual(trend['published_at'], NOW.isoformat())
        self.assertEqual(trend['traffic_label'], '2000+')
        self.assertEqual(trend['traffic_floor'], 2000)
        self.assertEqual(trend['article_urls'], [ARTICLE_URL])

    def test_traffic_buckets_and_invalid_values(self):
        for label, expected in [('200+', 200), ('1,000+', 1000), ('1.5K+', 1500), ('2M+', 2000000),
                                ('NaN', 0), ('-100', 0), ('1,2+', 0), ('', 0), ('0+', 0)]:
            self.assertEqual(traffic_floor(label), expected)

    def test_invalid_future_stale_and_missing_dates_are_not_scored(self):
        for at in ('bad', '', 'Mon, 14 Sep 2026 07:00:00 +0000',
                   'Sun, 13 Sep 2026 05:59:00 +0000', 'Mon, 14 Sep 2026 06:00:00'):
            self.assertEqual(parse_trends(feed(at=at), NOW), [])
        self.assertEqual(len(parse_trends(feed(at='Sun, 13 Sep 2026 06:00:00 +0000'), NOW)), 1)

    def test_generic_keyword_alone_never_matches_a_different_event(self):
        trends = parse_trends(feed(), NOW)
        self.assertIsNone(event_trend_bonus([article('https://www.example.org/haber/meb-maaslari')], trends, NOW))
        self.assertIsNotNone(event_trend_bonus([article(ARTICLE_URL + '?fbclid=tracking')], trends, NOW))

    def test_old_future_and_unknown_article_dates_do_not_link_a_trend(self):
        trends = parse_trends(feed(), NOW)
        for row in (article(hours=25), article(hours=-1), {**article(), 'published_at': None}):
            self.assertIsNone(event_trend_bonus([row], trends, NOW))

    def test_bonus_is_capped_and_duplicates_do_not_inflate_it(self):
        trend = parse_trends(feed(volume='1000000+'), NOW)[0]
        bonus = event_trend_bonus([article()], [trend], NOW)
        self.assertEqual(bonus['points'], POLICY['google_trends_max_points'])
        self.assertEqual(event_trend_bonus([article(), article()], [trend, trend], NOW), bonus)
        smaller = parse_trends(feed(volume='200+'), NOW)[0]
        self.assertLess(event_trend_bonus([article()], [smaller], NOW)['points'], bonus['points'])
        self.assertEqual(event_trend_bonus([article()], [smaller, trend], NOW), bonus)

    def test_unchanged_feed_timestamp_ages_bonus_on_rerun_and_in_web_feed(self):
        trends = parse_trends(feed(), NOW)
        first = event_trend_bonus([article()], trends, NOW)['points']
        later = NOW + timedelta(hours=6)
        second = event_trend_bonus([article()], trends, later)['points']
        self.assertAlmostEqual(second, first / 2)
        self.assertAlmostEqual(current_score({'popularity_score': first, 'popularity_updated_at': NOW.isoformat()}, later), second)

    def test_optional_feed_failure_has_no_bonus_or_second_request(self):
        with patch('google_trends.urlopen', side_effect=TimeoutError) as request:
            self.assertEqual(fetch_trends(NOW), [])
            request.assert_called_once_with(FEED_URL, timeout=15)
        self.assertIsNone(event_trend_bonus([article()], [], NOW))
        with patch('google_trends.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'<html>not RSS</html>'
            self.assertEqual(fetch_trends(NOW), [])
        with patch('google_trends.urlopen') as request:
            request.return_value.__enter__.return_value.read.side_effect = IncompleteRead(b'<rss>', 100)
            self.assertEqual(fetch_trends(NOW), [])
        with self.assertRaises(ValueError):
            parse_trends(b'<!DOCTYPE rss><rss><channel/></rss>', NOW)
        with self.assertRaises(ValueError):
            parse_trends('<!DOCTYPE rss><rss><channel/></rss>'.encode('utf-16'), NOW)
        with patch('google_trends.urlopen') as request:
            request.return_value.__enter__.return_value.read.side_effect = LookupError('unsupported encoding')
            self.assertEqual(fetch_trends(NOW), [])

    def test_scorer_persists_matched_bonus_once_and_preserves_base_without_feed(self):
        rows = {
            'events': [{'id': 1, 'created_at': NOW.isoformat()}],
            'event_news': [{'event_id': 1, 'news_id': 1}],
            'news': [article()], 'sources': [{'name': 'A', 'source_group': 'left'}],
            'event_micro_comments': [], 'event_comments': [], 'event_answers': [], 'event_analyses': [],
        }
        trends = parse_trends(feed(), NOW)
        expected_bonus = event_trend_bonus(rows['news'], trends, NOW)['points']
        for snapshot, expected_score in [(trends, 5 + expected_bonus), ([], 5)]:
            db = MagicMock()
            with patch.object(runner, 'load_dotenv'), patch.object(runner, 'create_client', return_value=db), \
                 patch.object(runner, 'read_all', side_effect=lambda db, table, *args, **kwargs: rows[table]), \
                 patch.object(runner, 'fetch_trends', return_value=snapshot), \
                 patch.object(runner, 'datetime') as clock, \
                 patch.dict('os.environ', {'SUPABASE_URL': 'https://example.invalid', 'SUPABASE_KEY': 'test'}):
                clock.now.return_value = NOW
                runner.main()
            db.table.return_value.update.assert_called_once()
            stored = db.table.return_value.update.call_args.args[0]
            self.assertAlmostEqual(stored['popularity_score'], expected_score)
            self.assertEqual(stored['source_count'], 1)  # Trends never counts as another publisher.


if __name__ == '__main__':
    unittest.main()

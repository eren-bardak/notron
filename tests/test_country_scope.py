import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from country_scope import country_eligible
from country_scope_fixture import COUNTRY_DATA
from generate_event_briefs import select_pending
from datetime import datetime, timezone


class CountryScopeTests(unittest.TestCase):
    def setUp(self):
        self.event = {'data': copy.deepcopy(COUNTRY_DATA)}
        self.articles = [{'id': item['article_id'], 'title': item['quote'], 'source': str(i)}
                         for i, item in enumerate(COUNTRY_DATA['country_scope']['evidence'])]

    def test_publisher_country_language_and_popularity_do_not_establish_country_scope(self):
        for title in ('Musk ABD çocuklarına SpaceX hissesi vaat etti',
                      'Macron bakanın istifasını kabul etmedi', 'Hindistan’da oyuncuya saldırı'):
            self.assertFalse(country_eligible({'title': title, 'country': 'TR', 'popularity_score': 999,
                                               'data': {'catalog_version': '1.1'}}))

    def test_domestic_and_documented_direct_effect_can_pass(self):
        self.assertTrue(country_eligible(self.event, articles=self.articles))
        self.event['data']['country_scope']['relationship'] = 'direct_impact'
        self.assertTrue(country_eligible(self.event, articles=self.articles))
        self.assertFalse(country_eligible(self.event, country='US', articles=self.articles))

    def test_unrelated_or_unknown_scope_fails_closed(self):
        for relationship in ('unrelated', 'global_interest', None):
            self.event['data']['country_scope']['relationship'] = relationship
            self.assertFalse(country_eligible(self.event))

    def test_country_evidence_must_belong_to_two_real_linked_publishers(self):
        bad = copy.deepcopy(self.articles)
        bad[1]['id'] = 3
        self.assertFalse(country_eligible(self.event, articles=bad))
        bad = copy.deepcopy(self.articles)
        bad[1]['source'] = bad[0]['source']
        self.assertFalse(country_eligible(self.event, articles=bad))
        self.event['data']['country_scope']['evidence'][0]['quote'] = 'Türkiye Gazetesi yayımladı.'
        self.assertFalse(country_eligible(self.event, articles=self.articles))

    def test_foreign_story_is_excluded_before_paid_brief_selection(self):
        now = datetime.now(timezone.utc)
        event = {'id': 1, 'source_count': 2, 'left_source_count': 1, 'right_source_count': 1,
                 'popularity_score': 999, 'popularity_updated_at': now.isoformat()}
        self.assertEqual(select_pending([event], [], now), [])
        event['data'] = COUNTRY_DATA
        self.assertEqual([row['id'] for row in select_pending([event], [], now)], [1])

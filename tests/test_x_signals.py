import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from x_signals import XCounts, build_query, parse_counts, signal_points, related_post, MAX_QUERIES
from daily_budget import BudgetError
from event_catalog import balanced_articles, balanced_event, category_id, CATEGORIES

NOW = datetime(2026,10,18,17,30,tzinfo=timezone.utc)
END = NOW.replace(minute=0)
START = END-timedelta(hours=24)
TERMS = ['Pendik', 'dere taskini']

def response(count=3):
    return {'data':[{'start':(START+timedelta(hours=i)).isoformat(),
                     'end':(START+timedelta(hours=i+1)).isoformat(),'tweet_count':count} for i in range(24)],
            'meta':{'total_tweet_count':24*count}}

class SignalsTests(unittest.TestCase):
    def test_only_concrete_safe_conjunctive_queries(self):
        self.assertEqual(build_query(TERMS), '"Pendik" "dere taskini" (min_likes:1000 OR min_replies:101) lang:tr -is:retweet')
        for terms in (None, [], ['Pendik'], ['haber','Turkiye'], ['Pendik','from:example'], ['Pendik','" OR test'], ['Pendik','Pendik']):
            self.assertIsNone(build_query(terms))

    def test_actual_hourly_counts_and_velocity_no_like_estimates(self):
        payload=response(3)
        payload['data'][-1]['tweet_count']=30
        payload['meta']['total_tweet_count']=99
        signal=parse_counts(payload,START,END,build_query(TERMS),NOW)
        self.assertEqual(signal['posts_24h'],99)
        self.assertEqual(signal['posts_per_hour'],12)
        self.assertEqual(signal['previous_posts_per_hour'],3)
        self.assertEqual(signal['growth_ratio'],4)
        self.assertLessEqual(signal['points'],15)
        self.assertNotIn('likes',signal)
        self.assertAlmostEqual(signal_points(signal,build_query(TERMS),NOW+timedelta(hours=12)),signal['points']/2)
        self.assertEqual(signal_points(signal,build_query(['Other','occurrence']),NOW),0)
        self.assertEqual(signal_points(signal,build_query(TERMS),NOW+timedelta(hours=24)),0)

    def test_event_alternatives_match_different_wording_but_not_hashtag_stuffing(self):
        terms=['Milas',['gözaltı','operasyon','Fevzi Topuz']]
        self.assertEqual(build_query(terms),'"Milas" ("gözaltı" OR "operasyon" OR "Fevzi Topuz") (min_likes:1000 OR min_replies:101) lang:tr -is:retweet')
        self.assertTrue(related_post('Milas Belediyesine operasyon düzenlendi, başkan gözaltına alındı.',terms))
        self.assertTrue(related_post('Fevzi Topuz hakkında Milas açıklaması geldi.',terms))
        self.assertFalse(related_post('Kuzey Kore haberi https://t.co/example #Milas #Fevzi Topuz',terms))
        self.assertFalse(related_post('Başka ilçede operasyon düzenlendi.',terms))
        self.assertIsNone(build_query(['Milas',['from:someone','operasyon']]))

    def test_missing_partial_or_invalid_counts_are_not_zero(self):
        for payload in ({}, {'errors':[{}]}, {'data':[]}, {**response(),'meta':{'total_tweet_count':0}},
                        {'data':response()['data'][:1],'meta':{'total_tweet_count':3}}):
            with self.assertRaises(ValueError):
                parse_counts(payload,START,END,build_query(TERMS),NOW)
        zero=parse_counts(response(0),START,END,build_query(TERMS),NOW)
        self.assertEqual(zero['posts_24h'],0)

    def test_no_credentials_or_shared_budget_never_calls_x(self):
        get=Mock()
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(XCounts(Mock(),NOW,get).measure(TERMS))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}), \
             patch('x_signals.ledger',side_effect=BudgetError('closed')):
            self.assertIsNone(XCounts(Mock(),NOW,get).measure(TERMS))
        get.assert_not_called()

    def test_reserves_before_http_caps_queries_and_reuses_cache(self):
        get=Mock(return_value=Mock(status_code=200,json=lambda:response()))
        order=[]
        def reserve(db, operation, **kwargs): order.append(operation)
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}), \
             patch('x_signals.ledger',side_effect=reserve):
            client=XCounts(Mock(),NOW,get)
            signal=client.measure(TERMS)
            self.assertEqual(order,['reserve','settle'])
            self.assertEqual(get.call_args.kwargs['timeout'],15)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(client.measure(TERMS,signal),signal)
            self.assertEqual(get.call_count,1)
            for _ in range(10): client.measure(TERMS)
            self.assertEqual(get.call_count,MAX_QUERIES)

    def test_failed_request_does_not_release_uncertain_reservation_or_retry(self):
        import requests
        get=Mock(side_effect=requests.Timeout())
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}), \
             patch('x_signals.ledger') as budget:
            self.assertIsNone(XCounts(Mock(),NOW,get).measure(TERMS))
            self.assertEqual(budget.call_args.args[1],'reserve')
            self.assertEqual(budget.call_count,1)
            self.assertEqual(get.call_count,1)

    def test_six_categories_and_both_sides_are_required(self):
        self.assertEqual(len(CATEGORIES),6)
        self.assertTrue(balanced_event({'category':'technology','source_count':2,'center_source_count':2}))
        self.assertFalse(balanced_event({'category':'sports','source_count':1}))
        self.assertFalse(balanced_event({'category':'politics','source_count':2,'center_source_count':2}))
        self.assertEqual(category_id('economy'),'finance')
        self.assertEqual(category_id(None,'Fenerbahçe şampiyon oldu'),'sports')
        self.assertFalse(balanced_event({'category':'politics','source_count':3,'left_source_count':2,'center_source_count':1}))
        self.assertTrue(balanced_event({'source_count':2,'left_source_count':1,'right_source_count':1}))
        articles=[{'source':'Sözcü','url':'https://a.test/1'},{'source':'Sabah','url':'https://b.test/1'}]
        self.assertTrue(balanced_articles(articles,{'sozcu':'left','sabah':'right'}))
        articles[1]['url']=articles[0]['url']
        self.assertFalse(balanced_articles(articles,{'sozcu':'left','sabah':'right'}))

if __name__=='__main__': unittest.main()

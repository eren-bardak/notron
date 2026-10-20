import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from x_engagement import XEngagement, parse_engagement, combined_x_points, MAX_QUERIES
from x_signals import build_query
from daily_budget import BudgetError

NOW=datetime(2026,10,19,13,tzinfo=timezone.utc)
START=NOW-timedelta(hours=24)
TERMS=['Orionid','meteor']

def payload(likes):
    return {'data':[{'id':str(i+1),'created_at':(NOW-timedelta(hours=1)).isoformat(),
        'public_metrics':{'like_count':n,'retweet_count':10,'reply_count':5,'quote_count':2}}
        for i,n in enumerate(likes)],'meta':{'result_count':len(likes)}}

class EngagementTests(unittest.TestCase):
    def test_million_like_tier_retains_exact_public_post_links_without_extra_requests(self):
        result=parse_engagement(payload([9999,10000,99999,100000,999999,1000000]),build_query(TERMS),START,NOW,NOW)
        self.assertEqual(result['likes_1m_plus'],1)
        self.assertEqual(result['likes_100k_plus'],3)
        self.assertEqual(result['likes_10k_plus'],5)
        self.assertEqual(result['posts'][-1]['id'],'6')
        self.assertEqual(result['posts'][-1]['likes'],1000000)
        self.assertLessEqual(result['points'],8)
        self.assertNotIn('text',result['posts'][-1])

    def test_real_totals_and_thresholds_keep_exclusive_viral_buckets(self):
        result=parse_engagement(payload([999,1000,9999,10000,99999,100000]),build_query(TERMS),START,NOW,NOW)
        self.assertEqual(result['likes'],221997)
        self.assertEqual(result['reposts'],60)
        self.assertEqual(result['replies'],30)
        self.assertEqual(result['quotes'],12)
        self.assertEqual(result['like_buckets'],[1,2,2,1])
        self.assertEqual(result['likes_1k_plus'],5)
        self.assertEqual(result['likes_10k_plus'],3)
        self.assertEqual(result['likes_100k_plus'],1)
        self.assertEqual(result['scope'],'sampled_matching_posts')
        self.assertLessEqual(result['points'],8)
        self.assertAlmostEqual(combined_x_points(None,result,TERMS,NOW+timedelta(hours=6)),result['points']/2)

    def test_missing_metrics_duplicates_and_unrelated_queries_do_not_become_zero(self):
        bad=payload([10]);bad['data'][0]['public_metrics'].pop('reply_count')
        duplicate=payload([10]);duplicate['data']*=2;duplicate['meta']['result_count']=2
        for data in [bad,duplicate,{'meta':[]},{'data':[],'meta':{'result_count':1}},{'errors':[{}]}]:
            with self.assertRaises(ValueError):
                parse_engagement(data,build_query(TERMS),START,NOW,NOW)
        result=parse_engagement(payload([1000]),build_query(TERMS),START,NOW,NOW)
        self.assertEqual(combined_x_points(None,result,['Başakşehir','Gaziantep'],NOW),0)
        self.assertEqual(parse_engagement(payload([]),build_query(TERMS),START,NOW,NOW)['points'],0)

    def test_reserves_worst_case_then_settles_only_returned_posts_and_caches(self):
        get=Mock(return_value=Mock(status_code=200,json=lambda:payload([1000,10000])))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger') as budget:
            client=XEngagement(Mock(),NOW,get)
            result=client.measure(TERMS)
            self.assertEqual(budget.call_args_list[0].kwargs['p_amount'],50000)
            self.assertEqual(budget.call_args_list[1].kwargs['p_amount'],10000)
            self.assertEqual(client.measure(TERMS,result),result)
            self.assertEqual(get.call_count,1)
            self.assertEqual(get.call_args.kwargs['params']['max_results'],10)
            self.assertNotIn('next_token',get.call_args.kwargs['params'])
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            for i in range(20):client.measure(TERMS)
            self.assertEqual(get.call_count,MAX_QUERIES)

    def test_no_token_no_budget_or_auth_failure_prevents_followup_requests(self):
        get=Mock()
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(XEngagement(Mock(),NOW,get).measure(TERMS))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger',side_effect=BudgetError('closed')):
            self.assertIsNone(XEngagement(Mock(),NOW,get).measure(TERMS))
        get.assert_not_called()
        failed=Mock(status_code=401)
        import requests
        failed.raise_for_status.side_effect=requests.HTTPError()
        get.return_value=failed
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger') as budget:
            client=XEngagement(Mock(),NOW,get)
            self.assertIsNone(client.measure(TERMS))
            self.assertIsNone(client.measure(TERMS))
            self.assertEqual(get.call_count,1)
            self.assertEqual(budget.call_count,1)

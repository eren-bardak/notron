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
        'text':'Orionid meteor yağmuru bu gece gözlenebilecek.',
        'public_metrics':{'like_count':n,'retweet_count':10,'reply_count':5,'quote_count':2}}
        for i,n in enumerate(likes)],'meta':{'result_count':len(likes)}}

class EngagementTests(unittest.TestCase):
    def test_view_only_post_survives_broad_search_and_missing_views_stay_unknown(self):
        data=payload([20,20])
        data['data'][0]['public_metrics']['impression_count']=1000000
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger'):
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual([p['id'] for p in result['posts']],['1'])
        self.assertEqual(result['posts'][0]['impressions'],1000000)
        self.assertNotIn('min_likes:',get.call_args.kwargs['params']['query'])
        missing=parse_engagement(payload([1000]),build_query(TERMS),START,NOW,NOW)
        self.assertNotIn('impressions',missing['posts'][0])
        data['data'][0]['public_metrics']['impression_count']=-1
        with self.assertRaises(ValueError):parse_engagement(data,build_query(TERMS),START,NOW,NOW)
    def test_million_like_tier_retains_exact_public_post_links_without_extra_requests(self):
        result=parse_engagement(payload([9999,10000,99999,100000,999999,1000000]),build_query(TERMS),START,NOW,NOW)
        self.assertEqual(result['likes_1m_plus'],1)
        self.assertEqual(result['likes_100k_plus'],3)
        self.assertEqual(result['likes_10k_plus'],5)
        self.assertEqual(result['posts'][-1]['id'],'6')
        self.assertEqual(result['posts'][-1]['likes'],1000000)
        self.assertLessEqual(result['points'],8)
        self.assertIn('Orionid',result['posts'][-1]['text'])

    def test_unrelated_hashtag_spam_is_billed_but_never_displayed_or_scored(self):
        data=payload([1000000,1000])
        data['data'][0]['text']='Başka bir haber https://t.co/example #Orionid #meteor'
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger') as budget:
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual(result['sample_size'],1)
        self.assertEqual(result['fetched_sample_size'],2)
        self.assertEqual(result['rejected_posts'],1)
        self.assertEqual(result['likes'],1000)
        self.assertEqual(result['likes_1m_plus'],0)
        self.assertEqual(budget.call_args_list[1].kwargs['p_amount'],10000)

    def test_100_likes_is_inclusive_and_101_replies_still_qualifies(self):
        data=payload([99,100,99])
        data['data'][0]['public_metrics']['reply_count']=100
        data['data'][2]['public_metrics']['reply_count']=101
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger') as budget:
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual([post['id'] for post in result['posts']],['2','3'])
        self.assertEqual(result['likes_1k_plus'],0)
        self.assertEqual(budget.call_args_list[1].kwargs['p_amount'],15000)

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
        self.assertEqual(combined_x_points(None,result,TERMS,NOW+timedelta(hours=6)),0)  # relevance review is required before ranking

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
            for i in range(MAX_QUERIES+1):client.measure(TERMS)
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

    def test_three_pages_are_billed_separately_and_deduplicated(self):
        pages=[]
        for ids in ([1,2],[2,3],[4]):
            data=payload([1000]*len(ids))
            for row,post_id in zip(data['data'],ids):row['id']=str(post_id)
            data['meta']['next_token']='page-'+str(len(pages)+1)
            pages.append(Mock(status_code=200,json=lambda data=data:data))
        get=Mock(side_effect=pages)
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run','X_MAX_PAGES':'3'}),patch('x_engagement.ledger') as budget:
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual([row['id'] for row in result['posts']],['1','2','3','4'])
        self.assertEqual(result['fetched_sample_size'],5)
        self.assertEqual(result['duplicate_posts'],1)
        self.assertEqual(result['likes'],4000)
        self.assertEqual(result['pages_fetched'],3)
        self.assertTrue(result['has_more'])
        self.assertFalse(result['search_complete'])
        self.assertEqual(result['stop_reason'],'page_limit')
        self.assertEqual([call.kwargs['p_amount'] for call in budget.call_args_list],[50000,10000,50000,10000,50000,5000])
        self.assertEqual(get.call_args_list[1].kwargs['params']['next_token'],'page-1')
        self.assertEqual(get.call_args_list[2].kwargs['params']['next_token'],'page-2')
        self.assertIn('note_tweet',get.call_args.kwargs['params']['tweet.fields'])

    def test_full_long_post_text_supplies_event_context(self):
        data=payload([1000]);data['data'][0]['text']='Uzun bir açıklama...'
        data['data'][0]['note_tweet']={'text':'Orionid meteor yağmuru hakkında uzun açıklamanın tamamı.'}
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger'):
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual(result['sample_size'],1)
        self.assertEqual(result['posts'][0]['text'],data['data'][0]['note_tweet']['text'])
        self.assertTrue(result['search_complete'])

    def test_budget_or_auth_failure_keeps_successful_pages_explicitly_partial(self):
        import requests
        data=payload([1000]);data['meta']['next_token']='second-page'
        for failure in ('budget','auth'):
            failed=Mock(status_code=429)
            failed.raise_for_status.side_effect=requests.HTTPError()
            get=Mock(side_effect=[Mock(status_code=200,json=lambda:data),failed])
            with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run'}),patch('x_engagement.ledger') as budget:
                if failure=='budget':budget.side_effect=[None,None,BudgetError('daily cap')]
                client=XEngagement(Mock(),NOW,get)
                result=client.measure(TERMS)
                self.assertIsNone(client.measure(['Nutuk','dijital']))
            self.assertEqual(result['sample_size'],1)
            self.assertEqual(result['likes'],1000)
            self.assertTrue(result['has_more'])
            self.assertFalse(result['search_complete'])
            self.assertEqual(get.call_count,1 if failure=='budget' else 2)

    def test_old_one_page_cache_is_upgraded_but_complete_deep_cache_is_reused(self):
        data=payload([1000])
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        old=parse_engagement(data,build_query(TERMS),START,NOW,NOW)
        old['relevance_revision']=1
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run','X_MAX_PAGES':'3'}),patch('x_engagement.ledger'):
            client=XEngagement(Mock(),NOW,get)
            result=client.measure(TERMS,old)
            self.assertEqual(result['relevance_revision'],4)
            self.assertEqual(client.measure(TERMS,result),result)
        self.assertEqual(get.call_count,1)

    def test_page_configuration_is_bounded_and_repeated_cursor_stops(self):
        for configured,expected in [('1000',3),('0',1),('invalid',3)]:
            with patch.dict(os.environ,{'X_MAX_PAGES':configured}):
                self.assertEqual(XEngagement(Mock(),NOW).max_pages,expected)
        data=payload([1000]);data['meta']['next_token']='same'
        get=Mock(return_value=Mock(status_code=200,json=lambda:data))
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test','NOTRON_RUN_ID':'run','X_MAX_PAGES':'3'}),patch('x_engagement.ledger'):
            result=XEngagement(Mock(),NOW,get).measure(TERMS)
        self.assertEqual(get.call_count,2)
        self.assertEqual(result['stop_reason'],'invalid_pagination')
        self.assertEqual(result['sample_size'],1)

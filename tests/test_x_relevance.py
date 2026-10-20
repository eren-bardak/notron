import os,sys,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from x_relevance import XRelevance,apply_review,related_likes_points,EventPostReview
from x_engagement import parse_engagement,combined_x_points
from x_signals import build_query
from x_authors import attach_authors,author_from_oembed

NOW=datetime(2026,10,20,8,tzinfo=timezone.utc)
TERMS=['SPK','başkan']
EVENT={'id':354,'title':'SPK başkanı görevden alındı','summary':'Resmi Gazete kararıyla kurum başkanı değişti.','terms':TERMS}
def signal():
 rows=[{'id':str(i+1),'text':text,'created_at':(NOW-timedelta(hours=1)).isoformat(),
 'public_metrics':{'like_count':likes,'retweet_count':2,'reply_count':1,'quote_count':0}}
 for i,(text,likes) in enumerate([('SPK başkanı görevden alındı, karar Resmi Gazete içinde yayımlandı.',2000),('SPK başkan adayı geçen ay okulun spor turnuvasına katıldı.',1000000)])]
 return parse_engagement({'data':rows,'meta':{'result_count':2}},build_query(TERMS),NOW-timedelta(hours=24),NOW,NOW)
def decisions():return [{'id':'1','related':True,'evidence_quote':'SPK başkanı görevden alındı'}, {'id':'2','related':False,'evidence_quote':''}]

class RelevanceTests(unittest.TestCase):
 def test_same_entity_different_event_never_inflates_favorites_or_score(self):
  result=apply_review(EVENT,signal(),decisions(),NOW)
  self.assertEqual(result['likes'],2000);self.assertEqual(result['sample_size'],1)
  self.assertEqual(result['semantic_review']['rejected_count'],1)
  self.assertEqual(result['points'],related_likes_points(2000))
  self.assertAlmostEqual(combined_x_points({'points':8},result,TERMS,NOW+timedelta(hours=6)),result['points']/2)
  self.assertEqual(combined_x_points({'points':8},signal(),TERMS,NOW),0)
 def test_invented_quotes_duplicate_decisions_and_unreviewed_ids_are_rejected(self):
  for changes in ([{'id':'1','related':True,'evidence_quote':'invented proof'},decisions()[1]],decisions()[:1],[decisions()[0],decisions()[0]]):
   with self.assertRaises(ValueError):apply_review(EVENT,signal(),changes,NOW)
 def test_review_cache_is_event_specific_and_does_not_pay_again(self):
  parsed=EventPostReview.model_validate({'decisions':decisions()})
  client=Mock();client.responses.parse.return_value=Mock(output_parsed=parsed)
  with patch.dict(os.environ,{'NOTRON_RUN_ID':'fixture'}):
   reviewer=XRelevance(Mock(),NOW,client)
   result=reviewer.review(EVENT,signal())
   self.assertEqual(reviewer.review(EVENT,result),result)
   self.assertIsNone(reviewer.review({**EVENT,'id':99},result,allow_paid=False))
  self.assertEqual(client.responses.parse.call_count,1)
  self.assertEqual(client.responses.parse.call_args.kwargs['model'],'gpt-6-luna')
 def test_missing_budget_review_does_not_fabricate_a_zero_or_approve_posts(self):
  with patch.dict(os.environ,{},clear=True):self.assertIsNone(XRelevance(Mock(),NOW).review(EVENT,signal()))
 def test_official_author_must_match_exact_post_and_is_cached(self):
  payload={'author_name':'Murat Emir','url':'https://x.com/muratemir_dr/status/1'}
  self.assertEqual(author_from_oembed(payload,'1'),'Murat Emir')
  self.assertIsNone(author_from_oembed(payload,'2'))
  self.assertIsNone(author_from_oembed({**payload,'url':'https://evil.example/status/1'},'1'))
  get=Mock(return_value=Mock(status_code=200,json=lambda:payload))
  good=apply_review(EVENT,signal(),decisions(),NOW)
  result=attach_authors(good,get=get)
  self.assertEqual(result['posts'][0]['author_name'],'Murat Emir')
  self.assertEqual(attach_authors(good,result,get=get)['posts'][0]['author_name'],'Murat Emir')
  self.assertEqual(get.call_count,1)
  self.assertNotIn('headers',get.call_args.kwargs)

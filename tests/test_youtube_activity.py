import sys, unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from youtube_activity import CHANNELS, YouTubeFeeds, parse_feed

NOW=datetime(2026,10,20,9,tzinfo=timezone.utc)
CHANNEL=next(iter(CHANNELS))
def feed(channel=CHANNEL):
 return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>{channel}</yt:channelId><author><uri>https://www.youtube.com/channel/{channel}</uri></author><entry><yt:videoId>AbC_1234567</yt:videoId><title>Milas Belediyesi operasyonunda gözaltı</title><published>{(NOW-timedelta(hours=1)).isoformat()}</published></entry></feed>'''.encode()

class YouTubeTests(unittest.TestCase):
 def test_real_channel_identity_and_fresh_video_required(self):
  self.assertEqual(len(parse_feed(feed(),CHANNEL,NOW)),1)
  self.assertEqual(parse_feed(feed(),CHANNEL,NOW+timedelta(days=4)),[])
  with self.assertRaises(ValueError):parse_feed(feed('different'),CHANNEL,NOW)
  with self.assertRaises(ValueError):parse_feed(b'<!DOCTYPE x><feed/>',CHANNEL,NOW)
 def test_each_channel_fetched_once_no_token_and_event_anchor_groups_required(self):
  def get(url,**kwargs):return Mock(status_code=200,content=feed(kwargs['params']['channel_id']))
  get=Mock(side_effect=get);client=YouTubeFeeds(NOW,get)
  event={'id':1,'data':{'x_query_terms':['Milas',['operasyon','gözaltı']]}}
  result=client.activity(event)
  self.assertEqual(len(result['videos']),1)
  self.assertEqual(result['channels_checked'],8)
  self.assertEqual(client.activity(event,result),result)
  other=client.activity({'id':2,'data':{'x_query_terms':['Üsküdar','başkan vekili']}})
  self.assertEqual(other['videos'],[]);self.assertEqual(get.call_count,8)
  self.assertNotIn('headers',get.call_args.kwargs)
 def test_outage_does_not_claim_measured_zero(self):
  import requests
  self.assertIsNone(YouTubeFeeds(NOW,Mock(side_effect=requests.Timeout())).activity({'id':1,'data':{'x_query_terms':['Milas','operasyon']}}))

 def test_libya_institution_and_agreement_variants_match_but_other_events_do_not(self):
  from youtube_activity import matching_video
  terms=['Libya Meclisi',['deniz mutabakatı','deniz yetki']]
  self.assertTrue(matching_video('Libya Parlamentosu Türkiye ile Deniz Yetki Anlaşmasını Onayladı!','',terms))
  self.assertTrue(matching_video('Türkiye-Libya Deniz Anlaşması Onaylandı','Libya Temsilciler Meclisi mutabakatı onayladı.',terms))
  self.assertFalse(matching_video('Libya Meclisi vergi kanununu onayladı','Türkiye ile ticaret.',terms))
  self.assertFalse(matching_video('Başka ülkede deniz anlaşması','Libya deprem haberleri',terms))
  self.assertFalse(matching_video('Mekke Savunma Anlaşması','Tezkere meclise geldi\nLibya ile deniz yetki anlaşması',terms))
 def test_api_discovers_full_metadata_once_and_caches_without_visitors(self):
  def get(url,**kwargs):
   if url.endswith('/feeds/videos.xml'):return Mock(status_code=200,content=feed(kwargs['params']['channel_id']))
   if url.endswith('/search'):return Mock(status_code=200,json=lambda:{'items':[{'id':{'videoId':'Libya123456'}}]})
   return Mock(status_code=200,json=lambda:{'items':[{'id':'Libya123456','snippet':{'title':'Libya Parlamentosu deniz anlaşmasını onayladı','description':'Türkiye ile deniz yetki alanları mutabakatı.', 'channelId':CHANNEL,'channelTitle':'TRT Haber','publishedAt':(NOW-timedelta(hours=36)).isoformat()}}]})
  get=Mock(side_effect=get);client=YouTubeFeeds(NOW,get,api_key='test-only-key')
  event={'id':359,'title':'Libya mutabakatı onayladı','data':{'x_query_terms':['Libya Meclisi',['deniz mutabakatı','deniz yetki']]}}
  result=client.activity(event)
  self.assertEqual(result['api_status'],'measured');self.assertEqual([v['id'] for v in result['videos']],['Libya123456'])
  self.assertEqual(result['videos'][0]['source'],'youtube_data_api')
  calls=get.call_count;self.assertEqual(client.activity(event,result),result);self.assertEqual(get.call_count,calls)
 def test_api_search_has_a_hard_batch_limit_and_no_pagination(self):
  get=Mock(return_value=Mock(status_code=200,json=lambda:{'items':[],'nextPageToken':'ignored'}))
  client=YouTubeFeeds(NOW,get,api_key='test-only-key')
  for _ in range(10):client.search({'title':'Libya deniz anlaşması'},['Libya Meclisi','deniz yetki'])
  self.assertEqual(get.call_count,6)
  self.assertTrue(all('pageToken' not in call.kwargs['params'] for call in get.call_args_list))
 def test_api_failure_is_not_a_measured_zero_and_does_not_retry(self):
  import requests
  get=Mock(side_effect=requests.HTTPError('quota exceeded'))
  client=YouTubeFeeds(NOW,get,api_key='test-only-key')
  videos,status=client.search({'title':'Libya deniz anlaşması'},['Libya Meclisi','deniz yetki'])
  self.assertEqual((videos,status),([], 'unavailable'));self.assertEqual(get.call_count,1)
 def test_empty_legacy_cache_does_not_hide_new_matching_and_missing_key_uses_no_api(self):
  from youtube_activity import terms_hash
  get=Mock(side_effect=lambda url,**kw:Mock(status_code=200,content=feed(kw['params']['channel_id'])))
  client=YouTubeFeeds(NOW,get,api_key='')
  event={'id':1,'data':{'x_query_terms':['Milas',['operasyon','gözaltı']]}}
  previous={'revision':1,'event_id':1,'terms_hash':terms_hash(event['data']['x_query_terms']),'measured_at':NOW.isoformat(),'videos':[]}
  result=client.activity(event,previous)
  self.assertEqual(len(result['videos']),1);self.assertEqual(result['api_status'],'missing_key')
  self.assertTrue(all(call.args[0].startswith('https://www.youtube.com/feeds/') for call in get.call_args_list))

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
  self.assertEqual(parse_feed(feed(),CHANNEL,NOW+timedelta(days=2)),[])
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

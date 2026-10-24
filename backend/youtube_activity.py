"""Cached official feeds plus optional bounded YouTube Data API discovery.

No visitor-triggered searches. At most six search calls per pipeline batch;
positive results cache six hours, empty results thirty minutes. API keys stay
server-side. Search failures retain usable prior results and never trigger retries.
"""
import hashlib
import html
import json
import os
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests
from popularity import normalize, parse_time
from x_signals import query_groups
from youtube_relevance import YouTubeRelevance, event_fingerprint

CHANNELS = {
    'UCBgTP2LOFVPmq15W-RH-WXA': 'TRT Haber',
    'UC9TDTjbOjFB9jADmPhSAPsw': 'NTV',
    'UCV6zcRug6Hqp1UX_FdyUeBg': 'CNN TÜRK',
    'UClGZC_r-sUcBdElAtDSrQ5g': 'Habertürk',
    'UCOulx_rep5O4i9y6AyDqVvw': 'SÖZCÜ Televizyonu',
    'UCtc-a9ZUIg0_5HpsPxEO7Qg': 'Haber Global',
    'UCVbZYhcirOke2vipxs4lT2w': 'Anadolu Agency',
    'UCKQhfw-lzz0uKnE1fY1PsAA': 'A Haber',
}
MATCH = json.loads((Path(__file__).resolve().parents[1]/'config/youtube-match.json').read_text())
NS = {'a':'http://www.w3.org/2005/Atom','yt':'http://www.youtube.com/xml/schemas/2015','m':'http://search.yahoo.com/mrss/'}
MAX_SEARCHES = 6


def terms_hash(terms):
    return hashlib.sha256(json.dumps(terms, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def matching_video(title, description, terms, anchor_only=False):
    groups = query_groups(terms)
    if not groups or not isinstance(title, str):
        return False
    if anchor_only:
        groups=groups[:1]
    def tokens(text):
        words = re.findall(r'[^\W_]+', normalize(text))
        return [next((canonical for prefix, canonical in MATCH['prefixAliases'] if word.startswith(prefix)), word) for word in words]
    description = re.sub(r'https?://\S+', ' ', str(description or '')[:1500])
    paragraphs = [part for part in re.split(r'\n+', description) if not part.strip().startswith('#')]
    for body in [title]+[title+' '+part for part in paragraphs]:
        words = tokens(body)
        if all(any(all(any(token == word or len(word) >= 4 and token.startswith(word) for token in words)
                       for word in tokens(phrase)) for phrase in group) for group in groups):
            return True
    return False


def valid_video(row, now):
    at = parse_time(row.get('published_at'))
    if at is None and row.get('source') == 'reviewed_public_page' and row.get('published_precision') == 'day' and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(row.get('published_at',''))):
        try:
            at = datetime.fromisoformat(row['published_at']).replace(tzinfo=timezone.utc)
        except ValueError:
            return False
    return (isinstance(row.get('id'), str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', row['id'])
        and isinstance(row.get('channel_id'), str) and re.fullmatch(r'UC[A-Za-z0-9_-]{22}', row['channel_id'])
        and isinstance(row.get('title'), str) and isinstance(row.get('channel'), str)
        and at and now-timedelta(hours=MATCH['windowHours']) <= at <= now)


def parse_feed(content, channel_id, now):
    if len(content) > 2_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Invalid YouTube feed')
    root = ET.fromstring(content)
    if root.tag != '{'+NS['a']+'}feed' or (root.findtext('yt:channelId', namespaces=NS) not in (channel_id, channel_id[2:])
            or root.findtext('a:author/a:uri', namespaces=NS) != 'https://www.youtube.com/channel/'+channel_id):
        raise ValueError('YouTube feed belongs to another channel')
    videos = []
    for entry in root.findall('a:entry', NS)[:20]:
        row = {'id':entry.findtext('yt:videoId', namespaces=NS),
            'title':html.unescape(entry.findtext('a:title', default='', namespaces=NS))[:300],
            'description':html.unescape(entry.findtext('m:group/m:description', default='', namespaces=NS))[:1500],
            'channel_id':channel_id,'channel':CHANNELS[channel_id],
            'published_at':entry.findtext('a:published', default='', namespaces=NS),'source':'channel_feed'}
        if valid_video(row, now):
            videos.append(row)
    return videos


class YouTubeFeeds:
    def __init__(self, now=None, get=None, api_key=None, db=None, reviewer=None):
        self.now, self.get = now or datetime.now(timezone.utc), get or requests.get
        self.api_key = (api_key if api_key is not None else os.getenv('YOUTUBE_API_KEY') or os.getenv('YOUTUBE_DATA_API_KEY') or '').strip()
        self.loaded, self.videos, self.ok, self.searches = False, [], 0, 0
        self.reviewer = reviewer or (YouTubeRelevance(db,self.now) if db is not None else None)

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        def fetch(channel_id):
            try:
                response = self.get('https://www.youtube.com/feeds/videos.xml', params={'channel_id':channel_id}, timeout=10, allow_redirects=False)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Unexpected feed response')
                return parse_feed(response.content, channel_id, self.now)
            except (requests.RequestException, ValueError, ET.ParseError):
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            for rows in pool.map(fetch, CHANNELS):
                if rows is not None:
                    self.ok += 1
                    self.videos.extend(rows)

    def search(self, event, terms):
        if not self.api_key:
            return [], 'missing_key'
        groups = query_groups(terms)
        if not groups:
            return [], 'invalid_terms'
        # One short entity/event anchor per story: full headlines overconstrain
        # search and two attempts per story previously starved later stories.
        queries = ['|'.join(groups[0])]
        found, status = {}, 'limited'
        for query in queries:
            if self.searches >= MAX_SEARCHES:
                break
            self.searches += 1
            try:
                response = self.get('https://www.googleapis.com/youtube/v3/search', params={
                    'key':self.api_key,'part':'snippet','type':'video','q':query,'maxResults':25,
                    'publishedAfter':(self.now-timedelta(hours=MATCH['windowHours'])).isoformat(),
                    'publishedBefore':self.now.isoformat(),'relevanceLanguage':'tr','regionCode':'TR','safeSearch':'moderate'},
                    timeout=10,allow_redirects=False)
                response.raise_for_status()
                payload = response.json()
                if response.status_code != 200 or not isinstance(payload, dict) or 'error' in payload or not isinstance(payload.get('items'), list):
                    raise ValueError('Incomplete YouTube search')
                ids = list(dict.fromkeys(item.get('id',{}).get('videoId') for item in payload['items'][:25] if isinstance(item,dict)))
                ids = [video_id for video_id in ids if isinstance(video_id,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id)]
                status = 'partial' if payload.get('nextPageToken') else 'measured'
                if not ids:
                    continue
                response = self.get('https://www.googleapis.com/youtube/v3/videos', params={'key':self.api_key,'part':'snippet','id':','.join(ids)},timeout=10,allow_redirects=False)
                response.raise_for_status()
                details = response.json()
                if response.status_code != 200 or not isinstance(details,dict) or 'error' in details or not isinstance(details.get('items'),list):
                    raise ValueError('Incomplete YouTube video metadata')
                for item in details['items'][:25]:
                    snippet = item.get('snippet',{})
                    row = {'id':item.get('id'),'title':html.unescape(str(snippet.get('title','')))[:300],
                        'description':html.unescape(str(snippet.get('description','')))[:1500],
                        'channel_id':snippet.get('channelId'),'channel':str(snippet.get('channelTitle',''))[:100],
                        'published_at':snippet.get('publishedAt'),'source':'youtube_data_api'}
                    if row['id'] in ids and valid_video(row,self.now):
                        found[row['id']] = row
                if found:
                    break
            except (requests.RequestException, ValueError, TypeError, AttributeError):
                # Never log exceptions containing a request URL or API key.
                status = 'unavailable'
                break
        return list(found.values()), status

    def activity(self, event, previous=None):
        terms = (event.get('data') or {}).get('x_query_terms')
        if not query_groups(terms):
            return None
        fingerprint = terms_hash(terms)
        previous = previous or {}
        at = parse_time(previous.get('measured_at'))
        same = previous.get('event_id') == event['id'] and previous.get('terms_hash') == fingerprint
        ttl = timedelta(hours=6) if previous.get('videos') else timedelta(minutes=30)
        mode = 'api_and_feeds' if self.api_key else 'channel_feeds'
        revision = 3 if self.reviewer else 2
        review = previous.get('semantic_review') or {}
        current_review = not self.reviewer or review.get('event_fingerprint') == event_fingerprint(event)
        if same and previous.get('revision') == revision and previous.get('mode') == mode and current_review and at and timedelta(0) <= self.now-at < ttl:
            return previous
        self.load()
        # Feed discovery is broad too; semantic review decides exact-event relevance.
        matched = {v['id']:v for v in self.videos if matching_video(v['title'],v.get('description'),terms,anchor_only=bool(self.reviewer))}
        videos, status = self.search(event,terms)
        matched.update({v['id']:v for v in videos})
        if not self.ok and status not in ('measured','limited') and not matched:
            return previous if same and at and timedelta(0) <= self.now-at < timedelta(hours=24) else None
        if status in ('unavailable','limited') and same and at and timedelta(0) <= self.now-at < timedelta(hours=24):
            for row in previous.get('videos',[]):
                if isinstance(row,dict) and valid_video(row,self.now) and matching_video(row['title'],row.get('description'),terms):
                    matched.setdefault(row['id'],row)
        candidates=list(matched.values())[:12]
        semantic_review=None
        relevance_status='legacy_keyword_match'
        if self.reviewer:
            reviewed=self.reviewer.review(event,candidates)
            relevance_status='measured' if reviewed is not None else 'unavailable'
            candidates,semantic_review=reviewed if reviewed is not None else ([],None)
        else:
            candidates=[v for v in candidates if matching_video(v['title'],v.get('description'),terms)]
        return {'revision':revision,'event_id':event['id'],'terms_hash':fingerprint,
            'measured_at':self.now.isoformat(),'scope':'matching_event_videos','mode':mode,
            'api_status':status,'window_hours':MATCH['windowHours'],'channels_checked':self.ok,
            'relevance_status':relevance_status,'semantic_review':semantic_review,
            'videos':sorted(candidates,key=lambda v:v['published_at'],reverse=True)[:12]}

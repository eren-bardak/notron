"""Free official channel feeds, fetched once per batch; no API key or paid search.

Only recent video titles containing every event anchor group are attached.
This is a bounded sample of channel uploads, not all of YouTube.
"""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests
from popularity import parse_time
from x_signals import query_groups, related_post

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
NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}


def terms_hash(terms):
    return hashlib.sha256(json.dumps(terms, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def parse_feed(content, channel_id, now):
    if len(content) > 2_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Invalid YouTube feed')
    root = ET.fromstring(content)
    if root.tag != '{'+NS['a']+'}feed' or (root.findtext('yt:channelId', namespaces=NS) not in (channel_id, channel_id[2:])
            or root.findtext('a:author/a:uri', namespaces=NS) != 'https://www.youtube.com/channel/'+channel_id):
        raise ValueError('YouTube feed belongs to another channel')
    videos = []
    for entry in root.findall('a:entry', NS)[:20]:
        video_id = entry.findtext('yt:videoId', namespaces=NS)
        title = entry.findtext('a:title', namespaces=NS)
        published = parse_time(entry.findtext('a:published', namespaces=NS))
        if (not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id)
                or not title or not published or not now-timedelta(hours=24) <= published <= now):
            continue
        videos.append({'id': video_id, 'title': ' '.join(title.split())[:300],
            'channel_id': channel_id, 'channel': CHANNELS[channel_id], 'published_at': published.isoformat()})
    return videos


class YouTubeFeeds:
    def __init__(self, now=None, get=None):
        self.now, self.get = now or datetime.now(timezone.utc), get or requests.get
        self.loaded, self.videos, self.ok = False, [], 0

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        def fetch(channel_id):
            try:
                response = self.get('https://www.youtube.com/feeds/videos.xml',
                    params={'channel_id': channel_id}, timeout=10, allow_redirects=False)
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

    def activity(self, event, previous=None):
        terms = (event.get('data') or {}).get('x_query_terms')
        if not query_groups(terms):
            return None
        fingerprint = terms_hash(terms)
        at = parse_time((previous or {}).get('measured_at'))
        if (at and timedelta(0) <= self.now-at < timedelta(hours=6)
                and previous.get('event_id') == event['id'] and previous.get('terms_hash') == fingerprint):
            return previous
        self.load()
        if not self.ok:
            return previous if (at and timedelta(0) <= self.now-at < timedelta(hours=24)
                and previous.get('event_id') == event['id'] and previous.get('terms_hash') == fingerprint) else None
        matched = {v['id']: v for v in self.videos if related_post(v['title'], terms)}
        return {'revision': 1, 'event_id': event['id'], 'terms_hash': fingerprint,
            'measured_at': self.now.isoformat(), 'scope': 'matching_channel_uploads',
            'channels_checked': self.ok, 'videos': sorted(matched.values(),
                key=lambda v: v['published_at'], reverse=True)[:12]}

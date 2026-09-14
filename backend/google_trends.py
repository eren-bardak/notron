"""Optional Google Trends RSS signal; a missing match never penalizes an event."""
import math
import re
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.request import urlopen

from popularity import POLICY, canonical_url, decay, parse_time

FEED_URL = 'https://trends.google.com/trending/rss?geo=TR'
NAMESPACE = {'ht': 'https://trends.google.com/trending/rss'}
MAX_FEED_BYTES = 2_000_000


def traffic_floor(value):
    """Read an approximate traffic bucket, never an exact search count."""
    match = re.fullmatch(r'(\d+(?:,\d{3})*(?:\.\d+)?)([KM]?)\+?', str(value or '').strip().upper())
    if not match:
        return 0
    number = float(match[1].replace(',', '')) * {'': 1, 'K': 1000, 'M': 1_000_000}[match[2]]
    return int(number) if math.isfinite(number) and number > 0 and number.is_integer() else 0


def parse_trends(data, now):
    """The RSS is a partial recent snapshot, not all searches in the last day."""
    if len(data) > MAX_FEED_BYTES:
        raise ValueError('Oversized feed')
    text = data.decode('utf-8-sig')
    if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Unsupported feed')
    root = ET.fromstring(text)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('Expected RSS channel')
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    trends = []
    for item in root.findall('./channel/item'):
        try:
            at = parsedate_to_datetime(item.findtext('pubDate', ''))
        except (TypeError, ValueError, OverflowError):
            continue
        if at.tzinfo is None or not cutoff <= at <= now:
            continue
        query = item.findtext('title', '').strip()
        label = item.findtext('ht:approx_traffic', '', NAMESPACE).strip()
        volume = traffic_floor(label)
        urls = sorted({url for node in item.findall('ht:news_item', NAMESPACE)
                       if (url := canonical_url(node.findtext('ht:news_item_url', '', NAMESPACE)))})
        if query and volume and urls:
            trends.append({'query': query, 'traffic_label': label, 'traffic_floor': volume,
                           'published_at': at.astimezone(timezone.utc).isoformat(), 'article_urls': urls})
    return trends


def fetch_trends(now):
    """One bounded anonymous request per scoring run, with no paid API fallback."""
    try:
        with urlopen(FEED_URL, timeout=15) as response:
            data = response.read(MAX_FEED_BYTES + 1)
        trends = parse_trends(data, now)
        print(f'Google Trends TR: {len(trends)} usable recent RSS trends (partial coverage).')
        return trends
    except (OSError, HTTPException, LookupError, ValueError, ET.ParseError) as exc:
        print(f'Google Trends unavailable ({type(exc).__name__}); using normal popularity scores.')
        return []


def event_trend_bonus(articles, trends, now):
    """Only a shared article URL establishes a match; a generic term cannot."""
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    urls = set()
    for article in articles:
        at = parse_time(article.get('published_at'))
        url = canonical_url(article.get('url'))
        if at and cutoff <= at <= now and url:
            urls.add(url)
    best = None
    for trend in trends:
        at = parse_time(trend['published_at'])
        shared = urls.intersection(trend['article_urls'])
        if not shared or not at or not cutoff <= at <= now:
            continue
        # Fixed scaling avoids making a small trend dominant in a sparse feed.
        strength = min(1.0, math.log1p(trend['traffic_floor']) / math.log1p(POLICY['google_trends_full_traffic']))
        points = POLICY['google_trends_max_points'] * strength * decay(at, now)
        if best is None or points > best['points']:
            best = {'source': 'Google Trends', 'source_url': FEED_URL, 'region': 'TR',
                    'query': trend['query'], 'traffic_label': trend['traffic_label'],
                    'feed_published_at': trend['published_at'], 'matched_article_url': sorted(shared)[0],
                    'match_method': 'exact_article_url', 'points': points}
    return best

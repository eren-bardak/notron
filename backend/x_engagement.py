"""Small, cached samples of real X public metrics, inside the daily budget.

Aggregates describe returned matching posts, never the whole X conversation.
Up to three ten-post pages, no user lookups or automatic retries.
"""
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import requests

from daily_budget import BudgetError, ledger
from popularity import decay, parse_time
from x_signals import build_query, query_hash, signal_points, related_post

SEARCH_URL = 'https://api.x.com/2/tweets/search/recent'
POST_LIMIT = 10
MAX_SAMPLE = 30
POST_PRICE = 5000  # $0.005/post, checked against official X pricing 2026-10-19.
MAX_QUERIES = 24


def post_text(row):
    note = row.get('note_tweet')
    full = note.get('text') if isinstance(note, dict) else None
    return full if isinstance(full, str) and full.strip() else row.get('text')


def qualifying_post(row, terms):
    metrics = row.get('public_metrics') or {}
    return (related_post(post_text(row), terms)
            and (metrics.get('like_count', 0) >= 1000 or metrics.get('reply_count', 0) > 100))


def parse_engagement(payload, query, start, end, now, limit=POST_LIMIT):
    if not isinstance(payload, dict) or payload.get('errors'):
        raise ValueError('Incomplete X engagement response')
    meta = payload.get('meta')
    if not isinstance(meta, dict):
        raise ValueError('Missing X result metadata')
    rows = payload.get('data', [])
    count = meta.get('result_count')
    if not isinstance(rows, list) or type(count) is not int or count != len(rows) or len(rows) > min(limit, MAX_SAMPLE):
        raise ValueError('Invalid X sample size')
    totals = dict(likes=0, reposts=0, replies=0, quotes=0)
    bins = [0, 0, 0, 0]
    seen, posts = set(), []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not re.fullmatch(r'[1-9][0-9]{0,19}', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate X post')
        seen.add(row['id'])
        at = parse_time(row.get('created_at'))
        if not at or not start <= at < end:
            raise ValueError('X post outside requested window')
        metrics = row.get('public_metrics') or {}
        if not isinstance(metrics, dict):
            raise ValueError('Invalid X metrics')
        values = {'likes': metrics.get('like_count'), 'reposts': metrics.get('repost_count', metrics.get('retweet_count')),
                  'replies': metrics.get('reply_count'), 'quotes': metrics.get('quote_count')}
        if any(type(value) is not int or not 0 <= value <= 2**63-1 for value in values.values()):
            raise ValueError('Missing or invalid X public metrics')
        for key, value in values.items():
            totals[key] += value
        likes = values['likes']
        bins[3 if likes >= 100000 else 2 if likes >= 10000 else 1 if likes >= 1000 else 0] += 1
        text = post_text(row)
        posts.append({'id': row['id'], 'created_at': at.isoformat(), **values,
                      **({'text': text[:2000]} if isinstance(text, str) else {})})
    # Exclusive tiers: a 100k post receives its tier once, not three bonuses.
    viral = min(3.0, .25 * bins[1] + .75 * bins[2] + 1.5 * bins[3])
    points = viral + sum(weight * min(1, math.log1p(totals[key]) / math.log1p(full))
        for key, weight, full in [('likes', 1.5, 100000), ('reposts', 1.5, 10000),
                                  ('replies', 1.0, 5000), ('quotes', 1.0, 5000)])
    return {'status': 'measured', 'kind': 'engagement_v1', 'query_hash': query_hash(query),
            'measured_at': now.isoformat(), 'window_start': start.isoformat(), 'window_end': end.isoformat(),
            'scope': 'sampled_matching_posts', 'sort_order': 'relevancy', 'sample_size': len(rows),
            'has_more': bool(payload.get('meta', {}).get('next_token')),
            **totals, 'likes_1k_plus': sum(bins[1:]), 'likes_10k_plus': sum(bins[2:]),
            'likes_100k_plus': bins[3], 'likes_1m_plus': sum(post['likes'] >= 1000000 for post in posts),
            'posts': posts, 'like_buckets': bins, 'points': round(min(8, points), 4)}


class XEngagement:
    def __init__(self, db, now=None, get=None):
        self.db, self.now = db, now or datetime.now(timezone.utc)
        self.get = get or requests.get
        self.token = os.getenv('X_BEARER_TOKEN', '')
        try:
            self.max_pages = max(1, min(3, int(os.getenv('X_MAX_PAGES', '3'))))
        except ValueError:
            self.max_pages = 3
        self.attempts, self.disabled = 0, False

    def measure(self, terms, previous=None):
        query = build_query(terms)
        if not query:
            return None
        at = parse_time(previous.get('measured_at')) if isinstance(previous, dict) else None
        if (at and timedelta(0) <= self.now-at < timedelta(hours=6)
                and previous.get('query_hash') == query_hash(query) and previous.get('kind') == 'engagement_v1'
                and previous.get('status') == 'measured' and previous.get('relevance_revision') == 2
                and (previous.get('search_complete') is True or previous.get('requested_pages') == self.max_pages)):
            return previous
        if not self.token or self.disabled or self.attempts >= MAX_QUERIES or not os.getenv('NOTRON_RUN_ID'):
            return None
        end = self.now-timedelta(seconds=30)
        start = end-timedelta(hours=24)
        rows, seen, tokens = [], set(), set()
        fetched, pages, next_token, reason = 0, 0, None, None
        for page in range(self.max_pages):
            if self.disabled or self.attempts >= MAX_QUERIES:
                reason = 'request_limit'
                break
            request_id = str(uuid.uuid4())
            try:
                ledger(self.db, 'reserve', p_request_id=request_id, p_amount=POST_LIMIT * POST_PRICE)
            except BudgetError:
                self.disabled = True
                reason = 'budget_limit'
                break
            self.attempts += 1
            params = {'query': query, 'max_results': POST_LIMIT,
                'sort_order': 'relevancy', 'start_time': start.isoformat().replace('+00:00', 'Z'),
                'end_time': end.isoformat().replace('+00:00', 'Z'), 'tweet.fields': 'created_at,public_metrics,note_tweet'}
            if next_token:
                params['next_token'] = next_token
            try:
                response = self.get(SEARCH_URL, params=params,
                    headers={'Authorization': 'Bearer '+self.token}, timeout=15, allow_redirects=False)
                if response.status_code in (401, 402, 403, 429):
                    self.disabled = True
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Unexpected X response')
                payload = response.json()
                # Every HTTP page is validated and billed before filtering or
                # cross-page deduplication. A duplicate can still cost money.
                raw = parse_engagement(payload, query, start, end, self.now)
                ledger(self.db, 'settle', p_request_id=request_id, p_amount=raw['sample_size'] * POST_PRICE)
                fetched += raw['sample_size']
                pages += 1
                for row in payload.get('data', []):
                    if row['id'] not in seen:
                        seen.add(row['id'])
                        rows.append(row)
                next_token = payload['meta'].get('next_token')
                if not next_token:
                    break
                if not isinstance(next_token, str) or len(next_token) > 4096 or next_token in tokens:
                    reason = 'invalid_pagination'
                    break
                tokens.add(next_token)
            except (requests.RequestException, ValueError, TypeError, BudgetError):
                # Do not retry an uncertain billed request. Retain already
                # measured pages and explicitly mark this sample incomplete.
                print('X engagement page unavailable; preserving measured results only.')
                self.disabled = True
                reason = 'page_unavailable'
                break
        if not pages:
            return None
        kept = [row for row in rows if qualifying_post(row, terms)]
        more = bool(next_token) or reason is not None
        result = parse_engagement({'data': kept, 'meta': {'result_count': len(kept), 'next_token': more}},
                                  query, start, end, self.now, limit=MAX_SAMPLE)
        result.update(relevance_revision=2, fetched_sample_size=fetched,
                      rejected_posts=len(rows)-len(kept), duplicate_posts=fetched-len(rows),
                      pages_fetched=pages, requested_pages=self.max_pages,
                      search_complete=not more, stop_reason=reason or ('page_limit' if more else 'exhausted'))
        result['engagement_filter'] = {'min_likes': 1000, 'min_replies': 101}
        return result


def combined_x_points(counts, engagement, terms, now):
    query = build_query(terms)
    volume = signal_points(counts, query, now)
    activity = signal_points(engagement, query, now)
    # A contaminated search sample cannot validate the unfiltered volume bonus.
    if isinstance(engagement, dict) and engagement.get('relevance_revision') in (1, 2) and engagement.get('rejected_posts', 0):
        return min(8, activity)
    def measured(signal):
        if not isinstance(signal, dict) or not query:
            return False
        at, points = parse_time(signal.get('measured_at')), signal.get('points')
        return (signal.get('status') == 'measured' and signal.get('query_hash') == query_hash(query)
                and at is not None and timedelta(0) <= now-at < timedelta(hours=24)
                and type(points) in (int,float) and math.isfinite(points) and 0 <= points <= 8)
    if measured(counts) and measured(engagement):
        return min(8, .4 * volume + .6 * activity)
    return min(8, volume + activity)

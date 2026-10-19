"""Small, cached samples of real X public metrics, inside the daily budget.

Aggregates describe returned matching posts, never the whole X conversation.
One page, at most ten posts, no user lookups, retries or pagination.
"""
import math
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests

from daily_budget import BudgetError, ledger
from popularity import decay, parse_time
from x_signals import build_query, query_hash, signal_points

SEARCH_URL = 'https://api.x.com/2/tweets/search/recent'
POST_LIMIT = 10
POST_PRICE = 5000  # $0.005/post, checked against official X pricing 2026-10-19.
MAX_QUERIES = 12


def parse_engagement(payload, query, start, end, now):
    if not isinstance(payload, dict) or payload.get('errors'):
        raise ValueError('Incomplete X engagement response')
    meta = payload.get('meta')
    if not isinstance(meta, dict):
        raise ValueError('Missing X result metadata')
    rows = payload.get('data', [])
    count = meta.get('result_count')
    if not isinstance(rows, list) or type(count) is not int or count != len(rows) or len(rows) > POST_LIMIT:
        raise ValueError('Invalid X sample size')
    totals = dict(likes=0, reposts=0, replies=0, quotes=0)
    bins = [0, 0, 0, 0]
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not str(row.get('id', '')).isdigit() or row['id'] in seen:
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
            'likes_100k_plus': bins[3], 'like_buckets': bins, 'points': round(min(8, points), 4)}


class XEngagement:
    def __init__(self, db, now=None, get=None):
        self.db, self.now = db, now or datetime.now(timezone.utc)
        self.get = get or requests.get
        self.token = os.getenv('X_BEARER_TOKEN', '')
        self.attempts, self.disabled = 0, False

    def measure(self, terms, previous=None):
        query = build_query(terms)
        if not query:
            return None
        at = parse_time(previous.get('measured_at')) if isinstance(previous, dict) else None
        if (at and timedelta(0) <= self.now-at < timedelta(hours=6)
                and previous.get('query_hash') == query_hash(query) and previous.get('kind') == 'engagement_v1'
                and previous.get('status') == 'measured'):
            return previous
        if not self.token or self.disabled or self.attempts >= MAX_QUERIES or not os.getenv('NOTRON_RUN_ID'):
            return None
        request_id = str(uuid.uuid4())
        try:
            ledger(self.db, 'reserve', p_request_id=request_id, p_amount=POST_LIMIT * POST_PRICE)
        except BudgetError:
            self.disabled = True
            return None
        self.attempts += 1
        end = self.now-timedelta(seconds=30)
        start = end-timedelta(hours=24)
        try:
            response = self.get(SEARCH_URL, params={'query': query, 'max_results': POST_LIMIT,
                'sort_order': 'relevancy', 'start_time': start.isoformat().replace('+00:00', 'Z'),
                'end_time': end.isoformat().replace('+00:00', 'Z'), 'tweet.fields': 'created_at,public_metrics'},
                headers={'Authorization': 'Bearer '+self.token}, timeout=15, allow_redirects=False)
            if response.status_code in (401, 402, 403, 429):
                self.disabled = True
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Unexpected X response')
            result = parse_engagement(response.json(), query, start, end, self.now)
            ledger(self.db, 'settle', p_request_id=request_id, p_amount=result['sample_size'] * POST_PRICE)
            return result
        except (requests.RequestException, ValueError, TypeError, BudgetError):
            print('X engagement unavailable; no fabricated likes, replies or reposts.')
            return None


def combined_x_points(counts, engagement, terms, now):
    query = build_query(terms)
    volume = signal_points(counts, query, now)
    activity = signal_points(engagement, query, now)
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

"""Bounded X counts only: volume and posting velocity, never inferred likes.

No token, no matching terms, unavailable budget or failed API => missing signal.
Every attempted paid request reserves $0.005 in the existing $1.50 daily ledger.
No automatic retries or pagination. Never fetch individual posts or user profiles.
"""
import hashlib
import math
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from daily_budget import ledger, BudgetError
from popularity import normalize, parse_time, decay

COUNTS_URL = 'https://api.x.com/2/tweets/counts/recent'
MAX_QUERIES = 6
MAX_POINTS = 15
GENERIC = {'haber', 'son dakika', 'turkiye', 'gundem', 'aciklama', 'gelisme', 'bugun'}


def build_query(terms):
    if not isinstance(terms, list):
        return None
    safe = []
    for term in terms[:3]:
        if not isinstance(term, str):
            return None
        term = ' '.join(term.split())
        if not 3 <= len(term) <= 65 or normalize(term) in GENERIC:
            return None
        # Model output is data, not X query syntax. No operators, URLs or quotes.
        if any(not (char.isalnum() or char in ' -') for char in term):
            return None
        if normalize(term) not in {normalize(item) for item in safe}:
            safe.append(term)
    if len(safe) < 2:
        return None
    return ' '.join('"' + term + '"' for term in safe) + ' lang:tr -is:retweet'


def query_hash(query):
    return hashlib.sha256(query.encode()).hexdigest()


def parse_counts(payload, start, end, query, now):
    if not isinstance(payload, dict) or payload.get('errors'):
        raise ValueError('Incomplete X counts response')
    rows = payload.get('data')
    total = payload.get('meta', {}).get('total_tweet_count')
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        raise ValueError('Missing X counts')
    hours = {}
    for row in rows:
        at, until = parse_time(row.get('start')), parse_time(row.get('end'))
        count = row.get('tweet_count')
        if (not at or not until or not start <= at < until <= end
                or until - at != timedelta(hours=1) or at.minute or at.second
                or type(count) is not int or count < 0 or at in hours):
            raise ValueError('Invalid hourly X count')
        hours[at] = count
    if sum(hours.values()) != total or (total and len(hours) != 24):
        raise ValueError('Incomplete hourly X counts')
    recent = sum(hours.get(end-timedelta(hours=i), 0) for i in range(1, 4)) / 3
    previous = sum(hours.get(end-timedelta(hours=i), 0) for i in range(4, 7)) / 3
    # Fixed scales keep unrelated stories and repeat runs from changing each other.
    volume = min(10.0, 10 * math.log1p(total) / math.log1p(10000))
    speed = min(5.0, 5 * math.log1p(recent) / math.log1p(1000))
    return {'status': 'measured', 'query_hash': query_hash(query),
            'measured_at': now.isoformat(), 'window_start': start.isoformat(),
            'window_end': end.isoformat(), 'posts_24h': total,
            'posts_per_hour': round(recent, 2), 'previous_posts_per_hour': round(previous, 2),
            'growth_ratio': round(recent / previous, 2) if previous else None,
            'points': round(volume + speed, 4)}


def signal_points(signal, query, now):
    if not isinstance(signal, dict) or not query or signal.get('query_hash') != query_hash(query):
        return 0.0
    at = parse_time(signal.get('measured_at'))
    points = signal.get('points')
    if (signal.get('status') != 'measured' or not at or not timedelta(0) <= now-at < timedelta(hours=24)
            or type(points) not in (int, float) or not math.isfinite(points) or not 0 <= points <= MAX_POINTS):
        return 0.0
    return points * decay(at, now)


class XCounts:
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
                and previous.get('query_hash') == query_hash(query) and previous.get('status') == 'measured'):
            return previous
        if not self.token or self.disabled or self.attempts >= MAX_QUERIES or not os.getenv('NOTRON_RUN_ID'):
            return None
        # Fail closed on the shared, atomic ledger before any network call.
        import uuid
        request_id = str(uuid.uuid4())
        try:
            ledger(self.db, 'reserve', p_request_id=request_id, p_amount=5000)
        except BudgetError:
            self.disabled = True
            return None
        self.attempts += 1
        end = self.now.replace(minute=0, second=0, microsecond=0)
        start = end-timedelta(hours=24)
        try:
            response = self.get(COUNTS_URL, params={
                'query': query, 'start_time': start.isoformat().replace('+00:00','Z'),
                'end_time': end.isoformat().replace('+00:00','Z'), 'granularity': 'hour',
            }, headers={'Authorization': 'Bearer ' + self.token}, timeout=15, allow_redirects=False)
            if response.status_code in (401, 402, 403, 429):
                self.disabled = True
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Unexpected X response')
            result = parse_counts(response.json(), start, end, query, self.now)
            ledger(self.db, 'settle', p_request_id=request_id, p_amount=5000)
            return result
        except (requests.RequestException, ValueError, TypeError, BudgetError):
            # Timeout/failure could have been billed; keep the reservation.
            print('X counts unavailable; no fabricated social signal.')
            return None

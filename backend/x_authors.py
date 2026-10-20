"""Public author attribution from official oEmbed, cached with each measured post.

No user lookup endpoint, bearer token or paid expansion is used.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
import requests


def author_from_oembed(payload, post_id):
    if not isinstance(payload, dict):
        return None
    name, address = payload.get('author_name'), payload.get('url')
    if not isinstance(name, str) or not name.strip() or not isinstance(address, str):
        return None
    parsed = urlsplit(address)
    if parsed.scheme != 'https' or parsed.hostname not in ('x.com', 'twitter.com', 'www.x.com', 'www.twitter.com') or not re.fullmatch(r'/[A-Za-z0-9_]{1,15}/status/'+re.escape(post_id), parsed.path):
        return None
    return ' '.join(name.split())[:160]


def attach_authors(signal, previous=None, get=None):
    if not signal or not signal.get('posts'):
        return signal
    get = get or requests.get
    cached = {p['id']: p.get('author_name') for p in (previous or {}).get('posts', []) if p.get('author_name')}
    def lookup(post):
        name = post.get('author_name') or cached.get(post['id'])
        if not name and (post['likes'] >= 100 or post.get('impressions', 0) >= 10000):
            try:
                response = get('https://publish.x.com/oembed', params={'url': 'https://x.com/i/status/'+post['id'],
                    'omit_script': 'true', 'dnt': 'true'}, timeout=8, allow_redirects=False)
                response.raise_for_status()
                if response.status_code == 200:
                    name = author_from_oembed(response.json(), post['id'])
            except (requests.RequestException, ValueError, TypeError):
                pass
        return {**post, **({'author_name': name} if name else {})}
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {**signal, 'posts': list(pool.map(lookup, signal['posts']))}

"""Bound LLM input without starving smaller categories or publishers."""
from collections import defaultdict, deque
from urllib.parse import unquote, urlsplit
from event_catalog import category_id
from popularity import normalize
import re

COMMON = {'haber', 'haberleri', 'bugun', 'son', 'dakika', 'acikladi', 'oldu', 'yeni', 'turkiye', 'yilinda', 'olarak', 'edildi', 'sonra', 'karsi', 'icin', 'olan', 'daha', 'kisi'}


def category_batches(payload):
    groups = defaultdict(list)
    for item in payload:
        groups[item['category_hint']].append(item)
    words = {item['id']: {word for word in re.findall(r'\w+', normalize(item['title'])) if len(word) >= 4 and word not in COMMON} for item in payload}
    for category, seeds in groups.items():
        ids = {item['id'] for item in seeds}
        for item in payload:
            if item['id'] not in ids and any(len(words[item['id']] & words[seed['id']]) >= 2 for seed in seeds):
                ids.add(item['id'])
        yield category, [item for item in payload if item['id'] in ids]


def article_category(row):
    path = unquote(urlsplit(row.get('url') or '').path).lower()
    for category, parts in (
        ('sports', ('/spor/',)), ('finance', ('/ekonomi/', '/finans/')),
        ('magazine', ('/magazin/', '/saklambac/')),
        ('technology', ('/teknoloji/', '/teknokulis/', '/bilim-teknoloji/')),
        ('entertainment', ('/kultur-sanat/', '/kultursanat/', '/sinema/', '/muzik/')),
        ('politics', ('/siyaset/',))):
        if any(part in path for part in parts):
            return category
    return category_id(None, row.get('title', ''))


def sample_articles(rows, limit):
    buckets = defaultdict(deque)
    ordered = sorted(rows, key=lambda row: (row.get('clustered_at') is not None,
                     -(row.get('id') or 0)))
    for row in ordered:
        hint = article_category(row)
        buckets[(hint, row.get('source'))].append(row)
    selected = []
    while buckets and len(selected) < limit:
        for key in list(buckets):
            selected.append(buckets[key].popleft())
            if not buckets[key]:
                del buckets[key]
            if len(selected) == limit:
                break
    return selected

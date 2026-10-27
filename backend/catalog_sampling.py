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
    context = {item['id']: {word for word in re.findall(r'\w+', normalize(item['title'] + ' ' + (item.get('description') or '')[:600])) if len(word) >= 4 and word not in COMMON} for item in payload}
    for category, seeds in groups.items():
        ids = {item['id'] for item in seeds}
        for item in payload:
            if item['id'] not in ids and any(len(shared := words[item['id']] & words[seed['id']]) >= 2
                    or any(len(word) >= 5 for word in shared)
                    or len(context[item['id']] & context[seed['id']]) >= 2 for seed in seeds):
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
    title = normalize(row.get('title', ''))
    if any(word in title for word in ('spacex','orionid','phobos','openai','nvidia','iphone','nasa')):
        return 'technology'
    if any(word in title for word in ('nutuk','kitap fuari','edebiyat','orkestra','film festivali')):
        return 'entertainment'
    return category_id(None, row.get('title', ''))


def sample_articles(rows, limit):
    buckets = defaultdict(deque)
    ordered = sorted(rows, key=lambda row: (row.get('clustered_at') is not None,
                     -(row.get('id') or 0)))
    for row in ordered:
        hint = article_category(row)
        buckets[(hint, row.get('source'))].append(row)
    categories = defaultdict(dict)
    for (category, source), queue in buckets.items():
        categories[category][source] = queue
    selected = []
    while categories and len(selected) < limit:
        for category in list(categories):
            publishers = categories[category]
            source = next(iter(publishers))
            queue = publishers.pop(source)
            selected.append(queue.popleft())
            if queue:
                publishers[source] = queue
            if not publishers:
                del categories[category]
            if len(selected) == limit:
                break
    return selected

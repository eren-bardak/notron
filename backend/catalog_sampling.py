"""Bound LLM input without starving smaller categories or publishers."""
from collections import defaultdict, deque
from urllib.parse import unquote, urlsplit
from event_catalog import category_id


def sample_articles(rows, limit):
    buckets = defaultdict(deque)
    ordered = sorted(rows, key=lambda row: (row.get('clustered_at') is not None,
                     -(row.get('id') or 0)))
    for row in ordered:
        path = unquote(urlsplit(row.get('url') or '').path).lower()
        hint = next((category for category, parts in (
            ('sports', ('/spor/',)), ('finance', ('/ekonomi/', '/finans/')),
            ('magazine', ('/magazin/', '/saklambac/')),
            ('technology', ('/teknoloji/', '/teknokulis/', '/bilim-teknoloji/')),
            ('entertainment', ('/kultur-sanat/', '/kultursanat/')),
            ('politics', ('/siyaset/',))) if any(part in path for part in parts)), None)
        hint = hint or category_id(None, row.get('title', ''))
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

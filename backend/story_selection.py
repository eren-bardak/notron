"""Category-balanced candidate ceilings, independent of the shared money budget."""
from collections import defaultdict, deque
from event_catalog import CATEGORY_IDS, category_id

PER_CATEGORY_LIMIT = 10
MAX_SELECTED_EVENTS = PER_CATEGORY_LIMIT * (len(CATEGORY_IDS) + 1)


def select_category_candidates(events, rank):
    """Keep up to ten per category, then interleave so one cannot spend first."""
    buckets = defaultdict(deque)
    seen = set()
    for event in sorted(events, key=rank):
        event_id = int(event['id'])
        # The ledger uses stored categories/aliases; legacy unknowns share general.
        category = category_id(event.get('category'))
        if event_id not in seen and len(buckets[category]) < PER_CATEGORY_LIMIT:
            buckets[category].append(event)
            seen.add(event_id)
    selected = []
    while buckets:
        for category in list(buckets):
            selected.append(buckets[category].popleft())
            if not buckets[category]:
                del buckets[category]
    return selected

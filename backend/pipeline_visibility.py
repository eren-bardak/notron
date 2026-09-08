"""Publish all eligible files; the public feed splits top three / Other Events."""
import math
from datetime import datetime, timedelta, timezone
from popularity import POLICY, current_score, parse_time, read_all


def valid_numeric_data(series):
    for item in series or []:
        if not isinstance(item, dict) or not str(item.get('source_url', '')).startswith(('https://', 'http://')):
            continue
        points = item.get('points') or []
        valid = [p for p in points if isinstance(p, dict) and isinstance(p.get('value'), (int, float)) and math.isfinite(p['value'])]
        if len(valid) >= 2:
            return True
    return False


def valid_questions(analysis):
    questions = (analysis or {}).get('binary_questions')
    return isinstance(questions, list) and len(questions) == 3 and all(
        isinstance(q, dict) and isinstance(q.get('question'), str) and q['question'].strip()
        for q in questions)


def ready_event_ids(events, analyses, now=None, limit=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    ready = {int(row['event_id']) for row in analyses if row.get('status') == 'ready'
             and valid_questions(row.get('analysis'))}
    eligible = []
    for event in events:
        created = parse_time(event.get('created_at'))
        if (int(event['id']) in ready and created and cutoff <= created <= now
                and event.get('enough_data') is True
                and valid_numeric_data(event.get('numeric_data')) and (event.get('source_count') or 0) >= 2
                and current_score(event, now) >= POLICY['display_threshold']):
            eligible.append(event)
    eligible.sort(key=lambda event: (-current_score(event, now), int(event['id'])))
    return [int(event['id']) for event in eligible[:limit]]


def publish_ready_events(db):
    now = datetime.now(timezone.utc)
    events = read_all(db, 'events', 'id,created_at,enough_data,problem_supported,numeric_data,source_count,popularity_score,popularity_updated_at')
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    recent = [e for e in events if (at := parse_time(e.get('created_at'))) and cutoff <= at <= now]
    ids = [int(e['id']) for e in recent]
    analyses = read_all(db, 'event_analyses', 'id,event_id,status,analysis', 'event_id', ids)
    visible = ready_event_ids(recent, analyses, now)
    db.table('events').update({'is_visible': False}).eq('is_visible', True).execute()
    for rank, event_id in enumerate(visible, 1):
        db.table('events').update({'is_visible': True, 'popularity_rank': rank}).eq('id', event_id).execute()
    print(f'Publication complete | Gündem={min(len(visible), POLICY["primary_limit"])} | Other Events={max(0, len(visible)-POLICY["primary_limit"])}')
    return visible

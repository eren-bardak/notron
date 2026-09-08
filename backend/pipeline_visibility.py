"""Publish eligible files; the public feed splits Gündem / Diğer Haberler."""
from datetime import datetime, timedelta, timezone
from numeric_data_quality import valid_analysis_timeline, valid_numeric_data
from popularity import POLICY, current_score, parse_time, read_all
from editorial_quality import current_editorial


def valid_questions(analysis):
    questions = analysis.get('binary_questions') if isinstance(analysis, dict) else None
    if not isinstance(questions, list) or len(questions) not in (1, 3):
        return False
    if not all(isinstance(q, dict) and isinstance(q.get('question'), str)
               and q['question'].strip() for q in questions):
        return False
    # Keep legacy arrays untouched: their original positions are part of ballot IDs.
    metrics = [q for q in questions if q.get('question_type') == 'metric']
    return (len(metrics) == 1 and isinstance(metrics[0].get('data_anchor'), str)
            and bool(metrics[0]['data_anchor'].strip()))



def ready_event_ids(events, analyses, now=None, limit=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    ready = {int(row['event_id']): row.get('analysis') for row in analyses if row.get('status') == 'ready'
             and current_editorial(row.get('analysis')) and valid_questions(row.get('analysis'))}
    eligible = []
    for event in events:
        created = parse_time(event.get('created_at'))
        if (int(event['id']) in ready and created and cutoff <= created <= now
                and event.get('enough_data') is True
                and valid_analysis_timeline(ready[int(event['id'])], event.get('numeric_data'), now)
                and (event.get('source_count') or 0) >= 2
                and current_score(event, now) >= POLICY['display_threshold']):
            eligible.append(event)
    eligible.sort(key=lambda event: (-current_score(event, now), int(event['id'])))
    return [int(event['id']) for event in eligible[:limit]]


def enforce_previous_year_gate(db, events, analyses, now=None):
    """Demote stale cached files before any paid research or publication attempt."""
    now = now or datetime.now(timezone.utc)
    by_id = {int(row['event_id']): row for row in analyses}
    rejected = []
    for event in events:
        event_id = int(event['id'])
        stored = by_id.get(event_id, {})
        if valid_analysis_timeline(stored.get('analysis'), event.get('numeric_data'), now):
            continue
        rejected.append(event_id)
        if event.get('enough_data') is not False or event.get('is_visible') is True:
            db.table('events').update({'enough_data': False, 'is_visible': False}).eq('id', event_id).execute()
        event['enough_data'] = False
        event['is_visible'] = False
        if stored.get('status') == 'ready':
            db.table('event_analyses').update({'status': 'insufficient_data'}).eq('event_id', event_id).execute()
            stored['status'] = 'insufficient_data'
    return rejected


def publish_ready_events(db):
    now = datetime.now(timezone.utc)
    events = read_all(db, 'events', 'id,created_at,enough_data,is_visible,problem_supported,numeric_data,source_count,popularity_score,popularity_updated_at')
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    recent = [e for e in events if (at := parse_time(e.get('created_at'))) and cutoff <= at <= now]
    ids = [int(e['id']) for e in recent]
    analyses = read_all(db, 'event_analyses', 'id,event_id,status,analysis', 'event_id', ids)
    rejected = enforce_previous_year_gate(db, recent, analyses, now)
    visible = ready_event_ids(recent, analyses, now)
    db.table('events').update({'is_visible': False}).eq('is_visible', True).execute()
    for rank, event_id in enumerate(visible, 1):
        db.table('events').update({'is_visible': True, 'popularity_rank': rank}).eq('id', event_id).execute()
    print(f'Publication complete | Gündem={min(len(visible), POLICY["primary_limit"])} | Diğer Haberler={max(0, len(visible)-POLICY["primary_limit"])} | previous_year={now.year - 1} | insufficient_data={len(rejected)}')
    return visible

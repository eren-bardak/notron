"""Run after clustering. Score candidates; deep dives publish completed events."""
import os
import json
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client
from popularity import POLICY, normalize, parse_time, read_all, score_event, source_side
from google_trends import event_trend_bonus, fetch_trends
from event_catalog import balanced_event, category_id
from x_signals import XCounts, build_query, signal_points


def main():
    load_dotenv()
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    events = read_all(db, 'events', 'id,title,category,data,created_at,problem_supported')
    events = [e for e in events if (created := parse_time(e.get('created_at'))) and cutoff <= created <= now]
    if not events:
        print('No recent events. Scoring skipped.')
        return
    ids = [int(e['id']) for e in events]
    # Complete every input read before overwriting any scores.
    links = read_all(db, 'event_news', 'event_id,news_id', 'event_id', ids, order_by='news_id')
    news_ids = sorted({int(r['news_id']) for r in links})
    news = read_all(db, 'news', 'id,source,title,url,published_at', 'id', news_ids)
    sources = read_all(db, 'sources', 'name,source_group', order_by='name')
    micro = read_all(db, 'event_micro_comments', 'id,event_id,user_id,text,status,created_at', 'event_id', ids)
    # Older comment tables lack user_id. Read their existing columns without
    # guessing an author; unattributed legacy rows earn no Writer points.
    comments = read_all(db, 'event_comments', '*', 'event_id', ids)
    legacy_count = sum(1 for row in comments if not row.get('user_id'))
    if legacy_count:
        print(f'Legacy Writer comments without account identity: {legacy_count}; no ranking credit.')
    answers = read_all(db, 'event_answers', 'id,event_id,user_id,binary_answers,created_at', 'event_id', ids)
    analyses = read_all(db, 'event_analyses', 'id,event_id,analysis', 'event_id', ids)
    news_by_id = {int(r['id']): r for r in news}
    analysis_by_id = {int(r['event_id']): r.get('analysis') or {} for r in analyses}
    sides = {normalize(s['name']): source_side(s.get('source_group')) for s in sources}
    trends = fetch_trends(now)
    articles_by_event = {event_id: [] for event_id in ids}
    for link in links:
        article = news_by_id.get(int(link['news_id']))
        if article and int(link['event_id']) in articles_by_event:
            articles_by_event[int(link['event_id'])].append(article)
    results = []
    x_counts = XCounts(db, now)
    for event in events:
        result = score_event(event, links, news_by_id, sides, micro, comments, answers, analysis_by_id.get(int(event['id'])), now)
        trend = event_trend_bonus(articles_by_event[int(event['id'])], trends, now)
        if trend:
            result['score'] += trend['points']
            print('GOOGLE_TRENDS_MATCH ' + json.dumps({'event_id': event['id'], **trend}, ensure_ascii=False))
        results.append((event, result))
    # Spend only on the strongest cross-spectrum candidates. One counts request
    # includes all 24 hourly buckets; individual posts/likes are never purchased.
    results.sort(key=lambda pair: (-pair[1]['score'], int(pair[0]['id'])))
    for event, result in results:
        balanced = balanced_event({'source_count':result['source_count'],
            'left_source_count':len(result['side_sources']['left']),
            'right_source_count':len(result['side_sources']['right'])})
        metadata = event.get('data') if isinstance(event.get('data'), dict) else {}
        terms = metadata.get('x_query_terms')
        signal = x_counts.measure(terms, metadata.get('x_signal')) if balanced else None
        if signal is not None:
            metadata = {**metadata, 'x_signal':signal}
        result['catalog_data'] = metadata
        result['score'] += signal_points(metadata.get('x_signal'), build_query(terms), now) if balanced else 0
    results.sort(key=lambda pair: (-pair[1]['score'], int(pair[0]['id'])))
    print('RANK | SCORE | SOURCES | BALLOTS | EVENT')
    for rank, (event, result) in enumerate(results, 1):
        data = {'popularity_score': result['score'], 'popularity_updated_at': now.isoformat(),
                'popularity_rank': rank, 'source_count': result['source_count'],
                'left_source_count': len(result['side_sources']['left']),
                'center_source_count': len(result['side_sources']['center']),
                'right_source_count': len(result['side_sources']['right']),
                'comment_count': result['writer_count'], 'micro_comment_count': result['micro_count']}
        data.update(category=category_id(event.get('category'), event.get('title', '')),
                    data=result['catalog_data'])
        db.table('events').update(data).eq('id', event['id']).execute()
        print(f"{rank:4} | {result['score']:7.2f} | {result['source_count']:7} | {result['vote_count']:7} | {event['id']}")


if __name__ == '__main__':
    main()

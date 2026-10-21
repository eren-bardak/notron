"""Refresh only one event's YouTube links; never runs LLM or X requests."""
import argparse
import json
import os
from dotenv import load_dotenv
from supabase import create_client
from youtube_activity import YouTubeFeeds


def refresh(db, event_id):
    rows = db.table('events').select('id,title,data').eq('id', event_id).eq('enough_data', True).eq('is_visible', True).limit(1).execute().data
    if not rows:
        raise ValueError('Visible event not found')
    event = rows[0]
    original = event.get('data') or {}
    activity = YouTubeFeeds().activity(event, original.get('youtube_activity'))
    if activity is None:
        raise ValueError('YouTube lookup unavailable; previous links were preserved')
    data = {**original, 'youtube_activity': activity}
    # Optimistic JSONB equality prevents clobbering a concurrent pipeline update.
    result = db.table('events').update({'data': data}).eq('id', event_id).eq('data', json.dumps(original, ensure_ascii=False, separators=(',', ':'))).execute().data
    if not result:
        raise ValueError('Event changed during refresh; no metadata was overwritten')
    print(json.dumps({'event_id':event_id,'videos':len(activity['videos']),'api_status':activity['api_status']},ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--event-id', type=int, required=True)
    args = parser.parse_args()
    if args.event_id < 1:
        parser.error('event-id must be positive')
    load_dotenv()
    refresh(create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']), args.event_id)


if __name__ == '__main__':
    main()

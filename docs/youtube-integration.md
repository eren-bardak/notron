# YouTube discovery

The daily popularity update always reads eight official channel feeds once per
batch. It matches event anchors in the title or an individual description line;
`meclis/parlamento` and `mutabakat/anlaşma` variants share canonical tokens.
Descriptions are used for matching, not shown as copied video content.

For wider discovery, enable YouTube Data API v3 in the application's Google Cloud
project and put an API-restricted key in Render's `YOUTUBE_API_KEY` secret.
`YOUTUBE_DATA_API_KEY` is also supported. Keep the key server-side and restrict it
to YouTube Data API v3. Never put it in public frontend variables or source files.
No visitor OAuth login or YouTube account access is needed for public video search.

At most six `search.list` calls are made per pipeline invocation, with at most
two queries per event. Each search inspects at most 25 IDs with one batched
`videos.list` request for full metadata. There is no pagination or automatic retry.
No visitor request performs an API search. Positive results cache for six hours;
empty results cache for thirty minutes. Only videos from the last 72 hours can
appear, and event metadata expires after 24 hours. API errors are marked unavailable
and do not claim that no matching videos exist. A newly added key bypasses an old
RSS-only cache on the next run. Existing daily LLM/X spending limits are unchanged.

Optional focused refresh, without an LLM or X run:
`python backend/refresh_youtube.py --event-id 359`

This updates only that event's `data.youtube_activity` through the existing
Supabase REST client. A refresh requires the normal server-side Supabase secrets.

# X popularity inputs

Coverage and real in-app participation remain the base score. X contributes at
most eight points before the same six-hour half-life.

For each reviewed event, recent counts measure 24 complete hourly buckets.
Recent search requests one relevance-sorted page, at most ten matching original
posts, with public metrics. Store sampled likes, reposts, replies and quotes,
plus counts at 1,000+, 10,000+ and 100,000+ likes. These are sample statistics,
not totals for all X posts about the event. A zero is stored only after a valid
successful measurement; missing credentials or failed requests mean unavailable.

Viral tiers are exclusive for scoring: [1k,10k), [10k,100k), [100k,infinity).
They contribute 0.25, 0.75 and 1.5 points per sampled post, capped at three.
Logarithmic likes/reposts/replies/quotes contribute at most another five points.
When both measurements exist, X points are 40% count/velocity and 60% public
engagement; otherwise use the available measurement. The combined cap is eight.

Refresh requests prioritize categories in rotation, cache query-matched results
for six hours, and have no pagination or automatic HTTP retries. Fetch no user
profiles, like lists or reply bodies. Only reviewed, newsworthy events qualify
for paid X requests.

Each ten-post request first reserves $0.05, then settles $0.005 per returned
post. Counts reserve $0.005 per request. Twelve search requests plus six counts
requests cost at most $0.63 per scoring pass, and all calls must fit the original
atomic $1.50 daily ledger alongside model calls and compute allowance. Failed or
uncertain calls retain reservations. Research runs before paid X measurements.

`--scores-only` makes no paid calls. `--supplement` refreshes RSS, groups by
category and creates bounded text-only briefs after the daily batch is complete.
It preserves the original selected event IDs and completion status; it does not
reset spending. Category refreshes share the same budget and cross-host lease.

Official references, checked 2026-10-19:
- https://docs.x.com/x-api/getting-started/pricing
- https://docs.x.com/x-api/posts/search-recent-posts

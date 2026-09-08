# Nötron news pipeline

Real-news ingestion, clustering, popularity ranking and deep analysis for [Nötron](https://notron-earth-voices.erenbardak.chatgpt.site).

This repository runs the Python news pipeline. The web application is published through Sites and is not included in this runner checkout.

## Running

Required repository Actions secrets: `SUPABASE_URL`, `SUPABASE_KEY` (server write key), and `OPENAI_API_KEY`. Use the same Supabase project as the website. Never commit secret values or `.env` files.

The workflow runs every six hours (00:17, 06:17, 12:17, 18:17 Europe/Istanbul), on pipeline-code changes to main, or manually from Actions. Scheduled starts can be delayed by GitHub.

Order: `rss_fetcher.py` → `clustering_news_enriched.py` → `update_event_popularity_v02.py` → `generate_event_deep_dives.py`.

Positive, neutral and negative events are welcome. Only the last 36 hours qualify. Gündem displays at most three eligible events; remaining qualifying events appear in Other Events.

See [backend/POPULARITY.md](backend/POPULARITY.md) for scoring and qualification rules.

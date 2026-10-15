# Nötron news pipeline

Real-news ingestion, clustering, ranking and analysis for [Nötron](https://notron-earth-voices.erenbardak.chatgpt.site). The website is maintained separately through Sites.

## Testing costs

| Mode | Behavior | OpenAI usage |
| --- | --- | --- |
| `test` | Runs backend unit tests with network and `.env` loading blocked. No live database changes or new news. | None |
| `economy` | Groups at most 80 articles into at most 3 candidates and researches at most 1 event. Skips duplicate enrichment and optional cover/photo/background passes. | Paid, bounded workload |
| `full` | Runs the full pipeline, researching up to 20 events. | Paid |

Code pushes run only offline tests. Manual **Actions → Nötron news pipeline → Run workflow** defaults to `test`; select `economy` when you need real news. Daily updates at 09:00 Türkiye use `economy` during testing. GitHub may delay scheduled starts. `full` must be chosen explicitly in Actions.

Economy mode still runs the real source research, independent question review, numeric-evidence checks and publication gates. It reuses acceptable saved research. Grouping uses supplied RSS text instead of an additional web search. Optional artwork/context updates wait for a full run. The limits are workload caps, not a guaranteed dollar budget; model/search costs vary. A positive API credit balance is still required for economy/full.

## Local commands

```bash
pip install -r backend/requirements.txt
python backend/run_pipeline.py --mode test
python backend/run_pipeline.py --mode economy
python backend/run_pipeline.py --mode full
```

The CLI defaults to `full` for compatibility with existing explicit local runners. Use `--check` to validate configuration without API requests or database changes.

Live modes need `SUPABASE_URL`, `SUPABASE_KEY` and `OPENAI_API_KEY`. In GitHub, keep them in repository Actions secrets. Never commit `.env` files or credential values. The offline checks job receives no repository secrets.

Pipeline order: RSS → clustering → popularity → research/publication. Current events and evidence must satisfy the existing freshness, source and editorial rules; economy mode does not publish test fixtures as news.

See [backend/POPULARITY.md](backend/POPULARITY.md) for scoring rules.

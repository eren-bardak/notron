# Nötron news pipeline

Real-news ingestion, clustering, ranking and analysis for [Nötron](https://notron-earth-voices.erenbardak.chatgpt.site). The website is maintained separately through Sites.

## Testing costs

| Mode | Behavior | OpenAI usage |
| --- | --- | --- |
| `test` | Runs backend unit tests with network and `.env` loading blocked. No live database changes or new news. | None |
| `economy` | Groups up to 300 current articles; targets the 3 events with the broadest publisher coverage. Keeps source, evidence and independent editorial checks. | Shared daily reservations required |
| `full` | Runs the full pipeline, researching up to 20 events. | Paid |

Code pushes and pull requests run only offline tests. The proposed daily runner is **Render Cron at 10:00 Türkiye** (`0 7 * * *` UTC), configured in `render.yaml`. GitHub remains for source, offline checks and explicit manual runs. See [deployment and cutover instructions](docs/render-cron.md). The YAML file alone does not activate a Render service.

Economy mode still runs the real source research, independent question review, numeric-evidence checks and publication gates. It reuses acceptable saved research. Grouping uses supplied RSS text instead of an additional web search. Optional artwork/context updates wait for a full run. A batch that publishes fewer than three selected stories fails visibly; it never weakens publication checks to fill the target.

`backend/daily_budget.sql` supplies a service-role-only PostgreSQL ledger. Each Türkiye calendar day has a $1.50 envelope, including a conservative $0.25 runner allowance per attempt. Calls reserve money atomically before contacting OpenAI. Successful calls reconcile conservatively priced usage; timeouts, parse failures and missing usage retain their full reservation. Retries share the same budget and story IDs, and overlapping hosts cannot acquire the same lease. An unavailable ledger stops paid calls. Output, search calls, request sizes, model and processing tier are restricted to the reviewed price envelope. Provider price changes, taxes and unrelated account usage are outside this application's accounting; verify actual hosting prices before activation.

During testing, economy mode uses `gpt-6-luna` for grouping, research, analysis and question review. See the [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) and [pricing](https://developers.openai.com/api/docs/pricing), checked 16 October 2026. Other models are rejected by the daily price guard until their costs are reviewed. Full mode preserves the previous uncapped model configuration and must not be used for the daily budgeted batch. Account access and live output quality still need a funded API run; offline tests do not establish these.

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

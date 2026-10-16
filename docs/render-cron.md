# Nötron daily runner

## Deployment

The Python backend runs as a Render Cron service. The existing Supabase project
continues storing stories and the shared daily budget. GitHub hosts the source
and tests; GitHub's cron is removed only as part of the verified cutover.

1. Apply `backend/daily_budget.sql` to Nötron's Supabase project.
2. Connect the Render integration and select the intended Render workspace.
3. Review the smallest Cron compute plan (`0.5c-512mb`). Render charges by active
   runtime with a $1/month minimum. Confirm its current rate fits the $0.25
   allowance for a run limited to 20 minutes. No paid service is created by
   committing the Blueprint.
4. Create the service from `render.yaml`, using the proposed branch for the
   initial test. Set `SUPABASE_URL`, the existing backend `SUPABASE_KEY` with
   service-role access, and `OPENAI_API_KEY` as private Render environment values.
   Enter credentials through the provider's secure settings, never chat or Git.
5. Verify that the OpenAI project has API credits and can use `gpt-6-luna`.
6. Trigger one funded economy run. Confirm that all three selected stories pass
   the existing publication gates, are visible in the public app, and that the
   daily ledger contains bounded charges with no outstanding failed request.
7. Merge the cutover PR, point Render at `main`, and verify the daily schedule is
   enabled at `0 7 * * *` UTC (**10:00 Europe/Istanbul**). The same PR removes
   GitHub's old schedule so only one scheduler remains. Keep manual GitHub runs
   available for diagnostics; their economy calls use the same shared ledger.

Do not describe the migration as active until the service, secrets, funded run
and schedule readback are verified. A connected Supabase database alone cannot
execute this Python process. A successful offline check is not a news refresh.

## Failure handling

- A maximum of one batch holds the 30-minute database lease. The runner's own
  deadline is 19 minutes; Render's command terminates it at 20 minutes.
- An already-completed Türkiye day skips paid work. A failed retry retains the
  original story selection and all uncertain spending reservations.
- Fewer than three publishable stories produces a nonzero exit. It does not
  fabricate stories, publish rejected analyses, or relax evidence checks.
- Expired stories retain the existing 24-hour window. No old publication date is
  rewritten to make stale content look current.
- Inspect `notron_daily_batches`, `notron_batch_runs`, and
  `notron_api_reservations` for status. They contain no participant records and
  are inaccessible to anonymous or signed-in app clients.
- Keep the uncapped legacy `full` mode outside this daily service.

## Price envelope

`daily_budget.py` allows only standard-tier GPT-6 Luna requests, at most 12000
output tokens, two built-in web-search calls, and bounded text inputs. It uses
the higher long-context cache-write/output rates plus a 10% premium when
settling usage. Text calls reserve $0.07. Search calls reserve $0.90, covering
three passes through the model's entire 1,050,000-token context plus search and
output fees. Successful calls normally settle far below those reservations.
Calls with uncertain billing keep the reservation; new calls stop when another
full reservation would exceed $1.50. This conservative policy can produce fewer
stories on a day with failed or unusually expensive research.

Prices and limits were checked on 2026-10-16 against:

- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/pricing
- https://render.com/docs/cronjobs
- https://render.com/docs/blueprint-spec

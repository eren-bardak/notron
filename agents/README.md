# Persistent cloud controllers — disabled implementation

This extends the first offline pilot in `docs/cloud-agent-pilot.md`. Real HTTP,
database and GitHub adapters now exist and have local tests. No hosted schema,
credentials, schedules, PR, merge, deployment or paid model call has been made.
The scheduler is deliberately stored as `workflows/cloud-agents.yml.disabled`,
outside GitHub's workflow directory. Both application and database default off.

## Runtime and boundaries

Three roles share two schedulers, not three copies of the news pipeline:

1. **News:** existing Render cron at 07:00 UTC, unchanged. It uses the existing
   $1.50/day Istanbul-day ledger and publication gates. None of the new code can
   dispatch a news workflow or access its credentials.
2. **Development:** GitHub standard Linux runner at 08:15 UTC. Read one issue
   labeled `agent-ready`, read a pinned main commit, request a bounded model
   proposal, validate JSON/Python syntax and path allowlist, and create one PR.
   Only `backend/catalog_sampling.py` can be proposed in this initial pilot.
   Two model calls maximum, one UTC-day slot and one open agent PR at a time.
   Main moving discards the proposal. Generated code is never imported or run
   by the credential-bearing controller. Existing PR CI runs it in a separate
   job without production secrets. An invalid proposal gets at most one format
   correction; provider errors are not retried.
3. **Monitor:** GitHub standard Linux runner at minute 17 each hour. No LLM key,
   GitHub write token or news service-role key. A restricted database function
   returns only news run status, latest visible event creation time and number
   of unresolved API reservations. It flags stale/incomplete/stuck work and
   unknown evidence. Incident rows are deduplicated and resolved when healthy.
   Findings are also printed as redacted JSON and make the workflow fail, so
   GitHub's configured workflow notifications can alert its owner. There is no
   Slack/email sender and no configured external notification subscription.

A separate **trusted release step within the development role**, checking hourly
but permitting at most one merge per UTC day with an approved monthly cost row, can
automatically squash only changes to the existing `COMMON` literal stop-word
set. AST comparison requires all executable code/imports to stay identical.
Other code repairs remain PR proposals. This narrow automatic-release scope is
intentional: passing tests alone is not proof arbitrary generated code is safe
to execute with production keys. Scope expansion needs additional verified
policies, not just a larger prompt or bypass token.

Release additionally requires the verified development App's bot identity,
same repository, `agents/` branch, current main as the single commit parent,
all required checks successful on the exact PR SHA, strict branch protection
including administrators, and server-side merge SHA matching. PR #27 is
explicitly excluded. Missing/paginated/unknown check data stops release. The
release App must not be a ruleset or branch-rule bypass actor. `NOTRON_AGENT_RELEASE_ENABLED`
defaults off independently of the other controllers. Render deployment is
subsequent to merge via `checksPass`; a merge response is never described as a
verified live deployment by this controller.

The monitor currently does not check the iOS app, public website rendering, or
Render control-plane deployment events. An unstarted news cron is detected by
the 26-hour stale-run threshold, not immediately. It writes an operational
incident queue; it does not automatically label incidents as safe coding tasks.
Maintainers label appropriate repository issues `agent-ready` for the developer.

## Durable monthly ledger

`schema.sql` is an unapplied bootstrap for a private `notron_agents` schema in
the existing PostgreSQL database. A separate exposed REST schema is unnecessary.
New roles have no table privileges, no production write access and no login by
default. Trusted functions serialize financial operations with an advisory
transaction lock. A function owner supplies narrowly scoped privileged access;
callers cannot edit limits, prices, balances, news rows or their reservations.
DB credentials stay in the controller process, never in a model prompt or file.

- Default off; each UTC month needs an explicitly approved cost row.
- Fixed $100 total maximum and $80 API sublimit. At least $20 is committed for
  all other costs. Use a larger reserve if taxes, existing storage overage,
  compute or other attributable costs require it. No transfer from news funds.
- Fixed $1 reservation before each text-only Standard request, committed before
  network access. Maximum two calls/day. At most $62 reserved for 31 days even
  if both calls consume the full bound every day.
- Model fixed to GPT-6.1 Terra; stateless input <=100k UTF-8 bytes, output <=6000
  tokens, no tools, no streaming, no automatic SDK/HTTP retries, no arbitrary
  caller-provided request options. Reviewed higher cache-write rate plus 10%
  margin prices <=200k reported input tokens and <=6000 output tokens below $1.
- Settle with usage only. Timeouts, missing usage and failed DB settlements keep
  reservations. ANY unresolved request blocks subsequent spending, even in a
  new month. A duplicate reservation never authorizes a second call. Duplicate
  identical settlement is idempotent. Over-envelope usage halts all agents.
- No automatic monthly budget renewal or price renewal. A DBA reconciles
  unresolved usage and approves the next month's actual non-API cost reserve.
  Pending requests must never be cleared just to restart jobs.

This bounds calls routed through this controller, not unrelated provider usage.
A separate model project/key and no sharing of that key are prerequisites. The
database role can settle calls and is therefore a trusted accounting credential;
it must not be exposed to generated code or generic shell tools. Production
network/credential isolation is part of the deployment boundary.

### Actual costs and unresolved accounting

Checked 2026-11-05: standard GitHub-hosted runners in public repositories have
no compute charge. The workflow and controller both reject a private repository.
No new worker, database plan, cache or artifact upload is proposed. Logs use
GitHub's normal workflow retention. Model calls use metered API billing; monitor
model-token cost is zero. Installation token generation is not a model call.

OpenAI lists Terra Standard $1/M input and $5/M output, with higher cache-write
and long-context rates. This implementation prices input at $2.50/M and output
at $5/M, plus 10%; its input cap stays below the long-context threshold. The
price expiry is controlled by the DBA and initially expired. API hard limits
should also be enabled, but their documented delayed enforcement is not an
exact invoice ceiling.

**Not verified against this account:** existing database storage/egress headroom,
taxes/currency conversion, GitHub paid account features, provider invoice usage,
and any costs outside the dedicated project. The $20 reserve is a proposed
allocation, not proof these costs are <=$20. If their worst case cannot be
bounded, do not approve the month or enable agents. The code intentionally
cannot bootstrap its own approval. Existing Render news compute remains in the
separate news budget. Additional Render builds caused by agent merges must be
included in the monthly non-API reserve or keep automatic release off.

Render also provides a pipeline-minutes spend limit. A verified $0 supplementary
pipeline budget is a way to prevent extra build-minute purchases: builds stop
when included minutes are exhausted. That setting is workspace-wide and can
affect other deployments, so it has NOT been changed. With automatic release
disabled, this pilot does not cause additional Render builds at all.

## Required external setup (none performed)

1. Review the schema locally. For Supabase, use its migration workflow and
   security advisors before applying a reviewed migration to the confirmed
   existing project; this bootstrap is not an already applied migration. The
   existing `public.notron_batch_runs` and `public.events(created_at,is_visible)`
   are required by `observe()`. Validate their names/permissions on the target.
2. Provision separate LOGIN credentials inheriting only `notron_agent_dev`,
   `notron_agent_monitor` or `notron_agent_release`. Audit inherited PUBLIC privileges on the existing
   database. Require TLS and store separate DSNs in separate GitHub environments.
   Do not use `postgres`, Supabase `service_role`, or an admin DB password.
3. Verify all attributable costs, a dedicated OpenAI project/key, hard limits
   and rate access. The key goes only in `notron-agent-development`. Approve the
   current month with an all-in `other_reserve` of at least 20,000,000 microdollars
   and a short price validity date. Enable the DB control row only after review.
4. Install two GitHub Apps on **only** `eren-bardak/notron`. Development needs
   Contents write, Pull requests write, Issues read. Release needs Contents
   write, Pull requests write, Checks read, Administration read (to verify branch
   protection); neither gets Actions write, Workflows write or bypass rights.
   Use distinct App credentials in `notron-agent-development` and
   `notron-agent-release`. Each workflow mints and later revokes a short-lived
   installation token; storing an expiring installation token as a permanent
   secret would not support unattended operation.
5. Protect main and require `Offline checks (no OpenAI calls)` and
   `Agent ledger integration`, with strict base freshness and no agent bypass.
   Protect controller/schema/workflow/dependency changes from the agent Apps.
   Require PRs for writes to main. Verify Render's EXISTING cron waits for CI
   and the test build command is effective. Repo auto-merge can remain disabled:
   the narrow controller calls the protected merge endpoint explicitly.
6. GitHub environment secrets: dev `AGENT_DATABASE_URL`, `AGENT_OPENAI_API_KEY`,
   `APP_PRIVATE_KEY`; monitor uses the existing `notron-agent-monitoring`
   environment with only its `AGENT_DATABASE_URL`; release its restricted
   `AGENT_DATABASE_URL` and `APP_PRIVATE_KEY`. Set each App's `APP_CLIENT_ID` environment variable. Set
   release `AGENT_BOT_LOGIN` to the verified DEVELOPMENT App login, not the release
   App login. Repo variables `NOTRON_AGENTS_ENABLED` and
   `NOTRON_AGENT_RELEASE_ENABLED` remain unset/false until ready.
7. After review/integration, copy the disabled template into `.github/workflows/`
   on main, then enable the selected flags. Do not add another news schedule.
   GitHub cron uses UTC, can be delayed, and public-repo schedules may be disabled
   after 60 days of inactivity. Confirm workflow enabled state and next observed
   scheduled runs; schedule files alone are not evidence of running agents.
8. Initial live validation, when later authorized: read-only monitor, one bounded
   developer request, PR checks, then a narrowly eligible release. Confirm exact
   Render SHA and next existing news run without launching a duplicate paid run.

Kill switches: clear repository flags and set database `control.enabled=false`.
These block new work; a request already sent may still be billed. Leave its
reservation intact and inspect before resuming.

Activation security hold: a downloaded development App private-key copy remains
in a read-only browser area and could not be removed. Before enabling agents,
assess who can access that copy, its retention and whether the key remains valid;
resolve its disposition through an explicitly authorized secure process. The
user instructed that the older development App key must not be deleted. Neither
development App key is changed or deleted by this workflow/environment fix.

## Local tests

```sh
python -m pip install -r agents/requirements.txt
python -m unittest discover -s agents/tests -p 'test_cloud_agents.py' -v
# Disposable local Postgres only. Test name/host checks reject a hosted DSN.
AGENT_TEST_DATABASE_URL='postgresql://postgres:local-pilot-only@127.0.0.1:55432/notron_agents_test?sslmode=disable' \
  python -m unittest discover -s agents/tests -p 'test_ledger_postgres.py' -v
```

Integration tests exercise real concurrent claims/reservations, restart
persistence, month rollover, duplicate settlement, cap exhaustion, uncertain
usage, kill switches and role privilege denial. HTTP/model/GitHub tests use
mocks; no funded call is needed. Existing backend tests remain unchanged.

Verified locally on 2026-11-05 with Python 3.12 and disposable PostgreSQL 17:
169 backend/release-policy tests and 31 controller/database tests passed (200
total). YAML parsing and `git diff --check` passed. All three controller CLI
roles returned `{"status":"disabled"}` with default settings. CI is configured
for Python 3.13, but no remote Actions run has been triggered in this task.
Logs: `/tmp/notron-final-backend-tests.log` and `/tmp/notron-cloud-tests.log`.
The local test database is not a Supabase production schema or paid service.

Sources checked:

- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://github.com/actions/create-github-app-token
- https://developers.openai.com/api/docs/models/gpt-6.1-terra
- https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform
- https://supabase.com/docs/guides/database/postgres/roles
- https://supabase.com/changelog (CLI v3 changes reviewed; no hosted CLI command used)
- https://render.com/docs/build-pipeline (pipeline spend limit; actual tier/rate needs Dashboard verification)

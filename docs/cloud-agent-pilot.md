# Nötron cloud agent pilot

Status: local, disabled pilot. No agents, schedules, services, deployments or
monthly billing controls have been activated. No change to PR #27.
Base: `6e064304532bc2cb501f314827f6f236dfc2eb32` (main, verified remotely).

## What is prepared

- The release checks run on every main push, PR and merge queue event, without
  path filters. The required job stays `Offline checks (no OpenAI calls)`.
- The existing Render cron proposes `autoDeployTrigger: checksPass`. Its build
  also runs offline tests, because Render accepts skipped/neutral checks and
  a build gate provides another barrier before new code can execute.
- Commit message tags no longer dispatch paid maintenance. Resume, supplement,
  background and card refreshes remain manual. Agents must never dispatch the
  legacy uncapped `full`, background or card refresh workflows.
- `agent_pilot.py` reads a local snapshot, reports failed/stale news and previews
  development budget eligibility. It never fetches data, calls an LLM, retries
  news, writes live state, merges or deploys. Missing/stale cost evidence stops
  the preview. It is NOT a billing enforcement gateway or atomic reservation.

Replay the synthetic fixture (not production evidence):

```sh
python backend/agent_pilot.py config/agent-pilot.example.json --now 2026-11-05T13:00:00Z
python backend/run_pipeline.py --mode test
```

## Three persistent roles after activation

Use server-side schedules, not a local computer or three chat subagents. The
lowest additional infrastructure cost is standard GitHub-hosted Linux runners
for development and monitoring, with the existing Render cron owning news.
These are proposed schedules, not newly registered schedules:

| Role | Schedule (UTC) | Work and credentials |
| --- | --- | --- |
| Development | `15 8 * * *`, one bounded run/day | Inspect approved backlog and monitor reports; reproduce one defect; edit a fresh branch; run offline tests; open a PR. A separate trusted controller may merge eligible PRs after current-head checks succeed. |
| News | Existing `0 7 * * *` | Existing `run_pipeline.py --mode economy`; publication remains automatic under current evidence gates, daily ledger and lease. No second news scheduler. |
| Monitoring | `17 * * * *`, no LLM in normal runs | Read deploy/build status, latest cron result, public publication freshness and redacted budget/lease status. Deduplicate incidents; send failures to the development backlog and a configured notification destination. Never retry paid news automatically. |

For development, implement a bounded model/tool loop in an ephemeral sandbox.
Install dependencies before isolating execution; expose only repository files,
offline test commands and patch tools. The model-facing sandbox must not receive
production credentials or credentials that bypass the budget gateway. Keep a
single development lease and one open agent PR per incident; skip if either is
already active. Persist run IDs, incident IDs, PR SHA, token usage and outcomes
outside the disposable runner. On restart, reconcile previous runs before retry.

The monitor needs adapters for Render, GitHub and a restricted read-only view of
news/budget status. A Render cron has no HTTP health endpoint; successful deploy
does not prove a successful news run. Check latest publication separately. The
pilot snapshot evaluator demonstrates these distinctions but does not provide
those authenticated adapters. Never give the monitor the existing database
service-role credential merely to read three operational fields.

## Release activation order

1. Confirm the Render workspace and exact existing cron service, connected GitHub
   repository/branch, current deploy and effective build command. This session's
   Render connector had no selected workspace, so live settings were not read.
2. Set the EXISTING service to wait for CI; verify the readback. Do not create a
   duplicate Blueprint service. Confirm whether the service is Blueprint-managed;
   editing this YAML alone does not update a manually configured service.
3. Protect main against direct agent pushes and require the exact offline check
   from GitHub Actions, with an up-to-date base/merge queue. Protect workflows,
   dependency definitions, release policy/tests, budget logic, schema and secret
   access from autonomous modification. A model must not be able to disable its
   own checks. GitHub repo metadata currently reports `allow_auto_merge=false`;
   enable auto-merge only as part of the later trusted release-controller setup.
4. Review this pilot and integrate it through normal checks. Verify a deliberately
   failing change cannot deploy, and that an approved passing SHA becomes the
   Render built SHA. Observe the next existing cron invocation; do not start a
   second paid invocation just to test deployment.
5. Provision restricted GitHub App credentials (branches/PRs for development;
   merge authority only in the trusted controller) and a dedicated model project
   behind the budget gateway. Add read-only monitoring access. Keep credentials
   out of model-generated scripts, repo files and report artifacts.
6. Implement and test the durable budget gateway, sandbox/model loop, read-only
   monitor adapters and incident persistence. Only then register the two new
   schedules, initially observation/PR-only. Automatic live changes are the
   requested end state, conditional on these technical gates, not another
   blanket approval request. Autonomous changes must not include migrations,
   billing/infra increases or edits to their own safety controls.
7. Verify schedule IDs, enabled state, last/next runs, role credentials, reports
   and kill switches after activation. Neither a YAML plan nor passing offline
   tests establishes that persistent agents are running.

## Monthly $100 additional limit

The user's $100/month is shared by development + monitoring and is additional
to the existing news envelope. Suggested allocation: $80 API maximum, $20 held
for infrastructure/storage/taxes/uncertainty. Unused news budget cannot fund
development. UTC calendar months are proposed for the new ledger; existing
news continues to use Europe/Istanbul days. Do not alter its $1.50 daily ledger,
30-minute lease, 19-minute internal deadline or 20-minute process timeout.

Pricing checked 2026-11-05:

- Standard GitHub-hosted runners for this currently public repository have no
  compute charge; larger runners are billable. Artifact/cache allowances are
  separate: use no new caches/artifacts initially and retain only small reports
  in existing storage. Re-evaluate cost if repository visibility changes.
- As one possible coding model, GPT-6.1 Terra Standard lists $1/M input and $5/M
  output tokens. A 100k input / 10k output call is $0.15 at those base rates;
  ten such calls/day for 31 days is $46.50. This is an illustration, not a quote
  or measured bill. Cache writes, long context, regional processing, tools and
  repeated context change costs. Do not enable paid web search, hosted shells
  or other priced tools without separate reservations.
- Monitoring can use deterministic checks and cost $0 in model tokens. Calling
  a model hourly solely to poll status needlessly spends budget.
- No new Render service is necessary in this design. Actual account bills,
  existing storage headroom, tax and provider usage have NOT been verified.

For a real enforceable application limit, implement a durable transactional
ledger outside writable agent code. Reserve a proven worst-case amount BEFORE
each API call and compute allocation; reject when charged + outstanding reserved
costs + the new reservation exceed either the $80 API envelope or $100 total.
Use integer currency units, unique request IDs, global concurrency protection,
bounded input/output/tool counts, no SDK retries, and price-version checks.
Keep timeout/unknown reservations until billing is reconciled. Fail closed if
the ledger, price configuration or current month is unknown. Never clear old
uncertain reservations on restart or authorize the same request twice.

Enable provider hard limits as defense in depth. OpenAI's current project guide
offers `Enforce a hard limit` but explicitly says enforcement is not instant and
spending may slightly exceed the configured amount. An alert alone does not
stop requests. A hard $100 all-provider bill cannot be promised from a prompt,
this snapshot preview, or provider alerts. The application gate can bound only
calls and infrastructure routed through it; separate credentials, accurate
maximum prices and all relevant costs are prerequisites. Leave agents disabled
until these are demonstrated. No actual monthly cap has been configured here.

## Validation and remaining blockers

Pilot uses Python 3.12 locally; production CI requests Python 3.13. Offline tests
patch dotenv loading and socket connections and strip live API credentials.
Baseline: 159 tests passed. Pilot: 168 tests passed (9 new policy/monitor tests).
All seven YAML files parsed, the synthetic preview returned
`execution_authorized: false`, and `git diff --check` passed. Dependencies were
installed in a temporary virtual environment; test execution made no live calls.
Before activation, run CI on 3.13 and perform provider-side Blueprint validation.
Public schema fetch from the shell returned HTTP 403; the current schema and
field documentation were readable through the web tool. Local YAML parsing and
release policy regression checks are available, but are not a replacement for
full platform validation or live settings readback.

Remaining: confirmed Render workspace/service; branch rules and merge setup;
dedicated API project, credentials and billing visibility; durable atomic
monthly ledger; production model/tool adapter; read-only monitor credentials
and adapters; incident store/notification destination; registered schedules.
These are implementation/configuration gaps, not an automatic approval denial.

## Sources

- https://render.com/docs/deploys
- https://render.com/docs/blueprint-spec
- https://render.com/docs/health-checks
- https://render.com/schema/render.yaml.json
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://developers.openai.com/api/docs/models/gpt-6.1-terra
- https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform

# Local Operations Runbook

Practical local-first runbook for daily Second Order operation.

## Daily Local Startup

Start backend:

```powershell
# From the repository root
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Start frontend in a second terminal:

```powershell
cd frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

Open:

```powershell
start http://127.0.0.1:3000
```

## Zero-Cost Smoke

These commands should not call Claude/OpenAI or trigger paid analysis.

Use the consolidated local smoke script first:

```powershell
# From the repository root
python scripts/no_paid_smoke.py --json
```

Inspect config health before enabling any paid path:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/config-health" |
  ConvertTo-Json -Depth 8
```

```powershell
# From the repository root

Invoke-RestMethod "http://127.0.0.1:8000/health" |
  ConvertTo-Json -Depth 6

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/data-quality" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/registry/diagnostics" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/registry/candidate-queue?limit=5&since_hours=72" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/movers/backfill-preview?limit=5&since_hours=72" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/events/1/similar?limit=5" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/validation-status-stats" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/reaction-profile-stats" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/track-record" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/major-skipped-headlines?limit=5" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/events?limit=5" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/events/1" |
  ConvertTo-Json -Depth 10
```

Frontend verification:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Validation Status Read Surfaces

`validation_status_v2` is live on archive read surfaces: event lists and event detail. The archive supports `validation_status_v2=validated|contradicted|unresolved|pending` filtering, and the frontend exposes the filter.

`reaction_profile_v1` is live on event detail when cached close windows exist. It is read-only and cache-backed; detail reads do not fetch live prices.

How to interpret:

- `pending`: young or incomplete evidence.
- `unresolved`: not enough usable evidence.
- `validated`: directional evidence majority supports the thesis.
- `contradicted`: directional evidence majority contradicts the thesis.

## Archive Backup

Dry run first:

```powershell
# From the repository root
python scripts/backup_archive.py --dry-run
```

Run backup:

```powershell
python scripts/backup_archive.py
```

Backups are local archive copies. Do not commit local database backups.

## CI Expectations

GitHub Actions runs on push and pull request. It installs backend and frontend dependencies, runs focused backend tests, then runs frontend typecheck and build.

Local pre-push check:

```powershell
# From the repository root

python -m unittest tests.test_diagnostics tests.test_logging_config -v
python -m unittest tests.test_headline_registry tests.test_backfill_paid_guard tests.test_market_context_consumer -v
python -m unittest tests.test_auto_backfill_ledger tests.test_auto_backfill_planner tests.test_auto_backfill_policy tests.test_auto_backfill_state -v
python -m unittest discover -s tests -p "test_events*.py" -v
python scripts/no_paid_smoke.py --json
python scripts/backup_archive.py --dry-run
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Paid-Analysis Guard

Default posture is no spend. Do not run paid candidate or backfill commands unless both are intentional:

- `ENABLE_PAID_ANALYSIS=true` is set in the operator environment.
- `confirm_paid=true` is present on the paid request.

Zero-cost preview is safe:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/movers/backfill-preview?limit=5&since_hours=72" |
  ConvertTo-Json -Depth 8
```

Paid single-candidate analysis example. Run only intentionally:

```powershell
$env:ENABLE_PAID_ANALYSIS = "true"

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/movers/backfill-candidate?headline=PASTE_HEADLINE_HERE&confirm_paid=true&since_hours=72" `
  -ContentType "application/json" `
  -Body "{}" | ConvertTo-Json -Depth 8
```

Paid recent backfill example. Run only intentionally:

```powershell
$env:ENABLE_PAID_ANALYSIS = "true"

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/movers/backfill-recent?dry_run=false&max_llm_calls=1&confirm_paid=true&limit=3&since_hours=72" `
  -ContentType "application/json" `
  -Body "{}" | ConvertTo-Json -Depth 8
```

## Auto-Backfill Operations

Auto-backfill is disabled by default and must stay disabled before demos unless the demo explicitly includes dry-run scheduler inspection. FastAPI lifespan wiring may start the dry-run scheduler only when both gates are explicit:

- `ENABLE_PAID_ANALYSIS=true`
- `ENABLE_AUTO_BACKFILL=true`

This still does not mean paid auto-backfill is implemented. The scheduler path is dry-run only: no Claude/API call, no paid candidate execution, and no ledger reservation.

Default local-safe config:

```powershell
$env:ENABLE_PAID_ANALYSIS = "false"
$env:ENABLE_AUTO_BACKFILL = "false"
$env:AUTO_BACKFILL_INTERVAL_HOURS = "6"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN = "2"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY = "4"
$env:AUTO_BACKFILL_MODEL = "claude-haiku-4-5-20251001"
```

Enable dry-run scheduler inspection intentionally:

```powershell
$env:ENABLE_PAID_ANALYSIS = "true"
$env:ENABLE_AUTO_BACKFILL = "true"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN = "1"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY = "2"

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/config-health" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/auto-backfill-status" |
  ConvertTo-Json -Depth 10

python scripts/no_paid_smoke.py --json
```

Emergency disable:

```powershell
$env:ENABLE_AUTO_BACKFILL = "false"
$env:ENABLE_PAID_ANALYSIS = "false"

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/config-health" |
  ConvertTo-Json -Depth 8
```

Restart the FastAPI app after setting `ENABLE_AUTO_BACKFILL=false` so any lifespan-managed dry-run scheduler is torn down.

Before a demo, do not:

- Start any background paid worker.
- Set `ENABLE_AUTO_BACKFILL=true`.
- Set `ENABLE_PAID_ANALYSIS=true` unless the paid action is the demo topic.
- Use paid POST routes to make the UI look populated.
- Leave daily caps unchecked.

## Auto-Backfill Foundation Checks

The auto-backfill dry-run foundation exists: config parsing, daily ledger,
candidate planner, policy decisions, local run-state helpers, dry-run runner,
dry-run scheduler skeleton, and lifespan plan checks. Diagnostics/status,
POST dry-run, and CLI dry-run surfaces are available and zero-cost. Lifespan
startup may wire a dry-run scheduler only when both env gates are true. There
is still no paid execution.

Do not enable a paid scheduler yet. Treat this as operator-visible planning
and safety plumbing only.

Run the pure foundation tests:

```powershell
python -m unittest tests.test_auto_backfill_ledger tests.test_auto_backfill_planner tests.test_auto_backfill_policy tests.test_auto_backfill_state tests.test_auto_backfill_runner tests.test_auto_backfill_scheduler tests.test_auto_backfill_dry_run_cli -v
```

Run no-paid smoke:

```powershell
python scripts/no_paid_smoke.py --json
```

Run dry-run scheduler smoke:

```powershell
python scripts/auto_backfill_scheduler_smoke.py --json
python scripts/no_paid_smoke.py --json
```

This smoke is fake/dry-run only. It checks the mocked lifespan scheduler path
and no-paid route inventory; it does not prove paid automation is safe and
does not mean paid scheduler execution is implemented. Expected fields:

- `mode` should be `dry_run_only` inside the scheduler smoke result.
- `scheduler_started` should be `true` only in the mocked/fake lifespan smoke.
- `ledger.used` should remain `0`.
- `spent_calls` should remain `0`.

Inspect config and status diagnostics:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/auto-backfill-config" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/auto-backfill-status" |
  ConvertTo-Json -Depth 10

python scripts/no_paid_smoke.py --json
```

The status route is a read-only GET. It must not reserve ledger calls:
repeat the call and confirm `ledger.used` is unchanged, `ledger.remaining`
does not decrease, and `state.last_spent_calls` is empty or `0`.

Run auto-backfill dry-run diagnostics:

```powershell
python scripts/auto_backfill_dry_run.py --json

Invoke-RestMethod -Method POST "http://127.0.0.1:8000/diagnostics/auto-backfill-dry-run" |
  ConvertTo-Json -Depth 10
```

Confirm no ledger calls were reserved by checking the dry-run response:
`spent_calls` should be `0`, `ledger.used` should stay unchanged, and
the status endpoint should not show a new paid run.

Dry-run interpretation:

- `selected_count` means the number of candidates the dry-run planner would
  choose under the current per-run and daily caps.
- `skipped` or `skip_counts` explains candidates not selected, such as
  `already_analyzed`, `expired_low_impact`, `skip_reason`,
  `run_cap_exhausted`, or `daily_cap_exhausted`.
- Dry-run output is planning only. It does not call Claude/API, does not
  mutate the ledger, and does not mean a scheduler or paid execution is
  running.

## Archive Rebuild Script — Safety Model

`scripts/rebuild_archive.py` is the operator-side tool for refreshing
archive overlays in bulk. The defaults are deliberately conservative:

```powershell
# Dry-run report — no DB writes. Safe to run any time.
python scripts/rebuild_archive.py

# Narrower dry-run slice (last 90 days, tariff family).
python scripts/rebuild_archive.py --family tariff --max-age 90

# Persist the changes only after reviewing the dry-run report.
python scripts/rebuild_archive.py --write --limit 50
```

What the script does and does not touch:

- **DB writes** — only when `--write` is passed. Default invocation
  is dry-run; no row is mutated.
- **LLM / paid analysis** — never. The composer chain is pure macro
  math over already-fetched bars; `ENABLE_PAID_ANALYSIS` has no effect.
- **Network / yfinance** — *not* fully isolated. The overlay composer
  pulls today's macro tape (^TNX, ^FVX, ^TYX, TIP, HYG, LQD, SHY)
  via `price_cache.fetch_daily_cached`. A warm cache serves from
  SQLite with no provider call; a cold cache will fetch the missing
  trailing window from the active provider. This applies to dry-run
  too — the validation pass runs the same composer with
  `persist=False`.

For a strictly offline dry-run, warm the price cache first (e.g. via
a recent market-context refresh) before invoking the script.

## Key-Rotation Reminder

- Keep `.env` local and uncommitted.
- Rotate Anthropic/OpenAI keys on a schedule and immediately after suspected exposure.
- After rotating, run zero-cost smoke first before any paid command.
- Never print or log API keys.

## Price-Cache Refresh

Run dry-run first before any paid auto-backfill work or cache write:

```powershell
python scripts/refresh_price_cache.py --json
```

Write mode is guarded and must be explicit:

```powershell
python scripts/refresh_price_cache.py --write --confirm --json
```

This does not spend LLM/API-analysis calls, but it may call the configured
market-data provider to fetch missing bars. Do not trigger it from a GET route,
page load, scheduler experiment, or demo flow. Run archive backup and local
preflight first, then review the dry-run plan before using write mode.

Recent outcome, 2026-05-06: guarded `auto_adjust=False` refresh improved
hydration (`hydrated_from_price_cache` 77, `reaction_profile_available_count`
49, `events_with_20d_signal` 31) with no paid/LLM paths. POT still warns as
likely delisted/no-data. Current no-forward-20d split: 53 too recent, 3
`auto_adjust` mismatches, 71 cache-window gaps, 0 likely delisted/sparse.

Focused no-forward-20d-gap refresh attempted 50 jobs but wrote 0 rows because
yfinance raised `OperationalError: unable to open database file`; coverage was
unchanged and no-paid smoke stayed green.

Stop condition: do not run further refreshes until the provider cache failure
is diagnosed.

Event-date dry-run checks:

```powershell
python scripts/event_date_backfill.py --json

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/event-date-backfill-candidates" |
  ConvertTo-Json -Depth 10
```

Current verified blocker count: 25 candidate legacy events / 126 ticker rows.
`no_event_date` currently blocks reaction hydration for those rows, and
`timestamp[:10]` is the only viable candidate source.

## Event-Date Backfill Write Mode

Write mode persists `event_date = timestamp[:10]` for events whose
`event_date` is NULL or empty. The writer is guarded:

- Only `event_date IS NULL OR event_date = ''` rows are touched — already
  dated rows are never re-dated.
- `BEGIN IMMEDIATE` serialises against any concurrent uvicorn writer on
  the same SQLite file.
- Malformed timestamps are skipped, not coerced; surfaces in
  `skipped_counts.timestamp_unparseable`.
- Idempotent: a second run writes nothing.
- No LLM, yfinance, market-data provider, `market_check`, `price_cache`,
  or FastAPI route is invoked.

**Operator sequence — backup → dry-run → write.** Stop and inspect at
each step; never invoke `--write --confirm` against the live archive
without first reviewing the dry-run plan from the same DB.

```powershell
# 1. Take a fresh backup. Never run write mode without one.
python scripts/backup_archive.py

# 2. Review the dry-run plan against the live DB.
python scripts/event_date_backfill.py --json
```

Inspect `total_candidates`, `ticker_rows_blocked`,
`projected_hydration_impact.ticker_rows_unblocked_by_write`, and
`skipped_counts`. If anything looks wrong, stop.

```powershell
# 3. Persist. Both flags are required together; either alone exits
#    non-zero with a guidance message and writes nothing.
python scripts/event_date_backfill.py --write --confirm --json
```

The write-mode JSON output adds `applied_count` and `applied_updates`
to the dry-run shape.

```powershell
# 4. Re-run the dry-run and confirm total_candidates dropped to zero
#    (or to the unparseable subset).
python scripts/event_date_backfill.py --json

# 5. Confirm the no_event_date hydration blocker drops on the live API.
Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/reaction-profile-blockers" |
  ConvertTo-Json -Depth 10
```

Rehearse against a backup copy first when in doubt — write mode accepts
`--db-path` so you can dry-run, write, and re-dry-run a copy without
touching the live `events.db`:

```powershell
Copy-Item backups\events-LATEST.db $env:TEMP\events_apply_test.db
python scripts/event_date_backfill.py --json --db-path $env:TEMP\events_apply_test.db
python scripts/event_date_backfill.py --write --confirm --db-path $env:TEMP\events_apply_test.db --json
python scripts/event_date_backfill.py --json --db-path $env:TEMP\events_apply_test.db
```

Operator validation (rehearsed against a `backups/events-*.db` copy):
pre-write `total_candidates=25` / `ticker_rows_blocked=126`;
`applied_count=25`; post-write dry-run `total_candidates=0`;
idempotent rerun `applied_count=0`.

Inspect:

- `provider_calls_estimate`: expected provider/network calls if write mode is
  used.
- `refresh_jobs`: count of ticker/date windows that would need cache refresh.
- `skipped_counts`: why candidates were skipped from refresh planning.

Before and after guarded write mode, inspect:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/reaction-profile-blockers" |
  ConvertTo-Json -Depth 10

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/price-cache-coverage" |
  ConvertTo-Json -Depth 10

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/reaction-profile-stats" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/track-record" |
  ConvertTo-Json -Depth 8
```

## Operator-Side Safety & Diagnostic Surface

The following operator tools are part of the durable safety surface.
None of them touch product code paths or call paid/provider/LLM seams.

- event-date backfill planner + guarded writer + CLI
  (`event_date_backfill.py`, `scripts/event_date_backfill.py`,
  `--write --confirm` required together for the writer).
- event-date diagnostics (`/diagnostics/event-date-backfill-candidates`,
  `/diagnostics/event-date-backfill-impact-preview`).
- repo hygiene guard (`.githooks/`, `scripts/repo_hygiene_check.py`).
- backup restore checker.
- no-paid smoke (`python scripts/no_paid_smoke.py --json`).

## Dirty-Tree Hygiene

Before committing:

```powershell
git diff --check
git status --short
```

Do not stage local DBs, backups, caches, logs, screenshots, build output, `.env`, or quarantine/design artifacts. Restore generated frontend build info after typecheck/build if it appears dirty:

```powershell
git restore -- frontend/tsconfig.app.tsbuildinfo
```

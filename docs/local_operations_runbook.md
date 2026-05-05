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

Auto-backfill is disabled by default and must stay disabled before demos unless the demo explicitly includes paid background work. It requires both gates:

- `ENABLE_PAID_ANALYSIS=true`
- `ENABLE_AUTO_BACKFILL=true`

Default local-safe config:

```powershell
$env:ENABLE_PAID_ANALYSIS = "false"
$env:ENABLE_AUTO_BACKFILL = "false"
$env:AUTO_BACKFILL_INTERVAL_HOURS = "6"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN = "2"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY = "4"
$env:AUTO_BACKFILL_MODEL = "claude-haiku-4-5-20251001"
```

Enable intentionally:

```powershell
$env:ENABLE_PAID_ANALYSIS = "true"
$env:ENABLE_AUTO_BACKFILL = "true"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN = "1"
$env:AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY = "2"

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/config-health" |
  ConvertTo-Json -Depth 8
```

Disable immediately:

```powershell
$env:ENABLE_AUTO_BACKFILL = "false"
$env:ENABLE_PAID_ANALYSIS = "false"

Invoke-RestMethod "http://127.0.0.1:8000/diagnostics/config-health" |
  ConvertTo-Json -Depth 8
```

Before a demo, do not:

- Start any background paid worker.
- Set `ENABLE_AUTO_BACKFILL=true`.
- Set `ENABLE_PAID_ANALYSIS=true` unless the paid action is the demo topic.
- Use paid POST routes to make the UI look populated.
- Leave daily caps unchecked.

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

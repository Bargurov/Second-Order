# Local Operations Runbook

Practical local-first runbook for daily Second Order operation.

## Daily Local Startup

Start backend:

```powershell
cd C:\Users\Bar\Desktop\geo_mechanism_project
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Start frontend in a second terminal:

```powershell
cd C:\Users\Bar\Desktop\geo_mechanism_project\frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

Open:

```powershell
start http://127.0.0.1:3000
```

## Zero-Cost Smoke

These commands should not call Claude/OpenAI or trigger paid analysis.

```powershell
cd C:\Users\Bar\Desktop\geo_mechanism_project

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
```

Frontend verification:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Archive Backup

Dry run first:

```powershell
cd C:\Users\Bar\Desktop\geo_mechanism_project
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
cd C:\Users\Bar\Desktop\geo_mechanism_project

python -m unittest tests.test_headline_registry tests.test_backfill_paid_guard tests.test_market_context_consumer -v
python -m unittest discover -s tests -p "test_events*.py" -v
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

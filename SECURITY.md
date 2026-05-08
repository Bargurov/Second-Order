# Security Policy

Second Order is local-first, but it can use paid LLM and market-data providers when explicitly configured. Treat secrets and paid actions as production-sensitive even during local development.

## Secret Handling

- Keep `.env` local only. Do not commit `.env`, local provider keys, tokens, database files, backups, or generated reports.
- Never paste API keys into chat, issue comments, logs, screenshots, docs, or test fixtures.
- Rotate any exposed key immediately, then remove the exposure from local history or public artifacts before pushing.
- Use dummy provider keys in CI and tests. Stable tests must not require real Anthropic, OpenAI, Polygon, yfinance, or other paid/network provider calls.
- Keep `.env.example` limited to placeholder values and safe defaults.

## Paid-Action Guardrails

- Paid analysis must be intentionally enabled with `ENABLE_PAID_ANALYSIS=true`.
- Paid candidate/backfill actions must require explicit request confirmation. Use `confirm_paid=true` only when the API spend is intentional.
- Background paid work must stay disabled unless both `ENABLE_PAID_ANALYSIS=true` and `ENABLE_AUTO_BACKFILL=true` are explicit operator choices.
- FastAPI lifespan wiring may start the auto-backfill scheduler only when both gates are true, and the current scheduler path is dry-run only: no paid execution, no provider call, and no ledger reservation.
- Paid work must never be triggered from GET routes, page load, refresh, diagnostics, preview endpoints, or background polling without both gates.
- Daily paid-call caps such as `AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY` must remain enforced and low.
- Keep `BACKFILL_DRY_RUN_DEFAULT=true` and `MAX_BACKFILL_LLM_CALLS` low for local work.
- Preview and diagnostics GET routes are zero-cost inspection surfaces. Examples include `/movers/backfill-preview`, `/registry/diagnostics`, and `/registry/candidate-queue`.
- Do not add UI or scripts that call paid endpoints on page load, refresh, or background polling.
- Emergency disable for auto-backfill is `ENABLE_AUTO_BACKFILL=false` followed by an app restart.

## Before Public Pushes

Run a quick safety check before pushing:

```powershell
git status --short
git diff --check
git ls-files .env .env.* frontend/.env frontend/.env.*
python scripts/repo_hygiene_check.py --json
python scripts/no_paid_smoke.py --json
```

Confirm before pushing:

- `.env` and provider keys are not tracked.
- No local SQLite databases, backups, caches, logs, screenshots, generated reports, or sandbox artifacts are staged.
- No local absolute paths or private workflow notes were added to public docs.
- Public docs describe validation methodology at a high level only, without exposing private datasets or generated artifacts.
- Public docs do not claim full backend or frontend test-suite status unless those suites were actually run for the change.
- Repo hygiene and no-paid smoke checks pass with dummy or absent provider keys.
- Paid paths remain guarded by `ENABLE_PAID_ANALYSIS` and `confirm_paid=true`.

## Reporting

For security concerns, open a private disclosure channel with the maintainer rather than filing public details. Include the affected file, route, or workflow and enough reproduction detail to verify safely without exposing secrets.

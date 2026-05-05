# Infrastructure Risk Checklist

Short operational checklist for Second Order infrastructure risks.

| Area | Status | Practical next check |
| --- | --- | --- |
| CI | done | GitHub Actions runs focused backend tests, Phase 0 hardening checks, backup dry-run, frontend typecheck, and frontend build. |
| Key rotation | done | Current keys were rotated/confirmed. Keep `.env` local and repeat rotation on a schedule or after suspected exposure. |
| Archive backup command | done | `scripts/backup_archive.py` supports dry-run and local backup. Next: define retention and restore-drill cadence. |
| Paid-action guards | done | Paid backfill has dry-run defaults, explicit limits, confirm guards, and the server-side `ENABLE_PAID_ANALYSIS` kill switch. |
| Structured logging | done | Shared structured logging setup and formatter tests are committed. |
| Config health diagnostics | done | `/diagnostics/config-health` reports safe provider/backfill config state without exposing secret values. |
| Data-quality diagnostics | done | Registry diagnostics, candidate queue, archive/degraded filters, and market-context metadata have zero-cost diagnostics paths. |
| Validation-status reads | done | `validation_status_v2` is live on `/events?limit=5`, `/events/{id}`, and `/diagnostics/validation-status-stats`; interpret pending as young/incomplete, unresolved as insufficient evidence, and validated/contradicted as directional majority outcomes. |
| Archive quality filtering | partial | Backend filters exist, but archive filtering remains backend-only/in progress until the frontend path is verified. |
| Local runbook | done | Daily startup, zero-cost smoke, backup, paid-guard, key-rotation, and dirty-tree hygiene commands are documented. |
| Schema migrations | planned | Migration discipline is documented, but no schema version table, migration runner, or rollback process exists yet. |
| Deployment readiness | not started | Local-first run path is stable; hosted deploy plan, secrets handling, observability, and recovery runbooks are not defined. |

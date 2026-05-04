# Infrastructure Risk Checklist

Short operational checklist for Second Order infrastructure risks.

| Area | Status | Practical next check |
| --- | --- | --- |
| CI | done | GitHub Actions runs focused backend tests plus frontend typecheck/build on push and pull request. Watch the first remote run for environment drift. |
| Key rotation | partial | Secrets stay local and CI uses dummy keys, but there is no rotation cadence or leak-response checklist yet. |
| Archive backups | partial | Backup script and ignore rules exist. Next: fix/land backup tests, define cadence, retention, and restore drill. |
| Paid-action guards | done | Paid backfill has dry-run defaults, explicit limits, confirm guards, and the server-side `ENABLE_PAID_ANALYSIS` kill switch. |
| Structured logging | partial | Structured logging work is in progress locally; finish commit/tests before treating it as an operational baseline. |
| Schema migrations | partial | Migration discipline is planned, but no schema version table, migration runner, or rollback process exists yet. |
| Data-quality diagnostics | partial | Registry diagnostics, candidate queue, degraded/archive filters, and market-context metadata exist. Next: regular smoke pass for stale/frozen/provider states. |
| Deployment readiness | not started | Local-first run path is stable; hosted deploy plan, secrets handling, observability, and recovery runbooks are not defined. |

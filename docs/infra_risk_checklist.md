# Infrastructure Risk Checklist

Short operational checklist for Second Order infrastructure risks.

| Area | Status | Practical next check |
| --- | --- | --- |
| CI | done | GitHub Actions runs focused backend tests plus frontend typecheck/build on push and pull request. Watch first remote run for environment drift. |
| Key rotation | partial | `.env` stays local and docs use dummy CI keys, but there is no formal rotation cadence or leak-response checklist yet. |
| Archive backups | not started | Define SQLite/archive backup location, cadence, retention, and restore drill. |
| Paid-action guards | done | Backfill defaults dry-run, requires explicit limits, and multi-call paid runs require confirmation. Keep paid endpoints off page-load paths. |
| Data-quality diagnostics | partial | Registry diagnostics, candidate queue, degraded/archive filters, and market-context metadata exist. Add a regular smoke pass for stale/frozen/provider states. |
| Schema migrations | partial | Schema changes are handled in code/tests, but there is no migration log, version table, or rollback procedure. |
| Deployment readiness | not started | Local-first run path is stable; hosted deploy plan, secrets handling, observability, and recovery runbooks are not defined. |

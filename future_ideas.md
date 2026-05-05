# Future Roadmap

This file is for deferred product ideas only. Shipped work, active blockers,
verification tasks, and current sprint chores belong in README, runbooks, tests,
or issue-sized plans instead.

## Phase 1 Candidates

These are the next foundation-validation candidates. Keep each scoped, tested,
and grounded in representative archive data before changing defaults.

- Build a magic-number inventory and empirically validate threshold values before changing them.
- Design and implement `validation_status` so market validation can distinguish pending, market-checked, degraded, clean, and unresolved states without overclaiming.
- Add reaction profiles: peak move, time-to-peak, fade/hold behavior, and mean-reversion window.
- Add archive aggregate stats for event cohorts, mechanism families, validation outcomes, and follow-through behavior.
- Introduce schema migration discipline: schema version, migration script, backup before migration, rollback note, and migration tests.

## Deferred Intentionally

These are useful, but not the next task unless Phase 1 evidence says otherwise.

- Improve Market Context Section C preview-candidate copy and compact detail views.
- Add explainability drawers for stale, frozen, degraded, low-information, and unavailable provider states.
- Expand Archive dashboards for theme trends, regime drift, cascade navigation, and historical mechanism performance.
- Add stricter multi-provider checks for benchmark market prints and suspicious-data quarantine.
- Build maintained feed, ticker, watchlist, and taxonomy registries with reviewable diffs.
- Expand non-US market, macro, FX, rates, sector, policy timing, and vulnerability-profile coverage.
- Add a ticker graveyard for delisted, renamed, invalid, duplicated, or provider-broken tickers.
- Build archive learning as retrieval and calibration: past headlines + mechanisms + market outcomes -> similar-case retrieval -> analog confidence.
- Add scenario packs, cohort research runs, and regime-conditioned performance studies after aggregate stats exist.
- Add frontend regression coverage for saved-study replay, portfolio response shapes, Market Context sections, policy tracker rows, and degraded/empty states.
- Add future code splitting for the non-blocking Vite chunk-size warning.
- Add memoization only if Archive, Portfolio, Movers, or Research pages become measurably sluggish.

## Do Not Start Before Prerequisites

These need stronger foundations first, so keep them out of near-term planning.

- Charts and richer event-reaction timelines: wait for reaction profiles and aggregate stats.
- Tagging expansion and broader taxonomy UX: wait for validated mechanism/status semantics.
- Scheduler, background jobs, and replay orchestration: wait for schema migration discipline and backup/restore confidence.
- Deployment profiles and hosted readiness: wait for migration discipline, config-health gates, and documented ops paths.
- Telegram/WhatsApp/OpenClaw delivery expansion: wait for stable app routes, data-quality diagnostics, and delivery-specific product requirements.
- PostgreSQL migration: wait until archive size, multi-user workflows, or deployment requirements justify it.
- WebSockets or real-time UI updates: wait until refresh semantics and background jobs are settled.
- Team/share workflows, roles, audit trails, and enterprise templates: wait until the local-first single-user product is stable.

# Future Roadmap

Later-stage backlog only. Shipped work, active blockers, and immediate
verification tasks do not belong here. Promote an item only when it has a clear
product use case, owner, and validation path.

## Checkpoint - 2026-05-04

Completed phase: headline registry, low-impact expiry, archive mock filtering,
paid-backfill guard, zero-cost backfill preview, and Section C live mover
pipeline.

Accepted limitations:

- Weekly needs real 5d returns.
- Persistent remains high-impact/supportive only.
- Vite chunk-size warning is non-blocking.
- Preview candidate UI needs later UX polish.

## Backlog Rules

- Do not add completed Engine v1, backend productization, or frozen UI-slice work back into this file.
- Do not use this file for active bugs, current sprint tasks, or required verification commands.
- Keep tunable numeric parameters tied to empirical validation before changing defaults.
- Non-fatal bad ticker and yfinance warnings should be logged in a ticker registry or graveyard, not treated as fatal regressions.
- Prefer product-useful upgrades over architecture for its own sake.

## 01 UI/product polish

### UI / UX / Explainability

- Improve Market Context Section C preview-candidates UI.
- Make preview copy clearer and less technical, especially the "Preview only - no Claude/API spend" message.
- Improve labels for `would_call_llm`, `already_analyzed`, and `skip_reason`.
- Consider a collapsed/detail view explaining why each candidate would or would not be analyzed.

- Add expandable explanations for Market Context sections A and B: what each metric means, why the current read appears, which inputs drove it, and what would make it change.
- Add explainability drawers for provider degradation states so users can distinguish unavailable, stale, degraded, frozen, and low-information reads.
- Continue Market Context density/readability polish, especially mover cards, compact metric cards, and mobile scan speed.
- Improve Event Detail collapsibility so proof, falsifiers, thesis content, and market validation stay primary while Engine Reference remains available.
- Convert the Thesis Module into a reusable component rather than a primary navigation destination.
- Add advanced Archive dashboards for theme trends, regime drift, cascade navigation, and historical mechanism performance.
- Add research-only watch panels, saved-study views, and comparison sessions for power users.
- Build visual QA rules for stale, frozen, degraded, low-information, and unavailable states so they remain distinct.
- Add a mechanism graph navigator: headline -> mechanism -> affected assets -> proof/falsifier -> related historical analogs.

## 02 Frontend QA/regression coverage

- Add frontend regression tests for `portfolio_view` saved-study render and replay.
- Add frontend contract tests for `/portfolio` bare-list responses versus filtered `{ items, counts }` envelope responses.
- Add a bottom-nav label-size guard so user-critical mobile text does not fall below 11px.
- Add Market Context render tests confirming sections A/B/C/D are present and snapshot degradation does not hide valid engine sections.
- Add Headlines Policy Tracker tests confirming top active policies and overflow row render correctly.
- Add design-source guardrails so future UI work uses `repo/design/` and does not reference stale Stitch or old design files.
- Add frontend smoke coverage for low-information, stale, frozen, degraded, and empty states.
- Add future code splitting for the non-blocking Vite chunk-size warning.
- Memoize heavy UI selectors if Archive, Portfolio, Movers, or Research pages become sluggish.

## 03 Data/provider reliability

- Add stricter multi-provider verification for benchmark markets, with explicit suspicious-print quarantine instead of trusting one provider.
- Build a versioned feed, ticker, and watchlist registry with ownership, tests, and reviewable diffs.
- Expand non-US market, macro, FX, rates, and sector coverage where current proxy sets are too US-centric.
- Expand official macro-release support with more release calendars, revisions, historical surprises, and country-specific datasets.
- Expand policy timing registry coverage for announced, effective, review, expired, delayed, and withdrawn policy phases.
- Expand maintained country and region vulnerability profiles for reserves, import dependence, funding mix, energy exposure, and external-debt pressure.
- Add provider freshness checks for ingest lag, stale caches, snapshot failures, and missing benchmark data.
- Add feed-quality controls to reduce oil/war overdominance and improve source diversity.
- Improve headline grouping and de-duplication across syndicated or repeated stories.
- Add official project/program context for infrastructure, financing, reconstruction, defense, and industrial-policy shocks.

## 04 Market data QA / ticker graveyard

- Maintain a ticker graveyard for delisted, renamed, invalid, duplicated, or provider-broken tickers.
- Add replacement mappings and provider-specific aliases where possible.
- Log non-fatal yfinance warnings without breaking eval or app runs.
- Track suspicious market prints caused by stale closes, splits, bad volume, holidays, illiquid assets, or temporary provider errors.
- Add coverage heatmaps showing which watchlists, ETFs, countries, sectors, and mechanisms have weak data support.
- Add tests that ensure unknown or unmapped tickers cannot become primary validation assets by default.
- Add broader sector-specific proxy modules after core market data quality is stable: semiconductors, energy, defense, shipping, banks/credit, industrial policy, and commodities.

## 05 Archive learning / memory layer

- Build an archive learning layer: past headlines + mechanisms + market outcomes -> similar-case retrieval -> analog confidence -> prompt/scoring improvements.
- Keep this as retrieval, calibration, and scoring support. This is not training a custom LLM.
- Store mechanism signatures, regime context, asset reactions, validation outcomes, proof/falsifier paths, and decay behavior in a queryable memory layer.
- Use similar-case retrieval to improve analog selection, confidence calibration, mover persistence scoring, and prompt grounding.
- Add archive-native clustering by transmission path so related events group by mechanism, not surface wording.
- Add side-by-side analog research views for comparing cohorts, regimes, and outcome paths.
- Add drift monitoring so old analogs are down-weighted when provider coverage, market structure, or policy regime changes.

## 06 Research / quant validation

- Build cross-event graph and cascade modeling with explicit parent/child links, spillover edges, and decay rules.
- Add mechanism-family calibration by regime and asset class instead of relying on one global confidence layer.
- Build archive-native cross-event correlation studies across sectors, countries, and mechanism families.
- Add reusable scenario packs for recurring shock types such as oil spikes, tariff cycles, funding squeezes, ceasefires, export controls, and sanctions.
- Add batch research runs that score persistence, repricing path, follow-through, and falsification across event cohorts.
- Add true yield-curve, breakeven, FX, and cross-asset rate math where proxy methods are still insufficient.
- Add event reaction profiles: peak move, time-to-peak, fade/hold behavior, and mean-reversion window.
- Add regime-conditioned performance studies showing which mechanism families work differently in calm, inflation, funding-stress, and risk-off regimes.
- Validate scoring thresholds, decay windows, similarity cutoffs, confidence bands, stale-event windows, and mover qualification rules empirically before changing defaults.

## 07 Database / infra / ops

- Migrate from SQLite to PostgreSQL when archive size, multi-user workflows, or deployment requirements justify it.
- Add proper schema migrations instead of ad hoc SQLite table evolution.
- Add materialized views for expensive Archive, Portfolio, Track Record, and Research queries if latency grows.
- Add background-job orchestration for long-running ingest, replay, export, archive rebuild, and cache refresh tasks.
- Add reproducible backfill and archive-rebuild tooling with validation reports before write-back.
- Add health dashboards and alerting for ingest lag, provider failures, cache freshness, analysis error budgets, and API route degradation.
- Add deployment profiles for local development, hosted app deployment, and OpenClaw delivery.
- Add secrets/config hygiene checks so `.env` stays local and required keys are validated without being exposed.
- Clean stale temp directories, obsolete test artifacts, and old generated files after the relevant smoke-test slice is frozen.

## 08 Enterprise product upgrades

- Add WebSockets or server-sent events for real-time UI updates when headlines refresh, provider status changes, movers update, or analysis streams complete.
- Integrate TradingView Lightweight Charts for event-reaction timelines, benchmark-relative moves, regime overlays, and proof/falsifier visualization.
- Build custom alerting for saved studies, persistent movers, falsifier triggers, provider degradation, policy status changes, and high-conviction headline clusters.
- Add team/share workflows for saved studies, export packs, annotated event reads, and analyst-style research notes.
- Add role-aware workspaces, audit trails, and saved research templates if the product moves beyond single-user local workflows.
- Add export-pack templates for investment committee memos, risk briefs, policy watch notes, and portfolio-review packets.

## 09 OpenClaw delivery — keep this last

- Add scheduled daily brief delivery once app routes and data quality are stable.
- Add alert routing for movers, falsifiers, refresh-needed events, stale provider states, policy status changes, and saved-study changes.
- Add conversational retrieval for questions such as:
  - "Show me active sanctions events still moving markets."
  - "What changed in credit stress this week?"
  - "Which policy events are awaiting review or expiry?"
- Add Telegram/WhatsApp delivery via OpenClaw after the core app is stable.
- Add saved-study sharing and research-note delivery workflows for users who want output outside the app.

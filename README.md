# Second Order

Second Order is a local-first geopolitical and macro research app. The current
product is a FastAPI backend with two maintained client surfaces:

- a React app for live inbox review, progressive analysis, archive/backtest work, and export
- a Telegram bot for direct headline analysis, `/brief`, and optional scheduled delivery

The system is designed for analyst workflows: ingest live headlines, cluster
overlapping coverage, run classify -> analysis -> market stages, layer in macro
and market-context overlays, save the result locally, and revisit dated events.

## Current Status

The tracked evidence track is complete through Phase 4. The cohort-wide
methodology and the Phase 1–4 arc are documented at
[`demo_artifacts/section_c_v2/phase_evidence_methodology.md`](demo_artifacts/section_c_v2/phase_evidence_methodology.md)
and
[`demo_artifacts/section_c_v2/phase_history.md`](demo_artifacts/section_c_v2/phase_history.md).

- **Phase 1** — a five-row freeze-candidate cohort
  (WHR / TXT / FSLR / RIO / LITE) is tracked at
  `demo_artifacts/section_c_v2/freeze_candidate_evidence.json`. Each row
  carries a pre-registered canonical test at the claimed horizon h = 1
  with a BH-adjusted q-value frozen at the original five-row Phase 1
  denominator. Phase 1 q-values are never recomputed against any later
  scope.
- **Phase 2** — a closed five-row BH/FDR pool
  (BA / ALB / NVDA / AMAT / CF) is tracked at
  `demo_artifacts/section_c_v2/phase2_pool_v1.json`. BA, ALB, and NVDA
  are BH/FDR discoveries at the q ≤ 0.05 threshold. AMAT and CF did not
  pass the screen but remain denominator members per the closed-pool
  policy. Phase 2 is a separate FDR scope from Phase 1.
- **Phase 3** — three schema validators
  (`scripts/validate_freeze_candidate_artifact.py`,
  `scripts/validate_phase2_pool.py`,
  `scripts/validate_rejection_log_summary.py`), the `cohort_evidence`
  loader, the `evidence_layer` section of
  `scripts/project_health_check.py`, and a CI gate in
  `.github/workflows/ci.yml` protect the tracked artifacts from silent
  regression. Deferred methodology lessons (CENX, NUE, NOC) are
  recorded in
  `demo_artifacts/section_c_v2/rejection_log_summary_v1.json`.
- **Phase 4** — `GET /evidence/summary` exposes the tracked evidence
  layer as a read-only JSON view. The route reads only from
  `demo_artifacts/section_c_v2/`; it does not read local operator
  artifact paths, the events database, the price cache, any provider,
  or the network. It preserves Phase 1 and Phase 2 as separate FDR
  scopes.

Phase 0 process hardening (CI hygiene checks, key rotation guidance,
archive backup command, paid-server guard, structured logging, config
health diagnostics, data-quality diagnostics) and the wider app's
existing Phase 1 read surfaces (archive/detail `validation_status_v2`,
`reaction_profile_v1` hydration, zero-cost diagnostics for
`/diagnostics/track-record`, `/diagnostics/major-skipped-headlines`,
and `/diagnostics/reaction-profile-stats`) remain in place and are
not affected by the tracked-evidence track.

## Event-Study Compute-Readiness Contract

The backend route `GET /events/{event_id}/event-study` is a wider-app
archive route, separate from the closed tracked-evidence Phase 1 and
Phase 2 FDR pools.

`archive-ready` is the broad coverage gate from
`scripts/stat_validation_readiness_report.py`: the event has an
`event_date`, a primary ticker, enough cached primary-ticker history,
forward cache coverage at the 1d / 5d / 20d horizons, and SPY benchmark
proxy coverage. It is a data-coverage denominator, not a promise that
the event-study engine can score the row.

`event-study compute-ready` is stricter. It reuses
`event_study_validation.build_event_study_validation`, the same gate
behind `GET /events/{event_id}/event-study`. The gate requires a
contiguous intersected asset-plus-SPY window, enough SPY pre-event
history for the estimation window, and an engine-usable volatility
estimate. A compute-ready row can return per-horizon abnormal return,
SAR, and CAR point estimates.

`matched adjusted basis` means the asset and SPY benchmark both use
`auto_adjust=True` price-cache rows for the full window consumed by the
event-study engine. As of the current local archive check, every
compute-ready event sits on matched adjusted basis, so no mixed
adjusted/raw basis caveat is attached to the compute-ready set.

Current verified counts from
`python scripts/stat_validation_readiness_report.py --json --limit 0`:

- total archive events: 157
- archive-ready events: 52
- event-study compute-ready events: 44
- matched adjusted-basis events: 44
- cross-flag caveats: 0

Compute-ready means SAR/CAR point estimates are computable. It does not
mean cohort-level statistical inference is available for a single
event. Single-event output has `n=1`, so CI, p-value, and FDR are not
available on the event-detail route; those remain cohort-level
statistics.

Compute-ready rows are also not automatically valid cohort
observations. Across the matched compute-ready set, cohort-level
inference is currently on hold, and the block is independence and
labeling rather than the event-study engine: the rows are concentrated
in a few primary tickers and one clustered macro event with overlapping
forward windows, and `mechanism_family` is unpopulated, so they are not
independent observations. Running cross-sectional CI, p-value, or FDR
over them would overstate precision. The criteria a future cohort phase
must meet are recorded in `stats/METHODOLOGY.md` ("Cohort inference —
currently blocked"). This decision does not change the closed Phase 1 or
Phase 2 FDR denominators.

Eight archive-ready rows remain frontier cases waiting for forward
close maturation. Most other non-ready archive rows are structurally
blocked, mainly by missing primary tickers or insufficient pre-event
estimation history. These archive event-study counts do not change the
closed Phase 1 or Phase 2 FDR denominators.

### Coverage report — per-event AR/SAR/CAR across the archive

`scripts/event_study_coverage_report.py` makes the engine's reach
auditable in one place. It loops `build_event_study_validation` over every
analysis-stage archived event (read-only — plain `SELECT`s, no provider,
no network, no DB write) and surfaces, for each compute-ready event, the
per-horizon (1d / 5d / 20d) `abnormal_return`, `sar`, and `car` point
estimates; for every other event it lists the `blocking_reasons` and no
estimates.

It is **not a new FDR pool** and never reads, modifies, or reopens the
closed Phase 1 / Phase 2 pools (`demo_artifacts` / `cohort_evidence` are a
separate scope). It reuses the same gate as the event-detail route, so its
`event_study_available` count matches the readiness report's
`event_study_compute_ready` exactly (44 = 44).

**Single-event output is point estimates only.** At `n=1` there is no
confidence interval, no p-value, and no FDR; the report makes no
`confirmed` / `validated` / "significant" claim. Each JSON payload carries
an explicit `non_claims` block stating this.

Current live coverage:

- event_study_available: 44
- insufficient_data: 113
- curated_intake excluded: 1
- auto_adjust basis: matched 44, cross_flag 0

The dominant blocker is `no_primary_ticker` (84) — a **coverage gap, not a
statistics failure**: those events never reach the engine because they
carry no primary ticker. The next blockers are forward-cache gaps
(`missing_forward_cache_20d` 20, `missing_forward_cache_5d` 10),
`insufficient_estimation_window_primary` (9), and
`no_contiguous_aligned_window` (8). None is an engine error; each is a
data-coverage or contiguity precondition.

```powershell
python scripts/event_study_coverage_report.py --json
```

### Event detail — the `event_study` block on `GET /events/{id}`

`GET /events/{id}` carries an additive top-level `event_study` block,
populated by the same `build_event_study_validation` gate as the standalone
`GET /events/{id}/event-study` route — the two return the **identical**
payload for a given event, so detail consumers need no second round-trip.

- **Compute-ready events** carry the per-horizon (1d / 5d / 20d)
  `abnormal_return`, `sar`, and `car` point estimates (alongside
  `raw_return`, `benchmark_return`, `estimation_window_used`, and
  `auto_adjust_basis`).
- **Not-ready events** carry `status = "insufficient_data"` and an explicit
  `blocking_reasons` list — never point estimates, never a raw-return
  fallback.

The block is **additive**: it changes nothing that already shipped.
`validation_status`, `validation_status_v2`, the track record, the movers
surfaces, and the UI are all unchanged — `event_study` is a new sibling key
alongside `validation_status_v2` and `reaction_profile_v1`.

It stays **point-estimate-only**. At `n=1` there is no confidence interval,
no p-value, and no FDR; the payload makes no `confirmed` / `validated` /
"significant" claim (the gate marks `cross_sectional_inference.available =
false` and lists those terms under `claims.not_claimed`). It never reads,
modifies, or reopens the closed Phase 1 / Phase 2 FDR pools.

**`GET /events/{id}` is read-only.** Its `mover_context` block reads the
cached mover slices without rebuilding or persisting them, so a detail
request never writes `movers_cache` (or anything else) to the database.

## Curated Intake — Source-Anchored Archive Stubs

Operator-curated events enter the archive through a guarded intake path
(`scripts/curated_event_intake_apply.py`), which writes one `events` row
plus one matching `event_provenance` row from a hand-authored YAML
worksheet.

A `curated_intake` row is a **source-anchored archive stub, not analyzed
evidence.** It records that a real, primary-source event happened and
where it came from. It carries no market check, no scored outcome, and no
validated thesis; it is stamped `stage = "curated_intake"`,
`persistence = "unscored"`, and must never be read as a confirmed
mechanism or a trading signal. The curated `predicted_direction` is a
falsifiable hypothesis recorded for later checking and is deliberately
**not** persisted, so no directional framing reaches any surface.

**First live curated row** (written 2026-06-01):

- `event_id` 293
- Federal Reserve FOMC statement, April 29, 2026 — official press release
  `monetary20260429a.htm`, released 2:00 p.m. EDT
- `mechanism_family` `policy_surprise` (the canonical family; the narrower
  "monetary policy rate decision" is descriptive only)
- `provenance_status` `source_anchored` (both `source_url` and
  `source_published_at` are recorded)

**Denominator policy.** Curated_intake rows are counted as **archive
inventory** but excluded from every **outcome / readiness / claim**
denominator, so they can never inflate or dilute a research finding:

- The **raw archive count includes** curated_intake rows (e.g.
  `events_by_stage`; the default `GET /events` listing).
- **Readiness, track-record, and validation-status exclude** them.
  `db.NON_ANALYSIS_STAGES` is the single source of truth for the filter.
- Each excluding surface **discloses** the omission via a
  `curated_intake_excluded_count` field — the rows are separated, never
  silently hidden.

**Backup policy.** A live intake write requires the full guarded triple —
`--write`, `--confirm`, and `--backup-path` pointing at a restore point
distinct from `events.db`. The writer snapshots the database before any
mutation, runs all inserts in one transaction that rolls back on error,
and is idempotent by `source_url`. The backup `.db` and `events.db`
itself are untracked (gitignored) and are never committed.

```powershell
python scripts/curated_event_intake_apply.py `
    --yaml examples/curated_events.candidate.yaml `
    --write --confirm --backup-path backups/pre-intake.db --json
```

**Current live counts** after the first curated write:

- raw events: 158
- readiness `total_events`: 157 (curated_intake excluded)
- `curated_intake_excluded_count`: 1

## Price-Provider Provenance — Where a Cached Bar Came From

The price cache (`price_cache`) now records **which market-data provider
served each bar** in a nullable `source_provider` column, read through the
single helper `db.derive_price_provider`. This is distinct from event
provenance (below) and never affects whether a bar is used — it only
records origin.

**`legacy_unknown` is a provenance gap, not bad data.** When
`source_provider` is NULL or blank, `db.derive_price_provider` returns
`legacy_unknown`. That means exactly one thing: the provider was **not
recorded at write time**. It is **not** a claim that the bar is wrong,
stale, or invalid — these are real cached closes that simply predate
provider stamping (or came from a writer that does not stamp yet).

**Current live coverage is 100% `legacy_unknown`, and that is expected,
not a regression.** The cache predates the stamping path, and no refresh
or backfill has been run to repopulate it (none is run casually). As of
2026-06-01:

- total cached bars: 18,630
- distinct providers: 1 (`legacy_unknown`)
- `legacy_unknown`: 18,630 bars across 155 tickers
- basis split: 9,274 raw (`auto_adjust=0`) / 9,356 adjusted (`auto_adjust=1`)
- date range: 2017-07-07 → 2026-05-29

**Future canonical fetches stamp the provider.** Bars pulled through the
canonical read-through path (`price_cache.fetch_daily_cached`) are stamped
with the resolved provider identity:

- `yfinance` — the default provider
- `polygon` — when configured via `MARKET_DATA_PROVIDER=polygon`
- `fallback:<arm>` — e.g. `fallback:yfinance` / `fallback:polygon`, when a
  `FallbackProvider` served the bar through the named arm

An unrecognized or unnamed provider is recorded as `legacy_unknown` rather
than guessed — provenance is stamped only when it is reliable.

**Repair / backfill / promote writers remain intentionally unstamped** for
now: `price_cache_refresh.py`, `auto_adjust_mismatch_repair.py`,
`scripts/adjusted_ticker_backfill.py`,
`scripts/spy_adjusted_benchmark_backfill.py`, and
`scripts/xle_live_backfill_promote.py`. Bars these write stay
`legacy_unknown` until a later step wires them in.

**Coverage report (read-only).** A single `SELECT` groups every cached bar
by `db.derive_price_provider` and reports per-provider row, ticker, basis,
and date-range counts. It never fetches, never mutates, and never calls a
provider:

```powershell
python scripts/price_provider_coverage_report.py --json
```

**This is separate from event provenance** — the two answer different
questions and must not be conflated:

- `event_provenance` / `provenance_status` answers **where the event came
  from** (the source-anchored origin of an archived event; see *Curated
  Intake* above).
- `source_provider` answers **where the price bar came from** (which
  market-data vendor served a cached daily close).

## Next Roadmap

The tracked evidence track is closed at Phase 4. No new candidates, new
pools, or new validators are scheduled by this README. Deferred
methodology lessons (CENX, NUE, NOC) are recorded separately in
`demo_artifacts/section_c_v2/rejection_log_summary_v1.json` and are not
denominator members of any open pool. No UI surface is claimed for the
tracked-evidence layer; the only public consumption surface is the
read-only `GET /evidence/summary` route.

Open work in the wider app, independent of the tracked-evidence track:

1. Magic-number inventory and empirical validation
2. `validation_status_v2` calibration and broader archive coverage
3. Reaction-profile calibration and coverage expansion
4. Archive aggregate stats and track-record interpretation
5. Schema migration discipline

Wider-app market validation continues to move from raw forward-return
checks toward abnormal returns, standardized abnormal returns (SAR),
confidence intervals (CI), and false-discovery-rate (FDR) controls.
That work is separate from the closed tracked-evidence pools and does
not modify them.

Deferred until the foundation is steadier: charts, tagging expansion,
scheduler/background jobs, deployment profiles, and Telegram /
WhatsApp / OpenClaw delivery.

Second Order is a local-first research and analyst-support tool. It is
not a live trading product. The tracked evidence layer is descriptive
of past, dated events; it does not generate trading signals and makes
no claim about future returns.

## Current Capabilities

- Live inbox from `news_inbox.json` plus curated RSS sources
- Source-preserving clustering and manual refresh via `/news/refresh`
- Progressive analysis through `/analyze/stream` with mechanism, watchlists, transmission chain, and macro overlays
- Recent events archive with search/filter, related-event linking, event cascade, and dated backtests
- Archive/detail validation readouts through `validation_status_v2`, including the `validation_status_v2` archive filter
- Event-detail reaction profiles through `reaction_profile_v1` when cached forward close windows exist
- Portfolio simulator over saved events, revisit snapshots, and share-page export
- Regime playbook, macro calendar, and policy-tracker surfaces
- Movers (today / weekly / yearly / persistent) and stress / rates-context / market-context endpoints
- Zero-cost diagnostics for `/diagnostics/track-record`, `/diagnostics/major-skipped-headlines`, and `/diagnostics/reaction-profile-stats`
- Ticker detail endpoints (chart, info, headlines) for inline inspection
- Bulk export of saved events: JSON / CSV / Markdown / ZIP / presentation deck / portfolio memo
- Telegram delivery for headline analysis and live-inbox briefing
- Layered caching:
  - news cache: in-memory hot cache + SQLite persistence
  - price/ticker cache for market data
  - optional snapshot warmer for liquid market benchmarks

Current limitations:

- Recent events can remain `pending` or `unresolved` until enough market evidence exists.
- `reaction_profile_v1` is read-only and cache-backed; it does not fetch live prices during detail reads.
- Reaction profiles may be unscorable until enough forward close bars are cached.
- Paid analysis does not run unless `ENABLE_PAID_ANALYSIS=true` and the paid request is explicitly confirmed.

## Engine Phase v1 / Backend Productization Freeze

Engine Phase v1 and the backend productization slice are frozen. Do not modify
engine or backend productization logic unless a regression is verified by a
focused failing test or a reproducible eval/API artifact. The next phase is
foundation validation: empirical thresholds, clearer validation status,
reaction profiles, archive aggregates, and migration discipline.

UI/API/export surfaces should preserve and render the engine-visible fields at
a high level:

- quality and warnings: `quality_tier`, `quality_warnings`
- mechanism classification: `mechanism_family`, `mechanism_subtype`
- asset/proxy discipline: primary, secondary, signal, rejected, and proxy eligibility fields
- thesis status: `thesis_state`, `thesis_state_reason`, `validation_rationale`
- actionability and counterfactuals: `actionability_check`, `counterfactual_check`
- support status and falsification: `proof_status`, `falsifier_status`
- traceability: `evidence_sources`

Backend research filters on `/portfolio`: `quality_tier`, `tradable`, and
`mechanism_subtype`. Track-record cuts should use the same frozen-engine
dimensions: `quality_tier`, `mechanism_subtype`, and `tradable`.

Completed backend productization scope:

- `/portfolio` filters: `quality_tier`, `tradable`, `mechanism_subtype`
- saved-study replay/export for those filters
- track-record dimensions: `quality_tier`, `tradable`, `mechanism_subtype`
- `portfolio_view` Markdown support in research export
- high-impact-only Still Moving Markets (`/movers/persistent`)

Still Moving Markets (`/movers/persistent`) is a high-bar surface. Eligible
entries are high-impact + thesis-relevant + persistent + non-low-information.
It requires `conviction.conviction_class == "conviction"` and
`conviction.impact_level == "high"`. `/movers/persistent` must not backfill
with low/medium-impact filler when too few events qualify. `/movers/yearly` is
a separate surface and may document different behavior if its eligibility or
fill policy diverges.

Focused freeze verification commands (targeted, not a full-suite claim):

```powershell
python -m unittest discover -s tests -p "test_*movers*.py" -v
python -m unittest discover -s tests -p "test_*portfolio*.py" -v
python -m unittest discover -s tests -p "test_track_record*.py" -v
python -m unittest tests.test_research_export -v
python eval.py --preset targeted
```

Compact local API examples:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/portfolio?quality_tier=actionable"
Invoke-RestMethod "http://127.0.0.1:8000/portfolio?tradable=true"
Invoke-RestMethod "http://127.0.0.1:8000/portfolio?mechanism_subtype=import_tariff_china"
# Still Moving Markets
Invoke-RestMethod "http://127.0.0.1:8000/movers/persistent"
```

## Run Locally

### 1. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/repo_hygiene_check.py --json
python scripts/project_health_check.py --json
python scripts/no_paid_smoke.py --json
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

The health commands above are lightweight safety and readiness checks. They do
not certify that every backend or frontend test is green.

API base URL: `http://127.0.0.1:8000`. Health check: `/health`.

For a fresh local run, keep `.env` minimal:

- leave provider API keys unset to use the built-in mock analysis fallback
- set `ANALYSIS_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or
  `ANALYSIS_PROVIDER=openai` with `OPENAI_API_KEY`, to use live analysis
- set `BACKFILL_PROVIDER=openai` and `BACKFILL_MODEL` for cheaper mover backfills
- keep `BACKFILL_DRY_RUN_DEFAULT=true` unless you are intentionally spending API calls

LLM cost guard: never run repeated `/movers/backfill-recent` calls with
`dry_run=false` without checking provider usage first. Backfill requests must
include `max_llm_calls`, and the requested value must be less than or equal to
`MAX_BACKFILL_LLM_CALLS`. Paid backfills with `dry_run=false` and
`max_llm_calls > 1` also require `confirm_paid=true`.

Use `GET /movers/backfill-preview` to inspect which recent headlines would be
eligible before spending. It is a zero-cost preview: it does not call Claude,
OpenAI, market checks, or persistence. Use `GET /registry/diagnostics` for
zero-cost headline-registry state counts, skip reasons, recent expiry counts,
and eligible unanalyzed candidates.

### 2. React Frontend

Market Overview, Event Detail, shell, portfolio, and archive polish use a
modern dark market-forensics interface: institutional, readable, and restrained
without terminal-style density. Current frontend type/build verification:

```powershell
cd frontend
npm run typecheck
npm run build
```

The Vite chunk-size warning is currently non-blocking.

These commands verify types and that the bundle builds. They do not
exercise the UI in a browser. UI-visible behavior — for example, how the
global error-boundary fallback renders when a page crashes — is verified
manually under `npm run dev` and is intentionally separate from the
automated type/build gate above.

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 3000
```

Vite runs at `http://localhost:3000` and proxies `/api/*` to the backend on
`http://127.0.0.1:8000`.
Optional frontend runtime config lives in `frontend/.env.example`:
leave `VITE_API_BASE_URL` unset for same-origin `/api`, or set it to a full
API origin for split deploys. `VITE_DEV_API_PROXY_TARGET` is local-dev only.

### 3. Telegram Bot

From the repo root, after the backend is running and `.env` includes
`TELEGRAM_BOT_TOKEN` plus `SECOND_ORDER_API_URL=http://127.0.0.1:8000`:

```powershell
python telegram_bot.py
```

The bot uses `SECOND_ORDER_API_URL` to call the local FastAPI service.

## Deploy

For a minimal public API deploy on Render, use `render.yaml`.
Set the API key for the selected `ANALYSIS_PROVIDER` only if you want real
model output in the deployed app; otherwise the API still boots with
mock-analysis fallback. Render injects `PORT` automatically.
For a split frontend/backend deploy, set `VITE_API_BASE_URL` on the frontend and
set `CORS_ALLOWED_ORIGINS` on the backend to the frontend origin.

## Configuration

Copy `.env.example` to `.env` for local use and keep `.env` untracked. Real current keys are:

Security and paid-action guardrails are documented in [SECURITY.md](SECURITY.md).
Contribution workflow and local verification commands are in [CONTRIBUTING.md](CONTRIBUTING.md).

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `ANALYSIS_PROVIDER`
- `ANTHROPIC_MODEL`
- `OPENAI_MODEL`
- `BACKFILL_PROVIDER`
- `BACKFILL_MODEL`
- `MAX_BACKFILL_LLM_CALLS`
- `BACKFILL_DRY_RUN_DEFAULT`
- `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS`
- `CORS_ALLOWED_ORIGINS`
- `TELEGRAM_BOT_TOKEN`
- `SECOND_ORDER_API_URL`
- `DAILY_BRIEF_ENABLED`
- `DAILY_BRIEF_CHAT_ID`
- `DAILY_BRIEF_TIME`
- `WATCHLIST_ENABLED`
- `WATCHLIST_CHAT_ID`
- `WATCHLIST_INTERVAL_MIN`
- `WATCHLIST_THRESHOLD_PCT`
- `MARKET_DATA_PROVIDER`
- `POLYGON_API_KEY`
- `MARKET_SNAPSHOTS_ENABLED`
- `MARKET_SNAPSHOTS_INTERVAL`
- `FEED_CONFIG_PATH` (override path for `feed_config.json`; defaults to repo root)

If the selected provider key is missing, analysis falls back to mock output for
local UI and testing flows. Mock analyses are not saved. `ANALYSIS_PROVIDER`
accepts `anthropic` or `openai`; `/movers/backfill-recent` uses
`BACKFILL_PROVIDER` and `BACKFILL_MODEL`, defaults to `dry_run=true`, and
rejects requests that omit `max_llm_calls`. Paid multi-call backfills
(`dry_run=false` and `max_llm_calls > 1`) require `confirm_paid=true`. Keep
`MAX_BACKFILL_LLM_CALLS` low (`1` in `.env.example`).
`HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS` controls how long analyzed low-impact
headlines remain visible on active archive/mover listing surfaces before they
are filtered as expired low-impact rows.

## Telegram Commands

- `/start`: intro and usage hint
- `/help`: command summary
- `/brief`: top clustered headlines with current market-context block
- plain text or forwarded headline: run the analysis pipeline and return a compact summary

## Typical Flow

1. Start FastAPI.
2. Start the React app and/or Telegram bot.
3. Review the inbox, refresh feeds when needed, and open a candidate event.
4. Run progressive analysis and inspect mechanism, watchlists, market validation, and macro overlays.
5. Save the event, review related follow-ups, and revisit it in Backtest later.
6. Export saved events from the archive when needed.

## Key Files

- `frontend/`: React + TypeScript app
- `api.py`: FastAPI surface and orchestration
- `routes/`: per-domain route modules (`analyze`, `events`, `news`, `movers`, `market`, `portfolio`, `playbook`)
- `telegram_bot.py`: Telegram client surface and scheduled jobs
- `classify.py`: deterministic stage / persistence classification
- `analyze_event.py`, `prompts.py`: LLM analysis, sanitization, field registry, prompt templates
- `news_sources.py`, `news_clustering.py`, `news_relevance.py`, `news_cluster_store.py`: ingestion, RSS normalization, clustering, persisted news cache
- `db.py`: SQLite persistence and cache storage
- `market_check.py`, `market_context.py`, `market_data.py`, `price_cache.py`, `market_snapshots.py`, `movers_cache.py`: market validation, overlays, provider access, warm caches
- `shock_decomposition.py`, `reaction_function_divergence.py`, `real_yield_context.py`: macro overlays (pure composers)
- `eval.py`, `calibration_report.py`, `calibrate_thresholds.py`, `calibrate_thresholds_pass2.py`: evaluation and threshold-drift reporting

## Evaluation

Quick canary run:

```powershell
python eval.py --preset canary
```

Model comparison example:

```powershell
python eval.py --preset canary --model claude-haiku-4-5-20251001
python eval.py --preset canary --model claude-sonnet-4-6
```

For a combined calibration + behavior report (clustering, sector keywords,
confidence-bucket depth, relevance filter, plausible-range guards) run:

```powershell
python calibration_report.py
```

See [EVALUATION.md](EVALUATION.md) for the current eval flow and limits.

## Test

The current conservative verification set is targeted. It checks DB isolation,
paid-action guardrails, and health/smoke summaries without claiming full-suite
coverage. From the repo root:

```powershell
python scripts/repo_hygiene_check.py --json
python scripts/project_health_check.py --json
python scripts/no_paid_smoke.py --json
python -m pytest tests/test_test_db_isolation.py -q
python -m pytest tests/test_backfill_paid_guard.py -q
python -m unittest tests.test_project_health_check -v
python -m unittest tests.test_no_paid_smoke -v
```

A full discovery run is useful before larger backend changes, but this README
does not present it as a green release gate unless it has been separately
verified.

## Scope

- Local-first research support, not automated trading
- Heuristic classification and market validation remain analyst-support tools
- FastAPI, the React app, and the Telegram bot are the maintained product paths

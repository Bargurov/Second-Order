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
python scripts/project_health_check.py --json --allow-duplicate-clusters 32
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
python scripts/project_health_check.py --json --allow-duplicate-clusters 32
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

# Second Order

Second Order is a local-first geopolitical and macro research app. The current
product is a FastAPI backend with two maintained client surfaces:

- a React app for live inbox review, progressive analysis, archive/backtest work, and export
- a Telegram bot for direct headline analysis, `/brief`, and optional scheduled delivery

The system is designed for analyst workflows: ingest live headlines, cluster
overlapping coverage, run classify -> analysis -> market stages, layer in macro
and market-context overlays, save the result locally, and revisit dated events.

## What this is — for a finance reader

Second Order is a research dashboard for geopolitical, macro, and policy events:
it traces an event's plausible second-order transmission to assets and reads the
market's event-window reaction honestly — as descriptive evidence, never as a
forecast or a recommendation.

It is a research-craftsmanship piece, not a trading product. It works one event
at a time: what changed, the mechanism (who benefits, who is exposed, and the
transmission chain), the affected assets, and how those assets actually moved in
the days after the event.

## What it does / what it does not do

**It does:**

- ingest live headlines and events and cluster overlapping coverage
- articulate a mechanism and the affected assets for each event
- read the raw 1-day / 5-day / 20-day event-window reaction of the named assets
- show a benchmark-adjusted event-study readout (abnormal return, standardized
  AR, cumulative AR vs SPY) wherever the price data allows
- score tape-direction agreement on the scored names, descriptively
- package each event as a single research note (an *EventDossier*)

**It does not:**

- issue directional recommendations of any kind
- claim statistical significance at a single event (`n = 1`: no confidence
  interval, p-value, or false-discovery control on a single-event readout)
- claim a permanent asset forecast
- merge the descriptive archive with the closed Phase 1 / Phase 2 FDR pools —
  those denominators stay separate

## Five-minute walkthrough

1. **Market Overview** (the landing page) — read the market backdrop, recent
   event activity, and the *Track record & evidence* framing.
2. **Case Library** (Research nav) — five representative cases, one per outcome
   type, with the denominator anchor and the standing non-claims on the page.
3. **Open #105 — OPEC output cuts** (strong support): the in-app Archive / Event
   Detail dossier, where the tape agreed with the thesis direction across several
   legs.
4. **Open #29 — Strait of Hormuz** (contradiction): the canonical oil-shock
   thesis the tape rejected — the honest counterweight to a winners-only read.
5. **Read one EventDossier** end to end: mechanism, affected assets and their
   realized move, the event-study readout (at `n = 1`), the scored outcome where
   available, and the standing claim boundary.
6. **Evidence Coverage / denominators** — the *Track record & evidence* card and
   the funnel below: which gates apply and how many events clear each.
7. **Backtest** *(optional)* — the descriptive directional-agreement review
   across saved events; a track record, not a strategy result.
8. **End on the boundary** — every read is descriptive event-window evidence at
   `n = 1`, not a recommendation and not a claim of predictive power.

## How the surfaces fit

- **EventDossier** — the shared research note for one event; it leads both the
  Share page and the Archive / Event Detail view.
- **Case Library** — a guided, representative entry point (five real cases).
- **Archive / Event Detail** — the full in-app dossier, including the scored
  outcome (`validation_status_v2`) when the archive row carries it.
- **Share page (`/share/:id`)** — the same dossier, shell-free for linking; it
  may omit the scored outcome because the export payload does not carry it.
- **Market Overview — Evidence Coverage** — the denominators and the evidence
  gates, kept phase-separated from the closed FDR pools.
- **Backtest** — a descriptive directional-agreement review, not strategy
  validation.

## The funnel — denominators, honestly

Freshly verified against the local archive (2026-06-08); a clean clone starts
empty, so re-run the read-only reports for live figures.

- **166 events saved** in the archive (the readiness report counts **165**,
  excluding one source-anchored `curated_intake` stub).
- **81 market-scored** (events carrying scored market data): **19 any-supporting
  · 35 contradicted · 27 unresolved**.
- **71 archive-ready** and **71 event-study compute-ready** (per-horizon point
  estimates computable vs SPY).

Denominators differ by gate and data availability, and the gates are **not
pooled**. The closed Phase 1 and Phase 2 FDR pools (five rows each) are a
**separate** evidence track with their own frozen q-values — they are not
derived from the saved-event archive.

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

## Reproducibility & data

This repository is local-first, and its two kinds of numbers reproduce
differently from a clean clone:

- **The closed Phase 1–4 evidence track is clean-clone reproducible.** Its
  artifacts (`demo_artifacts/section_c_v2/`) and the three schema validators
  are tracked, and `.github/workflows/ci.yml` re-runs them on every push
  against a fixture database it builds on the CI runner — it never needs a
  local archive. A fresh clone reproduces the Phase 1 / Phase 2 pool counts
  exactly.
- **The wider-app archive coverage and data-hygiene counts do not ship.** They
  are computed against the maintainer's local `events.db`, which is
  intentionally **not** committed — it is gitignored, large, and carries
  seed/test rows. A clean clone therefore starts with an **empty** archive, so
  the coverage / hygiene / price-provider figures quoted below reflect the
  maintainer's local archive as of the dates noted, not a fresh checkout.

The read-only report commands in the sections below recompute every archive
figure from whatever `events.db` is present, so they — not the numbers frozen
in this file — are the source of truth. On a clean clone with no archive they
return an empty (zero-count) report.

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

`matched basis` means the asset and SPY benchmark use the **same**
`auto_adjust` flag for the full window the event-study engine consumes
(no adjusted/raw splice within a series). All compute-ready events sit on
matched basis (`cross_flag` = 0). Note that since the Batch-1 coverage
repair (below) the 18 repaired events resolved on matched **raw** basis,
so the earlier "every compute-ready event is on matched *adjusted* basis"
no longer holds — but no row mixes flags, so no splice caveat applies.

Current verified counts from
`python scripts/stat_validation_readiness_report.py --json --limit 0` (2026-06-08):

- total archive events: 165
- archive-ready events: 71
- event-study compute-ready events: 71 (was 62 after the Batch-1 coverage
  repair documented below, and 44 before it; +8 from the Phase-K
  `curated_observation` promotions, and +1 as #280's 20-day forward bar has
  since printed)
- matched-basis events: 71
- cross-flag caveats: 0

Compute-ready means SAR/CAR point estimates are computable. It does not
mean cohort-level statistical inference is available for a single
event. Single-event output has `n=1`, so CI, p-value, and FDR are not
available on the event-detail route; those remain cohort-level
statistics.

Compute-ready rows are also not automatically valid cohort
observations. Across the matched compute-ready set, cohort-level
inference is currently on hold, and the block is independence and
labeling rather than the event-study engine: the legacy/organic
compute-ready rows are concentrated in a few primary tickers and one
clustered macro window with overlapping forward windows and carry no
`mechanism_family` label, so they are not independent observations. The
8 Phase-K `curated_observation` rows *are* labeled (tariff / sanction),
but a pooled read across them is still blocked by a family/sign confound
and per-family n < 8 — see `stats/PHASE_K_EVIDENCE.md`. Running
cross-sectional CI, p-value, or FDR over the set would overstate
precision. The criteria a future cohort phase must meet are recorded in
`stats/METHODOLOGY.md` ("Cohort inference — currently blocked"). This
decision does not change the closed Phase 1 or Phase 2 FDR denominators.

After the Batch-1 coverage repair (below) the residual cache/window
blockers shrank sharply — `no_contiguous_aligned_window` fell from 8 to
1 and the forward-cache gaps roughly halved. The one remaining Batch-1
frontier case is #280 (XLE), whose 20th forward trading-day bar had not
yet printed at repair time. The dominant remaining blocker is still
`no_primary_ticker` (84) — a coverage gap left deliberately untouched
(see the repair note below). These archive event-study counts do not
change the closed Phase 1 or Phase 2 FDR denominators.

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
`event_study_compute_ready` exactly (71 = 71).

**Single-event output is point estimates only.** At `n=1` there is no
confidence interval, no p-value, and no FDR; the report makes no
`confirmed` / `validated` / "significant" claim. Each JSON payload carries
an explicit `non_claims` block stating this.

Current live coverage (2026-06-08, after the Batch-1 coverage repair below and
the Phase-K `curated_observation` promotions):

- event_study_available: 71
- insufficient_data: 94
- curated_intake excluded: 1
- auto_adjust basis: matched 71, cross_flag 0

The dominant blocker is `no_primary_ticker` (84) — a **coverage gap, not a
statistics failure**: those events never reach the engine because they
carry no primary ticker, and that pool was left untouched (see the repair
note below). The remaining cache/window blockers are
`insufficient_estimation_window_primary` (9), `missing_forward_cache_20d`
(9), `missing_forward_cache_5d` (5), `no_cached_prices_for_primary_ticker`
(4), `missing_forward_cache_1d` (4), `no_contiguous_aligned_window` (1),
and `missing_benchmark_proxy` (1). None is an engine error; each is a
data-coverage or contiguity precondition.

```powershell
python scripts/event_study_coverage_report.py --json
```

### Batch-1 event-study coverage repair (H1 → H3, 2026-06-03)

The first bounded coverage-repair batch lifted event-study compute-ready
events from **44 to 62** (insufficient **113 → 95**) against the then-157
analysis-stage rows, by backfilling missing `price_cache` rows. It added no
events, changed no thesis text, and reassigned no tickers or benchmarks — it
is a data-coverage fix, not new evidence.

**Denominator at repair time.** 157 analysis-stage events as of 2026-06-03;
curated_intake stubs are excluded separately (1 at repair time) and never
enter this count. (The live analysis-stage denominator is now 165 after the
Phase-K promotions — see the data-hygiene section below for the current
split.)

**Frozen baseline (H1).** The 113 insufficient rows split into 84 with no
primary ticker and 29 that already carried a primary ticker but failed a
cache/window precondition. The 84 `no_primary_ticker` rows were left
untouched — **71 are synthetic/seed/test duplicates** ("OPEC slashes output
by 2 mbpd", "Macro shock test event", "Test headline", repeated across
consecutive dates) and **13 are real macro/geopolitical events with no
single defensible public ticker**. Assigning tickers to them after the fact
would be survivorship/look-ahead bias, so that pool is explicitly out of
scope for this batch.

**Frozen Batch-1 selection rule (pre-outcome attributes only).** An event
qualified iff: (a) it already had a primary ticker chosen at analysis time,
(b) that ticker is a real US-listed instrument, (c) its blocker was
cache/window coverage (forward-cache gap or non-contiguous window), not
ticker assignment, and (d) the event + 20 business-day window was already
in the past. No ticker or benchmark was reassigned; only price history was
backfilled.

**Frozen 19 ids:** 2, 42, 45, 80, 94, 211, 212, 213, 214, 232, 233, 234,
235, 236, 238, 239, 240, 250, 280.

**Result — 18 pass / 1 fail.** Eighteen events flipped to
`event_study_available` (all on matched raw basis). The single failure is
**#280 (XLE, 2026-05-05)**: its 20th forward trading-day bar is 2026-06-03,
which had not yet printed at repair time — a data frontier, not an engine
error. It is reported as a failure (not dropped or replaced) and becomes
compute-ready once that bar exists.

**Mutation scope (H3, live, `price_cache` only).** The repair ran first
against a DB copy (`events.h2.dev.db`, via `EVENTS_DB_FILE`) and was then
promoted to the live archive as a `price_cache`-only change: **+1,440
inserted rows** and **15 updated adjusted (`auto_adjust=1`) rows** (14
`legacy_unknown → yfinance` provider/close refreshes plus one SPY
2026-06-02 volume refresh). The `events`, `event_provenance`, and
`movers_cache` tables were unchanged; no headline, ticker, or benchmark was
edited. Live `events.db` SHA-256 went `c813ad4d…` → `8736908a…`; a
pre-promotion backup is at
`backups/pre_h3_price_cache_promote_2026-06-03.db`.

**Non-claims.** This is coverage repair (more rows can now produce point
estimates), **not** new-evidence discovery and **not** a cohort-level
inference — the Batch-1 compute-ready rows were concentrated in a few primary
tickers with `mechanism_family` unpopulated, so no cross-sectional CI,
p-value, or BH-FDR is claimed and the closed Phase 1 / Phase 2 FDR pools are
untouched. No replacement events were cherry-picked to inflate the pass
rate; the one failure (#280) stays on the record.

### Archive data-hygiene & denominator policy

> The coverage ratios in this section are a dated snapshot (2026-06-03) from
> `scripts/data_hygiene_report.py`. The live readiness counts above were
> refreshed 2026-06-08 (event-study compute-ready 70 → 71, as #280's 20-day
> forward bar has since printed); re-run the report for current figures. The
> denominator *policy* below is unchanged.

`scripts/data_hygiene_report.py` is the read-only, reproducible **source of
truth** for which archive rows are genuine research events and which are
seeded/test contamination. It classifies every analysis-stage row by exact
headline + `model` fingerprint (never by lack of a ticker) into
`synthetic_seed` / `synthetic_test` / `real_duplicate` / `real_unique`, and
emits three denominator views so every coverage figure names the base it uses:

- **165 — analysis-stage observation denominator:** 70/165 ≈ 42% event-study
  coverage. Every analysis-stage row, contamination included. This is the
  research-*observation* denominator (`db.NON_ANALYSIS_STAGES` excludes only
  the 1 `curated_intake` stub: 166 − 1 = 165); it **includes** the 8 Phase-K
  `curated_observation` promotions.
- **94 — real rows** (165 − 71 synthetic): 70/94 ≈ 74%. Non-synthetic rows.
- **79 — distinct real events** (the 94 real rows after collapsing duplicate
  headlines): 60/79 ≈ 76%. The most defensible research-coverage figure.

(Archive raw total is 166, including the one excluded `curated_intake` stub.)

**Two separate denominators — and why 157 is still here.** The 8 Phase-K
`curated_observation` rows raised the analysis-stage *observation* denominator
from 157 to **165**, but the *thesis / track-record* denominator stayed at
exactly **157**, because `db.NON_THESIS_STAGES` excludes **both**
`curated_intake` (1) **and** `curated_observation` (8): 166 − 1 − 8 = 157.
Those 8 rows carry a primary ticker and a `mechanism_family`, so they are real
event-study *observations* (counted in the 165), but they carry no LLM thesis
(beneficiaries / losers / direction), so they never enter the *outcome* pool
(the 157). One denominator answers "can the engine read this event"; the other
answers "did a scored thesis play out". The 8 promotions and their descriptive,
single-event (h1-only) evidence — explicitly **not** a validation and **not** a
pooled cohort — are recorded in `stats/PHASE_K_EVIDENCE.md`. A third
crossed-sign mechanism-family candidate, regulation, was separately sourced,
source-pinned, timing-audited, and read descriptively h1-only on a DB copy in
`stats/PHASE_K_REGULATION_EVIDENCE.md`; it was **not** promoted to live
`curated_observation` and does not enter the analysis, track-record, cohort, or
FDR denominators.

**Why 165 keeps the contamination visible.** Reporting coverage against the
full analysis-stage 165 first keeps the legacy/seed/test contamination
*visible* instead of quietly dropping it — a reader sees that a large share of
the analysis-stage archive is non-research rows rather than being handed a
flattering ratio with the noise hidden. Coverage is always reported against
165 first.

**Why 94 and 79 matter.** They are the honest denominators for any
coverage/quality *claim*. The 71 synthetic rows never reach the engine (all
no-ticker, all insufficient), so 70/165 actually *understates* real reach; the
94-row and 79-event views state it honestly, and the 79-event view
additionally collapses duplicate headlines so coverage is not double-counted.
Exclusion here enables *computation*, never silent shrinkage: every ratio is
reported alongside 165, never instead of it.

**Synthetic / seed / test rows: 71.** 58 are seed/demo headlines run through
the real model (e.g. "OPEC slashes output by 2 mbpd", "Fed speakers rotate"),
repeated across consecutive dates; 13 are literal test artifacts ("Macro shock
test event", "Test headline" / the `test-model` fingerprint). All 71 carry no
primary ticker and are insufficient — none is compute-ready.

**Real duplicates: 27 rows across 12 headlines (15 redundant copies).** Even
within the 94 real rows, the same genuine headline is sometimes analysed on
multiple dates (e.g. "AP News: OPEC members discuss extending output cuts" ×4),
so the 70 compute-ready *rows* are only **60 distinct events**. Duplicates
barely move the coverage *ratio* (the redundancy nearly cancels between
numerator and denominator); their real cost is to the independent-observation
count any cohort claim would need.

**Non-claims.** This is denominator *hygiene*, not statistical inference. The
report deletes and mutates nothing (read-only) and never reads, modifies, or
reopens the closed Phase 1 / Phase 2 FDR pools; it changes neither the 165
analysis-stage observation denominator nor the separate 157 thesis denominator.
The cohort/inference denominator stays **separately gated** by the independence
and `mechanism_family` rules in `stats/METHODOLOGY.md` and the Phase-K blockers
in `stats/PHASE_K_EVIDENCE.md` — de-duplicating headlines is necessary but not
sufficient for cohort eligibility.

```powershell
python scripts/data_hygiene_report.py --json
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

**Current live counts** (live archive, post-Phase-K):

- raw events: 166 (1 `curated_intake` stub + 8 Phase-K `curated_observation`
  promotions + 157 thesis-eligible analysis-stage rows)
- readiness `total_events`: 165 (`curated_intake` excluded; the 8
  `curated_observation` rows are counted here but excluded from the thesis /
  track-record denominator — see the data-hygiene section)
- `curated_intake_excluded_count`: 1
- `source_anchored_promoted_count`: 8 (Phase-K `curated_observation` rows)

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

**The cache is predominantly `legacy_unknown`, by design — but that share is
not fixed.** Most cached bars predate the stamping path and carry no recorded
provider; as provider-stamped reads land, the mix shifts. The Batch-1 coverage
repair (above) introduced the first `yfinance`-stamped bars through the
canonical read-through path, so the cache now spans **two** providers
(`legacy_unknown` and `yfinance`) — 20,118 cached bars across 155 tickers at
the time of writing. These counts drift with every backfill, so the live split
is whatever the read-only coverage report below prints, never a number frozen
in this file. `legacy_unknown` there means the provider was **not recorded at
write time, not that the data is invalid**.

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

Requires **Python 3.12** (the version pinned in `.github/workflows/ci.yml`).

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

A bare `uvicorn api:app` binds the live `events.db`; for dev servers and
verification runs, point `EVENTS_DB_FILE` at a copy first — see **Dev /
verification DB safety** below.

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

### Dev / verification DB safety (`EVENTS_DB_FILE`)

A bare `uvicorn api:app` and most scripts bind to the live `events.db` by
default, so a leaked dev server or an ad-hoc script can silently mutate the real
archive. For dev servers, visual passes, and Phase-H coverage / ticker repair
work, run against a **copy** instead of the live archive:

```powershell
Copy-Item events.db events.dev.db
$env:EVENTS_DB_FILE = "events.dev.db"
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

`EVENTS_DB_FILE` is resolved once, at import time. When it is unset the backend
falls back to the live `events.db` and logs a startup warning so the live
binding is never silent. Phase-H repair scripts must point at a copy via
`EVENTS_DB_FILE` (or an explicit `--db` flag) and must not run against the bare
live default.

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
Local verification commands are in the [Test](#test) section below.

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

The eval presets above are canary / targeted smoke runs that exercise the
analysis pipeline and threshold reporting; they are not a full benchmark or a
statistical-coverage claim.

## Test

The current conservative verification set is targeted. It checks DB isolation,
paid-action guardrails, and health/smoke summaries without claiming full-suite
coverage. From the repo root:

```powershell
python scripts/repo_hygiene_check.py --json
python scripts/project_health_check.py --json
python scripts/no_paid_smoke.py --json
python -m unittest tests.test_test_db_isolation -v
python -m unittest tests.test_backfill_paid_guard -v
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

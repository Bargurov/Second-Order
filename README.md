# Second Order

Second Order is an honest research dashboard for geopolitical, macro, and policy
events. It traces an event's plausible second-order transmission to assets and
reads the market's event-window reaction descriptively — as evidence, never as a
forecast or a recommendation. It is a quant-finance research-craftsmanship piece,
not a trading product.

**Current research state.** The tracked Phase 1-4 evidence track is frozen and
complete; the wider-app archive is descriptive, read-only, and reproducible from
the read-only reports below. Two distinct null-like results exist over different
denominators and different questions — do not conflate them. The accepted-lane
baseline verdict is `not_above_baseline` — no robust above-baseline directional
skill in the 86-row accepted archive. Separately, the completed Mission G
historical program (97 events; see
[`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md)) asked whether pre-event market
state conditioned historical event reactions and found a predominantly flat,
fragile, or contradictory surface. Cohort-level inference remains blocked (see
the Compute-Readiness Contract).

**Best starting point for a finance reviewer.** Start with
[`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md): it explains the completed
research chain, evidence lanes, Mission G design, main null result, bounded OPEC
association, representative cases, and claim boundaries. Then use the
[five-minute walkthrough](#five-minute-walkthrough), denominator funnel, and
read-only commands in [Verify it yourself](#verify-it-yourself-read-only-research-reports).

Second Order runs as a FastAPI backend with a React app and a Telegram bot; local
setup is in [Run Locally](#run-locally). Detailed operator history and dated
repair logs are intentionally kept out of this reviewer-facing README; the repo
preserves that evolution through git history and the durable research reports
linked below.

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

## Reviewer reading path

A skeptical reviewer can follow the intended order without a guided tour:

1. **Evidence Overview** (Research nav) — the front-door screen: the denominator
   ledger, the mechanism-family inventory, and the representative case library on
   one page.
2. **Mechanism-family evidence inventory** —
   [`stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md`](stats/MECHANISM_FAMILY_EVIDENCE_INVENTORY.md):
   where the accepted archive has mass, which families are thin, which are
   overlay-only buckets, and where readouts show missingness.
3. **Representative case library** —
   [`stats/REPRESENTATIVE_CASE_EXPANSION.md`](stats/REPRESENTATIVE_CASE_EXPANSION.md):
   15 illustrative cases across 6 mechanism families — 6 already-covered anchors
   plus 9 newly proposed cases with expanded notes.
4. **Expanded case notes** —
   [`stats/EXPANDED_CASE_NOTES.md`](stats/EXPANDED_CASE_NOTES.md): source-grounded
   notes for the 9 newly proposed cases. Each note keeps the readout lens (primary
   ticker vs SPY) separate from the thesis-outcome lens (support / contradiction /
   unresolved) — the two can disagree.
5. **Optional numeric readout layer** —
   [`stats/CASE_LIBRARY_REACTION_MATRIX.md`](stats/CASE_LIBRARY_REACTION_MATRIX.md):
   a compact 1d / 5d / 20d SPY-relative matrix for the 15 representative cases.
   It shows 12 / 15 available readouts, makes missing readouts explicit, and
   keeps the readout lens separate from thesis-outcome scoring.
6. **Effective independent evidence** —
   [`stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md`](stats/EFFECTIVE_INDEPENDENT_EVIDENCE.md):
   answers the reviewer question "are the 86 accepted track-record rows really 86
   separate market stories?" They group into 7 descriptive market-story clusters
   under transparent same-date / same-primary-ticker-window / duplicate-link rules,
   and the largest cluster holds 79 rows — so the archive reads as a small number
   of market tapes observed many ways, not 86 separate pieces of evidence. Read it
   before treating the support / contradiction / unresolved counts as separate
   evidence; it makes the interpretation more honest, not weaker. A descriptive
   independence-caution layer — not an inferential effective sample size, score,
   rank, p-value, or FDR pool.
7. **Methodology / non-claims** —
   [`stats/METHODOLOGY.md`](stats/METHODOLOGY.md): market-adjusted readouts are
   SPY-relative with beta fixed at 1. Representative cases are walkthrough
   material, not family-level inference; not a recommendation or forecast.

Locked protocol for the gated historical-evidence phase (Mission G): [`stats/G_RESEARCH_PROTOCOL.md`](stats/G_RESEARCH_PROTOCOL.md) with its standardization spec [`stats/G_STANDARDIZATION_SPEC.md`](stats/G_STANDARDIZATION_SPEC.md).

## Five-minute walkthrough

1. **Market Overview** (the landing page) — read the market backdrop, recent
   event activity, and the *Track record & evidence* framing.
2. **Case Library** (Research nav) — fifteen representative cases (only three
   any-supporting; the rest contradictions or unresolved / data-limited reads),
   with the denominator anchor and the standing non-claims on the page.
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

Technical and finance reviewers: the self-verifiable evidence lives in
[**Verify it yourself**](#verify-it-yourself-read-only-research-reports), whose
read-only reports recompute the family overlay, transmission cases, sector
backdrop, and case-selection stress.

## How the surfaces fit

- **EventDossier** — the shared research note for one event; it leads both the
  Share page and the Archive / Event Detail view.
- **Case Library** — a guided, representative entry point (fifteen real cases;
  only three any-supporting, the rest contradictions or unresolved / data-limited
  reads).
- **Archive / Event Detail** — the full in-app dossier, including the scored
  outcome (`validation_status_v2`) when the archive row carries it.
- **Share page (`/share/:id`)** — the same dossier, shell-free for linking; it
  may omit the scored outcome because the export payload does not carry it.
- **Market Overview — Evidence Coverage** — the denominators and the evidence
  gates, kept phase-separated from the closed FDR pools.
- **Backtest** — a descriptive directional-agreement review, not strategy
  validation.

## The funnel — denominators, honestly

The canonical live denominators (re-run the read-only reports in
[Verify it yourself](#verify-it-yourself-read-only-research-reports) for current
figures — a clean clone starts empty):

- **180** archive rows — every saved event.
- **94** accepted coverage / analysis rows.
- **86** accepted track-record rows (46 any-supporting, 8 contradicted,
  32 unresolved).
- **78 of 94** event-study compute-ready — rows with per-horizon (1d / 5d / 20d)
  point estimates computable against SPY.
- **13** staged candidates — review staging, excluded from every accepted
  denominator.

These gates are **not pooled**, and they differ by data availability. SPY is the
one canonical abnormal-return benchmark; sector baselines are descriptive context
only, never a sector-relative abnormal return. The headline baseline conclusion
is `not_above_baseline` (no robust above-baseline directional skill), and
cohort-level inference is currently blocked — see the
[Compute-Readiness Contract](#event-study-compute-readiness-contract). That
accepted-lane verdict answers a directional-skill question; it is distinct from
the Mission G historical state-conditioning null summarized in
[`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md). The closed
Phase 1 and Phase 2 FDR pools (five rows each) are a **separate** evidence track
with their own frozen q-values, never derived from this saved-event archive.

Re-run the read-only reports above for the live figures; the dated
pre-restatement funnel snapshots and the full AP3b restatement detail are kept
out of this reviewer-facing README.

## Verify it yourself: read-only research reports

Every figure above recomputes from the live archive. The Phase-1 methods
spine is [`stats/METHODOLOGY.md`](stats/METHODOLOGY.md) — the
abnormal-return / SAR / p-value / FDR conventions plus the
statistical-honesty layer (small-sample robust diagnostics, event-window
overlap disclosure, and track-record scoring-rule sensitivity). Current
methodology is distributed across the canonical documents: the close-basis
policy in [`stats/BASIS_RESTATEMENT.md`](stats/BASIS_RESTATEMENT.md), the
event-study lens spec in
[`stats/G_STANDARDIZATION_SPEC.md`](stats/G_STANDARDIZATION_SPEC.md), and
the locked Mission G protocol in
[`stats/G_RESEARCH_PROTOCOL.md`](stats/G_RESEARCH_PROTOCOL.md).

The separate **Mission I** ordinary-period baseline — whether completed FOMC and
OPEC event windows are unusual relative to eligible ordinary periods on the same
frozen assets — is closed out in
[`stats/MISSION_I_CLOSEOUT.md`](stats/MISSION_I_CLOSEOUT.md) (structure and
evidence chain summarized in [`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md)). Its
finding is family-, horizon-, and metric-specific and carries no significance,
causal, or predictive claim.

These reports are **read-only**: they open `events.db` with `mode=ro`, never
mutate it, never call a paid provider, and never run `/analyze`. They never
reopen or recompute the **frozen** Phase 1 / Phase 2 FDR pools. Every payload
carries a `non_claims` block — the numbers are descriptive coverage and
sensitivity diagnostics, not significance results. (These surfaces live in the
reports and `stats/METHODOLOGY.md`; the app does not expose this layer yet.)

Run from the repo root:

- **Accepted denominators + event-study reach** —
  `python scripts/event_study_coverage_report.py --json`
  Verifies the accepted coverage denominator. Expect **94** accepted events,
  **78** event-study compute-ready.

- **Archive data-hygiene & denominator provenance** —
  `python scripts/data_hygiene_report.py --json`
  The read-only source of truth behind the funnel: it classifies every
  analysis-stage row (by exact headline + `model` fingerprint) as
  synthetic-seed / synthetic-test / real-duplicate / real-unique, so the **71**
  synthetic-seed rows excluded from the accepted denominators are auditable by
  id. Denominator hygiene, not statistical inference; it mutates nothing and
  never touches the closed Phase 1 / Phase 2 FDR pools.

- **Compute-readiness + window-overlap caveat** —
  `python scripts/stat_validation_readiness_report.py --json --lens accepted --limit 0`
  Verifies per-event compute-readiness and the event-window overlap caveat,
  scoped to the compute-ready set. Expect compute-ready **78**, `window_overlap`
  n **78**, lens `accepted`.

- **Small-sample robust diagnostics** —
  `python scripts/baseline_characterization_report.py --db events.db --sims 60 --json`
  Verifies the `robust_diagnostics` block: an exact sign test, a Wilcoxon
  signed-rank summary, the overlap caveat co-located with each p-value as its
  independence qualifier, and the SAR-convention audit.

- **Event-date placebo / negative control** *(text mode — no `--json`)* —
  `python scripts/archive_placebo_report.py --db events.db --draws 1000 --seed 20260608`
  A null / negative-control readout. Expect the observed event-window overlap
  caveat over the placebo-feasible role-observations.

- **Track-record scoring-rule sensitivity** —
  `python scripts/track_record_sensitivity_report.py --db-path events.db --json --limit 5`
  Verifies how the accepted track-record split moves under stricter scoring
  rules over one shared denominator. Expect denominator **86**; the canonical
  `validated` count moves **46 → 19 → 11** across any-support → majority →
  strict. No rule is claimed correct; the canonical headline rule is unchanged.

- **Mechanism-family coverage map** —
  `python scripts/mechanism_family_overview_report.py --db-path events.db --json`
  Shows which mechanism families carry accepted evidence vs staged no-paid
  candidates, with the untagged bucket disclosed as a limitation. Narrative
  context: [`stats/MECHANISM_FAMILY_OVERVIEW.md`](stats/MECHANISM_FAMILY_OVERVIEW.md);
  candidate-review decisions:
  [`stats/STAGED_CANDIDATE_SHORTLIST.md`](stats/STAGED_CANDIDATE_SHORTLIST.md).
  Staged candidates never enter accepted denominators.

- **Accepted-corpus family overlay** —
  `python scripts/accepted_family_overlay_report.py --db-path events.db --json`
  Classifies the **86** untagged accepted thesis rows with deterministic
  whole-token headline rules, entirely in memory (no DB write). Expect
  single + multi + unclassified to sum to **86**; ambiguous rows are
  surfaced, never forced. Coverage decomposition only — see
  [`stats/ACCEPTED_FAMILY_OVERLAY.md`](stats/ACCEPTED_FAMILY_OVERLAY.md).

### Accepted-family overlay arc — reviewer walkthrough

The accepted track-record corpus has **86 thesis rows**, and all 86 remain
family-untagged in `events.db`. The completed overlay arc measures that
limitation without changing the database or any accepted denominator:

1. **J1 — headline overlay:** deterministic whole-token rules classify the
   headlines in memory as **52 single-match / 16 multi-match / 18
   unclassified**. This is a coverage map, not a family comparison.
2. **K1 — weak-bucket review:** **15 of 16** multi-match rows are legitimate
   overlaps; one `trade war` row is a token overfit. The 18 unclassified rows
   divide into archive noise, taxonomy gaps, and **2** bounded rule misses.
3. **L1 — mechanism-text second lens:** applying the same rules to richer
   mechanism text recovers only **3** rows and increases ambiguity to **30
   single / 32 multi / 24 unclassified**, so it is not used as a replacement.

Final stance: the headline lens remains primary; mechanism text is diagnostic
only. Neither lens writes DB labels, changes the **86-row** denominator, or
supports family-level inference. Read the arc in
[`ACCEPTED_FAMILY_OVERLAY.md`](stats/ACCEPTED_FAMILY_OVERLAY.md),
[`ACCEPTED_FAMILY_OVERLAY_REVIEW.md`](stats/ACCEPTED_FAMILY_OVERLAY_REVIEW.md),
and
[`ACCEPTED_FAMILY_SECOND_LENS.md`](stats/ACCEPTED_FAMILY_SECOND_LENS.md).

- **Event-date quality / anticipation risk** —
  `python scripts/event_date_quality_report.py --db-path events.db --json`
  Classifies each row's event-date anchor (clean filing vs partial
  anticipation vs scheduled signing vs thread sibling vs duplicate) with
  explainable rules, before any window is interpreted. Caution layer, not
  proof; see [`stats/EVENT_DATE_QUALITY.md`](stats/EVENT_DATE_QUALITY.md).

- **Staged-family coverage board** —
  `python scripts/staged_family_coverage_report.py --db-path events.db --json`
  One cross-family view of the 13 staged/no-paid candidates: anchor quality,
  family-packet coverage, local computability (cached rows are not the same
  as computable-at-date), and ranked no-paid next moves. Staged candidates
  never enter accepted denominators; see
  [`stats/STAGED_FAMILY_COVERAGE.md`](stats/STAGED_FAMILY_COVERAGE.md).

- **Representative transmission-case walkthrough** —
  `python scripts/transmission_case_walkthrough_report.py --db-path events.db --json`
  Renders a small, deterministic, outcome-diverse set of accepted cases
  (forced to include a support, a contradiction, and an unresolved/data-limited
  case) as full event → mechanism → named-assets → 1d/5d/20d reaction
  walkthroughs, reusing the J1 overlay, event-date-quality, track-record
  scoring, and event-study layers. Representative, not proof (n=1 per case);
  see
  [`stats/TRANSMISSION_CASE_WALKTHROUGH.md`](stats/TRANSMISSION_CASE_WALKTHROUGH.md).

- **Case-selection stress** —
  `python scripts/transmission_case_selection_stress_report.py --db-path events.db --json`
  Stress-tests the six walkthrough cases under alternative deterministic
  selection policies (family-first, outcome-first, anchor-quality-first,
  missingness-aware, reverse tie-break) **without changing the selector or the
  six cases**. Discloses tie-break sensitivity and an anchor-score doc/impl
  mismatch; no returns- or sector-based selection. See
  [`stats/TRANSMISSION_CASE_SELECTION_STRESS.md`](stats/TRANSMISSION_CASE_SELECTION_STRESS.md).

- **Sector-baseline availability** —
  `python scripts/sector_baseline_availability_report.py --db-path events.db --json`
  For each accepted row, reports whether a *suggested* sector ETF baseline is
  locally cached and **computable at the 1d/5d/20d event windows** (cached is
  not computable-at-date), plus the sector ETF's own raw window move as
  descriptive context. SPY stays the canonical abnormal-return benchmark; the
  sector is a hint, never a sector-relative abnormal return. See
  [`stats/SECTOR_BASELINE_AVAILABILITY.md`](stats/SECTOR_BASELINE_AVAILABILITY.md).

- **Research queue — staged candidates, no paid call** —
  `python scripts/research_queue_report.py --json`
  Read-only triage over the 13 staged `z1a_candidate_pack` candidates (excluded
  from every accepted denominator): per-candidate event-study readiness, the
  per-horizon point estimates already computable from the cache, source
  provenance, and near-duplicate collisions, with one deterministic review
  classification. It orders human review only — `ready_for_no_paid_review` is not
  approval for a paid run, and paid `/analyze` stays blocked. Staged candidates
  never enter accepted denominators.

- **Price-provider coverage** *(operational provenance)* —
  `python scripts/price_provider_coverage_report.py --json`
  Read-only: groups every cached bar by resolved market-data provider
  (`legacy_unknown` = provider not recorded at write time, not bad data). It
  never fetches, mutates, or calls a provider; this is data-provenance plumbing,
  separate from the research denominators above.

## Current Status

The tracked evidence track is complete through Phase 4. Beyond that track,
the Mission G historical research program (97 events across two separate
ledgers) is complete, and Mission H surfaces the completed record — the
[`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md) front door, the read-only
`GET /evidence/mission-g` contract, and the Evidence Overview card — without
adding any new research claim. The cohort-wide
methodology and the Phase 1–4 arc are documented at
[`evidence_artifacts/section_c_v2/phase_evidence_methodology.md`](evidence_artifacts/section_c_v2/phase_evidence_methodology.md)
and
[`evidence_artifacts/section_c_v2/phase_history.md`](evidence_artifacts/section_c_v2/phase_history.md).

The separate **Mission J** hindsight-controlled FOMC robustness program — the
asset/benchmark, timing/collision, and transmission-graph challenge to Mission
I's inherited one-day reading — is published and complete. Its record is
surfaced in the app on the **Evidence Overview** screen and through the
read-only, tracked-only `GET /evidence/mission-j` contract
(`mission-j-evidence-v1`), which parses the frozen `stats/J*` publications at
request time and adds no new research claim. The frozen source chain is
J0 → J1A → J1B → J2 → J3, summarized in
[`RESEARCH_OVERVIEW.md`](RESEARCH_OVERVIEW.md).

- **Phase 1** — a five-row freeze-candidate cohort
  (WHR / TXT / FSLR / RIO / LITE) is tracked at
  `evidence_artifacts/section_c_v2/freeze_candidate_evidence.json`. Each row
  carries a pre-registered canonical test at the claimed horizon h = 1
  with a BH-adjusted q-value frozen at the original five-row Phase 1
  denominator. Phase 1 q-values are never recomputed against any later
  scope.
- **Phase 2** — a closed five-row BH/FDR pool
  (BA / ALB / NVDA / AMAT / CF) is tracked at
  `evidence_artifacts/section_c_v2/phase2_pool_v1.json`. BA, ALB, and NVDA
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
  `evidence_artifacts/section_c_v2/rejection_log_summary_v1.json`.
- **Phase 4** — `GET /evidence/summary` exposes the tracked evidence
  layer as a read-only JSON view. The route reads only from
  `evidence_artifacts/section_c_v2/`; it does not read local operator
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
  artifacts (`evidence_artifacts/section_c_v2/`) and the three schema validators
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

The read-only report commands above recompute every archive
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
repair the 18 repaired events resolved on matched **raw** basis,
so the earlier "every compute-ready event is on matched *adjusted* basis"
no longer holds — but no row mixes flags, so no splice caveat applies.

The readiness report (`scripts/stat_validation_readiness_report.py`) runs
under an explicit **denominator lens** (`--lens accepted` | `--lens raw`,
AT1 2026-06-10):

- `--lens accepted` (the **default**) is the canonical hygiene-aware
  accepted-corpus analysis/coverage denominator: it excludes the
  non-analysis stages (`curated_intake`, `z1a_candidate_pack` staged
  candidates, `analysis_pending_review` quarantine) and the 71 AP3b
  `event_hygiene` synthetic-seed rows. This is the **same lens** as
  `scripts/event_study_coverage_report.py`, so the two reports share one
  denominator.
- `--lens raw` is an all-stage **diagnostic** data-coverage scan over every
  archive row, including the flagged seed rows, staged candidates, and the
  pending-review row. Diagnostic only — its counts must never be quoted as
  accepted-corpus numbers.
- Every payload carries a `denominator` metadata block (active lens,
  included/excluded stages, excluded override classes, per-class excluded
  and population counts) plus a `non_claims` block, so exclusions are
  disclosed rather than silent.
- Counts drift with every coverage repair, so re-run the commands for live
  figures rather than trusting any number frozen here:
  `python scripts/stat_validation_readiness_report.py --json --lens accepted --limit 0`
  (and `--lens raw`).

The dated per-run snapshots ("Current run" / "Earlier runs reported") and the
Batch-1 data-frontier note are kept out of this reviewer-facing README; re-run
the readiness command above for live figures.

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

## Next Roadmap

The tracked evidence track is closed at Phase 4; no new candidates, pools,
or validators are scheduled for it. The Mission G historical research
program is likewise complete, and Mission H (which surfaces that completed
record) adds no new research claim. Deferred
methodology lessons (CENX, NUE, NOC) are recorded separately in
`evidence_artifacts/section_c_v2/rejection_log_summary_v1.json` and are not
denominator members of any open pool. The public consumption surfaces for
completed evidence are the read-only `GET /evidence/summary` and
`GET /evidence/mission-g` routes.

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
of past, dated events and makes no claim about future returns.

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

For a minimal public API deploy on Render, use `render.yaml`. Render injects
`PORT` automatically. With no provider key the API boots with the
mock-analysis fallback (no billing, nothing persisted), which is the safe
default for a public demo.

**Do not expose a real provider key on a public deploy without the paid-route
guard.** The `/analyze` (and `/analyze/stream`) routes can make billed provider
calls, and they fail **closed**: when a real (billable) `ANTHROPIC_API_KEY` is
configured, a request is rejected with `403` unless **both**

- `ENABLE_PAID_ANALYSIS=true`, **and**
- `SECOND_ORDER_ADMIN_TOKEN` is set and the request sends a matching
  `X-Second-Order-Admin-Token` header

are present. A real key with no admin token therefore leaves the paid routes
locked, not open. Only set `ANALYSIS_PROVIDER` + the provider key on a public
deploy if you have also set `SECOND_ORDER_ADMIN_TOKEN` (and want paid analysis
enabled); otherwise leave the key unset and run the mock fallback.

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

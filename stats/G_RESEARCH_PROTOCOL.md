# Mission G research protocol (G0 contract, version g0-v1)

**Status:** versioned research contract. This document locks the Mission G
protocol BEFORE any G code, data acquisition, candidate discovery, or
comparison work exists. Future G slices must obey it; any change to a locked
item requires an explicit version bump (g0-v2, ...) with a logged rationale
and a reproducible re-run of anything derived under the old version. This
slice ships documentation only: no application code, no tests, no database or
cache access, no provider call, and no change to any existing research output
or denominator.

Grounding state at lock time: HEAD `7c1ba86` (main == origin/main); live
track record 86 accepted rows spanning 2026-04-03..2026-05-30 over only 19
distinct event dates; accepted coverage 94; event-study coverage 78/94; the
F3 canonical adjusted-preferred basis policy is shipped
(`event_study_validation.py`, `stats/BASIS_RESTATEMENT.md`). No G historical
evidence exists yet.

## 1. Mission and claim ceiling

Mission G expands genuinely independent historical evidence and attaches a
point-in-time, pre-event market-state vector to each event.

Mission G does NOT:

- claim natural market prevalence for any cohort, lane, or pooled set;
- eliminate survivorship bias (it measures and discloses attrition; missing
  historical data is presumptively era- and state-correlated);
- infer causality from cross-period or cross-state differences;
- reopen, extend, or merge the closed Phase 1 / Phase 2 FDR pools;
- merge historical G rows into the immutable 86-event live track-record
  denominator or any existing funnel number (180 / 94 / 86 / 78-of-94 / 13).

## 2. Four research objects

> **One storage substrate, separate denominator ledgers.**

All accepted evidence lives in the same live workbench; lineage fields, not
physical location, determine the one ledger a row counts in.

1. **Existing live track record (immutable).** The 86 accepted rows and their
   lineage are frozen; future genuinely live-ingested rows follow the existing
   rules. Rows without a sampling-lane marker are this lane by definition, so
   every existing denominator reproduces unchanged.
2. **Frame-complete historical evidence.** Historical rows drawn from an
   explicitly enumerable, independently auditable universe (section 3). Same
   workbench, own denominator ledger with its own funnel (frame N ->
   discovered -> identity-valid -> mechanically eligible -> promoted ->
   event-study available), displayed phase-separated from the live funnel.
3. **Designed contrast evidence.** Rows deliberately recruited to fill
   pre-specified comparison coverage. Same workbench, own denominator ledger,
   permanently labeled as designed recruitment. No prevalence claims of any
   kind.
4. **Analytical comparison sets.** Derived, versioned views assembled at G6
   under the locked comparison plan. Never stored as evidence rows; no
   denominator of their own; regenerable from cohort snapshot + plan version.

> **One event identity may have multiple discovery paths but exactly one
> denominator ledger.**

**Ledger precedence (frozen):** 1. existing live track record ->
2. frame-complete historical -> 3. designed contrast. If the same event
identity is discovered by a later path, the additional discovery path is
preserved in provenance, but the event is never duplicated and never moves to
a more convenient ledger. A designed-lane recruitment that turns out to match
a frame member counts in the frame ledger; a historical discovery matching a
live row counts in the live ledger.

## 3. Sampling-frame rule

"Frame-complete" language is permitted ONLY where the event universe can
actually be enumerated and independently audited (examples of admissible
frames: official decision calendars such as central-bank policy decisions,
cartel ministerial meeting calendars, official sanction registers). The frame
identifier and its version are recorded on every member.

Open-ended event families (broad geopolitical escalations, undefined supply
shocks, headline-driven classes with no registry) can NEVER receive
completeness language. They may enter designed contrast evidence only,
carrying an explicit non-enumerable-family limitation on every surface that
shows them, with claims restricted to conditional contrasts and representative
description.

**Pooling prohibition.** No statistic may pool across sampling lanes: no
pooled mean, no pooled outcome rate, no prevalence figure, no weighted
aggregate - weighted or unweighted - unless a future, separately versioned
phase establishes a real sampling frame and valid inclusion probabilities for
every pooled row. This prohibition is symmetric: the live track record itself
is a convenience window of one regime and supports no prevalence claim either.

## 4. Provenance contract

Minimum permanent information per G event (concepts, not a database schema;
implementation reuses the existing sidecar pattern established by the L2
`event_provenance` / `event_hygiene` side-tables):

- **sampling lane** - live_natural / frame_complete_historical /
  designed_contrast;
- **candidate source / frame identifier** - the versioned generation rule or
  frame (e.g. an official calendar id at a stated version);
- **selection rule version** - the locked protocol version in force at
  selection;
- **selection reason** - enumerated: frame_member / cell_coverage (with the
  target comparison cell) / live_ingestion;
- **source-pinned anchor provenance** - how the event date was pinned and its
  anchor-quality label (section 6);
- **all discovery paths** - every path that found this identity, not only the
  first;
- **primary denominator ledger** - the single ledger the row counts in
  (section 2 precedence);
- **non-enumerable-family flag** - where applicable (section 3).

This must be sufficient to answer, years later: how was this candidate
discovered; why was it selected; under which locked protocol; did a
comparison-cell need cause the recruitment; and what other discovery paths
found the same event.

## 5. Candidate identity and duplicate rule

Every discovery remains visible in the funnel. Obvious duplicate or
re-ingestion discoveries may be linked to the canonical identity, quarantined,
and excluded from advancement - but never silently deleted and never collapsed
out of discovery counts. The canonical event identity advances through the
pipeline exactly once. (This encodes the L2 lesson: cross-date re-ingestion is
a hygiene fact to record, not a row to erase.)

## 6. Date-anchor contract

Event-date quality is a first-class G gate, and the mission's highest-leverage
error channel: a wrong anchor corrupts BOTH the pre-event state assignment and
the reaction window, with correlated errors that no downstream control can
detect. (Precedent: 14 of the 86 live rows needed anchor repair in L1A/L1B.)

**Identity-valid candidate** (the only candidates that receive state or can
ever reach G6):

1. valid sampling-frame membership (or documented designed-lane source);
2. real source evidence that the event occurred;
3. a resolvable, source-pinned event date;
4. duplicate identity resolved per section 5.

Anchor quality uses the existing event-date-quality vocabulary
(`clean_discrete_anchor`, `partial_anticipation`, `scheduled_or_weak_anchor`,
`continuation_or_thread_sibling`, `duplicate_or_deferred`,
`manual_review_needed`). G0 admission rule (semantic, not numeric): no state
assignment or G6 eligibility for candidates whose anchor label is
`manual_review_needed` or `duplicate_or_deferred`; anticipation-class anchors
are admissible only with the anticipation limitation disclosed on every
comparison that includes them. Per-cell anchor-quality composition is part of
the G4 eligibility evidence.

## 7. G0 state menu (v1, frozen)

Five continuous, point-in-time, pre-event dimensions. Continuous values are
canonical and permanent; readable tags are secondary derived views.

1. **Recent Fed policy path** - net policy-rate change over one predeclared
   six-month lookback ending at the cutoff.
2. **Volatility state** - VIX level at the conservative pre-event cutoff, and
   its trailing 252-session percentile computed only from history available by
   that cutoff.
3. **Equity trend state** - SPY percentage distance from its 200-session
   moving average at the cutoff.
4. **Yield-curve state** - 2s10s spread level as available by the cutoff.
5. **Credit state** - high-yield OAS, the latest value publicly available by
   the cutoff.

No categorical tag thresholds are frozen in G0. G4 MAY: freeze tag cuts using
only the permitted outcome-blind structural evidence (section 8), or drop a
dimension that turns out to be unusable (vintage-unsafe, unavailable, unstable). G4 may
NOT: invent new lookbacks, search over alternative windows, or alter any
definition using returns or outcomes. If a v1 definition is unusable, the
default is omission of the dimension or a future versioned protocol change -
never a quiet substitution.

## 8. Two-freeze governance

**G0 freezes (this document):** the state variables and their finite
definitions (section 7); data-source contracts (section 10); allowed
calibration inputs; forbidden inputs; the list of eligibility quantities
(final analyzable N, unique event dates, date concentration, story
concentration, anchor-quality composition, retention, differential retention,
calendar span and overlap); governance and versioning rules; comparison-plan
shape (tiered conditional contrasts, full pre-specified cell list); and claim
tiers.

**G4 freezes (later, before any outcome is inspected):** the actual numeric
values - category cuts, minimum-N rules, concentration limits, warning
thresholds, and comparison-eligibility rules - calibrated ONLY from
outcome-blind candidate structure.

G4 may use only: occupancy; missingness; unique dates; concentration;
temporal distribution; mechanical attrition; classification attrition;
interpretability.

G4 may not use: AR; SAR; CAR; outcome labels; effect direction; significance;
any downstream market response.

No numeric G6 threshold is frozen in this document, deliberately: an
unsupported constant frozen now would be indistinguishable from a magic
number. The G4 freeze memo must enumerate every input consulted and is itself
a versioned artifact.

## 9. Outcome-blindness firewall

Outcome values MAY be mechanically produced inside existing code paths - the
event-study gate returns readout values as a side effect of any
availability/status check, and this protocol does not pretend otherwise.

The auditable rule: before the G4 final freeze, G-candidate outcome values
(AR / SAR / CAR / outcome labels / any market response) may not be

- shown to humans for design decisions;
- persisted into any candidate-selection artifact (ledger, exhibit, log,
  recruitment list, freeze memo);
- used for recruitment;
- used for state or tag definitions;
- used for thresholds;
- used for comparison eligibility.

Candidate artifacts before G4 must whitelist their fields (status, blocking
reasons, basis metadata, state vector, provenance - nothing outcome-shaped),
and the whitelist is testable. Any accidental outcome exposure is logged as a
protocol deviation in the permanent record - dated, with what was seen.
Deviations do not void the mission; concealing them would. For famous
historical events, blindness is procedural, not mental; the defense against
remembered outcomes is frame-completeness plus pre-registration, stated
plainly.

## 10. No-lookahead contract

**Conservative cutoff:** the last completed trading-session close before the
source-pinned event date (t-1 close). Disclosed limitations: an event early on
day t forgoes that morning's information; and for anticipated events (the
anticipation-class anchors of section 6) the t-1 state may already partially
reflect anticipation. State is pre-event market posture; it does not
establish a pre-information state.

For every state value:

- qualification depends on PUBLIC AVAILABILITY by the cutoff, not merely the
  observation date (a series value dated t-1 but published later does not
  qualify);
- lagged series use the latest value actually published by the cutoff;
- revised macro series require point-in-time vintage data (first-release
  values as of the cutoff);
- if vintage-safe history is unavailable for a dimension, the dimension is
  omitted rather than filled with revised hindsight data.

## 11. Mechanism-label comparability

Historical and existing events must be compared under ONE derived rubric, not
under their heterogeneous stored fields.

v1 contract:

- one deterministic, J1-compatible headline-based overlay (the whole-token
  rule classifier of `scripts/accepted_family_overlay_report.py::classify_headline`
  is the reference implementation) applied identically across all cohorts;
- taxonomy/rule version stored on every analytical set;
- the existing 86 rows' stored mechanism fields are never rewritten - the
  comparison label is a derived overlay only;
- multi-match remains an explicit bucket, excluded from single-mechanism
  cells; unclassified remains explicit, excluded from mechanism-keyed cells
  and counted on every exhibit;
- no event-level manual override: an event that "should" match requires a
  logged rubric amendment (version bump) reapplied to every cohort;
- rubric changes bump the taxonomy version and force reapplication and re-run
  of every derived view.

Classification attrition (rows lost to unclassified/multi-match) must be
measured by sampling lane, period, state, and source family - it is a third
attrition class, not a footnote.

## 12. Attrition contract

G measures three failure classes separately, each with its own ledger:

1. **identity failures** (section 6 gate: frame validity, source evidence,
   resolvable date, duplicates) - recorded with codes; no state computed,
   because state is undefined without a valid date; diagnosable at frame +
   approximate-era granularity, disclosed as coarser;
2. **mechanical failures** (ticker/price/benchmark/event-study eligibility) -
   state IS computed for every identity-valid candidate BEFORE this grinder,
   so mechanical casualties retain their state vector and differential
   attrition stays measurable; multiple failure codes are retained per
   candidate (first-failure-only encoding hides correlated failure structure);
3. **classification failures** (section 11).

The attrition report shape (per lane, per stratum, per era): candidate N ->
survivor N -> retention fraction -> failure-code composition -> state
distribution before/after -> era distribution before/after -> unique-date
counts before/after.

Failure codes explain HOW candidates failed; they do not and cannot prove that
attrition is ignorable. Missing historical data is presumptively correlated
with era and state; the report quantifies, it never absolves.

## 13. Time-drift rules (v1)

No narrative eras and no span constant are frozen in this document.

Every G6 comparison must disclose: the date span of each group; events by
calendar period per group; and whether the groups' date ranges overlap (a
binary fact requiring no threshold).

- Zero calendar overlap between compared groups -> automatic downgrade to
  descriptive-only, with the time-distribution table inline.
- Where overlap exists -> report an overlap-period sensitivity (the same
  contrast restricted to the overlapping span) whenever mechanically possible;
  if the overlap subset is too thin under the G4 rules, that fact IS the
  sensitivity result and is printed.
- Externally documented structural boundaries may be added only through a
  versioned protocol change citing independent justification. No
  narrative-era labels.

Cross-period differences are differences between periods; attribution among
market structure, participation, liquidity, information diffusion, index
concentration, and the mechanism itself remains unresolved, permanently.

## 14. G6 claim ceiling

G6 is conditional descriptive comparison. It makes no causal regime-effect
claims, publishes no p-values, no FDR figures, and no significance claims,
makes no cross-lane prevalence claims, and performs no hidden cell selection.

Every pre-specified comparison cell must be reported, including null-looking
results, insufficient-N cells (as insufficient), structurally empty cells
(empty by history, distinguished from empty by attrition), and cells carrying
attrition warnings.

## 15. Rejected wording register

The following phrases are REJECTED and may not appear in any G artifact
except, as here, to mark them rejected:

- "natural historical cohort" - rejected: "natural" smuggles a prevalence
  connotation; the correct object is the frame-complete historical cohort;
- "bias-free" / "free of survivorship bias" - rejected: attrition is
  measured and disclosed, never eliminated;
- "SCAR already implemented" - rejected as overstated; see
  `stats/G_STANDARDIZATION_SPEC.md` for the exact SAR/SCAR relationship;
- "raw cash-basis" - rejected: under the F3 policy the first lens is a
  hold-period total-return-basis quantity on adjusted closes, with a
  disclosed raw fallback;
- "no outcome is computed before G6" - rejected as procedurally unrealistic;
  replaced by the section 9 firewall;
- "24 months" - rejected as an unsupported span constant for time-drift
  triggering (section 13 uses structural disclosure instead).

## 16. Phase sequence (locked shape)

G0 protocol lock (this document) -> G1 dual-lane candidate inventory with
anchor pinning -> G2 gated state-series acquisition + state computation for
identity-valid candidates -> G3 mechanical eligibility grinder (casualties
retain state) -> G4 integrity + differential-attrition validation + final
numeric freeze -> G5 temp-DB verification + controlled promotion into the separate
ledgers -> G6 pre-specified conditional comparisons. Every data-acquisition
step is its own explicitly gated slice; nothing in G0/G1 touches providers,
databases, or caches.

## 17. Non-claims

- This protocol creates no evidence and changes no existing number, surface,
  denominator, or methodology document.
- Nothing here is an effective sample size, a p-value, or an FDR figure; the
  closed Phase 1 / Phase 2 pools stay closed and separate.
- Not a trading, prediction, or recommendation surface, and nothing here says
  anything about future returns of any asset.

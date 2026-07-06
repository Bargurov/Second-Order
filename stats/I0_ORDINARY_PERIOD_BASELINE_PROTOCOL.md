# Mission I0 - ordinary-period baseline protocol (locked, i0-v1)

Status: versioned research contract, locked BEFORE any ordinary-period
outcome value exists. A later implementation slice (Mission I1) executes
this protocol mechanically; any change to a locked item requires an
explicit version bump (i0-v2, ...) with a logged rationale. This document
ships alone: no code, no computed comparison, no DB/cache/provider
mutation.

## 1. Research question

Are the completed Mission G event windows unusual relative to eligible
ordinary non-event periods on the same frozen assets, response metrics,
horizons, and calculation rules?

Precisely: how do the response distributions that BEGIN at the 65 FOMC and
32 OPEC frozen event anchor sessions compare with the response
distributions that begin at eligible ordinary trading sessions of the same
era, computed by the same engine under the same eligibility gates - per
family, per metric, per horizon, never pooled across families?

## 2. Claim and non-claim boundary

Mission I is descriptive and comparative. It does not claim:

- that any event caused the observed market move;
- that an event window is predictive of anything;
- that any result is a trading indication of any kind;
- that ordinary dates estimate a counterfactual "what would have happened
  absent the event" (they are a reference distribution, not a
  counterfactual);
- that FOMC and OPEC form one pooled evidence sample;
- statistical significance: the calibration layer of section 14 produces
  placement percentiles, not p-values, and joins no FDR pool.

A null result - event windows looking broadly ordinary - is a valid and
reportable outcome of equal standing.

## 3. Inherited frozen contracts (reused, never reimplemented)

Mission I1 must reuse the following shipped contracts verbatim; creating a
second event-study methodology is prohibited.

1. Event universe: the 65 FOMC identities in
   `stats/G1A_FOMC_FRAME_INVENTORY.md` and the 32 OPEC identities in
   `stats/G1B_OPEC_DESIGNED_RESERVOIR.md` (canonical/none rows), parsed by
   the existing `scripts/g_state_acquisition.py` parsers. 97 events, 97
   unique source-pinned dates, ledgers separate. The G1B ledger serves a
   SECOND, separately-governed role in this protocol: its full discovery
   record (not just the 32 promoted identities) supplies the OPEC
   known-date exclusion register of section 8.
2. Event-date anchoring: `event_study_validation` anchors an event date to
   the LAST joint trading session at or before the source-pinned date
   (`_last_index_le` over the asset-and-benchmark common session list);
   these anchoring invariants are regression-pinned by the existing
   event-date divergence-audit tests.
3. Trading-session alignment: horizons are counted in joint sessions of
   the asset/benchmark pair; the readiness gates require at least
   ESTIMATION_WINDOW = 60 prior sessions on both series and forward cache
   through the business-day offset of the maximum horizon, with the
   engine's interior-gap guard (window gaps over 5 calendar days gate to
   insufficient).
4. Price basis (F3): matched adjusted/adjusted preferred, matched raw/raw
   as the only disclosed fallback, never a cross-basis pair.
5. Horizons: 1d / 5d / 20d exactly as shipped (`HORIZONS = (1, 5, 20)`).
6. SPY-relative abnormal return: BHAR-style hold-period difference vs
   SPY, beta fixed at 1 (per `stats/G_STANDARDIZATION_SPEC.md`).
7. Sector-relative abnormal return: identical arithmetic vs the frozen
   family sector ETF.
8. SAR: `abnormal_return / (sigma_ar_daily * sqrt(h))` with sigma from the
   60-session pre-window daily abnormal-return series (ddof = 1).
9. Transmission map (`g3-transmission-map-v1`): FOMC -> KRE / SPY / XLF;
   OPEC -> XOP / SPY / XLE. No event-specific ticker change.
10. Price substrate: the gitignored `g_state_cache/g3_price_cache.db`
    (KRE, XLF, XOP, XLE, SPY; 2017-01-01 .. 2026-06-30), rebuildable by
    the documented zero-cost G3 fetch.

## 4. Candidate baseline designs considered (three, compared outcome-blind)

- **Design A - all eligible ordinary sessions.** Every joint trading
  session of the event era that passes the engine-computability gates and
  the own-family exclusion rule enters the reference distribution.
- **Design B - deterministically matched ordinary sessions.** k control
  dates per event matched on calendar year and weekday.
- **Design C - deterministic pseudo-event calendar.** One placebo date at
  the midpoint of each same-family inter-event gap.

Assessment on outcome-blind properties only (diagnostics in section 5):

| property | A (all eligible) | B (matched k-per-event) | C (mid-gap placebo) |
|---|---|---|---|
| denominator (FOMC 1d/5d/20d) | 1816 / 1299 / 0 | 65k bounded by A | 64 / 64 / 0 |
| denominator (OPEC 1d/5d/20d, register exclusion) | 1903 / 1631 / 889 | 32k bounded by A | 31 / 31 / 31 |
| calendar coverage | all 8 era years at every feasible horizon | inherits A, thinner | gap midpoints only |
| overlap dependence | high at 5d/20d (handled, section 9) | lower but rule-dependent | minimal |
| event contamination | controlled by the exclusion rule | same rule needed | same rule needed |
| selection freedom (researcher degrees of freedom) | none | k and tolerance are free knobs with no structural basis | none, but only one placebo set |
| operator complexity | lowest | highest | low |
| reviewer legibility | "every ordinary session of the same era" | requires defending the matching rule | "one fake meeting per gap" |

**Frozen choice: Design A as the primary baseline.** It has zero
selection freedom, the largest and best-covered denominators, and the
plainest reviewer reading. Design B is rejected: its free parameters (k,
tolerance, matched factors) cannot be justified outcome-blind and solve no
identified design problem. Design C is rejected as a standalone baseline
(31-64 dates add nothing over A) - but its one virtue, matching the event
calendar's count and rhythm, is retained as the SHAPE of the calibration
layer (section 14), which effectively draws thousands of rhythm-preserving
pseudo-calendars instead of one.

## 5. Outcome-blind diagnostics used (dates and counts only)

Read-only probes over the G1 ledgers and the DISTINCT session dates of the
G3 price cache; no close value was selected, no return computed. Findings
that drive the design:

- Joint session frames: KRE/SPY/XLF and XOP/SPY/XLE each have 2,385 joint
  ADJUSTED sessions (2017-01-03 .. 2026-06-30) and IDENTICAL raw
  coverage; zero raw-only sessions. Event-era (2018-2025) sessions: 2,011
  per lane, 250-253 per calendar year.
- Anchors: 65 FOMC events -> 65 unique anchor sessions; 32 OPEC -> 32.
- Same-family anchor spacing (sessions): FOMC min 8 (the 2020 emergency
  pair), p25 29, median 30, p75 34, max 39 - the FOMC cycle is ~30
  sessions. OPEC min 19, median 42, max 222, with a monthly cluster
  (six gaps of 11-20 sessions) in 2024-2025.
- Cross-family proximity: EVERY OPEC anchor lies within 13 sessions of an
  FOMC anchor (median 9); 36/65 FOMC anchors lie within 20 sessions of an
  OPEC anchor. Scheduled ambient events are a property of every calendar
  window on both sides of any comparison.
- Eligible ordinary-session counts (era 2018-2025, >= 60 estimation
  sessions, +h forward sessions, symmetric +-h exclusion against the
  family's section-8 exclusion set): FOMC 1816 (1d) / 1299 (5d) /
  **0 (20d)**; OPEC under the 41-date known-date register (39 anchor
  sessions) 1903 / 1631 / 889 - versus 1915 / 1659 / 958 had only the 32
  promoted dates been excluded, a modest cost that removes every known
  tracked OPEC date from the reference. Per-year minimums: FOMC 226 (1d),
  157 (5d); OPEC 218 (1d), 138 (5d), 18 (20d - thin years disclosed).
- Uniform +-20 own-family exclusion: FOMC 0 at every horizon (a 41-session
  hole exceeds the 30-session cycle); OPEC 958.
- Cross-family exclusion at +-20: zero eligible dates in BOTH lanes at
  every horizon. At +-h it removes 20-37 percent of dates at 5d.
- Non-overlapping window blocks in Design A (eligible dates / h): FOMC
  ~1816 (1d) / ~259 (5d); OPEC ~1903 / ~326 / ~44 (20d).
- Single pre-declared sensitivity count: FOMC 20d under FORWARD-ONLY
  own-family exclusion (no own event inside [t, t+20]) = 659 dates, all 8
  years (min-year 75), ~32 non-overlapping blocks.

## 6. Selected primary baseline design

Design A: per family and per horizon, the ordinary reference set is every
joint trading session t of the event era that passes the section 7
eligibility gates and the section 8 exclusion rule. The reference is used
as a DISTRIBUTION (section 13), never as a set of independent draws.

## 7. Exact eligibility rules (symmetric with the event side)

A session t enters the horizon-h ordinary reference set of a family iff:

1. t is a joint session of the family's primary, SPY, and sector series
   under the F3 basis policy (adjusted/adjusted preferred; raw/raw
   fallback only; never cross) - identical to the event gate;
2. 2018-01-01 <= t <= 2025-12-31 (the event era; era symmetry);
3. at least 60 joint sessions precede t (SAR estimation window);
4. at least h joint sessions follow t within the cache;
5. the engine's interior-gap guard passes (as for events);
6. t survives the section 8 exclusion rule;
7. ALL FOUR response lenses are computable at t (single denominator per
   family x horizon, matching the event side, which is 97/97 all-lens).

Rules 1, 3, 4, 5, and 7 are exactly the shipped event gates; no side of
the comparison uses a looser rule than the other.

## 8. Event-exclusion rule (frozen, structurally derived)

**Rule: per-horizon symmetric exclusion with buffer = h against the
family's EXCLUSION SET.** Session t is ineligible for horizon h iff any
anchor e in the family's exclusion set satisfies
|session_index(t) - session_index(e)| <= h.

**The exclusion set is not the study denominator, and the two differ by
lane.**

- FOMC: the exclusion set IS the 65-event frame. The G1A frame is
  complete for the event class it enumerates (scheduled and unscheduled
  FOMC policy decisions), so "no frame event within +-h" genuinely means
  no known event of the studied class. Other Federal Reserve
  communications (minutes, speeches, facility announcements) are not
  FOMC policy decisions and remain ambient environment on both sides,
  exactly like all other world events.
- OPEC: the 32 promoted identities are a DESIGNED-CONTRAST denominator,
  not a frame, so they cannot by themselves certify that a date is free
  of known OPEC events. The exclusion set is therefore the separate
  **known-date exclusion register `opec-known-date-exclusion-register@
  i0-v1`**: all 38 dated source records of the G1B discovery ledger
  (including the five Conference/agreement-in-principle mirror dates and
  the held 2020-03-05 recommendation), the documented 2020-03-06
  non-agreement context date, and the two non-material official meeting
  dates the ledger names while excluding (2022-12-04, 2025-05-28) - 41
  calendar dates resolving to 39 anchor sessions. The register's
  coverage basis is the G1B reservoir contract's source-bounded
  completeness claim: applying the frozen rule to the bounded official
  source family (OPEC Conference, ONOMM, and V8 records at opec.org,
  2018-2025) reproduces the ledger.

**Exclusion-only guarantees (frozen):** register dates are never
denominator members; they never enter event results; they support no
prevalence claim; their only function is to prevent known OPEC event
windows from being labeled ordinary. The study denominator remains
exactly the 32 promoted identities.

**Residual limitation (disclosed, not waved away):** the tracked
register enumerates the official production-policy record, not every
OPEC-adjacent date. Routine 2021 monthly ONOMM confirmations and JMMC
sessions are described by the ledger's exclusion rule but not
individually dated in tracked material, and non-OPEC oil-supply events
(wars, strikes, accidents, unilateral national decisions) are outside
any OPEC register by construction. The OPEC reference pool is therefore
defined as "eligible sessions outside all known-register windows" -
never as proven OPEC-event-free. This residual is acceptable for a
DESCRIPTIVE comparison because (a) every date the frozen materiality
rule identifies as a material collective production-policy decision is
excluded, (b) the residual known class is, by that same rule,
non-material routine records, and (c) ambient non-OPEC events load both
sides of the comparison symmetrically, like the cross-family exposure
below. If Mission I1's results ever hinge on this residual, the
predefined `unstable difference` / `coverage-inadequate` interpretations
of section 16 apply - the residual may not be re-litigated post hoc.

Basis (not intuition): h is the minimal buffer that guarantees the
ordinary window [t, t+h] shares no session with any exclusion-set event
window [e, e+h] in either direction - forward contamination (event inside
the ordinary window) and backward contamination (ordinary window inside an
event's response window) are both excluded exactly, with nothing excluded
beyond what the horizon geometry requires. Alternatives inspected
(section 5): a uniform +-20 buffer annihilates the FOMC lane at ALL
horizons (41-session hole > 30-session cycle) - strictly worse coverage
with no added cleanliness at 1d/5d.

**Structural consequence, pre-declared: the FOMC-lane 20d comparison is
INFEASIBLE under this rule (0 eligible dates).** The modern calendar
contains no 20-session window that is 20 sessions clear of an FOMC
meeting. Mission I1 must report this cell as `structurally_infeasible`
with its empty funnel - it is a finding about the calendar, not missing
data, and no post-freeze buffer weakening is permitted to rescue it.

**Single pre-declared sensitivity (answers one design-risk question):**
is the FOMC-20d infeasibility purely the backward half of the buffer? The
sensitivity uses FORWARD-ONLY own-family exclusion (no own event inside
[t, t+20]; 659 dates, all 8 years). It is labeled `aftermath_inclusive`:
its windows may begin inside a prior meeting's response window, so it
contrasts event starts with starts scattered across the whole meeting
cycle INCLUDING aftermaths. Frozen boundaries: it is NOT the primary
ordinary baseline; it is NOT a member of the section-14 twenty-statistic
primary comparison family; and it is NOT a rescue of the missing FOMC 20d
cell - that cell's primary conclusion remains `structurally_infeasible`
regardless of what the sensitivity shows.

**Cross-family events are NOT excluded - frozen with evidence.** Every
OPEC anchor sits within 13 sessions of an FOMC meeting, so the event
windows themselves carry exactly the same ambient cross-family exposure
as any ordinary window; excluding cross-family proximity from the
reference but not from the events would break the symmetry rule of
section 7 (and, mechanically, +-20 cross exclusion leaves zero dates in
both lanes). Ambient scheduled events are part of the environment on both
sides; this is disclosed wherever results are shown.

## 9. Overlap and dependence handling

Adjacent ordinary start dates share up to (h-1)/h of their price path.
The protocol handles this dependence three ways, and never claims
independent observations:

1. The reference set enters the estimand only as an empirical
   distribution for percentile ranking (section 13) - no standard error,
   effective-N, or independence claim is ever attached to its size.
2. The funnel (section 17) must report, beside every reference count, the
   non-overlapping block count (eligible range / h; e.g. OPEC 20d: 889
   dates but only ~44 disjoint windows), so apparent size is never
   mistaken for information.
3. The calibration layer (section 14) draws pseudo-event PLACEMENTS on
   the same eligible calendar, so every calibration draw inherits exactly
   the same overlap structure as the real comparison - dependence cancels
   by construction rather than by assumption.

Falsifier F3 (section 15) additionally recomputes the estimand on a
deterministic non-overlapping decimation of the reference set.

## 10. Family separation

The two lanes share one construction RULE but nothing else: each family's
reference set is built on its own asset triple's joint session frame, its
own exclusion calendar, and is compared only against its own events. No
statistic, table, figure, or sentence may pool, sum, average, or rank
FOMC and OPEC together. The accepted-86 lane does not participate in
Mission I at all.

## 11. Price and missingness rules

- Required windows per date (both sides): 60 prior joint sessions and h
  forward joint sessions, per the shipped gates.
- Basis: F3 policy verbatim. Diagnostics show adjusted coverage equals
  raw coverage on every joint session (zero raw-only sessions), so the
  expected real split is all-adjusted on both sides; any raw/raw fallback
  is disclosed per date exactly as the event side disclosed it.
- Missing data: a date failing any gate simply does not enter that
  horizon's denominator, on either side, and the funnel records the loss
  per gate. No fill, no proxy, no interpolation.
- Delisted/proxy behavior: all five ETFs are alive through the cache end;
  if a future refetch loses coverage, dates gate out symmetrically on
  both sides and Mission I1 must fail loudly if the pinned session counts
  of section 18 no longer reconcile.
- All four lenses required per date (section 7, rule 7).

## 12. Response metrics

All four frozen Mission G lenses at all feasible horizons, inherited
unchanged: raw return, SPY-relative AR, sector-relative AR, SAR at 1d /
5d / 20d (FOMC 20d: primary cell structurally infeasible, section 8). No
metric is removed; no new metric is added. CAR remains unextracted, as in
G6A.

## 13. Primary estimand (exact)

For family F, metric m, horizon h:

- For each event e of F, compute its response y(e, m, h) by the shipped
  engine, and the ordinary reference multiset R(F, m, h) = { y(t, m, h) :
  t eligible under sections 7-8 }.
- The event's **magnitude percentile** is the mid-rank percentile of
  |y(e, m, h)| within { |r| : r in R(F, m, h) }:
  pct = (#{|r| < |y|} + 0.5 * #{|r| = |y|}) / |R|.
- The primary statistic is **MEMP(F, m, h): the median across F's events
  of the magnitude percentile.** Under ordinariness, MEMP is approximately
  0.5; MEMP near 1 means typical event-window magnitudes sit high inside
  the ordinary magnitude distribution.

Unit: percentile of an absolute response within the family's ordinary
absolute-response reference distribution. Denominators: the event count
(65 or 32) and the reference count from the section 17 funnel. Supporting
displays (fixed, uncurated): the full per-event percentile list per
family x metric x horizon, and the signed-percentile median beside every
MEMP (location read; same mid-rank convention without absolute values).
The phrase "events moved more" may never appear without the exact MEMP
value, its family, metric, horizon, and both denominators.

## 14. Inferential scope

**Descriptive primary; one tightly bounded calibration layer; no FDR
pool; no significance vocabulary.**

Calibration layer (pre-specified exactly; a placement-randomization
reference, conditional on the eligible calendar - not sampling
inference):

- Hypothesis family: exactly the 20 pre-listed statistics - MEMP for
  FOMC x 4 metrics x {1d, 5d} plus OPEC x 4 metrics x {1d, 5d, 20d}. All
  20 are always reported; there is no selection to correct for, and no
  FDR pool is created (the accepted-86 pools and the Mission G archive
  stay separate).
- Unit of analysis: one pseudo-event placement of the family's full event
  set.
- Procedure: B = 2,000 draws. Each draw places, for every calendar year,
  exactly as many pseudo-anchors as the family has real events that year
  (per-year count matching = the era-drift control of section 16),
  uniformly without replacement from that year's eligible ordinary
  sessions for the given horizon; the draw's MEMP is computed by the
  identical pipeline. The observed MEMP is reported as its percentile
  within the 2,000 calibration MEMPs.
- Dependence validity: every draw inherits the same overlapping-window,
  clustered-calendar structure as the real event set by construction;
  the comparison is placement-vs-placement, so overlap does not have to
  be modeled.
- B = 2,000 basis (numeric discipline): Monte-Carlo resolution only - the
  standard error of a reported calibration percentile is at most
  sqrt(0.25/2000) ~ 1.1 percentage points, adequate for the quartile
  statements of section 16 at roughly one minute of compute; the seed is
  fixed at 20180101 (the era start date, chosen before any outcome
  exists).
- Prohibited vocabulary for this layer: p-value, significant, confirmed,
  validated, rejected null. The output is "the observed MEMP sits at the
  Xth percentile of 2,000 era-matched placements."

## 15. Falsifiers (frozen; none may be added after results are visible)

- F1 leave-one-year-out: recompute each MEMP excluding each calendar
  year's events and ordinary dates; report min/max and whether
  sign(MEMP - 0.5) flips (flip conventions as in G6B; no new threshold).
- F2 leave-one-event-out: same, removing one event at a time.
- F3 overlap decimation: recompute each MEMP against the deterministic
  non-overlapping reference subset (every h-th eligible session, starting
  at the first); report the change and any sign flip.
- F4 cross-metric consistency: per family x horizon, count metrics
  agreeing on sign(MEMP - 0.5).
- F5 cross-horizon consistency: per family x metric, whether feasible
  horizons agree on sign(MEMP - 0.5).
- F6 calibration position: whether the observed MEMP falls inside the
  central 50 percent of its calibration distribution.

## 16. Era drift and predefined result interpretations

Era drift control: the calibration layer's per-year count matching (every
placement has the same year profile as the real events), plus a required
per-year MEMP table (descriptive, per family) and falsifier F1. No
volatility/regime/state matching is used - Mission G already showed broad
state conditioning is flat or fragile, and Mission I does not recreate it.

Predefined interpretations (per family; evaluated on the primary cells):

- **Broadly ordinary**: at least 3 of 4 metrics at every feasible primary
  horizon have F6 inside the central 50 percent and no F1/F2 sign flip.
- **Narrow difference**: exactly one metric or one horizon has F6 outside
  the central 90 percent with no F1/F2 flip - reported as bounded and
  metric- or horizon-specific, never generalized.
- **Unstable difference**: any cell outside the central 90 percent that
  F1 or F2 flips - reported as calendar- or event-driven, not a
  difference.
- **Overlap-dependent**: F3 flips the sign of (MEMP - 0.5) for the cell -
  reported as too overlap-dependent to interpret.
- **Family asymmetry**: interpretations differ between FOMC and OPEC -
  reported per family, never averaged.
- **Structurally infeasible**: the FOMC 20d primary cell, and any cell
  whose funnel empties - reported with its empty funnel.
- **Coverage-inadequate**: any OPEC 20d year contributing fewer than the
  disclosed minimum (18) is flagged in the per-year table; if F1 shows
  those years drive the read, the unstable-difference label applies.

The phase is justified by whichever outcome occurs; a fully ordinary
result is a first-class publishable finding of the workbench.

## 17. Denominator and funnel reporting requirements

Mission I1 must publish, per family x horizon: era sessions -> estimation
survivors -> forward survivors -> exclusion-set survivors -> final
reference N; the non-overlapping block count; the per-year reference
distribution; the event N (65 / 32); and every gate's casualties. The
funnel must also state each lane's exclusion-set size beside its study
denominator (FOMC: frame = exclusion set = 65; OPEC: denominator 32,
register 41 dates / 39 anchor sessions) so a reviewer sees that
exclusion breadth and evidence membership are different things. The
FOMC 20d funnel is published with its zero. Nothing is hidden or merged.

## 18. Reproducibility limits (stated plainly)

- The event universe and this protocol are tracked; a fresh clone can
  read both and audit every rule.
- Execution requires the LOCAL price substrate
  (`g_state_cache/g3_price_cache.db`, gitignored), rebuildable by the
  documented zero-cost G3 fetch; Yahoo adjusted closes can drift on
  refetch, so regenerated numbers may differ slightly from an original
  run - runs must print their substrate provenance.
- Session-frame pins for fail-loud drift detection: joint ADJ sessions
  2,385 per lane (2017-01-03 .. 2026-06-30); era sessions 2,011; if these
  counts do not reconcile at run time, Mission I1 must refuse to run
  rather than silently recompute on a different calendar.
- The events.db workbench is NOT required: the event dates come from the
  tracked G1 ledgers.
- Full fresh-clone reproducibility is therefore NOT claimed: code and
  rules yes, price inputs provider-dependent.

## 19. Rejected alternatives (and why)

- Using the 32 designed-contrast dates as if they defined OPEC-event-free
  ordinariness: rejected - the 32 are a recruitment denominator with no
  completeness claim, and the tracked discovery ledger itself contains
  known OPEC dates outside them (mirrors, the held 2020 non-agreement,
  named non-material meetings) that would otherwise have entered the
  "ordinary" pool; corrected by the section-8 exclusion-only register.
- Matched k-per-event controls (Design B): free parameters with no
  outcome-blind basis; solves no identified problem under a
  reference-distribution estimand.
- Single mid-gap placebo calendar (Design C): 31-64 dates, no coverage
  advantage; superseded by the 2,000-placement calibration layer.
- Uniform +-20 exclusion buffer: destroys the FOMC lane entirely and
  caps OPEC with no cleanliness gain at 1d/5d.
- Cross-family exclusion: structurally impossible (+-20 leaves zero dates
  in both lanes) and asymmetric in principle - the event windows carry
  the same ambient cross-family exposure as any ordinary window.
- Volatility / policy-regime / oil-regime matching: recreates Mission G's
  failed state conditioning inside the baseline; rejected.
- Weekday or month matching: no identified design problem; anchor-weekday
  composition is disclosed in the funnel instead.
- New response metrics (e.g. CAR-based or range-based): no unresolved
  question requires them; presumed rejected per the task rule.
- Event-count-weighted pooling of FOMC and OPEC: prohibited by the
  standing pooling ban.
- Spacing-enforced placements in the calibration draw: adds a constraint
  with no identified failure mode under per-year count matching; plain
  uniform-within-year placement is simpler and sufficient.

## 20. Freeze statement

Protocol i0-v1 is LOCKED as written. The design was chosen using only
event dates, trading calendars, session counts, spacing, coverage,
overlap arithmetic, and price-availability facts. Before publication of
this protocol, the OPEC exclusion set was corrected from the 32 promoted
identities to the section-8 known-date register - a pre-push,
outcome-blind amendment made from the tracked G1B discovery ledger and
calendar geometry alone; the study denominators, design, estimand,
calibration, and falsifiers are unchanged by it.

No ordinary-period outcome comparison was computed or inspected before
this protocol freeze.

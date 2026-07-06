# Mission J0 - hindsight-controlled FOMC robustness constitution (locked, j0-v1)

Status: versioned research contract, locked BEFORE any Mission J robustness
outcome exists. Mission J attacks the already-observed Mission I FOMC 1d
result; this document freezes every decision rule - response mathematics,
edge adjudication, proxy panels, measurement classes, benchmark model,
timing windows, collision boundaries, claim tiers, and stop conditions -
before any new asset outcome, rate-series outcome, benchmark result,
pre-event drift result, collision-subset result, or transmission-graph
result is inspected. Any change to a locked item requires an explicit
version bump (j0-v2, ...) with a logged rationale. This document ships
alone: no code, no computed comparison, no DB/cache/provider mutation, no
new outcome value.

## 1. Mission J research question

Does the completed Mission I FOMC 1d finding - a broad, perturbation-stable
elevation in one-day response magnitude on the frozen KRE / XLF / SPY
specification (`stats/MISSION_I_CLOSEOUT.md` section 2) - survive
prospectively frozen robustness challenges to its asset choice, benchmark
treatment, timing placement, and collision environment, and does a frozen
economic-role transmission graph carry that elevation beyond the single
inherited asset?

Mission J is descriptive and comparative, exactly as Mission I was. A
weakened, localized, or broken result is a valid and reportable outcome of
equal standing with a surviving one. An honest downgrade is a successful
research outcome.

## 2. Critical honesty statement

Nothing selected in J0 is historically ex-ante relative to the 2018-2025
Mission I sample. The project authors, operator, and language models
already know the historical period and have already seen the Mission I
FOMC 1d result. Every new same-sample choice in this document is therefore
a **post-outcome, prospectively frozen robustness hypothesis**: frozen
before its own new outcome is inspected, but selected by researchers who
have seen the inherited outcome.

Same-sample Mission J evidence may strengthen, weaken, localize, or break
the Mission I interpretation. It may not be described as independent
historical confirmation, and no Mission J artifact may use
"independent confirmation" language for same-sample results.

## 3. Outcome-exposure constitution

### 3.1 Class A - inherited outcome-exposed specification

Everything whose FOMC historical result has already appeared in project
artifacts. Allowed claim: **"inherited Mission I specification"** (or
"inherited Mission G specification" where applicable). Never: "newly
selected without outcome knowledge."

### 3.2 Class B - post-outcome, prospectively frozen robustness hypothesis

Every new asset, proxy, rate series, curve series, benchmark model, graph
edge, timing test, and collision test introduced in J0 whose new Mission J
result has not yet been inspected. Allowed claim: **"prospectively frozen
before the new robustness outcome was inspected."** Same-sample evidence
from this class remains **post-outcome robustness evidence**, never
independent confirmation.

### 3.3 Class C - genuinely untouched or prospective evidence

**No Class C sample is declared to exist.** Candidates were examined and
rejected:

- FOMC decisions in 2026 H1 sit inside the local price frame
  (2017-01-01 .. 2026-06-30), inside the authors' ambient market
  knowledge, and outside the frozen 2018-2025 era and 65-event frame.
  They are NOT Class C: not project-inspected, but ambient-exposed and
  frame-external.
- Only FOMC decisions occurring after this freeze (2026-07-06) could
  qualify as prospective Class C evidence, and only under a future
  protocol that freezes their handling before they occur. J0 makes no
  commitment that such a sample will be used.

Allowed future claim ("prospective or untouched evidence") activates only
after such a sample genuinely exists and remains uncontaminated.

### 3.4 Narrow exposure inventory (FOMC-related items only)

Read-only inventory over tracked artifacts. "Inspected?" means a historical
FOMC-related outcome value for the item appears in project artifacts.

| item | role / type | prior project use | inspected? | class | allowed future claim |
|---|---|---|---|---|---|
| KRE | primary asset | `g3-transmission-map-v1`; G6 manifest; Mission I 20-cell family + 904-row per-event surface | yes | A | inherited Mission I specification |
| SPY | market benchmark; raw-close trend state | same; `spy_trend_ma200` state | yes | A | inherited Mission I specification |
| XLF | sector benchmark | same; sector-relative AR component | yes | A | inherited Mission I specification |
| raw_return, spy_relative_ar (beta-1 BHAR), sector_relative_ar, sar | response metrics | `stats/G_STANDARDIZATION_SPEC.md`; Mission I | yes | A | inherited Mission I specification |
| beta-fixed-at-1 benchmark treatment; 60-session SAR sigma | benchmark treatment | shipped engine; Mission I | yes | A | inherited Mission I specification |
| FOMC 1d/5d MEMPs, calibration percentiles, falsifier battery, per-event percentiles (65 events) | statistics | I2B / I2C-A / I2C-B | yes | A | inherited Mission I specification |
| fed_policy_path (target-range midpoint, 6-month net change) | state variable | G2/G4 substrate; G6A/G6B comparisons | yes (state-conditioned results) | A | inherited Mission G specification |
| vix_level_percentile | state variable | same | yes | A | inherited Mission G specification |
| spy_trend_ma200 | state variable | same | yes | A | inherited Mission G specification |
| curve_2s10s LEVEL at pre-event cutoff | state variable | same (G6A correlations; G6B calendar-time reads) | yes, as a state variable | A (as state) | inherited Mission G specification |
| credit_hy_oas | era-bounded secondary state | G4 secondary; G6B confound reads | yes | A | inherited Mission G specification; not used in Mission J |
| XOP / XLE | OPEC-lane assets | Mission G/I OPEC lane | yes (OPEC lane) | A | out of Mission J scope (FOMC-only mission) |
| curve_2s10s CHANGE over a response window | new response statistic | none | no | B | prospectively frozen robustness hypothesis (underlying series Class A as a state; the change statistic is new) |
| 2-Yr Treasury CMT yield change over a response window | new response statistic | none (series parsed for the 2s10s state, level never reported) | no | B | prospectively frozen robustness hypothesis |
| SHY | rates-role investable proxy | app-layer live market-context code only (asset-class maps, credit-regime composer); no FOMC event-window result in any tracked artifact | no | B | prospectively frozen robustness hypothesis |
| IAT | regional-bank alternate | none anywhere in tracked artifacts | no | B | prospectively frozen robustness hypothesis |
| KBE | bank-ETF alternate | app-layer ticker pools only; no FOMC event-window result | no | B | prospectively frozen robustness hypothesis |
| VFH | broad-financials alternate | none anywhere in tracked artifacts | no | B | prospectively frozen robustness hypothesis |
| rolling 252/20 OLS market-model AR | new benchmark treatment | none | no | B | prospectively frozen robustness hypothesis |
| pre-event drift windows [-5,-1], [-20,-1] | timing statistics | none (no tracked FOMC pre-event drift result exists) | no | B | prospectively frozen robustness hypothesis |
| collision tags and subsets on the exact 1d interval | collision statistics | none | no | B | prospectively frozen robustness hypothesis |
| fed funds futures / OIS | ideal repricing measure | none; no acquisition capability in the repo | no | (unavailable; section 8) | external source support required before implementation |

Graph-like prior claims: the only tracked FOMC transmission language is the
`g3-transmission-map-v1` interpretation line ("policy decision -> policy
path / funding and curve conditions -> regional-bank equities",
`stats/G3_MECHANICAL_ELIGIBILITY.md` section 1). That rationale is
inherited; no edge-level adjudicated outcome exists anywhere, so all edge
outcomes in Mission J are Class B.

## 4. Frozen node-state mathematics

Mission J never judges a node visually. Forbidden vocabulary for node
reads: "looks active", "large move", "clear reaction", any SAR cutoff
(no `SAR > 1.5` or any other magnitude threshold is introduced), and any
post-chart analyst judgement. All node reads use the inherited normalized
Mission I response language below.

### 4.1 Frozen node-level quantities

For measurement n (a frozen proxy/series of a role) and frozen response
window w (section 10 notation):

- **Event magnitude percentile.** For event response y_e and ordinary
  reference multiset R_(n,w) (duplicates kept):

  `p_(e,n,w) = ( #{ |r| < |y_e| } + 0.5 * #{ |r| = |y_e| } ) / |R_(n,w)|`

  Exact ties contribute one half each. This is the I0 section-13 / I2B
  mid-rank rule verbatim.

- **Node MEMP.** `M_(n,w) = median over events of p_(e,n,w)`.

- **Placement calibration position.** `C_(n,w)` = the mid-rank percentile
  of the observed `M_(n,w)` within its frozen era-matched placement
  distribution, under the I2C-A semantics verbatim: B = 2,000 placements;
  fixed seed 20180101; per-year event-count matching on the anchor-session
  year; uniform draws without replacement from that year's eligible
  ordinary pool; one drawn calendar reused across the cell's metrics;
  reference percentiles self-included per the fixed-R definition; the
  observed MEMP external to the 2,000-placement denominator. The per-year
  vector matched is the year vector of the events actually available to
  that lens (section 9.6), so calibration always matches the compared
  sample. No p-values, no significance vocabulary, no FDR pool.

### 4.2 Frozen four-state node classification

Uses the established Mission I central-50% boundaries. Per measurement,
computed once from the full-sample pair (M, C):

- **State A - ELEVATED.** Exactly: `M > 0.5` AND `C > 0.75`.
  Interpretation: response magnitude is above ordinary-period central
  tendency and lies in the upper side of the frozen placement calibration
  distribution.
- **State B - ORDINARY / UNRESOLVED.** Exactly: `0.25 <= C <= 0.75`,
  regardless of whether M is slightly above or below 0.5. An M of 0.53,
  0.51, or 0.48 with C inside the central 50% is never narrated as a
  special response.
- **State C - LOWER-MAGNITUDE.** Exactly: `M < 0.5` AND `C < 0.25`.
  Interpretation: response magnitude is descriptively lower than its
  ordinary-period reference and lies on the lower side of the placement
  distribution. Never called negative response, suppression, or reversal.
- **State D - DISCORDANT.** Everything else: `M <= 0.5` with `C > 0.75`;
  `M >= 0.5` with `C < 0.25`; including M exactly 0.5 with C outside the
  central 50%. Interpretation: the frozen response measures do not support
  a single directional classification. No rescue rule exists.

Exhaustiveness (frozen): State B claims all outcomes with C in
[0.25, 0.75]. Outside that interval, C > 0.75 splits into A (M > 0.5) and
D (M <= 0.5); C < 0.25 splits into C-state (M < 0.5) and D (M >= 0.5).
Every (M, C) pair therefore receives exactly one state.

Only state-bearing primary statistics (section 13) receive these states.
The frozen descriptive timing diagnostics (sections 10 and 13) have no
valid ordinary reference or calibration under the frozen design and
receive no node state.

### 4.3 Boundary discipline

The interval `[0.25, 0.75]` is inclusive: C exactly 0.25 or exactly 0.75
is ORDINARY / UNRESOLVED. These boundaries may not change after any new
result appears.

### 4.4 Stability is an overlay, not a state rewrite

Every Mission J state-bearing cell carries the inherited perturbation
overlays: F1-style
leave-one-year-out, F2-style leave-one-event-out, and F3-style canonical
overlap decimation (greedy earliest-first disjoint windows on the eligible
session indices, starts >= span+1 apart), with direction
`sign(MEMP - 0.5)` and the frozen G6B flip convention (`sign(0) = 0`; a
flip requires strict opposite signs). As in I2C-B, perturbations re-rank
the MEMP; calibration percentiles are not recomputed per perturbation.
Overlays never change a node's primary state. Reporting form:
"ELEVATED + stable under X + fragile under Y". No classification threshold
may move to rescue a fragile result.

## 5. Frozen edge-state mathematics

The graph is never read visually. For a frozen edge `A -> B`, adjudication
uses the frozen PRIMARY measurement's node state of each role (alternates
inform role-level modifiers, section 6.5, never edge states) plus the
measurement-adjudicability rules of section 7.

Upstream reading (frozen, three-valued): before edge states are assigned,
every upstream role receives exactly one reading:

- **ACTIVATED**: primary measurement State A (ELEVATED), and either the
  primary is class M1/M2 (it stands alone) or the role carries at least
  the ROLE-CONSISTENT modifier (the M3-primary corroboration rule).
- **NOT ACTIVATED**: primary measurement State B or State C.
- **UNRESOLVED**: primary measurement State A with an M3 primary whose
  role modifier is below ROLE-CONSISTENT; primary measurement State D; or
  a primary unusable at run time.

This conservative three-valued partition is frozen now, before outcomes,
and the critical case is fixed explicitly: an M3-primary upstream at
State A WITHOUT the ROLE-CONSISTENT modifier is upstream-UNRESOLVED and
its edges are MEASUREMENT UNRESOLVED - a measurement-corroboration
failure, never PROPAGATED, never TRANSMISSION BREAK, never UPSTREAM NOT
ACTIVATED, and never DOWNSTREAM WITHOUT UPSTREAM (an uncorroborated
single-proxy elevation is not evidence that the upstream role is quiet,
and not evidence that it is active).

Downstream adjudicability (frozen, per claim type): every path-level
positive or negative edge claim requires sufficient measurement
adjudicability for the downstream economic role.

- A downstream role supports an **ELEVATED edge claim** iff its primary
  measurement is State A and either the primary is a usable M1/M2 (it
  stands alone) or the role carries at least the ROLE-CONSISTENT
  modifier (the M3 corroboration rule).
- A downstream role supports a **NON-RESPONSE edge claim** iff its
  primary measurement is State B or State C and either the primary is a
  usable M1/M2 (section 7 Route A) or section 7 Route B is satisfied.
- A downstream primary at State D, an unusable primary, or a measurement
  disagreement that blocks the required support leaves the edge
  MEASUREMENT UNRESOLVED.

Measurement-governance symmetry (frozen): Mission J does not require
corroboration only for failures while accepting single-proxy successes.
For M3 downstream roles, an elevated edge claim and a non-response edge
claim both require the predeclared role-level measurement support
appropriate to their claim. (This is a measurement-governance rule, not a
statistical-symmetry claim.) The same measurement skepticism applies to
apparent success and apparent failure.

Edge adjudication never downgrades or rewrites a node state. A single
elevated M3 primary remains fully visible at node level as an
asset/proxy-specific ELEVATED measurement, displayed beside its
alternates and its role modifier, while the edge reports MEASUREMENT
UNRESOLVED. Intended honest output, for example: KRE ELEVATED; IAT
ORDINARY / UNRESOLVED; KBE ORDINARY / UNRESOLVED; role modifier
PROXY-SPECIFIC; edge MEASUREMENT UNRESOLVED.

The five edge states (frozen; no sixth category may be created after J1
results are visible):

1. **PROPAGATED.** Upstream reading ACTIVATED; downstream supports the
   ELEVATED edge claim (usable M1/M2 primary at State A, or M3 primary at
   State A with the role at least ROLE-CONSISTENT). Allowed wording: "the
   frozen upstream and downstream roles show aligned elevated-response
   states." Never: causality or transmission proven. A single M3
   elevation without the role-level corroboration can never produce this
   state.
2. **TRANSMISSION BREAK.** Upstream reading ACTIVATED; downstream
   supports the NON-RESPONSE edge claim (primary State B or State C, with
   a usable M1/M2 primary under Route A or with Route B satisfied).
   Allowed wording: "the predeclared downstream role did not carry the
   upstream elevated-response state under the frozen measurement rule."
3. **UPSTREAM NOT ACTIVATED.** Upstream reading NOT ACTIVATED; downstream
   primary State B or State C (no break claim is considered, so Route B
   support is not required). Status wording: "edge not adjudicated
   because the frozen upstream activation condition was not met."
4. **DOWNSTREAM WITHOUT UPSTREAM.** Upstream reading NOT ACTIVATED;
   downstream supports the ELEVATED edge claim. Status wording:
   "downstream response unsupported by the frozen upstream path." No path
   retrofitting. A single uncorroborated M3 elevation can never produce
   this state.
5. **MEASUREMENT UNRESOLVED.** Any remaining case: upstream reading
   UNRESOLVED; downstream primary State D or unusable (regardless of the
   upstream reading); M3 downstream primary at State A with the role
   below ROLE-CONSISTENT (regardless of the upstream reading - never
   PROPAGATED, never TRANSMISSION BREAK, never UPSTREAM NOT ACTIVATED,
   never DOWNSTREAM WITHOUT UPSTREAM); M3 downstream primary at State B
   or C without Route B while upstream is ACTIVATED (a break claim is
   considered but unsupported); or a measurement disagreement blocking
   the required support. This state is not a transmission break.

Exhaustiveness and mutual exclusivity (frozen; evaluated in this exact
order, so the branches cannot overlap):

1. **Upstream reading UNRESOLVED** -> MEASUREMENT UNRESOLVED, regardless
   of downstream.
2. **Downstream cannot support the edge-level claim under its frozen
   M-class/panel rule** -> MEASUREMENT UNRESOLVED: downstream primary
   State D or unusable (regardless of upstream); M3 downstream primary at
   State A with the role below ROLE-CONSISTENT (regardless of upstream);
   M3 downstream primary at State B/C without Route B while upstream is
   ACTIVATED (a break claim is considered but unsupported); blocking
   measurement disagreement.
3. **Adjudicate the remaining cases.** Upstream ACTIVATED: downstream
   supports the ELEVATED claim -> PROPAGATED; downstream supports the
   NON-RESPONSE claim -> TRANSMISSION BREAK. Upstream NOT ACTIVATED:
   downstream supports the ELEVATED claim -> DOWNSTREAM WITHOUT UPSTREAM;
   otherwise (downstream primary State B/C; no break claim is considered,
   so Route B support is not required) -> UPSTREAM NOT ACTIVATED.

The upstream reading is a total function (primary State A splits by the
corroboration rule into ACTIVATED or UNRESOLVED; State B or C gives NOT
ACTIVATED; State D or an unusable primary gives UNRESOLVED), and for each
reading the downstream cases above are disjoint and cover every
possibility - State A (claim supported or not), State B/C (claim
supported or not), State D, and unusable - so every possible combination
maps to exactly one of the five edge states, and no sixth state exists.

## 6. Proxy-panel constitution

True historical blindness is impossible and is not claimed. The design is:
post-outcome proxy selection, prospectively frozen before new proxy
outcomes are inspected.

### 6.1 Nodes are economic roles, not tickers

The graph is `FOMC -> economic role -> measurement panel`, never
`FOMC -> ticker -> ticker`. Tickers and series are measurement
instruments of a role.

### 6.2 Frozen panels

Every measurable role carries a frozen panel (section 12 node table):
one primary, plus alternates where defensible. Where only one or two
defensible measurements exist, that is stated and adjudicability is
downgraded accordingly; no weak proxy is added merely to reach three.
The policy/rates-repricing role and the broad-financial-sector role each
have exactly one defensible alternate (section 12) and that limitation is
frozen rather than padded; the curve-shape observable is a distinct
economic construct, not a rates-panel member (section 12.2).

### 6.3 Ordered selection criteria (as applied)

1. conceptual directness to the economic role;
2. source and data quality;
3. timestamp and temporal alignment;
4. historical coverage;
5. implementation feasibility.

Forbidden criteria - none of these was used and none may ever be used:
historical volatility; strongest past reaction; visual responsiveness
around FOMC; preservation of the Mission I result; graph clarity.
Historical performance is never a valid proxy-selection rationale.

### 6.4 Primary is frozen; no proxy rescue

The primary measurement is the adjudication anchor. Alternates are
corroboration or disagreement evidence, never replacement candidates. If
the primary fails and an alternate succeeds, the frozen report is: "the
frozen primary measurement did not support the role; alternate
measurements produced a different result." All frozen proxies must be
displayed in J3 - never only the successful proxy, the largest response,
or the proxy closest to a preferred mechanism story.

### 6.5 Role-level evidence modifiers (descriptive, never scored)

- **PROXY-SPECIFIC.** Only one frozen measurement of the role shows the
  relevant state.
- **ROLE-CONSISTENT.** The primary and at least one predeclared alternate
  of a different measurement design show the same relevant state.
- **BROAD MEASUREMENT CONSISTENCY.** All usable frozen measurements of the
  role agree.
- **MEASUREMENT DISAGREEMENT.** Primary and alternates do not support one
  common role-level reading.

"Relevant state" means the same section-4.2 state letter under each
measurement's frozen lens. Modifiers are reported side by side and never
combined into a score.

## 7. Measurement adjudicability constitution (M1/M2/M3)

A failed proxy is not automatically a failed mechanism.

- **M1 - direct or near-direct market measure.** E.g. a direct
  rate-repricing instrument (fed funds futures / OIS-type representation),
  with defensible source, timestamp, coverage, and contract treatment.
- **M2 - economically close official or market series.** E.g. official
  Treasury CMT yield and curve series. Known limitations: daily frequency,
  fixing/timestamp methodology, market-calendar alignment.
- **M3 - investable proxy.** ETFs and listed instruments approximating a
  role. Known limitations: duration construction, liquidity, portfolio
  mechanics, rebalancing, fund structure.

Frozen adjudication rules:

- One M3 non-response cannot adjudicate mechanism failure. Allowed claim:
  "this investable proxy did not show the frozen response state." Never:
  "the economic mechanism failed."
- One M3 elevated response cannot by itself support a mechanism-level
  claim. Allowed claim: "asset/proxy-specific elevated response."
- A TRANSMISSION BREAK may be adjudicated only if either:
  - **Route A:** the downstream role has a usable M1 or M2 measurement
    under this frozen protocol; or
  - **Route B:** at least two predeclared M3 measurements of meaningfully
    different measurement design agree on the relevant downstream
    non-response state.
  Otherwise the edge is MEASUREMENT UNRESOLVED.

A role is never called adjudicable merely because a ticker exists; the
node table (section 12) records adjudicability per role from the frozen
panel and this section's routes.

## 8. Read-only data-readiness inventory

Inventory basis (all read-only; no provider fetch, no outcome value, no
return computed, no proxy compared or ranked): tracked artifacts
(`stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md` sections 3/18,
`stats/G2_STATE_SOURCE_READINESS.md`, `stats/G3_MECHANICAL_ELIGIBILITY.md`
section 7), the gitignored cache metadata (`g_state_cache/
g3_price_meta.json`; the acquisition script's series contracts), and
source semantics already documented in the repo.

| measurement | class | provider / source | frequency | documented coverage | timestamp semantics | adjustment basis | key risks | local availability |
|---|---|---|---|---|---|---|---|---|
| KRE, XLF, SPY daily closes | M3 | Yahoo public chart endpoint (documented zero-cost G3 fetch) | daily | 2017-01-01 .. 2026-06-30; 2,385 joint ADJ sessions; era 2,011 | exchange close | adjusted-preferred; matched raw/raw fallback (F3) | adjusted-close drift on refetch (disclosed in I0 s18) | PRESENT (`g_state_cache/g3_price_cache.db`, meta-pinned) |
| IAT, KBE, VFH, SHY daily closes | M3 | same documented path | daily | expected full-era (all four ETFs predate 2017); to be verified dates-only at acquisition | exchange close | same F3 policy | same drift risk; availability unverified until fetched | NOT PRESENT; acquisition required in J1, cached and frozen before any outcome inspection |
| 2-Yr Treasury CMT yield level | M2 | official U.S. Treasury daily yield-curve CSVs (existing parser already reads the "2 Yr" column) | daily (Treasury business days) | source: full era; local cache holds only the derived 2s10s spread (2016-06 .. 2025-12) | next_day publication class (frozen in G2); observation dated at market day | level in percentage points; no adjustment basis | calendar differs from equity joint sessions; effectively unrevised | capability PRESENT, series NOT persisted; J1 must persist it via the same documented path (FRED `DGS2` is a documented fallback distribution, to be verified at acquisition; the Treasury CSV remains the frozen source) |
| 2s10s CMT spread level/change | M2 | same source | daily | LOCAL: 2,396 observations, 2016-06 .. 2025-12 | next_day class | percentage points | same as above | PRESENT (`g_state_cache/curve_2s10s.json`) |
| fed funds futures / OIS | M1 (ideal) | none in repo | - | - | - | contract-roll treatment undefined | no zero-cost auditable historical distribution known to the repo | UNAVAILABLE; external source support required before implementation |
| HY OAS (`BAMLH0A0HYM2`) | (state series) | FRED authenticated API | daily | rolling 3-year license window; pre-2023-07-04 source-withdrawn | next_day class | percent | license truncation (G2 section 3) | PRESENT for surviving window; NOT USED in Mission J |

Data-readiness hierarchy: M1 > M2 > M3, applied only where the
higher-quality measurement is actually usable under the required
historical and timestamp contract.

**Direct-measure-unavailable rule, applied now:** the economically ideal
policy/repricing measure (fed funds futures / OIS implied path change) is
unavailable in the current substrate. The gap is recorded; the frozen
best defensible panel is the M2 Treasury panel of section 12; and every
repricing-role adjudication is marked **measurement-limited**: the 2-Yr
CMT yield blends near-term policy expectations with term premium and is
observed once per day, so it is close to, but not identical to, pure
policy-path repricing. No ETF is quietly substituted for the direct
measure, and no M3 failure at this role can ever be treated as a
mechanism failure (section 7).

Substitutes are not equivalents: where the ideal measure is absent, the
claim limitation above travels with every affected result.

## 9. Exact benchmark constitution (J1 primary model)

"Rolling beta" is not a specification. Exactly one model is frozen. No
grid search. No alternate windows.

- **Response focus:** the FOMC 1d window only. The benchmark task does not
  extend to 5d or 20d.
- **Benchmark:** SPY - the frozen broad-market benchmark of the inherited
  specification (section 3.4 ledger; nothing in the ledger indicates
  otherwise).
- **Return definition:** simple returns under the inherited basis-symmetry
  rules (F3): matched adjusted/adjusted preferred, matched raw/raw as the
  only disclosed fallback, never a cross-basis pair, never log returns,
  never adjusted-asset-with-raw-benchmark.
- **Estimation sample:** exactly `252` completed aligned paired trading
  sessions.
- **Embargo:** exactly `20` completed aligned trading sessions immediately
  before the anchor.
- **Exact indexing (frozen).** Let i be the anchor's joint-session index
  and `r_j = P(j)/P(j-1) - 1` the daily paired return of session j.
  Estimation observations: `r_j` for `j in {i-272, ..., i-21}` (252
  observations, ending immediately before the embargo). Embargo sessions
  `i-20 .. i-1` contribute no estimation observation. Conceptually:
  252-session estimation sample -> 20-session quarantine -> anchor.
- **Model:** OLS with intercept,
  `r_asset,t = alpha + beta * r_benchmark,t + epsilon_t`.
- **Abnormal return:**
  `AR_t = r_asset,t - (alpha_hat + beta_hat * r_benchmark,t)`.
  For the 1d window `[t, t+1]` this is the single daily abnormal return at
  session i+1 (hold-period and daily AR coincide at h = 1).
- **Lookahead prohibition:** alpha and beta use only observations before
  the 20-session embargo - no event-window observation, no observation
  from the frozen J2 20-session pre-event-drift window (which lies inside
  the embargo by construction), no future observation.
- **Missingness:** exactly 252 valid aligned paired observations under the
  frozen basis policy are required. If unavailable at an anchor (event or
  ordinary reference), that anchor is reported `unavailable` for this
  lens. No shortened window, no minimum-180 rule, no 80% rule, no
  interpolation, no backward search for a more convenient specification.
  Structural note, stated now: the local price frame begins 2017-01-03 and
  the requirement reaches 273 sessions of prior price history, so the
  earliest 2018 anchors sit near the boundary; per-anchor availability is
  a J1 funnel fact to disclose, never to repair.
- **No hyperparameter alternatives in J1:** no 30d, 60d, 90d, 120d, 126d,
  180d, or 504d estimation windows; no window comparison. If the frozen
  252/20 specification reverses the inherited result, the finding is
  reported as **benchmark-sensitive**; no other beta window is searched.

Hyperparameter rationale (frozen): 252 sessions is one full trading-year
exposure regime; the 20-session embargo structurally separates estimation
from the [-20,-1] pre-event-drift window planned for J2. These choices are
not outcome-calibrated, and no claim is made that they are uniquely
correct.

Scope of the model: the rolling-beta lens applies to equity measurements
against SPY only. Rates-role and curve-shape measurements (yield and
spread changes, SHY) use raw changes/returns only (section 12); no
equity-benchmark regression is applied to them, and no volatility-scaled
variant of any new lens is introduced in Mission J.

## 10. Exact timing constitution

Window notation (frozen): for anchor index i on a measurement's own
aligned calendar, window `[a, b]` (integers, a < b) is the hold-period
response from the session-(i+a) close to the session-(i+b) close -
`P(i+b)/P(i+a) - 1` for prices; `y(i+b) - y(i+a)` in percentage points for
yield/spread levels. Span = b - a. The inherited 1d window is `[t, t+1]`,
i.e. `[0, +1]`.

- **Official anchor:** the existing Mission I mapping is preserved
  verbatim - an event date anchors to the last joint trading session at
  or before the source-pinned date (regression-pinned divergence-audit
  behavior). Mission I's anchors are not rewritten.
- **Pre-event drift windows (frozen):** exactly `[-5, -1]` and
  `[-20, -1]` relative to the resolved anchor in the same session-index
  system. No alternative windows may be added after results.
- **Reference geometry for a window (frozen):** an ordinary anchor u is
  eligible for window w iff it passes the transplanted I0 gates on the
  measurement's calendar (era 2018-01-01 .. 2025-12-31; the lens's own
  estimation prerequisite; window-span availability on both sides;
  interior-gap guard where the shipped engine applies) and no 65-frame
  event e has `|index(u) - index(e)| <= span(w)` - the same minimal-buffer
  geometry as I0 buffer = h, which guarantees no session sharing between
  same-shape windows. Gates are symmetric between event and reference
  sides within each lens.
- **Pre-declared structural consequence:** for `[-20, -1]` (span 19), an
  eligible ordinary anchor needs both neighboring frame events at least
  20 sessions away, which requires an inter-event gap of at least 40
  sessions. The I0 section-5 spacing table records a maximum FOMC gap of
  39 sessions (median 30), so the interior of the era supplies no
  eligible anchor and only era-edge slivers (early 2018 / late 2025) are
  geometrically possible. The frozen calibration cannot execute either:
  I2C-A per-year placement matching must draw each year's event count
  from that year's eligible ordinary pool, and every year's interior pool
  is empty. Consequence, frozen now: the four `[-20, -1]` readouts are
  **descriptive-only under the frozen design because the
  ordinary-reference construction is structurally infeasible** - no
  ordinary reference, no percentile, no MEMP, no placement calibration,
  no node state (none of ELEVATED, ORDINARY / UNRESOLVED,
  LOWER-MAGNITUDE, or DISCORDANT may be assigned), and no
  pseudo-calibration may be invented to rescue them. They are the frozen
  descriptive timing diagnostics of section 13, always displayed, never
  state-classified. J2 must still publish the empty funnel as fail-loud
  documentation. No buffer weakening, no rescue.
- **Timing interpretation rules (frozen):**
  - pre-event window elevated, official 1d not: "substantial information
    incorporation may have preceded the official anchor."
  - both elevated: "the daily data do not isolate whether the response
    began before or continued through the official event window."
  - only the official 1d window elevated: "the result is more
    concentrated around the official anchor under daily measurement."
  "Elevated" in these rules is the section-4.2 state, so state-based
  timing interpretation rests on the `[-5, -1]` state-bearing cells only;
  the `[-20, -1]` descriptive diagnostics inform no state-based
  interpretation. No intraday timing claim may ever be made from daily
  data.
- **Scheduled-event limitation (frozen statement):** FOMC is a scheduled
  event family; anticipation is structurally plausible; daily
  close-to-close data cannot resolve intraday repricing. Additionally,
  the FOMC statement is released at 2 p.m. ET (frozen in the G2 source
  contract) while the inherited anchor convention starts the `[t, t+1]`
  window at the anchor-session close - so part of the same-session
  reaction sits before the window opens, and daily data cannot decompose
  it. J2 timing results remain descriptive.
- **SAR for drift windows (frozen):** sigma_ar_daily is estimated from
  the 60 daily abnormal returns ending immediately before the window
  start (session i+a), ddof = 1, with `sqrt(span)` scaling - the shipped
  rule transplanted to the shifted window.

## 11. Exact collision constitution

Collision is NOT "anything within +/-20 days." Mission J attacks a 1d
result, so the collision boundary is the exact response interval.

- **Frozen primary collision interval:** the exact sessions consumed by
  the existing 1d response calculation - `[t, t+1]` in the resolved
  session index. No broader proximity buffer.
- **Objective rule:** an event is a collision only if its source-pinned /
  resolved occurrence overlaps the exact response-measurement interval.
  A CPI release five sessions after an FOMC anchor is not a collision for
  the 1d question; a frozen competing release inside `[t, t+1]` is.
- **C1 - direct-channel collision (frozen finite family list):** a
  predeclared event family plausibly affecting the same
  policy/rates-repricing channel, overlapping `[t, t+1]`:
  1. FOMC policy decisions themselves (the G1A frame). Structurally
     collision-free at this interval: the frame's minimum anchor spacing
     is 8 sessions (I0 section 5), so no second frame event can fall
     inside `[t, t+1]`. Frozen as a checked invariant, not an assumption.
  2. Scheduled U.S. CPI releases (official BLS release schedule).
     **External source support required before implementation:** the
     register must be built from the official BLS calendar (dates only,
     no outcome values) and frozen before any J2 outcome inspection.
  3. Scheduled U.S. Employment Situation releases (official BLS release
     schedule). Same external-register requirement and freeze deadline.
  This list is closed. No open-ended "other important macro news" and no
  post-hoc family additions.
- **C2 - cross-channel compound event (frozen register):** the tracked
  OPEC known-date exclusion register
  (`opec-known-date-exclusion-register@i0-v1`, 41 calendar dates
  resolving to 39 anchor sessions; I0 section 8) - the only in-repo
  cross-channel register with defensible source/date provenance. An
  event register may be consulted only for dates; no ad hoc headline
  searching after observing an unusual FOMC window.
- **C3 - background environment:** everything not covered by the frozen
  C1/C2 registers - earnings seasons, routine company news, events
  outside the exact interval, unregistered world events. C3 remains
  market background on both sides of every comparison. No attempt is made
  to clean the world.
- **Primary denominator rule:** the Mission I denominator is untouched;
  the primary J analysis retains all 65 FOMC events; collision status is
  metadata only.
- **Sensitivity rule:** predeclared subset re-reads may compare all 65 vs
  the known-register collision-free subset vs the C1-tagged subset vs the
  C2-tagged subset. **No numeric event floor governs these subsets.**
  Threshold provenance, traced and rejected: the Mission G floor
  `MIN_UNIQUE_DATES = 11` (`stats/G4_STRUCTURAL_FREEZE.md` section 2) was
  considered for import and rejected. Its derivation is
  universe-specific: 11 = 10 + 1, where 10 is the largest single
  lane-year occupancy of the 97-candidate two-lane Mission G universe
  (the OPEC 2025 lane-year), chosen so no Mission G tag category or
  comparison cell could be the artifact of one calendar year of one
  lane. The Mission J universe is the 65-event FOMC frame, whose largest
  event-year occupancy is 9 (2020, per the frozen I2C-A per-year
  vector), so the same reasoning applied to this mission's universe
  would yield a different constant; the number 11 does not transfer, and
  no replacement constant is minted. Instead, every subset re-read is
  governed by frozen algorithmic feasibility requirements: report the
  exact subset N; report the subset's event-year distribution; report
  per-event response availability under the cell's frozen gate; report
  whether the frozen comparison and calibration procedure can execute
  mechanically (a non-empty subset of available events, and per-year
  placement matching able to draw the subset's year vector from the
  cell's eligible ordinary pools); and fail loudly with `insufficient
  subset under the frozen procedure` when any required mechanic cannot
  run. The subset's LOYO/LOEO overlays (section 4.4) mechanically expose
  single-year or single-event dependence, serving the original
  concentration concern without a numeric floor. No result-based tuning:
  the feasibility requirements may never be loosened or tightened, and
  no collision category may ever be redrawn, because a subset is small
  or a result is inconvenient. Collisions are never silently removed
  from the primary denominator, and the collision definition is never
  broadened or narrowed to rescue sample size.
- **No clean-world claim:** a collision-free event under the frozen
  registers is described as "outside known-register collisions", never as
  "free of competing events".

## 12. Frozen economic-role graph

Frozen only after sections 3-11. The graph uses economic roles; tickers
and series are measurement instruments. This is the smallest defensible
structure supported by existing repository rationale; no node was chosen
for historical responsiveness, and no node may be added or removed after
J1/J2 results are visible. Failed nodes remain in the graph: the J3
surface must show held, broke, unactivated, and unresolved alike.

### 12.1 Node table

| node | economic role / mechanism (repo-supported rationale) | primary | alt A | alt B | M-class (primary) | exposure class | data readiness | node-state lens | failure meaning | claim limit |
|---|---|---|---|---|---|---|---|---|---|---|
| N0 `fomc_decision` | the event family itself: 65 frame-complete policy decisions (G1A) | - (event trigger; not measured) | - | - | - | A | frozen ledgers tracked | - (activation definitional: the decision occurred) | - | event occurrence only; no market claim |
| N1 `policy_rates_repricing` | decision + statement reprice the expected near-term policy path ("policy decision -> policy path / funding and curve conditions", `g3-transmission-map-v1`; G2 `fed_policy_path` definition) | 2-Yr CMT yield change (M2) | SHY 1d return (M3) | - (the 2s10s curve-shape observable is a distinct construct and is NOT a member of this panel, section 12.2; frozen as a two-member panel, adjudicability via Route A on the M2 primary) | M2 | B (statistics) | primary: capability present, series must be persisted in J1; alternate requires fetch | raw absolute change (no benchmark regression) | frozen repricing measurements did not register elevated 1d magnitude under daily close data - measurement-limited (section 8), not mechanism failure by itself | measurement-limited: 2Y CMT blends policy expectations and term premium; ideal M1 unavailable |
| N2 `balance_sheet_sensitive_second_order` | funding/curve conditions transmit to regional-bank equities (same G3 line; KRE claim ceiling verbatim: one predeclared second-order equity transmission lens, not the complete market reaction) | KRE (M3, inherited) | IAT (M3) | KBE (M3) | M3 | instruments: KRE A; IAT/KBE B; all new J statistics B | KRE cached; IAT/KBE require fetch | rolling 252/20 OLS abnormal return vs SPY (section 9) | the frozen panel did not carry an elevated state; adjudicable as a break only via Route B (two design-distinct M3s agreeing: KRE is S&P Select Industry modified-equal-weight; IAT is cap-weighted Dow Jones U.S. regional banks) | equity-proxy limits (fund mechanics); single-proxy results stay asset-specific |
| N3 `broad_financial_sector` | breadth layer: does an elevation in the concentrated rate-sensitive bank layer also appear at the broad financial-sector level? XLF is the inherited FOMC sector lens; the edge into N3 orders specificity, not causation | XLF (M3, inherited) | VFH (M3) | - (only one defensible design-distinct alternate exists; frozen as a two-member panel, adjudicability downgraded accordingly) | M3 | instruments: XLF A; VFH B; new statistics B | XLF cached; VFH requires fetch | rolling 252/20 OLS abnormal return vs SPY | the broad sector did not show the elevated state; break adjudicable only via Route B (XLF: S&P 500 large-cap financials; VFH: CRSP all-cap financials - distinct universes) | sector ETFs are cap-weighted composites; not a statement about every financial firm |
| N4 `broad_market_context` | context/benchmark role: SPY is the frozen market benchmark of the inherited specification and the AR-model regressor | SPY (M3, inherited) | - | - | M3 | A | cached | - (context only; no adjudicated state, no edges) | - | benchmark/context duty only |

Rates-role metric discipline (frozen): N1 measurements and the
curve-shape observable carry exactly one lens each - the raw change (or
raw return for SHY) in absolute value under the section-4.1 machinery. No
SPY-relative, sector-relative, or volatility-scaled variant exists for
them, and none may be added after outcomes.

### 12.2 Curve-shape contextual layer (predeclared; not a graph node)

The 2s10s CMT spread change is a curve-shape observable, not a
short-rate-level observable: a change in `(10Y yield - 2Y yield)` can
occur because the 2Y leg moved, because the 10Y leg moved, or because
both moved differently. It is therefore not an interchangeable
measurement design for the latent quantity of the policy/rates-repricing
role, and Mission G already froze `curve_2s10s` as its own state
dimension, separate from `fed_policy_path`
(`stats/G4_STRUCTURAL_FREEZE.md` section 3). J0 freezes it in the
smallest defensible role: a predeclared contextual layer.

- Measurement: 2s10s CMT spread change (M2; section 8 row), raw-change
  lens, carried as one state-bearing primary statistic (J1 cell 11,
  section 13) with its own reference, calibration, node state, and
  overlays, interpreted standalone.
- It is NOT a graph node: no panel, no alternates, no edges, and no role
  in any edge adjudication.
- Frozen prohibitions - the curve-shape layer must never:
  - rescue a failed or unusable 2-Yr primary (including standing in as
    the rates role's Route A measurement);
  - count against a successful 2-Yr primary;
  - count toward any rates-repricing role-level modifier (ROLE-CONSISTENT,
    BROAD MEASUREMENT CONSISTENCY, and MEASUREMENT DISAGREEMENT for that
    role are computed over the two-member rates panel only);
  - satisfy Route B for any role;
  - be described as a substitute measurement of short-rate repricing.
- J3 must display it beside the graph as context, in whatever state the
  frozen machinery assigns it.

### 12.3 Edge table

| edge | economic rationale | upstream activation requirement | downstream state requirement | adjudicability requirement | PROPAGATED | TRANSMISSION BREAK | MEASUREMENT UNRESOLVED | does not prove |
|---|---|---|---|---|---|---|---|---|
| E1 `fomc_decision -> policy_rates_repricing` | policy decisions reprice the near-term policy path (G3 map line) | definitional (all 65 anchors exist), so UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM are structurally unreachable on E1 | N1 primary state per section 4.2 | N1 primary is M2 - a usable M2 primary adjudicates both the elevated and the non-response claim alone (Route A) | N1 = State A (usable M2 primary) | N1 = State B or C (usable M2 primary) | N1 = State D, or primary unusable at run time | causality; that repricing is policy-specific rather than term-premium; anything intraday |
| E2 `policy_rates_repricing -> balance_sheet_sensitive_second_order` | funding and curve conditions transmit to regional-bank equities (G3 map line) | N1 primary = State A (M2 primary stands alone) | N2 primary state per section 4.2, under section-5 downstream adjudicability | N2 primary is M3: the elevated claim requires KRE at State A AND the role at least ROLE-CONSISTENT; the break claim requires Route B on N2 (KRE and IAT/KBE design-distinct agreement); a single-proxy elevation or non-response is UNRESOLVED | upstream ACTIVATED and N2 supports the ELEVATED claim (KRE State A + role at least ROLE-CONSISTENT) | upstream ACTIVATED and N2 = State B/C with Route B satisfied | N1 = State D or unusable (upstream reading UNRESOLVED); KRE at State A with the role below ROLE-CONSISTENT (proxy-specific elevation, displayed at node level); N2 = State D; Route B unsatisfied on a considered break; panel MEASUREMENT DISAGREEMENT blocking one reading | causality; completeness of the banking channel; direction of returns |
| E3 `balance_sheet_sensitive_second_order -> broad_financial_sector` | breadth/specificity ordering: concentration -> breadth. Explicitly NOT a causal ordering - both equity layers respond simultaneously; the edge asks whether the elevation generalizes | N2 ACTIVATED: primary = State A AND role modifier at least ROLE-CONSISTENT (M3-primary rule, section 5) | N3 primary state per section 4.2, under section-5 downstream adjudicability | N3 primary is M3: the elevated claim requires XLF at State A AND the role at least ROLE-CONSISTENT (with the frozen two-member panel, XLF-VFH agreement); the break claim requires Route B on N3 (XLF and VFH agreement); a single-proxy elevation or non-response is UNRESOLVED | upstream ACTIVATED and N3 supports the ELEVATED claim (XLF State A + role at least ROLE-CONSISTENT) | upstream ACTIVATED and N3 = State B/C with Route B satisfied | N2 primary at State A without the ROLE-CONSISTENT modifier (upstream reading UNRESOLVED, section 5); XLF at State A with the role below ROLE-CONSISTENT (proxy-specific elevation, displayed at node level); N2 = State D; N3 = State D; Route B unsatisfied on a considered break; VFH unavailable at run time | causal ordering between equity layers; sector-wide mechanism confirmation (never claimed) |

For every edge, UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM
follow the section-5 decision table verbatim where reachable. No new edge
state may be created after outcomes.

## 13. Frozen Mission J sequence and statistic family

Two frozen families, counted and labeled separately, all FOMC-only, all
reported regardless of value, none ranked or highlighted:

- exactly **16 primary state-bearing robustness statistics** (J1 cells
  1-12; J2 cells 13-16). Each carries: an ordinary reference
  distribution, MEMP, era-matched placement calibration (section 4.1), a
  section-4.2 node state, the section-4.4 stability overlays, and a full
  funnel (reference N, non-overlapping block count, per-year table,
  per-gate casualties, available-event N beside 65);
- exactly **4 frozen descriptive timing diagnostics** (D1-D4), the
  `[-20, -1]` readouts of section 10: descriptive-only under the frozen
  design because the ordinary-reference construction is structurally
  infeasible. They carry event-side responses and the fail-loud empty
  funnel only - no reference, no MEMP, no calibration, no node state, no
  stability overlay.

Multiplicity disclosure (frozen reporting rules binding J1, J2, and J3):
the two families are always reported with these exact counts and labels;
a descriptive diagnostic is never counted as, averaged with, or presented
as a calibrated primary statistic; the four diagnostics are never hidden;
and a diagnostic is never offered as substitute evidence when a primary
statistic disappoints. No FOMC/OPEC pooling anywhere; the OPEC lane does
not participate in Mission J.

### J1 - asset and benchmark robustness (12 cells; window [t, t+1])

> Does the inherited FOMC 1d pattern depend on the already-observed KRE
> asset choice or the fixed beta-1 benchmark treatment?

| # | measurement | lens |
|---|---|---|
| 1 | KRE | rolling 252/20 OLS AR vs SPY |
| 2 | IAT | rolling 252/20 OLS AR vs SPY |
| 3 | KBE | rolling 252/20 OLS AR vs SPY |
| 4 | XLF | rolling 252/20 OLS AR vs SPY |
| 5 | VFH | rolling 252/20 OLS AR vs SPY |
| 6 | IAT | raw return (inherited definition) |
| 7 | KBE | raw return |
| 8 | XLF | raw return |
| 9 | VFH | raw return |
| 10 | 2-Yr CMT yield | raw change |
| 11 | 2s10s CMT spread | raw change |
| 12 | SHY | raw return |

Cells 1-10 and 12 measure graph roles (section 12.1); cell 11 is the
curve-shape contextual layer of section 12.2 - state-bearing, but outside
every proxy panel and every edge adjudication. KRE's inherited raw-return
and beta-1 cells are Class A facts displayed beside the new cells, never
recomputed into new statistics. J1 must show the complete panels (section
6.4) plus the contextual layer; no best-proxy selection. Events or
reference anchors failing a lens's gate are `unavailable`; each lens must
report its available-event N and event-year distribution, and a lens
whose frozen comparison or calibration procedure cannot execute
mechanically is reported as `insufficient subset under the frozen
procedure` (the section-11 feasibility rule; no numeric floor). MEMPs
from lenses with different references or different available-event sets
are positioned per cell and are not value-comparable across lenses; any
comparison to the inherited MEMP must disclose the coverage difference.

### J2 - timing and collision robustness (4 state-bearing cells + 4 descriptive diagnostics + tags/sensitivities)

> Is the FOMC 1d pattern concentrated around the official anchor,
> anticipated before it, or dependent on known-register compound windows?

Cells 13-16 (state-bearing): window `[-5, -1]` on the inherited
KRE / SPY / XLF specification, four inherited metrics (raw return,
SPY-relative beta-1 AR, sector-relative beta-1 AR, SAR per section 10).
Diagnostics D1-D4 (descriptive-only): window `[-20, -1]`, same four
metrics, under the frozen section-10 classification - no ordinary
reference, no MEMP, no calibration, no node state. Collision work
(section 11) adds tags and predeclared subset re-reads of existing
state-bearing cells only - no new statistic.

### J3 - transmission graph readout (no new statistics)

Only after J1 and J2 are complete and frozen. J3 displays every frozen
role and edge in exactly one predeclared state, with all panel members,
modifiers, and overlays shown, plus the curve-shape contextual layer
(section 12.2) and the four descriptive timing diagnostics under their
descriptive-only labels - held, broke, unactivated, and unresolved alike.
No node added because J1 found an interesting asset; no failed node
removed; no graph UI before the research surface exists.

## 14. Permanent claim ladder

Frozen tiers; the levels may never be collapsed:

1. **Mission I:** "descriptive same-specification event-versus-ordinary
   evidence."
2. **Mission J same-sample robustness:** "post-outcome robustness evidence
   under prospectively frozen new tests." Never "independent
   confirmation."
3. **Proxy-specific result:** "the response is specific to the frozen
   observable."
4. **Role-consistent result:** allowed only when the section-6.5
   ROLE-CONSISTENT rule is satisfied.
5. **Mechanism-consistent descriptive pattern:** allowed only when the
   predeclared linked roles satisfy the frozen state rules, measurement
   adjudicability is sufficient, and no edge is rescued by proxy
   substitution. Still not causal, and never phrased as a confirmed
   mechanism.
6. **Future Class C evidence:** potentially stronger prospective language
   only if genuinely untouched or future evidence exists (none is claimed
   now; section 3.3).

## 15. Stop and downgrade conditions

Mission J must downgrade or stop a claim if any of the following occurs.
An honest downgrade is a successful research outcome.

- the pattern exists only in KRE (report proxy-specific, tier 3 maximum);
- new asset layers disagree (report MEASUREMENT DISAGREEMENT; no
  role-level claim);
- the frozen 252/20 benchmark model reverses the inherited result (report
  benchmark-sensitive; no window search);
- the response is primarily pre-event (report the frozen anticipation
  interpretation; the 1d concentration claim is withdrawn);
- known-register collisions drive the result in the predeclared subsets
  (report collision-dependence; the primary denominator still stands);
- the upstream role is not activated (edges report UPSTREAM NOT ACTIVATED
  / DOWNSTREAM WITHOUT UPSTREAM; no path retrofitting);
- an M3 proxy is the only evidence for a mechanism-level claim (cap at
  proxy-specific);
- the proxy panel produces measurement disagreement (no single role-level
  reading);
- the frozen procedure cannot execute on a supposedly clean subset
  (report `insufficient subset under the frozen procedure`; no boundary
  re-drawing, no floor tuning, no category redrawing);
- the ideal measurement is unavailable and the remaining panel cannot
  adjudicate the mechanism (report MEASUREMENT UNRESOLVED and the
  section-8 limitation).

## 16. Explicit non-claims

Mission J does not and will not claim:

- causality, prediction, tradeability, or alpha;
- statistical significance (no p-values, no significance vocabulary, no
  FDR pool; calibration percentiles are placement positions only);
- that any same-sample result is independent historical confirmation of
  Mission I;
- that any node, edge, or panel was selected without knowledge of the
  Mission I outcome (section 2);
- that a confirmed mechanism exists at any tier - mechanism-consistent
  descriptive patterns are the ceiling, and edge states are descriptive
  alignments, never proof of transmission;
- intraday timing resolution from daily data;
- that any window is "free of competing events" (only "outside
  known-register collisions");
- that the 2-Yr CMT panel equals the unavailable direct policy-repricing
  measure (section 8);
- that the 252/20 hyperparameters are uniquely correct (section 9);
- that a Class C sample exists (section 3.3);
- that MEMPs from different lenses, references, or availability sets are
  value-comparable;
- that the 2s10s curve-shape observable measures short-rate repricing -
  it is a distinct economic construct and never substitutes for, rescues,
  or corroborates the rates-repricing panel (section 12.2);
- that the `[-20, -1]` descriptive diagnostics carry any ordinary
  reference, MEMP, calibrated position, or node state (sections 10
  and 13);
- any FOMC/OPEC pooled statement (standing pooling ban);
- any buy/sell/directional reading of any state, edge, or statistic -
  this remains a research surface, not a recommendation surface.

## 17. Freeze statement

Protocol j0-v1 is LOCKED as written. It was assembled from tracked
artifacts, documented source semantics, cache metadata, and calendar/
spacing facts already frozen in Mission I; no new asset history was
fetched, no new event return, ordinary-period comparison, MEMP, or
calibration percentile was computed, no candidate proxies were compared or
ranked by performance, no rolling-beta, timing, or collision result was
inspected, and no node was chosen for remembered historical
responsiveness. Mission I artifacts, denominators, values, and
interpretations are unchanged and remain governing. No Mission J
robustness outcome was computed or inspected before this freeze.

**Pre-publication amendment (j0-v1, outcome-blind, before any Mission J
outcome existed and before push).** Four repairs were made to the locked
text before publication, from construction facts only: (1) the 2s10s
curve-shape observable was separated from the policy/rates-repricing
panel into the predeclared contextual layer of section 12.2 - level and
shape are distinct economic constructs, so the rates panel is the 2-Yr
CMT primary plus the SHY alternate only; (2) the statistic family was
split into exactly 16 primary state-bearing robustness statistics and
exactly 4 frozen descriptive timing diagnostics, because the `[-20, -1]`
ordinary-reference and per-year calibration construction is structurally
infeasible under the frozen geometry (sections 10 and 13); (3) the
imported Mission G subset floor `MIN_UNIQUE_DATES = 11` was traced to its
G4 derivation, found universe-specific and non-transferable, and replaced
by the section-11 algorithmic feasibility requirements with no
replacement constant; (4) section-5 edge adjudication was made
measurement-symmetric on both sides of every edge - the upstream reading
is explicitly three-valued, and downstream adjudicability requires the
same role-level support for an elevated edge claim as for a non-response
edge claim - so no single uncorroborated M3 measurement, upstream or
downstream, can produce PROPAGATED, TRANSMISSION BREAK, or DOWNSTREAM
WITHOUT UPSTREAM; every such case maps to MEASUREMENT UNRESOLVED while
the proxy-specific node state remains displayed. No Mission J robustness
outcome was computed or inspected before or during this amendment.

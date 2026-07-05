# G6C representative cases (Mission G, g0-v1)

Version: `g6c-representative-cases-v1`.

## Case-selection contract

- Disclosed as post-readout selection: this slice ran after the G6A outcomes and G6B diagnostics existed. The defense against cherry-picking is mechanical: outcome magnitude was not used - cases are anchored to STATE quantiles, the selector receives no outcome object (tested), and perturbing outcome values cannot change the selected ids (tested).
- Three frozen roles, six slots: Role A - stable-but-confounded association illustration (OPEC lane, fed_policy_path, all 32 designed rows); Role B - fragile era-bounded secondary lens (OPEC lane, credit_hy_oas, the 16-row credit-available subset); Role C - broad null illustration (FOMC frame lane, fed_policy_path, all 65 rows). Each role selects its Q25 and Q75 state-anchor case.
- Anchors use the G6A inclusive quantile convention; selection minimizes |state - target| with ties broken by event date ascending, then candidate id ascending. No manual override, no largest-return path, no famous-event path; duplicate role selections are preserved and rendered once.
- Representative cases are illustrations, never proof.

## Six-slot selection ledger

| role | lane | axis | quantile | target | selected candidate | state | distance |
|---|---|---|---|---|---|---|---|
| A (stable-but-confounded association illustration) | designed_contrast | `fed_policy_path` | Q25 | -0.5000 | `opec-2024-11-03-one-month-delay` | -0.5000 | 0.0000 |
| A (stable-but-confounded association illustration) | designed_contrast | `fed_policy_path` | Q75 | +0.3125 | `opec-2023-11-30-voluntary-2p2` | +0.2500 | 0.0625 |
| B (fragile era-bounded secondary lens) | designed_contrast | `credit_hy_oas` | Q25 | +2.8325 | `opec-2025-09-07-oct-137k` | +2.8400 | 0.0075 |
| B (fragile era-bounded secondary lens) | designed_contrast | `credit_hy_oas` | Q75 | +3.2950 | `opec-2024-03-03-q2-extension` | +3.2900 | 0.0050 |
| C (broad null illustration) | frame_complete_historical | `fed_policy_path` | Q25 | -0.2500 | `fomc-policy-decision-2019-09-18` | -0.2500 | 0.0000 |
| C (broad null illustration) | frame_complete_historical | `fed_policy_path` | Q75 | +0.5000 | `fomc-policy-decision-2018-05-02` | +0.5000 | 0.0000 |

Six role slots resolve to 6 unique cases; no candidate serves two roles.

## Representative case dossiers

### `opec-2024-11-03-one-month-delay`

Role slots: A/Q25 (target -0.5000, state -0.5000)

- event date: 2024-11-03 | lane: designed_contrast | family: opec
- source (G1 ledger): V8 statement
- source-native description: Phased return delayed one further month (to end-December 2024)
- frozen transmission hypothesis: collective production policy -> crude supply expectations -> producer cash flows -> E&P equities -> XOP
- assets: primary XOP, market benchmark SPY, sector benchmark XLE

Pre-event state (cutoff 2024-11-01): fed policy path -0.5000 (easing); VIX percentile +0.9683; SPY vs MA200 +0.0683 (above_ma); 2s10s +0.1200 (non_inverted); HY OAS +2.8800.

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | +1.90% | +8.27% | +11.20% |
| SPY-relative AR | +2.12% | +3.51% | +5.50% |
| sector-relative AR | +0.15% | +1.77% | +3.83% |
| SAR | +1.46 | +1.08 | +0.85 |

Parent-surface context (Role A, from the G6B board - sector-relative AR, the association under scrutiny):
- 1d: rho -0.4564; LOEO range [-0.5288, -0.4015] (0 sign reversals); LOYO range [-0.5183, -0.3668] (0 reversals)
- 5d: rho -0.2929; LOEO range [-0.3838, -0.2378] (0 sign reversals); LOYO range [-0.4754, -0.1859] (0 reversals)
- 20d: rho -0.3824; LOEO range [-0.4445, -0.3190] (0 sign reversals); LOYO range [-0.4569, -0.3104] (0 reversals)
- state-vs-date rho (OPEC lane): -0.2708 - the calendar-time confound remains unresolved

#### Event and transmission mechanism

The V8 producers delayed the phased return of withheld supply by one further month, to end-December 2024 (source: the pinned V8 statement). Under the frozen chain, a delayed return is continued supply restraint: crude supply expectations tighten relative to the pre-announcement schedule, supporting producer cash-flow expectations and, second-order, E&P equities (XOP). The pre-event state is the deep-easing anchor of the OPEC lane, with the VIX percentile near the top of its historical range (values above).

#### What the market readout shows

Absolute asset return: +1.90% at 1d, +8.27% at 5d, +11.20% at 20d. Against SPY: +2.12% / +3.51% / +5.50%. Against the sector benchmark: +0.15% / +1.77% / +3.83%. Standardized (SAR): +1.46 / +1.08 / +0.85; the largest standardized move is +1.46 at 1d.

The move is positive on every lens and every horizon and does not collapse after sector benchmarking, so it is not purely a broad-energy effect; standardized against the asset's own pre-event volatility it is visible at the one-day horizon and fades with distance.

#### What this case cannot establish

The decision is a scheduled item on the producers' calendar, so anticipation and any other information arriving inside the five- and twenty-day windows cannot be separated from the decision itself. The deep-easing state also sits late in the lane's calendar, so this case cannot separate the easing state from calendar position - the unresolved confound of its parent association (the lane's state-vs-date value is printed above).

#### Role in the research record

illustrates stable descriptive association (with unresolved calendar-time confounding).

### `opec-2023-11-30-voluntary-2p2`

Role slots: A/Q75 (target +0.3125, state +0.2500)

- event date: 2023-11-30 | lane: designed_contrast | family: opec
- source (G1 ledger): 36th ONOMM PR + coordinating-producers statement
- source-native description: Coordinated additional voluntary adjustments of about 2.2 mb/d for Q1 2024
- frozen transmission hypothesis: collective production policy -> crude supply expectations -> producer cash flows -> E&P equities -> XOP
- assets: primary XOP, market benchmark SPY, sector benchmark XLE

Pre-event state (cutoff 2023-11-29): fed policy path +0.2500 (tightening); VIX percentile +0.0317; SPY vs MA200 +0.0642 (above_ma); 2s10s -0.3900 (inverted); HY OAS +3.9000.

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | +0.80% | -5.28% | -0.03% |
| SPY-relative AR | +0.21% | -5.68% | -4.60% |
| sector-relative AR | +0.28% | -1.46% | -0.11% |
| SAR | +0.13 | -1.61 | -0.65 |

Parent-surface context (Role A, from the G6B board - sector-relative AR, the association under scrutiny):
- 1d: rho -0.4564; LOEO range [-0.5288, -0.4015] (0 sign reversals); LOYO range [-0.5183, -0.3668] (0 reversals)
- 5d: rho -0.2929; LOEO range [-0.3838, -0.2378] (0 sign reversals); LOYO range [-0.4754, -0.1859] (0 reversals)
- 20d: rho -0.3824; LOEO range [-0.4445, -0.3190] (0 sign reversals); LOYO range [-0.4569, -0.3104] (0 reversals)
- state-vs-date rho (OPEC lane): -0.2708 - the calendar-time confound remains unresolved

#### Event and transmission mechanism

The 36th ONOMM and the accompanying coordinating-producers statement announced additional voluntary adjustments of about 2.2 mb/d for Q1 2024 (source: the pinned ONOMM release). Under the frozen chain an announced cut is supply restraint and would, taken at face value, support producer cash-flow expectations and XOP. The pre-event state is the lane's upper-quartile tightening anchor, with an inverted curve and the VIX percentile near its floor (values above).

#### What the market readout shows

Absolute asset return: +0.80% at 1d, -5.28% at 5d, -0.03% at 20d. Against SPY: +0.21% / -5.68% / -4.60%. Against the sector benchmark: +0.28% / -1.46% / -0.11%. Standardized (SAR): +0.13 / -1.61 / -0.65; the largest standardized move is -1.61 at 5d.

Past the first day the traded outcome runs opposite the announcement's face-value direction on every benchmark: whatever the decision's nominal supply direction, the five-day window shows weakness against the market, the sector, and the asset's own volatility scale.

#### What this case cannot establish

This was a scheduled meeting announcing voluntary, member-level adjustments (per the pinned record), so anticipation and post-announcement repositioning cannot be separated from the decision's content in a single case. The tightening state co-occurs with one segment of the calendar, so era effects and state effects are indistinguishable here - the same confound its parent association carries.

#### Role in the research record

illustrates stable descriptive association (with unresolved calendar-time confounding).

### `opec-2025-09-07-oct-137k`

Role slots: B/Q25 (target +2.8325, state +2.8400)

- event date: 2025-09-07 | lane: designed_contrast | family: opec
- source (G1 ledger): V8 statement (opec.org pr-detail 573-07-september-2025)
- source-native description: October 2025 level raised by 0.137 mb/d - first step of returning the separate 1.65 mb/d voluntary layer (new phase)
- frozen transmission hypothesis: collective production policy -> crude supply expectations -> producer cash flows -> E&P equities -> XOP
- assets: primary XOP, market benchmark SPY, sector benchmark XLE

Pre-event state (cutoff 2025-09-05): fed policy path +0.0000 (hold); VIX percentile +0.1706; SPY vs MA200 +0.0873 (above_ma); 2s10s +0.5800 (non_inverted); HY OAS +2.8400.

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | -0.73% | +0.38% | +3.44% |
| SPY-relative AR | -0.98% | -1.19% | -0.24% |
| sector-relative AR | -0.50% | -1.04% | +0.80% |
| SAR | -0.63 | -0.34 | -0.03 |

Parent-surface context (Role B): N=16, era-bounded (2023-07-04 onward), secondary-only lens.
- sar 5d: rho -0.3194; LOEO [-0.4987, -0.2020]; LOYO [-0.4286, -0.2020]
- spy_relative_ar 5d: rho -0.2899; LOEO [-0.5165, -0.1448]; LOYO [-0.6000, -0.1448]
- 9 of the 12 credit associations flip sign under leave-one-out; reversal-free: absolute_asset_return 20d, sar 5d, spy_relative_ar 5d
- credit-vs-date rho (OPEC lane): -0.4489 - the credit level itself tracks calendar time inside the surviving window

#### Event and transmission mechanism

The V8 statement raised the October 2025 production level by 0.137 mb/d, the first step of returning the separate 1.65 mb/d voluntary layer (source: the pinned V8 release). Under the frozen chain an announced supply increase pressures crude supply expectations and producer cash flows. The pre-event credit state is the lower-quartile anchor of the era-bounded subset: a tight high-yield spread (value above).

#### What the market readout shows

Absolute asset return: -0.73% at 1d, +0.38% at 5d, +3.44% at 20d. Against SPY: -0.98% / -1.19% / -0.24%. Against the sector benchmark: -0.50% / -1.04% / +0.80%. Standardized (SAR): -0.63 / -0.34 / -0.03; the largest standardized move is -0.63 at 1d.

The immediate response is mildly negative and consistent across lenses; the raw twenty-day gain does not survive the market benchmark, so it reads as broad market participation rather than an asset-specific response, and no standardized move is large on the asset's own volatility scale.

#### What this case cannot establish

A tight credit spread in this subset is largely a property of when the event happened: the credit level tracks calendar time inside the surviving window (the subset's state-vs-date value is printed above), and the subset is era-bounded and small. Most of the credit associations flip sign under leave-one-out (counts above), so no single case in this lens - including this one - supports any state-conditional reading beyond illustration.

#### Role in the research record

illustrates fragility / era limitation.

### `opec-2024-03-03-q2-extension`

Role slots: B/Q75 (target +3.2950, state +3.2900)

- event date: 2024-03-03 | lane: designed_contrast | family: opec
- source (G1 ledger): Coordinating-producers statement (opec.org pr-detail 4-03-mar-2024)
- source-native description: 2.2 mb/d voluntary adjustments extended through Q2 2024
- frozen transmission hypothesis: collective production policy -> crude supply expectations -> producer cash flows -> E&P equities -> XOP
- assets: primary XOP, market benchmark SPY, sector benchmark XLE

Pre-event state (cutoff 2024-03-01): fed policy path +0.0000 (hold); VIX percentile +0.1548; SPY vs MA200 +0.1354 (above_ma); 2s10s -0.3900 (inverted); HY OAS +3.2900.

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | -1.02% | +0.58% | +10.21% |
| SPY-relative AR | -0.91% | +0.80% | +8.08% |
| sector-relative AR | +0.05% | -0.61% | +0.18% |
| SAR | -0.66 | +0.26 | +1.31 |

Parent-surface context (Role B): N=16, era-bounded (2023-07-04 onward), secondary-only lens.
- sar 5d: rho -0.3194; LOEO [-0.4987, -0.2020]; LOYO [-0.4286, -0.2020]
- spy_relative_ar 5d: rho -0.2899; LOEO [-0.5165, -0.1448]; LOYO [-0.6000, -0.1448]
- 9 of the 12 credit associations flip sign under leave-one-out; reversal-free: absolute_asset_return 20d, sar 5d, spy_relative_ar 5d
- credit-vs-date rho (OPEC lane): -0.4489 - the credit level itself tracks calendar time inside the surviving window

#### Event and transmission mechanism

The coordinating-producers statement extended the 2.2 mb/d voluntary adjustments through Q2 2024 (source: the pinned opec.org release). Under the frozen chain an extension of cuts is continued restraint. The pre-event credit state is the upper-quartile anchor of the era-bounded subset - the wider end of a narrow, tight-spread era - with an inverted curve (values above).

#### What the market readout shows

Absolute asset return: -1.02% at 1d, +0.58% at 5d, +10.21% at 20d. Against SPY: -0.91% / +0.80% / +8.08%. Against the sector benchmark: +0.05% / -0.61% / +0.18%. Standardized (SAR): -0.66 / +0.26 / +1.31; the largest standardized move is +1.31 at 20d.

The large raw twenty-day gain survives the market benchmark but collapses to almost nothing after sector benchmarking - the lens hierarchy doing exactly the work it was designed for: a sector-wide energy move, not an asset-specific one.

#### What this case cannot establish

The case cannot attribute the twenty-day sector-wide oil move to this scheduled extension, and the era-bounded credit subset cannot support any conditional claim about spread levels (its size, era bound, and state-vs-date value are printed above). The case illustrates the fragility documented in G6B rather than escaping it.

#### Role in the research record

illustrates fragility / era limitation.

### `fomc-policy-decision-2019-09-18`

Role slots: C/Q25 (target -0.2500, state -0.2500)

- event date: 2019-09-18 | lane: frame_complete_historical | family: fomc
- source (G1 ledger): [Fed statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20190918a.htm)
- source-native description: Lower target range to 1.75-2.00 percent
- frozen transmission hypothesis: policy decision -> policy path / funding and curve conditions -> regional-bank equities -> KRE
- assets: primary KRE, market benchmark SPY, sector benchmark XLF

Pre-event state (cutoff 2019-09-17): fed policy path -0.2500 (easing); VIX percentile +0.2976; SPY vs MA200 +0.0676 (above_ma); 2s10s +0.1000 (non_inverted); HY OAS source_missing (pre-window).

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | -0.88% | -0.90% | -2.13% |
| SPY-relative AR | -0.88% | -0.20% | -1.69% |
| sector-relative AR | -0.43% | +0.10% | -0.87% |
| SAR | -0.78 | -0.08 | -0.33 |

Parent-surface context (Role C, the FOMC frame lane):
- largest absolute full-sample rho anywhere in the lane: 0.2746
- of the lane's 60 associations, 17 flip sign under leave-one-event-out and 44 under leave-one-year-out
- state-vs-date rho (fed_policy_path, FOMC lane): -0.1414
- this breadth of flatness and instability is the null result the case below illustrates

#### Event and transmission mechanism

The FOMC lowered the target range to 1.75-2.00 percent (source: the pinned Fed statement), the mid-cycle easing anchor of the frame. Under the frozen chain a policy-path change transmits through funding and curve conditions to regional-bank equities (KRE).

#### What the market readout shows

Absolute asset return: -0.88% at 1d, -0.90% at 5d, -2.13% at 20d. Against SPY: -0.88% / -0.20% / -1.69%. Against the sector benchmark: -0.43% / +0.10% / -0.87%. Standardized (SAR): -0.78 / -0.08 / -0.33; the largest standardized move is -0.78 at 1d.

The readout is small and negative on every lens and every horizon, and muted relative to the asset's own pre-event volatility; against the market, the financial sector, or its own volatility scale, KRE's response to a realized rate cut is quiet.

#### What this case cannot establish

This was a scheduled decision, anticipated in the sense of the anchor-quality label the whole frame carries, so the muted response cannot distinguish 'no transmission' from 'already priced'. KRE is one predeclared second-order lens, not the complete market reaction to monetary policy - a flat KRE readout is not a flat monetary event.

#### Role in the research record

illustrates broad null or contradiction.

### `fomc-policy-decision-2018-05-02`

Role slots: C/Q75 (target +0.5000, state +0.5000)

- event date: 2018-05-02 | lane: frame_complete_historical | family: fomc
- source (G1 ledger): [Fed statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20180502a.htm)
- source-native description: Maintain target range at 1.50-1.75 percent
- frozen transmission hypothesis: policy decision -> policy path / funding and curve conditions -> regional-bank equities -> KRE
- assets: primary KRE, market benchmark SPY, sector benchmark XLF

Pre-event state (cutoff 2018-05-01): fed policy path +0.5000 (tightening); VIX percentile +0.7579; SPY vs MA200 +0.0152 (above_ma); 2s10s +0.4600 (non_inverted); HY OAS source_missing (pre-window).

| metric | 1d | 5d | 20d |
|---|---|---|---|
| absolute asset return | -0.98% | +2.61% | +1.95% |
| SPY-relative AR | -0.76% | +0.22% | -0.99% |
| sector-relative AR | -0.14% | -0.70% | +1.84% |
| SAR | -0.81 | +0.11 | -0.24 |

Parent-surface context (Role C, the FOMC frame lane):
- largest absolute full-sample rho anywhere in the lane: 0.2746
- of the lane's 60 associations, 17 flip sign under leave-one-event-out and 44 under leave-one-year-out
- state-vs-date rho (fed_policy_path, FOMC lane): -0.1414
- this breadth of flatness and instability is the null result the case below illustrates

#### Event and transmission mechanism

The FOMC maintained the target range at 1.50-1.75 percent (source: the pinned Fed statement). The case anchors the frame's upper-quartile tightening state: the STATE reflects the hiking path into the meeting, while the decision itself was a hold - a useful reminder that the state axis describes pre-event posture, not the decision's content.

#### What the market readout shows

Absolute asset return: -0.98% at 1d, +2.61% at 5d, +1.95% at 20d. Against SPY: -0.76% / +0.22% / -0.99%. Against the sector benchmark: -0.14% / -0.70% / +1.84%. Standardized (SAR): -0.81 / +0.11 / -0.24; the largest standardized move is -0.81 at 1d.

The hierarchy is small and direction-unstable: no lens holds one sign across the three horizons - the shape of the broad FOMC null in one dossier.

#### What this case cannot establish

A scheduled hold cannot isolate decision content from prior expectations and accompanying communication; this case illustrates only the observed KRE readout under the frozen pre-event state. It is one draw from a lane whose associations are flat and sign-unstable under leave-one-out stress (the lane board above).

#### Role in the research record

illustrates broad null or contradiction.

## Cross-case synthesis

All four Mission G research outcomes stand together; none is traded away for a cleaner story:

1. Broad historical state conditioning is mostly flat, fragile, or contradictory: 44 of 120 continuous associations flip sign when one event is removed, 76 of 120 when one calendar year is removed (G6B).
2. The OPEC fed_policy_path x sector-relative AR pattern is a stable descriptive association with unresolved calendar-time confounding: no leave-one-out check flips it, and the state's own correlation with calendar time (-0.27) means these data cannot separate the two.
3. Credit evidence is narrow, era-bounded, and mostly fragile: 9 of its 12 OPEC-lane associations flip sign under leave-one-out, and the credit level itself tracks calendar time (-0.45 OPEC / -0.73 FOMC) inside the surviving window.
4. Representative cases neither rescue nor overturn the aggregate surface: they are quantile-anchored illustrations of what the boards already say, selected without outcome values.

## Rejected interpretations

- Broad regime prediction from the historical state vector: rejected - the surface is predominantly flat and unstable.
- A causal Fed effect on OPEC-event transmission: rejected - the association is descriptive, one lane, N=32, and the calendar-time confound is unresolved; the frozen wording is 'stable descriptive association with unresolved calendar-time confounding'.
- Credit as a primary cross-period state variable: rejected - era-bounded coverage (36/97) with strong calendar tracking; surviving two 5d stability checks does not promote it.
- Single-case confirmation: rejected - cases are illustrations, never proof.
- Thin-cell inference: rejected - `insufficient_n` cells remain descriptive display only.
- The FOMC flat surface as absence of substance: rejected - it is a substantive null result of a frame-complete lane under a frozen manifest.

## Non-claims

Descriptive illustration only. No causal regime effect, no forecast, no trading recommendation, no significance claim, no prevalence claim for designed-contrast evidence. Not a trading, prediction, or recommendation surface.

## Reproduction

```
python scripts/g6c_representative_cases.py --emit
python -m unittest tests.test_g6c_representative_cases
```

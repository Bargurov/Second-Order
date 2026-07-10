# J2 timing and collision results - the frozen challenge to the published FOMC 1d readout (Mission J)

Contract: `j2-timing-collision-v1` under the locked j0-v1 constitution (sections 10, 11, 13). This is the **first real J2 timing execution**: no Mission J timing or collision outcome value existed before this run.

## 1. Contract and provenance

- execution commit: `f7a9c799b5e5c7966d712362778734219a0558f3`
- executed at: 2026-07-10T16:27:14Z
- frozen-input verification: **0 failures** (gate: scripts/j1a_data_readiness.py::verify_frozen_inputs)
  - `g3_price_cache.db`: sha256 `a5bb09f87fa6566588baa6638119ce7b0b349d02143c72415b49d426b14c2754` (2502656 bytes)
  - `j1a_price_cache.db`: sha256 `b735c227d8155816045eca4bbfc83b361caa64482252182ed4b2c227794eac28` (1990656 bytes)
  - `j1a_price_meta.json`: sha256 `e4a09b00a72a71f0f2659edcca7dc6df8062011e210699f798095248c36b2b89` (376 bytes)
  - `j1a_treasury.json`: sha256 `b1df6fa21dfffb281c2f363e439609457a5c2765f873420f8dcac91ca8c529e7` (127924 bytes)
- calibration: B = 2000, seed 20180101, RNG policy `grouped_shared_calendar_single_stream` (single J2 placement group: cells 13-16 share one drawn calendar per placement)
- frozen J2 manifest: exactly 4 state-bearing `[-5, -1]` cells (13-16: raw_return, spy_relative_ar, sector_relative_ar, sar on the inherited KRE / SPY / XLF specification) and exactly 4 descriptive `[-20, -1]` diagnostics (D1-D4, same metrics). No ninth timing statistic exists.
- timing windows: state-bearing `[-5, -1]` (span 4); descriptive `[-20, -1]` (span 19); the official anchor mapping is the inherited last-session-at-or-before rule, unchanged; the anchor session is outside both windows.
- collision boundary: the exact `[t, t+1]` sessions consumed by the existing 1d response - no proximity buffer of any width. C1 = frozen finite family (FOMC self, checked invariant; BLS CPI; BLS Employment Situation). C2 = the tracked `opec-known-date-exclusion-register@i0-v1`. C3 = background environment, context only, never an exclusion rule.
- collision status is metadata: the primary denominator retains all frozen FOMC events in every primary readout.
- non-claims: see section 9; no hypothesis-test vocabulary appears anywhere; calibration percentiles are placement positions only; MEMPs from different windows, references, or availability sets are not value-comparable.

## 2. State-bearing [-5, -1] surface (cells 13-16, frozen order)

| # | measurement | metric | window | events avail/att | ref N | MEMP | calib pct | node state |
|---|---|---|---|---|---|---|---|---|
| 13 | KRE | raw_return | [-5, -1] | 65 / 65 | 1427 | 0.491240 | 0.424500 | ORDINARY_UNRESOLVED |
| 14 | KRE | spy_relative_ar | [-5, -1] | 65 / 65 | 1427 | 0.537491 | 0.716500 | ORDINARY_UNRESOLVED |
| 15 | KRE | sector_relative_ar | [-5, -1] | 65 / 65 | 1427 | 0.609671 | 0.970000 | ELEVATED |
| 16 | KRE | sar | [-5, -1] | 65 / 65 | 1427 | 0.572530 | 0.889000 | ELEVATED |

### Stability overlays (overlays never rewrite a state)

| # | metric | LOYO flips/runs | LOEO flips/runs | F3 ref N -> canonical N | F3 decimated MEMP | F3 sign flip |
|---|---|---|---|---|---|---|
| 13 | raw_return | 4/8 | 32/65 | 1427 -> 297 | 0.464646 | False |
| 14 | spy_relative_ar | 1/8 | 0/65 | 1427 -> 297 | 0.518519 | False |
| 15 | sector_relative_ar | 0/8 | 0/65 | 1427 -> 297 | 0.589226 | False |
| 16 | sar | 0/8 | 0/65 | 1427 -> 297 | 0.548822 | False |

### Per-cell denominators and availability

- **Cell 13 - KRE raw_return**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1427 (excluded by event proximity 584); placement year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 14 - KRE spy_relative_ar**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1427 (excluded by event proximity 584); placement year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 15 - KRE sector_relative_ar**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1427 (excluded by event proximity 584); placement year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 16 - KRE sar**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1427 (excluded by event proximity 584); placement year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

## 3. Descriptive [-20, -1] diagnostics (D1-D4, frozen order; explicitly no state)

Frozen rule: descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure. The ordinary-reference and per-year calibration construction is structurally infeasible under the frozen geometry (j0-v1 section 10); no pseudo-calibration is invented, and no node state (ELEVATED, ORDINARY / UNRESOLVED, LOWER-MAGNITUDE, DISCORDANT) may be assigned.

| diag | metric | window | events avail/att | median response | median |response| | direction |
|---|---|---|---|---|---|---|
| D1 | raw_return | [-20, -1] | 65 / 65 | 0.003612 | 0.050052 | positive |
| D2 | spy_relative_ar | [-20, -1] | 65 / 65 | -0.003032 | 0.039001 | negative |
| D3 | sector_relative_ar | [-20, -1] | 65 / 65 | -0.001372 | 0.028352 | negative |
| D4 | sar | [-20, -1] | 65 / 65 | -0.071910 | 0.616683 | negative |

- **D1 - raw_return**: descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure.

- **D2 - spy_relative_ar**: descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure.

- **D3 - sector_relative_ar**: descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure.

- **D4 - sar**: descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure.

### Fail-loud reference funnel (documentation only)

- era ordinary candidates: 2011; response-gate casualties: 0; span-19 exclusion casualties: 2010; eligible total: 1
- eligible per year: {"2018": 1}
- event year vector: {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
- per-year placement matching mechanically executable: False - and regardless, the frozen design assigns these diagnostics no reference, no MEMP, no calibration, and no state.

## 4. Timing comparison with the published J1B result

The published J1B 12-cell `[t, t+1]` surface is the post-anchor robustness result (Class B; tracked in `stats/J1B_FOMC_ROBUSTNESS_RESULTS.md`); the inherited Mission I 1d cells are Class A facts. The J2 `[-5, -1]` cells are a different statistical family with their own reference geometry: MEMPs are **not value-comparable** across the families and are never merged; the comparison below is state-based only, under the frozen interpretation rules of j0-v1 section 10.

| published J1B cell | lens | node state |
|---|---|---|
| 1 KRE | rolling_beta_ar | ELEVATED |
| 2 IAT | rolling_beta_ar | ELEVATED |
| 3 KBE | rolling_beta_ar | ELEVATED |
| 4 XLF | rolling_beta_ar | ELEVATED |
| 5 VFH | rolling_beta_ar | ELEVATED |
| 6 IAT | raw_return | ELEVATED |
| 7 KBE | raw_return | ELEVATED |
| 8 XLF | raw_return | ELEVATED |
| 9 VFH | raw_return | ELEVATED |
| 10 2Y_CMT | raw_change | ELEVATED |
| 11 2S10S_CMT | raw_change | ELEVATED |
| 12 SHY | raw_return | ELEVATED |

- cell 13 (raw_return): pre-event state ORDINARY_UNRESOLVED beside the published post-anchor ELEVATED surface - the result is more concentrated around the official anchor under daily measurement.
- cell 14 (spy_relative_ar): pre-event state ORDINARY_UNRESOLVED beside the published post-anchor ELEVATED surface - the result is more concentrated around the official anchor under daily measurement.
- cell 15 (sector_relative_ar): pre-event state ELEVATED beside the published post-anchor ELEVATED surface - the daily data do not isolate whether the response began before or continued through the official event window.
- cell 16 (sar): pre-event state ELEVATED beside the published post-anchor ELEVATED surface - the daily data do not isolate whether the response began before or continued through the official event window.

Scheduled-event limitation (frozen): FOMC is a scheduled event family; anticipation is structurally plausible; daily close-to-close data cannot resolve intraday repricing, and the 2 p.m. ET statement release sits before the anchor-session close, so part of the same-session reaction is outside every daily window. No intraday timing claim is made.

## 5. Collision register (exact [t, t+1] overlap only)

- C1 family 1 - FOMC self-collision: checked invariant holds (minimum anchor spacing 8 sessions; 0 violations); no frame event shares another's [t, t+1] interval.
- C1 families 2-3 - BLS CPI and BLS Employment Situation: **unadjudicable in this execution**. no source-pinned BLS release register covers the frozen era: the in-repo macro calendar is an app-layer display list (self-declared approximate) missing era years {'CPI': [2018, 2019, 2020, 2021, 2022, 2023, 2024], 'NFP': [2018, 2019, 2020, 2021, 2022, 2023, 2024]}; the C1 CPI / Employment Situation branch is unadjudicable in this execution and no substitute calendar is fetched.
- C2 - cross-channel compound events: the tracked `opec-known-date-exclusion-register@i0-v1` (41 calendar dates) yields **0** tagged FOMC event(s).
- C3: background environment; context only - C3 is never an exclusion rule and no attempt is made to clean the world.
- Events outside the adjudicable registers are described as outside known-register collisions only; no stronger clean-window claim exists.

## 6. Collision sensitivity (denominator-preserving re-reads of the existing J1B cells)

The primary J1B result keeps all frozen FOMC events; these subset re-reads qualify it and never replace it. No numeric event floor governs any subset; feasibility is algorithmic only.

- **all**: exact N = 65.
- **collision_free**: exact N = 65 (outside known-register collisions under the adjudicable registers (C2 OPEC known-date register; C1 FOMC-self by checked invariant); the C1 CPI / Employment Situation branch is unadjudicable in this execution, so freedom from those releases is NOT certified).
- **c1_tagged**: unadjudicable - no source-pinned BLS release register covers the frozen era: the in-repo macro calendar is an app-layer display list (self-declared approximate) missing era years {'CPI': [2018, 2019, 2020, 2021, 2022, 2023, 2024], 'NFP': [2018, 2019, 2020, 2021, 2022, 2023, 2024]}; the C1 CPI / Employment Situation branch is unadjudicable in this execution and no substitute calendar is fetched.
- **c2_tagged**: exact N = 0.

### Sensitivity re-read: all

- The all-events family IS the published J1B surface (section 4 table); it was recomputed through the identical frozen machinery and reproduced exactly (6-decimal MEMP and calibration agreement asserted before this report was written). It is not restated as a new statistic.

### Sensitivity re-read: collision_free

- subset N = 65; calibration B = 2000, seed 20180101, policy `grouped_shared_calendar_single_stream` (fresh stream per sensitivity family; frozen J1B groups in fixed order).

| cell | measurement | lens | avail N | MEMP | calib pct | sensitivity read | LOYO | LOEO |
|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | 64 | 0.664719 | 0.998000 | ELEVATED | 0/8 | 0/64 |
| 2 | IAT | rolling_beta_ar | 64 | 0.691987 | 1.000000 | ELEVATED | 0/8 | 0/64 |
| 3 | KBE | rolling_beta_ar | 64 | 0.629382 | 0.983000 | ELEVATED | 0/8 | 0/64 |
| 4 | XLF | rolling_beta_ar | 64 | 0.658319 | 0.996000 | ELEVATED | 0/8 | 0/64 |
| 5 | VFH | rolling_beta_ar | 64 | 0.696717 | 0.999000 | ELEVATED | 0/8 | 0/64 |
| 6 | IAT | raw_return | 65 | 0.655837 | 0.997000 | ELEVATED | 0/8 | 0/65 |
| 7 | KBE | raw_return | 65 | 0.669604 | 0.999500 | ELEVATED | 0/8 | 0/65 |
| 8 | XLF | raw_return | 65 | 0.645925 | 0.995500 | ELEVATED | 0/8 | 0/65 |
| 9 | VFH | raw_return | 65 | 0.670705 | 0.999000 | ELEVATED | 0/8 | 0/65 |
| 10 | 2Y_CMT | raw_change | 65 | 0.615576 | 0.981500 | ELEVATED | 0/8 | 0/65 |
| 11 | 2S10S_CMT | raw_change | 65 | 0.652716 | 0.996000 | ELEVATED | 0/8 | 0/65 |
| 12 | SHY | raw_return | 65 | 0.579295 | 0.934000 | ELEVATED | 0/8 | 0/65 |

- subset event-year distribution: {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

### Sensitivity re-read: c1_tagged

- unadjudicable: no source-pinned BLS release register covers the frozen era: the in-repo macro calendar is an app-layer display list (self-declared approximate) missing era years {'CPI': [2018, 2019, 2020, 2021, 2022, 2023, 2024], 'NFP': [2018, 2019, 2020, 2021, 2022, 2023, 2024]}; the C1 CPI / Employment Situation branch is unadjudicable in this execution and no substitute calendar is fetched.

### Sensitivity re-read: c2_tagged

- subset N = 0; calibration B = 2000, seed 20180101, policy `grouped_shared_calendar_single_stream` (fresh stream per sensitivity family; frozen J1B groups in fixed order).

| cell | measurement | lens | avail N | MEMP | calib pct | sensitivity read | LOYO | LOEO |
|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 2 | IAT | rolling_beta_ar | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 3 | KBE | rolling_beta_ar | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 4 | XLF | rolling_beta_ar | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 5 | VFH | rolling_beta_ar | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 6 | IAT | raw_return | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 7 | KBE | raw_return | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 8 | XLF | raw_return | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 9 | VFH | raw_return | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 10 | 2Y_CMT | raw_change | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 11 | 2S10S_CMT | raw_change | 0 | insufficient subset under the frozen procedure | - | - | - | - |
| 12 | SHY | raw_return | 0 | insufficient subset under the frozen procedure | - | - | - | - |

## 7. What the timing challenge supports

The frozen timing evidence is mixed, with cross-metric disagreement
inside the four-cell [-5, -1] surface:

- On the raw-return and SPY-relative lenses (cells 13-14, both
  ORDINARY / UNRESOLVED), the published post-anchor elevation is not
  accompanied by comparable frozen pre-event elevation: under the
  frozen interpretation rule, the result is more concentrated around
  the official anchor under daily measurement.
- On the sector-relative and SAR lenses (cells 15-16, both ELEVATED,
  0 LOYO / 0 LOEO / 0 F3 flips), the pre-event window carries the
  elevated state beside the elevated post-anchor surface: the daily
  data do not isolate whether the response began before or continued
  through the official event window.
- The response is not primarily pre-event on any lens, so the frozen
  section-15 withdrawal condition for the 1d concentration claim is
  not triggered; the concentration reading is lens-dependent as stated
  above.
- Collision qualification: under the adjudicable frozen registers, no
  FOMC event carries an exact [t, t+1] collision tag (FOMC-self holds
  as a checked invariant at minimum spacing 8; the C2 OPEC register
  tags 0 of 65). The known-register collision-free subset is therefore
  the full frozen frame, and its re-read reproduces the published J1B
  surface by construction - the published readout survives the
  collision-free sensitivity vacuously, because the adjudicable
  registers identify no collision to remove.

## 8. What weakened or remained unresolved

- The raw-return pre-event cell (13) is knife-edge fragile: MEMP
  0.491240 sits essentially at the 0.5 boundary, and the direction of
  (MEMP - 0.5) flips under 4/8 LOYO and 32/65 LOEO perturbations. Its
  ORDINARY / UNRESOLVED state is assigned once from the full-sample
  pair and is never rewritten by overlays, but the fragility is
  disclosed and mirrors the Mission I FOMC 5d raw knife-edge pattern.
- The four-cell surface disagrees across metrics (two ORDINARY /
  UNRESOLVED, two ELEVATED); no single pre-event reading exists.
- The C1 BLS CPI / Employment Situation branch is unadjudicable in
  this execution: the repository contains no source-pinned BLS release
  register covering the frozen era, so freedom from those releases is
  not certified for any event, and the C1-tagged sensitivity cannot
  execute. No substitute calendar was fetched.
- The C2-tagged subset is empty: insufficient subset under the frozen
  procedure; the C2-tagged descriptive comparison cannot execute.
- The [-20, -1] diagnostics remain descriptive-only by frozen design;
  the fail-loud funnel (1 eligible anchor, 2018 only; per-year
  matching not executable) mechanically confirms the pre-declared
  structural infeasibility. Their signed medians are small and mixed
  in direction and carry no ordinary-reference position.
- All of this is same-sample Class B evidence: post-outcome robustness
  under prospectively frozen new tests, never independent historical
  confirmation.

## 9. What J2 does not establish

- an anticipation mechanism;
- information leakage;
- insider activity of any kind;
- causality;
- prediction;
- tradeability;
- alpha;
- independent historical confirmation of Mission I or J1B;
- intraday response timing (daily close-to-close data cannot resolve
  it, and the 2 p.m. ET release sits before the anchor-session close);
- graph propagation (edge adjudication belongs to J3);
- any hypothesis-test conclusion (calibration percentiles are
  placement positions, not test outcomes);
- that any window is free of competing events (only outside
  known-register collisions, and the C1 macro branch is unadjudicable
  here);
- that MEMPs from different windows, references, or availability sets
  are value-comparable.

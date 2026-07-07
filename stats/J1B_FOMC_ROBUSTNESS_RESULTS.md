# J1B FOMC robustness results - the frozen 12-cell surface (Mission J)

Contract: `j1b-live-execution-v1` executing `j1b-preoutcome-engine-v1` under the locked j0-v1 constitution and its outcome-blind clarifications. This is the **first real J1B execution**: no Mission J outcome value existed before this run.

- execution commit: `2ec68108affc1d3e084c7242e5b13669e3c5d76d`
- executed at: 2026-07-07T00:11:57Z
- frozen-input verification: **0 failures** (gate: scripts/j1a_data_readiness.py::verify_frozen_inputs; 0 recorded)
  - `g3_price_cache.db`: sha256 `a5bb09f87fa6566588baa6638119ce7b0b349d02143c72415b49d426b14c2754` (2502656 bytes)
  - `j1a_price_cache.db`: sha256 `b735c227d8155816045eca4bbfc83b361caa64482252182ed4b2c227794eac28` (1990656 bytes)
  - `j1a_price_meta.json`: sha256 `e4a09b00a72a71f0f2659edcca7dc6df8062011e210699f798095248c36b2b89` (376 bytes)
  - `j1a_treasury.json`: sha256 `b1df6fa21dfffb281c2f363e439609457a5c2765f873420f8dcac91ca8c529e7` (127924 bytes)
- calibration: B = 2000, seed 20180101, RNG policy `grouped_shared_calendar_single_stream`
- events: 65 frame-complete FOMC decisions (G1A); era 2018-01-01 .. 2025-12-31; window [t, t+1]

Cells appear in frozen J0 order; none is highlighted, none is ordered by value, and no hypothesis-test vocabulary appears. MEMPs from cells with different references or event sets are positioned per cell and are **not value-comparable** across cells. Edge adjudication belongs to J3 and does not appear here.

## Complete 12-cell surface (frozen order)

| # | measurement | lens | role | M | evid. | events avail/att | ref N | MEMP | calib pct | node state |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | A instrument; B statistic | 64 / 65 | 1797 | 0.664719 | 0.998000 | ELEVATED |
| 2 | IAT | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | B instrument; B statistic | 64 / 65 | 1797 | 0.691987 | 1.000000 | ELEVATED |
| 3 | KBE | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | B instrument; B statistic | 64 / 65 | 1797 | 0.629382 | 0.983000 | ELEVATED |
| 4 | XLF | rolling_beta_ar | broad_financial_sector | M3 | A instrument; B statistic | 64 / 65 | 1797 | 0.658319 | 0.996000 | ELEVATED |
| 5 | VFH | rolling_beta_ar | broad_financial_sector | M3 | B instrument; B statistic | 64 / 65 | 1797 | 0.696717 | 0.999000 | ELEVATED |
| 6 | IAT | raw_return | balance_sheet_sensitive_second_order | M3 | B instrument; B statistic | 65 / 65 | 1816 | 0.655837 | 0.997000 | ELEVATED |
| 7 | KBE | raw_return | balance_sheet_sensitive_second_order | M3 | B instrument; B statistic | 65 / 65 | 1816 | 0.669604 | 0.999500 | ELEVATED |
| 8 | XLF | raw_return | broad_financial_sector | M3 | A instrument; B statistic | 65 / 65 | 1816 | 0.645925 | 0.995500 | ELEVATED |
| 9 | VFH | raw_return | broad_financial_sector | M3 | B instrument; B statistic | 65 / 65 | 1816 | 0.670705 | 0.999000 | ELEVATED |
| 10 | 2Y_CMT | raw_change | policy_rates_repricing | M2 | B statistic | 65 / 65 | 1804 | 0.615576 | 0.981500 | ELEVATED |
| 11 | 2S10S_CMT | raw_change | curve_shape_contextual_layer | M2 | B statistic (underlying series A as a state) | 65 / 65 | 1804 | 0.652716 | 0.996000 | ELEVATED |
| 12 | SHY | raw_return | policy_rates_repricing | M3 | B instrument; B statistic | 65 / 65 | 1816 | 0.579295 | 0.934000 | ELEVATED |

### Stability overlays (frozen order)

| # | measurement/lens | LOYO flips/runs | LOEO flips/runs | F3 ref N -> canonical N | F3 decimated MEMP | F3 sign flip |
|---|---|---|---|---|---|---|
| 1 | KRE rolling_beta_ar | 0/8 | 0/64 | 1797 -> 917 | 0.655398 | False |
| 2 | IAT rolling_beta_ar | 0/8 | 0/64 | 1797 -> 917 | 0.691930 | False |
| 3 | KBE rolling_beta_ar | 0/8 | 0/64 | 1797 -> 917 | 0.621047 | False |
| 4 | XLF rolling_beta_ar | 0/8 | 0/64 | 1797 -> 917 | 0.654308 | False |
| 5 | VFH rolling_beta_ar | 0/8 | 0/64 | 1797 -> 917 | 0.695202 | False |
| 6 | IAT raw_return | 0/8 | 0/65 | 1816 -> 927 | 0.645092 | False |
| 7 | KBE raw_return | 0/8 | 0/65 | 1816 -> 927 | 0.665588 | False |
| 8 | XLF raw_return | 0/8 | 0/65 | 1816 -> 927 | 0.635383 | False |
| 9 | VFH raw_return | 0/8 | 0/65 | 1816 -> 927 | 0.656958 | False |
| 10 | 2Y_CMT raw_change | 0/8 | 0/65 | 1804 -> 920 | 0.611957 | False |
| 11 | 2S10S_CMT raw_change | 0/8 | 0/65 | 1804 -> 920 | 0.638587 | False |
| 12 | SHY raw_return | 0/8 | 0/65 | 1816 -> 927 | 0.580367 | False |

### Per-cell denominators and availability (frozen order)

- **Cell 1 - KRE (rolling_beta_ar)**: basis adjusted; attempted 65, available 64; event-year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1797 (excluded by event proximity 192); placement group year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
  - unavailable event 2018-01-31: insufficient_history_252_20

- **Cell 2 - IAT (rolling_beta_ar)**: basis adjusted; attempted 65, available 64; event-year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1797 (excluded by event proximity 192); placement group year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
  - unavailable event 2018-01-31: insufficient_history_252_20

- **Cell 3 - KBE (rolling_beta_ar)**: basis adjusted; attempted 65, available 64; event-year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1797 (excluded by event proximity 192); placement group year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
  - unavailable event 2018-01-31: insufficient_history_252_20

- **Cell 4 - XLF (rolling_beta_ar)**: basis adjusted; attempted 65, available 64; event-year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1797 (excluded by event proximity 192); placement group year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
  - unavailable event 2018-01-31: insufficient_history_252_20

- **Cell 5 - VFH (rolling_beta_ar)**: basis adjusted; attempted 65, available 64; event-year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1797 (excluded by event proximity 192); placement group year vector {"2018": 7, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
  - unavailable event 2018-01-31: insufficient_history_252_20

- **Cell 6 - IAT (raw_return)**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1816 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 7 - KBE (raw_return)**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1816 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 8 - XLF (raw_return)**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1816 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 9 - VFH (raw_return)**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1816 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 10 - 2Y_CMT (raw_change)**: basis official_level; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1804 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 11 - 2S10S_CMT (raw_change)**: basis official_level; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1804 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

- **Cell 12 - SHY (raw_return)**: basis adjusted; attempted 65, available 65; event-year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}; reference 1816 (excluded by event proximity 195); placement group year vector {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8, "2023": 8, "2024": 8, "2025": 8}

## Role-level panel summaries (frozen modifiers; no edge adjudication)

### policy_rates_repricing
- members: 2Y_CMT, SHY (primary: 2Y_CMT)
- 2Y_CMT: ELEVATED
- SHY: ELEVATED
- role modifier: **BROAD MEASUREMENT CONSISTENCY**

### balance_sheet_sensitive_second_order
- members: KRE, IAT, KBE (primary: KRE)
- KRE: ELEVATED
- IAT: ELEVATED
- KBE: ELEVATED
- role modifier: **BROAD MEASUREMENT CONSISTENCY**

### broad_financial_sector
- members: XLF, VFH (primary: XLF)
- XLF: ELEVATED
- VFH: ELEVATED
- role modifier: **BROAD MEASUREMENT CONSISTENCY**

## Curve-shape contextual layer (cell 11)

- 2S10S_CMT: **ELEVATED** - state-bearing and contextual; outside the rates-repricing proxy panel, outside role modifiers, outside edge adjudication (J0 section 12.2). It neither rescues nor contradicts the rates-role panel.

## Bounded comparison with the inherited Mission I specification

Question (J0 section 13): does the inherited FOMC 1d finding appear dependent on the already-observed KRE asset choice or the fixed beta=1 benchmark treatment?

The inherited Mission I FOMC 1d surface (**Class A: outcome-exposed before Mission J existed**; KRE / XLF / SPY specification, 65 events, reference 1816, quoted from the tracked I2C artifacts, not recomputed):

| inherited Mission I metric | MEMP | calibration pct |
|---|---|---|
| raw_return | 0.674559 | 0.997000 |
| spy_relative_ar (beta=1) | 0.672357 | 0.999500 |
| sector_relative_ar (beta=1) | 0.662996 | 0.997000 |
| sar | 0.725771 | 1.000000 |

All four inherited 1d cells carried 0/8 LOYO, 0/65 LOEO, and 0/4 F3 flips (I2C-B). The J1B cells above are **Class B: post-outcome robustness statistics under prospectively frozen new tests** - same-sample evidence that may strengthen, weaken, localize, or break the inherited reading, never independent historical confirmation. Denominator differences are preserved: the rolling-beta cells cover fewer events than the inherited 65 (the 252/20 history boundary excludes 2018-01-31) and use their own reference sets; the inherited and new MEMPs are not value-comparable and are never merged into one family.

## What survived

Every frozen state and overlay rule supports one reading: the inherited
FOMC 1d response-magnitude elevation survived the frozen challenge on
every axis this surface tests.

- Not asset-specific: the elevation is not a KRE artifact. IAT and KBE
  are ELEVATED under both frozen lenses, and the regional-bank panel is
  BROAD MEASUREMENT CONSISTENCY.
- Not benchmark-sensitive: replacing the inherited beta=1 treatment with
  the frozen 252/20 OLS-with-intercept market model left every equity
  cell ELEVATED (cells 1-5). The frozen model did not reverse the
  inherited result.
- The broad financial sector carried the state (XLF and VFH, both
  lenses; BROAD MEASUREMENT CONSISTENCY).
- The rates-repricing role is ELEVATED on its frozen two-member panel
  (2Y CMT, M2 primary; SHY, M3 alternate; BROAD MEASUREMENT
  CONSISTENCY) - a role-consistent reading under the frozen modifier
  rules, subject to the measurement limitation below.
- Perturbation stability: 0 LOYO flips across 96 runs, 0 LOEO flips
  across 775 runs, 0 F3 sign flips across all 12 cells.

## What weakened or broke

Under the frozen rules, nothing on this surface weakened or broke: no
benchmark sensitivity, no asset specificity, no panel measurement
disagreement, and no overlay fragility was observed. A null,
lower-magnitude, or fragile cell would have been reported here with
identical completeness; none occurred.

## What remains unresolved

- The ideal M1 policy-repricing measure (fed funds futures / OIS) is
  unavailable in the frozen substrate; the rates-role reading rests on
  an M2 official series plus an M3 investable proxy, and the 2Y CMT
  blends policy expectations with term premium (J0 section 8). The
  rates-role elevation is measurement-limited accordingly.
- Daily close-to-close data cannot resolve whether the response is
  anticipated before or concentrated at the official anchor; the frozen
  timing challenge belongs to J2 and has not been run.
- Known-register collision structure is untested; the frozen [t, t+1]
  collision work also belongs to J2.
- All of this is same-sample Class B evidence: post-outcome robustness
  under prospectively frozen new tests. It may never be described as
  independent historical confirmation of the Mission I finding.
- Denominator differences persist by design: the five rolling-beta
  cells cover 64 of the inherited 65 events and their own 1797-anchor
  reference; MEMPs across cells are not value-comparable.
- The 12 frozen cells are correlated robustness views over overlapping
  events, assets, benchmarks, and reference structures. They are not 12
  independent replications or 12 independent statistical tests.

## What J1B does not establish

- causality;
- prediction;
- tradeability;
- alpha;
- independent historical confirmation;
- mechanism proof (edge adjudication belongs to J3 under the frozen
  five-state rules; no edge state is asserted here);
- intraday timing;
- graph propagation;
- any hypothesis-test conclusion (calibration percentiles are placement
  positions, not test outcomes).

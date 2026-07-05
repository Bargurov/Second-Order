# G4 structural freeze (Mission G, g0-v1)

Freeze version: `g4-structural-freeze-v1`. This is the second freeze of the two-freeze governance (protocol section 8): final state design, secondary tags, designed-contrast recruitment, numeric support floors, and the G6 comparison manifest - frozen from OUTCOME-BLIND candidate structure before any market-response value is inspected.

Inputs consulted (complete enumeration, per the protocol's G4 duty): candidate identity ledgers (G1A frame, G1B reservoir); lane; source family; event date; calendar year; conservative cutoff; state values and state availability from the G2 substrate; occupancy; missingness structure; unique-date counts; lane/year concentration; the G3A mechanical-eligibility funnel (tracked artifact); the G3B classification-attrition finding (tracked artifact); economic interpretability of the G0 definitions. No absolute return, AR, SAR, CAR, sector-relative response, sign, direction, magnitude, or outcome label was computed, read, persisted, or summarized anywhere in this slice; structural inputs are validated against a tested field whitelist.

## 1. Universe reconciliation (exact, fail-loud)

| check | value |
|---|---|
| frame-complete FOMC | 65 |
| OPEC designed reservoir | 32 |
| total | 97 |
| unique candidate ids | 97 |
| unique event dates | 97 |
| identity-valid (G3 artifact) | 97 |
| canonical event-study eligible | 97 |
| sector-relative eligible | 97 |

## 2. Frozen numeric support floor

`MIN_UNIQUE_DATES = 11` for every tag category and every G6 comparison cell. Derivation (structural, enumerated): the largest single lane-year occupancy in the universe is 10; requiring strictly more unique dates than any single lane-year can supply means no sufficient category or cell can be the artifact of one calendar year of one lane (10 + 1 = 11). Cells below the floor are retained in the manifest and reported as `insufficient_n` - reported, never hidden (protocol section 14).

## 3. Final state design

### `fed_policy_path` -> **primary_retained**

- coverage: 97/97 (by lane: designed_contrast: 32, frame_complete_historical: 65)
- reason: full coverage: available for every candidate in both lanes and all years

### `vix_level_percentile` -> **primary_retained**

- coverage: 97/97 (by lane: designed_contrast: 32, frame_complete_historical: 65)
- reason: full coverage: available for every candidate in both lanes and all years

### `spy_trend_ma200` -> **primary_retained**

- coverage: 97/97 (by lane: designed_contrast: 32, frame_complete_historical: 65)
- reason: full coverage: available for every candidate in both lanes and all years

### `curve_2s10s` -> **primary_retained**

- coverage: 97/97 (by lane: designed_contrast: 32, frame_complete_historical: 65)
- reason: full coverage: available for every candidate in both lanes and all years

### `credit_hy_oas` -> **secondary_subset_only**

- coverage: 36/97 (by lane: designed_contrast: 16, frame_complete_historical: 20)
- reason: era-structural partial coverage: every missing cutoff precedes every available cutoff (single source-era boundary), so availability is a source-level property of calendar time; the dimension cannot enter the primary cross-period vector without confounding state availability with era, but is usable as an explicitly era-bounded secondary subset lens
- era boundary: last missing cutoff 2023-06-13, first available cutoff 2023-07-25
- structural limitations: the surviving source window is a rolling three-year license (G2 section 3); the candidate-level inputs in use are preserved in `stats/G2D_CREDIT_POINT_IN_TIME_EVIDENCE.md`; missingness follows the source-era boundary with no candidate-level attrition inside the window; every use is era-bounded and descriptive only

The primary cross-period state vector is therefore: `fed_policy_path`, `vix_level_percentile`, `spy_trend_ma200`, `curve_2s10s`. `credit_hy_oas` may not enter it: with 61/97 missing along the source-era boundary, any cross-period conditioning on credit would compare eras, not states. It is frozen as an era-bounded secondary subset lens only.

## 4. Frozen secondary tags

Continuous state values remain canonical everywhere; tags are secondary derived views. Only sign-based rules whose zero is definitionally meaningful were candidates; every retained rule and every rejection is recorded.

### `fed_policy_path` -> **tag_retained**

- rule: `easing if value < 0, hold if value == 0, tightening if value > 0`
- reason: sign-based tag: zero is definitionally meaningful (no net policy-rate change over the frozen six-month lookback); every category clears the frozen unique-date floor
- occupancy (total 97):
  - `easing`: 29 candidates on 29 unique dates | by lane: designed_contrast: 12, frame_complete_historical: 17 | by year: 2019: 4, 2020: 8, 2024: 4, 2025: 13
  - `hold`: 33 candidates on 33 unique dates | by lane: designed_contrast: 11, frame_complete_historical: 22 | by year: 2019: 2, 2020: 4, 2021: 11, 2022: 2, 2024: 9, 2025: 5
  - `tightening`: 35 candidates on 35 unique dates | by lane: designed_contrast: 9, frame_complete_historical: 26 | by year: 2018: 10, 2019: 4, 2022: 10, 2023: 11

### `vix_level_percentile` -> **continuous_only**

- reason: continuous only: the percentile is already a normalized state; any cut point (0.5, 0.8, quartiles) would be an arbitrary threshold not derivable from the G0 definition

### `spy_trend_ma200` -> **tag_retained**

- rule: `below_ma if value < 0 else above_ma`
- reason: sign-based tag: zero is definitionally meaningful (price exactly at its 200-session moving average); every category clears the frozen unique-date floor
- occupancy (total 97):
  - `below_ma`: 23 candidates on 23 unique dates | by lane: designed_contrast: 8, frame_complete_historical: 15 | by year: 2018: 2, 2019: 1, 2020: 3, 2022: 12, 2023: 1, 2025: 4
  - `above_ma`: 74 candidates on 74 unique dates | by lane: designed_contrast: 24, frame_complete_historical: 50 | by year: 2018: 8, 2019: 9, 2020: 9, 2021: 11, 2023: 10, 2024: 13, 2025: 14

### `curve_2s10s` -> **tag_retained**

- rule: `inverted if value < 0 else non_inverted`
- reason: sign-based tag: zero is definitionally meaningful (flat 2s10s spread); every category clears the frozen unique-date floor
- occupancy (total 97):
  - `inverted`: 26 candidates on 26 unique dates | by lane: designed_contrast: 9, frame_complete_historical: 17 | by year: 2022: 7, 2023: 11, 2024: 8
  - `non_inverted`: 71 candidates on 71 unique dates | by lane: designed_contrast: 23, frame_complete_historical: 48 | by year: 2018: 10, 2019: 10, 2020: 12, 2021: 11, 2022: 5, 2024: 5, 2025: 18

### `credit_hy_oas` -> **continuous_only**

- reason: non-primary dimension (secondary_subset_only); tags apply to the primary state vector only

Rejected tag ideas (recorded, not silently skipped): composite multi-dimension regime labels and any 12-cell regime grid (banned by task and protocol); VIX-percentile cut points (arbitrary constants); HY OAS spread-level cuts (arbitrary, and the dimension is era-bounded secondary); moving-average-distance magnitude bands (arbitrary); any threshold chosen for response separation (outcome-dependent, firewall-banned).

## 5. Designed-contrast recruitment ledger

Rule `g4-designed-recruitment-v1` (deterministic, outcome-blind, applied once): recruit a reservoir candidate iff it is identity-valid in the G1B reservoir ledger, mechanically eligible (section 1 reconciles the G3 funnel at 97/97 before recruitment runs), and carries a complete primary state vector (`fed_policy_path`, `vix_level_percentile`, `spy_trend_ma200`, `curve_2s10s`). No candidate is recruited or excluded for remembered historical importance, and no response value exists anywhere in the path.

- reservoir denominator: 32
- recruited denominator: 32
- non-recruited: 0
- frame lane preserved intact: 65 rows (never filtered)

Recruited candidate ids (32):

- `opec-2018-06-23-conformity-return`
- `opec-2018-12-07-cut-1p2`
- `opec-2019-07-02-extension`
- `opec-2019-12-06-deepen-1p7`
- `opec-2020-04-12-cut-9p7`
- `opec-2020-06-06-extension`
- `opec-2020-12-03-restoration-start`
- `opec-2021-01-05-feb-mar-levels`
- `opec-2021-04-01-gradual-return`
- `opec-2021-07-18-monthly-400k`
- `opec-2022-06-02-accelerate-648k`
- `opec-2022-08-03-sep-100k`
- `opec-2022-09-05-oct-minus-100k`
- `opec-2022-10-05-cut-2mbd`
- `opec-2023-04-02-voluntary-1p16`
- `opec-2023-06-04-2024-levels`
- `opec-2023-11-30-voluntary-2p2`
- `opec-2024-03-03-q2-extension`
- `opec-2024-06-02-extension-schedule`
- `opec-2024-09-05-two-month-delay`
- `opec-2024-11-03-one-month-delay`
- `opec-2024-12-05-april-start`
- `opec-2025-03-03-activation`
- `opec-2025-04-03-may-411k`
- `opec-2025-05-03-jun-411k`
- `opec-2025-06-01-jul-411k`
- `opec-2025-07-05-aug-548k`
- `opec-2025-08-03-sep-547k`
- `opec-2025-09-07-oct-137k`
- `opec-2025-10-05-nov-137k`
- `opec-2025-11-02-dec-137k-pause`
- `opec-2025-11-30-2026-hold`

Non-recruited candidate ids: none. Every reservoir row passes every structural gate, so the frozen rule recruits the full reservoir; selective recruitment would have required a structural discriminator that does not exist, and inventing one would be arbitrary.

Discovery provenance: the reservoir is `opec-production-policy-reservoir-2018-2025@v1` (`stats/G1B_OPEC_DESIGNED_RESERVOIR.md`), a designed-recruitment ledger over a NON-ENUMERABLE event family; per-candidate discovery provenance lives in that ledger and is preserved unchanged.

Non-prevalence claim (explicit): the designed-contrast cohort is recruited evidence. It supports conditional contrasts and representative description only; it carries NO prevalence claim, NO frame-completeness claim, and no statistic pooled across sampling lanes may ever include it (protocol section 3).

## 6. G6 comparison manifest (frozen before any outcome is visible)

Every planned G6 comparison, exhaustively. All entries are conditional DESCRIPTIVE comparisons (protocol section 14): no p-value, no FDR figure, no significance claim; none belongs to any closed FDR pool. Within-lane conditioning only - no pooled FOMC + OPEC statistic of any kind. Response lenses for every entry are the four shipped lenses of the standardization spec (absolute, market-relative, sector-relative where eligible, SAR), displayed per the spec's discipline; the benchmarks below come from the frozen `g3-transmission-map-v1` with no event-specific ticker change.

| lane | family | primary | market | sector | state axis | use | denominator | unique dates | date span | sufficiency | claim tier | FDR scope |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| designed_contrast | opec | XOP | SPY | XLE | `credit_hy_oas` (secondary) | continuous | 16 | 16 | 2023-11-30 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `curve_2s10s` | categorical | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `curve_2s10s` | continuous | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `fed_policy_path` | categorical | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `fed_policy_path` | continuous | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `spy_trend_ma200` | categorical | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `spy_trend_ma200` | continuous | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| designed_contrast | opec | XOP | SPY | XLE | `vix_level_percentile` | continuous | 32 | 32 | 2018-06-23 .. 2025-11-30 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `credit_hy_oas` (secondary) | continuous | 20 | 20 | 2023-07-26 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `curve_2s10s` | categorical | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `curve_2s10s` | continuous | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `fed_policy_path` | categorical | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `fed_policy_path` | continuous | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `spy_trend_ma200` | categorical | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `spy_trend_ma200` | continuous | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |
| frame_complete_historical | fomc | KRE | SPY | XLF | `vix_level_percentile` | continuous | 65 | 65 | 2018-01-31 .. 2025-12-10 | sufficient | conditional_descriptive | none_descriptive_only |

Categorical cells (per retained tag, per lane):

- designed_contrast / `curve_2s10s`:
  - `inverted`: occupancy 9, unique dates 9, insufficient_n
  - `non_inverted`: occupancy 23, unique dates 23, sufficient
- designed_contrast / `fed_policy_path`:
  - `easing`: occupancy 12, unique dates 12, sufficient
  - `hold`: occupancy 11, unique dates 11, sufficient
  - `tightening`: occupancy 9, unique dates 9, insufficient_n
- designed_contrast / `spy_trend_ma200`:
  - `below_ma`: occupancy 8, unique dates 8, insufficient_n
  - `above_ma`: occupancy 24, unique dates 24, sufficient
- frame_complete_historical / `curve_2s10s`:
  - `inverted`: occupancy 17, unique dates 17, sufficient
  - `non_inverted`: occupancy 48, unique dates 48, sufficient
- frame_complete_historical / `fed_policy_path`:
  - `easing`: occupancy 17, unique dates 17, sufficient
  - `hold`: occupancy 22, unique dates 22, sufficient
  - `tightening`: occupancy 26, unique dates 26, sufficient
- frame_complete_historical / `spy_trend_ma200`:
  - `below_ma`: occupancy 15, unique dates 15, sufficient
  - `above_ma`: occupancy 50, unique dates 50, sufficient

Time-drift duty inherited from protocol section 13: every G6 exhibit must print each group's date span and period distribution; zero-calendar-overlap contrasts are automatically descriptive-only with the time table inline. The era-bounded credit entries satisfy this by construction (their spans are printed above).

## 7. Exclusions (inherited and structural)

- The J1 mechanism overlay is not a comparable cross-cohort axis and is excluded from G6 conditioning: the G3B finding shows classification coverage collapses across source registers (accepted 79.1% vs FOMC 0.0% / OPEC 3.1%), so no G6 comparison conditions on, stratifies by, or filters with the G3B/J1 mechanism labels, and no cross-cohort mechanism comparison uses that overlay.
- No pooled FOMC + OPEC 'overall effect' exists in the manifest; the pooling prohibition is symmetric and permanent.
- No event-specific ticker change: benchmarks are the frozen family-level map.
- The accepted 86 remain a separate lineage: they are never merged into historical G6 state-conditioned pools, and no accepted-vs-historical state-conditioned comparison is frozen here (the cohorts are temporally disjoint; any such display would be descriptive-only under section 13 and is out of scope for this manifest).
- Representative cases and descriptive archive reads never enter any closed FDR pool.
- The closed Phase 1 / Phase 2 FDR pools stay closed; nothing in G6 joins them.

## 8. Non-claims

No outcome inference, no regime prediction, no causal regime effect, and no trading interpretation. This freeze validates structure only: it says nothing about the direction, size, or existence of any market response, and nothing here is a p-value, an effective sample size, or an FDR figure. Not a trading, prediction, or recommendation surface.

## 9. Reproduction

```
python scripts/g4_structural_freeze.py --freeze   # regenerate this report (byte-identical)
python scripts/g4_structural_freeze.py --json     # structural JSON (whitelisted fields only)
python -m unittest tests.test_g4_structural_freeze
```

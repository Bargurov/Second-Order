# G6 frozen-manifest readout (Mission G, g0-v1)

Readout version: `g6a-frozen-manifest-readout-v1`. First outcome-visible Mission G surface: the SIXTEEN comparison entries frozen at G4 (before any outcome was inspected), executed exactly as written over the 97 promoted historical candidates. Complete raw evidence surface - every frozen entry, every cell, every metric, every horizon; nothing curated, nothing hidden, no 'top findings' section by design.

## 1. Method contract

- Universe: the 97 promoted `g_historical_evidence` rows only (65 frame-complete FOMC + 32 designed-contrast OPEC). The accepted 86, curated and representative cases, synthetic seeds, and every other archive row are excluded by construction (the loader reads only the promoted table).
- Outcome machinery: the shipped event-study gate (`event_study_validation.build_event_study_validation`) under the frozen `g3-transmission-map-v1` lenses (FOMC KRE/SPY/XLF; OPEC XOP/SPY/XLE) and the canonical adjusted-preferred basis. No parallel implementation.
- Metrics (exactly four): absolute asset return, SPY-relative AR, sector-relative AR, SAR. The gate also returns CAR; it is deliberately NOT extracted (no CAR, no SCAR, no VIX-scaled or ATR metric, no regression beta).
- Horizons (exactly the shipped triple): 1d, 5d, 20d.
- Continuous association: Spearman rank correlation only - descriptive, tie-aware, computed between the pre-event state value and each outcome metric. No p-value, no confidence interval, no significance label, no Pearson, no regression, no spline, no binning of continuous axes.
- Categorical cells: the three frozen G4 sign tags only, every cell reported with N, unique dates, mean, median, p25, p75, min, max, and sign counts. No pairwise significance test.
- Structural support floor: MIN_CELL_UNIQUE_DATES = 11, reused verbatim from the G4 freeze. It is a structural support floor only - not statistical power. Thin cells stay fully visible and are marked `insufficient_n`.

## 2. Denominator board (all 16 frozen entries)

| lane | family | axis | use | eligible N | unique dates | support note |
|---|---|---|---|---|---|---|
| designed_contrast | opec | `credit_hy_oas` | continuous | 16 | 16 | era-bounded secondary subset |
| designed_contrast | opec | `curve_2s10s` | categorical | 32 | 32 | - |
| designed_contrast | opec | `curve_2s10s` | continuous | 32 | 32 | - |
| designed_contrast | opec | `fed_policy_path` | categorical | 32 | 32 | - |
| designed_contrast | opec | `fed_policy_path` | continuous | 32 | 32 | - |
| designed_contrast | opec | `spy_trend_ma200` | categorical | 32 | 32 | - |
| designed_contrast | opec | `spy_trend_ma200` | continuous | 32 | 32 | - |
| designed_contrast | opec | `vix_level_percentile` | continuous | 32 | 32 | - |
| frame_complete_historical | fomc | `credit_hy_oas` | continuous | 20 | 20 | era-bounded secondary subset |
| frame_complete_historical | fomc | `curve_2s10s` | categorical | 65 | 65 | - |
| frame_complete_historical | fomc | `curve_2s10s` | continuous | 65 | 65 | - |
| frame_complete_historical | fomc | `fed_policy_path` | categorical | 65 | 65 | - |
| frame_complete_historical | fomc | `fed_policy_path` | continuous | 65 | 65 | - |
| frame_complete_historical | fomc | `spy_trend_ma200` | categorical | 65 | 65 | - |
| frame_complete_historical | fomc | `spy_trend_ma200` | continuous | 65 | 65 | - |
| frame_complete_historical | fomc | `vix_level_percentile` | continuous | 65 | 65 | - |

## 3. Complete raw evidence surface

### designed_contrast / `credit_hy_oas` (continuous) - XOP vs SPY, sector XLE

N = 16, unique dates = 16, era-bounded secondary subset (descriptive only).
State distribution: min +2.6600, p25 +2.8325, median +2.9400, p75 +3.2950, max +3.9000.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0100 | -0.0065 | -0.0160 | +0.0074 | -0.1067 | +0.0190 | 7/0/9 | -0.0427 |
| absolute asset return | 5d | -0.0080 | -0.0010 | -0.0328 | +0.0233 | -0.1262 | +0.0827 | 8/0/8 | -0.0854 |
| absolute asset return | 20d | +0.0252 | +0.0440 | -0.0358 | +0.0671 | -0.0495 | +0.1120 | 9/0/7 | +0.1781 |
| SPY-relative AR | 1d | -0.0056 | -0.0012 | -0.0117 | +0.0051 | -0.0482 | +0.0212 | 8/0/8 | -0.1060 |
| SPY-relative AR | 5d | -0.0096 | -0.0009 | -0.0456 | +0.0258 | -0.1036 | +0.0381 | 8/0/8 | -0.2899 |
| SPY-relative AR | 20d | +0.0008 | +0.0022 | -0.0492 | +0.0420 | -0.0938 | +0.1024 | 8/0/8 | -0.1074 |
| sector-relative AR | 1d | -0.0007 | +0.0002 | -0.0028 | +0.0024 | -0.0147 | +0.0065 | 9/0/7 | -0.0618 |
| sector-relative AR | 5d | -0.0010 | -0.0020 | -0.0112 | +0.0065 | -0.0278 | +0.0284 | 8/0/8 | -0.0486 |
| sector-relative AR | 20d | +0.0040 | +0.0061 | -0.0121 | +0.0216 | -0.0446 | +0.0461 | 10/0/6 | +0.1545 |
| SAR | 1d | -0.4138 | -0.0611 | -0.6890 | +0.3480 | -3.0478 | +1.4612 | 8/0/8 | -0.1177 |
| SAR | 5d | -0.3494 | -0.0139 | -1.4270 | +0.7466 | -2.9295 | +1.1421 | 8/0/8 | -0.3194 |
| SAR | 20d | -0.0021 | +0.0270 | -0.7064 | +0.6773 | -1.6354 | +1.5290 | 8/0/8 | -0.0780 |

### designed_contrast / `curve_2s10s` (categorical) - XOP vs SPY, sector XLE

**cell `inverted`** - N = 9, unique dates = 9, support = `insufficient_n`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0065 | -0.0140 | -0.0156 | +0.0080 | -0.0466 | +0.0493 | 3/0/6 |
| absolute asset return | 5d | -0.0035 | +0.0058 | -0.0299 | +0.0197 | -0.0528 | +0.0424 | 5/0/4 |
| absolute asset return | 20d | +0.0298 | +0.0484 | -0.0107 | +0.0730 | -0.0598 | +0.1022 | 5/0/4 |
| SPY-relative AR | 1d | -0.0038 | -0.0091 | -0.0121 | +0.0021 | -0.0459 | +0.0455 | 4/0/5 |
| SPY-relative AR | 5d | -0.0084 | +0.0016 | -0.0471 | +0.0231 | -0.0568 | +0.0419 | 5/0/4 |
| SPY-relative AR | 20d | +0.0206 | +0.0075 | -0.0257 | +0.0543 | -0.0725 | +0.1487 | 6/0/3 |
| sector-relative AR | 1d | -0.0027 | -0.0031 | -0.0055 | +0.0005 | -0.0095 | +0.0040 | 3/0/6 |
| sector-relative AR | 5d | -0.0030 | -0.0069 | -0.0071 | +0.0033 | -0.0146 | +0.0098 | 3/0/6 |
| sector-relative AR | 20d | -0.0078 | -0.0011 | -0.0218 | +0.0043 | -0.0464 | +0.0212 | 4/0/5 |
| SAR | 1d | -0.2890 | -0.3623 | -0.6866 | +0.1304 | -2.9888 | +2.4696 | 4/0/5 |
| SAR | 5d | -0.3929 | +0.0249 | -1.5934 | +0.5877 | -2.4405 | +1.0164 | 5/0/4 |
| SAR | 20d | +0.1162 | +0.0952 | -0.3118 | +0.6203 | -1.6354 | +1.3085 | 6/0/3 |

**cell `non_inverted`** - N = 23, unique dates = 23, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | +0.0006 | +0.0032 | -0.0200 | +0.0108 | -0.1067 | +0.1271 | 12/0/11 |
| absolute asset return | 5d | +0.0048 | +0.0199 | -0.0150 | +0.0305 | -0.1262 | +0.1324 | 14/0/9 |
| absolute asset return | 20d | +0.0116 | -0.0068 | -0.0470 | +0.0643 | -0.2384 | +0.2913 | 11/0/12 |
| SPY-relative AR | 1d | +0.0035 | +0.0036 | -0.0124 | +0.0156 | -0.0626 | +0.1150 | 12/0/11 |
| SPY-relative AR | 5d | +0.0049 | +0.0142 | -0.0261 | +0.0340 | -0.1098 | +0.1323 | 13/0/10 |
| SPY-relative AR | 20d | -0.0042 | -0.0054 | -0.0591 | +0.0498 | -0.1755 | +0.2401 | 10/0/13 |
| sector-relative AR | 1d | +0.0031 | +0.0000 | -0.0056 | +0.0059 | -0.0244 | +0.0821 | 12/0/11 |
| sector-relative AR | 5d | +0.0037 | +0.0050 | -0.0049 | +0.0178 | -0.0468 | +0.0528 | 17/0/6 |
| sector-relative AR | 20d | +0.0088 | +0.0080 | -0.0324 | +0.0347 | -0.0692 | +0.1477 | 13/0/10 |
| SAR | 1d | -0.0934 | +0.2462 | -0.7955 | +0.6291 | -3.0478 | +2.9674 | 12/0/11 |
| SAR | 5d | +0.0403 | +0.3529 | -0.4463 | +0.9104 | -2.9295 | +1.7582 | 13/0/10 |
| SAR | 20d | -0.0900 | -0.0784 | -0.7464 | +0.5210 | -1.5246 | +1.5290 | 10/0/13 |


### designed_contrast / `curve_2s10s` (continuous) - XOP vs SPY, sector XLE

N = 32, unique dates = 32.
State distribution: min -0.7200, p25 -0.0925, median +0.3100, p75 +0.5500, max +1.5700.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0014 | -0.0040 | -0.0187 | +0.0102 | -0.1067 | +0.1271 | 15/0/17 | +0.1115 |
| absolute asset return | 5d | +0.0025 | +0.0130 | -0.0210 | +0.0283 | -0.1262 | +0.1324 | 19/0/13 | +0.0770 |
| absolute asset return | 20d | +0.0167 | +0.0170 | -0.0433 | +0.0671 | -0.2384 | +0.2913 | 16/0/16 | -0.1419 |
| SPY-relative AR | 1d | +0.0015 | -0.0012 | -0.0122 | +0.0140 | -0.0626 | +0.1150 | 16/0/16 | +0.1258 |
| SPY-relative AR | 5d | +0.0012 | +0.0110 | -0.0334 | +0.0335 | -0.1098 | +0.1323 | 18/0/14 | +0.0491 |
| SPY-relative AR | 20d | +0.0028 | -0.0004 | -0.0519 | +0.0545 | -0.1755 | +0.2401 | 16/0/16 | -0.2200 |
| sector-relative AR | 1d | +0.0015 | -0.0013 | -0.0056 | +0.0040 | -0.0244 | +0.0821 | 15/0/17 | +0.2457 |
| sector-relative AR | 5d | +0.0018 | +0.0026 | -0.0071 | +0.0147 | -0.0468 | +0.0528 | 20/0/12 | +0.2138 |
| sector-relative AR | 20d | +0.0041 | +0.0014 | -0.0261 | +0.0231 | -0.0692 | +0.1477 | 17/0/15 | +0.0396 |
| SAR | 1d | -0.1484 | -0.0611 | -0.7846 | +0.5332 | -3.0478 | +2.9674 | 16/0/16 | +0.1188 |
| SAR | 5d | -0.0815 | +0.2948 | -0.5824 | +0.7466 | -2.9295 | +1.7582 | 18/0/14 | +0.1034 |
| SAR | 20d | -0.0320 | -0.0110 | -0.6313 | +0.5615 | -1.6354 | +1.5290 | 16/0/16 | -0.1973 |

### designed_contrast / `fed_policy_path` (categorical) - XOP vs SPY, sector XLE

**cell `easing`** - N = 12, unique dates = 12, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | +0.0037 | +0.0069 | -0.0085 | +0.0105 | -0.1067 | +0.1271 | 8/0/4 |
| absolute asset return | 5d | -0.0067 | +0.0203 | -0.0295 | +0.0264 | -0.1262 | +0.0827 | 7/0/5 |
| absolute asset return | 20d | +0.0390 | +0.0559 | -0.0403 | +0.0769 | -0.1783 | +0.2913 | 7/0/5 |
| SPY-relative AR | 1d | +0.0096 | +0.0069 | -0.0002 | +0.0140 | -0.0482 | +0.1150 | 9/0/3 |
| SPY-relative AR | 5d | -0.0023 | +0.0154 | -0.0179 | +0.0263 | -0.1036 | +0.0381 | 7/0/5 |
| SPY-relative AR | 20d | +0.0173 | +0.0073 | -0.0610 | +0.0764 | -0.1755 | +0.2401 | 7/0/5 |
| sector-relative AR | 1d | +0.0080 | +0.0019 | -0.0004 | +0.0068 | -0.0147 | +0.0821 | 9/0/3 |
| sector-relative AR | 5d | +0.0065 | +0.0114 | +0.0000 | +0.0183 | -0.0278 | +0.0284 | 9/0/3 |
| sector-relative AR | 20d | +0.0252 | +0.0230 | -0.0127 | +0.0403 | -0.0446 | +0.1477 | 8/0/4 |
| SAR | 1d | +0.1798 | +0.3817 | +0.0260 | +0.5332 | -3.0478 | +2.9674 | 9/0/3 |
| SAR | 5d | -0.0084 | +0.3514 | -0.3354 | +0.7585 | -2.9295 | +1.1421 | 7/0/5 |
| SAR | 20d | +0.1274 | +0.0927 | -0.9045 | +1.0067 | -1.3261 | +1.5290 | 7/0/5 |

**cell `hold`** - N = 11, unique dates = 11, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0034 | -0.0102 | -0.0222 | +0.0004 | -0.0483 | +0.0844 | 3/0/8 |
| absolute asset return | 5d | +0.0142 | +0.0038 | -0.0178 | +0.0258 | -0.0826 | +0.1324 | 6/0/5 |
| absolute asset return | 20d | +0.0214 | +0.0344 | -0.0387 | +0.0741 | -0.0626 | +0.1073 | 6/0/5 |
| SPY-relative AR | 1d | -0.0048 | -0.0098 | -0.0190 | -0.0012 | -0.0626 | +0.0758 | 3/0/8 |
| SPY-relative AR | 5d | +0.0015 | -0.0119 | -0.0389 | +0.0235 | -0.1098 | +0.1323 | 5/0/6 |
| SPY-relative AR | 20d | -0.0041 | -0.0024 | -0.0543 | +0.0412 | -0.1043 | +0.0808 | 5/0/6 |
| sector-relative AR | 1d | -0.0004 | -0.0026 | -0.0053 | +0.0029 | -0.0244 | +0.0299 | 4/0/7 |
| sector-relative AR | 5d | +0.0017 | +0.0008 | -0.0071 | +0.0040 | -0.0405 | +0.0528 | 6/0/5 |
| sector-relative AR | 20d | -0.0030 | +0.0018 | -0.0332 | +0.0136 | -0.0453 | +0.0564 | 6/0/5 |
| SAR | 1d | -0.5464 | -0.6268 | -0.9372 | -0.0611 | -2.9888 | +2.2526 | 3/0/8 |
| SAR | 5d | -0.2659 | -0.3419 | -1.2362 | +0.6198 | -2.4405 | +1.7582 | 5/0/6 |
| SAR | 20d | -0.0863 | -0.0347 | -0.5918 | +0.5210 | -1.6354 | +1.3085 | 5/0/6 |

**cell `tightening`** - N = 9, unique dates = 9, support = `insufficient_n`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0056 | -0.0140 | -0.0263 | +0.0119 | -0.0466 | +0.0493 | 4/0/5 |
| absolute asset return | 5d | +0.0004 | +0.0150 | -0.0181 | +0.0277 | -0.0777 | +0.0424 | 6/0/3 |
| absolute asset return | 20d | -0.0186 | -0.0068 | -0.0502 | +0.0484 | -0.2384 | +0.1022 | 3/0/6 |
| SPY-relative AR | 1d | -0.0017 | -0.0110 | -0.0127 | +0.0249 | -0.0459 | +0.0455 | 4/0/5 |
| SPY-relative AR | 5d | +0.0056 | +0.0231 | -0.0281 | +0.0364 | -0.0659 | +0.0743 | 6/0/3 |
| SPY-relative AR | 20d | -0.0080 | -0.0257 | -0.0301 | +0.0075 | -0.1558 | +0.1487 | 4/0/5 |
| sector-relative AR | 1d | -0.0048 | -0.0055 | -0.0073 | -0.0013 | -0.0167 | +0.0040 | 2/0/7 |
| sector-relative AR | 5d | -0.0043 | +0.0005 | -0.0072 | +0.0082 | -0.0468 | +0.0146 | 5/0/4 |
| sector-relative AR | 20d | -0.0153 | -0.0148 | -0.0269 | +0.0010 | -0.0692 | +0.0212 | 3/0/6 |
| SAR | 1d | -0.0995 | -0.3623 | -0.8173 | +0.9724 | -2.2747 | +2.4696 | 4/0/5 |
| SAR | 5d | +0.0463 | +0.5877 | -0.4148 | +0.6809 | -1.9586 | +1.4541 | 6/0/3 |
| SAR | 20d | -0.1782 | -0.3118 | -0.4474 | +0.0952 | -1.5246 | +1.1337 | 4/0/5 |


### designed_contrast / `fed_policy_path` (continuous) - XOP vs SPY, sector XLE

N = 32, unique dates = 32.
State distribution: min -1.7500, p25 -0.5000, median +0.0000, p75 +0.3125, max +2.7500.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0014 | -0.0040 | -0.0187 | +0.0102 | -0.1067 | +0.1271 | 15/0/17 | -0.1433 |
| absolute asset return | 5d | +0.0025 | +0.0130 | -0.0210 | +0.0283 | -0.1262 | +0.1324 | 19/0/13 | +0.0713 |
| absolute asset return | 20d | +0.0167 | +0.0170 | -0.0433 | +0.0671 | -0.2384 | +0.2913 | 16/0/16 | -0.2087 |
| SPY-relative AR | 1d | +0.0015 | -0.0012 | -0.0122 | +0.0140 | -0.0626 | +0.1150 | 16/0/16 | -0.1973 |
| SPY-relative AR | 5d | +0.0012 | +0.0110 | -0.0334 | +0.0335 | -0.1098 | +0.1323 | 18/0/14 | +0.0647 |
| SPY-relative AR | 20d | +0.0028 | -0.0004 | -0.0519 | +0.0545 | -0.1755 | +0.2401 | 16/0/16 | -0.0941 |
| sector-relative AR | 1d | +0.0015 | -0.0013 | -0.0056 | +0.0040 | -0.0244 | +0.0821 | 15/0/17 | -0.4564 |
| sector-relative AR | 5d | +0.0018 | +0.0026 | -0.0071 | +0.0147 | -0.0468 | +0.0528 | 20/0/12 | -0.2929 |
| sector-relative AR | 20d | +0.0041 | +0.0014 | -0.0261 | +0.0231 | -0.0692 | +0.1477 | 17/0/15 | -0.3824 |
| SAR | 1d | -0.1484 | -0.0611 | -0.7846 | +0.5332 | -3.0478 | +2.9674 | 16/0/16 | -0.1511 |
| SAR | 5d | -0.0815 | +0.2948 | -0.5824 | +0.7466 | -2.9295 | +1.7582 | 18/0/14 | +0.0253 |
| SAR | 20d | -0.0320 | -0.0110 | -0.6313 | +0.5615 | -1.6354 | +1.5290 | 16/0/16 | -0.1264 |

### designed_contrast / `spy_trend_ma200` (categorical) - XOP vs SPY, sector XLE

**cell `below_ma`** - N = 8, unique dates = 8, support = `insufficient_n`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0227 | -0.0160 | -0.0359 | +0.0102 | -0.1067 | +0.0145 | 3/0/5 |
| absolute asset return | 5d | -0.0121 | +0.0173 | -0.0330 | +0.0240 | -0.1262 | +0.0361 | 5/0/3 |
| absolute asset return | 20d | +0.0137 | +0.0053 | -0.0526 | +0.0658 | -0.2384 | +0.2913 | 4/0/4 |
| SPY-relative AR | 1d | -0.0099 | -0.0113 | -0.0372 | +0.0203 | -0.0482 | +0.0283 | 3/0/5 |
| SPY-relative AR | 5d | -0.0071 | -0.0040 | -0.0375 | +0.0368 | -0.1036 | +0.0743 | 4/0/4 |
| SPY-relative AR | 20d | +0.0216 | +0.0048 | -0.0460 | +0.0779 | -0.1558 | +0.2401 | 5/0/3 |
| sector-relative AR | 1d | -0.0047 | -0.0044 | -0.0108 | -0.0008 | -0.0167 | +0.0129 | 2/0/6 |
| sector-relative AR | 5d | -0.0011 | -0.0018 | -0.0088 | +0.0158 | -0.0468 | +0.0284 | 4/0/4 |
| sector-relative AR | 20d | +0.0099 | +0.0011 | -0.0279 | +0.0269 | -0.0692 | +0.1477 | 4/0/4 |
| SAR | 1d | -0.6657 | -0.4984 | -1.7432 | +0.5042 | -3.0478 | +1.2392 | 3/0/5 |
| SAR | 5d | -0.2917 | -0.0274 | -0.8007 | +0.7107 | -2.9295 | +1.4541 | 4/0/4 |
| SAR | 20d | -0.0730 | +0.0547 | -0.6670 | +0.6052 | -1.5246 | +1.1337 | 5/0/3 |

**cell `above_ma`** - N = 24, unique dates = 24, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | +0.0058 | +0.0004 | -0.0144 | +0.0093 | -0.0483 | +0.1271 | 12/0/12 |
| absolute asset return | 5d | +0.0073 | +0.0084 | -0.0197 | +0.0283 | -0.0893 | +0.1324 | 14/0/10 |
| absolute asset return | 20d | +0.0178 | +0.0170 | -0.0369 | +0.0671 | -0.1783 | +0.1580 | 12/0/12 |
| SPY-relative AR | 1d | +0.0052 | +0.0016 | -0.0120 | +0.0104 | -0.0626 | +0.1150 | 13/0/11 |
| SPY-relative AR | 5d | +0.0040 | +0.0141 | -0.0334 | +0.0260 | -0.1098 | +0.1323 | 14/0/10 |
| SPY-relative AR | 20d | -0.0035 | -0.0039 | -0.0519 | +0.0473 | -0.1755 | +0.1280 | 11/0/13 |
| sector-relative AR | 1d | +0.0036 | +0.0002 | -0.0051 | +0.0044 | -0.0244 | +0.0821 | 13/0/11 |
| sector-relative AR | 5d | +0.0027 | +0.0033 | -0.0070 | +0.0111 | -0.0405 | +0.0528 | 16/0/8 |
| sector-relative AR | 20d | +0.0022 | +0.0014 | -0.0261 | +0.0231 | -0.0453 | +0.1008 | 13/0/11 |
| SAR | 1d | +0.0240 | +0.1106 | -0.7084 | +0.5332 | -2.9888 | +2.9674 | 13/0/11 |
| SAR | 5d | -0.0115 | +0.3422 | -0.5824 | +0.7466 | -2.4405 | +1.7582 | 14/0/10 |
| SAR | 20d | -0.0184 | -0.0566 | -0.6313 | +0.5615 | -1.6354 | +1.5290 | 11/0/13 |


### designed_contrast / `spy_trend_ma200` (continuous) - XOP vs SPY, sector XLE

N = 32, unique dates = 32.
State distribution: min -0.0986, p25 +0.0134, median +0.0652, p75 +0.1098, max +0.1642.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0014 | -0.0040 | -0.0187 | +0.0102 | -0.1067 | +0.1271 | 15/0/17 | +0.0367 |
| absolute asset return | 5d | +0.0025 | +0.0130 | -0.0210 | +0.0283 | -0.1262 | +0.1324 | 19/0/13 | +0.0663 |
| absolute asset return | 20d | +0.0167 | +0.0170 | -0.0433 | +0.0671 | -0.2384 | +0.2913 | 16/0/16 | +0.0759 |
| SPY-relative AR | 1d | +0.0015 | -0.0012 | -0.0122 | +0.0140 | -0.0626 | +0.1150 | 16/0/16 | +0.0191 |
| SPY-relative AR | 5d | +0.0012 | +0.0110 | -0.0334 | +0.0335 | -0.1098 | +0.1323 | 18/0/14 | +0.0282 |
| SPY-relative AR | 20d | +0.0028 | -0.0004 | -0.0519 | +0.0545 | -0.1755 | +0.2401 | 16/0/16 | -0.0436 |
| sector-relative AR | 1d | +0.0015 | -0.0013 | -0.0056 | +0.0040 | -0.0244 | +0.0821 | 15/0/17 | +0.1741 |
| sector-relative AR | 5d | +0.0018 | +0.0026 | -0.0071 | +0.0147 | -0.0468 | +0.0528 | 20/0/12 | +0.0968 |
| sector-relative AR | 20d | +0.0041 | +0.0014 | -0.0261 | +0.0231 | -0.0692 | +0.1477 | 17/0/15 | +0.1371 |
| SAR | 1d | -0.1484 | -0.0611 | -0.7846 | +0.5332 | -3.0478 | +2.9674 | 16/0/16 | -0.0392 |
| SAR | 5d | -0.0815 | +0.2948 | -0.5824 | +0.7466 | -2.9295 | +1.7582 | 18/0/14 | +0.0674 |
| SAR | 20d | -0.0320 | -0.0110 | -0.6313 | +0.5615 | -1.6354 | +1.5290 | 16/0/16 | -0.0088 |

### designed_contrast / `vix_level_percentile` (continuous) - XOP vs SPY, sector XLE

N = 32, unique dates = 32.
State distribution: min +0.0040, p25 +0.2282, median +0.5456, p75 +0.7659, max +0.9722.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0014 | -0.0040 | -0.0187 | +0.0102 | -0.1067 | +0.1271 | 15/0/17 | +0.0477 |
| absolute asset return | 5d | +0.0025 | +0.0130 | -0.0210 | +0.0283 | -0.1262 | +0.1324 | 19/0/13 | -0.0654 |
| absolute asset return | 20d | +0.0167 | +0.0170 | -0.0433 | +0.0671 | -0.2384 | +0.2913 | 16/0/16 | +0.1980 |
| SPY-relative AR | 1d | +0.0015 | -0.0012 | -0.0122 | +0.0140 | -0.0626 | +0.1150 | 16/0/16 | +0.1379 |
| SPY-relative AR | 5d | +0.0012 | +0.0110 | -0.0334 | +0.0335 | -0.1098 | +0.1323 | 18/0/14 | +0.0379 |
| SPY-relative AR | 20d | +0.0028 | -0.0004 | -0.0519 | +0.0545 | -0.1755 | +0.2401 | 16/0/16 | +0.2376 |
| sector-relative AR | 1d | +0.0015 | -0.0013 | -0.0056 | +0.0040 | -0.0244 | +0.0821 | 15/0/17 | +0.1045 |
| sector-relative AR | 5d | +0.0018 | +0.0026 | -0.0071 | +0.0147 | -0.0468 | +0.0528 | 20/0/12 | +0.0554 |
| sector-relative AR | 20d | +0.0041 | +0.0014 | -0.0261 | +0.0231 | -0.0692 | +0.1477 | 17/0/15 | +0.1802 |
| SAR | 1d | -0.1484 | -0.0611 | -0.7846 | +0.5332 | -3.0478 | +2.9674 | 16/0/16 | +0.1520 |
| SAR | 5d | -0.0815 | +0.2948 | -0.5824 | +0.7466 | -2.9295 | +1.7582 | 18/0/14 | +0.0400 |
| SAR | 20d | -0.0320 | -0.0110 | -0.6313 | +0.5615 | -1.6354 | +1.5290 | 16/0/16 | +0.2508 |

### frame_complete_historical / `credit_hy_oas` (continuous) - KRE vs SPY, sector XLF

N = 20, unique dates = 20, era-bounded secondary subset (descriptive only).
State distribution: min +2.6600, p25 +2.8500, median +3.1300, p75 +3.4575, max +4.5000.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | +0.0047 | +0.0053 | -0.0126 | +0.0183 | -0.0448 | +0.0567 | 12/0/8 | +0.0369 |
| absolute asset return | 5d | +0.0038 | +0.0121 | -0.0198 | +0.0246 | -0.1054 | +0.0663 | 12/0/8 | -0.1640 |
| absolute asset return | 20d | +0.0133 | +0.0057 | -0.0316 | +0.0588 | -0.1106 | +0.1328 | 10/0/10 | -0.1053 |
| SPY-relative AR | 1d | +0.0031 | +0.0043 | -0.0083 | +0.0115 | -0.0443 | +0.0451 | 13/0/7 | +0.0647 |
| SPY-relative AR | 5d | -0.0016 | +0.0067 | -0.0102 | +0.0197 | -0.0889 | +0.0323 | 12/0/8 | -0.1535 |
| SPY-relative AR | 20d | -0.0015 | -0.0052 | -0.0380 | +0.0393 | -0.0836 | +0.0734 | 9/0/11 | -0.2746 |
| sector-relative AR | 1d | +0.0016 | -0.0001 | -0.0092 | +0.0144 | -0.0327 | +0.0384 | 10/0/10 | +0.2212 |
| sector-relative AR | 5d | -0.0027 | +0.0015 | -0.0103 | +0.0150 | -0.0666 | +0.0362 | 11/0/9 | +0.1272 |
| sector-relative AR | 20d | -0.0042 | -0.0093 | -0.0282 | +0.0217 | -0.0722 | +0.0772 | 6/0/14 | -0.1392 |
| SAR | 1d | +0.2552 | +0.2525 | -0.4274 | +0.8069 | -2.5069 | +2.7893 | 13/0/7 | +0.0971 |
| SAR | 5d | -0.0215 | +0.2339 | -0.3756 | +0.5786 | -2.2501 | +1.1481 | 12/0/8 | -0.1016 |
| SAR | 20d | +0.0254 | -0.0630 | -0.6396 | +0.5165 | -1.0581 | +1.3142 | 9/0/11 | -0.2641 |

### frame_complete_historical / `curve_2s10s` (categorical) - KRE vs SPY, sector XLF

**cell `inverted`** - N = 17, unique dates = 17, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0042 | -0.0145 | -0.0228 | +0.0164 | -0.0545 | +0.0567 | 7/0/10 |
| absolute asset return | 5d | -0.0091 | -0.0004 | -0.0288 | +0.0168 | -0.1054 | +0.0550 | 8/0/9 |
| absolute asset return | 20d | +0.0052 | -0.0012 | -0.0205 | +0.0296 | -0.1048 | +0.1328 | 8/0/9 |
| SPY-relative AR | 1d | -0.0045 | +0.0020 | -0.0178 | +0.0070 | -0.0474 | +0.0451 | 9/0/8 |
| SPY-relative AR | 5d | -0.0113 | -0.0033 | -0.0233 | +0.0125 | -0.0889 | +0.0281 | 8/0/9 |
| SPY-relative AR | 20d | -0.0147 | -0.0155 | -0.0457 | +0.0081 | -0.0836 | +0.0690 | 5/0/12 |
| sector-relative AR | 1d | -0.0018 | +0.0013 | -0.0151 | +0.0066 | -0.0417 | +0.0384 | 9/0/8 |
| sector-relative AR | 5d | -0.0087 | -0.0028 | -0.0242 | +0.0108 | -0.0666 | +0.0212 | 7/0/10 |
| sector-relative AR | 20d | -0.0151 | -0.0181 | -0.0446 | -0.0047 | -0.0722 | +0.0642 | 4/0/13 |
| SAR | 1d | -0.1987 | +0.1315 | -1.3996 | +0.6455 | -2.5069 | +2.7893 | 9/0/8 |
| SAR | 5d | -0.2438 | -0.0678 | -0.9687 | +0.3189 | -2.2501 | +1.3163 | 8/0/9 |
| SAR | 20d | -0.1716 | -0.2148 | -0.5381 | +0.0747 | -1.5575 | +1.1451 | 5/0/12 |

**cell `non_inverted`** - N = 48, unique dates = 48, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0078 | -0.0049 | -0.0154 | +0.0095 | -0.1366 | +0.0380 | 22/0/26 |
| absolute asset return | 5d | -0.0114 | -0.0019 | -0.0292 | +0.0181 | -0.1812 | +0.0918 | 23/0/25 |
| absolute asset return | 20d | +0.0010 | +0.0043 | -0.0444 | +0.0505 | -0.3076 | +0.2030 | 25/0/23 |
| SPY-relative AR | 1d | -0.0040 | -0.0034 | -0.0148 | +0.0095 | -0.0500 | +0.0259 | 23/0/25 |
| SPY-relative AR | 5d | -0.0060 | -0.0006 | -0.0214 | +0.0193 | -0.1262 | +0.0996 | 24/0/24 |
| SPY-relative AR | 20d | -0.0057 | -0.0118 | -0.0413 | +0.0225 | -0.1711 | +0.1805 | 19/0/29 |
| sector-relative AR | 1d | -0.0026 | -0.0028 | -0.0107 | +0.0039 | -0.0233 | +0.0258 | 19/0/29 |
| sector-relative AR | 5d | -0.0032 | -0.0016 | -0.0095 | +0.0038 | -0.0634 | +0.0643 | 23/0/25 |
| sector-relative AR | 20d | -0.0044 | -0.0086 | -0.0257 | +0.0189 | -0.0882 | +0.0772 | 16/0/32 |
| SAR | 1d | -0.2621 | -0.3240 | -1.1191 | +0.7010 | -3.5204 | +3.1105 | 23/0/25 |
| SAR | 5d | -0.2007 | -0.0257 | -0.8868 | +0.5481 | -7.1874 | +3.4275 | 24/0/24 |
| SAR | 20d | -0.2071 | -0.2027 | -0.8511 | +0.3766 | -4.8732 | +2.1973 | 19/0/29 |


### frame_complete_historical / `curve_2s10s` (continuous) - KRE vs SPY, sector XLF

N = 65, unique dates = 65.
State distribution: min -0.9500, p25 -0.1500, median +0.2500, p75 +0.5300, max +1.4800.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0069 | -0.0056 | -0.0179 | +0.0112 | -0.1366 | +0.0567 | 29/0/36 | +0.0572 |
| absolute asset return | 5d | -0.0108 | -0.0018 | -0.0288 | +0.0179 | -0.1812 | +0.0918 | 31/0/34 | +0.0349 |
| absolute asset return | 20d | +0.0021 | +0.0007 | -0.0404 | +0.0435 | -0.3076 | +0.2030 | 33/0/32 | +0.0522 |
| SPY-relative AR | 1d | -0.0041 | -0.0029 | -0.0161 | +0.0093 | -0.0500 | +0.0451 | 32/0/33 | +0.0439 |
| SPY-relative AR | 5d | -0.0074 | -0.0020 | -0.0233 | +0.0172 | -0.1262 | +0.0996 | 32/0/33 | +0.0871 |
| SPY-relative AR | 20d | -0.0080 | -0.0152 | -0.0443 | +0.0183 | -0.1711 | +0.1805 | 24/0/41 | +0.0792 |
| sector-relative AR | 1d | -0.0024 | -0.0025 | -0.0107 | +0.0049 | -0.0417 | +0.0384 | 28/0/37 | -0.0566 |
| sector-relative AR | 5d | -0.0047 | -0.0017 | -0.0102 | +0.0094 | -0.0666 | +0.0643 | 30/0/35 | +0.0190 |
| sector-relative AR | 20d | -0.0072 | -0.0107 | -0.0277 | +0.0184 | -0.0882 | +0.0772 | 20/0/45 | +0.1366 |
| SAR | 1d | -0.2455 | -0.2892 | -1.2953 | +0.6713 | -3.5204 | +3.1105 | 32/0/33 | +0.0547 |
| SAR | 5d | -0.2120 | -0.0678 | -0.8950 | +0.5472 | -7.1874 | +3.4275 | 32/0/33 | +0.0519 |
| SAR | 20d | -0.1978 | -0.2148 | -0.6530 | +0.3150 | -4.8732 | +2.1973 | 24/0/41 | +0.0546 |

### frame_complete_historical / `fed_policy_path` (categorical) - KRE vs SPY, sector XLF

**cell `easing`** - N = 17, unique dates = 17, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0126 | +0.0008 | -0.0152 | +0.0100 | -0.1366 | +0.0313 | 9/0/8 |
| absolute asset return | 5d | -0.0131 | +0.0125 | -0.0111 | +0.0300 | -0.1812 | +0.0663 | 11/0/6 |
| absolute asset return | 20d | -0.0280 | -0.0013 | -0.0526 | +0.0299 | -0.3076 | +0.1270 | 8/0/9 |
| SPY-relative AR | 1d | -0.0051 | -0.0039 | -0.0143 | +0.0068 | -0.0354 | +0.0227 | 8/0/9 |
| SPY-relative AR | 5d | -0.0068 | +0.0139 | -0.0195 | +0.0207 | -0.1262 | +0.0323 | 10/0/7 |
| SPY-relative AR | 20d | -0.0302 | -0.0172 | -0.0481 | +0.0003 | -0.1711 | +0.0734 | 5/0/12 |
| sector-relative AR | 1d | -0.0037 | -0.0036 | -0.0113 | +0.0005 | -0.0152 | +0.0158 | 6/0/11 |
| sector-relative AR | 5d | -0.0024 | +0.0003 | -0.0058 | +0.0101 | -0.0634 | +0.0362 | 9/0/8 |
| sector-relative AR | 20d | -0.0180 | -0.0141 | -0.0340 | -0.0046 | -0.0882 | +0.0772 | 2/0/15 |
| SAR | 1d | -0.1651 | -0.3624 | -1.0101 | +0.7918 | -3.0780 | +3.1105 | 8/0/9 |
| SAR | 5d | -0.1626 | +0.3307 | -0.2483 | +0.8636 | -7.1874 | +1.3323 | 10/0/7 |
| SAR | 20d | -0.5228 | -0.3755 | -0.8438 | +0.0041 | -4.8732 | +1.3056 | 5/0/12 |

**cell `hold`** - N = 22, unique dates = 22, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0049 | -0.0049 | -0.0198 | +0.0140 | -0.0503 | +0.0380 | 10/0/12 |
| absolute asset return | 5d | -0.0120 | -0.0078 | -0.0437 | +0.0208 | -0.1054 | +0.0918 | 8/0/14 |
| absolute asset return | 20d | +0.0281 | +0.0067 | -0.0348 | +0.1005 | -0.1121 | +0.2030 | 11/0/11 |
| SPY-relative AR | 1d | -0.0067 | -0.0030 | -0.0221 | +0.0103 | -0.0500 | +0.0259 | 11/0/11 |
| SPY-relative AR | 5d | -0.0137 | -0.0132 | -0.0505 | +0.0118 | -0.0889 | +0.0996 | 8/0/14 |
| SPY-relative AR | 20d | +0.0097 | -0.0118 | -0.0454 | +0.0674 | -0.1166 | +0.1805 | 10/0/12 |
| sector-relative AR | 1d | -0.0056 | -0.0059 | -0.0150 | +0.0037 | -0.0327 | +0.0258 | 7/0/15 |
| sector-relative AR | 5d | -0.0124 | -0.0116 | -0.0316 | +0.0036 | -0.0666 | +0.0643 | 8/0/14 |
| sector-relative AR | 20d | -0.0006 | -0.0089 | -0.0406 | +0.0548 | -0.0722 | +0.0696 | 8/0/14 |
| SAR | 1d | -0.4739 | -0.1126 | -1.4960 | +0.6126 | -3.5204 | +1.9915 | 11/0/11 |
| SAR | 5d | -0.4521 | -0.4495 | -1.3012 | +0.2115 | -2.4003 | +3.4275 | 8/0/14 |
| SAR | 20d | +0.0358 | -0.1473 | -0.8136 | +1.1073 | -1.8599 | +2.1973 | 10/0/12 |

**cell `tightening`** - N = 26, unique dates = 26, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0048 | -0.0079 | -0.0180 | +0.0077 | -0.0545 | +0.0567 | 10/0/16 |
| absolute asset return | 5d | -0.0083 | -0.0016 | -0.0255 | +0.0109 | -0.0811 | +0.0550 | 12/0/14 |
| absolute asset return | 20d | -0.0002 | +0.0014 | -0.0354 | +0.0290 | -0.1530 | +0.1642 | 14/0/12 |
| SPY-relative AR | 1d | -0.0012 | -0.0004 | -0.0113 | +0.0067 | -0.0474 | +0.0451 | 13/0/13 |
| SPY-relative AR | 5d | -0.0024 | +0.0010 | -0.0149 | +0.0123 | -0.0562 | +0.0314 | 14/0/12 |
| SPY-relative AR | 20d | -0.0086 | -0.0127 | -0.0309 | +0.0138 | -0.0774 | +0.0975 | 9/0/17 |
| sector-relative AR | 1d | +0.0013 | +0.0010 | -0.0057 | +0.0058 | -0.0417 | +0.0384 | 15/0/11 |
| sector-relative AR | 5d | +0.0004 | +0.0003 | -0.0047 | +0.0100 | -0.0485 | +0.0256 | 13/0/13 |
| sector-relative AR | 20d | -0.0058 | -0.0077 | -0.0200 | +0.0162 | -0.0672 | +0.0561 | 10/0/16 |
| SAR | 1d | -0.1048 | -0.0789 | -1.3558 | +0.6014 | -2.3398 | +2.7893 | 13/0/13 |
| SAR | 5d | -0.0411 | +0.0375 | -0.6977 | +0.4275 | -1.2648 | +1.3985 | 14/0/12 |
| SAR | 20d | -0.1831 | -0.2012 | -0.6121 | +0.2745 | -1.7160 | +1.7324 | 9/0/17 |


### frame_complete_historical / `fed_policy_path` (continuous) - KRE vs SPY, sector XLF

N = 65, unique dates = 65.
State distribution: min -1.7500, p25 -0.2500, median +0.0000, p75 +0.5000, max +3.0000.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0069 | -0.0056 | -0.0179 | +0.0112 | -0.1366 | +0.0567 | 29/0/36 | -0.0506 |
| absolute asset return | 5d | -0.0108 | -0.0018 | -0.0288 | +0.0179 | -0.1812 | +0.0918 | 31/0/34 | -0.0740 |
| absolute asset return | 20d | +0.0021 | +0.0007 | -0.0404 | +0.0435 | -0.3076 | +0.2030 | 33/0/32 | +0.0984 |
| SPY-relative AR | 1d | -0.0041 | -0.0029 | -0.0161 | +0.0093 | -0.0500 | +0.0451 | 32/0/33 | +0.0612 |
| SPY-relative AR | 5d | -0.0074 | -0.0020 | -0.0233 | +0.0172 | -0.1262 | +0.0996 | 32/0/33 | -0.0253 |
| SPY-relative AR | 20d | -0.0080 | -0.0152 | -0.0443 | +0.0183 | -0.1711 | +0.1805 | 24/0/41 | +0.1145 |
| sector-relative AR | 1d | -0.0024 | -0.0025 | -0.0107 | +0.0049 | -0.0417 | +0.0384 | 28/0/37 | +0.1647 |
| sector-relative AR | 5d | -0.0047 | -0.0017 | -0.0102 | +0.0094 | -0.0666 | +0.0643 | 30/0/35 | +0.0537 |
| sector-relative AR | 20d | -0.0072 | -0.0107 | -0.0277 | +0.0184 | -0.0882 | +0.0772 | 20/0/45 | +0.1269 |
| SAR | 1d | -0.2455 | -0.2892 | -1.2953 | +0.6713 | -3.5204 | +3.1105 | 32/0/33 | +0.0039 |
| SAR | 5d | -0.2120 | -0.0678 | -0.8950 | +0.5472 | -7.1874 | +3.4275 | 32/0/33 | -0.0339 |
| SAR | 20d | -0.1978 | -0.2148 | -0.6530 | +0.3150 | -4.8732 | +2.1973 | 24/0/41 | +0.0790 |

### frame_complete_historical / `spy_trend_ma200` (categorical) - KRE vs SPY, sector XLF

**cell `below_ma`** - N = 15, unique dates = 15, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0173 | -0.0112 | -0.0259 | -0.0033 | -0.1366 | +0.0567 | 4/0/11 |
| absolute asset return | 5d | -0.0216 | +0.0032 | -0.0393 | +0.0105 | -0.1812 | +0.0663 | 8/0/7 |
| absolute asset return | 20d | +0.0105 | +0.0021 | -0.0182 | +0.0365 | -0.1106 | +0.1642 | 8/0/7 |
| SPY-relative AR | 1d | -0.0043 | -0.0039 | -0.0181 | +0.0064 | -0.0310 | +0.0376 | 6/0/9 |
| SPY-relative AR | 5d | -0.0151 | -0.0133 | -0.0295 | +0.0111 | -0.1049 | +0.0281 | 7/0/8 |
| SPY-relative AR | 20d | -0.0120 | -0.0099 | -0.0442 | +0.0169 | -0.1166 | +0.0975 | 6/0/9 |
| sector-relative AR | 1d | -0.0019 | -0.0060 | -0.0102 | +0.0020 | -0.0233 | +0.0331 | 7/0/8 |
| sector-relative AR | 5d | -0.0059 | -0.0036 | -0.0088 | +0.0028 | -0.0484 | +0.0362 | 5/0/10 |
| sector-relative AR | 20d | -0.0091 | -0.0058 | -0.0330 | +0.0029 | -0.0704 | +0.0561 | 4/0/11 |
| SAR | 1d | -0.3028 | -0.3624 | -1.4724 | +0.5532 | -1.9560 | +2.7893 | 6/0/9 |
| SAR | 5d | -0.4038 | -0.5423 | -1.2084 | +0.4170 | -1.7578 | +1.3163 | 7/0/8 |
| SAR | 20d | -0.1797 | -0.1697 | -0.7484 | +0.3004 | -1.7345 | +1.7324 | 6/0/9 |

**cell `above_ma`** - N = 50, unique dates = 50, support = `sufficient_structure`

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg |
|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0038 | -0.0017 | -0.0156 | +0.0126 | -0.0931 | +0.0483 | 25/0/25 |
| absolute asset return | 5d | -0.0076 | -0.0024 | -0.0285 | +0.0198 | -0.1656 | +0.0918 | 23/0/27 |
| absolute asset return | 20d | -0.0004 | -0.0003 | -0.0418 | +0.0472 | -0.3076 | +0.2030 | 25/0/25 |
| SPY-relative AR | 1d | -0.0041 | +0.0016 | -0.0138 | +0.0098 | -0.0500 | +0.0451 | 26/0/24 |
| SPY-relative AR | 5d | -0.0051 | -0.0006 | -0.0204 | +0.0189 | -0.1262 | +0.0996 | 25/0/25 |
| SPY-relative AR | 20d | -0.0069 | -0.0154 | -0.0424 | +0.0194 | -0.1711 | +0.1805 | 18/0/32 |
| sector-relative AR | 1d | -0.0025 | -0.0022 | -0.0108 | +0.0051 | -0.0417 | +0.0384 | 21/0/29 |
| sector-relative AR | 5d | -0.0043 | -0.0001 | -0.0106 | +0.0099 | -0.0666 | +0.0643 | 25/0/25 |
| sector-relative AR | 20d | -0.0066 | -0.0136 | -0.0259 | +0.0186 | -0.0882 | +0.0772 | 16/0/34 |
| SAR | 1d | -0.2283 | +0.0926 | -1.1906 | +0.7088 | -3.5204 | +3.1105 | 26/0/24 |
| SAR | 5d | -0.1544 | -0.0193 | -0.7114 | +0.5344 | -7.1874 | +3.4275 | 25/0/25 |
| SAR | 20d | -0.2033 | -0.2252 | -0.6384 | +0.3224 | -4.8732 | +2.1973 | 18/0/32 |


### frame_complete_historical / `spy_trend_ma200` (continuous) - KRE vs SPY, sector XLF

N = 65, unique dates = 65.
State distribution: min -0.1546, p25 +0.0152, median +0.0618, p75 +0.0994, max +0.1641.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0069 | -0.0056 | -0.0179 | +0.0112 | -0.1366 | +0.0567 | 29/0/36 | +0.2465 |
| absolute asset return | 5d | -0.0108 | -0.0018 | -0.0288 | +0.0179 | -0.1812 | +0.0918 | 31/0/34 | +0.0519 |
| absolute asset return | 20d | +0.0021 | +0.0007 | -0.0404 | +0.0435 | -0.3076 | +0.2030 | 33/0/32 | +0.0616 |
| SPY-relative AR | 1d | -0.0041 | -0.0029 | -0.0161 | +0.0093 | -0.0500 | +0.0451 | 32/0/33 | +0.1549 |
| SPY-relative AR | 5d | -0.0074 | -0.0020 | -0.0233 | +0.0172 | -0.1262 | +0.0996 | 32/0/33 | +0.1373 |
| SPY-relative AR | 20d | -0.0080 | -0.0152 | -0.0443 | +0.0183 | -0.1711 | +0.1805 | 24/0/41 | +0.1487 |
| sector-relative AR | 1d | -0.0024 | -0.0025 | -0.0107 | +0.0049 | -0.0417 | +0.0384 | 28/0/37 | -0.0177 |
| sector-relative AR | 5d | -0.0047 | -0.0017 | -0.0102 | +0.0094 | -0.0666 | +0.0643 | 30/0/35 | -0.0418 |
| sector-relative AR | 20d | -0.0072 | -0.0107 | -0.0277 | +0.0184 | -0.0882 | +0.0772 | 20/0/45 | +0.0111 |
| SAR | 1d | -0.2455 | -0.2892 | -1.2953 | +0.6713 | -3.5204 | +3.1105 | 32/0/33 | +0.1631 |
| SAR | 5d | -0.2120 | -0.0678 | -0.8950 | +0.5472 | -7.1874 | +3.4275 | 32/0/33 | +0.1092 |
| SAR | 20d | -0.1978 | -0.2148 | -0.6530 | +0.3150 | -4.8732 | +2.1973 | 24/0/41 | +0.1502 |

### frame_complete_historical / `vix_level_percentile` (continuous) - KRE vs SPY, sector XLF

N = 65, unique dates = 65.
State distribution: min +0.0040, p25 +0.2817, median +0.5556, p75 +0.7778, max +0.9960.

| metric | h | mean | median | p25 | p75 | min | max | pos/zero/neg | Spearman rho |
|---|---|---|---|---|---|---|---|---|---|
| absolute asset return | 1d | -0.0069 | -0.0056 | -0.0179 | +0.0112 | -0.1366 | +0.0567 | 29/0/36 | -0.0670 |
| absolute asset return | 5d | -0.0108 | -0.0018 | -0.0288 | +0.0179 | -0.1812 | +0.0918 | 31/0/34 | -0.0302 |
| absolute asset return | 20d | +0.0021 | +0.0007 | -0.0404 | +0.0435 | -0.3076 | +0.2030 | 33/0/32 | -0.0675 |
| SPY-relative AR | 1d | -0.0041 | -0.0029 | -0.0161 | +0.0093 | -0.0500 | +0.0451 | 32/0/33 | -0.0170 |
| SPY-relative AR | 5d | -0.0074 | -0.0020 | -0.0233 | +0.0172 | -0.1262 | +0.0996 | 32/0/33 | -0.0236 |
| SPY-relative AR | 20d | -0.0080 | -0.0152 | -0.0443 | +0.0183 | -0.1711 | +0.1805 | 24/0/41 | -0.0230 |
| sector-relative AR | 1d | -0.0024 | -0.0025 | -0.0107 | +0.0049 | -0.0417 | +0.0384 | 28/0/37 | +0.0066 |
| sector-relative AR | 5d | -0.0047 | -0.0017 | -0.0102 | +0.0094 | -0.0666 | +0.0643 | 30/0/35 | +0.0323 |
| sector-relative AR | 20d | -0.0072 | -0.0107 | -0.0277 | +0.0184 | -0.0882 | +0.0772 | 20/0/45 | +0.1084 |
| SAR | 1d | -0.2455 | -0.2892 | -1.2953 | +0.6713 | -3.5204 | +3.1105 | 32/0/33 | -0.0097 |
| SAR | 5d | -0.2120 | -0.0678 | -0.8950 | +0.5472 | -7.1874 | +3.4275 | 32/0/33 | -0.0427 |
| SAR | 20d | -0.1978 | -0.2148 | -0.6530 | +0.3150 | -4.8732 | +2.1973 | 24/0/41 | -0.0463 |

## 4. Integrity reconciliation

- universe: frame 65 + designed 32 = 97; unique ids 97; unique dates 97
- credit era-bounded subsets: FOMC 20 / OPEC 16 (frozen G4 denominators, reconciled above)
- basis split: adjusted 97 / raw fallback 0 / cross 0 (expected 97/0/0; drift fails the run)
- manifest: derived entries reconciled field-by-field against the tracked G4 freeze table (16/16; any drift raises)
- accepted-86 contamination: none - the loader reads only `g_historical_evidence`; no accepted-stage row, curated case, representative case, or synthetic seed can enter
- mechanism-taxonomy conditioning: none - the promoted table carries no such column and no G3B/J1 label is read anywhere
- FOMC/OPEC pooling: none - every entry, cell, and statistic is single-lane by construction

## 5. Non-claims

Descriptive conditional association only. No causal regime effect, no forecast, no trading recommendation, no single-event significance, no p-value, no confidence interval, no FDR figure. The designed-contrast lane carries no prevalence claim. The structural support floor is not an inferential threshold, and `sufficient_structure` is not a significance statement. Spearman rho values are descriptive rank associations within one lane and one axis; they establish no mechanism and no cross-era equivalence. Not a trading, prediction, or recommendation surface.

## 6. Reproduction

```
python scripts/g6_frozen_manifest_readout.py --emit
python -m unittest tests.test_g6_frozen_manifest_readout
```

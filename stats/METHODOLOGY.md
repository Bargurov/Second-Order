# stats/ — Production Methodology (Phase 1)

Current contract for the event-study statistics pipeline.
Nothing in this document constitutes a claim about market direction,
mechanism causality, or replicable returns.

## Abnormal return

| Measure | Formula | Module |
|---|---|---|
| **BHAR** (production standard) | `(P_asset[t+h]/P_asset[t] - 1) - (P_bench[t+h]/P_bench[t] - 1)` | `event_study.py` |
| **CAR** (reported alongside) | `sum(daily_AR[t+1..t+h])` where daily AR = daily asset return - daily benchmark return | `event_study.py` |

BHAR is the buy-and-hold abnormal return an investor would observe.
CAR is the additive accumulation of daily abnormal returns over the
same window. At h=1 the two are identical; at h>1 they diverge by
compounding. Both are reported per horizon so the operator can
compare.

## SAR (standardized abnormal return)

`SAR_h = BHAR_h / (sigma_ar_daily * sqrt(h))`

`sigma_ar_daily` is the sample standard deviation (ddof=1) of the
daily AR series over a 60-bar pre-event estimation window. The
BHAR/sigma mismatch (compounded numerator, additive denominator) is
small at h <= 20 and is documented in `event_study.py`.

## P-values

Two-sided normal approximation from SAR. Per-event: `erfc`-based
(`p_values.py`). Cross-sectional cohort z-test:
`z = mean(SAR) / (sd(SAR) / sqrt(n))` (`validation_pipeline.py`).

## FDR

Benjamini-Hochberg step-up procedure over raw per-horizon p-values
(`fdr.py`). Discovery rule: `q <= alpha` (default alpha = 0.05).

## Bootstrap CI

IID percentile bootstrap (Efron's method) over **cross-sectional
event-level AR samples** — one scalar per event, resampled across
events. Default: 2000 resamples, 95% confidence, deterministic seed.

This is **not** a time-series or block bootstrap. The sampling unit
is independent events, not correlated daily returns.

## What is intentionally absent

| Item | Status | Condition for revisiting |
|---|---|---|
| Market-model OLS (alpha + beta regression) | Not production standard | Only if a future cohort requires beta-adjusted residuals |
| Block bootstrap | Deferred | Cohort grows to 20+ events with calendar clustering |
| CAAR (cross-sectional average CAR) | Deferred | After CAR is consumed by at least one archive runner |
| BCa / bias-corrected bootstrap | Deferred | n is too small for the correction to matter |
| Fama-French 3-factor | Not planned | Out of scope for Phase 1 |

## Record schema

`stat_validation.py` defines the canonical 10-field record:

```
horizon, abnormal_return, sar, car, ci_low, ci_high,
p_value, fdr_q, statistically_significant, interpretation
```

`abnormal_return` is BHAR. `car` is CAR. Significance derives from
`fdr_q <= alpha`, not from raw p or CI bounds. Interpretation labels:
`significant_positive`, `significant_negative`, `not_significant`,
`insufficient_data`.

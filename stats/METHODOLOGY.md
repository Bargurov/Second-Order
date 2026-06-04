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

## Cohort inference — currently blocked (not by the engine)

A compute-ready event-study row (per-horizon BHAR / SAR / CAR point
estimate) is **not** automatically a valid cohort observation. The
cross-sectional cohort tools above — the z-test in
`validation_pipeline.py`, the percentile bootstrap CI in
`bootstrap_ci.py`, and BH-FDR in `fdr.py` — all assume the sampling unit
is **independent events**. Computability says nothing about whether a
row is independent of the others.

As of the current local archive the matched compute-ready set — **70 rows:
the 62 legacy/organic compute-ready rows plus the 8 Phase-K
`curated_observation` rows** — does not meet that assumption, so cohort
inference is on hold. The block is **labeling and independence, not the
event-study engine**. (The counts below are a dated snapshot — run
`scripts/event_study_coverage_report.py` for live figures, which drift with
every coverage repair.)

- **`mechanism_family` is unpopulated for the legacy/organic compute-ready
  rows, and the 8 labeled Phase-K rows do not rescue a pooled read.** The 62
  legacy/organic compute-ready rows carry no economic grouping label, so for
  them the one economically grouped cohort axis does not exist. The 8 Phase-K
  `curated_observation` rows *are* labeled (tariff / sanction), but pooling
  across them is still blocked by a family/sign confound (every tariff event
  is expected-positive, every sanction event expected-negative) and per-family
  n < 8 — see `stats/PHASE_K_EVIDENCE.md` §7. Either way there is no defensible
  cohort to declare. The count-based buckets that reach `n >= 8` (a single
  ticker; one `stage` value; one `persistence` value) are not independent
  cohorts — they re-slice the same correlated rows under a different label.
- **The legacy/organic rows are date-clustered with overlapping forward
  windows.** Those 62 legacy/organic rows fall within about four weeks — 14
  distinct event dates from 2026-04-04 to 2026-05-02 — so their 20-day forward
  windows overlap heavily (an event dated one business day after another
  shares 19 of its 20 forward bars). Overlap makes the observations correlated
  regardless of how many distinct tickers are present. (The 8 Phase-K rows are
  separate historical anchors from 2018–2024 and do not share this window.)
- **Ticker coverage in that legacy cluster is broader than before but still
  concentrated.** It spans roughly 19 distinct primary tickers across several
  sectors — broader than the pre-repair energy / oil cluster — yet one ticker
  (XLE) is still about a third of the rows, so the nominal row count badly
  overstates the count of independent observations.

Why the existing tools would overstate on this set: the cohort z
statistic is `mean(SAR) / (sd(SAR) / sqrt(n))`. With correlated,
window-overlapping observations the effective independent count is far
below the nominal `n` — closer to the number of distinct,
non-overlapping shocks than to the row count — so `sqrt(n)` is too
large, the standard error too small, and the p-value too small. The IID
percentile bootstrap has the same defect: resampling correlated event
SARs as if exchangeable yields a CI that is too narrow. Both would
report a precision the sample does not carry. This is a sampling
condition, not a tooling gap — no script change makes the current set
valid for cohort inference.

### Minimum criteria before a cohort inference phase

A cohort phase may proceed only when all of the following hold, verified
read-only first:

- `mechanism_family` (or an equivalent economic label) populated for the
  candidate rows;
- at least 8 **independent** shocks — distinct underlying events, not 8
  rows;
- distinct event dates, or non-overlapping forward windows, so per-event
  observations do not share forward bars;
- a single, clear primary-ticker / benchmark mapping per event;
- an explicit denominator and a written exclusion list (which candidate
  rows were dropped and why), fixed before the tests run;
- a new, self-contained FDR scope for the cohort report's
  `(cohort, horizon)` hypotheses — never merged with, or compared
  against, the closed Phase 1 or Phase 2 evidence FDR pools.

Until then the honest surface is the single-event route
(`GET /events/{event_id}/event-study`): per-horizon point estimates with
CI, p-value, and FDR explicitly unavailable at `n = 1`. The Phase-K
`curated_observation` events are read this way in
`stats/PHASE_K_EVIDENCE.md` — descriptive, h1-only single-event evidence,
explicitly **not** a validation and **not** a pooled cohort.

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

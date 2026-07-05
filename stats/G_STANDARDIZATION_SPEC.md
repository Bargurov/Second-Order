# Mission G standardization spec (methodology of record, version g0-v1)

**Status:** documentation of the SHIPPED event-study standardization, verified
line-by-line against source at HEAD `7c1ba86`, plus the locked Mission G v1
normalization decisions. This document changes nothing: no code, no data, no
existing research output. It exists so that every G comparison uses - and is
audited against - the methodology that is actually implemented, not a
remembered approximation of it.

Source of truth inspected: `stats/event_study.py` (engine),
`event_study_validation.py` (gate; canonical basis policy at line 388,
`ESTIMATION_WINDOW = 60` and `HORIZONS = (1, 5, 20)` at lines 75-76),
`scripts/sector_relative_readout.py` (F1 lens), `stats/BASIS_RESTATEMENT.md`
and `stats/BASIS_INTEGRITY.md` (basis policy record).

## 1. The four shipped lenses (exact definitions)

1. **Absolute asset return** - the hold-period return of the primary asset,
   `raw_return = P_a[t+h] / P_a[t] - 1`, computed under the canonical
   adjusted-preferred basis policy (F3): matched adjusted/adjusted closes
   preferred (total-return basis); matched raw/raw only as an explicitly
   disclosed fallback (`basis_fallback = "matched_raw_fallback"` in the
   payload); no cross-basis pair in the default order. Live composition at
   lock time: 69 of the 70 canonical readouts on the adjusted basis, 1
   disclosed raw fallback.
2. **SPY-relative abnormal return** -
   `abnormal_return = raw_return - benchmark_return`, the difference of two
   hold-period returns (BHAR-style market-adjusted return), benchmark SPY,
   beta fixed at 1, no market-model intercept.
3. **Sector-relative abnormal return** - the identical arithmetic with the
   primary's own sector ETF as benchmark (F1 lens), computed only where the
   conservative ticker-to-sector map provides an eligible benchmark; every
   ineligible state is explicit.
4. **SAR (standardized abnormal return)** -
   `sar = abnormal_return / (sigma_ar_daily * sqrt(h))`.

Supporting quantities:

- **CAR** - `car` = the sum of the DAILY abnormal returns from
  `event_index + 1` through `event_index + h` (classical summed measure),
  published beside the BHAR-style `abnormal_return`. Per the engine's own
  documentation: at h = 1 the two are equal exactly; at larger horizons they
  diverge because BHAR compounds while CAR sums. CAR is a separate estimand
  (cumulative daily drift), not the same number as the BHAR.
- **sigma_ar_daily** - the sample standard deviation (`ddof = 1`) of the
  daily abnormal-return series (daily asset return minus daily benchmark
  return) over the pre-event estimation window
  `event_index - 60 .. event_index` (60 daily returns;
  `estimation_window_used` recorded per readout). If the window is too thin,
  no horizons are computed; if sigma is zero or non-finite, SAR is None and a
  warning is emitted - missingness gates, never fills.

## 2. Exact SAR / SCAR relationship

- The textbook SCAR standardizes the SUMMED cumulative abnormal return:
  `SCAR = CAR / (sigma_daily * sqrt(T))` under serial independence.
- The shipped SAR shares the SAME `sigma_daily * sqrt(h)` standardization
  discipline in the denominator but standardizes the BHAR-style hold-period
  numerator, not the summed CAR.
- Therefore: the existing SAR is NOT literally textbook CAR-based SCAR. The
  two are identical at the 1-day horizon and may diverge at 5d/20d; with
  20-day moves of 25 percent and more on the books, the BHAR-vs-CAR gap is
  not always negligible, and both numerators are published per readout so the
  divergence is visible row by row.
- A literal CAR-based SCAR is a one-line derived quantity from two
  already-published fields (`car`, `sigma_ar_daily`); it requires no new
  methodology and is NOT implemented in G0 (see section 4).

## 3. Known limitations of the shipped standardization

- beta fixed at 1 (market-adjusted, not market-model); no market-model intercept;
- no estimation-error correction (no Patell-style inflation of the
  standardization for prediction error);
- no event-induced-variance correction (event-window variance is assumed
  comparable to estimation-window variance);
- `sqrt(h)` scaling assumes sufficiently weak serial dependence of daily
  abnormal returns;
- a compounded (BHAR-style) numerator is paired with an additive-AR sigma -
  a convention mismatch the engine itself documents as small at horizons of
  20 days or less;
- SAR provides descriptive scale comparison relative to the asset's own
  local pre-event residual volatility; it does not establish cross-era
  equivalence and does not bridge structural market change.

## 4. Mission G v1 normalization decisions (locked)

- **No new normalization metric.** The volatility-relative lens for G is the
  shipped SAR, with the section 3 limitations disclosed wherever it appears.
- **VIX remains a state variable** (level and trailing percentile in the G0
  state menu), not a return denominator. **No VIX-scaled CAR**: a global
  SPX implied-volatility measure is the wrong deflator for ticker- and
  sector-specific readouts, double-deflates values already standardized by
  ticker-level residual sigma, and would introduce an arbitrary baseline
  constant.
- **No ATR-normalized event metric**: range-consumption framing imports a
  magic lookback and an unbenchmarked denominator without adding research
  value over SAR.
- **No new SCAR implementation in G0.** If a G6 exhibit ever chooses to show
  the classical-sum variant, it is derived from the published `car` and
  `sigma_ar_daily` fields as a display choice, decided before outcomes are
  inspected, and shown beside - never instead of - the shipped fields.
- **Any volatility-relative value is additive, never a replacement** for the
  actual magnitude.

## 5. Metric ceiling and display discipline

The complete lens set for Mission G surfaces (all four already shipped):

1. absolute asset return (hold-period, adjusted-preferred basis);
2. SPY-relative abnormal return (BHAR-style, beta = 1);
3. sector-relative abnormal return, where an eligible sector benchmark
   exists;
4. SAR.

No fifth magnitude lens. Cross-state magnitude discussion MUST show the
unadjusted value and the volatility-relative value together - a normalized
number never appears without its unadjusted neighbor, and no language may
equate a large unadjusted move in a high-volatility state with a stronger
mechanism.

## 6. Non-claims

- Descriptive standardization documentation only: no p-value, no CI, no FDR,
  no significance threshold, no new statistical model.
- Nothing here restates any published number or redefines any denominator.
- Not a trading, prediction, or recommendation surface; nothing here says
  anything about future returns of any asset.

# J1A data readiness - outcome-blind symmetric substrate (Mission J)

Contract: `j1a-data-readiness-v1`, executing the locked j0-v1 constitution over the 12 frozen J1 state-bearing cells. This report contains availability geometry ONLY: no event-window response value, no MEMP, no placement calibration, no node or edge state, and no proxy ranking appears here or in any J1A output. Event and ordinary-reference anchors were gated by the identical readiness functions (membership is metadata, not mathematics).

## Frozen manifest and headline funnel (12 cells, J0 order)

| # | measurement | lens | role | M | events ready / 65 | reference ready / era attempted | excluded (+-1) | coverage first..last |
|---|---|---|---|---|---|---|---|---|
| 1 | KRE | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | 64 / 65 | 1797 / 2011 | 192 | 2017-01-03 .. 2026-06-30 |
| 2 | IAT | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | 64 / 65 | 1797 / 2011 | 192 | 2017-01-03 .. 2026-06-30 |
| 3 | KBE | rolling_beta_ar | balance_sheet_sensitive_second_order | M3 | 64 / 65 | 1797 / 2011 | 192 | 2017-01-03 .. 2026-06-30 |
| 4 | XLF | rolling_beta_ar | broad_financial_sector | M3 | 64 / 65 | 1797 / 2011 | 192 | 2017-01-03 .. 2026-06-30 |
| 5 | VFH | rolling_beta_ar | broad_financial_sector | M3 | 64 / 65 | 1797 / 2011 | 192 | 2017-01-03 .. 2026-06-30 |
| 6 | IAT | raw_return | balance_sheet_sensitive_second_order | M3 | 65 / 65 | 1816 / 2011 | 195 | 2017-01-03 .. 2026-06-30 |
| 7 | KBE | raw_return | balance_sheet_sensitive_second_order | M3 | 65 / 65 | 1816 / 2011 | 195 | 2017-01-03 .. 2026-06-30 |
| 8 | XLF | raw_return | broad_financial_sector | M3 | 65 / 65 | 1816 / 2011 | 195 | 2017-01-03 .. 2026-06-30 |
| 9 | VFH | raw_return | broad_financial_sector | M3 | 65 / 65 | 1816 / 2011 | 195 | 2017-01-03 .. 2026-06-30 |
| 10 | 2Y_CMT | raw_change | policy_rates_repricing | M2 | 65 / 65 | 1804 / 1999 | 195 | 2016-06-01 .. 2026-06-30 |
| 11 | 2S10S_CMT | raw_change | curve_shape_contextual_layer | M2 | 65 / 65 | 1804 / 1999 | 195 | 2016-06-01 .. 2026-06-30 |
| 12 | SHY | raw_return | policy_rates_repricing | M3 | 65 / 65 | 1816 / 2011 | 195 | 2017-01-03 .. 2026-06-30 |

## Per-cell detail

### Cell 1 - KRE (rolling_beta_ar)

- role: balance_sheet_sensitive_second_order; M-class: M3; evidence class: A instrument; B statistic
- source: yahoo_chart (g3_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 64, unavailable 1
- event ready-by-year: 2018:7, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
  - unavailable event 2018-01-31: insufficient_history_252_20
- event failure counts: {"insufficient_history_252_20": 1}
- reference: era attempted 2011, ready 1797, excluded by event proximity (+-1) 192
- reference failure counts: {"insufficient_history_252_20": 22}
- reference ready-by-year: 2018:208, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226
- rolling-beta gates: anchors failing 252/20 history: events 1, reference 22; failing response-window alignment: events 0, reference 0; failing basis compatibility: 0 (cross-basis pairs are structurally impossible; raw-only sessions disclosed above)
- embargo: exactly 20 completed aligned sessions immediately before every anchor, estimation strictly precedes it (confirmed: True)

### Cell 2 - IAT (rolling_beta_ar)

- role: balance_sheet_sensitive_second_order; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 64, unavailable 1
- event ready-by-year: 2018:7, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
  - unavailable event 2018-01-31: insufficient_history_252_20
- event failure counts: {"insufficient_history_252_20": 1}
- reference: era attempted 2011, ready 1797, excluded by event proximity (+-1) 192
- reference failure counts: {"insufficient_history_252_20": 22}
- reference ready-by-year: 2018:208, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226
- rolling-beta gates: anchors failing 252/20 history: events 1, reference 22; failing response-window alignment: events 0, reference 0; failing basis compatibility: 0 (cross-basis pairs are structurally impossible; raw-only sessions disclosed above)
- embargo: exactly 20 completed aligned sessions immediately before every anchor, estimation strictly precedes it (confirmed: True)

### Cell 3 - KBE (rolling_beta_ar)

- role: balance_sheet_sensitive_second_order; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 64, unavailable 1
- event ready-by-year: 2018:7, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
  - unavailable event 2018-01-31: insufficient_history_252_20
- event failure counts: {"insufficient_history_252_20": 1}
- reference: era attempted 2011, ready 1797, excluded by event proximity (+-1) 192
- reference failure counts: {"insufficient_history_252_20": 22}
- reference ready-by-year: 2018:208, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226
- rolling-beta gates: anchors failing 252/20 history: events 1, reference 22; failing response-window alignment: events 0, reference 0; failing basis compatibility: 0 (cross-basis pairs are structurally impossible; raw-only sessions disclosed above)
- embargo: exactly 20 completed aligned sessions immediately before every anchor, estimation strictly precedes it (confirmed: True)

### Cell 4 - XLF (rolling_beta_ar)

- role: broad_financial_sector; M-class: M3; evidence class: A instrument; B statistic
- source: yahoo_chart (g3_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 64, unavailable 1
- event ready-by-year: 2018:7, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
  - unavailable event 2018-01-31: insufficient_history_252_20
- event failure counts: {"insufficient_history_252_20": 1}
- reference: era attempted 2011, ready 1797, excluded by event proximity (+-1) 192
- reference failure counts: {"insufficient_history_252_20": 22}
- reference ready-by-year: 2018:208, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226
- rolling-beta gates: anchors failing 252/20 history: events 1, reference 22; failing response-window alignment: events 0, reference 0; failing basis compatibility: 0 (cross-basis pairs are structurally impossible; raw-only sessions disclosed above)
- embargo: exactly 20 completed aligned sessions immediately before every anchor, estimation strictly precedes it (confirmed: True)

### Cell 5 - VFH (rolling_beta_ar)

- role: broad_financial_sector; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 64, unavailable 1
- event ready-by-year: 2018:7, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
  - unavailable event 2018-01-31: insufficient_history_252_20
- event failure counts: {"insufficient_history_252_20": 1}
- reference: era attempted 2011, ready 1797, excluded by event proximity (+-1) 192
- reference failure counts: {"insufficient_history_252_20": 22}
- reference ready-by-year: 2018:208, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226
- rolling-beta gates: anchors failing 252/20 history: events 1, reference 22; failing response-window alignment: events 0, reference 0; failing basis compatibility: 0 (cross-basis pairs are structurally impossible; raw-only sessions disclosed above)
- embargo: exactly 20 completed aligned sessions immediately before every anchor, estimation strictly precedes it (confirmed: True)

### Cell 6 - IAT (raw_return)

- role: balance_sheet_sensitive_second_order; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 2011, ready 1816, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:227, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226

### Cell 7 - KBE (raw_return)

- role: balance_sheet_sensitive_second_order; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 2011, ready 1816, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:227, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226

### Cell 8 - XLF (raw_return)

- role: broad_financial_sector; M-class: M3; evidence class: A instrument; B statistic
- source: yahoo_chart (g3_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 2011, ready 1816, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:227, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226

### Cell 9 - VFH (raw_return)

- role: broad_financial_sector; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 2011, ready 1816, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:227, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226

### Cell 10 - 2Y_CMT (raw_change)

- role: policy_rates_repricing; M-class: M2; evidence class: B statistic
- source: treasury_daily_yield_curve_csv (j1a_treasury.json); basis: official_level_percentage_points; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2520; coverage 2016-06-01 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 1999, ready 1804, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:225, 2019:226, 2020:224, 2021:227, 2022:225, 2023:226, 2024:226, 2025:225

### Cell 11 - 2S10S_CMT (raw_change)

- role: curve_shape_contextual_layer; M-class: M2; evidence class: B statistic (underlying series A as a state)
- source: treasury_daily_yield_curve_csv (j1a_treasury.json); basis: official_level_percentage_points; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2520; coverage 2016-06-01 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 1999, ready 1804, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:225, 2019:226, 2020:224, 2021:227, 2022:225, 2023:226, 2024:226, 2025:225

### Cell 12 - SHY (raw_return)

- role: policy_rates_repricing; M-class: M3; evidence class: B instrument; B statistic
- source: yahoo_chart (j1a_price_cache.db); basis: adjusted; raw-only (disclosed fallback) sessions: 0
- frame sessions: 2385; coverage 2017-01-03 .. 2026-06-30
- events: attempted 65, ready 65, unavailable 0
- event ready-by-year: 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8
- event failure counts: {}
- reference: era attempted 2011, ready 1816, excluded by event proximity (+-1) 195
- reference failure counts: {}
- reference ready-by-year: 2018:227, 2019:228, 2020:226, 2021:228, 2022:227, 2023:226, 2024:228, 2025:226

## Provenance (dates and counts only)

```json
{
 "contract": "j1a-data-readiness-v1",
 "fomc_events": 65,
 "g3_meta": {
  "end": "2026-06-30",
  "retrieved_at": "2026-07-05T11:23:21.291523+00:00",
  "source": "Yahoo public chart endpoint (raw close + adjusted close)",
  "start": "2017-01-01",
  "tickers": {
   "KRE": {
    "adjusted": 2385,
    "raw": 2385
   },
   "SPY": {
    "adjusted": 2385,
    "raw": 2385
   },
   "XLE": {
    "adjusted": 2385,
    "raw": 2385
   },
   "XLF": {
    "adjusted": 2385,
    "raw": 2385
   },
   "XOP": {
    "adjusted": 2385,
    "raw": 2385
   }
  }
 },
 "j1a_meta": {
  "contract": "j1a-data-readiness-v1",
  "end": "2026-06-30",
  "retrieved_at": "2026-07-06T19:37:20.498248+00:00",
  "source": "Yahoo public chart endpoint (raw close + adjusted close)",
  "start": "2017-01-01",
  "tickers": {
   "IAT": {
    "adjusted": 2385,
    "raw": 2385
   },
   "KBE": {
    "adjusted": 2385,
    "raw": 2385
   },
   "SHY": {
    "adjusted": 2385,
    "raw": 2385
   },
   "VFH": {
    "adjusted": 2385,
    "raw": 2385
   }
  }
 },
 "spread_drift": {
  "existing_observations": 2396,
  "mismatches": [],
  "overlap": 2396
 },
 "treasury_meta": {
  "contract": "j1a-data-readiness-v1",
  "duplicate_dates": {},
  "retrieved_at": "2026-07-06T19:37:40.054780+00:00",
  "source": "U.S. Treasury daily yield-curve CSVs",
  "spread_2s10s": {
   "first": "2016-06-01",
   "last": "2026-06-30",
   "observations": 2520,
   "series": "10 Yr minus 2 Yr CMT spread"
  },
  "two_yr": {
   "first": "2016-06-01",
   "last": "2026-06-30",
   "observations": 2520,
   "series": "2 Yr CMT level"
  }
 }
}
```

## Boundary

Not computed here (they belong to J1B under the frozen constitution): event responses, ordinary-reference responses, event percentiles, MEMPs, placement calibration, node states, edge states, and any proxy comparison. The section-11 feasibility rule (`insufficient subset under the frozen procedure`) is evaluated in J1B against these funnels; no numeric floor exists.

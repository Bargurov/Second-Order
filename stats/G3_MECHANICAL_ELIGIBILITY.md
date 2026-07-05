# G3 mechanical eligibility (Mission G, g0-v1)

Status: G3A mechanical-eligibility funnel. This slice turns the 97 identity-valid historical candidates (65 FOMC frame-complete + 32 OPEC designed-reservoir) into an OUTCOME-BLIND eligibility funnel under two frozen, family-level transmission lenses. It reuses the shipped event-study gate and canonical basis policy; it computes no persisted outcome, creates no state tag, promotes no candidate, and mutates neither `events.db` nor the root `price_cache.db`. Prices live only in a gitignored local cache (`g_state_cache/g3_price_cache.db`).

## 1. Mapping contract (frozen, family-level)

Mapping version: `g3-transmission-map-v1`. Mapping is a pure function of the candidate FAMILY. No candidate receives an asset because of remembered historical importance; no response value influences the mapping; there is no event-specific override rule. A future mapping change requires a version bump and a full re-run across the family.

| family | primary | market | sector | transmission interpretation |
|---|---|---|---|---|
| FOMC | `KRE` | `SPY` | `XLF` | policy decision -> policy path / funding and curve conditions -> regional-bank equities |
| OPEC production-policy | `XOP` | `SPY` | `XLE` | collective production policy -> crude supply expectations -> producer cash flows -> exploration-and-production equities |

Claim ceilings (predeclared, bounded):

- FOMC / `KRE`: KRE is one predeclared second-order equity transmission lens for FOMC decisions. It is not the complete market reaction to monetary policy and does not imply every FOMC decision should move regional banks in one direction.
- OPEC / `XOP`: XOP is one predeclared producer-equity transmission lens for collective OPEC/OPEC+ production policy. It is not a complete measure of oil-market consequences.

The canonical (market-relative) event study reuses `event_study_validation.build_event_study_validation` under its default basis policy: matched adjusted/adjusted preferred, matched raw/raw as the only disclosed fallback, never a cross-basis pair. The sector-relative layer reuses the SAME gate with the family sector ETF as the benchmark. No second event-study or basis implementation exists in this slice.

## 2. Funnel (all 97)

Monotone eligibility chain (each node a subset of the previous):

- identity-valid: 97
- mapped: 97
- primary-price available: 97
- canonical event-study available: 97
- sector-relative available: 97

### By lane

| lane | identity | mapped | primary | canonical | sector-rel |
|---|---|---|---|---|---|
| designed_contrast | 32 | 32 | 32 | 32 | 32 |
| frame_complete_historical | 65 | 65 | 65 | 65 | 65 |

### By family

| family | identity | mapped | primary | canonical | sector-rel |
|---|---|---|---|---|---|
| fomc | 65 | 65 | 65 | 65 | 65 |
| opec | 32 | 32 | 32 | 32 | 32 |

### By calendar year

| year | identity | mapped | primary | canonical | sector-rel |
|---|---|---|---|---|---|
| 2018 | 10 | 10 | 10 | 10 | 10 |
| 2019 | 10 | 10 | 10 | 10 | 10 |
| 2020 | 12 | 12 | 12 | 12 | 12 |
| 2021 | 11 | 11 | 11 | 11 | 11 |
| 2022 | 12 | 12 | 12 | 12 | 12 |
| 2023 | 11 | 11 | 11 | 11 | 11 |
| 2024 | 13 | 13 | 13 | 13 | 13 |
| 2025 | 18 | 18 | 18 | 18 | 18 |

## 3. Failure composition

A candidate may carry more than one mechanical failure; all applicable codes are captured. A missing sector-relative layer is NOT counted as a complete event-study failure - the two layers are evaluated independently. This is structural accounting, not a causal claim about attrition.

| failure code | candidates |
|---|---|
| mapping_missing | 0 |
| primary_price_missing | 0 |
| market_benchmark_missing | 0 |
| canonical_event_study_unavailable | 0 |
| sector_benchmark_missing | 0 |
| sector_relative_unavailable | 0 |

- candidates with more than one failure code: 0

Failure codes by lane:

- (none)

Failure codes by family:

- (none)

Failure codes by calendar year:

- (none)

## 4. Basis integrity (no response values)

- adjusted canonical (matched adjusted/adjusted): 97
- disclosed raw fallback (matched raw/raw): 0
- canonical event study unavailable: 0
- cross-basis canonical pairs: 0 (must be 0; the default policy never mixes bases)

## 5. Date structure

- unique candidate dates entering the grinder: 97
- unique dates surviving canonical event-study eligibility: 97

Entering dates by calendar year: 2018:10, 2019:10, 2020:12, 2021:11, 2022:12, 2023:11, 2024:13, 2025:18

Surviving dates by calendar year: 2018:10, 2019:10, 2020:12, 2021:11, 2022:12, 2023:11, 2024:13, 2025:18

This is structural evidence for the later G4 freeze, not a comparison result.

## 6. Non-claims and firewall

No market response of any kind appears in this report, in the persisted rows, or in any G3 artifact: no absolute return, no abnormal return, no SAR, no CAR, no sector-relative return, no sign, no direction, no effect magnitude, and no outcome label. The engine mechanically computes those values only as a side effect of the availability check and discards them; a tested field whitelist enforces the persisted rows. The six-code failure machinery is validated by isolated unit fixtures (one per code, plus a multi-code case), so an all-pass funnel here reflects real coverage, not a silently broken detector. This is not a trading, prediction, or recommendation surface.

## 7. Provenance and reproduction (zero-cost)

- price cache retrieval timestamp: 2026-07-05T11:23:21.291523+00:00
- price cache SHA256 (`g_state_cache/g3_price_cache.db`, gitignored): `a5bb09f87fa6566588baa6638119ce7b0b349d02143c72415b49d426b14c2754`
- prices: KRE, XLF, XOP, XLE, SPY daily raw close + adjusted close from the Yahoo public chart endpoint (zero-cost), fetched by series/range (five requests, not one per candidate).

```
python scripts/g3_mechanical_grinder.py --probe-sources
python scripts/g3_mechanical_grinder.py --fetch
python scripts/g3_mechanical_grinder.py --grind
python -m unittest tests.test_g3_mechanical_grinder
```

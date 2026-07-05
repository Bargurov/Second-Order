# G2 state-source readiness (Mission G, g0-v1)

Status: G2 acquisition/readiness report. This slice built the point-in-time
state-data substrate for the five frozen G0 dimensions and probed readiness
across the 97 identity-valid historical candidates (65 frame-complete FOMC +
32 reservoir-ready OPEC). It computed no outcome, created no state tag,
recruited no candidate, and mutated neither `events.db` nor the existing
`price_cache`. Raw series live only in the gitignored local cache
(`g_state_cache/`, with per-series source, URL, observation range, and
retrieval timestamp); no generated data artifact is committed.

## 1. Source contract (five frozen dimensions)

Availability classes: `same_day` = an observation dated at the cutoff was
public by the cutoff close; `next_day` = an observation dated at the cutoff
publishes after the cutoff close, so the latest eligible value is the prior
session's. The conservative cutoff is the last completed trading session
STRICTLY before the source-pinned event date (reference calendar: the VIX
session calendar).

| dimension | source | series | availability | revision/vintage | missing rule |
|---|---|---|---|---|---|
| fed_policy_path | repo-internal: G1A frame target ranges + official 2016-2017 anchor decisions | target-range midpoint; net change over a six-month calendar lookback | same_day (statements 2 p.m. ET) | never revised; no vintage issue | lookback before timeline start -> insufficient_history |
| vix_level_percentile | Cboe official VIX history CSV | daily close; level at cutoff + trailing 252-session percentile | same_day | not revised | under 252 eligible sessions -> insufficient_history |
| spy_trend_ma200 | Yahoo public chart endpoint, SPY daily RAW closes | close vs 200-session moving average, percent distance | same_day | not revised | under 200 eligible sessions -> insufficient_history |
| curve_2s10s | U.S. Treasury daily yield-curve CSVs | "10 Yr" minus "2 Yr" CMT spread, level | next_day (conservative) | effectively unrevised | no eligible observation -> source_missing |
| credit_hy_oas | ICE BofA US High Yield OAS via FRED | OAS level | next_day | effectively unrevised | BLOCKED (section 3); never proxied |

Point-in-time semantics distinguished throughout: observation date (the
series date), publication availability (observation date plus the class lag
above), and retrieval date (recorded in cache metadata). A value is eligible
only if publicly available by the candidate's cutoff.

Vintage note: none of the five v1 dimensions is a revised macro series, so
no ALFRED-style vintage data is required in v1; the publication-lag classes
carry the whole no-lookahead burden. Any future revised-series dimension
would require true vintages per the G0 contract (omit, never proxy).

Two explicit structural choices (stated, not silent):

- SPY moving-average distance uses RAW closes - the market price-index
  convention for trend-vs-average distance. The event-study
  adjusted-preferred policy governs readouts, not this state series.
- The existing `price_cache` was evaluated and REJECTED as the SPY source:
  it is event-window shaped (about 74 percent of sessions present over
  2015-2026), and trailing windows over a gapped series would silently
  shrink. The state layer acquires its own complete series instead.

## 2. Zero-cost source verification (real-data spot checks, all passing)

- Weekend + market-holiday cutoff: event 2020-04-12 (Sunday; the prior
  Friday was a market holiday) resolves to cutoff 2020-04-09. Plain-weekend
  case: event 2025-05-03 (Saturday) resolves to 2025-05-02.
- No backward leakage: the trailing 252-session VIX percentile at a real
  cutoff is bit-identical when computed on the full series and on a series
  truncated at the cutoff.
- Publication lag respected: at cutoff 2022-10-04 the latest eligible
  curve observation is dated 2022-10-03 (next_day class), where a same-day
  class would have used 2022-10-04 - the difference demonstrates the rule.
- Own-decision exclusion: a cutoff one session before an FOMC decision
  excludes that decision from its own six-month lookback (unit-tested and
  spot-checked on the real timeline).
- No paid source and no paid request was used anywhere; all four acquired
  series came from zero-cost official/public endpoints.

## 3. Blocked dimension (G2B source resolution)

`credit_hy_oas` remains BLOCKED. G2B ran a bounded source resolution (three
source paths, hard-capped) and refined the diagnosis from "FRED unreachable"
to ENVIRONMENT-BLOCKED with the failure layer identified:

1. Intended path - FRED CSV channel
   (`fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`): DNS, TCP
   connect, and TLS handshake to the CDN edge all succeed; the HTTP request
   is then silently dropped (read timeout, zero response bytes). The drop is
   host-level and header-independent (browser-identical headers behave the
   same), affects the plain series page too, and reproduced across checks
   hours apart; a control host fetched over the same network answered
   normally. A cloud-egress cross-check of the same URL received an explicit
   HTTP 403. This is edge-level request filtering for this environment's
   egress - not a source outage and not a DNS, TCP, or TLS failure. The
   attempted URL and evidence stay recorded in
   `g_state_cache/hy_oas.blocked.json`.
2. Official FRED API (`api.stlouisfed.org/fred/series/observations`, same
   series id): REACHABLE from this environment - it answers HTTP 400
   "api_key is not set" in under a second. This is the same official FRED
   distribution of the same ICE BofA series, zero-cost behind a free
   registered API key, and its realtime (vintage) parameters would let the
   acquisition verify publication semantics directly. No key exists in this
   environment and registration is an operator action; the path is
   credential-gated, not network-blocked.
3. Issuer platform (ICE, `indices.ice.com`): reachable, but a
   registration-gated interactive platform with no documented zero-cost
   scriptable endpoint for full 2018-2025 OAS history; it does not meet the
   auditable point-in-time acquisition bar. (The legacy
   `indices.theice.com` hostname no longer resolves.)

Diagnosis: ENVIRONMENT-BLOCKED. The intended series identity and its frozen
`next_day` availability class remain methodologically valid; the block is a
property of this environment's network egress plus a missing free
credential, not of the source. Concrete resolution path: a free FRED API
key supplied by the operator (environment variable, never committed), after
which acquisition, publication-semantics verification, and the
97-candidate readiness probe can run in a future gated slice. Per the G0
contract no proxy was introduced and no substitute series was fetched; the
decision to drop the dimension, if it stays unusable, belongs to G4.

## 4. 97-candidate readiness matrix (outcome-blind)

| measure | count |
|---|---|
| candidates | 97 (65 frame_complete_historical + 32 designed_contrast) |
| cutoff resolved | 97 / 97 |
| complete state vector (5/5) | 0 |
| partial state vector (4/5) | 97 |
| missing: fed_policy_path | 0 |
| missing: vix_level_percentile | 0 |
| missing: spy_trend_ma200 | 0 |
| missing: curve_2s10s | 0 |
| missing: credit_hy_oas | 97 (blocked source) |

Missingness by lane and calendar year: the only missing dimension is
credit_hy_oas, and it is missing uniformly (every candidate, both lanes,
every year 2018-2025) because the block is a source-level property, not a
candidate-level one. No differential-attrition signature exists in the
acquired dimensions: the other four are available for all 97 candidates in
both lanes and all years.

Acquired history (gitignored local cache, 2016-06 through 2025-12): VIX
2438 observations; SPY 2411; 2s10s 2396 - sufficient for every candidate
cutoff, the six-month policy lookback, the 252-session percentile, and the
200-session moving average, with margin. No unrelated backfill was
performed.

## 5. No-lookahead limitations (disclosed)

- The cutoff is a session-close boundary: an event early on day t forgoes
  that morning's information by design.
- For anticipated events (anticipation-class anchors), the cutoff state may
  already partially reflect anticipation. State is pre-event market
  posture; it does not establish a pre-information state.
- The next_day class for the Treasury curve is deliberately conservative
  (the official daily table is typically posted the same evening; treating
  it as next-session-available can only exclude, never leak).

## 6. Non-claims

- Readiness is availability accounting only: no market response of any kind
  (no abnormal returns, no standardized values, no outcome labels, no
  event-study fields) appears in this report, in the probe output, or in
  any G2 artifact - enforced by a tested field whitelist.
- No state tags, no G4 thresholds, no recruitment, no promotion, no
  comparison, and no pooling; those are later, separately governed slices.
- Descriptive infrastructure documentation only: no p-value, no CI, no FDR;
  the closed Phase 1 / Phase 2 pools are untouched.
- Not a trading, prediction, or recommendation surface; nothing here says
  anything about the market behavior of any asset.

## 7. Reproduction (zero-cost)

```
python scripts/g_state_acquisition.py --fetch    # bounded acquisition
python scripts/g_state_acquisition.py --probe    # readiness, no outcomes
python -m unittest tests.test_g_state_acquisition
```

Contracts and constants live in `scripts/g_state_acquisition.py`
(SOURCE_CONTRACTS, FED_TARGET_TIMELINE, READINESS_FIELDS); the cutoff,
eligibility, window, missing-source, whitelist, and 65+32=97 reconciliation
behaviors are unit-tested in `tests/test_g_state_acquisition.py`.

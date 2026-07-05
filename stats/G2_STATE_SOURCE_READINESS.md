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
| credit_hy_oas | ICE BofA US High Yield OAS via the official FRED API (authenticated, free key, never stored) | OAS level | next_day | effectively unrevised (section 3) | cutoff at/before the surviving-window start (2023-07-04) -> source_missing (section 3); never proxied |

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
- No paid source and no paid request was used anywhere; all five acquired
  series came from zero-cost official/public endpoints (the FRED API key is
  free registration, not a paid product).
- Credit series identity verified from the authenticated API (G2C):
  `BAMLH0A0HYM2` = "ICE BofA US High Yield Index Option-Adjusted Spread",
  frequency "Daily, Close", units "Percent", not seasonally adjusted,
  release "ICE BofA Indices".
- Credit publication schedule observed live: the release `last_updated`
  stamp (2026-07-03 11:05 US Central) covers observations through
  2026-07-02 - the next-business-morning update the frozen `next_day`
  class conservatively assumes. Sampled observations are single-valued
  across all surviving vintages (no revision observed).

## 3. Credit dimension (G2B network diagnosis + G2C authenticated resolution)

G2B ran a bounded source resolution (three source paths, hard-capped) and
refined the G2A diagnosis from "FRED unreachable" to environment-blocked
with the failure layer identified:

1. Intended path - FRED CSV channel
   (`fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`): DNS, TCP
   connect, and TLS handshake to the CDN edge all succeed; the HTTP request
   is then silently dropped (read timeout, zero response bytes). The drop is
   host-level and header-independent (browser-identical headers behave the
   same), affects the plain series page too, and reproduced across checks
   hours apart; a control host fetched over the same network answered
   normally. A cloud-egress cross-check of the same URL received an explicit
   HTTP 403. The evidence is consistent with edge-level request filtering
   of this environment's egress - and rules out a source outage and DNS,
   TCP, or TLS failure as the cause. The
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

G2C completed the credential-gated path with an operator-supplied free FRED
API key (resolved from the gitignored `.env`; the key authenticates
requests only and never enters logs, cache metadata, or the repository -
the cached request URL is stored with `api_key=REDACTED`). Findings:

- Series identity verified from the API itself (section 2): the exact
  frozen series, `BAMLH0A0HYM2`, daily close, percent, NSA.
- LICENSING TRUNCATION (the material new fact): since April 2026 FRED
  distributes only a rolling three-year window of this ICE series. At
  acquisition (2026-07-05) observations exist from 2023-07-04 onward only.
  The ALFRED vintage archive is truncated to the same window - observation
  dates in 2018-2022 return no vintage rows at all. History before
  2023-07-04 is therefore SOURCE-WITHDRAWN: no zero-cost distribution of
  the same series exists for that span (the issuer platform remains
  registration-gated with no auditable scriptable history; G2B path 3).
- Vintage stamps are NOT availability evidence: ALFRED `realtime_start`
  equals the observation date even for the newest observation, while the
  release `last_updated` stamp shows the value physically arriving the
  NEXT business morning. The stamps are back-dated by convention, so
  publication timing rests on the observed update schedule instead - the
  same evidentiary standard the Treasury-curve dimension already uses.
  Under that schedule the frozen `next_day` class is conservative and
  valid: the latest eligible observation at cutoff c is dated c-1 or
  earlier and posts by c's morning, before the cutoff close.
- No revision observed: sampled observations across the surviving window
  are single-valued across all vintages, consistent with the frozen
  "effectively unrevised" classification.

Diagnosis after G2C: the environment/credential block is RESOLVED (the
authenticated API acquires cleanly from this environment), and the
dimension is now PARTIALLY AVAILABLE - honest availability for cutoffs
after 2023-07-04, structural `source_missing` for the 61 candidates whose
cutoffs precede the surviving window. The gap is a source-level licensing
property, uniform within its era across both lanes; it is not
candidate-selective. Per the G0 contract no proxy, no substitute series,
and no backfill from revised history were introduced; whether a
partially-covered dimension enters the frozen state vector (era-restricted
use, or drop) is a G4 decision, not a G2 one.

## 4. 97-candidate readiness matrix (outcome-blind)

| measure | count |
|---|---|
| candidates | 97 (65 frame_complete_historical + 32 designed_contrast) |
| cutoff resolved | 97 / 97 |
| complete state vector (5/5) | 36 |
| partial state vector (4/5) | 61 |
| missing: fed_policy_path | 0 |
| missing: vix_level_percentile | 0 |
| missing: spy_trend_ma200 | 0 |
| missing: curve_2s10s | 0 |
| missing: credit_hy_oas | 61 (source-withdrawn history; section 3) |

Missingness by lane and calendar year: the only missing dimension is
credit_hy_oas, and its missingness is exactly the source's licensing
window - every candidate whose cutoff precedes 2023-07-04, in both lanes
(frame_complete_historical 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:4;
designed_contrast 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:2), and
zero missing in 2024-2025. Within the surviving window there is no
candidate-level attrition at all. The four G2A dimensions remain available
for all 97 candidates in both lanes and all years, so the substrate's only
attrition signature is the disclosed era boundary, a source-level property.

Acquired history (gitignored local cache, 2016-06 through 2025-12): VIX
2438 observations; SPY 2411; 2s10s 2396; HY OAS 654 (2023-07-04 through
2025-12-31 - the substrate window intersected with the source's surviving
licensing window). Sufficient for every candidate cutoff, the six-month
policy lookback, the 252-session percentile, and the 200-session moving
average, with margin; the credit series covers every post-window cutoff.
No unrelated backfill was performed.

## 5. No-lookahead limitations (disclosed)

- The cutoff is a session-close boundary: an event early on day t forgoes
  that morning's information by design.
- For anticipated events (anticipation-class anchors), the cutoff state may
  already partially reflect anticipation. State is pre-event market
  posture; it does not establish a pre-information state.
- The next_day class for the Treasury curve is deliberately conservative
  (the official daily table is typically posted the same evening; treating
  it as next-session-available can only exclude, never leak).
- The credit dimension's no-lookahead guarantee is schedule-based, not
  vintage-proven: ALFRED realtime stamps for this series are back-dated to
  the observation date, so publication timing rests on the provider's
  observed next-business-morning update schedule (section 3) plus the
  conservative next_day class - the same standard as the Treasury curve.
- The credit series is served under a rolling three-year license window:
  a future re-run of `--fetch` will retrieve a LATER window than the one
  cached here (retrieval date recorded in cache metadata). The 36/61
  availability split in section 4 is reproducible only against a cache
  acquired while 2023-07-04 remains inside the source's window; the
  per-candidate cutoffs and eligibility rules themselves are deterministic.

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

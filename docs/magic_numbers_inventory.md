# Magic Numbers & Tunable Thresholds — Inventory

**Status:** read-only inventory. No values proposed. Compiled 2026-05-05.

**Scope:** `routes/movers.py`, `market_context.py`, `market_check.py`, `db.py`, `headline_registry.py`, plus an audit of which thresholds are pinned by tests.

**Convention:**
- *Empirical* = inline comment cites a calibration run, dataset size, or historical event that justified the value (e.g. "169 ticker-pairs: p10=0.15%").
- *Reasoned* = inline comment gives qualitative justification but no measured calibration ("comment notes diminishing returns at 8").
- *Intuitive* = no inline justification; value appears picked by feel.

`market_context.py` contains no tunable numerics — pure composition. Omitted from the tables below.

---

## 1. routes/movers.py

### 1a. Time windows / TTLs

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 162 | `_api._MARKET_MOVERS_TTL` (ref) | (imported) | Cache TTL for market_movers slice | Intuitive |
| 171 | `_api._WEEKLY_MOVERS_TTL` (ref) | (imported) | Cache TTL for weekly slice | Intuitive |
| 183 | `_api._PERSISTENT_MOVERS_TTL` (ref) | (imported) | Cache TTL for persistent slice | Intuitive |
| 273 | `max_age_seconds` (inline) | 86400 | SQLite news cache load freshness (1d) | Intuitive |
| ~362 | "today" window fallback | 48h fallback | Today window falls back when 24h is empty | Reasoned (inline comment) |
| 1339–1344 | `since_hours` default (cluster filter) | 48h, bounded ge=1, le=720 | Recency window for cluster filtering | Intuitive |
| 2060–2061 | `since_hours` default (backfill candidate) | 72h, bounded ge=1, le=720 | Backfill recency window | Intuitive |

### 1b. Cluster ranking weights (`_RANK_W_*`)

Block introduced with comment explicitly flagging these as the operator-tunable surface (lines 612–613). No empirical references for any individual value.

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 614 | `_RANK_W_SOURCE_COUNT_PER` | 1.0 | Per-publisher weight (capped) | Reasoned |
| 615 | `_RANK_SOURCE_COUNT_CAP` | 8 | Diminishing-returns cap on source_count | Reasoned |
| 616 | `_RANK_W_HIGH_TIER_PER` | 1.5 | Per high-tier publisher weight | Reasoned |
| 617 | `_RANK_W_ASSET_TERMS` | 1.5 | Asset/ticker mention weight | Reasoned |
| 618 | `_RANK_W_MACRO_POLICY` | 3.0 | CB / CPI / rate-decision weight | Reasoned |
| 619 | `_RANK_W_GEOPOLITICAL` | 2.5 | Sanctions / tariffs / military weight | Reasoned |
| 620 | `_RANK_W_COMMODITY_POLICY` | 2.5 | OPEC / crude / LNG / rare-earth weight | Reasoned |
| 621 | `_RANK_W_CORPORATE_ACTION` | 1.0 | M&A / buyback / IPO / guidance weight | Reasoned |
| 622 | `_RANK_W_GENERIC_NOISE` | -3.0 | Market-wrap roundup penalty | Reasoned |
| 743 | (inline) | `_RANK_SOURCE_COUNT_CAP` | Reuse of cap in score computation | — |

### 1c. Top-N / page-size limits

| Line | Where | Value | Controls | Validation |
|---|---|---|---|---|
| 29 | `_PERSISTENT_OVERFETCH` | 100 | Over-fetch ceiling for persistent surface | Reasoned (lines 25–28) |
| 131 | `limit` default | 100 | Default UI mover cards per window | Intuitive |
| 253 | (inline) | 500 | Events loaded for diagnostics | Intuitive |
| 308 | `/market-movers` `limit` default | 5 | Default route limit | Intuitive |
| 1327 | `/movers/backfill-recent` `limit` | 3, bounded le=20 | Headlines past dedup gate | Intuitive |
| 1338 | `scan_limit` | 25, bounded ge=1, le=100 | Clusters scanned before stop | Intuitive |
| 1835 | `/movers/backfill-preview` `limit` | 25, bounded ge=1, le=100 | Preview items returned | Intuitive |
| 2338 | `/movers/today` `limit` | 10 | Default route limit | Intuitive |
| 2386 | `/movers/weekly` `limit` | 10 | Default route limit | Intuitive |
| 2399 | `/movers/yearly` `limit` | 10 | Default route limit | Intuitive |
| 2416 | `/movers/persistent` `limit` | 12 | Default route limit | Intuitive |

### 1d. Other

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 23 | `_GUARDRAIL_WINDOWS` | {today, weekly, market} | Windows receiving diversity guardrail (persistent excluded) | Reasoned |
| 36 | `_DEFAULT_MAX_BACKFILL_LLM_CALLS` | 1 | Default LLM-call budget per backfill | Intuitive |
| 95–98 | `MAX_BACKFILL_LLM_CALLS` env bounds | min=0, max=20 | Hard bounds on env override | Intuitive |
| 2016 | `rank_score` rounding | 3 dp | Output formatting | Cosmetic |

No move-size / pct-change thresholds in this file.

---

## 2. market_check.py

### 2a. Time windows / TTLs

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 248 | `SPARK_LENGTH` | 20 | Sparkline bars (~1 trading month) | Reasoned |
| 297 | `_STALE_TICKER_CALENDAR_DAYS` | 5 | Calendar days before ticker stale | Reasoned ("≈ 3 trading days") |
| 312 | `_TICKER_CACHE_TTL` | 600s | In-memory ticker cache TTL | **Empirical** (54-event sizing comment) |
| 313 | `_TICKER_CACHE_MAXSIZE` | 512 | Cache max entries | **Empirical** ("320 live → 512 headroom") |
| 452 | `_clamp_to_market_date` loop cap | 10 | Max iterations to skip holidays | Reasoned ("≤~4 days") |
| 601 | `_VERIFY_TIMEOUT` | 8.0s | Secondary-fetch verify timeout | Intuitive |
| 969 | volume window | 20 | Trailing days for avg volume | Reasoned (matches `SPARK_LENGTH`) |

### 2b. Score thresholds / cutoffs

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 243 | `_DATA_QUALITY_DEGRADED_THRESHOLD` | 0.5 | Fraction missing → degraded flag | Intuitive |
| 598 | `_VERIFY_MOVE_THRESHOLD` | 5.0 | abs(r5) triggers dual-source verify | Intuitive |
| 599 | `_VERIFY_DELTA_PCT` | 3.0 | Primary-vs-secondary delta = disputed | Intuitive |
| 600 | `_VERIFY_LOW_VOL` | 0.1 | Suspicious low vol_ratio | Intuitive |
| 847 | `_direction_tag` flat zone | ±0.5% | Inconclusive return zone | Reasoned |
| 975 | high_volume threshold | 1.25× | 25% above avg = noteworthy | Reasoned |
| 1014 | big_5d_move | 2.0% | ≥2% in 5d = notable | Reasoned |
| 1597 | rates regime `THRESH` | 0.3 | pp / % cutoff for directional flag | Intuitive |
| 1966 | `_TIGHT_THRESHOLD` (inventory) | +3.0% | 20-day tightening flag | Intuitive |
| 1967 | `_COMFORT_THRESHOLD` (inventory) | -3.0% | 20-day easing flag | Intuitive |
| 2165 | VIX elevated ratio | 1.20 | VIX > 20d × 1.20 = elevated | Reasoned |
| 2170 | VIX slightly-elevated pct | 5% | >5% above avg | Intuitive |
| 2256 | credit widening | 0.5pp | Spread move = credit stress | Intuitive |
| 2295 | safe-haven inflow | 0.3% | Per-haven inflow flag | Intuitive |
| 2299 | `safe_haven_bid` | 1.5pp | Aggregate flight-to-safety | **Empirical** (raised 0.5→1.5; comment cites 2025 base rates 45%→10%) |
| 2330 | breadth deterioration | -1.5pp | RSP-vs-SPY lag flag | **Empirical** (raised -0.5→-1.5; 2025 data 36%→6%) |
| 2486 | `DECAY_DE_MINIMIS` | 0.3 | Returns below = noise | **Empirical** (169 ticker-pairs, p10=0.15%) |
| 2554, 2560 | decay retention | 0.8, 0.4 | Accelerating / Holding bands | **Empirical** (213 pairs) |

### 2c. Move-size / sanity caps

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 536 | `_RETURN_SANITY_R1_PCT` | 100.0% | 1d sanity ceiling | Reasoned (catches +624%/+1348% bugs) |
| 537 | `_RETURN_SANITY_R5_PCT` | 200.0% | 5d ceiling | Reasoned |
| 538 | `_RETURN_SANITY_R20_PCT` | 500.0% | 20d ceiling | Reasoned |
| 1642, 1661, 1672 | nominal/FVX/TYX caps | ±5pp | Yield 5d cap | Reasoned |
| 1699, 1709 | STIP / LTPZ caps | 20%, 30% | TIPS short/long caps | Intuitive |
| 1724 | breakeven proxy cap | ±7pp | Parity with shock_decomposition | Reasoned |
| 2087 | `_MACRO_MOVE_CAPS["DXY"]` | 15.0% | DXY move ceiling | Reasoned |
| 2088 | `_MACRO_MOVE_CAPS["^VIX"]` | 200.0% | VIX move ceiling | **Empirical** (2020 spike ~115%) |
| 2089 | `_MACRO_MOVE_CAPS["CL"]` | 65.0% | WTI ceiling | **Empirical** (Apr 2020 ~$0) |
| 2090 | `_MACRO_MOVE_CAPS["BZ=F"]` | 65.0% | Brent ceiling | Reasoned |
| 2091 | `_MACRO_MOVE_CAPS["10Y"]` | 5.0pp | 10Y yield ceiling | Reasoned |
| 2064 | `_PRICE_FLOORS["GLD"]` upper | 600.0 | GLD price ceiling | **Empirical** (2026 ATH ~496) |

### 2d. Other

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 238 | `_MAX_FETCH_WORKERS` | 6 | Parallel yfinance downloads | Reasoned (rate limits) |
| 1572 | `_TIP_DURATION` | 7.5 | TIP ETF modified duration | **Empirical** (iShares 7.4–7.7) |
| 1760 | SHY duration divisor | 1.9 | 2Y pp conversion | Intuitive |

---

## 3. db.py

PRODUCT thresholds only. Infrastructure constants (sqlite timeout=30s, schema_version=3) are listed at the bottom and excluded from validation focus.

### 3a. Time windows / TTLs / retention

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 519 | `_is_duplicate` window | 10 min | Event dedup time window | Reasoned |
| 814 | timestamp decay fallback | 7 days | Legacy row dedup fallback | Intuitive |
| 1793 | `_DEDUP_DATE_WINDOW_DAYS` | 2 | Date proximity for read-time dedup | Reasoned |
| 2412 | `find_cached_analysis` max age | 86400s (24h) | Analysis cache expiry | Reasoned (default doc'd) |
| 2502 | `load_news_cache` max age | 300s | News cache freshness | Intuitive |
| 2792 | `get_trending_clusters` window | 72h | Trending recency window | Intuitive |

### 3b. Similarity / score thresholds

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 1475 | `_RELATED_THRESHOLD` | 0.35 | Jaccard cutoff for related events | Reasoned (comment vs 0.30 alt) |
| 1492 | `_MIN_SHARED_TOKENS` | 2 | Min shared tokens (short headlines) | Reasoned |
| 1493 | `_SHORT_HEADLINE_THRESHOLD` | 4 words | Short-headline guard | Reasoned |
| 1792 | `_DEDUP_THRESHOLD` | 0.65 | Read-time near-duplicate collapse | Reasoned |
| 1943 | `_ANALOG_THRESHOLD` | 0.15 | Historical analog Jaccard | Reasoned (vs 0.35 above) |
| 2074 | transmission match cutoff | 0.60 | Transmission-boost eligibility | Intuitive |

### 3c. Weights / multipliers

| Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|
| 1591 | `_SIMILAR_W_HEADLINE` | 0.40 | Headline-overlap weight | Reasoned (dominance documented) |
| 1592 | `_SIMILAR_W_MECHANISM` | 0.25 | Mechanism-text weight | Reasoned |
| 1593 | `_SIMILAR_W_TICKERS` | 0.20 | Shared-tickers weight | Reasoned |
| 1594 | `_SIMILAR_W_STAGE` | 0.10 | Stage tie-breaker | Reasoned |
| 1595 | `_SIMILAR_W_PERSISTENCE` | 0.05 | Persistence tie-breaker | Reasoned |
| 1950 | `_TRANSMISSION_BOOST_SAME_CHAIN` | 0.10 | Same-chain boost | Reasoned hierarchy |
| 1951 | `_TRANSMISSION_BOOST_SAME_FAMILY_CHANNELS` | 0.06 | Same-family+channels boost | Reasoned hierarchy |
| 1952 | `_TRANSMISSION_BOOST_SAME_FAMILY` | 0.03 | Same-family-only boost | Reasoned hierarchy |
| 1990 | analog stage match bonus | 0.05 | Stage match score boost | Intuitive |
| 1992 | analog persistence match bonus | 0.03 | Persistence match score boost | Intuitive |

### 3d. Top-N / page-size limits

| Line | Where | Value | Controls | Validation |
|---|---|---|---|---|
| 1521 | `find_related_events` | 5 | Max related events returned | Intuitive |
| 1699 | cascade `per_level` | 5 | Hop-1 cascade | Intuitive |
| 1700 | cascade `hop2_per_parent` | 2 | Hop-2 per parent | Intuitive |
| 1868 | analogs limit | 3 | Max analogs returned | Intuitive |
| 1902 | analog candidate pool | limit × 3 (regime) | Pool widened for regime rerank | Reasoned |
| 1914 | analog SQL LIMIT | 500 | Scan window | Reasoned |
| 2253 | `load_recent_events` default | 10 | Default rows | Intuitive |
| 2794 | `get_trending_clusters` default | 8 | Trending count | Intuitive |
| 3145 | `load_eligible_unanalyzed_candidates` | 50 | Max unanalyzed candidates | Intuitive |

### 3e. Infrastructure (excluded from validation focus)

| Line | Symbol | Value | Notes |
|---|---|---|---|
| 11 | `SCHEMA_VERSION` | 3 | Structural |
| 588 | sqlite3 timeout | 30.0s | Lock-wait |

---

## 4. headline_registry.py

| Cat. | Line | Symbol | Value | Controls | Validation |
|---|---|---|---|---|---|
| TTL | 22 | `_DEFAULT_TTL_DAYS` | 5 | Low-impact headline expiry (env-overridable via `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS`) | Intuitive |
| Window | 224 | `recent_hours` (diagnostics arg) | 24 | "Recent" event count window | Intuitive |
| Limit | 223 | `candidates_limit` (diagnostics arg) | 50 | Max unanalyzed candidates returned | Intuitive |

---

## 5. Test pinning audit

Of the threshold-asserting tests located, **almost all hardcode the expected value** rather than importing the source constant. Changing a source constant therefore breaks the test even if the new value is correct.

| Source constant | Test | Imported? |
|---|---|---|
| db `_is_duplicate` window (10 min) | `test_db.py:204` | **Hardcoded** |
| `headline_registry._DEFAULT_TTL_DAYS` (5d) | `test_headline_registry.py:122` | **Hardcoded** |
| `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS` env (1d) | `test_headline_registry.py:176` | env-driven |
| `_REFRESH_RECENT_HOURS` (4h) | `test_market_check_freshness.py:97,105` | **Hardcoded** |
| `_REFRESH_OLDER_HOURS` (24h) | `test_market_check_freshness.py:113` | **Hardcoded** |
| `_EVENT_AGE_FROZEN_DAYS` (30d) | `test_market_check_freshness.py:126` | **Hardcoded** |
| `_TODAY_WINDOW_HOURS` (24h) | `test_movers_time_window.py:118,131` | **Hardcoded** |
| `_TODAY_FALLBACK_HOURS` (48h) | `test_movers_time_window.py:131` | **Hardcoded** |
| `_MARKET_MOVERS_WINDOW` (48h) | `test_movers_time_window.py:155,162` | **Hardcoded** |
| `SNAPSHOT_MAX_AGE_SECONDS` (120s) | `test_market_context.py:449` | **imported** |

No tests assert ranking weights, similarity thresholds, stress-regime cutoffs, or sanity caps — meaning those tunables are **unprotected by tests**, free to drift, and need their own validation harness.

---

## 6. Top 5 highest-risk tunables to validate next

Selected for: high user-visible impact, weak/no empirical backing, and (for items 1–4) absence of test coverage that would surface drift.

1. **Cluster ranking weight set `_RANK_W_*`** — `routes/movers.py:614–622`. Directly orders the user-facing movers list. All 9 weights are reasoned but un-calibrated, no test fixes them, and small shifts (e.g. `_RANK_W_GENERIC_NOISE` from −3.0 → −2.0) materially reorder cards. Highest blast radius.

2. **`_DEDUP_THRESHOLD = 0.65`** — `db.py:1792`. Read-time near-duplicate collapse. Too low ⇒ legitimate distinct headlines get suppressed; too high ⇒ user sees the same story 4×. No empirical calibration, no test pinning. Pair with `_RELATED_THRESHOLD = 0.35` and `_ANALOG_THRESHOLD = 0.15` (db.py:1475, 1943) since they are the same Jaccard family at three sensitivity levels.

3. **Stress-regime cutoffs (intuitive ones only)** — `market_check.py:2165 (1.20), 2256 (0.5pp), 2295 (0.3%), 2170 (5%)`. The Calm/Watch/Stressed badge is the most prominent context signal. Two of its inputs (safe_haven_bid 1.5pp, breadth −1.5pp) were already empirically re-tuned away from intuitive defaults in 2025 — strong prior that the *un-recalibrated* siblings (VIX ratio, credit widening, haven inflow per-name) are also miscalibrated.

4. **`_VERIFY_MOVE_THRESHOLD = 5.0`** + `_VERIFY_DELTA_PCT = 3.0` + `_VERIFY_LOW_VOL = 0.1`** — `market_check.py:598–600`. Triple of intuitive thresholds gating dual-source verification. Wrong values mean either unnecessary provider load or silent acceptance of bad data; recent 1348%/+624% bugs cited in `_RETURN_SANITY_*` comments suggest verification is load-bearing.

5. **`headline_registry._DEFAULT_TTL_DAYS = 5`** — `headline_registry.py:22`. Determines when low-impact headlines drop out of the registry, which feeds downstream mover/relevance pipelines. Test pins it as 5d but doesn't justify it. A wrong TTL silently shrinks or inflates the population of analyzable events.

Honourable mentions worth queueing right after the top 5: `routes/movers.py:1339` `since_hours=48` cluster window; `db.py:2412` analysis cache 24h TTL; `db.py:2074` transmission match 0.60.

---

## Verification

`git diff --check` is run after this file is written; expected output: nothing (this commit is doc-only and CLAUDE.md mandates editing in place on `master`). Result recorded below.

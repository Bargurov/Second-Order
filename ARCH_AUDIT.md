# Second Order — Architectural Audit

**Date:** 2026-04-07
**Scope:** Full repository read-only audit across structural integrity, bug hunting, quantitative rigor, and strategic architecture.

---

## Triage Summary

| Tier | Count | Highest-Impact Item |
|------|-------|---------------------|
| Critical (Fix Now) | 6 | `compute_stress_regime` swallows all exceptions — silently reports calm markets during actual stress |
| Quantitative Vulnerabilities | 8 | NaN from yfinance propagates through direction tags, producing incorrect "contradicts" labels |
| High (Fix Before V2) | 11 | `_TICKER_CACHE` is unbounded and unprotected by locks; will leak memory and break under free-threading |
| Strategic Upgrades | 7 | MarketDataProvider protocol to phase out yfinance; Polygon.io at $29/mo covers equities + futures |

---

## Critical (Fix Now)

### C-1. `compute_stress_regime()` wraps 150 lines in bare `except Exception: pass`

**File:** `market_check.py` ~L916-1066
**Impact:** If any internal calculation raises (division by zero, missing key, yfinance change), the entire stress computation silently returns an all-calm regime. During actual market stress — the exact moment the tool matters most — users see green across the board with no indication of failure.

**Fix:** Replace the outer `try/except` with per-signal exception handling. Each of the five signals (VIX, term structure, credit, safe haven, breadth) should compute independently so a failure in one does not mask the others. Log every exception.

---

### C-2. NaN propagation from yfinance corrupts direction tags

**File:** `market_check.py`, `_pct()` → `_direction_tag()`
**Impact:** yfinance can return NaN in Close/Volume columns (stock splits, corporate actions, gaps). `_pct()` returns NaN (float arithmetic), not None. `_direction_tag()` checks `if r5 is None` (L170) but NaN is NOT None. The comparison `abs(NaN) < 0.5` evaluates to `False`, so the function proceeds to `r5 > 0` which is also `False` for NaN. A beneficiary ticker with NaN data gets classified as `"contradicts ↓"` — the exact opposite of what the model predicted. The hypothesis support ratio is silently corrupted.

**Fix:** Add `if r5 is None or math.isnan(r5): return None` at the top of `_direction_tag()`. Apply similar guards in `_pct()` and `_pct_forward()`.

---

### C-3. No punctuation stripping in `_headline_words()`

**File:** `db.py` L297, `news_sources.py` L727-728
**Impact:** `title.lower().split()` does not strip punctuation. The headline `"Oil: OPEC's decision, markets rally."` produces tokens `{"oil:", "opec's", "decision,", "markets", "rally."}`. These will never match clean tokens `{"oil", "opec", "decision", "markets", "rally"}` from another headline. Every punctuation-attached word becomes a unique token, defeating similarity matching for both related events and historical analogs.

**Fix:** Apply `re.sub(r"[^\w\s]", "", token)` or equivalent stripping before set insertion.

---

### C-4. 13 silent exception blocks with zero logging

**Files:** `api.py` (8 blocks), `market_check.py` (5 blocks)
**Impact:** Production debugging is impossible when errors are swallowed. The worst offenders beyond C-1:

| Location | Pattern | Risk |
|----------|---------|------|
| `compute_rates_context()` ~L640 | `except Exception: pass` | Returns garbage regime silently |
| `macro_snapshot()` inner loop ~L529 | `except Exception: pass` | Missing macro instruments show as null, indistinguishable from "no data" |
| `_get_news_cached()` ~L111 | `except Exception: db_payload = None` | Stale news cache silently used, fresh fetch failure hidden |
| `_backtest_one()` ~L470 | `except Exception` | Returns empty outcomes, indistinguishable from "no tickers" |

**Fix:** Replace every bare `except Exception: pass` with `except Exception: logger.exception("context")`. Never pass silently.

---

### C-5. Network failures silently produce all-null analysis

**File:** `market_check.py`, `_fetch()` → `_check_one_ticker()` L311
**Impact:** If yfinance network calls fail (timeout, rate limit, DNS), ALL tickers return `_no_data` with `direction: None`, `return_5d: None`, etc. The analysis proceeds with zero market data. The frontend renders "Pending" badges on every ticker, but there is no top-level error banner telling the user "market data is unavailable." The user sees a complete-looking analysis with all neutral/missing market signals, which is actively misleading.

**Fix:** Track fetch failure count in `market_check()`. If > 50% of tickers fail, return a top-level error flag (e.g., `"market_error": "X of Y tickers failed to fetch"`). Surface this in the frontend as a degraded-data warning.

---

### C-6. Duplicated decay classification logic will diverge

**Files:** `db.py` L428-438, `market_check.py` L1123-1162
**Impact:** `find_historical_analogs()` in `db.py` contains an inline copy of the decay classification logic from `classify_decay()` in `market_check.py`. Fixing a bug in one copy (e.g., the C-2 NaN issue) while forgetting the other creates silently inconsistent behavior between the analogs module and the movers module.

**Fix:** Delete the inline copy in `db.py`. Import and call `classify_decay()` from `market_check.py`.

---

## Quantitative Vulnerabilities

### Q-1. Decay "Reversed" classification has a coverage gap

**File:** `market_check.py` L1139, `db.py` L431
**Trigger:** `r5=-0.3, r20=+0.8`. `same_sign=False`, `abs(r5)=0.3 < 0.5` → Reversed check fails. Falls through to "Fading". But a swing from +0.8% to -0.3% is a genuine sign reversal, not a fade. Similarly, `r5=-2.0, r20=+0.4` is clearly reversed but `abs(r20)=0.4 < 0.5` blocks it.

**Fix:** Lower the magnitude threshold from 0.5% to 0.2%, or check only `not same_sign and (abs(r5) > 0.2 or abs(r20) > 0.2)`.

---

### Q-2. No de minimis threshold — noise is classified as signal

**File:** `market_check.py` `classify_decay()`
**Trigger:** `r5=0.1, r20=0.1`. Both positive, `same_sign=True`, `abs5 > abs20*0.8` → "Accelerating". Evidence: "5d move (+0.1%) is still intensifying vs 20d (+0.1%)". A 0.1% move is market noise, not acceleration.

**Fix:** Add a de minimis guard: `if abs(r5) < 0.3 and abs(r20) < 0.3: return "Flat"` (or "Negligible").

---

### Q-3. Zero-zero returns classified as "Fading"

**File:** `classify_decay()` and `db.py` inline copy
**Trigger:** `r5=0.0, r20=0.0`. `same_sign=False` (neither > 0 nor < 0). All checks fail; falls through to "Fading" with evidence "5d +0.0% has pulled back from 20d +0.0%". Nonsensical.

**Fix:** Add an explicit check at the top: `if r5 == 0.0 and r20 == 0.0: return "Flat"`.

---

### Q-4. "Accelerating" label is semantically inverted

**File:** `market_check.py` L1147
**Logic:** `abs5 > abs20 * 0.8` → "Accelerating". But if 80% of the 20d move happened in the first 5 days and only 20% in the remaining 15 days, the move is actually decelerating. `r5=+5%, r20=+5%` (completely flat after the initial shock) is classified as "Accelerating" when it is "Holding."

**Fix:** Rename "Accelerating" to "Front-loaded" or change the logic to compare the rate of change: the last-5d return vs. the first-5d return of the 20d window. Alternatively, accept the current ratio-based label but rename to "Sustained" (for `ratio > 0.8`) to avoid the misleading "intensifying" connotation.

---

### Q-5. `best_20d` selection is coupled to `best_5d`, not independently maximized

**File:** `db.py` L418-425
**Trigger:** Ticker A has `r5=+8%, r20=None`; Ticker B has `r5=+3%, r20=+6%`. Code picks A (largest |r5|), sets `best_20d=None`, classifies as "Unknown" — ignoring B's valid 20d data.

**Fix:** Track `best_5d` and `best_20d` independently, or prefer tickers where both are available.

---

### Q-6. Adjusted-close lookahead in backtesting

**File:** `market_check.py`, `_fetch()` L128, `_fetch_since()` L150 (`auto_adjust=True`)
**Impact:** yfinance retroactively adjusts historical closes for subsequent dividends and splits. A backtest run today sees different March 1 closes than the system would have seen on March 1. Magnitude: ~0.2-0.5% per quarter from dividends, discrete jumps from splits. Small but compounds across historical comparisons.

**Fix (low priority):** For backtesting integrity, use `auto_adjust=False` and handle splits via the `actions` attribute. For live analysis, `auto_adjust=True` is fine.

---

### Q-7. No holiday handling in date clamping

**File:** `market_check.py`, `_clamp_to_market_date()` L94-117
**Impact:** Only weekends are clamped. An event_date of "2026-01-19" (MLK Day, a Monday) passes the weekday check. yfinance returns data starting from the next trading day, shifting the anchor by one day. Benign for most cases (the `anchor_date` field reflects the actual first bar), but introduces subtle one-day misalignment for holiday events.

**Fix:** Add a US market holiday calendar (e.g., `pandas_market_calendars` or a static set of federal holidays).

---

### Q-8. Lack of stemming causes false negatives in similarity matching

**File:** `db.py` L297, `news_sources.py` L728
**Impact:** "tariffs" != "tariff", "sanctions" != "sanction", "exports" != "export". Same-event headlines using singular vs. plural forms score 0 on those terms. Two genuinely related events fail to match when they should.

**Fix:** Apply a minimal suffix stripper (strip trailing 's', 'ed', 'ing') to `_headline_words()`. A full Porter stemmer is unnecessary for short headlines but a 3-rule striper captures the common cases.

---

## High (Fix Before V2)

### H-1. `_TICKER_CACHE` is unbounded

**File:** `market_check.py` L68
**Impact:** The cache is a plain `dict` with TTL-based lazy eviction: stale entries are only removed when they are next accessed. On a long-running server with diverse ticker queries, the dict grows monotonically. At 3 months of daily OHLCV per ticker (~64 rows × 2 columns × 8 bytes ≈ 1 KB per entry), 10,000 unique tickers = 10 MB. Not catastrophic, but with no size cap it will grow until OOM on a constrained server.

**Fix:** Use `cachetools.TTLCache(maxsize=500, ttl=600)` or implement an LRU eviction pass.

---

### H-2. No thread-safety on shared mutable state

**File:** `market_check.py` L60 (`_MAX_FETCH_WORKERS = 6`), L68 (`_TICKER_CACHE`), `api.py` (5 module-level caches)
**Impact:** `ThreadPoolExecutor` with 6 workers writes to `_TICKER_CACHE` concurrently. Currently protected only by CPython's GIL, which is being removed in Python 3.13+ (free-threaded mode). The api.py caches (`_analysis_cache`, `_news_cache`, `_stress_cache`, `_rates_cache`, `_macro_cache`) are similarly unprotected.

**Fix:** Add `threading.Lock` around all cache reads/writes. Use `dict.setdefault` or `Lock`-guarded patterns.

---

### H-3. Frontend TypeScript types are stale

**File:** `frontend/src/lib/api.ts`
**Issues:**
- `Ticker.return_1d: number` (L34) — backend can return `null` (market_check.py L302)
- `Ticker.return_5d: number` and `return_20d: number` (L35-36) — same issue
- `StressComponentDetail.status` includes `"watch"` (L182) — backend only returns `"stressed"` or `"calm"`, never `"watch"`
- `SavedEvent` (L115-132) is missing 7 fields the backend provides: `transmission_chain`, `if_persists`, `currency_channel`, `policy_sensitivity`, `inventory_context`, `low_signal`, `model`
- `MarketMover` includes optional `currency_channel`, `policy_sensitivity`, `inventory_context` — backend's `_build_mover_summary()` never includes these

**Fix:** Audit and sync all TypeScript interfaces against actual API responses. Make nullable fields `| null`.

---

### H-4. No financial-domain stopwords

**File:** `db.py` L281-287
**Impact:** Words like "market", "stock", "price", "global", "economy", "billion", "impact" are extremely common in financial headlines but carry no discriminating power. They inflate Jaccard similarity between unrelated events. Example: "China launches space station module imports equipment" matches "China imposes tariffs on semiconductor imports" at Jaccard=0.18 (above the 0.15 analog threshold) purely due to "china" and "imports."

**Fix:** Add ~20 financial-domain stopwords to `_STOP_WORDS`: `market, stock, price, trade, global, economy, economic, index, sector, shares, growth, impact, policy, billion, million, rise, fall, drop, surge, gains`.

---

### H-5. Short headlines produce inflated Jaccard scores

**File:** `db.py`, `_jaccard()`
**Impact:** For 3-word content sets, sharing 1 word produces Jaccard = 1/(3+2-1) = 0.20, above the 0.15 analog threshold. "Oil prices surge" matches "Oil prices drop" at 0.50 — semantically opposite events. The Jaccard method has no concept of semantic opposition.

**Fix:** Add a minimum shared-word-count requirement alongside the ratio: `if len(shared) < 2: continue` when both headline word sets are under 5 words.

---

### H-6. Partial yfinance rate-limiting yields inconsistent ticker subsets

**File:** `market_check.py`, `market_check()` L350 (6 parallel workers)
**Impact:** If yfinance rate-limits mid-batch, some tickers succeed and some fail. The hypothesis support ratio (`supporting / total_with_direction`) is computed from whichever tickers happened to succeed — an arbitrary and non-reproducible subset.

**Fix:** Implement retry logic with exponential backoff (1 retry, 2s delay). If > 50% still fail, flag the analysis as degraded (see C-5).

---

### H-7. Delisted tickers return stale data without a staleness flag

**File:** `market_check.py`, `_fetch()` L127-128
**Impact:** A ticker delisted 2 months ago may still have 6+ bars of historical data from before delisting. The code's `len(data) < 6` guard passes, and "returns" are computed from dead historical prices as if they were current. No staleness check exists.

**Fix:** Compare the most recent bar's date against today. If the gap exceeds 5 trading days, flag the ticker as potentially delisted/halted.

---

### H-8. Sparkline arrays have inconsistent lengths

**File:** `market_check.py` L289-295
**Impact:** Spark arrays range from 6 to 20 elements depending on data availability. When the frontend renders sparklines side-by-side, different lengths mean different x-axis scales: one ticker covers 6 days while another covers 20. Visual comparison is meaningless.

**Fix:** Always pad/truncate to exactly 20 elements. If fewer than 20 bars, left-pad with the earliest available value.

---

### H-9. Ticker in both beneficiary and loser lists silently becomes beneficiary

**File:** `market_check.py` L358-362
**Impact:** `role_map` is built by iterating losers first, then beneficiaries. A ticker in both lists gets the last-assigned role ("beneficiary"). The LLM can produce overlapping lists (e.g., an oil company that benefits from supply disruption but loses from demand destruction). The system silently discards the "loser" classification with no warning.

**Fix:** Detect the overlap and assign `role = "mixed"` or log a warning. A "mixed" role should skip direction-tag evaluation entirely.

---

### H-10. `compute_stress_regime()` and `compute_rates_context()` fail identically

**File:** `market_check.py` ~L640 (`rates`), ~L897 (`stress`)
**Impact:** Both wrap their entire computation in bare `except Exception: pass`. If either fails, the API returns a default "calm" / "neutral" regime. The frontend has no way to distinguish "genuinely calm markets" from "failed to compute."

**Fix:** Same as C-4 — add per-signal error handling and return an error flag when computation fails.

---

### H-11. api.py is a 930-line monolith but safely splittable

**File:** `api.py`
**Structure:** 22 endpoints across 5 functional groups:

| Group | Endpoints | Shared State Needed |
|-------|-----------|---------------------|
| Analyze | `/analyze`, `/analyze/stream` | `_analysis_cache`, `analyze_event`, `market_check`, `find_historical_analogs` |
| Events | `/events`, `/events/{id}/review`, `/events/{id}/related`, `/events/{id}/backtest` | `db.*` functions |
| Market/Macro | `/macro`, `/macro/batch`, `/stress`, `/rates-context`, `/ticker/*` | `_macro_cache`, `_stress_cache`, `_rates_cache`, `market_check.*` |
| Movers | `/market-movers`, `/movers/today`, `/movers/weekly`, `/movers/yearly`, `/movers/persistent` | `db.load_recent_events`, `market_check.*`, news cache |
| News | `/news` | `_news_cache`, `news_sources.*` |

**Fix path:** Extract into `routes/analyze.py`, `routes/events.py`, `routes/market.py`, `routes/movers.py`, `routes/news.py` using FastAPI `APIRouter`. The only cross-group dependency is Movers → News (for the `/ticker/{symbol}/headlines` data). This can be resolved with a shared `news_service` module.

---

## Strategic Upgrades

### S-1. MarketDataProvider Protocol — Phase Out yfinance

All yfinance usage is confined to `market_check.py` across 5 call sites:

| Call Site | yfinance API | Replacement Method |
|-----------|-------------|-------------------|
| `_fetch()` L127 | `yf.download(period="3mo")` | `provider.fetch_daily(period="3mo")` |
| `_fetch_since()` L150 | `yf.download(start=date)` | `provider.fetch_daily(start=date)` |
| `ticker_chart()` L1186 | `yf.download(start, end)` | `provider.fetch_daily(start, end)` |
| `ticker_info()` L1244 | `yf.Ticker().info` | `provider.fetch_info()` |

Minimal Protocol interface:

```python
from typing import Protocol, runtime_checkable
from datetime import date
import pandas as pd

@runtime_checkable
class MarketDataProvider(Protocol):
    def fetch_daily(
        self, ticker: str, *,
        period: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame | None:
        """Return DataFrame with DatetimeIndex, 'Close' and 'Volume' columns."""
        ...

    def fetch_info(self, ticker: str) -> dict:
        """Return {name, sector, industry, market_cap, avg_volume}."""
        ...
```

**Migration:** 1) Create protocol + YFinanceProvider wrapper. 2) Refactor `_fetch`/`_fetch_since` to delegate. 3) Add PolygonProvider. 4) Switch via env var. 5) Remove yfinance.

**Recommended replacement:** Polygon.io Basic ($29/mo). Only provider with native equity + ETF + futures + index support in a single API. Official SIP data eliminates yfinance scraping noise. REST + WebSocket APIs enable real-time path.

---

### S-2. Real-Time Macro Ingestion via Background Workers

**Current state:** All macro data is demand-fetched synchronously inside API handlers. First request after cache expiry pays 2-5 second latency. `/stress` fetches 9 tickers; cache-cold starts can take 10-15 seconds.

**Target architecture:**

```
Background workers (macro, stress, rates)
  → Poll Polygon.io every 30-60s
  → Publish to Redis channels
  → Store latest snapshot in Redis key

FastAPI SSE endpoints (/macro/stream, /stress/stream)
  → Send current state immediately from Redis key
  → Stream updates from Redis pub/sub

Frontend
  → EventSource connection replaces polling
```

This eliminates cold-start latency entirely and enables sub-second regime change detection.

---

### S-3. Futures Contract Mapping

**Current state:** The system maps entirely to US equities and ETFs. No futures concept exists.

**Required changes:**
1. Extend the LLM prompt to output `futures_exposure: ["ES", "CL"]` alongside ticker lists
2. Add `_FUTURES_PROXY_MAP` in `analyze_event.py` mapping keywords to root symbols
3. Add `asset_type` field to `market_tickers` JSON schema
4. Use continuous contract symbols (`CL=F`, `ES=F`) for price data
5. Future: Add roll-date awareness for backtest accuracy across contract expiry

---

### S-4. Database Migration Path: SQLite → PostgreSQL → TimescaleDB

**What breaks first at scale:**
1. Write contention at ~10 concurrent users (SQLite file lock)
2. Full table scans at ~5,000 events (no indexes beyond PK)
3. JSON deserialization overhead at ~1,000 events (Python-side `json.loads` per row)
4. Per-process cache isolation with multiple uvicorn workers

**Phase 1 (PostgreSQL):** Replace `sqlite3` with `asyncpg` connection pool. Convert JSON TEXT columns to native JSONB. Add indexes on `(headline, event_date)`, `timestamp DESC`, and GIN on `market_tickers`. Replace `PRAGMA user_version` with Alembic migrations.

**Phase 2 (TimescaleDB):** Add `ticker_prices` hypertable for persisted price data. Eliminates redundant API calls for historical data. Enables materialized continuous aggregates for precomputed 5d/20d returns.

---

### S-5. Order Flow Integration

**Attachment points in current codebase:**
- `compute_stress_regime()` already has a composite signal dict — add `order_flow_imbalance`
- `volume_ratio` in `_check_one_ticker()` is a flow proxy — replace with real bid/ask imbalance
- `_TICKER_CACHE` could store L2 snapshots with 5-10s TTL

**Architecture:** Order book feed (Polygon WS / IBKR) → `orderflow_worker.py` → Redis → FastAPI enrichment layer + frontend `OrderFlowPanel`.

---

### S-6. TF-IDF Cluster Threshold Calibration

**Current state:** The 0.20 cosine similarity threshold in `news_sources.py` was empirically tuned. The threshold is static regardless of corpus characteristics.

**Improvement:** Compute the mean + 2σ of pairwise cosine similarities across the current batch. Use this as a dynamic threshold floor. This adapts to batches where all headlines are on a single topic (e.g., earnings season) vs. diverse news cycles. The current 0.20 is appropriate for typical batches but may over-cluster during single-topic periods.

---

### S-7. Analog Matching — Semantic Embeddings

**Current state:** Jaccard on bag-of-words is fast but semantically blind. "OPEC agrees to production cut" vs. "Saudi Arabia reduces oil output" scores 0.0 despite being the same event.

**Improvement:** Replace Jaccard with a lightweight sentence embedding model (e.g., `all-MiniLM-L6-v2`, 80MB, 14ms/headline). Store embeddings alongside events in the DB. Use cosine similarity on embeddings for analog matching. Keep Jaccard as a fast pre-filter to avoid embedding computation on the full archive.

**Tradeoff:** Adds a ~100MB model dependency and ~50ms per analog search. Acceptable for analysis-time computation (not latency-critical).

---

## Lookahead Bias Verdict

**Primary event flow: NO lookahead bias.** The `_pct_forward()` function correctly anchors returns to the event-date close. The denominator is `series.iloc[0]` (first trading day on/after event date), and the numerator is `series.iloc[N]` (N trading days forward). Insufficient data returns `None`, never a fabricated value.

**Minor contamination:** `auto_adjust=True` in yfinance retroactively modifies historical closes for subsequent dividends/splits. A backtest run today sees different historical closes than were observable at event time. Magnitude: ~0.2-0.5% per quarter from dividends. Low severity for 5d/20d horizons but technically impure.

**Design choice to document:** The event-date close as return denominator means the event-day market reaction is excluded from the 5d window. The 5d return measures days 1-5 of post-event drift, not the initial shock. This is defensible but should be explicitly noted.

---

## Similarity Math Verdict

**Jaccard 0.15 analog threshold:** Mathematically sound for augmented word sets (headline + mechanism_summary). Random 5-word headlines have ~0.5% chance of exceeding 0.15. The mechanism augmentation adds 15-30 content words, making the denominator large enough that incidental overlap rarely crosses the threshold. However, short (3-4 word) headlines need the financial-domain stopword fix (H-4) and minimum shared-word guard (H-5) to prevent false positives.

**Jaccard 0.35 related-events threshold:** Strict but defensible. Same-event cross-source headlines may fall below 0.35 due to vocabulary variation, but the threshold prioritizes precision over recall.

**TF-IDF 0.20 cluster threshold:** Empirically calibrated and mathematically appropriate. One shared distinctive word between 5-word headlines produces cosine ~0.36 (above threshold). Common-only shared words produce ~0.06 (below). The threshold correctly separates topical from incidental overlap.

**Stage/persistence bonuses (+0.05/+0.03):** Applied AFTER the 0.15 threshold gate (line 406-407), NOT before. No risk of inflating sub-threshold matches into false positives. Bonuses affect ranking only. Magnitudes are uncalibrated but reasonable (~13-53% of the qualifying similarity range).

# market_check.py
# Runs a basic event-window validation on two lists of tickers:
# beneficiary_tickers and loser_tickers.
# Computes 1-day, 5-day, and 20-day returns plus a volume check.
# For sector tickers, computes return relative to a sector benchmark ETF.
# Evaluates whether each ticker moved in the direction the hypothesis predicts.
# This is a rough screen — not proof of anything.

import math as _math
import logging as _logging

_log = _logging.getLogger("second_order.market")

# Sector benchmark map: ticker → benchmark ETF for relative return comparison.
# Each sector has one benchmark ETF; tickers in the set get a vs_<benchmark>
# column so the analyst can see idiosyncratic vs sector-wide moves.
SECTOR_BENCHMARKS: dict[str, tuple[str, set[str]]] = {
    "energy": ("XLE", {
        "XLE", "XOM", "CVX", "COP", "SLB", "HAL", "MPC", "VLO",
        "USO", "UNG", "BNO", "OIH", "PSX", "PBF", "LNG", "FANG",
    }),
    "semiconductors": ("SMH", {
        "SMH", "SOXX", "TSM", "ASML", "NVDA", "AMD", "INTC", "AMAT",
        "LRCX", "KLAC", "MRVL", "AVGO", "QCOM", "TXN", "MU", "ON",
    }),
    "defense": ("XAR", {
        "XAR", "ITA", "LMT", "RTX", "NOC", "GD", "BA", "LHX",
        "HII", "TDG", "KTOS", "LDOS",
    }),
    "shipping": ("BDRY", {
        "BDRY", "FRO", "STNG", "EGLE", "SBLK", "GOGL", "ZIM",
        "DAC", "MATX", "KEX",
    }),
    "financials": ("XLF", {
        "XLF", "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW",
        "AXP", "BLK", "KRE", "KBE",
    }),
    "tech_software": ("XLK", {
        "XLK", "AAPL", "MSFT", "GOOG", "GOOGL", "META", "CRM", "ORCL",
        "ADBE", "NOW", "PANW", "CRWD",
    }),
    "healthcare": ("XLV", {
        "XLV", "JNJ", "PFE", "UNH", "MRK", "LLY", "ABBV", "TMO",
        "ABT", "BMY", "GILD", "CVS",
    }),
    "industrials": ("XLI", {
        "XLI", "CAT", "DE", "HON", "UNP", "GE", "EMR", "ETN",
        "MMM", "CSX", "NSC", "LUV",
    }),
    "materials": ("XLB", {
        "XLB", "FCX", "NEM", "NUE", "DOW", "LIN", "SHW", "APD",
        "GOLD", "X", "CLF", "AA",
    }),
    "consumer_disc": ("XLY", {
        "XLY", "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX",
        "TJX", "F", "GM",
    }),
    "consumer_staples": ("XLP", {
        "XLP", "PG", "KO", "PEP", "WMT", "COST", "MDLZ", "CL",
        "KMB", "GIS", "TGT",
    }),
    "utilities": ("XLU", {
        "XLU", "NEE", "DUK", "SO", "AEP", "SRE", "D", "EXC",
    }),
    "real_estate": ("XLRE", {
        "XLRE", "IYR", "VNQ", "PLD", "AMT", "EQIX", "PSA", "SPG",
    }),
    "communication": ("XLC", {
        "XLC", "NFLX", "DIS", "T", "VZ", "CMCSA", "TMUS", "CHTR",
    }),
}

# Flat lookup: ticker → (benchmark_etf, sector_name) for O(1) access.
_TICKER_TO_BENCHMARK: dict[str, tuple[str, str]] = {}
for _sect, (_bench, _members) in SECTOR_BENCHMARKS.items():
    for _t in _members:
        _TICKER_TO_BENCHMARK[_t] = (_bench, _sect)

# Default benchmark when a ticker has no sector assignment.  SPY is the
# universal fallback so EVERY validated ticker gets a relative-move read —
# the upgrade point of relative_move.py is that no ticker is judged solely
# on absolute returns.
_DEFAULT_BENCHMARK: str = "SPY"
_DEFAULT_SECTOR: str = "market"


def resolve_benchmark(ticker: str) -> tuple[str, str]:
    """Return (benchmark_etf, sector) for *ticker*.

    Falls back to SPY / "market" when the ticker is not in any sector bucket,
    so relative-move scoring applies to every validated symbol.
    """
    info = _TICKER_TO_BENCHMARK.get((ticker or "").upper())
    if info is not None:
        return info
    return (_DEFAULT_BENCHMARK, _DEFAULT_SECTOR)

# Backward compat: callers that imported ENERGY_PROXIES directly.
ENERGY_PROXIES = SECTOR_BENCHMARKS["energy"][1]


def _is_finite(v) -> bool:
    """Return True if *v* is a real finite number (rejects None, NaN, ±inf)."""
    try:
        return v is not None and _math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


import re as _re

_PROXY_SUFFIX_RE = _re.compile(r"\s*\(proxy\)\s*$", _re.IGNORECASE)


def _clean_fetch_symbol(raw: str) -> str:
    """Strip proxy-annotation suffixes before passing a symbol to any market-data provider.

    "(PROXY)" and "(proxy)" artifacts must never reach yfinance or any other
    provider — they produce silent no-data or misleading warnings.
    Returns the clean symbol (uppercased and stripped).  The caller is
    responsible for skipping the ticker when this returns an empty string.
    """
    return _PROXY_SUFFIX_RE.sub("", raw).strip()


# ---------------------------------------------------------------------------
# Unit-aware move computation
# ---------------------------------------------------------------------------
# Different market series require different math:
#   "price"  — ETFs, equities, commodities: (end - start) / start * 100  → %
#   "yield"  — ^TNX, ^FVX, ^TYX (CBOE yields already in %): end - start → pp
#   "level"  — ^VIX, index levels: (end - start) / start * 100           → %
#
# Mapping a ticker to the wrong unit type is the root cause of the
# recurring "+2680%" / "+3.45% for a 15 bps move" bug class.

UNIT_PRICE = "price"
UNIT_YIELD = "yield"
UNIT_LEVEL = "level"

_TICKER_UNIT: dict[str, str] = {
    # CBOE yield indices — values are already in percent (e.g. 4.35 = 4.35%)
    "^TNX":   UNIT_YIELD,   # 10-year nominal
    "^FVX":   UNIT_YIELD,   # 5-year nominal
    "^TYX":   UNIT_YIELD,   # 30-year nominal
    "^IRX":   UNIT_YIELD,   # 13-week T-bill
    # Volatility index — level, not yield
    "^VIX":   UNIT_LEVEL,
    "^VIX3M": UNIT_LEVEL,
}


def ticker_unit(ticker: str) -> str:
    """Return the unit type for a ticker symbol.

    Unknown tickers default to ``UNIT_PRICE`` (percent change), which is
    correct for the vast majority of instruments (ETFs, equities,
    commodities, forex).
    """
    return _TICKER_UNIT.get(ticker.upper(), UNIT_PRICE)


def compute_move(series, n: int, unit: str) -> float | None:
    """Compute the trailing *n*-period move in the correct unit.

    * ``UNIT_PRICE`` / ``UNIT_LEVEL``: ``(end − start) / start × 100``  → %
    * ``UNIT_YIELD``: ``end − start``  → absolute pp change

    Returns ``None`` when there is insufficient data or values are
    non-finite.
    """
    if series is None or len(series) < n + 1:
        return None
    end = float(series.iloc[-1])
    start = float(series.iloc[-(n + 1)])
    if not _is_finite(end) or not _is_finite(start):
        return None
    if unit == UNIT_YIELD:
        return float(end - start)
    # price / level: classical percent change
    if start == 0:
        return None
    return float((end - start) / start * 100)


def compute_move_forward(series, n: int, unit: str) -> float | None:
    """Like ``compute_move`` but from ``series[0]`` to ``series[n]``
    (event-date-anchored mode)."""
    if series is None or len(series) < n + 1:
        return None
    end = float(series.iloc[n])
    start = float(series.iloc[0])
    if not _is_finite(end) or not _is_finite(start):
        return None
    if unit == UNIT_YIELD:
        return float(end - start)
    if start == 0:
        return None
    return float((end - start) / start * 100)


def _pct(series, periods: int) -> float | None:
    """Percentage change over the last N periods (rolling / current-price mode).

    Returns None when there are insufficient rows or when the values
    involved are NaN / non-finite (e.g. from yfinance gaps).
    """
    if len(series) < periods + 1:
        return None
    end = float(series.iloc[-1])
    start = float(series.iloc[-(periods + 1)])
    if not _is_finite(end) or not _is_finite(start) or start == 0:
        return None
    return float((end - start) / start * 100)


def _pct_forward(series, periods: int) -> float | None:
    """Percentage change from series[0] to series[periods] (event-date-anchored mode).

    Returns None when there are insufficient rows or when the values
    involved are NaN / non-finite.
    """
    if len(series) < periods + 1:
        return None
    end = float(series.iloc[periods])
    start = float(series.iloc[0])
    if not _is_finite(end) or not _is_finite(start) or start == 0:
        return None
    return float((end - start) / start * 100)


import time as _time
import threading as _threading
from collections import OrderedDict as _OrderedDict
from concurrent.futures import ThreadPoolExecutor as _TPE

# Max parallel yfinance downloads. 6 keeps us under typical rate-limit
# thresholds while still being 5-6x faster than serial.
_MAX_FETCH_WORKERS = 6

# When this fraction (or more) of tickers return no price data,
# the market block is flagged as "degraded" so the UI / memo can
# warn that market validation is incomplete.
_DATA_QUALITY_DEGRADED_THRESHOLD: float = 0.5

# Every ticker sparkline is padded or trimmed to this length so
# side-by-side comparisons use the same time scale.  20 bars ≈ one
# trading month — matches the window in _check_one_ticker.
SPARK_LENGTH: int = 20


def normalize_spark(spark: list, *, length: int = SPARK_LENGTH) -> list:
    """Pad or trim a spark array to exactly ``length`` entries.

    * Short arrays are **left-padded** with the first value (or 0.0 if
      empty) so the most-recent bars stay right-aligned.
    * Long arrays are trimmed from the left (oldest bars dropped).
    * Exact-length arrays pass through unchanged.
    """
    if not spark:
        return [0.0] * length
    if len(spark) >= length:
        return list(spark[-length:])
    pad_val = spark[0]
    return [pad_val] * (length - len(spark)) + list(spark)


def derive_data_quality(tickers: list) -> dict:
    """Compute data_quality / data_quality_note from a tickers list.

    Returns a dict with at least ``"data_quality"`` (``"ok"`` | ``"degraded"``).
    ``"data_quality_note"`` is only present when quality is degraded.
    Called by market_check() and re-used by market_check_freshness so
    cached response paths carry the same signal as fresh ones.
    """
    n_total = len(tickers)
    if n_total == 0:
        return {"data_quality": "ok"}
    n_missing = sum(
        1 for t in tickers
        if t.get("return_5d") is None and t.get("return_1d") is None
    )
    ratio = n_missing / n_total
    if ratio >= _DATA_QUALITY_DEGRADED_THRESHOLD:
        return {
            "data_quality": "degraded",
            "data_quality_note": (
                f"{n_missing}/{n_total} tickers returned no price data — "
                "market validation is incomplete"
            ),
        }
    return {"data_quality": "ok"}

# A ticker whose latest bar is older than this many calendar days is
# flagged as stale (likely delisted, halted, or data-gap).  5 calendar
# days ≈ 3 trading days — generous enough to tolerate long weekends
# and holidays without false-positiving on healthy tickers.
_STALE_TICKER_CALENDAR_DAYS: int = 5

# ---------------------------------------------------------------------------
# Thread-safe, bounded TTL cache for ticker data
# ---------------------------------------------------------------------------
# Avoids redundant yfinance downloads within the same analysis session.
# Keyed by (ticker, mode, start_date). Short TTL: 10 minutes.
#
# Bounded to 512 entries — empirically calibrated against 54 live events:
#   89 unique symbols (rolling) + 231 worst-case since-mode keys = 320.
#   512 gives generous headroom without risking unbounded memory growth.
#
# Thread-safe via a lock that protects all reads and writes.  This is safe
# under both CPython (GIL) and free-threaded Python 3.13+.

_TICKER_CACHE_TTL = 600       # 10 minutes
_TICKER_CACHE_MAXSIZE = 512   # max entries before LRU eviction

_cache_lock = _threading.Lock()
_cache_data: _OrderedDict[str, tuple[float, object]] = _OrderedDict()


def _cache_get(key: str):
    """Return cached value or None if missing/expired.  Thread-safe."""
    with _cache_lock:
        entry = _cache_data.get(key)
        if entry is None:
            return None
        ts, val = entry
        if (_time.monotonic() - ts) > _TICKER_CACHE_TTL:
            _cache_data.pop(key, None)
            return None
        # Move to end (most recently used)
        _cache_data.move_to_end(key)
        return val


def _cache_set(key: str, val: object) -> None:
    """Store a value in the cache, evicting the oldest entry if full.  Thread-safe."""
    now = _time.monotonic()
    with _cache_lock:
        if key in _cache_data:
            _cache_data.move_to_end(key)
        _cache_data[key] = (now, val)
        # Evict oldest entries if over capacity
        while len(_cache_data) > _TICKER_CACHE_MAXSIZE:
            _cache_data.popitem(last=False)


def _cache_clear() -> None:
    """Clear the entire cache.  Exposed for testing."""
    with _cache_lock:
        _cache_data.clear()


def _cache_len() -> int:
    """Return the number of entries in the cache.  Exposed for testing."""
    with _cache_lock:
        return len(_cache_data)


from datetime import date as _date_type, timedelta as _timedelta

# ---------------------------------------------------------------------------
# US market holidays — NYSE/NASDAQ observed closure calendar.
#
# Covers the fixed-date and rule-based holidays through 2030.  Each
# entry is the *observed* closure date (if the holiday falls on a
# Saturday/Sunday, the market observes Friday/Monday).
#
# Source: NYSE Rule 7.2.  Updated when the exchange publishes a year's
# calendar.  A missing year degrades to weekday-only clamping — safe
# but won't skip holidays for that year.
# ---------------------------------------------------------------------------

_US_MARKET_HOLIDAYS: frozenset[_date_type] = frozenset({
    # 2025
    _date_type(2025, 1, 1),    # New Year's Day
    _date_type(2025, 1, 20),   # MLK Day
    _date_type(2025, 2, 17),   # Presidents' Day
    _date_type(2025, 4, 18),   # Good Friday
    _date_type(2025, 5, 26),   # Memorial Day
    _date_type(2025, 6, 19),   # Juneteenth
    _date_type(2025, 7, 4),    # Independence Day
    _date_type(2025, 9, 1),    # Labor Day
    _date_type(2025, 11, 27),  # Thanksgiving
    _date_type(2025, 12, 25),  # Christmas
    # 2026
    _date_type(2026, 1, 1),    # New Year's Day
    _date_type(2026, 1, 19),   # MLK Day
    _date_type(2026, 2, 16),   # Presidents' Day
    _date_type(2026, 4, 3),    # Good Friday
    _date_type(2026, 5, 25),   # Memorial Day
    _date_type(2026, 6, 19),   # Juneteenth
    _date_type(2026, 7, 3),    # Independence Day (obs. Fri)
    _date_type(2026, 9, 7),    # Labor Day
    _date_type(2026, 11, 26),  # Thanksgiving
    _date_type(2026, 12, 25),  # Christmas
    # 2027
    _date_type(2027, 1, 1),    # New Year's Day
    _date_type(2027, 1, 18),   # MLK Day
    _date_type(2027, 2, 15),   # Presidents' Day
    _date_type(2027, 3, 26),   # Good Friday
    _date_type(2027, 5, 31),   # Memorial Day
    _date_type(2027, 6, 18),   # Juneteenth (obs. Fri)
    _date_type(2027, 7, 5),    # Independence Day (obs. Mon)
    _date_type(2027, 9, 6),    # Labor Day
    _date_type(2027, 11, 25),  # Thanksgiving
    _date_type(2027, 12, 24),  # Christmas (obs. Fri)
    # 2028
    _date_type(2028, 1, 17),   # MLK Day
    _date_type(2028, 2, 21),   # Presidents' Day
    _date_type(2028, 4, 14),   # Good Friday
    _date_type(2028, 5, 29),   # Memorial Day
    _date_type(2028, 6, 19),   # Juneteenth
    _date_type(2028, 7, 4),    # Independence Day
    _date_type(2028, 9, 4),    # Labor Day
    _date_type(2028, 11, 23),  # Thanksgiving
    _date_type(2028, 12, 25),  # Christmas
})


def is_market_holiday(d: _date_type) -> bool:
    """Return True if ``d`` is a known US market holiday."""
    return d in _US_MARKET_HOLIDAYS


def _clamp_to_market_date(date_str: str) -> str:
    """Clamp a date string to the nearest plausible US market trading date.

    - Future dates → today (then holiday-adjusted if needed).
    - Weekend dates → preceding Friday.
    - Holiday dates → next trading day (forward-roll).
    - Returns a YYYY-MM-DD string that is always <= today and a real
      trading day (weekday, not a known US market holiday).
    """
    try:
        d = _date_type.fromisoformat(date_str)
    except (ValueError, TypeError):
        d = _date_type.today()

    today = _date_type.today()
    if d > today:
        d = today

    # Roll back to Friday if Saturday (5) or Sunday (6)
    wd = d.weekday()
    if wd == 5:
        d = d - _timedelta(days=1)
    elif wd == 6:
        d = d - _timedelta(days=2)

    # Roll forward over holidays to the next real trading session.
    # Bounded to 10 iterations to avoid infinite loops on calendar
    # gaps (consecutive holidays + weekends never exceed ~4 days).
    for _ in range(10):
        if not is_market_holiday(d):
            break
        d = d + _timedelta(days=1)
        # Skip weekends that follow the holiday
        wd = d.weekday()
        if wd == 5:
            d = d + _timedelta(days=2)
        elif wd == 6:
            d = d + _timedelta(days=1)

    # Final guard: don't roll past today
    if d > today:
        d = today

    return d.isoformat()


def _fetch(ticker: str):
    """Download ~3 months of daily data for one ticker. Returns a DataFrame or None.

    Routed through the SQLite price cache, which only hits the provider for
    date ranges that aren't already persisted locally.  The in-memory TTL
    cache above remains the hot per-session layer.
    """
    key = f"fetch:{ticker.upper()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    from price_cache import fetch_daily_cached
    data = fetch_daily_cached(ticker, period="3mo", auto_adjust=True)
    if data is None:
        return None
    _cache_set(key, data)
    return data


def _fetch_since(ticker: str, start_date: str):
    """Download daily data from start_date to today. Returns a DataFrame or None.

    The start_date is clamped to the latest valid market date so future or
    weekend dates don't produce inverted ranges or empty results.

    Uses auto_adjust=False to avoid retroactive price adjustments from
    future dividends/splits.  This eliminates lookahead bias when computing
    forward returns for backtests and follow-through checks.  Raw 'Close'
    values are what a trader would have observed on each historical date.

    Routed through the SQLite price cache.  Raw closes never change once
    fetched, so backtest flows become essentially free after the first run.
    """
    clamped = _clamp_to_market_date(start_date)
    key = f"since:{ticker.upper()}:{clamped}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    from price_cache import fetch_daily_cached
    data = fetch_daily_cached(ticker, start=clamped, auto_adjust=False)
    if data is None:
        return None
    _cache_set(key, data)
    return data


# ---------------------------------------------------------------------------
# Sanity bounds for return values
# ---------------------------------------------------------------------------
#
# Returns above these absolute magnitudes are essentially impossible
# for any liquid equity / ETF / liquid future, and indicate corrupted
# source data — yfinance race conditions, stub bars in the price
# cache (e.g. close values 0.0, 1.0, 2.0, ...), unadjusted splits,
# etc.  When a return exceeds the bound the compute layer drops it
# to None instead of propagating a value like +1348.50% into the
# persisted ``market_tickers`` payload and the UI.
#
# Numbers chosen to be conservative — they catch obviously-broken
# fetches (the 1348% XLE bug, +624% one-day moves) without
# false-positiving on plausible high-volatility moves (VIX +80% in a
# day during a crash, single-name penny-stock spikes).

_RETURN_SANITY_R1_PCT:  float = 100.0   # 1d move ceiling
_RETURN_SANITY_R5_PCT:  float = 200.0   # 5d move ceiling
_RETURN_SANITY_R20_PCT: float = 500.0   # 20d move ceiling


def _sanitize_returns(
    r1: float | None,
    r5: float | None,
    r20: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Drop implausibly large absolute return values to None.

    Three independent caps so a corrupt single-bar fetch can blow
    out r1 / r5 without nuking a still-valid r20 (or vice versa).
    Pure function — no side effects, fully unit-testable.
    """
    if r1 is not None and abs(r1) > _RETURN_SANITY_R1_PCT:
        r1 = None
    if r5 is not None and abs(r5) > _RETURN_SANITY_R5_PCT:
        r5 = None
    if r20 is not None and abs(r20) > _RETURN_SANITY_R20_PCT:
        r20 = None
    return r1, r5, r20


def _scrub_implausible_ticker_returns(tickers: list[dict]) -> list[dict]:
    """Apply sanity bounds to a list of persisted ticker dicts.

    Catches the case where corrupted persisted ``market_tickers`` JSON
    rows (saved before this layer existed) carry absurd return values
    like the +1348.50% XLE bug.  When a 5d return is dropped, the
    derived ``direction_tag`` is also cleared because it was computed
    from the now-suspect number.

    Returns a fresh list of fresh dicts; never mutates input.
    """
    out: list[dict] = []
    for t in tickers:
        scrubbed = dict(t)
        r1 = scrubbed.get("return_1d")
        r5 = scrubbed.get("return_5d")
        r20 = scrubbed.get("return_20d")
        r1_s, r5_s, r20_s = _sanitize_returns(r1, r5, r20)
        scrubbed["return_1d"] = r1_s
        scrubbed["return_5d"] = r5_s
        scrubbed["return_20d"] = r20_s
        # If r5 was scrubbed away, the direction_tag derived from it
        # (via _direction_tag) is now stale and should not lead the UI.
        if r5_s is None and r5 is not None:
            scrubbed["direction_tag"] = None
        out.append(scrubbed)
    return out


# ---------------------------------------------------------------------------
# Dual-source verification
# ---------------------------------------------------------------------------
#
# When the primary provider reports a suspicious move, optionally fetch the
# same ticker from a secondary provider and compare.  The primary is always
# the source of record — the secondary only flags disagreement.

_VERIFY_MOVE_THRESHOLD: float = 5.0    # |r5| >= this triggers verification
_VERIFY_DELTA_PCT:      float = 3.0    # |primary - secondary| > this = disputed
_VERIFY_LOW_VOL:        float = 0.1    # vol_ratio < this = suspicious
_VERIFY_TIMEOUT:        float = 8.0    # seconds before giving up on the secondary fetch


def _should_verify(r5: float | None, r5_pre_sanitize: float | None,
                   vol_ratio: float | None) -> bool:
    """Return True if the ticker's returns warrant a secondary-source check."""
    # Scrubbed by sanitize_returns — was implausible
    if r5 != r5_pre_sanitize:
        return True
    if r5 is not None and abs(r5) >= _VERIFY_MOVE_THRESHOLD:
        return True
    if vol_ratio is not None and _is_finite(vol_ratio) and vol_ratio < _VERIFY_LOW_VOL:
        return True
    return False


def _verify_ticker_return_impl(
    ticker: str,
    r5_primary: float | None,
    event_date: str | None = None,
) -> dict:
    """Inner body of dual-source verification — no timeout guard.

    Returns a verdict dict with:
      status: "confirmed" | "disputed" | "unavailable"
      secondary_r5, delta, provider
    """
    unavailable = {
        "status": "unavailable", "secondary_r5": None,
        "delta": None, "provider": None,
    }
    # Clean the symbol before hitting the secondary provider.  Callers may
    # pass raw ticker strings that carry "(proxy)" annotations or other
    # decorations — the primary fetch path strips those via
    # _clean_fetch_symbol, so the secondary path must do the same or a
    # verification round will fail on symbol syntax instead of real data.
    fetch_symbol = _clean_fetch_symbol(ticker)
    if not fetch_symbol:
        return unavailable

    try:
        from market_data import get_secondary_provider
        secondary = get_secondary_provider()
    except Exception:
        return unavailable
    if secondary is None:
        return unavailable

    provider_name = type(secondary).__name__.replace("Provider", "").lower()

    try:
        if event_date:
            clamped = _clamp_to_market_date(event_date)
            data = secondary.fetch_daily(fetch_symbol, start=clamped, auto_adjust=False)
            pct_fn = _pct_forward
        else:
            data = secondary.fetch_daily(fetch_symbol, period="3mo", auto_adjust=True)
            pct_fn = _pct
    except Exception:
        _log.warning("_verify_ticker_return_impl(%s): secondary fetch failed", ticker, exc_info=True)
        return unavailable

    if data is None or len(data) < 6:
        return unavailable

    closes = data["Close"] if "Close" in data.columns else None
    if closes is None:
        return unavailable

    secondary_r5 = pct_fn(closes, 5)
    if secondary_r5 is None:
        return unavailable

    secondary_r5 = round(secondary_r5, 2)
    if r5_primary is None:
        return {
            "status": "unavailable", "secondary_r5": secondary_r5,
            "delta": None, "provider": provider_name,
        }

    delta = round(r5_primary - secondary_r5, 2)
    status = "disputed" if abs(delta) > _VERIFY_DELTA_PCT else "confirmed"
    return {
        "status": status,
        "secondary_r5": secondary_r5,
        "delta": delta,
        "provider": provider_name,
    }


def _verify_ticker_return(
    ticker: str,
    r5_primary: float | None,
    event_date: str | None = None,
) -> dict:
    """Fetch the same ticker from the secondary provider and compare r5.

    Wraps ``_verify_ticker_return_impl`` with a ``_VERIFY_TIMEOUT``-second
    wall-clock deadline.  If the secondary fetch does not complete in time
    the function returns ``status="timed_out"`` instead of blocking the
    caller indefinitely.

    Returns a verdict dict with:
      status: "confirmed" | "disputed" | "unavailable" | "timed_out"
      secondary_r5, delta, provider
    """
    # Without an event anchor both sources compare against different rolling
    # windows (primary may be hours-old cache, secondary always fetches live).
    # The resulting delta is driven by cache staleness, not data quality — do
    # not produce a "disputed" verdict in this case.
    if event_date is None:
        return {"status": "unverified", "secondary_r5": None,
                "delta": None, "provider": None}
    timed_out_result = {
        "status": "timed_out", "secondary_r5": None,
        "delta": None, "provider": None,
    }
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _FuturesTimeout
        with ThreadPoolExecutor(max_workers=1) as _pool:
            _fut = _pool.submit(_verify_ticker_return_impl, ticker, r5_primary, event_date)
            try:
                return _fut.result(timeout=_VERIFY_TIMEOUT)
            except _FuturesTimeout:
                _log.warning(
                    "_verify_ticker_return(%s): secondary check timed out after %.1fs",
                    ticker, _VERIFY_TIMEOUT,
                )
                return timed_out_result
    except Exception:
        _log.warning("_verify_ticker_return(%s): unexpected error", ticker, exc_info=True)
        return {"status": "unavailable", "secondary_r5": None, "delta": None, "provider": None}


# ---------------------------------------------------------------------------
# Defensive validation: per-ticker independence
# ---------------------------------------------------------------------------
#
# Two distinct symbols should never produce byte-identical (return_5d,
# spark) pairs.  When that happens it is a high-confidence corruption
# signature from the upstream fetch layer (yfinance race conditions,
# cross-contaminated price-cache rows, shared DataFrame references,
# etc.).  We surface this as "needs more evidence" pending entries
# instead of misleading the UI with shared values across distinct
# cards.  See ``_suppress_duplicate_tickers`` below.

def _ticker_signature(t: dict) -> tuple | None:
    """Return a (return_5d, spark-tuple) signature for a ticker, or
    None if there is not enough numeric data to compare."""
    r5 = t.get("return_5d")
    spark = t.get("spark") or []
    if r5 is None or not spark:
        return None
    try:
        r5_q = round(float(r5), 4)
        spark_q = tuple(round(float(x), 4) for x in spark)
    except (TypeError, ValueError):
        return None
    return (r5_q, spark_q)


def _make_pending_ticker(t: dict) -> dict:
    """Return a fresh pending placeholder dict that preserves the
    symbol/role of the input but clears all numeric / series fields."""
    return {
        "symbol":       t.get("symbol", "?"),
        "role":         t.get("role", "beneficiary"),
        "label":        "needs more evidence",
        "direction_tag": None,
        "return_1d":    None,
        "return_5d":    None,
        "return_20d":   None,
        "volume_ratio": None,
        "vs_xle_5d":    None,
        "spark":        [],
    }


def _suppress_duplicate_tickers(tickers: list[dict]) -> list[dict]:
    """Replace cross-contaminated ticker dicts with pending placeholders.

    Walks ``tickers`` and groups entries by their (return_5d, spark)
    signature.  Any signature that appears across two or more distinct
    symbols is treated as corruption — the upstream fetch layer leaked
    one ticker's data into another's slot — and EVERY entry in that
    group is rewritten to a pending placeholder so the UI displays
    "needs more evidence" instead of repeating the same numbers.

    The chance of two distinct, real symbols producing pixel-identical
    20-bar normalized sparks AND identical 5d returns is effectively
    zero.  Suppressing the entire colliding group (rather than keeping
    one "winner") is intentional: when the data is corrupt, we don't
    know which slot — if any — actually belongs to the right symbol.

    Always returns a fresh list of fresh dicts, with fresh ``spark``
    lists for the entries that pass through unchanged.
    """
    if len(tickers) < 2:
        # Still return a fresh-copy list so callers can mutate freely.
        # Preserve the spark exactly as-is (fresh copy only) — normalization
        # happens upstream in _check_one_ticker; pending tickers keep [].
        out: list[dict] = []
        for t in tickers:
            s = t.get("spark") or []
            out.append({**t, "spark": list(s) if s else []})
        return out
    by_signature: dict[tuple, list[int]] = {}
    for i, t in enumerate(tickers):
        sig = _ticker_signature(t)
        if sig is None:
            continue
        by_signature.setdefault(sig, []).append(i)
    duplicates: set[int] = set()
    for sig, indices in by_signature.items():
        if len(indices) >= 2:
            # Collision across distinct symbols only counts as corruption.
            symbols = {tickers[i].get("symbol") for i in indices}
            if len(symbols) >= 2:
                duplicates.update(indices)
    out: list[dict] = []
    for i, t in enumerate(tickers):
        if i in duplicates:
            out.append(_make_pending_ticker(t))
        else:
            # Fresh copy — no shared references.  Normalization happened
            # upstream; preserve the spark as-is.  Pending tickers keep [].
            _s = t.get("spark") or []
            out.append({**t, "spark": list(_s) if _s else []})
    return out


def _direction_tag(r5: float | None, role: str) -> str | None:
    """Return a direction tag based on 5-day return and the ticker's predicted role.

    Logic:
      beneficiary + up   → hypothesis says this should rise  → supports ↑
      beneficiary + down → moves against the prediction       → contradicts ↓
      loser       + down → hypothesis says this should fall   → supports ↓
      loser       + up   → moves against the prediction       → contradicts ↑

    Returns None when r5 is unavailable, NaN, or non-finite.
    """
    if not _is_finite(r5):
        return None
    # Flat zone: returns within ±0.5% are inconclusive, not directional.
    if abs(r5) < 0.5:
        return None
    if role == "beneficiary":
        return "supports ↑" if r5 > 0 else "contradicts ↓"
    else:  # loser
        return "supports ↓" if r5 < 0 else "contradicts ↑"


def _check_one_ticker(
    ticker: str,
    role: str = "beneficiary",
    xle_data=None,
    event_date: str | None = None,
    benchmark_cache: dict | None = None,
    persistence: str | None = None,
    stage: str | None = None,
) -> dict:
    """Compute return windows, volume check, direction tag, and optional relative return.

    role: "beneficiary" or "loser" — used to decide if a move supports the hypothesis.
    event_date: optional 'YYYY-MM-DD' string. When provided, data is fetched from that
      date forward and returns are anchored to the event-date close (iloc[0]).
      When omitted, the existing rolling 3-month / current-price behaviour is used.

    Returns a dict with:
      label, detail, direction  — for human-readable output (unchanged)
      return_1d, return_5d, return_20d, volume_ratio, vs_xle_5d  — structured numbers
    All numeric fields are None when data is unavailable.
    """
    # Shared None-filled fallback for error / no-data paths
    _no_data: dict = {
        "label": "needs more evidence",
        "detail": "Not enough price data.",
        "direction": None,
        "return_1d": None,
        "return_5d": None,
        "return_20d": None,
        "volume_ratio": None,
        "vs_xle_5d": None,
        "spark": [],
    }

    try:
        # Strip any "(proxy)" annotation before hitting the provider.
        fetch_symbol = _clean_fetch_symbol(ticker)
        if not fetch_symbol:
            return dict(_no_data)

        # Choose fetch strategy and matching return function based on event_date.
        if event_date:
            data   = _fetch_since(fetch_symbol, event_date)
            pct_fn = _pct_forward   # returns from iloc[0] (event close) forward
        else:
            data   = _fetch(fetch_symbol)
            pct_fn = _pct           # returns from iloc[-(n+1)] to iloc[-1]

        # Same-day fallback: when event_date IS the latest available trading
        # bar, ``_fetch_since`` returns exactly one row and there is no
        # forward bar yet to compute return_1d against.  Fall back to a
        # rolling fetch so return_1d still reflects the same-day reaction
        # (event-day close vs prior-session close).  Without this fallback
        # /movers/today stays empty for any event whose ticker validation
        # runs before the next session — its today-window surface gates on
        # return_1d when return_5d hasn't matured yet.  return_5d / return_20d
        # stay None in this branch because rolling _pct over those windows
        # would be backward-looking pre-event noise, not a post-event read.
        same_day_fallback = False
        if event_date and (data is None or len(data) < 2):
            data = _fetch(fetch_symbol)
            pct_fn = _pct
            same_day_fallback = True

        # Need at least 2 rows to compute any return (event close + 1 forward
        # bar).  ``_pct``/``_pct_forward`` already return None when their own
        # window doesn't have enough data, so we don't need a 6-row gate to
        # protect downstream — the gate was zeroing out return_1d for every
        # event younger than 6 trading bars and that's why /movers/today
        # stayed empty even after tickers were populated.
        if data is None or len(data) < 2:
            return dict(_no_data)

        # Surface the actual anchor bar when in event-date mode.  In the
        # normal forward-anchored path that's iloc[0] (the event-day close);
        # in the same-day fallback the anchor is iloc[-1] (latest available
        # bar, which is the event-day close itself).
        anchor_date = None
        if event_date:
            anchor_date = str(
                data.index[-1].date() if same_day_fallback
                else data.index[0].date()
            )

        # --- Staleness: detect delisted / halted tickers ---
        last_bar_date = data.index[-1].date() if hasattr(data.index[-1], 'date') else None
        stale = False
        last_trade_date = str(last_bar_date) if last_bar_date else None
        if last_bar_date is not None:
            age_days = (_date_type.today() - last_bar_date).days
            stale = age_days > _STALE_TICKER_CALENDAR_DAYS

        closes  = data["Close"]
        volumes = data["Volume"]

        # --- Return windows ---
        # In the same-day fallback path the data is rolling 3-month closes
        # ending at today's bar, so r5/r20 from rolling _pct would be
        # backward-looking pre-event windows — not the post-event reaction
        # the rest of the system expects.  Compute r1 only there; r5/r20
        # naturally populate on the next backfill once forward bars exist.
        r1  = pct_fn(closes, 1)
        r5  = None if same_day_fallback else pct_fn(closes, 5)
        r20 = None if same_day_fallback else pct_fn(closes, 20)

        # Sanity bounds — drop implausibly large returns produced by
        # corrupt source bars (yfinance race, stub price_cache rows
        # like 0.0/1.0/2.0, unadjusted splits).  See
        # ``_RETURN_SANITY_*`` constants at the top of this module.
        r5_pre = r5  # remember pre-sanitize for verification trigger
        r1, r5, r20 = _sanitize_returns(r1, r5, r20)

        # --- Volume: latest day vs 20-day average ---
        latest_vol = float(volumes.iloc[-1])
        avg_vol    = float(volumes.iloc[-20:].mean()) if len(volumes) >= 20 else float(volumes.mean())
        if not _is_finite(latest_vol):
            latest_vol = 0.0
        if not _is_finite(avg_vol) or avg_vol == 0:
            avg_vol = 0.0
        vol_ratio  = latest_vol / avg_vol if avg_vol > 0 else 1.0
        high_volume = vol_ratio >= 1.25   # 25% above average = noteworthy

        # --- Dual-source verification (optional) ---
        if _should_verify(r5, r5_pre, vol_ratio):
            verification = _verify_ticker_return(ticker, r5, event_date=event_date)
        else:
            verification = {"status": "unverified", "secondary_r5": None,
                            "delta": None, "provider": None}

        # --- Relative return vs benchmark (sector ETF or SPY fallback) ---
        # Every ticker now gets a benchmark-aware read — SPY is the universal
        # fallback so thesis validation is never judged on absolute returns
        # alone.  rel_vs_xle is the legacy 5d-only field; relative_move_block
        # carries the richer 1d / 5d / 20d + validation_quality read consumed
        # by the frontend and reaction-function layer.
        t_upper = ticker.upper()
        bench_etf, bench_sector = resolve_benchmark(t_upper)
        rel_vs_xle = None   # legacy field kept for API compat
        bench_r1: float | None = None
        bench_r5: float | None = None
        bench_r20: float | None = None
        bench_data = None
        if t_upper != bench_etf:
            # Prefer xle_data for XLE (legacy warm-cache path); otherwise go
            # through the benchmark_cache populated in market_check().
            if bench_etf == "XLE" and xle_data is not None:
                bench_data = xle_data
            elif benchmark_cache and bench_etf in benchmark_cache:
                bench_data = benchmark_cache[bench_etf]
        if bench_data is not None:
            bench_closes = bench_data["Close"]
            bench_r1  = pct_fn(bench_closes, 1)
            bench_r5  = pct_fn(bench_closes, 5)
            bench_r20 = pct_fn(bench_closes, 20)
            if r5 is not None and bench_r5 is not None:
                rel_vs_xle = r5 - bench_r5

        # --- Label: based on 5-day move and volume ---
        # 5-day is the primary window — captures event reaction without daily noise.
        big_5d_move = r5 is not None and abs(r5) >= 2.0   # ≥ 2% in 5 days

        if big_5d_move and high_volume:
            label = "notable move"
        elif big_5d_move or high_volume:
            label = "in motion"
        elif r5 is not None and abs(r5) < 0.5:
            label = "flat"
        else:
            label = "needs more evidence"

        # --- Direction: did the ticker move in the predicted direction? ---
        direction = _direction_tag(r5, role)

        # --- Degrade on suspicious-move verification failure ---
        # A "disputed" result means primary and secondary sources disagree by
        # more than _VERIFY_DELTA_PCT — the move cannot be treated as
        # confirming/contradicting evidence.  A "timed_out" result means the
        # secondary check did not complete within _VERIFY_TIMEOUT seconds and
        # we have no second opinion.  In both cases clear direction_tag (do
        # not use as a validation signal) and mark the label as disputed when
        # the label would otherwise overstate confidence.
        v_status = verification.get("status")
        if v_status in ("disputed", "timed_out"):
            direction = None
            if v_status == "disputed" and label not in ("needs more evidence", "flat"):
                label = label + " (disputed)"

        # --- Build readable detail string ---
        parts = []
        if r1  is not None: parts.append(f"1d: {r1:+.1f}%")
        if r5  is not None: parts.append(f"5d: {r5:+.1f}%")
        if r20 is not None: parts.append(f"20d: {r20:+.1f}%")
        parts.append(f"vol {vol_ratio:.1f}x avg")
        if rel_vs_xle is not None:
            parts.append(f"vs XLE 5d: {rel_vs_xle:+.1f}%")

        # --- Sparkline: last 20 closes normalised to 0-1 ---
        spark_window = closes.iloc[-20:] if len(closes) >= 20 else closes
        lo = float(spark_window.min())
        hi = float(spark_window.max())
        if hi - lo > 1e-9:
            spark = [round((float(c) - lo) / (hi - lo), 3) for c in spark_window]
        else:
            spark = [0.5] * len(spark_window)
        spark = normalize_spark(spark)

        # --- Relative-move validation (alpha vs beta vs drift) ---
        # The composer runs even when the benchmark is unavailable so the
        # downstream shape is stable; it just returns ``validation_quality =
        # unavailable`` in that case.  Distinguishes "supported by alpha"
        # from "moved with the tape" so thesis validation is no longer
        # credited to market-wide drift.
        from relative_move import classify_relative_move
        rel_block = classify_relative_move(
            ticker_returns={
                "return_1d": r1, "return_5d": r5, "return_20d": r20,
            },
            benchmark_returns={
                "return_1d": bench_r1,
                "return_5d": bench_r5,
                "return_20d": bench_r20,
            },
            role=role,
            benchmark_symbol=bench_etf,
        )

        result = {
            "label": label,
            "detail": "  |  ".join(parts),
            "direction": direction,
            # Structured numeric fields — rounded to 2 dp for clean JSON storage
            "return_1d":    round(r1,         2) if r1         is not None else None,
            "return_5d":    round(r5,         2) if r5         is not None else None,
            "return_20d":   round(r20,        2) if r20        is not None else None,
            "volume_ratio": round(vol_ratio,  2),
            "vs_xle_5d":    round(rel_vs_xle, 2) if rel_vs_xle is not None else None,
            "anchor_date":  anchor_date,
            "spark":        spark,
            "verification": verification,
            # Relative-move block — benchmark-aware validation carrying the
            # alpha / beta / drift separation described in relative_move.py.
            "benchmark_symbol":         rel_block["benchmark_symbol"],
            "benchmark_sector":         bench_sector,
            "benchmark_return_5d":      rel_block["benchmark_return_5d"],
            "relative_return_1d":       rel_block["relative_return_1d"],
            "relative_return_5d":       rel_block["relative_return_5d"],
            "relative_return_20d":      rel_block["relative_return_20d"],
            "validation_quality":       rel_block["validation_quality"],
            "validation_quality_label": rel_block["validation_quality_label"],
            "thesis_support":           rel_block["thesis_support"],
            "validation_rationale":     rel_block["rationale"],
        }
        # Weighted-evidence read — replaces the flat latest-day label
        # logic.  Pure composer against the record we just assembled;
        # additive so all existing keys stay intact.
        try:
            from validation_evidence import classify_validation_evidence
            evidence = classify_validation_evidence(
                {**result, "role": role},
                persistence=persistence,
                stage=stage,
            )
            result.update(evidence)
        except Exception as _ve_exc:
            _log.warning(
                "validation_evidence failed for %s: %s", ticker, _ve_exc,
            )
        if stale:
            result["stale"] = True
            result["last_trade_date"] = last_trade_date
        return result

    except Exception as e:
        _log.warning("_check_one_ticker(%s) failed: %s", ticker, e, exc_info=True)
        no_data_error = dict(_no_data)
        no_data_error["detail"] = f"Error: {e}"
        return no_data_error


def compute_pre_event_drift(
    symbols: list[str],
    event_date: str | None = None,
) -> dict[str, float]:
    """Return {symbol_upper: pre_event_5d_drift_pct} for each symbol.

    "Pre-event drift" is the 5-trading-day return ENDING at ``event_date``
    (or today if no date is supplied) — i.e. how much price moved in the
    days leading UP TO the headline.  A large positive drift in the
    thesis direction means markets started pricing the event before it
    was announced; a near-zero drift means the headline ran into a flat
    tape; a negative drift means markets were positioned the other way.

    Pure lookup over the existing price cache — no new provider calls
    beyond what market_check would already do.  Symbols that fail the
    fetch or lack enough history return nothing (missing from the dict).
    Capped to ±_RETURN_SANITY_R5_PCT to drop corrupt bars.
    """
    out: dict[str, float] = {}
    if not symbols:
        return out

    for sym in symbols:
        if not sym or not isinstance(sym, str):
            continue
        clean = _clean_fetch_symbol(sym)
        if not clean:
            continue
        try:
            data = _fetch(clean)
        except Exception:
            _log.warning("compute_pre_event_drift: fetch %s failed", clean, exc_info=True)
            continue
        if data is None or len(data) < 6:
            continue

        closes = data["Close"]
        # When event_date is provided, slice the series so we compute the 5d
        # return ending at (or before) event_date — this supports backtest
        # / past-event analyses without leaking post-event information.
        if event_date:
            try:
                import pandas as _pd
                cutoff = _pd.Timestamp(event_date)
                closes = closes[closes.index <= cutoff]
            except Exception:
                pass
        if len(closes) < 6:
            continue

        drift = _pct(closes, 5)
        if drift is None:
            continue
        if abs(drift) > _RETURN_SANITY_R5_PCT:
            continue
        out[sym.upper()] = round(drift, 2)

    return out


def market_check(
    beneficiary_tickers: list[str],
    loser_tickers: list[str],
    event_date: str | None = None,
    persistence: str | None = None,
    stage: str | None = None,
) -> dict:
    """Run event-window validation on beneficiary and loser ticker lists.

    event_date: optional 'YYYY-MM-DD'. When provided, returns are computed from
      the event-date close forward. When omitted, uses the rolling 3-month window
      (current-price mode — existing behaviour).

    persistence / stage: optional event-level context used to weight the
      per-ticker validation_evidence read (transient/anticipation events
      lean on 1d/5d; structural events lean on 20d).  Default ``None``
      preserves the prior balanced read for callers that haven't been
      threaded through.

    Returns a 'note' string for the pipeline and per-ticker 'details'.
    This is a rough screen — not proof of anything.
    """
    all_tickers = list(dict.fromkeys(beneficiary_tickers + loser_tickers))  # dedup, preserve order
    if not all_tickers:
        return {"note": "No assets to check.", "details": {}, "tickers": [],
                "data_quality": "ok"}

    # Pre-fetch sector benchmark ETFs in parallel.  SPY is always fetched
    # as the universal fallback so every validated ticker gets a relative-
    # move read, even when it sits outside every sector bucket.
    benchmark_cache: dict = {}
    xle_data = None
    needed_benchmarks: set[str] = {_DEFAULT_BENCHMARK}
    for t in all_tickers:
        bench_etf, _ = resolve_benchmark(t)
        if bench_etf:
            needed_benchmarks.add(bench_etf)

    def _fetch_bench(etf: str):
        try:
            return etf, (_fetch_since(etf, event_date) if event_date else _fetch(etf))
        except Exception:
            _log.warning("_fetch_bench(%s) failed", etf, exc_info=True)
            return etf, None

    with _TPE(max_workers=_MAX_FETCH_WORKERS) as pool:
        for etf, bd in pool.map(_fetch_bench, needed_benchmarks):
            if bd is not None:
                benchmark_cache[etf] = bd
                if etf == "XLE":
                    xle_data = bd

    # Build a role lookup.
    role_map: dict[str, str] = {}
    for t in loser_tickers:
        role_map[t] = "loser"
    for t in beneficiary_tickers:
        role_map[t] = "beneficiary"

    # Fetch all tickers in parallel.
    def _check_one(ticker: str) -> tuple[str, dict]:
        role = role_map.get(ticker, "beneficiary")
        return ticker, _check_one_ticker(
            ticker, role=role, xle_data=xle_data, event_date=event_date,
            benchmark_cache=benchmark_cache,
            persistence=persistence, stage=stage,
        )

    details = {}
    with _TPE(max_workers=_MAX_FETCH_WORKERS) as pool:
        for t, result in pool.map(_check_one, all_tickers):
            details[t] = result

    # --- Per-ticker lines ---
    lines = []
    for t, v in details.items():
        role = role_map.get(t, "beneficiary")
        dir_tag = f", {v['direction']}" if v["direction"] else ""
        lines.append(f"  {t} ({role}): {v['label']}{dir_tag} — {v['detail']}")

    # --- Summary: how many tickers moved in the predicted direction? ---
    tickers_with_direction = [v for v in details.values() if v["direction"] is not None]
    supporting = [v for v in tickers_with_direction if v["direction"].startswith("supports")]
    if tickers_with_direction:
        lines.append(
            f"  ---\n  Hypothesis support: {len(supporting)} of {len(tickers_with_direction)} "
            f"tickers moving in predicted direction"
        )

    # Determine the actual trading anchor date across tickers.
    # All tickers fetch from the same start_date so anchors should agree;
    # pick the first non-None one as representative.
    anchor_date = None
    if event_date:
        for v in details.values():
            if v.get("anchor_date"):
                anchor_date = v["anchor_date"]
                break

    if event_date:
        header = f"Market check (anchored to event date: {event_date}"
        if anchor_date and anchor_date != event_date:
            header += f", first trading day: {anchor_date}"
        header += "):"
    else:
        header = "Market check (current prices, not event-date validation):"
    note = header + "\n" + "\n".join(lines)

    # Structured ticker list — one dict per ticker with numeric fields for storage/analysis.
    # `details` (dict keyed by symbol) is kept for backward compatibility with existing callers.
    #
    # Defensive emission: dedupe by symbol (already unique by dict
    # construction, but re-asserted here so a future regression can't
    # leak shared cards into the frontend) and copy ``spark`` into a
    # fresh list per ticker so no two ticker dicts share the same
    # underlying sequence reference.
    tickers: list[dict] = []
    seen_symbols: set[str] = set()
    for t, v in details.items():
        if t in seen_symbols:
            continue
        seen_symbols.add(t)
        _spark_raw = v.get("spark") or []
        spark_src = normalize_spark(_spark_raw) if _spark_raw else []
        td = {
            "symbol":       t,
            "role":         role_map.get(t, "beneficiary"),
            "label":        v["label"],
            "direction_tag": v["direction"],
            "return_1d":    v.get("return_1d"),
            "return_5d":    v.get("return_5d"),
            "return_20d":   v.get("return_20d"),
            "volume_ratio": v.get("volume_ratio"),
            "vs_xle_5d":    v.get("vs_xle_5d"),
            "spark":        list(spark_src),
        }
        # Surface verification verdict when present — additive field, older
        # stored rows simply won't have it.  Status "unverified" is omitted
        # from the output to keep the response lean for the common no-op path.
        _verif = v.get("verification")
        if _verif and _verif.get("status") not in (None, "unverified"):
            td["verification"] = _verif
        # Additive staleness fields — only present when the ticker's
        # latest bar is older than _STALE_TICKER_CALENDAR_DAYS.
        if v.get("stale"):
            td["stale"] = True
            td["last_trade_date"] = v.get("last_trade_date")
        tickers.append(td)

    # Final defensive pass: sanity-bound returns AND suppress
    # cross-contaminated rows.  The sanity scrub catches absurdly
    # large persisted values (e.g. +1348% from corrupt price_cache
    # bars); the dedupe suppression catches yfinance-race
    # cross-contamination.  Both pass over fresh-copy ticker dicts
    # so no shared references leak into the response payload.
    tickers = _scrub_implausible_ticker_returns(tickers)
    tickers = _suppress_duplicate_tickers(tickers)

    # --- Data-quality signal: flag when too many tickers lack data ---
    result = {"note": note, "details": details, "tickers": tickers}
    result.update(derive_data_quality(tickers))

    if anchor_date:
        result["anchor_date"] = anchor_date
    return result


# ---------------------------------------------------------------------------
# Follow-up check — forward returns for saved events
# ---------------------------------------------------------------------------

def followup_check(tickers: list[dict], event_date: str) -> list[dict]:
    """Compute forward 1d/5d/20d returns for previously saved tickers.

    tickers: list of dicts from a saved event's market_tickers field.
              Each dict must have at least 'symbol' and 'role'.
    event_date: 'YYYY-MM-DD' string — the anchor date.

    Returns a list of dicts, one per ticker:
        { symbol, role, return_1d, return_5d, return_20d, direction }

    Designed to be lightweight: no volume check, no XLE comparison, no label.
    Just forward returns and a direction tag so the UI can show what happened.
    """
    if not tickers or not event_date:
        return []

    def _check_one_followup(t: dict) -> dict:
        symbol = t.get("symbol", "")
        role   = t.get("role", "beneficiary")
        _no = {"symbol": symbol, "role": role,
               "return_1d": None, "return_5d": None, "return_20d": None, "return_60d": None,
               "direction": None, "anchor_date": None}
        if not symbol:
            return None  # filtered out below
        # Strip proxy annotation — never send "(proxy)" suffixes to the provider.
        fetch_symbol = _clean_fetch_symbol(symbol)
        if not fetch_symbol:
            return None  # skip empty-after-clean tickers
        try:
            data = _fetch_since(fetch_symbol, event_date)
            if data is None or len(data) < 2:
                return _no
            anchor = str(data.index[0].date())
            closes = data["Close"]
            r1  = _pct_forward(closes, 1)
            r5  = _pct_forward(closes, 5)
            r20 = _pct_forward(closes, 20)
            r60 = _pct_forward(closes, 60)
            return {
                "symbol": symbol, "role": role,
                "return_1d":  round(r1,  2) if r1  is not None else None,
                "return_5d":  round(r5,  2) if r5  is not None else None,
                "return_20d": round(r20, 2) if r20 is not None else None,
                "return_60d": round(r60, 2) if r60 is not None else None,
                "direction":  _direction_tag(r5, role),
                "anchor_date": anchor,
            }
        except Exception:
            _log.warning("followup_check: %s fetch/calc failed", symbol, exc_info=True)
            return _no

    with _TPE(max_workers=_MAX_FETCH_WORKERS) as pool:
        raw = list(pool.map(_check_one_followup, tickers))
    return [r for r in raw if r is not None]


# ---------------------------------------------------------------------------
# Macro context snapshot — provider-backed via market_universe
# ---------------------------------------------------------------------------
# Uses the same _fetch/_fetch_since/caching infrastructure as ticker checks.
#
# Each instrument is identified by either:
#   - a liquid market identifier (DXY, 10Y, CL) — resolved via market_universe
#     to whichever ticker the active provider can serve, or
#   - a raw symbol (^VIX, BZ=F) — used as-is when no liquid mapping exists.

# (identifier, display label, unit)
_MACRO_INSTRUMENTS: list[tuple[str, str, str]] = [
    ("DXY",  "USD",   "idx"),     # US Dollar Index — resolved per provider
    ("10Y",  "10Y",   "%"),        # 10-year Treasury — resolved per provider
    ("^VIX", "VIX",   ""),         # CBOE VIX — no liquid-market entry
    ("CL",   "WTI",   "$/bbl"),    # WTI crude — resolved per provider
    ("BZ=F", "Brent", "$/bbl"),    # Brent crude — no liquid-market entry
]


def macro_snapshot(event_date: str | None = None) -> list[dict]:
    """Return a compact macro context strip for the given date.

    Each entry: {label, value, change_5d, unit}.
    Resolves liquid market identifiers via market_universe so the active
    provider's preferred symbol is used.  Falls back to literal symbols
    for instruments outside the liquid-market catalogue.
    Returns partial results on failure — never raises.
    """
    from market_universe import resolve_symbol
    # Fetched serially: yfinance is not thread-safe for concurrent downloads.
    # With the 10-min TTL cache, second+ calls resolve from memory instantly.
    results: list[dict] = []
    for identifier, label, unit in _MACRO_INSTRUMENTS:
        entry: dict = {"label": label, "value": None, "change_5d": None, "unit": unit}
        # Resolve liquid market IDs (DXY, 10Y, CL) to provider-specific
        # tickers; pass through raw symbols (^VIX, BZ=F) unchanged.
        ticker = resolve_symbol(identifier) or identifier
        is_yield = (identifier == "10Y")
        try:
            data = _fetch_since(ticker, event_date) if event_date else _fetch(ticker)
            if data is not None and len(data) >= 2:
                closes = data["Close"]
                chg = None  # default; stays None for short forward histories
                if event_date:
                    entry["value"] = round(float(closes.iloc[0]), 2)
                    if len(closes) >= 6:
                        # Yields use absolute pp change, not percent-of-level.
                        if is_yield:
                            s, e = float(closes.iloc[0]), float(closes.iloc[5])
                            chg = (e - s) if _is_finite(s) and _is_finite(e) else None
                        else:
                            _start = float(closes.iloc[0])
                            _bounds = _MACRO_PRICE_FLOORS.get(identifier)
                            if _bounds and _is_finite(_start) and not (_bounds[0] <= _start <= _bounds[1]):
                                _log.warning(
                                    "macro_snapshot: %s start price %.2f outside "
                                    "plausible range %s — discarding change_5d",
                                    identifier, _start, _bounds,
                                )
                            else:
                                chg = _pct_forward(closes, 5)
                    else:
                        _log.debug(
                            "macro_snapshot: %s (%s) only %d forward row(s) — "
                            "change_5d unavailable (need ≥6)",
                            identifier, ticker, len(closes),
                        )
                else:
                    entry["value"] = round(float(closes.iloc[-1]), 2)
                    if is_yield and len(closes) > 5:
                        s, e = float(closes.iloc[-6]), float(closes.iloc[-1])
                        chg = (e - s) if _is_finite(s) and _is_finite(e) else None
                    elif len(closes) > 5:
                        _start = float(closes.iloc[-6])
                        _bounds = _MACRO_PRICE_FLOORS.get(identifier)
                        if _bounds and _is_finite(_start) and not (_bounds[0] <= _start <= _bounds[1]):
                            _log.warning(
                                "macro_snapshot: %s start price %.2f outside "
                                "plausible range %s — discarding change_5d",
                                identifier, _start, _bounds,
                            )
                        else:
                            chg = _pct(closes, 5)
                if chg is not None:
                    _move_cap = _MACRO_MOVE_CAPS.get(identifier)
                    if _move_cap is not None and abs(chg) > _move_cap:
                        _log.warning(
                            "macro_snapshot: %s move %.4g exceeds cap ±%.4g — "
                            "discarding",
                            identifier, chg, _move_cap,
                        )
                        chg = None
                    if chg is not None:
                        entry["change_5d"] = round(chg, 2)
            else:
                if data is None:
                    _log.debug(
                        "macro_snapshot: %s (%s) returned no data — "
                        "row will have null values",
                        identifier, ticker,
                    )
                else:
                    _log.debug(
                        "macro_snapshot: %s (%s) returned only %d row(s) — "
                        "need ≥2, row will have null values",
                        identifier, ticker, len(data),
                    )
        except Exception:
            _log.warning("macro_snapshot: failed to fetch %s (%s): %s",
                          identifier, ticker, __import__('sys').exc_info()[1])
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Market stress regime
# ---------------------------------------------------------------------------

_STRESS_TICKERS = ["^VIX", "^VIX3M", "HYG", "SHY", "GLD", "DX-Y.NYB", "TLT", "RSP", "SPY"]


def _safe_pct(series, n: int) -> float | None:
    """Trailing n-period percent change, None if insufficient data or NaN."""
    if series is None or len(series) < n + 1:
        return None
    end = float(series.iloc[-1])
    start = float(series.iloc[-(n + 1)])
    if not _is_finite(end) or not _is_finite(start) or start == 0:
        return None
    return float((end - start) / start * 100)


# ---------------------------------------------------------------------------
# Inflation / rates context
# ---------------------------------------------------------------------------
# Three liquid proxies, all available through yfinance:
#   ^TNX  — 10-year nominal yield (CBOE)
#   TIP   — iShares TIPS Bond ETF (moves inversely with real yields)
#   Breakeven ≈ nominal yield move − real yield move
#
# TIP price *falls* when real yields *rise*, so:
#   real_yield_pp ≈ −TIP_pct / _TIP_DURATION   (Fisher decomposition)
#   breakeven_pp  = nominal_pp + TIP_pct / _TIP_DURATION
# This is a proxy, not an exact number, but directionally reliable for
# the classification we need.

# Approximate modified duration of the TIP ETF (iShares TIPS Bond ETF).
# Converts a TIP price % change to an implied real-yield pp change:
#   real_yield_pp ≈ −TIP_pct / _TIP_DURATION
# iShares reports ~7.4–7.7 years; 7.5 is the midpoint.
_TIP_DURATION: float = 7.5

def classify_rates_regime(
    nominal_5d: float | None,
    tip_5d: float | None,
) -> str:
    """Classify the rates/inflation regime from 5-day moves.

    nominal_5d: 5d absolute change in ^TNX in percentage points
                (positive = yields rising, e.g. 0.15 = +15 bps)
    tip_5d:     5d % change in TIP ETF price
                (positive = real yields falling, since TIP is inversely priced)

    Returns one of:
      "Inflation pressure"    — breakevens rising (nominals up, real yields flat/down)
      "Real-rate tightening"  — real yields rising faster than breakevens
      "Risk-off / growth scare" — nominals falling (flight to safety)
      "Mixed"                 — no clear pattern or insufficient data
    """
    if nominal_5d is None or tip_5d is None:
        return "Mixed"

    # Directional thresholds — small moves are noise.
    # For nominal_5d (pp): 0.3 = 30 bps threshold.
    # For tip_5d (%): 0.3 = 0.3% TIP price move threshold.
    THRESH = 0.3

    nom_up   = nominal_5d >  THRESH
    nom_down = nominal_5d < -THRESH
    tip_down = tip_5d < -THRESH   # real yields rising
    tip_up   = tip_5d >  THRESH   # real yields falling

    if nom_up and (tip_up or abs(tip_5d) <= THRESH):
        # Nominals rising but real yields flat or falling → breakevens widening
        return "Inflation pressure"
    if tip_down and (not nom_up or nom_down):
        # Real yields rising with flat/falling nominals → pure tightening
        return "Real-rate tightening"
    if tip_down and nom_up:
        # Both moving: real yields rising AND nominals rising → also tightening
        return "Real-rate tightening"
    if nom_down and tip_up:
        # Nominals falling, TIPS rallying → flight to safety
        return "Risk-off / growth scare"
    if nom_down and not tip_down:
        # Nominals falling, real yields not rising → growth scare
        return "Risk-off / growth scare"
    return "Mixed"


def compute_rates_context() -> dict:
    """Compute a compact inflation/rates context snapshot.

    Returns {regime, nominal, real_proxy, breakeven_proxy, raw}.
    Uses ^TNX and TIP via the existing _fetch + TTL cache.
    """
    raw: dict = {}
    nominal_5d: float | None = None
    tip_5d: float | None = None

    try:
        tnx = _fetch("^TNX")
        if tnx is not None and len(tnx) >= 6:
            closes_tnx = tnx["Close"]
            val = float(closes_tnx.iloc[-1])
            raw["tnx"] = round(val, 2)
            # Unit-aware: ^TNX is UNIT_YIELD → compute_move returns pp,
            # matching _CHANNEL_SCALE["nominal_yield"] = 0.20 (20 bps).
            diff = compute_move(closes_tnx, 5, UNIT_YIELD)
            # Hard cap: ±5 pp (±500 bps) in 5 days is beyond any extreme.
            if diff is not None and abs(diff) <= 5.0:
                nominal_5d = round(diff, 4)
            if nominal_5d is not None:
                raw["tnx_change_5d"] = round(nominal_5d, 4)
    except Exception:
        _log.warning("compute_rates_context: ^TNX fetch/calc failed", exc_info=True)

    # 5Y and 30Y yields — used by shock_decomposition's rates_pack to build
    # the 5s30s curve decomposition alongside the existing 2s10s.  Fetched
    # here (same TTL cache as ^TNX) so a single rates_context call carries
    # everything the curve classifier needs.  Both are optional; missing
    # values degrade the long-end read to "unavailable" without disturbing
    # the front-end 2s10s classification.
    try:
        fvx = _fetch("^FVX")
        if fvx is not None and len(fvx) >= 6:
            closes_fvx = fvx["Close"]
            raw["fvx"] = round(float(closes_fvx.iloc[-1]), 2)
            diff = compute_move(closes_fvx, 5, UNIT_YIELD)
            if diff is not None and abs(diff) <= 5.0:
                raw["fvx_change_5d"] = round(diff, 4)
    except Exception:
        _log.warning("compute_rates_context: ^FVX fetch/calc failed", exc_info=True)

    try:
        tyx = _fetch("^TYX")
        if tyx is not None and len(tyx) >= 6:
            closes_tyx = tyx["Close"]
            raw["tyx"] = round(float(closes_tyx.iloc[-1]), 2)
            diff = compute_move(closes_tyx, 5, UNIT_YIELD)
            if diff is not None and abs(diff) <= 5.0:
                raw["tyx_change_5d"] = round(diff, 4)
    except Exception:
        _log.warning("compute_rates_context: ^TYX fetch/calc failed", exc_info=True)

    try:
        tip = _fetch("TIP")
        if tip is not None and len(tip) >= 6:
            val = float(tip["Close"].iloc[-1])
            raw["tip"] = round(val, 2)
            # _validated_pct checks start price against _PRICE_FLOORS["TIP"]
            # (60–160) and delegates to compute_move with UNIT_PRICE.
            tip_5d = _validated_pct(tip["Close"], 5, "TIP")
            if tip_5d is not None:
                raw["tip_change_5d"] = round(tip_5d, 2)
    except Exception:
        _log.warning("compute_rates_context: TIP fetch/calc failed", exc_info=True)

    # Short-end + long-end TIPS ETFs for the per-tenor breakeven curve.
    # STIP = 0-5Y TIPS (duration ~2.5y), LTPZ = 15Y+ TIPS (duration ~20y).
    # Both are optional; missing values degrade a single tenor without
    # disturbing the overall rates_context block.
    try:
        stip = _fetch("STIP")
        if stip is not None and len(stip) >= 6:
            raw["stip"] = round(float(stip["Close"].iloc[-1]), 2)
            mv = _safe_pct(stip["Close"], 5)
            if mv is not None and abs(mv) <= 20.0:
                raw["stip_change_5d"] = round(mv, 2)
    except Exception:
        _log.warning("compute_rates_context: STIP fetch/calc failed", exc_info=True)

    try:
        ltpz = _fetch("LTPZ")
        if ltpz is not None and len(ltpz) >= 6:
            raw["ltpz"] = round(float(ltpz["Close"].iloc[-1]), 2)
            mv = _safe_pct(ltpz["Close"], 5)
            if mv is not None and abs(mv) <= 30.0:
                raw["ltpz_change_5d"] = round(mv, 2)
    except Exception:
        _log.warning("compute_rates_context: LTPZ fetch/calc failed", exc_info=True)

    # Breakeven proxy (pp-consistent via Fisher decomposition):
    #   breakeven_pp = nominal_pp − real_yield_pp
    #   real_yield_pp ≈ −TIP_pct / _TIP_DURATION
    #   → breakeven_pp = nominal_pp + TIP_pct / _TIP_DURATION
    # When TIP rises (real yields fell), breakevens widen — correct direction.
    if nominal_5d is not None and tip_5d is not None:
        be_proxy = nominal_5d + tip_5d / _TIP_DURATION
        # ±7 pp cap — keeps parity with shock_decomposition channel cap for
        # breakeven.  Guards against the rare case where both nominal and TIP
        # are individually within bounds but their combination is nonsense.
        if abs(be_proxy) > 7.0:
            _log.warning(
                "compute_rates_context: breakeven_proxy %.4g pp exceeds "
                "±7 pp cap — discarding",
                be_proxy,
            )
            be_proxy = None
        if be_proxy is not None:
            raw["breakeven_proxy_5d"] = round(be_proxy, 4)

    # When both primary inputs are None, the regime classification is
    # meaningless — surface an explicit unavailable state.
    has_nominal = nominal_5d is not None
    has_tip = tip_5d is not None
    available = has_nominal or has_tip

    if available:
        regime = classify_rates_regime(nominal_5d, tip_5d)
    else:
        regime = "Unavailable"

    # Per-tenor breakeven decomposition.  Assembled from whatever yields +
    # TIPS proxies we have — partial data is tolerated and surfaces as
    # unavailable tenors rather than a global failure.  Uses SHY (already
    # fetched for the stress-regime credit block) to derive the 2Y nominal
    # pp change; the Fisher-inversion for real yields lives in the
    # breakeven_curve module.
    breakeven_curve_block: dict = {}
    try:
        import breakeven_curve as _be_mod
        # 2Y nominal pp approximation from SHY (duration ~1.9y).  SHY is
        # fetched separately by compute_stress_regime; when this function
        # runs standalone the field may be absent.
        shy_5d_pct = raw.get("shy_5d")
        twoy_pp: float | None = None
        if isinstance(shy_5d_pct, (int, float)):
            twoy_pp = -float(shy_5d_pct) / 1.9
        nominal_pp_by_tenor = {
            "2Y":  round(twoy_pp, 4) if twoy_pp is not None else None,
            "5Y":  raw.get("fvx_change_5d"),
            "10Y": raw.get("tnx_change_5d"),
            "30Y": raw.get("tyx_change_5d"),
        }
        real_pp_by_tenor = _be_mod.real_pp_from_tips_pct(
            stip_pct_5d=raw.get("stip_change_5d"),
            tip_pct_5d=raw.get("tip_change_5d"),
            ltpz_pct_5d=raw.get("ltpz_change_5d"),
        )
        breakeven_curve_block = _be_mod.compute_breakeven_curve(
            nominal_5d_pp=nominal_pp_by_tenor,
            real_5d_pp=real_pp_by_tenor,
        )
    except Exception:
        _log.warning("compute_rates_context: breakeven_curve build failed",
                     exc_info=True)
        breakeven_curve_block = {}

    return {
        "regime": regime,
        "available": available,
        "nominal": {
            "label": "10Y yield",
            "value": raw.get("tnx"),
            "change_5d": raw.get("tnx_change_5d"),
        },
        # Extra tenors for the 5s30s curve decomposition in shock_decomposition.
        # These stay on the response (not nested under `raw`) so consumers can
        # treat the mid and long tenors symmetrically with the 10Y field.
        "mid_nominal": {
            "label": "5Y yield",
            "value": raw.get("fvx"),
            "change_5d": raw.get("fvx_change_5d"),
        },
        "long_nominal": {
            "label": "30Y yield",
            "value": raw.get("tyx"),
            "change_5d": raw.get("tyx_change_5d"),
        },
        "real_proxy": {
            "label": "TIP (real yield proxy)",
            "value": raw.get("tip"),
            "change_5d": raw.get("tip_change_5d"),
        },
        "breakeven_proxy": {
            "label": "Breakeven proxy",
            "change_5d": raw.get("breakeven_proxy_5d"),
        },
        "breakeven_curve": breakeven_curve_block,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Monetary policy sensitivity classifier
# ---------------------------------------------------------------------------
# Determines whether an event's mechanism is reinforced, opposed, or
# unaffected by the current rates/inflation regime.  Purely deterministic:
# cross-references the rates regime with keyword signals from the analysis.

# Keywords signalling the event benefits from loose/falling rates
_LOOSE_RATE_KW: set[str] = {
    "multiple expansion", "lower discount", "risk-on", "rate cut",
    "valuation lift", "growth stock", "housing", "mortgage",
    "refinanc", "equity rally", "buyback", "leveraged", "duration",
    "real estate", "reit", "construction", "home",
}

# Keywords signalling the event benefits from tight/rising rates
_TIGHT_RATE_KW: set[str] = {
    "bank margin", "net interest", "money market", "saver",
    "deposit rate", "insurance yield", "cash yield", "t-bill",
    "short duration", "floating rate", "rate hike benefit",
}

# Keywords signalling an inflationary channel
_INFLATION_KW: set[str] = {
    "oil price", "crude", "commodity", "supply shock", "input cost",
    "food price", "wage pressure", "tariff", "import cost",
    "energy price", "fuel cost", "pipeline", "opec", "shipping cost",
}


def classify_policy_sensitivity(
    rates_regime: str,
    mechanism_text: str,
) -> dict:
    """Classify whether the event mechanism is reinforced or opposed by rates.

    Parameters
    ----------
    rates_regime : str
        Output of classify_rates_regime(): "Inflation pressure",
        "Real-rate tightening", "Risk-off / growth scare", or "Mixed".
    mechanism_text : str
        The mechanism_summary + what_changed from the analysis.

    Returns
    -------
    dict with keys:
        stance: "reinforced" | "fighting" | "neutral"
        explanation: one plain-English sentence
        regime: the rates regime used for classification
    Returns {} only when mechanism_text is empty (low-signal guard).
    For mixed/unclear regimes, returns a visible neutral fallback.
    """
    if not mechanism_text or not mechanism_text.strip():
        return {}
    if rates_regime == "Mixed":
        return {
            "stance": "neutral",
            "explanation": "No clear rates tilt — mixed signals across nominal and real yields.",
            "regime": "Mixed",
        }

    mech_low = mechanism_text.lower()

    has_loose = any(kw in mech_low for kw in _LOOSE_RATE_KW)
    has_tight = any(kw in mech_low for kw in _TIGHT_RATE_KW)
    has_inflation = any(kw in mech_low for kw in _INFLATION_KW)

    # If neither signal matches, the event is rates-neutral
    if not has_loose and not has_tight and not has_inflation:
        return {
            "stance": "neutral",
            "explanation": f"This event's mechanism has no direct rate sensitivity. Current regime: {rates_regime}.",
            "regime": rates_regime,
        }

    stance = "neutral"
    explanation = ""

    if rates_regime == "Inflation pressure":
        if has_inflation:
            stance = "reinforced"
            explanation = "Inflationary event amplified by a rising-breakeven environment — price pressures compound."
        elif has_loose:
            stance = "fighting"
            explanation = "Event mechanism benefits from easy money, but inflation pressure may force tighter policy."
        elif has_tight:
            stance = "reinforced"
            explanation = "Tight-rate beneficiary aligned with current inflation-driven tightening expectations."

    elif rates_regime == "Real-rate tightening":
        if has_loose:
            stance = "fighting"
            explanation = "Event mechanism needs lower rates, but real rates are rising — headwind for the thesis."
        elif has_tight:
            stance = "reinforced"
            explanation = "Event benefits from higher real rates, which the current tightening regime delivers."
        elif has_inflation:
            stance = "fighting"
            explanation = "Inflationary channel is being offset by aggressive real-rate tightening."

    elif rates_regime == "Risk-off / growth scare":
        if has_loose:
            stance = "reinforced"
            explanation = "Falling yields support the event's rate-sensitive mechanism — tailwind."
        elif has_tight:
            stance = "fighting"
            explanation = "Event needs rate income, but yields are collapsing in a risk-off move."
        elif has_inflation:
            stance = "fighting"
            explanation = "Supply-side inflation channel weakened by demand destruction in a growth scare."

    if not explanation:
        return {
            "stance": "neutral",
            "explanation": f"Mixed signals — no clear alignment with {rates_regime}.",
            "regime": rates_regime,
        }

    return {
        "stance": stance,
        "explanation": explanation,
        "regime": rates_regime,
    }


# ---------------------------------------------------------------------------
# Inventory / supply context classifier
# ---------------------------------------------------------------------------
# Deterministic: checks whether relevant commodity/supply proxies signal
# tightness or comfort, then cross-references with mechanism keywords.
# Uses liquid Yahoo-finance ETFs only — no paid data.

# Proxy tickers: each maps a commodity theme to an ETF whose price action
# reflects inventory/supply tightness.  Rising price = tighter supply.
_INVENTORY_PROXIES: list[tuple[set[str], str, str]] = [
    # (mechanism keywords, ticker, label)
    ({"oil", "crude", "petroleum", "opec", "barrel", "refin", "fuel",
      "gasoline", "diesel", "pipeline"},                    "USO",  "Crude Oil (USO)"),
    ({"natural gas", "lng", "gas export", "gas terminal"},  "UNG",  "Natural Gas (UNG)"),
    ({"copper", "metal", "mining", "aluminum", "steel"},    "COPX", "Copper Miners (COPX)"),
    ({"wheat", "grain", "food", "corn", "soybean",
      "agriculture", "fertiliz"},                           "WEAT", "Wheat (WEAT)"),
    ({"shipping", "freight", "tanker", "dry bulk",
      "container", "maritime"},                             "BDRY", "Dry Bulk Shipping (BDRY)"),
    ({"semiconductor", "chip", "foundry", "wafer", "fab",
      "dram", "nand", "hbm"},                               "SMH",  "Semiconductors (SMH)"),
]

# Thresholds for 20-day return classification.
_TIGHT_THRESHOLD = 3.0    # >+3% in 20d → supply tightening signal
_COMFORT_THRESHOLD = -3.0 # <-3% in 20d → supply easing signal


def classify_inventory_context(mechanism_text: str) -> dict:
    """Classify inventory/supply context from commodity proxy price action.

    Parameters
    ----------
    mechanism_text : str
        Combined what_changed + mechanism_summary from analysis.

    Returns
    -------
    dict with keys:
        status: "tight" | "comfortable" | "neutral"
        proxy: the ETF ticker used
        proxy_label: human-readable label
        return_20d: the 20-day return (%)
        explanation: one plain-English sentence
    Returns {} when no commodity/supply keywords match or data unavailable.
    """
    if not mechanism_text or not mechanism_text.strip():
        return {}

    mech_low = mechanism_text.lower()

    # Find the best-matching proxy
    matched_proxy = None
    for keywords, ticker, label in _INVENTORY_PROXIES:
        if any(kw in mech_low for kw in keywords):
            matched_proxy = (ticker, label)
            break

    if not matched_proxy:
        return {}

    ticker, label = matched_proxy

    # Fetch 20d return — fall back to neutral if data unavailable
    ret_20d: float | None = None
    try:
        data = _fetch(ticker)
        if data is not None and len(data) >= 21:
            ret_20d = compute_move(data["Close"], 20, ticker_unit(ticker))
            if ret_20d is not None:
                ret_20d = round(ret_20d, 2)
    except Exception:
        _log.warning("classify_inventory_context: %s fetch failed", ticker, exc_info=True)

    if ret_20d is None:
        return {
            "status": "neutral",
            "proxy": ticker,
            "proxy_label": label,
            "explanation": f"{label} data unavailable — no inventory signal. Supply-relevant event detected.",
        }

    if ret_20d > _TIGHT_THRESHOLD:
        status = "tight"
        explanation = f"{label} up {ret_20d:+.1f}% over 20 days — supply tightening, inventory drawdowns likely."
    elif ret_20d < _COMFORT_THRESHOLD:
        status = "comfortable"
        explanation = f"{label} down {ret_20d:+.1f}% over 20 days — supply easing, inventory builds likely."
    else:
        status = "neutral"
        explanation = f"{label} flat ({ret_20d:+.1f}% / 20d) — no strong inventory signal from price action."

    return {
        "status": status,
        "proxy": ticker,
        "proxy_label": label,
        "return_20d": ret_20d,
        "explanation": explanation,
    }


def _stress_status(active: bool) -> str:
    """Return 'stressed' / 'watch' / 'calm' for a single signal."""
    return "stressed" if active else "calm"


# Plausible price ranges for stress-regime tickers.  The start price of
# the 5d window must land inside these bounds for the return calculation
# to be trusted.  Values far outside (e.g. HYG at $0.50 from a corrupt
# cache row) would produce +1900 % returns that are mathematically
# correct but empirically meaningless.
#
# Ranges are deliberately wide — they cover 15 years of history plus a
# generous margin — so they never reject real data even under extreme
# market conditions.  They only catch cache corruption where the stored
# price is in a completely different universe.
_PRICE_FLOORS: dict[str, tuple[float, float]] = {
    "HYG":      (40.0, 120.0),
    "LQD":      (70.0, 160.0),   # IG corporate ETF — GFC ~85, 2020 high ~137
    "SHY":      (60.0, 110.0),
    "RSP":      (50.0, 300.0),
    "SPY":      (150.0, 900.0),
    "GLD":      (80.0, 600.0),   # raised from 400 — 2026 ATH ~496; 600 gives headroom
    "DX-Y.NYB": (60.0, 150.0),
    "TLT":      (50.0, 200.0),
    # Used by compute_rates_context via _validated_pct:
    "TIP":      (60.0, 160.0),
}

# Plausible start-price ranges for macro snapshot instruments.
# Keyed by _MACRO_INSTRUMENTS identifier (not resolved ticker).
# Ranges cover 15+ years of history with generous margins —
# only rejects cache rows that are in a completely different universe.
_MACRO_PRICE_FLOORS: dict[str, tuple[float, float]] = {
    "DXY":  (70.0,  130.0),   # DXY index (GFC low ~71, 2022 high ~115)
    "CL":   (10.0,  200.0),   # WTI crude $/bbl (Apr 2020 approached $0 briefly)
    "BZ=F": (10.0,  200.0),   # Brent crude $/bbl
    "^VIX": (5.0,   90.0),    # CBOE VIX (historical range ~8–80)
}
# "10Y" omitted — nominal yield start-price is not a useful guard;
# the ±5 pp move cap is the right filter for yields.

# Per-identifier cap on computed 5d moves in macro_snapshot.
# Moves exceeding these are rejected → None (corrupt data / provider glitch).
_MACRO_MOVE_CAPS: dict[str, float] = {
    "DXY":  15.0,   # %  — largest recorded weekly DXY move ~5%; 15% = corrupt
    "^VIX": 200.0,  # %  — 2020 VIX spike was ~115%; kept in sync with stress cap
    "CL":   65.0,   # %  — WTI approached $0 in Apr 2020; 65% covers that extreme
    "BZ=F": 65.0,   # %  — Brent same
    "10Y":  5.0,    # pp — ±500 bps in 5 days is beyond any recorded extreme
}

# Shared alias — ensures compute_stress_regime and macro_snapshot
# use the same VIX cap without duplication.
_VIX_MOVE_CAP: float = _MACRO_MOVE_CAPS["^VIX"]


def _validated_pct(series, n: int, ticker: str) -> float | None:
    """Unit-aware move with plausible-range validation.

    Rejects the result when the start value falls outside the known
    plausible range for *ticker* (corrupt cache row).  Delegates to
    ``compute_move`` with the correct unit for the ticker.
    """
    if series is None or len(series) < n + 1:
        return None
    start = float(series.iloc[-(n + 1)])
    if not _is_finite(start):
        return None
    bounds = _PRICE_FLOORS.get(ticker)
    if bounds and not (bounds[0] <= start <= bounds[1]):
        _log.warning(
            "_validated_pct: %s start value %.2f outside plausible "
            "range %s — corrupt cache row, discarding",
            ticker, start, bounds,
        )
        return None
    return compute_move(series, n, ticker_unit(ticker))


def compute_stress_regime() -> dict:
    """Compute a composite market-stress regime from live data.

    Returns {regime, signals, raw, detail, summary}.
    - detail: per-component dicts with value, context, status, explanation.
    - summary: one-sentence overall summary.
    Backward-compatible: regime, signals, raw are unchanged.
    Uses the existing _fetch + TTL cache so repeated calls are instant.
    """
    raw: dict = {}
    signals: dict[str, bool] = {
        "vix_elevated": False,
        "term_inversion": False,
        "credit_widening": False,
        "safe_haven_bid": False,
        "breadth_deterioration": False,
    }
    detail: dict[str, dict] = {}

    _failed_signals: list[str] = []

    # --- Volatility: VIX vs 20d average ---
    vix_data = None
    vix_now: float | None = None
    vix_avg20: float | None = None
    try:
        vix_data = _fetch("^VIX")
        if vix_data is not None and len(vix_data) >= 20:
            _vn = float(vix_data["Close"].iloc[-1])
            _va = float(vix_data["Close"].iloc[-20:].mean())
            if not _is_finite(_vn) or not _is_finite(_va):
                raise ValueError("VIX latest or 20d avg is NaN/non-finite")
            vix_now = _vn
            vix_avg20 = _va
            raw["vix"] = round(vix_now, 2)
            raw["vix_avg20"] = round(vix_avg20, 2)
            vix_5d = compute_move(vix_data["Close"], 5, UNIT_LEVEL)
            # VIX can spike hard (2020: +100% in a week) but +200%
            # in 5 days is beyond any recorded extreme.
            if vix_5d is not None and abs(vix_5d) > _VIX_MOVE_CAP:
                vix_5d = None
            if vix_5d is not None:
                raw["vix_change_5d"] = round(vix_5d, 2)
            signals["vix_elevated"] = vix_now > vix_avg20 * 1.20

            ratio_pct = round((vix_now / vix_avg20 - 1) * 100, 1) if vix_avg20 else 0
            if signals["vix_elevated"]:
                expl = f"VIX at {raw['vix']} vs 20d avg of {raw['vix_avg20']} — elevated ({ratio_pct:+.0f}% above average), signaling heightened fear"
            elif ratio_pct > 5:
                expl = f"VIX at {raw['vix']} vs 20d avg of {raw['vix_avg20']} — slightly elevated but within normal range"
            else:
                expl = f"VIX at {raw['vix']} vs 20d avg of {raw['vix_avg20']} — volatility (fear gauge) is subdued"
            detail["volatility"] = {
                "label": "Volatility",
                "value": raw["vix"], "avg20": raw["vix_avg20"],
                "change_5d": raw.get("vix_change_5d"),
                "status": _stress_status(signals["vix_elevated"]),
                "explanation": expl,
            }
        else:
            detail["volatility"] = {
                "label": "Volatility", "value": None, "avg20": None,
                "change_5d": None, "status": "calm",
                "explanation": "VIX (volatility index) data unavailable",
            }
    except Exception:
        _log.error("compute_stress_regime: volatility signal failed", exc_info=True)
        _failed_signals.append("volatility")
        detail["volatility"] = {
            "label": "Volatility", "value": None, "avg20": None,
            "change_5d": None, "status": "calm",
            "explanation": "VIX computation error — treating as unknown",
        }

    # --- Term Structure: VIX vs VIX3M ---
    try:
        vix3m_data = _fetch("^VIX3M")
        if vix_data is not None and vix3m_data is not None and len(vix3m_data) > 0:
            if vix_now is None:
                vix_now = raw.get("vix")
            _v3 = float(vix3m_data["Close"].iloc[-1])
            if not _is_finite(_v3) or not _is_finite(vix_now):
                raise ValueError("VIX3M or VIX value is NaN/non-finite")
            vix3m = _v3
            raw["vix3m"] = round(vix3m, 2)
            signals["term_inversion"] = vix_now > vix3m
            if signals["term_inversion"]:
                expl = f"Short-term vol ({raw.get('vix', '?')}) above long-term ({raw['vix3m']}) — backwardation signals immediate panic"
            else:
                expl = f"Short-term vol below long-term (contango) — no immediate panic"
            detail["term_structure"] = {
                "label": "Term Structure",
                "value": raw.get("vix"), "vix3m": raw["vix3m"],
                "status": _stress_status(signals["term_inversion"]),
                "explanation": expl,
            }
        else:
            detail["term_structure"] = {
                "label": "Term Structure", "value": None, "vix3m": None,
                "status": "calm",
                "explanation": "VIX term structure data unavailable",
            }
    except Exception:
        _log.error("compute_stress_regime: term_structure signal failed", exc_info=True)
        _failed_signals.append("term_structure")
        detail["term_structure"] = {
            "label": "Term Structure", "value": None, "vix3m": None,
            "status": "calm",
            "explanation": "Term structure computation error — treating as unknown",
        }

    # --- Credit Stress: HYG vs SHY (+ LQD for default-vs-duration decomposition) ---
    # HYG  — high-yield corporates (default risk + duration)
    # LQD  — investment-grade corporates (mostly duration)
    # SHY  — 1-3Y Treasuries (pure-ish duration at the front end)
    # credit_regime.py consumes all three to separate default-risk widening
    # from rate-driven (duration) widening.  LQD is optional; when missing,
    # credit_regime falls back to a HY-only read.
    try:
        hyg_data = _fetch("HYG")
        shy_data = _fetch("SHY")
        lqd_data = _fetch("LQD")
        if lqd_data is not None:
            lqd_5d = _validated_pct(lqd_data["Close"], 5, "LQD")
            if lqd_5d is not None:
                raw["lqd_5d"] = round(lqd_5d, 2)
        if hyg_data is not None and shy_data is not None:
            hyg_5d = _validated_pct(hyg_data["Close"], 5, "HYG")
            shy_5d = _validated_pct(shy_data["Close"], 5, "SHY")
            if hyg_5d is not None and shy_5d is not None:
                spread_move = shy_5d - hyg_5d
                raw["credit_spread_5d"] = round(spread_move, 2)
                raw["hyg_5d"] = round(hyg_5d, 2)
                raw["shy_5d"] = round(shy_5d, 2)
                signals["credit_widening"] = spread_move > 0.5
                if signals["credit_widening"]:
                    expl = f"High-yield bonds underperforming treasuries by {abs(raw['credit_spread_5d']):.1f}pp over 5d — credit stress rising"
                else:
                    expl = "High-yield bonds steady vs treasuries — credit markets calm"
                detail["credit"] = {
                    "label": "Credit Stress",
                    "spread_5d": raw["credit_spread_5d"],
                    "status": _stress_status(signals["credit_widening"]),
                    "explanation": expl,
                }
            else:
                detail["credit"] = {
                    "label": "Credit Stress", "spread_5d": None, "status": "calm",
                    "explanation": "Credit spread data unavailable",
                }
        else:
            detail["credit"] = {
                "label": "Credit Stress", "spread_5d": None, "status": "calm",
                "explanation": "Credit spread data unavailable",
            }
    except Exception:
        _log.error("compute_stress_regime: credit signal failed", exc_info=True)
        _failed_signals.append("credit")
        detail["credit"] = {
            "label": "Credit Stress", "spread_5d": None, "status": "calm",
            "explanation": "Credit stress computation error — treating as unknown",
        }

    # --- Safe Haven Flows: GLD, DXY, TLT ---
    try:
        haven_detail: dict[str, float | None] = {}
        haven_returns: list[float] = []
        for sym, name in [("GLD", "Gold"), ("DX-Y.NYB", "Dollar"), ("TLT", "Long Bonds")]:
            d = _fetch(sym)
            r = _validated_pct(d["Close"], 5, sym) if d is not None else None
            haven_detail[name] = round(r, 2) if r is not None else None
            if r is not None:
                haven_returns.append(r)
        inflows = sum(1 for v in haven_detail.values() if v is not None and v > 0.3)
        if haven_returns:
            avg_haven = sum(haven_returns) / len(haven_returns)
            raw["haven_avg_5d"] = round(avg_haven, 2)
            signals["safe_haven_bid"] = avg_haven > 1.5   # raised from 0.5 — 0.5pp fired 45% of days (2025 data); 1.5pp targets ~10%
        if signals["safe_haven_bid"]:
            expl = f"{inflows} of 3 safe havens showing inflows — flight to safety underway"
        else:
            expl = f"{inflows} of 3 safe havens showing inflows — no flight to safety"
        detail["safe_haven"] = {
            "label": "Safe Haven Flows",
            "assets": haven_detail,
            "inflow_count": inflows,
            "status": _stress_status(signals["safe_haven_bid"]),
            "explanation": expl,
        }
    except Exception:
        _log.error("compute_stress_regime: safe_haven signal failed", exc_info=True)
        _failed_signals.append("safe_haven")
        detail["safe_haven"] = {
            "label": "Safe Haven Flows", "assets": {}, "inflow_count": 0,
            "status": "calm",
            "explanation": "Safe haven computation error — treating as unknown",
        }

    # --- Breadth: RSP vs SPY ---
    try:
        rsp_data = _fetch("RSP")
        spy_data = _fetch("SPY")
        if rsp_data is not None and spy_data is not None:
            rsp_5d = _validated_pct(rsp_data["Close"], 5, "RSP")
            spy_5d = _validated_pct(spy_data["Close"], 5, "SPY")
            if rsp_5d is not None and spy_5d is not None:
                breadth_gap = rsp_5d - spy_5d
                raw["breadth_gap_5d"] = round(breadth_gap, 2)
                signals["breadth_deterioration"] = breadth_gap < -1.5  # raised from -0.5 — -0.5pp fired 36% of days (2025 data); -1.5pp targets ~6%
                if signals["breadth_deterioration"]:
                    expl = f"Equal-weight lagging cap-weight by {abs(raw['breadth_gap_5d']):.1f}pp — narrow leadership, fewer stocks participating"
                else:
                    expl = "Equal-weight keeping pace with cap-weight — broad market participation"
                detail["breadth"] = {
                    "label": "Market Breadth",
                    "gap_5d": raw["breadth_gap_5d"],
                    "status": _stress_status(signals["breadth_deterioration"]),
                    "explanation": expl,
                }
            else:
                detail["breadth"] = {
                    "label": "Market Breadth", "gap_5d": None, "status": "calm",
                    "explanation": "Breadth data unavailable",
                }
        else:
            detail["breadth"] = {
                "label": "Market Breadth", "gap_5d": None, "status": "calm",
                "explanation": "Breadth data unavailable",
            }
    except Exception:
        _log.error("compute_stress_regime: breadth signal failed", exc_info=True)
        _failed_signals.append("breadth")
        detail["breadth"] = {
            "label": "Market Breadth", "gap_5d": None, "status": "calm",
            "explanation": "Breadth computation error — treating as unknown",
        }

    # --- FX cross-rates (EURUSD, USDJPY, USDCNY) ---
    # Additive: exposes 5d moves in raw for downstream cross_rate_fx /
    # reserve_stress / terms_of_trade consumers.  Not counted against the
    # 5-signal live-data budget above — these are supplementary, not a
    # gate on regime classification.
    try:
        _fx_pairs = [
            ("EURUSD=X", "eurusd_5d"),
            ("JPY=X",    "usdjpy_5d"),
            ("CNY=X",    "usdcny_5d"),
        ]
        for sym, key in _fx_pairs:
            try:
                d = _fetch(sym)
            except Exception:
                _log.warning("compute_stress_regime: FX fetch %s failed", sym, exc_info=True)
                continue
            if d is None:
                continue
            r = _pct(d["Close"], 5)
            if r is not None and abs(r) <= _RETURN_SANITY_R5_PCT:
                raw[key] = round(r, 3)
    except Exception:
        _log.error("compute_stress_regime: FX cross-rate block failed", exc_info=True)

    if _failed_signals:
        _log.warning("compute_stress_regime: %d of 5 signals failed: %s",
                      len(_failed_signals), ", ".join(_failed_signals))

    # Count how many signals have real data vs empty/errored.
    # Each signal type has its own primary-value key:
    #   volatility    → value (VIX level)
    #   term_structure→ value (VIX level) + vix3m
    #   credit        → spread_5d
    #   safe_haven    → assets dict with at least one non-None value
    #   breadth       → gap_5d
    _n_live = 0
    if detail.get("volatility", {}).get("value") is not None:
        _n_live += 1
    if detail.get("term_structure", {}).get("value") is not None:
        _n_live += 1
    if detail.get("credit", {}).get("spread_5d") is not None:
        _n_live += 1
    _haven_assets = detail.get("safe_haven", {}).get("assets", {})
    if any(v is not None for v in _haven_assets.values()):
        _n_live += 1
    if detail.get("breadth", {}).get("gap_5d") is not None:
        _n_live += 1
    _n_dead = 5 - _n_live

    # When the majority of signals have no data, the regime label is
    # unreliable — surface an explicit degraded/unavailable state so the
    # frontend shows a warning instead of masking total provider failure
    # as "Calm".
    if _n_dead == 5:
        regime = "Unavailable"
        available = False
    elif _n_dead >= 3:
        regime = "Degraded"
        available = False
    else:
        regime = classify_regime(signals)
        available = True

    # One-sentence summary
    active_count = sum(signals.values())
    if not available and _n_dead == 5:
        summary = "Stress data unavailable — all provider signals failed"
    elif not available:
        summary = f"Stress data degraded — {_n_dead} of 5 signals lack data"
    elif active_count == 0:
        summary = "Markets stable — no signs of stress across volatility, credit, or safe havens"
    elif regime == "Systemic Stress":
        summary = "Multiple stress signals firing — elevated volatility, credit widening, and term structure inversion"
    elif regime == "Geopolitical Stress":
        summary = "Volatility elevated with safe-haven flows — geopolitical risk is being priced"
    elif regime == "Calm with Undercurrent":
        summary = f"{active_count} secondary signal{'s' if active_count > 1 else ''} active — surface calm but watch for escalation"
    else:
        summary = f"{active_count} signal{'s' if active_count > 1 else ''} active — mixed but no systemic pattern"

    return {
        "regime": regime,
        "signals": signals,
        "raw": raw,
        "detail": detail,
        "summary": summary,
        "available": available,
    }


def classify_regime(signals: dict[str, bool]) -> str:
    """Classify the market regime from individual stress signals.

    Labels:
    - Systemic Stress: VIX elevated + credit widening + term inversion
    - Geopolitical Stress: VIX elevated + safe-haven bid, but credit stable
    - Calm with Undercurrent: safe-haven bid or breadth deterioration without VIX spike
    - Calm: none of the above
    """
    active = sum(signals.values())
    vix = signals.get("vix_elevated", False)
    credit = signals.get("credit_widening", False)
    term = signals.get("term_inversion", False)
    haven = signals.get("safe_haven_bid", False)
    breadth = signals.get("breadth_deterioration", False)

    if vix and credit and term:
        return "Systemic Stress"
    if vix and (haven or term) and not credit:
        return "Geopolitical Stress"
    if active >= 2 and not vix:
        return "Calm with Undercurrent"
    if haven or breadth:
        return "Calm with Undercurrent"
    return "Calm"


# ---------------------------------------------------------------------------
# Shock decay classification
# ---------------------------------------------------------------------------

# Moves below this threshold (in %) are treated as market noise.
# Calibrated against 169 ticker-pairs from the live event archive:
#   p5 = 0.15%, p10 = 0.15% — so ~10% of real event returns land below 0.3%.
#   Only 1 of 169 pairs had *both* legs under 0.3%.
# 0.3% filters noise without discarding real modest moves (e.g. 0.5%).
DECAY_DE_MINIMIS: float = 0.3


def classify_decay(return_5d: float | None, return_20d: float | None) -> dict:
    """Classify the trajectory of a ticker's post-event move.

    Compares the 5d and 20d returns to determine whether the shock is
    accelerating, holding, fading, or reversed.

    Returns {label, evidence} where evidence is a one-line explanation.

    Edge-case handling
    ------------------
    * **Both legs below noise** → ``Negligible``.
    * **One leg below noise + sign flip** → the noisy leg is treated as
      effectively zero and the pair routes through the magnitude logic
      using the dominant leg.  Prevents a -0.15% wiggle from turning a
      +8.89% 20d into "Reversed."
    * **Both legs above noise + sign flip** → ``Reversed``.
    * **One or both legs exactly zero** → routed through magnitude logic
      (zero is unsigned, not a sign flip).

    Thresholds validated against 213 ticker-pairs from the live archive:
      DECAY_DE_MINIMIS = 0.3%  (p10 of real returns)
      Accelerating     ≥ 80% retained
      Holding          ≥ 40% retained
      Fading           < 40% retained
    """
    if return_5d is None or return_20d is None:
        return {"label": "Unknown", "evidence": "Insufficient return data"}

    r5, r20 = return_5d, return_20d
    abs5, abs20 = abs(r5), abs(r20)

    # De minimis: if both legs are below the noise floor, don't classify.
    if abs5 < DECAY_DE_MINIMIS and abs20 < DECAY_DE_MINIMIS:
        return {
            "label": "Negligible",
            "evidence": f"5d {r5:+.1f}% / 20d {r20:+.1f}% — both below noise threshold",
        }

    # Sign check — treats zero as unsigned (falls through to magnitude)
    same_sign = (r5 > 0 and r20 > 0) or (r5 < 0 and r20 < 0)

    # Sign-flip handling: only call it "Reversed" when BOTH legs are
    # above the noise floor.  A sign flip where the smaller leg is
    # below de-minimis is really just noise around zero — route it
    # through the magnitude path using the dominant leg instead.
    if not same_sign and r5 != 0 and r20 != 0:
        if min(abs5, abs20) >= DECAY_DE_MINIMIS:
            return {
                "label": "Reversed",
                "evidence": f"5d {r5:+.1f}% vs 20d {r20:+.1f}% — direction flipped",
            }
        # else: noisy sign flip — fall through to magnitude logic

    # Magnitude-based classification.  Uses absolute values so the
    # logic works whether the dominant move is positive or negative.
    #
    # When abs20 is zero (or effectively zero) and abs5 is above noise,
    # the move is recent — classify as Accelerating.  When abs5 is zero
    # and abs20 is above noise, the move faded — classify as Fading.
    if abs20 < 1e-9 and abs5 >= DECAY_DE_MINIMIS:
        return {
            "label": "Accelerating",
            "evidence": f"5d move ({r5:+.1f}%) is new vs flat 20d ({r20:+.1f}%)",
        }

    if abs20 > 0 and abs5 >= abs20 * 0.8:
        return {
            "label": "Accelerating",
            "evidence": f"5d move ({r5:+.1f}%) is still intensifying vs 20d ({r20:+.1f}%)",
        }

    if abs20 > 0 and abs5 >= abs20 * 0.4:
        return {
            "label": "Holding",
            "evidence": f"5d {r5:+.1f}% retains most of 20d {r20:+.1f}% move",
        }

    return {
        "label": "Fading",
        "evidence": f"5d {r5:+.1f}% has pulled back from 20d {r20:+.1f}%",
    }


# ---------------------------------------------------------------------------
# Macro context for prompt injection
# ---------------------------------------------------------------------------

def build_macro_context_for_prompt(
    rates: "dict | None" = None,
    stress: "dict | None" = None,
) -> str:
    """Return a compact structured macro backdrop string for injection into
    the LLM analysis prompt.

    Calls compute_rates_context() and compute_stress_regime() if pre-fetched
    dicts are not passed in (uses the existing TTL cache — instant if already
    fetched this request).  Returns an empty string on any failure so the
    prompt degrades gracefully.
    """
    try:
        if rates is None:
            rates = compute_rates_context()
        if stress is None:
            stress = compute_stress_regime()
    except Exception:
        _log.warning("build_macro_context_for_prompt: fetch failed", exc_info=True)
        return ""

    lines: list[str] = [
        "Macro backdrop (calibrate conviction and mechanism direction against this):"
    ]

    # Regime — prefer rates regime label, fall back to stress regime
    regime = (rates.get("regime") or stress.get("regime") or "").replace("_", "-")
    if regime:
        lines.append(f"- Regime: {regime}")

    # 10Y nominal yield
    raw_rates = rates.get("raw", {})
    tnx = raw_rates.get("tnx")
    tnx_chg = raw_rates.get("tnx_change_5d")
    if tnx is not None:
        chg_str = f" ({tnx_chg:+.2f}pp 5d)" if tnx_chg is not None else ""
        lines.append(f"- 10Y nominal: {tnx:.2f}%{chg_str}")

    # Real yield proxy (TIP price change)
    # TIP price UP = bond prices rising = real yields FALLING (inverse relationship)
    tip_chg = raw_rates.get("tip_change_5d")
    if tip_chg is not None:
        direction = "falling" if tip_chg > 0 else "rising"
        lines.append(f"- Real yield proxy (TIP): {tip_chg:+.1f}% 5d ({direction} real yields)")

    # Breakeven proxy
    be = raw_rates.get("breakeven_proxy_5d")
    if be is not None:
        direction = "widening" if be > 0 else "narrowing"
        lines.append(f"- Breakeven proxy: {be:+.2f}pp 5d ({direction} inflation pricing)")

    # VIX
    raw_stress = stress.get("raw", {})
    vix = raw_stress.get("vix")
    vix_avg20 = raw_stress.get("vix_avg20")
    if vix is not None:
        elevated = stress.get("signals", {}).get("vix_elevated", False)
        avg_str = f", 20d avg {vix_avg20:.1f}" if vix_avg20 is not None else ""
        status = " — elevated" if elevated else ""
        lines.append(f"- VIX: {vix:.1f}{avg_str}{status}")

    # Active stress signals
    _sig_labels = {
        "vix_elevated": "VIX elevated",
        "term_inversion": "yield curve inverted",
        "credit_widening": "credit spreads widening",
        "safe_haven_bid": "safe-haven bid active",
        "breadth_deterioration": "breadth deteriorating",
    }
    active_signals = [
        _sig_labels[k]
        for k, v in stress.get("signals", {}).items()
        if v and k in _sig_labels
    ]
    if active_signals:
        lines.append(f"- Active stress signals: {', '.join(active_signals)}")

    # Return empty string if only the header was built (no data)
    if len(lines) == 1:
        return ""

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ticker detail helpers
# ---------------------------------------------------------------------------

def ticker_chart(symbol: str, event_date: str, window: int = 30) -> list[dict]:
    """Return daily closes for a ticker centered on event_date.

    Returns a list of {date, close} dicts spanning ~window days before and
    after the event date.  The event_date index is included so the frontend
    can draw a vertical marker.
    """
    # Never send proxy-annotated symbols to the data provider.
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return []

    try:
        clamped = _clamp_to_market_date(event_date)
        anchor = _date_type.fromisoformat(clamped)
    except (ValueError, TypeError):
        return []

    today = _date_type.today()
    start = (anchor - _timedelta(days=window + 10)).isoformat()
    end = min(anchor + _timedelta(days=window + 10), today).isoformat()

    key = f"chart:{symbol.upper()}:{start}:{end}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    from price_cache import fetch_daily_cached
    data = fetch_daily_cached(symbol, start=start, end=end, auto_adjust=True)
    if data is None or data.empty:
        return []

    # Trim to window
    closes = data["Close"]
    result: list[dict] = []
    for ts, val in closes.items():
        d = str(ts.date())  # type: ignore[union-attr]
        result.append({"date": d, "close": round(float(val), 2)})

    # Trim to roughly window days on each side of the anchor
    anchor_str = event_date
    anchor_idx = None
    for i, r in enumerate(result):
        if r["date"] >= anchor_str:
            anchor_idx = i
            break
    if anchor_idx is not None:
        lo = max(0, anchor_idx - window)
        hi = min(len(result), anchor_idx + window + 1)
        result = result[lo:hi]

    _cache_set(key, result)
    return result


def ticker_info(symbol: str) -> dict:
    """Return compact company info for a ticker.

    Delegates to the active MarketDataProvider.  Returns a flat dict with
    name, sector, industry, market_cap, avg_volume. Missing fields default
    to None.  Cached via the shared ticker cache (10-minute TTL).
    """
    # Strip proxy annotations before hitting the provider.
    symbol = _clean_fetch_symbol(symbol)
    if not symbol:
        return {}
    key = f"info:{symbol.upper()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    from market_data import get_provider
    result = get_provider().fetch_info(symbol)
    _cache_set(key, result)
    return result

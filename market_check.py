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
}

# Flat lookup: ticker → (benchmark_etf, sector_name) for O(1) access.
_TICKER_TO_BENCHMARK: dict[str, tuple[str, str]] = {}
for _sect, (_bench, _members) in SECTOR_BENCHMARKS.items():
    for _t in _members:
        _TICKER_TO_BENCHMARK[_t] = (_bench, _sect)

# Backward compat: callers that imported ENERGY_PROXIES directly.
ENERGY_PROXIES = SECTOR_BENCHMARKS["energy"][1]


def _is_finite(v) -> bool:
    """Return True if *v* is a real finite number (rejects None, NaN, ±inf)."""
    try:
        return v is not None and _math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


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

def _clamp_to_market_date(date_str: str) -> str:
    """Clamp a date string to the latest plausible market date.

    - Future dates → today
    - Weekend dates → preceding Friday
    - Returns a YYYY-MM-DD string that is always <= today and a weekday.
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
        return [
            {**t, "spark": list(t.get("spark") or [])}
            for t in tickers
        ]
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
            # Fresh copy with fresh spark list — no shared references.
            out.append({**t, "spark": list(t.get("spark") or [])})
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
        # Choose fetch strategy and matching return function based on event_date.
        if event_date:
            data   = _fetch_since(ticker, event_date)
            pct_fn = _pct_forward   # returns from iloc[0] (event close) forward
        else:
            data   = _fetch(ticker)
            pct_fn = _pct           # returns from iloc[-(n+1)] to iloc[-1]

        if data is None or len(data) < 6:
            return dict(_no_data)

        # Surface the actual first trading bar when in event-date mode.
        anchor_date = None
        if event_date:
            anchor_date = str(data.index[0].date())

        closes  = data["Close"]
        volumes = data["Volume"]

        # --- Return windows ---
        r1  = pct_fn(closes, 1)
        r5  = pct_fn(closes, 5)
        r20 = pct_fn(closes, 20)

        # Sanity bounds — drop implausibly large returns produced by
        # corrupt source bars (yfinance race, stub price_cache rows
        # like 0.0/1.0/2.0, unadjusted splits).  See
        # ``_RETURN_SANITY_*`` constants at the top of this module.
        r1, r5, r20 = _sanitize_returns(r1, r5, r20)

        # --- Volume: latest day vs 20-day average ---
        latest_vol = float(volumes.iloc[-1])
        avg_vol    = float(volumes.iloc[-20:].mean()) if len(volumes) >= 20 else float(volumes.mean())
        vol_ratio  = latest_vol / avg_vol if avg_vol > 0 else 1.0
        high_volume = vol_ratio >= 1.25   # 25% above average = noteworthy

        # --- Relative return vs sector benchmark ---
        rel_vs_xle = None   # field name kept for API compat
        t_upper = ticker.upper()
        bench_info = _TICKER_TO_BENCHMARK.get(t_upper)
        if bench_info is not None:
            bench_etf, _sector = bench_info
            if t_upper != bench_etf:
                # Try xle_data first (backward compat), then benchmark_cache
                bench_data = None
                if bench_etf == "XLE" and xle_data is not None:
                    bench_data = xle_data
                elif benchmark_cache and bench_etf in benchmark_cache:
                    bench_data = benchmark_cache[bench_etf]
                if bench_data is not None:
                    bench_closes = bench_data["Close"]
                    bench_r5 = pct_fn(bench_closes, 5)
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

        return {
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
        }

    except Exception as e:
        _log.warning("_check_one_ticker(%s) failed: %s", ticker, e, exc_info=True)
        no_data_error = dict(_no_data)
        no_data_error["detail"] = f"Error: {e}"
        return no_data_error


def market_check(
    beneficiary_tickers: list[str],
    loser_tickers: list[str],
    event_date: str | None = None,
) -> dict:
    """Run event-window validation on beneficiary and loser ticker lists.

    event_date: optional 'YYYY-MM-DD'. When provided, returns are computed from
      the event-date close forward. When omitted, uses the rolling 3-month window
      (current-price mode — existing behaviour).

    Returns a 'note' string for the pipeline and per-ticker 'details'.
    This is a rough screen — not proof of anything.
    """
    all_tickers = list(dict.fromkeys(beneficiary_tickers + loser_tickers))  # dedup, preserve order
    if not all_tickers:
        return {"note": "No assets to check.", "details": {}, "tickers": []}

    # Pre-fetch sector benchmark ETFs in parallel.
    benchmark_cache: dict = {}
    xle_data = None
    needed_benchmarks: set[str] = set()
    for t in all_tickers:
        info = _TICKER_TO_BENCHMARK.get(t.upper())
        if info:
            needed_benchmarks.add(info[0])

    def _fetch_bench(etf: str):
        try:
            return etf, (_fetch_since(etf, event_date) if event_date else _fetch(etf))
        except Exception:
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
        spark_src = v.get("spark") or []
        tickers.append({
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
        })

    # Final defensive pass: sanity-bound returns AND suppress
    # cross-contaminated rows.  The sanity scrub catches absurdly
    # large persisted values (e.g. +1348% from corrupt price_cache
    # bars); the dedupe suppression catches yfinance-race
    # cross-contamination.  Both pass over fresh-copy ticker dicts
    # so no shared references leak into the response payload.
    tickers = _scrub_implausible_ticker_returns(tickers)
    tickers = _suppress_duplicate_tickers(tickers)

    result = {"note": note, "details": details, "tickers": tickers}
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
               "return_1d": None, "return_5d": None, "return_20d": None,
               "direction": None, "anchor_date": None}
        if not symbol:
            return None  # filtered out below
        try:
            data = _fetch_since(symbol, event_date)
            if data is None or len(data) < 2:
                return _no
            anchor = str(data.index[0].date())
            closes = data["Close"]
            r1  = _pct_forward(closes, 1)
            r5  = _pct_forward(closes, 5)
            r20 = _pct_forward(closes, 20)
            return {
                "symbol": symbol, "role": role,
                "return_1d":  round(r1,  2) if r1  is not None else None,
                "return_5d":  round(r5,  2) if r5  is not None else None,
                "return_20d": round(r20, 2) if r20 is not None else None,
                "direction":  _direction_tag(r5, role),
                "anchor_date": anchor,
            }
        except Exception:
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
        try:
            data = _fetch_since(ticker, event_date) if event_date else _fetch(ticker)
            if data is not None and len(data) >= 2:
                closes = data["Close"]
                if event_date:
                    entry["value"] = round(float(closes.iloc[0]), 2)
                    chg = _pct_forward(closes, 5) if len(closes) > 5 else None
                else:
                    entry["value"] = round(float(closes.iloc[-1]), 2)
                    chg = _pct(closes, 5) if len(closes) > 5 else None
                if chg is not None:
                    entry["change_5d"] = round(chg, 2)
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
    """Trailing n-period percent change, None if insufficient data."""
    if series is None or len(series) < n + 1:
        return None
    return float((series.iloc[-1] - series.iloc[-(n + 1)]) / series.iloc[-(n + 1)] * 100)


# ---------------------------------------------------------------------------
# Inflation / rates context
# ---------------------------------------------------------------------------
# Three liquid proxies, all available through yfinance:
#   ^TNX  — 10-year nominal yield (CBOE)
#   TIP   — iShares TIPS Bond ETF (moves inversely with real yields)
#   Breakeven ≈ nominal yield move − real yield move
#
# TIP price *falls* when real yields *rise*, so:
#   real_yield_move ≈ −TIP_price_change
# This is a proxy, not an exact number, but directionally reliable for
# the classification we need.

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
            # Use absolute pp change (not _safe_pct) so that nominal_5d is in
            # the same unit as _CHANNEL_SCALE["nominal_yield"] = 0.20 (20 bps).
            # _safe_pct would give the *percentage change in yield level* (e.g.
            # +3.45% for a 15 bps move on a 4.5% yield), inflating z-scores
            # by 20-25× and producing absurd values when old cache rows are
            # near zero (e.g. COVID-era stubs → +2680%).
            end_val = float(closes_tnx.iloc[-1])
            start_val = float(closes_tnx.iloc[-6])
            if _is_finite(end_val) and _is_finite(start_val):
                diff = end_val - start_val
                # Hard cap: ±5 pp (±500 bps) in 5 trading days is beyond any
                # historical extreme; larger values indicate corrupt cache rows.
                nominal_5d = round(diff, 4) if abs(diff) <= 5.0 else None
            if nominal_5d is not None:
                raw["tnx_change_5d"] = round(nominal_5d, 4)
    except Exception:
        _log.warning("compute_rates_context: ^TNX fetch/calc failed", exc_info=True)

    try:
        tip = _fetch("TIP")
        if tip is not None and len(tip) >= 6:
            val = float(tip["Close"].iloc[-1])
            raw["tip"] = round(val, 2)
            tip_5d = _safe_pct(tip["Close"], 5)
            if tip_5d is not None:
                raw["tip_change_5d"] = round(tip_5d, 2)
    except Exception:
        _log.warning("compute_rates_context: TIP fetch/calc failed", exc_info=True)

    # Breakeven proxy: if nominals rise and TIP price is flat,
    # breakevens are widening.  Approximate as nominal_move + tip_move
    # (since TIP moves inversely with real yields).
    if nominal_5d is not None and tip_5d is not None:
        be_proxy = nominal_5d + tip_5d
        raw["breakeven_proxy_5d"] = round(be_proxy, 2)

    regime = classify_rates_regime(nominal_5d, tip_5d)

    return {
        "regime": regime,
        "nominal": {
            "label": "10Y yield",
            "value": raw.get("tnx"),
            "change_5d": raw.get("tnx_change_5d"),
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

# Thresholds for 20-day return classification
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
            ret_20d = _safe_pct(data["Close"], 20)
            if ret_20d is not None:
                ret_20d = round(ret_20d, 2)
    except Exception:
        pass

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
            vix_now = float(vix_data["Close"].iloc[-1])
            vix_avg20 = float(vix_data["Close"].iloc[-20:].mean())
            raw["vix"] = round(vix_now, 2)
            raw["vix_avg20"] = round(vix_avg20, 2)
            vix_5d = _safe_pct(vix_data["Close"], 5)
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
            vix3m = float(vix3m_data["Close"].iloc[-1])
            raw["vix3m"] = round(vix3m, 2)
            signals["term_inversion"] = (vix_now or 0) > vix3m
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

    # --- Credit Stress: HYG vs SHY ---
    try:
        hyg_data = _fetch("HYG")
        shy_data = _fetch("SHY")
        if hyg_data is not None and shy_data is not None:
            hyg_5d = _safe_pct(hyg_data["Close"], 5)
            shy_5d = _safe_pct(shy_data["Close"], 5)
            if hyg_5d is not None and shy_5d is not None:
                spread_move = shy_5d - hyg_5d
                raw["credit_spread_5d"] = round(spread_move, 2)
                signals["credit_widening"] = spread_move > 0.5
                if signals["credit_widening"]:
                    expl = f"High-yield bonds underperforming treasuries by {abs(raw['credit_spread_5d']):.1f}% over 5d — credit stress rising"
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
                    "explanation": "Credit spread data insufficient",
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
            r = _safe_pct(d["Close"], 5) if d is not None else None
            haven_detail[name] = round(r, 2) if r is not None else None
            if r is not None:
                haven_returns.append(r)
        inflows = sum(1 for v in haven_detail.values() if v is not None and v > 0.3)
        if haven_returns:
            avg_haven = sum(haven_returns) / len(haven_returns)
            raw["haven_avg_5d"] = round(avg_haven, 2)
            signals["safe_haven_bid"] = avg_haven > 0.5
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
            rsp_5d = _safe_pct(rsp_data["Close"], 5)
            spy_5d = _safe_pct(spy_data["Close"], 5)
            if rsp_5d is not None and spy_5d is not None:
                breadth_gap = rsp_5d - spy_5d
                raw["breadth_gap_5d"] = round(breadth_gap, 2)
                signals["breadth_deterioration"] = breadth_gap < -0.5
                if signals["breadth_deterioration"]:
                    expl = f"Equal-weight lagging cap-weight by {abs(raw['breadth_gap_5d']):.1f}% — narrow leadership, fewer stocks participating"
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
                    "explanation": "Breadth data insufficient",
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

    if _failed_signals:
        _log.warning("compute_stress_regime: %d of 5 signals failed: %s",
                      len(_failed_signals), ", ".join(_failed_signals))

    regime = classify_regime(signals)

    # One-sentence summary
    active_count = sum(signals.values())
    if active_count == 0:
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

    # Sign check — treats zero as unsigned (falls through to magnitude checks)
    same_sign = (r5 > 0 and r20 > 0) or (r5 < 0 and r20 < 0)

    # Reversed: different signs and at least one leg is above de minimis.
    # The old check required both legs > 0.5%, which missed genuine reversals
    # where one leg was modest (e.g. r5=-0.3%, r20=+0.8%).
    if not same_sign and r5 != 0 and r20 != 0 and max(abs5, abs20) >= DECAY_DE_MINIMIS:
        return {
            "label": "Reversed",
            "evidence": f"5d {r5:+.1f}% vs 20d {r20:+.1f}% — direction flipped",
        }

    if same_sign and abs5 >= abs20 * 0.8:
        return {
            "label": "Accelerating",
            "evidence": f"5d move ({r5:+.1f}%) is still intensifying vs 20d ({r20:+.1f}%)",
        }

    if same_sign and abs5 >= abs20 * 0.4:
        return {
            "label": "Holding",
            "evidence": f"5d {r5:+.1f}% retains most of 20d {r20:+.1f}% move",
        }

    return {
        "label": "Fading",
        "evidence": f"5d {r5:+.1f}% has pulled back from 20d {r20:+.1f}%",
    }


# ---------------------------------------------------------------------------
# Ticker detail helpers
# ---------------------------------------------------------------------------

def ticker_chart(symbol: str, event_date: str, window: int = 30) -> list[dict]:
    """Return daily closes for a ticker centered on event_date.

    Returns a list of {date, close} dicts spanning ~window days before and
    after the event date.  The event_date index is included so the frontend
    can draw a vertical marker.
    """
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
    key = f"info:{symbol.upper()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    from market_data import get_provider
    result = get_provider().fetch_info(symbol)
    _cache_set(key, result)
    return result

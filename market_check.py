# market_check.py
# Runs a basic event-window validation on two lists of tickers:
# beneficiary_tickers and loser_tickers.
# Computes 1-day, 5-day, and 20-day returns plus a volume check.
# For sector tickers, computes return relative to a sector benchmark ETF.
# Evaluates whether each ticker moved in the direction the hypothesis predicts.
# This is a rough screen — not proof of anything.

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


def _pct(series, periods: int) -> float | None:
    """Percentage change over the last N periods (rolling / current-price mode)."""
    if len(series) < periods + 1:
        return None
    return float((series.iloc[-1] - series.iloc[-(periods + 1)]) / series.iloc[-(periods + 1)] * 100)


def _pct_forward(series, periods: int) -> float | None:
    """Percentage change from series[0] to series[periods] (event-date-anchored mode)."""
    if len(series) < periods + 1:
        return None
    return float((series.iloc[periods] - series.iloc[0]) / series.iloc[0] * 100)


import time as _time
from concurrent.futures import ThreadPoolExecutor as _TPE

# Max parallel yfinance downloads. 6 keeps us under typical rate-limit
# thresholds while still being 5-6x faster than serial.
_MAX_FETCH_WORKERS = 6

# ---------------------------------------------------------------------------
# In-memory TTL cache for ticker data
# ---------------------------------------------------------------------------
# Avoids redundant yfinance downloads within the same analysis session.
# Keyed by (ticker, mode, start_date). Short TTL: 10 minutes.

_TICKER_CACHE: dict[str, tuple[float, object]] = {}
_TICKER_CACHE_TTL = 600  # 10 minutes


def _cache_get(key: str):
    """Return cached value or None if missing/expired.

    Uses pop() instead of del to avoid KeyError races when multiple
    ThreadPoolExecutor threads expire the same key simultaneously.
    """
    entry = _TICKER_CACHE.get(key)
    if entry is None:
        return None
    ts, val = entry
    if (_time.monotonic() - ts) > _TICKER_CACHE_TTL:
        _TICKER_CACHE.pop(key, None)  # atomic under CPython GIL; no KeyError
        return None
    return val


def _cache_set(key: str, val: object) -> None:
    _TICKER_CACHE[key] = (_time.monotonic(), val)


def _fetch(ticker: str):
    """Download ~3 months of daily data for one ticker. Returns a DataFrame or None."""
    key = f"fetch:{ticker.upper()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    import yfinance as yf
    data = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
    if data.empty:
        return None
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)
    _cache_set(key, data)
    return data


def _fetch_since(ticker: str, start_date: str):
    """Download daily data from start_date to today. Returns a DataFrame or None."""
    key = f"since:{ticker.upper()}:{start_date}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    import yfinance as yf
    data = yf.download(ticker, start=start_date, interval="1d", progress=False, auto_adjust=True)
    if data.empty:
        return None
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)
    _cache_set(key, data)
    return data


def _direction_tag(r5: float | None, role: str) -> str | None:
    """Return a direction tag based on 5-day return and the ticker's predicted role.

    Logic:
      beneficiary + up   → hypothesis says this should rise  → supports ↑
      beneficiary + down → moves against the prediction       → contradicts ↓
      loser       + down → hypothesis says this should fall   → supports ↓
      loser       + up   → moves against the prediction       → contradicts ↑

    Returns None when r5 is unavailable (not enough data).
    """
    if r5 is None:
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
    tickers = [
        {
            "symbol":       t,
            "role":         role_map.get(t, "beneficiary"),
            "label":        v["label"],
            "direction_tag": v["direction"],
            "return_1d":    v.get("return_1d"),
            "return_5d":    v.get("return_5d"),
            "return_20d":   v.get("return_20d"),
            "volume_ratio": v.get("volume_ratio"),
            "vs_xle_5d":    v.get("vs_xle_5d"),
            "spark":        v.get("spark", []),
        }
        for t, v in details.items()
    ]

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
# Macro context snapshot — yfinance-backed
# ---------------------------------------------------------------------------
# Uses the same _fetch/_fetch_since/caching infrastructure as ticker checks.
# Each instrument is fetched in parallel via ThreadPoolExecutor.

# (yfinance symbol, display label, unit)
_MACRO_INSTRUMENTS: list[tuple[str, str, str]] = [
    ("DX-Y.NYB",  "USD",   "idx"),     # US Dollar Index
    ("^TNX",      "10Y",   "%"),        # 10-year Treasury yield
    ("^VIX",      "VIX",   ""),         # CBOE VIX
    ("CL=F",      "WTI",   "$/bbl"),    # WTI crude futures
    ("BZ=F",      "Brent", "$/bbl"),    # Brent crude futures
]


def macro_snapshot(event_date: str | None = None) -> list[dict]:
    """Return a compact macro context strip for the given date.

    Each entry: {label, value, change_5d, unit}.
    Uses the existing yfinance fetch layer with its 10-minute TTL cache.
    Returns partial results on failure — never raises.
    """
    # Fetched serially: yfinance is not thread-safe for concurrent downloads.
    # With the 10-min TTL cache, second+ calls resolve from memory instantly.
    results: list[dict] = []
    for yf_ticker, label, unit in _MACRO_INSTRUMENTS:
        entry: dict = {"label": label, "value": None, "change_5d": None, "unit": unit}
        try:
            data = _fetch_since(yf_ticker, event_date) if event_date else _fetch(yf_ticker)
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
            pass
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


def compute_stress_regime() -> dict:
    """Compute a composite market-stress regime from live data.

    Returns {regime, signals: {vix_elevated, term_inversion, credit_widening,
    safe_haven_bid, breadth_deterioration}, raw: {vix, vix_avg20, ...}}.
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

    try:
        # VIX vs 20d average
        vix_data = _fetch("^VIX")
        if vix_data is not None and len(vix_data) >= 20:
            vix_now = float(vix_data["Close"].iloc[-1])
            vix_avg20 = float(vix_data["Close"].iloc[-20:].mean())
            raw["vix"] = round(vix_now, 2)
            raw["vix_avg20"] = round(vix_avg20, 2)
            vix_5d = _safe_pct(vix_data["Close"], 5)
            if vix_5d is not None:
                raw["vix_change_5d"] = round(vix_5d, 2)
            signals["vix_elevated"] = vix_now > vix_avg20 * 1.20  # >20% above 20d avg

        # VIX term structure: ^VIX vs ^VIX3M
        vix3m_data = _fetch("^VIX3M")
        if vix_data is not None and vix3m_data is not None and len(vix3m_data) > 0:
            vix_now = float(vix_data["Close"].iloc[-1]) if "vix" not in raw else raw["vix"]
            vix3m = float(vix3m_data["Close"].iloc[-1])
            raw["vix3m"] = round(vix3m, 2)
            signals["term_inversion"] = vix_now > vix3m  # backwardation = stress

        # Credit spread direction: HYG vs SHY 5d relative
        hyg_data = _fetch("HYG")
        shy_data = _fetch("SHY")
        if hyg_data is not None and shy_data is not None:
            hyg_5d = _safe_pct(hyg_data["Close"], 5)
            shy_5d = _safe_pct(shy_data["Close"], 5)
            if hyg_5d is not None and shy_5d is not None:
                spread_move = shy_5d - hyg_5d  # positive = widening
                raw["credit_spread_5d"] = round(spread_move, 2)
                signals["credit_widening"] = spread_move > 0.5

        # Safe-haven composite: GLD, DXY, TLT — average 5d return
        haven_returns: list[float] = []
        for sym in ["GLD", "DX-Y.NYB", "TLT"]:
            d = _fetch(sym)
            if d is not None:
                r = _safe_pct(d["Close"], 5)
                if r is not None:
                    haven_returns.append(r)
        if haven_returns:
            avg_haven = sum(haven_returns) / len(haven_returns)
            raw["haven_avg_5d"] = round(avg_haven, 2)
            signals["safe_haven_bid"] = avg_haven > 0.5

        # Breadth proxy: RSP vs SPY 5d relative
        rsp_data = _fetch("RSP")
        spy_data = _fetch("SPY")
        if rsp_data is not None and spy_data is not None:
            rsp_5d = _safe_pct(rsp_data["Close"], 5)
            spy_5d = _safe_pct(spy_data["Close"], 5)
            if rsp_5d is not None and spy_5d is not None:
                breadth_gap = rsp_5d - spy_5d
                raw["breadth_gap_5d"] = round(breadth_gap, 2)
                signals["breadth_deterioration"] = breadth_gap < -0.5

    except Exception:
        pass

    regime = classify_regime(signals)
    return {"regime": regime, "signals": signals, "raw": raw}


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

def classify_decay(return_5d: float | None, return_20d: float | None) -> dict:
    """Classify the trajectory of a ticker's post-event move.

    Compares the 5d and 20d returns to determine whether the shock is
    accelerating, holding, fading, or reversed.

    Returns {label, evidence} where evidence is a one-line explanation.
    """
    if return_5d is None or return_20d is None:
        return {"label": "Unknown", "evidence": "Insufficient return data"}

    r5, r20 = return_5d, return_20d

    # Same sign check
    same_sign = (r5 > 0 and r20 > 0) or (r5 < 0 and r20 < 0)

    if not same_sign and abs(r5) > 0.5 and abs(r20) > 0.5:
        return {
            "label": "Reversed",
            "evidence": f"5d {r5:+.1f}% vs 20d {r20:+.1f}% — direction flipped",
        }

    abs5, abs20 = abs(r5), abs(r20)

    if same_sign and abs5 > abs20 * 0.8:
        return {
            "label": "Accelerating",
            "evidence": f"5d move ({r5:+.1f}%) is still intensifying vs 20d ({r20:+.1f}%)",
        }

    if same_sign and abs5 > abs20 * 0.4:
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

from datetime import date as _date, timedelta as _timedelta


def ticker_chart(symbol: str, event_date: str, window: int = 30) -> list[dict]:
    """Return daily closes for a ticker centered on event_date.

    Returns a list of {date, close} dicts spanning ~window days before and
    after the event date.  The event_date index is included so the frontend
    can draw a vertical marker.
    """
    try:
        anchor = _date.fromisoformat(event_date)
    except (ValueError, TypeError):
        return []

    start = (anchor - _timedelta(days=window + 10)).isoformat()  # pad for weekends
    end = (anchor + _timedelta(days=window + 10)).isoformat()

    import yfinance as yf
    key = f"chart:{symbol.upper()}:{start}:{end}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        data = yf.download(symbol, start=start, end=end, interval="1d",
                           progress=False, auto_adjust=True)
        if data.empty:
            return []
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)
    except Exception:
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

    Uses yfinance's .info property, cached aggressively (1 hour via the
    ticker cache). Returns a flat dict with name, sector, industry,
    market_cap, avg_volume. Missing fields default to None.
    """
    key = f"info:{symbol.upper()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    fallback: dict = {
        "symbol": symbol.upper(),
        "name": None, "sector": None, "industry": None,
        "market_cap": None, "avg_volume": None,
    }

    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info or {}
        result = {
            "symbol": symbol.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "avg_volume": info.get("averageVolume"),
        }
    except Exception:
        result = fallback

    _cache_set(key, result)
    return result

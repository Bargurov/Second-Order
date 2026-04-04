# market_check.py
# Runs a basic event-window validation on two lists of tickers:
# beneficiary_tickers and loser_tickers.
# Computes 1-day, 5-day, and 20-day returns plus a volume check.
# For energy/commodity tickers, also computes return relative to XLE.
# Evaluates whether each ticker moved in the direction the hypothesis predicts.
# This is a rough screen — not proof of anything.

# Tickers where a relative-to-XLE comparison makes sense.
ENERGY_PROXIES = {"XLE", "XOM", "CVX", "COP", "SLB", "HAL", "MPC", "VLO",
                  "USO", "UNG", "BNO", "OIH"}


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


def _fetch(ticker: str):
    """Download ~3 months of daily data for one ticker. Returns a DataFrame or None."""
    import yfinance as yf
    data = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
    if data.empty:
        return None
    # yfinance sometimes returns MultiIndex columns — flatten them
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)
    return data


def _is_valid_ticker(ticker: str) -> bool:
    """Quick 5-day availability probe before the full download.

    Downloads only 5 days of data to check whether yfinance has anything for
    this ticker symbol. Returns True if at least one row comes back.
    The short window keeps the probe fast; the full 3-month fetch only runs
    when this check passes.
    """
    import yfinance as yf
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=True)
        return not data.empty
    except Exception:
        return False


def _fetch_since(ticker: str, start_date: str):
    """Download daily data from start_date to today. Returns a DataFrame or None.

    start_date: 'YYYY-MM-DD' string. Used when the caller wants returns anchored
    to the event date rather than a rolling trailing window.
    """
    import yfinance as yf
    data = yf.download(ticker, start=start_date, interval="1d", progress=False, auto_adjust=True)
    if data.empty:
        return None
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)
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
    if role == "beneficiary":
        return "supports ↑" if r5 >= 0 else "contradicts ↓"
    else:  # loser
        return "supports ↓" if r5 <= 0 else "contradicts ↑"


def _check_one_ticker(
    ticker: str,
    role: str = "beneficiary",
    xle_data=None,
    event_date: str | None = None,
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
    # Quick availability probe — skip the full download for invalid/unknown tickers.
    # In event-date mode we skip this: a ticker may have no recent 5-day data
    # (e.g. delisted or acquired) yet have perfectly good historical data around
    # the event date.  The historical fetch itself acts as the validity check.
    if not event_date and not _is_valid_ticker(ticker):
        return {
            "label":        "needs more evidence",
            "detail":       "Invalid or unavailable ticker.",
            "direction":    None,
            "return_1d":    None,
            "return_5d":    None,
            "return_20d":   None,
            "volume_ratio": None,
            "vs_xle_5d":    None,
        }

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

        # --- Relative return vs XLE (energy sector benchmark) ---
        rel_vs_xle = None
        if xle_data is not None and ticker.upper() in ENERGY_PROXIES and ticker.upper() != "XLE":
            xle_closes = xle_data["Close"]
            xle_r5 = pct_fn(xle_closes, 5)   # same function keeps the comparison consistent
            if r5 is not None and xle_r5 is not None:
                rel_vs_xle = r5 - xle_r5

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

    # Pre-fetch XLE once so we don't re-download it for every energy ticker.
    # Use the same fetch strategy as the tickers for a consistent comparison.
    xle_data = None
    needs_xle = any(t.upper() in ENERGY_PROXIES for t in all_tickers)
    if needs_xle:
        try:
            xle_data = _fetch_since("XLE", event_date) if event_date else _fetch("XLE")
        except Exception:
            pass   # XLE fetch failing is non-fatal

    # Build a role lookup so _check_one_ticker knows which camp each ticker is in.
    # If a ticker appears in both lists, beneficiary takes precedence.
    role_map: dict[str, str] = {}
    for t in loser_tickers:
        role_map[t] = "loser"
    for t in beneficiary_tickers:
        role_map[t] = "beneficiary"  # beneficiary overwrites if duplicated

    details = {}
    for ticker in all_tickers:
        role = role_map.get(ticker, "beneficiary")
        details[ticker] = _check_one_ticker(ticker, role=role, xle_data=xle_data, event_date=event_date)

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

    results: list[dict] = []
    for t in tickers:
        symbol = t.get("symbol", "")
        role   = t.get("role", "beneficiary")
        if not symbol:
            continue

        try:
            data = _fetch_since(symbol, event_date)
            if data is None or len(data) < 2:
                results.append({
                    "symbol": symbol, "role": role,
                    "return_1d": None, "return_5d": None, "return_20d": None,
                    "direction": None, "anchor_date": None,
                })
                continue

            anchor = str(data.index[0].date())
            closes = data["Close"]
            r1  = _pct_forward(closes, 1)
            r5  = _pct_forward(closes, 5)
            r20 = _pct_forward(closes, 20)

            results.append({
                "symbol":      symbol,
                "role":        role,
                "return_1d":   round(r1,  2) if r1  is not None else None,
                "return_5d":   round(r5,  2) if r5  is not None else None,
                "return_20d":  round(r20, 2) if r20 is not None else None,
                "direction":   _direction_tag(r5, role),
                "anchor_date": anchor,
            })
        except Exception:
            results.append({
                "symbol": symbol, "role": role,
                "return_1d": None, "return_5d": None, "return_20d": None,
                "direction": None, "anchor_date": None,
            })

    return results

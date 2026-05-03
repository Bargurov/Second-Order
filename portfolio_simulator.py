"""Pure position-simulator logic.

No I/O or DB calls — callers load event dicts and pass them in.
This keeps the module trivially testable and independently composable.
"""

from __future__ import annotations

import math
from collections import defaultdict

_HORIZON_DAY: dict[str, int] = {"1d": 1, "5d": 5, "20d": 20}
_HORIZON_FIELD: dict[str, str] = {
    "1d": "return_1d",
    "5d": "return_5d",
    "20d": "return_20d",
}


def _best_return(
    ticker: dict,
    revisit_snapshots: list[dict],
    horizon: str,
) -> tuple[float | None, str]:
    """Return (value_pct, source) for the ticker at the requested horizon.

    Source is "revisit", "market_check", or "missing".
    Revisit snapshots are preferred — they represent validated follow-through
    captured after the event.  Falls back to the stored market_check return.
    NaN / inf values are treated as missing.
    """
    day = _HORIZON_DAY[horizon]
    field = _HORIZON_FIELD[horizon]
    symbol = (ticker.get("symbol") or "").upper()

    # 1. Try the matching revisit snapshot
    for snap in revisit_snapshots:
        if snap.get("day") == day:
            for rt in snap.get("tickers") or []:
                if (rt.get("symbol") or "").upper() == symbol:
                    raw = rt.get(field)
                    if raw is not None:
                        try:
                            val = float(raw)
                        except (TypeError, ValueError):
                            break
                        if math.isfinite(val):
                            return (val, "revisit")
            break  # snapshot for this day exists but ticker absent / non-finite

    # 2. Fall back to stored market_check return
    raw = ticker.get(field)
    if raw is not None:
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return (None, "missing")
        if math.isfinite(val):
            return (val, "market_check")

    return (None, "missing")


def simulate_portfolio(
    events: list[dict],
    horizon: str = "5d",
    include_shorts: bool = False,
    direction_filter: str = "all",
) -> dict:
    """Simulate a portfolio across the provided event dicts.

    Parameters
    ----------
    events:
        Fully decoded event dicts (market_tickers + revisit_snapshots populated).
    horizon:
        "1d", "5d", or "20d".
    include_shorts:
        When True, loser-role positions are entered short (return sign flipped).
    direction_filter:
        "all" = all role-eligible tickers;
        "supporting" = only tickers with direction_tag startswith "supports".

    Returns
    -------
    { "summary": {...}, "positions": [...], "warnings": [...] }
    """
    if horizon not in _HORIZON_DAY:
        horizon = "5d"

    # ------------------------------------------------------------------
    # Phase 1: build position list per event
    # ------------------------------------------------------------------
    all_positions: list[dict] = []
    events_per_symbol: dict[str, set[int]] = defaultdict(set)

    for ev in events:
        event_id = ev.get("id")
        tickers = [t for t in (ev.get("market_tickers") or []) if isinstance(t, dict)]
        revisits = ev.get("revisit_snapshots") or []

        included: list[dict] = []
        for t in tickers:
            symbol = (t.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            role = (t.get("role") or "beneficiary").lower()
            dtag = t.get("direction_tag") or ""

            if direction_filter == "supporting" and not dtag.startswith("supports"):
                continue
            if role == "loser" and not include_shorts:
                continue

            included.append((symbol, role, dtag, t))

        # Events with no usable tickers are skipped from positions but
        # still counted in events_requested / events_with_data.
        if not included:
            continue

        for symbol, role, dtag, ticker in included:
            is_short = role == "loser" and include_shorts
            gross_return, source = _best_return(ticker, revisits, horizon)

            portfolio_return: float | None = None
            if gross_return is not None:
                portfolio_return = -gross_return if is_short else gross_return

            all_positions.append({
                "event_id": event_id,
                "event_headline": ev.get("headline", ""),
                "event_date": ev.get("event_date"),
                "event_confidence": ev.get("confidence"),
                "symbol": symbol,
                "role": role,
                "direction_tag": dtag or None,
                "gross_return": round(gross_return, 4) if gross_return is not None else None,
                "portfolio_return": round(portfolio_return, 4) if portfolio_return is not None else None,
                "return_source": source,
                "short": is_short,
                "_n_siblings": len(included),  # used for weighting, stripped later
            })
            if portfolio_return is not None:
                events_per_symbol[symbol].add(event_id)

    # ------------------------------------------------------------------
    # Phase 2: assign weights (equal-event, equal-position within event)
    # ------------------------------------------------------------------
    # Count how many events contributed at least one position
    contributing_event_ids = {p["event_id"] for p in all_positions}
    n_contributing = len(contributing_event_ids)

    for p in all_positions:
        if n_contributing > 0:
            p["weight"] = round(1.0 / n_contributing / p["_n_siblings"], 8)
        else:
            p["weight"] = 0.0
        del p["_n_siblings"]

    # ------------------------------------------------------------------
    # Phase 3: summary
    # ------------------------------------------------------------------
    with_data = [p for p in all_positions if p["portfolio_return"] is not None]
    data_weight = sum(p["weight"] for p in with_data)

    portfolio_return_val: float | None = None
    win_rate: float | None = None
    if with_data and data_weight > 0:
        weighted_sum = sum(p["weight"] * p["portfolio_return"] for p in with_data)
        portfolio_return_val = round(weighted_sum / data_weight, 4)
        winners = sum(1 for p in with_data if p["portfolio_return"] > 0)
        win_rate = round(winners / len(with_data), 4)

    events_with_data_ids = {p["event_id"] for p in with_data}

    summary = {
        "events_requested": len(events),
        "events_contributing": n_contributing,
        "events_with_data": len(events_with_data_ids),
        "positions_total": len(all_positions),
        "positions_with_data": len(with_data),
        "portfolio_return": portfolio_return_val,
        "data_coverage": round(data_weight, 4),
        "win_rate": win_rate,
        "horizon": horizon,
        "include_shorts": include_shorts,
        "direction_filter": direction_filter,
    }

    # ------------------------------------------------------------------
    # Phase 4: warnings
    # ------------------------------------------------------------------
    warnings: list[dict] = []

    # Concentration: symbol appears across multiple distinct events
    weight_by_symbol: dict[str, float] = defaultdict(float)
    for p in all_positions:
        weight_by_symbol[p["symbol"]] += p["weight"]

    # Only flag symbols that actually had data (events_per_symbol was built from with_data)
    for sym, ev_ids in sorted(events_per_symbol.items()):
        count = len(ev_ids)
        if count > 1:
            total_w = weight_by_symbol.get(sym, 0.0)
            warnings.append({
                "type": "concentration",
                "symbol": sym,
                "event_count": count,
                "total_weight": round(total_w, 4),
                "message": (
                    f"{sym} appears across {count} events "
                    f"({round(total_w * 100, 1)}\u202f% of portfolio weight)"
                ),
            })

    # Missing data: positions with no return at this horizon
    missing_event_ids = {
        p["event_id"] for p in all_positions if p["return_source"] == "missing"
    }
    # Also events that were filtered to zero positions
    events_with_no_positions = {
        ev.get("id") for ev in events
        if ev.get("id") not in contributing_event_ids
    }
    all_missing = missing_event_ids | events_with_no_positions
    if all_missing:
        n = len(all_missing)
        warnings.append({
            "type": "missing_data",
            "event_count": n,
            "message": (
                f"{n}\u00a0event{'s' if n != 1 else ''} contributed no return data "
                f"at {horizon} horizon"
            ),
        })

    # Low confidence
    low_conf_ids = {
        p["event_id"] for p in all_positions
        if (p.get("event_confidence") or "").lower() in ("low", "very_low")
    }
    if low_conf_ids:
        n = len(low_conf_ids)
        warnings.append({
            "type": "low_confidence",
            "event_count": n,
            "message": (
                f"{n}\u00a0event{'s' if n != 1 else ''} rated low confidence \u2014 "
                "signal quality may be reduced"
            ),
        })

    # Sort warnings deterministically
    warnings.sort(key=lambda w: (w["type"], w.get("symbol", "")))

    return {
        "summary": summary,
        "positions": all_positions,
        "warnings": warnings,
    }

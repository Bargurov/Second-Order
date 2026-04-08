"""
market_context.py

A single normalized "market context" surface that composes:
  1. Liquid benchmark snapshots (from the warm SnapshotStore)
  2. Stress regime
  3. Recent market movers / highlights

Design:
  - This module owns the *composition* shape and the small helpers that
    summarise each section.  It does NOT fetch anything itself.
  - The /market-context route in api.py orchestrates the underlying calls
    (snapshots, stress, movers) with try/except wrappers and passes the
    fetched parts into compose_market_context().  This split keeps the
    composer pure and trivially testable.
  - No new cold-fetch logic: snapshots come from the warm path, stress
    and movers reuse the existing api.py logic which goes through the
    shared TTL cache.
  - Freshness/source metadata is carried at two levels:
      * top-level: built_at, source (active provider name)
      * per-snapshot: fetched_at, stale, error (already on each snapshot)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

_log = logging.getLogger("second_order.market_context")


# ---------------------------------------------------------------------------
# Provider name detection
# ---------------------------------------------------------------------------

def _provider_name() -> str:
    """Return the active market data provider name, or 'unknown' on failure."""
    try:
        from market_data import PolygonProvider, get_provider
        p = get_provider()
        if isinstance(p, PolygonProvider):
            return "polygon"
        cls = type(p).__name__
        if "YFinance" in cls or "Yfinance" in cls:
            return "yfinance"
        return cls.lower() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Section summarisers
# ---------------------------------------------------------------------------

def _summarize_snapshots(snapshots: list[dict]) -> dict:
    """Count fresh / stale / unavailable snapshots in the list."""
    total = len(snapshots)
    fresh = 0
    stale = 0
    unavailable = 0
    for s in snapshots:
        value = s.get("value")
        error = s.get("error")
        if value is None or error is not None:
            unavailable += 1
        elif s.get("stale"):
            stale += 1
        else:
            fresh += 1
    return {
        "total": total,
        "fresh": fresh,
        "stale": stale,
        "unavailable": unavailable,
    }


def _normalize_stress(stress: Optional[dict]) -> dict:
    """Return a stress-regime dict, falling back to a degraded shape."""
    if stress is None or not isinstance(stress, dict):
        return {
            "regime": "Unknown",
            "summary": "Stress computation unavailable",
            "signals": {},
            "raw": {},
            "detail": {},
            "available": False,
        }
    out = dict(stress)
    out.setdefault("available", True)
    return out


def _summarize_highlights(highlights: list[dict]) -> dict:
    return {
        "count": len(highlights),
        "source": "movers/today",
    }


# ---------------------------------------------------------------------------
# Pure composer — no I/O, fully testable with mock data
# ---------------------------------------------------------------------------

def compose_market_context(
    snapshots: list[dict],
    stress: Optional[dict],
    highlights: list[dict],
    *,
    source: Optional[str] = None,
) -> dict:
    """Combine the three pre-fetched sections into the unified context object.

    All sections are optional — pass empty lists / None when a fetch failed
    and the resulting context will simply mark that section as degraded.

    Returns a dict with this shape:
      {
        built_at:        ISO 8601 UTC timestamp string
        source:          "yfinance" / "polygon" / "unknown"
        snapshots:       list[snapshot dict]   (per-market freshness inside)
        snapshots_meta:  {total, fresh, stale, unavailable}
        stress:          stress regime dict   (with `available` flag)
        highlights:      list[mover dict]
        highlights_meta: {count, source}
      }
    """
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source or _provider_name(),
        "snapshots": list(snapshots or []),
        "snapshots_meta": _summarize_snapshots(snapshots or []),
        "stress": _normalize_stress(stress),
        "highlights": list(highlights or []),
        "highlights_meta": _summarize_highlights(highlights or []),
    }

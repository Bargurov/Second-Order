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


def _compose_snapshot_freshness_note(
    snapshots: list[dict], meta: dict,
) -> Optional[str]:
    """Operator-readable explanation of why snapshots are not all fresh.

    Returns ``None`` when every snapshot is fresh — UI consumers branch
    on presence to decide whether to render the strip's status footer.
    Stale (cached but past TTL) and unavailable (no value, or provider
    error) are explained separately in product-facing language; the
    note never refers to internal terms like ``not_refreshed`` directly,
    but it does distinguish "not refreshed yet" from a real provider
    failure so the operator sees the truthful state.

    Pure read; never refreshes, never touches the snapshot store.
    """
    total       = int(meta.get("total")       or 0)
    fresh       = int(meta.get("fresh")       or 0)
    stale       = int(meta.get("stale")       or 0)
    unavailable = int(meta.get("unavailable") or 0)

    if total == 0:
        return "Benchmark snapshots are not available right now."
    if fresh == total:
        return None

    # When every unavailable row is the placeholder, the store has not
    # warmed yet — distinct from a real provider outage.
    placeholders_only = unavailable > 0 and all(
        (s.get("error") or "") == "not_refreshed"
        for s in snapshots
        if s.get("value") is None or s.get("error") is not None
    )

    parts: list[str] = []
    if stale > 0:
        if stale == total:
            parts.append(
                "All benchmark values are cached from the most recent "
                "refresh and may lag the live tape."
            )
        else:
            parts.append(
                f"{stale} of {total} benchmark values are cached and "
                f"may lag the live tape."
            )
    if unavailable > 0:
        if placeholders_only:
            if unavailable == total:
                parts.append(
                    "Benchmark snapshots have not been refreshed yet — "
                    "live values will appear once the next refresh runs."
                )
            else:
                parts.append(
                    f"{unavailable} of {total} benchmarks have not been "
                    f"refreshed yet."
                )
        else:
            if unavailable == total:
                parts.append(
                    "All benchmarks failed to refresh from the data "
                    "provider; values are unavailable."
                )
            else:
                parts.append(
                    f"{unavailable} of {total} benchmarks failed to "
                    f"refresh from the data provider; their values are "
                    f"unavailable."
                )
    return " ".join(parts) if parts else None


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

def _normalize_rates(rates: Optional[dict]) -> dict:
    """Ensure rates context always has a stable shape."""
    if not rates or not isinstance(rates, dict):
        return {"available": False, "regime": "Unknown"}
    out = dict(rates)
    out.setdefault("available", True)
    return out


def _normalize_regime_vector(vec: Optional[dict]) -> dict:
    """Ensure regime vector always has a stable shape."""
    if not vec or not isinstance(vec, dict):
        return {"available": False}
    out = dict(vec)
    out.setdefault("available", True)
    return out


def _normalize_uncertainty_concentration(uc: Optional[dict]) -> dict:
    """Ensure uncertainty_concentration always has a stable fallback shape."""
    if not uc or not isinstance(uc, dict):
        return {"available": False, "uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}
    out = dict(uc)
    out.setdefault("available", True)
    return out


# ---------------------------------------------------------------------------
# Product-facing explanations for the A/B card layout.  Static copy: each
# entry says what the card means and what would change it.  No data,
# no provider calls, no scoring — pure read so the composer stays trivially
# testable and the backend can ship demo-ready text without coupling to
# any runtime state.  Keep entries short (≤ ~25 words each); the UI lays
# them out under each card title.
# ---------------------------------------------------------------------------
_CONTEXT_EXPLANATIONS: dict[str, dict[str, str]] = {
    "snapshots": {
        "meaning": (
            "Live (or recently-cached) prices and 1d/5d changes for the "
            "core liquid benchmarks — equities, bonds, FX, commodities."
        ),
        "what_changes_it": (
            "A new market-data refresh that updates the underlying "
            "values, or provider failures that push a row into "
            "stale or unavailable state."
        ),
    },
    "stress": {
        "meaning": (
            "Composite cross-asset stress regime — Calm / Watch / "
            "Stressed — across volatility, credit, safe havens, and "
            "breadth. Frames how reliably event reactions can be read; "
            "stressed conditions widen the confidence band on any "
            "single reaction, they do not invalidate it."
        ),
        "what_changes_it": (
            "VIX falling back below its 20d average, credit spreads "
            "tightening, safe havens easing, breadth recovering — or "
            "any of the same components dislocating further."
        ),
    },
    "rates": {
        "meaning": (
            "Front-end and long-end rates picture: nominal yields, real "
            "yields, breakeven inflation, and the implied policy stance."
        ),
        "what_changes_it": (
            "Curve moves, central-bank communications, or inflation "
            "prints that reprice real yields and breakevens."
        ),
    },
    "regime_vector": {
        "meaning": (
            "Compact 4-axis regime read — growth, inflation, policy, "
            "liquidity — for the current macro backdrop."
        ),
        "what_changes_it": (
            "New data on growth (PMI / GDP), inflation (CPI / PCE), "
            "policy (rate decisions / guidance), or liquidity (reserves "
            "/ funding spreads)."
        ),
    },
    "uncertainty_concentration": {
        "meaning": (
            "News-derived map of where macro uncertainty is "
            "concentrating — global vs. sector-specific, with the "
            "leading sector flagged when concentration is high."
        ),
        "what_changes_it": (
            "Newsflow on a single sector or theme outpacing global "
            "macro coverage, or a sustained burst of cross-asset "
            "uncertainty."
        ),
    },
}


def _explanations_block() -> dict:
    """Return a fresh copy of the static explanations table so callers
    can mutate the response shape without bleeding back into the module
    constant.  Pure: no I/O, no scoring."""
    return {k: dict(v) for k, v in _CONTEXT_EXPLANATIONS.items()}


def _normalize_generic(block: Optional[dict]) -> dict:
    """Pass-through normaliser for blocks that already carry their own
    ``available`` flag.  Falls back to ``{"available": False}`` when
    the input is missing or malformed so the frontend can always branch
    on presence without a None-check."""
    if not block or not isinstance(block, dict):
        return {"available": False}
    out = dict(block)
    out.setdefault("available", True)
    return out


def compose_market_context(
    snapshots: list[dict],
    stress: Optional[dict],
    highlights: list[dict],
    *,
    rates: Optional[dict] = None,
    regime_vector: Optional[dict] = None,
    source: Optional[str] = None,
    uncertainty_concentration: Optional[dict] = None,
    # --- Deeper macro-engine blocks --------------------------------------
    # Each is optional: the route computes them as pure composers over
    # data it already fetched (no extra provider calls).  Missing blocks
    # carry {"available": False} in the output so the frontend can skip
    # the corresponding panel.
    credit_regime: Optional[dict] = None,
    funding_stress_mode: Optional[dict] = None,
    sector_rotation: Optional[dict] = None,
    finance_playbook: Optional[dict] = None,
) -> dict:
    """Combine the pre-fetched sections into the unified context object.

    All sections are optional — pass empty lists / None when a fetch failed
    and the resulting context will simply mark that section as degraded.

    Returns a dict with this shape:
      {
        built_at:        ISO 8601 UTC timestamp string
        source:          "yfinance" / "polygon" / "unknown"
        snapshots:       list[snapshot dict]   (per-market freshness inside)
        snapshots_meta:  {total, fresh, stale, unavailable}
        snapshot_freshness_note: operator-readable explanation when the
                         strip carries stale or unavailable rows; None
                         when every snapshot is fresh.
        stress:          stress regime dict   (with `available` flag)
        rates:           rates context dict   (with `available` flag)
        regime_vector:   compact 4-axis regime vector
        highlights:      list[mover dict]
        highlights_meta: {count, source}
        uncertainty_concentration: news-derived sector concentration (with `available` flag)
      }
    """
    snaps = list(snapshots or [])
    snaps_meta = _summarize_snapshots(snaps)
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source or _provider_name(),
        "snapshots": snaps,
        "snapshots_meta": snaps_meta,
        "snapshot_freshness_note": _compose_snapshot_freshness_note(
            snaps, snaps_meta,
        ),
        "stress": _normalize_stress(stress),
        "rates": _normalize_rates(rates),
        "regime_vector": _normalize_regime_vector(regime_vector),
        "highlights": list(highlights or []),
        "highlights_meta": _summarize_highlights(highlights or []),
        "uncertainty_concentration": _normalize_uncertainty_concentration(uncertainty_concentration),
        # Deeper engine blocks — pure composers over the inputs above.
        "credit_regime":        _normalize_generic(credit_regime),
        "funding_stress_mode":  _normalize_generic(funding_stress_mode),
        "sector_rotation":      _normalize_generic(sector_rotation),
        "finance_playbook":     _normalize_generic(finance_playbook),
        # Read-only product-facing explanations for the A/B cards.  Static
        # copy; consumers render verbatim under each card title.
        "context_explanations": _explanations_block(),
    }

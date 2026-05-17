"""Demo "Still Moving Market" source.

A read-only projection over an existing persistent / still-moving
candidate stream.  Surfaces only strict eligible Still Moving
candidates and refuses weak sector / index primary reads so the demo
narrative reads as a single-name story, not a sector-wide tape.

Read-only by construction
-------------------------

* No DB writes, no ``yfinance`` / ``market_data`` / paid provider /
  LLM import, no FastAPI surface imported at module load.
* Does not mutate the input candidate list or any candidate dict.
* Does not touch the production ``/movers/persistent`` surface or its
  cache layer.
* Not registered in ``api.py`` — callers must pass candidates in
  directly.  The expected upstream is the same persistent slice the
  production gate already serves.

Output envelope
---------------

Eight pinned keys::

    {
      "ok":                 bool,
      "section":            "still_moving",
      "items":              list[dict],
      "count":              int,        # == len(items)
      "rejected_count":     int,
      "rejection_summary":  dict[str, int],
      "warnings":           list[str],
      "errors":             list[str],
    }

Each item carries::

    event_id, headline, event_date, primary_ticker,
    persistence_signal, evidence_reason, caution_label

The eligibility rule is :func:`mover_card_normalizer.is_high_conviction_persistent`
— the same strict gate ``/movers/persistent`` applies — so a card that
passes here is one a production surface would already promote.  The
sector-ETF rejection reason is broken out from the gate's residual
``filtered_by_persistent_gate`` bucket so the operator can see, at a
glance, when the demo is empty because every candidate failed on the
single-name read.
"""
from __future__ import annotations

from typing import Any, Iterable

from mover_card_normalizer import (
    SURFACED_REASONS,
    is_high_conviction_persistent,
    primary_is_sector_etf,
    to_ui_card,
)


SECTION_NAME: str = "still_moving"


# Conservative caution copy.  Kept generic on purpose — the demo
# surface is informational, never a recommendation.
_CAUTION_LABEL: str = "Monitor for trajectory change"


_SECTOR_ETF_PRIMARY_BLOCKLIST: frozenset[str] = frozenset({
    "SPY",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLB",
    "XLU", "XLY", "XLP", "XLRE",
    "SMH", "XAR",
})


def _top_mover_symbol(card: dict) -> str | None:
    """Return the strongest |return_5d| ticker symbol on the card.

    Routes through :func:`mover_card_normalizer.to_ui_card` so the
    "primary" the demo surface displays is the same ticker the
    :func:`primary_is_sector_etf` rejection check consults — there is
    one definition of "primary" and both the gate and the surface
    look at it.
    """
    ui = to_ui_card(card, "persistent")
    moved = ui.get("moved_tickers") or []
    if not moved:
        return None
    sym = moved[0].get("symbol")
    if not isinstance(sym, str):
        return None
    sym = sym.strip().upper()
    return sym or None


def _rejection_reason(card: Any) -> str:
    """Bucket a rejected candidate for the rejection_summary block.

    The order mirrors :func:`is_high_conviction_persistent` so the
    reason returned is the first disqualifying check the gate would
    have hit.  Sector-ETF primary is broken out from the residual
    ``filtered_by_persistent_gate`` bucket so the operator can see
    that specific failure mode in the summary.
    """
    if not isinstance(card, dict):
        return "malformed_card"
    if card.get("low_information") is True:
        return "low_information"
    thesis = card.get("thesis_state")
    if thesis == "low_information":
        return "low_information"
    if thesis == "falsified":
        return "falsified"
    stale = card.get("stale_signal")
    if stale in ("stale", "legacy"):
        return str(stale)
    weighted = card.get("weighted_evidence")
    label = weighted.get("evidence_label") if isinstance(weighted, dict) else None
    if label != "supportive":
        return "not_supportive_evidence"
    if thesis not in ("confirming", "partial"):
        return "not_thesis_relevant"
    conviction = card.get("conviction")
    if not isinstance(conviction, dict):
        return "missing_conviction"
    if conviction.get("conviction_class") != "conviction":
        return "not_conviction_class"
    if conviction.get("impact_level") != "high":
        return "not_high_impact"
    if primary_is_sector_etf(card):
        return "sector_etf_as_primary"
    return "filtered_by_persistent_gate"


def _evidence_reason(card: dict) -> str:
    """Pick the controlled-vocabulary reason this card surfaced.

    Persistent cards that carry both a proof set and falsifiers read
    as ``"proof-backed confirmation"``; everything else lands on
    ``"persistent follow-through"``.  Both phrases are members of the
    pinned :data:`SURFACED_REASONS` vocabulary.
    """
    if card.get("has_proof_set") and card.get("has_falsifiers"):
        return "proof-backed confirmation"
    return "persistent follow-through"


def _persistence_signal(card: dict) -> Any:
    """Return the source card's persistence_signal verbatim, or ``None``.

    The demo never invents a persistence read.  When the source carries
    no value (``None``, missing key, empty string), the item reports
    ``None`` and the operator can correlate that with the upstream
    builder.
    """
    sig = card.get("persistence_signal")
    if sig in (None, ""):
        return None
    return sig


def _project_item(card: dict) -> dict:
    """Project an admitted card onto the demo item shape."""
    return {
        "event_id":           card.get("event_id"),
        "headline":           card.get("headline") or "",
        "event_date":         card.get("event_date"),
        "primary_ticker":     _top_mover_symbol(card),
        "persistence_signal": _persistence_signal(card),
        "evidence_reason":    _evidence_reason(card),
        "caution_label":      _CAUTION_LABEL,
    }


def build_demo_still_moving_market(
    *,
    candidates: Iterable[Any] | None = None,
) -> dict:
    """Build the demo Still Moving Market envelope.

    Parameters
    ----------
    candidates :
        Iterable of raw mover candidate dicts — typically the same
        payload :func:`movers_cache.get_slice` produces for the
        ``persistent`` slice.  ``None`` is treated as empty so the
        caller can defer the upstream lookup without crashing the
        envelope.

    Returns
    -------
    dict
        The envelope described in the module docstring.  ``ok`` stays
        ``True`` even when every candidate is rejected — the surface
        is allowed to read as "no eligible candidates" without
        signalling an error.
    """
    items: list[dict] = []
    rejection_summary: dict[str, int] = {}
    rejected_count = 0

    for raw in candidates or []:
        if isinstance(raw, dict) and is_high_conviction_persistent(raw):
            items.append(_project_item(raw))
            continue
        reason = _rejection_reason(raw)
        rejection_summary[reason] = rejection_summary.get(reason, 0) + 1
        rejected_count += 1

    return {
        "ok":                True,
        "section":           SECTION_NAME,
        "items":             items,
        "count":             len(items),
        "rejected_count":    rejected_count,
        "rejection_summary": rejection_summary,
        "warnings":          [],
        "errors":            [],
    }


__all__ = (
    "SECTION_NAME",
    "SURFACED_REASONS",
    "build_demo_still_moving_market",
)

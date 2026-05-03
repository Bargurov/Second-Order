"""
evidence_sources.py

Evidence-source traceability primitive.

Why this module
---------------
Several composers in the analysis / validation pipeline already build
an evidence read (competing_thesis, evidence_attribution,
reaction_function_divergence, evidence_ladder).  A reader auditing the
call wants to know *which* internal field or market observation each
piece of evidence came from, whether it supports or contradicts the
thesis, and what about that source is weak.

This module is the small contract that those composers share — a
shape definition (`make_source`) and a weak-traceability predicate
(`is_weak_traceability`) used by the confidence / actionability
downgrade hooks.

Item shape::

    {
      "source_type":              str,   # SOURCE_TYPES enum
      "field_used":               str,   # exact field path / channel /
                                          #   ticker — what was read
      "supports_or_contradicts":  str,   # DIRECTIONS enum
      "limitation":               str,   # short, substantive note when
                                          #   the source is weak; "" when
                                          #   the source is clean
    }

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Optional


SOURCE_TYPES: tuple[str, ...] = (
    "internal_field",       # value lifted from a normalised event field
    "ticker_observation",   # a single-name move from the market basket
    "market_channel",       # a channel-level read (rates / fx / credit / ...)
    "thesis_classifier",    # output of real_yield_context.classify_thesis
    "regime_signal",        # rates / stress regime label
    "agreement_verdict",    # agreement-engine verdict (ladder)
)


DIRECTIONS: tuple[str, ...] = ("supports", "contradicts", "neutral")


_MAX_FIELD_LEN:      int = 160
_MAX_LIMITATION_LEN: int = 200


def make_source(
    *,
    source_type: str,
    field_used: str,
    supports_or_contradicts: str,
    limitation: str = "",
) -> Optional[dict]:
    """Build one ``evidence_sources`` entry, or ``None`` when the inputs
    are unusable (unknown enum value, missing field path).  Safe to feed
    the result of this directly into a list — callers append only when
    the return is truthy.
    """
    if source_type not in SOURCE_TYPES:
        return None
    if supports_or_contradicts not in DIRECTIONS:
        return None
    field = (field_used or "").strip()
    if not field:
        return None
    return {
        "source_type":             source_type,
        "field_used":              field[:_MAX_FIELD_LEN],
        "supports_or_contradicts": supports_or_contradicts,
        "limitation":              (limitation or "").strip()[:_MAX_LIMITATION_LEN],
    }


# Defaults for is_weak_traceability — picked tight so a single-line,
# auditable thesis trace doesn't qualify as "strong" by accident.
_DEFAULT_MIN_ITEMS:        int   = 2
_DEFAULT_MAX_LIMITED_SHARE: float = 0.5


def is_weak_traceability(
    sources: Any,
    *,
    min_items: int = _DEFAULT_MIN_ITEMS,
    max_limited_share: float = _DEFAULT_MAX_LIMITED_SHARE,
) -> bool:
    """Return True when ``sources`` is too thin or mostly limited to
    support a high-conviction call.

    "Weak" means either:
      * fewer than ``min_items`` valid entries, OR
      * more than ``max_limited_share`` of entries carry a non-empty
        ``limitation`` (the entries are real but the desk has open
        questions on each of them).

    Missing / non-list / empty input is weak by definition.  Used by
    the confidence-downgrade rule in ``analyze_event._validate_result``
    and the actionability sizing-caveat hook in
    ``low_information_gate.compose_actionability_check``.
    """
    if not isinstance(sources, list) or not sources:
        return True
    items = [
        s for s in sources
        if isinstance(s, dict)
        and s.get("source_type") in SOURCE_TYPES
        and s.get("supports_or_contradicts") in DIRECTIONS
    ]
    if len(items) < min_items:
        return True
    limited = sum(
        1 for s in items
        if isinstance(s.get("limitation"), str) and s["limitation"].strip()
    )
    return limited / len(items) > max_limited_share

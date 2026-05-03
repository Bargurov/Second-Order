"""
analog_explainer.py

Regime-aware analog explainer.

Takes the raw analogs emitted by ``db.find_historical_analogs`` plus the
current event's regime + mechanism-family + credit-regime snapshots and
enriches each analog with structured match dimensions so the UI can render
"why this analog matters" as compact pills instead of parsing prose.

Key addition over the existing ``match_reason`` string:

  * ``match_dimensions`` — list of {dimension, status, current, analog,
    note} entries for mechanism_family / regime / credit / inflation_rates.
    Each dimension carries ``status`` in {match, mismatch, unknown} so the
    frontend can colour-code without substring matching.
  * ``explainer`` — a finance-useful 1-2 sentence summary.
  * ``topic_vs_regime_mismatch`` — True when topic similarity is strong
    but regime alignment is weak; with ``mismatch_note`` spelling out the
    reason.  This is the "similar event but different setup" flag the
    task cares about.

Pure composer.  No I/O, no DB access — caller hands in the already-loaded
analog list and the current context.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Regime-axis groupings — which axes map to which "dimension".
# ---------------------------------------------------------------------------

# The full 7-axis regime vector in regime_vector.py is grouped here into
# four finance-facing dimensions the explainer surfaces.  ``regime`` is a
# roll-up of every axis (for the overall match score); the others are the
# narrower reads a macro desk watches specifically.
_INFLATION_RATES_AXES: tuple[str, ...] = (
    "inflation", "policy_stance", "inflation_path", "curve_shape",
)
_CREDIT_AXES: tuple[str, ...] = ("credit",)
_OVERALL_REGIME_AXES: tuple[str, ...] = (
    "inflation", "policy_stance", "fx", "growth_stress",
    "credit", "curve_shape", "inflation_path",
)

# Threshold below which we call regime alignment "weak".  Tuned so 2 of 7
# axes matching reads as weak, 3 of 7 as middling, 4+ as aligned.  Matches
# the ratio rerank_analogs uses implicitly (>= 0.5 = meaningful match).
_REGIME_WEAK_RATIO:   float = 0.30
_REGIME_STRONG_RATIO: float = 0.65

# Topic similarity above this threshold counts as "same topic" for the
# topic-vs-regime-mismatch flag.  Jaccard scores above 0.35 correspond to
# clearly-related events in the existing calibration corpus.
_TOPIC_SIMILAR_FLOOR: float = 0.30


# ---------------------------------------------------------------------------
# Per-dimension comparison
# ---------------------------------------------------------------------------


def _status(current: Optional[str], analog: Optional[str]) -> str:
    """Three-state compare: match / mismatch / unknown.

    Neutral or missing values on either side collapse to ``unknown`` — we
    don't want to penalise analogs for a dimension the system couldn't
    classify cleanly.
    """
    if not current or not analog:
        return "unknown"
    if current in ("neutral", "none", "") or analog in ("neutral", "none", ""):
        return "unknown"
    return "match" if current == analog else "mismatch"


def _axes_ratio(
    current: Optional[dict],
    analog: Optional[dict],
    axes: tuple[str, ...],
) -> tuple[int, int, float]:
    """Return (matched, comparable, ratio) across the given regime axes.

    ``comparable`` excludes axis pairs where either side is neutral /
    None — those are unknown, not mismatches.
    """
    if not current or not analog:
        return 0, 0, 0.0
    matched = 0
    comparable = 0
    for axis in axes:
        a = current.get(axis)
        b = analog.get(axis)
        if a in (None, "neutral") or b in (None, "neutral"):
            continue
        comparable += 1
        if a == b:
            matched += 1
    ratio = matched / comparable if comparable else 0.0
    return matched, comparable, ratio


def _axes_summary_status(matched: int, comparable: int) -> str:
    """Collapse a matched/comparable count into match/mismatch/unknown.

    A single-axis dimension (e.g. credit) is a clean three-state compare.
    A multi-axis dimension (inflation/rates, overall regime) uses the
    weak/strong ratio to decide.
    """
    if comparable == 0:
        return "unknown"
    if comparable == 1:
        return "match" if matched == 1 else "mismatch"
    ratio = matched / comparable
    if ratio >= _REGIME_STRONG_RATIO:
        return "match"
    if ratio <= _REGIME_WEAK_RATIO:
        return "mismatch"
    # Middle band: report the closer edge — but mark "partial" so the UI
    # can render it differently from a clean match.
    return "partial"


def _mechanism_family_dimension(
    current_family: Optional[str],
    analog_family: Optional[str],
) -> dict:
    status = _status(current_family, analog_family)
    if status == "match":
        note = f"same family: {current_family}"
    elif status == "mismatch":
        note = f"different family: {current_family} vs {analog_family}"
    else:
        note = "mechanism family unavailable"
    return {
        "dimension": "mechanism_family",
        "label":     "Mechanism family",
        "status":    status,
        "current":   current_family or "none",
        "analog":    analog_family or "none",
        "note":      note,
    }


def _single_axis_dimension(
    label: str,
    dimension_id: str,
    axis: str,
    current_regime: Optional[dict],
    analog_regime: Optional[dict],
) -> dict:
    """Build a match-dimension entry over a single regime axis."""
    current_val = (current_regime or {}).get(axis)
    analog_val = (analog_regime or {}).get(axis)
    status = _status(
        str(current_val) if current_val is not None else None,
        str(analog_val) if analog_val is not None else None,
    )
    return {
        "dimension": dimension_id,
        "label":     label,
        "status":    status,
        "current":   current_val or "unknown",
        "analog":    analog_val or "unknown",
        "note":      _single_axis_note(label, status, current_val, analog_val),
    }


def _single_axis_note(
    label: str, status: str,
    current: Optional[str], analog: Optional[str],
) -> str:
    if status == "match":
        return f"same {label.lower()}: {current}"
    if status == "mismatch":
        return f"different {label.lower()}: {current} vs {analog}"
    return f"{label.lower()} unavailable"


def _multi_axis_dimension(
    label: str,
    dimension_id: str,
    axes: tuple[str, ...],
    current_regime: Optional[dict],
    analog_regime: Optional[dict],
) -> dict:
    """Build a dimension across a group of regime axes (e.g. inflation/rates)."""
    matched, comparable, ratio = _axes_ratio(current_regime, analog_regime, axes)
    status = _axes_summary_status(matched, comparable)

    if comparable == 0:
        note = f"{label.lower()} unavailable on one side"
    else:
        note = f"{matched}/{comparable} axes agree ({label.lower()})"
    return {
        "dimension": dimension_id,
        "label":     label,
        "status":    status,
        "axes_matched":    matched,
        "axes_comparable": comparable,
        "match_ratio":     round(ratio, 2) if comparable else 0.0,
        "note":            note,
    }


# ---------------------------------------------------------------------------
# Mismatch note — "same topic, different regime"
# ---------------------------------------------------------------------------


def _topic_regime_divergence(
    topic_similarity: float,
    overall_matched: int,
    overall_comparable: int,
) -> tuple[bool, str]:
    """Detect the "similar event but different setup" case.

    Fires when:
      * topic similarity clears ``_TOPIC_SIMILAR_FLOOR``
      * overall regime match ratio is weak
      * at least 2 regime axes were comparable (can't diverge on 0 axes)
    """
    if topic_similarity < _TOPIC_SIMILAR_FLOOR:
        return False, ""
    if overall_comparable < 2:
        return False, ""
    ratio = overall_matched / overall_comparable
    if ratio > _REGIME_WEAK_RATIO:
        return False, ""
    return True, (
        f"Topic overlap is strong (similarity {topic_similarity:.2f}) but only "
        f"{overall_matched}/{overall_comparable} regime axes line up — "
        f"past playbook may not transfer."
    )


# ---------------------------------------------------------------------------
# Explainer sentence
# ---------------------------------------------------------------------------


def _explainer(
    analog: dict,
    dimensions: list[dict],
    mismatch_active: bool,
    mismatch_note: str,
) -> str:
    """Compose a 1-2 sentence finance-useful summary.

    Leads with the mechanism family + regime fit; appends the mismatch
    warning when the topic-vs-regime flag fires.  The decay and return_5d
    from the base analog dict give the user a quick "what happened last
    time" anchor.
    """
    fam = next((d for d in dimensions if d["dimension"] == "mechanism_family"), None)
    inflation_rates = next(
        (d for d in dimensions if d["dimension"] == "inflation_rates"), None,
    )
    credit = next((d for d in dimensions if d["dimension"] == "credit"), None)

    parts: list[str] = []
    if fam and fam["status"] == "match":
        parts.append(f"same mechanism family ({fam['current']})")
    elif fam and fam["status"] == "mismatch":
        parts.append(f"different family ({analog.get('mechanism_family', 'none')})")
    if inflation_rates and inflation_rates["status"] in ("match", "partial"):
        parts.append(f"rates/inflation backdrop aligns "
                     f"({inflation_rates['axes_matched']}/"
                     f"{inflation_rates['axes_comparable']})")
    elif inflation_rates and inflation_rates["status"] == "mismatch":
        parts.append("rates/inflation backdrop diverges")
    if credit and credit["status"] == "match":
        parts.append(f"credit state matches ({credit['current']})")
    elif credit and credit["status"] == "mismatch":
        parts.append(f"credit state differs ({analog.get('regime_snapshot', {}).get('credit', 'unknown')})")

    decay = analog.get("decay")
    r5 = analog.get("return_5d")
    tail = ""
    if decay or r5 is not None:
        bits = []
        if r5 is not None:
            bits.append(f"5d {r5:+.1f}%")
        if decay:
            bits.append(f"decay: {decay}")
        tail = f" — last time: {', '.join(bits)}."

    lead = "; ".join(parts) if parts else "keyword overlap only"
    summary = f"{lead}.{tail}".strip()

    if mismatch_active and mismatch_note:
        return f"{summary} {mismatch_note}"
    return summary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def explain_analog(
    analog: dict,
    current_regime: Optional[dict] = None,
    current_mechanism_family: Optional[str] = None,
) -> dict:
    """Enrich a single analog dict with match dimensions + mismatch flag.

    Returns a NEW dict — does not mutate the input.  Safe to call with
    every input None (missing current context); every dimension will
    report ``status="unknown"`` and the explainer will still produce a
    readable line from the analog's decay / return.
    """
    if not isinstance(analog, dict):
        return analog

    analog_regime = analog.get("regime_snapshot") or {}
    analog_family = analog.get("mechanism_family") or "none"

    # Build dimensions.
    dimensions: list[dict] = []
    dimensions.append(_mechanism_family_dimension(
        current_mechanism_family, analog_family,
    ))
    dimensions.append(_multi_axis_dimension(
        "Overall regime", "regime",
        _OVERALL_REGIME_AXES, current_regime, analog_regime,
    ))
    dimensions.append(_multi_axis_dimension(
        "Inflation / rates", "inflation_rates",
        _INFLATION_RATES_AXES, current_regime, analog_regime,
    ))
    dimensions.append(_single_axis_dimension(
        "Credit state", "credit",
        "credit", current_regime, analog_regime,
    ))

    # Topic-vs-regime-mismatch flag — only fires when topic is clearly
    # similar AND the overall regime dimension is weakly matched.
    overall_dim = next(d for d in dimensions if d["dimension"] == "regime")
    mismatch_active, mismatch_note = _topic_regime_divergence(
        float(analog.get("similarity") or 0.0),
        overall_dim.get("axes_matched") or 0,
        overall_dim.get("axes_comparable") or 0,
    )

    enriched = dict(analog)
    enriched["match_dimensions"]        = dimensions
    enriched["topic_vs_regime_mismatch"] = mismatch_active
    enriched["mismatch_note"]           = mismatch_note if mismatch_active else None
    enriched["explainer"]               = _explainer(
        enriched, dimensions, mismatch_active, mismatch_note,
    )
    return enriched


def explain_analogs(
    analogs: list[dict],
    current_regime: Optional[dict] = None,
    current_mechanism_family: Optional[str] = None,
) -> list[dict]:
    """Apply ``explain_analog`` to each analog in the list."""
    if not analogs:
        return []
    return [
        explain_analog(a, current_regime, current_mechanism_family)
        for a in analogs
    ]

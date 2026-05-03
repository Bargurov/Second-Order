"""
narrative_divergence.py

Detect divergence between stated thesis confidence, calibrated historical
validation rate, and observed market behaviour for a given event.

Pure computation — no I/O, no LLM calls.
"""

from __future__ import annotations

_SHARP_GAP: float = 0.30
_MILD_GAP:  float = 0.15
_MIN_CAL_N: int   = 5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_signal(tickers: list[dict], role: str) -> str:
    """Alignment signal for a role group.

    Returns one of: "aligned", "contra", "mixed", "no_data".
    """
    group = [t for t in tickers if t.get("role") == role]
    if not group:
        return "no_data"

    n_aligned = sum(
        1 for t in group
        if isinstance(t.get("direction_tag"), str)
        and t["direction_tag"].startswith("supports")
    )
    n_contra = sum(
        1 for t in group
        if isinstance(t.get("direction_tag"), str)
        and t["direction_tag"].startswith("contradicts")
    )
    eligible = n_aligned + n_contra
    if eligible == 0:
        return "no_data"
    if n_aligned == eligible:
        return "aligned"
    if n_contra == eligible:
        return "contra"
    return "mixed"


def _rationale(
    label: str,
    confidence: str,
    actual_pct: float,
    expected_pct: float,
) -> str:
    actual_str   = f"{actual_pct * 100:.0f}%"
    expected_str = f"{expected_pct * 100:.0f}%"
    conf_cap     = confidence.capitalize()
    if label == "confident_miss":
        return (
            f"{conf_cap} confidence validated at {actual_str} vs. calibrated "
            f"{expected_str} — sharp miss against historical base rate."
        )
    if label == "surprise_validation":
        return (
            f"{conf_cap} confidence validated at {actual_str} vs. calibrated "
            f"{expected_str} — outperforming historical expectations."
        )
    if label == "aligned":
        return (
            f"{conf_cap} confidence validated at {actual_str}, in line with "
            f"calibrated {expected_str}."
        )
    # mixed
    return (
        f"{conf_cap} confidence validated at {actual_str} vs. calibrated "
        f"{expected_str} — mild deviation from expectations."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_narrative_divergence(
    tickers: list[dict],
    confidence: str,
    calibration_stats: dict,
) -> dict:
    """Compute narrative divergence between confidence, calibration, and market signal.

    Parameters
    ----------
    tickers:
        Ticker dicts from market_check output — need ``role`` and ``direction_tag``.
    confidence:
        LLM-assigned level: ``"low"``, ``"medium"``, or ``"high"``.
    calibration_stats:
        From ``db.get_confidence_calibration_stats()``::

            {"low": {"hit_rate": 0.35, "n": 45}, "medium": ..., "high": ...}

    Returns
    -------
    dict with ``available: bool`` plus computed fields when data is present.
    """
    n_supporting = sum(
        1 for t in tickers
        if isinstance(t.get("direction_tag"), str)
        and t["direction_tag"].startswith("supports")
    )
    n_contradicting = sum(
        1 for t in tickers
        if isinstance(t.get("direction_tag"), str)
        and t["direction_tag"].startswith("contradicts")
    )
    n_total = n_supporting + n_contradicting

    if n_total == 0:
        return {"available": False}

    actual_rate = n_supporting / n_total

    cal_bucket = calibration_stats.get(confidence, {})
    cal_n: int = cal_bucket.get("n", 0)
    has_calibration = cal_n >= _MIN_CAL_N
    expected_rate: float | None = cal_bucket.get("hit_rate") if has_calibration else None
    n_calibration_events: int | None = cal_n if has_calibration else None

    bene_signal = _role_signal(tickers, "beneficiary")
    loser_signal = _role_signal(tickers, "loser")

    if expected_rate is None:
        # No calibration — report raw directional signal without a gap label
        label = "validated" if actual_rate >= 0.5 else "contradicted"
        return {
            "available": True,
            "confidence": confidence,
            "actual_rate": round(actual_rate, 4),
            "expected_rate": None,
            "gap": None,
            "label": label,
            "severity": "none",
            "rationale": None,
            "n_supporting": n_supporting,
            "n_contradicting": n_contradicting,
            "n_total": n_total,
            "beneficiary_signal": bene_signal,
            "loser_signal": loser_signal,
            "n_calibration_events": n_calibration_events,
        }

    gap = actual_rate - expected_rate

    if gap <= -_SHARP_GAP:
        label, severity = "confident_miss", "sharp"
    elif gap >= _SHARP_GAP:
        label, severity = "surprise_validation", "sharp"
    elif abs(gap) < _MILD_GAP:
        label, severity = "aligned", "none"
    else:
        label, severity = "mixed", "mild"

    return {
        "available": True,
        "confidence": confidence,
        "actual_rate": round(actual_rate, 4),
        "expected_rate": round(expected_rate, 4),
        "gap": round(gap, 4),
        "label": label,
        "severity": severity,
        "rationale": _rationale(label, confidence, actual_rate, expected_rate),
        "n_supporting": n_supporting,
        "n_contradicting": n_contradicting,
        "n_total": n_total,
        "beneficiary_signal": bene_signal,
        "loser_signal": loser_signal,
        "n_calibration_events": n_calibration_events,
    }

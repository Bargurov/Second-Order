"""
channel_timing.py

Time-aware channel scoring for validation.

Why this module
---------------
The agreement engine and the thesis scorecard already separate direct
from second-order evidence, but they treat every observation as
equal-weight regardless of WHEN it fires.  In practice the six
transmission channels — rates, FX, commodities, credit, equities
(direct), equities (downstream) — confirm on different timelines:

  * rates / vol       → 0-3d (fast repricing)
  * equities (direct) → 1-5d
  * fx / commodities  → 3-10d
  * credit            → 5-12d
  * equities (downstream) → 7-20d (cascade)

A commodity print that contradicts at 1d on a supply-shock event is
NOT the same signal as the same contradiction at 20d — it's simply
too early.  Equally, a rates move that's still flat at 10d on a
policy_surprise event is MORE damning than a flat 1d print on the
same rates channel.  This module encodes that timing asymmetry.

Contract
--------
    score_channel_observation(channel, days_elapsed, direction_sign, *, mechanism_family=None)
        -> {phase, factor, note}

    classify_thesis_timing(event_age_days, observations) -> dict

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Validation matrix — canonical per-channel confirmation windows.
# ---------------------------------------------------------------------------
#
# Each channel carries four anchors that divide the timeline into five
# phases:
#
#   days 0 … early_day       → "pre_window"  (too early to score meaningfully)
#   early_day … peak_start   → "early_window" (plausible but ahead of peak)
#   peak_start … peak_end    → "peak_window" (canonical confirmation band)
#   peak_end … late_day      → "late_window" (signal should have fired by now)
#   > late_day               → "expired"     (beyond institutional horizon)
#
# Numbers are calendar days.  They mirror the "1-5d direct / 5-20d
# downstream" split already used by sector_passthrough.py and extend it
# across all six channels.
#
# Channels match ``mechanism_family.FAMILY_CHANNEL_PACKS`` so callers
# can pipe the family's primary/second-order channels directly.

_CANONICAL_WINDOWS: dict[str, dict[str, int]] = {
    "rates":               {"early_day": 0, "peak_start": 1, "peak_end": 3,  "late_day": 10},
    "vol":                 {"early_day": 0, "peak_start": 0, "peak_end": 1,  "late_day": 5},
    "fx":                  {"early_day": 1, "peak_start": 3, "peak_end": 7,  "late_day": 14},
    "commodities":         {"early_day": 1, "peak_start": 3, "peak_end": 10, "late_day": 20},
    "credit":              {"early_day": 2, "peak_start": 5, "peak_end": 12, "late_day": 25},
    "equities":            {"early_day": 0, "peak_start": 1, "peak_end": 5,  "late_day": 15},
    "equities_downstream": {"early_day": 3, "peak_start": 7, "peak_end": 20, "late_day": 45},
}


# Family-aware multipliers — scale each channel's windows when a
# specific family accelerates / delays that channel's response.
# A factor < 1.0 SHORTENS the windows (confirmation expected sooner);
# > 1.0 lengthens them.  Only non-1.0 entries need to appear here.
_FAMILY_CHANNEL_SHIFT: dict[str, dict[str, float]] = {
    "supply_shock":          {"commodities": 0.7, "equities": 0.8},
    "commodity_squeeze":     {"commodities": 0.7},
    "policy_surprise":       {"rates": 0.7, "vol": 0.7, "fx": 0.85},
    "fiscal_issuance":       {"rates": 1.2, "credit": 1.15},
    "bank_stress":           {"credit": 0.8, "vol": 0.8, "equities": 0.85},
    "labor_inflation":       {"rates": 1.1},
    "ceasefire_deescalation":{"vol": 0.7, "commodities": 0.85},
    "sanction":              {"fx": 0.85, "commodities": 0.85},
    "tariff":                {"equities": 0.85, "fx": 0.9},
    "supply_normalization":  {"commodities": 0.85},
}


# ---------------------------------------------------------------------------
# Scoring weights — (phase, direction) → signed contribution factor.
# Positive for confirmation, negative for contradiction.  Magnitudes
# encode the institutional intuition: peak-window signals count for
# full credit, early / late signals discount, pre-window contradictions
# are softened (too early to call broken), expired signals barely
# count.
# ---------------------------------------------------------------------------

_PHASE_DIRECTION_WEIGHT: dict[tuple[str, str], float] = {
    ("pre_window",   "support"):     +0.5,
    ("pre_window",   "contradict"):  -0.3,   # softened: too early to conclude
    ("early_window", "support"):     +0.7,
    ("early_window", "contradict"):  -0.8,
    ("peak_window",  "support"):     +1.0,
    ("peak_window",  "contradict"):  -1.0,
    ("late_window",  "support"):     +0.5,   # still counts but thesis slow
    ("late_window",  "contradict"):  -0.7,
    ("expired",      "support"):     +0.2,
    ("expired",      "contradict"):  -0.4,
}


PHASES: tuple[str, ...] = (
    "pre_window", "early_window", "peak_window", "late_window", "expired",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scaled_windows(
    channel: str,
    mechanism_family: Optional[str],
) -> Optional[dict[str, int]]:
    """Return the per-channel anchors with family-aware scaling applied."""
    base = _CANONICAL_WINDOWS.get(channel)
    if base is None:
        return None
    shift = (_FAMILY_CHANNEL_SHIFT.get(mechanism_family or "") or {}).get(channel)
    if shift is None or shift == 1.0:
        return dict(base)
    return {
        k: max(0, int(round(v * shift)))
        for k, v in base.items()
    }


def _phase_for(days_elapsed: int, windows: dict[str, int]) -> str:
    if days_elapsed < windows["early_day"]:
        return "pre_window"
    if days_elapsed < windows["peak_start"]:
        return "early_window"
    if days_elapsed <= windows["peak_end"]:
        return "peak_window"
    if days_elapsed <= windows["late_day"]:
        return "late_window"
    return "expired"


def _direction_label(direction_sign: float) -> Optional[str]:
    if direction_sign > 0:
        return "support"
    if direction_sign < 0:
        return "contradict"
    return None   # zero/flat is no contribution


# ---------------------------------------------------------------------------
# Public: per-observation score
# ---------------------------------------------------------------------------

def score_channel_observation(
    channel: Optional[str],
    days_elapsed: Optional[int],
    direction_sign: float,
    *,
    mechanism_family: Optional[str] = None,
) -> dict[str, Any]:
    """Score a single channel observation with its timing phase.

    ``direction_sign`` is +1 for a thesis-aligned move, -1 for a
    contradiction, 0 for flat / no signal.  The returned ``factor`` is
    already signed — callers can sum contributions without tracking
    direction separately.

    Returns::

        {
          "phase":           str in PHASES,
          "factor":          float,         # signed, already scaled by phase
          "note":            str,           # one-line reason
          "channel":         str | None,    # echoed
          "days_elapsed":    int | None,
          "applied_windows": dict | None,   # the (possibly family-shifted) windows
        }

    Unknown channels / missing days fold to a zero-factor observation
    so malformed input never crashes the aggregate layer.
    """
    if not channel or not isinstance(channel, str) or days_elapsed is None:
        return {
            "phase":           "unknown",
            "factor":           0.0,
            "note":              "channel or age unavailable",
            "channel":           channel,
            "days_elapsed":       days_elapsed,
            "applied_windows":    None,
        }
    try:
        d = int(days_elapsed)
    except (TypeError, ValueError):
        return {
            "phase":           "unknown",
            "factor":           0.0,
            "note":              "non-integer age",
            "channel":           channel,
            "days_elapsed":       days_elapsed,
            "applied_windows":    None,
        }
    if d < 0:
        d = 0

    windows = _scaled_windows(channel, mechanism_family)
    if windows is None:
        return {
            "phase":           "unknown",
            "factor":           0.0,
            "note":              f"no validation window for channel {channel!r}",
            "channel":           channel,
            "days_elapsed":       d,
            "applied_windows":    None,
        }

    phase = _phase_for(d, windows)
    dir_label = _direction_label(float(direction_sign or 0.0))
    if dir_label is None:
        note = f"{channel} at day {d}: flat / no signal"
        return {
            "phase":           phase,
            "factor":           0.0,
            "note":              note,
            "channel":           channel,
            "days_elapsed":       d,
            "applied_windows":    windows,
        }

    factor = _PHASE_DIRECTION_WEIGHT.get((phase, dir_label), 0.0)
    verb = "support" if dir_label == "support" else "contradict"
    note = (
        f"{channel} at day {d} ({phase.replace('_', ' ')}): "
        f"{verb} · factor {factor:+.2f}"
    )
    return {
        "phase":           phase,
        "factor":           factor,
        "note":              note,
        "channel":           channel,
        "days_elapsed":       d,
        "applied_windows":    windows,
    }


# ---------------------------------------------------------------------------
# Public: aggregate timing status
# ---------------------------------------------------------------------------

TIMING_STATUSES: tuple[str, ...] = (
    "early_confirming",      # support signals firing ahead of / in early window
    "in_window_confirming",  # peak-window positives dominate
    "delayed_on_track",      # late_window positives dominate, no peak contradiction
    "late_and_failing",      # peak/late contradictions outweigh support
    "pending",               # too few observations past pre_window to judge
    "insufficient",          # no usable observations at all
)


_TIMING_LABEL: dict[str, str] = {
    "early_confirming":       "Early confirming",
    "in_window_confirming":   "In-window confirming",
    "delayed_on_track":       "Delayed but on track",
    "late_and_failing":       "Late and failing",
    "pending":                "Pending — event still young",
    "insufficient":           "Insufficient observations",
}


def _classify_status(
    scored: list[dict],
    event_age_days: int,
) -> tuple[str, str]:
    """Pick the timing_status from the scored observations.  Returns
    ``(status, rationale)`` — rationale is the one-line reason."""
    if not scored:
        return "insufficient", "No usable channel observations."

    # Filter out flat / zero-factor observations when counting support
    # vs contradict; those don't meaningfully tip the aggregate.
    meaningful = [o for o in scored if o.get("factor")]
    if not meaningful:
        return "pending", (
            f"Event is {event_age_days}d old; observed channels are flat."
        )

    # Bucket contributions by phase × direction.
    peak_support    = sum(1 for o in meaningful
                           if o["phase"] == "peak_window" and o["factor"] > 0)
    peak_contradict = sum(1 for o in meaningful
                           if o["phase"] == "peak_window" and o["factor"] < 0)
    early_support   = sum(1 for o in meaningful
                           if o["phase"] in ("pre_window", "early_window")
                           and o["factor"] > 0)
    late_support    = sum(1 for o in meaningful
                           if o["phase"] in ("late_window", "expired")
                           and o["factor"] > 0)
    late_contradict = sum(1 for o in meaningful
                           if o["phase"] in ("late_window", "expired")
                           and o["factor"] < 0)

    total_pos = sum(1 for o in meaningful if o["factor"] > 0)
    total_neg = sum(1 for o in meaningful if o["factor"] < 0)
    net_factor = sum(o["factor"] for o in meaningful)

    # --- late_and_failing ---
    # Peak / late contradictions dominate a meaningful sample.
    if (peak_contradict + late_contradict) >= max(2, total_pos) and net_factor < -0.4:
        return "late_and_failing", (
            f"{peak_contradict} peak- + {late_contradict} late-window "
            "contradiction(s) outweigh any support — thesis is running out of time."
        )

    if total_neg >= 2 and net_factor < -0.3:
        return "late_and_failing", (
            f"{total_neg} channel contradiction(s) with net negative timing "
            f"score ({net_factor:+.2f}) — thesis looks late and failing."
        )

    # --- early_confirming ---
    # Most positives are in early/pre-window phases and nothing has
    # fired in peak with a contradiction.
    if early_support >= 2 and peak_contradict == 0 and net_factor > 0.3:
        return "early_confirming", (
            f"{early_support} channel(s) already firing in the early / pre-peak "
            "window with no peak-window contradiction — thesis is ahead of schedule."
        )

    # --- in_window_confirming ---
    # Peak-window positives carry the read.
    if peak_support >= 2 and peak_support > peak_contradict:
        return "in_window_confirming", (
            f"{peak_support} peak-window confirmation(s) vs "
            f"{peak_contradict} contradiction(s) — thesis confirming on schedule."
        )

    if peak_support >= 1 and peak_contradict == 0 and net_factor > 0:
        return "in_window_confirming", (
            f"{peak_support} peak-window confirmation with no in-window "
            "contradiction — thesis confirming."
        )

    # --- delayed_on_track ---
    # Late-window positives dominate, no peak contradiction.
    if late_support >= 1 and peak_contradict == 0 and net_factor > 0:
        return "delayed_on_track", (
            f"{late_support} late-window confirmation(s), no peak-window "
            "contradiction — thesis delayed but still on track."
        )

    # --- pending ---
    # Most observations sit in the pre_window phase for their channel;
    # too early to call.
    pre_window_obs = sum(1 for o in meaningful if o["phase"] == "pre_window")
    if pre_window_obs >= len(meaningful) - 1:
        return "pending", (
            f"Event is {event_age_days}d old; most channels are still in "
            "their pre-confirmation window."
        )

    # Fallback — mixed timing picture.
    return "pending", (
        f"Timing picture is mixed: {total_pos} support / {total_neg} contradict "
        f"across phases; net score {net_factor:+.2f}."
    )


def classify_thesis_timing(
    event_age_days: Optional[int],
    observations: Optional[Iterable[dict]],
) -> dict[str, Any]:
    """Aggregate channel observations into a timing-aware status.

    Inputs
    ------
    event_age_days:
        Calendar-day age of the event.  None / missing folds to 0.
    observations:
        Iterable of scored observations (as returned by
        ``score_channel_observation``) OR raw dicts with
        ``{channel, days_elapsed, direction_sign, mechanism_family?}``
        — the latter are re-scored inline so callers can hand in
        lists without prepping them first.

    Returns::

        {
          "status":         one of TIMING_STATUSES,
          "status_label":   str,
          "rationale":      one-line explanation,
          "observations":    [...],            # scored list (for audit / UI)
          "phase_summary":   {phase: count},
          "net_factor":      float,
          "event_age_days":   int,
        }
    """
    age = 0
    if event_age_days is not None:
        try:
            age = max(0, int(event_age_days))
        except (TypeError, ValueError):
            age = 0

    scored: list[dict] = []
    for o in observations or []:
        if not isinstance(o, dict):
            continue
        # If the observation already carries a phase + factor, trust it.
        if "phase" in o and "factor" in o:
            scored.append(o)
            continue
        # Otherwise score it inline.
        s = score_channel_observation(
            channel=o.get("channel"),
            days_elapsed=o.get("days_elapsed", age),
            direction_sign=o.get("direction_sign") or 0.0,
            mechanism_family=o.get("mechanism_family"),
        )
        scored.append(s)

    status, rationale = _classify_status(scored, age)
    phase_summary: dict[str, int] = {p: 0 for p in PHASES}
    phase_summary["unknown"] = 0
    for o in scored:
        p = o.get("phase") or "unknown"
        phase_summary[p] = phase_summary.get(p, 0) + 1

    net_factor = round(sum(o.get("factor") or 0.0 for o in scored), 3)

    return {
        "status":         status,
        "status_label":   _TIMING_LABEL.get(status, status),
        "rationale":      rationale,
        "observations":    scored,
        "phase_summary":   phase_summary,
        "net_factor":      net_factor,
        "event_age_days":   age,
    }

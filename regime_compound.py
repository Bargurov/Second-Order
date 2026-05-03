"""
regime_compound.py

Compound regime labels + transition detection built on top of the
7-axis ``regime_vector.build_regime_vector`` output.

Why this module
---------------
The axis-level vector answers "what is each macro channel saying?".
It does not answer the question analysts actually ask: *"what regime
ARE we in?"*  Those are compound patterns across axes — reflation,
stagflation pulse, funding stress, growth scare, supply squeeze,
disinflation relief — that matter for analog selection and thesis
interpretation.

This module adds that layer without mutating the existing per-axis
code:

  1. ``classify_compound_regime(vector)`` pattern-matches a current
     regime vector against a small rulebook and returns the best-
     fitting compound label plus a 0..1 confidence and a one-line
     rationale.
  2. ``detect_regime_transition(current, baseline)`` compares the
     current vector to a baseline and returns one of
     ``stable / shifting / flipping / unavailable`` plus the list of
     axes that changed.
  3. ``baseline_from_events(events)`` takes a sample of saved events
     (each carrying a persisted ``regime_snapshot``) and returns a
     modal vector — the "typical regime over this window" that
     transitions are measured against.

All functions are pure composers: no I/O, no globals, no imports
beyond stdlib + ``regime_vector.REGIME_AXES`` / ``_AXIS_OPPOSITES``.
Missing / malformed inputs degrade cleanly to ``{"label": "none", ...}``
or ``{"state": "unavailable", ...}``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from regime_vector import REGIME_AXES, _AXIS_OPPOSITES


# ---------------------------------------------------------------------------
# Compound regime rulebook
# ---------------------------------------------------------------------------
# Each rule specifies two kinds of axis constraints:
#
#   requires — HARD constraints; every entry must match or the rule is
#              excluded from consideration for this vector.
#   supports — SOFT constraints; each match boosts confidence but none
#              is individually required.
#
# A rule's confidence = (required_matches + 0.5 * support_matches) /
#                       (len(requires) + 0.5 * len(supports)).
#
# Values are either a single string (exact match) or a set of strings
# (any one counts).  "neutral" is accepted in most supports so the
# classifier doesn't penalise incomplete data — an axis reading
# ``"neutral"`` contributes no evidence either way rather than
# evidence against.

# Minimum confidence before we emit the label.  Below the floor the
# classifier returns ``"none"`` — an honest "no compound pattern
# locked in" beats a misleading rough match.
_COMPOUND_CONFIDENCE_FLOOR: float = 0.60


_RULES: tuple[dict[str, Any], ...] = (
    {
        "label":     "reflation",
        "requires": {
            "inflation":     "hot",
            "growth_stress": {"calm", "watch"},
        },
        "supports": {
            "credit":       {"risk_on"},
            "curve_shape":  {"parallel"},
            "fx":           {"dollar_weak"},
        },
        "rationale": "Prices rising against stable growth with risk-on credit",
    },
    {
        "label":     "stagflation_pulse",
        "requires": {
            "inflation":     "hot",
            "policy_stance": "hawkish",
            "growth_stress": {"watch", "stressed"},
        },
        "supports": {
            "curve_shape":    {"front_loaded"},
            "inflation_path": {"hawkish_constraint"},
            "credit":         {"risk_off"},
        },
        "rationale": "Hot inflation + tight Fed with growth cracking",
    },
    {
        "label":     "funding_stress",
        "requires": {
            "growth_stress": "stressed",
            "credit":        "risk_off",
        },
        "supports": {
            "fx":            {"dollar_strong"},
            "policy_stance": {"hawkish", "neutral"},
        },
        "rationale": "Dollar bid, credit widening, broad risk aversion",
    },
    {
        "label":     "growth_scare",
        "requires": {
            "growth_stress": {"watch", "stressed"},
            "inflation":     "cool",
        },
        "supports": {
            "policy_stance":  {"dovish"},
            "credit":         {"risk_off"},
            "curve_shape":    {"term_premium", "parallel"},
            "inflation_path": {"dovish_space"},
        },
        "rationale": "Demand concern, Fed pivoting dovish, disinflationary",
    },
    {
        "label":     "supply_squeeze",
        "requires": {
            "inflation":   "hot",
            "curve_shape": "front_loaded",
        },
        "supports": {
            "inflation_path": {"hawkish_constraint"},
            "growth_stress":  {"calm", "watch"},
            "policy_stance":  {"hawkish"},
        },
        "rationale": "Front-loaded inflation, Fed boxed in, growth intact",
    },
    {
        "label":     "disinflation_relief",
        "requires": {
            "inflation":     "cool",
            "policy_stance": {"dovish", "neutral"},
        },
        "supports": {
            "credit":         {"risk_on"},
            "curve_shape":    {"parallel", "term_premium"},
            "fx":             {"dollar_weak"},
            "inflation_path": {"dovish_space"},
        },
        "rationale": "Prices cooling, Fed easing, risk-on regaining",
    },
)


# ---------------------------------------------------------------------------
# Internal: per-rule match scoring
# ---------------------------------------------------------------------------

def _axis_matches(actual: Any, expected: Any) -> bool:
    """Return True iff the actual axis value satisfies the rule spec.

    ``expected`` is either a single string (exact match) or a set of
    strings (any-of match).  ``actual`` of ``None`` never matches so
    rules never fire on an unavailable vector.
    """
    if actual is None:
        return False
    if isinstance(expected, str):
        return actual == expected
    if isinstance(expected, (set, frozenset)):
        return actual in expected
    return False


def _score_rule(vector: dict, rule: dict) -> tuple[float, list[str]]:
    """Return (confidence, satisfied_axes) for one rule against the vector.

    Returns ``(0.0, [])`` when any required axis fails — the hard gate.
    Otherwise the confidence is the weighted sum of required (1.0) and
    support (0.5) matches divided by the max possible score, i.e. in
    [0, 1].
    """
    satisfied: list[str] = []

    # Hard gate: every required axis must pass.
    for axis, expected in rule["requires"].items():
        if not _axis_matches(vector.get(axis), expected):
            return 0.0, []
        satisfied.append(axis)

    # Soft supports contribute half-weight.
    support_hits = 0
    for axis, expected in rule["supports"].items():
        if _axis_matches(vector.get(axis), expected):
            satisfied.append(axis)
            support_hits += 1

    max_score = len(rule["requires"]) + 0.5 * len(rule["supports"])
    score = len(rule["requires"]) + 0.5 * support_hits
    return score / max_score if max_score else 0.0, satisfied


# ---------------------------------------------------------------------------
# Public: classify_compound_regime
# ---------------------------------------------------------------------------

def classify_compound_regime(vector: Optional[dict]) -> dict[str, Any]:
    """Pattern-match a regime vector against the compound rulebook.

    Returns::

        {
          "label":          "reflation" | "stagflation_pulse" | … | "none",
          "confidence":     float in [0, 1],
          "rationale":      str,
          "matched_axes":   list[str],          # axes that carried the rule
          "candidates":     list[{label, confidence}],   # runners-up
        }

    ``label == "none"`` when either the vector is unavailable or the
    best-fitting rule's confidence is below the floor — an honest
    "no locked compound pattern" instead of a low-confidence guess.
    """
    unavailable_result = {
        "label":        "none",
        "confidence":   0.0,
        "rationale":    "Regime vector unavailable",
        "matched_axes": [],
        "candidates":   [],
    }
    if not isinstance(vector, dict) or not vector.get("available"):
        return unavailable_result

    scored: list[tuple[float, dict, list[str]]] = []
    for rule in _RULES:
        conf, axes = _score_rule(vector, rule)
        if conf > 0:
            scored.append((conf, rule, axes))

    if not scored:
        return {
            **unavailable_result,
            "rationale": "No compound regime rule matched the vector",
        }

    scored.sort(key=lambda t: -t[0])
    best_conf, best_rule, best_axes = scored[0]

    candidates = [
        {"label": r["label"], "confidence": round(c, 3)}
        for (c, r, _a) in scored[1:4]
    ]

    if best_conf < _COMPOUND_CONFIDENCE_FLOOR:
        return {
            "label":        "none",
            "confidence":   round(best_conf, 3),
            "rationale": (
                f"Best candidate `{best_rule['label']}` below "
                f"{_COMPOUND_CONFIDENCE_FLOOR:.2f} confidence floor"
            ),
            "matched_axes": best_axes,
            "candidates":   [{"label": best_rule["label"],
                              "confidence": round(best_conf, 3)}] + candidates,
        }

    return {
        "label":        best_rule["label"],
        "confidence":   round(best_conf, 3),
        "rationale":    best_rule["rationale"],
        "matched_axes": best_axes,
        "candidates":   candidates,
    }


# ---------------------------------------------------------------------------
# Public: detect_regime_transition
# ---------------------------------------------------------------------------

_STABLE_CEILING: int = 1    # <=1 axes differ → stable
_SHIFT_CEILING:  int = 3    # 2..3 axes differ → shifting; more → still shifting,
                            #                     flip check dominates for >3


def _axis_direction(axis: str, before: Any, after: Any) -> str:
    """Classify a single axis change.

    Returns one of ``"flip"`` (opposite-pair), ``"toward_neutral"``,
    ``"away_from_neutral"``, or ``"lateral"`` so the caller can reason
    about whether the shift is a sign change or just drift.
    """
    if before == after:
        return "stable"
    opposites = _AXIS_OPPOSITES.get(axis, frozenset())
    if before in opposites and after in opposites and before != after:
        return "flip"
    if after == "neutral" and before != "neutral":
        return "toward_neutral"
    if before == "neutral" and after != "neutral":
        return "away_from_neutral"
    return "lateral"


def detect_regime_transition(
    current: Optional[dict],
    baseline: Optional[dict],
) -> dict[str, Any]:
    """Summarise the macro-regime shift between baseline and current.

    Returns::

        {
          "state":         "stable" | "shifting" | "flipping" | "unavailable",
          "changed_axes":  [
            {"axis": str, "before": str, "after": str, "direction": str},
            ...
          ],
          "rationale":     str,
        }

    ``state`` is picked by these rules, evaluated top-to-bottom:

      * either side unavailable           → ``"unavailable"``
      * ANY axis shows an opposite-pair flip → ``"flipping"``
      * <= 1 axis differs                 → ``"stable"``
      * otherwise                         → ``"shifting"``
    """
    if not isinstance(current, dict) or not current.get("available"):
        return {"state": "unavailable", "changed_axes": [],
                "rationale": "Current vector unavailable"}
    if not isinstance(baseline, dict) or not baseline.get("available"):
        return {"state": "unavailable", "changed_axes": [],
                "rationale": "Baseline vector unavailable"}

    changed: list[dict[str, str]] = []
    any_flip = False
    for axis in REGIME_AXES:
        before = baseline.get(axis)
        after = current.get(axis)
        if before == after:
            continue
        direction = _axis_direction(axis, before, after)
        if direction == "flip":
            any_flip = True
        changed.append({
            "axis":      axis,
            "before":    str(before) if before is not None else "neutral",
            "after":     str(after) if after is not None else "neutral",
            "direction": direction,
        })

    if any_flip:
        state = "flipping"
        rationale = (
            f"{len(changed)} axis change(s); "
            f"at least one opposite-pair flip"
        )
    elif len(changed) <= _STABLE_CEILING:
        state = "stable"
        rationale = (
            "Matches baseline across all axes" if not changed
            else f"Baseline match on {len(REGIME_AXES) - 1} of {len(REGIME_AXES)} axes"
        )
    else:
        state = "shifting"
        rationale = f"{len(changed)} of {len(REGIME_AXES)} axes changed, no flip"

    return {"state": state, "changed_axes": changed, "rationale": rationale}


# ---------------------------------------------------------------------------
# Public: baseline_from_events
# ---------------------------------------------------------------------------

_BASELINE_MIN_SAMPLE: int = 3


def baseline_from_events(
    events: Optional[list[dict]],
    *,
    min_sample: int = _BASELINE_MIN_SAMPLE,
) -> Optional[dict]:
    """Compute a modal regime vector across saved events.

    For each axis, the modal (most common) non-``None`` value across
    every event's persisted ``regime_snapshot`` becomes the baseline
    value.  Ties break toward the most recently-seen value (input
    order is assumed newest-first, matching ``db.load_recent_events``).

    Returns ``None`` when fewer than ``min_sample`` events carry an
    available regime snapshot — a small-sample baseline is worse than
    no baseline, since transitions would flicker on single outliers.
    """
    if not events:
        return None

    snapshots: list[dict] = []
    for ev in events:
        snap = ev.get("regime_snapshot") if isinstance(ev, dict) else None
        if isinstance(snap, dict) and snap.get("available"):
            snapshots.append(snap)

    if len(snapshots) < min_sample:
        return None

    baseline: dict[str, Any] = {"available": True, "stale": False}

    for axis in REGIME_AXES:
        values = [s.get(axis) for s in snapshots]
        values = [v for v in values if v]
        if not values:
            baseline[axis] = "neutral"
            continue
        counts = Counter(values)
        top_count = counts.most_common(1)[0][1]
        # Collect every value tied for the top count; pick the one that
        # appeared most recently in the event list (snapshots[0] is
        # newest).  Deterministic tie-break without sorting bias.
        tied = {v for v, c in counts.items() if c == top_count}
        chosen = next((v for v in values if v in tied), values[0])
        baseline[axis] = chosen

    return baseline


# ---------------------------------------------------------------------------
# Public: enrich_with_compound_regime
# ---------------------------------------------------------------------------

def enrich_with_compound_regime(
    vector: Optional[dict],
    baseline: Optional[dict] = None,
) -> dict[str, Any]:
    """Return a copy of ``vector`` with ``compound`` + ``transition``
    fields attached.

    Never raises.  Unavailable vectors come back with the new fields
    populated by their respective ``unavailable`` sentinels so callers
    can always dereference them without a None-check.
    """
    if not isinstance(vector, dict):
        vector = {}
    out = dict(vector)
    out["compound"] = classify_compound_regime(vector if vector else None)
    out["transition"] = detect_regime_transition(
        vector if vector else None, baseline,
    )
    return out

"""Side-by-side comparison of two cohort research reports.

Takes two reports as emitted by ``cohort_research.run_batch_research``
and produces a deterministic side-by-side diff across the structural
axes (mechanism family, stage, persistence label, regime) and the
outcome axes (repricing path, persistence hold rate, falsification
rate, 20d mean return).  The output is a compact research note
answering questions like:

    "How did tariff cycles differ across regimes?"
    "Which funding-squeeze cohort had stronger follow-through?"
    "When do similar mechanisms produce different outcomes?"

Design notes
------------
* Pure composer: no I/O; never raises on malformed input.
* Each diff dimension carries its own magnitude bucket (``large``,
  ``medium``, ``small``, ``noise``) so the caller doesn't have to
  recompute whether a 3-pt hold-rate gap matters.  The thresholds are
  pinned module constants.
* The aggregate ``divergence_score`` in [0, 1] is a deterministic
  weighted sum of the outcome-axis magnitudes — structural differences
  (same cohort size but different regime) shouldn't mask that they
  actually repriced the same way.
* A ``headline_insight`` one-liner summarises the dominant divergence
  so the UI / prompt can print a single research-style sentence
  without reassembling the dimension list.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Magnitude thresholds — pinned so calibrate_thresholds can audit.
# ---------------------------------------------------------------------------

# Rate-style deltas (hold_rate, failure_rate, typical_share, distribution share).
_RATE_LARGE: float = 0.30
_RATE_MEDIUM: float = 0.15
_RATE_SMALL: float = 0.05

# Percentage-point deltas (mean_20d, median_abs_20d).
_PP_LARGE: float = 2.0
_PP_MEDIUM: float = 1.0
_PP_SMALL: float = 0.3

# Weights for the divergence score.  Outcome axes dominate structural
# ones by design: when comparing cohorts a reader mostly cares whether
# the repricing diverged, not whether the composition did.
_WEIGHT_REPRICING: float = 0.30
_WEIGHT_HOLD_RATE: float = 0.25
_WEIGHT_FAILURE: float = 0.20
_WEIGHT_MEAN_20D: float = 0.15
_WEIGHT_COMPOSITION: float = 0.10

MAGNITUDES: tuple = ("noise", "small", "medium", "large")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rate_magnitude(delta: Optional[float]) -> str:
    if delta is None:
        return "noise"
    a = abs(delta)
    if a >= _RATE_LARGE:
        return "large"
    if a >= _RATE_MEDIUM:
        return "medium"
    if a >= _RATE_SMALL:
        return "small"
    return "noise"


def _pp_magnitude(delta: Optional[float]) -> str:
    if delta is None:
        return "noise"
    a = abs(delta)
    if a >= _PP_LARGE:
        return "large"
    if a >= _PP_MEDIUM:
        return "medium"
    if a >= _PP_SMALL:
        return "small"
    return "noise"


def _magnitude_score(mag: str) -> float:
    """Map magnitude label to a normalized weight in [0, 1]."""
    return {"large": 1.0, "medium": 0.6, "small": 0.25, "noise": 0.0}.get(mag, 0.0)


def _safe_rate(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _direction(delta: Optional[float]) -> str:
    if delta is None:
        return "tie"
    if delta > 0:
        return "a"
    if delta < 0:
        return "b"
    return "tie"


def _top_key(dist: dict[str, int]) -> Optional[str]:
    if not dist:
        return None
    # Deterministic tie-break on key lexicographic order.
    return max(dist.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _share_for(dist: dict[str, int], key: Optional[str]) -> float:
    total = sum(dist.values()) if dist else 0
    if not key or total == 0:
        return 0.0
    return dist.get(key, 0) / total


def _jensen_shannon_like(a: dict[str, int], b: dict[str, int]) -> float:
    """Symmetric total-variation-style distance in [0, 1].

    Used for composition distributions where we just want a single
    "how different are these buckets" number.  Uses total-variation
    distance (max distance between any bucket shares) rather than the
    full JSD — simpler, still bounded, and deterministic.
    """
    total_a = sum(a.values()) if a else 0
    total_b = sum(b.values()) if b else 0
    if total_a == 0 and total_b == 0:
        return 0.0
    if total_a == 0 or total_b == 0:
        return 1.0
    keys = set(a) | set(b)
    max_diff = 0.0
    for k in keys:
        pa = a.get(k, 0) / total_a
        pb = b.get(k, 0) / total_b
        d = abs(pa - pb)
        if d > max_diff:
            max_diff = d
    return max_diff


def _get_nested(d: dict, *path: str, default=None):
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, default if key == path[-1] else None)
    return cur


# ---------------------------------------------------------------------------
# Dimension builders
# ---------------------------------------------------------------------------

def _dim_repricing(a: dict, b: dict) -> dict[str, Any]:
    a_label = _get_nested(a, "repricing_path", "typical") or "unknown"
    b_label = _get_nested(b, "repricing_path", "typical") or "unknown"
    a_share = float(_get_nested(a, "repricing_path", "typical_share") or 0.0)
    b_share = float(_get_nested(b, "repricing_path", "typical_share") or 0.0)
    share_delta = round(a_share - b_share, 3)
    # Magnitude combines "do they agree on the label" with "how dominant
    # is each cohort's typical path" — disagreeing labels with thin
    # shares are still only noise.
    if a_label != b_label and max(a_share, b_share) >= 0.5:
        mag = "large" if max(a_share, b_share) >= 0.6 else "medium"
    else:
        mag = _rate_magnitude(share_delta)
    return {
        "axis":       "repricing_path",
        "a_value":    a_label,
        "b_value":    b_label,
        "a_share":    round(a_share, 3),
        "b_share":    round(b_share, 3),
        "delta":      share_delta,
        "direction":  _direction(share_delta),
        "magnitude":  mag,
    }


def _dim_hold_rate(a: dict, b: dict) -> dict[str, Any]:
    a_val = _get_nested(a, "persistence", "hold_rate")
    b_val = _get_nested(b, "persistence", "hold_rate")
    if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
        delta = round(a_val - b_val, 3)
    else:
        delta = None
    return {
        "axis":       "hold_rate",
        "a_value":    a_val,
        "b_value":    b_val,
        "delta":      delta,
        "direction":  _direction(delta),
        "magnitude":  _rate_magnitude(delta),
    }


def _dim_failure_rate(a: dict, b: dict) -> dict[str, Any]:
    a_val = _get_nested(a, "falsification", "event_failure_rate")
    b_val = _get_nested(b, "falsification", "event_failure_rate")
    if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
        delta = round(a_val - b_val, 3)
    else:
        delta = None
    return {
        "axis":       "failure_rate",
        "a_value":    a_val,
        "b_value":    b_val,
        "delta":      delta,
        "direction":  _direction(delta),
        "magnitude":  _rate_magnitude(delta),
    }


def _dim_mean_20d(a: dict, b: dict) -> dict[str, Any]:
    a_val = _get_nested(a, "persistence", "mean_20d")
    b_val = _get_nested(b, "persistence", "mean_20d")
    if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
        delta = round(a_val - b_val, 2)
    else:
        delta = None
    return {
        "axis":       "mean_20d",
        "a_value":    a_val,
        "b_value":    b_val,
        "delta":      delta,
        "direction":  _direction(delta),
        "magnitude":  _pp_magnitude(delta),
    }


def _dim_composition(
    a: dict, b: dict, key: str, axis_label: str,
) -> dict[str, Any]:
    a_dist = _get_nested(a, "composition", key) or {}
    b_dist = _get_nested(b, "composition", key) or {}
    a_top = _top_key(a_dist)
    b_top = _top_key(b_dist)
    tv = _jensen_shannon_like(a_dist, b_dist)
    mag = _rate_magnitude(tv)
    return {
        "axis":              axis_label,
        "a_top":             a_top,
        "b_top":             b_top,
        "a_top_share":       round(_share_for(a_dist, a_top), 3),
        "b_top_share":       round(_share_for(b_dist, b_top), 3),
        "a_distribution":    a_dist,
        "b_distribution":    b_dist,
        "distance":          round(tv, 3),
        "magnitude":         mag,
    }


# ---------------------------------------------------------------------------
# Divergence + headline insight
# ---------------------------------------------------------------------------

def _divergence_score(dims: list[dict]) -> float:
    """Weighted average of outcome-axis magnitudes, in [0, 1]."""
    by_axis = {d["axis"]: d for d in dims}
    components: list[tuple[float, float]] = []
    for axis, weight in (
        ("repricing_path", _WEIGHT_REPRICING),
        ("hold_rate",      _WEIGHT_HOLD_RATE),
        ("failure_rate",   _WEIGHT_FAILURE),
        ("mean_20d",       _WEIGHT_MEAN_20D),
    ):
        d = by_axis.get(axis)
        if d:
            components.append((weight, _magnitude_score(d["magnitude"])))
    composition_axes = [
        d for d in dims if d["axis"] in {"mechanism_family", "stage", "persistence_label", "regime"}
    ]
    if composition_axes:
        comp_avg = sum(_magnitude_score(d["magnitude"]) for d in composition_axes) / len(composition_axes)
        components.append((_WEIGHT_COMPOSITION, comp_avg))

    if not components:
        return 0.0
    total_weight = sum(w for w, _ in components)
    weighted = sum(w * s for w, s in components)
    return max(0.0, min(1.0, weighted / total_weight if total_weight else 0.0))


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{int(round(v * 100))}%"


def _fmt_pp(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _headline_insight(
    a_label: str, b_label: str, dims: list[dict], divergence: float,
) -> str:
    """One-line research-style summary of the dominant divergence."""
    if divergence < 0.1:
        return (
            f"{a_label} and {b_label} look similar across repricing, "
            "persistence, and falsification — the cohorts rhyme."
        )

    by_axis = {d["axis"]: d for d in dims}
    priority = ("repricing_path", "hold_rate", "failure_rate", "mean_20d")
    for axis in priority:
        d = by_axis.get(axis)
        if not d or d.get("magnitude") in ("noise", "small"):
            continue
        if axis == "repricing_path":
            if d["a_value"] != d["b_value"]:
                return (
                    f"{a_label} typically {d['a_value']} at 20d while "
                    f"{b_label} runs {d['b_value']} — the repricing path "
                    "diverges."
                )
            return (
                f"Both {a_label} and {b_label} lean {d['a_value']}, but "
                f"{a_label} commits harder ({_fmt_pct(d['a_share'])} vs "
                f"{_fmt_pct(d['b_share'])})."
            )
        if axis == "hold_rate":
            winner = a_label if d["direction"] == "a" else b_label
            loser = b_label if winner == a_label else a_label
            return (
                f"{winner} held in {_fmt_pct(d['a_value' if winner == a_label else 'b_value'])} "
                f"of events vs {_fmt_pct(d['b_value' if winner == a_label else 'a_value'])} "
                f"for {loser} — stronger follow-through."
            )
        if axis == "failure_rate":
            # Lower failure rate wins.
            loser = a_label if d["direction"] == "a" else b_label
            winner = b_label if loser == a_label else a_label
            return (
                f"{loser} got falsified in "
                f"{_fmt_pct(d['a_value' if loser == a_label else 'b_value'])} "
                f"of events vs {_fmt_pct(d['b_value' if loser == a_label else 'a_value'])} "
                f"for {winner} — {loser} fails faster."
            )
        if axis == "mean_20d":
            winner = a_label if d["direction"] == "a" else b_label
            loser = b_label if winner == a_label else a_label
            return (
                f"{winner} drifted "
                f"{_fmt_pp(d['a_value' if winner == a_label else 'b_value'])} "
                f"at 20d vs {_fmt_pp(d['b_value' if winner == a_label else 'a_value'])} "
                f"for {loser}."
            )

    # No outcome axis separated them — fall back to composition.
    for axis in ("regime", "mechanism_family", "stage", "persistence_label"):
        d = by_axis.get(axis)
        if d and d.get("magnitude") in ("medium", "large"):
            return (
                f"{a_label} and {b_label} move similarly but differ in "
                f"{axis} composition (top: {d['a_top']} vs {d['b_top']})."
            )

    return f"{a_label} and {b_label} diverge modestly across multiple axes."


def _confidence_floor(a: dict, b: dict) -> str:
    """Lower of the two cohorts' confidence bases."""
    order = {"deep": 2, "medium": 1, "thin": 0}
    a_b = a.get("confidence_basis") or "thin"
    b_b = b.get("confidence_basis") or "thin"
    return a_b if order.get(a_b, 0) <= order.get(b_b, 0) else b_b


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compare_cohorts(
    cohort_a: Optional[dict],
    cohort_b: Optional[dict],
) -> dict[str, Any]:
    """Produce a deterministic side-by-side comparison of two cohort reports.

    Accepts the dict shape emitted by ``cohort_research.run_batch_research``
    (composition block required for structural axes; missing keys
    degrade to "noise" diffs).

    Returns:
        {
          "a_label": str, "b_label": str,
          "a_size":  int, "b_size":  int,
          "confidence_basis": str,
          "dimensions": [
            {axis, a_value, b_value, delta, direction, magnitude, ...},
          ],
          "divergence_score": float,        # [0, 1]
          "headline_insight": str,
          "rationale": str,
        }
    """
    a = cohort_a if isinstance(cohort_a, dict) else {}
    b = cohort_b if isinstance(cohort_b, dict) else {}

    a_label = a.get("cohort_label") or "Cohort A"
    b_label = b.get("cohort_label") or "Cohort B"
    a_size = int(a.get("size") or 0)
    b_size = int(b.get("size") or 0)

    dims: list[dict] = [
        _dim_repricing(a, b),
        _dim_hold_rate(a, b),
        _dim_failure_rate(a, b),
        _dim_mean_20d(a, b),
        _dim_composition(a, b, "mechanism_family", "mechanism_family"),
        _dim_composition(a, b, "stage", "stage"),
        _dim_composition(a, b, "persistence_label", "persistence_label"),
        _dim_composition(a, b, "regime", "regime"),
    ]

    if a_size == 0 or b_size == 0:
        return {
            "a_label":          a_label,
            "b_label":          b_label,
            "a_size":           a_size,
            "b_size":           b_size,
            "confidence_basis": "thin",
            "dimensions":       dims,
            "divergence_score": 0.0,
            "headline_insight": (
                f"Cannot compare: {a_label if a_size == 0 else b_label} is empty."
            ),
            "rationale": "One of the cohorts has no members.",
        }

    divergence = round(_divergence_score(dims), 3)
    basis = _confidence_floor(a, b)
    insight = _headline_insight(a_label, b_label, dims, divergence)

    rationale = (
        f"Comparing {a_label} (n={a_size}) vs {b_label} (n={b_size}); "
        f"divergence score {divergence} on a 0-1 scale; confidence floor {basis}."
    )

    return {
        "a_label":          a_label,
        "b_label":          b_label,
        "a_size":           a_size,
        "b_size":           b_size,
        "confidence_basis": basis,
        "dimensions":       dims,
        "divergence_score": divergence,
        "headline_insight": insight,
        "rationale":        rationale,
    }


# ---------------------------------------------------------------------------
# Filter-based public wrapper — compares two filter specs over one event pool
# ---------------------------------------------------------------------------
# The report-shape ``compare_cohorts`` above is the structural core; it takes
# two already-computed cohort reports and returns the diff.  Researchers
# usually want to drive the pipeline from filter specs — "tariff cycles in
# reflation vs tariff cycles in stagflation" — without orchestrating
# ``run_batch_research`` calls themselves.  This wrapper takes the raw event
# archive + two declarative filter specs, runs the cohort builder on each,
# and hands the resulting reports to ``compare_cohorts``.
#
# The filter schema is CLOSED — unknown keys raise ``ValueError`` so a typo
# doesn't silently match every event.  Hard thin-sample floor: both cohorts
# must have ≥ ``_FILTER_MIN_COHORT_SIZE`` members or the comparison refuses
# to compute and returns ``available=False, reason="thin_sample"``.


_FILTER_MIN_COHORT_SIZE: int = 3

_FILTER_ALLOWED_KEYS: frozenset[str] = frozenset({
    "family",
    "regime_inflation",
    "regime_policy_stance",
    "compound_regime",
    "stage",
    "persistence",
    "scenario_pack",
})


def _validate_filter_spec(spec: Any, *, which: str) -> dict[str, str]:
    """Validate a filter dict and return a normalised copy.

    Raises ``ValueError`` on unknown keys or non-string values.  Empty
    dict is valid — matches every event (the "all events" cohort).
    """
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ValueError(
            f"filter_{which} must be a dict, got {type(spec).__name__}",
        )
    unknown = set(spec.keys()) - _FILTER_ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"filter_{which} has unknown keys: {sorted(unknown)}; "
            f"allowed keys: {sorted(_FILTER_ALLOWED_KEYS)}"
        )
    out: dict[str, str] = {}
    for key, value in spec.items():
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError(
                f"filter_{which}[{key!r}] must be a string, "
                f"got {type(value).__name__}"
            )
        v = value.strip()
        if v:
            out[key] = v
    if "family" in out:
        # Lazy import so this module stays importable on upgrade paths.
        from mechanism_family import FAMILY_IDS
        if out["family"] not in FAMILY_IDS:
            raise ValueError(
                f"filter_{which}.family={out['family']!r} is not a known "
                f"mechanism family; allowed: {sorted(FAMILY_IDS)}",
            )
    return out


def compare_cohorts_by_filter(
    events: Optional[list[dict]],
    filter_a: Optional[dict[str, str]],
    filter_b: Optional[dict[str, str]],
    *,
    label_a: Optional[str] = None,
    label_b: Optional[str] = None,
) -> dict[str, Any]:
    """Compare two cohorts defined by declarative filter specs.

    Filter-spec keys (closed set; unknown keys raise ``ValueError``):

      * ``family``                — mechanism family id
      * ``regime_inflation``      — ``regime_snapshot.inflation``
      * ``regime_policy_stance``  — ``regime_snapshot.policy_stance``
      * ``compound_regime``       — ``regime_snapshot.compound.label``
      * ``stage``                 — event stage
      * ``persistence``           — event persistence label
      * ``scenario_pack``         — one of ``cohort_research.SCENARIO_PACKS``

    Returns the same shape as :func:`compare_cohorts` with two extras on
    the envelope::

        {
          ...all compare_cohorts keys...,
          "available":     bool,
          "reason":        "thin_sample" | None,
          "filter_a":      dict,   # normalised spec for provenance
          "filter_b":      dict,
        }

    An empty filter dict selects the whole pool (the "all events" cohort).
    """
    spec_a = _validate_filter_spec(filter_a, which="a")
    spec_b = _validate_filter_spec(filter_b, which="b")

    # Lazy import so the module stays usable when cohort_research is
    # mid-refactor — avoids a circular import surprise.
    from cohort_research import run_batch_research

    def _run(spec: dict, label: Optional[str]) -> dict:
        fam = spec.get("family") or None
        pack = spec.get("scenario_pack") or None
        return run_batch_research(
            events or [],
            mechanism_family=fam,
            scenario_pack=pack,
            stage=spec.get("stage") or None,
            persistence=spec.get("persistence") or None,
            regime_inflation=spec.get("regime_inflation") or None,
            regime_policy_stance=spec.get("regime_policy_stance") or None,
            compound_regime=spec.get("compound_regime") or None,
            cohort_label=label,
        )

    report_a = _run(spec_a, label_a)
    report_b = _run(spec_b, label_b)

    size_a = int(report_a.get("size") or 0)
    size_b = int(report_b.get("size") or 0)
    if size_a < _FILTER_MIN_COHORT_SIZE or size_b < _FILTER_MIN_COHORT_SIZE:
        return {
            "available":        False,
            "reason":           "thin_sample",
            "a_label":          report_a.get("cohort_label") or (label_a or "A"),
            "b_label":          report_b.get("cohort_label") or (label_b or "B"),
            "a_size":           size_a,
            "b_size":           size_b,
            "filter_a":         spec_a,
            "filter_b":         spec_b,
            "confidence_basis": "thin",
            "dimensions":       [],
            "divergence_score": 0.0,
            "headline_insight": (
                f"Thin sample — need ≥{_FILTER_MIN_COHORT_SIZE} events per "
                f"cohort (A={size_a}, B={size_b})."
            ),
            "rationale": (
                f"Cohort A has {size_a} event(s); cohort B has {size_b}. "
                f"Floor is {_FILTER_MIN_COHORT_SIZE} per side."
            ),
        }

    diff = compare_cohorts(report_a, report_b)
    diff["available"] = True
    diff["reason"]    = None
    diff["filter_a"]  = spec_a
    diff["filter_b"]  = spec_b
    return diff

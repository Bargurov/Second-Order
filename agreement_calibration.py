"""
agreement_calibration.py

Historical calibration layer for agreement scoring.

Why this module
---------------
The agreement engine emits a signed ``weighted_score`` and a verdict
tier.  Taken alone, a mid-band score like +0.25 is opaque — is that
a tepid-but-positive read, or is it the kind of score that has
historically played out 58% of the time for this mechanism family in
this regime?  A macro desk asking the latter question needs a
calibration layer grounded in saved outcomes.

This module wraps the already-shipped ``confidence_calibration``
tree (the cascading family+regime+confidence → hit rate registry)
and overlays two orthogonal reads:

  * **cohort_reliability** — how noisy is the historical cohort
    itself?  A 50% hit rate means the pattern is a coin flip even
    when it scores high; a 65% hit rate means the cohort carries a
    real edge.  Four bands: ``strong / moderate / noisy / weak``.

  * **thesis_vs_cohort** — is the current thesis's implied
    probability ahead of / behind / aligned with the historical
    cohort mean?  A thesis scoring 0.70 in a cohort that averaged
    0.55 is "above"; the same 0.70 score in a 0.68 cohort is
    "aligned".

Combining the two answers the question the user asked: "low
agreement because thesis is weak" vs "low agreement because this
evidence pattern is historically noisy".

Pure composer.  No I/O.  Never raises.  Falls back cleanly when no
cohort data is available or the sample is too thin.

Contract
--------
    calibrate_agreement(agreement, *, mechanism_family, compound_regime,
                         confidence, calibration_tree) -> dict

    build_historical_tree(samples) -> dict
        thin convenience wrapper around ``confidence_calibration
        .build_calibration_tree`` so callers don't need two imports.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Thresholds — calibrated to the existing archive depth + the bands
# the confidence_calibration layer already uses.
# ---------------------------------------------------------------------------

# Cohort-reliability bands.  A 50% hit rate is a coin flip — the
# "noisy" band intentionally tight (±5pp) so a 46% or 53% cohort both
# still read as noisy.  Outside that band, 60%+ = strong, 40%- = weak.
_COHORT_STRONG_FLOOR: float = 0.60
_COHORT_NOISY_BAND:   tuple[float, float] = (0.45, 0.55)
_COHORT_WEAK_CEIL:    float = 0.40

# Thesis-vs-cohort tolerance — within ±12 percentage points the current
# thesis's implied probability is "aligned" with the historical mean.
_ALIGNMENT_BAND_PP: float = 0.12

# Weight given to the historical mean when blending the adjusted score.
# Grows with sample size but capped at 40% so a thin cohort can't
# completely override a strong raw score.
_MAX_BLEND_WEIGHT: float = 0.40
_BLEND_SATURATION_N: int = 100   # n at which the cap is reached


# ---------------------------------------------------------------------------
# Diagnosis codes — compact enum for telemetry + UI routing
# ---------------------------------------------------------------------------

DIAGNOSIS_CODES: tuple[str, ...] = (
    "strong_cohort_confirming_thesis",   # cohort works, thesis aligned+
    "strong_cohort_weak_thesis",          # cohort works but THIS thesis lags
    "noisy_pattern",                       # cohort itself is a coin flip
    "weak_cohort",                         # cohort historically failed
    "weak_cohort_thesis_beating_it",       # rare: strong raw score in weak cohort
    "moderate_cohort_aligned",             # middle-of-the-road everything
    "moderate_cohort_thesis_ahead",        # thesis beats a middling cohort
    "moderate_cohort_thesis_behind",       # thesis lags a middling cohort
    "thin_sample",                         # cohort depth below the reliable floor
    "no_cohort_data",                      # no calibration tree or no lookup
)


_DIAGNOSIS_LABEL: dict[str, str] = {
    "strong_cohort_confirming_thesis":
        "Strong historical cohort — thesis confirming in line with / above average",
    "strong_cohort_weak_thesis":
        "Strong historical cohort but THIS thesis is lagging the cohort mean",
    "noisy_pattern":
        "Historical cohort is coin-flip — low agreement reflects a noisy pattern, not a broken thesis",
    "weak_cohort":
        "Historical cohort has failed more than succeeded — thesis class itself is fragile",
    "weak_cohort_thesis_beating_it":
        "Thesis scoring higher than its historically-weak cohort — edge worth re-checking",
    "moderate_cohort_aligned":
        "Moderate historical cohort — thesis tracking the expected band",
    "moderate_cohort_thesis_ahead":
        "Moderate historical cohort — thesis scoring ahead of the typical outcome",
    "moderate_cohort_thesis_behind":
        "Moderate historical cohort — thesis lagging the typical outcome",
    "thin_sample":
        "Too few historical analogs to calibrate against — treat score at face value",
    "no_cohort_data":
        "No calibration tree available — historical anchor unavailable",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _classify_cohort(hit_rate: float) -> str:
    if hit_rate >= _COHORT_STRONG_FLOOR:
        return "strong"
    if hit_rate <= _COHORT_WEAK_CEIL:
        return "weak"
    low, high = _COHORT_NOISY_BAND
    if low <= hit_rate <= high:
        return "noisy"
    return "moderate"


def _classify_alignment(implied: float, hit_rate: float) -> str:
    delta = implied - hit_rate
    if abs(delta) <= _ALIGNMENT_BAND_PP:
        return "aligned"
    return "above" if delta > 0 else "below"


def _diagnose(
    cohort: str,
    alignment: str,
    weak_depth: bool,
) -> str:
    """Return a canonical diagnosis code for the combined read."""
    if weak_depth:
        return "thin_sample"

    if cohort == "strong":
        if alignment == "below":
            return "strong_cohort_weak_thesis"
        return "strong_cohort_confirming_thesis"

    if cohort == "noisy":
        # Noisy cohort dominates — the diagnosis is "pattern is
        # noisy", regardless of alignment; a thesis can't really
        # "beat" a coin-flip cohort in a meaningful way.
        return "noisy_pattern"

    if cohort == "weak":
        if alignment == "above":
            return "weak_cohort_thesis_beating_it"
        return "weak_cohort"

    # moderate
    if alignment == "above":
        return "moderate_cohort_thesis_ahead"
    if alignment == "below":
        return "moderate_cohort_thesis_behind"
    return "moderate_cohort_aligned"


def _blended_implied(
    implied: float,
    hit_rate: float,
    n: int,
    weak_depth: bool,
) -> float:
    """Blend the current implied probability with the historical mean.

    The blend weight grows with ``n`` up to ``_MAX_BLEND_WEIGHT``.
    When ``weak_depth`` is set the blend is disabled entirely — thin
    samples must not second-guess a fresh score.
    """
    if weak_depth:
        return implied
    w = min(_MAX_BLEND_WEIGHT, max(0.0, n / _BLEND_SATURATION_N))
    return (1.0 - w) * implied + w * hit_rate


# ---------------------------------------------------------------------------
# Public: cohort-tree builder (thin convenience wrapper)
# ---------------------------------------------------------------------------

def build_historical_tree(samples: Optional[list[dict]]) -> dict[str, Any]:
    """Build the same cascading calibration tree the confidence
    calibration layer uses, so a caller that already has a sample list
    (from ``db.collect_calibration_samples``) can hand it in here
    without a second import.  Missing / None input degrades to an
    empty tree that lookups will report as ``insufficient``."""
    try:
        from confidence_calibration import build_calibration_tree
    except Exception:
        return {}
    return build_calibration_tree(samples or [])


# ---------------------------------------------------------------------------
# Public: per-event calibration
# ---------------------------------------------------------------------------

def calibrate_agreement(
    agreement: Optional[dict],
    *,
    mechanism_family: Optional[str] = None,
    compound_regime:  Optional[str] = None,
    confidence:        Optional[str] = None,
    calibration_tree:  Optional[dict] = None,
) -> dict[str, Any]:
    """Overlay a historical-calibration read onto the raw agreement verdict.

    Returns a dict with:

      * ``available``            — bool, True when a hit rate was resolved
      * ``implied_probability``  — float in [0, 1]; raw agreement mapped
      * ``historical_hit_rate``  — float in [0, 1] or None
      * ``historical_n``         — cohort sample size
      * ``depth_tier``           — from confidence_calibration (family+regime
                                   / family / regime / global / insufficient)
      * ``weak_depth``           — bool; True when the cohort is too thin
      * ``cohort_reliability``   — strong / moderate / noisy / weak / unknown
      * ``thesis_vs_cohort``     — aligned / above / below / unknown
      * ``diagnosis_code``       — one of DIAGNOSIS_CODES
      * ``diagnosis``            — one-line human read
      * ``adjusted_score``       — weighted_score bent toward cohort mean
                                   (signed, in [-1, 1]); equals the raw
                                   score when weak_depth or unavailable
    """
    agreement = agreement or {}

    # Map raw weighted_score ∈ [-1, 1] to an implied probability ∈ [0, 1].
    raw_score = _f(agreement.get("weighted_score")) or 0.0
    implied = max(0.0, min(1.0, (raw_score + 1.0) / 2.0))

    # Empty / None tree — surface the "no cohort data" sentinel.
    if not isinstance(calibration_tree, dict) or not calibration_tree:
        return _no_data_result(implied, raw_score, "no_cohort_data")

    # Normalise the regime key: None / "" / "none" all collapse to None
    # at the lookup level so the cascade can fall back cleanly.
    reg = compound_regime if (compound_regime and compound_regime != "none") else None
    fam = mechanism_family if (mechanism_family and mechanism_family != "none") else None

    try:
        from confidence_calibration import lookup_calibration
        lookup = lookup_calibration(
            calibration_tree,
            confidence=confidence or "medium",
            family=fam,
            compound_regime=reg,
        )
    except Exception:
        return _no_data_result(implied, raw_score, "no_cohort_data")

    hit_rate = _f(lookup.get("hit_rate"))
    depth_tier = lookup.get("depth_tier") or "insufficient"
    weak_depth = bool(lookup.get("weak"))
    n = int(lookup.get("n") or 0)

    if hit_rate is None or depth_tier == "insufficient":
        # No usable cohort — map to the thin-sample diagnosis.
        return {
            "available":           False,
            "implied_probability": round(implied, 3),
            "historical_hit_rate": None,
            "historical_n":        n,
            "depth_tier":          depth_tier,
            "weak_depth":          True,
            "cohort_reliability":  "unknown",
            "thesis_vs_cohort":    "unknown",
            "diagnosis_code":      "thin_sample" if n > 0 else "no_cohort_data",
            "diagnosis":            _DIAGNOSIS_LABEL["thin_sample" if n > 0 else "no_cohort_data"],
            "adjusted_score":       round(raw_score, 3),
        }

    cohort = _classify_cohort(hit_rate)
    alignment = _classify_alignment(implied, hit_rate)
    code = _diagnose(cohort, alignment, weak_depth)

    adjusted_implied = _blended_implied(implied, hit_rate, n, weak_depth)
    adjusted_score = 2.0 * adjusted_implied - 1.0

    return {
        "available":           True,
        "implied_probability": round(implied, 3),
        "historical_hit_rate": round(hit_rate, 3),
        "historical_n":        n,
        "depth_tier":          depth_tier,
        "weak_depth":          weak_depth,
        "cohort_reliability":  cohort,
        "thesis_vs_cohort":    alignment,
        "diagnosis_code":       code,
        "diagnosis":            _DIAGNOSIS_LABEL.get(code, code),
        "adjusted_score":       round(adjusted_score, 3),
    }


def _no_data_result(implied: float, raw_score: float, code: str) -> dict[str, Any]:
    return {
        "available":           False,
        "implied_probability": round(implied, 3),
        "historical_hit_rate": None,
        "historical_n":        0,
        "depth_tier":          "insufficient",
        "weak_depth":          True,
        "cohort_reliability":  "unknown",
        "thesis_vs_cohort":    "unknown",
        "diagnosis_code":       code,
        "diagnosis":            _DIAGNOSIS_LABEL.get(code, code),
        "adjusted_score":       round(raw_score, 3),
    }

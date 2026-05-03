"""
confidence_calibration.py

Regime-conditioned, mechanism-family-aware confidence calibration.

Why this module
---------------
``db.get_confidence_calibration_stats`` surfaces ONE global hit rate per
confidence bucket — "high-confidence events hit 0.67" — mixing every
mechanism family and every macro regime into a single signal.  In
practice, a supply-shock event under funding-stress is not the same
calibration class as a tariff event under reflation; the global number
misses that texture.

This module adds a cascading-fallback calibration that tries the
finest slice first and degrades to coarser ones only when sample
depth is too thin to trust.  Preference order::

    (confidence, family, compound_regime)   —  strict joint
    (confidence, family)                    —  family-only fallback
    (confidence, compound_regime)           —  regime-only fallback
    (confidence)                            —  global (always last)

Each slice must clear its own minimum-sample floor before it is
returned.  When NOTHING clears even the global floor, the lookup
returns an explicit ``depth_tier="insufficient"`` verdict rather than
inventing a hit rate out of a one-or-two-event sample.

All inputs are passed in; the module itself makes no DB calls.  Sample
collection lives in :func:`db.collect_calibration_samples` so this
layer stays pure and unit-testable on in-memory fixtures.

Contract
--------
    build_calibration_tree(samples)
        → nested {(confidence, family, compound_regime): {n, validated, hit_rate}}
          plus per-bucket marginals

    lookup_calibration(tree, *, confidence, family, compound_regime)
        → {
            hit_rate:        float | None,
            n:               int,
            depth_tier:      "family+regime" | "family" | "regime"
                              | "global" | "insufficient",
            weak:            bool,          # True when the archive is too thin
            sample_warning:  str | None,    # human-readable when weak / insufficient
            slice_key:       tuple,         # the exact slice that resolved the lookup
          }
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Sample-depth floors — empirically reasonable for the archive scale the
# app currently runs at.  Below the FAMILY+REGIME joint floor the slice is
# assumed too noisy to beat the coarser fallback.
# ---------------------------------------------------------------------------

_N_STRICT: int = 10   # family + compound_regime joint slice
_N_FAMILY: int = 5    # family marginal (family-only fallback)
_N_REGIME: int = 5    # compound_regime marginal (regime-only fallback)
_N_GLOBAL: int = 3    # confidence-only global slice

# Quality bar above which we do NOT mark a slice as weak.  Slices
# between the per-tier floor and this threshold still resolve but carry
# weak=True so the UI can render a thin-sample warning chip.
_WEAK_BELOW: int = 10

_VALID_CONFIDENCE: frozenset[str] = frozenset({"low", "medium", "high"})


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------

def _empty_bucket() -> dict[str, Any]:
    return {"validated": 0, "n": 0}


def _bucket_stats(bucket: dict) -> dict[str, Any]:
    n = bucket["n"]
    v = bucket["validated"]
    return {
        "n":         n,
        "validated": v,
        "hit_rate":  round(v / n, 3) if n > 0 else None,
    }


def build_calibration_tree(samples: Iterable[dict]) -> dict[str, Any]:
    """Aggregate raw samples into the four slice-depth tables.

    Returned shape::

        {
          "joint":       {(confidence, family, regime): {n, validated, hit_rate}},
          "family":      {(confidence, family):          {n, validated, hit_rate}},
          "regime":      {(confidence, regime):          {n, validated, hit_rate}},
          "global":      {confidence:                    {n, validated, hit_rate}},
          "total":       int,                 # total usable samples
        }

    ``samples`` is the list produced by ``db.collect_calibration_samples``.
    Malformed entries (non-dict, missing confidence, unknown confidence
    label) are skipped silently so a single bad row can't poison the
    whole tree.
    """
    joint:     dict[tuple, dict] = {}
    by_family: dict[tuple, dict] = {}
    by_regime: dict[tuple, dict] = {}
    by_global: dict[str,   dict] = {}
    total = 0

    for s in samples or []:
        if not isinstance(s, dict):
            continue
        conf = s.get("confidence")
        if conf not in _VALID_CONFIDENCE:
            continue
        family = (s.get("family") or "none") or "none"
        regime = (s.get("compound_regime") or "none") or "none"
        validated = 1 if s.get("validated") else 0

        total += 1

        for table, key in (
            (joint,     (conf, family, regime)),
            (by_family, (conf, family)),
            (by_regime, (conf, regime)),
        ):
            slot = table.setdefault(key, _empty_bucket())
            slot["n"] += 1
            slot["validated"] += validated

        g = by_global.setdefault(conf, _empty_bucket())
        g["n"] += 1
        g["validated"] += validated

    return {
        "joint":  {k: _bucket_stats(v) for k, v in joint.items()},
        "family": {k: _bucket_stats(v) for k, v in by_family.items()},
        "regime": {k: _bucket_stats(v) for k, v in by_regime.items()},
        "global": {k: _bucket_stats(v) for k, v in by_global.items()},
        "total":  total,
    }


# ---------------------------------------------------------------------------
# Lookup with cascade
# ---------------------------------------------------------------------------

def _resolved_result(
    slice_key: tuple,
    bucket:    dict,
    depth_tier: str,
    floor:     int,
) -> dict[str, Any]:
    n = bucket.get("n", 0)
    weak = n < _WEAK_BELOW or depth_tier != "family+regime"
    warning: Optional[str] = None
    if depth_tier == "global":
        warning = (
            f"Global calibration only — no same-family or same-regime "
            f"archive depth (n={n})."
        )
    elif depth_tier == "regime":
        warning = (
            f"Regime-only calibration — family bucket below the "
            f"{_N_FAMILY}-event floor (n={n})."
        )
    elif depth_tier == "family":
        warning = (
            f"Family-only calibration — joint family+regime bucket below "
            f"the {_N_STRICT}-event floor (n={n})."
        )
    elif n < _WEAK_BELOW:
        warning = f"Thin sample — only {n} matching events in the archive."

    return {
        "hit_rate":       bucket.get("hit_rate"),
        "n":              n,
        "depth_tier":     depth_tier,
        "weak":           weak,
        "sample_warning": warning,
        "slice_key":      slice_key,
        "floor":          floor,
    }


def _insufficient(reason: str) -> dict[str, Any]:
    return {
        "hit_rate":       None,
        "n":              0,
        "depth_tier":     "insufficient",
        "weak":           True,
        "sample_warning": reason,
        "slice_key":      None,
        "floor":          _N_GLOBAL,
    }


def lookup_calibration(
    tree: Optional[dict],
    *,
    confidence: str,
    family:     Optional[str] = None,
    compound_regime: Optional[str] = None,
) -> dict[str, Any]:
    """Cascade through slice tables to find the finest trustworthy bucket.

    Inputs are soft: ``family`` / ``compound_regime`` may be None or
    "none" — the cascade skips those slices and tries the next level.
    ``confidence`` must be one of ``low`` / ``medium`` / ``high``;
    anything else short-circuits to the ``insufficient`` verdict.

    The returned ``depth_tier`` string is the canonical way for consumers
    to decide what UI label to render alongside the hit rate.
    """
    if confidence not in _VALID_CONFIDENCE:
        return _insufficient(
            f"Confidence {confidence!r} is not one of low/medium/high."
        )
    if not isinstance(tree, dict):
        return _insufficient("No calibration tree available yet — archive empty.")

    family_key = family if family and family != "none" else None
    regime_key = compound_regime if compound_regime and compound_regime != "none" else None

    joint = tree.get("joint", {})
    fam   = tree.get("family", {})
    reg   = tree.get("regime", {})
    glb   = tree.get("global", {})

    # 1) Strictest: family + regime.
    if family_key and regime_key:
        slice_key = (confidence, family_key, regime_key)
        b = joint.get(slice_key)
        if b and b["n"] >= _N_STRICT:
            return _resolved_result(slice_key, b, "family+regime", _N_STRICT)

    # 2) Family-only fallback.
    if family_key:
        slice_key = (confidence, family_key)
        b = fam.get(slice_key)
        if b and b["n"] >= _N_FAMILY:
            return _resolved_result(slice_key, b, "family", _N_FAMILY)

    # 3) Regime-only fallback.
    if regime_key:
        slice_key = (confidence, regime_key)
        b = reg.get(slice_key)
        if b and b["n"] >= _N_REGIME:
            return _resolved_result(slice_key, b, "regime", _N_REGIME)

    # 4) Global fallback.
    b = glb.get(confidence)
    if b and b["n"] >= _N_GLOBAL:
        return _resolved_result((confidence,), b, "global", _N_GLOBAL)

    # Nothing cleared even the global floor.
    n_avail = (b or {}).get("n", 0)
    return _insufficient(
        f"Archive too thin for `{confidence}` calibration "
        f"(n={n_avail}, need >= {_N_GLOBAL})."
    )

"""
regime_vector.py

Compact macro-regime vector + analog re-ranker.

What this adds
--------------
Historical analog matching used to score on headline / mechanism Jaccard
similarity alone.  That makes "OPEC cut + tariff" headlines look related
to "OPEC cut + ceasefire" headlines even when the underlying macro
backdrop is opposite (inflation pressure vs growth scare).

This module:

  1. Builds a compact, deterministic regime vector from the existing
     macro stack (rates_context + stress_regime + snapshots).
  2. Provides a re-ranker that combines the existing topic similarity
     with regime-axis match into a single score.

Vector shape
------------
    {
      "inflation":       "hot" | "cool" | "neutral",
      "policy_stance":   "hawkish" | "dovish" | "neutral",
      "fx":              "dollar_strong" | "dollar_weak" | "neutral",
      "growth_stress":   "calm" | "watch" | "stressed" | "neutral",
      # Axes added in the breadth expansion — derived from the richer
      # finance-engine work (credit_regime.py, breakeven_curve.py).  When
      # their inputs aren't available the axes degrade to "neutral", which
      # the re-ranker treats as a soft signal rather than a mismatch.
      "credit":          "risk_on" | "risk_off" | "duration_stress" | "neutral",
      "curve_shape":     "front_loaded" | "term_premium" | "parallel" | "neutral",
      "inflation_path":  "hawkish_constraint" | "dovish_space" | "neutral",
      "available":       bool,
      "stale":           bool,
    }

Design notes
------------
- Pure composer; no I/O.  Caller passes pre-fetched macro inputs.
- TIP sign convention preserved: ``real_5d < 0`` means TIP fell which
  means real yields ROSE which is hawkish.
- ``rerank_analogs`` is a layer ON TOP of the existing keyword analog
  search — it does not replace it.  When the current regime vector is
  unavailable, the function returns the input list unchanged so the
  topic-only ordering survives stale macro context.
- Historical analogs that lack a stored regime snapshot fall back to a
  neutral 0.5 baseline so old rows are not unfairly penalised.
- ``credit``, ``curve_shape``, and ``inflation_path`` are additive — an
  older row persisted before they were introduced will carry
  ``"neutral"`` on each (via the graceful-degradation path) and so match
  at the per-axis ``None-vs-neutral`` threshold instead of being
  penalised outright.
- Weights below were validated empirically — see
  ``validate_regime_rerank.py``.  They are tunable but the validation
  script must continue to pass when they change.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Axis labels + tunable weights
# ---------------------------------------------------------------------------

REGIME_AXES: tuple[str, ...] = (
    "inflation", "policy_stance", "fx", "growth_stress",
    # Breadth expansion: each axis fed by an existing composer output
    # (credit_regime.classify_credit_regime + rates_context.breakeven_curve)
    # so no additional provider call is needed in the caller.
    "credit", "curve_shape", "inflation_path",
)

# Final weights — picked by validate_regime_rerank.py.  Topic stays the
# dominant signal because the analog system is fundamentally a similarity
# search; the regime layer adds context, not replacement.  These are the
# median of the weight corridor where all three required properties hold;
# update via the validator script when the rerank logic changes.
TOPIC_WEIGHT: float = 0.60
REGIME_WEIGHT: float = 0.40

# Historical rows missing a regime snapshot get this neutral baseline.
# Sits between full match (1.0) and full miss (0.0) so old rows aren't
# locked out, but new rows with strong regime alignment can still beat
# them.
NEUTRAL_REGIME_MATCH: float = 0.5


# Pairs that count as "opposite" on each axis when generating the
# match-reason text.  Mismatches that aren't true opposites just read
# as "different".
_AXIS_OPPOSITES: dict[str, frozenset[str]] = {
    "inflation":      frozenset({"hot", "cool"}),
    "policy_stance":  frozenset({"hawkish", "dovish"}),
    "fx":             frozenset({"dollar_strong", "dollar_weak"}),
    "growth_stress":  frozenset({"calm", "stressed"}),
    "credit":         frozenset({"risk_on", "risk_off"}),
    "curve_shape":    frozenset({"front_loaded", "term_premium"}),
    "inflation_path": frozenset({"hawkish_constraint", "dovish_space"}),
}

# Display labels for the match-reason string.
_AXIS_DISPLAY: dict[str, str] = {
    "inflation":      "inflation",
    "policy_stance":  "policy stance",
    "fx":             "dollar",
    "growth_stress":  "growth/stress",
    "credit":         "credit",
    "curve_shape":    "curve shape",
    "inflation_path": "inflation path",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _rates_usable(rates_context: Optional[dict]) -> bool:
    if not rates_context or not isinstance(rates_context, dict):
        return False
    nom = _f((rates_context.get("nominal") or {}).get("change_5d"))
    real = _f((rates_context.get("real_proxy") or {}).get("change_5d"))
    return nom is not None or real is not None


def _stress_usable(stress_regime: Optional[dict]) -> bool:
    if not stress_regime or not isinstance(stress_regime, dict):
        return False
    return bool(stress_regime.get("raw") or stress_regime.get("signals"))


def _snap_change_5d(snapshots: Optional[list[dict]], market: str) -> Optional[float]:
    if not snapshots:
        return None
    target = market.upper()
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        if (s.get("market") or "").upper() != target:
            continue
        if s.get("value") is None or s.get("error"):
            return None
        return _f(s.get("change_5d"))
    return None


def _stress_dollar_5d(stress_regime: Optional[dict]) -> Optional[float]:
    """Fallback DXY 5d move from stress_regime.detail.safe_haven.assets.Dollar."""
    detail = ((stress_regime or {}).get("detail") or {}).get("safe_haven") or {}
    assets = detail.get("assets") or {}
    return _f(assets.get("Dollar"))


# ---------------------------------------------------------------------------
# Per-axis classifiers
# ---------------------------------------------------------------------------

def _inflation_axis(rates_context: Optional[dict]) -> str:
    rc = rates_context or {}
    regime = rc.get("regime")
    be_5d = _f((rc.get("breakeven_proxy") or {}).get("change_5d"))

    if regime == "Inflation pressure":
        return "hot"
    if be_5d is not None and be_5d > 0.15:
        return "hot"
    if be_5d is not None and be_5d < -0.15:
        return "cool"
    if regime == "Real-rate tightening":
        return "cool"
    return "neutral"


def _policy_stance_axis(rates_context: Optional[dict]) -> str:
    """Bidirectional score from real yield + nominal + regime label.

    TIP sign convention: real_5d < 0 means real yields rose (hawkish).
    """
    rc = rates_context or {}
    nom = _f((rc.get("nominal") or {}).get("change_5d"))
    real = _f((rc.get("real_proxy") or {}).get("change_5d"))
    regime = rc.get("regime")

    hawk = 0
    dove = 0

    if real is not None:
        if real < -0.3:
            hawk += 2
        elif real > 0.3:
            dove += 2

    if nom is not None:
        if nom > 0.25:
            hawk += 1
        elif nom < -0.25:
            dove += 1

    if regime == "Real-rate tightening":
        hawk += 1
    elif regime == "Inflation pressure":
        hawk += 1
    elif regime == "Risk-off / growth scare":
        dove += 2

    if hawk > dove + 1:
        return "hawkish"
    if dove > hawk + 1:
        return "dovish"
    return "neutral"


def _fx_axis(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> str:
    """Dollar regime from snapshot DXY or safe_haven dollar fallback."""
    dxy = _snap_change_5d(snapshots, "DXY")
    if dxy is None:
        dxy = _stress_dollar_5d(stress_regime)
    if dxy is None:
        return "neutral"
    if dxy > 1.0:
        return "dollar_strong"
    if dxy < -1.0:
        return "dollar_weak"
    return "neutral"


def _growth_stress_axis(stress_regime: Optional[dict]) -> str:
    if not stress_regime or not isinstance(stress_regime, dict):
        return "neutral"
    regime = (stress_regime.get("regime") or "").strip()
    signals = stress_regime.get("signals") or {}
    fired = sum(1 for v in signals.values() if v)
    lower = regime.lower()

    if "stress" in lower or "risk-off" in lower or "growth scare" in lower:
        return "stressed"
    if "watch" in lower or fired >= 2:
        return "watch"
    if "calm" in lower:
        return "calm"
    return "neutral"


# ---------------------------------------------------------------------------
# Breadth-expansion axes — derived from existing composer outputs.
# ---------------------------------------------------------------------------

def _credit_axis(credit_regime: Optional[dict]) -> str:
    """Collapse credit_regime.regime into a binary-leaning analog axis.

    ``credit_regime.classify_credit_regime`` emits nine fine-grained labels;
    the re-ranker only needs the directional lean.  ``duration_stress`` is
    kept as a distinct value because it carries a different transmission
    story from default-risk widening — a rates-led sell-off vs a credit
    event.
    """
    if not credit_regime or not isinstance(credit_regime, dict):
        return "neutral"
    regime = (credit_regime.get("regime") or "").strip().lower()
    if regime in ("risk_on", "default_risk_tightening", "duration_tightening"):
        return "risk_on"
    if regime in ("risk_off", "default_risk_widening"):
        return "risk_off"
    if regime == "duration_widening":
        return "duration_stress"
    return "neutral"


def _curve_shape_axis(rates_context: Optional[dict]) -> str:
    """Read the breakeven-curve shape surfaced by rates_context.

    ``parallel_up`` / ``parallel_down`` / ``twist`` all collapse to
    ``parallel`` — the re-ranker only cares whether the curve is
    expressing a FRONT-LOADED or TERM-PREMIUM lean vs a broad shift.
    """
    if not rates_context or not isinstance(rates_context, dict):
        return "neutral"
    curve = rates_context.get("breakeven_curve") or {}
    if not curve.get("available"):
        return "neutral"
    shape = (curve.get("shape") or "").strip().lower()
    if shape == "front_loaded":
        return "front_loaded"
    if shape == "term_premium_like":
        return "term_premium"
    if shape in ("parallel_up", "parallel_down", "twist"):
        return "parallel"
    return "neutral"


def _inflation_path_axis(rates_context: Optional[dict]) -> str:
    """Read the breakeven-curve policy-space interpretation.

    ``behind_the_curve`` joins ``narrow_hawkish`` as *hawkish_constraint*
    because both say the Fed has less room to ease than headline rates
    suggest.  ``look_through`` joins ``ease_room`` for the opposite
    reason.
    """
    if not rates_context or not isinstance(rates_context, dict):
        return "neutral"
    curve = rates_context.get("breakeven_curve") or {}
    if not curve.get("available"):
        return "neutral"
    space = (curve.get("policy_space") or "").strip().lower()
    if space in ("narrow_hawkish", "behind_the_curve"):
        return "hawkish_constraint"
    if space in ("ease_room", "look_through"):
        return "dovish_space"
    return "neutral"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def build_regime_vector(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]] = None,
    *,
    credit_regime: Optional[dict] = None,
) -> dict:
    """Build the compact regime vector from pre-fetched macro inputs.

    Returns a vector with ``available=False`` and ``stale=True`` when
    neither rates nor stress is usable; the rerank layer treats that as
    "no current regime, fall through to topic-only ranking".

    ``credit_regime`` is the output of
    ``credit_regime.classify_credit_regime(...)``.  Keyword-only so
    existing callers (``build_regime_vector(rates, stress, snapshots)``)
    continue to work; callers that haven't been wired to pass it simply
    get ``credit="neutral"`` on the new axis.

    The curve-shape and inflation-path axes read ``rates_context
    ["breakeven_curve"]`` — already populated by ``compute_rates_context``
    — so no extra composer call is required from the caller.
    """
    rates_ok = _rates_usable(rates_context)
    stress_ok = _stress_usable(stress_regime)

    # Neutral stub used both for the fully-unavailable path and as the
    # default shape a partial build fills in.
    neutral_vec: dict = {
        "inflation":      "neutral",
        "policy_stance":  "neutral",
        "fx":             "neutral",
        "growth_stress":  "neutral",
        "credit":         "neutral",
        "curve_shape":    "neutral",
        "inflation_path": "neutral",
    }

    if not rates_ok and not stress_ok:
        return {
            **neutral_vec,
            "available": False,
            "stale":     True,
        }

    return {
        "inflation":      _inflation_axis(rates_context) if rates_ok else "neutral",
        "policy_stance":  _policy_stance_axis(rates_context) if rates_ok else "neutral",
        "fx":             _fx_axis(rates_context, stress_regime, snapshots),
        "growth_stress":  _growth_stress_axis(stress_regime) if stress_ok else "neutral",
        "credit":         _credit_axis(credit_regime),
        "curve_shape":    _curve_shape_axis(rates_context) if rates_ok else "neutral",
        "inflation_path": _inflation_path_axis(rates_context) if rates_ok else "neutral",
        "available":      True,
        "stale":          not (rates_ok and stress_ok),
    }


# ---------------------------------------------------------------------------
# Distance / explanation helpers
# ---------------------------------------------------------------------------

def regime_distance(
    current: Optional[dict],
    historical: Optional[dict],
) -> Optional[float]:
    """Return a match ratio in [0, 1] across the four regime axes.

    Returns None when either side is missing or marked unavailable, so
    the caller can decide how to fall back.
    """
    if not current or not historical:
        return None
    if not current.get("available") or not historical.get("available"):
        return None

    matches = 0
    for axis in REGIME_AXES:
        if current.get(axis) == historical.get(axis):
            matches += 1
    return matches / len(REGIME_AXES)


def regime_match_reason(
    current: Optional[dict],
    historical: Optional[dict],
) -> str:
    """Compact deterministic explanation, e.g.
    'same inflation, opposite policy stance, same dollar'."""
    if not current or not historical:
        return ""
    if not current.get("available") or not historical.get("available"):
        return ""

    same_parts: list[str] = []
    opposite_parts: list[str] = []

    for axis in REGIME_AXES:
        a = current.get(axis)
        b = historical.get(axis)
        if a == b:
            if a in (None, "neutral"):
                continue
            same_parts.append(f"same {_AXIS_DISPLAY[axis]}")
            continue
        if a in (None, "neutral") or b in (None, "neutral"):
            continue
        if _AXIS_OPPOSITES.get(axis) == frozenset({a, b}):
            opposite_parts.append(f"opposite {_AXIS_DISPLAY[axis]}")

    parts = same_parts + opposite_parts
    return ", ".join(parts[:4])


# ---------------------------------------------------------------------------
# Re-ranker — pure layer over an existing analog list
# ---------------------------------------------------------------------------

def rerank_analogs(
    analogs: list[dict],
    current_vector: Optional[dict],
    *,
    topic_weight: float = TOPIC_WEIGHT,
    regime_weight: float = REGIME_WEIGHT,
) -> list[dict]:
    """Re-rank existing analog candidates with the regime layer.

    Each analog dict must contain ``similarity`` (the existing topic
    Jaccard).  Optional ``regime_snapshot`` is the historical regime
    vector saved with the row.

    Behaviour:
      - When ``current_vector`` is unavailable, return the input list
        unchanged (graceful degradation: topic-only ordering survives).
      - When a candidate has no historical regime snapshot, the regime
        score falls back to ``NEUTRAL_REGIME_MATCH`` so old rows aren't
        unfairly penalised.
      - The function mutates each analog with: ``regime_match`` (the
        raw [0, 1] score or None), ``final_score`` (the combined
        score), and appends a regime explanation to ``match_reason``.
    """
    if not analogs:
        return analogs
    if not current_vector or not current_vector.get("available"):
        return analogs

    rescored: list[dict] = []
    for a in analogs:
        topic_sim = float(a.get("similarity") or 0.0)
        hist = a.get("regime_snapshot") if isinstance(a, dict) else None

        rmatch = regime_distance(current_vector, hist) if hist else None
        effective = NEUTRAL_REGIME_MATCH if rmatch is None else rmatch
        final = topic_weight * topic_sim + regime_weight * effective

        a["regime_match"] = rmatch
        a["final_score"] = round(final, 3)

        # Append a deterministic regime reason to the existing match_reason
        # string so the frontend doesn't need a new field.  Only when there
        # is something to say.
        if hist:
            reason = regime_match_reason(current_vector, hist)
            if reason:
                base = (a.get("match_reason") or "").strip()
                a["match_reason"] = f"{base} · regime: {reason}" if base else f"regime: {reason}"

        rescored.append(a)

    rescored.sort(key=lambda x: -float(x.get("final_score") or 0.0))
    return rescored

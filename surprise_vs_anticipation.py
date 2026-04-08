"""
surprise_vs_anticipation.py

Surprise vs Anticipation Decomposition.

What it adds
------------
Most reactions on the tape are a mixture of:
  - "already in the price" (anticipated confirmation),
  - "new information arriving now" (surprise shock),
  - "vol collapse after a known pending event" (uncertainty resolution),
  - ambiguous / contradictory signal (mixed).

Desks care about which of these is driving the tape because it changes
whether you fade or follow.  Until now we had the raw inputs — stage,
ticker 1d/5d returns, VIX term structure — but nothing that combined
them into a single classification.

This module is a pure composer: api.py fetches the usual stage /
market / stress inputs once per request and passes them in; we emit
a compact structured block that the analysis page renders verbatim.

Output shape
------------
    {
      "regime":                 "surprise_shock" | "anticipated_confirmation"
                                | "uncertainty_resolution" | "mixed",
      "regime_label":           str,
      "rationale":              str,  # one-line institutional read
      "priced_before":          str,  # what markets were carrying into the event
      "changed_on_realization": str,  # what moved on the realisation
      "key_markets":            list[str],
      "available":              bool,
      "stale":                  bool,
      "signals": {
          "intraday_share":     float | None,
          "vix_change_5d":      float | None,
          "stage":              str,
          "ticker_move_count":  int,
      },
    }

Design notes
------------
- Intraday-share decomposition: for each ticker with both r1 and r5 in
  the expected direction, compute |r1| / |r5|.  A high share means the
  move happened today (surprise); a low share means it was pre-moved
  (anticipated).  We average over all usable tickers.
- Stage bias: "anticipation" and "normalization" push toward
  anticipated; "escalation" pushes toward surprise; "de-escalation" /
  "realized" bias toward uncertainty resolution.
- Stress overlay: VIX jumped +1.5 on 5d → surprise bonus; VIX fell
  -1.5 on 5d → uncertainty_resolution bonus; term inversion + vix
  elevated → strong surprise signal.
- Two-point margin rule: top regime must lead the runner-up by ≥ 2
  points, otherwise we classify as "mixed".
- Degrades cleanly: with no usable tickers and no stress signal we
  fall back to the stage alone and mark the block stale.  When even
  stage and inputs are fully empty we return ``{}`` so the caller can
  skip rendering.
"""

from __future__ import annotations

from typing import Optional


REGIME_IDS: tuple[str, ...] = (
    "surprise_shock",
    "anticipated_confirmation",
    "uncertainty_resolution",
    "mixed",
)

_REGIME_LABEL: dict[str, str] = {
    "surprise_shock":           "Surprise Shock",
    "anticipated_confirmation": "Anticipated / Priced-In",
    "uncertainty_resolution":   "Uncertainty Resolution",
    "mixed":                    "Mixed / Unclear",
}

_KEY_MARKETS: dict[str, list[str]] = {
    "surprise_shock":           ["ES", "VIX", "DXY", "GC"],
    "anticipated_confirmation": ["2Y", "ES", "TIP", "DXY"],
    "uncertainty_resolution":   ["VIX", "ES", "HYG", "TLT"],
    "mixed":                    ["VIX", "2Y", "ES", "DXY"],
}

# Stage → regime bias (points).  Keeps the language aligned with the
# upstream classify_stage labels so the mapping is explicit.
_STAGE_BIAS: dict[str, dict[str, int]] = {
    "anticipation":  {"anticipated_confirmation": 2},
    "normalization": {"anticipated_confirmation": 1, "uncertainty_resolution": 1},
    "escalation":    {"surprise_shock": 2},
    "de-escalation": {"uncertainty_resolution": 2},
    "realized":      {"surprise_shock": 1, "uncertainty_resolution": 1},
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


def _intraday_share(r1: Optional[float], r5: Optional[float]) -> Optional[float]:
    """Fraction of the 5d move concentrated in today's bar.

    Returns None when either return is missing, when the 5d move is
    negligible, or when the two values point in opposite directions
    (which means the ticker reversed intraday — not informative for a
    surprise/anticipation decomposition).
    """
    if r1 is None or r5 is None:
        return None
    if abs(r5) < 0.3:
        return None
    if (r5 > 0 and r1 < 0) or (r5 < 0 and r1 > 0):
        return None
    return min(abs(r1) / abs(r5), 1.5)


def _tickers_usable(tickers: Optional[list[dict]]) -> list[dict]:
    if not tickers or not isinstance(tickers, list):
        return []
    out: list[dict] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        if _f(t.get("return_1d")) is None and _f(t.get("return_5d")) is None:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

def _score_regime(
    stage: str,
    tickers: list[dict],
    stress_regime: Optional[dict],
) -> tuple[dict[str, int], dict]:
    """Accumulate regime points from each signal family.

    Returns (points, debug_signals).
    """
    pts: dict[str, int] = {rid: 0 for rid in REGIME_IDS if rid != "mixed"}
    debug: dict = {
        "intraday_share": None,
        "vix_change_5d": None,
        "stage": stage or "",
        "ticker_move_count": 0,
    }

    # --- Intraday-share concentration across tickers ---------------------
    shares: list[float] = []
    for t in tickers:
        r1 = _f(t.get("return_1d"))
        r5 = _f(t.get("return_5d"))
        share = _intraday_share(r1, r5)
        if share is not None:
            shares.append(share)

    debug["ticker_move_count"] = len(shares)

    if shares:
        avg_share = sum(shares) / len(shares)
        debug["intraday_share"] = round(avg_share, 3)
        if avg_share >= 0.60:
            # Move mostly happened today → surprise.
            pts["surprise_shock"] += 3
        elif avg_share <= 0.25:
            # Move was in before today → anticipated.
            pts["anticipated_confirmation"] += 3
        elif avg_share <= 0.40:
            pts["anticipated_confirmation"] += 1
        elif avg_share >= 0.45:
            pts["surprise_shock"] += 1

    # --- Stage bias ------------------------------------------------------
    for regime, boost in _STAGE_BIAS.get(stage or "", {}).items():
        pts[regime] = pts.get(regime, 0) + boost

    # --- Stress-regime overlay ------------------------------------------
    sr = stress_regime or {}
    signals = sr.get("signals") or {}
    raw = sr.get("raw") or {}
    vix_change_5d = _f(raw.get("vix_change_5d"))
    debug["vix_change_5d"] = vix_change_5d

    if vix_change_5d is not None:
        if vix_change_5d >= 1.5:
            pts["surprise_shock"] += 2
        elif vix_change_5d <= -1.5:
            pts["uncertainty_resolution"] += 2
        elif vix_change_5d <= -0.75:
            pts["uncertainty_resolution"] += 1
        elif vix_change_5d >= 0.75:
            pts["surprise_shock"] += 1

    if signals.get("vix_elevated") and signals.get("term_inversion"):
        # Short-end vol above long-end vol + absolute elevation is the
        # classic shock fingerprint.
        pts["surprise_shock"] += 2

    if signals.get("safe_haven_bid") and not signals.get("vix_elevated"):
        # Bid into safety without a vol spike looks like a pre-positioned
        # hedge rather than a shock response.
        pts["anticipated_confirmation"] += 1

    regime_label = (sr.get("regime") or "").strip().lower()
    if regime_label == "calm" and vix_change_5d is not None and abs(vix_change_5d) < 0.5:
        # No drama anywhere → whatever moved was already expected.
        pts["anticipated_confirmation"] += 1

    return pts, debug


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def _decide_regime(pts: dict[str, int]) -> tuple[str, int]:
    """Pick the winning regime with a 2-point margin rule.

    Returns (regime_id, top_points).
    """
    if not pts or all(v == 0 for v in pts.values()):
        return "mixed", 0
    ranked = sorted(pts.items(), key=lambda kv: kv[1], reverse=True)
    top_id, top_pts = ranked[0]
    runner_pts = ranked[1][1] if len(ranked) > 1 else 0
    if top_pts - runner_pts < 2:
        return "mixed", top_pts
    return top_id, top_pts


# ---------------------------------------------------------------------------
# Narrative builders
# ---------------------------------------------------------------------------

def _rationale(regime: str, debug: dict) -> str:
    share = debug.get("intraday_share")
    vix_5d = debug.get("vix_change_5d")
    stage = debug.get("stage") or ""

    share_txt = f"intraday share {share:.0%}" if share is not None else "no directional ticker move"
    vix_txt = f"VIX 5d {vix_5d:+.2f}" if vix_5d is not None else "VIX change unavailable"

    if regime == "surprise_shock":
        return (
            f"Move concentrated in today's tape ({share_txt}); {vix_txt}; "
            f"stage {stage or 'unclassified'} — reaction looks like new information."
        )
    if regime == "anticipated_confirmation":
        return (
            f"Move already in the price before today ({share_txt}); "
            f"{vix_txt}; stage {stage or 'unclassified'} — market was positioned "
            f"for this."
        )
    if regime == "uncertainty_resolution":
        return (
            f"Volatility compression on the realisation ({vix_txt}); "
            f"stage {stage or 'unclassified'} — event removed overhang rather "
            f"than introducing new information."
        )
    return (
        f"Signals conflict ({share_txt}, {vix_txt}, stage {stage or 'unclassified'}) "
        f"— classification deferred."
    )


def _priced_before(regime: str, debug: dict) -> str:
    stage = debug.get("stage") or ""
    if regime == "surprise_shock":
        if stage in ("anticipation", "normalization"):
            return "Some optionality priced, but not the full tail outcome."
        return "Little to no directional risk priced in before today."
    if regime == "anticipated_confirmation":
        return "Most of the directional move had already been absorbed by positioning."
    if regime == "uncertainty_resolution":
        return "Elevated hedging demand and wide distribution of outcomes."
    return "Mixed positioning — no single consensus on what was priced."


def _changed_on_realization(regime: str, debug: dict) -> str:
    share = debug.get("intraday_share")
    if regime == "surprise_shock":
        if share is not None:
            return f"Directional repricing today ({share:.0%} of the 5d move landed in the realisation bar)."
        return "Directional repricing on the realisation bar."
    if regime == "anticipated_confirmation":
        return "Follow-through is modest; risk premia compressed rather than expanded."
    if regime == "uncertainty_resolution":
        return "Implied vol collapsed; directional move is secondary to the vol unwind."
    return "Signal mixed — direction and vol moved in uncoordinated ways."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_surprise_vs_anticipation(
    stage: str,
    tickers: Optional[list[dict]] = None,
    stress_regime: Optional[dict] = None,
) -> dict:
    """Classify an event as surprise / anticipated / uncertainty / mixed.

    Pure composer — performs no I/O.  The caller must pass the already
    computed ``stage`` label, the ``tickers`` list from market_check
    (each with return_1d / return_5d / role), and the stress regime
    dict from compute_stress_regime.

    Returns ``{}`` when there is genuinely nothing to classify — no
    stage, no tickers, no stress regime.  Otherwise returns the block
    with ``stale=True`` when any of the three input families is
    missing, so the UI can render a degraded pill instead of a hard
    "unavailable" card.
    """
    usable_tickers = _tickers_usable(tickers)
    has_stage = bool(stage)
    has_stress = bool(
        (stress_regime or {}).get("raw") or (stress_regime or {}).get("signals"),
    )
    has_ticks = bool(usable_tickers)

    if not has_stage and not has_stress and not has_ticks:
        return {}

    pts, debug = _score_regime(stage or "", usable_tickers, stress_regime)
    regime, _top = _decide_regime(pts)

    stale = not (has_stage and has_stress and has_ticks)

    return {
        "regime":                 regime,
        "regime_label":           _REGIME_LABEL[regime],
        "rationale":              _rationale(regime, debug),
        "priced_before":          _priced_before(regime, debug),
        "changed_on_realization": _changed_on_realization(regime, debug),
        "key_markets":            list(_KEY_MARKETS[regime]),
        "available":              True,
        "stale":                  stale,
        "signals":                debug,
    }

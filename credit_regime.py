"""
credit_regime.py

Credit regime classifier.

Takes the three liquid credit-market 5d moves (HYG for high-yield, LQD for
investment-grade, SHY for short Treasury) and classifies the credit state
into a regime richer than the single pp-spread number that
shock_decomposition surfaces.  Specifically, it separates:

  - **default-risk widening** (HY underperforms IG, spread opens)
  - **duration widening** (both HY and IG fall together as rates rise)
  - **risk-on**              (HY outperforms, spreads tighten)
  - **decoupled**            (HY and IG move in opposite directions by
                              more than noise, no single clean read)

This matters because an event that widens credit spreads via default-risk
has different transmission implications (banks, leveraged issuers, EM
funding) than an event that widens them via higher rates (term-premium
reset, duration selling).  The shock-decomposition credit channel
collapses these into one number; this module keeps them apart.

Design
------
- Pure composer; no I/O.  Consumes HYG/LQD/SHY 5d % changes.
- All inputs optional.  Missing inputs degrade gracefully — the classifier
  returns the richest regime it can justify with the data in hand, or
  ``available=False`` when too few inputs are present.

Output shape
------------
    {
      regime:                  str,    # one of the REGIME_LABELS keys
      regime_label:            str,    # human-readable label
      rationale:               str,    # one-line explanation
      hy_5d:                   float | None,   # HYG ETF 5d % move
      ig_5d:                   float | None,   # LQD ETF 5d % move
      shy_5d:                  float | None,   # SHY ETF 5d % move
      hy_ig_differential_5d:   float | None,   # HY − IG (negative = HY underperforms)
      default_risk_signal:     str,    # "widening" | "tightening" | "quiet" | "unavailable"
      duration_signal:         str,    # "rising_rates" | "falling_rates" | "quiet" | "unavailable"
      available:               bool,
      stale:                   bool,
    }
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Thresholds — judgment-set against the 5y |HYG/LQD/SHY 5d| %-move
# distribution.  The ≈p75 figures (|HYG 5d| ≈ 0.9%, |LQD 5d| ≈ 0.8%) are
# APPROXIMATE orientation, not a pinned calibration target — this module is
# not named in calibrate_thresholds_pass2.py's targets.  A 0.5% absolute move
# is clearly above noise without being a tail event.
# ---------------------------------------------------------------------------
_MOVE_FLOOR: float = 0.5           # % — individual HY / IG move to count
_DIFFERENTIAL_FLOOR: float = 0.3   # % — HY − IG gap to call it default-driven
_DECOUPLE_FLOOR: float = 0.6       # % — HY vs IG opposite signs by this much


REGIME_LABELS: dict[str, str] = {
    "default_risk_widening":  "Default-risk widening (HY underperforms IG)",
    "default_risk_tightening": "Default-risk tightening (HY outperforms IG)",
    "duration_widening":      "Rates-driven bond weakness (HY + IG both fall)",
    "duration_tightening":    "Rates-driven bond strength (HY + IG both rally)",
    "risk_on":                "Risk-on (HY rally leads)",
    "risk_off":               "Risk-off (HY selloff leads)",
    "decoupled":              "Decoupled (HY and IG diverge directionally)",
    "quiet":                  "Quiet (no meaningful credit move)",
    "unavailable":            "Credit inputs unavailable",
}


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    # Guard against NaN/inf at the composer boundary.
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _sign(v: Optional[float], floor: float) -> str:
    if v is None:
        return "quiet"
    if abs(v) < floor:
        return "quiet"
    return "up" if v > 0 else "down"


def _classify(
    hy_5d: Optional[float],
    ig_5d: Optional[float],
) -> tuple[str, str]:
    """Core regime classifier over HY and IG 5d %.

    Returns ``(regime, rationale)``.
    """
    if hy_5d is None and ig_5d is None:
        return "unavailable", "HY and IG inputs both missing."

    # If only one leg is available, we can still say something.
    if hy_5d is None:
        if abs(ig_5d) < _MOVE_FLOOR:
            return "quiet", f"IG 5d {ig_5d:+.2f}% near flat; HY leg unavailable."
        direction = "tightening" if ig_5d > 0 else "widening"
        return ("duration_" + direction,
                f"IG 5d {ig_5d:+.2f}%; HY leg unavailable — duration read only.")
    if ig_5d is None:
        if abs(hy_5d) < _MOVE_FLOOR:
            return "quiet", f"HY 5d {hy_5d:+.2f}% near flat; IG leg unavailable."
        direction = "risk_on" if hy_5d > 0 else "risk_off"
        return (direction,
                f"HY 5d {hy_5d:+.2f}%; IG leg unavailable — risk-on/off read only.")

    hy_sign = _sign(hy_5d, _MOVE_FLOOR)
    ig_sign = _sign(ig_5d, _MOVE_FLOOR)
    diff = hy_5d - ig_5d  # > 0 means HY outperforming IG

    # Decoupling: HY and IG in clearly opposite directions.
    if (hy_sign == "up" and ig_sign == "down" and abs(diff) >= _DECOUPLE_FLOOR) or \
       (hy_sign == "down" and ig_sign == "up" and abs(diff) >= _DECOUPLE_FLOOR):
        return (
            "decoupled",
            f"HY {hy_5d:+.2f}% and IG {ig_5d:+.2f}% moved in opposite directions "
            f"(Δ={diff:+.2f}%).",
        )

    # Both quiet → quiet.
    if hy_sign == "quiet" and ig_sign == "quiet":
        return (
            "quiet",
            f"HY 5d {hy_5d:+.2f}% and IG 5d {ig_5d:+.2f}% both below the "
            f"{_MOVE_FLOOR:.1f}% noise floor.",
        )

    # Both down (or one quiet, other down) with a meaningful HY−IG gap → default-risk widening.
    both_lower = (hy_sign == "down" or ig_sign == "down") and (
        hy_sign != "up" and ig_sign != "up"
    )
    both_higher = (hy_sign == "up" or ig_sign == "up") and (
        hy_sign != "down" and ig_sign != "down"
    )

    if both_lower and diff <= -_DIFFERENTIAL_FLOOR:
        return (
            "default_risk_widening",
            f"HY 5d {hy_5d:+.2f}% underperforms IG 5d {ig_5d:+.2f}% "
            f"(Δ={diff:+.2f}% ≤ −{_DIFFERENTIAL_FLOOR:.1f}%).",
        )
    if both_higher and diff >= _DIFFERENTIAL_FLOOR:
        return (
            "default_risk_tightening",
            f"HY 5d {hy_5d:+.2f}% outperforms IG 5d {ig_5d:+.2f}% "
            f"(Δ={diff:+.2f}% ≥ +{_DIFFERENTIAL_FLOOR:.1f}%).",
        )

    # Both-same-direction without a meaningful HY−IG gap → duration story.
    if both_lower:
        return (
            "duration_widening",
            f"HY 5d {hy_5d:+.2f}% and IG 5d {ig_5d:+.2f}% both lower with "
            f"small spread move (Δ={diff:+.2f}%) — rate-driven widening.",
        )
    if both_higher:
        return (
            "duration_tightening",
            f"HY 5d {hy_5d:+.2f}% and IG 5d {ig_5d:+.2f}% both higher with "
            f"small spread move (Δ={diff:+.2f}%) — rate-driven tightening.",
        )

    # Fallback: one meaningful move, other quiet but same-ish direction as diff.
    if hy_sign != "quiet" and ig_sign == "quiet":
        return (
            "risk_on" if hy_5d > 0 else "risk_off",
            f"HY 5d {hy_5d:+.2f}% leads, IG near flat ({ig_5d:+.2f}%).",
        )
    if ig_sign != "quiet" and hy_sign == "quiet":
        return (
            "duration_tightening" if ig_5d > 0 else "duration_widening",
            f"IG 5d {ig_5d:+.2f}% leads, HY near flat ({hy_5d:+.2f}%).",
        )

    # Defensive fall-through.
    return "quiet", "Credit move inconclusive."


def classify_credit_regime(
    hy_5d: Optional[float] = None,
    ig_5d: Optional[float] = None,
    shy_5d: Optional[float] = None,
) -> dict:
    """Classify the credit regime from HY (HYG), IG (LQD), and SHY 5d moves.

    All inputs are percent changes (e.g. 0.5 = +0.5%).  Any of them may be
    None; the output ``available`` flag reports whether at least one leg
    was usable.
    """
    hy = _safe_float(hy_5d)
    ig = _safe_float(ig_5d)
    shy = _safe_float(shy_5d)

    regime, rationale = _classify(hy, ig)

    # Differential: HY − IG, so negative values mean HY is lagging IG.
    diff_5d: Optional[float] = None
    if hy is not None and ig is not None:
        diff_5d = round(hy - ig, 3)

    default_risk_signal = "unavailable"
    if regime in ("default_risk_widening", "risk_off"):
        default_risk_signal = "widening"
    elif regime in ("default_risk_tightening", "risk_on"):
        default_risk_signal = "tightening"
    elif regime in ("duration_widening", "duration_tightening", "quiet"):
        default_risk_signal = "quiet"
    elif regime == "decoupled":
        default_risk_signal = "quiet"

    duration_signal = "unavailable"
    if ig is not None:
        if abs(ig) < _MOVE_FLOOR:
            duration_signal = "quiet"
        else:
            duration_signal = "rising_rates" if ig < 0 else "falling_rates"

    available = hy is not None or ig is not None
    stale = not available or (hy is None or ig is None)

    return {
        "regime":                regime,
        "regime_label":          REGIME_LABELS[regime],
        "rationale":             rationale,
        "hy_5d":                 round(hy, 3) if hy is not None else None,
        "ig_5d":                 round(ig, 3) if ig is not None else None,
        "shy_5d":                round(shy, 3) if shy is not None else None,
        "hy_ig_differential_5d": diff_5d,
        "default_risk_signal":   default_risk_signal,
        "duration_signal":       duration_signal,
        "available":             available,
        "stale":                 stale,
    }

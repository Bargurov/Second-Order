"""
credit_transmission.py

Credit / funding-stress transmission composer.

What this adds on top of ``credit_regime``
------------------------------------------
``credit_regime`` classifies HY/IG/SHY 5d moves into regimes
(default_risk_widening, duration_widening, risk_on/off, decoupled, quiet).
This module asks the next question: *given that classification plus the
equity / volatility / real-rate tape, what does it mean for funding and
refinancing pressure?*

It answers three questions that matter for a macro/credit desk:

1. **Funding stress** — is this a refinancing squeeze, elevated-but-
   manageable, contained, or outright insulated?
2. **Equity vs credit separation** — are equities selling off without the
   credit market confirming (hedging demand, not default stress) or is
   credit actually deteriorating?  These have very different transmission
   implications: equity-only risk-off is largely positioning, while real
   credit deterioration bleeds through to banks, leveraged issuers, and
   EM sovereign spreads.
3. **Which sectors are most exposed** — banks and REITs on rate-led
   widening; leveraged growth and HY issuers on default-led widening;
   EM debt / USD-funded borrowers on credit + strong-dollar combos.

Design
------
Pure composer; no I/O.  Takes three already-computed inputs:
  * ``credit_regime``  — output of ``credit_regime.classify_credit_regime``
  * ``stress_regime``  — output of ``market_check.compute_stress_regime``
  * ``rates_context``  — output of ``market_check.compute_rates_context``

Always returns a dict with a stable shape.  ``available=False`` when the
credit_regime input itself is unavailable; partial inputs on the equity /
rates side degrade to ``stale=True`` without collapsing the block.

Output shape
------------
    {
      "funding_stress":            "acute" | "elevated" | "contained" | "insulated" | "unavailable",
      "funding_stress_label":      str,
      "equity_vs_credit":          "equity_only_riskoff"
                                   | "credit_only_deterioration"
                                   | "synchronized_stress"
                                   | "synchronized_calm"
                                   | "mixed"
                                   | "unavailable",
      "equity_vs_credit_label":    str,
      "sector_exposures":          list[str],   # canonical sector ids most at risk
      "drivers":                   list[str],   # which inputs fired
      "rationale":                 str,
      "signals": {
          "default_risk_signal":   "widening" | "tightening" | "quiet" | "unavailable",
          "duration_signal":       "rising_rates" | "falling_rates" | "quiet" | "unavailable",
          "hy_ig_differential_5d": float | None,
          "vix_elevated":          bool,
          "safe_haven_bid":        bool,
          "real_yield_rising":     bool,
      },
      "available":                 bool,
      "stale":                     bool,
    }
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Labels — keep all user-facing strings in one place
# ---------------------------------------------------------------------------

_FUNDING_STRESS_LABELS: dict[str, str] = {
    "acute":        "Acute funding stress",
    "elevated":     "Elevated refinancing pressure",
    "contained":    "Contained credit move",
    "insulated":    "Insulated — credit quiet or tightening",
    "unavailable":  "Credit inputs unavailable",
}

_EQUITY_VS_CREDIT_LABELS: dict[str, str] = {
    "equity_only_riskoff":       "Equity-only risk-off — credit not confirming",
    "credit_only_deterioration": "Credit deterioration without equity stress",
    "synchronized_stress":       "Synchronized stress — equity + credit deteriorating",
    "synchronized_calm":         "Synchronized calm",
    "mixed":                     "Mixed equity / credit signal",
    "unavailable":               "Equity / credit cross-check unavailable",
}


# ---------------------------------------------------------------------------
# Sector exposure maps — deliberately small, documented, no keyword scraping
# ---------------------------------------------------------------------------
# Each sector id maps to a canonical label the frontend can render and a
# backend consumer can pattern-match.  Keep this tight; adding a sector
# implies adding a real economic rationale, not a keyword guess.

_RATE_LED_SECTORS: tuple[str, ...] = (
    "banks",
    "reits",
    "utilities",
    "long_duration_growth",
)
_DEFAULT_LED_SECTORS: tuple[str, ...] = (
    "hy_issuers",
    "leveraged_growth",
    "em_debt",
    "private_credit",
    "small_caps",
)
_DOLLAR_CROSS_SECTORS: tuple[str, ...] = (
    "em_debt",
    "em_equity",
    "non_us_banks",
)


# ---------------------------------------------------------------------------
# Funding-stress classifier
# ---------------------------------------------------------------------------
# Decision lattice:
#
#   default_risk_widening + VIX elevated         → acute
#   default_risk_widening alone                  → elevated (real stress, no hedge bid)
#   duration_widening + real yields rising       → elevated (rate-led financial tightening)
#   duration_widening alone                      → contained
#   risk_off (HY-led sell, IG leg unavailable)   → elevated
#   decoupled                                    → contained
#   default_risk_tightening / risk_on / quiet    → insulated
#   unavailable                                  → unavailable


def _classify_funding_stress(
    credit_regime: dict,
    vix_elevated: bool,
    real_yield_rising: bool,
) -> str:
    regime = (credit_regime or {}).get("regime") or "unavailable"
    if regime in ("unavailable",):
        return "unavailable"
    if regime == "default_risk_widening":
        return "acute" if vix_elevated else "elevated"
    if regime == "risk_off":
        return "elevated"
    if regime == "duration_widening":
        return "elevated" if real_yield_rising else "contained"
    if regime == "decoupled":
        return "contained"
    # default_risk_tightening, duration_tightening, risk_on, quiet
    return "insulated"


# ---------------------------------------------------------------------------
# Equity vs credit separator — the whole point of this module
# ---------------------------------------------------------------------------


def _classify_equity_vs_credit(
    credit_regime: dict,
    vix_elevated: bool,
    safe_haven_bid: bool,
) -> str:
    """Tell apart positioning-driven equity risk-off from real credit stress.

    The two are frequently confused.  VIX + safe-haven bid without credit
    confirmation is a hedging event — leveraged positioning unwinds, not
    an actual deterioration in balance-sheet quality.  Credit widening
    without VIX is more insidious — spreads are pricing real default risk
    while equity complacency persists.  Synchronized moves carry the most
    weight.
    """
    regime = (credit_regime or {}).get("regime") or "unavailable"
    if regime == "unavailable":
        return "unavailable"

    credit_stressing = regime in (
        "default_risk_widening", "duration_widening", "risk_off",
    )
    equity_stressing = vix_elevated or safe_haven_bid

    if credit_stressing and equity_stressing:
        return "synchronized_stress"
    if credit_stressing and not equity_stressing:
        return "credit_only_deterioration"
    if equity_stressing and not credit_stressing:
        return "equity_only_riskoff"
    # Neither side stressing — tightening / risk_on / quiet with calm vol.
    if regime in ("default_risk_tightening", "risk_on",
                  "duration_tightening", "quiet"):
        return "synchronized_calm"
    return "mixed"


# ---------------------------------------------------------------------------
# Sector exposure resolver
# ---------------------------------------------------------------------------


def _resolve_sector_exposures(
    credit_regime: dict,
    real_yield_rising: bool,
) -> list[str]:
    """Return the canonical sector ids most exposed to the current credit tape.

    Not a definitive list — just the groups a credit desk would watch
    first given the classifier's output.  Returns an empty list when the
    credit regime is insulated or unavailable.
    """
    regime = (credit_regime or {}).get("regime") or "unavailable"

    exposures: list[str] = []
    if regime == "default_risk_widening":
        exposures.extend(_DEFAULT_LED_SECTORS)
    elif regime == "risk_off":
        # HY leading without IG confirmation — default-led with some duration.
        exposures.extend(_DEFAULT_LED_SECTORS[:3])
    elif regime == "duration_widening":
        exposures.extend(_RATE_LED_SECTORS)
    elif regime == "decoupled":
        # Pull a couple from each bucket — both channels show a pulse.
        exposures.extend(_DEFAULT_LED_SECTORS[:2] + _RATE_LED_SECTORS[:2])

    # Real-yield rise amplifies the rate-led cohort regardless of the
    # primary classifier call.
    if real_yield_rising:
        for s in _RATE_LED_SECTORS:
            if s not in exposures:
                exposures.append(s)

    # Dedup preserving insertion order.
    seen: set[str] = set()
    unique: list[str] = []
    for s in exposures:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------


def _rationale(
    credit_regime: dict,
    funding_stress: str,
    equity_vs_credit: str,
    vix_elevated: bool,
    safe_haven_bid: bool,
    real_yield_rising: bool,
) -> str:
    regime_label = (credit_regime or {}).get("regime_label") or "credit tape unavailable"
    diff = (credit_regime or {}).get("hy_ig_differential_5d")

    if funding_stress == "unavailable":
        return "Credit inputs unavailable — funding-stress read skipped."

    bits: list[str] = [regime_label]
    if diff is not None and abs(diff) >= 0.3:
        bits.append(f"HY−IG {diff:+.2f}%/5d")
    if vix_elevated:
        bits.append("VIX elevated")
    if safe_haven_bid:
        bits.append("safe-haven bid")
    if real_yield_rising:
        bits.append("real yields rising")

    bridge = {
        "acute":     "Acute funding stress — balance-sheet pressure building",
        "elevated":  "Elevated refinancing pressure on leveraged issuers",
        "contained": "Credit move contained — no systemic funding signal",
        "insulated": "Credit tape insulated / tightening — no funding pressure",
    }.get(funding_stress, "")

    equity_bridge = {
        "equity_only_riskoff":       "; equity hedging demand without credit confirmation",
        "credit_only_deterioration": "; spreads widening while equity remains complacent",
        "synchronized_stress":       "; equity and credit both deteriorating",
        "synchronized_calm":         "",
        "mixed":                     "; equity / credit signals diverge",
    }.get(equity_vs_credit, "")

    tail = f"  [{'; '.join(bits)}]" if bits else ""
    return f"{bridge}{equity_bridge}.{tail}"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def compute_credit_transmission(
    credit_regime: Optional[dict] = None,
    stress_regime: Optional[dict] = None,
    rates_context: Optional[dict] = None,
) -> dict:
    """Compose the credit / funding-stress transmission block."""
    credit_regime = credit_regime or {}
    stress_regime = stress_regime or {}
    rates_context = rates_context or {}

    signals = stress_regime.get("signals") or {}
    vix_elevated = bool(signals.get("vix_elevated"))
    safe_haven_bid = bool(signals.get("safe_haven_bid"))

    # Real yield 5d change (pp-equivalent): TIP ETF moves inversely with
    # real yields, so a negative TIP change implies rising real yields.
    real_proxy = rates_context.get("real_proxy") or {}
    tip_5d = real_proxy.get("change_5d")
    try:
        tip_5d_f = float(tip_5d) if tip_5d is not None else None
    except (TypeError, ValueError):
        tip_5d_f = None
    real_yield_rising = tip_5d_f is not None and tip_5d_f <= -0.3  # match stress threshold

    credit_available = bool(credit_regime.get("available"))
    funding = _classify_funding_stress(credit_regime, vix_elevated, real_yield_rising)
    equity_vs_credit = _classify_equity_vs_credit(credit_regime, vix_elevated, safe_haven_bid)
    exposures = _resolve_sector_exposures(credit_regime, real_yield_rising)

    drivers: list[str] = []
    default_signal = credit_regime.get("default_risk_signal")
    if default_signal == "widening":
        drivers.append("default_risk_widening")
    elif default_signal == "tightening":
        drivers.append("default_risk_tightening")
    if credit_regime.get("duration_signal") == "rising_rates":
        drivers.append("duration_rising_rates")
    if vix_elevated:
        drivers.append("vix_elevated")
    if safe_haven_bid:
        drivers.append("safe_haven_bid")
    if real_yield_rising:
        drivers.append("real_yield_rise")

    rationale = _rationale(
        credit_regime, funding, equity_vs_credit,
        vix_elevated, safe_haven_bid, real_yield_rising,
    )

    stale = not credit_available or not signals or tip_5d_f is None

    return {
        "funding_stress":         funding,
        "funding_stress_label":   _FUNDING_STRESS_LABELS[funding],
        "equity_vs_credit":       equity_vs_credit,
        "equity_vs_credit_label": _EQUITY_VS_CREDIT_LABELS[equity_vs_credit],
        "sector_exposures":       exposures,
        "drivers":                drivers,
        "rationale":              rationale,
        "signals": {
            "default_risk_signal":   credit_regime.get("default_risk_signal") or "unavailable",
            "duration_signal":       credit_regime.get("duration_signal") or "unavailable",
            "hy_ig_differential_5d": credit_regime.get("hy_ig_differential_5d"),
            "vix_elevated":          vix_elevated,
            "safe_haven_bid":        safe_haven_bid,
            "real_yield_rising":     real_yield_rising,
        },
        "available": credit_available,
        "stale":     stale,
    }

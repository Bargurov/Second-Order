"""
funding_stress_classifier.py

Decompose the broad "stress" read into explicit, orthogonal funding /
liquidity modes.

Why this module
---------------
``compute_stress_regime`` already emits a single aggregate regime label
("Calm" / "Undercurrent" / "Systemic Stress" / …) plus signal flags.
``credit_regime`` separately classifies HY/IG/SHY direction.  What
neither surfaces is the specific FINANCE-REAL stress MODE the tape is
expressing — and the transmission playbook for each mode is different:

  * **duration_shock**   — rates-led sell-off; long bonds hurt most,
    duration-heavy equities (utilities, REITs, long-duration tech) lag,
    credit pressure is *rates-transmitted*, not default-driven.
  * **credit_widening**  — default-risk spreads blowing out; HY
    underperforms IG, banks + leveraged issuers pressured, flight-to-
    quality into Treasuries typically rallies duration at the same time.
  * **dollar_shortage**  — USD funding squeeze; DXY bid broadly, EM
    FX bleeding, pegged-regime reserves under pressure, gold often
    firm as a non-dollar haven.
  * **liquidity_squeeze** — broad risk aversion across dimensions;
    VIX spike + breadth deterioration + safe-haven bid, often but not
    always coincident with the other three.

The four modes are NOT mutually exclusive — a late-cycle event can
fire multiple at once — but they emit different transmission
signatures and the engine should name WHICH mode is binding.

Pure composer.  No I/O.  Never raises.

Contract
--------
    classify_funding_stress(
        rates_context,  stress_regime,
        credit_regime,   fx_pack,
    ) -> dict

Returned shape::

    {
      "available":           bool,
      "modes": {
        "duration_shock":    {fired, severity, drivers, rationale},
        "credit_widening":   {...},
        "dollar_shortage":   {...},
        "liquidity_squeeze": {...},
      },
      "active_modes":        [str, ...],        # severity >= "mild"
      "primary_mode":        str,                # "none" when nothing fires
      "composite_severity":  "none"|"mild"|"elevated"|"acute",
      "rationale":           str,
    }
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Thresholds — judgment-set against the same empirical 5d move distributions
# the shock / reaction composers use.  The per-tier percentile labels below
# (~p85 / ~p95) are APPROXIMATE orientation against those distributions —
# calibrate_thresholds_pass2.py computes the |TNX 5d| / |HYG 5d| / |DXY 5d|
# move distributions — NOT a pinned calibration target: this module is not
# named in that script's targets, so read the percentiles as orientation,
# not asserted calibration.
# ---------------------------------------------------------------------------

# Duration shock: 10Y nominal 5d change, measured in pp (basis points / 100).
_DURATION_ELEVATED_PP: float = 0.25   # ~p85 of |TNX 5d| (approx.)
_DURATION_ACUTE_PP:    float = 0.45   # ~p95 of |TNX 5d| (approx.)

# Credit widening: HYG ETF 5d %-change.  Sign matters (negative = spreads
# wider).  Magnitudes documented at the rough percentile they fire at.
_CREDIT_ELEVATED_PCT: float = -1.0    # HY drops 1%+ in 5d
_CREDIT_ACUTE_PCT:    float = -2.0    # HY drops 2%+ in 5d
# Default-risk amplifier: HY underperforming IG is a stronger default-risk
# signal than a joint HY+IG drop (duration-driven).
_HY_IG_DIFFERENTIAL_FLOOR: float = -0.6

# Dollar shortage: DXY 5d % (always stress when positive and broad).
_DOLLAR_ELEVATED_PCT: float = 1.0
_DOLLAR_ACUTE_PCT:    float = 2.0
# USDCNY break is a dedicated dollar-shortage amplifier: CNY is tightly
# managed so anything >0.5%/5d means the PBoC is letting reserves bleed.
_USDCNY_BREAK_PCT:    float = 0.50

# Liquidity squeeze: VIX absolute level.  The broader flag also requires
# at least one stress-flag corroboration (safe-haven or breadth).
_VIX_ELEVATED: float = 25.0
_VIX_ACUTE:    float = 30.0


# Severity ordering — used to aggregate.
_SEVERITY_ORDER: tuple[str, ...] = ("none", "mild", "elevated", "acute")
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}


# Tie-break order when multiple modes reach the same severity.  Earlier
# means "primary".  Duration wins ties because a rates-led shock is the
# widest-transmission mode; liquidity ranks last because it overlaps
# with every other mode and shouldn't "claim" the primary label when a
# more specific mode fired alongside.
_MODE_PRIORITY: tuple[str, ...] = (
    "duration_shock",
    "credit_widening",
    "dollar_shortage",
    "liquidity_squeeze",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def _empty_mode(reason: str = "") -> dict[str, Any]:
    return {
        "fired":    False,
        "severity": "none",
        "drivers":  [],
        "rationale": reason,
    }


# ---------------------------------------------------------------------------
# Per-mode classifiers
# ---------------------------------------------------------------------------

def _classify_duration_shock(rates_context: Optional[dict]) -> dict[str, Any]:
    """Rates-led shock read from the 10Y nominal 5d change."""
    if not isinstance(rates_context, dict):
        return _empty_mode("rates context unavailable")

    tnx_5d = _f((rates_context.get("nominal") or {}).get("change_5d"))
    if tnx_5d is None:
        return _empty_mode("10Y 5d change unavailable")

    mag = abs(tnx_5d)
    if mag >= _DURATION_ACUTE_PP:
        severity = "acute"
    elif mag >= _DURATION_ELEVATED_PP:
        severity = "elevated"
    elif mag >= _DURATION_ELEVATED_PP * 0.6:
        severity = "mild"
    else:
        severity = "none"

    drivers: list[str] = []
    if severity != "none":
        direction = "higher" if tnx_5d > 0 else "lower"
        drivers.append(f"10Y nominal {tnx_5d:+.2f}pp/5d ({direction} yields)")

    # Curve-parallel shift amplifies — if the whole curve is moving
    # together, duration is binding across tenors.
    curve = rates_context.get("breakeven_curve") or {}
    shape = (curve.get("shape") or "").lower()
    if severity != "none" and shape in ("parallel_up", "parallel_down"):
        drivers.append(f"breakeven curve {shape}")
        # Parallel ups under severe rates-up move escalates to acute.
        if severity == "elevated" and shape == "parallel_up" and tnx_5d > 0:
            severity = "acute"

    return {
        "fired":    severity != "none",
        "severity": severity,
        "drivers":  drivers,
        "rationale": "; ".join(drivers) if drivers else "no material 10Y move",
    }


def _classify_credit_widening(
    stress_regime: Optional[dict],
    credit_regime: Optional[dict],
) -> dict[str, Any]:
    """Credit-spread-widening read from HYG + HY/IG differential."""
    if not isinstance(stress_regime, dict):
        return _empty_mode("stress regime unavailable")
    raw = stress_regime.get("raw") or {}
    hyg_5d = _f(raw.get("hyg_5d"))

    drivers: list[str] = []
    severity = "none"

    if hyg_5d is not None:
        if hyg_5d <= _CREDIT_ACUTE_PCT:
            severity = "acute"
            drivers.append(f"HYG {hyg_5d:+.2f}%/5d (HY spreads blowing out)")
        elif hyg_5d <= _CREDIT_ELEVATED_PCT:
            severity = "elevated"
            drivers.append(f"HYG {hyg_5d:+.2f}%/5d (HY under pressure)")
        elif hyg_5d <= _CREDIT_ELEVATED_PCT * 0.5:  # -0.5%
            severity = "mild"
            drivers.append(f"HYG {hyg_5d:+.2f}%/5d")

    # Default-risk amplifier: HY underperforming IG isolates spread
    # widening from broader duration moves.
    diff = _f((credit_regime or {}).get("hy_ig_differential_5d"))
    if severity != "none" and diff is not None and diff <= _HY_IG_DIFFERENTIAL_FLOOR:
        drivers.append(
            f"HY-IG differential {diff:+.2f}% (default-risk driven)"
        )
        # Escalate elevated to acute when default-risk is the driver.
        if severity == "elevated":
            severity = "acute"

    # Fold in the pre-classified credit_regime label as evidence.
    regime_label = (credit_regime or {}).get("regime", "")
    if regime_label == "default_risk_widening" and severity == "none":
        severity = "mild"
        drivers.append("credit_regime flagged default_risk_widening")

    return {
        "fired":    severity != "none",
        "severity": severity,
        "drivers":  drivers,
        "rationale": "; ".join(drivers) if drivers else "no material HY pressure",
    }


def _classify_dollar_shortage(
    fx_pack: Optional[dict],
    stress_regime: Optional[dict],
) -> dict[str, Any]:
    """USD funding squeeze read from DXY + dispersion + USDCNY break.

    Distinct from duration_shock because the dollar can rally on pure
    funding pressure even when rates are falling (a classic risk-off
    flight-to-dollar).  Requires BROAD dollar strength (not a single
    pair driving it) to fire.
    """
    # Prefer the richer fx_pack; fall back to stress_regime safe-haven
    # dollar reading when fx_pack is absent.
    dxy_5d: Optional[float] = None
    usdcny_5d: Optional[float] = None
    dispersion_tag: Optional[str] = None

    if isinstance(fx_pack, dict):
        dxy_5d = _f(fx_pack.get("dxy_5d"))
        pairs = fx_pack.get("pairs") or {}
        usdcny_5d = _f((pairs.get("USDCNY") or {}).get("usd_5d"))
        dispersion_tag = fx_pack.get("dispersion_tag")

    if dxy_5d is None and isinstance(stress_regime, dict):
        detail = ((stress_regime.get("detail") or {}).get("safe_haven") or {})
        dxy_5d = _f((detail.get("assets") or {}).get("Dollar"))

    if dxy_5d is None:
        return _empty_mode("dollar move unavailable")

    severity = "none"
    drivers: list[str] = []

    if dxy_5d >= _DOLLAR_ACUTE_PCT:
        severity = "acute"
        drivers.append(f"DXY +{dxy_5d:.2f}%/5d (broad dollar spike)")
    elif dxy_5d >= _DOLLAR_ELEVATED_PCT:
        severity = "elevated"
        drivers.append(f"DXY +{dxy_5d:.2f}%/5d")
    elif dxy_5d >= _DOLLAR_ELEVATED_PCT * 0.6:
        severity = "mild"
        drivers.append(f"DXY +{dxy_5d:.2f}%/5d")

    # Uniform dispersion amplifies — broad USD strength vs a single-pair
    # dollar story is a classic funding squeeze signature.
    if severity != "none" and dispersion_tag == "uniform":
        drivers.append("uniform dispersion across pairs")
        if severity == "elevated":
            severity = "acute"

    # USDCNY break amplifies because CNY is managed — any meaningful move
    # means the PBoC is letting reserves bleed.
    if usdcny_5d is not None and usdcny_5d >= _USDCNY_BREAK_PCT:
        drivers.append(f"USDCNY +{usdcny_5d:.2f}%/5d (managed-rate break)")
        # Escalate by one tier on a CNY break.
        if severity == "none":
            severity = "mild"
        elif severity == "mild":
            severity = "elevated"
        elif severity == "elevated":
            severity = "acute"

    return {
        "fired":    severity != "none",
        "severity": severity,
        "drivers":  drivers,
        "rationale": "; ".join(drivers) if drivers else "no material USD move",
    }


def _classify_liquidity_squeeze(stress_regime: Optional[dict]) -> dict[str, Any]:
    """Broad risk-aversion read from VIX + breadth + safe-haven bid.

    Requires BOTH a VIX level trigger AND at least one corroborating
    signal (safe-haven or breadth) — a standalone VIX spike without
    breadth confirmation is often single-name / sector noise rather
    than a liquidity event.
    """
    if not isinstance(stress_regime, dict):
        return _empty_mode("stress regime unavailable")
    raw = stress_regime.get("raw") or {}
    signals = stress_regime.get("signals") or {}

    vix = _f(raw.get("vix"))
    if vix is None:
        return _empty_mode("VIX unavailable")

    safe_haven = bool(signals.get("safe_haven_bid"))
    breadth = bool(signals.get("breadth_deterioration"))

    drivers: list[str] = []
    severity = "none"

    if vix >= _VIX_ACUTE:
        severity = "acute"
        drivers.append(f"VIX {vix:.1f} (acute tail)")
    elif vix >= _VIX_ELEVATED:
        severity = "elevated"
        drivers.append(f"VIX {vix:.1f} elevated")
    elif vix >= _VIX_ELEVATED * 0.8:  # ~20
        severity = "mild"
        drivers.append(f"VIX {vix:.1f}")

    # Corroboration requirement: when only VIX is elevated but neither
    # safe-haven nor breadth fires, demote to mild — isolated VIX is
    # often a specific-name event, not a liquidity regime.
    corroborated = safe_haven or breadth
    if severity in ("elevated", "acute") and not corroborated:
        severity = "mild"
        drivers.append("no breadth/safe-haven corroboration")

    if safe_haven:
        drivers.append("safe-haven bid active")
    if breadth:
        drivers.append("breadth deterioration")

    return {
        "fired":    severity != "none",
        "severity": severity,
        "drivers":  drivers,
        "rationale": "; ".join(drivers) if drivers else "no material liquidity stress",
    }


# ---------------------------------------------------------------------------
# Aggregate composer
# ---------------------------------------------------------------------------

def _primary_and_composite(modes: dict[str, dict]) -> tuple[str, str]:
    """Pick the primary mode + composite severity.

    Primary mode = the fired mode with highest severity, tied by
    ``_MODE_PRIORITY`` order.  Returns ("none", "none") when nothing fires.
    """
    fired = [(name, mode["severity"]) for name, mode in modes.items() if mode["fired"]]
    if not fired:
        return "none", "none"

    # Highest severity rank, breaking ties by priority order.
    def _key(entry: tuple[str, str]) -> tuple[int, int]:
        name, sev = entry
        return (_SEVERITY_RANK[sev], -_MODE_PRIORITY.index(name))

    fired.sort(key=_key, reverse=True)
    primary_name = fired[0][0]
    composite = fired[0][1]

    return primary_name, composite


def classify_funding_stress(
    rates_context: Optional[dict] = None,
    stress_regime: Optional[dict] = None,
    credit_regime: Optional[dict] = None,
    fx_pack:       Optional[dict] = None,
) -> dict[str, Any]:
    """Decompose the tape into four orthogonal funding / liquidity modes.

    Every input is optional; missing inputs degrade the relevant mode
    to ``fired=False`` rather than blocking the others.  The composite
    severity is the max across fired modes; the primary mode is the one
    whose drivers are dominant (priority tie-break for equal severity).

    Never raises.  When nothing fires, returns an all-``none`` structure
    with ``available`` still True so the engine can distinguish "we
    looked and nothing is stressed" from "we couldn't look at all".
    """
    modes = {
        "duration_shock":    _classify_duration_shock(rates_context),
        "credit_widening":   _classify_credit_widening(stress_regime, credit_regime),
        "dollar_shortage":   _classify_dollar_shortage(fx_pack, stress_regime),
        "liquidity_squeeze": _classify_liquidity_squeeze(stress_regime),
    }

    # Availability: at least one classifier had enough input to produce
    # a non-"unavailable" rationale.  The per-mode _empty_mode paths
    # that returned a "…unavailable" rationale count as NOT available.
    available = any(
        not m["rationale"].endswith("unavailable")
        for m in modes.values()
    )

    primary, composite = _primary_and_composite(modes)

    active = [
        name for name, m in modes.items()
        if _SEVERITY_RANK.get(m["severity"], 0) >= _SEVERITY_RANK["mild"]
    ]
    # Active list returned in priority order for deterministic UI rendering.
    active.sort(key=lambda n: _MODE_PRIORITY.index(n))

    # One-line rationale summarising the active modes.
    if not active:
        rationale = "No funding/liquidity stress mode firing"
    else:
        parts = []
        for name in active:
            mode = modes[name]
            parts.append(f"{name} ({mode['severity']})")
        rationale = (
            f"Primary: {primary} [{composite}]; active: "
            + ", ".join(parts)
        )

    return {
        "available":          available,
        "modes":              modes,
        "active_modes":       active,
        "primary_mode":       primary,
        "composite_severity": composite,
        "rationale":          rationale,
    }

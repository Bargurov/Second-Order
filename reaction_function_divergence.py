"""
reaction_function_divergence.py

Reaction Function Divergence.

Compares what the EVENT implies policymakers *should* do against what
markets are *actually* pricing right now, and surfaces the tension when
those two read differently.  Reuses the existing thesis classifier and
live macro / snapshot infrastructure — no new fetches.

Output shape
------------
    {
      implied:          "hawkish" | "dovish" | "neutral",
      implied_label:    "Hawkish (tighter)" | ...,
      implied_basis:    str,               # why the event reads that way
      priced:           "hawkish" | "dovish" | "neutral",
      priced_label:     "Dovish (easing priced)" | ...,
      priced_basis:     str,               # what markets are doing
      divergence:       "aligned" | "mild" | "sharp",
      divergence_label: "Aligned" | "Mild divergence" | "Sharp divergence",
      rationale:        str,               # one-line tie to numbers
      macro_read:       str,               # institutional "so what"
      key_markets:      list[str],
      available:        bool,
      stale:            bool,
    }

Design
------
- Pure composer; takes pre-fetched inputs and performs no I/O.
- Implied direction is derived from the existing thesis classifier in
  ``real_yield_context`` so the language stays consistent across modules.
- Priced direction is a small bidirectional score: hawkish points and
  dovish points are accumulated from nominal / real / breakeven moves,
  the rates regime label, stress-regime signals and snapshot overlays.
- Divergence is the 2-axis cross product of {hawkish, dovish, neutral}
  on both sides.  Opposite directions = "sharp"; one neutral = "mild";
  same label = "aligned".
- Returns ``{}`` only when there is no usable thesis AND no usable macro.
  Otherwise returns the block with ``stale=True`` and the unavailable
  side degraded to neutral, so the UI can still render.
"""

from __future__ import annotations

from typing import Optional

from real_yield_context import classify_thesis


# ---------------------------------------------------------------------------
# Direction labels + metadata
# ---------------------------------------------------------------------------

DIRECTION_IDS: tuple[str, ...] = ("hawkish", "dovish", "neutral")

_IMPLIED_LABEL: dict[str, str] = {
    "hawkish": "Hawkish (tighter)",
    "dovish":  "Dovish (easier)",
    "neutral": "Neutral",
}

_PRICED_LABEL: dict[str, str] = {
    "hawkish": "Hawkish (tightening priced)",
    "dovish":  "Dovish (easing priced)",
    "neutral": "Neutral",
}

_DIVERGENCE_LABEL: dict[str, str] = {
    "aligned": "Aligned",
    "mild":    "Mild divergence",
    "sharp":   "Sharp divergence",
}

# Canonical liquid markets per divergence read.  Points at the markets a
# macro desk would watch to confirm or challenge the divergence.
_KEY_MARKETS: dict[str, list[str]] = {
    "aligned": ["10Y", "TIP", "DXY", "ES"],
    "mild":    ["10Y", "TIP", "2Y", "DXY", "ES"],
    "sharp":   ["2Y", "10Y", "TIP", "DXY", "ES", "GC"],
}


# ---------------------------------------------------------------------------
# Macro-read sentence templates
# ---------------------------------------------------------------------------
# Keyed on (implied, priced).  Only the interesting combinations are
# spelled out — fallbacks handle the remainder.

_MACRO_READ: dict[tuple[str, str], str] = {
    ("hawkish", "hawkish"): (
        "Event pressure and market pricing point the same way — reaction "
        "function has a clean hawkish mandate."
    ),
    ("dovish", "dovish"): (
        "Event pressure and market pricing point the same way — reaction "
        "function has a clean dovish mandate."
    ),
    ("neutral", "neutral"): (
        "Neither the event nor market pricing signals a directional shift "
        "in the reaction function."
    ),
    ("hawkish", "dovish"): (
        "Event implies tighter policy but markets are pricing cuts — "
        "either the thesis resolves benign or the market is fading it; "
        "watch front-end rates and real yields for repricing."
    ),
    ("dovish", "hawkish"): (
        "Event implies easier policy but markets are pricing tightening — "
        "either demand is stickier than thesis suggests or breakevens "
        "need to drop; watch real yields and equities."
    ),
    ("hawkish", "neutral"): (
        "Event implies hawkish pressure but market pricing is still flat — "
        "room for repricing if the thesis follows through."
    ),
    ("dovish", "neutral"): (
        "Event implies dovish pressure but markets aren't pricing easing "
        "yet — front-end rates and risk assets have room to catch up."
    ),
    ("neutral", "hawkish"): (
        "Markets are already pricing tightening without a clear event "
        "catalyst — fade risk is elevated on soft data."
    ),
    ("neutral", "dovish"): (
        "Markets are pricing easing without a clear event catalyst — "
        "positioning, not fundamentals, is doing the work."
    ),
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


# ---------------------------------------------------------------------------
# Implied policy direction (from the event)
# ---------------------------------------------------------------------------

def _implied_direction(headline: str, mechanism_text: str) -> tuple[str, str]:
    """Map the event thesis to an implied hawkish/dovish/neutral read.

    Returns (direction, basis_text).
    """
    info = classify_thesis(headline, mechanism_text)
    thesis = info.get("thesis", "none")
    evidence = info.get("evidence") or []
    evidence_str = ", ".join(evidence[:3]) if evidence else ""

    if thesis == "inflationary":
        basis = "thesis implies higher inflation"
        if evidence_str:
            basis += f" ({evidence_str})"
        return "hawkish", basis
    if thesis == "rate_pressure_up":
        basis = "thesis implies hawkish pressure"
        if evidence_str:
            basis += f" ({evidence_str})"
        return "hawkish", basis
    if thesis == "disinflationary":
        basis = "thesis implies cooler inflation"
        if evidence_str:
            basis += f" ({evidence_str})"
        return "dovish", basis
    if thesis == "rate_pressure_down":
        basis = "thesis implies dovish pressure"
        if evidence_str:
            basis += f" ({evidence_str})"
        return "dovish", basis

    return "neutral", "no clear policy thesis detected"


# ---------------------------------------------------------------------------
# Market-priced direction
# ---------------------------------------------------------------------------

def _priced_direction(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> tuple[str, str, int]:
    """Score what markets appear to be pricing right now.

    Returns (direction, basis_text, confidence_points).

    Sign convention: TIP ETF moves INVERSELY with real yields.
      real_5d < 0  => TIP fell  => real yields ROSE   (hawkish pricing)
      real_5d > 0  => TIP rose  => real yields FELL   (dovish pricing)
    """
    hawk = 0
    dove = 0
    bits: list[str] = []

    rc = rates_context or {}
    nom_5d = _f((rc.get("nominal") or {}).get("change_5d"))
    real_5d = _f((rc.get("real_proxy") or {}).get("change_5d"))
    be_5d = _f((rc.get("breakeven_proxy") or {}).get("change_5d"))
    regime = rc.get("regime")

    # --- Nominal 10Y ----------------------------------------------------
    if nom_5d is not None:
        if nom_5d > 0.3:
            hawk += 2
            bits.append(f"10Y +{nom_5d:.2f}/5d")
        elif nom_5d < -0.3:
            dove += 2
            bits.append(f"10Y {nom_5d:.2f}/5d")

    # --- Real yields (via TIP) -----------------------------------------
    if real_5d is not None:
        if real_5d < -0.4:
            hawk += 2
            bits.append(f"real yields rising (TIP {real_5d:.2f}/5d)")
        elif real_5d > 0.4:
            dove += 2
            bits.append(f"real yields falling (TIP +{real_5d:.2f}/5d)")

    # --- Breakevens as a hint ------------------------------------------
    if be_5d is not None:
        if be_5d < -0.3:
            # Breakevens collapsing is consistent with dovish/disinflation.
            dove += 1
        elif be_5d > 0.3:
            # Widening breakevens = inflation pricing, tilts hawkish.
            hawk += 1

    # --- Rates regime label --------------------------------------------
    if regime == "Real-rate tightening":
        hawk += 1
    elif regime == "Risk-off / growth scare":
        dove += 2
        bits.append("regime: risk-off / growth scare")
    elif regime == "Inflation pressure":
        hawk += 1

    # --- Stress signals -------------------------------------------------
    signals = (stress_regime or {}).get("signals") or {}
    if signals.get("safe_haven_bid"):
        dove += 1
        bits.append("safe-haven bid")
    if signals.get("credit_widening"):
        # Credit widening usually forces the market to start pricing cuts.
        dove += 1
        bits.append("credit widening")

    # --- Snapshot overlays ---------------------------------------------
    es_5d = _snap_change_5d(snapshots, "ES")
    if es_5d is not None and es_5d < -2.0:
        dove += 1
        bits.append(f"S&P {es_5d:+.1f}/5d")

    dxy_5d = _snap_change_5d(snapshots, "DXY")
    if dxy_5d is not None:
        if dxy_5d > 1.0:
            # Dollar strength usually reflects hawkish US repricing.
            hawk += 1
            bits.append(f"DXY +{dxy_5d:.1f}/5d")
        elif dxy_5d < -1.0:
            dove += 1
            bits.append(f"DXY {dxy_5d:.1f}/5d")

    # --- Decide ---------------------------------------------------------
    if hawk == 0 and dove == 0:
        return "neutral", "no clear directional pricing", 0
    if hawk > dove + 1:
        return "hawkish", "; ".join(bits) if bits else "hawkish bias", hawk
    if dove > hawk + 1:
        return "dovish", "; ".join(bits) if bits else "dovish bias", dove
    return "neutral", ("mixed pricing signals: " + "; ".join(bits)) if bits else "mixed pricing signals", max(hawk, dove)


# ---------------------------------------------------------------------------
# Divergence classifier
# ---------------------------------------------------------------------------

def _classify_divergence(implied: str, priced: str) -> str:
    if implied == priced:
        return "aligned"
    if implied == "neutral" or priced == "neutral":
        return "mild"
    return "sharp"


def _rationale(implied: str, priced: str, divergence: str,
               implied_basis: str, priced_basis: str) -> str:
    if divergence == "aligned":
        return (
            f"Event and market pricing both read {implied}: {implied_basis}; "
            f"markets confirm with {priced_basis}."
        )
    if divergence == "mild":
        if priced == "neutral":
            return (
                f"Event implies {implied} ({implied_basis}); markets not "
                f"pricing it yet ({priced_basis})."
            )
        return (
            f"Markets pricing {priced} ({priced_basis}); event has no clear "
            f"policy thesis ({implied_basis})."
        )
    # sharp
    return (
        f"Event implies {implied} ({implied_basis}); markets pricing the "
        f"opposite — {priced} ({priced_basis})."
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_reaction_function_divergence(
    headline: str,
    mechanism_text: str,
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]] = None,
) -> dict:
    """Compose the reaction-function divergence block.

    Pure composer — performs no I/O.  Degrades gracefully:
      - No thesis AND no usable macro → ``{}``.
      - Thesis present, macro stale → block with ``stale=True`` and
        ``priced="neutral"``.
      - Macro present, thesis absent → block with ``stale=False`` and
        ``implied="neutral"``.
    """
    implied, implied_basis = _implied_direction(headline, mechanism_text)
    priced, priced_basis, priced_pts = _priced_direction(
        rates_context, stress_regime, snapshots,
    )

    rates_ok = _rates_usable(rates_context)
    stress_ok = _stress_usable(stress_regime)
    macro_ok = rates_ok or stress_ok

    # If neither side has anything to say, nothing to render.
    if implied == "neutral" and not macro_ok:
        return {}

    # If macro is unusable, force priced to neutral and flag stale.
    if not macro_ok:
        priced = "neutral"
        priced_basis = "macro inputs unavailable"
        priced_pts = 0

    divergence = _classify_divergence(implied, priced)
    rationale = _rationale(implied, priced, divergence, implied_basis, priced_basis)
    macro_read = _MACRO_READ.get(
        (implied, priced),
        "Reaction-function direction is ambiguous given current inputs.",
    )

    return {
        "implied":          implied,
        "implied_label":    _IMPLIED_LABEL[implied],
        "implied_basis":    implied_basis,
        "priced":           priced,
        "priced_label":     _PRICED_LABEL[priced],
        "priced_basis":     priced_basis,
        "divergence":       divergence,
        "divergence_label": _DIVERGENCE_LABEL[divergence],
        "rationale":        rationale,
        "macro_read":       macro_read,
        "key_markets":      list(_KEY_MARKETS.get(divergence, [])),
        "available":        macro_ok,
        "stale":            not (rates_ok and stress_ok),
    }

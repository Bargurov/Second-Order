"""
real_yield_context.py

Real-yield + breakeven inflation context block for the analysis flow.

What this adds
--------------
Some events come with an implicit *thesis* about inflation, disinflation,
or rate-pressure direction.  Until now we showed `policy_sensitivity` and
`inventory_context` separately, but neither one cross-checks the analysis
thesis directly against the live real-yield / breakeven trajectory.

This module reuses the existing `compute_rates_context()` data path
(which already pulls ^TNX + TIP through the warm cache) and produces a
small structured block:

  {
    "thesis":               "inflationary" | "disinflationary"
                            | "rate_pressure_up" | "rate_pressure_down"
                            | "none",
    "thesis_evidence":      list[str]    # keywords that triggered thesis,
    "alignment":            "confirm" | "tension" | "neutral" | "stale",
    "regime":               str | None,  # the rates regime label
    "nominal_5d":           float | None,
    "real_proxy_5d":        float | None,
    "breakeven_proxy_5d":   float | None,
    "explanation":          str,         # one short human sentence
    "available":            bool,        # macro data was usable
    "stale":                bool,        # macro data was missing/stale
  }

Design notes
------------
- Thesis classification is keyword-driven and deterministic.  No new
  LLM call.  An empty thesis returns `{}` so api.py can skip rendering.
- A non-confirming macro context surfaces as `alignment="tension"`,
  NOT as a hard contradiction.  Validation never blocks the analysis.
- When the underlying rates context is unavailable or "Mixed" with
  no real numbers, alignment is `"stale"` and `available=False` so
  the UI can render a degraded "macro data unavailable" pill.
- The function is pure: it takes pre-fetched `rates_context` so the
  caller (api.py) controls all I/O and tests can pass synthetic data.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Thesis keyword maps — deliberately small + specific
# ---------------------------------------------------------------------------

# Words that imply the event pushes inflation higher.
_INFLATIONARY_KW: tuple[str, ...] = (
    "tariff", "import cost", "supply shock", "supply disruption",
    "opec cut", "production cut", "export ban", "sanction",
    "wage pressure", "wage gain", "minimum wage", "rent",
    "energy price", "oil price", "crude price", "gasoline",
    "fuel cost", "input cost", "shipping cost", "freight rate",
    "food price", "grain price", "fertiliz", "drought",
    "commodity rally", "scarcity", "shortage", "bottleneck",
    "price hike", "passes through to consumers",
)

# Words that imply the event pushes inflation lower.
_DISINFLATIONARY_KW: tuple[str, ...] = (
    "demand destruction", "recession", "deflation", "price war",
    "discounting", "glut", "oversupply", "inventory build",
    "production surge", "capacity expansion", "tariff relief",
    "subsidy", "price cap", "ceasefire", "supply restored",
    "pipeline restart", "export resumed", "harvest",
    "softening demand", "consumer pullback",
)

# Words that imply the event raises policy-rate pressure (hawkish).
_RATE_UP_KW: tuple[str, ...] = (
    "rate hike", "tighter policy", "hawkish", "fed hike",
    "ecb hike", "boe hike", "boj hike", "raise rates",
    "restrictive policy", "qt", "balance sheet runoff",
    "above-target inflation", "sticky inflation",
)

# Words that imply the event lowers policy-rate pressure (dovish).
_RATE_DOWN_KW: tuple[str, ...] = (
    "rate cut", "easier policy", "dovish", "fed cut", "ecb cut",
    "boe cut", "boj cut", "lower rates", "accommodative",
    "qe", "balance sheet expansion", "pause hikes", "pivot",
    "growth scare", "soft landing risk",
)


THESIS_LABELS = (
    "inflationary",
    "disinflationary",
    "rate_pressure_up",
    "rate_pressure_down",
    "none",
)


# ---------------------------------------------------------------------------
# Thesis classifier
# ---------------------------------------------------------------------------

def classify_thesis(headline: str, mechanism_text: str = "") -> dict:
    """Return a thesis label + the evidence keywords that fired.

    Returns a dict {thesis, evidence}.  ``thesis="none"`` when no
    keyword matches; ``evidence`` is the deduped list of terms hit.

    The headline and mechanism are concatenated and lowercased.  When
    multiple thesis families match, the strongest signal wins, with
    inflation/disinflation taking precedence over rate-pressure
    (because they're closer to the breakeven channel).
    """
    text = f"{headline or ''} {mechanism_text or ''}".lower()
    if not text.strip():
        return {"thesis": "none", "evidence": []}

    inflation_hits = [kw for kw in _INFLATIONARY_KW if kw in text]
    disinflation_hits = [kw for kw in _DISINFLATIONARY_KW if kw in text]
    rate_up_hits = [kw for kw in _RATE_UP_KW if kw in text]
    rate_down_hits = [kw for kw in _RATE_DOWN_KW if kw in text]

    # Inflation/disinflation override rate hawkish/dovish — they're the
    # primary breakeven signal.
    if inflation_hits and not disinflation_hits:
        return {"thesis": "inflationary", "evidence": inflation_hits}
    if disinflation_hits and not inflation_hits:
        return {"thesis": "disinflationary", "evidence": disinflation_hits}
    if inflation_hits and disinflation_hits:
        # Conflicting signals → fall back to whichever has more hits.
        if len(inflation_hits) >= len(disinflation_hits):
            return {"thesis": "inflationary", "evidence": inflation_hits}
        return {"thesis": "disinflationary", "evidence": disinflation_hits}

    if rate_up_hits and not rate_down_hits:
        return {"thesis": "rate_pressure_up", "evidence": rate_up_hits}
    if rate_down_hits and not rate_up_hits:
        return {"thesis": "rate_pressure_down", "evidence": rate_down_hits}
    if rate_up_hits and rate_down_hits:
        if len(rate_up_hits) >= len(rate_down_hits):
            return {"thesis": "rate_pressure_up", "evidence": rate_up_hits}
        return {"thesis": "rate_pressure_down", "evidence": rate_down_hits}

    return {"thesis": "none", "evidence": []}


# ---------------------------------------------------------------------------
# Macro pre-flight: did rates_context come back with usable numbers?
# ---------------------------------------------------------------------------

def _macro_is_usable(rates_context: Optional[dict]) -> bool:
    """Return True iff the supplied rates_context has at least nominal+real
    5-day moves available so we can score alignment."""
    if not rates_context or not isinstance(rates_context, dict):
        return False
    nom = (rates_context.get("nominal") or {}).get("change_5d")
    real = (rates_context.get("real_proxy") or {}).get("change_5d")
    return nom is not None and real is not None


def _breakeven_5d(rates_context: dict) -> Optional[float]:
    """Pull the breakeven proxy 5d from the existing rates_context dict."""
    be = rates_context.get("breakeven_proxy") or {}
    val = be.get("change_5d")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Alignment scoring
# ---------------------------------------------------------------------------

def _alignment_for(thesis: str, regime: Optional[str], breakeven_5d: Optional[float],
                   real_5d: Optional[float], nominal_5d: Optional[float]) -> str:
    """Decide whether the macro context confirms or tensions the thesis.

    Returns one of: "confirm" | "tension" | "neutral".
    """
    if thesis == "none":
        return "neutral"

    if thesis == "inflationary":
        # Confirm: breakevens widening OR regime is "Inflation pressure".
        if regime == "Inflation pressure":
            return "confirm"
        if breakeven_5d is not None and breakeven_5d > 0.2:
            return "confirm"
        # Tension: real-rate tightening or growth scare with no breakeven lift.
        if regime in ("Real-rate tightening", "Risk-off / growth scare"):
            return "tension"
        if breakeven_5d is not None and breakeven_5d < -0.2:
            return "tension"
        return "neutral"

    if thesis == "disinflationary":
        if regime in ("Real-rate tightening", "Risk-off / growth scare"):
            return "confirm"
        if breakeven_5d is not None and breakeven_5d < -0.2:
            return "confirm"
        if regime == "Inflation pressure":
            return "tension"
        if breakeven_5d is not None and breakeven_5d > 0.2:
            return "tension"
        return "neutral"

    # Sign convention: real_5d is the TIP ETF price change.
    # TIP moves INVERSELY with real yields, so:
    #   real_5d < 0  => TIP fell  => real yields ROSE  (tightening)
    #   real_5d > 0  => TIP rose  => real yields FELL  (easing)

    if thesis == "rate_pressure_up":
        # Hawkish event confirms when real yields rose (TIP fell).
        if real_5d is not None and real_5d < -0.2:
            return "confirm"
        if regime == "Real-rate tightening":
            return "confirm"
        if real_5d is not None and real_5d > 0.2:
            return "tension"
        if regime == "Risk-off / growth scare":
            return "tension"
        return "neutral"

    if thesis == "rate_pressure_down":
        # Dovish event confirms when real yields fell (TIP rose).
        if real_5d is not None and real_5d > 0.2:
            return "confirm"
        if regime == "Risk-off / growth scare":
            return "confirm"
        if real_5d is not None and real_5d < -0.2:
            return "tension"
        if regime == "Real-rate tightening":
            return "tension"
        return "neutral"

    return "neutral"


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def _explain(thesis: str, alignment: str, regime: Optional[str],
             breakeven_5d: Optional[float], real_5d: Optional[float]) -> str:
    """Return one short institutional sentence describing the result."""
    be_text = (
        f"breakevens {breakeven_5d:+.2f}% / 5d"
        if breakeven_5d is not None else "breakeven proxy unavailable"
    )
    real_text = (
        f"real-yield proxy {real_5d:+.2f}% / 5d"
        if real_5d is not None else "real-yield proxy unavailable"
    )
    regime_text = regime or "regime unclear"

    if thesis == "inflationary":
        if alignment == "confirm":
            return f"Thesis implies higher inflation; {regime_text}, {be_text} — macro confirms."
        if alignment == "tension":
            return f"Thesis implies higher inflation but {regime_text}, {be_text} — macro does NOT confirm."
        return f"Thesis implies higher inflation; macro inconclusive ({regime_text}, {be_text})."

    if thesis == "disinflationary":
        if alignment == "confirm":
            return f"Thesis implies cooler inflation; {regime_text}, {be_text} — macro confirms."
        if alignment == "tension":
            return f"Thesis implies cooler inflation but {regime_text}, {be_text} — macro does NOT confirm."
        return f"Thesis implies cooler inflation; macro inconclusive ({regime_text}, {be_text})."

    if thesis == "rate_pressure_up":
        if alignment == "confirm":
            return f"Thesis implies hawkish pressure; {regime_text}, {real_text} — macro confirms."
        if alignment == "tension":
            return f"Thesis implies hawkish pressure but {regime_text}, {real_text} — macro does NOT confirm."
        return f"Thesis implies hawkish pressure; macro inconclusive ({regime_text}, {real_text})."

    if thesis == "rate_pressure_down":
        if alignment == "confirm":
            return f"Thesis implies dovish pressure; {regime_text}, {real_text} — macro confirms."
        if alignment == "tension":
            return f"Thesis implies dovish pressure but {regime_text}, {real_text} — macro does NOT confirm."
        return f"Thesis implies dovish pressure; macro inconclusive ({regime_text}, {real_text})."

    return f"No inflation/rate thesis detected ({regime_text})."


# ---------------------------------------------------------------------------
# Public composer — pure, no I/O
# ---------------------------------------------------------------------------

def build_real_yield_context(
    headline: str,
    mechanism_text: str,
    rates_context: Optional[dict],
) -> dict:
    """Build the real-yield / breakeven context block.

    Pure composer — performs no I/O.  The caller (api.py) is responsible
    for fetching `rates_context` via `compute_rates_context()` and passing
    it in.  Tests can pass synthetic dicts directly.

    Returns ``{}`` when no thesis is detected — api.py can then skip
    rendering rather than show an empty card.
    """
    thesis_info = classify_thesis(headline, mechanism_text)
    thesis = thesis_info["thesis"]

    # No thesis → no card. This keeps the analysis page uncluttered for
    # events that have nothing to do with inflation or rates.
    if thesis == "none":
        return {}

    if not _macro_is_usable(rates_context):
        return {
            "thesis": thesis,
            "thesis_evidence": thesis_info["evidence"],
            "alignment": "stale",
            "regime": (rates_context or {}).get("regime"),
            "nominal_5d": None,
            "real_proxy_5d": None,
            "breakeven_proxy_5d": None,
            "explanation": (
                "Real-yield / breakeven series unavailable — cannot cross-check "
                "the thesis against live macro data."
            ),
            "available": False,
            "stale": True,
        }

    # Macro is usable — score alignment.
    nominal_5d = (rates_context.get("nominal") or {}).get("change_5d")
    real_5d = (rates_context.get("real_proxy") or {}).get("change_5d")
    breakeven_5d = _breakeven_5d(rates_context)
    regime = rates_context.get("regime")

    alignment = _alignment_for(
        thesis, regime, breakeven_5d, real_5d, nominal_5d,
    )
    explanation = _explain(thesis, alignment, regime, breakeven_5d, real_5d)

    return {
        "thesis": thesis,
        "thesis_evidence": thesis_info["evidence"],
        "alignment": alignment,
        "regime": regime,
        "nominal_5d": nominal_5d,
        "real_proxy_5d": real_5d,
        "breakeven_proxy_5d": breakeven_5d,
        "explanation": explanation,
        "available": True,
        "stale": False,
    }

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
from shock_decomposition import compute_shock_decomposition
from cross_asset_confirmation import compute_cross_asset_confirmation
from cross_asset_coherence import compute_cross_asset_coherence


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

# ---------------------------------------------------------------------------
# Mechanism-specific reaction reads
# ---------------------------------------------------------------------------
# Replace the old bulk hawk/dove point accumulator with per-channel reads.
# Each channel's observed move is checked against a hawkish-expectation map;
# aligned moves add to hawk_score, opposing moves add to dove_score, silent
# (below z-floor) channels contribute nothing.  The priced direction is
# then whichever score clearly leads — not a raw point count.

# Direction convention matches shock_decomposition._CHANNEL_UNITS.
# Only channels with a clean one-sided hawkish read are included; breakeven
# and commodity are deliberately excluded because they cut both ways across
# policy vs supply-shock mechanisms.
_HAWKISH_EXPECT: dict[str, str] = {
    "nominal_yield": "up",     # 10Y pp rising is hawkish pricing
    "real_yield":    "down",   # TIP falling = real yields up = restrictive
    "fx":            "up",     # DXY strength = hawkish US
    "credit":        "up",     # widening = tighter financial conditions
}

# Z-score floor a channel must clear to be counted at all.
_CHANNEL_Z_FLOOR: float = 0.8

# Score separation needed to declare a direction.  Matches the old "> 1"
# rule in points but now applied to z-weighted magnitudes.
_DIRECTION_MARGIN: float = 0.8


def _channel_reads(channels: dict[str, dict]) -> tuple[list[dict], float, float]:
    """Derive mechanism-specific reads from the shock-decomposition channels.

    Returns (reads, hawk_score, dove_score).  Each entry in ``reads`` is:
      {channel, label, expected_for_hawkish, observed_dir, z, verdict,
       contribution}
    where ``verdict`` is one of "hawkish" / "dovish" / "silent".
    """
    reads: list[dict] = []
    hawk = 0.0
    dove = 0.0
    for cid, expected in _HAWKISH_EXPECT.items():
        ch = channels.get(cid) or {}
        if not isinstance(ch, dict):
            continue
        z = float(ch.get("z") or 0.0)
        move = ch.get("move_5d")
        observed_dir = "unavailable"
        if ch.get("available") and move is not None:
            if move > 0:
                observed_dir = "up"
            elif move < 0:
                observed_dir = "down"
            else:
                observed_dir = "flat"

        contribution = 0.0
        verdict = "silent"
        if (
            observed_dir in ("up", "down")
            and z >= _CHANNEL_Z_FLOOR
        ):
            if observed_dir == expected:
                verdict = "hawkish"
                contribution = z
                hawk += z
            else:
                verdict = "dovish"
                contribution = z
                dove += z

        reads.append({
            "channel":      cid,
            "label":        ch.get("label", cid),
            "expected_for_hawkish": expected,
            "observed":     move,
            "unit":         ch.get("unit", ""),
            "z":            round(z, 2),
            "observed_dir": observed_dir,
            "verdict":      verdict,
            "contribution": round(contribution, 2),
        })
    return reads, round(hawk, 2), round(dove, 2)


def _priced_direction(
    shock_channels: dict[str, dict],
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
) -> tuple[str, str, float, list[dict]]:
    """Score what markets appear to be pricing right now.

    Returns (direction, basis_text, lead_score, channel_reads).  The
    direction is derived from mechanism-specific reads over the six
    shock-decomposition channels, augmented by two small regime-level
    signals (rates regime label, stress safe-haven bid) that encode
    information not fully captured by 5d channel moves.

    Sign convention: TIP ETF moves INVERSELY with real yields.
    """
    reads, hawk, dove = _channel_reads(shock_channels or {})

    bits: list[str] = []
    for r in reads:
        if r["verdict"] == "silent":
            continue
        move = r["observed"]
        if move is None:
            continue
        bits.append(
            f"{r['label']} {move:+.2f}{r['unit']}/5d ({r['z']:.1f}σ)"
        )

    # Rates regime label adds a small nudge — it encodes multi-day
    # context (regime persistence) that 5d moves alone don't capture.
    regime = (rates_context or {}).get("regime")
    if regime == "Real-rate tightening":
        hawk += 0.5
    elif regime == "Inflation pressure":
        hawk += 0.5
    elif regime == "Risk-off / growth scare":
        dove += 1.0
        bits.append("regime: risk-off / growth scare")

    # Stress safe-haven bid adds to dovish pricing (bonds bid, risk off).
    signals = (stress_regime or {}).get("signals") or {}
    if signals.get("safe_haven_bid"):
        dove += 0.5
        bits.append("safe-haven bid")

    if hawk == 0 and dove == 0:
        return "neutral", "no clear directional pricing", 0.0, reads
    if hawk - dove > _DIRECTION_MARGIN:
        return (
            "hawkish",
            "; ".join(bits) if bits else "hawkish bias",
            round(hawk, 2),
            reads,
        )
    if dove - hawk > _DIRECTION_MARGIN:
        return (
            "dovish",
            "; ".join(bits) if bits else "dovish bias",
            round(dove, 2),
            reads,
        )
    return (
        "neutral",
        ("mixed pricing signals: " + "; ".join(bits)) if bits else "mixed pricing signals",
        round(max(hawk, dove), 2),
        reads,
    )


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

    # Build the shock-decomposition channels once so priced_direction and the
    # cross-asset confirmation matrix share a single view of the tape.
    shock_block = compute_shock_decomposition(rates_context, stress_regime, snapshots)
    shock_channels = (shock_block or {}).get("channels") or {}
    rates_pack = (shock_block or {}).get("rates_pack") or {}

    priced, priced_basis, priced_lead, mechanism_reads = _priced_direction(
        shock_channels, rates_context, stress_regime,
    )

    # Confirmation matrix — uses the event's own thesis (not hawk/dove) so
    # confirms and disconfirms are scored against the mechanism the event
    # actually implies, not a generic hawkish probe.
    thesis_info = classify_thesis(headline, mechanism_text)
    confirmation_matrix = compute_cross_asset_confirmation(
        thesis_info.get("thesis", "none"),
        shock_channels,
        rates_pack=rates_pack,
    )

    # Cross-asset coherence matrix — broader, macro-tape read across 6
    # grouped channels (rates, fx, commodities, vol, credit, equities)
    # with a coherence score and explicit thesis_rejection / tension
    # flags.  Reads straight from the tape; does not depend on the
    # shock_decomposition internal channel set.
    coherence_matrix = compute_cross_asset_coherence(
        thesis_info.get("thesis", "none"),
        rates_context=rates_context,
        stress_regime=stress_regime,
        snapshots=snapshots,
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
        priced_lead = 0.0

    divergence = _classify_divergence(implied, priced)
    rationale = _rationale(implied, priced, divergence, implied_basis, priced_basis)
    macro_read = _MACRO_READ.get(
        (implied, priced),
        "Reaction-function direction is ambiguous given current inputs.",
    )
    sources = _build_reaction_evidence_sources(
        implied=implied,
        priced=priced,
        mechanism_reads=mechanism_reads,
        rates_context=rates_context,
        stress_regime=stress_regime,
        rates_ok=rates_ok,
        stress_ok=stress_ok,
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
        "mechanism_reads":  mechanism_reads,
        "confirmation_matrix": confirmation_matrix,
        "coherence_matrix": coherence_matrix,
        "priced_lead":      priced_lead,
        "evidence_sources": sources,
        "available":        macro_ok,
        "stale":            not (rates_ok and stress_ok),
    }


# ---------------------------------------------------------------------------
# Evidence-source traceability
# ---------------------------------------------------------------------------

def _build_reaction_evidence_sources(
    *,
    implied: str,
    priced: str,
    mechanism_reads: list[dict],
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    rates_ok: bool,
    stress_ok: bool,
) -> list[dict]:
    """Trace the implied / priced direction back to the fields and
    channels that drove the read.  Pure read — uses only the inputs the
    composer has already consumed.
    """
    try:
        from evidence_sources import make_source
    except Exception:
        return []

    out: list[dict] = []

    # Implied side — the thesis classifier output.  The classifier is a
    # token-driven heuristic, so we tag the source with that limitation
    # so a reader knows the implied direction is text-derived, not
    # structurally proven.
    if implied != "neutral":
        src = make_source(
            source_type="thesis_classifier",
            field_used="real_yield_context.classify_thesis",
            supports_or_contradicts="supports",
            limitation="thesis token-classifier — text heuristic, not structural",
        )
        if src:
            out.append(src)

    # Priced side — one source per channel read that actually fired.
    # Direction is "supports" when the channel verdict aligns with the
    # implied direction, "contradicts" when opposite, "neutral" if the
    # implied side itself was neutral.
    for r in mechanism_reads or []:
        verdict = r.get("verdict")
        if verdict not in ("hawkish", "dovish"):
            continue
        z = float(r.get("z") or 0.0)
        if implied == "neutral":
            direction = "neutral"
        else:
            direction = "supports" if verdict == implied else "contradicts"
        if z < 1.5:
            limitation = f"low z-score ({z:.1f}σ); 5d horizon only"
        else:
            limitation = "5d horizon only"
        src = make_source(
            source_type="market_channel",
            field_used=f"reaction_function.mechanism_reads.{r.get('channel')}",
            supports_or_contradicts=direction,
            limitation=limitation,
        )
        if src:
            out.append(src)

    # Regime label nudge — captures the multi-day context the 5d moves
    # alone don't carry.  Always tagged with a regime-label limitation
    # so the desk knows it's a slot read, not a structural confirmation.
    regime = (rates_context or {}).get("regime")
    if isinstance(regime, str) and regime:
        if regime in ("Real-rate tightening", "Inflation pressure"):
            direction = "supports" if implied == "hawkish" else (
                "contradicts" if implied == "dovish" else "neutral"
            )
        elif regime == "Risk-off / growth scare":
            direction = "supports" if implied == "dovish" else (
                "contradicts" if implied == "hawkish" else "neutral"
            )
        else:
            direction = "neutral"
        src = make_source(
            source_type="regime_signal",
            field_used=f"rates_context.regime={regime}",
            supports_or_contradicts=direction,
            limitation="regime label only — not a tape confirmation",
        )
        if src:
            out.append(src)

    if (stress_regime or {}).get("signals", {}).get("safe_haven_bid"):
        direction = "supports" if implied == "dovish" else (
            "contradicts" if implied == "hawkish" else "neutral"
        )
        src = make_source(
            source_type="regime_signal",
            field_used="stress_regime.signals.safe_haven_bid",
            supports_or_contradicts=direction,
            limitation="binary signal — does not size the move",
        )
        if src:
            out.append(src)

    if not (rates_ok and stress_ok):
        missing = []
        if not rates_ok:
            missing.append("rates_context")
        if not stress_ok:
            missing.append("stress_regime")
        src = make_source(
            source_type="market_channel",
            field_used="reaction_function.macro_inputs",
            supports_or_contradicts="neutral",
            limitation=f"macro inputs unavailable: {', '.join(missing)}",
        )
        if src:
            out.append(src)

    return out

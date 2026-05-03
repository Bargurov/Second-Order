"""
sector_rotation.py

Deterministic macro → sector rotation map.

Why this module
---------------
The existing post-market overlays describe macro channels (rates,
breakevens, credit, FX, commodities, funding stress) and validate
individual tickers (``market_tickers`` + ``sector_passthrough``), but
they don't produce a single SECTOR-LEVEL read saying "these macro
moves favour Energy + Financials over Utilities + REITs".  That's the
gap a macro desk actually trades off.

This composer resolves that gap with a DETERMINISTIC playbook:

  1. Each macro channel (rates_up, breakevens_up, credit_widening, …)
     has an explicit per-sector weight table plus a direct / second-
     order tag documenting the transmission path.
  2. Channel intensities are normalised from raw moves (e.g. a +0.25pp
     10Y shift = intensity 1.0, +0.50pp = 2.0, capped at 3.0) so the
     scoring scales with the magnitude.
  3. Per-sector net_score = Σ(playbook_weight × channel_intensity),
     and the sign + magnitude determine winner / loser / neutral.
  4. The broad-market tilt (risk_on / risk_off / mixed / neutral) is
     computed INDEPENDENTLY from the stress-mode channels so the
     caller can separate "market is risk-off" from "within risk-off,
     defensives are outperforming cyclicals".

Pure composer.  No I/O.  Never raises.  All inputs optional; missing
inputs degrade to ``available=False`` on the sectors that depend on
them rather than producing random zero-scores.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Sector registry — compact institutional list mapped to liquid ETFs.
# Labels are the names shown in the UI; symbols match the ETF universe
# already used elsewhere in the codebase (sector_passthrough, market_universe).
# ---------------------------------------------------------------------------

SECTORS: tuple[tuple[str, str], ...] = (
    ("XLE",  "Energy"),
    ("XLB",  "Materials"),
    ("XLF",  "Financials"),
    ("KRE",  "Regional Banks"),
    ("XLU",  "Utilities"),
    ("XLRE", "Real Estate"),
    ("XLI",  "Industrials"),
    ("XLY",  "Consumer Discretionary"),
    ("XLP",  "Consumer Staples"),
    ("XLV",  "Healthcare"),
    ("XLK",  "Technology"),
    ("XLC",  "Communications"),
)

_SECTOR_LABELS: dict[str, str] = dict(SECTORS)


# ---------------------------------------------------------------------------
# Channel intensity normalisers — one-sigma-ish move = intensity 1.0.
# Capped at INTENSITY_CAP so a tail-event print doesn't swamp the score.
# ---------------------------------------------------------------------------

_INTENSITY_CAP: float = 3.0


def _intensity(move: Optional[float], one_sigma: float) -> float:
    """Normalise a raw move to a capped intensity in [-cap, +cap]."""
    if move is None or one_sigma <= 0:
        return 0.0
    try:
        val = float(move) / one_sigma
    except (TypeError, ValueError):
        return 0.0
    if val > _INTENSITY_CAP:
        return _INTENSITY_CAP
    if val < -_INTENSITY_CAP:
        return -_INTENSITY_CAP
    return val


# ---------------------------------------------------------------------------
# Playbook — per-channel per-sector weight tables.
# Each entry is ``(weight, tag)`` where tag is "direct" or "second_order"
# and weight is the per-unit-intensity contribution to the sector score.
#
# Sign convention: positive weight = channel BENEFITS the sector when the
# channel intensity is positive.  Negative channel intensities (e.g.
# rates_down, dollar_weak) flip the contribution sign automatically.
# ---------------------------------------------------------------------------

# Weight units: each +1 intensity move adds/subtracts this much score.
# Score threshold bands below are calibrated so a typical broad tape
# produces clearly-ranked winners/losers without overfitting to any
# single channel.

_PLAYBOOK: dict[str, dict[str, tuple[float, str]]] = {
    # ---------- RATES (10Y nominal 5d move; one_sigma = 0.25 pp) -----
    "rates": {
        "XLF":  (+1.0, "direct"),        # higher rates lift NIM
        "KRE":  (+0.6, "direct"),        # regional banks likewise but funding-sensitive
        "XLU":  (-1.2, "direct"),        # classic duration loser
        "XLRE": (-1.5, "direct"),        # duration + borrowing cost stack
        "XLK":  (-0.8, "second_order"),  # long-duration valuations
        "XLC":  (-0.4, "second_order"),  # mega-cap communications tilt long duration
        "XLY":  (-0.4, "second_order"),  # consumer credit sensitivity
        "XLI":  (+0.2, "direct"),        # modest positive (cycle-dependent)
        "XLE":  (+0.2, "direct"),        # rate pressure helps inflationary story
    },
    # ---------- BREAKEVENS (breakeven 5d pp; one_sigma = 0.15 pp) ----
    "breakevens": {
        "XLE":  (+0.8, "direct"),
        "XLB":  (+0.8, "direct"),
        "XLF":  (+0.4, "second_order"),  # steeper curve
        "XLP":  (-0.6, "second_order"),  # margin squeeze from input-cost rise
        "XLY":  (-0.4, "second_order"),  # demand pressure under inflation
        "XLRE": (-0.3, "second_order"),
    },
    # ---------- CREDIT WIDENING (HYG 5d %; one_sigma = 1.0%) ---------
    # Sign convention: channel intensity is POSITIVE when credit is
    # WIDENING (HYG negative).  Playbook weights read accordingly.
    "credit_widening": {
        "KRE":  (-1.5, "direct"),        # funding + credit losses
        "XLF":  (-0.6, "second_order"),  # large-cap banks less exposed
        "XLY":  (-0.8, "second_order"),  # credit-dependent consumption
        "XLI":  (-0.5, "second_order"),  # capex pullback
        "XLP":  (+0.5, "direct"),        # flight-to-defensives
        "XLV":  (+0.5, "direct"),
        "XLU":  (+0.3, "direct"),
    },
    # ---------- DOLLAR (DXY 5d %; one_sigma = 1.0%) ------------------
    # Positive intensity = dollar STRONG.
    "dollar": {
        "XLB":  (-0.8, "direct"),        # commodities priced in USD
        "XLE":  (-0.5, "direct"),
        "XLK":  (-0.4, "second_order"),  # multinational revenue translation
        "XLC":  (-0.4, "second_order"),
        "XLY":  (+0.2, "second_order"),  # domestic consumers benefit mildly
        "XLP":  (+0.1, "direct"),
    },
    # ---------- CRUDE (WTI 5d %; one_sigma = 5%) ---------------------
    "crude": {
        "XLE":  (+1.5, "direct"),
        "XLB":  (+0.3, "second_order"),
        "XLI":  (-0.5, "second_order"),  # transport + airline cost pressure
        "XLY":  (-0.7, "second_order"),  # gas prices hit discretionary spend
        "XLP":  (-0.2, "second_order"),  # input cost
    },
    # ---------- METALS / GOLD (gold 5d %; one_sigma = 3%) ------------
    "metals": {
        "XLB":  (+1.0, "direct"),
        "XLE":  (+0.3, "second_order"),
    },
}


# Funding-stress modes emit a FIXED contribution pattern independent of
# a continuous intensity — they're discrete regime signals.  Severity
# determines the intensity multiplier (mild=0.5, elevated=1.0, acute=1.5).
_FUNDING_MODE_PLAYBOOK: dict[str, dict[str, tuple[float, str]]] = {
    "liquidity_squeeze": {
        "XLP":  (+0.6, "direct"),        # defensives bid
        "XLU":  (+0.4, "direct"),
        "XLV":  (+0.5, "direct"),
        "XLK":  (-0.8, "second_order"),  # high-beta tech pressured
        "XLC":  (-0.5, "second_order"),
        "XLY":  (-0.6, "second_order"),
        "KRE":  (-0.8, "direct"),        # small / regional funding-sensitive
    },
    "dollar_shortage": {
        # Separate from the continuous DXY channel — flags the explicit
        # funding-squeeze signature rather than an FX move.
        "XLB":  (-0.4, "direct"),
        "XLE":  (-0.3, "second_order"),
        "KRE":  (-0.4, "second_order"),
        "XLP":  (+0.2, "direct"),
    },
}

_FUNDING_SEVERITY_INTENSITY: dict[str, float] = {
    "mild":     0.5,
    "elevated": 1.0,
    "acute":    1.5,
    "none":     0.0,
}


# One-sigma constants documented next to each playbook section.
_ONE_SIGMA: dict[str, float] = {
    "rates":            0.25,
    "breakevens":       0.15,
    "credit_widening":  1.0,
    "dollar":           1.0,
    "crude":            5.0,
    "metals":           3.0,
}


# ---------------------------------------------------------------------------
# Score → direction label bands.  Tuned so a single one-sigma channel on a
# highly-exposed sector clears "winner"; multi-channel alignment clears
# "strong winner" via higher magnitude.
# ---------------------------------------------------------------------------

_WINNER_FLOOR: float = 0.5
_NEUTRAL_BAND: float = 0.5   # |score| < this → neutral


def _direction_for(score: float) -> str:
    if score >= _WINNER_FLOOR:
        return "winner"
    if score <= -_WINNER_FLOOR:
        return "loser"
    return "neutral"


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


def _apply_channel(
    channel_key: str,
    intensity: float,
    sector_scores: dict[str, float],
    sector_breakdown: dict[str, list[dict]],
) -> list[str]:
    """Add a channel's contributions to the running per-sector scores.

    Returns the list of sector symbols that received a non-zero weight
    from this channel, for the broad-market-tilt aggregation.
    """
    if abs(intensity) < 1e-9:
        return []
    book = _PLAYBOOK.get(channel_key, {})
    touched: list[str] = []
    for sym, (weight, tag) in book.items():
        contribution = round(weight * intensity, 3)
        if abs(contribution) < 1e-9:
            continue
        sector_scores[sym] = sector_scores.get(sym, 0.0) + contribution
        sector_breakdown.setdefault(sym, []).append({
            "channel":   channel_key,
            "weight":    contribution,
            "tag":       tag,
            "intensity": round(intensity, 3),
        })
        touched.append(sym)
    return touched


def _apply_funding_mode(
    mode: str,
    severity: str,
    sector_scores: dict[str, float],
    sector_breakdown: dict[str, list[dict]],
) -> None:
    mult = _FUNDING_SEVERITY_INTENSITY.get(severity, 0.0)
    if mult <= 0:
        return
    book = _FUNDING_MODE_PLAYBOOK.get(mode)
    if not book:
        return
    for sym, (weight, tag) in book.items():
        contribution = round(weight * mult, 3)
        if abs(contribution) < 1e-9:
            continue
        sector_scores[sym] = sector_scores.get(sym, 0.0) + contribution
        sector_breakdown.setdefault(sym, []).append({
            "channel":   f"funding_{mode}",
            "weight":    contribution,
            "tag":       tag,
            "intensity": round(mult, 3),
        })


# ---------------------------------------------------------------------------
# Broad-market tilt computation
# ---------------------------------------------------------------------------

def _broad_market_tilt(
    rates_intensity: float,
    credit_widening_intensity: float,
    dollar_intensity: float,
    funding_mode: Optional[dict],
) -> tuple[str, list[str]]:
    """Classify the overall macro tape into a risk-on / risk-off tilt.

    This is deliberately SEPARATE from the per-sector scoring so the
    caller can say "the tape is risk-off but defensives are still
    underperforming" — the relative-advantage signal is not drowned
    by the broad tilt.
    """
    risk_off_points = 0.0
    risk_on_points = 0.0
    drivers: list[str] = []

    # Credit widening is the cleanest risk-off signal.
    if credit_widening_intensity > 0.5:
        risk_off_points += credit_widening_intensity
        drivers.append(f"credit widening (intensity {credit_widening_intensity:.1f})")
    elif credit_widening_intensity < -0.5:
        risk_on_points += abs(credit_widening_intensity)
        drivers.append(f"credit tightening (intensity {abs(credit_widening_intensity):.1f})")

    # Dollar strength under funding stress is risk-off; pure export-
    # competitiveness weak dollar tends to be risk-on.
    if dollar_intensity > 1.0:
        risk_off_points += 0.5 * dollar_intensity
        drivers.append(f"broad DXY strength")

    # Rates move interpretation: up-in-yield without credit widening is
    # usually risk-on (growth repricing), with credit widening it's
    # risk-off (rates + spreads = pain).  Down-in-yield with credit
    # widening is flight-to-quality = risk-off.
    if rates_intensity > 1.0 and credit_widening_intensity > 0.3:
        risk_off_points += 0.5
        drivers.append("rates up + credit widening stack")
    elif rates_intensity < -1.0 and credit_widening_intensity > 0.3:
        risk_off_points += 0.8
        drivers.append("flight-to-quality (rates down, credit wide)")

    # Funding-mode inputs trump everything when they fire acute.
    if funding_mode and funding_mode.get("composite_severity") in ("elevated", "acute"):
        primary = funding_mode.get("primary_mode", "")
        if primary in ("credit_widening", "liquidity_squeeze", "dollar_shortage"):
            risk_off_points += 1.5
            drivers.append(f"{primary} {funding_mode['composite_severity']}")

    if risk_off_points > risk_on_points + 0.5:
        tilt = "risk_off"
    elif risk_on_points > risk_off_points + 0.5:
        tilt = "risk_on"
    elif risk_off_points > 0 and risk_on_points > 0:
        tilt = "mixed"
    else:
        tilt = "neutral"
    return tilt, drivers


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_sector_rotation(
    *,
    rates_5d_pp:       Optional[float] = None,
    breakeven_5d_pp:   Optional[float] = None,
    credit_regime:     Optional[dict]  = None,
    dxy_5d_pct:        Optional[float] = None,
    crude_5d_pct:      Optional[float] = None,
    gold_5d_pct:       Optional[float] = None,
    funding_stress_mode: Optional[dict] = None,
) -> dict[str, Any]:
    """Build the macro → sector rotation map.

    Every input is optional; channels whose inputs are missing simply
    don't contribute to scores.  ``available=False`` when NO channel
    has usable input — the engine distinguishes "nothing to rotate on"
    from "we couldn't look at the tape".

    Returned shape::

        {
          "available":            bool,
          "broad_market_tilt":    "risk_on"|"risk_off"|"mixed"|"neutral",
          "broad_market_drivers": [str, ...],
          "sectors": [
            {
              "symbol":                str,
              "label":                 str,
              "net_score":             float,
              "direction":             "winner"|"loser"|"neutral",
              "confidence":            "low"|"medium"|"high",
              "channels_direct":       [{channel, weight, intensity}, ...],
              "channels_second_order": [{channel, weight, intensity}, ...],
              "rationale":             str,
            },
            ...
          ],
          "winners": {"direct": [sym, ...], "second_order": [sym, ...]},
          "losers":  {"direct": [sym, ...], "second_order": [sym, ...]},
          "rationale": str,
        }
    """
    sector_scores: dict[str, float] = {sym: 0.0 for sym, _ in SECTORS}
    sector_breakdown: dict[str, list[dict]] = {sym: [] for sym, _ in SECTORS}

    # --- Channel intensity normalisation ---------------------------------
    rates_int        = _intensity(_f(rates_5d_pp),        _ONE_SIGMA["rates"])
    breakevens_int   = _intensity(_f(breakeven_5d_pp),    _ONE_SIGMA["breakevens"])
    dollar_int       = _intensity(_f(dxy_5d_pct),         _ONE_SIGMA["dollar"])
    crude_int        = _intensity(_f(crude_5d_pct),       _ONE_SIGMA["crude"])
    metals_int       = _intensity(_f(gold_5d_pct),        _ONE_SIGMA["metals"])

    # Credit widening is derived from the credit_regime block.  HYG raw
    # move lives inside stress_regime.raw.hyg_5d; callers that already
    # have stress_regime can forward the credit_regime dict which
    # carries the HY-IG differential + classified regime.
    credit_widening_int = 0.0
    if isinstance(credit_regime, dict):
        hy = _f(credit_regime.get("hy_5d"))
        if hy is not None:
            # Sign flip: HY dropping 1%+ = credit widening intensity positive.
            credit_widening_int = _intensity(-hy, _ONE_SIGMA["credit_widening"])
        regime_label = (credit_regime.get("regime") or "").lower()
        if regime_label == "default_risk_widening" and credit_widening_int < 1.0:
            credit_widening_int = max(credit_widening_int, 1.0)
        elif regime_label in ("risk_on", "default_risk_tightening") and credit_widening_int > -1.0:
            credit_widening_int = min(credit_widening_int, -1.0)

    # --- Apply each channel ---------------------------------------------
    touched_any = False
    for key, intensity in (
        ("rates",           rates_int),
        ("breakevens",      breakevens_int),
        ("credit_widening", credit_widening_int),
        ("dollar",          dollar_int),
        ("crude",           crude_int),
        ("metals",          metals_int),
    ):
        touched = _apply_channel(key, intensity, sector_scores, sector_breakdown)
        if touched:
            touched_any = True

    # --- Apply funding-mode contributions --------------------------------
    if isinstance(funding_stress_mode, dict):
        for mode_name in ("liquidity_squeeze", "dollar_shortage"):
            mode = (funding_stress_mode.get("modes") or {}).get(mode_name) or {}
            severity = mode.get("severity", "none")
            if severity != "none":
                _apply_funding_mode(
                    mode_name, severity, sector_scores, sector_breakdown,
                )
                touched_any = True

    # --- Broad-market tilt ------------------------------------------------
    tilt, tilt_drivers = _broad_market_tilt(
        rates_int, credit_widening_int, dollar_int, funding_stress_mode,
    )

    # --- Assemble per-sector output --------------------------------------
    sectors_out: list[dict] = []
    for sym, label in SECTORS:
        score = round(sector_scores.get(sym, 0.0), 3)
        breakdown = sector_breakdown.get(sym, [])
        direct = [b for b in breakdown if b["tag"] == "direct"]
        second = [b for b in breakdown if b["tag"] == "second_order"]

        # Confidence: based on channel count + magnitude.
        channel_count = len(breakdown)
        if abs(score) >= 1.5 and channel_count >= 2:
            confidence = "high"
        elif abs(score) >= 0.8 and channel_count >= 1:
            confidence = "medium"
        elif channel_count >= 1:
            confidence = "low"
        else:
            confidence = "low"

        # Rationale string.
        if not breakdown:
            rationale = "No macro channels firing against this sector."
        else:
            top = sorted(breakdown, key=lambda b: abs(b["weight"]), reverse=True)[:2]
            bits = [
                f"{b['channel']} {'+' if b['weight'] > 0 else ''}{b['weight']}"
                for b in top
            ]
            rationale = f"{_direction_for(score)}; top drivers: {', '.join(bits)}"

        sectors_out.append({
            "symbol":                sym,
            "label":                 label,
            "net_score":             score,
            "direction":             _direction_for(score),
            "confidence":            confidence,
            "channels_direct":       direct,
            "channels_second_order": second,
            "rationale":             rationale,
        })

    # Stable sort for display: winners descending by score, losers
    # ascending by score, neutrals last.
    def _sort_key(s: dict) -> tuple[int, float]:
        d = s["direction"]
        order = {"winner": 0, "loser": 1, "neutral": 2}[d]
        # Within winners: descending score; within losers: ascending score.
        return (order, -s["net_score"] if d == "winner" else s["net_score"])
    sectors_out.sort(key=_sort_key)

    # --- Winners / losers split by direct vs second-order dominance ------
    winners_direct:  list[str] = []
    winners_second:  list[str] = []
    losers_direct:   list[str] = []
    losers_second:   list[str] = []
    for s in sectors_out:
        if s["direction"] == "winner":
            direct_sum = sum(b["weight"] for b in s["channels_direct"])
            second_sum = sum(b["weight"] for b in s["channels_second_order"])
            if direct_sum >= second_sum:
                winners_direct.append(s["symbol"])
            else:
                winners_second.append(s["symbol"])
        elif s["direction"] == "loser":
            direct_sum = sum(b["weight"] for b in s["channels_direct"])
            second_sum = sum(b["weight"] for b in s["channels_second_order"])
            if direct_sum <= second_sum:
                losers_direct.append(s["symbol"])
            else:
                losers_second.append(s["symbol"])

    # Top-level rationale.
    winner_labels = [_SECTOR_LABELS[w] for w in (winners_direct + winners_second)[:3]]
    loser_labels  = [_SECTOR_LABELS[l] for l in (losers_direct + losers_second)[:3]]
    bits: list[str] = []
    if winner_labels:
        bits.append(f"Winners: {', '.join(winner_labels)}")
    if loser_labels:
        bits.append(f"Losers: {', '.join(loser_labels)}")
    if not bits:
        bits.append("No sector rotation detected on current macro inputs")
    rationale = "; ".join(bits) + f" [broad tape: {tilt}]"

    return {
        "available":            touched_any,
        "broad_market_tilt":    tilt,
        "broad_market_drivers": tilt_drivers,
        "sectors":              sectors_out,
        "winners": {"direct": winners_direct, "second_order": winners_second},
        "losers":  {"direct": losers_direct,  "second_order": losers_second},
        "rationale":            rationale,
    }

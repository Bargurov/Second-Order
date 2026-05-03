"""
shock_decomposition.py

Real vs Nominal shock decomposition.

Given the live macro state (rates_context + stress_regime + optional
snapshots), classify which transmission channel is doing the work:

    nominal_yield  — nominal rates (10Y, ^TNX move)
    real_yield     — real rates (TIP move, sign-inverted)
    breakeven      — breakeven inflation (nominal − real proxy)
    fx             — dollar / DXY
    commodity      — gold + crude composite

Returns a compact block with primary driver, secondary drivers, the
short empirical rationale, what it implies for the macro read, and the
key liquid markets that should confirm or challenge it.

Design
------
- Pure composer.  Takes pre-fetched dicts; performs no I/O.
- Channels are normalized via institutional 1-sigma 5d move scales so
  magnitudes can be compared apples-to-apples (yields in %, prices in %).
- Highest normalized magnitude = primary; others above the secondary
  threshold are listed in score order.
- This is a *macro state* read — not driven by event keywords.  The same
  macro state is the same decomposition no matter what headline shipped.
- When no macro inputs are usable, returns the block with
  ``available=False, stale=True`` and an empty channel set so the UI
  can render a degraded "macro unavailable" pill.
- When macro is usable but every channel is below the noise floor,
  returns ``primary="none"`` so the UI can show "no clear shock today".
- Returns ``{}`` only when there is literally no data of any kind.
"""

from __future__ import annotations

from typing import Optional

from benchmark_quarantine import (
    _HARD_FAIL_REASONS,
    channel_quality_block,
    compute_benchmark_quarantine,
)
from cross_rate_fx import compute_cross_rate_fx


# Channel → representative benchmark ticker used for quarantine lookups.
# Nominal/real/breakeven use the 10Y tape since their moves are derived
# from it; FX and commodity-composite channels use the lead price ticker
# (DXY / CL / GLD).  Credit is a composite so it's skipped (None) —
# quarantine lives on the underlying HYG / LQD prints themselves, which
# run through cross_asset_coherence.
_CHANNEL_BENCHMARK_TICKER: dict[str, str] = {
    "nominal_yield": "10Y",
    "real_yield":    "TIP",
    "breakeven":     "10Y",
    "fx":            "DXY",
    "commodity":     "CL",
}


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------

CHANNEL_IDS: tuple[str, ...] = (
    "nominal_yield",
    "real_yield",
    "breakeven",
    "fx",
    "commodity",
    "credit",
)

_CHANNEL_LABELS: dict[str, str] = {
    "nominal_yield": "Nominal yields",
    "real_yield":    "Real yields",
    "breakeven":     "Breakeven inflation",
    "fx":            "Dollar / FX",
    "commodity":     "Commodities",
    "credit":        "Credit spreads",
}

# Institutional 1-sigma 5d move scales.
#
# Unit conventions (must match compute_rates_context output):
#   nominal_yield — absolute pp change in ^TNX Close
#                   (e.g. 0.20 = 20 bps.  NOT percentage change in yield level.)
#   real_yield    — percentage change in TIP ETF price
#                   (e.g. 0.50 = TIP fell/rose 0.50%)
#   breakeven     — Fisher decomposition proxy (pp):
#                   nominal_pp + TIP_pct / _TIP_DURATION
#                   (same order of magnitude as nominal pp)
#   fx            — percentage change in DXY (DX-Y.NYB or equivalent)
#   commodity     — percentage change in CL (crude) or GC (gold)
#
# A move of ~1.5× the scale starts to feel real; >2.5× is a regime event.
_CHANNEL_SCALE: dict[str, float] = {
    "nominal_yield": 0.20,   # 20 bps absolute change in ^TNX  (pp-unit; same scale as breakeven)
    "real_yield":    0.75,   # 0.75% TIP ETF price move        (5y 1-sigma: 0.776 %)
    "breakeven":     0.20,   # breakeven proxy (pp)            (same pp-unit as nominal_yield)
    "fx":            0.90,   # 0.90% DXY move                  (5y 1-sigma: 0.956 %)
    "commodity":     5.00,   # 5% crude-equivalent move        (5y 1-sigma: 5.347 %)
    "credit":        1.00,   # 1.0 pp HY-vs-Treasury 5d spread (SHY_5d - HYG_5d); +0.5 fires ~20%, +1.0 ~8%
}

# Sanity caps per channel: move_5d values beyond these thresholds are
# artifacts of corrupted price-cache data (stub rows near zero, or
# _safe_pct applied to a near-zero historical yield start point producing
# values like +2680%).  Discard rather than propagate.
#
# Units match _CHANNEL_SCALE above.
_CHANNEL_MOVE_CAPS: dict[str, float] = {
    "nominal_yield": 5.0,    # ±500 bps in 5 days has never been recorded
    "real_yield":    20.0,   # TIP ETF ±20% in 5 days is physically impossible
    "breakeven":     7.0,    # derived proxy; ceiling a bit above nominal
    "fx":            15.0,   # DXY ±15% in 5 days has never happened
    "commodity":     60.0,   # crude can spike hard but not 60%+ in 5 days
    "credit":        10.0,   # HY-vs-Treasury 5d spread ±10pp is GFC-territory tail
}

# Canonical liquid markets to watch per channel.  These are the same
# market IDs the rest of the product already understands.
# Display units per channel — so rationale text and the payload carry the
# correct suffix instead of blanket "%".
_CHANNEL_UNITS: dict[str, str] = {
    "nominal_yield": "pp",   # absolute percentage-point change
    "real_yield":    "%",    # TIP ETF price percentage change
    "breakeven":     "pp",   # composite proxy, same order as nominal
    "fx":            "%",    # DXY percentage change
    "commodity":     "%",    # crude/gold percentage change
    "credit":        "pp",   # HY-vs-Treasury relative spread (SHY_5d − HYG_5d)
}

_CHANNEL_MARKETS: dict[str, list[str]] = {
    "nominal_yield": ["10Y", "2Y", "30Y", "TLT"],
    "real_yield":    ["TIP", "10Y", "TLT", "GC"],
    "breakeven":     ["TIP", "10Y", "GC", "CL"],
    "fx":            ["DXY", "10Y", "GC", "ES"],
    "commodity":     ["CL", "GC", "DXY", "10Y"],
    "credit":        ["HYG", "LQD", "VIX", "SPY"],
}

# Macro-read sentence templates per primary driver.
_MACRO_READ: dict[str, str] = {
    "nominal_yield": (
        "Move is in nominal rates with neither real yields nor breakevens "
        "dominating — duration trades will lead the reaction function."
    ),
    "real_yield": (
        "Real yields are doing the work — risk assets and long-duration "
        "growth equities should feel this most directly."
    ),
    "breakeven": (
        "Inflation expectations are leading — gold, TIPS, and commodity-"
        "linked equities should confirm; nominals matter less than the "
        "breakeven path."
    ),
    "fx": (
        "Dollar channel is dominant — EM equities, FX-sensitive multinationals "
        "and commodity prices will reflect the shock first."
    ),
    "commodity": (
        "Commodity-led shock — passthrough to inflation expectations and "
        "energy/materials equities is the main monitoring axis."
    ),
    "credit": (
        "Credit spreads are doing the work — risk premia are repricing "
        "faster than rates; equity vol and HY-sensitive names will lead "
        "the reaction function."
    ),
    "none": (
        "All channels are below their normal noise band — no single shock "
        "is doing the work; macro is in a quiet state."
    ),
}


# Ranking floor: a channel must clear this normalized magnitude (z-units)
# to qualify as the primary driver.  Below this, primary is "none".
_PRIMARY_FLOOR: float = 0.8

# Secondary threshold: channels above this normalized magnitude are
# listed alongside the primary.
_SECONDARY_FLOOR: float = 0.6


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


def _safe_move(cid: str, move: Optional[float]) -> Optional[float]:
    """Return move if within the sanity cap for this channel, else None.

    Prevents corrupted price-cache values (e.g. +2680% from near-zero
    historical ^TNX rows) from reaching the z-score ranking.
    """
    if move is None:
        return None
    cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
    return move if abs(move) <= cap else None


def _rates_usable(rates_context: Optional[dict]) -> bool:
    if not rates_context or not isinstance(rates_context, dict):
        return False
    nom = (rates_context.get("nominal") or {}).get("change_5d")
    real = (rates_context.get("real_proxy") or {}).get("change_5d")
    return nom is not None or real is not None


# ---------------------------------------------------------------------------
# Rates pack: curve shape
# ---------------------------------------------------------------------------
# SHY ETF tracks 1-3Y Treasuries; effective duration ≈ 1.9y. A 1% price
# move in SHY therefore translates to roughly -0.53 pp in the underlying
# front-end yield (inverse price/yield).  This is a proxy — nothing like
# a clean 2Y futures print — but gives a usable slope-change signal that
# is correct in sign and order-of-magnitude for curve classification.
_SHY_DURATION: float = 1.9

# Noise floor per leg (pp).  A 5d leg-move under this is treated as "flat".
# Empirical: 10Y 1-sigma ≈ 0.13pp, 2Y_proxy 1-sigma ≈ 0.10pp.  0.10pp fires
# the classifier only when at least one leg has meaningfully moved.
_CURVE_LEG_FLOOR: float = 0.10

# Slope-change significance (pp).  Below this, legs move in tandem and we
# call the move "parallel" instead of steepening/flattening.
_CURVE_SLOPE_FLOOR: float = 0.08


def _twoy_change_pp_from_shy(shy_pct_5d: Optional[float]) -> Optional[float]:
    """Convert SHY ETF % price move to an approximate 2Y yield change (pp).

    SHY rises → 2Y yield fell; invert sign and divide by duration.
    """
    if shy_pct_5d is None:
        return None
    return -float(shy_pct_5d) / _SHY_DURATION


def _classify_curve_shape(tenyr_pp: Optional[float], twoy_pp: Optional[float]) -> str:
    """Classify the 2s10s curve move.

    Returns one of:
      bull_steepener, bear_steepener, bull_flattener, bear_flattener,
      parallel_up, parallel_down, flat, unavailable.

    Convention: slope = 10Y - 2Y.  slope rising → steepening.  Bull/bear
    tags the sign of the 10Y leg (bull = rates falling, bear = rising).
    """
    if tenyr_pp is None or twoy_pp is None:
        return "unavailable"

    slope_change = tenyr_pp - twoy_pp

    # Both legs quiet → flat.
    if abs(tenyr_pp) < _CURVE_LEG_FLOOR and abs(twoy_pp) < _CURVE_LEG_FLOOR:
        return "flat"

    # Slope move is within the parallel band → parallel shift.
    if abs(slope_change) < _CURVE_SLOPE_FLOOR:
        if tenyr_pp > 0 or twoy_pp > 0:
            return "parallel_up"
        return "parallel_down"

    steepening = slope_change > 0
    # Direction of the 10Y leg (fallback to 2Y when 10Y is quiet).
    leg_up = tenyr_pp > 0 if abs(tenyr_pp) >= _CURVE_LEG_FLOOR else twoy_pp > 0

    if steepening and leg_up:
        return "bear_steepener"
    if steepening and not leg_up:
        return "bull_steepener"
    if (not steepening) and leg_up:
        return "bear_flattener"
    return "bull_flattener"


def _magnitude_tier(slope_change_pp: Optional[float]) -> str:
    """Classify the size of a slope move.

    ``small`` = within the parallel floor (below the classifier's sensitivity).
    ``medium`` = between the parallel floor and ~2x the leg floor.
    ``large``  = beyond ~2x the leg floor (a meaningful steepener/flattener).
    """
    if slope_change_pp is None:
        return "unavailable"
    mag = abs(slope_change_pp)
    if mag < _CURVE_SLOPE_FLOOR:
        return "small"
    if mag < 2 * _CURVE_LEG_FLOOR:
        return "medium"
    return "large"


# ---------------------------------------------------------------------------
# Long-end curve: 5s30s
# ---------------------------------------------------------------------------
# 5s30s is an independent curve read from 2s10s: a 5Y-30Y steepener can occur
# with a flat 2s10s when term-premium is re-pricing at the long end only
# (classic "long-end-driven" move).  A bull-steepener of the whole curve
# (rates falling, slopes widening across both) reads completely differently.


def _classify_long_curve_shape(
    thirtyyr_pp: Optional[float],
    fiveyr_pp: Optional[float],
) -> str:
    """Classify the 5s30s curve move using the same taxonomy as 2s10s.

    Convention: long_slope = 30Y − 5Y.  long_slope rising → long-end
    steepening.  Bull/bear tags the sign of the 30Y leg.
    """
    if thirtyyr_pp is None or fiveyr_pp is None:
        return "unavailable"

    slope_change = thirtyyr_pp - fiveyr_pp

    if abs(thirtyyr_pp) < _CURVE_LEG_FLOOR and abs(fiveyr_pp) < _CURVE_LEG_FLOOR:
        return "flat"

    if abs(slope_change) < _CURVE_SLOPE_FLOOR:
        if thirtyyr_pp > 0 or fiveyr_pp > 0:
            return "parallel_up"
        return "parallel_down"

    steepening = slope_change > 0
    leg_up = thirtyyr_pp > 0 if abs(thirtyyr_pp) >= _CURVE_LEG_FLOOR else fiveyr_pp > 0

    if steepening and leg_up:
        return "bear_steepener"
    if steepening and not leg_up:
        return "bull_steepener"
    if (not steepening) and leg_up:
        return "bear_flattener"
    return "bull_flattener"


# ---------------------------------------------------------------------------
# Combined regime state — distinguishes level-driven from curve-driven moves
# ---------------------------------------------------------------------------

# Regime-state taxonomy.  Each label is mutually exclusive; the composer picks
# whichever reads most cleanly from the available legs.
_REGIME_STATE_LABELS: dict[str, str] = {
    "parallel_shift_up":           "Parallel shift up (all tenors rising)",
    "parallel_shift_down":         "Parallel shift down (all tenors falling)",
    "bear_steepener_whole":        "Bear steepener (whole curve)",
    "bull_steepener_whole":        "Bull steepener (whole curve)",
    "bear_flattener_whole":        "Bear flattener (whole curve)",
    "bull_flattener_whole":        "Bull flattener (whole curve)",
    "twist_short_steep_long_flat": "Twist — front steepens, long flattens",
    "twist_short_flat_long_steep": "Twist — front flattens, long steepens",
    "short_end_driven":            "Front-end driven (long end quiet)",
    "long_end_driven":             "Long-end driven (front quiet)",
    "mixed":                       "Mixed curve moves",
    "flat_quiet":                  "Quiet — no meaningful move",
    "unavailable":                 "Curve inputs unavailable",
}


def _classify_regime_state(
    twoy_pp: Optional[float],
    tenyr_pp: Optional[float],
    fiveyr_pp: Optional[float],
    thirtyyr_pp: Optional[float],
) -> str:
    """Combined 2s10s + 5s30s regime read.

    Returns a label from ``_REGIME_STATE_LABELS`` that distinguishes
    curve-driven moves (steepener/flattener/twist), level-driven moves
    (parallel shifts), and partial moves (one section of the curve only).
    """
    short_avail = twoy_pp is not None and tenyr_pp is not None
    long_avail  = thirtyyr_pp is not None and fiveyr_pp is not None

    if not short_avail and not long_avail:
        return "unavailable"

    legs = [v for v in (twoy_pp, tenyr_pp, fiveyr_pp, thirtyyr_pp) if v is not None]
    max_leg = max((abs(v) for v in legs), default=0.0)
    if max_leg < _CURVE_LEG_FLOOR:
        return "flat_quiet"

    # Only one section of the curve available — degrade gracefully.
    if short_avail and not long_avail:
        short_slope = tenyr_pp - twoy_pp
        if abs(short_slope) < _CURVE_SLOPE_FLOOR:
            return "parallel_shift_up" if tenyr_pp > 0 else "parallel_shift_down"
        return "short_end_driven"
    if long_avail and not short_avail:
        long_slope = thirtyyr_pp - fiveyr_pp
        if abs(long_slope) < _CURVE_SLOPE_FLOOR:
            return "parallel_shift_up" if thirtyyr_pp > 0 else "parallel_shift_down"
        return "long_end_driven"

    # Both sections available.
    short_slope = tenyr_pp - twoy_pp
    long_slope  = thirtyyr_pp - fiveyr_pp

    short_steep = short_slope > _CURVE_SLOPE_FLOOR
    short_flat  = short_slope < -_CURVE_SLOPE_FLOOR
    long_steep  = long_slope > _CURVE_SLOPE_FLOOR
    long_flat   = long_slope < -_CURVE_SLOPE_FLOOR
    short_quiet = not short_steep and not short_flat
    long_quiet  = not long_steep and not long_flat

    # Parallel shift — both sections quiet but at least one leg moved.
    if short_quiet and long_quiet:
        signs = [v > 0 for v in legs]
        if all(signs):
            return "parallel_shift_up"
        if not any(signs):
            return "parallel_shift_down"
        return "mixed"

    # Twist — short and long move in opposite directions beyond the floor.
    if short_steep and long_flat:
        return "twist_short_steep_long_flat"
    if short_flat and long_steep:
        return "twist_short_flat_long_steep"

    # Whole-curve moves — both sections agree on direction.
    if short_steep and long_steep:
        return "bear_steepener_whole" if tenyr_pp > 0 else "bull_steepener_whole"
    if short_flat and long_flat:
        return "bear_flattener_whole" if tenyr_pp > 0 else "bull_flattener_whole"

    # One section moving, the other quiet.
    if short_quiet and not long_quiet:
        return "long_end_driven"
    if long_quiet and not short_quiet:
        return "short_end_driven"

    return "mixed"


def _regime_class(regime_state: str) -> str:
    """Summary class: level_move vs curve_move vs partial vs quiet.

    Gives consumers a coarse read without branching over the full taxonomy.
    """
    if regime_state in ("parallel_shift_up", "parallel_shift_down"):
        return "level_move"
    if regime_state in (
        "bear_steepener_whole", "bull_steepener_whole",
        "bear_flattener_whole", "bull_flattener_whole",
        "twist_short_steep_long_flat", "twist_short_flat_long_steep",
    ):
        return "curve_move"
    if regime_state in ("short_end_driven", "long_end_driven"):
        return "partial"
    if regime_state in ("flat_quiet", "unavailable"):
        return regime_state
    return "mixed"


def _leg_driver(tenyr_pp: Optional[float], twoy_pp: Optional[float]) -> str:
    """Attribute the curve move to the leg that moved more.

    Useful because a 20bp steepening from the 10Y alone has a different
    transmission read (term-premium reset, long-duration selling) than a
    20bp steepening from a 2Y rally alone (cut priced in).
    """
    if tenyr_pp is None or twoy_pp is None:
        return "unavailable"
    if abs(tenyr_pp) < _CURVE_LEG_FLOOR and abs(twoy_pp) < _CURVE_LEG_FLOOR:
        return "flat"
    # If one leg dominates by >= 1.5x the other, attribute to it.
    if abs(tenyr_pp) >= 1.5 * abs(twoy_pp) and abs(tenyr_pp) >= _CURVE_LEG_FLOOR:
        return "long_end"
    if abs(twoy_pp) >= 1.5 * abs(tenyr_pp) and abs(twoy_pp) >= _CURVE_LEG_FLOOR:
        return "short_end"
    return "both"


def _build_rates_pack(
    tenyr_pp: Optional[float],
    shy_pct_5d: Optional[float],
    fiveyr_pp: Optional[float] = None,
    thirtyyr_pp: Optional[float] = None,
) -> dict:
    """Compose the rates pack: 2s10s + 5s30s + combined regime-state read.

    Short-end fields (2s10s, derived from 10Y and SHY-implied 2Y):
      - tenyr_5d_pp, twoy_5d_pp, slope_5d_pp
      - curve_shape            : bull/bear steepener/flattener label
      - parallel_component_pp  : average of legs (pure parallel shift portion)
      - twist_component_pp     : half of slope_5d (rotation-only portion)
      - driver                 : "long_end" | "short_end" | "both" | "flat"
      - magnitude_tier         : "small" | "medium" | "large"

    Long-end fields (5s30s, derived from 5Y and 30Y yields):
      - fiveyr_5d_pp, thirtyyr_5d_pp, long_slope_5d_pp
      - long_curve_shape       : same taxonomy as curve_shape
      - long_magnitude_tier    : size classification for the 5s30s slope move

    Combined read:
      - regime_state           : detailed label across both sections of the curve
      - regime_state_label     : human-readable version of regime_state
      - regime_class           : "level_move" | "curve_move" | "partial" | "flat_quiet"

    Always returns a dict; fields are None when inputs are missing so the
    payload shape is stable.
    """
    twoy_pp = _twoy_change_pp_from_shy(shy_pct_5d)

    slope_5d = None
    parallel_component = None
    twist_component = None
    if tenyr_pp is not None and twoy_pp is not None:
        slope_5d = tenyr_pp - twoy_pp
        parallel_component = (tenyr_pp + twoy_pp) / 2.0
        twist_component = slope_5d / 2.0

    long_slope_5d = None
    long_parallel_component = None
    long_twist_component = None
    if fiveyr_pp is not None and thirtyyr_pp is not None:
        long_slope_5d = thirtyyr_pp - fiveyr_pp
        long_parallel_component = (fiveyr_pp + thirtyyr_pp) / 2.0
        long_twist_component = long_slope_5d / 2.0

    regime_state = _classify_regime_state(twoy_pp, tenyr_pp, fiveyr_pp, thirtyyr_pp)

    return {
        # 2s10s leg
        "tenyr_5d_pp":           round(tenyr_pp, 3) if tenyr_pp is not None else None,
        "twoy_5d_pp":            round(twoy_pp, 3)  if twoy_pp  is not None else None,
        "slope_5d_pp":           round(slope_5d, 3) if slope_5d is not None else None,
        "curve_shape":           _classify_curve_shape(tenyr_pp, twoy_pp),
        "parallel_component_pp": round(parallel_component, 3) if parallel_component is not None else None,
        "twist_component_pp":    round(twist_component, 3)    if twist_component is not None else None,
        "driver":                _leg_driver(tenyr_pp, twoy_pp),
        "magnitude_tier":        _magnitude_tier(slope_5d),
        # 5s30s leg
        "fiveyr_5d_pp":                  round(fiveyr_pp, 3) if fiveyr_pp is not None else None,
        "thirtyyr_5d_pp":                round(thirtyyr_pp, 3) if thirtyyr_pp is not None else None,
        "long_slope_5d_pp":              round(long_slope_5d, 3) if long_slope_5d is not None else None,
        "long_curve_shape":              _classify_long_curve_shape(thirtyyr_pp, fiveyr_pp),
        "long_parallel_component_pp":    round(long_parallel_component, 3) if long_parallel_component is not None else None,
        "long_twist_component_pp":       round(long_twist_component, 3) if long_twist_component is not None else None,
        "long_magnitude_tier":           _magnitude_tier(long_slope_5d),
        # Combined read
        "regime_state":       regime_state,
        "regime_state_label": _REGIME_STATE_LABELS.get(regime_state, regime_state),
        "regime_class":       _regime_class(regime_state),
        "available":          tenyr_pp is not None and twoy_pp is not None,
    }


def _stress_credit_spread(stress_regime: Optional[dict]) -> Optional[float]:
    """Return the 5d credit-spread proxy (SHY_5d − HYG_5d, pp).

    Positive = high-yield underperforming Treasuries (widening).
    Reads from stress_regime detail first, then raw.
    """
    if not stress_regime or not isinstance(stress_regime, dict):
        return None
    detail = stress_regime.get("detail") or {}
    credit = detail.get("credit") or {}
    spread = credit.get("spread_5d")
    if spread is None:
        spread = (stress_regime.get("raw") or {}).get("credit_spread_5d")
    return _f(spread)


def _stress_shy_5d(stress_regime: Optional[dict]) -> Optional[float]:
    """Return SHY ETF 5d % change from stress_regime.raw (if exposed)."""
    if not stress_regime or not isinstance(stress_regime, dict):
        return None
    return _f((stress_regime.get("raw") or {}).get("shy_5d"))


def _stress_haven_assets(stress_regime: Optional[dict]) -> dict:
    """Return the safe-haven asset 5d returns dict from stress_regime.

    Stress regime exposes Gold/Dollar/Long Bonds 5d under
    ``detail.safe_haven.assets``.  Empty dict when unavailable.
    """
    if not stress_regime or not isinstance(stress_regime, dict):
        return {}
    detail = stress_regime.get("detail") or {}
    safe = detail.get("safe_haven") or {}
    assets = safe.get("assets") or {}
    return assets if isinstance(assets, dict) else {}


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
# Channel extraction
# ---------------------------------------------------------------------------

def _extract_channels(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> dict[str, dict]:
    """Pull each channel's 5d move from the supplied macro inputs.

    Returns {channel_id: {label, move_5d, available, scale}} for every
    channel id (channels with no data are still present with
    ``available=False`` so the UI never KeyErrors).
    """
    out: dict[str, dict] = {
        cid: {
            "label":     _CHANNEL_LABELS[cid],
            "move_5d":   None,
            "available": False,
            "scale":     _CHANNEL_SCALE[cid],
        }
        for cid in CHANNEL_IDS
    }

    rc = rates_context or {}
    nom_5d = _safe_move("nominal_yield", _f((rc.get("nominal") or {}).get("change_5d")))
    real_5d = _safe_move("real_yield", _f((rc.get("real_proxy") or {}).get("change_5d")))
    be_5d = _safe_move("breakeven", _f((rc.get("breakeven_proxy") or {}).get("change_5d")))

    if nom_5d is not None:
        out["nominal_yield"]["move_5d"] = nom_5d
        out["nominal_yield"]["available"] = True
    if real_5d is not None:
        out["real_yield"]["move_5d"] = real_5d
        out["real_yield"]["available"] = True
    if be_5d is not None:
        out["breakeven"]["move_5d"] = be_5d
        out["breakeven"]["available"] = True

    # FX: prefer snapshot DXY, fall back to safe-haven Dollar.
    dxy_5d = _safe_move("fx", _snap_change_5d(snapshots, "DXY"))
    if dxy_5d is None:
        haven = _stress_haven_assets(stress_regime)
        dxy_5d = _safe_move("fx", _f(haven.get("Dollar")))
    if dxy_5d is not None:
        out["fx"]["move_5d"] = dxy_5d
        out["fx"]["available"] = True

    # Commodities: composite of crude + gold (whichever is moving more,
    # measured against its own scale).  This avoids the equal-weight bias
    # that would let small gold moves outweigh big crude moves.
    cl_5d = _safe_move("commodity", _snap_change_5d(snapshots, "CL"))
    gc_5d = _safe_move("commodity", _snap_change_5d(snapshots, "GC"))
    if gc_5d is None:
        haven = _stress_haven_assets(stress_regime)
        gc_5d = _safe_move("commodity", _f(haven.get("Gold")))

    # Credit: prefer snapshot HYG/LQD/SHY, fall back to stress_regime
    # detail.credit.spread_5d (SHY_5d − HYG_5d).  Sign convention: positive
    # value = widening (HY underperforming Treasuries / safe credit).
    credit_5d: Optional[float] = None
    hyg_snap = _snap_change_5d(snapshots, "HYG")
    lqd_snap = _snap_change_5d(snapshots, "LQD")
    shy_snap = _snap_change_5d(snapshots, "SHY")
    if hyg_snap is not None and (lqd_snap is not None or shy_snap is not None):
        # LQD is a cleaner duration-matched reference; prefer it when present.
        ref = lqd_snap if lqd_snap is not None else shy_snap
        credit_5d = _safe_move("credit", ref - hyg_snap)
    if credit_5d is None:
        credit_5d = _safe_move("credit", _stress_credit_spread(stress_regime))
    if credit_5d is not None:
        out["credit"]["move_5d"] = credit_5d
        out["credit"]["available"] = True

    cmdty_components: list[tuple[str, float, float]] = []
    if cl_5d is not None:
        cmdty_components.append(("crude", cl_5d, 3.0))
    if gc_5d is not None:
        cmdty_components.append(("gold", gc_5d, 1.5))

    if cmdty_components:
        # Pick the component with the largest normalized magnitude as the
        # representative move.  Stash both raw values for the UI.
        leader = max(cmdty_components, key=lambda c: abs(c[1]) / c[2])
        out["commodity"]["move_5d"] = leader[1]
        out["commodity"]["available"] = True
        out["commodity"]["leader"] = leader[0]
        if cl_5d is not None:
            out["commodity"]["crude_5d"] = cl_5d
        if gc_5d is not None:
            out["commodity"]["gold_5d"] = gc_5d
        # Effective scale matches whichever leg is leading.
        out["commodity"]["scale"] = leader[2]

    return out


# ---------------------------------------------------------------------------
# Benchmark quarantine hook
# ---------------------------------------------------------------------------

def _apply_benchmark_quarantine(
    channels: dict[str, dict],
    snapshots: Optional[list[dict]],
) -> tuple[dict[str, dict], list[dict]]:
    """Score each channel's move through the benchmark quarantine layer.

    Adds ``data_quality`` and ``reasons`` to every channel dict.  When a
    channel is quarantined (hard-fail), zeros out its ``move_5d`` and
    marks it unavailable so downstream ranking / rationale doesn't read
    a corrupt print.  Healthy-path channels ("ok") are unchanged beyond
    the new metadata keys.

    Returns (mutated-channels, list-of-verdicts) so the caller can
    build the top-level ``channel_quality`` block.  The verdict list
    covers only channels that map to a benchmark — the credit channel
    is a composite and skipped.
    """
    verdicts: list[dict] = []
    for cid, ch in channels.items():
        market = _CHANNEL_BENCHMARK_TICKER.get(cid)
        if market is None:
            # No direct benchmark mapping for this channel; still emit a
            # default data_quality so the UI shape is stable.
            ch.setdefault("data_quality", "ok")
            ch.setdefault("reasons", [])
            continue

        # Pull the last price from the snapshot if available so the
        # price_floor guard has something to check against.
        last_price: Optional[float] = None
        if snapshots:
            target = market.upper()
            for s in snapshots:
                if not isinstance(s, dict):
                    continue
                if (s.get("market") or "").upper() == target:
                    last_price = _f(s.get("value"))
                    break

        verdict = compute_benchmark_quarantine(
            market,
            move_5d=ch.get("move_5d"),
            last_price=last_price,
        )
        # The benchmark-quarantine layer applies a stricter per-ticker
        # ``hard_cap`` calibrated for raw ticker prints.  The
        # channel-level ``_CHANNEL_MOVE_CAPS`` is the declared sanity
        # bound for the derived channel move.  A value at or below the
        # channel cap is legitimate by contract — don't let the
        # benchmark layer's stricter hard_cap reject it.
        move_val = ch.get("move_5d")
        channel_cap = _CHANNEL_MOVE_CAPS.get(cid)
        reasons = list(verdict["reasons"])
        data_quality = verdict["data_quality"]
        if (move_val is not None
                and channel_cap is not None
                and abs(float(move_val)) <= channel_cap
                and "hard_bound_violation" in reasons):
            reasons = [r for r in reasons if r != "hard_bound_violation"]
            # Recompute quality now that the hard-fail reason is gone.
            hard_left = any(r in _HARD_FAIL_REASONS for r in reasons)
            if hard_left:
                data_quality = "quarantined"
            elif reasons:
                data_quality = "warn"
            else:
                data_quality = "ok"

        verdict_channel = dict(verdict)
        verdict_channel["channel"]      = cid
        verdict_channel["reasons"]      = reasons
        verdict_channel["data_quality"] = data_quality
        verdicts.append(verdict_channel)

        ch["data_quality"] = data_quality
        ch["reasons"]      = reasons

        if data_quality == "quarantined":
            # Hard-fail: downstream ranking + rationale must not see
            # the corrupt value.  Drop move_5d and mark the channel
            # unavailable so it doesn't contribute to primary selection.
            ch["move_5d"]    = None
            ch["available"]  = False
    return channels, verdicts


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _normalized_magnitude(channel: dict) -> float:
    move = channel.get("move_5d")
    scale = channel.get("scale") or 1.0
    if move is None or scale <= 0:
        return 0.0
    return abs(float(move)) / scale


def _rank_channels(channels: dict[str, dict]) -> list[tuple[str, float]]:
    """Return [(channel_id, normalized_magnitude), ...] sorted desc.

    Only available channels are returned.
    """
    rows: list[tuple[str, float]] = []
    for cid, ch in channels.items():
        if not ch.get("available"):
            continue
        rows.append((cid, _normalized_magnitude(ch)))
    rows.sort(key=lambda r: -r[1])
    return rows


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

def _fmt_move(move: Optional[float], cid: str = "") -> str:
    """Format a channel move with the correct unit suffix."""
    if move is None:
        return "—"
    unit = _CHANNEL_UNITS.get(cid, "%")
    return f"{move:+.2f} {unit}"


def _rationale(primary: str, channels: dict[str, dict],
               ranked: list[tuple[str, float]]) -> str:
    """Return a one-line empirical rationale.

    Always tied to actual numbers — never generic prose.
    """
    if primary == "none":
        if not ranked:
            return "All transmission channels unavailable; cannot decompose."
        top = ranked[0]
        ch = channels[top[0]]
        return (
            f"All channels below noise band — leader is "
            f"{_CHANNEL_LABELS[top[0]].lower()} at {_fmt_move(ch.get('move_5d'), top[0])} / 5d "
            f"({top[1]:.1f}σ)."
        )

    primary_ch = channels[primary]
    primary_move = primary_ch.get("move_5d")
    primary_z = _normalized_magnitude(primary_ch)

    bits = [
        f"{_CHANNEL_LABELS[primary].lower()} {_fmt_move(primary_move, primary)} / 5d "
        f"({primary_z:.1f}σ)"
    ]

    # Add the next ranked channel for contrast (if any).
    for cid, z in ranked[1:3]:
        ch = channels[cid]
        bits.append(
            f"{_CHANNEL_LABELS[cid].lower()} {_fmt_move(ch.get('move_5d'), cid)} ({z:.1f}σ)"
        )

    return f"Primary mover: {bits[0]}" + (
        " — vs " + ", ".join(bits[1:]) if len(bits) > 1 else ""
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_shock_decomposition(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]] = None,
) -> dict:
    """Decompose the live macro shock into transmission channels.

    Pure composer — no I/O.  All inputs optional; degrades gracefully:
      - No usable inputs at all → ``{}`` (UI skips the card).
      - Only some channels available → block with ``stale=True`` and the
        unavailable channels marked ``available=False``.
      - All channels quiet → ``primary="none"`` and macro_read explains.
    """
    rates_ok = _rates_usable(rates_context)
    stress_ok = bool(stress_regime and isinstance(stress_regime, dict)
                     and (stress_regime.get("raw") or stress_regime.get("detail")))

    channels = _extract_channels(rates_context, stress_regime, snapshots)
    # Benchmark-quarantine pass — label warn-grade channels and
    # hard-fail quarantined ones before ranking sees them.  Healthy
    # prints pass through unchanged.
    channels, quarantine_verdicts = _apply_benchmark_quarantine(
        channels, snapshots,
    )
    channel_quality = channel_quality_block(quarantine_verdicts)
    available_count = sum(1 for c in channels.values() if c["available"])

    # Rates pack — 2s10s + 5s30s decomposition + combined regime-state read.
    # 10Y and SHY-proxy-2Y form the front-end slope; 5Y and 30Y (surfaced on
    # rates_context under mid_nominal / long_nominal since v2) form the long
    # end.  Any tenor missing degrades its section of the curve to
    # unavailable without disturbing the others.
    tenyr_pp = _f((rates_context or {}).get("nominal", {}).get("change_5d")) \
        if rates_context else None
    tenyr_pp = _safe_move("nominal_yield", tenyr_pp)
    shy_pct = _snap_change_5d(snapshots, "2Y")
    if shy_pct is None:
        shy_pct = _snap_change_5d(snapshots, "SHY")
    if shy_pct is None:
        shy_pct = _stress_shy_5d(stress_regime)

    fiveyr_pp = _f((rates_context or {}).get("mid_nominal", {}).get("change_5d")) \
        if rates_context else None
    fiveyr_pp = _safe_move("nominal_yield", fiveyr_pp)
    thirtyyr_pp = _f((rates_context or {}).get("long_nominal", {}).get("change_5d")) \
        if rates_context else None
    thirtyyr_pp = _safe_move("nominal_yield", thirtyyr_pp)

    rates_pack = _build_rates_pack(tenyr_pp, shy_pct, fiveyr_pp, thirtyyr_pp)

    # FX pack — cross-rate decomposition (EURUSD/USDJPY/USDCNY) on top of
    # DXY.  Snapshots can override stress_regime values when present.
    fx_pack_override: dict = {}
    for pid, snap_key in (("EURUSD", "EURUSD"), ("USDJPY", "USDJPY"),
                           ("USDCNY", "USDCNY"), ("DXY", "DXY")):
        mv = _snap_change_5d(snapshots, snap_key)
        if mv is not None:
            fx_pack_override[pid] = mv
    fx_pack = compute_cross_rate_fx(
        stress_regime=stress_regime,
        fx_pack=fx_pack_override or None,
    )

    # Breakeven curve — per-tenor (2Y/5Y/10Y/30Y) decomposition + inflation
    # shape + policy-space read.  Comes pre-assembled on rates_context so
    # this module just surfaces it.  Safe passthrough when missing.
    breakeven_curve = (rates_context or {}).get("breakeven_curve") or {}

    # Hard short-circuit: nothing to say at all.
    if available_count == 0 and not rates_ok and not stress_ok:
        return {}

    ranked = _rank_channels(channels)

    if not ranked:
        # Macro inputs were nominally present but every channel ended up
        # unavailable (e.g. snapshots all errored).  Surface a stale block.
        return {
            "primary":       "none",
            "primary_label": "Macro unavailable",
            "secondary":     [],
            "rationale":     "No channel had a usable 5d move.",
            "macro_read":    _MACRO_READ["none"],
            "key_markets":   [],
            "channels":      _channels_for_payload(channels),
            "rates_pack":    rates_pack,
            "fx_pack":       fx_pack,
            "breakeven_curve": breakeven_curve,
            "channel_quality": channel_quality,
            "available":     False,
            "stale":         True,
        }

    top_id, top_z = ranked[0]
    if top_z < _PRIMARY_FLOOR:
        primary = "none"
    else:
        primary = top_id

    secondary: list[dict] = []
    for cid, z in ranked[1:]:
        if z < _SECONDARY_FLOOR:
            continue
        secondary.append({
            "id":       cid,
            "label":    _CHANNEL_LABELS[cid],
            "move_5d":  channels[cid].get("move_5d"),
            "unit":     _CHANNEL_UNITS.get(cid, "%"),
            "z":        round(z, 2),
        })
        if len(secondary) >= 3:
            break

    primary_label = (
        _CHANNEL_LABELS[primary] if primary != "none" else "No clear shock"
    )
    key_markets = list(_CHANNEL_MARKETS.get(primary, [])) if primary != "none" else []
    rationale = _rationale(primary, channels, ranked)
    macro_read = _MACRO_READ.get(primary, _MACRO_READ["none"])

    # Stale flag: any of the five channels is missing.
    stale = available_count < len(CHANNEL_IDS)

    return {
        "primary":       primary,
        "primary_label": primary_label,
        "secondary":     secondary,
        "rationale":     rationale,
        "macro_read":    macro_read,
        "key_markets":   key_markets,
        "channels":      _channels_for_payload(channels),
        "rates_pack":    rates_pack,
        "fx_pack":       fx_pack,
        "breakeven_curve": breakeven_curve,
        "channel_quality": channel_quality,
        "available":     True,
        "stale":         stale,
    }


def sanitize_shock_decomposition_block(block: dict) -> dict:
    """Clamp absurd move_5d values in a persisted shock-decomposition block.

    Frozen-archive events were saved before the unit fix landed; their channel
    dicts may carry move_5d values like +2680 (from _safe_pct on near-zero
    historical ^TNX rows).  This function applies _CHANNEL_MOVE_CAPS and
    recalculates z-scores so the frontend never sees those artifacts.

    Returns a deep copy with clamped values — does not mutate the input.
    Idempotent: safe to call on already-sanitized blocks.
    """
    import copy
    if not block or not isinstance(block, dict):
        return block or {}

    block = copy.deepcopy(block)

    channels = block.get("channels") or {}
    for cid, ch in channels.items():
        if not isinstance(ch, dict):
            continue
        move = ch.get("move_5d")
        if move is None:
            continue
        cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
        if abs(float(move)) > cap:
            ch["move_5d"] = None
            ch["available"] = False
            ch["z"] = 0.0

    # Sanitize secondary list — drop any entry whose move is absurd.
    secondary = block.get("secondary") or []
    clean_secondary = []
    for s in secondary:
        if not isinstance(s, dict):
            continue
        cid = s.get("id", "")
        move = s.get("move_5d")
        cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
        if move is not None and abs(float(move)) > cap:
            continue
        clean_secondary.append(s)
    block["secondary"] = clean_secondary

    return block


def _channels_for_payload(channels: dict[str, dict]) -> dict[str, dict]:
    """Strip internal fields ("scale") and round numbers for JSON payload."""
    out: dict[str, dict] = {}
    for cid, ch in channels.items():
        entry = {
            "label":     ch["label"],
            "move_5d":   round(ch["move_5d"], 3) if ch.get("move_5d") is not None else None,
            "unit":      _CHANNEL_UNITS.get(cid, "%"),
            "available": ch["available"],
            "z":         round(_normalized_magnitude(ch), 2),
        }
        # Carry through commodity sub-components when present.
        if "crude_5d" in ch:
            entry["crude_5d"] = round(ch["crude_5d"], 3)
        if "gold_5d" in ch:
            entry["gold_5d"] = round(ch["gold_5d"], 3)
        if "leader" in ch:
            entry["leader"] = ch["leader"]
        # Benchmark-quarantine metadata — always present so the UI shape
        # is stable.  Defaults to "ok"/[] for channels not mapped to a
        # benchmark (e.g. credit composite).
        entry["data_quality"] = ch.get("data_quality", "ok")
        entry["reasons"]      = list(ch.get("reasons") or [])
        out[cid] = entry
    return out

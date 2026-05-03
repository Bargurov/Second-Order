"""
breakeven_curve.py

Breakeven-curve decomposition + inflation-path interpretation.

Why this module
---------------
The existing rates/inflation read compresses everything into a single
point estimate (``breakeven_proxy`` ≈ 10Y nominal − 10Y TIPS proxy).
That is fine for a quick regime label but loses the *shape* information
a macro desk actually cares about:

  * Is inflation concern FRONT-LOADED (short breakevens rising faster
    than long) — i.e. an immediate pass-through that the Fed has to
    respond to near-term?
  * Or does it look TERM-PREMIUM-LIKE (long breakevens rising faster
    than short) — structural / fiscal / supply issuance pressure that
    the Fed can look through while still watching the long end?
  * Is the curve shifting in PARALLEL — a broad regime reprice across
    all tenors?

This module encodes that decomposition as pure data:

  1. Per-tenor (2Y / 5Y / 10Y / 30Y) breakeven readings from proxy
     TIPS ETFs (STIP, TIP, LTPZ) and nominal yield symbols
     (derived 2Y from SHY, ^FVX, ^TNX, ^TYX).
  2. Short-end (2Y+5Y) vs long-end (10Y+30Y) aggregates.
  3. A shape classifier + a policy-space interpretation.

Pure composer: no I/O, no external imports beyond stdlib.  Inputs are
per-tenor ``(nominal_5d_pp, real_5d_pp)`` tuples; breakeven at each
tenor is derived via Fisher decomposition as ``nominal − real``.

The ``real_5d_pp`` at each tenor is an ETF-duration-adjusted proxy
rather than a clean direct TIPS-yield print — there is no free feed
for that.  Treat the values as institutional-grade approximations,
not tradeable yields.  Duration constants are documented on the map
below so the sign and order-of-magnitude are correct.

Output shape
------------
    {
      available:        bool,
      stale:            bool,
      tenors: {
        "2Y":  {nominal_5d_pp, real_5d_pp, breakeven_5d_pp, available},
        "5Y":  {...},
        "10Y": {...},
        "30Y": {...},
      },
      short_end_be_5d:   float | None,   # avg 2Y+5Y breakeven move (pp)
      long_end_be_5d:    float | None,   # avg 10Y+30Y breakeven move (pp)
      shape_change_5d:   float | None,   # long_end - short_end
      shape:             "front_loaded" | "term_premium_like"
                         | "parallel_up" | "parallel_down"
                         | "twist" | "flat" | "unavailable",
      policy_space:      "narrow_hawkish" | "look_through" | "ease_room"
                         | "behind_the_curve" | "neutral" | "unavailable",
      rationale:         str,
    }

Sign convention (all tenors, pp over 5d):
  nominal_5d_pp > 0  ⇒ yields rising
  real_5d_pp > 0     ⇒ real yields rising (TIPS ETF falling)
  breakeven_5d_pp > 0⇒ inflation expectations widening
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Tenor metadata
# ---------------------------------------------------------------------------

TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")

_TENOR_LABEL: dict[str, str] = {
    "2Y":  "2-year",
    "5Y":  "5-year",
    "10Y": "10-year",
    "30Y": "30-year",
}

# TIPS ETF effective durations used to convert a price % move into a
# real-yield pp change.  Rough institutional approximations:
#   STIP: 0-5Y TIPS,   duration ~2.5y
#   VTIP/SCHP/TIPX are interchangeable short proxies at similar duration.
#   TIP:  7-10Y TIPS,  duration ~7.5y
#   LTPZ: 15Y+ TIPS,   duration ~20y
# Values are used by market_check upstream; this module receives the
# already-computed real_5d_pp so these constants are documented here as
# a reference, not consumed directly.
_TIPS_DURATION_BY_TENOR: dict[str, float] = {
    "2Y":  2.5,    # STIP proxy for the short end
    "5Y":  4.5,    # short-TIPS / TIP blend proxy
    "10Y": 7.5,    # TIP
    "30Y": 20.0,   # LTPZ
}

# Short-end vs long-end grouping for shape classification.
_SHORT_TENORS: tuple[str, ...] = ("2Y", "5Y")
_LONG_TENORS:  tuple[str, ...] = ("10Y", "30Y")


# ---------------------------------------------------------------------------
# Thresholds (validated in tests)
# ---------------------------------------------------------------------------

# Per-tenor noise floor in pp.  Below this the leg is treated as "flat".
_TENOR_NOISE_PP: float = 0.05

# Shape classifier gates.  These are calibrated against empirical 5d
# breakeven moves: a 1-sigma 5y move in a single-tenor breakeven is
# ~0.08pp, so a 0.08pp short-vs-long GAP is ~1σ on the differential.
_SHAPE_GAP_FLOOR_PP: float = 0.08

# Parallel-shift band: when the aggregate short-end and long-end both
# cleared the noise floor AND the gap between them is below this
# threshold, we call it a parallel shift.
_PARALLEL_BAND_PP:  float = 0.05

# Twist: short goes one way, long the other (opposing signs).
_TWIST_OPPOSING_FLOOR_PP: float = 0.05


# ---------------------------------------------------------------------------
# Policy-space thresholds
# ---------------------------------------------------------------------------
# Magnitudes (pp) at which the policy_space label escalates from neutral.
_POLICY_FRONT_MAG_PP: float = 0.10     # short_end up this much = narrow Fed space
_POLICY_LONG_MAG_PP:  float = 0.10     # long_end up this much = term-premium pressure


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


def _avg(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _tenor_block(
    nominal_5d_pp: Optional[float],
    real_5d_pp: Optional[float],
) -> dict:
    """Compose a single tenor's {nominal, real, breakeven, available} dict.

    Breakeven is derived via Fisher decomposition: nominal − real.  When
    either input is None the tenor is marked unavailable; partial data
    does not fabricate a breakeven number.
    """
    nom = _f(nominal_5d_pp)
    real = _f(real_5d_pp)
    avail = nom is not None and real is not None
    return {
        "nominal_5d_pp":   round(nom, 3)  if nom  is not None else None,
        "real_5d_pp":      round(real, 3) if real is not None else None,
        "breakeven_5d_pp": round(nom - real, 3) if avail else None,
        "available":       avail,
    }


# ---------------------------------------------------------------------------
# Shape classifier
# ---------------------------------------------------------------------------

def _classify_shape(
    short_be: Optional[float],
    long_be:  Optional[float],
) -> str:
    if short_be is None and long_be is None:
        return "unavailable"
    if short_be is None or long_be is None:
        # One end available but the other missing — we can't distinguish
        # shape with only one anchor; report unavailable shape even
        # though the tenor-level breakeven is still surfaced.
        return "unavailable"

    short_mag_low = abs(short_be) < _TENOR_NOISE_PP
    long_mag_low  = abs(long_be)  < _TENOR_NOISE_PP
    if short_mag_low and long_mag_low:
        return "flat"

    # Twist: opposing signs, both clearing the opposing floor.
    if (
        short_be * long_be < 0
        and abs(short_be) >= _TWIST_OPPOSING_FLOOR_PP
        and abs(long_be)  >= _TWIST_OPPOSING_FLOOR_PP
    ):
        return "twist"

    # Signed gap for parallel-band check (treats +0.15/+0.17 as parallel).
    signed_gap = short_be - long_be
    if abs(signed_gap) < _PARALLEL_BAND_PP:
        return "parallel_up" if (short_be + long_be) > 0 else "parallel_down"

    # Magnitude-based comparison for front-loaded vs term-premium-like.
    # "Front-loaded" = short end moved MORE (in magnitude) than long end,
    # regardless of sign.  A short-be of -0.20 with long-be of -0.05 is
    # front-loaded disinflation, NOT term-premium-like.
    mag_gap = abs(short_be) - abs(long_be)
    if mag_gap >= _SHAPE_GAP_FLOOR_PP:
        return "front_loaded"
    if -mag_gap >= _SHAPE_GAP_FLOOR_PP:
        return "term_premium_like"

    # Fallback band — signed gap is meaningful but below the magnitude
    # floor; treat as parallel when both legs point the same way.
    return "parallel_up" if (short_be + long_be) > 0 else "parallel_down"


# ---------------------------------------------------------------------------
# Policy-space interpretation
# ---------------------------------------------------------------------------

def _policy_space(
    shape: str,
    short_be: Optional[float],
    long_be:  Optional[float],
) -> str:
    if shape in ("unavailable", "flat") or short_be is None or long_be is None:
        return "unavailable" if shape == "unavailable" else "neutral"

    if shape == "front_loaded":
        # Short end pushing up → Fed must stay near-term hawkish.
        if short_be >= _POLICY_FRONT_MAG_PP:
            return "narrow_hawkish"
        # Short end pushing DOWN (disinflation front-loaded) → ease room.
        if short_be <= -_POLICY_FRONT_MAG_PP:
            return "ease_room"
        return "neutral"

    if shape == "term_premium_like":
        # Long end carrying inflation pressure (structural / fiscal).
        if long_be >= _POLICY_LONG_MAG_PP:
            return "look_through"
        if long_be <= -_POLICY_LONG_MAG_PP:
            return "behind_the_curve"
        return "neutral"

    if shape == "twist":
        # Short up + long down = curve flattening as cuts priced in
        # despite near-term inflation → classic "behind the curve" risk.
        if short_be > 0 > long_be:
            return "behind_the_curve"
        # Short down + long up = steepener led by term premium → Fed
        # has ease room near-term but long end is skeptical.
        if short_be < 0 < long_be:
            return "look_through"
        return "neutral"

    if shape in ("parallel_up", "parallel_down"):
        avg = ((short_be or 0.0) + (long_be or 0.0)) / 2
        # Broad regime reprice.  Parallel-up = inflation concern across
        # the curve (narrow hawkish).  Parallel-down = disinflation
        # broadly (ease room).
        if avg >= _POLICY_FRONT_MAG_PP:
            return "narrow_hawkish"
        if avg <= -_POLICY_FRONT_MAG_PP:
            return "ease_room"
        return "neutral"

    return "neutral"


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

_SHAPE_LABEL: dict[str, str] = {
    "front_loaded":      "Front-loaded",
    "term_premium_like": "Term-premium-like",
    "parallel_up":       "Parallel shift up",
    "parallel_down":     "Parallel shift down",
    "twist":             "Twist (front + long diverge)",
    "flat":              "Flat (no meaningful breakeven move)",
    "unavailable":       "Insufficient tenor data",
}

_POLICY_LABEL: dict[str, str] = {
    "narrow_hawkish":    "Narrow near-term ease space — Fed boxed in",
    "look_through":      "Fed can look through long-end pressure",
    "ease_room":         "Near-term ease space opens up",
    "behind_the_curve":  "Curve says Fed is behind the curve",
    "neutral":           "Policy implication neutral",
    "unavailable":       "Policy read unavailable",
}


def _rationale(
    shape: str,
    policy: str,
    short_be: Optional[float],
    long_be:  Optional[float],
) -> str:
    def _fmt(v: Optional[float]) -> str:
        return f"{v:+.2f} pp" if v is not None else "n/a"

    tag = _SHAPE_LABEL.get(shape, shape)
    base = (
        f"{tag}: short-end {_fmt(short_be)} vs long-end {_fmt(long_be)}"
    )
    if policy not in ("neutral", "unavailable"):
        base += f" — {_POLICY_LABEL[policy]}"
    return base + "."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_breakeven_curve(
    nominal_5d_pp: dict[str, Optional[float]],
    real_5d_pp:    dict[str, Optional[float]],
) -> dict:
    """Decompose the breakeven curve across 2Y / 5Y / 10Y / 30Y tenors.

    Inputs are dicts keyed by tenor label.  Missing / None entries are
    tolerated: the tenor is marked unavailable and aggregates fall back
    to whichever tenors DO have data.

    Returns the structured block documented at the top of this module.
    Never raises — always returns a dict with every top-level key even
    when all inputs are absent.
    """
    tenors_out: dict[str, dict] = {}
    for t in TENORS:
        tenors_out[t] = _tenor_block(
            (nominal_5d_pp or {}).get(t),
            (real_5d_pp    or {}).get(t),
        )

    # Aggregate breakevens by end.
    short_vals = [
        tenors_out[t]["breakeven_5d_pp"]
        for t in _SHORT_TENORS
        if tenors_out[t]["available"]
        and tenors_out[t]["breakeven_5d_pp"] is not None
    ]
    long_vals = [
        tenors_out[t]["breakeven_5d_pp"]
        for t in _LONG_TENORS
        if tenors_out[t]["available"]
        and tenors_out[t]["breakeven_5d_pp"] is not None
    ]
    short_be = _avg(short_vals)
    long_be  = _avg(long_vals)

    shape = _classify_shape(short_be, long_be)
    policy = _policy_space(shape, short_be, long_be)
    rationale = _rationale(shape, policy, short_be, long_be)

    shape_change = None
    if short_be is not None and long_be is not None:
        shape_change = round(long_be - short_be, 3)

    any_avail = any(t["available"] for t in tenors_out.values())

    return {
        "available":        any_avail,
        "stale":            not any_avail,
        "tenors":           tenors_out,
        "short_end_be_5d":  round(short_be, 3) if short_be is not None else None,
        "long_end_be_5d":   round(long_be, 3)  if long_be  is not None else None,
        "shape_change_5d":  shape_change,
        "shape":            shape,
        "shape_label":      _SHAPE_LABEL.get(shape, shape),
        "policy_space":     policy,
        "policy_label":     _POLICY_LABEL.get(policy, policy),
        "rationale":        rationale,
    }


# ---------------------------------------------------------------------------
# Convenience: build the real_5d_pp dict from TIPS-ETF % moves
# ---------------------------------------------------------------------------

def real_pp_from_tips_pct(
    stip_pct_5d: Optional[float] = None,
    tip_pct_5d:  Optional[float] = None,
    ltpz_pct_5d: Optional[float] = None,
    mid_tips_pct_5d: Optional[float] = None,
) -> dict[str, Optional[float]]:
    """Convert TIPS-ETF % moves to per-tenor real-yield pp changes.

    Uses the duration constants documented at the top of this module.
    STIP covers 0-5Y TIPS → used for the 2Y tenor (duration ~2.5y) AND
    as a blend proxy for 5Y.  When ``mid_tips_pct_5d`` is supplied it
    overrides the 5Y STIP proxy with an explicit 3-7Y TIPS move.

    Returns a dict suitable for feeding ``compute_breakeven_curve``:
      {"2Y": ..., "5Y": ..., "10Y": ..., "30Y": ...}
    """
    def _invert(pct: Optional[float], duration: float) -> Optional[float]:
        """Convert a TIPS ETF price % move to a real-yield pp change.

        TIPS price up ⇒ real yield down.  The magnitude is scaled by the
        ETF's effective duration: ``Δyield ≈ −Δprice / duration``.
        """
        val = _f(pct)
        if val is None:
            return None
        return -val / duration

    return {
        "2Y":  _invert(stip_pct_5d, _TIPS_DURATION_BY_TENOR["2Y"]),
        "5Y":  _invert(
            mid_tips_pct_5d if mid_tips_pct_5d is not None else stip_pct_5d,
            _TIPS_DURATION_BY_TENOR["5Y"],
        ),
        "10Y": _invert(tip_pct_5d,  _TIPS_DURATION_BY_TENOR["10Y"]),
        "30Y": _invert(ltpz_pct_5d, _TIPS_DURATION_BY_TENOR["30Y"]),
    }

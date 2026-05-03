"""Pure composer for truer market math — real/breakeven decomposition + USD basket.

Why this module
---------------
The existing rates + FX reads lean on single-instrument ETF proxies:

  * ``breakeven_proxy_5d = nominal_pp + TIP_pct / 7.5`` — Fisher
    decomposition through a single duration inversion.  Carries the
    same noise as TIP itself.
  * ``DXY`` as the sole USD proxy — 57.6 % EUR weight, so a CNY or JPY
    shock barely registers.

We cannot ship *truer* numbers without a feed that yfinance doesn't
serve (e.g. direct DFII10 real yields), but we can ship:

  1. A **derived** breakeven read from ``(TIP − IEF)`` price ratio
     (two direct market prints, no nominal-yield dependence) in
     parallel with the existing Fisher proxy, and a cross-check that
     flags when the two disagree.
  2. A **constructed USD basket** from equal-weighted ``(EURUSD,
     USDJPY, GBPUSD, USDCNY)`` log-return contributions with the
     sign normalised to "USD strength positive".  DXY is kept as a
     second read; the two confirm each other under broad USD moves
     and diverge when the driver is concentrated in one leg (e.g. a
     China devaluation shock DXY barely sees).
  3. A closed ``QUALITY_IDS`` enum carried on every returned block so
     consumers can see at a glance whether a number is a direct print,
     a derived combination, a duration-proxy, or a degraded fallback.

This is a **pure composer** — no I/O, no SQLite, no imports beyond
stdlib.  All inputs are pre-fetched 5-day moves; the caller
(``market_check.compute_rates_context``) is the only place providers
touch.

Output guarantees
-----------------
* Every block has a ``quality`` field ∈ ``QUALITY_IDS`` — never missing.
* ``unavailable`` is an explicit state, never an exception.
* Sign convention on the USD basket is tested — a single flipped pair
  would fail ``tests/test_market_math.py``.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
# A block's ``quality`` is always one of these; never missing.  The
# enum encodes the evidentiary weight a consumer should give the read:
#
#   direct       — raw market print, no derivation.  ^TNX yield move.
#   derived      — combination of two or more direct prints via market
#                  math (e.g. breakeven = (TIP − IEF) price ratio).
#   proxy        — single-instrument ETF duration inversion; correct
#                  in sign and order-of-magnitude but noisy.
#   degraded     — primary source unavailable, a fallback was used.
#   unavailable  — no usable signal; all downstream reads are None.

QUALITY_IDS: tuple[str, ...] = (
    "direct",
    "derived",
    "proxy",
    "degraded",
    "unavailable",
)

_QUALITY_ENUM: frozenset[str] = frozenset(QUALITY_IDS)


# ---------------------------------------------------------------------------
# Duration constants (institutional approximations)
# ---------------------------------------------------------------------------
# TIP and IEF both track ~7-10Y Treasuries with closely matched duration,
# which is precisely what makes their price ratio a clean breakeven proxy:
# shared duration cancels in the ratio, leaving only the real-vs-nominal
# differential.
#
# Values are widely documented on iShares product pages and move slowly
# (quarterly re-check is enough).

_TIP_DURATION_YR: float = 7.5
_IEF_DURATION_YR: float = 7.5

# Mean duration used in the (TIP − IEF) ratio breakeven conversion.
# Shared-duration assumption; the gap between _TIP and _IEF durations is
# well inside the noise of the move itself.
_RATIO_DURATION_YR: float = 0.5 * (_TIP_DURATION_YR + _IEF_DURATION_YR)


# ---------------------------------------------------------------------------
# Cross-check thresholds (pp over 5d)
# ---------------------------------------------------------------------------
# If the two breakeven reads differ by less than this, we call them in
# agreement.  Calibrated against the 5y 1-sigma breakeven move (~0.08 pp):
# 0.10 pp is roughly one noise unit, tight enough to flag real divergence.
_BE_AGREEMENT_GAP_PP: float = 0.10

# USD basket vs DXY agreement band — in percent over 5d.  DXY's 1-sigma
# 5d move is ~0.7 %; a 0.5 % gap between basket and DXY is real
# disagreement, not noise.
_FX_AGREEMENT_GAP_PCT: float = 0.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    """Coerce to float; None on missing / NaN / inf / non-numeric."""
    if v is None or isinstance(v, bool):
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _block_unavailable(rationale: str) -> dict[str, Any]:
    return {
        "value_5d_pp": None,
        "source":      "none",
        "quality":     "unavailable",
        "rationale":   rationale,
    }


# ---------------------------------------------------------------------------
# Real-rate / breakeven decomposition
# ---------------------------------------------------------------------------

def compute_real_rate_read(
    *,
    nominal_5d_pp: Optional[float] = None,
    tip_pct_5d:    Optional[float] = None,
    ief_pct_5d:    Optional[float] = None,
) -> dict[str, Any]:
    """Decompose rates into nominal / real / breakeven with source labels.

    Inputs
    ------
    nominal_5d_pp : absolute percentage-point change in the 10Y nominal
        yield (e.g. ``^TNX`` print).  ``None`` if unavailable — falls
        back to ratio-derived breakeven where possible.
    tip_pct_5d : 5-day percent move in the TIP ETF (7-10Y TIPS price).
    ief_pct_5d : 5-day percent move in the IEF ETF (7-10Y nominal
        Treasury price).  When supplied, enables the *derived*
        breakeven read: ``(TIP − IEF) / duration`` has no nominal-yield
        dependence so it's a structurally distinct signal from the
        Fisher proxy.

    Output shape (all pp unless otherwise noted)
    --------------------------------------------
        {
          nominal:           {value_5d_pp, source, quality, rationale},
          real:              {value_5d_pp, source, quality, rationale},
          breakeven_primary: {value_5d_pp, source, quality, rationale},
          breakeven_fallback:{value_5d_pp, source, quality, rationale} | None,
          cross_check:       {agreement, gap_pp, rationale},
          overall_quality:   one of QUALITY_IDS,
          rationale:         str,
        }

    ``overall_quality`` is the minimum evidentiary weight across the
    three legs (nominal / real / breakeven_primary) — if any leg is a
    proxy, the whole block is labelled *proxy*; if a fallback kicked
    in, *degraded*; all unavailable → *unavailable*.
    """
    nom_pp = _f(nominal_5d_pp)
    tip = _f(tip_pct_5d)
    ief = _f(ief_pct_5d)

    # --- Nominal leg (direct ^TNX print) -------------------------------
    if nom_pp is None:
        nominal = _block_unavailable("No ^TNX move available.")
    else:
        nominal = {
            "value_5d_pp": round(nom_pp, 4),
            "source":      "tnx_direct",
            "quality":     "direct",
            "rationale":   "10Y nominal yield change from ^TNX.",
        }

    # --- Breakeven legs ------------------------------------------------
    # Derived (preferred): (TIP − IEF) / mean_duration.  Two direct
    # prints, no nominal dependency.
    breakeven_derived: Optional[dict[str, Any]] = None
    if tip is not None and ief is not None:
        be_derived_pp = (tip - ief) / _RATIO_DURATION_YR
        breakeven_derived = {
            "value_5d_pp": round(be_derived_pp, 4),
            "source":      "tip_over_ief_ratio",
            "quality":     "derived",
            "rationale":   (
                "Breakeven from TIP − IEF price ratio (both ~7.5y "
                "duration); shared-duration cancels in the ratio "
                "leaving the real-vs-nominal differential."
            ),
        }

    # Proxy (Fisher): nominal_pp + TIP_pct / duration.  Same method the
    # existing market_check breakeven_proxy uses — kept as the fallback
    # and as a cross-check against the derived read.
    breakeven_proxy: Optional[dict[str, Any]] = None
    if nom_pp is not None and tip is not None:
        be_proxy_pp = nom_pp + tip / _TIP_DURATION_YR
        breakeven_proxy = {
            "value_5d_pp": round(be_proxy_pp, 4),
            "source":      "fisher_nominal_minus_tip_duration",
            "quality":     "proxy",
            "rationale":   (
                "Breakeven from Fisher decomposition: nominal − "
                "(−TIP_pct / 7.5 duration).  Single-instrument "
                "duration inversion, same noise as TIP itself."
            ),
        }

    # Primary = derived if we have it; otherwise fall back to Fisher.
    if breakeven_derived is not None:
        breakeven_primary = breakeven_derived
        breakeven_fallback = breakeven_proxy  # may be None
    elif breakeven_proxy is not None:
        breakeven_primary = dict(breakeven_proxy)
        # When the derived path is unavailable, the Fisher proxy is the
        # only read — label quality as "degraded" rather than plain
        # "proxy" so callers see that the better source was missing.
        breakeven_primary["quality"] = "degraded"
        breakeven_primary["rationale"] += (
            "  TIP-over-IEF derived read unavailable — using Fisher "
            "proxy as a degraded fallback."
        )
        breakeven_fallback = None
    else:
        breakeven_primary = _block_unavailable(
            "No breakeven read available — both TIP and the nominal "
            "yield inputs are missing."
        )
        breakeven_fallback = None

    # --- Real-yield leg ------------------------------------------------
    # Preferred: nominal_pp − breakeven_primary_pp (Fisher definition).
    # Falls back to −TIP_pct / duration when nominal is missing.
    real: dict[str, Any]
    be_primary_pp = breakeven_primary.get("value_5d_pp")
    if nom_pp is not None and be_primary_pp is not None:
        real_pp = nom_pp - be_primary_pp
        # Quality tracks the breakeven that fed it: derived → derived;
        # proxy/degraded → proxy; etc.
        be_q = breakeven_primary["quality"]
        real = {
            "value_5d_pp": round(real_pp, 4),
            "source":      "nominal_minus_breakeven",
            "quality":     be_q if be_q in {"derived", "proxy"} else "degraded",
            "rationale":   (
                f"Real yield = nominal − breakeven; inherits the "
                f"{be_q} breakeven quality."
            ),
        }
    elif tip is not None:
        real_pp = -tip / _TIP_DURATION_YR
        real = {
            "value_5d_pp": round(real_pp, 4),
            "source":      "tip_duration_proxy",
            "quality":     "proxy",
            "rationale":   (
                "Real yield from TIP ETF duration inversion "
                "(−TIP_pct / 7.5) — nominal yield unavailable."
            ),
        }
    else:
        real = _block_unavailable(
            "Neither nominal yield nor TIP print available."
        )

    # --- Cross-check between the two breakeven reads -------------------
    cross: dict[str, Any]
    if breakeven_derived is not None and breakeven_proxy is not None:
        gap = breakeven_derived["value_5d_pp"] - breakeven_proxy["value_5d_pp"]
        if abs(gap) <= _BE_AGREEMENT_GAP_PP:
            cross = {
                "agreement": "confirmed",
                "gap_pp":    round(gap, 4),
                "rationale": (
                    "Derived (TIP−IEF) and Fisher-proxy breakeven "
                    "reads agree within noise — signal is reliable."
                ),
            }
        else:
            cross = {
                "agreement": "divergent",
                "gap_pp":    round(gap, 4),
                "rationale": (
                    f"Derived and Fisher breakeven reads disagree by "
                    f"{gap:+.2f} pp — one path may be picking up "
                    f"TIP-specific liquidity / duration mismatch."
                ),
            }
    elif breakeven_primary.get("quality") == "unavailable":
        cross = {
            "agreement": "unavailable",
            "gap_pp":    None,
            "rationale": "No breakeven read computable.",
        }
    else:
        cross = {
            "agreement": "single_source",
            "gap_pp":    None,
            "rationale": (
                f"Only one breakeven path available "
                f"({breakeven_primary['source']}) — no cross-check."
            ),
        }

    # --- Overall quality ----------------------------------------------
    legs = [nominal["quality"], real["quality"], breakeven_primary["quality"]]
    overall = _worst_quality(legs)

    rationale = (
        "Rates read composed from "
        f"nominal={nominal['quality']} / "
        f"real={real['quality']} / "
        f"breakeven={breakeven_primary['quality']}; "
        f"overall={overall}."
    )

    return {
        "nominal":            nominal,
        "real":               real,
        "breakeven_primary":  breakeven_primary,
        "breakeven_fallback": breakeven_fallback,
        "cross_check":        cross,
        "overall_quality":    overall,
        "rationale":          rationale,
    }


# Quality ordering for the worst-of aggregation.  Lower index = better.
_QUALITY_RANK: dict[str, int] = {
    "direct":      0,
    "derived":     1,
    "proxy":       2,
    "degraded":    3,
    "unavailable": 4,
}


def _worst_quality(qualities: list[str]) -> str:
    """Return the lowest-ranked quality (closest to 'unavailable')."""
    if not qualities:
        return "unavailable"
    return max(qualities, key=lambda q: _QUALITY_RANK.get(q, 99))


# ---------------------------------------------------------------------------
# USD basket construction
# ---------------------------------------------------------------------------
# The basket normalises every component to "USD strength positive" before
# averaging.  Quote conventions used by yfinance / most providers:
#
#   EURUSD=X  — USD is the QUOTE currency.  USD weaker → number up.
#               Invert sign: usd_contrib = -eurusd_pct
#   GBPUSD=X  — USD is the QUOTE.  Same inversion.
#   USDJPY=X  — USD is the BASE.  USD stronger → number up.  Keep sign.
#   USDCNY=X  — USD is the BASE.  Keep sign.
#
# We do NOT use yfinance's inverted tickers (JPYUSD=X / CNYUSD=X); those
# are typically far less liquid and noisier than the conventional quote.

_BASKET_PAIRS: tuple[tuple[str, int], ...] = (
    # (pair_name, sign_for_usd_strength).  Sign is the multiplier
    # applied to the raw pct_5d input to express "USD strength positive".
    ("EURUSD", -1),
    ("GBPUSD", -1),
    ("USDJPY", +1),
    ("USDCNY", +1),
)


def compute_usd_basket_read(
    *,
    dxy_pct_5d:     Optional[float] = None,
    eurusd_pct_5d:  Optional[float] = None,
    gbpusd_pct_5d:  Optional[float] = None,
    usdjpy_pct_5d:  Optional[float] = None,
    usdcny_pct_5d:  Optional[float] = None,
) -> dict[str, Any]:
    """Construct an equal-weighted USD-strength basket + DXY cross-check.

    Sign convention: every component is normalised so "positive = USD
    strength".  The equal-weighted average is a broad-basket read that
    picks up moves DXY misses (e.g. USDCNY, USDJPY concentration).

    Output shape
    ------------
        {
          basket_5d_pct:    float | None,
          components: [
             {pair, raw_pct_5d, usd_strength_contrib, present},
             ...
          ],
          dxy: {value_5d_pct, present},
          source:     "dxy_plus_basket" | "basket_only" | "dxy_only" | "none",
          quality:    one of QUALITY_IDS,
          agreement:  "confirmed" | "divergent" | "single_source" | "unavailable",
          divergence_pct: float | None,
          rationale:  str,
        }

    The ``quality`` label:
      * ``derived``  — ≥ 2 basket components + DXY all present and agree
      * ``derived``  — ≥ 2 basket components, DXY missing → basket-only
      * ``direct``   — DXY only, basket thin → fallback to DXY
      * ``degraded`` — basket + DXY available but disagree > 0.5 %
      * ``unavailable`` — no usable input
    """
    dxy = _f(dxy_pct_5d)
    raw_inputs: dict[str, Optional[float]] = {
        "EURUSD": _f(eurusd_pct_5d),
        "GBPUSD": _f(gbpusd_pct_5d),
        "USDJPY": _f(usdjpy_pct_5d),
        "USDCNY": _f(usdcny_pct_5d),
    }

    components: list[dict[str, Any]] = []
    strength_contribs: list[float] = []
    for pair, sign in _BASKET_PAIRS:
        raw = raw_inputs[pair]
        if raw is None:
            components.append({
                "pair":                 pair,
                "raw_pct_5d":           None,
                "usd_strength_contrib": None,
                "present":              False,
            })
            continue
        contrib = sign * raw
        components.append({
            "pair":                 pair,
            "raw_pct_5d":           round(raw, 4),
            "usd_strength_contrib": round(contrib, 4),
            "present":              True,
        })
        strength_contribs.append(contrib)

    present_count = len(strength_contribs)
    basket_value: Optional[float]
    if present_count >= 2:
        basket_value = sum(strength_contribs) / present_count
        basket_value = round(basket_value, 4)
    else:
        basket_value = None

    dxy_block = {
        "value_5d_pct": round(dxy, 4) if dxy is not None else None,
        "present":      dxy is not None,
    }

    # --- Source + quality ---------------------------------------------
    divergence_pct: Optional[float] = None
    agreement: str
    source: str
    quality: str
    rationale_parts: list[str] = []

    if basket_value is not None and dxy is not None:
        divergence_pct = round(basket_value - dxy, 4)
        source = "dxy_plus_basket"
        if abs(divergence_pct) <= _FX_AGREEMENT_GAP_PCT:
            agreement = "confirmed"
            quality = "derived"
            rationale_parts.append(
                "Broad basket and DXY agree within noise — USD move "
                "is broad-based."
            )
        else:
            agreement = "divergent"
            quality = "degraded"
            rationale_parts.append(
                f"Broad basket ({basket_value:+.2f} %) and DXY "
                f"({dxy:+.2f} %) disagree by {divergence_pct:+.2f} % — "
                f"USD move is concentrated in specific legs, not "
                f"broad-based."
            )
    elif basket_value is not None:
        source = "basket_only"
        agreement = "single_source"
        quality = "derived"
        rationale_parts.append(
            f"Basket read from {present_count} USD crosses; DXY "
            f"print unavailable."
        )
    elif dxy is not None:
        source = "dxy_only"
        agreement = "single_source"
        # Basket thin (<2 components) → we have only DXY.  DXY is a
        # direct market index print, but the composer's contract was to
        # construct a broader basket; labelling "direct" here is
        # honest about what's in hand.
        quality = "direct"
        rationale_parts.append(
            "Only DXY is available — constructed basket is too thin "
            "(<2 cross components) to cross-check."
        )
    else:
        source = "none"
        agreement = "unavailable"
        quality = "unavailable"
        rationale_parts.append(
            "No DXY print and no basket components — USD read unavailable."
        )

    return {
        "basket_5d_pct":   basket_value,
        "components":      components,
        "dxy":             dxy_block,
        "source":          source,
        "quality":         quality,
        "agreement":       agreement,
        "divergence_pct":  divergence_pct,
        "rationale":       " ".join(rationale_parts),
    }

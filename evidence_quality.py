"""
evidence_quality.py

Evidence-quality weighting for the validation chain.

Why this module
---------------
Every layer downstream of the raw ticker list (agreement, evidence
ladder, attribution, conviction) counts a directional move as a
directional move.  In practice a move's *reliability* varies hugely:

  * An alpha-support on a liquid direct proxy with a +3% move is
    high-quality evidence.
  * The same alpha-support with a +0.2% move on thin volume is
    provisional — a coin-flip inside the noise band.
  * A ``drift`` tag, a flat return, or a near-zero volume_ratio is
    low-quality / noisy — the kind of thing a desk discounts by
    default.

This module classifies each ticker into one of three quality tiers,
aggregates the distribution, produces a quality-weighted score that
downstream consumers can substitute for the raw count, and emits an
explicit ``confidence_basis`` label so the UI can say "driven by
strong evidence" vs "fragile basket — mostly noise".

Pure composer.  No I/O.  Never raises.  Missing inputs degrade to the
``thin`` basis without crashing.

Contract
--------
    classify_evidence_quality(tickers) -> dict

Returned shape::

    {
      "available":            bool,
      "quality_distribution": {"high": int, "provisional": int, "low": int},
      "weighted_score":       float,   # signed, in [-1, 1]
      "confidence_basis":     "strong_evidence" | "mixed_quality"
                              | "fragile_basket" | "thin",
      "basis_label":          str,
      "per_ticker":           [{symbol, tier, rationale, contribution}, ...],
      "rationale":            str,     # one-line evidence-memo summary
    }
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Quality tier thresholds — pinned to small constants so a constants-
# test can lock any future drift.
# ---------------------------------------------------------------------------

# Magnitude floors.  A |return_5d| below the noise floor drops a
# ticker to low-quality regardless of its validation_quality.
# Between noise and modest, a ticker may still be high-quality but
# only if the alpha signal is clean.
_NOISE_FLOOR_PCT:   float = 0.30     # |ret_5d| below this = low-quality
_MODEST_FLOOR_PCT:  float = 1.00     # alpha + this+ = unambiguously high

# Volume floors.  Low volume turns any evidence into provisional at
# best — a thin tape print is rarely a clean signal.  Numbers mirror
# the volume_ratio convention already on the ticker dict (relative
# to the 20-day average).
_VOLUME_THIN_FLOOR:   float = 0.50   # below = thin → demote
_VOLUME_LIQUID_FLOOR: float = 0.80   # above = healthy

# Contribution weights applied to the signed direction.  Drop-offs
# are aggressive on purpose: a low-quality "support" should NOT drown
# out one clean high-quality alpha hit.
_WEIGHT_HIGH:        float = 1.00
_WEIGHT_PROVISIONAL: float = 0.50
_WEIGHT_LOW:         float = 0.15


QUALITY_TIERS: tuple[str, ...] = ("high", "provisional", "low")


_TIER_LABEL: dict[str, str] = {
    "high":         "High-quality evidence",
    "provisional":  "Provisional evidence",
    "low":          "Low-quality / noisy",
}


# Confidence-basis taxonomy.  Small enum keyed by the distribution
# shape.  Keep it small — the UI renders one of four chips.
CONFIDENCE_BASES: tuple[str, ...] = (
    "strong_evidence",
    "mixed_quality",
    "fragile_basket",
    "thin",
)


_BASIS_LABEL: dict[str, str] = {
    "strong_evidence":  "Strong evidence",
    "mixed_quality":    "Mixed quality",
    "fragile_basket":   "Fragile basket",
    "thin":             "Thin basket",
}


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


def _direction_sign(t: dict) -> float:
    """+1 for thesis-aligned, -1 for contradicts, 0 for flat / unknown.

    Prefers ``validation_quality`` when set; falls back to
    ``direction_tag`` for legacy rows.
    """
    vq = (t.get("validation_quality") or "").strip().lower()
    if vq in ("alpha_support", "beta_aligned"):
        return +1.0
    if vq in ("alpha_contradicts", "beta_contradicts"):
        return -1.0
    if vq in ("drift", "flat", "unavailable"):
        return 0.0
    dt = (t.get("direction_tag") or "").strip().lower()
    if dt.startswith("supports"):
        return +1.0
    if dt.startswith("contradicts"):
        return -1.0
    return 0.0


def _is_alpha_quality(vq: Optional[str]) -> bool:
    return (vq or "").strip().lower() in ("alpha_support", "alpha_contradicts")


def _is_beta_quality(vq: Optional[str]) -> bool:
    return (vq or "").strip().lower() in ("beta_aligned", "beta_contradicts")


def _is_noisy_quality(vq: Optional[str]) -> bool:
    return (vq or "").strip().lower() in ("drift", "flat", "unavailable")


# ---------------------------------------------------------------------------
# Per-ticker classifier
# ---------------------------------------------------------------------------

def _classify_ticker(t: dict) -> tuple[str, str]:
    """Return ``(tier, rationale)`` for a single ticker.

    Tier is ``"high" | "provisional" | "low"``.  The rationale is a
    compact one-line reason a reader can audit.
    """
    if not isinstance(t, dict):
        return "low", "non-dict ticker"

    vq = t.get("validation_quality")
    r5 = _f(t.get("return_5d"))
    vol = _f(t.get("volume_ratio"))
    abs_ret = abs(r5) if r5 is not None else 0.0

    # Outright noise — drift / flat / unavailable signals never earn
    # more than low tier, regardless of how big the raw move looks.
    if _is_noisy_quality(vq):
        return "low", f"{vq or 'flat'} validation signal"

    # Deep noise band — below the floor, no tier upgrade even with
    # clean alpha tagging.  A clean alpha read on a 0.1% move is
    # still just a coin-flip wiggle.
    if r5 is None or abs_ret < _NOISE_FLOOR_PCT:
        reason = (
            "return below noise floor"
            if r5 is not None else "no 5d return"
        )
        return "low", reason

    # Thin volume — demote regardless of validation_quality.  A clean
    # alpha print on a 0.3× volume day is fragile.
    if vol is not None and vol < _VOLUME_THIN_FLOOR:
        return "low", f"thin volume (vol_ratio {vol:.2f})"

    # Alpha + healthy magnitude + adequate liquidity = high quality.
    if (
        _is_alpha_quality(vq)
        and abs_ret >= _MODEST_FLOOR_PCT
        and (vol is None or vol >= _VOLUME_LIQUID_FLOOR)
    ):
        vol_note = (
            f"vol_ratio {vol:.2f}" if vol is not None else "liquidity unknown"
        )
        return "high", (
            f"alpha signal with {abs_ret:.1f}% move on liquid tape "
            f"({vol_note})"
        )

    # Alpha but softer (either modest magnitude or modest liquidity)
    # still clears provisional — it's real evidence, just not decisive.
    if _is_alpha_quality(vq):
        if vol is not None:
            return "provisional", (
                f"alpha signal with modest magnitude / liquidity "
                f"({abs_ret:.1f}%, vol_ratio {vol:.2f})"
            )
        return "provisional", (
            f"alpha signal, modest magnitude ({abs_ret:.1f}%)"
        )

    # Beta-aligned — second-order corroboration at best.  Falls to
    # provisional when the move is clean; demoted to low when tape is
    # marginal.
    if _is_beta_quality(vq):
        if abs_ret >= _MODEST_FLOOR_PCT:
            return "provisional", (
                f"beta signal — corroborates tape, not alpha "
                f"({abs_ret:.1f}% move)"
            )
        return "low", (
            f"beta signal with modest move ({abs_ret:.1f}%) — "
            "not thesis-specific"
        )

    # Legacy row with direction_tag only.  Grade by magnitude alone.
    dt = t.get("direction_tag")
    if isinstance(dt, str) and (dt.startswith("supports") or dt.startswith("contradicts")):
        if abs_ret >= _MODEST_FLOOR_PCT:
            return "provisional", (
                f"legacy direction tag + {abs_ret:.1f}% move — "
                "no alpha/beta decomposition"
            )
        return "low", (
            f"legacy direction tag with marginal {abs_ret:.1f}% move"
        )

    # Nothing else to go on — low.
    return "low", "no validation signal"


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

_TIER_WEIGHT: dict[str, float] = {
    "high":        _WEIGHT_HIGH,
    "provisional": _WEIGHT_PROVISIONAL,
    "low":         _WEIGHT_LOW,
}


def _classify_basis(
    dist: dict[str, int],
    high_net: int,
    total: int,
) -> str:
    """Pick the confidence_basis label from the quality distribution."""
    if total < 2:
        return "thin"
    n_high = dist["high"]
    n_prov = dist["provisional"]
    n_low  = dist["low"]

    if n_high >= 2 and high_net >= 1:
        return "strong_evidence"
    if n_high >= 1 and (n_prov >= 1 or n_low >= 1):
        return "mixed_quality"
    if n_high == 0 and n_prov >= 1 and n_low <= n_prov:
        return "fragile_basket"
    # n_low dominates → thin.
    return "thin"


def _compose_rationale(
    basis: str,
    dist: dict[str, int],
    high_supporters: list[str],
    high_contradicters: list[str],
) -> str:
    """Evidence-memo-style one-liner."""
    total = sum(dist.values())
    if basis == "strong_evidence":
        bits = []
        if high_supporters:
            bits.append(
                f"{dist['high']} high-quality signal(s) "
                f"({', '.join(high_supporters[:3])})"
            )
        else:
            bits.append(f"{dist['high']} high-quality signals")
        if dist["provisional"]:
            bits.append(f"{dist['provisional']} provisional")
        return "Driven by " + "; ".join(bits) + "."

    if basis == "mixed_quality":
        lead = f"{dist['high']} high-quality"
        tail = []
        if dist["provisional"]:
            tail.append(f"{dist['provisional']} provisional")
        if dist["low"]:
            tail.append(f"{dist['low']} low-quality")
        return f"Mixed basis: {lead}" + (
            f" + {', '.join(tail)}" if tail else ""
        ) + "."

    if basis == "fragile_basket":
        return (
            f"Fragile basket — no high-quality evidence; "
            f"{dist['provisional']} provisional reads "
            f"carrying the signal."
        )

    # thin
    return (
        f"Thin basket — {dist['low']}/{total} tickers in the "
        "noise / low-quality band."
    ) if total else "No evidence available."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def classify_evidence_quality(
    tickers: Optional[list[dict]],
) -> dict[str, Any]:
    """Classify each ticker + produce a quality-weighted aggregate.

    Returns a dict with the documented shape (see module docstring).
    Missing / empty / malformed inputs fold to the ``thin`` basis
    with an empty per_ticker list.
    """
    tickers = tickers or []
    if not tickers:
        return _empty_result()

    per_ticker: list[dict] = []
    dist: dict[str, int] = {t: 0 for t in QUALITY_TIERS}
    numerator = 0.0
    denominator = 0.0
    high_supporters: list[str] = []
    high_contradicters: list[str] = []
    high_net = 0
    net_sign_contributions = 0

    for t in tickers:
        if not isinstance(t, dict):
            continue
        tier, rationale = _classify_ticker(t)
        sign = _direction_sign(t)
        weight = _TIER_WEIGHT.get(tier, 0.0)
        contribution = weight * sign

        if tier == "high":
            if sign > 0:
                high_supporters.append(t.get("symbol") or "")
                high_net += 1
            elif sign < 0:
                high_contradicters.append(t.get("symbol") or "")
                high_net -= 1

        dist[tier] += 1
        numerator += contribution
        # Tier weight contributes to the denominator regardless of
        # sign — it calibrates how much the directional evidence in
        # that tier is actually worth.
        denominator += weight
        net_sign_contributions += 1 if sign != 0 else 0

        per_ticker.append({
            "symbol":       t.get("symbol"),
            "tier":         tier,
            "tier_label":   _TIER_LABEL.get(tier, tier),
            "rationale":    rationale,
            "weight":       weight,
            "contribution": round(contribution, 3),
        })

    weighted_score = (
        numerator / denominator if denominator > 0 else 0.0
    )
    weighted_score = max(-1.0, min(1.0, weighted_score))

    basis = _classify_basis(dist, high_net, total=len(tickers))
    rationale = _compose_rationale(
        basis, dist, high_supporters, high_contradicters,
    )

    return {
        "available":            bool(net_sign_contributions),
        "quality_distribution": dist,
        "weighted_score":       round(weighted_score, 3),
        "confidence_basis":      basis,
        "basis_label":           _BASIS_LABEL.get(basis, basis),
        "per_ticker":            per_ticker,
        "rationale":             rationale,
    }


def _empty_result() -> dict[str, Any]:
    return {
        "available":            False,
        "quality_distribution": {t: 0 for t in QUALITY_TIERS},
        "weighted_score":       0.0,
        "confidence_basis":      "thin",
        "basis_label":           _BASIS_LABEL["thin"],
        "per_ticker":            [],
        "rationale":             "No evidence available.",
    }

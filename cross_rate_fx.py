"""
cross_rate_fx.py

Cross-rate FX composer.

Moves beyond the DXY-only FX read by decomposing the dollar move into
the major crosses (EUR, JPY, CNY) and surfacing:

  - per-pair moves with consistent sign convention (USD strength = +)
  - regional stress tags (DM majors, DM safe-haven, EM Asia anchor)
  - dispersion across pairs (all moving together vs. mixed)
  - a driver decomposition: which cross is actually pushing DXY
  - carry-unwind / risk-off fingerprint when safe-haven FX strengthens
    while risk FX weakens

Pure composer.  Inputs come from ``stress_regime.raw`` (populated by
``compute_stress_regime``) OR an explicit ``fx_pack`` dict.  No I/O.

Output shape
------------
    {
      available:        bool,
      stale:            bool,
      pairs: {
        "EURUSD": {label, usd_5d, unit, move_pct_5d, bucket},
        "USDJPY": {...},
        "USDCNY": {...},
      },
      dxy_5d:           float | None,      # passthrough reference
      driver:           "eur" | "jpy" | "cny" | "mixed" | "dxy_only" | None,
      driver_label:     str,
      dispersion:       float | None,      # stdev of USD-strength % moves
      dispersion_tag:   "uniform" | "mixed" | "single_pair",
      regional_stress:  list[str],         # e.g. ["dm_majors", "em_asia"]
      carry_unwind:     bool,              # EM weak + JPY strong pattern
      rationale:        str,
      key_markets:      list[str],
    }

Sign convention
---------------
All pair moves are normalized to **USD-strength % / 5d**.
  EURUSD ↓ (euro weaker)   =>  usd_5d > 0
  USDJPY ↑ (yen weaker)    =>  usd_5d > 0
  USDCNY ↑ (yuan weaker)   =>  usd_5d > 0

So a positive ``usd_5d`` on every pair means uniform USD strength; a
positive on one pair and negative on another means the dollar story is
being driven by ONE cross, not a broad dollar move.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Pair metadata
# ---------------------------------------------------------------------------

PAIR_IDS: tuple[str, ...] = ("EURUSD", "USDJPY", "USDCNY")

_PAIR_META: dict[str, dict[str, str]] = {
    "EURUSD": {
        "label":    "EUR / USD",
        "region":   "dm_majors",
        "polarity": "usd_base",   # EURUSD goes DOWN when USD strengthens
    },
    "USDJPY": {
        "label":    "USD / JPY",
        "region":   "dm_safe_haven",
        "polarity": "usd_quote",  # USDJPY goes UP when USD strengthens
    },
    "USDCNY": {
        "label":    "USD / CNY",
        "region":   "em_asia",
        "polarity": "usd_quote",  # USDCNY goes UP when USD strengthens
    },
}


# ---------------------------------------------------------------------------
# Thresholds (validated in tests)
# ---------------------------------------------------------------------------

# Pair-move bucket floors (% / 5d, absolute).  Calibrated to equity-scale
# FX vol: majors 5d 1-sigma ≈ 1.0–1.5%, USDCNY ≈ 0.4–0.6% (CNY is managed).
_PAIR_FLOOR_PP:      float = 0.30   # below this = flat
_PAIR_MODERATE_PP:   float = 0.80   # mild move
_PAIR_STRONG_PP:     float = 1.80   # strong move
_PAIR_EXTREME_PP:    float = 3.00   # extreme / regime move

# Driver attribution: a single cross qualifies as "the" driver when it
# clears the strong floor AND dominates the next-largest by this margin.
_DRIVER_DOMINANCE_PP: float = 0.60

# Dispersion classifier: stdev of the three USD-strength moves.
_DISPERSION_UNIFORM:  float = 0.50
_DISPERSION_MIXED:    float = 1.50

# Carry-unwind fingerprint: risk FX weak AND JPY strong by this margin.
_CARRY_UNWIND_RISK_PP:  float = 0.80    # positive USD vs risk EM cross
_CARRY_UNWIND_SAFE_PP:  float = -0.50   # USDJPY dropping (yen strong)


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


def _usd_strength(pair_id: str, move_pct_5d: Optional[float]) -> Optional[float]:
    """Normalize a pair's 5d % move to USD-strength % terms.

    EURUSD polarity is "usd_base" — sign flipped.
    USDJPY / USDCNY polarity is "usd_quote" — sign preserved.
    """
    if move_pct_5d is None:
        return None
    meta = _PAIR_META.get(pair_id)
    if not meta:
        return None
    return -float(move_pct_5d) if meta["polarity"] == "usd_base" else float(move_pct_5d)


def _bucket(move_usd_5d: Optional[float]) -> str:
    """Classify a single USD-strength move by magnitude."""
    if move_usd_5d is None:
        return "unavailable"
    mag = abs(move_usd_5d)
    if mag < _PAIR_FLOOR_PP:
        return "flat"
    if mag < _PAIR_MODERATE_PP:
        return "moderate"
    if mag < _PAIR_STRONG_PP:
        return "strong"
    if mag < _PAIR_EXTREME_PP:
        return "very_strong"
    return "extreme"


def _dispersion(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var ** 0.5


def _dispersion_tag(values: list[float]) -> str:
    if len(values) < 2:
        return "single_pair"
    s = _dispersion(values)
    if s is None:
        return "single_pair"
    if s < _DISPERSION_UNIFORM:
        return "uniform"
    if s < _DISPERSION_MIXED:
        return "mixed"
    return "single_pair"  # very high stdev → one outlier driving the number


def _driver(pair_usd_moves: dict[str, float]) -> tuple[Optional[str], str]:
    """Identify which cross is driving the dollar story.

    Returns (driver_pair_id, human_label).  None when no single cross
    clears the strong floor + dominance margin.
    """
    if not pair_usd_moves:
        return None, "no FX data"
    ranked = sorted(
        pair_usd_moves.items(), key=lambda kv: abs(kv[1]), reverse=True,
    )
    top_id, top_move = ranked[0]
    if abs(top_move) < _PAIR_STRONG_PP:
        return None, "no dominant FX driver"
    tag_map = {"EURUSD": "eur", "USDJPY": "jpy", "USDCNY": "cny"}
    if len(ranked) == 1:
        return tag_map.get(top_id, top_id.lower()), f"only {top_id} has data"
    next_move = ranked[1][1]
    if abs(top_move) - abs(next_move) < _DRIVER_DOMINANCE_PP:
        return None, f"no clear driver — {top_id} {top_move:+.1f}% vs {ranked[1][0]} {next_move:+.1f}%"
    return tag_map.get(top_id, top_id.lower()), f"{top_id} {top_move:+.1f}% / 5d"


def _regional_stress(pair_buckets: dict[str, str]) -> list[str]:
    """Return region tags where the pair-bucket is strong or stronger."""
    stress_buckets = {"strong", "very_strong", "extreme"}
    regions: list[str] = []
    for pid, bucket in pair_buckets.items():
        if bucket in stress_buckets:
            region = _PAIR_META.get(pid, {}).get("region")
            if region and region not in regions:
                regions.append(region)
    return regions


def _carry_unwind_flag(pair_usd_moves: dict[str, float]) -> bool:
    """Risk FX weakening (USD strong vs EM) while JPY strengthens — classic carry unwind."""
    risk_moves = [
        pair_usd_moves.get("USDCNY"),
    ]
    safe_move = pair_usd_moves.get("USDJPY")
    if safe_move is None:
        return False
    risk_ok = any(
        m is not None and m >= _CARRY_UNWIND_RISK_PP for m in risk_moves
    )
    safe_ok = safe_move <= _CARRY_UNWIND_SAFE_PP
    return bool(risk_ok and safe_ok)


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def _rationale(
    driver: Optional[str],
    driver_label: str,
    dispersion_tag: str,
    regional_stress: list[str],
    carry_unwind: bool,
    dxy_5d: Optional[float],
) -> str:
    bits: list[str] = []
    if dxy_5d is not None:
        bits.append(f"DXY {dxy_5d:+.1f}% / 5d")
    if driver:
        bits.append(f"driven by {driver_label}")
    else:
        bits.append(driver_label or "no single driver")
    if dispersion_tag == "uniform":
        bits.append("broad USD move (crosses aligned)")
    elif dispersion_tag == "single_pair":
        bits.append("single-cross story (not a broad USD move)")
    if regional_stress:
        bits.append("regional stress: " + ", ".join(regional_stress))
    if carry_unwind:
        bits.append("carry-unwind fingerprint (EM weak + JPY bid)")
    return "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_cross_rate_fx(
    stress_regime: Optional[dict] = None,
    fx_pack: Optional[dict] = None,
) -> dict:
    """Build the cross-rate FX decomposition block.

    Prefers ``fx_pack`` (explicit override) when supplied, otherwise
    reads from ``stress_regime.raw`` keys ``eurusd_5d / usdjpy_5d /
    usdcny_5d`` populated by compute_stress_regime.

    Returns ``{}`` when no FX pack can be assembled (no stress_regime,
    no override, no DXY either) so callers can skip rendering.  When
    only DXY is present and crosses are missing, returns an available
    block with ``stale=True`` and empty ``pairs`` so the UI can at
    least surface the dollar move.
    """
    raw = (stress_regime or {}).get("raw") or {}
    pack = fx_pack or {}

    def _pick(pack_key: str, raw_key: str) -> Optional[float]:
        if pack_key in pack:
            return _f(pack[pack_key])
        return _f(raw.get(raw_key))

    raw_pairs: dict[str, Optional[float]] = {
        "EURUSD": _pick("EURUSD", "eurusd_5d"),
        "USDJPY": _pick("USDJPY", "usdjpy_5d"),
        "USDCNY": _pick("USDCNY", "usdcny_5d"),
    }

    # DXY comes either from the explicit pack or stress_regime.raw
    dxy_5d = _pick("DXY", "haven_dollar_5d")
    if dxy_5d is None:
        # Fallback: safe_haven detail has the Dollar 5d move too.
        haven = (((stress_regime or {}).get("detail") or {}).get("safe_haven") or {}).get("assets") or {}
        dxy_5d = _f(haven.get("Dollar"))

    # Normalize each pair to USD-strength direction.
    usd_moves: dict[str, float] = {}
    pair_output: dict[str, dict] = {}
    for pid in PAIR_IDS:
        raw_move = raw_pairs[pid]
        meta = _PAIR_META[pid]
        usd_mv = _usd_strength(pid, raw_move)
        pair_output[pid] = {
            "label":          meta["label"],
            "move_pct_5d":    round(raw_move, 3) if raw_move is not None else None,
            "usd_5d":         round(usd_mv, 3)  if usd_mv   is not None else None,
            "unit":           "%",
            "region":         meta["region"],
            "bucket":         _bucket(usd_mv),
            "available":      usd_mv is not None,
        }
        if usd_mv is not None:
            usd_moves[pid] = usd_mv

    any_pair = bool(usd_moves)
    if not any_pair and dxy_5d is None:
        return {}

    disp = _dispersion(list(usd_moves.values())) if usd_moves else None
    disp_tag = _dispersion_tag(list(usd_moves.values()))
    buckets = {pid: entry["bucket"] for pid, entry in pair_output.items()}
    regional = _regional_stress(buckets)
    driver_id, driver_label = _driver(usd_moves)
    carry = _carry_unwind_flag(usd_moves)

    rationale = _rationale(
        driver_id, driver_label, disp_tag, regional, carry, dxy_5d,
    )

    key_markets = ["DXY"] + list(PAIR_IDS)
    if carry:
        key_markets.append("GC")  # gold as companion haven

    return {
        "available":        any_pair,
        "stale":            not any_pair,
        "pairs":            pair_output,
        "dxy_5d":           round(dxy_5d, 3) if dxy_5d is not None else None,
        "driver":           driver_id or ("dxy_only" if dxy_5d is not None and not any_pair else None),
        "driver_label":     driver_label,
        "dispersion":       round(disp, 3) if disp is not None else None,
        "dispersion_tag":   disp_tag,
        "regional_stress":  regional,
        "carry_unwind":     carry,
        "rationale":        rationale,
        "key_markets":      key_markets,
    }

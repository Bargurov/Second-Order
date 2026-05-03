"""
country_fx_passthrough.py

Per-country FX + commodity passthrough helper.

Given a country and a cross-rate FX pack (as produced by cross_rate_fx),
return how much of the dollar/commodity move is actually flowing through
that country's external balance.

Two axes combine into a net "passthrough stress" number:

  1. FX passthrough:
       stress = |primary_pair_usd_strength_5d| * fx_beta
     where primary_pair is the cross most correlated with the local FX
     (USDCNY for EM Asia names, EURUSD for Eurozone-linked, DXY for
     EM LatAm / EMEA where no better proxy exists).  Pegged regimes
     (GCC, HKD, etc.) carry a beta far below 1 so a DXY spike does not
     inflate their stress reading.

  2. Commodity passthrough:
       stress = sign-adjusted commodity move × net-exposure weight
     Oil exporters get a NEGATIVE passthrough score when crude rallies
     (their external balance IMPROVES — less vulnerable); importers get
     a positive score.

The returned dict is compact (~5 fields) so callers can nest it under
terms_of_trade exposures or reserve_stress country entries without a
schema change.

Pure composer.  No I/O.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Country → primary FX pair + beta + region
# ---------------------------------------------------------------------------
#
# ``primary`` is the cross whose move we use as the local-FX proxy.
#   - USDCNY anchors EM Asia names (KRW, TWD, PHP, IDR, SGD often follow)
#   - EURUSD anchors Eurozone + periphery + NOK / HUF
#   - USDJPY is its own proxy for JPY
#   - DXY is the fallback for broad-EM names without a clean cross proxy
#
# ``beta`` is the 5y rule-of-thumb sensitivity of the country's external
# balance to a 1% move in the primary pair (USD strength).  Values:
#   0.2-0.4 : pegged / strongly-managed regimes (GCC, CHF, HKD)
#   0.5-0.7 : DM low-beta (CAD, AUD, NOK in normal regimes)
#   0.8-1.0 : typical EM
#   1.0-1.3 : fragile EM (high external debt, thin reserves)

_COUNTRY_FX: dict[str, dict] = {
    # --- DM majors ----------------------------------------------------
    "Eurozone":      {"primary": "EURUSD", "beta": 1.0, "region": "DM Europe"},
    "Japan":         {"primary": "USDJPY", "beta": 1.0, "region": "DM Asia"},
    "South Korea":   {"primary": "USDCNY", "beta": 0.7, "region": "EM Asia"},
    "Switzerland":   {"primary": "EURUSD", "beta": 0.4, "region": "DM Europe"},
    "Canada":        {"primary": "DXY",    "beta": 0.7, "region": "DM Americas"},
    "Norway":        {"primary": "EURUSD", "beta": 0.6, "region": "DM Europe"},
    "Australia":     {"primary": "USDCNY", "beta": 0.8, "region": "DM Asia-Pac"},

    # --- EM Asia -------------------------------------------------------
    "China":         {"primary": "USDCNY", "beta": 1.0, "region": "EM Asia"},
    "India":         {"primary": "DXY",    "beta": 0.9, "region": "EM Asia"},
    "Indonesia":     {"primary": "USDCNY", "beta": 0.9, "region": "EM Asia"},
    "Philippines":   {"primary": "USDCNY", "beta": 0.8, "region": "EM Asia"},
    "Taiwan":        {"primary": "USDCNY", "beta": 0.6, "region": "EM Asia"},
    "Singapore":     {"primary": "USDCNY", "beta": 0.5, "region": "EM Asia"},
    "Pakistan":      {"primary": "DXY",    "beta": 1.1, "region": "EM Asia"},
    "Sri Lanka":     {"primary": "DXY",    "beta": 1.1, "region": "EM Asia"},

    # --- EM EMEA / frontier -------------------------------------------
    "Turkey":        {"primary": "DXY",    "beta": 1.3, "region": "EM EMEA"},
    "Egypt":         {"primary": "DXY",    "beta": 1.1, "region": "EM EMEA"},
    "South Africa":  {"primary": "DXY",    "beta": 1.2, "region": "EM EMEA"},
    "Russia":        {"primary": "DXY",    "beta": 1.0, "region": "EM EMEA"},
    "Hungary":       {"primary": "EURUSD", "beta": 0.9, "region": "EM EMEA"},
    "North Africa":  {"primary": "DXY",    "beta": 1.0, "region": "EM EMEA"},
    "Zambia":        {"primary": "DXY",    "beta": 1.0, "region": "EM EMEA"},

    # --- LatAm ---------------------------------------------------------
    "Argentina":     {"primary": "DXY",    "beta": 1.3, "region": "LatAm"},
    "Brazil":        {"primary": "DXY",    "beta": 0.9, "region": "LatAm"},
    "Chile":         {"primary": "DXY",    "beta": 0.8, "region": "LatAm"},
    "Peru":          {"primary": "DXY",    "beta": 0.8, "region": "LatAm"},
    "Colombia":      {"primary": "DXY",    "beta": 0.9, "region": "LatAm"},

    # --- GCC (pegged regimes) -----------------------------------------
    "Saudi Arabia":  {"primary": "DXY",    "beta": 0.3, "region": "GCC"},
    "UAE":           {"primary": "DXY",    "beta": 0.3, "region": "GCC"},
    "Qatar":         {"primary": "DXY",    "beta": 0.3, "region": "GCC"},
}


# ---------------------------------------------------------------------------
# Country → commodity exposure
# ---------------------------------------------------------------------------
#
# Sign convention: +N = net EXPORTER of that commodity (benefits from
# price rise).  -N = net IMPORTER (hurts on price rise).  Magnitude is
# how central the commodity is to the external balance (rough tier 0-3).

_COUNTRY_COMMODITY: dict[str, dict] = {
    "Saudi Arabia": {"oil": +3, "metals":  0},
    "Norway":       {"oil": +2, "metals":  0},
    "Canada":       {"oil": +2, "metals": +1},
    "Russia":       {"oil": +3, "metals": +1},
    "Brazil":       {"oil": +1, "metals": +2},
    "UAE":          {"oil": +3, "metals":  0},
    "Qatar":        {"oil": +3, "metals":  0},
    "Colombia":     {"oil": +2, "metals":  0},

    "Japan":        {"oil": -2, "metals": -1},
    "South Korea":  {"oil": -2, "metals": -1},
    "India":        {"oil": -3, "metals":  0},
    "Turkey":       {"oil": -3, "metals": -1},
    "Eurozone":     {"oil": -2, "metals": -1},
    "Philippines":  {"oil": -2, "metals":  0},
    "Pakistan":     {"oil": -2, "metals":  0},
    "Sri Lanka":    {"oil": -2, "metals":  0},
    "North Africa": {"oil": -2, "metals":  0},

    "Chile":        {"oil": -1, "metals": +3},   # copper exporter
    "Peru":         {"oil": -1, "metals": +3},
    "Australia":    {"oil":  0, "metals": +3},
    "Zambia":       {"oil": -1, "metals": +3},

    # Default when unknown: net zero.
}


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# Stress label bands for the combined passthrough score.
_STRESS_MILD_FLOOR:     float = 0.6
_STRESS_MODERATE_FLOOR: float = 1.4
_STRESS_ACUTE_FLOOR:    float = 2.5


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


def _pair_usd_strength(pair_id: str, fx_pack: Optional[dict]) -> Optional[float]:
    """Return USD-strength % from the cross_rate_fx pack for a given pair.

    Falls back to DXY if the requested pair is unavailable.
    """
    if not fx_pack:
        return None
    pairs = fx_pack.get("pairs") or {}
    entry = pairs.get(pair_id)
    if entry and entry.get("usd_5d") is not None:
        return _f(entry["usd_5d"])
    # Fallback: the aggregate dollar move.
    return _f(fx_pack.get("dxy_5d"))


def _stress_label(score: float) -> str:
    mag = abs(score)
    if mag >= _STRESS_ACUTE_FLOOR:
        return "acute"
    if mag >= _STRESS_MODERATE_FLOOR:
        return "moderate"
    if mag >= _STRESS_MILD_FLOOR:
        return "mild"
    return "quiet"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_country_passthrough(
    country: str,
    fx_pack: Optional[dict] = None,
    crude_5d: Optional[float] = None,
    gold_5d: Optional[float] = None,
) -> dict:
    """Compute FX + commodity passthrough stress for a single country.

    Returns (always a dict, never None) with:
      primary_pair:  str | None       — the cross used as local-FX proxy
      fx_beta:       float | None
      fx_move_5d:    float | None     — USD-strength on the primary pair
      fx_stress:     float | None     — |usd_5d| * beta (positive number)
      commodity_stress: float | None  — sign-adjusted, negative means beneficial
      passthrough_total: float | None — fx_stress + max(commodity_stress, 0)
      stress_label:  "quiet" | "mild" | "moderate" | "acute" | "unknown"
      region:        str | None
      available:     bool
    """
    meta = _COUNTRY_FX.get(country)
    if not meta:
        return {
            "country":          country,
            "primary_pair":     None,
            "fx_beta":          None,
            "fx_move_5d":       None,
            "fx_stress":        None,
            "commodity_stress": None,
            "passthrough_total": None,
            "stress_label":     "unknown",
            "region":           None,
            "available":        False,
        }

    primary = meta["primary"]
    beta = float(meta["beta"])
    region = meta["region"]

    usd_5d = _pair_usd_strength(primary, fx_pack)
    fx_stress = None
    if usd_5d is not None:
        fx_stress = round(abs(usd_5d) * beta, 3)

    # Commodity passthrough: sign-adjusted.  Positive = harmful
    # (importer on rising price OR exporter on falling price).
    cmdty_meta = _COUNTRY_COMMODITY.get(country, {})
    oil_score = cmdty_meta.get("oil", 0)
    metals_score = cmdty_meta.get("metals", 0)

    commodity_stress_raw = 0.0
    commodity_terms: list[str] = []
    if crude_5d is not None and oil_score != 0:
        # Exporter (oil_score > 0) benefits when crude rises → stress is
        # NEGATIVE (relief).  Importer (oil_score < 0) harmed when crude
        # rises → stress is POSITIVE.
        contribution = -oil_score * (crude_5d / 5.0)  # normalized to 5y 1-sigma crude
        commodity_stress_raw += contribution
        commodity_terms.append(f"oil {crude_5d:+.1f}%")
    if gold_5d is not None and metals_score != 0:
        contribution = -metals_score * (gold_5d / 3.0)   # 3% = ~1-sigma gold
        commodity_stress_raw += contribution
        commodity_terms.append(f"gold/metals {gold_5d:+.1f}%")
    commodity_stress = round(commodity_stress_raw, 3) if (crude_5d is not None or gold_5d is not None) else None

    # Combined passthrough: FX always adds to stress; commodity only adds
    # when it worsens the external balance (positive contribution).  A
    # benign commodity move is surfaced as a negative commodity_stress
    # but does NOT reduce the FX-driven stress score — those are two
    # distinct pressure sources a macro desk tracks independently.
    total = None
    if fx_stress is not None or commodity_stress is not None:
        total = (fx_stress or 0.0) + max(commodity_stress or 0.0, 0.0)
        total = round(total, 3)

    return {
        "country":           country,
        "primary_pair":      primary,
        "fx_beta":           beta,
        "fx_move_5d":        round(usd_5d, 3) if usd_5d is not None else None,
        "fx_stress":         fx_stress,
        "commodity_stress":  commodity_stress,
        "passthrough_total": total,
        "stress_label":      _stress_label(total) if total is not None else "unknown",
        "region":            region,
        "commodity_terms":   commodity_terms,
        "available":         fx_stress is not None or commodity_stress is not None,
    }


def enrich_country_exposures(
    exposures: list[dict],
    fx_pack: Optional[dict] = None,
    crude_5d: Optional[float] = None,
    gold_5d: Optional[float] = None,
) -> list[dict]:
    """Add a ``passthrough`` sub-dict to each exposure entry, in place-like.

    Returns a NEW list — does not mutate the input.  Exposures without a
    known country mapping carry a ``passthrough`` entry with
    ``available=False`` so the UI can uniformly key on it.
    """
    out: list[dict] = []
    for e in exposures or []:
        if not isinstance(e, dict):
            out.append(e)
            continue
        country = e.get("country", "")
        passthrough = compute_country_passthrough(
            country, fx_pack=fx_pack, crude_5d=crude_5d, gold_5d=gold_5d,
        )
        new_entry = dict(e)
        new_entry["passthrough"] = passthrough
        out.append(new_entry)
    return out


# ---------------------------------------------------------------------------
# Aggregations useful for reserve_stress / terms_of_trade callers
# ---------------------------------------------------------------------------

def em_fx_pressure(fx_pack: Optional[dict]) -> dict:
    """Aggregate EM-FX stress from USDCNY + a DXY-broadness check.

    Returns a compact dict with ``fired`` bool and a score (0-100 scale)
    so reserve_stress can treat "EM FX bleeding" as its own driver.

    Rule:
      - If USDCNY usd_5d >= 0.50% (CNY is tightly managed, anything
        >0.50/5d is notable): fire, score proportional to magnitude.
      - Boost with +20 points if the FX pack dispersion is "uniform"
        (broad USD strength, no single-pair story).
      - Boost with +15 if the carry_unwind flag is set.
    """
    out = {
        "fired":        False,
        "score":        0,
        "basis":        "",
    }
    if not fx_pack or not isinstance(fx_pack, dict):
        return out

    pairs = fx_pack.get("pairs") or {}
    cny = _f((pairs.get("USDCNY") or {}).get("usd_5d"))
    eur = _f((pairs.get("EURUSD") or {}).get("usd_5d"))
    jpy = _f((pairs.get("USDJPY") or {}).get("usd_5d"))

    # Mean absolute USD strength across available pairs — used to gate the
    # "uniform" dispersion bonus so a uniform-but-tiny move (all pairs at
    # +0.1%) does not fire an EM-FX-stress alert.
    mags = [abs(v) for v in (cny, eur, jpy) if v is not None]
    mean_abs_move = (sum(mags) / len(mags)) if mags else 0.0

    bits: list[str] = []
    score = 0.0
    if cny is not None and cny >= 0.50:
        # Score grows 20 per 0.5% move, capped.
        score += min(60.0, 20.0 * (cny / 0.5))
        bits.append(f"USDCNY +{cny:.2f}%/5d")

    # Uniform broad-USD bonus: requires an actually meaningful move, not
    # just low dispersion at near-zero.
    if fx_pack.get("dispersion_tag") == "uniform" and mean_abs_move >= 0.50:
        score += 20.0
        bits.append("broad USD strength")

    if fx_pack.get("carry_unwind"):
        score += 15.0
        bits.append("carry unwind")

    out["fired"] = score >= 20.0
    out["score"] = int(round(min(score, 100.0)))
    out["basis"] = "; ".join(bits) if bits else ""
    return out

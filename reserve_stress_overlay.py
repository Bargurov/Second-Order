"""
reserve_stress_overlay.py

Current Account + FX Reserve Stress Overlay.

What it adds
------------
The terms-of-trade layer answers "which countries live or die by this
commodity / FX move".  This overlay answers the adjacent institutional
question: *given the current macro tape, which external balances are
actually under stress right now, and which ones are insulated?*

Specifically it scores whether the event increases pressure on:

  * current-account-deficit importers
  * weak-reserve / weak-funding EMs
  * external-financing-sensitive regions

Reuses the existing data path — it's a pure composer that takes the
already-computed ``terms_of_trade`` block, the rates context and the
stress regime.  No network calls, no new providers.

Output shape
------------
    {
      "vulnerable": [
          {"country", "region", "vulnerability",
           "drivers": ["dollar_rally", "oil_squeeze"],
           "rationale": "..."},
          ...
      ],
      "insulated": [
          {"country", "region", "strength",
           "drivers": ["reserve_buffer", "current_account_surplus"],
           "rationale": "..."},
          ...
      ],
      "dominant_channel":       one of _CHANNEL_IDS,
      "dominant_channel_label": str,
      "pressure_score":         int  0..100  — overall stress intensity
      "pressure_label":         one of {"elevated", "moderate", "contained"},
      "rationale":              str  — compact 1-2 line institutional read
      "key_markets":            list[str]   — proxies that should confirm/challenge
      "available":              bool
      "stale":                  bool
      "signals": {
          "crude_5d":           float | None,
          "dxy_5d":             float | None,
          "credit_spread_5d":   float | None,
          "real_yield_5d":      float | None,
          "stress_regime":      str | None,
          "matched_channel":    str,
          "thresholds":         str,
      },
    }

Degrade rules
-------------
* No terms-of-trade, no rates, no stress → ``{}`` (caller skips rendering)
* Partial inputs → ``stale=True`` but block still populated with whatever
  signal is available
* Old ``.stale`` flags on upstream inputs propagate forward — this layer
  never manufactures freshness it doesn't have

Scoring weights
---------------
Weights + thresholds are calibrated in
``tools/reserve_stress_overlay_validation.py`` against a representative
scenario bank (oil shock, dollar funding squeeze, disinflation, mixed
benign).  See the validation script for the grounded numbers.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------

_CHANNEL_IDS: tuple[str, ...] = (
    "dual_oil_dollar",        # crude + dollar both up — classic importer squeeze
    "oil_import_squeeze",     # crude up, dollar flat — commodity-led pressure
    "usd_funding_stress",     # dollar up, no commodity catalyst — funding shock
    "food_importer_stress",   # food / grain theme
    "commodity_exporter_cushion",  # crude/metal down OR dollar falling — relief
    "mixed",
    "none",
)

_CHANNEL_LABEL: dict[str, str] = {
    "dual_oil_dollar":           "Oil + dollar double squeeze",
    "oil_import_squeeze":        "Oil importers under pressure",
    "usd_funding_stress":        "USD funding stress",
    "food_importer_stress":      "Food importers exposed",
    "commodity_exporter_cushion": "Commodity exporters cushioned",
    "mixed":                     "Mixed external-balance signal",
    "none":                      "No clear external-balance stress",
}

# Canonical liquid markets / proxies per channel.  These are the
# instruments a desk would watch to confirm or challenge the read.
_CHANNEL_MARKETS: dict[str, list[str]] = {
    "dual_oil_dollar":            ["CL", "DXY", "EMB", "EEM", "TUR"],
    "oil_import_squeeze":         ["CL", "EMB", "INDA", "EWJ", "TUR"],
    "usd_funding_stress":         ["DXY", "EMB", "EEM", "TUR", "TLT"],
    "food_importer_stress":       ["WEAT", "EGPT", "EEM", "DXY"],
    "commodity_exporter_cushion": ["CL", "EWW", "EWZ", "EWC", "DXY"],
    "mixed":                      ["DXY", "EMB", "EEM", "CL"],
    "none":                       ["DXY", "EMB", "EEM", "CL"],
}


# ---------------------------------------------------------------------------
# Country taxonomy — reserve-vulnerability and insulation scores
# ---------------------------------------------------------------------------
#
# Each country carries two opinionated weights on [0, 10]:
#
#   vulnerability — how fragile the external balance is right now
#   insulation    — how much buffer (reserves / surplus / anchor) absorbs
#                   a shock before it reaches the real economy
#
# These are NOT numerically continuous — they're bucketed by what the
# macro desk actually watches.  A change requires re-running
# tools/reserve_stress_overlay_validation.py.
#
# The list is deliberately short (~20 names) so the output stays dense
# and institutional.  Adding a country here requires a one-line
# rationale that a human reader can verify from public data.

_VULNERABLE_UNIVERSE: list[dict] = [
    {"country": "Turkey",       "region": "EM EMEA",
     "vulnerability": 10,
     "rationale": "thin FX reserves, high external debt, CBRT has repeatedly burned buffers defending the lira"},
    {"country": "Argentina",    "region": "LatAm",
     "vulnerability": 10,
     "rationale": "chronic reserve scarcity, dollar-indexed liabilities, cyclical IMF programmes"},
    {"country": "Egypt",        "region": "EM EMEA",
     "vulnerability": 9,
     "rationale": "wheat + fuel import bill, structural dollar shortage, Gulf-deposit dependent"},
    {"country": "Pakistan",     "region": "EM Asia",
     "vulnerability": 9,
     "rationale": "weeks-of-imports reserve cover, IMF-programme dependent, acute FX rationing history"},
    {"country": "Sri Lanka",    "region": "EM Asia",
     "vulnerability": 8,
     "rationale": "post-default rebuild, tourism-reliant FX inflows, slim reserve cushion"},
    {"country": "South Africa", "region": "EM EMEA",
     "vulnerability": 7,
     "rationale": "twin deficits, rand historically leads the EM-FX selloff on DXY spikes"},
    {"country": "Turkey (corp FX)", "region": "EM EMEA",
     "vulnerability": 7,
     "rationale": "corporate dollar debt concentrated in unhedged borrowers; second-order to sovereign stress"},
    {"country": "Indonesia",    "region": "EM Asia",
     "vulnerability": 6,
     "rationale": "current account sensitive to DXY via portfolio outflows; reserves adequate but not deep"},
    {"country": "India",        "region": "EM Asia",
     "vulnerability": 6,
     "rationale": "~85% of crude is imported; twin-deficit sensitivity tightens on any oil rally"},
    {"country": "Hungary",      "region": "EM EMEA",
     "vulnerability": 6,
     "rationale": "external debt share high for CEE; HUF tracks bund-bund spread + funding stress"},
    {"country": "Colombia",     "region": "LatAm",
     "vulnerability": 5,
     "rationale": "current-account deficit larger than peers; COP responds quickly to oil + DXY"},
    {"country": "Chile (import)","region": "LatAm",
     "vulnerability": 4,
     "rationale": "oil importer with normally-liquid FX; tightens on dual-squeeze but buffered vs peers"},
    {"country": "Eurozone periphery", "region": "DM Europe",
     "vulnerability": 4,
     "rationale": "structurally energy-short; not a reserve story, but external balance is oil-sensitive"},
]

_INSULATED_UNIVERSE: list[dict] = [
    {"country": "Saudi Arabia", "region": "GCC",
     "insulation": 10,
     "rationale": "marginal-barrel oil exporter with deep reserves and SAMA buffer; fiscal breakeven absorbs shock"},
    {"country": "UAE",          "region": "GCC",
     "insulation": 10,
     "rationale": "surplus exporter with one of the largest sovereign wealth funds; dirham peg backstopped"},
    {"country": "Norway",       "region": "DM Europe",
     "insulation": 10,
     "rationale": "oil-export windfall mechanism + GPFG sovereign wealth buffer absorbs nearly all spillover"},
    {"country": "Switzerland",  "region": "DM Europe",
     "insulation": 9,
     "rationale": "reserve-currency shelter; SNB balance sheet dominates FX transmission"},
    {"country": "Singapore",    "region": "DM Asia-Pac",
     "insulation": 9,
     "rationale": "structural current-account surplus; MAS runs a managed exchange-rate band"},
    {"country": "Taiwan",       "region": "DM Asia-Pac",
     "insulation": 9,
     "rationale": "very large FX reserves relative to imports; persistent external surplus"},
    {"country": "China",        "region": "EM Asia",
     "insulation": 8,
     "rationale": "managed-FX regime backed by ~$3T reserves; shock absorbed by PBoC fix not EM-FX spot"},
    {"country": "Japan",        "region": "DM Asia",
     "insulation": 8,
     "rationale": "creditor nation with large external assets; BoJ/MoF can intervene from strength"},
    {"country": "Qatar",        "region": "GCC",
     "insulation": 9,
     "rationale": "LNG export mechanism + QIA sovereign buffer; dollar peg comfortably funded"},
    {"country": "Brazil (oil)", "region": "LatAm",
     "insulation": 6,
     "rationale": "Petrobras-linked terms-of-trade tailwind on crude; the oil channel is a cushion, not a buffer"},
    {"country": "Canada",       "region": "DM Americas",
     "insulation": 6,
     "rationale": "energy is the swing component of the trade balance; CAD rallies with crude"},
    {"country": "Chile (metals)", "region": "LatAm",
     "insulation": 5,
     "rationale": "copper export concentration; buffered on metal rallies, not on DXY spikes"},
]


# ---------------------------------------------------------------------------
# Scoring weights — CALIBRATED in tools/reserve_stress_overlay_validation.py
# ---------------------------------------------------------------------------
#
# These are the only tunable numbers in this module.  Changing any of
# them requires re-running the validation script (it asserts the
# scenario bank still lands in the expected pressure buckets) and
# updating the scenario table in the script's docstring.

# Dollar rally thresholds (DXY 5d move, %):
_DXY_MODERATE_MOVE_PCT: float = 0.5
_DXY_STRONG_MOVE_PCT:   float = 1.0
_DXY_EXTREME_MOVE_PCT:  float = 2.0

# Crude rally thresholds (WTI 5d move, %):
_CRUDE_MODERATE_MOVE_PCT: float = 3.0
_CRUDE_STRONG_MOVE_PCT:   float = 5.0

# Credit / real-yield thresholds
_CREDIT_WIDENING_5D_PCT: float = 0.5
_REAL_YIELD_RISE_5D_PCT: float = 0.2   # TIP falling → real yields rising

# ----- Per-signal pressure contribution (sum capped at 100) -----
#
# DXY tiers are NON-STACKING — only the highest tier the 5d move
# clears contributes.  The old design stacked moderate + strong +
# extreme (15 + 15 + 20 = 50) on a single 2.5% print, letting one
# signal consume half the pressure budget.  A flat tiered lookup
# keeps a strong dollar decisive without letting it dominate the
# ceiling alone.
_W_DXY_MODERATE:      int = 15   # dxy ≥ 0.5%
_W_DXY_STRONG:        int = 25   # dxy ≥ 1.0% (replaces, not stacks on, moderate)
_W_DXY_EXTREME:       int = 35   # dxy ≥ 2.0% (replaces strong)

_W_CREDIT_WIDENING:   int = 20
_W_CRUDE_OIL_THEME:   int = 20
_W_CRUDE_STRONG:      int = 5    # stacks on oil_theme when crude ≥ 5%
_W_REAL_YIELD_RISE:   int = 15
_W_DUAL_SQUEEZE:      int = 15

# Systemic-stress meta-confirmation bonus — fires ONLY when the
# stress classifier returns the exact "Systemic Stress" regime AND
# signals.credit_widening is true.  It is no longer triggered by
# generic substring matches on "stress" or "risk-off" labels, so
# Geopolitical Stress (which by construction has
# credit_widening=False) never adds pressure here.
_W_STRESS_REGIME_HIT: int = 10

# Bucketing
_PRESSURE_ELEVATED_MIN: int = 60
_PRESSURE_MODERATE_MIN: int = 30


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


def _dxy_5d_from_stress(stress_regime: Optional[dict]) -> Optional[float]:
    """Pull DXY 5d move from the safe-haven component of the stress block."""
    if not isinstance(stress_regime, dict):
        return None
    detail = stress_regime.get("detail") or {}
    safe_haven = detail.get("safe_haven") if isinstance(detail, dict) else None
    if not isinstance(safe_haven, dict):
        return None
    assets = safe_haven.get("assets") or {}
    if not isinstance(assets, dict):
        return None
    return _f(assets.get("Dollar"))


def _credit_spread_5d_from_stress(stress_regime: Optional[dict]) -> Optional[float]:
    """Pull credit spread 5d move (SHY - HYG) from stress detail."""
    if not isinstance(stress_regime, dict):
        return None
    detail = stress_regime.get("detail") or {}
    credit = detail.get("credit") if isinstance(detail, dict) else None
    if not isinstance(credit, dict):
        return None
    return _f(credit.get("spread_5d"))


def _stress_regime_label(stress_regime: Optional[dict]) -> Optional[str]:
    if not isinstance(stress_regime, dict):
        return None
    val = stress_regime.get("regime")
    return str(val) if val else None


def _real_yield_5d_from_rates(rates_context: Optional[dict]) -> Optional[float]:
    """Derive a 5d real-yield change from the rates context.

    ``compute_rates_context`` exposes TIP (real-yield proxy) 5d change.
    TIP prices move inversely with real yields, so a falling TIP = rising
    real yields.  We return the *real-yield* move, not the price move.
    """
    if not isinstance(rates_context, dict):
        return None
    real_proxy = rates_context.get("real_proxy") or {}
    tip_5d = _f(real_proxy.get("change_5d"))
    if tip_5d is None:
        return None
    return -tip_5d  # invert price → yield


def _credit_widening_active(
    stress_regime: Optional[dict],
    credit_spread_5d: Optional[float],
) -> bool:
    """True when credit is actually widening, per the structured signal.

    Prefers the boolean flag ``signals.credit_widening`` that
    ``market_check.compute_stress_regime`` sets from the HY/SHY 5d
    divergence.  Falls back to the numeric spread when the signals
    dict is absent or stubbed (tests, validation).  Both paths read
    structured payload fields — no label scraping.
    """
    if isinstance(stress_regime, dict):
        signals = stress_regime.get("signals") or {}
        if isinstance(signals, dict) and signals.get("credit_widening"):
            return True
    if credit_spread_5d is not None and credit_spread_5d >= _CREDIT_WIDENING_5D_PCT:
        return True
    return False


def _stress_regime_confirms_funding_pressure(
    stress_regime: Optional[dict],
) -> bool:
    """True iff the classifier independently reports Systemic Stress
    *and* its credit-widening signal is firing.

    This replaces the old substring match on "stress" / "risk-off" /
    "funding".  That match also swept in the "Geopolitical Stress"
    regime, which ``market_check.classify_regime`` explicitly defines
    as VIX + safe-haven flows with ``credit_widening == False`` — so
    it should never add reserve-funding pressure here.

    Uses only structured payload fields:

      * ``regime`` — exact enum match against the canonical label
        ``market_check.compute_stress_regime`` emits.  No substring
        matching: "Risk-off / funding stress" from a mock does not
        match "Systemic Stress", by design.
      * ``signals.credit_widening`` — boolean set by the classifier
        from the same HY/SHY spread this module already reads.

    Both conditions must hold, so the bonus is a genuine
    cross-confirmation of systemic-stress pricing, not a label echo.
    """
    if not isinstance(stress_regime, dict):
        return False
    regime = (stress_regime.get("regime") or "").strip()
    if regime != "Systemic Stress":
        return False
    signals = stress_regime.get("signals") or {}
    if not isinstance(signals, dict):
        return False
    return bool(signals.get("credit_widening"))


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------


def _resolve_channel(
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
    matched_theme: str,
) -> tuple[str, str]:
    """Pick the dominant stress channel for the overlay.

    Returns (channel_id, one-line channel basis).
    """
    theme_oil = matched_theme in ("oil", "gas")
    theme_food = matched_theme == "food"
    theme_metal = matched_theme == "metal"

    crude_up   = crude_5d is not None and crude_5d >=  _CRUDE_MODERATE_MOVE_PCT
    crude_down = crude_5d is not None and crude_5d <= -_CRUDE_MODERATE_MOVE_PCT
    dxy_up     = dxy_5d is not None and dxy_5d >=  _DXY_MODERATE_MOVE_PCT
    dxy_down   = dxy_5d is not None and dxy_5d <= -_DXY_MODERATE_MOVE_PCT
    dxy_strong = dxy_5d is not None and dxy_5d >= _DXY_STRONG_MOVE_PCT

    # Dual squeeze wins first: crude + dollar both rallying is the
    # classic external-balance shock on net importers.
    if crude_up and dxy_up:
        return "dual_oil_dollar", (
            f"crude +{crude_5d:.1f}/5d and DXY +{dxy_5d:.2f}/5d — "
            f"double squeeze on net importers"
        )

    # Pure oil-importer squeeze
    if crude_up and (theme_oil or matched_theme == "none"):
        return "oil_import_squeeze", (
            f"crude +{crude_5d:.1f}/5d drives importer pressure"
        )

    # Pure dollar funding stress: DXY rallying without a commodity catalyst
    if dxy_strong and not crude_up and not crude_down:
        return "usd_funding_stress", (
            f"DXY +{dxy_5d:.2f}/5d without a commodity catalyst — pure funding shock"
        )
    if dxy_up and not theme_oil and not crude_down:
        return "usd_funding_stress", (
            f"DXY +{dxy_5d:.2f}/5d — funding channel in play"
        )

    if theme_food:
        return "food_importer_stress", (
            "food / grain theme; import-heavy EM carry the pass-through"
        )

    # Commodity exporter cushion: crude falling OR dollar falling
    if crude_down:
        return "commodity_exporter_cushion", (
            f"crude {crude_5d:+.1f}/5d — exporters give back, importers get relief"
        )
    if dxy_down:
        return "commodity_exporter_cushion", (
            f"DXY {dxy_5d:+.2f}/5d — dollar retreat eases EM funding conditions"
        )

    # Metal-only move is not a reserve story — hand back mixed unless we
    # also see dollar pressure.
    if theme_metal and dxy_up:
        return "usd_funding_stress", (
            f"metals + DXY {dxy_5d:+.2f}/5d — funding channel dominates"
        )

    return "none", "no dominant external-balance channel"


# ---------------------------------------------------------------------------
# Pressure scoring
# ---------------------------------------------------------------------------


def _compute_pressure_score(
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
    credit_spread_5d: Optional[float],
    real_yield_5d: Optional[float],
    stress_regime: Optional[dict],
    theme: str,
) -> tuple[int, list[str]]:
    """Return (score 0..100, list of driver keys that contributed).

    The weights are locked by tools/reserve_stress_overlay_validation.py
    — any change requires re-running it.

    Scoring contract (see the weight block at the top of the module):
      * DXY contribution is NON-STACKING — only the highest tier the
        5d move clears fires.  A 2.5% print contributes 35 (extreme
        tier), not 15+15+20 = 50 as the old stacked design did.
      * Credit widening reads structured ``signals.credit_widening``
        first, falls back to the numeric spread.  No label scraping.
      * The stress-regime bonus fires only when the classifier emits
        the exact ``Systemic Stress`` enum AND ``signals.credit_widening``
        is true — cross-confirmation, not a generic risk-off catch-all.
        Geopolitical Stress (VIX + haven, no credit widening) never
        matches.
    """
    score = 0
    drivers: list[str] = []

    # --- DXY: non-stacking tiered lookup ---
    if dxy_5d is not None and dxy_5d >= _DXY_MODERATE_MOVE_PCT:
        if dxy_5d >= _DXY_EXTREME_MOVE_PCT:
            score += _W_DXY_EXTREME
        elif dxy_5d >= _DXY_STRONG_MOVE_PCT:
            score += _W_DXY_STRONG
        else:
            score += _W_DXY_MODERATE
        drivers.append("dollar_rally")

    # --- Credit widening: structured signal first, numeric fallback ---
    if _credit_widening_active(stress_regime, credit_spread_5d):
        score += _W_CREDIT_WIDENING
        drivers.append("credit_widening")

    # --- Crude / oil-theme squeeze ---
    if (
        crude_5d is not None
        and crude_5d >= _CRUDE_MODERATE_MOVE_PCT
        and theme in ("oil", "gas", "none")
    ):
        score += _W_CRUDE_OIL_THEME
        drivers.append("oil_squeeze")
        if crude_5d >= _CRUDE_STRONG_MOVE_PCT:
            score += _W_CRUDE_STRONG

    # --- Real yield rise ---
    if real_yield_5d is not None and real_yield_5d >= _REAL_YIELD_RISE_5D_PCT:
        score += _W_REAL_YIELD_RISE
        drivers.append("real_yield_rise")

    # --- Dual squeeze (crude + dollar both rallying) ---
    if (
        crude_5d is not None and crude_5d >= _CRUDE_MODERATE_MOVE_PCT
        and dxy_5d is not None and dxy_5d >= _DXY_MODERATE_MOVE_PCT
    ):
        score += _W_DUAL_SQUEEZE
        drivers.append("dual_squeeze")

    # --- Systemic-stress cross-confirmation (guarded) ---
    if _stress_regime_confirms_funding_pressure(stress_regime):
        score += _W_STRESS_REGIME_HIT
        drivers.append("risk_off_regime")

    return min(score, 100), drivers


def _pressure_label(score: int) -> str:
    if score >= _PRESSURE_ELEVATED_MIN:
        return "elevated"
    if score >= _PRESSURE_MODERATE_MIN:
        return "moderate"
    return "contained"


# ---------------------------------------------------------------------------
# Country list building
# ---------------------------------------------------------------------------


def _build_vulnerable_list(
    channel: str, drivers: list[str], pressure_score: int,
) -> list[dict]:
    """Rank vulnerable countries for the resolved channel.

    We never show the full universe — 4 entries is the institutional
    sweet spot (dense, scannable, not a world index).  The channel
    picks which countries are in-frame; the vulnerability weight drives
    the ranking.
    """
    if channel in ("none", "commodity_exporter_cushion"):
        return []

    pool = list(_VULNERABLE_UNIVERSE)

    # Food-importer channel reweights the pool: Egypt + Pakistan jump,
    # corp-FX splinter drops out.
    if channel == "food_importer_stress":
        food_boost = {"Egypt", "Pakistan", "Sri Lanka", "Indonesia"}
        pool = [c for c in pool if c["country"] in food_boost or c["vulnerability"] >= 8]

    # Oil-import channel drops the "Turkey (corp FX)" splinter to avoid
    # duplicating Turkey; we want distinct macro lenses in the display.
    if channel in ("oil_import_squeeze", "dual_oil_dollar"):
        pool = [c for c in pool if c["country"] != "Turkey (corp FX)"]

    # Rank by vulnerability desc, then stable by country name.
    pool.sort(key=lambda c: (-int(c["vulnerability"]), c["country"]))

    top = pool[:4]
    out: list[dict] = []
    for entry in top:
        out.append({
            "country":       entry["country"],
            "region":        entry["region"],
            "vulnerability": int(entry["vulnerability"]),
            "drivers":       list(drivers),
            "rationale":     entry["rationale"],
        })
    return out


def _build_insulated_list(
    channel: str, drivers: list[str],
) -> list[dict]:
    """Pick the 3-4 insulated countries in scope for the channel."""
    if channel == "none":
        return []

    pool = list(_INSULATED_UNIVERSE)

    if channel in ("dual_oil_dollar", "oil_import_squeeze"):
        # GCC oil exporters and Norway are the classic relief names.
        target = {"Saudi Arabia", "UAE", "Norway", "Qatar", "Brazil (oil)"}
        pool = [c for c in pool if c["country"] in target]
    elif channel == "usd_funding_stress":
        # Dollar rally → shelter in Switzerland / Japan / Taiwan / Singapore / China
        target = {"Switzerland", "Japan", "Taiwan", "Singapore", "China"}
        pool = [c for c in pool if c["country"] in target]
    elif channel == "food_importer_stress":
        target = {"Saudi Arabia", "UAE", "Qatar", "Singapore", "Taiwan"}
        pool = [c for c in pool if c["country"] in target]
    elif channel == "commodity_exporter_cushion":
        target = {"Saudi Arabia", "Norway", "Canada", "Brazil (oil)", "Chile (metals)"}
        pool = [c for c in pool if c["country"] in target]
    else:  # mixed
        target = {"Switzerland", "Japan", "Singapore", "Taiwan", "Saudi Arabia"}
        pool = [c for c in pool if c["country"] in target]

    pool.sort(key=lambda c: (-int(c["insulation"]), c["country"]))
    top = pool[:4]
    out: list[dict] = []
    for entry in top:
        out.append({
            "country":    entry["country"],
            "region":     entry["region"],
            "strength":   int(entry["insulation"]),
            "drivers":    list(drivers),
            "rationale":  entry["rationale"],
        })
    return out


# ---------------------------------------------------------------------------
# Rationale string
# ---------------------------------------------------------------------------


def _rationale(
    channel: str,
    pressure_score: int,
    drivers: list[str],
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
    credit_spread_5d: Optional[float],
) -> str:
    bits = []
    if crude_5d is not None:
        bits.append(f"crude {crude_5d:+.1f}/5d")
    if dxy_5d is not None:
        bits.append(f"DXY {dxy_5d:+.2f}/5d")
    if credit_spread_5d is not None and abs(credit_spread_5d) >= 0.1:
        bits.append(f"HY spread {credit_spread_5d:+.2f}/5d")
    signal_strip = "; ".join(bits) if bits else "no meaningful signals"

    if channel == "dual_oil_dollar":
        return (
            f"Dual oil + dollar squeeze — net-importer EMs with thin reserves "
            f"take the full hit ({signal_strip}). Pressure {pressure_score}/100."
        )
    if channel == "oil_import_squeeze":
        return (
            f"Crude rally drives pressure on net-importer external balances "
            f"({signal_strip}). Pressure {pressure_score}/100."
        )
    if channel == "usd_funding_stress":
        return (
            f"Dollar rally is the binding channel — EMs with dollar liabilities "
            f"and thin reserves take the hit first ({signal_strip}). "
            f"Pressure {pressure_score}/100."
        )
    if channel == "food_importer_stress":
        return (
            f"Food-price shock routes through net food importers with "
            f"high-food-CPI weight ({signal_strip}). Pressure {pressure_score}/100."
        )
    if channel == "commodity_exporter_cushion":
        return (
            f"Commodity or dollar retreat eases external-balance stress — "
            f"importers get breathing room ({signal_strip}). "
            f"Pressure {pressure_score}/100."
        )
    if channel == "mixed":
        return (
            f"Signals are mixed — no single channel dominates the external-balance "
            f"read ({signal_strip}). Pressure {pressure_score}/100."
        )
    return (
        f"No dominant external-balance stress in the current tape "
        f"({signal_strip}). Pressure {pressure_score}/100."
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def compute_reserve_stress(
    headline: str,
    mechanism_text: str,
    terms_of_trade: Optional[dict] = None,
    rates_context: Optional[dict] = None,
    stress_regime: Optional[dict] = None,
) -> dict:
    """Score external-balance / reserve stress for one event.

    Pure composer: no I/O.  Reuses the terms-of-trade block (for the
    crude + DXY signals and the theme match), the rates context (for
    the real-yield 5d change) and the stress regime (for the credit
    spread, dollar fallback and risk-off label).

    Returns ``{}`` when there is genuinely nothing to report (no
    upstream inputs and no headline).  Otherwise returns the full
    block with ``stale=True`` when inputs are partial.
    """
    has_text = bool((headline or "").strip() or (mechanism_text or "").strip())
    has_tot = isinstance(terms_of_trade, dict) and terms_of_trade.get("available")
    has_rates = isinstance(rates_context, dict) and bool(rates_context)
    has_stress = isinstance(stress_regime, dict) and bool(stress_regime)

    if not has_text and not has_tot and not has_rates and not has_stress:
        return {}

    # Pull signals, preferring terms_of_trade (which already resolved
    # crude + DXY for us) and falling back to stress_regime for DXY.
    tot_signals = (terms_of_trade or {}).get("signals") or {}
    crude_5d = _f(tot_signals.get("crude_5d"))
    dxy_5d = _f(tot_signals.get("dxy_5d"))
    if dxy_5d is None:
        dxy_5d = _dxy_5d_from_stress(stress_regime)

    credit_spread_5d = _credit_spread_5d_from_stress(stress_regime)
    real_yield_5d = _real_yield_5d_from_rates(rates_context)
    matched_theme = (tot_signals.get("matched_theme") or "none")

    # Score.
    pressure_score, drivers = _compute_pressure_score(
        crude_5d, dxy_5d, credit_spread_5d, real_yield_5d,
        stress_regime, matched_theme,
    )

    # Channel resolution.
    channel, channel_basis = _resolve_channel(crude_5d, dxy_5d, matched_theme)

    # If absolutely nothing fired, tell the caller to skip rendering.
    if (
        channel == "none"
        and pressure_score == 0
        and not has_text
    ):
        return {}

    # Stale whenever we're running on degraded inputs: no tot block,
    # no rates, no stress, missing price signals, or an upstream layer
    # already marked itself stale.  The first two clauses catch the
    # "partial context" case where we can still produce a channel but
    # the consumer should know it's not on a full tape.
    stale = (
        not has_tot
        or not has_rates
        or not has_stress
        or (crude_5d is None and dxy_5d is None)
        or bool((terms_of_trade or {}).get("stale"))
        or bool((rates_context or {}).get("stale"))
    )

    vulnerable = _build_vulnerable_list(channel, drivers, pressure_score)
    insulated = _build_insulated_list(channel, drivers)

    rationale = _rationale(
        channel, pressure_score, drivers,
        crude_5d, dxy_5d, credit_spread_5d,
    )

    return {
        "vulnerable":             vulnerable,
        "insulated":              insulated,
        "dominant_channel":       channel,
        "dominant_channel_label": _CHANNEL_LABEL[channel],
        "pressure_score":         pressure_score,
        "pressure_label":         _pressure_label(pressure_score),
        "rationale":              rationale,
        "key_markets":            list(_CHANNEL_MARKETS[channel]),
        "available":              True,
        "stale":                  stale,
        "signals": {
            "crude_5d":         crude_5d,
            "dxy_5d":           dxy_5d,
            "credit_spread_5d": credit_spread_5d,
            "real_yield_5d":    real_yield_5d,
            "stress_regime":    _stress_regime_label(stress_regime),
            "matched_channel":  channel,
            "matched_theme":    matched_theme,
            "thresholds": (
                f"DXY moderate≥{_DXY_MODERATE_MOVE_PCT}%  "
                f"strong≥{_DXY_STRONG_MOVE_PCT}%; "
                f"crude moderate≥{_CRUDE_MODERATE_MOVE_PCT}%; "
                f"credit widen≥{_CREDIT_WIDENING_5D_PCT}%"
            ),
        },
    }

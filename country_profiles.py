"""Maintained country / region vulnerability profiles.

Replaces scattered static heuristics in ``country_vulnerability.py``,
``country_fx_passthrough.py``, and ``reserve_stress_overlay.py`` with
one versioned registry that downstream modules can migrate toward.

Design principles
-----------------
* **Versioned + validated**.  Mirrors the shape of
  ``coverage_registry.py``: a module constant, a pure
  ``validate_country_profiles`` function, and a
  ``load_country_profiles`` helper that returns a validated deep copy.
* **Explicit ownership metadata per profile**: ``added_at`` +
  ``updated_at`` + ``source_note`` (a one-line human rationale),
  because "why is Turkey rated thin-reserve?" is the kind of question
  a reviewer has to answer from the registry alone, not from git blame.
* **Four orthogonal dimensions** — reserve coverage, import dependence,
  funding mix, commodity sensitivity — each a small closed shape.  A
  reader can grep a country's profile and see every factor at once
  instead of piecing it together from three modules.
* **Aliases** are a first-class feature so existing label-based
  lookups (``country_vulnerability`` keys on free-form names like
  "Eurozone periphery") keep resolving without renames.
* **Deterministic shock mapping**.
  ``map_shock_to_vulnerability(profile, shock)`` returns the same
  channel-stress dict on repeat calls — no randomness, no hidden
  globals, no I/O.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Iterator, Optional


# ---------------------------------------------------------------------------
# Pinned enums + version
# ---------------------------------------------------------------------------

COUNTRY_PROFILES_VERSION: str = "2026.04.01"

REGIONS: frozenset[str] = frozenset({
    "DM NA", "DM EU", "DM Asia",
    "GCC",
    "EM EMEA", "EM Asia", "EM LatAm",
    "Africa",
})

RESERVE_LEVELS: tuple[str, ...] = ("strong", "adequate", "thin", "critical")

IMPORT_LEVELS: tuple[str, ...] = ("low", "moderate", "high", "severe")

FUNDING_MIXES: tuple[str, ...] = (
    "domestic_funded",      # reserve-currency or deep local funding base
    "mixed",                # some external financing need, manageable
    "external_dependent",   # material reliance on external funding
    "usd_funded",           # heavy USD-denominated liabilities
)

FX_REGIMES: tuple[str, ...] = (
    "free_floating", "managed_float", "pegged", "crisis_multiple_rates",
)

COMMODITY_DIMENSIONS: tuple[str, ...] = ("oil", "metals", "food")

# Stress-label thresholds (pinned so calibrate_thresholds can audit).
_STRESS_ACUTE: float = 0.70
_STRESS_STRESSED: float = 0.40
_STRESS_WATCH: float = 0.15

# Per-channel weights for the aggregate stress score.  FX + funding
# dominate because they drive most crisis episodes; reserves is a
# multiplier on both rather than a standalone big share.
_CHANNEL_WEIGHTS: dict[str, float] = {
    "fx":         0.35,
    "commodity":  0.25,
    "funding":    0.25,
    "reserves":   0.15,
}


_REQUIRED_PROFILE_KEYS: frozenset[str] = frozenset({
    "iso", "name", "region", "aliases",
    "added_at", "updated_at", "source_note",
    "reserve_coverage", "import_dependence",
    "funding_mix", "commodity_sensitivity",
})


# ---------------------------------------------------------------------------
# The registry itself.
#
# Scores follow convention:
#   reserve_coverage.score      ∈ [0, 1]  — 1.0 = strongest reserves
#   import_dependence.oil/gas/food/metals ∈ IMPORT_LEVELS
#   funding_mix.usd_debt_share  ∈ [0, 1]  — roughly, share of gov+corp
#                                            external debt in USD
#   commodity_sensitivity.oil / metals / food
#                              ∈ [-3, +3] — sign: + exporter, - importer
#
# Tiers reflect desk-grade priors for a macro research engine — not a
# quant data-feed.  Each profile carries a ``source_note`` so a
# reviewer can evaluate the judgment without re-reading the modules.
# ---------------------------------------------------------------------------

COUNTRY_PROFILES: dict[str, Any] = {
    "version":    COUNTRY_PROFILES_VERSION,
    "updated_at": "2026-04-19",
    "profiles": [
        # ---- DM NA ----
        {
            "iso": "US", "name": "United States", "region": "DM NA",
            "aliases": ["USA", "U.S."],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Reserve currency issuer — USD funding flows in, "
                           "not out.  Net oil exporter as of 2024.",
            "reserve_coverage":   {"level": "strong",   "score": 1.00,
                                    "notes": "USD is the reserve; no coverage ratio applies."},
            "import_dependence":  {"level": "low",
                                    "oil": "low", "gas": "low",
                                    "food": "low", "metals": "moderate"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 1.00,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": 1, "metals": 0, "food": 1},
        },
        {
            "iso": "CA", "name": "Canada", "region": "DM NA",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Commodity-currency DM; oil + metals exporter "
                           "with deep domestic funding.",
            "reserve_coverage":   {"level": "adequate", "score": 0.70,
                                    "notes": "Modest reserves but USD swap line + deep markets."},
            "import_dependence":  {"level": "low",
                                    "oil": "low", "gas": "low",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.15,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": 2, "metals": 2, "food": 2},
        },
        # ---- DM EU ----
        {
            "iso": "EU", "name": "Eurozone", "region": "DM EU",
            "aliases": ["Euro Area", "EUR", "Eurozone periphery"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Major energy importer; reserve-currency adjacent "
                           "via EUR but exposed to gas shocks.",
            "reserve_coverage":   {"level": "adequate", "score": 0.75,
                                    "notes": "Deep markets + swap lines; periphery weaker."},
            "import_dependence":  {"level": "high",
                                    "oil": "high", "gas": "severe",
                                    "food": "moderate", "metals": "high"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.20,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -2, "metals": -2, "food": -1},
        },
        {
            "iso": "GB", "name": "United Kingdom", "region": "DM EU",
            "aliases": ["UK", "Britain"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Financial-centre DM with twin deficits but "
                           "reserve-currency-adjacent via GBP.",
            "reserve_coverage":   {"level": "adequate", "score": 0.65,
                                    "notes": "Runs current-account deficit; relies on portfolio inflows."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "moderate", "gas": "high",
                                    "food": "moderate", "metals": "moderate"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.25,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -1, "metals": -1, "food": -1},
        },
        {
            "iso": "CH", "name": "Switzerland", "region": "DM EU",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Safe-haven currency; extreme reserves via SNB "
                           "FX interventions.",
            "reserve_coverage":   {"level": "strong",   "score": 0.95,
                                    "notes": "SNB balance sheet holds ~100% of GDP in FX."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "high", "gas": "moderate",
                                    "food": "moderate", "metals": "moderate"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.10,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -1, "metals": 0, "food": 0},
        },
        {
            "iso": "NO", "name": "Norway", "region": "DM EU",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Commodity DM par excellence — sovereign wealth "
                           "fund dwarfs GDP.",
            "reserve_coverage":   {"level": "strong",   "score": 1.00,
                                    "notes": "Oil fund reserves > 3× GDP."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "low", "gas": "low",
                                    "food": "moderate", "metals": "moderate"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.05,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": 3, "metals": 0, "food": 0},
        },
        # ---- DM Asia ----
        {
            "iso": "JP", "name": "Japan", "region": "DM Asia",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Reserve-holder giant but ~100% energy importer. "
                           "Domestic savings finance government debt.",
            "reserve_coverage":   {"level": "strong",   "score": 0.95,
                                    "notes": "Second-largest FX reserves globally."},
            "import_dependence":  {"level": "severe",
                                    "oil": "severe", "gas": "severe",
                                    "food": "high", "metals": "high"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.15,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -3, "metals": -2, "food": -2},
        },
        {
            "iso": "AU", "name": "Australia", "region": "DM Asia",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Metals + LNG exporter; deep domestic markets.",
            "reserve_coverage":   {"level": "adequate", "score": 0.70,
                                    "notes": "Small reserves but AUD floats + RBA swaps."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "high", "gas": "low",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.25,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -1, "metals": 3, "food": 2},
        },
        # ---- GCC ----
        {
            "iso": "SA", "name": "Saudi Arabia", "region": "GCC",
            "aliases": ["KSA"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Swing producer; riyal peg + massive FX reserves "
                           "cushion oil downside.",
            "reserve_coverage":   {"level": "strong",   "score": 0.90,
                                    "notes": "Reserves + PIF assets anchor the peg."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "low", "gas": "low",
                                    "food": "high", "metals": "high"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.35,
                                    "fx_regime": "pegged"},
            "commodity_sensitivity": {"oil": 3, "metals": 0, "food": -1},
        },
        {
            "iso": "AE", "name": "United Arab Emirates", "region": "GCC",
            "aliases": ["UAE"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Diversified Gulf; ADIA + Dubai reserves + AED "
                           "peg to USD.",
            "reserve_coverage":   {"level": "strong",   "score": 0.90,
                                    "notes": "Sovereign wealth + USD peg stability."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "low", "gas": "low",
                                    "food": "severe", "metals": "moderate"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.40,
                                    "fx_regime": "pegged"},
            "commodity_sensitivity": {"oil": 3, "metals": 0, "food": -1},
        },
        # ---- EM EMEA ----
        {
            "iso": "TR", "name": "Turkey", "region": "EM EMEA",
            "aliases": ["Turkiye"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Chronic thin reserves + large external financing "
                           "need + oil/gas importer.",
            "reserve_coverage":   {"level": "critical", "score": 0.15,
                                    "notes": "Gross reserves masked by swap liabilities."},
            "import_dependence":  {"level": "severe",
                                    "oil": "severe", "gas": "severe",
                                    "food": "moderate", "metals": "high"},
            "funding_mix":        {"level": "usd_funded",
                                    "usd_debt_share": 0.55,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -3, "metals": -2, "food": -1},
        },
        {
            "iso": "HU", "name": "Hungary", "region": "EM EMEA",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Open CEE economy; HUF sensitive to DM risk-off "
                           "and gas supply shocks.",
            "reserve_coverage":   {"level": "thin",     "score": 0.35,
                                    "notes": "Reserves adequate but HUF volatile."},
            "import_dependence":  {"level": "high",
                                    "oil": "high", "gas": "severe",
                                    "food": "low", "metals": "high"},
            "funding_mix":        {"level": "external_dependent",
                                    "usd_debt_share": 0.30,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -2, "metals": -1, "food": 1},
        },
        {
            "iso": "PL", "name": "Poland", "region": "EM EMEA",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Larger, more resilient CEE; EU + NATO anchor.",
            "reserve_coverage":   {"level": "adequate", "score": 0.65,
                                    "notes": "Reserves healthy; credible NBP."},
            "import_dependence":  {"level": "high",
                                    "oil": "high", "gas": "high",
                                    "food": "low", "metals": "moderate"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.20,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -2, "metals": -1, "food": 1},
        },
        {
            "iso": "ZA", "name": "South Africa", "region": "EM EMEA",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Metals exporter but twin deficits and structural "
                           "energy constraint.",
            "reserve_coverage":   {"level": "thin",     "score": 0.30,
                                    "notes": "Reserves < 6 months imports."},
            "import_dependence":  {"level": "high",
                                    "oil": "high", "gas": "moderate",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "external_dependent",
                                    "usd_debt_share": 0.35,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -2, "metals": 2, "food": 1},
        },
        {
            "iso": "EG", "name": "Egypt", "region": "EM EMEA",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Recurring FX crises; food + oil importer with "
                           "high USD debt service.",
            "reserve_coverage":   {"level": "critical", "score": 0.15,
                                    "notes": "IMF-supported reserves; recurrent shortages."},
            "import_dependence":  {"level": "severe",
                                    "oil": "high", "gas": "moderate",
                                    "food": "severe", "metals": "high"},
            "funding_mix":        {"level": "usd_funded",
                                    "usd_debt_share": 0.50,
                                    "fx_regime": "crisis_multiple_rates"},
            "commodity_sensitivity": {"oil": -2, "metals": -1, "food": -3},
        },
        # ---- EM Asia ----
        {
            "iso": "CN", "name": "China", "region": "EM Asia",
            "aliases": ["PRC"],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Massive reserves + managed float; structural "
                           "energy + metals importer.",
            "reserve_coverage":   {"level": "strong",   "score": 0.90,
                                    "notes": "Largest FX reserves globally; capital controls."},
            "import_dependence":  {"level": "high",
                                    "oil": "severe", "gas": "high",
                                    "food": "moderate", "metals": "severe"},
            "funding_mix":        {"level": "domestic_funded",
                                    "usd_debt_share": 0.15,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -3, "metals": -3, "food": -1},
        },
        {
            "iso": "IN", "name": "India", "region": "EM Asia",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Large oil importer but robust reserves + managed "
                           "float cushion cycles.",
            "reserve_coverage":   {"level": "adequate", "score": 0.65,
                                    "notes": "Reserves ~10 months imports."},
            "import_dependence":  {"level": "high",
                                    "oil": "severe", "gas": "high",
                                    "food": "low", "metals": "moderate"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.25,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -3, "metals": 0, "food": 1},
        },
        {
            "iso": "ID", "name": "Indonesia", "region": "EM Asia",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Commodity EM with coal + palm oil exports but "
                           "oil importer and dollar-sensitive.",
            "reserve_coverage":   {"level": "adequate", "score": 0.55,
                                    "notes": "Reserves healthy post-2013."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "high", "gas": "low",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.35,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -1, "metals": 2, "food": 2},
        },
        {
            "iso": "PK", "name": "Pakistan", "region": "EM Asia",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Perennial BoP stress; oil + food importer with "
                           "IMF-anchored reserves.",
            "reserve_coverage":   {"level": "critical", "score": 0.20,
                                    "notes": "Reserves < 2 months imports without IMF."},
            "import_dependence":  {"level": "severe",
                                    "oil": "severe", "gas": "high",
                                    "food": "high", "metals": "high"},
            "funding_mix":        {"level": "usd_funded",
                                    "usd_debt_share": 0.60,
                                    "fx_regime": "managed_float"},
            "commodity_sensitivity": {"oil": -3, "metals": -1, "food": -2},
        },
        # ---- EM LatAm ----
        {
            "iso": "BR", "name": "Brazil", "region": "EM LatAm",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Commodity + agricultural exporter; floats freely "
                           "with deep local-currency markets.",
            "reserve_coverage":   {"level": "strong",   "score": 0.80,
                                    "notes": "Reserves ~15 months imports."},
            "import_dependence":  {"level": "low",
                                    "oil": "low", "gas": "moderate",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.20,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": 1, "metals": 3, "food": 3},
        },
        {
            "iso": "MX", "name": "Mexico", "region": "EM LatAm",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Oil exporter (declining) + USD-linked trade; "
                           "Banxico credible and peso floats.",
            "reserve_coverage":   {"level": "adequate", "score": 0.65,
                                    "notes": "Reserves healthy + USD swap line."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "moderate", "gas": "high",
                                    "food": "moderate", "metals": "low"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.30,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": 1, "metals": 1, "food": 0},
        },
        {
            "iso": "AR", "name": "Argentina", "region": "EM LatAm",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Serial crisis country; multiple FX rates, "
                           "negative net reserves at points.",
            "reserve_coverage":   {"level": "critical", "score": 0.10,
                                    "notes": "Net reserves frequently negative."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "moderate", "gas": "moderate",
                                    "food": "low", "metals": "low"},
            "funding_mix":        {"level": "usd_funded",
                                    "usd_debt_share": 0.70,
                                    "fx_regime": "crisis_multiple_rates"},
            "commodity_sensitivity": {"oil": 0, "metals": 1, "food": 3},
        },
        {
            "iso": "CL", "name": "Chile", "region": "EM LatAm",
            "aliases": [],
            "added_at": "2025-10-01", "updated_at": "2026-04-19",
            "source_note": "Copper exporter with credible institutions + "
                           "fiscal stabilisation fund.",
            "reserve_coverage":   {"level": "adequate", "score": 0.70,
                                    "notes": "Reserves healthy; sovereign wealth fund cushions."},
            "import_dependence":  {"level": "moderate",
                                    "oil": "high", "gas": "moderate",
                                    "food": "moderate", "metals": "low"},
            "funding_mix":        {"level": "mixed",
                                    "usd_debt_share": 0.25,
                                    "fx_regime": "free_floating"},
            "commodity_sensitivity": {"oil": -1, "metals": 3, "food": 1},
        },
        # ---- Africa ----
        {
            "iso": "NG", "name": "Nigeria", "region": "Africa",
            "aliases": [],
            "added_at": "2026-01-15", "updated_at": "2026-04-19",
            "source_note": "Oil exporter but chronic FX shortages + heavy "
                           "fuel subsidies; parallel FX market.",
            "reserve_coverage":   {"level": "thin",     "score": 0.25,
                                    "notes": "Reserves drained by FX defences."},
            "import_dependence":  {"level": "high",
                                    "oil": "low", "gas": "low",
                                    "food": "high", "metals": "high"},
            "funding_mix":        {"level": "external_dependent",
                                    "usd_debt_share": 0.45,
                                    "fx_regime": "crisis_multiple_rates"},
            "commodity_sensitivity": {"oil": 3, "metals": -1, "food": -2},
        },
    ],
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _ensure_iso_date(value: Any, *, path: str) -> None:
    if not _is_nonempty_str(value) or len(value) != 10 \
            or value[4] != "-" or value[7] != "-":
        raise ValueError(
            f"country_profiles: {path} must be ISO YYYY-MM-DD "
            f"(got {value!r})"
        )


def _validate_reserve_coverage(block: Any, *, path: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{path} must be a dict")
    for k in ("level", "score", "notes"):
        if k not in block:
            raise ValueError(f"{path} missing key {k!r}")
    if block["level"] not in RESERVE_LEVELS:
        raise ValueError(
            f"{path}.level={block['level']!r} "
            f"not in {list(RESERVE_LEVELS)}"
        )
    score = block["score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError(f"{path}.score must be a number")
    if not 0.0 <= float(score) <= 1.0:
        raise ValueError(f"{path}.score must be in [0, 1]")
    if not _is_nonempty_str(block["notes"]):
        raise ValueError(f"{path}.notes must be a non-empty string")


def _validate_import_dependence(block: Any, *, path: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{path} must be a dict")
    required = {"level", "oil", "gas", "food", "metals"}
    missing = required - set(block)
    extra = set(block) - required
    if missing:
        raise ValueError(f"{path} missing keys {sorted(missing)}")
    if extra:
        raise ValueError(f"{path} has unknown keys {sorted(extra)}")
    for k in required:
        if block[k] not in IMPORT_LEVELS:
            raise ValueError(
                f"{path}.{k}={block[k]!r} not in {list(IMPORT_LEVELS)}"
            )


def _validate_funding_mix(block: Any, *, path: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{path} must be a dict")
    required = {"level", "usd_debt_share", "fx_regime"}
    missing = required - set(block)
    if missing:
        raise ValueError(f"{path} missing keys {sorted(missing)}")
    if block["level"] not in FUNDING_MIXES:
        raise ValueError(
            f"{path}.level={block['level']!r} not in {list(FUNDING_MIXES)}"
        )
    share = block["usd_debt_share"]
    if not isinstance(share, (int, float)) or isinstance(share, bool):
        raise ValueError(f"{path}.usd_debt_share must be a number")
    if not 0.0 <= float(share) <= 1.0:
        raise ValueError(f"{path}.usd_debt_share must be in [0, 1]")
    if block["fx_regime"] not in FX_REGIMES:
        raise ValueError(
            f"{path}.fx_regime={block['fx_regime']!r} "
            f"not in {list(FX_REGIMES)}"
        )


def _validate_commodity_sensitivity(block: Any, *, path: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{path} must be a dict")
    missing = set(COMMODITY_DIMENSIONS) - set(block)
    extra = set(block) - set(COMMODITY_DIMENSIONS)
    if missing:
        raise ValueError(f"{path} missing keys {sorted(missing)}")
    if extra:
        raise ValueError(f"{path} has unknown keys {sorted(extra)}")
    for k in COMMODITY_DIMENSIONS:
        v = block[k]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError(f"{path}.{k} must be an int in [-3, 3]")
        if not -3 <= v <= 3:
            raise ValueError(f"{path}.{k} must be in [-3, 3]")


def _validate_profile(p: Any, *, path: str) -> None:
    if not isinstance(p, dict):
        raise ValueError(f"{path} must be a dict")
    missing = _REQUIRED_PROFILE_KEYS - set(p)
    extra = set(p) - _REQUIRED_PROFILE_KEYS
    if missing:
        raise ValueError(f"{path} missing keys {sorted(missing)}")
    if extra:
        raise ValueError(f"{path} has unknown keys {sorted(extra)}")
    for k in ("iso", "name", "region", "source_note"):
        if not _is_nonempty_str(p[k]):
            raise ValueError(f"{path}.{k} must be non-empty string")
    if p["region"] not in REGIONS:
        raise ValueError(
            f"{path}.region={p['region']!r} not in {sorted(REGIONS)}"
        )
    if not isinstance(p["aliases"], list):
        raise ValueError(f"{path}.aliases must be a list")
    for i, a in enumerate(p["aliases"]):
        if not _is_nonempty_str(a):
            raise ValueError(f"{path}.aliases[{i}] must be non-empty string")
    _ensure_iso_date(p["added_at"],   path=f"{path}.added_at")
    _ensure_iso_date(p["updated_at"], path=f"{path}.updated_at")

    _validate_reserve_coverage(
        p["reserve_coverage"], path=f"{path}.reserve_coverage",
    )
    _validate_import_dependence(
        p["import_dependence"], path=f"{path}.import_dependence",
    )
    _validate_funding_mix(
        p["funding_mix"], path=f"{path}.funding_mix",
    )
    _validate_commodity_sensitivity(
        p["commodity_sensitivity"], path=f"{path}.commodity_sensitivity",
    )


def validate_country_profiles(reg: Any) -> None:
    """Validate the country profiles registry in place.

    Raises ``ValueError`` on any shape violation.  Returns ``None`` on
    success.  Asserts ISO uniqueness + name/alias uniqueness so a
    single country never straddles two profiles.
    """
    if not isinstance(reg, dict):
        raise ValueError(
            "country_profiles: registry must be a dict"
        )
    required_top = {"version", "updated_at", "profiles"}
    missing = required_top - set(reg)
    extra = set(reg) - required_top
    if missing:
        raise ValueError(
            f"country_profiles: missing top-level keys {sorted(missing)}"
        )
    if extra:
        raise ValueError(
            f"country_profiles: unknown top-level keys {sorted(extra)}"
        )
    if not _is_nonempty_str(reg["version"]):
        raise ValueError("country_profiles.version must be a non-empty string")
    _ensure_iso_date(reg["updated_at"], path="country_profiles.updated_at")

    profiles = reg["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("country_profiles.profiles must be a non-empty list")

    seen_iso: set[str] = set()
    seen_labels: set[str] = set()
    for i, p in enumerate(profiles):
        path = f"profiles[{i}]"
        _validate_profile(p, path=path)
        iso = p["iso"]
        if iso in seen_iso:
            raise ValueError(
                f"country_profiles: duplicate iso={iso!r}"
            )
        seen_iso.add(iso)
        labels = [p["name"], *p["aliases"]]
        for lab in labels:
            key = lab.strip().lower()
            if key in seen_labels:
                raise ValueError(
                    f"country_profiles: label {lab!r} appears on more "
                    f"than one profile"
                )
            seen_labels.add(key)


# ---------------------------------------------------------------------------
# Deterministic load + resolvers
# ---------------------------------------------------------------------------

def load_country_profiles() -> dict[str, Any]:
    """Return a validated deep copy of COUNTRY_PROFILES."""
    reg = copy.deepcopy(COUNTRY_PROFILES)
    validate_country_profiles(reg)
    return reg


def iter_profiles() -> Iterator[dict[str, Any]]:
    """Yield each profile dict in registry order."""
    for p in COUNTRY_PROFILES["profiles"]:
        yield p


def resolve_country(label: Optional[str]) -> Optional[dict[str, Any]]:
    """Return the profile matching ``label`` by canonical name, alias,
    or ISO code.  Case-insensitive.  Returns ``None`` when unknown.
    """
    if not _is_nonempty_str(label):
        return None
    key = label.strip().lower()
    for p in iter_profiles():
        if p["iso"].lower() == key:
            return p
        if p["name"].lower() == key:
            return p
        for alias in p["aliases"]:
            if alias.lower() == key:
                return p
    return None


def countries_by_region(region: str) -> list[dict[str, Any]]:
    """Return every profile whose ``region`` matches (exact match)."""
    return [p for p in iter_profiles() if p["region"] == region]


# ---------------------------------------------------------------------------
# Deterministic shock mapping
# ---------------------------------------------------------------------------

_RESERVE_STRESS_MULT: dict[str, float] = {
    # Multiplier applied to fx + funding channel stress.  Strong
    # reserves reduce real stress; critical reserves amplify it.
    "strong":   0.70,
    "adequate": 1.00,
    "thin":     1.30,
    "critical": 1.60,
}

_IMPORT_LEVEL_SCORE: dict[str, float] = {
    "low":      0.10,
    "moderate": 0.35,
    "high":     0.65,
    "severe":   1.00,
}

_FUNDING_MIX_EXTERNAL: dict[str, float] = {
    "domestic_funded":    0.10,
    "mixed":              0.40,
    "external_dependent": 0.75,
    "usd_funded":         1.00,
}

_FX_REGIME_FRAGILITY: dict[str, float] = {
    "free_floating":         0.30,
    "managed_float":         0.60,
    "pegged":                0.80,
    "crisis_multiple_rates": 1.00,
}

_STRESS_LABELS: tuple[tuple[float, str], ...] = (
    (_STRESS_ACUTE,     "acute"),
    (_STRESS_STRESSED,  "stressed"),
    (_STRESS_WATCH,     "watch"),
)


def _stress_label(total: float) -> str:
    for threshold, label in _STRESS_LABELS:
        if total >= threshold:
            return label
    return "calm"


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _primary_channel(channel_stress: dict[str, float]) -> Optional[str]:
    """Return the channel with the highest stress, or None if all zero."""
    best = None
    best_val = 0.0
    for axis in ("fx", "commodity", "funding", "reserves"):
        v = channel_stress.get(axis, 0.0)
        if v > best_val:
            best_val = v
            best = axis
    return best


def map_shock_to_vulnerability(
    profile: Optional[dict[str, Any]],
    shock: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Map a macro/FX/commodity shock to per-country vulnerability.

    ``profile`` is a profile dict from ``resolve_country`` or
    ``load_country_profiles()``.  ``shock`` is a dict of:

      * ``dxy_change_pct``        — +ve = USD strengthens (headwind for
                                     USD-funded / import-dependent EM).
      * ``crude_5d_pct``          — +ve = crude up (windfall for
                                     exporters, headwind for importers).
      * ``credit_spread_bps``     — +ve = widening (funding squeeze).
      * ``real_yield_bps``        — +ve = real yields rising.

    Returns a shaped dict.  Unknown profile or shock inputs collapse
    to ``{"available": False, ...}``.  Never raises.
    """
    if not isinstance(profile, dict) or not isinstance(shock, dict):
        return {
            "available":      False,
            "country":        (profile or {}).get("name"),
            "channel_stress": {"fx": 0.0, "commodity": 0.0,
                               "funding": 0.0, "reserves": 0.0},
            "total_stress":   0.0,
            "stress_label":   "calm",
            "primary_channel": None,
            "rationale":      "Profile or shock unavailable.",
        }

    dxy     = float(shock.get("dxy_change_pct")    or 0.0)
    crude   = float(shock.get("crude_5d_pct")      or 0.0)
    credit  = float(shock.get("credit_spread_bps") or 0.0)
    real_y  = float(shock.get("real_yield_bps")    or 0.0)

    rc = profile.get("reserve_coverage") or {}
    idp = profile.get("import_dependence") or {}
    fm  = profile.get("funding_mix") or {}
    cs  = profile.get("commodity_sensitivity") or {}

    reserve_level = rc.get("level", "adequate")
    reserve_score = float(rc.get("score") or 0.5)
    reserve_mult  = _RESERVE_STRESS_MULT.get(reserve_level, 1.0)

    funding_ext  = _FUNDING_MIX_EXTERNAL.get(fm.get("level"), 0.40)
    fx_regime_f  = _FX_REGIME_FRAGILITY.get(fm.get("fx_regime"), 0.50)
    usd_share    = float(fm.get("usd_debt_share") or 0.20)

    # FX channel: a USD rally hurts countries with USD debt and fragile
    # FX regimes.  Scaled by reserve buffer.
    fx_raw = abs(dxy) / 2.0 * fx_regime_f * (0.4 + usd_share)
    if dxy < 0:
        # USD weakness is usually tailwind — dampen the stress.
        fx_raw *= 0.25
    fx_stress = _clip(fx_raw * reserve_mult)

    # Commodity channel: crude move intersected with per-country
    # commodity sensitivity.  Importers (neg sensitivity) take stress on
    # positive crude moves; exporters gain a cushion and post 0 stress.
    oil_sens = int(cs.get("oil", 0))
    oil_effect = (oil_sens / 3.0) * (crude / 10.0)
    # Positive product = windfall (cushion); negative product = stress.
    commodity_stress = _clip(-oil_effect) if oil_effect < 0 else 0.0

    # Food importers also care about grain moves, but we don't carry a
    # grain shock input here — deliberately out of scope.  Import
    # dependence is folded in as an additional weight on the commodity
    # channel for high-import profiles.
    food_level = idp.get("food", "low")
    if oil_effect < 0 and food_level in ("high", "severe"):
        commodity_stress = _clip(commodity_stress + 0.10)

    # Funding channel: credit widening + real yield rise + external
    # dependence.  Scaled by reserve buffer.
    credit_comp = _clip(credit / 150.0) * 0.6
    real_comp   = _clip(max(0.0, real_y) / 75.0) * 0.4
    funding_stress = _clip(
        (credit_comp + real_comp) * (0.4 + funding_ext) * reserve_mult
    )

    # Reserves channel: a summary "are buffers being burnt?" read.
    # Captures the idea that an already-thin reserve position amplifies
    # downside from either FX or commodity stress.
    reserves_pressure = (fx_stress + commodity_stress) * (1.0 - reserve_score)
    reserves_stress = _clip(reserves_pressure * 0.5)

    channel_stress = {
        "fx":        round(fx_stress, 3),
        "commodity": round(commodity_stress, 3),
        "funding":   round(funding_stress, 3),
        "reserves":  round(reserves_stress, 3),
    }
    total = sum(
        channel_stress[axis] * _CHANNEL_WEIGHTS[axis]
        for axis in channel_stress
    )
    total = round(_clip(total), 3)

    primary = _primary_channel(channel_stress)
    label = _stress_label(total)

    rationale_bits: list[str] = []
    if primary == "fx" and channel_stress["fx"] > 0.05:
        rationale_bits.append(
            f"USD +{dxy:+.1f}% × usd_debt_share={usd_share:.0%} "
            f"× {fm.get('fx_regime', 'unknown')} regime"
        )
    if primary == "commodity" and channel_stress["commodity"] > 0.05:
        rationale_bits.append(
            f"crude {crude:+.1f}% × oil_sensitivity={oil_sens}"
        )
    if primary == "funding" and channel_stress["funding"] > 0.05:
        rationale_bits.append(
            f"credit +{int(credit)}bps × funding={fm.get('level')}"
        )
    if reserve_level in ("thin", "critical"):
        rationale_bits.append(
            f"{reserve_level} reserves amplify ×{reserve_mult:.2f}"
        )
    rationale = "; ".join(rationale_bits) or "No material channel stress."

    return {
        "available":       True,
        "country":         profile.get("name"),
        "iso":             profile.get("iso"),
        "region":          profile.get("region"),
        "channel_stress":  channel_stress,
        "total_stress":    total,
        "stress_label":    label,
        "primary_channel": primary,
        "rationale":       rationale,
    }


def score_cohort(
    labels: Iterable[str],
    shock: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score a cohort of countries against the same shock.

    Returns the list sorted by ``total_stress`` desc, with unknown
    labels captured as ``{available: False}`` rows so the caller can
    surface "we don't have a profile for X" rather than silently dropping.
    """
    rows: list[dict[str, Any]] = []
    for label in labels or []:
        profile = resolve_country(label)
        if profile is None:
            rows.append({
                "available":      False,
                "country":        label,
                "iso":            None,
                "region":         None,
                "channel_stress": {"fx": 0.0, "commodity": 0.0,
                                   "funding": 0.0, "reserves": 0.0},
                "total_stress":   0.0,
                "stress_label":   "unknown",
                "primary_channel": None,
                "rationale":      f"No maintained profile for {label!r}.",
            })
            continue
        rows.append(map_shock_to_vulnerability(profile, shock))
    rows.sort(key=lambda r: (-float(r.get("total_stress") or 0.0),
                              r.get("country") or ""))
    return rows


# Validate on import so deploys fail fast.
validate_country_profiles(COUNTRY_PROFILES)

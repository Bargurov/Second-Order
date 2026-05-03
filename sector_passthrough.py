"""
sector_passthrough.py

Sector-to-sector passthrough + downstream contagion composer.

The existing analysis layer names beneficiaries / losers — the *direct*
first-order winners and losers.  This module answers the adjacent question
a macro desk always asks next: *which other sectors should move, on what
lag, and with what intensity, if this mechanism actually plays out?*

Concrete examples this maps:

  * materials / input shock → industrials + consumer discretionary (weeks,
    inverse, margin compression)
  * energy shock → transport (days, inverse, fuel costs), chemicals / materials
    (days-weeks, inverse, feedstock), refiners (days, mixed, crack spread)
  * rates shock → banks (days, reinforcing, NIM), REITs + homebuilders
    (days-weeks, inverse, discount rate / mortgage rate)
  * semiconductors shock → tech software (quarters, low, capex cycle)
  * shipping shock → retail / consumer discretionary (weeks, inverse,
    freight cost)

Design
------
Pure composer; no I/O.  Inputs are already-fetched primitives:
  * ticker lists (beneficiary + loser) — mapped to direct sectors via
    ``market_check.resolve_benchmark``
  * mechanism text — scanned with ``news_consensus._SECTOR_KEYWORDS`` to
    pick up macro drivers (rates, credit, fx) that aren't ticker-shaped
  * shock_primary — the dominant channel from shock_decomposition
    (optional), used as a fallback direct-hit source

Always returns a dict with a stable shape.  ``available=False`` when no
direct-hit source could be resolved from any input.

Output distinguishes **direct** validation (should show alpha in 1-5d) from
**downstream** validation (5-20d), so consumers can check per-tier
confirmation rather than lumping everything together.
"""

from __future__ import annotations

from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Sector taxonomy — aligned with market_check.SECTOR_BENCHMARKS keys, plus
# macro-driver pseudo-sectors (rates / credit / fx) so rate-shock and
# credit-shock events have first-class direct-hit sources.
# ---------------------------------------------------------------------------

SECTOR_LABELS: dict[str, str] = {
    # Real-economy sectors (match SECTOR_BENCHMARKS in market_check.py)
    "energy":           "Energy",
    "semiconductors":   "Semiconductors",
    "defense":          "Defense",
    "shipping":         "Shipping & Logistics",
    "financials":       "Financials",
    "tech_software":    "Tech / Software",
    "healthcare":       "Healthcare",
    "industrials":      "Industrials",
    "materials":        "Materials",
    "consumer_disc":    "Consumer Discretionary",
    "consumer_staples": "Consumer Staples",
    "utilities":        "Utilities",
    "real_estate":      "Real Estate / REITs",
    "communication":    "Communication Services",
    # Sub-sector / adjacency targets not in the benchmark map (no dedicated
    # ETF is tracked, but they matter for downstream reads).
    "transport":        "Transport (airlines / trucking)",
    "chemicals":        "Chemicals",
    "refiners":         "Refiners",
    "homebuilders":     "Homebuilders",
    "banks":            "Banks (sub-sector of financials)",
    "retail":           "Retail",
    "agriculture":      "Agriculture",
    "critical_minerals": "Critical Minerals",
    "metals":           "Metals & Mining",
    # Macro-driver pseudo-sectors — surface when a shock is rates/fx/credit
    # rather than a real-economy sector.
    "rates":            "Rates shock",
    "credit":           "Credit shock",
    "fx":               "FX / dollar shock",
}


# ---------------------------------------------------------------------------
# Passthrough map — expert-curated sector → downstream dependents.
# Each entry is (target_sector, lag, intensity, sign, mechanism, examples).
# ---------------------------------------------------------------------------

# Valid enum tokens
_LAG_ENUM = frozenset({"immediate", "days", "weeks", "quarters"})
_INTENSITY_ENUM = frozenset({"low", "medium", "high"})
_SIGN_ENUM = frozenset({"reinforcing", "inverse", "mixed"})

# Lag ordering for timing-profile aggregation.
_LAG_WEIGHT: dict[str, int] = {"immediate": 0, "days": 1, "weeks": 2, "quarters": 3}


def _entry(target: str, lag: str, intensity: str, sign: str,
           mechanism: str, examples: tuple[str, ...] = ()) -> dict:
    """Small builder so the big map below stays readable."""
    return {
        "target": target, "lag": lag, "intensity": intensity,
        "sign": sign, "mechanism": mechanism,
        "example_proxies": list(examples),
    }


_PASSTHROUGH_MAP: dict[str, list[dict]] = {
    # Energy shock — fuel costs + feedstocks propagate quickly.
    "energy": [
        _entry("transport",     "days",  "high",   "inverse",
               "fuel cost spike compresses airline / trucking margins",
               ("DAL", "UAL", "LUV", "XTN", "UNP")),
        _entry("chemicals",     "days",  "high",   "inverse",
               "naphtha / ethane feedstock repricing",
               ("LYB", "DOW", "APD")),
        _entry("refiners",      "days",  "medium", "mixed",
               "crack spread may widen or compress depending on product demand",
               ("MPC", "VLO", "PSX", "PBF")),
        _entry("consumer_disc", "weeks", "medium", "inverse",
               "gasoline tax on discretionary spending",
               ("XLY", "HD", "LOW")),
        _entry("utilities",     "weeks", "medium", "mixed",
               "regulated passthrough lags; merchant power squeezed",
               ("XLU",)),
    ],
    # Materials / input shock — margin compression flows downstream.
    "materials": [
        _entry("industrials",   "weeks",    "medium", "inverse",
               "input-cost passthrough to machinery / aerospace margins",
               ("CAT", "DE", "HON", "XLI")),
        _entry("consumer_disc", "quarters", "low",    "inverse",
               "eventual consumer-goods pricing; elasticity varies",
               ("XLY",)),
        _entry("homebuilders",  "weeks",    "medium", "inverse",
               "lumber / steel / copper input pressure on housing margins",
               ("DHI", "LEN", "XHB")),
    ],
    # Critical minerals — semi-specific upstream shock.
    "critical_minerals": [
        _entry("semiconductors", "weeks",    "medium", "inverse",
               "rare-earth / lithium / cobalt input risk for chips",
               ("SMH", "NVDA", "AMD")),
        _entry("defense",        "quarters", "low",    "inverse",
               "rare-earth dependence in missile / radar systems",
               ("LMT", "RTX", "XAR")),
        _entry("industrials",    "weeks",    "medium", "inverse",
               "EV / industrial battery supply-chain exposure",
               ("XLI",)),
    ],
    # Metals — same as materials but mining-focused; routes similarly.
    "metals": [
        _entry("industrials",   "weeks", "medium", "inverse",
               "steel / aluminum input pressure on capital-goods margins",
               ("CAT", "DE", "XLI")),
        _entry("consumer_disc", "weeks", "low",    "inverse",
               "auto / appliance input-cost pressure",
               ("F", "GM")),
    ],
    # Semiconductors shock — capex cycle + downstream tech.
    "semiconductors": [
        _entry("tech_software",  "quarters", "low",    "reinforcing",
               "capacity scarcity supports hyperscaler capex pricing",
               ("MSFT", "GOOGL", "META")),
        _entry("consumer_disc",  "quarters", "low",    "inverse",
               "chip shortages hit auto / consumer electronics",
               ("TSLA", "F")),
    ],
    # Defense — budget-driven, multi-quarter cycle.
    "defense": [
        _entry("industrials",    "quarters", "low",    "reinforcing",
               "defense budget uplift spills to supplier industrials",
               ("XLI", "HON")),
        _entry("materials",      "quarters", "low",    "reinforcing",
               "munitions / armor increase specialty-metal demand",
               ("ATI",)),
    ],
    # Shipping / freight shock — retail + discretionary margin hit.
    "shipping": [
        _entry("retail",         "weeks",    "medium", "inverse",
               "container / tanker rate pass-through to COGS",
               ("WMT", "TGT", "XLP")),
        _entry("consumer_disc",  "weeks",    "medium", "inverse",
               "freight cost pressures discretionary margins",
               ("AMZN", "HD", "XLY")),
        _entry("energy",         "days",     "low",    "mixed",
               "tanker rates feed back into physical crude logistics",
               ("XLE", "FRO", "STNG")),
    ],
    # Agriculture / food shock — consumer staples + EM exposure.
    "agriculture": [
        _entry("consumer_staples", "weeks",    "medium", "inverse",
               "grain / food-cost input pressure on packaged-food margins",
               ("GIS", "K", "XLP")),
        _entry("consumer_disc",    "quarters", "low",    "inverse",
               "restaurant / QSR margin compression",
               ("MCD", "SBUX")),
    ],
    # Financials / bank stress — credit transmission to real economy.
    "financials": [
        _entry("consumer_disc",  "quarters", "medium", "inverse",
               "tighter lending standards hit auto / housing demand",
               ("XLY", "F", "DHI")),
        _entry("real_estate",    "quarters", "high",   "inverse",
               "CRE refinancing squeeze + credit tightening",
               ("XLRE", "VNQ")),
        _entry("industrials",    "quarters", "medium", "inverse",
               "capex demand softens as credit tightens",
               ("CAT", "XLI")),
    ],
    # Healthcare — mostly idiosyncratic; minimal direct-sector cascades.
    "healthcare": [
        _entry("consumer_staples", "quarters", "low", "mixed",
               "pharma / grocery channel overlap on pricing policy",
               ("XLP",)),
    ],
    # Communication services — ad-cycle exposure to consumer discretionary.
    "communication": [
        _entry("consumer_disc",  "quarters", "low",    "reinforcing",
               "ad spend cycle correlates with consumer demand",
               ("XLY",)),
    ],
    # Tech / software — direct cloud-capex dependency on semis (reverse).
    "tech_software": [
        _entry("semiconductors", "quarters", "medium", "reinforcing",
               "cloud capex guidance drives chip orders",
               ("NVDA", "AMD", "SMH")),
    ],
    # Utilities — low-cascade but housing / rates-adjacent.
    "utilities": [
        _entry("real_estate",    "weeks", "low", "reinforcing",
               "rate-sensitivity overlap with REITs",
               ("XLRE",)),
    ],
    # Consumer discretionary — mostly a downstream target, but leaks back
    # to financials via credit-card / auto-loan quality.
    "consumer_disc": [
        _entry("financials",     "quarters", "low", "inverse",
               "weakening consumer → credit-card / auto-loan delinquencies",
               ("XLF", "COF", "ALLY")),
    ],
    # Real estate — direct adjacency to banks (CRE exposure).
    "real_estate": [
        _entry("financials",     "weeks",    "medium", "inverse",
               "CRE loss provisioning pressure on bank earnings",
               ("KRE", "XLF", "JPM")),
        _entry("homebuilders",   "weeks",    "medium", "reinforcing",
               "same rate / credit regime drives both",
               ("DHI", "LEN", "XHB")),
    ],
    # Consumer staples — defensives; minimal downstream cascade.
    "consumer_staples": [],
    # ---------- Macro-driver pseudo-sectors ----------
    "rates": [
        _entry("banks",          "days",  "medium", "reinforcing",
               "rising rates lift NIM for deposit-franchise banks",
               ("JPM", "BAC", "WFC", "XLF")),
        _entry("real_estate",    "days",  "high",   "inverse",
               "discount-rate pressure on REIT valuations + CRE financing",
               ("XLRE", "VNQ", "PLD", "AMT")),
        _entry("homebuilders",   "weeks", "high",   "inverse",
               "mortgage-rate passthrough slows new-home demand",
               ("DHI", "LEN", "PHM", "XHB")),
        _entry("utilities",      "days",  "high",   "inverse",
               "bond-proxy status → inverse duration exposure",
               ("XLU", "NEE", "DUK")),
        _entry("tech_software",  "days",  "medium", "inverse",
               "long-duration growth discounted harder as real yields rise",
               ("XLK", "MSFT", "GOOGL")),
    ],
    "credit": [
        _entry("financials",     "days",    "high",   "inverse",
               "spread widening prices credit losses into bank equity",
               ("XLF", "JPM", "BAC", "C")),
        _entry("real_estate",    "weeks",   "high",   "inverse",
               "refinancing pressure when HY-IG spreads open",
               ("XLRE", "VNQ")),
        _entry("consumer_disc",  "weeks",   "medium", "inverse",
               "leveraged retailers and auto-finance exposure",
               ("F", "GM", "XLY")),
        _entry("industrials",    "weeks",   "medium", "inverse",
               "BBB-heavy industrial balance sheets re-price",
               ("XLI",)),
    ],
    "fx": [
        _entry("materials",      "days",    "medium", "mixed",
               "dollar-strength weighs on commodity-priced producers",
               ("FCX", "NEM", "GOLD", "XLB")),
        _entry("energy",         "days",    "medium", "mixed",
               "crude priced in USD — stronger dollar = weaker crude tape",
               ("XLE", "CVX", "XOM")),
        _entry("semiconductors", "weeks",   "low",    "mixed",
               "EM-FX driven demand / input mix effects",
               ("TSM", "SMH")),
        _entry("consumer_staples", "quarters", "low", "inverse",
               "US multinationals lose translation revenue on strong USD",
               ("PG", "KO", "XLP")),
    ],
}


# ---------------------------------------------------------------------------
# Direct-hit detection helpers
# ---------------------------------------------------------------------------

# Mapping from news-consensus sector labels to our canonical keys.
_NEWS_SECTOR_TO_CANONICAL: dict[str, str] = {
    "critical minerals": "critical_minerals",
    "semiconductors":    "semiconductors",
    "energy":            "energy",
    "metals":            "metals",
    "defense":           "defense",
    "shipping":          "shipping",
    "agriculture":       "agriculture",
    "finance":           "financials",
}

# Shock-decomposition primary channels that map to macro-driver sources.
_SHOCK_TO_SECTOR: dict[str, str] = {
    "nominal_yield": "rates",
    "real_yield":    "rates",
    "breakeven":     "rates",
    "fx":            "fx",
    "credit":        "credit",
    "commodity":     "energy",  # most commodity-led shocks are energy-adjacent
}


def _sectors_from_tickers(tickers: Iterable[str]) -> list[str]:
    """Resolve each ticker to its sector via market_check.resolve_benchmark."""
    from market_check import resolve_benchmark  # local import: avoid cycle
    out: list[str] = []
    seen: set[str] = set()
    for t in tickers or []:
        if not isinstance(t, str) or not t.strip():
            continue
        _bench, sector = resolve_benchmark(t)
        if sector in ("market", "unknown", ""):
            continue
        if sector in seen:
            continue
        seen.add(sector)
        out.append(sector)
    return out


def _sectors_from_mechanism_text(text: str) -> list[str]:
    """Scan the mechanism text for news-consensus sector keywords."""
    if not text or not isinstance(text, str):
        return []
    try:
        from news_consensus import _SECTOR_KEYWORDS, _scan_keywords
    except ImportError:
        return []
    try:
        hits = _scan_keywords(text, _SECTOR_KEYWORDS)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for h in hits or []:
        canon = _NEWS_SECTOR_TO_CANONICAL.get(h)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _timing_profile(downstream: list[dict]) -> str:
    """Classify the timing profile of the downstream cascade.

    fast_cascade  — majority of entries at ``immediate`` or ``days``
    slow_cascade  — majority at ``weeks`` or ``quarters``
    mixed         — clear split across fast and slow bands
    no_downstream — empty list
    """
    if not downstream:
        return "no_downstream"
    fast = sum(1 for e in downstream if _LAG_WEIGHT.get(e.get("lag"), 99) <= 1)
    slow = sum(1 for e in downstream if _LAG_WEIGHT.get(e.get("lag"), 99) >= 2)
    if fast == 0 and slow > 0:
        return "slow_cascade"
    if slow == 0 and fast > 0:
        return "fast_cascade"
    if fast >= 2 * slow:
        return "fast_cascade"
    if slow >= 2 * fast:
        return "slow_cascade"
    return "mixed"


def _rationale(direct_sectors: list[str], downstream: list[dict],
               timing: str) -> str:
    if not direct_sectors:
        return "No direct-hit sector resolved from inputs — downstream read skipped."
    direct_label = ", ".join(SECTOR_LABELS.get(s, s) for s in direct_sectors)
    if not downstream:
        return f"Direct hit: {direct_label}. No structured downstream cascade mapped."
    top = downstream[0]
    top_label = SECTOR_LABELS.get(top["target"], top["target"])
    return (
        f"Direct hit: {direct_label}. Top downstream: {top_label} "
        f"({top['lag']}, {top['intensity']} intensity, {top['sign']}) — "
        f"{len(downstream)} downstream candidates on a {timing.replace('_', ' ')} profile."
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def compute_sector_passthrough(
    beneficiary_tickers: Optional[list[str]] = None,
    loser_tickers: Optional[list[str]] = None,
    mechanism_text: str = "",
    shock_primary: Optional[str] = None,
) -> dict:
    """Build the sector-passthrough block.

    Direct-hit resolution precedence:
      1. Union of ticker-derived sectors (beneficiary + loser lists)
      2. Mechanism-text sector keywords (news_consensus map)
      3. shock_decomposition primary channel → macro pseudo-sector

    Downstream candidates come from the static passthrough map, deduped
    and sorted by (intensity, lag) so the highest-conviction / fastest
    cascades lead the list.
    """
    ticker_sectors = _sectors_from_tickers(
        list(beneficiary_tickers or []) + list(loser_tickers or [])
    )
    text_sectors = _sectors_from_mechanism_text(mechanism_text)

    # Union preserving precedence order.
    direct_sectors: list[str] = []
    seen: set[str] = set()
    for s in ticker_sectors + text_sectors:
        if s not in seen:
            seen.add(s)
            direct_sectors.append(s)

    # Fall back to shock-primary when tickers + text yield nothing.
    if not direct_sectors and shock_primary:
        macro_source = _SHOCK_TO_SECTOR.get(shock_primary)
        if macro_source and macro_source not in seen:
            direct_sectors.append(macro_source)

    # Resolve downstream candidates.  Dedup by target sector; the strongest
    # (intensity, shortest lag) source wins when two directs cascade to the
    # same target.
    _INTENSITY_RANK = {"high": 0, "medium": 1, "low": 2}
    by_target: dict[str, dict] = {}
    for src in direct_sectors:
        for cand in _PASSTHROUGH_MAP.get(src, []):
            target = cand["target"]
            if target in direct_sectors:
                # A direct sector is never also a downstream target.
                continue
            existing = by_target.get(target)
            if existing is None:
                by_target[target] = {**cand, "source": src,
                                     "target_label": SECTOR_LABELS.get(target, target)}
                continue
            # Prefer the higher-intensity / faster-lag entry.
            new_rank = (_INTENSITY_RANK.get(cand["intensity"], 99),
                        _LAG_WEIGHT.get(cand["lag"], 99))
            old_rank = (_INTENSITY_RANK.get(existing["intensity"], 99),
                        _LAG_WEIGHT.get(existing["lag"], 99))
            if new_rank < old_rank:
                by_target[target] = {**cand, "source": src,
                                     "target_label": SECTOR_LABELS.get(target, target)}

    downstream = sorted(
        by_target.values(),
        key=lambda e: (_INTENSITY_RANK.get(e["intensity"], 99),
                       _LAG_WEIGHT.get(e["lag"], 99),
                       e["target"]),
    )

    timing = _timing_profile(downstream)
    available = bool(direct_sectors)

    return {
        "direct_sectors":        direct_sectors,
        "direct_sectors_label":  [SECTOR_LABELS.get(s, s) for s in direct_sectors],
        "downstream":            downstream,
        "timing_profile":        timing,
        # Validation tiers — consumers should check alpha within these windows.
        "direct_validation_window":     "1-5d",
        "downstream_validation_window": "5-20d",
        "rationale":             _rationale(direct_sectors, downstream, timing),
        "available":             available,
        "stale":                 not available,
    }

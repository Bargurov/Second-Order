"""
mechanism_family.py

Mechanism-family taxonomy + canonical cross-asset channel packs.

Every macro event fits roughly into one of a small number of
well-understood *family* archetypes — a tariff, a sanction, a supply
shock, a central-bank surprise, and so on.  Each family has a well-worn
cross-asset playbook: which channels move first, which follow, which
tend to be silent.  This module encodes that taxonomy as data so:

  1. The LLM prompt can force a commit to exactly one family per event.
  2. A deterministic keyword classifier can backfill the family when the
     LLM output is thin or empty.
  3. Downstream composers can look up the canonical expected-channel
     pack for the family and compare it against the live tape.

Public API
----------
    FAMILY_IDS                      tuple of all valid family ids
    FAMILY_LABELS                   dict mapping id → human label
    FAMILY_CHANNEL_PACKS            dict mapping id → {first, second} channel lists
    CHANNEL_IDS                     canonical 6-channel universe
    get_default_channel_pack(fam)   → {first, second} for the family
    classify_family(headline, mech) → family id (keyword-based, deterministic)

    BOTTLENECK_IDS / BOTTLENECK_LABELS           — forensic mechanism-type taxonomy
    TRANSMISSION_TYPE_IDS / TRANSMISSION_TYPE_LABELS — how the shock propagates
    CHANNEL_DOMAIN_IDS / CHANNEL_DOMAIN_LABELS   — which market-structure channel carries it
    is_valid_bottleneck / is_valid_transmission_type / is_valid_channel_domain
                                    → enum-membership guards the sanitizer uses

Channel universe
----------------
Grouped to match cross_asset_coherence + shock_decomposition:

    rates         — nominal rates (10Y)
    fx            — dollar / cross-rate FX
    commodities   — oil, gold, base metals
    vol           — equity vol (VIX)
    credit        — HY / IG credit spreads
    equities      — broad index + sector-level reactions

Pure data module — no I/O, no external imports.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Channel universe — must match cross_asset_coherence.CHANNEL_IDS
# ---------------------------------------------------------------------------

CHANNEL_IDS: tuple[str, ...] = (
    "rates",
    "fx",
    "commodities",
    "vol",
    "credit",
    "equities",
)


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

FAMILY_IDS: tuple[str, ...] = (
    "tariff",
    "sanction",
    "supply_shock",
    "ceasefire_deescalation",
    "policy_surprise",
    "fiscal_issuance",
    "labor_inflation",
    "bank_stress",
    "commodity_squeeze",
    "supply_normalization",
    # Coverage expansion — themes the original registry structurally
    # missed.  Each family has its own distinctive validation matrix
    # (see FAMILY_VALIDATION_MATRIX) so they aren't redundant with the
    # existing ten.
    "industrial_policy",     # IRA / CHIPS Act / EU green deal / subsidy packages
    "regulation",            # antitrust / merger block / capital rules / disclosure
    "external_balance",      # EM BOP / reserves / sovereign credit / capital flight
    "none",
)


FAMILY_LABELS: dict[str, str] = {
    "tariff":                 "Tariff / trade barrier",
    "sanction":               "Sanction / restriction",
    "supply_shock":           "Supply shock",
    "ceasefire_deescalation": "Ceasefire / de-escalation",
    "policy_surprise":        "Central-bank / policy surprise",
    "fiscal_issuance":        "Fiscal issuance",
    "labor_inflation":        "Labor / wage inflation",
    "bank_stress":            "Bank / financial-system stress",
    "commodity_squeeze":      "Commodity squeeze",
    "supply_normalization":   "Supply normalization / relief",
    "industrial_policy":      "Industrial policy / subsidy package",
    "regulation":             "Regulation / antitrust",
    "external_balance":       "External balance / EM funding stress",
    "none":                   "No clear family",
}


# ---------------------------------------------------------------------------
# Canonical channel packs per family
# ---------------------------------------------------------------------------
# "first" = the channel(s) that tend to move first in the family's classic
# playbook.  "second" = the cascade channels that follow.  Channels listed
# in neither list are treated as "silent by default" for the family.
# These packs are used as priors: the LLM can override per event, but
# when it doesn't, the composer still surfaces a sensible expectation.

FAMILY_CHANNEL_PACKS: dict[str, dict[str, list[str]]] = {
    "tariff": {
        "first":  ["commodities", "equities", "fx"],
        "second": ["rates", "credit"],
    },
    "sanction": {
        "first":  ["commodities", "fx", "equities"],
        "second": ["credit", "vol"],
    },
    "supply_shock": {
        "first":  ["commodities", "equities"],
        "second": ["rates", "fx", "credit"],
    },
    "ceasefire_deescalation": {
        "first":  ["vol", "equities", "commodities"],
        "second": ["credit", "fx"],
    },
    "policy_surprise": {
        "first":  ["rates", "fx", "vol"],
        "second": ["credit", "equities", "commodities"],
    },
    "fiscal_issuance": {
        "first":  ["rates", "fx"],
        "second": ["credit", "equities"],
    },
    "labor_inflation": {
        "first":  ["rates", "equities"],
        "second": ["fx", "commodities"],
    },
    "bank_stress": {
        "first":  ["credit", "equities", "vol"],
        "second": ["rates", "fx"],
    },
    "commodity_squeeze": {
        "first":  ["commodities", "equities"],
        "second": ["rates", "fx"],
    },
    "supply_normalization": {
        "first":  ["commodities", "equities"],
        "second": ["credit", "rates", "fx"],
    },
    "industrial_policy": {
        # Equity sector dispersion is the primary read — beneficiaries
        # (semis, clean-tech, EV) vs losers (incumbent fossil, traditional
        # autos) — rather than a broad-index move.  Rates stay quiet
        # unless the package is large enough to trigger the
        # ``fiscal_issuance`` family instead.
        "first":  ["equities"],
        "second": ["credit", "rates", "fx"],
    },
    "regulation": {
        # Targeted-company equity move + event-driven vol; other macro
        # channels are typically silent for single-name regulatory hits
        # (merger block, consent decree, capital requirement hike).
        "first":  ["equities", "vol"],
        "second": ["credit"],
    },
    "external_balance": {
        # EM currency + sovereign credit lead; US tape quiet.  Equities
        # and commodities follow as capital-flight contagion spreads.
        "first":  ["fx", "credit"],
        "second": ["equities", "commodities"],
    },
    "none": {
        "first":  [],
        "second": [],
    },
}


def get_default_channel_pack(family: str) -> dict[str, list[str]]:
    """Return a deep-copied canonical pack for ``family`` (safe to mutate)."""
    pack = FAMILY_CHANNEL_PACKS.get(family) or FAMILY_CHANNEL_PACKS["none"]
    return {
        "first":  list(pack["first"]),
        "second": list(pack["second"]),
    }


# ---------------------------------------------------------------------------
# Family-allowed transmission channels — the second registry the
# transmission_path validator checks against.  ``FAMILY_CHANNEL_PACKS``
# above lists asset-class channels (rates / fx / commodities / vol /
# credit / equities); this registry lists the TRANSMISSION-MODE tokens
# (policy_gate / supply / pricing_power / etc.) the ``transmission_path``
# hop schema uses.
#
# A chain whose hops mostly use channels NOT in this set for the
# committed family is a sign the LLM picked the wrong family or
# articulated the wrong cascade — the chain-family consistency gate
# downgrades these to ``watch_only`` (or ``low_information`` when
# the conflict is severe).  ``"none"`` permits the full enum so an
# uncommitted family doesn't trip the gate.

FAMILY_TRANSMISSION_CHANNELS: dict[str, frozenset[str]] = {
    "tariff": frozenset({
        "tariff", "supply", "demand", "pricing_power",
        "substitution", "regulatory",
    }),
    "sanction": frozenset({
        "sanction", "supply", "regulatory", "policy_gate",
        "capital_flow", "substitution", "pricing_power",
    }),
    "supply_shock": frozenset({
        "supply", "pricing_power", "substitution", "demand",
    }),
    "ceasefire_deescalation": frozenset({
        "supply", "demand", "capital_flow", "regulatory",
        "policy_gate",
    }),
    "policy_surprise": frozenset({
        "policy_gate", "rate_transmission", "capital_flow",
        "regulatory",
    }),
    "fiscal_issuance": frozenset({
        "capital_flow", "rate_transmission", "demand",
        "policy_gate",
    }),
    "labor_inflation": frozenset({
        "demand", "pricing_power", "rate_transmission",
    }),
    "bank_stress": frozenset({
        "capital_flow", "rate_transmission", "regulatory",
        "pricing_power",
    }),
    "commodity_squeeze": frozenset({
        "supply", "pricing_power", "substitution", "demand",
    }),
    "supply_normalization": frozenset({
        "supply", "pricing_power", "substitution", "sanction",
        "regulatory", "policy_gate",
    }),
    "industrial_policy": frozenset({
        "regulatory", "supply", "demand", "capital_flow",
        "policy_gate", "substitution",
    }),
    "regulation": frozenset({
        "regulatory", "policy_gate", "pricing_power",
    }),
    "external_balance": frozenset({
        "capital_flow", "rate_transmission", "regulatory",
        "pricing_power",
    }),
    # "none" — no committed family, no channel constraint applied.
    "none": frozenset({
        "policy_gate", "supply", "demand", "pricing_power",
        "capital_flow", "substitution", "regulatory", "sanction",
        "tariff", "rate_transmission",
    }),
}


def get_family_transmission_channels(family: str) -> frozenset[str]:
    """Return the allowed transmission-channel set for ``family``.

    Falls back to the unconstrained "none" set when ``family`` is
    unknown or empty — callers always get a usable frozenset.
    """
    if not isinstance(family, str) or not family.strip():
        return FAMILY_TRANSMISSION_CHANNELS["none"]
    key = family.strip().lower()
    return FAMILY_TRANSMISSION_CHANNELS.get(
        key, FAMILY_TRANSMISSION_CHANNELS["none"],
    )


# ---------------------------------------------------------------------------
# Per-family validation matrix
# ---------------------------------------------------------------------------
# The channel-pack registry above says which channels move when; this
# registry answers the richer question a desk asks after an event:
# "what should confirm the thesis, what should fool me, and what would
# break it?"  Each family carries five structured rows:
#
#   primary            — channels / markets that should confirm FIRST
#   secondary          — cascade channels that confirm after the primary
#   false_positives    — channels that often LOOK like confirmation but
#                        aren't mechanism-specific; each entry names a
#                        distinguishing_signal that separates real from
#                        coincidental alignment
#   invalidation       — the strongest falsifiers — concrete signals
#                        that, if observed, break the thesis outright
#   timing_by_channel  — horizon for each expected-move channel, drawn
#                        from a small controlled vocabulary
#
# Invariant: every channel listed in FAMILY_CHANNEL_PACKS[family]["first"]
# must appear in FAMILY_VALIDATION_MATRIX[family]["primary"].
# (Enforced by tests/test_validation_matrix.py.)

# Controlled timing vocabulary — four fixed buckets.  Free text is not
# allowed; the validation engine branches on these exact tokens.
TIMING_VOCABULARY: tuple[str, ...] = ("1d", "1-5d", "5-20d", "20d+")


FAMILY_VALIDATION_MATRIX: dict[str, dict] = {
    "tariff": {
        "primary": [
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["KWEB", "FXI"],
             "rationale": "Tariff-exposed China baskets sell off; domestic protected sectors rally — watch sector dispersion vs the broad tape."},
            {"channel": "commodities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["DBA", "CPER"],
             "rationale": "Targeted agricultural / metal complex reprices at the tariff wedge."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["CYB", "CEW"],
             "rationale": "Affected-country currency weakens vs USD on trade-balance drag (CYB for CNY tariff cases, CEW for broader EM)."},
        ],
        "secondary": [
            {"channel": "rates", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Inflation pass-through lifts breakevens; growth drag offsets at the long end."},
            {"channel": "credit", "expected_direction": "wider", "timing": "5-20d",
             "named_assets": ["HYG", "JNK"],
             "rationale": "Margin squeeze on import-dependent HY issuers widens spreads."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "Broad index rally can mask sector dispersion — pro-tariff and anti-tariff sectors offset",
             "primary_basket": ["KWEB", "FXI"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Check tariff-exposed ETFs (KWEB, EWH, FXI) vs SPY absolute; dispersion is the real signal."},
        ],
        "invalidation": [
            {"signal": "Tariff-exposed sector ETFs recover within 1d on carve-out rumours",
             "channel": "equities", "timing": "1d"},
            {"signal": "Targeted commodity price moves opposite the tariff wedge within 5d",
             "channel": "commodities", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "equities": "1d", "commodities": "1d", "fx": "1d",
            "rates": "5-20d", "credit": "5-20d",
        },
    },
    "sanction": {
        "primary": [
            {"channel": "commodities", "expected_direction": "up", "timing": "1d",
             "named_assets": ["USO", "UNG", "URA"],
             "rationale": "Targeted commodity supply premium widens on access cut (oil for Russia/Iran cases, gas for LNG cuts, uranium for nuclear-fuel sanctions)."},
            {"channel": "fx", "expected_direction": "up", "timing": "1d",
             "named_assets": ["UUP", "CEW"],
             "rationale": "USD strength on safe-haven flows; affected-country EM currency basket collapses (CEW reads the EM cross)."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["KWEB", "FXI"],
             "rationale": "Sanctioned-country equity baskets sell; alternative-supplier equities rally."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "wider", "timing": "5-20d",
             "named_assets": ["HYG", "EMB"],
             "rationale": "Counterparty-risk repricing on exposed HY and EM credit."},
            {"channel": "vol", "expected_direction": "up", "timing": "1-5d",
             "named_assets": ["VXX", "VIXY"],
             "rationale": "Event-driven vol premium on geopolitical tail risk."},
        ],
        "false_positives": [
            {"channel": "commodities", "reason": "Broad commodity rally on weaker USD, not sanction-specific supply premium",
             "primary_basket": ["USO"],
             "false_basket": ["DBA", "CPER"],
             "distinguishing_signal": "Sanctioned commodity should outperform its peers (Russian oil vs Brent, not oil broadly)."},
        ],
        "invalidation": [
            {"signal": "Sanctioned commodity premium collapses on licence / carve-out issuance",
             "channel": "commodities", "timing": "1-5d"},
            {"signal": "Alternative-supplier equities fail to rally within 5d",
             "channel": "equities", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "commodities": "1d", "fx": "1d", "equities": "1d",
            "credit": "5-20d", "vol": "1-5d",
        },
    },
    "supply_shock": {
        "primary": [
            {"channel": "commodities", "expected_direction": "up", "timing": "1d",
             "named_assets": ["USO", "UNG"],
             "rationale": "Direct physical-supply squeeze on affected commodity (energy is the dominant case; specialise to DBA/CPER for ag/metal shocks)."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["XLE", "XME"],
             "rationale": "Producers of the squeezed input (XLE energy, XME metals) rally; consumers / downstream squeezed on margin."},
        ],
        "secondary": [
            {"channel": "rates", "expected_direction": "up", "timing": "5-20d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Breakeven inflation repricing as pass-through hits CPI."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["UUP", "CEW"],
             "rationale": "Commodity-exporter currencies firm; importer currencies weaken — read DXY-proxy UUP vs the EM basket CEW."},
            {"channel": "credit", "expected_direction": "wider", "timing": "5-20d",
             "named_assets": ["HYG", "JNK"],
             "rationale": "Consumer-discretionary HY widens on margin compression."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "SPY rallies alongside commodity producers and masks the sector dispersion",
             "primary_basket": ["XLE", "XME"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Watch XLE / XME vs SPY — producer outperformance is the real confirm, not index direction."},
            {"channel": "commodities", "reason": "Dollar-driven commodity rally moves the complex together without supply specificity",
             "primary_basket": ["USO"],
             "false_basket": ["DBA", "CPER"],
             "distinguishing_signal": "The affected commodity should outpace the broader complex; check affected vs peer spread."},
        ],
        "invalidation": [
            {"signal": "Affected commodity reverses >50% of headline move within 1d",
             "channel": "commodities", "timing": "1d"},
            {"signal": "Producer margins flat in quarterly guidance despite price spike",
             "channel": "equities", "timing": "20d+"},
        ],
        "timing_by_channel": {
            "commodities": "1d", "equities": "1d",
            "rates": "5-20d", "fx": "5-20d", "credit": "5-20d",
        },
    },
    "ceasefire_deescalation": {
        "primary": [
            {"channel": "vol", "expected_direction": "down", "timing": "1d",
             "named_assets": ["VXX", "VIXY"],
             "rationale": "Event-premium unwind on de-escalation headline."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["ITA", "XAR", "BDRY"],
             "rationale": "Defense / shipping baskets sell; cyclicals + risk-on assets rally."},
            {"channel": "commodities", "expected_direction": "down", "timing": "1d",
             "named_assets": ["USO"],
             "rationale": "Oil / geopolitical-risk premium fades."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "tighter", "timing": "5-20d",
             "named_assets": ["HYG", "EMB"],
             "rationale": "Risk appetite returns; HY and EM spreads tighten."},
            {"channel": "fx", "expected_direction": "down", "timing": "1-5d",
             "named_assets": ["UUP"],
             "rationale": "Safe-haven dollar bid fades."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "SPY rally looks like de-escalation confirmation but is often just broad risk-on",
             "primary_basket": ["ITA", "XAR", "BDRY"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Defense / shipping underperformance (ITA, XAR, BDRY vs SPY) is the purer read."},
        ],
        "invalidation": [
            {"signal": "Oil reverses higher within 1d on follow-up headline",
             "channel": "commodities", "timing": "1d"},
            {"signal": "Defense names rally instead of selling",
             "channel": "equities", "timing": "1d"},
        ],
        "timing_by_channel": {
            "vol": "1d", "equities": "1d", "commodities": "1d",
            "credit": "5-20d", "fx": "1-5d",
        },
    },
    "policy_surprise": {
        "primary": [
            {"channel": "rates", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["SHY", "IEF", "TLT"],
             "rationale": "Front-end rates (SHY) reprice immediately to the surprise; long end (TLT/IEF) follows the path read."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["UUP", "FXE", "FXY"],
             "rationale": "Rate-differential move drives the dollar / cross-rate (UUP for USD, FXE for EUR cases, FXY for JPY)."},
            {"channel": "vol", "expected_direction": "up", "timing": "1d",
             "named_assets": ["VXX", "VIXY"],
             "rationale": "Surprise magnitude reprices rate vol and equity vol."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["LQD", "HYG"],
             "rationale": "Financial-conditions pass-through to HY / IG spreads."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1-5d",
             "named_assets": ["KRE", "XLU", "XLRE"],
             "rationale": "Rate-sensitive sectors (regional banks, utilities, REITs) reprice within the week — SPY direction is a noisier read."},
            {"channel": "commodities", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["GLD", "USO"],
             "rationale": "Dollar-linked commodity repricing after FX settles (gold leads on rate-cut cases, oil on hawkish ones)."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "SPY direction often diverges from rate-sensitive sectors on a surprise day",
             "primary_basket": ["KRE", "XLU", "XLRE"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Rate-sensitive ETFs (KRE, XLU, XLRE) move first; SPY catches up or diverges — watch the relative."},
        ],
        "invalidation": [
            {"signal": "Front-end rates retrace >50% of headline move within 1d",
             "channel": "rates", "timing": "1d"},
            {"signal": "DXY drifts against the surprise direction within 1d",
             "channel": "fx", "timing": "1d"},
        ],
        "timing_by_channel": {
            "rates": "1d", "fx": "1d", "vol": "1d",
            "credit": "5-20d", "equities": "1-5d", "commodities": "5-20d",
        },
    },
    "fiscal_issuance": {
        "primary": [
            {"channel": "rates", "expected_direction": "up", "timing": "1d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Term-premium repricing on heavier supply hits the long end (TLT) hardest."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["UUP", "UDN"],
             "rationale": "Dollar direction depends on whether supply is demand- or debt-sustainability-driven (UUP up on safe-haven demand, UDN up on sustainability fear)."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "wider", "timing": "5-20d",
             "named_assets": ["LQD", "HYG"],
             "rationale": "Duration-heavy credit widens on rates sell-off."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1-5d",
             "named_assets": ["XLK", "XLRE"],
             "rationale": "Long-duration equities (tech, REITs) underperform on rate shock."},
        ],
        "false_positives": [
            {"channel": "rates", "reason": "Curve steepens for auction-technical reasons unrelated to thesis",
             "primary_basket": ["TLT"],
             "false_basket": ["IEF", "SHY"],
             "distinguishing_signal": "Check 10s-30s spread vs 2s-10s — term-premium story is the long end (TLT), not the belly."},
        ],
        "invalidation": [
            {"signal": "Auction stops through expected yield",
             "channel": "rates", "timing": "1d"},
            {"signal": "Term premium collapses within 5d",
             "channel": "rates", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "rates": "1d", "fx": "1d",
            "credit": "5-20d", "equities": "1-5d",
        },
    },
    "labor_inflation": {
        "primary": [
            {"channel": "rates", "expected_direction": "up", "timing": "1d",
             "named_assets": ["SHY", "IEF"],
             "rationale": "Front-end rates (SHY) reprice hike expectations on sticky wage data."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["XLY", "XLF"],
             "rationale": "Margin-sensitive consumer discretionary (XLY) sells on wage cost pressure; financials (XLF) rally on higher rates."},
        ],
        "secondary": [
            {"channel": "fx", "expected_direction": "up", "timing": "1-5d",
             "named_assets": ["UUP"],
             "rationale": "Dollar strength on rate differential."},
            {"channel": "commodities", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["GLD", "USO"],
             "rationale": "Demand-signal vs dollar-strength tug-of-war (gold reads the inflation hedge, oil reads the demand."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "Index rally on strong jobs headline can mask margin-squeeze sectors underperforming",
             "primary_basket": ["XLY"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Watch XLY / XRT vs SPY — consumer-facing margin-sensitive names are the cleanest read."},
        ],
        "invalidation": [
            {"signal": "Average hourly earnings revision lower within 20d",
             "channel": "rates", "timing": "20d+"},
            {"signal": "Rate-sensitive sectors rally within 1d — suggests market sees data as noise",
             "channel": "equities", "timing": "1d"},
        ],
        "timing_by_channel": {
            "rates": "1d", "equities": "1d",
            "fx": "1-5d", "commodities": "5-20d",
        },
    },
    "bank_stress": {
        "primary": [
            {"channel": "credit", "expected_direction": "wider", "timing": "1d",
             "named_assets": ["HYG", "LQD"],
             "rationale": "HY / IG spreads widen on counterparty-risk repricing."},
            {"channel": "equities", "expected_direction": "down", "timing": "1d",
             "named_assets": ["KRE", "KBE"],
             "rationale": "Regional and money-centre bank baskets sell off sharply (KRE/KBE underperform XLF)."},
            {"channel": "vol", "expected_direction": "up", "timing": "1d",
             "named_assets": ["VXX", "VIXY"],
             "rationale": "VIX spikes on systemic-risk premium."},
        ],
        "secondary": [
            {"channel": "rates", "expected_direction": "down", "timing": "1-5d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Safe-haven bid drives Treasuries; front-end reprices cut expectations."},
            {"channel": "fx", "expected_direction": "up", "timing": "1-5d",
             "named_assets": ["UUP"],
             "rationale": "Dollar strength on liquidity flight."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "SPY drops on the headline but large-cap financials can recover while regional banks remain under stress",
             "primary_basket": ["KRE", "KBE"],
             "false_basket": ["XLF", "SPY"],
             "distinguishing_signal": "KRE / KBE vs XLF relative — regional-bank underperformance is the thesis read, not SPY direction."},
        ],
        "invalidation": [
            {"signal": "Credit spreads tighten within 5d despite headline",
             "channel": "credit", "timing": "1-5d"},
            {"signal": "Regional bank ETF (KRE) recovers to pre-event level within 5d",
             "channel": "equities", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "credit": "1d", "equities": "1d", "vol": "1d",
            "rates": "1-5d", "fx": "1-5d",
        },
    },
    "commodity_squeeze": {
        "primary": [
            {"channel": "commodities", "expected_direction": "up", "timing": "1d",
             "named_assets": ["USO", "UNG", "CPER"],
             "rationale": "Targeted commodity spikes on physical-flow constraint (specialise to oil/gas/copper depending on which complex is squeezed)."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["XLE", "XME"],
             "rationale": "Producer baskets (energy XLE, metals XME) rally; consumers squeezed on input cost."},
        ],
        "secondary": [
            {"channel": "rates", "expected_direction": "up", "timing": "5-20d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Breakeven inflation repricing."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["UUP", "FXC"],
             "rationale": "Commodity-exporter currencies firm (FXC for CAD, FXA for AUD); UUP softens vs the exporter basket."},
        ],
        "false_positives": [
            {"channel": "commodities", "reason": "Broad commodity rally on dollar weakness, not squeeze-specific",
             "primary_basket": ["USO"],
             "false_basket": ["DBA", "GLD"],
             "distinguishing_signal": "Affected commodity should lead its complex — check spread vs peers (Brent vs WTI, copper vs base metals)."},
        ],
        "invalidation": [
            {"signal": "Commodity curve flattens within 1-5d — suggests physical tightness priced out",
             "channel": "commodities", "timing": "1-5d"},
            {"signal": "Producer equities fail to rally despite price spike",
             "channel": "equities", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "commodities": "1d", "equities": "1d",
            "rates": "5-20d", "fx": "5-20d",
        },
    },
    "supply_normalization": {
        "primary": [
            {"channel": "commodities", "expected_direction": "down", "timing": "1d",
             "named_assets": ["USO", "UNG"],
             "rationale": "Restored physical supply compresses the scarcity premium."},
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["XLY", "XLE"],
             "rationale": "Downstream beneficiaries (consumer discretionary XLY, refiners) rally; producer-side XLE squeezed as scarcity trade unwinds."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "tighter", "timing": "5-20d",
             "named_assets": ["HYG", "JNK"],
             "rationale": "Consumer-discretionary HY tightens as margin pressure eases."},
            {"channel": "rates", "expected_direction": "down", "timing": "5-20d",
             "named_assets": ["TLT", "IEF"],
             "rationale": "Breakeven inflation drifts lower on commodity deflation."},
            {"channel": "fx", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["UUP", "FXC"],
             "rationale": "Commodity-exporter currencies (FXC) soften; importer currencies firm relative to UUP."},
        ],
        "false_positives": [
            {"channel": "commodities", "reason": "Broad commodity complex softens on dollar strength rather than supply-specific normalisation",
             "primary_basket": ["USO"],
             "false_basket": ["DBA", "GLD"],
             "distinguishing_signal": "Affected commodity should underperform its peers — check spread vs complex."},
        ],
        "invalidation": [
            {"signal": "Loading / shipping data fails to confirm volume ramp within 5d",
             "channel": "commodities", "timing": "1-5d"},
            {"signal": "Scarcity-premium unwind reverses on infrastructure / political setback",
             "channel": "commodities", "timing": "1-5d"},
        ],
        "timing_by_channel": {
            "commodities": "1d", "equities": "1d",
            "credit": "5-20d", "rates": "5-20d", "fx": "5-20d",
        },
    },
    "industrial_policy": {
        # Signature: equity SECTOR DISPERSION around targeted beneficiaries
        # and losers; macro channels stay quiet.  If rates move materially,
        # the event is probably better classified as ``fiscal_issuance``.
        "primary": [
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["SMH", "ITA", "XLE"],
             "rationale": "Beneficiary sector baskets (semis SMH, defense ITA, clean-tech) rally; incumbent losers (fossil XLE, traditional autos) sell — sector dispersion is the real signal, not index level."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["HYG", "LQD"],
             "rationale": "Beneficiary-sector HY tightens on subsidy-supported cash flows; losers widen on margin risk."},
            {"channel": "fx", "expected_direction": "up", "timing": "5-20d",
             "named_assets": ["UUP"],
             "rationale": "Large packages (IRA-scale) attract in-shoring capex which lifts the domestic currency on capital-inflow narrative."},
            {"channel": "rates", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["IEF", "TLT"],
             "rationale": "Rates generally silent unless funding mechanism is large enough to be fiscal — in which case the event belongs in ``fiscal_issuance``."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "Broad equity rally can mask the beneficiary/loser split and make the event look like risk-on",
             "primary_basket": ["SMH", "ITA"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Compare beneficiary ETFs (SMH, KWEB, ITA) to SPY; dispersion — not index level — is the signal."},
            {"channel": "fx", "reason": "Concurrent Fed hawkishness can drive the dollar up on rates alone, masquerading as a capex-inflow confirm",
             "primary_basket": ["UUP"],
             "false_basket": ["SHY"],
             "distinguishing_signal": "Check 2Y nominal (SHY) — if it rose materially the FX move is a rates story, not an industrial-policy one."},
        ],
        "invalidation": [
            {"signal": "Beneficiary sector ETFs fail to outperform SPY within 5d",
             "channel": "equities", "timing": "1-5d"},
            {"signal": "Implementing agency signals delays / funding claw-backs within 20d",
             "channel": "equities", "timing": "5-20d"},
        ],
        "timing_by_channel": {
            "equities": "1d",
            "credit": "5-20d", "fx": "5-20d", "rates": "5-20d",
        },
    },
    "regulation": {
        # Signature: sharp targeted-name equity move + event-driven vol;
        # broad macro quiet.  Often fully prices within a single session.
        "primary": [
            {"channel": "equities", "expected_direction": "mixed", "timing": "1d",
             "named_assets": ["XLF", "XLK", "XLC"],
             "rationale": "Targeted-company sector basket carries the read (financials XLF for capital-rule / merger blocks; tech XLK or comms XLC for FTC/SEC actions). The named company itself is the cleanest read where the LLM commits a ticker."},
            {"channel": "vol", "expected_direction": "up", "timing": "1d",
             "named_assets": ["VXX", "VIXY"],
             "rationale": "Single-name implied vol jumps; index vol rises only when the action is systemic (financial rule, sector-wide mandate)."},
        ],
        "secondary": [
            {"channel": "credit", "expected_direction": "wider", "timing": "1-5d",
             "named_assets": ["HYG", "LQD"],
             "rationale": "Targeted issuer's CDS / bond spreads widen on cash-flow / litigation risk; peer HY usually unaffected."},
        ],
        "false_positives": [
            {"channel": "equities", "reason": "Broad sector sell-off on unrelated macro can look like a regulatory reaction",
             "primary_basket": ["XLF", "XLK"],
             "false_basket": ["SPY"],
             "distinguishing_signal": "Targeted name should underperform its peer basket by ≥2× on the day — if all peers fall in lockstep, the driver is elsewhere."},
            {"channel": "vol", "reason": "Index vol spike can dominate a single-name vol move in a correlated regime",
             "primary_basket": ["VXX"],
             "false_basket": ["VIXY"],
             "distinguishing_signal": "Look at single-name IV minus index IV — if the spread widens the regulation is doing the work."},
        ],
        "invalidation": [
            {"signal": "Targeted name recovers ≥50 % of its drawdown within 5d (rule watered down / court block / political pushback)",
             "channel": "equities", "timing": "1-5d"},
            {"signal": "No peer dispersion emerges — all peers move in lockstep",
             "channel": "equities", "timing": "1d"},
        ],
        "timing_by_channel": {
            "equities": "1d", "vol": "1d",
            "credit": "1-5d",
        },
    },
    "external_balance": {
        # Signature: EM-specific FX crash + sovereign-credit blowout;
        # the US tape stays quiet unless the affected country is systemic
        # (China funding stress would upgrade to ``bank_stress``).
        "primary": [
            {"channel": "fx", "expected_direction": "up", "timing": "1d",
             "named_assets": ["CEW"],
             "rationale": "Affected-country currency weakens vs USD as capital flees and reserves drain; CEW reads the EM cross. USD index move is usually modest because the driver is idiosyncratic, not broad."},
            {"channel": "credit", "expected_direction": "wider", "timing": "1d",
             "named_assets": ["EMB"],
             "rationale": "Sovereign CDS and EM hard-currency bond spreads blow out; EMB leads the repricing."},
        ],
        "secondary": [
            {"channel": "equities", "expected_direction": "down", "timing": "1-5d",
             "named_assets": ["KWEB", "FXI"],
             "rationale": "EM equity baskets (KWEB / FXI for China cases; EEM / EWZ for broad EM) sell on balance-sheet contagion; DM equities stay relatively unfazed."},
            {"channel": "commodities", "expected_direction": "mixed", "timing": "5-20d",
             "named_assets": ["USO", "CPER"],
             "rationale": "Commodity-exporter stress can lift targeted commodity prices (Russia-ruble-oil-2022 dynamic); importer stress has the opposite sign."},
        ],
        "false_positives": [
            {"channel": "fx", "reason": "Broad USD strength can lift USDXXX crosses across all EMs, masking whether the driver is country-specific or dollar-wide",
             "primary_basket": ["CEW"],
             "false_basket": ["UUP"],
             "distinguishing_signal": "Check USDXXX vs the EM basket — if the affected cross outruns its peers by ≥1σ the stress is idiosyncratic; if it tracks them, the driver is broad USD."},
            {"channel": "credit", "reason": "Global HY widening can drag EM credit with it on risk-off days",
             "primary_basket": ["EMB"],
             "false_basket": ["HYG"],
             "distinguishing_signal": "EMB minus HYG spread differential — widening means EM-specific; flat means broad risk-off."},
        ],
        "invalidation": [
            {"signal": "IMF bailout / central-bank swap line announced within 5d and currency recovers > 50 % of the drawdown",
             "channel": "fx", "timing": "1-5d"},
            {"signal": "Sovereign CDS fully retraces within 20d without policy action",
             "channel": "credit", "timing": "5-20d"},
        ],
        "timing_by_channel": {
            "fx": "1d", "credit": "1d",
            "equities": "1-5d", "commodities": "5-20d",
        },
    },
    "none": {
        "primary":          [],
        "secondary":        [],
        "false_positives":  [],
        "invalidation":     [],
        "timing_by_channel": {},
    },
}


def get_validation_matrix(family: str, subtype: Optional[str] = None) -> dict:
    """Return a deep-copied validation matrix for ``family`` (safe to mutate).

    Unknown families degrade to the ``"none"`` entry so callers don't
    need a membership check; the empty shape lets the UI render without
    branching.

    When ``subtype`` is provided AND it matches an entry in
    ``FAMILY_SUBTYPES[family]``, the subtype's ``primary_overrides``
    tighten the family matrix: rows that share a channel with an
    override get merged (subtype values win on the named_assets /
    expected_direction / timing fields), and net-new override rows
    are appended.  Unknown subtypes are ignored — callers always get
    the family-level matrix back.

    The function signature stays backward-compatible — callers passing
    only ``family`` get the same matrix as before.
    """
    raw = FAMILY_VALIDATION_MATRIX.get(family) or FAMILY_VALIDATION_MATRIX["none"]

    def _row(e: dict) -> dict:
        # Shallow-copy the row, then deep-copy any list-valued fields
        # (named_assets / primary_basket / false_basket) so caller
        # mutations can't leak back into the registry.
        out = dict(e)
        for k in ("named_assets", "primary_basket", "false_basket"):
            v = out.get(k)
            if isinstance(v, list):
                out[k] = list(v)
        return out

    out = {
        "primary":           [_row(e) for e in raw.get("primary") or []],
        "secondary":         [_row(e) for e in raw.get("secondary") or []],
        "false_positives":   [_row(e) for e in raw.get("false_positives") or []],
        "invalidation":      [_row(e) for e in raw.get("invalidation") or []],
        "timing_by_channel": dict(raw.get("timing_by_channel") or {}),
    }

    if subtype:
        sub_meta = FAMILY_SUBTYPES.get(family, {}).get(subtype)
        if sub_meta:
            primary_overrides = sub_meta.get("primary_overrides") or []
            if primary_overrides:
                merged: list[dict] = list(out["primary"])
                for ov in primary_overrides:
                    if not isinstance(ov, dict):
                        continue
                    ov_channel = ov.get("channel")
                    replaced = False
                    for i, row in enumerate(merged):
                        if row.get("channel") == ov_channel:
                            merged_row = {**row, **{
                                k: list(v) if isinstance(v, list) else v
                                for k, v in ov.items()
                            }}
                            merged[i] = merged_row
                            replaced = True
                            break
                    if not replaced:
                        merged.append(_row(ov))
                out["primary"] = merged

            invalidation_extras = sub_meta.get("invalidation_extras") or []
            if invalidation_extras:
                out["invalidation"] = (
                    out["invalidation"] + [_row(e) for e in invalidation_extras]
                )

    return out


# ---------------------------------------------------------------------------
# Mechanism subtypes — specific transmission variants per family
# ---------------------------------------------------------------------------
# Each canonical family carries 0+ subtypes that name a tighter
# transmission shape — same family, more specific channel / asset
# read.  When the analyzer infers a subtype from the mechanism prose
# we use it to TIGHTEN the validation matrix; when no subtype is
# inferred we keep the family-level matrix unchanged so existing
# callers see no behaviour drift.
#
# Subtype keys MUST stay disjoint from family ids (so a downstream
# consumer that mixes the two doesn't accidentally match).  The
# ``keywords`` tuple drives the keyword-based ``infer_mechanism_subtype``
# helper; the ``primary_overrides`` and ``invalidation_extras`` lists
# tighten the validation matrix when the subtype is present.

FAMILY_SUBTYPES: dict[str, dict[str, dict]] = {
    "tariff": {
        "import_tariff_china": {
            "keywords": (
                "china tariff", "chinese imports", "section 301",
                "tariff on china", "duties on chinese",
            ),
            "primary_overrides": [
                {"channel": "equities", "expected_direction": "down",
                 "timing": "1d", "named_assets": ["KWEB", "FXI", "MCHI"],
                 "rationale": "China-exposed equity baskets sell first; KWEB / FXI / MCHI carry the targeted-import wedge."},
                {"channel": "fx", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["CYB"],
                 "rationale": "USD/CNY upside on tariff-driven trade-balance drag."},
            ],
        },
        "agricultural_tariff": {
            "keywords": ("agricultural tariff", "soybean", "grain tariff", "corn tariff"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "mixed",
                 "timing": "1d", "named_assets": ["DBA", "SOYB", "CORN"],
                 "rationale": "Targeted ag complex (DBA / SOYB / CORN) reprices at the tariff wedge."},
            ],
        },
        "metals_tariff": {
            "keywords": ("steel tariff", "aluminum tariff", "metals tariff"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "mixed",
                 "timing": "1d", "named_assets": ["CPER", "JJC", "SLX"],
                 "rationale": "Metals complex (CPER copper, SLX steel) reprices at the tariff wedge."},
            ],
        },
    },
    "sanction": {
        "oil_sanction": {
            "keywords": ("oil sanction", "crude sanction", "petroleum sanction",
                         "russian oil", "iranian oil", "venezuelan oil"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["USO", "BNO"],
                 "rationale": "Targeted-crude supply premium widens; USO / BNO carry the read."},
            ],
        },
        "tech_sanction": {
            "keywords": ("export control", "entity list", "chip sanction",
                         "semiconductor sanction", "tech sanction"),
            "primary_overrides": [
                {"channel": "equities", "expected_direction": "mixed",
                 "timing": "1d", "named_assets": ["SMH", "SOXX", "KWEB"],
                 "rationale": "Semis basket (SMH / SOXX) reprices the export-control wedge; KWEB carries the China leg."},
            ],
        },
        "financial_sanction": {
            "keywords": ("swift", "financial sanction", "asset freeze",
                         "banking sanction", "central bank sanction"),
            "primary_overrides": [
                {"channel": "credit", "expected_direction": "wider",
                 "timing": "1d", "named_assets": ["EMB", "CEMB"],
                 "rationale": "EM sovereign / corporate credit (EMB / CEMB) widens on counterparty repricing."},
            ],
        },
    },
    "supply_shock": {
        "oil_supply_shock": {
            "keywords": ("oil supply", "crude shutdown", "opec cut",
                         "pipeline outage", "refinery outage"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["USO", "XLE"],
                 "rationale": "Direct oil supply squeeze — USO carries the spot leg, XLE the producer windfall."},
            ],
        },
        "gas_supply_shock": {
            "keywords": ("natural gas", "lng cut", "gas pipeline", "gas supply"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["UNG", "BOIL"],
                 "rationale": "Gas-specific squeeze — UNG / BOIL carry the spot leg."},
            ],
        },
        "agri_supply_shock": {
            "keywords": ("crop failure", "drought", "agricultural supply",
                         "wheat supply", "corn supply", "soybean supply"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["DBA", "WEAT", "CORN"],
                 "rationale": "Ag complex spike on yield disruption — DBA broad, WEAT / CORN single-name."},
            ],
        },
        "metals_supply_shock": {
            "keywords": ("mine shutdown", "metals supply", "copper supply",
                         "lithium supply", "nickel supply"),
            "primary_overrides": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["XME", "CPER", "REMX"],
                 "rationale": "Metals supply squeeze — XME producer basket leads, CPER / REMX carry the spot."},
            ],
        },
    },
    "policy_surprise": {
        "hawkish_surprise": {
            "keywords": ("hawkish surprise", "rate hike", "tighter than expected",
                         "raise rates", "rate increase"),
            "primary_overrides": [
                {"channel": "rates", "expected_direction": "up",
                 "timing": "1d", "named_assets": ["TLT", "IEF", "SHY"],
                 "rationale": "Front-end repricing on hawkish surprise — TLT / IEF / SHY carry the curve move."},
            ],
        },
        "dovish_surprise": {
            "keywords": ("dovish surprise", "rate cut", "easing surprise",
                         "lower rates", "rate cut"),
            "primary_overrides": [
                {"channel": "rates", "expected_direction": "down",
                 "timing": "1d", "named_assets": ["TLT", "IEF"],
                 "rationale": "Curve rallies on dovish surprise — TLT / IEF carry the read."},
            ],
        },
    },
    "bank_stress": {
        "regional_bank_stress": {
            "keywords": ("regional bank", "kre stress", "deposit run",
                         "regional banks", "midsize banks"),
            "primary_overrides": [
                {"channel": "equities", "expected_direction": "down",
                 "timing": "1d", "named_assets": ["KRE", "IAT"],
                 "rationale": "Regional banking equities lead — KRE / IAT carry the stress read."},
            ],
        },
        "credit_event": {
            "keywords": ("default", "bankruptcy", "credit event",
                         "missed payment", "creditor"),
            "primary_overrides": [
                {"channel": "credit", "expected_direction": "wider",
                 "timing": "1d", "named_assets": ["HYG", "JNK", "LQD"],
                 "rationale": "HY spreads widen on credit event — HYG / JNK lead, LQD trails."},
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Subtype-channel invariant — asserts every subtype's override channels
# are members of its parent family's channel pack.
# ---------------------------------------------------------------------------
# Why this matters
# ----------------
# Subtype overrides flow into ``proof_set_for_family`` and
# ``falsifier_set_for_family`` via ``get_validation_matrix``.  Downstream
# consumers (``low_information_gate._filter_items_to_subtype``) intersect
# the proof / falsifier items with the union of:
#
#   * the subtype's named channels (drawn from ``primary_overrides``)
#   * the family's secondary cascade pack
#
# If a subtype names a channel that is NOT in ``FAMILY_CHANNEL_PACKS``
# for its family, the filter still runs but the proof and falsifier
# items — which are sourced from the family matrix — land on family
# channels the subtype filter doesn't know about.  Result: the desk
# silently sees an empty proof / falsifier list and reads it as
# "no observable trigger" instead of "subtype was authored against
# the wrong channel".  This validator surfaces the misconfiguration
# loudly at module-load time so the error is impossible to miss.

def validate_subtype_channels() -> None:
    """Assert subtype overrides target channels in their parent family's
    channel pack.  Raises ``ValueError`` listing every offending entry
    when the invariant is broken; returns ``None`` on success.

    Checks both ``primary_overrides`` and ``invalidation_extras`` since
    both feed downstream proof / falsifier generation.  Public so tests
    can call it directly against monkey-patched registries.
    """
    errors: list[str] = []
    for family, subtypes in FAMILY_SUBTYPES.items():
        pack = FAMILY_CHANNEL_PACKS.get(family) or {}
        allowed = set(pack.get("first") or []) | set(pack.get("second") or [])
        if not allowed:
            errors.append(
                f"family '{family}' has subtypes registered but no entry "
                "in FAMILY_CHANNEL_PACKS — cannot validate subtype channels"
            )
            continue
        if not isinstance(subtypes, dict):
            continue
        for subtype, meta in subtypes.items():
            if not isinstance(meta, dict):
                errors.append(
                    f"{family}.{subtype}: subtype meta is not a dict"
                )
                continue
            for kind in ("primary_overrides", "invalidation_extras"):
                rows = meta.get(kind) or []
                if not isinstance(rows, list):
                    errors.append(
                        f"{family}.{subtype}.{kind}: must be a list"
                    )
                    continue
                for idx, row in enumerate(rows):
                    if not isinstance(row, dict):
                        errors.append(
                            f"{family}.{subtype}.{kind}[{idx}]: row is not a dict"
                        )
                        continue
                    ch = row.get("channel")
                    if not isinstance(ch, str) or not ch.strip():
                        errors.append(
                            f"{family}.{subtype}.{kind}[{idx}]: missing channel"
                        )
                        continue
                    if ch not in allowed:
                        errors.append(
                            f"{family}.{subtype}.{kind}[{idx}] channel "
                            f"'{ch}' not in FAMILY_CHANNEL_PACKS['{family}']"
                            f" (allowed: {sorted(allowed)})"
                        )
    if errors:
        raise ValueError(
            "Invalid subtype channel configuration in FAMILY_SUBTYPES — "
            "subtype overrides must target channels in their parent "
            "family's pack:\n  " + "\n  ".join(errors)
        )


# Run the invariant at module load.  Misconfigured subtypes fail
# loudly here rather than silently emptying the proof / falsifier
# pipeline downstream.
validate_subtype_channels()


def infer_mechanism_subtype(
    family: Optional[str],
    mechanism_summary: Optional[str],
    what_changed: Optional[str] = "",
) -> Optional[str]:
    """Return the inferred subtype id for ``family`` based on prose
    keywords, or ``None`` when no subtype matches.

    Inference is intentionally cheap: lowercase the combined
    ``mechanism_summary`` + ``what_changed`` blob and check it against
    each subtype's ``keywords`` tuple in registry order.  First-match
    wins so callers get deterministic output across retries.

    When the family has no subtypes registered (or family is None /
    empty / "none"), returns ``None`` and callers fall back to the
    family-level matrix.
    """
    if not isinstance(family, str) or not family.strip():
        return None
    fam = family.strip().lower()
    if fam == "none":
        return None
    subtypes = FAMILY_SUBTYPES.get(fam)
    if not subtypes:
        return None

    parts: list[str] = []
    for v in (mechanism_summary, what_changed):
        if isinstance(v, str):
            parts.append(v)
    blob = " ".join(parts).lower()
    if not blob.strip():
        return None
    for subtype_id, meta in subtypes.items():
        for kw in meta.get("keywords", ()):
            if kw in blob:
                return subtype_id
    return None


# ---------------------------------------------------------------------------
# Deterministic family-aware minimum_proof_set generator
# ---------------------------------------------------------------------------
# Distils ``FAMILY_VALIDATION_MATRIX[family]`` into a tight 2–4 item
# proof set per canonical family.  Each item carries exactly
# ``{channel, expected_direction, timing, why_it_matters}`` — the LLM
# output sanitizer handles richer shapes, this composer emits the
# deterministic floor every family gets regardless of model output.
#
# Design rules (enforced by ``tests/test_family_proof_set.py``):
#   * Cap at 4 items — more than that is noise, not a minimum.
#   * Dedupe on ``(channel, expected_direction, timing)`` so the set
#     cannot carry the same generic check twice.
#   * Backfill from ``secondary`` when ``primary`` is thin (<2 rows)
#     so every real family emits at least 2 items.
#   * Enforce multi-channel coverage when the family's primary +
#     secondary combined actually span multiple channels — a
#     single-channel proof set hides the cross-asset read a desk
#     expects for families like fiscal_issuance or external_balance.
#   * Return ``[]`` for ``"none"`` or unknown families so consumers
#     can render a null-state without branching.

_MAX_PROOF_ITEMS: int = 4
_MIN_PROOF_ITEMS: int = 2


def _proof_item_from_row(row: dict) -> Optional[dict]:
    """Convert a matrix row into the public proof-item shape.

    Returns ``None`` for malformed rows (missing channel or timing) so
    the caller can skip rather than emit a ``None``-laden item.
    """
    if not isinstance(row, dict):
        return None
    channel = row.get("channel")
    timing = row.get("timing")
    if not isinstance(channel, str) or not isinstance(timing, str):
        return None
    return {
        "channel":            channel,
        "expected_direction": row.get("expected_direction") or "mixed",
        "timing":             timing,
        "why_it_matters":     (row.get("rationale") or "").strip(),
    }


def proof_set_for_family(
    family: str, subtype: Optional[str] = None,
) -> list[dict]:
    """Return the deterministic ``minimum_proof_set`` for ``family``.

    Shape per item: ``{channel, expected_direction, timing, why_it_matters}``.
    Returns an empty list for ``"none"`` or unknown families.

    When ``subtype`` is provided AND it's registered for ``family`` in
    ``FAMILY_SUBTYPES``, the subtype's ``primary_overrides`` tighten
    which rows feed the proof set — same shape, channel-correct
    rationales, named_assets specialized to the subtype.  Default
    ``subtype=None`` preserves the family-level behaviour for callers
    that haven't been threaded through.
    """
    if not isinstance(family, str) or family == "none":
        return []
    # ``get_validation_matrix`` is the single source of truth for
    # family + subtype merging — re-use it instead of reaching into
    # ``FAMILY_VALIDATION_MATRIX`` directly so subtype overrides
    # (named_assets, expected_direction, timing) flow through.
    if subtype:
        matrix = get_validation_matrix(family, subtype=subtype)
    else:
        matrix = FAMILY_VALIDATION_MATRIX.get(family)
    if not matrix:
        return []

    primary = list(matrix.get("primary") or [])
    secondary = list(matrix.get("secondary") or [])

    # Walk primary first, then secondary for backfill, deduping on the
    # composite key so identical checks can't appear twice.
    seen: set[tuple] = set()
    out: list[dict] = []
    for row in primary + secondary:
        item = _proof_item_from_row(row)
        if item is None:
            continue
        key = (item["channel"], item["expected_direction"], item["timing"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= _MAX_PROOF_ITEMS:
            break

    # Multi-channel enforcement — if the combined primary + secondary
    # set spans multiple channels but our deduped output landed on just
    # one, swap in the first off-channel item we haven't emitted.
    # Protects against authoring drift where primary happens to carry
    # multiple same-channel rows.
    all_channels = {
        r.get("channel") for r in (primary + secondary)
        if isinstance(r, dict) and isinstance(r.get("channel"), str)
    }
    out_channels = {i["channel"] for i in out}
    if (
        len(all_channels) >= 2
        and len(out_channels) == 1
        and out
    ):
        current_channel = next(iter(out_channels))
        for row in primary + secondary:
            item = _proof_item_from_row(row)
            if item is None or item["channel"] == current_channel:
                continue
            key = (item["channel"], item["expected_direction"], item["timing"])
            if key in seen:
                continue
            # Append if we still have room; otherwise replace the
            # last same-channel entry so the cap holds.
            if len(out) < _MAX_PROOF_ITEMS:
                seen.add(key)
                out.append(item)
            else:
                out[-1] = item
                seen.add(key)
            break

    # Minimum-items floor — if somehow a family only surfaced 1 item
    # after dedupe (the matrix genuinely has one distinct check), keep
    # it at 1.  We never invent a second check; the floor is advisory
    # for well-formed families and doesn't force filler.
    if len(out) < _MIN_PROOF_ITEMS:
        pass

    return out


# ---------------------------------------------------------------------------
# Deterministic family-aware key_falsifiers generator
# ---------------------------------------------------------------------------
# Mirror of ``proof_set_for_family`` but sourced from the
# ``invalidation`` rows of ``FAMILY_VALIDATION_MATRIX``.  The invariant
# is that proof items come from primary+secondary (what should confirm)
# and falsifier items come from invalidation (what would break) — the
# two lists are structurally disjoint by construction so a falsifier
# cannot copy a proof item verbatim.
#
# Output shape per item: ``{channel, trigger_condition, timing,
# why_it_breaks_thesis}``.  ``why_it_breaks_thesis`` is sourced from
# ``_FAMILY_THESIS_REQUIREMENT`` so every emitted falsifier carries a
# family-level statement of what the thesis actually requires — a
# desk reading "oil rallies broadly" can see why that doesn't break
# a commodity_squeeze thesis (the family's requirement is the
# *affected* commodity leading its complex, not a broad commodity
# rally).

_MAX_FALSIFIER_ITEMS: int = 3

# One sentence per family stating what the thesis requires to transmit.
# Used to populate every falsifier item's ``why_it_breaks_thesis`` so a
# consumer always sees the thesis claim the trigger condition disproves.
# Keep these short (≤160 chars) and concrete — they should read like a
# desk's one-line read, not a textbook definition.
_FAMILY_THESIS_REQUIREMENT: dict[str, str] = {
    "tariff": (
        "the tariff wedge to show up in affected-sector equity dispersion "
        "and in targeted-commodity pricing"
    ),
    "sanction": (
        "a sustained supply premium on the sanctioned commodity and "
        "currency stress on the affected country"
    ),
    "supply_shock": (
        "a physical-supply repricing that holds in the affected commodity "
        "and in downstream-consumer margins"
    ),
    "ceasefire_deescalation": (
        "a risk-premium unwind in vol and in the commodities the conflict "
        "was supporting"
    ),
    "policy_surprise": (
        "a durable rates repricing with matching FX and vol response"
    ),
    "fiscal_issuance": (
        "duration-specific pressure at the long end versus the front — a "
        "steepener on issuance supply"
    ),
    "labor_inflation": (
        "pass-through of wage growth into goods inflation and into rising "
        "breakevens"
    ),
    "bank_stress": (
        "credit spreads to widen and bank-funding proxies to underperform"
    ),
    "commodity_squeeze": (
        "the affected commodity to lead its complex and hold the squeeze "
        "premium"
    ),
    "supply_normalization": (
        "physical volume ramp that drives the scarcity premium out"
    ),
    "industrial_policy": (
        "beneficiary-sector equity dispersion versus the broad index"
    ),
    "regulation": (
        "the targeted name to underperform peers and hold the discount"
    ),
    "external_balance": (
        "sustained EM currency pressure and widening sovereign-credit "
        "spreads"
    ),
}

# Minimum signal length — prevents a generic "watch markets" or "risk
# event" string from surviving into a falsifier item.  Aligned with the
# _clean_key_falsifiers floor in analyze_event.
_MIN_SIGNAL_LEN: int = 20

# Keywords that mark a signal as too generic to be a falsifier.  If the
# ``signal`` text matches one of these the row is rejected — authoring
# mistakes that drift into watch-the-market filler can't smuggle through.
_GENERIC_SIGNAL_TERMS: tuple[str, ...] = (
    "watch markets", "watch the market", "market uncertainty",
    "general risk-off", "broad risk-off",
    "macro headwinds", "ambiguous signal", "unclear signal",
    "mixed signals", "various indicators",
    # Generic-thesis-shift phrases the desk doesn't accept on a
    # critical breakpoint — naming "sentiment shift" or "narrative
    # change" without a price-checkable observation is the bluff.
    "market sentiment changes", "sentiment shifts",
    "narrative changes", "narrative shifts",
    "consensus changes", "consensus shifts",
    "appetite changes", "appetite shifts",
)


def _is_generic_signal(signal: str) -> bool:
    if not isinstance(signal, str) or len(signal.strip()) < _MIN_SIGNAL_LEN:
        return True
    low = signal.lower()
    return any(term in low for term in _GENERIC_SIGNAL_TERMS)


def _why_breaks_thesis_for(family: str) -> str:
    """Family-level one-liner plugged into every falsifier item."""
    req = _FAMILY_THESIS_REQUIREMENT.get(family)
    if not req:
        return ""
    return (
        f"Thesis requires {req}; this observation is direct evidence "
        f"the mechanism is not transmitting."
    )


def _falsifier_item_from_row(row: dict, *, why: str) -> Optional[dict]:
    """Convert an invalidation row into the public falsifier shape.

    Rejects malformed rows (missing channel / timing), generic-signal
    rows, and rows whose ``signal`` is too thin to be a concrete
    thesis-breaking observation.
    """
    if not isinstance(row, dict):
        return None
    channel = row.get("channel")
    timing = row.get("timing")
    signal = row.get("signal")
    if not isinstance(channel, str) or not isinstance(timing, str):
        return None
    if _is_generic_signal(signal):
        return None
    return {
        "channel":              channel,
        "trigger_condition":    signal.strip(),
        "timing":               timing,
        "why_it_breaks_thesis": why,
    }


def falsifier_set_for_family(
    family: str, subtype: Optional[str] = None,
) -> list[dict]:
    """Return the deterministic ``key_falsifiers`` for ``family``.

    Shape per item: ``{channel, trigger_condition, timing,
    why_it_breaks_thesis}``.  Capped at 3 items, deduped on
    ``(channel, trigger_condition)`` so near-identical signals
    collapse.  Returns an empty list for ``"none"`` or unknown
    families so consumers render a null state without branching.

    When ``subtype`` is provided AND it's registered for ``family``,
    the subtype's ``invalidation_extras`` are appended via
    ``get_validation_matrix(family, subtype)``.  Default
    ``subtype=None`` preserves family-level behaviour.
    """
    if not isinstance(family, str) or family == "none":
        return []
    if subtype:
        matrix = get_validation_matrix(family, subtype=subtype)
    else:
        matrix = FAMILY_VALIDATION_MATRIX.get(family)
    if not matrix:
        return []

    why = _why_breaks_thesis_for(family)
    invalidation_rows = list(matrix.get("invalidation") or [])

    seen: set[tuple] = set()
    out: list[dict] = []
    for row in invalidation_rows:
        item = _falsifier_item_from_row(row, why=why)
        if item is None:
            continue
        key = (item["channel"], item["trigger_condition"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= _MAX_FALSIFIER_ITEMS:
            break
    return out


# ---------------------------------------------------------------------------
# Keyword-based fallback classifier
# ---------------------------------------------------------------------------
# Deliberately small, specific term sets.  When an LLM run fails or emits
# "none", this gives the engine a deterministic baseline family rather
# than collapsing to no expectations at all.
#
# Order matters: families listed earlier take precedence when multiple
# term sets hit.  The order is calibrated for real-world ambiguity — e.g.
# a ceasefire announcement should beat a generic "commodity" keyword, a
# bank-stress event should beat a generic "rate" keyword, etc.

_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ceasefire_deescalation", (
        "ceasefire", "cease-fire", "truce", "peace deal", "armistice",
        "de-escalation", "talks resume", "sanctions lifted",
    )),
    ("supply_normalization", (
        "supply restored", "pipeline restart", "export resumed",
        "production resumes", "restart operations", "tariff relief",
        "harvest", "inventory build",
    )),
    ("bank_stress", (
        "bank run", "deposit flight", "bank failure", "counterparty risk",
        "liquidity crunch", "discount window", "bank bailout", "ring-fenced",
        "resolution authority", "bank stress",
    )),
    ("commodity_squeeze", (
        "opec cut", "production cut", "export ban", "supply squeeze",
        "physical shortage", "inventory draw", "refinery outage",
        "lng terminal", "shipping disruption", "strait of hormuz",
    )),
    ("supply_shock", (
        "supply disruption", "supply shock", "outage", "blackout",
        "drought", "freeze", "hurricane", "earthquake", "pandemic",
        "force majeure", "force-majeure",
    )),
    ("sanction", (
        "sanction", "entity list", "export control", "oFAC",
        "secondary sanction", "freeze assets", "embargo",
    )),
    ("tariff", (
        "tariff", "import duty", "countervailing duty", "section 301",
        "section 232", "anti-dumping",
    )),
    ("policy_surprise", (
        "rate hike", "rate cut", "fomc", "ecb hike", "ecb cut",
        "boj", "boe hike", "boe cut", "hawkish surprise",
        "dovish surprise", "jumbo cut", "emergency meeting",
        "rate decision", "press conference",
    )),
    ("fiscal_issuance", (
        "refunding announcement", "quarterly refunding", "debt ceiling",
        "treasury auction", "deficit widens", "issuance surge",
        "gilt issuance", "jgb auction",
    )),
    ("labor_inflation", (
        "wage inflation", "wage growth", "minimum wage",
        "unemployment rate", "payrolls", "jobs report",
        "wage-price spiral", "unit labor cost",
    )),
    # Coverage for the three expansion families added in the industrial/
    # regulation/external-balance pass.  Without these the deterministic
    # fallback collapses to "none" on any event that slipped a clean LLM
    # commitment, even though the event is otherwise recognisable.
    ("industrial_policy", (
        "chips act", "inflation reduction act", "ira ", " ira.",
        "subsidy", "subsidies", "production tax credit",
        "investment tax credit", "tax credit program", "capex incentive",
        "green deal", "industrial strategy", "onshoring", "reshoring",
        "made in america", "made in china",
    )),
    ("regulation", (
        "antitrust", "anti-trust", "anti trust",
        "merger review", "merger block", "consent decree",
        "ftc suit", "ftc investigation", "sec ruling", "sec charges",
        "capital requirement", "basel iii", "basel 3",
        "dodd-frank", "mifid", "gdpr fine",
        "stress test result", "disclosure rule",
    )),
    ("external_balance", (
        "current account", "balance of payments", "bop stress",
        "capital flight", "forex reserves", "fx reserves", "reserves drain",
        "swap line", "sovereign cds", "sovereign spread",
        "imf bailout", "imf rescue", "em funding", "em rescue",
        "hard currency debt",
    )),
)


# ---------------------------------------------------------------------------
# Family aliases — LLM synonym normalisation
# ---------------------------------------------------------------------------
# The LLM sometimes emits a synonym for a canonical family name
# ("antitrust" instead of "regulation", "chips_act" instead of
# "industrial_policy").  Before the hard enum check rejects the string,
# we map recognised aliases onto the canonical id.  Keep the map
# deliberately conservative — an alias that could plausibly belong to
# two families (e.g. "monetary" could be policy_surprise OR fiscal)
# is NOT aliased; it falls through to the keyword fallback instead.

_FAMILY_ALIASES: dict[str, str] = {
    # regulation
    "antitrust":          "regulation",
    "anti_trust":         "regulation",
    "merger_block":       "regulation",
    "regulatory_action":  "regulation",
    "disclosure":         "regulation",
    "capital_rules":      "regulation",
    # industrial policy
    "subsidy":            "industrial_policy",
    "subsidies":          "industrial_policy",
    "ira":                "industrial_policy",
    "chips_act":          "industrial_policy",
    "industrial_strategy": "industrial_policy",
    "green_deal":         "industrial_policy",
    # external balance
    "em_stress":          "external_balance",
    "em_crisis":          "external_balance",
    "em_funding":         "external_balance",
    "bop_crisis":         "external_balance",
    "sovereign_crisis":   "external_balance",
    "balance_of_payments": "external_balance",
    "reserves_drain":     "external_balance",
    # sanctions
    "ofac":               "sanction",
    "entity_list":        "sanction",
    "export_control":     "sanction",
    "secondary_sanction": "sanction",
    # tariff
    "import_duty":        "tariff",
    "trade_war":          "tariff",
    "countervailing_duty": "tariff",
    # monetary / fiscal
    "monetary_policy":    "policy_surprise",
    "rate_surprise":      "policy_surprise",
    "central_bank":       "policy_surprise",
    "debt_issuance":      "fiscal_issuance",
    "treasury_supply":    "fiscal_issuance",
    # supply / commodity
    "oil_shock":          "commodity_squeeze",
    "opec_cut":           "commodity_squeeze",
    "supply_relief":      "supply_normalization",
    "pipeline_restart":   "supply_normalization",
    # bank stress
    "banking_crisis":     "bank_stress",
    "financial_stress":   "bank_stress",
    # labor
    "wage_inflation":     "labor_inflation",
    "wage_spiral":        "labor_inflation",
    # peace
    "peace_deal":         "ceasefire_deescalation",
    "ceasefire":          "ceasefire_deescalation",
}


def normalize_family_alias(raw: Optional[str]) -> Optional[str]:
    """Map an LLM-emitted family alias onto its canonical id.

    Returns the canonical id when ``raw`` matches a known synonym.
    Returns ``None`` when no alias applies — the caller falls back to
    the normal enum check + keyword classifier.
    """
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    return _FAMILY_ALIASES.get(key)


# ---------------------------------------------------------------------------
# Forensic mechanism-structure taxonomy
# ---------------------------------------------------------------------------
# Three small enums that let the LLM output commit to the specific
# market-structure primitive behind an event — a complement to the
# mechanism-family archetype, not a replacement.  The family says
# "sanction"; the bottleneck says "export-control carveout"; the
# transmission type says "regulatory gate"; the channel domain says
# "regulatory".  Together they are what a desk calls a forensic read.

BOTTLENECK_IDS: tuple[str, ...] = (
    "commodity_quality_mismatch",   # e.g. heavy-sour vs light-sweet crude
    "export_control_carveout",      # licence / Entity-List gate
    "refinancing_channel",          # rollover stress, debt maturity wall
    "shipping_chokepoint",          # Strait of Hormuz, Suez, Red Sea
    "input_cost_passthrough",       # raw-input → margin → output price
    "reserve_bop_stress",           # FX reserves, balance-of-payments
    "capacity_bottleneck",          # fab capacity, pipeline throughput
    "substitution_constraint",      # no substitute at scale
    "regulatory_gate",              # tariff, sanction, approval
    "sole_source_physical",         # EUV, rare-earth separation
    "none",
)

BOTTLENECK_LABELS: dict[str, str] = {
    "commodity_quality_mismatch": "Commodity quality mismatch",
    "export_control_carveout":    "Export-control carveout",
    "refinancing_channel":        "Refinancing / funding channel",
    "shipping_chokepoint":        "Shipping chokepoint",
    "input_cost_passthrough":     "Input-cost pass-through",
    "reserve_bop_stress":         "Reserve / balance-of-payments stress",
    "capacity_bottleneck":        "Capacity bottleneck",
    "substitution_constraint":    "Substitution constraint",
    "regulatory_gate":            "Regulatory gate",
    "sole_source_physical":       "Sole-source physical dependency",
    "none":                       "No specific bottleneck identified",
}


TRANSMISSION_TYPE_IDS: tuple[str, ...] = (
    "physical_flow",      # actual cargoes, barrels, shipments
    "pricing_power",      # contract / spread / premium re-rating
    "regulatory_gate",    # licence / tariff / Entity List acts as the valve
    "financing",          # rates, credit, refinancing path
    "balance_sheet",      # reserves, solvency, FX buffers
    "substitution",       # alternative supplier activation
    "passthrough",        # input cost → margin → output price
    "none",
)

TRANSMISSION_TYPE_LABELS: dict[str, str] = {
    "physical_flow":   "Physical flow",
    "pricing_power":   "Pricing power",
    "regulatory_gate": "Regulatory gate",
    "financing":       "Financing / funding",
    "balance_sheet":   "Balance-sheet / reserves",
    "substitution":    "Substitution activation",
    "passthrough":     "Cost pass-through",
    "none":            "Unclassified transmission",
}


CHANNEL_DOMAIN_IDS: tuple[str, ...] = (
    "regulatory",
    "financing",
    "supply_chain",
    "demand",
    "macro_rates",
    "currency",
    "labor",
    "infrastructure",
    "none",
)

CHANNEL_DOMAIN_LABELS: dict[str, str] = {
    "regulatory":     "Regulatory",
    "financing":      "Financing",
    "supply_chain":   "Supply chain",
    "demand":         "Demand",
    "macro_rates":    "Macro rates",
    "currency":       "Currency",
    "labor":          "Labor",
    "infrastructure": "Infrastructure",
    "none":           "Unclassified channel",
}


def is_valid_bottleneck(value: Optional[str]) -> bool:
    return isinstance(value, str) and value in BOTTLENECK_IDS


def is_valid_transmission_type(value: Optional[str]) -> bool:
    return isinstance(value, str) and value in TRANSMISSION_TYPE_IDS


def is_valid_channel_domain(value: Optional[str]) -> bool:
    return isinstance(value, str) and value in CHANNEL_DOMAIN_IDS


def classify_family(
    headline: Optional[str] = "",
    mechanism_text: Optional[str] = "",
) -> str:
    """Return the best keyword-derived family id, or ``"none"`` on no hit.

    Deliberately simple: concatenates headline + mechanism text, lowercases
    once, and scans in priority order.  First family whose term set hits
    wins.  This is the fallback — callers preferring a strict
    "LLM committed or nothing" contract should check for an LLM-provided
    value first.
    """
    text = f"{headline or ''} {mechanism_text or ''}".lower()
    if not text.strip():
        return "none"
    for fam, terms in _FAMILY_KEYWORDS:
        for term in terms:
            if term in text:
                return fam
    return "none"

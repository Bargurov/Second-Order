"""
scenario_packs.py

Deterministic playbooks for recurring macro / geopolitical shock types.

Why this module
---------------
Every OPEC cut, tariff round, or ceasefire headline kicks off roughly
the same desk note: what moves first, what rotates, what would fade the
thesis, which sectors take the hit.  Rebuilding that playbook from
scratch every event makes the analysis uneven and prone to omission.

A *scenario pack* is a pre-baked view over a mechanism_family that adds
the institutional muscle-memory pieces missing from the family
taxonomy:

  * a human-readable scenario label (``oil_spike``, ``tariff_cycle``)
  * a typical ``repricing_pattern`` — ordered phases with horizon tokens
  * typical ``sector_consequences`` — winners / losers by SECTOR name
    (not tickers; tickers drift, sectors don't)
  * scenario-specific ``scenario_falsifiers`` that layer on top of the
    family's invalidation list

Primary / secondary channel expectations live on the linked
mechanism_family and are joined in on read — this registry deliberately
does NOT duplicate channel lists.  ``scenario.family`` is the single
source of truth for channel direction.

Contracts
---------
  * ``SCENARIO_PACKS[sid]["family"]`` MUST be in
    ``mechanism_family.FAMILY_IDS`` (tested).
  * Every phase in ``repricing_pattern`` carries a ``horizon`` from
    ``mechanism_family.TIMING_VOCABULARY`` (tested).
  * ``sector_consequences`` entries are ``{"sector": str, "rationale": str}``
    — no tickers (tested).

Pure data + composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Optional

from mechanism_family import (
    FAMILY_IDS,
    FAMILY_LABELS,
    FAMILY_VALIDATION_MATRIX,
    TIMING_VOCABULARY,
    get_validation_matrix,
)


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------
# Keep this set tight — a scenario pack is earning its place only if the
# archetype actually recurs.  Add new packs sparingly; duplicates within
# a family are a smell.

SCENARIO_IDS: tuple[str, ...] = (
    "oil_spike",
    "tariff_cycle",
    "funding_squeeze",
    "ceasefire_deescalation",
    "sanction_export_control",
)

SCENARIO_LABELS: dict[str, str] = {
    "oil_spike":                "Oil spike",
    "tariff_cycle":             "Tariff cycle",
    "funding_squeeze":          "Funding squeeze",
    "ceasefire_deescalation":   "Ceasefire / de-escalation",
    "sanction_export_control":  "Sanction / export-control shock",
}


# The core registry.  Each pack references the mechanism family that
# carries its channel / validation matrix.  Channel expectations are
# NOT duplicated here — consumers call ``compute_scenario_playbook``
# to join the scenario-level data with the family-level matrix.

SCENARIO_PACKS: dict[str, dict[str, Any]] = {
    "oil_spike": {
        "family": "commodity_squeeze",
        "summary": (
            "Physical-tight commodity move in crude — OPEC action, refinery "
            "outage, geopolitical chokepoint.  Price leads volume data by 5-20d."
        ),
        "repricing_pattern": [
            {"phase": "immediate", "horizon": "1d",
             "description": "Crude +3-7% intraday; energy equities (XLE, OIH) lead; "
                            "breakevens lift; USD strengthens vs commodity importers (JPY, EUR)."},
            {"phase": "follow_through", "horizon": "1-5d",
             "description": "Refining-margin crack spreads widen; transport / airline equities sell; "
                            "consumer-discretionary ETF (XLY) underperforms SPY by 1-2pp."},
            {"phase": "macro_pass_through", "horizon": "5-20d",
             "description": "Headline CPI expectations revise higher; central-bank commentary "
                            "turns cautious on cuts; real yields re-price as breakevens lead."},
        ],
        "sector_consequences": {
            "beneficiaries": [
                {"sector": "energy",
                 "rationale": "Upstream producers have direct EPS leverage to crude price."},
                {"sector": "materials",
                 "rationale": "Integrated commodity producers share the macro tailwind."},
                {"sector": "defense",
                 "rationale": "Higher geopolitical-risk premium often attached to oil spikes."},
            ],
            "losers": [
                {"sector": "airlines",
                 "rationale": "Jet fuel ~20-30% of operating cost; margin compression immediate."},
                {"sector": "consumer_discretionary",
                 "rationale": "Gasoline price hits disposable income; discretionary demand slows."},
                {"sector": "transports",
                 "rationale": "Diesel / bunker fuel passes through with a lag; freight rates rise."},
                {"sector": "rate_sensitive_equities",
                 "rationale": "Higher breakevens + policy caution compresses long-duration multiples."},
            ],
        },
        "scenario_falsifiers": [
            {"signal": "SPR / coordinated producer announcement reverses supply fear",
             "channel": "commodities", "timing": "1-5d"},
            {"signal": "Airline equities rally alongside crude — mechanism didn't bind",
             "channel": "equities",    "timing": "1-5d"},
        ],
    },
    "tariff_cycle": {
        "family": "tariff",
        "summary": (
            "Announced tariff / carve-out / retaliation round affecting a named "
            "sector or country.  Equity dispersion is the cleanest read; FX matters "
            "more for the targeted country than broad USD."
        ),
        "repricing_pattern": [
            {"phase": "immediate", "horizon": "1d",
             "description": "Exposed-sector ETFs sell off (KWEB, FXI, EWH for China tariffs); "
                            "domestic-protected sectors rally; USD firms vs targeted FX."},
            {"phase": "retaliation_or_carveout", "horizon": "1-5d",
             "description": "Counter-tariff or carve-out headlines drive sector re-rating; "
                            "affected commodities reprice to the new tariff wedge."},
            {"phase": "earnings_pass_through", "horizon": "5-20d",
             "description": "Margin-sensitive importers flag exposure in guidance; "
                            "breakevens drift higher on input-cost pass-through; HY credit widens."},
        ],
        "sector_consequences": {
            "beneficiaries": [
                {"sector": "domestic_producers",
                 "rationale": "Tariff protection lifts domestic-supplier pricing power."},
                {"sector": "defense",
                 "rationale": "Escalatory trade posture often pairs with defense spending."},
            ],
            "losers": [
                {"sector": "technology",
                 "rationale": "Semis / hardware supply chains cross the tariff border most often."},
                {"sector": "consumer_discretionary",
                 "rationale": "Import-heavy retailers and apparel take the margin hit."},
                {"sector": "industrials",
                 "rationale": "Capital-goods exporters face reciprocal tariffs."},
                {"sector": "autos",
                 "rationale": "Multi-country supply chains concentrate tariff exposure."},
            ],
        },
        "scenario_falsifiers": [
            {"signal": "Exposed-sector ETFs (KWEB / FXI) recover within 1d on carve-out rumours",
             "channel": "equities",    "timing": "1d"},
            {"signal": "Targeted FX (CNY / KRW) strengthens within 1-5d — tariff risk priced out",
             "channel": "fx",          "timing": "1-5d"},
        ],
    },
    "funding_squeeze": {
        "family": "bank_stress",
        "summary": (
            "Counterparty / liquidity stress — regional bank failure, repo spike, "
            "dollar-funding scramble.  Credit widens first, dollar bid follows, "
            "regional banks underperform systemically."
        ),
        "repricing_pattern": [
            {"phase": "immediate", "horizon": "1d",
             "description": "HY credit spreads +30-80bp; KRE / KBE -5-10%; VIX +3-6 points; "
                            "dollar strengthens; Treasuries catch a safe-haven bid."},
            {"phase": "contagion", "horizon": "1-5d",
             "description": "Peer regional banks reprice downward; money-market fund flows visible; "
                            "EM-credit spreads widen; emerging-market currencies sell vs USD."},
            {"phase": "policy_response", "horizon": "5-20d",
             "description": "Discount-window borrowing data; BTFP-style facility headlines; "
                            "rate-cut expectations reprice lower; banking-sector guidance cuts."},
        ],
        "sector_consequences": {
            "beneficiaries": [
                {"sector": "treasuries",
                 "rationale": "Safe-haven bid bids duration; long-end rallies as cuts reprice."},
                {"sector": "gold",
                 "rationale": "Real-rate fall + USD debasement fear lifts gold."},
                {"sector": "systemically_important_financials",
                 "rationale": "Flight-to-quality within financials — JPM / BAC relative outperform."},
            ],
            "losers": [
                {"sector": "regional_banks",
                 "rationale": "Deposit-flight risk; balance-sheet exposure to stressed names."},
                {"sector": "commercial_real_estate",
                 "rationale": "Regional-bank exposure + refinancing cost concentrates stress."},
                {"sector": "high_yield_credit",
                 "rationale": "Funding-cost spike + recession repricing both hit HY."},
                {"sector": "small_cap_equities",
                 "rationale": "Russell 2000 is bank-heavy and funding-sensitive."},
            ],
        },
        "scenario_falsifiers": [
            {"signal": "KRE recovers to pre-event level within 5d",
             "channel": "equities",    "timing": "1-5d"},
            {"signal": "HY credit spreads tighten within 5d despite headline",
             "channel": "credit",      "timing": "1-5d"},
        ],
    },
    "ceasefire_deescalation": {
        "family": "ceasefire_deescalation",
        "summary": (
            "Risk-premium unwind — geopolitical de-escalation, ceasefire, "
            "sanctions relief.  Vol and oil premium collapse first; defense / "
            "shipping sell; cyclicals and risk-on assets rally."
        ),
        "repricing_pattern": [
            {"phase": "immediate", "horizon": "1d",
             "description": "VIX -3-6 points; oil -3-8%; defense ETFs (ITA, XAR) -3-6%; "
                            "shipping (BDRY, FRO) -5-10%; EM currencies firm vs USD."},
            {"phase": "rotation", "horizon": "1-5d",
             "description": "Cyclical sectors (XLI, XLY, XME) outperform defensives; "
                            "HY credit tightens; consumer-facing equities firm."},
            {"phase": "structural_unwind", "horizon": "5-20d",
             "description": "Defense-spending guidance moderates; energy capex plans re-rated; "
                            "breakeven inflation softens on commodity de-risking."},
        ],
        "sector_consequences": {
            "beneficiaries": [
                {"sector": "cyclicals",
                 "rationale": "Risk-on rotation lifts industrials, materials, discretionary."},
                {"sector": "airlines",
                 "rationale": "Jet fuel compression + travel-demand lift compound."},
                {"sector": "consumer_discretionary",
                 "rationale": "Gasoline relief + confidence re-rating."},
                {"sector": "emerging_markets",
                 "rationale": "EM FX + EM credit both firm on risk-on."},
            ],
            "losers": [
                {"sector": "defense",
                 "rationale": "Order-book re-rating down; geopolitical-spending premium fades."},
                {"sector": "shipping",
                 "rationale": "Chokepoint-risk premium on freight rates unwinds."},
                {"sector": "energy",
                 "rationale": "Scarcity premium fades; crude-leveraged producers sell."},
                {"sector": "gold",
                 "rationale": "Safe-haven bid fades as risk-on takes hold."},
            ],
        },
        "scenario_falsifiers": [
            {"signal": "Oil reverses higher within 1d on follow-up headline",
             "channel": "commodities", "timing": "1d"},
            {"signal": "Defense ETFs (ITA, XAR) rally instead of selling",
             "channel": "equities",    "timing": "1d"},
        ],
    },
    "sanction_export_control": {
        "family": "sanction",
        "summary": (
            "Restriction on a named entity / technology / commodity — Entity List, "
            "OFAC designation, export-control package.  Targeted commodity + equity "
            "premium widens; alternative suppliers rally; exposed revenue lines sell."
        ),
        "repricing_pattern": [
            {"phase": "immediate", "horizon": "1d",
             "description": "Targeted commodity / equity repricing (oil / heavy crude / semis); "
                            "alternative-supplier equities rally; affected FX weakens; "
                            "sanctioned-sector credit widens."},
            {"phase": "sell_side_revisions", "horizon": "1-5d",
             "description": "Estimate cuts on exposed-revenue names; sector-rotation visible "
                            "in ETF flows; affected-commodity curve shifts."},
            {"phase": "structural_rewire", "horizon": "5-20d",
             "description": "Guidance calls flag exposed-line revenue headwinds; "
                            "supply-chain re-wire announcements; indigenous-substitute capex headlines."},
        ],
        "sector_consequences": {
            "beneficiaries": [
                {"sector": "alternative_suppliers",
                 "rationale": "Non-sanctioned producers gain market share at the restricted margin."},
                {"sector": "defense",
                 "rationale": "Export controls often pair with strategic-industry support."},
                {"sector": "domestic_champions",
                 "rationale": "On-shoring / re-shoring narrative lifts protected sectors."},
            ],
            "losers": [
                {"sector": "technology",
                 "rationale": "Semis / EDA / advanced-equipment revenue most commonly targeted."},
                {"sector": "emerging_markets",
                 "rationale": "Sanctioned-country and adjacent EM risk-premium repricing."},
                {"sector": "sanctioned_sector_equities",
                 "rationale": "Direct revenue / access hit — the named chokepoint."},
            ],
        },
        "scenario_falsifiers": [
            {"signal": "Carve-out or licence rumours reverse the affected-sector sell-off within 1d",
             "channel": "equities",    "timing": "1d"},
            {"signal": "Alternative-supplier equities fail to rally within 5d — scarcity premium absent",
             "channel": "equities",    "timing": "1-5d"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_valid_scenario(value: Optional[str]) -> bool:
    return isinstance(value, str) and value in SCENARIO_IDS


def get_scenario_pack(scenario_id: str) -> Optional[dict[str, Any]]:
    """Return a deep-copied scenario pack, or None if unknown."""
    raw = SCENARIO_PACKS.get(scenario_id)
    if raw is None:
        return None
    # Deep-enough copy: every collection rebuilt so callers can mutate
    # freely without polluting the registry.
    return {
        "family":  raw["family"],
        "summary": raw["summary"],
        "repricing_pattern": [dict(p) for p in raw.get("repricing_pattern") or []],
        "sector_consequences": {
            "beneficiaries": [dict(s) for s in (raw.get("sector_consequences") or {}).get("beneficiaries") or []],
            "losers":        [dict(s) for s in (raw.get("sector_consequences") or {}).get("losers") or []],
        },
        "scenario_falsifiers": [dict(f) for f in raw.get("scenario_falsifiers") or []],
    }


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def _falsifier_key(entry: dict) -> tuple:
    """Stable identity for a falsifier row — used to dedupe scenario
    additions against the family's invalidation list."""
    return (
        (entry.get("signal") or "").strip().lower(),
        (entry.get("channel") or "").strip().lower(),
    )


def compute_scenario_playbook(scenario_id: str) -> dict[str, Any]:
    """Return the joined scenario + family view as the scenario playbook.

    Shape::

      {
        "available":         bool,
        "scenario":          str,              # scenario_id
        "scenario_label":    str,
        "family":            str,              # mechanism_family id
        "family_label":      str,
        "summary":            str,
        "repricing_pattern":  [{phase, horizon, description}, ...],
        "sector_consequences": {"beneficiaries": [...], "losers": [...]},
        "primary_channels":   [...]   # from FAMILY_VALIDATION_MATRIX
        "secondary_channels": [...]   # from FAMILY_VALIDATION_MATRIX
        "false_positives":    [...]   # from FAMILY_VALIDATION_MATRIX
        "invalidators":       [...]   # scenario + family union with provenance
        "timing_by_channel":  {...}   # from FAMILY_VALIDATION_MATRIX
      }

    The ``invalidators`` list carries every family-level invalidation
    entry plus every scenario-level falsifier the scenario added.
    Duplicate signals (same signal + channel) are de-duplicated; each
    entry carries a ``source`` of ``"family"`` or ``"scenario"`` so the
    UI / telemetry can branch on provenance.

    Unknown scenarios return ``{"available": False, ...}`` with empty
    lists — callers don't need a membership check.
    """
    pack = get_scenario_pack(scenario_id)
    if pack is None:
        return {
            "available":           False,
            "scenario":            scenario_id or "",
            "scenario_label":      "",
            "family":              "none",
            "family_label":        FAMILY_LABELS.get("none", ""),
            "summary":              "",
            "repricing_pattern":    [],
            "sector_consequences": {"beneficiaries": [], "losers": []},
            "primary_channels":     [],
            "secondary_channels":   [],
            "false_positives":      [],
            "invalidators":         [],
            "timing_by_channel":    {},
        }

    family = pack["family"]
    matrix = get_validation_matrix(family)

    # Join invalidators: family first, scenario falsifiers deduped and
    # tagged with provenance.  Dedup key = (signal, channel) lowercased.
    invalidators: list[dict] = []
    seen: set[tuple] = set()

    for entry in matrix.get("invalidation") or []:
        key = _falsifier_key(entry)
        if key in seen:
            continue
        seen.add(key)
        row = dict(entry)
        row["source"] = "family"
        invalidators.append(row)

    for entry in pack.get("scenario_falsifiers") or []:
        key = _falsifier_key(entry)
        if key in seen:
            continue
        seen.add(key)
        row = dict(entry)
        row["source"] = "scenario"
        invalidators.append(row)

    return {
        "available":           True,
        "scenario":            scenario_id,
        "scenario_label":      SCENARIO_LABELS.get(scenario_id, scenario_id),
        "family":              family,
        "family_label":        FAMILY_LABELS.get(family, family),
        "summary":              pack["summary"],
        "repricing_pattern":    list(pack.get("repricing_pattern") or []),
        "sector_consequences":  pack.get("sector_consequences") or {
            "beneficiaries": [], "losers": [],
        },
        "primary_channels":     list(matrix.get("primary") or []),
        "secondary_channels":   list(matrix.get("secondary") or []),
        "false_positives":      list(matrix.get("false_positives") or []),
        "invalidators":         invalidators,
        "timing_by_channel":    dict(matrix.get("timing_by_channel") or {}),
    }

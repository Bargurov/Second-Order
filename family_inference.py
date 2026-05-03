"""Deterministic ``mechanism_family`` fallback using stored evidence only.

Two use sites share this helper:

* Analysis normalization — called at the tail of ``_normalize_schema``
  in ``analyze_event`` to reduce false ``"none"`` commits at save time.
* Event read — applied in response-path code (``/events/{id}`` detail,
  ``/events`` list decoration, ``/portfolio``) so legacy rows stored
  with ``mechanism_family="none"`` can surface a better family without
  mutating the database.

The helper **only reads stored fields** on the event — no network,
no DB, no LLM call — and returns one of the canonical family ids from
``mechanism_family.FAMILY_IDS``.  ``"none"`` stays only when the
evidence is genuinely weak or conflicting.

Inference tiers, in priority order:

1. Already committed family (non-``"none"``) → pass through unchanged.
2. ``mechanism_family.classify_family`` over ``headline`` +
   ``mechanism_summary`` + ``transmission_chain`` + ``what_changed``
   + proof/falsifier observation text.  First keyword hit wins.
3. ``hidden_mechanism.bottleneck_type`` → family map (e.g.
   ``reserve_bop_stress`` → ``external_balance``).
4. ``hidden_mechanism.channel_domain`` + ``transmission_type`` pair.
5. Asset-bucket dominance: ≥2 distinct tickers from the relevant
   family-marker sets in ``primary_assets`` / ``beneficiary_tickers``
   / ``loser_tickers`` / ``assets_to_watch``.

When two tiers disagree, the first hit wins — this is a conservative
fallback, not a scorer.  Ties / low-signal input → ``"none"``.

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from mechanism_family import (
    FAMILY_IDS,
    _FAMILY_KEYWORDS,
    classify_family,
    normalize_family_alias,
)


_FAMILY_ENUM: frozenset[str] = frozenset(FAMILY_IDS)


# ``hidden_mechanism.bottleneck_type`` → family.  Kept conservative:
# only bottleneck types with a single dominant family sit here.
_BOTTLENECK_TO_FAMILY: dict[str, str] = {
    "reserve_bop_stress":      "external_balance",
    "refinancing_channel":     "bank_stress",
    "shipping_chokepoint":     "commodity_squeeze",
    "sole_source_physical":    "supply_shock",
    "export_control_carveout": "sanction",
    "input_cost_passthrough":  "labor_inflation",
    "capacity_bottleneck":     "supply_shock",
}


# Asset-bucket dominance markers — ≥2 hits in the event's asset lists
# tilts the family when textual classifiers turn up empty.
_EM_STRESS_MARKERS: frozenset[str] = frozenset({
    "EMB", "EEM", "EWZ", "EWY", "EEMA", "EMLC", "CEMB",
})
_BANK_STRESS_MARKERS: frozenset[str] = frozenset({
    "KRE", "KBE", "XLF", "HYG", "JNK",
})
_SEMI_SUBSIDY_MARKERS: frozenset[str] = frozenset({
    "SMH", "SOXX", "TSM", "INTC", "ITA", "XAR", "ICLN", "KWEB",
})
_COMMODITY_MARKERS: frozenset[str] = frozenset({
    "USO", "XLE", "BNO", "GLD", "SLV", "CL", "BZ", "GC", "HG", "UNG",
})


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _event_text_parts(event: dict) -> list[str]:
    """Collect every string field the inference reads for keyword match."""
    out: list[str] = []
    for key in ("headline", "mechanism_summary", "what_changed"):
        v = event.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v)
    # competing_thesis carries the analyst's own thesis framing in
    # primary_thesis / alternative_thesis / discriminator — load-bearing
    # vocabulary the keyword classifier shouldn't miss when the
    # headline is generic.
    ct = event.get("competing_thesis")
    if isinstance(ct, dict):
        for k in ("primary_thesis", "alternative_thesis"):
            v = ct.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v)
        disc = ct.get("discriminator")
        if isinstance(disc, dict):
            for k in ("observation", "primary_outcome", "alternative_outcome"):
                v = disc.get(k)
                if isinstance(v, str) and v.strip():
                    out.append(v)
    # transmission_chain can be list[str] or list[dict(hop, channel, actor)]
    chain = event.get("transmission_chain")
    if isinstance(chain, list):
        for step in chain:
            if isinstance(step, str) and step.strip():
                out.append(step)
            elif isinstance(step, dict):
                hop = step.get("hop")
                if isinstance(hop, str) and hop.strip():
                    out.append(hop)
    # transmission_path (structured hops) — same shape
    path = event.get("transmission_path")
    if isinstance(path, list):
        for step in path:
            if isinstance(step, dict):
                hop = step.get("hop")
                if isinstance(hop, str) and hop.strip():
                    out.append(hop)
    # Proof + falsifier observations carry the analyst's own framing
    # of what would confirm or kill the thesis — rich vocabulary for
    # the keyword classifier.
    for key in ("minimum_proof_set", "key_falsifiers",
                "critical_breakpoints"):
        items = event.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for obs_key in ("observation", "signal", "trigger_condition"):
                        obs = item.get(obs_key)
                        if isinstance(obs, str) and obs.strip():
                            out.append(obs)
    return out


def _collect_tickers(event: dict, *, keys: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for key in keys:
        bucket = event.get(key)
        if not isinstance(bucket, list):
            continue
        for entry in bucket:
            if isinstance(entry, str) and entry.strip():
                out.add(entry.strip().upper())
            elif isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("ticker")
                if isinstance(sym, str) and sym.strip():
                    out.add(sym.strip().upper())
    return out


# ---------------------------------------------------------------------------
# Tier functions — each returns a family id or None.
# ---------------------------------------------------------------------------

def _tier_keyword(event: dict) -> Optional[str]:
    """Text-based classifier over every stored text surface.

    Two passes:

    1. **Hit-count scorer (most-specific wins).**  Counts every keyword
       hit per family across the joined text.  When ≥1 family hits the
       text, picks the family with the highest hit count.  Ties break
       against ``_FAMILY_KEYWORDS`` priority order — the order is
       calibrated so that, e.g., a ceasefire announcement that also
       mentions sanctions resolves to ``ceasefire_deescalation``, not
       ``sanction``.  This addresses the failure mode where a single
       generic keyword (``"tariff"`` mentioned in passing) would steal
       the family from a clearly-different mechanism.

    2. **classify_family fallback.**  When no keyword hits, defer to
       the priority-ordered first-match classifier.  Keeps existing
       behaviour intact for thin events.
    """
    parts = _event_text_parts(event)
    if not parts:
        return None
    joined_lower = " ".join(parts).lower()

    best_family: Optional[str] = None
    best_count: int = 0
    for fam, terms in _FAMILY_KEYWORDS:
        hits = sum(1 for term in terms if term in joined_lower)
        if hits > best_count:
            best_count = hits
            best_family = fam
        # Strict ``>`` keeps the existing priority order as the
        # tiebreaker — earlier families in _FAMILY_KEYWORDS win on
        # equal hit counts.

    if best_family and best_family in _FAMILY_ENUM and best_family != "none":
        return best_family

    headline = event.get("headline") if isinstance(
        event.get("headline"), str,
    ) else ""
    fam = classify_family(headline, " ".join(parts))
    if fam and fam != "none" and fam in _FAMILY_ENUM:
        return fam
    return None


def _tier_bottleneck(event: dict) -> Optional[str]:
    hm = event.get("hidden_mechanism")
    if not isinstance(hm, dict):
        return None
    bt = hm.get("bottleneck_type")
    if not isinstance(bt, str):
        return None
    fam = _BOTTLENECK_TO_FAMILY.get(bt.strip().lower())
    if fam and fam in _FAMILY_ENUM:
        return fam
    return None


def _tier_channel_pair(event: dict) -> Optional[str]:
    hm = event.get("hidden_mechanism")
    if not isinstance(hm, dict):
        return None
    cd = hm.get("channel_domain")
    tt = hm.get("transmission_type")
    cd_s = cd.strip().lower() if isinstance(cd, str) else ""
    tt_s = tt.strip().lower() if isinstance(tt, str) else ""
    if cd_s == "currency" and tt_s == "balance_sheet":
        return "external_balance"
    if cd_s == "financing" and tt_s == "financing":
        return "bank_stress"
    if cd_s == "labor":
        return "labor_inflation"
    if cd_s == "macro_rates" and tt_s == "financing":
        return "policy_surprise"
    if cd_s == "supply_chain" and tt_s == "physical_flow":
        return "supply_shock"
    if cd_s == "regulatory":
        return "regulation"
    return None


def _tier_asset_dominance(event: dict) -> Optional[str]:
    # Pull from every stored asset bucket; tickers the analyst listed
    # as beneficiaries / losers / primary / assets_to_watch are all
    # evidence for what the mechanism is about.
    symbols = _collect_tickers(event, keys=(
        "primary_assets", "beneficiary_tickers", "loser_tickers",
        "assets_to_watch", "secondary_assets", "hedge_or_signal_assets",
    ))
    if not symbols:
        return None
    if len(symbols & _EM_STRESS_MARKERS) >= 2:
        return "external_balance"
    if len(symbols & _BANK_STRESS_MARKERS) >= 2:
        return "bank_stress"
    if len(symbols & _SEMI_SUBSIDY_MARKERS) >= 2:
        return "industrial_policy"
    if len(symbols & _COMMODITY_MARKERS) >= 2:
        return "commodity_squeeze"
    return None


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def resolve_effective_family(event: Any) -> str:
    """Return the best mechanism family for ``event`` without writing
    anything back.

    Respects a pre-existing non-``"none"`` value on
    ``event["mechanism_family"]`` — the analyst's / LLM's committed
    family always wins over this deterministic fallback.  When the
    stored family is ``"none"`` (missing, empty, or the literal
    sentinel), runs each tier in order and returns the first canonical
    family id it produces.  Falls back to ``"none"`` when every tier
    turns up empty.
    """
    if not isinstance(event, dict):
        return "none"

    raw = event.get("mechanism_family")
    if isinstance(raw, str) and raw.strip() and raw.strip().lower() != "none":
        # Use the same alias normaliser the analysis path uses so
        # slight casing / punctuation differences match a canonical
        # family before we give up and run the fallback.
        aliased = normalize_family_alias(raw)
        resolved = aliased or raw.strip().lower()
        if resolved in _FAMILY_ENUM and resolved != "none":
            return resolved

    for tier in (
        _tier_keyword,
        _tier_bottleneck,
        _tier_channel_pair,
        _tier_asset_dominance,
    ):
        try:
            fam = tier(event)
        except Exception:
            fam = None
        if fam and fam in _FAMILY_ENUM and fam != "none":
            return fam

    return "none"


def with_effective_family(event: dict) -> dict:
    """Return a shallow copy of ``event`` with ``mechanism_family``
    upgraded via ``resolve_effective_family``.  Safe for response-path
    use: does not mutate the input, does not write back to the DB.
    Returns ``event`` unchanged if it's not a dict.
    """
    if not isinstance(event, dict):
        return event
    fam = resolve_effective_family(event)
    if event.get("mechanism_family") == fam:
        return event
    out = dict(event)
    out["mechanism_family"] = fam
    return out

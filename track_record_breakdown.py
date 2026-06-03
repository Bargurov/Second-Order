"""
track_record_breakdown.py

Mechanism-family + regime-aware track-record analytics.

The existing ``db.compute_track_record`` rolls up a single flat summary over
every saved event.  This module takes the same event rows and slices the
outcome counts three ways:

  * by mechanism family (tariff / supply_shock / policy_surprise / …)
  * by regime — a 2-axis key ``(inflation, policy_stance)`` pulled from
    the persisted ``regime_snapshot``
  * by compound regime label — ``regime_snapshot.compound.label`` (e.g.
    ``reflation``, ``stagflation_pulse``)

Each group carries counts, hit rate, coverage, and mean realised returns so
a later portfolio or research surface can read a compact machine-readable
shape without rescanning the event table.

Design
------
Pure composer.  Takes already-loaded event rows — no DB access — so it's
trivially testable and reusable by any caller that already has the rows in
hand (notably the ``/stats/track-record/breakdown`` endpoint added in
``api.py``).  Output shape is stable even when every group is empty.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import db


# ---------------------------------------------------------------------------
# Mechanism-family display labels
# ---------------------------------------------------------------------------
# Match the frontend _FAMILY_LABEL table in analysis-view.tsx so the archive
# UI and breakdown endpoint surface identical names.

_FAMILY_LABELS: dict[str, str] = {
    "tariff":                 "Tariff",
    "sanction":               "Sanction",
    "supply_shock":           "Supply shock",
    "ceasefire_deescalation": "Ceasefire / de-escalation",
    "policy_surprise":        "Policy surprise",
    "fiscal_issuance":        "Fiscal / issuance",
    "labor_inflation":        "Labor / inflation print",
    "bank_stress":            "Bank / funding stress",
    "commodity_squeeze":      "Commodity squeeze",
    "supply_normalization":   "Supply normalization",
    "none":                   "No family matched",
    "unclassified":           "Unclassified",
}


# Compound-regime labels (mirrors the rulebook in regime_compound.py;
# unknown labels pass through verbatim via title-casing).
_COMPOUND_LABELS: dict[str, str] = {
    "reflation":          "Reflation",
    "stagflation_pulse":  "Stagflation pulse",
    "disinflation":       "Disinflation",
    "goldilocks":         "Goldilocks",
    "risk_off":           "Risk off",
    "financial_stress":   "Financial stress",
    "qt_grind":           "QT grind",
    "none":               "No compound pattern",
}


# Policy-timing status labels — mirrors policy_timing.TIMING_STATUSES.
# Used as the bucket key for the per-event ``policy_timing_context.status``
# breakdown.  Listed in this fixed order so the export renders the lifecycle
# left-to-right (announced → effective → under_review → expired).
POLICY_STATUS_BUCKETS: tuple[str, ...] = (
    "announced", "effective", "under_review", "expired",
)

_POLICY_STATUS_LABELS: dict[str, str] = {
    "announced":    "Announced",
    "effective":    "Effective",
    "under_review": "Under review",
    "expired":      "Expired",
}


# Country-vulnerability tier labels — mirrors country_backdrop.VULNERABILITY_TIERS.
# Used as the bucket key for the per-event
# ``country_vulnerability_context.overall_vulnerability`` breakdown.
VULNERABILITY_BUCKETS: tuple[str, ...] = (
    "resilient", "moderate", "vulnerable", "fragile",
)

_VULNERABILITY_LABELS: dict[str, str] = {
    "resilient":  "Resilient",
    "moderate":   "Moderate",
    "vulnerable": "Vulnerable",
    "fragile":    "Fragile",
}


# Proof-quality buckets — stable enum consumed by the frontend + export
# serializers.  See ``_proof_quality_key`` for the classification rules.
PROOF_QUALITY_BUCKETS: tuple[str, ...] = (
    "proof_backed",
    "partial_proof",
    "no_proof",
    "falsified",
    "low_information",
)

_PROOF_QUALITY_LABELS: dict[str, str] = {
    "proof_backed":    "Proof-backed",
    "partial_proof":   "Partial proof",
    "no_proof":        "No proof structure",
    "falsified":       "Falsifier triggered",
    "low_information": "Low information",
}


# Engine-phase quality-tier buckets — mirrors the closed enum surfaced
# by ``engine_phase_surface.decorate_full``.  Used by the key extractor
# below to validate the tier value; the breakdown emits only buckets
# that have at least one event (no pre-seeded empties), so this tuple
# defines the *valid* set, not the rendered set.
QUALITY_TIER_BUCKETS: tuple[str, ...] = (
    "actionable",
    "watch_only",
    "low_information",
)


# Tradable buckets derived from ``actionability_check.tradable``.
# Events whose actionability_check is missing or carries a non-boolean
# tradable field are skipped from this dimension entirely (still
# counted in the totals) — no synthetic ``unknown`` bucket.  The
# breakdown emits only buckets that have at least one event.
TRADABLE_BUCKETS: tuple[str, ...] = (
    "tradable",
    "not_tradable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loads(raw: Any, default: Any) -> Any:
    """JSON-decode ``raw`` (string) or pass through a decoded value."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def _score_event(market_tickers: list[dict],
                 revisit_snapshots: list[dict]) -> dict:
    """Classify a single event's outcome using the same source-preference
    rules as ``db.compute_track_record`` + pull best realised returns.

    Returns::

        {
          "outcome":      "validated" | "contradicted" | "unresolved",
          "has_direction": bool,
          "support_ratio": float,    # supporting / with_direction, 0.0 when none
          "best_return_5d":  Optional[float],
          "best_return_20d": Optional[float],
          "revisit_scored":  bool,
        }
    """
    # Lazy import to keep this module import-free at module load.
    from db import _best_revisit_snapshot, _score_directions

    best_revisit = _best_revisit_snapshot(revisit_snapshots or [])
    used_revisit = False
    has_sup = has_con = False
    sup_cnt = dir_cnt = 0
    if best_revisit:
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(best_revisit)
        if dir_cnt > 0:
            used_revisit = True
    if not used_revisit:
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(
            market_tickers or [],
        )

    if has_sup:
        outcome = "validated"
    elif has_con:
        outcome = "contradicted"
    else:
        outcome = "unresolved"

    # Realised-return extraction — prefer revisit snapshot tickers (same
    # source as the direction call above) then fall back to market_tickers.
    best_5d: Optional[float] = None
    best_20d: Optional[float] = None
    source_tickers = best_revisit if used_revisit else (market_tickers or [])
    for t in source_tickers:
        if not isinstance(t, dict):
            continue
        r5 = t.get("return_5d")
        r20 = t.get("return_20d")
        if isinstance(r5, (int, float)) and (best_5d is None or abs(r5) > abs(best_5d)):
            best_5d = float(r5)
        if isinstance(r20, (int, float)) and (best_20d is None or abs(r20) > abs(best_20d)):
            best_20d = float(r20)

    return {
        "outcome":         outcome,
        "has_direction":   dir_cnt > 0,
        "support_ratio":   (sup_cnt / dir_cnt) if dir_cnt > 0 else 0.0,
        "best_return_5d":  best_5d,
        "best_return_20d": best_20d,
        "revisit_scored":  used_revisit,
    }


def _empty_group(**keys: Any) -> dict:
    """Seed dict for a freshly-created group; extra keys are carried through."""
    return {
        **keys,
        "total":           0,
        "validated":       0,
        "contradicted":    0,
        "unresolved":      0,
        "revisit_scored":  0,
        "_sum_return_5d":  0.0,
        "_cnt_return_5d":  0,
        "_sum_return_20d": 0.0,
        "_cnt_return_20d": 0,
        "_sum_support":    0.0,
        "_cnt_support":    0,
    }


def _accumulate(group: dict, scored: dict) -> None:
    """Fold one scored event into a group dict (mutates in place)."""
    group["total"] += 1
    outcome = scored["outcome"]
    group[outcome] += 1
    if scored["revisit_scored"]:
        group["revisit_scored"] += 1
    r5 = scored.get("best_return_5d")
    r20 = scored.get("best_return_20d")
    if isinstance(r5, (int, float)):
        group["_sum_return_5d"] += r5
        group["_cnt_return_5d"] += 1
    if isinstance(r20, (int, float)):
        group["_sum_return_20d"] += r20
        group["_cnt_return_20d"] += 1
    if scored["has_direction"]:
        group["_sum_support"] += scored["support_ratio"]
        group["_cnt_support"] += 1


def _finalize(group: dict) -> dict:
    """Convert a raw accumulator dict into the public summary shape."""
    total = group["total"]
    validated = group["validated"]
    contradicted = group["contradicted"]
    directional = validated + contradicted

    hit_rate = (validated / directional) if directional > 0 else None
    coverage = (directional / total) if total > 0 else None

    def _mean(sum_key: str, cnt_key: str) -> Optional[float]:
        cnt = group[cnt_key]
        if cnt <= 0:
            return None
        return round(group[sum_key] / cnt, 3)

    # Keep only the public fields — drop the _-prefixed accumulators.
    public = {k: v for k, v in group.items() if not k.startswith("_")}
    public["hit_rate"] = round(hit_rate, 3) if hit_rate is not None else None
    public["coverage"] = round(coverage, 3) if coverage is not None else None
    public["avg_return_5d"]  = _mean("_sum_return_5d",  "_cnt_return_5d")
    public["avg_return_20d"] = _mean("_sum_return_20d", "_cnt_return_20d")
    public["avg_support_ratio"] = _mean("_sum_support", "_cnt_support")
    return public


# ---------------------------------------------------------------------------
# Key extraction — decides how each event is bucketed
# ---------------------------------------------------------------------------


def _family_key(ev: dict) -> str:
    """Bucket key for the mechanism-family breakdown."""
    fam = (ev.get("mechanism_family") or "").strip()
    return fam if fam else "unclassified"


def _regime_key(regime: Optional[dict]) -> Optional[tuple[str, str]]:
    """Return (inflation, policy_stance) when both are usable, else None.

    A regime snapshot with ``available=False`` or either axis neutral /
    missing is treated as "not bucketable" — the event is counted in the
    totals but skipped in the regime breakdown.
    """
    if not isinstance(regime, dict) or not regime.get("available"):
        return None
    inflation = (regime.get("inflation") or "").strip().lower()
    policy = (regime.get("policy_stance") or "").strip().lower()
    if not inflation or not policy:
        return None
    if inflation == "neutral" or policy == "neutral":
        return None
    return (inflation, policy)


def _compound_key(regime: Optional[dict]) -> Optional[str]:
    """Return the compound-regime label, or None when unavailable / 'none'."""
    if not isinstance(regime, dict):
        return None
    compound = regime.get("compound")
    if not isinstance(compound, dict):
        return None
    label = (compound.get("label") or "").strip().lower()
    if not label or label == "none":
        return None
    return label


def _policy_status_key(policy_ctx: Optional[dict]) -> Optional[str]:
    """Return the policy_timing_context.status, or None when missing.

    A ``{}`` block (no tracked policy matched the cluster) and any value
    outside the canonical ``TIMING_STATUSES`` enum are treated as "not
    bucketable" — the event still counts in the totals but is skipped
    in the policy_status breakdown so unknown / placeholder strings
    don't pollute the dimension.
    """
    if not isinstance(policy_ctx, dict):
        return None
    status = (policy_ctx.get("status") or "").strip().lower()
    if not status:
        return None
    if status not in POLICY_STATUS_BUCKETS:
        return None
    return status


def _quality_tier_key(ev: dict) -> Optional[str]:
    """Return the engine-phase quality_tier bucket, or None when the
    field can't be derived from stored data.

    Reads ``ev["quality_tier"]`` first (set by
    ``engine_phase_surface.decorate_full`` when the row was loaded
    through the per-event API path) and falls back to the same
    composer used at decorate time so the bulk-export path bucket the
    same way as the live route.  Anything outside the canonical
    ``QUALITY_TIER_BUCKETS`` enum returns None so unknown / placeholder
    strings don't pollute the dimension.
    """
    raw = ev.get("quality_tier")
    if not isinstance(raw, str) or not raw:
        try:
            from low_information_gate import evidence_quality_tier
            raw = evidence_quality_tier(ev)
        except Exception:
            return None
    tier = (raw or "").strip().lower()
    if tier not in QUALITY_TIER_BUCKETS:
        return None
    return tier


def _mechanism_subtype_key(ev: dict) -> Optional[str]:
    """Return the keyword-inferred ``mechanism_subtype``, or None when
    the family is ``"none"`` / no subtype keyword matched.

    Reads ``ev["mechanism_subtype"]`` first (already surfaced on rows
    that passed through ``engine_phase_surface``); otherwise infers
    from family + summary + what_changed using the same
    ``mechanism_family.infer_mechanism_subtype`` helper the per-event
    decorator uses.  Empty / null-like results are skipped — events
    without a usable subtype still count toward the totals but are
    excluded from this dimension's groups, mirroring the
    regime / compound / policy_status pattern.
    """
    raw = ev.get("mechanism_subtype")
    if not isinstance(raw, str) or not raw.strip():
        try:
            from mechanism_family import infer_mechanism_subtype
            raw = infer_mechanism_subtype(
                ev.get("mechanism_family"),
                ev.get("mechanism_summary"),
                ev.get("what_changed", "") or "",
            )
        except Exception:
            return None
    if not isinstance(raw, str):
        return None
    sub = raw.strip().lower()
    if not sub or sub == "none":
        return None
    return sub


def _tradable_key(ev: dict) -> Optional[str]:
    """Return the tradable bucket for ``ev`` or None when the event
    carries no usable actionability read.

    Reads ``ev["actionability_check"].tradable`` first; if no
    ``actionability_check`` is attached (raw row from the bulk export
    path), composes the block via ``compose_actionability_check`` so
    bucketing matches the live route.  Events whose composed block is
    empty or whose ``tradable`` field is non-boolean are skipped from
    this dimension entirely — the event still counts in the totals
    but is not bucketed (no synthetic "unknown" group).

    Lenient on source: composer output is treated as canonical because
    it's the same composer ``engine_phase_surface.decorate_full`` uses
    on the live route.  Strict on shape: only literal True / False
    values bucket; ``None`` / strings / missing keys all skip cleanly.
    """
    ac = ev.get("actionability_check")
    if not isinstance(ac, dict) or "tradable" not in ac:
        try:
            from low_information_gate import compose_actionability_check
            ac = compose_actionability_check(ev)
        except Exception:
            ac = {}
    if not isinstance(ac, dict):
        return None
    v = ac.get("tradable")
    if v is True:
        return "tradable"
    if v is False:
        return "not_tradable"
    return None


def _vulnerability_key(country_ctx: Optional[dict]) -> Optional[str]:
    """Return the country_vulnerability_context.overall_vulnerability, or
    None when missing.

    A ``{}`` block (no profiled country matched the headline) and any
    value outside the canonical ``VULNERABILITY_TIERS`` enum are
    skipped — same contract as ``_policy_status_key``.
    """
    if not isinstance(country_ctx, dict):
        return None
    tier = (country_ctx.get("overall_vulnerability") or "").strip().lower()
    if not tier:
        return None
    if tier not in VULNERABILITY_BUCKETS:
        return None
    return tier


# ---------------------------------------------------------------------------
# Proof-quality bucketing — reads persisted event fields only
# ---------------------------------------------------------------------------


def _proof_quality_key(ev: dict, scored: dict) -> tuple[str, dict[str, bool]]:
    """Classify an event into a proof-quality bucket using stored fields.

    No market validation recomputation — this function reads
    ``minimum_proof_set`` / ``key_falsifiers`` + low-information flags
    via the same ``portfolio_flags`` helper the ranking layer uses.
    The ``scored["outcome"]`` comes from upstream event scoring (based
    on persisted direction_tags + revisit snapshots) and flips
    ``proof_backed`` to ``falsified`` when the named falsifiers line
    up with a contradicted outcome.

    Returns ``(bucket, flags)`` where ``flags`` carries the raw
    booleans the summary counts need (``has_proof_set`` /
    ``has_falsifiers`` / ``low_information`` / ``falsifier_triggered``).
    """
    try:
        from portfolio_flags import portfolio_flags
        pf = portfolio_flags(ev)
    except Exception:
        pf = {
            "has_proof_set":   False,
            "has_falsifiers":  False,
            "low_information": False,
        }

    has_proof   = bool(pf.get("has_proof_set"))
    has_fals    = bool(pf.get("has_falsifiers"))
    low_info    = bool(pf.get("low_information"))
    triggered   = has_fals and scored.get("outcome") == "contradicted"

    if low_info:
        bucket = "low_information"
    elif triggered:
        bucket = "falsified"
    elif has_proof and has_fals:
        bucket = "proof_backed"
    elif has_proof or has_fals:
        bucket = "partial_proof"
    else:
        bucket = "no_proof"

    return bucket, {
        "has_proof_set":       has_proof,
        "has_falsifiers":      has_fals,
        "low_information":     low_info,
        "falsifier_triggered": triggered,
    }


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def compute_track_record_breakdown(events: Iterable[dict]) -> dict:
    """Build mechanism-family + regime + compound-regime performance summaries.

    ``events`` is an iterable of event dicts with at least these keys:
      * ``mechanism_family``     — string or missing
      * ``regime_snapshot``      — dict or JSON-string or None
      * ``market_tickers``       — list-of-dicts or JSON-string or None
      * ``revisit_snapshots``    — list-of-dicts or JSON-string or None

    Rows decoded through ``_decode_event_row`` already have the list /
    dict fields in their native Python form; raw ``sqlite3.Row`` tuples
    are supported too via ``_loads``.
    """
    family_groups: dict[str, dict] = {}
    regime_groups: dict[tuple[str, str], dict] = {}
    compound_groups: dict[str, dict] = {}
    proof_groups: dict[str, dict] = {
        key: _empty_group(
            bucket=key,
            label=_PROOF_QUALITY_LABELS[key],
        )
        for key in PROOF_QUALITY_BUCKETS
    }
    # Deterministic-context dimensions — the policy-timing + country-vuln
    # buckets are pre-seeded so the export shape is stable even when no
    # event in the input set carries the matching context block.
    policy_status_groups: dict[str, dict] = {
        key: _empty_group(
            status=key,
            label=_POLICY_STATUS_LABELS[key],
        )
        for key in POLICY_STATUS_BUCKETS
    }
    vulnerability_groups: dict[str, dict] = {
        key: _empty_group(
            tier=key,
            label=_VULNERABILITY_LABELS[key],
        )
        for key in VULNERABILITY_BUCKETS
    }
    # Engine-phase dimensions — populated lazily.  Buckets render only
    # when at least one event lands in them (no pre-seeded empties),
    # and identity values are the verbatim stored tokens (no humanised
    # label keys).
    quality_tier_groups: dict[str, dict] = {}
    tradable_groups: dict[str, dict] = {}
    subtype_groups: dict[str, dict] = {}

    total_events = 0
    validated_total = 0
    contradicted_total = 0
    revisit_total = 0
    proof_backed_count = 0
    falsifier_triggered_count = 0
    low_information_count = 0

    # Curated rows (intake stubs + promoted observations) carry no thesis
    # outcome.  Exclude every non-thesis stage so the breakdown slices the
    # SAME outcome set as db.compute_track_record rather than counting an
    # outcome-less row in a mechanism-family group.
    _non_thesis = getattr(db, "NON_THESIS_STAGES", frozenset())
    for ev in events or []:
        if isinstance(ev, dict):
            _stage = ev.get("stage") or ""
            if isinstance(_stage, str) and _stage in _non_thesis:
                continue
        total_events += 1
        tickers     = _loads(ev.get("market_tickers"), [])
        revisit     = _loads(ev.get("revisit_snapshots"), [])
        regime      = _loads(ev.get("regime_snapshot"), {}) or {}
        policy_ctx  = _loads(ev.get("policy_timing_context"), {}) or {}
        country_ctx = _loads(ev.get("country_vulnerability_context"), {}) or {}

        scored = _score_event(
            tickers if isinstance(tickers, list) else [],
            revisit if isinstance(revisit, list) else [],
        )
        if scored["outcome"] == "validated":
            validated_total += 1
        elif scored["outcome"] == "contradicted":
            contradicted_total += 1
        if scored["revisit_scored"]:
            revisit_total += 1

        # ---- Family breakdown ------------------------------------------
        fkey = _family_key(ev)
        group = family_groups.setdefault(fkey, _empty_group(
            family=fkey,
            family_label=_FAMILY_LABELS.get(fkey, fkey.replace("_", " ").title()),
        ))
        _accumulate(group, scored)

        # ---- Regime breakdown ------------------------------------------
        rkey = _regime_key(regime)
        if rkey is not None:
            group = regime_groups.setdefault(rkey, _empty_group(
                regime_key=f"{rkey[0]}/{rkey[1]}",
                inflation=rkey[0],
                policy_stance=rkey[1],
            ))
            _accumulate(group, scored)

        # ---- Compound-regime breakdown --------------------------------
        ckey = _compound_key(regime)
        if ckey is not None:
            group = compound_groups.setdefault(ckey, _empty_group(
                state=ckey,
                label=_COMPOUND_LABELS.get(ckey, ckey.replace("_", " ").title()),
            ))
            _accumulate(group, scored)

        # ---- Policy-timing-status breakdown ---------------------------
        # Reads the persisted ``policy_timing_context.status`` only — no
        # date arithmetic here.  Events whose cluster never matched a
        # tracked policy carry an empty block and are skipped.
        pskey = _policy_status_key(policy_ctx)
        if pskey is not None:
            _accumulate(policy_status_groups[pskey], scored)

        # ---- Country-vulnerability breakdown --------------------------
        # Reads the persisted ``country_vulnerability_context.overall_vulnerability``
        # tier only — events whose headline never resolved to a profiled
        # country carry an empty block and are skipped.
        vkey = _vulnerability_key(country_ctx)
        if vkey is not None:
            _accumulate(vulnerability_groups[vkey], scored)

        # ---- Proof-quality breakdown ----------------------------------
        pkey, pflags = _proof_quality_key(ev, scored)
        _accumulate(proof_groups[pkey], scored)
        if pflags["has_proof_set"] and pflags["has_falsifiers"]:
            proof_backed_count += 1
        if pflags["falsifier_triggered"]:
            falsifier_triggered_count += 1
        if pflags["low_information"]:
            low_information_count += 1

        # ---- Engine-phase quality_tier breakdown ----------------------
        # Buckets are populated lazily and identity values are stored
        # verbatim — no label key, no humanisation.  Off-enum values
        # skip the dimension; the event still counts in the totals.
        qkey = _quality_tier_key(ev)
        if qkey is not None:
            group = quality_tier_groups.setdefault(qkey, _empty_group(tier=qkey))
            _accumulate(group, scored)

        # ---- Mechanism-subtype breakdown ------------------------------
        # ``infer_mechanism_subtype`` returns None for the ``"none"``
        # family or when no subtype keyword matches — those events are
        # skipped here so a thin row never invents an empty subtype
        # group.  The stored ``mechanism_family`` token rides along on
        # the group as additional identity context (raw, not relabeled).
        skey = _mechanism_subtype_key(ev)
        if skey is not None:
            family_raw = (ev.get("mechanism_family") or "").strip().lower() or None
            group = subtype_groups.setdefault(skey, _empty_group(
                subtype=skey,
                family=family_raw,
            ))
            _accumulate(group, scored)

        # ---- Tradable breakdown --------------------------------------
        # Events without a usable actionability read are skipped — no
        # synthetic "unknown" bucket pollutes the dimension.
        tkey = _tradable_key(ev)
        if tkey is not None:
            group = tradable_groups.setdefault(tkey, _empty_group(bucket=tkey))
            _accumulate(group, scored)

    # Finalize + sort.  Largest-sample groups lead each list so the
    # frontend can take(N) and still show the highest-signal buckets.
    def _finalize_and_sort(groups: dict) -> list[dict]:
        out = [_finalize(g) for g in groups.values()]
        out.sort(key=lambda g: (-g["total"], g.get("family", g.get("regime_key", g.get("state", "")))))
        return out

    # Proof-quality dimension uses a fixed enum order (not sample-size
    # sort) so the memo / CSV always lists buckets in the same place.
    proof_quality_list = [
        _finalize(proof_groups[key]) for key in PROOF_QUALITY_BUCKETS
    ]
    # Same fixed-enum-order treatment for the deterministic-context
    # dimensions: lifecycle and vulnerability tiers read better in
    # canonical order than re-sorted by sample size.
    policy_status_list = [
        _finalize(policy_status_groups[key]) for key in POLICY_STATUS_BUCKETS
    ]
    vulnerability_list = [
        _finalize(vulnerability_groups[key]) for key in VULNERABILITY_BUCKETS
    ]
    # Engine-phase dimensions — dynamic, sample-size descending with a
    # deterministic key tiebreaker.  Empty buckets are never emitted:
    # ``setdefault`` only creates a group when at least one event lands
    # in it, so the export never carries placeholder rows.
    quality_tier_list = sorted(
        (_finalize(g) for g in quality_tier_groups.values()),
        key=lambda g: (-g["total"], g.get("tier", "")),
    )
    tradable_list = sorted(
        (_finalize(g) for g in tradable_groups.values()),
        key=lambda g: (-g["total"], g.get("bucket", "")),
    )
    subtype_list = sorted(
        (_finalize(g) for g in subtype_groups.values()),
        key=lambda g: (-g["total"], g.get("subtype", "")),
    )

    overall_directional = validated_total + contradicted_total
    overall_hit_rate = (
        round(validated_total / overall_directional, 3)
        if overall_directional > 0 else None
    )

    return {
        "total_events":       total_events,
        "validated_total":    validated_total,
        "contradicted_total": contradicted_total,
        "revisit_scored":     revisit_total,
        "hit_rate":           overall_hit_rate,
        # Additive summary counts — existing keys above are untouched.
        "proof_backed":        proof_backed_count,
        "falsifier_triggered": falsifier_triggered_count,
        "low_information":     low_information_count,
        "by_mechanism_family":     _finalize_and_sort(family_groups),
        "by_regime":               _finalize_and_sort(regime_groups),
        "by_compound_regime":      _finalize_and_sort(compound_groups),
        "by_proof_quality":        proof_quality_list,
        "by_policy_status":        policy_status_list,
        "by_overall_vulnerability": vulnerability_list,
        # Engine-phase dimensions — additive; existing keys above are
        # untouched so older consumers keep parsing the same shape.
        "by_quality_tier":         quality_tier_list,
        "by_mechanism_subtype":    subtype_list,
        "by_tradable":             tradable_list,
        "generated_at":            datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

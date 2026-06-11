#!/usr/bin/env python3
"""Read-only diagnostics for the J1 overlay's two weak buckets.

J1 (``scripts/accepted_family_overlay_report.py``) classified the accepted
thesis corpus with deterministic whole-token rules and deliberately left two
honest buckets: multi-match rows (ambiguity surfaced, never forced) and
unclassified / review-needed rows. This review CONSUMES that report's output
- it does not re-select the corpus - and explains, row by row, WHY each row
landed in a weak bucket, then proposes (never applies) bounded rule
refinements.

Discipline (non-negotiable):

  * **Consumes J1, does not reselect.** Bucket membership comes from
    ``build_overlay``; the accepted-record loader is reused only to attach
    headlines. No independent target selection, no second denominator.
  * **Overlay, not DB labels.** Nothing is written to events.db. Diagnoses
    are curation notes about the *rules*, never family labels on rows.
  * **Ambiguity is explained, never forced.** Multi-match rows keep every
    matched family. Unclassified rows keep an honest reason category; a
    curated diagnosis is applied only when the row's headline still matches
    the frozen J1 snapshot, otherwise it downgrades to ``review_needed``.
  * **No fake precision.** No family-level inference, no significance, no
    performance ranking, no recommendation - just a taxonomy diagnostic.

Usage::

    python scripts/accepted_family_overlay_review.py --db-path events.db --json
    python scripts/accepted_family_overlay_review.py --db-path events.db
    python scripts/accepted_family_overlay_review.py --db-path events.db \
        --include-examples 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accepted_family_overlay_report import build_overlay  # noqa: E402
from scripts.track_record_sensitivity_report import (  # noqa: E402
    _load_accepted_records,
)

DEFAULT_EXAMPLES = 3
# Large enough that the overlay's capped representative lists return every
# weak-bucket row, never a silent subset (guarded explicitly below).
_OVERLAY_LIST_CAP = 100000

ALLOWED_CATEGORIES: set[str] = {
    "legitimate_overlap",
    "taxonomy_gap",
    "terse_or_missing_context",
    "off_topic_or_noise",
    "rule_miss_candidate",
    "overfit_risk",
    "review_needed",
}


# ---------------------------------------------------------------------------
# Multi-match diagnosis: by matched FAMILY SET (a robust pattern, not per id)
# ---------------------------------------------------------------------------

MULTI_PATTERNS: dict[frozenset, dict[str, str]] = {
    frozenset({"supply_shock", "geopolitical_conflict_context"}): {
        "category": "legitimate_overlap",
        "why": (
            "Conflict-driven supply disruption: an oil / commodity supply "
            "token co-occurs with a conflict token (war, drone, missile, "
            "refinery strike). Both channels are genuinely present in one "
            "headline; the canonical taxonomy has no single family for a "
            "conflict that is itself the supply shock."
        ),
        "recommendation": (
            "Keep as multi-match. Do not pick a winner and do not collapse "
            "the pair into one family - the co-occurrence is the structural "
            "fact, not an error to resolve."
        ),
    },
    frozenset({"supply_shock", "ceasefire_deescalation"}): {
        "category": "legitimate_overlap",
        "why": (
            "Supply repricing co-present with a de-escalation path: an oil / "
            "tanker token sits beside a ceasefire / peace / diplomacy token. "
            "Two opposite-direction mechanisms occupy one headline - the "
            "de-escalation reprices the very supply risk named alongside it."
        ),
        "recommendation": (
            "Keep as multi-match. The pairing is the observation; forcing a "
            "single family would hide that the supply move and the "
            "de-escalation are the same story."
        ),
    },
    frozenset({"sanction", "supply_shock"}): {
        "category": "legitimate_overlap",
        "why": (
            "Sanction-triggered supply threat: a sanction / export-control "
            "token names the trigger and a Strait-of-Hormuz / oil token "
            "names the transmission channel. Both are correctly present - "
            "the sanction is the cause and the supply route is the effect."
        ),
        "recommendation": (
            "Keep as multi-match. Recording cause and channel together is "
            "honest; collapsing to one family loses half the mechanism."
        ),
    },
    frozenset({"tariff", "geopolitical_conflict_context"}): {
        "category": "overfit_risk",
        "why": (
            "False overlap from a token collision: the conflict bucket's "
            "bare 'war' token fires on the metaphor 'trade war' in what is "
            "otherwise a pure tariff / trade-policy headline. The conflict "
            "tag is a rule artifact, not a second mechanism."
        ),
        "recommendation": (
            "The clean fix is a bounded negative phrase ('trade war') on the "
            "conflict 'war' token so the row resolves to single-match tariff "
            "- but generalizing war-metaphor exclusions invites whack-a-mole, "
            "so defer the rule edit to a reviewed K2 rather than applying it "
            "here."
        ),
    },
}


def diagnose_multi(matched_families: Sequence[str]) -> dict[str, str]:
    """Diagnose a multi-match row from its set of matched families."""
    key = frozenset(matched_families)
    hit = MULTI_PATTERNS.get(key)
    if hit is not None:
        return dict(hit)
    return {
        "category": "review_needed",
        "why": (
            "Multi-match family set "
            f"{sorted(key)} is not covered by a reviewed overlap pattern; "
            "it needs curated human review before any interpretation."
        ),
        "recommendation": (
            "Surface for human review. Do not auto-resolve and do not assume "
            "the overlap is legitimate or spurious without reading the "
            "headline."
        ),
    }


# ---------------------------------------------------------------------------
# Unclassified diagnosis: a curated snapshot keyed to the frozen J1 buckets.
# Each entry carries an ``expects`` substring; the curated label is applied
# only if the row's current headline still contains it, otherwise the row
# downgrades to ``review_needed`` (so the review self-invalidates on drift).
# ---------------------------------------------------------------------------

_REC_OFF_TOPIC = (
    "Leave unclassified - no mechanism family should absorb a non-market "
    "row. Capturing it would require noise vocabulary that pulls genuine "
    "off-topic headlines into the taxonomy."
)
_REC_GAP = (
    "Leave unclassified - the event is real but the canonical taxonomy has "
    "no family for this mechanism. Inventing a catch-all bucket would "
    "manufacture coverage without meaning."
)
_REC_RULE_MISS = (
    "Candidate for a bounded, context-gated phrase in a reviewed K2 - not a "
    "rule edit here. The benefit is one row; the risk is generic tokens "
    "over-firing (see proposed_rule_refinements)."
)

CURATED_UNCLASSIFIED: dict[int, dict[str, str]] = {
    # --- archive noise: no market mechanism -------------------------------
    2: {"expects": "artemis", "category": "off_topic_or_noise",
        "why": "Space human-interest (Artemis II crew imagery). No "
               "geopolitical, macro, or policy transmission channel.",
        "recommendation": _REC_OFF_TOPIC},
    49: {"expects": "artemis", "category": "off_topic_or_noise",
         "why": "Space human-interest (Artemis II crew imagery), an "
                "exact-headline duplicate of the other Artemis row.",
         "recommendation": _REC_OFF_TOPIC},
    4: {"expects": "rescue team in iran", "category": "off_topic_or_noise",
        "why": "Human-interest rescue framing of a conflict-adjacent event; "
               "the headline carries no supply or conflict token, and the "
               "market-relevant sibling classifies on its own headline.",
        "recommendation": _REC_OFF_TOPIC},
    8: {"expects": "stage queens", "category": "off_topic_or_noise",
        "why": "Human-interest profile (stage performer). Not a market "
               "event.",
        "recommendation": _REC_OFF_TOPIC},
    9: {"expects": "barnsley", "category": "off_topic_or_noise",
        "why": "Local crime / road-collision report. Not a market event.",
        "recommendation": _REC_OFF_TOPIC},
    51: {"expects": "barnsley", "category": "off_topic_or_noise",
         "why": "Local crime / road-collision report, an exact-headline "
                "duplicate of the other Barnsley row.",
         "recommendation": _REC_OFF_TOPIC},
    206: {"expects": "auto show", "category": "off_topic_or_noise",
          "why": "Auto-show photo essay; industry colour with no event "
                 "mechanism.",
          "recommendation": _REC_OFF_TOPIC},
    207: {"expects": "graduate students", "category": "off_topic_or_noise",
          "why": "Crime report (homicide case). Not a market event.",
          "recommendation": _REC_OFF_TOPIC},
    216: {"expects": "off-camera", "category": "off_topic_or_noise",
          "why": "Diplomatic-protocol / ceremonial item (off-camera "
                 "meeting, 'clash fears'); political theatre, not a market "
                 "transmission mechanism.",
          "recommendation": _REC_OFF_TOPIC},
    236: {"expects": "ai spending", "category": "off_topic_or_noise",
          "why": "Big-tech results / AI capex round-up; corporate-earnings "
                 "colour with no geopolitical or policy mechanism.",
          "recommendation": _REC_OFF_TOPIC},
    # --- real macro/policy events the taxonomy cannot name ----------------
    25: {"expects": "foxconn", "category": "taxonomy_gap",
         "why": "Corporate-earnings row citing generic 'geopolitics' with no "
                "specific named instrument (no tariff, sanction, supply, or "
                "conflict token). Generic geopolitical-risk language has no "
                "mechanism family.",
         "recommendation": _REC_GAP},
    50: {"expects": "foxconn", "category": "taxonomy_gap",
         "why": "Corporate-earnings row citing generic 'geopolitics', an "
                "exact-headline duplicate of the other Foxconn row.",
         "recommendation": _REC_GAP},
    101: {"expects": "international standards", "category": "taxonomy_gap",
          "why": "Development-economics / global-standards report; a "
                 "macro-structural item the canonical mechanism taxonomy "
                 "does not cover.",
          "recommendation": _REC_GAP},
    213: {"expects": "doing business", "category": "taxonomy_gap",
          "why": "Business-climate reform ranking (Doing Business); "
                 "macro-reform colour with no canonical mechanism family.",
          "recommendation": _REC_GAP},
    235: {"expects": "export growth", "category": "taxonomy_gap",
          "why": "Trade-data / export-growth print; a macro flow with no "
                 "canonical family (the sanction rule's 'export control' "
                 "phrase correctly does not fire on 'export growth').",
          "recommendation": _REC_GAP},
    237: {"expects": "gas exports", "category": "taxonomy_gap",
          "why": "Energy-tax-policy poll (tax on gas exports); a policy item "
                 "the taxonomy has no family for, and 'gas' is too generic a "
                 "token to add safely.",
          "recommendation": _REC_GAP},
    # --- genuine headline-token misses of an existing family --------------
    34: {"expects": "strait remains blocked",
         "category": "rule_miss_candidate",
         "why": "Unmistakably a Strait-of-Hormuz supply-and-conflict row, "
                "but the headline says 'Strait remains blocked' (not the "
                "literal 'hormuz' token) and 'infrastructure' (not an oil "
                "token), so the headline-only rules miss it.",
         "recommendation": _REC_RULE_MISS},
    218: {"expects": "export reductions",
          "category": "rule_miss_candidate",
          "why": "Unmistakably an oil-supply cut (Saudi voluntary production "
                 "/ export reductions), but the headline carries none of the "
                 "oil / opec / crude tokens - it says 'cuts' and 'export "
                 "reductions' instead.",
          "recommendation": _REC_RULE_MISS},
}


def diagnose_unclassified(event_id: int, headline: str | None) -> dict[str, str]:
    """Diagnose an unclassified row.

    Curated labels are applied only when the headline still matches the
    frozen J1 snapshot; anything else is honestly ``review_needed``.
    """
    entry = CURATED_UNCLASSIFIED.get(event_id)
    low = (headline or "").lower()
    if entry is not None and entry["expects"] in low:
        return {"category": entry["category"], "why": entry["why"],
                "recommendation": entry["recommendation"]}
    return {
        "category": "review_needed",
        "why": (
            "No curated diagnosis matches this row at its current headline; "
            "it falls outside the frozen J1 snapshot this review was written "
            "against and needs fresh human review."
        ),
        "recommendation": (
            "Review by hand. Do not assume a category and do not assign a "
            "family."
        ),
    }


# ---------------------------------------------------------------------------
# Proposed / rejected refinements, taxonomy lessons, non-claims (constants)
# ---------------------------------------------------------------------------

PROPOSED_REFINEMENTS: tuple[dict[str, Any], ...] = (
    {
        "refinement": "Add a bounded 'strait of hormuz' / 'strait ... "
                      "blocked' phrase to supply_shock so Hormuz "
                      "supply-threat rows that avoid the literal 'hormuz' "
                      "token are caught.",
        "affected_examples": [34],
        "expected_benefit": "Recovers one clear Strait-of-Hormuz "
                            "supply-and-conflict row (34) that currently "
                            "lands unclassified because it says 'Strait "
                            "remains blocked' rather than 'Hormuz'.",
        "risk": "'strait' and 'blocked' are generic; a loose phrase could "
                "fire on non-oil shipping or metaphorical 'blocked'. Must be "
                "a tightly bounded phrase, and the gain is a single row.",
        "status": "defer",
    },
    {
        "refinement": "Add oil-supply-action phrasing ('export reduction(s)', "
                      "'output cut', 'production cut') to supply_shock, gated "
                      "on a producer / OPEC context token.",
        "affected_examples": [218],
        "expected_benefit": "Recovers the Saudi / OPEC voluntary-cut row "
                            "(218), an oil-supply story with no oil / opec "
                            "token in the headline.",
        "risk": "Bare 'cut(s)' collides with rate cuts, job cuts, tax cuts, "
                "and price cuts - a high-false-positive token. Only a "
                "context-gated phrase is defensible; as a bare keyword it is "
                "rejected.",
        "status": "reject",
    },
    {
        "refinement": "Add a literal 'trade war' negative phrase to the "
                      "geopolitical_conflict_context 'war' token so "
                      "trade-policy rows stop drawing a spurious conflict "
                      "tag.",
        "affected_examples": [250],
        "expected_benefit": "Resolves the false {tariff, conflict} overlap "
                            "on row 250 back to single-match tariff by "
                            "suppressing the 'trade war' metaphor.",
        "risk": "Enumerating war-metaphor exclusions ('trade war', 'price "
                "war', 'bidding war') is whack-a-mole and could suppress a "
                "genuine 'war on X' conflict headline. Bounded to the literal "
                "'trade war' it is low-risk but narrow.",
        "status": "consider",
    },
    {
        "refinement": "Add a generic 'geopolitics' / 'geopolitical' catch-all "
                      "bucket to absorb rows that mention geopolitical risk "
                      "without a specific instrument.",
        "affected_examples": [25, 50],
        "expected_benefit": "Would reduce the unclassified count by the two "
                            "generic-geopolitics earnings rows.",
        "risk": "A generic 'geopolitics' token over-absorbs: most conflict "
                "and supply rows also mention geopolitics, so the bucket "
                "would swallow rows that belong to specific families and "
                "manufacture a meaningless mega-bucket. This is fake "
                "coverage and is rejected.",
        "status": "reject",
    },
    {
        "refinement": "Auto-suppress off-topic / archive-noise rows (space, "
                      "crime, trade-show) with a noise lexicon so the "
                      "unclassified bucket looks smaller.",
        "affected_examples": [2, 8, 9, 206, 207],
        "expected_benefit": "Would shrink the visible unclassified count.",
        "risk": "Hiding noise rows misrepresents the archive's heterogeneity "
                "and hardcodes a brittle noise lexicon; honest practice is to "
                "leave non-market rows visibly unclassified, not "
                "auto-filtered. Rejected.",
        "status": "reject",
    },
)

TAXONOMY_LESSONS: dict[str, list[str]] = {
    "what_the_weak_buckets_reveal": [
        "The 16 multi-match rows are almost entirely (15 of 16) one "
        "legitimate structural overlap: conflict-driven supply disruption "
        "(9 rows), oil repricing co-present with a de-escalation path "
        "(5 rows), and a sanction-triggered supply threat (1 row). The "
        "canonical taxonomy has no single family for a conflict that is "
        "itself the supply shock - the overlap is the structural fact, not "
        "rule failure.",
        "The single remaining multi-match row is a false overlap: the "
        "conflict 'war' token fires on the 'trade war' metaphor in a pure "
        "tariff headline.",
        "The 18 unclassified rows split into archive noise (10, no market "
        "mechanism), real macro / policy events the taxonomy cannot name "
        "(6: development / standards, trade-data, energy-tax, generic "
        "geopolitical-risk), and only 2 genuine headline-token misses "
        "(34 Hormuz, 218 Saudi cuts). Three of the 18 are exact-headline "
        "duplicates of others in the same bucket.",
    ],
    "what_should_not_be_forced": [
        "The conflict x supply and supply x de-escalation overlaps: do not "
        "pick a winner; both mechanisms are present in the headline.",
        "The off-topic / archive-noise rows: no mechanism family should "
        "absorb Moon imagery, local crime, ceremony, or trade-show colour.",
        "The generic-geopolitics rows: do not invent a catch-all "
        "'geopolitics' bucket; 'no specific mechanism named' is the honest "
        "state.",
    ],
    "what_can_improve_without_db_write": [
        "A curated, read-only second pass over only the 2 rule-miss rows "
        "(34, 218) with tightly bounded, context-gated phrases reviewed by a "
        "human before any rule change.",
        "Surfacing the duplicate-headline rows so the bucket's effective "
        "distinct size is visible.",
        "Documenting the conflict / supply overlap as an explicit, named "
        "taxonomy limitation rather than treating the multi-match bucket as "
        "a defect to eliminate.",
    ],
}

NON_CLAIMS: tuple[str, ...] = (
    "Review diagnoses are research notes, not DB labels: the "
    "mechanism_family column was not read as truth and was not modified.",
    "No database write occurred anywhere in this review (read-only overlay "
    "consumption; price_cache untouched).",
    "No family-level inference: the diagnoses describe why rows are "
    "ambiguous or unlabeled, never what any family does or how it behaves.",
    "No family performance ranking and no validated-vs-contradicted "
    "comparison is implied or computed here.",
    "No significance testing: no CI, p-value, or FDR anywhere in this "
    "review.",
    "Not a recommendation of any kind; the 'recommendation' fields are "
    "curation notes about the rules, not market guidance.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted "
    "track-record on the live archive; this review adds no denominator.",
)


# ---------------------------------------------------------------------------
# Review composer
# ---------------------------------------------------------------------------


def _clip(text: str | None, n: int = 160) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _safe(text: str) -> str:
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def build_review(db_path: str | None = None, *,
                 overlay: dict[str, Any] | None = None,
                 records: list[dict] | None = None,
                 include_examples: int = DEFAULT_EXAMPLES) -> dict[str, Any]:
    """Build the weak-bucket review dict. Read-only; consumes the J1 overlay.

    ``overlay`` / ``records`` are injectable for testing; by default the
    overlay comes from ``build_overlay`` (authoritative bucket membership)
    and the accepted records from the same loader J1 uses (headline
    enrichment only).
    """
    if overlay is None:
        overlay = build_overlay(db_path=db_path, limit=_OVERLAY_LIST_CAP)
    if records is None:
        records, _ = _load_accepted_records(db_path)
    by_id = {r["event_id"]: r for r in (records or [])}
    ex_cap = max(int(include_examples), 0)

    mm = overlay["ambiguous_or_multi_match"]
    unc = overlay["unclassified_or_review_needed"]

    mm_ids = list(mm.get("representative_event_ids", []))
    mm_sets = list(mm.get("matched_family_sets", []))
    if len(mm_ids) != mm.get("count", 0) or len(mm_sets) != mm.get("count", 0):
        raise ValueError(
            "multi-match overlay list is truncated; rerun the overlay with a "
            "larger --limit before reviewing")
    unc_ids = list(unc.get("representative_event_ids", []))
    unc_hs = list(unc.get("representative_headlines", []))
    if (len(unc_ids) != unc.get("count", 0)
            or len(unc_hs) != unc.get("count", 0)):
        raise ValueError(
            "unclassified overlay list is truncated; rerun the overlay with a "
            "larger --limit before reviewing")

    # Multi-match diagnostics (diagnosed by matched family set).
    multi_rows = []
    for eid, fams in zip(mm_ids, mm_sets):
        rec = by_id.get(eid)
        headline = _clip((rec.get("headline") if rec else "") or "")
        diag = diagnose_multi(fams)
        multi_rows.append({
            "event_id": eid,
            "headline": headline,
            "matched_families": list(fams),
            "diagnosis_category": diag["category"],
            "why_ambiguous": diag["why"],
            "recommendation": diag["recommendation"],
        })

    # Duplicate-headline detection within the unclassified bucket.
    groups: dict[str, list[int]] = {}
    full_by_eid: dict[int, str] = {}
    for eid, h in zip(unc_ids, unc_hs):
        rec = by_id.get(eid)
        full_h = ((rec.get("headline") if rec else None) or h or "")
        full_by_eid[eid] = full_h
        groups.setdefault(full_h.strip().lower(), []).append(eid)

    # Unclassified diagnostics (diagnosed by curated snapshot + drift guard).
    unc_rows = []
    for eid in unc_ids:
        full_h = full_by_eid[eid]
        diag = diagnose_unclassified(eid, full_h)
        row = {
            "event_id": eid,
            "headline": _clip(full_h),
            "diagnosis_category": diag["category"],
            "why_unclassified": diag["why"],
            "recommendation": diag["recommendation"],
        }
        siblings = [x for x in groups.get(full_h.strip().lower(), [])
                    if x != eid]
        if siblings:
            row["duplicate_of"] = sorted(siblings)
        unc_rows.append(row)

    single_match = sum(int(f.get("row_count", 0))
                       for f in overlay.get("family_counts", []))

    all_rows = multi_rows + unc_rows
    cats = [r["diagnosis_category"] for r in all_rows]

    def _count(name: str) -> int:
        return cats.count(name)

    examples: dict[str, list[int]] = {}
    for r in all_rows:
        bucket = examples.setdefault(r["diagnosis_category"], [])
        if len(bucket) < ex_cap:
            bucket.append(r["event_id"])

    pattern_summary = {
        "legitimate_overlap_count": _count("legitimate_overlap"),
        "taxonomy_gap_count": _count("taxonomy_gap"),
        "terse_or_missing_context_count": _count("terse_or_missing_context"),
        "off_topic_or_noise_count": _count("off_topic_or_noise"),
        "rule_miss_candidate_count": _count("rule_miss_candidate"),
        "overfit_risk_count": _count("overfit_risk"),
        "review_needed_count": _count("review_needed"),
        "total_weak_bucket_rows": len(all_rows),
        "examples_by_category": examples,
    }

    od = overlay["denominators"]
    denoms = {k: od.get(k) for k in (
        "archive_rows", "accepted_coverage_denominator",
        "accepted_track_record_denominator", "staged_candidate_count",
        "overlay_target_count")}

    return {
        "denominators": denoms,
        "review_scope": {
            "source_report": "accepted_family_overlay_report",
            "source_counts": {
                "single_match": single_match,
                "multi_match": mm.get("count", 0),
                "unclassified_or_review_needed": unc.get("count", 0),
            },
            "db_write_status": "not_written",
            "overlay_only": True,
        },
        "multi_match_diagnostics": {
            "count": mm.get("count", 0),
            "rows": multi_rows,
        },
        "unclassified_diagnostics": {
            "count": unc.get("count", 0),
            "rows": unc_rows,
        },
        "pattern_summary": pattern_summary,
        "proposed_rule_refinements": [dict(r) for r in PROPOSED_REFINEMENTS],
        "taxonomy_lessons": {k: list(v)
                             for k, v in TAXONOMY_LESSONS.items()},
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(review: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Accepted-family overlay review - weak-bucket diagnostics (read-only)")
    add("=" * 68)
    d = review["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | overlay target "
        f"{d['overlay_target_count']}")
    sc = review["review_scope"]["source_counts"]
    add(f"Source overlay (accepted_family_overlay_report): single-match "
        f"{sc['single_match']} | multi-match {sc['multi_match']} | "
        f"unclassified/review-needed {sc['unclassified_or_review_needed']}")
    add(f"DB write status: {review['review_scope']['db_write_status']} "
        "(overlay only)")
    add("")

    add("Multi-match diagnostics (ambiguity surfaced, never forced):")
    for r in review["multi_match_diagnostics"]["rows"]:
        add(f"  [{r['event_id']}] {r['diagnosis_category']}  "
            f"{' + '.join(r['matched_families'])}")
        add(f"      {_safe(_clip(r['headline'], 96))}")
        add(f"      why: {_safe(r['why_ambiguous'])}")
        add(f"      -> {_safe(r['recommendation'])}")
    add("")

    add("Unclassified / review-needed diagnostics:")
    for r in review["unclassified_diagnostics"]["rows"]:
        dup = (f"  (duplicate of {r['duplicate_of']})"
               if r.get("duplicate_of") else "")
        add(f"  [{r['event_id']}] {r['diagnosis_category']}{dup}")
        add(f"      {_safe(_clip(r['headline'], 96))}")
        add(f"      why: {_safe(r['why_unclassified'])}")
        add(f"      -> {_safe(r['recommendation'])}")
    add("")

    ps = review["pattern_summary"]
    add("Pattern summary (counts across both weak buckets):")
    add(f"  legitimate overlap      {ps['legitimate_overlap_count']}")
    add(f"  taxonomy gap            {ps['taxonomy_gap_count']}")
    add(f"  terse / missing context {ps['terse_or_missing_context_count']}")
    add(f"  off-topic / noise       {ps['off_topic_or_noise_count']}")
    add(f"  rule-miss candidate     {ps['rule_miss_candidate_count']}")
    add(f"  overfit risk            {ps['overfit_risk_count']}")
    add(f"  review needed           {ps['review_needed_count']}")
    add("")

    add("Proposed / rejected rule refinements (recommendations only, never "
        "applied):")
    for r in review["proposed_rule_refinements"]:
        add(f"  [{r['status']}] {_safe(r['refinement'])}")
        add(f"      examples: {r['affected_examples']}")
        add(f"      benefit:  {_safe(r['expected_benefit'])}")
        add(f"      risk:     {_safe(r['risk'])}")
    add("")

    add("Do not force ambiguity:")
    for item in review["taxonomy_lessons"]["what_should_not_be_forced"]:
        add(f"  - {_safe(item)}")
    add("")

    add("Non-claims:")
    for item in review["non_claims"]:
        add(f"  - {_safe(item)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostics for the J1 overlay's weak "
                    "buckets (multi-match and unclassified rows).")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-examples", type=int,
                        default=DEFAULT_EXAMPLES)
    args = parser.parse_args(argv)

    review = build_review(db_path=args.db_path,
                          include_examples=args.include_examples)
    if args.json:
        print(json.dumps(review, indent=2, sort_keys=True))
    else:
        print(_render_text(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

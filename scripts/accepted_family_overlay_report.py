#!/usr/bin/env python3
"""Read-only mechanism-family overlay for the accepted thesis corpus.

The mechanism-family overview states the project's largest taxonomy
limitation: every thesis row in the accepted track-record corpus is
family-untagged (`none`), so per-family splits are structurally degenerate.
This report measures how the taxonomy covers that corpus WITHOUT touching it:
deterministic, inspectable whole-token rules classify each accepted thesis
headline entirely in memory.

Discipline (non-negotiable):

  * **Overlay, not DB labels.** Nothing is written to events.db; the
    ``mechanism_family`` column stays untouched. ``db_write_status`` is
    ``not_written`` by construction (``mode=ro`` connections only).
  * **Ambiguity is surfaced, never forced.** A headline matching two
    families lands in the multi-match bucket with both names; a headline
    matching none stays unclassified. No tie-breaking, no second-guessing.
  * **Coverage decomposition, not family performance.** The descriptive
    splits reuse the AV3 scoring module's canonical any_support rule per
    event, but per-family n is tiny and post-hoc-labeled - the splits say
    where the corpus sits, never which family "works".
  * Row selection reuses the AV3 sensitivity report's accepted-record
    loader, so the overlay target is exactly the canonical track-record
    denominator set.

Usage::

    python scripts/accepted_family_overlay_report.py --db-path events.db --json
    python scripts/accepted_family_overlay_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402
from scripts.track_record_sensitivity_report import _load_accepted_records  # noqa: E402
from stats.track_record_scoring import score_event_under_rule  # noqa: E402

DEFAULT_EXAMPLES = 3
DEFAULT_LIST_CAP = 10

# Deterministic rule set. Whole-token / bounded-phrase matching over the
# headline only - the most inspectable basis field. ``canonical_family`` marks
# whether the name exists in the project taxonomy (mechanism_family.py);
# overlay-only buckets are flagged False and exist to make coverage honest,
# not to extend the taxonomy.
FAMILY_RULES: tuple[dict[str, Any], ...] = (
    {
        "family": "tariff",
        "canonical_family": True,
        "include_terms": ["tariff", "tariffs"],
        "include_phrases": ["trade deal", "trade pact", "reciprocal trade"],
        "rationale": "Trade-policy instrument named directly; the archive's "
                     "accepted tariff observations use the same vocabulary.",
    },
    {
        "family": "sanction",
        "canonical_family": True,
        "include_terms": ["sanction", "sanctions", "sanctioned"],
        "include_phrases": ["export control", "export controls",
                            "entity list"],
        "rationale": "Sanction/export-control instrument named directly; "
                     "matches the curated export-control anchors' vocabulary.",
    },
    {
        "family": "supply_shock",
        "canonical_family": True,
        "include_terms": ["oil", "crude", "opec", "hormuz", "refinery",
                          "refineries", "pipeline", "tanker", "bpd",
                          "barrel", "barrels", "osp", "osps"],
        "include_phrases": [],
        "rationale": "Oil/commodity supply disruption and supply policy. At "
                     "overlay level this bucket deliberately folds the "
                     "commodity_squeeze / supply_normalization flavors into "
                     "one supply family - splitting them by keyword would be "
                     "fake precision.",
    },
    {
        "family": "ceasefire_deescalation",
        "canonical_family": True,
        "include_terms": ["ceasefire", "diplomacy"],
        "include_phrases": ["peace deal", "peace talks"],
        "rationale": "De-escalation path named directly; distinct repricing "
                     "direction from the conflict/supply cluster.",
    },
    {
        "family": "regulation",
        "canonical_family": True,
        "include_terms": ["antitrust"],
        "include_phrases": ["monopoly power", "antitrust suit"],
        "rationale": "Antitrust/regulatory overhang vocabulary. Expected to "
                     "be rare or absent in the accepted thesis corpus - the "
                     "regulation family currently lives in staged candidates "
                     "only.",
    },
    {
        "family": "labor_inflation",
        "canonical_family": True,
        "include_terms": ["union", "wage", "wages", "walkout"],
        "include_phrases": ["labor strike", "workers strike"],
        "rationale": "Labor-cost shock vocabulary. The bare token 'strike' "
                     "is deliberately excluded: it collides with military "
                     "strikes throughout this archive.",
    },
    {
        "family": "industrial_policy",
        "canonical_family": True,
        "include_terms": ["subsidy", "subsidies"],
        "include_phrases": ["chips act", "inflation reduction act"],
        "rationale": "Beneficiary-channel policy vocabulary. Expected rare "
                     "or absent - industrial_policy lives in staged "
                     "candidates only.",
    },
    {
        "family": "monetary_policy_or_rates",
        "canonical_family": False,
        "include_terms": ["powell"],
        "include_phrases": ["federal reserve", "central bank",
                            "interest rate", "interest rates",
                            "bank of england"],
        "rationale": "Overlay-only bucket: the canonical taxonomy has no "
                     "monetary-policy family, yet central-bank rows visibly "
                     "exist in the corpus. Flagging them honestly beats "
                     "leaving them unclassified.",
    },
    {
        "family": "geopolitical_conflict_context",
        "canonical_family": False,
        "include_terms": ["war", "drone", "drones", "missile", "missiles",
                          "military", "jet", "jets", "airman", "troops"],
        "include_phrases": ["fighter jet", "shot down", "armed forces"],
        "rationale": "Overlay-only bucket: the archive's dominant cluster is "
                     "conflict-driven, and the canonical taxonomy has no "
                     "conflict family. Overlap with supply_shock is the "
                     "point - it is measured in the multi-match bucket, not "
                     "hidden.",
    },
)

NON_CLAIMS: tuple[str, ...] = (
    "Overlay labels are research overlay, not DB labels: the "
    "mechanism_family column was not read as truth and was not modified.",
    "No database write occurred anywhere in this report (read-only "
    "connections; price_cache untouched).",
    "No family-level inference: per-family rows are post-hoc keyword "
    "matches over tiny n - the splits describe where the corpus sits, "
    "nothing about any family's behavior.",
    "No family performance ranking and no validated-vs-contradicted "
    "comparison across families is implied; outcome labels are the "
    "canonical AV3 vocabulary applied per event, descriptively.",
    "No significance testing: no CI, p-value, or FDR anywhere here.",
    "Not a recommendation of any kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted "
    "track-record on the live archive; the overlay adds no denominator.",
)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _compile_rules() -> list[tuple[str, list[re.Pattern]]]:
    compiled = []
    for rule in FAMILY_RULES:
        pats = [re.compile(rf"\b{re.escape(t)}\b")
                for t in rule["include_terms"]]
        pats += [re.compile(rf"\b{re.escape(p)}\b")
                 for p in rule["include_phrases"]]
        compiled.append((rule["family"], pats))
    return compiled


_COMPILED = _compile_rules()


def classify_headline(headline: str | None) -> list[str]:
    """Return the list of families whose rules match the headline."""
    low = (headline or "").lower()
    return [family for family, pats in _COMPILED
            if any(p.search(low) for p in pats)]


# ---------------------------------------------------------------------------
# Overlay composer
# ---------------------------------------------------------------------------


def build_overlay(*, db_path: str | None = None,
                  include_examples: int = DEFAULT_EXAMPLES,
                  limit: int = DEFAULT_LIST_CAP) -> dict[str, Any]:
    """Build the overlay dict. Read-only; labels live in memory only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    ex_cap = max(int(include_examples), 0)
    list_cap = max(int(limit), 0)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    records, _denom_meta = _load_accepted_records(path)

    denoms = {
        "archive_rows": edq["denominators"]["archive_rows"],
        "accepted_coverage_denominator":
            edq["denominators"]["accepted_coverage_denominator"],
        "accepted_track_record_denominator":
            edq["denominators"]["accepted_track_record_denominator"],
        "staged_candidate_count":
            edq["denominators"]["staged_candidate_count"],
        "overlay_target_count": len(records),
        "target_matches_track_record_denominator":
            len(records)
            == edq["denominators"]["accepted_track_record_denominator"],
        "note": (
            "The overlay target is the accepted thesis (track-record) set, "
            "selected with the same loader as the AV3 sensitivity report. "
            "Staged, curated-observation, intake, pending, and synthetic "
            "rows are excluded and never classified here."
        ),
    }

    single: dict[str, list[dict]] = {r["family"]: [] for r in FAMILY_RULES}
    multi: list[dict] = []
    unclassified: list[dict] = []
    for rec in records:
        matched = classify_headline(rec["headline"])
        entry = {"event_id": rec["event_id"],
                 "headline": (rec["headline"] or "")[:90],
                 "tickers": rec["tickers"], "matched": matched}
        if len(matched) == 1:
            single[matched[0]].append(entry)
        elif matched:
            multi.append(entry)
        else:
            unclassified.append(entry)

    target = len(records)

    def _share(n: int) -> float:
        return round(100.0 * n / target, 1) if target else 0.0

    family_counts = []
    for rule in FAMILY_RULES:
        rows = single[rule["family"]]
        family_counts.append({
            "family": rule["family"],
            "canonical_family": rule["canonical_family"],
            "row_count": len(rows),
            "share_of_overlay_target": _share(len(rows)),
            "representative_event_ids":
                [e["event_id"] for e in rows[:ex_cap]],
            "representative_headlines":
                [e["headline"] for e in rows[:ex_cap]],
        })

    splits = []
    for rule in FAMILY_RULES:
        rows = single[rule["family"]]
        if not rows:
            continue
        outcomes = {"validated": 0, "contradicted": 0, "unresolved": 0}
        for e in rows:
            outcomes[score_event_under_rule(e["tickers"], "any_support")] += 1
        splits.append({
            "family": rule["family"],
            "n": len(rows),
            "any_support_outcomes": outcomes,
            "descriptive_only": True,
            "no_family_level_inference": True,
        })

    conflict_supply_overlap = sum(
        1 for e in multi
        if {"geopolitical_conflict_context", "supply_shock"} <= set(e["matched"])
    )
    dominant = max(family_counts, key=lambda f: f["row_count"],
                   default=None) if target else None
    zero_canonical = [f["family"] for f in family_counts
                      if f["canonical_family"] and f["row_count"] == 0]

    taxonomy_readout = {
        "what_the_overlay_reveals": [
            (f"Dominant single-match bucket: {dominant['family']} "
             f"({dominant['row_count']} rows, "
             f"{dominant['share_of_overlay_target']}% of the target)."
             if dominant and dominant["row_count"] else
             "No dominant single-match bucket."),
            (f"{len(multi)} rows match more than one family; "
             f"{conflict_supply_overlap} of them sit on the conflict x "
             "supply overlap - the archive's core cluster is conflict-"
             "driven supply disruption, which the canonical taxonomy has "
             "no single family for."),
            (f"Canonical families with zero accepted thesis matches: "
             f"{', '.join(zero_canonical) if zero_canonical else 'none'} - "
             "consistent with the C3 finding that those families exist "
             "only as staged candidates."),
        ],
        "what_remains_missing": [
            "Headline-only classification: richer local fields "
            "(mechanism_summary, transmission_chain) are not used yet, so "
            "terse headlines under-classify.",
            "The unclassified bucket visibly contains non-market rows "
            "(human-interest / off-topic headlines) that no taxonomy "
            "family should absorb; they need curated review, not rules.",
            "Overlay-only buckets (monetary policy, conflict context) mark "
            "real corpus mass the canonical taxonomy cannot name.",
        ],
        "suggested_next_no_mutation_improvements": [
            "Curated human review of the unclassified and multi-match "
            "buckets against the rule table (read-only).",
            "A second basis field (mechanism_summary) behind the same "
            "whole-token rules, reported as a separate lens - never merged "
            "silently with the headline lens.",
            "Only after the rules are reviewed and stable should writing "
            "labels into the DB even be considered - and that would be its "
            "own gated task.",
        ],
    }

    return {
        "denominators": denoms,
        "overlay_scope": {
            "target_corpus": "accepted_thesis_track_record_rows",
            "db_write_status": "not_written",
            "overlay_only": True,
            "classifier_type": "deterministic_rules",
            "classification_basis_fields": ["headline"],
        },
        "family_rules": [dict(r) for r in FAMILY_RULES],
        "family_counts": family_counts,
        "ambiguous_or_multi_match": {
            "count": len(multi),
            "share_of_overlay_target": _share(len(multi)),
            "representative_event_ids":
                [e["event_id"] for e in multi[:list_cap]],
            "matched_family_sets":
                [e["matched"] for e in multi[:list_cap]],
            "how_resolved": (
                "Not forced: rows matching more than one family are "
                "reported here with every matched family, instead of being "
                "assigned by precedence or weights."
            ),
        },
        "unclassified_or_review_needed": {
            "count": len(unclassified),
            "share_of_overlay_target": _share(len(unclassified)),
            "representative_event_ids":
                [e["event_id"] for e in unclassified[:list_cap]],
            "representative_headlines":
                [e["headline"] for e in unclassified[:list_cap]],
            "reason": (
                "No rule matched the headline. This bucket mixes terse "
                "market headlines and visibly off-topic rows; it needs "
                "curated review, not looser rules."
            ),
        },
        "descriptive_splits_if_available": {
            "splits": splits,
            "note": (
                "Coverage decomposition only: per-event outcomes use the "
                "canonical any_support rule from the AV3 scoring module, "
                "aggregated by overlay family. Tiny post-hoc-labeled n - "
                "these counts locate the corpus, they do not compare "
                "families."
            ),
        },
        "taxonomy_readout": taxonomy_readout,
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _safe(text: str) -> str:
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def _render_text(overlay: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Accepted-corpus mechanism-family overlay (read-only)")
    add("=" * 60)
    d = overlay["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | overlay target "
        f"{d['overlay_target_count']}")
    add("")
    add("Overlay, not DB labels:")
    add("  Labels below are computed in memory from deterministic "
        "whole-token rules")
    add("  over headlines. The mechanism_family column was not modified "
        "(db_write_status:")
    add(f"  {overlay['overlay_scope']['db_write_status']}).")
    add("")
    add("Family coverage (single-match rows):")
    add(f"  {'family':<32}{'canonical':>10}{'rows':>6}{'share':>8}")
    for f in overlay["family_counts"]:
        add(f"  {f['family']:<32}{str(f['canonical_family']):>10}"
            f"{f['row_count']:>6}{f['share_of_overlay_target']:>7}%")
    multi = overlay["ambiguous_or_multi_match"]
    unc = overlay["unclassified_or_review_needed"]
    add(f"  {'(multi-match, not forced)':<32}{'-':>10}{multi['count']:>6}"
        f"{multi['share_of_overlay_target']:>7}%")
    add(f"  {'(unclassified / review-needed)':<32}{'-':>10}{unc['count']:>6}"
        f"{unc['share_of_overlay_target']:>7}%")
    add("")
    add("Representative examples:")
    for f in overlay["family_counts"]:
        if f["row_count"]:
            ex = "; ".join(_safe(h) for h in f["representative_headlines"])
            add(f"  {f['family']}: {ex}")
    add("")
    add("Unclassified / review-needed:")
    add(f"  {unc['count']} rows ({unc['share_of_overlay_target']}%). "
        f"{unc['reason']}")
    for h in unc["representative_headlines"]:
        add(f"  - {_safe(h)}")
    add("")
    add("Coverage decomposition, not family performance:")
    splits = overlay["descriptive_splits_if_available"]
    add(f"  {splits['note']}")
    for s in splits["splits"]:
        oc = s["any_support_outcomes"]
        add(f"  {s['family']}: n={s['n']} | validated {oc['validated']} / "
            f"contradicted {oc['contradicted']} / unresolved "
            f"{oc['unresolved']} (descriptive only)")
    add("")
    add("Taxonomy lessons:")
    tr = overlay["taxonomy_readout"]
    for item in tr["what_the_overlay_reveals"]:
        add(f"  - {item}")
    add("  Missing:")
    for item in tr["what_remains_missing"]:
        add(f"  - {item}")
    add("")
    add("Non-claims:")
    for item in overlay["non_claims"]:
        add(f"  - {item}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only mechanism-family overlay for the accepted "
                    "thesis corpus.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-examples", type=int,
                        default=DEFAULT_EXAMPLES)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIST_CAP)
    args = parser.parse_args(argv)

    overlay = build_overlay(db_path=args.db_path,
                            include_examples=args.include_examples,
                            limit=args.limit)
    if args.json:
        print(json.dumps(overlay, indent=2, sort_keys=True))
    else:
        print(_render_text(overlay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

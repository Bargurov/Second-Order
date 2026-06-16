"""Event-date quality distribution (J1) -- read-only honesty layer.

This report shows *how reliable the event-date anchors are* across the archive,
the accepted corpus, the event-study-available subset, and the 15-case
representative library. It answers one question only: when we read a market
window around an event, how trustworthy is the date the window is anchored on?

It is a pure honesty / legibility layer. It:

* reuses the existing event-date quality labels and their definitions
  (``scripts/event_date_quality_report``) -- it invents no new label semantics;
* reuses the event-study coverage report for the 78-of-94 available subset;
* reuses the representative case matrix (H1) for the 15-case library;
* reuses the headline family overlay (E1) for the per-family cross-section.

It computes NO new score, NO ranking, NO ordering by anchor quality, NO
inference, NO p-value and NO FDR. Anchor quality is an inherent per-event
gradient; this
report tabulates it and never aggregates it into a per-subset or per-family
quality number. The label-level anticipation_risk it surfaces is reused
verbatim from the event-date quality report and is never summed or used to rank.

Read-only: opens the archive in SQLite ``mode=ro`` and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accepted_family_overlay_report import classify_headline  # noqa: E402
from scripts.case_library_reaction_matrix import build_report as _h1_report  # noqa: E402
from scripts.event_date_quality_report import (  # noqa: E402
    LABELS as _EDQ_LABELS,
    _ANTICIPATION_RISK,
    build_report as _edq_report,
)
from scripts.event_study_coverage_report import (  # noqa: E402
    summarize_event_study_coverage,
)
from scripts.mechanism_family_evidence_inventory import _enrich_records  # noqa: E402

DEFAULT_DB = "events.db"

# Reuse the authoritative edq label set + canonical order (drift-guarded by test).
LABELS: tuple[str, ...] = tuple(_EDQ_LABELS)

# Canonical taxonomy order shared with E1 / I1 (never reordered by count/quality).
FAMILY_ORDER: tuple[str, ...] = (
    "supply_shock",
    "geopolitical_conflict_context",
    "tariff",
    "sanction",
    "ceasefire_deescalation",
    "monetary_policy_or_rates",
)

# One-line definitions, sourced from the edq classifier's rule descriptions. The
# anticipation_risk value is reused verbatim from the edq report (no new scale).
_DEFINITION_TEXT: dict[str, str] = {
    "clean_discrete_anchor":
        "Discrete filing or action wording on a specific date.",
    "partial_anticipation":
        "Process-start or anticipatory wording; the move can leak before "
        "the date.",
    "scheduled_or_weak_anchor":
        "Scheduled-culmination wording; most information was likely priced "
        "before the date.",
    "continuation_or_thread_sibling":
        "Shares a policy thread with an earlier anchor row; the date is not "
        "independent of it.",
    "duplicate_or_deferred":
        "Same-announcement collision with another row; deferred until the "
        "duplicate is resolved.",
    "manual_review_needed":
        "Missing or ambiguous date / fields, or no rule matched the wording.",
}

LABEL_DEFINITIONS: dict[str, dict[str, str]] = {
    label: {
        "definition": _DEFINITION_TEXT[label],
        "anticipation_risk": _ANTICIPATION_RISK[label],
    }
    for label in LABELS
}

# Plain-English reader names for the raw labels. Display only -- the raw labels
# remain the data-model keys everywhere (counts, percentages, per-case rows).
LABEL_DISPLAY_MAP: dict[str, str] = {
    "clean_discrete_anchor": "clear anchor",
    "partial_anticipation": "partly anticipated",
    "scheduled_or_weak_anchor": "scheduled / weak anchor",
    "continuation_or_thread_sibling": "thread continuation",
    "duplicate_or_deferred": "duplicate / deferred reaction",
    "manual_review_needed": "needs human anchor review",
}

# Reviewer-posture grouping: a fixed, descriptive reading aid that partitions the
# six labels into plain interpretation postures. It is NOT a score, NOT a rank,
# and nothing is sorted by it; label order inside each posture stays canonical.
POSTURE_DEFS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Clearer anchor", ("clean_discrete_anchor",)),
    ("Caveated but inspectable",
     ("partial_anticipation", "scheduled_or_weak_anchor")),
    ("Needs caution before interpretation",
     ("continuation_or_thread_sibling", "duplicate_or_deferred",
      "manual_review_needed")),
)

_RISK_GUARDRAIL = (
    "anticipation_risk is a per-label research caution reused from the "
    "event-date quality report; this report does not sum it, weight it, or "
    "use it to rank or score any subset or family."
)

_PCT_GUARDRAIL = (
    "Percentages are descriptive composition shares within each denominator. "
    "They are not scores, ranks, or evidence of stronger anchor quality."
)

_POSTURE_GUARDRAIL = (
    "Reviewer posture is a reading aid, not a score and not a rank; no case, "
    "family, or subset is sorted or ranked by it. It only groups the same "
    "labels into plain reading postures so the eye lands faster."
)

_MANUAL_REVIEW_EXPLANATION = (
    # negated non-claim kept contiguous on one line so a file-grep sees the "not"
    "manual_review_needed does not mean the event is false, the thesis failed, or the data is bad. "  # noqa: E501
    "It means the stored fields and headline are not enough for the system to "
    "treat the date as a clean anchor without human review. The row can still "
    "serve as archive evidence or a representative walkthrough case; only the "
    "market window around it should be read cautiously."
)

# Plain-English glosses for internal vocabulary a finance reader meets below.
VOCABULARY_GLOSSARY: tuple[dict[str, str], ...] = (
    {"term": "event-study available",
     "plain": "a price window can be computed around the date; it is not "
              "thesis support."},
    {"term": "representative case",
     "plain": "a walkthrough example chosen to illustrate a family; it is not "
              "evidence and not a claim."},
    {"term": "family cross-section",
     "plain": "a mechanism-family lens for side-by-side comparison; it is not "
              "a causal model."},
    {"term": "single-match / multi-match / unclassified",
     "plain": "headline-overlay taxonomy coverage categories (one family, "
              "several families, or none); they are not quality grades."},
    {"term": "curated / accepted / staged",
     "plain": "corpus-status buckets marking where a row sits in the pipeline; "
              "they are not market outcomes."},
)

READER_TAKEAWAYS: tuple[str, ...] = (
    "Most accepted track-record rows carry manual_review_needed: the date "
    "anchor or fields need a manual look before any window is read.",
    "clean_discrete_anchor is the minority of the accepted track record and is "
    "more common among the curated observation rows than the thesis rows.",
    "The archive-only continuation_or_thread_sibling label never appears in the "
    "accepted corpus; thread siblings are not carried as independent anchors.",
    "In the 15-case library only two cases (210, 212) are clean_discrete_anchor; "
    "the rest carry anticipation, scheduling, duplicate, or manual-review "
    "caveats.",
    "An anchor's quality label, its event-study availability, its market-readout "
    "availability, and its thesis outcome are four separate facts; this report "
    "keeps them separate and combines none of them into a number.",
)

LENS_DISCIPLINE: tuple[str, ...] = (
    "The event-date quality label, event-study availability, market-readout "
    "availability, and thesis outcome are four different lenses; do not collapse "
    "them into one number.",
    "A label is research caution about the date anchor; it is not a statement "
    "about whether the thesis held or how the market moved.",
    "Event-study availability is whether a SPY-relative window can be computed; "
    "it is not anchor quality and not thesis support.",
)

NON_CLAIMS: tuple[str, ...] = (
    "An event-date quality label is research caution, not evidence of any "
    "mechanism and not a measure of mechanism correctness.",
    "This report adds no new score and no ranking; it ranks nothing and orders "
    "no subset or family by anchor quality.",
    "Counts are descriptive; a visible pattern is not inference, and there is no "
    "significance claim, no p-value, and no FDR here.",
    "The closed Phase 1 / Phase 2 FDR pools remain separate from this "
    "descriptive read; nothing here is merged into them.",
    "Not a recommendation, forecast, or trading signal.",
)


# --------------------------------------------------------------------------- #
# Pure core                                                                   #
# --------------------------------------------------------------------------- #
def percent(count: int, denominator: int) -> float:
    """Descriptive composition share of ``count`` within ``denominator``,
    rounded to one decimal. Returns 0.0 when the denominator is zero. This is a
    composition share only -- never a score, a rank, or a quality measure.
    """
    if not denominator:
        return 0.0
    return round(count / denominator * 100, 1)


def format_count_pct(count: int, denominator: int) -> str:
    """Render a count with its descriptive percentage, count kept primary."""
    return f"{count} ({percent(count, denominator):.1f}%)"


def tabulate(labels_present: list[str]) -> dict[str, Any]:
    """Count ``labels_present`` over ALL six labels, zeros explicit, canonical
    order. Raises on an unknown label so a taxonomy drift cannot pass silently.
    """
    counts: dict[str, int] = {label: 0 for label in LABELS}
    for lab in labels_present:
        if lab not in counts:
            raise ValueError(f"unknown event-date quality label: {lab!r}")
        counts[lab] += 1
    return {"counts": counts, "total": len(labels_present)}


# --------------------------------------------------------------------------- #
# Read-only DB helper                                                         #
# --------------------------------------------------------------------------- #
def _unlabeled_by_stage(db_path: str, labeled_ids: set[int]) -> dict[str, Any]:
    """Characterise the archive rows outside the edq labelling universe."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT id, stage FROM events").fetchall()
    finally:
        con.close()
    by_stage: Counter[str] = Counter()
    for r in rows:
        if r["id"] not in labeled_ids:
            by_stage[r["stage"] or "unknown"] += 1
    return {"total": sum(by_stage.values()), "by_stage": dict(by_stage)}


# --------------------------------------------------------------------------- #
# Report                                                                      #
# --------------------------------------------------------------------------- #
def build_report(*, db_path: str | None = None) -> dict[str, Any]:
    path = db_path or DEFAULT_DB

    edq = _edq_report(db_path=path, lens="all", limit=0)
    events = edq["events"]
    id_label = {e["event_id"]: e["event_date_quality"] for e in events}
    id_status = {e["event_id"]: e["corpus_status"] for e in events}
    id_risk = {e["event_id"]: e["anticipation_risk"] for e in events}
    id_caveat = {
        e["event_id"]: e["horizon_interpretation_caution"] for e in events
    }
    labeled_ids = set(id_label)

    ed = edq["denominators"]
    es = summarize_event_study_coverage(db_path=path, limit=100_000)
    es_ids = [a["event_id"] for a in es["available"]]

    denominators = {
        "archive_rows": ed["archive_rows"],
        "accepted_coverage": ed["accepted_coverage_denominator"],
        "accepted_track_record": ed["accepted_track_record_denominator"],
        "event_study_available": es["event_study_available_count"],
        "event_study_total": es["total_events"],
        "staged_candidates": ed["staged_candidate_count"],
    }

    coverage_ids = [i for i, s in id_status.items() if s in ("accepted", "curated")]
    track_ids = [i for i, s in id_status.items() if s == "accepted"]

    # -- distributions (canonical subset order; each lists all six labels) ---- #
    archive_tab = tabulate([id_label[e["event_id"]] for e in events])
    unlabeled = _unlabeled_by_stage(path, labeled_ids)
    distributions = [
        {
            "subset": "archive",
            "scope": "all archive rows that carry an event-date quality label",
            "denominator": denominators["archive_rows"],
            "labeled_total": archive_tab["total"],
            "counts": archive_tab["counts"],
            "unlabeled": unlabeled,
        },
        {
            "subset": "accepted_coverage",
            "scope": "accepted coverage rows (accepted thesis rows + curated "
                     "observation rows)",
            "denominator": denominators["accepted_coverage"],
            "labeled_total": len(coverage_ids),
            "counts": tabulate([id_label[i] for i in coverage_ids])["counts"],
        },
        {
            "subset": "accepted_track_record",
            "scope": "accepted track-record rows (accepted thesis rows only)",
            "denominator": denominators["accepted_track_record"],
            "labeled_total": len(track_ids),
            "counts": tabulate([id_label[i] for i in track_ids])["counts"],
        },
        {
            "subset": "event_study_available",
            "scope": "rows with a computable SPY-relative event-study window",
            "denominator": denominators["event_study_available"],
            "lens": (
                "coverage-lens subset (78 of 94 event-study-available rows, "
                "including 8 curated observation rows alongside 70 accepted "
                "rows); not a track-record subset"
            ),
            "labeled_total": len(es_ids),
            "counts": tabulate([id_label[i] for i in es_ids])["counts"],
            "corpus_split": dict(Counter(id_status[i] for i in es_ids)),
        },
    ]

    # -- representative library (H1) ---------------------------------------- #
    h1 = _h1_report(db_path=path)
    matrix = h1["matrix"]
    missing_ids = list(h1["missingness_summary"]["missing_ids"])
    rep_tab = tabulate([r["event_date_quality"] for r in matrix])
    distributions.append({
        "subset": "representative_library",
        "scope": "the 15 selected representative cases",
        "denominator": len(matrix),
        "labeled_total": rep_tab["total"],
        "counts": rep_tab["counts"],
    })

    # -- descriptive composition percentages (count primary, % secondary) --- #
    # Each subset's percent denominator is its own labelled total: archive over
    # the 108 labelled rows (NOT 180), coverage over 94, track-record over 86,
    # event-study over 78, representative over 15.
    for dist in distributions:
        denom = dist["labeled_total"]
        dist["percent_denominator"] = denom
        dist["percentages"] = {
            label: percent(dist["counts"][label], denom) for label in LABELS
        }
    archive_dist = distributions[0]
    archive_dist["unlabeled"]["percent_of_archive"] = percent(
        archive_dist["unlabeled"]["total"], archive_dist["denominator"])

    representative_cases = []
    for r in matrix:
        eid = r["event_id"]
        representative_cases.append({
            "event_id": eid,
            "role": r["role"],
            "family": r["family"],
            "outcome": r["outcome"],
            "primary_ticker": r["primary_ticker"],
            "event_date_quality": r["event_date_quality"],
            "anticipation_risk": id_risk.get(
                eid, _ANTICIPATION_RISK.get(r["event_date_quality"], "unknown")),
            "anchor_caveat": id_caveat.get(eid, ""),
            "event_study_available": bool(r["event_study_available"]),
            "readout_available": bool(r["readout"]["available"]),
        })

    # -- family cross-section (E1 single-match overlay) --------------------- #
    enriched, _, _ = _enrich_records(path)
    fam_ids: dict[str, list[int]] = {}
    multi = 0
    unclassified = 0
    for rec in enriched:
        matches = classify_headline(rec["headline"])
        if len(matches) == 1:
            fam_ids.setdefault(matches[0], []).append(rec["event_id"])
        elif matches:
            multi += 1
        else:
            unclassified += 1
    families = []
    for fam in FAMILY_ORDER:
        ids = fam_ids.get(fam, [])
        families.append({
            "family": fam,
            "n": len(ids),
            "counts": tabulate([id_label[i] for i in ids])["counts"],
        })
    single_total = sum(f["n"] for f in families)
    family_cross_section = {
        "families": families,
        "multi_match": multi,
        "unclassified": unclassified,
        "single_match_total": single_total,
        "accepted_total": single_total + multi + unclassified,
    }

    # -- reviewer-facing legibility layer (descriptive only, no new metric) -- #
    track_dist = next(
        d for d in distributions if d["subset"] == "accepted_track_record")
    track_counts = track_dist["counts"]
    track_denom = denominators["accepted_track_record"]
    manual_n = track_counts["manual_review_needed"]
    clean_n = track_counts["clean_discrete_anchor"]

    reviewer_headline = [
        f"{manual_n} of {track_denom} accepted track-record rows "
        f"({percent(manual_n, track_denom):.1f}%) are labelled "
        f"manual_review_needed: the row is kept, but its event-date anchor "
        f"should be checked by a human before anyone leans on the market "
        f"window around it.",
        # negated non-claim kept contiguous on one line for a clean file-grep
        "That is an anchor-confidence warning, not a failed thesis and not bad data -- "  # noqa: E501
        "the stored fields and headline are simply not enough to treat the "
        "date as a clean anchor without review.",
        f"Only {clean_n} of {track_denom} accepted track-record rows "
        f"({percent(clean_n, track_denom):.1f}%) are clean discrete anchors; "
        f"the rest carry an anticipation, scheduling, duplicate, or review "
        f"caveat.",
        "Read this as the archive being more honest, not weaker: it marks "
        "where the date is solid enough to inspect a window and where "
        "interpretation must stay cautious.",
    ]

    posture_groups = {
        "denominator": track_denom,
        "scope": "accepted track-record rows",
        "guardrail": _POSTURE_GUARDRAIL,
        "groups": [
            {
                "posture": name,
                "labels": list(labels),
                "display": [LABEL_DISPLAY_MAP[l] for l in labels],
                "count": sum(track_counts[l] for l in labels),
                "percent": percent(sum(track_counts[l] for l in labels),
                                   track_denom),
                "members": [
                    {"label": l, "display": LABEL_DISPLAY_MAP[l],
                     "count": track_counts[l]} for l in labels
                ],
            }
            for name, labels in POSTURE_DEFS
        ],
    }

    return {
        "reviewer_headline": reviewer_headline,
        "manual_review_explanation": _MANUAL_REVIEW_EXPLANATION,
        "label_display_map": dict(LABEL_DISPLAY_MAP),
        "posture_groups": posture_groups,
        "vocabulary_glossary": [dict(g) for g in VOCABULARY_GLOSSARY],
        "purpose": (
            "Read-only event-date quality distribution: how reliable the event "
            "anchors are across the archive, the accepted corpus, the "
            "event-study-available subset, and the representative case library. "
            "It adds no new score and ranks nothing."
        ),
        "denominators": denominators,
        "label_definitions": [
            {"label": label, **LABEL_DEFINITIONS[label]} for label in LABELS
        ],
        "label_definition_guardrail": _RISK_GUARDRAIL,
        "percentage_guardrail": _PCT_GUARDRAIL,
        "distributions": distributions,
        "representative_cases": representative_cases,
        "missing_readout_ids": missing_ids,
        "family_cross_section": family_cross_section,
        "reader_takeaways": list(READER_TAKEAWAYS),
        "lens_discipline": list(LENS_DISCIPLINE),
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/event_date_quality_distribution_report.py "
            "--db-path events.db --json"
        ),
    }


# --------------------------------------------------------------------------- #
# Text rendering (ASCII / cp1252-safe)                                        #
# --------------------------------------------------------------------------- #
_SHORT = {
    "clean_discrete_anchor": "clean",
    "partial_anticipation": "partial",
    "scheduled_or_weak_anchor": "scheduled",
    "continuation_or_thread_sibling": "thread",
    "duplicate_or_deferred": "dup",
    "manual_review_needed": "manual",
}


def _counts_row(counts: dict[str, int]) -> str:
    return "  ".join(f"{_SHORT[l]} {counts[l]}" for l in LABELS)


def _counts_pct_row(counts: dict[str, int], pcts: dict[str, float]) -> str:
    return "  ".join(
        f"{_SHORT[l]} {counts[l]} ({pcts[l]:.1f}%)" for l in LABELS)


def render_text(report: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("Event-date quality distribution (J1)")
    out.append("")

    # -- reviewer takeaway first, before any methodology / denominators ------ #
    out.append("What a reviewer should take away first")
    out.append("-" * 38)
    for line in report["reviewer_headline"]:
        out.append(f"  - {line}")
    out.append("")
    out.append("What `manual_review_needed` means")
    out.append(f"  {report['manual_review_explanation']}")
    out.append("")

    out.append("Plain-English label map (display names; raw labels unchanged):")
    for raw in LABELS:
        out.append(f"  {raw:<32} = {report['label_display_map'][raw]}")
    out.append("")

    pg = report["posture_groups"]
    out.append(f"Reviewer posture, not a score "
               f"(over {pg['denominator']} accepted track-record rows):")
    for g in pg["groups"]:
        breakdown = ", ".join(
            f"{m['display']} {m['count']}" for m in g["members"])
        out.append(
            f"  {g['posture']}: {g['count']} ({g['percent']:.1f}%)  "
            f"[{breakdown}]"
        )
    out.append(f"  Note: {pg['guardrail']}")
    out.append("")

    out.append("Project vocabulary used below:")
    for g in report["vocabulary_glossary"]:
        out.append(f"  {g['term']} -- {g['plain']}")
    out.append("")

    d = report["denominators"]
    out.append("Denominators (live):")
    out.append(
        f"  archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage']} | accepted track-record "
        f"{d['accepted_track_record']} | event-study "
        f"{d['event_study_available']}/{d['event_study_total']} | staged "
        f"{d['staged_candidates']} (excluded)"
    )
    out.append("")

    out.append("Label definitions (reused from the event-date quality report):")
    for row in report["label_definitions"]:
        out.append(
            f"  {row['label']} [risk: {row['anticipation_risk']}]"
        )
        out.append(f"      {row['definition']}")
    out.append(f"  Note: {report['label_definition_guardrail']}")
    out.append("")

    out.append("Distributions (count primary, descriptive % over the subset "
               "denominator; all six labels, canonical order):")
    for dist in report["distributions"]:
        head = f"  [{dist['subset']}] n={dist['labeled_total']} " \
               f"(% over {dist['percent_denominator']})"
        if "lens" in dist:
            head += f"  ({dist['lens']})"
        out.append(head)
        out.append(f"      {_counts_pct_row(dist['counts'], dist['percentages'])}")
        if "unlabeled" in dist:
            by = dist["unlabeled"]["by_stage"]
            stages = ", ".join(f"{k} {v}" for k, v in by.items())
            out.append(
                f"      unlabeled {dist['unlabeled']['total']} "
                f"({dist['unlabeled']['percent_of_archive']:.1f}% of "
                f"{dist['denominator']}; {stages}) -> archive total "
                f"{dist['denominator']}"
            )
        if "corpus_split" in dist:
            cs = ", ".join(f"{k} {v}" for k, v in dist["corpus_split"].items())
            out.append(f"      corpus split: {cs}")
    out.append(f"  Note: {report['percentage_guardrail']}")
    out.append("")

    out.append("Representative cases (four separate lenses per case):")
    out.append(
        "  id    label                 risk           ES   readout  outcome"
    )
    for c in report["representative_cases"]:
        out.append(
            f"  {c['event_id']:<5} {c['event_date_quality']:<21} "
            f"{c['anticipation_risk']:<14} "
            f"{'y' if c['event_study_available'] else 'n':<4} "
            f"{'y' if c['readout_available'] else 'n':<8} {c['outcome']}"
        )
    out.append(
        f"  missing market readouts: "
        f"{', '.join(str(i) for i in report['missing_readout_ids'])}"
    )
    out.append("")

    fx = report["family_cross_section"]
    out.append("Family cross-section (accepted thesis rows, single-match overlay):")
    for f in fx["families"]:
        out.append(f"  {f['family']:<32} n={f['n']:<3} {_counts_row(f['counts'])}")
    out.append(
        f"  single-match {fx['single_match_total']} + multi-match "
        f"{fx['multi_match']} + unclassified {fx['unclassified']} = "
        f"{fx['accepted_total']}"
    )
    out.append("")

    out.append("Reader takeaways:")
    for t in report["reader_takeaways"]:
        out.append(f"  - {t}")
    out.append("")
    out.append("Lens discipline:")
    for t in report["lens_discipline"]:
        out.append(f"  - {t}")
    out.append("")
    out.append("Caveats / non-claims:")
    for t in report["non_claims"]:
        out.append(f"  - {t}")
    out.append("")
    out.append("About this report (source / method):")
    out.append(f"  {report['purpose']}")
    out.append(f"  Reproduce: {report['reproduce_command']}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Event-date quality distribution report (read-only).")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    args = parser.parse_args(argv)
    sink = out if out is not None else sys.stdout

    report = build_report(db_path=args.db_path)
    if args.json:
        json.dump(report, sink, indent=2)
        sink.write("\n")
    else:
        sink.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

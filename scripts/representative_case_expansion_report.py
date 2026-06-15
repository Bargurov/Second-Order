#!/usr/bin/env python3
"""Read-only representative-case expansion report (F1).

Propose a broader, deterministic representative case library across mechanism
families, so a finance reviewer can see the archive's mechanisms, outcomes, weak
spots, contradictions, and unresolved examples beyond the six N1 anchors. It
adds no new analysis, no p-values, no FDR, no forecast, and no trading language.

Faithful reuse (no reinvented taxonomy or scoring):
  * canonical denominators + per-family coverage come from the E1 inventory
    (``mechanism_family_evidence_inventory.build_inventory``) and are displayed
    verbatim, so this report cannot drift from E1;
  * per-row candidate pools come from E1's ``_enrich_records`` grouped by the
    same tested headline overlay (``classify_headline``) and scored by the same
    canonical ``score_event_under_rule`` (any_support).

Selection policy (deterministic):
  * The six N1 cases (1, 61, 210, 46, 66, 211) are carried as already-covered
    anchors, one per family on the live archive.
  * Per family the library = anchors + new picks, capped at 3 total. New picks
    fill the remaining slots in order support -> contradiction -> unresolved,
    then by (event-study-available first, lowest event_id).
  * Thin families (n <= 4) keep their unresolved cases rather than dropping them.
  * Global target 12-15 total (hard max 18). If the per-family selection exceeds
    the target, trim NEW picks only (never anchors), removing the most-removable
    first: support before contradiction/unresolved, missing-readout before
    event-study-available, higher event_id before lower; never drop a family's
    last library entry.

Read-only throughout (mode=ro loaders, reused tested helpers); no DB or
price_cache write, no paid call, no /analyze, no fetch.

Usage::

    python scripts/representative_case_expansion_report.py --db-path events.db --json
    python scripts/representative_case_expansion_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts.accepted_family_overlay_report import classify_headline  # noqa: E402
from scripts.mechanism_family_evidence_inventory import (  # noqa: E402
    _enrich_records,
    build_inventory,
)
from stats.track_record_scoring import score_event_under_rule  # noqa: E402

N1_BASELINE_IDS: tuple[int, ...] = (1, 61, 210, 46, 66, 211)
PER_FAMILY_CAP = 3       # library entries per family, INCLUDING N1 anchors
THIN_FLOOR = 4           # families with n <= this are thin
GLOBAL_TARGET = 15       # trim total library to <= this (target band 12-15)
GLOBAL_MAX = 18          # hard ceiling (6 families x cap 3)
SCORING_RULE = "any_support"

_OUTCOME_LABEL = {
    "validated": "support",
    "contradicted": "contradiction",
    "unresolved": "unresolved",
}

NON_CLAIMS: tuple[str, ...] = (
    "Illustrative case library only; this report adds no new claim.",
    "Representative cases are illustrative, not evidence and not family-level "
    "inference.",
    "No pooled significance: no CI, p-value, or FDR is computed or implied.",
    "No family performance ranking and no across-family comparison is implied.",
    "Not a recommendation of any kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record; "
    "staged candidates (13) are excluded and never selected here.",
)


# ---------------------------------------------------------------------------
# Pure selection core
# ---------------------------------------------------------------------------

def _order_key(r: dict) -> tuple:
    """Prefer event-study-available, then lowest event_id."""
    return (not bool(r.get("event_study_available")), r["event_id"])


def select_family_new(candidates: Sequence[dict], slots: int) -> list[dict]:
    """Pick up to ``slots`` new cases: one support, one contradiction, one
    unresolved (in that order), then fill by (event-study, lowest id)."""
    slots = max(0, int(slots))
    picks: list[dict] = []
    taken: set = set()
    for oc in ("validated", "contradicted", "unresolved"):
        if len(picks) >= slots:
            break
        bucket = sorted([r for r in candidates if r.get("outcome") == oc], key=_order_key)
        for r in bucket:
            if r["event_id"] not in taken:
                picks.append(r)
                taken.add(r["event_id"])
                break
    if len(picks) < slots:
        rest = sorted([r for r in candidates if r["event_id"] not in taken], key=_order_key)
        for r in rest:
            if len(picks) >= slots:
                break
            picks.append(r)
            taken.add(r["event_id"])
    return picks


def _global_trim(library: list[dict], *, target: int) -> list[dict]:
    """Trim NEW picks only until the library is within ``target``.

    Protection hierarchy (most protected -> least), so the trim avoids
    cherry-picking the largest family down to non-supporting cases:
      1. anchors are never removed (only ``newly_proposed`` rows are removable);
      2. a family's last remaining entry is never removed (family coverage);
      3. one support example for a MATERIAL (non-thin) family with support is
         protected (removed last);
      4. contradiction / unresolved diversifying examples are protected next;
      5. duplicate same-outcome extras (an outcome already covered by the
         family's anchor or an earlier diversifying pick) are trimmed FIRST.
    Within a tier: non-thin before thin, missing-readout before
    event-study-available, higher event_id before lower (lower id kept).
    """
    if len(library) <= target:
        return list(library)
    fam_count: Counter = Counter(r["family"] for r in library)

    # Per family, mark each new pick as diversifying (introduces an outcome not
    # already covered) or a duplicate same-outcome extra; flag the protected
    # support of a material family.
    anchor_outcomes: dict[str, set] = {}
    for r in library:
        if r["role"] == "already_covered_anchor":
            anchor_outcomes.setdefault(r["family"], set()).add(r["outcome"])
    new_by_family: dict[str, list[dict]] = {}
    for r in library:
        if r["role"] == "newly_proposed":
            new_by_family.setdefault(r["family"], []).append(r)
    diversifying: set = set()
    protected_support: set = set()
    for fam, rows in new_by_family.items():
        covered = set(anchor_outcomes.get(fam, set()))
        material = not rows[0].get("thin", False)
        for r in sorted(rows, key=lambda x: x.get("rank_in_family", 0)):
            key = (fam, r["event_id"])
            oc = r["outcome"]
            if oc not in covered:
                diversifying.add(key)
                covered.add(oc)
                if oc == "validated" and material:
                    protected_support.add(key)

    def remove_key(r: dict) -> tuple:
        key = (r["family"], r["event_id"])
        return (
            1 if key in diversifying else 0,          # duplicates removed first
            1 if key in protected_support else 0,     # material support last
            1 if r.get("thin") else 0,                # non-thin before thin
            1 if r["event_study_available"] else 0,   # missing-readout first
            -r["event_id"],                           # higher event_id first
        )

    removable = sorted(
        [r for r in library if r["role"] == "newly_proposed"], key=remove_key
    )
    to_remove: set = set()
    n = len(library)
    for r in removable:
        if n <= target:
            break
        if fam_count[r["family"]] <= 1:
            continue  # preserve family coverage
        to_remove.add((r["family"], r["event_id"]))
        fam_count[r["family"]] -= 1
        n -= 1
    return [r for r in library if (r["family"], r["event_id"]) not in to_remove]


def select_expansion(
    family_pools: dict,
    *,
    n1_ids: Sequence[int],
    family_order: Sequence[str],
    per_family_cap: int = PER_FAMILY_CAP,
    thin_floor: int = THIN_FLOOR,
    global_target: int = GLOBAL_TARGET,
) -> dict:
    """Deterministic per-family selection + global trim. Pure."""
    n1 = set(n1_ids or [])
    library: list[dict] = []
    per_family: dict[str, dict] = {}

    for fam in family_order:
        pool = family_pools.get(fam)
        if not pool:
            continue
        anchors = sorted([r for r in pool if r["event_id"] in n1],
                         key=lambda r: r["event_id"])
        non_anchor = [r for r in pool if r["event_id"] not in n1]
        slots = max(0, per_family_cap - len(anchors))
        new = select_family_new(non_anchor, slots)
        thin = len(pool) <= thin_floor
        for a in anchors:
            library.append({**a, "family": fam, "role": "already_covered_anchor",
                            "thin": thin})
        for j, nrow in enumerate(new):
            library.append({**nrow, "family": fam, "role": "newly_proposed",
                            "thin": thin, "rank_in_family": j})
        per_family[fam] = {
            "anchor_ids": [a["event_id"] for a in anchors],
            "new_ids": [r["event_id"] for r in new],
            "thin": thin,
            "pool_size": len(pool),
            "library_count": len(anchors) + len(new),
        }

    library = _global_trim(library, target=global_target)

    for fam in per_family:
        kept_new = [r["event_id"] for r in library
                    if r["family"] == fam and r["role"] == "newly_proposed"]
        per_family[fam]["new_ids"] = sorted(kept_new)
        per_family[fam]["library_count"] = sum(
            1 for r in library if r["family"] == fam
        )

    selected = sorted(library, key=lambda r: (r["family"], r["event_id"]))
    already = sorted(r["event_id"] for r in library
                     if r["role"] == "already_covered_anchor")
    newly = sorted(r["event_id"] for r in library if r["role"] == "newly_proposed")
    outcomes_present = sorted({r["outcome"] for r in library})

    summary = {
        "total_proposed": len(library),
        "count_already_in_n1": len(already),
        "count_newly_proposed": len(newly),
        "already_covered_ids": already,
        "newly_proposed_ids": newly,
        "families_represented": sorted({r["family"] for r in library}),
        "outcomes_present": outcomes_present,
        "has_contradiction": "contradicted" in outcomes_present,
        "has_unresolved": "unresolved" in outcomes_present,
        "es_available_count": sum(1 for r in library if r["event_study_available"]),
        "es_missing_count": sum(1 for r in library if not r["event_study_available"]),
    }
    return {
        "selected": selected,
        "per_family": per_family,
        "already_covered_ids": already,
        "newly_proposed_ids": newly,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Read-only DB wiring
# ---------------------------------------------------------------------------

def _edq_labels(path: str | None) -> dict[int, str]:
    """Best-effort per-event date-quality anchor label from the tested
    event-date-quality report. Returns {} if unavailable."""
    try:
        from scripts.event_date_quality_report import build_report as edq_build_report
        edq = edq_build_report(db_path=path, lens="all", limit=0)
    except Exception:
        return {}
    out: dict[int, str] = {}

    for ev in edq.get("events", []) if isinstance(edq, dict) else []:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("event_id")
        label = ev.get("event_date_quality")
        if isinstance(eid, int) and isinstance(label, str) and eid not in out:
            out[eid] = label
    return out


def _build_pools(path: str | None) -> tuple[dict, int, int]:
    """Group the canonical accepted thesis rows into single-match family pools,
    scored by the canonical rule. Read-only (reuses E1's loader)."""
    enriched, es_count, es_total = _enrich_records(path)
    pools: dict[str, list[dict]] = {}
    for r in enriched:
        matched = classify_headline(r["headline"])
        if len(matched) != 1:
            continue  # multi-match / unclassified are surfaced as counts, not selected
        fam = matched[0]
        pools.setdefault(fam, []).append({
            "event_id": r["event_id"],
            "headline": r["headline"],
            "event_date": r["event_date"],
            "symbols": r["symbols"],
            "outcome": score_event_under_rule(r["tickers"], SCORING_RULE),
            "event_study_available": r["event_study_available"],
        })
    return pools, es_count, es_total


def _representative_reason(row: dict, *, overlay_only: bool) -> str:
    fam = row["family"]
    oc = row["outcome"]
    if row["role"] == "already_covered_anchor":
        return f"N1 baseline anchor for {fam} ({_OUTCOME_LABEL.get(oc, oc)})"
    base = _OUTCOME_LABEL.get(oc, oc)
    reason = f"{base} example in {fam}"
    if overlay_only:
        reason += " (overlay-only bucket)"
    if row.get("thin"):
        reason += " (thin family)"
    return reason


def _case_caveats(row: dict, *, date_quality: str | None) -> list[str]:
    caveats: list[str] = []
    if not row["event_study_available"]:
        caveats.append("missing event-study readout")
    if row.get("thin"):
        caveats.append("low-n / thin family")
    if row["outcome"] in ("unresolved", "contradicted"):
        caveats.append("non-supporting outcome (falsifier / unresolved)")
    if date_quality and date_quality not in ("clean", "clean_filing", "clean_discrete_anchor"):
        caveats.append(f"event-date anchor: {date_quality}")
    return caveats


def build_report(*, db_path: str | None = None) -> dict:
    """Build the expansion report from the live archive. Read-only end to end."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    inv = build_inventory(db_path=path)
    denom = inv["denominators"]
    g = inv["global_summary"]

    e1_order = [f["family"] for f in inv["families"]]
    overlay_by_family = {f["family"]: (not f["canonical_family"]) for f in inv["families"]}
    family_coverage = [
        {
            "family": f["family"],
            "accepted_n": f["accepted_thesis_count"],
            "support": f["outcomes"]["validated"],
            "contradiction": f["outcomes"]["contradicted"],
            "unresolved": f["outcomes"]["unresolved"],
            "event_study_available": f["event_study_available"]["available"],
            "event_study_of": f["event_study_available"]["of_family_thesis"],
            "overlay_only": not f["canonical_family"],
            "thin": f["accepted_thesis_count"] <= THIN_FLOOR,
        }
        for f in inv["families"]
    ]

    pools, _es_count, _es_total = _build_pools(path)
    edq_map = _edq_labels(path)

    sel = select_expansion(
        pools, n1_ids=N1_BASELINE_IDS, family_order=e1_order,
        per_family_cap=PER_FAMILY_CAP, thin_floor=THIN_FLOOR,
        global_target=GLOBAL_TARGET,
    )

    selected_cases = []
    for row in sel["selected"]:
        overlay = overlay_by_family.get(row["family"], False)
        dq = edq_map.get(row["event_id"])
        selected_cases.append({
            "event_id": row["event_id"],
            "headline": (row.get("headline") or "")[:90],
            "event_date": row.get("event_date"),
            "family": row["family"],
            "outcome": row["outcome"],
            "event_study_available": row["event_study_available"],
            "role": row["role"],
            "assets": list(row.get("symbols") or [])[:6],
            "representative_reason": _representative_reason(row, overlay_only=overlay),
            "event_date_quality": dq,
            "caveats": _case_caveats(row, date_quality=dq),
            "non_claim": "illustrative case, not evidence or family-level inference",
        })

    # per-family coverage + why-selected, joined with selection counts
    coverage_with_selection = []
    for fc in family_coverage:
        fam = fc["family"]
        pf = sel["per_family"].get(fam, {})
        n1_in_family = sorted(set(N1_BASELINE_IDS) & {c["event_id"] for c in selected_cases
                                                       if c["family"] == fam})
        selected_new = len(pf.get("new_ids", []))
        coverage_with_selection.append({
            **fc,
            "n1_covered": bool(n1_in_family),
            "n1_anchor_ids": n1_in_family,
            "selected_new_count": selected_new,
            "library_count": pf.get("library_count", 0),
            "why": (
                f"thin family (n={fc['accepted_n']} <= {THIN_FLOOR}); "
                "selected up to the cap, unresolved kept"
                if fc["thin"] else
                f"capped at {PER_FAMILY_CAP} per family (anchor + new)"
            ),
        })

    # baseline N1 coverage from the pools (family + outcome per anchor)
    anchor_lookup = {}
    for fam, rows in pools.items():
        for r in rows:
            if r["event_id"] in N1_BASELINE_IDS:
                anchor_lookup[r["event_id"]] = (fam, r["outcome"])
    baseline_covers = [
        {"event_id": i,
         "family": anchor_lookup.get(i, (None, None))[0],
         "outcome": anchor_lookup.get(i, (None, None))[1]}
        for i in N1_BASELINE_IDS
    ]

    summary = {
        **sel["summary"],
        "family_diversity": len(sel["summary"]["families_represented"]),
        "outcome_diversity": len(sel["summary"]["outcomes_present"]),
        "event_study_coverage": (
            f"{sel['summary']['es_available_count']} of "
            f"{sel['summary']['total_proposed']} selected have a readout"
        ),
        "multi_match_count": g["multi_match_count"],
        "unclassified_count": g["unclassified_count"],
    }

    return {
        "denominators": denom,
        "baseline_n1": {
            "ids": list(N1_BASELINE_IDS),
            "covers": baseline_covers,
            "limitation": (
                "N1 cases are illustrative anchors only, not representative "
                "evidence; this expansion broadens family and outcome coverage "
                "around them, and never rewrites the N1 walkthrough."
            ),
        },
        "selection_policy": (
            f"Per family: anchors + new, capped at {PER_FAMILY_CAP} (incl. N1 "
            "anchors). New picks: support -> contradiction -> unresolved, then "
            "by (event-study-available, lowest event_id). Thin families (n <= "
            f"{THIN_FLOOR}) keep unresolved. Global target {GLOBAL_TARGET} "
            f"(max {GLOBAL_MAX}); trim new picks only, never anchors and never a "
            "family's last entry. The trim removes duplicate same-outcome extras "
            "first and protects one support example for each material (non-thin) "
            "family, so the largest family keeps a support case; contradiction / "
            "unresolved examples are protected above duplicates. Within a tier: "
            "non-thin before thin, missing-readout before event-study-available, "
            "higher event_id before lower."
        ),
        "family_coverage": coverage_with_selection,
        "selected": selected_cases,
        "summary": summary,
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/representative_case_expansion_report.py "
            "--db-path events.db --json"
        ),
    }


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------

def render_text(report: dict) -> str:
    """ASCII / cp1252-safe text rendering."""
    d = report["denominators"]
    s = report["summary"]
    lines: list[str] = []
    lines.append("Representative case expansion (read-only)")
    lines.append("=" * 42)
    lines.append("")
    lines.append(
        f"Denominators: archive {d.get('archive_rows')} / coverage "
        f"{d.get('accepted_coverage_denominator')} / track-record "
        f"{d.get('accepted_track_record_denominator')} / event-study "
        f"{d.get('event_study_available_count')}/"
        f"{d.get('event_study_coverage_denominator')} / staged "
        f"{d.get('staged_candidates')} (excluded)"
    )
    lines.append("")
    lines.append(
        f"Proposed library: {s['total_proposed']} cases "
        f"({s['count_already_in_n1']} N1 anchors + {s['count_newly_proposed']} new); "
        f"families {s['family_diversity']}; outcomes {s['outcome_diversity']}; "
        f"{s['event_study_coverage']}"
    )
    lines.append("")
    lines.append("Family coverage:")
    for fc in report["family_coverage"]:
        marks = []
        if fc["overlay_only"]:
            marks.append("overlay-only")
        if fc["thin"]:
            marks.append("thin")
        mark = (" [" + ", ".join(marks) + "]") if marks else ""
        lines.append(
            f"  {fc['family']:<32}{mark} n={fc['accepted_n']:<3} "
            f"S/C/U={fc['support']}/{fc['contradiction']}/{fc['unresolved']} "
            f"ES={fc['event_study_available']}/{fc['event_study_of']} "
            f"library={fc['library_count']} (anchor {fc['n1_anchor_ids']}, "
            f"+{fc['selected_new_count']} new)"
        )
    lines.append("")
    lines.append("Selected cases:")
    for c in report["selected"]:
        tag = "anchor" if c["role"] == "already_covered_anchor" else "new"
        es = "ES" if c["event_study_available"] else "no-ES"
        lines.append(
            f"  [{tag:<6}] {c['event_id']:<4} {c['family']:<30} "
            f"{c['outcome']:<12} {es:<5} {c['event_date']}  - {c['representative_reason']}"
        )
        if c["caveats"]:
            lines.append(f"           caveats: {'; '.join(c['caveats'])}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in report["non_claims"]:
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(f"Reproduce: {report['reproduce_command']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only representative-case expansion report.",
    )
    parser.add_argument("--db-path", default=None,
                        help="path to events.db (default: db.DB_FILE)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout

    report = build_report(db_path=args.db_path)
    if args.json:
        json.dump(report, stream, indent=2)  # ensure_ascii=True -> cp1252-safe
        stream.write("\n")
    else:
        stream.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

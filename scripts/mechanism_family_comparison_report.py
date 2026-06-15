#!/usr/bin/env python3
"""Read-only mechanism-family comparison report (I1).

Lets a skeptical reviewer compare the accepted mechanism families side by side:
for each family, the accepted track-record n, the support / contradiction /
unresolved counts, event-study coverage, taxonomy status (canonical /
overlay-only / thin), the selected representative case ids, and their H1 readout
coverage. It answers "what descriptive patterns are visible, and where are the
denominators too thin / overlay-only / incomplete to say anything beyond a
descriptive archive read."

It is a descriptive read only: not a model, not inference, not p-values, not
FDR, and not a new score. It introduces no new threshold beyond the
already-established thin-family flag, and it ranks nothing and asserts no family
ordering. It REUSES and recomputes nothing:
  * E1 (`mechanism_family_evidence_inventory.build_inventory`) for the family
    counts, the canonical-vs-overlay flag, the sum-invariant, and denominators;
  * H1 (`case_library_reaction_matrix.build_report`) for per-family selected case
    ids and their readout availability;
  * F1's `THIN_FLOOR` for the thin-family flag (no new threshold).

Lens discipline: outcome counts are thesis-direction scoring; readouts are the
primary ticker vs SPY; representative cases are walkthrough material. These are
different lenses and are never collapsed into one success metric.

Read-only throughout (mode=ro via reused helpers); no DB / price_cache write,
no paid call, no /analyze, no fetch.

Usage::

    python scripts/mechanism_family_comparison_report.py --db-path events.db --json
    python scripts/mechanism_family_comparison_report.py --db-path events.db
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

import db  # noqa: E402
from scripts.case_library_reaction_matrix import build_report as h1_build_report  # noqa: E402
from scripts.mechanism_family_evidence_inventory import build_inventory  # noqa: E402
from scripts.representative_case_expansion_report import THIN_FLOOR  # noqa: E402

LENS_DISCIPLINE = {
    "outcome_lens": (
        "Outcome counts are thesis-direction scoring of the named tickers "
        "(support / contradiction / unresolved)."
    ),
    "readout_lens": (
        "Readouts are the primary ticker's abnormal return vs SPY (the H1 "
        "reaction matrix), a different lens from the outcome."
    ),
    "representative_cases": (
        "Representative cases are walkthrough material, not a family verdict."
    ),
    "do_not_collapse": (
        "These are different lenses; do not collapse them into one success "
        "metric."
    ),
}

NON_CLAIMS: tuple[str, ...] = (
    "Descriptive archive read only; this comparison adds no new claim and no new "
    "score.",
    "No family-level inference; counts and coverage are descriptive - a visible "
    "pattern is not inference.",
    "No statistical-significance claim; no CI, p-value, or FDR, and the "
    "descriptive archive is not merged with the closed Phase 1 / Phase 2 FDR "
    "pools.",
    "No family is ranked above another; this is a side-by-side descriptive read, "
    "not a contest.",
    "Not a recommendation, forecast, or trading signal.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record; "
    "staged candidates (13) are excluded.",
)


# ---------------------------------------------------------------------------
# Pure comparison core
# ---------------------------------------------------------------------------

def build_family_comparison(
    families: Sequence[dict],
    matrix_rows: Sequence[dict],
    *,
    thin_floor: int = THIN_FLOOR,
) -> list[dict]:
    """One comparison row per family (E1 family dicts + H1 matrix rows). Pure."""
    by_fam: dict[str, list[dict]] = {}
    for r in matrix_rows:
        by_fam.setdefault(r.get("family"), []).append(r)

    rows: list[dict] = []
    for f in families:
        fam = f["family"]
        n = f["accepted_thesis_count"]
        oc = f["outcomes"]
        s, c, u = oc["validated"], oc["contradicted"], oc["unresolved"]
        es = f["event_study_available"]
        esa, eso = es["available"], es["of_family_thesis"]
        canonical = bool(f["canonical_family"])
        overlay = not canonical
        thin = n <= thin_floor
        rate = round(esa / eso, 2) if eso else 0.0
        coverage = "complete" if (eso and esa == eso) else "partial"
        unresolved_heavy = n > 0 and u >= (s + c)
        contradiction_present = c > 0

        sel = by_fam.get(fam, [])
        sel_ids = [x["event_id"] for x in sel]
        sel_avail = sum(1 for x in sel if x["readout"]["available"])
        sel_missing = [x["event_id"] for x in sel if not x["readout"]["available"]]

        status_flags = (["canonical"] if canonical else ["overlay-only"])
        if thin:
            status_flags.append("thin family")

        caveats: list[str] = []
        if thin:
            caveats.append(f"low-n / thin family (n <= {thin_floor})")
        if overlay:
            caveats.append("overlay-only bucket (outside the canonical taxonomy)")
        if unresolved_heavy:
            caveats.append("unresolved-heavy")
        if contradiction_present:
            caveats.append("contradiction present")
        if sel_missing:
            caveats.append(
                f"missing event-study readouts in selected cases: {sel_missing}"
            )
        caveats.append("representative cases are illustrative only")

        rows.append({
            "family": fam,
            "n": n,
            "support": s,
            "contradiction": c,
            "unresolved": u,
            "event_study_available": esa,
            "event_study_of": eso,
            "event_study_rate": rate,
            "event_study_coverage": coverage,
            "canonical": canonical,
            "overlay_only": overlay,
            "thin": thin,
            "status_flags": status_flags,
            "unresolved_heavy": unresolved_heavy,
            "contradiction_present": contradiction_present,
            "selected_case_ids": sel_ids,
            "selected_readout_available": sel_avail,
            "selected_missing_ids": sel_missing,
            "caveats": caveats,
        })
    return rows


# ---------------------------------------------------------------------------
# Read-only DB wiring
# ---------------------------------------------------------------------------

def build_report(*, db_path: str | None = None) -> dict:
    """Build the family comparison from the live archive. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    inv = build_inventory(db_path=path)
    h1 = h1_build_report(db_path=path)
    rows = build_family_comparison(inv["families"], h1["matrix"], thin_floor=THIN_FLOOR)

    g = inv["global_summary"]
    miss = h1["missingness_summary"]
    case_library = {
        "total_selected": len(h1["matrix"]),
        "readout_available": miss["readout_available_count"],
        "missing_ids": miss["missing_ids"],
    }
    comparison_notes = {
        "enough_mass_to_inspect_descriptively":
            [r["family"] for r in rows if not r["thin"]],
        "thin_families": [r["family"] for r in rows if r["thin"]],
        "overlay_only_families": [r["family"] for r in rows if r["overlay_only"]],
        "unresolved_heavy_families":
            [r["family"] for r in rows if r["unresolved_heavy"]],
        "families_with_contradiction":
            [r["family"] for r in rows if r["contradiction_present"]],
        "families_with_blocking_missingness":
            [r["family"] for r in rows if r["selected_missing_ids"]],
        "note": (
            "A larger accepted-family bucket is only more inspectable "
            "descriptively; a visible pattern is not inference."
        ),
    }

    return {
        "purpose": (
            "Side-by-side descriptive comparison of the accepted mechanism "
            "families; no new score, no ranking, no inference."
        ),
        "denominators": inv["denominators"],
        "family_comparison": rows,
        "global_summary": {
            "n_families": len(rows),
            "sum_invariant": g["sum_invariant"],
            "multi_match_count": g["multi_match_count"],
            "unclassified_count": g["unclassified_count"],
            "case_library": case_library,
        },
        "comparison_notes": comparison_notes,
        "lens_discipline": LENS_DISCIPLINE,
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/mechanism_family_comparison_report.py "
            "--db-path events.db --json"
        ),
    }


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------

def render_text(report: dict) -> str:
    d = report.get("denominators", {})
    g = report.get("global_summary", {})
    lines: list[str] = []
    lines.append("Mechanism-family comparison (read-only)")
    lines.append("=" * 39)
    lines.append("")
    lines.append(
        f"Denominators: archive {d.get('archive_rows')} / coverage "
        f"{d.get('accepted_coverage_denominator')} / track-record "
        f"{d.get('accepted_track_record_denominator')} / event-study "
        f"{d.get('event_study_available_count')}/"
        f"{d.get('event_study_coverage_denominator')} / staged "
        f"{d.get('staged_candidates')} (excluded)"
    )
    si = g.get("sum_invariant", {})
    lines.append(
        f"Headline overlay: single {si.get('single_match_total')} + multi "
        f"{si.get('multi_match')} + unclassified {si.get('unclassified')} = "
        f"{si.get('sum')}"
    )
    cl = g.get("case_library", {})
    lines.append(
        f"Case library: {cl.get('total_selected')} selected, "
        f"{cl.get('readout_available')} with a readout, missing "
        f"{cl.get('missing_ids')}"
    )
    lines.append("")
    lines.append("Family comparison:")
    for r in report.get("family_comparison", []):
        flags = ", ".join(r["status_flags"])
        lines.append(
            f"  {r['family']:<32} n={r['n']:<3} "
            f"S/C/U={r['support']}/{r['contradiction']}/{r['unresolved']} "
            f"ES={r['event_study_available']}/{r['event_study_of']} "
            f"({r['event_study_coverage']}) [{flags}]"
        )
        lines.append(
            f"        selected={r['selected_case_ids']} "
            f"readouts {r['selected_readout_available']}/"
            f"{len(r['selected_case_ids'])}"
            + (f" missing {r['selected_missing_ids']}" if r["selected_missing_ids"] else "")
        )
        if r["caveats"]:
            lines.append(f"        caveats: {'; '.join(r['caveats'])}")
    lines.append("")
    cn = report.get("comparison_notes", {})
    lines.append("Comparison notes:")
    lines.append(f"  enough mass to inspect descriptively: {cn.get('enough_mass_to_inspect_descriptively')}")
    lines.append(f"  thin families: {cn.get('thin_families')}")
    lines.append(f"  overlay-only families: {cn.get('overlay_only_families')}")
    lines.append(f"  unresolved-heavy: {cn.get('unresolved_heavy_families')}")
    lines.append(f"  contradiction present: {cn.get('families_with_contradiction')}")
    lines.append(f"  missingness blocks interpretation: {cn.get('families_with_blocking_missingness')}")
    lines.append("")
    lines.append("Lens discipline:")
    for k in ("outcome_lens", "readout_lens", "representative_cases", "do_not_collapse"):
        lines.append(f"  - {report['lens_discipline'][k]}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in report.get("non_claims", []):
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(f"Reproduce: {report.get('reproduce_command')}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only mechanism-family comparison report.",
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

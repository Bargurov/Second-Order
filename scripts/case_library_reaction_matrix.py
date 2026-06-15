#!/usr/bin/env python3
"""Read-only market-reaction matrix for the 15-case representative library (H1).

One compact, finance-readable row per representative case:
case -> role -> family -> outcome -> event-study availability -> primary ticker
-> 1d / 5d / 20d SPY-relative readout -> caveats -> non-claim.

Descriptive readout surface only: no model, no inference, no p-values, no FDR,
no thresholds, no trading language. It REUSES the existing layers and recomputes
nothing:
  * F1 (`representative_case_expansion_report.build_report`) for the 15 selected
    cases' identity, role, family, outcome, event-study availability, caveats,
    and event-date quality;
  * F2 (`expanded_case_notes_report._readout_by_id` / `_readout_block`) for the
    per-horizon SPY-relative readout and its lens label.

Lens discipline (carried from F2, one level up to the whole library): the
readout is the primary ticker's abnormal return vs SPY; the outcome is
thesis-direction scoring of the named tickers. These can disagree - cases 29
and 38 share an identical XLE-vs-SPY readout on the same date yet carry opposite
outcomes. Readout shown as AR% / SAR / CAR% (SAR is a ratio, not a percent).

Read-only throughout (mode=ro via reused helpers); no DB / price_cache write,
no paid call, no /analyze, no fetch.

Usage::

    python scripts/case_library_reaction_matrix.py --db-path events.db --json
    python scripts/case_library_reaction_matrix.py --db-path events.db
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
from scripts.expanded_case_notes_report import (  # noqa: E402
    _readout_block,
    _readout_by_id,
)
from scripts.representative_case_expansion_report import (  # noqa: E402
    build_report as f1_build_report,
)

ANCHOR_IDS: tuple[int, ...] = (1, 46, 61, 66, 210, 211)
NEW_IDS: tuple[int, ...] = (7, 29, 38, 71, 153, 154, 160, 212, 239)
ALL_IDS: tuple[int, ...] = ANCHOR_IDS + NEW_IDS

_OUTCOME_MAP = {
    "validated": "support", "support": "support",
    "contradicted": "contradiction", "contradiction": "contradiction",
    "unresolved": "unresolved",
}

NON_CLAIM = (
    "Descriptive case-library readout only - not evidence, no family-level "
    "inference, not a recommendation, forecast, or trading signal."
)

NON_CLAIMS: tuple[str, ...] = (
    "Descriptive case-library readout only; this matrix adds no new claim.",
    "No family-level inference; outcome labels are the canonical any_support "
    "vocabulary applied per event, descriptively.",
    "No pooled significance: no CI, p-value, FDR, or threshold is computed or "
    "implied.",
    "Readout is the primary ticker's abnormal return vs SPY over the window - a "
    "different lens from the outcome, not a significance claim.",
    "Not a recommendation of any kind, and no forecast.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record; "
    "staged candidates (13) are excluded.",
)

LENS_WARNING = {
    "readout_lens": (
        "Readout lens = the primary ticker's abnormal return vs SPY over the "
        "event window (AR% / SAR / CAR%)."
    ),
    "outcome_lens": (
        "Outcome lens = thesis-direction scoring of the named tickers "
        "(support / contradiction / unresolved)."
    ),
    "can_disagree": (
        "These two lenses can disagree; readout availability is not the same as "
        "thesis support."
    ),
    "example_29_38": (
        "Cases 29 and 38 are the canonical example: same XLE-vs-SPY readout on "
        "the same date, opposite outcomes (29 contradiction, 38 support)."
    ),
}


# ---------------------------------------------------------------------------
# Pure assembly
# ---------------------------------------------------------------------------

def build_matrix(
    cases: Sequence[dict],
    *,
    readout_by_id: dict,
    overlay_families: set | frozenset = frozenset(),
) -> list[dict]:
    """Assemble one reaction row per case, ordered by ALL_IDS. Pure.

    ``overlay_families`` are the family names that sit outside the canonical
    stored taxonomy (from F1's per-family ``overlay_only`` flag); rows in those
    families get an ``overlay-only bucket`` caveat.
    """
    overlay_families = set(overlay_families or ())
    order = {eid: i for i, eid in enumerate(ALL_IDS)}
    selected = sorted(
        [c for c in cases if c.get("event_id") in order],
        key=lambda c: order[c["event_id"]],
    )

    # Shared event-study primary + date clusters (readout-available rows only).
    key_by_id: dict[int, tuple] = {}
    counts: dict[tuple, int] = {}
    for c in selected:
        entry = readout_by_id.get(c["event_id"])
        if entry and entry.get("per_horizon"):
            k = (entry.get("primary_ticker"), c.get("event_date"))
            key_by_id[c["event_id"]] = k
            counts[k] = counts.get(k, 0) + 1

    rows: list[dict] = []
    for c in selected:
        eid = c["event_id"]
        readout = _readout_block(readout_by_id.get(eid))
        caveats = list(c.get("caveats") or [])
        if c.get("family") in overlay_families:
            caveats.append("overlay-only bucket")
        k = key_by_id.get(eid)
        if k is not None and counts.get(k, 0) >= 2:
            caveats.append(
                f"shared event-study primary/date cluster ({k[0]} on {k[1]})"
            )
        rows.append({
            "event_id": eid,
            "role": "anchor" if c.get("role") == "already_covered_anchor" else "new",
            "headline": c.get("headline"),
            "event_date": c.get("event_date"),
            "family": c.get("family"),
            "outcome": _OUTCOME_MAP.get(c.get("outcome"), c.get("outcome")),
            "event_study_available": bool(c.get("event_study_available")),
            "primary_ticker": readout.get("primary_ticker") if readout["available"] else None,
            "benchmark": readout.get("benchmark") if readout["available"] else None,
            "readout": readout,
            "caveats": caveats,
            "event_date_quality": c.get("event_date_quality"),
            "non_claim": NON_CLAIM,
        })
    return rows


# ---------------------------------------------------------------------------
# Read-only DB wiring
# ---------------------------------------------------------------------------

def build_report(*, db_path: str | None = None) -> dict:
    """Build the reaction-matrix report from the live archive. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    f1 = f1_build_report(db_path=path)
    cases = f1["selected"]
    readout_by_id = _readout_by_id(path, ALL_IDS)
    overlay_families = {
        f["family"] for f in f1.get("family_coverage", []) if f.get("overlay_only")
    }
    matrix = build_matrix(
        cases, readout_by_id=readout_by_id, overlay_families=overlay_families
    )

    missing_ids = sorted(r["event_id"] for r in matrix if not r["readout"]["available"])
    available = sum(1 for r in matrix if r["readout"]["available"])

    return {
        "purpose": (
            "Descriptive market-reaction matrix over the 15 representative cases "
            "(6 N1 anchors + 9 newly proposed); readout and outcome are separate "
            "lenses."
        ),
        "denominators": f1["denominators"],
        "selected_ids": {"anchors": list(ANCHOR_IDS), "new": list(NEW_IDS)},
        "matrix": matrix,
        "missingness_summary": {
            "readout_available_count": available,
            "readout_missing_count": len(missing_ids),
            "missing_ids": missing_ids,
        },
        "lens_warning": LENS_WARNING,
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/case_library_reaction_matrix.py --db-path events.db --json"
        ),
    }


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------

def _cp1252(s: Any) -> str:
    text = "" if s is None else str(s)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _readout_cell(rd: dict) -> str:
    if not rd["available"]:
        return "unavailable"
    hz = rd["horizons"]

    def _h(k: str) -> str:
        v = hz.get(k, {})
        return f"AR {v.get('ar_pct')}% / SAR {v.get('sar')} / CAR {v.get('car_pct')}%"

    return f"1d {_h('1d')} | 5d {_h('5d')} | 20d {_h('20d')}"


def render_text(report: dict) -> str:
    d = report.get("denominators", {})
    ms = report.get("missingness_summary", {})
    lines: list[str] = []
    lines.append("Case-library market reaction matrix (read-only)")
    lines.append("=" * 47)
    lines.append("")
    lines.append(
        f"Denominators: archive {d.get('archive_rows')} / coverage "
        f"{d.get('accepted_coverage_denominator')} / track-record "
        f"{d.get('accepted_track_record_denominator')} / event-study "
        f"{d.get('event_study_available_count')}/"
        f"{d.get('event_study_coverage_denominator')} / staged "
        f"{d.get('staged_candidates')} (excluded)"
    )
    sel = report.get("selected_ids", {})
    lines.append(f"Anchors: {sel.get('anchors')}")
    lines.append(f"New: {sel.get('new')}")
    lines.append("")
    lines.append("Reaction matrix (SPY-relative; SAR is a ratio, not a percent):")
    for r in report.get("matrix", []):
        lines.append(
            f"  #{r['event_id']:<4} {r['role']:<6} {r['family']:<30} "
            f"{r['outcome']:<12} ES={'yes' if r['event_study_available'] else 'no':<3} "
            f"primary={r['primary_ticker'] or '-'}  {_cp1252(r['headline'])[:50]}"
        )
        lines.append(f"        readout: {_readout_cell(r['readout'])}")
        if r["caveats"]:
            lines.append(f"        caveats: {'; '.join(_cp1252(c) for c in r['caveats'])}")
        lines.append(f"        anchor: {r['event_date']} ({r['event_date_quality']})")
    lines.append("")
    lines.append(
        f"Missingness: {ms.get('readout_available_count')} readouts available, "
        f"{ms.get('readout_missing_count')} missing ({ms.get('missing_ids')})."
    )
    lines.append("")
    lines.append("Lens warning:")
    for k in ("readout_lens", "outcome_lens", "can_disagree", "example_29_38"):
        lines.append(f"  - {report['lens_warning'][k]}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in report.get("non_claims", []):
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(f"Reproduce: {report.get('reproduce_command')}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only market-reaction matrix for the 15-case library.",
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

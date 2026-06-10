#!/usr/bin/env python3
"""Read-only sanction/export-control thread-collapse report (307-310).

Four staged sanction rows look like family breadth; the C4 layer says they
are continuations of an existing US-China semiconductor export-control
thread anchored by curated observations (298 Huawei, 300 NVIDIA license,
301 SMIC). This report makes the collapse explicit so raw row count can
never masquerade as independent evidence: it derives sibling links from the
C4 layer at run time, groups staged rows and their anchors into connected
thread components, and reports the honest accounting - raw staged rows vs
staged rows that add an independent event (today: zero).

Discipline: everything stays staged/no-paid; thread membership is derived,
never hardcoded (a staged row that stops reading as a sibling is surfaced as
a potential independent event instead); readouts are descriptive n=1 AND
thread-caveated - the NVDA cases share overlapping windows on one ticker.
Read-only throughout.

Usage::

    python scripts/sanction_thread_collapse_report.py --db-path events.db --json
    python scripts/sanction_thread_collapse_report.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - DB_FILE seam for the event-study gate
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

FAMILY = "sanction"
THREAD_NAME = "sanction / US-China semiconductor export-control thread"

# Curated context anchors that belong to the thread by reviewed judgment
# (AX1) even when no mechanical C4 link fires - labeled as such, never
# presented as a mechanical match.
THREAD_CONTEXT_ANCHORS: tuple[int, ...] = (301,)

CASE_REGISTRY: dict[int, dict[str, str]] = {
    307: {
        "policy_subtype": "advanced_computing_export_controls (industry-wide rule)",
        "why_this_may_be_thread_sibling": (
            "Broad October-2022 rule arriving 37 days after the curated "
            "NVIDIA license requirement (300) - same thread, instrument "
            "widened from one name to the industry."
        ),
        "what_new_information_if_any": (
            "Breadth of instrument: industry-wide controls and a second "
            "exposed name (AMD) - thread evolution, not a new thread."
        ),
    },
    308: {
        "policy_subtype": "export_control_tightening (equipment scope)",
        "why_this_may_be_thread_sibling": (
            "Explicit strengthening of the 2022 rule (307/300 thread), one "
            "year on; adds the equipment leg (AMAT) the curated SMIC anchor "
            "(301) already represents."
        ),
        "what_new_information_if_any": (
            "Scope detail on equipment controls - the least new information "
            "in the cluster."
        ),
    },
    309: {
        "policy_subtype": "foreign_direct_product_rule (Huawei thread)",
        "why_this_may_be_thread_sibling": (
            "Extends the curated 2019 Huawei Entity-List action (298) via "
            "the FDPR - same target, new instrument detail."
        ),
        "what_new_information_if_any": (
            "Instrument detail (FDPR reach over foreign-made chips) and a "
            "different exposed name (QCOM) within the same Huawei thread."
        ),
    },
    310: {
        "policy_subtype": "license_requirement_disclosure (company 8-K)",
        "why_this_may_be_thread_sibling": (
            "A 2025 echo of the curated 2022 NVIDIA license pattern (300): "
            "same company, same instrument, new chip generation."
        ),
        "what_new_information_if_any": (
            "A quantified impact disclosure (company-estimated charge) - "
            "useful magnitude context inside the thread, not a new thread."
        ),
    },
}

_UNKNOWN_CASE = {
    "policy_subtype": "other_or_manual_review",
    "why_this_may_be_thread_sibling": (
        "Unreviewed sanction row - assess thread membership before use."
    ),
    "what_new_information_if_any": "Manual review required.",
}

THREAD_INTERPRETATION: dict[str, str] = {
    "what_can_be_read": (
        "Descriptive thread-evolution context: how the same policy thread "
        "escalated across instruments and dates - with every window read "
        "as n=1 AND thread-caveated (three of four cases share NVDA, so "
        "their windows overlap on one ticker's tape)."
    ),
    "what_cannot_be_read": (
        "Independent confirmations: four staged rows cannot be counted as "
        "four pieces of evidence for an export-control mechanism - they are "
        "correlated observations of one evolving thread."
    ),
    "why_raw_row_count_overstates_breadth": (
        "Same thread, shared tickers, and overlapping event windows mean "
        "the rows co-move by construction; treating them as independent "
        "would multiply one observation into four."
    ),
    "how_to_treat_307_310_in_future_packets": (
        "Collapse to thread level: at most one observation per thread "
        "component, anchored at the curated root (298 or 300), with the "
        "staged rows as dated escalation context - never as separate "
        "evidence rows."
    ),
}

NEXT_NO_PAID_MOVES: tuple[str, ...] = (
    "Collapse/defer 307-310 as thread context; do not count them toward "
    "family breadth in any packet or board.",
    "Only build a sanction/export-control family packet after independent "
    "anchors are separated from the thread (none exist among the staged "
    "rows today).",
    "No paid call: thread-dense staged rows justify no paid analysis.",
)

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "Thread siblings are not independent breadth - the raw row count is "
    "explicitly NOT an evidence count.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "Thread grouping supports no family-level inference and no "
    "recommendation of any kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _linked_ids(thread_independence: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", thread_independence or "")]


def _exposed_tickers(path: str, event_id: int) -> list[str]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        try:
            row = conn.execute(
                "SELECT market_tickers FROM events WHERE id = ?", (event_id,),
            ).fetchone()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    if not row:
        return []
    try:
        parsed = json.loads(row[0] or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, dict):
                sym = entry.get("symbol")
                if isinstance(sym, str) and sym.strip():
                    out.append(sym.strip().upper())
    return out


def _local_readout(event_id: int, event_date: str, primary: str | None,
                   *, db_path: str) -> dict:
    base = {"available": False, "horizons": [], "descriptive_only": True,
            "n_equals_one": True, "thread_caveated": True}
    try:
        from event_study_validation import (
            STATUS_AVAILABLE,
            build_event_study_validation,
        )
    except Exception:
        return base
    event = {"id": event_id, "event_date": event_date,
             "market_tickers": [{"symbol": primary}] if primary else []}
    saved = db.DB_FILE
    try:
        db.DB_FILE = db_path
        out = build_event_study_validation(event)
    except Exception:
        return base
    finally:
        db.DB_FILE = saved
    if out.get("status") != STATUS_AVAILABLE:
        return base
    horizons = [
        {"horizon": h.get("horizon"), "abnormal_return": h.get("abnormal_return"),
         "sar": h.get("sar"), "car": h.get("car")}
        for h in out.get("per_horizon") or [] if isinstance(h, dict)
    ]
    return {**base, "available": bool(horizons), "horizons": horizons}


def _components(edges: dict[int, list[int]]) -> list[list[int]]:
    """Connected components over an undirected id graph (BFS)."""
    nodes = set(edges)
    for targets in edges.values():
        nodes.update(targets)
    adj: dict[int, set[int]] = {n: set() for n in nodes}
    for a, targets in edges.items():
        for b in targets:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[int] = set()
    comps: list[list[int]] = []
    for start in sorted(nodes):
        if start in seen:
            continue
        comp, queue = [], [start]
        seen.add(start)
        while queue:
            cur = queue.pop()
            comp.append(cur)
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        comps.append(sorted(comp))
    return comps


def _disposition(label: str) -> str:
    if label == "continuation_or_thread_sibling":
        return ("collapse_into_thread_or_defer - thread context, not an "
                "independent case; no paid")
    if label == "duplicate_or_deferred":
        return "deferred_duplicate - resolve before any use; no paid"
    if label in ("clean_discrete_anchor", "partial_anticipation"):
        return ("review_as_potential_independent_event - still staged/"
                "no-paid; verify independence before any packet use")
    return "manual review needed before any use"


# ---------------------------------------------------------------------------
# Report composer
# ---------------------------------------------------------------------------


def build_report(*, db_path: str | None = None, limit: int = 0) -> dict[str, Any]:
    """Build the thread-collapse report. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    by_id = {e["event_id"]: e for e in edq["events"]}
    staged = [e for e in edq["events"]
              if e["mechanism_family"] == FAMILY
              and e["corpus_status"] == "staged"]

    sibling_ids: list[int] = []
    independent_ids: list[int] = []
    edges: dict[int, list[int]] = {}
    mechanical_anchor_ids: set[int] = set()
    cases: list[dict] = []
    for e in sorted(staged, key=lambda x: x["event_id"]):
        spec = CASE_REGISTRY.get(e["event_id"], _UNKNOWN_CASE)
        links = (_linked_ids(e["thread_independence"])
                 if e["event_date_quality"] == "continuation_or_thread_sibling"
                 else [])
        if links:
            sibling_ids.append(e["event_id"])
            edges[e["event_id"]] = links
            mechanical_anchor_ids.update(links)
        else:
            independent_ids.append(e["event_id"])
        exposed = _exposed_tickers(path, e["event_id"])
        primary = exposed[0] if exposed else None

        present = [f"linked thread anchors present locally: {links}"
                   if links else "no mechanical thread link - candidate "
                                 "independent anchor"]
        missing = (["evidence the row moved on its own information, "
                    "separate from the thread it continues"]
                   if links else [])

        cases.append({
            "event_id": e["event_id"],
            "date": e["date"],
            "headline": e["headline"],
            "stage": e["stage"],
            "corpus_status": e["corpus_status"],
            "mechanism_family": FAMILY,
            "policy_subtype": spec["policy_subtype"],
            "primary_ticker": primary,
            "exposed_tickers": exposed,
            "event_date_quality": e["event_date_quality"],
            "anticipation_risk": e["anticipation_risk"],
            "thread_independence": e["thread_independence"],
            "related_anchor_ids": links,
            "local_readout": _local_readout(e["event_id"], e["date"],
                                            primary, db_path=path),
            "why_this_may_be_thread_sibling":
                spec["why_this_may_be_thread_sibling"],
            "what_new_information_if_any":
                spec["what_new_information_if_any"],
            "local_evidence_present": present,
            "local_evidence_missing": missing,
            "disposition": _disposition(e["event_date_quality"]),
        })

    capped = max(int(limit), 0)
    surfaced = cases[:capped] if capped else cases

    # Thread components over staged siblings + their mechanical anchors.
    comps = _components(edges) if edges else []
    effective_threads = sum(
        1 for comp in comps if any(i in set(sibling_ids) for i in comp))

    # Related anchors: mechanical links that resolve to curated/accepted rows
    # in the archive, plus the registry context anchors (labeled).
    related_ids: list[int] = []
    related_rows: list[dict] = []
    for aid in sorted(mechanical_anchor_ids | set(THREAD_CONTEXT_ANCHORS)):
        row = by_id.get(aid)
        if row is None or row["corpus_status"] not in ("accepted", "curated"):
            continue
        related_ids.append(aid)
        related_rows.append({
            "event_id": aid,
            "date": row["date"],
            "stage": row["stage"],
            "corpus_status": row["corpus_status"],
            "headline": row["headline"],
            "event_date_quality": row["event_date_quality"],
            "link_provenance": (
                "mechanical (C4 thread link)" if aid in mechanical_anchor_ids
                else "curated context (reviewed equipment-channel sibling, "
                     "no mechanical link)"
            ),
        })

    edq_denoms = edq["denominators"]
    return {
        "denominators": {
            "archive_rows": edq_denoms["archive_rows"],
            "accepted_coverage_denominator":
                edq_denoms["accepted_coverage_denominator"],
            "accepted_track_record_denominator":
                edq_denoms["accepted_track_record_denominator"],
            "staged_candidate_count": edq_denoms["staged_candidate_count"],
            "sanction_or_export_control_staged_count": len(staged),
            "related_accepted_or_curated_count": len(related_ids),
            "note": (
                "Accepted vs staged stay separated; thread membership "
                "changes no denominator."
            ),
        },
        "thread_scope": {
            "family_or_thread_name": THREAD_NAME,
            "included_staged_ids": sorted(e["event_id"] for e in staged),
            "related_curated_or_accepted_ids": related_ids,
            "likely_thread_sibling_ids": sorted(sibling_ids),
            "independent_event_ids": sorted(independent_ids),
            "collapse_or_defer_ids": sorted(sibling_ids),
        },
        "breadth_accounting": {
            "raw_staged_row_count": len(staged),
            "staged_rows_adding_independent_events": len(independent_ids),
            "effective_thread_count": effective_threads,
            "thread_components": comps,
            "explanation": (
                "Connected components over the C4 thread links: every staged "
                "sibling collapses into a component rooted at a curated "
                "anchor, so the staged rows add thread depth, not "
                "independent events."
            ),
        },
        "cases": surfaced,
        "related_anchor_rows": related_rows,
        "thread_interpretation": dict(THREAD_INTERPRETATION),
        "next_no_paid_moves": list(NEXT_NO_PAID_MOVES),
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(rep: dict[str, Any]) -> str:
    d = rep["denominators"]
    b = rep["breadth_accounting"]
    lines = ["Sanction/export-control thread-collapse report "
             "(read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | thread staged "
        f"{d['sanction_or_export_control_staged_count']} | related anchors "
        f"{d['related_accepted_or_curated_count']}"
    )
    lines.append(
        f"Breadth accounting: raw staged rows {b['raw_staged_row_count']} | "
        f"adding independent events "
        f"{b['staged_rows_adding_independent_events']} | effective threads "
        f"{b['effective_thread_count']} | components {b['thread_components']}"
    )
    lines.append("")
    lines.append("Related curated/accepted anchors:")
    for a in rep["related_anchor_rows"]:
        lines.append(
            f"  #{a['event_id']} {a['date']} [{a['corpus_status']}] "
            f"{a['event_date_quality']} ({a['link_provenance']})"
        )
        lines.append(f"      {a['headline'][:78]}")
    lines.append("")
    lines.append("Thread cases (labels from the C4 layer):")
    for c in rep["cases"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} "
            f"{'/'.join(c['exposed_tickers']) or '-':<10} "
            f"{c['event_date_quality']} -> anchors {c['related_anchor_ids']}"
        )
        ro = c["local_readout"]
        if ro["available"]:
            parts = " ".join(f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                             for h in ro["horizons"])
            lines.append(f"      AR vs SPY (descriptive n=1, "
                         f"thread-caveated): {parts}")
        else:
            lines.append("      AR vs SPY: not locally computable")
        lines.append(f"      sibling because: "
                     f"{c['why_this_may_be_thread_sibling']}")
        lines.append(f"      adds: {c['what_new_information_if_any']}")
        lines.append(f"      disposition: {c['disposition']}")
    lines.append("")
    ti = rep["thread_interpretation"]
    lines.append("Why thread siblings overstate breadth:")
    lines.append(f"  {ti['why_raw_row_count_overstates_breadth']}")
    lines.append(f"  Can read:    {ti['what_can_be_read']}")
    lines.append(f"  Cannot read: {ti['what_cannot_be_read']}")
    lines.append(f"  Future packets: "
                 f"{ti['how_to_treat_307_310_in_future_packets']}")
    lines.append("")
    lines.append("Disposition / next no-paid moves:")
    for m in rep["next_no_paid_moves"]:
        lines.append(f"  - {m}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in rep["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(rep: dict[str, Any]) -> str:
    return json.dumps(rep, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only sanction/export-control thread-collapse report: "
            "derives thread membership from the C4 layer and reports honest "
            "breadth accounting (raw rows vs independent events). No DB "
            "write, no provider call, no paid analysis, no promotion."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap surfaced case entries (0 = no cap).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    rep = build_report(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(rep), file=output)
    else:
        print(_render_text(rep), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

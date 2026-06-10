#!/usr/bin/env python3
"""Read-only staged-family coverage board (cross-family research view).

Consolidates the staged research universe in one place: which mechanism
families are staged, which have been deepened into committed packets, which
rows are clean anchors vs partial / weak / thread-sibling / duplicate cases,
which legs actually compute locally (the C2A lesson: cached rows are NOT the
same as computable-at-date), and what the ranked no-paid next moves are.

Inputs are consumed live, never restated by hand:

  * anchor labels / corpus status - the C4 event-date quality layer;
  * packet existence - committed scripts + docs notes on disk;
  * candidate 304's paid disposition - the committed B2b packet text;
  * computability - the SELECT-only event-study gate per staged primary leg,
    plus gate checks on known transmission legs (313: LEA/APTV).

Discipline (non-negotiable): staged candidates are review staging, not
accepted evidence; accepted vs staged denominators never merge; no paid
analysis is approved anywhere in this board; read-only throughout.

Usage::

    python scripts/staged_family_coverage_report.py --db-path events.db --json
    python scripts/staged_family_coverage_report.py --db-path events.db
    python scripts/staged_family_coverage_report.py --db-path events.db --family regulation
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - DB_FILE seam for the event-study gate
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

# Shortlist tiers - source: stats/STAGED_CANDIDATE_SHORTLIST.md (AX1-AX5).
TIERS: dict[int, int] = {
    303: 1, 304: 1, 313: 1,
    305: 2, 306: 2, 307: 2, 311: 2, 312: 2, 314: 2,
    302: 3, 308: 3, 309: 3, 310: 3,
}

# Known transmission legs whose computability must be gate-checked per date
# (the C2A correction: rows cached != computable at the event window).
KNOWN_TRANSMISSION_LEGS: dict[int, tuple[str, ...]] = {
    313: ("LEA", "APTV"),
}

# Per-family curated metadata. Packet paths are detected on disk - a family
# only reads "packet_available" when both the script and the docs note exist.
FAMILY_REGISTRY: dict[str, dict[str, Any]] = {
    "regulation": {
        "packet_paths": ["scripts/regulation_cohort_packet.py",
                         "stats/REGULATION_COHORT_PACKET.md"],
        "what_it_adds": (
            "Legal/regulatory overhang on named defendants, with a "
            "conduct-vs-structural remedy contrast the archive lacks."
        ),
        "next_no_paid_move": (
            "No-paid comparison of the clean anchors (303 vs 304, conduct "
            "vs structural); cautious Tier-2 review of 305/306 afterwards."
        ),
        "no_paid_status": (
            "No paid analysis approved; 304's paid path is closed-deferred "
            "by operator; 302 retired from paid consideration."
        ),
    },
    "labor_inflation": {
        "packet_paths": ["scripts/labor_shock_cohort_packet.py",
                         "stats/LABOR_SHOCK_COHORT_PACKET.md"],
        "what_it_adds": (
            "Wage-cost / production-disruption transmission with a built-in "
            "goods-vs-media contrast - furthest from existing coverage."
        ),
        "next_no_paid_move": (
            "Design the bounded LEA/APTV pre-event backfill (own approval "
            "gate) so the 313 supplier read becomes computable; read 314 "
            "only as a weak anchor."
        ),
        "no_paid_status": (
            "No paid analysis approved; both cases stay staged/no-paid."
        ),
    },
    "industrial_policy": {
        "packet_paths": [],
        "what_it_adds": (
            "Industrial-policy beneficiary channel (CHIPS/IRA) - a new "
            "family, but anchored on scheduled signings."
        ),
        "next_no_paid_move": (
            "No-paid anchor-quality / policy-timeline review: find the real "
            "information-shock dates inside each bill's path (votes, "
            "surprise provisions) before any window is read."
        ),
        "no_paid_status": (
            "No paid analysis approved; weak/scheduled anchors must not be "
            "read as clean evidence."
        ),
    },
    "sanction": {
        "packet_paths": [],
        "what_it_adds": (
            "Density on the existing export-control thread - depth around "
            "curated anchors, not new family breadth."
        ),
        "next_no_paid_move": (
            "Thread-collapse / deferral logic: group 307-310 with their "
            "curated anchors (298/300/301) as one thread, not four "
            "independent observations."
        ),
        "no_paid_status": (
            "No paid analysis approved; thread siblings stay deferred as "
            "independent cases."
        ),
    },
}

_PAID_DOC: dict[int, str] = {
    304: "stats/CANDIDATE_304_PAID_GATE_PACKET.md",
}

DEEP_SLICES: dict[str, dict[str, Any]] = {
    "regulation_cohort_packet": {
        "paths": ["scripts/regulation_cohort_packet.py",
                  "stats/REGULATION_COHORT_PACKET.md"],
        "summary": "Family packet over the staged antitrust cases (C1).",
    },
    "labor_shock_cohort_packet": {
        "paths": ["scripts/labor_shock_cohort_packet.py",
                  "stats/LABOR_SHOCK_COHORT_PACKET.md"],
        "summary": "Goods-vs-media labor family packet (C2).",
    },
    "uaw_supplier_transmission_packet": {
        "paths": ["scripts/uaw_supplier_transmission_packet.py",
                  "stats/UAW_SUPPLIER_TRANSMISSION_PACKET.md"],
        "summary": (
            "313 deep slice: OEM legs readable, supplier legs corrected to "
            "not-currently-computable (C2A)."
        ),
    },
}

COVERAGE_GAPS: tuple[str, ...] = (
    "industrial_policy (311/312) has only weak/scheduled anchors and no "
    "deep packet - anchor-quality review needed before any read.",
    "sanction staged rows (307-310) are thread-dense siblings of curated "
    "anchors - they add depth, not independent breadth.",
    "labor supplier transmission (313: LEA/APTV) is not computable at the "
    "event date - bounded pre-event backfill gap.",
    "regulation's paid path is closed for 304 (operator deferral); 302 "
    "stays a deferred duplicate of quarantined row 315.",
)

NEXT_NO_PAID_OPPORTUNITIES: tuple[dict[str, Any], ...] = (
    {"rank": 1, "family": "industrial_policy", "no_paid": True,
     "requires_gate": False,
     "task": ("Anchor-quality / policy-timeline review of 311/312: locate "
              "the genuine information-shock dates in each bill's path "
              "before reading any window."),
     "rationale": "Cheapest read-only step that could rescue a new family "
                  "from its weak-anchor problem."},
    {"rank": 2, "family": "regulation", "no_paid": True,
     "requires_gate": False,
     "task": ("No-paid conduct-vs-structural comparison memo over the "
              "clean anchors 303/304, then cautious Tier-2 review of "
              "305/306."),
     "rationale": "Both anchors are clean and locally readable today."},
    {"rank": 3, "family": "labor_inflation", "no_paid": True,
     "requires_gate": True,
     "task": ("Design the bounded LEA/APTV pre-event cache backfill "
              "(~85 daily bars each around 2023-09-15) so the 313 supplier "
              "read becomes computable - the backfill itself writes "
              "price_cache and needs its own approval gate."),
     "rationale": "Converts the C2A correction into a costed, gated plan."},
    {"rank": 4, "family": "sanction", "no_paid": True,
     "requires_gate": False,
     "task": ("Thread-collapse note grouping 307-310 with curated anchors "
              "298/300/301 as one export-control thread."),
     "rationale": "Prevents thread density from masquerading as breadth."},
)

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "No paid analysis was run and none is approved anywhere on this board; "
    "paid /analyze remains blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers behind this board are descriptive n=1 point "
    "estimates: no CI, p-value, FDR, or single-event significance.",
    "Cross-family consolidation is a research index, not family-level "
    "inference and not a recommendation of any kind.",
    "Dispositions and rankings are review ordering, illustrative and "
    "revisable; representative cases are illustrative only.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)

_LABEL_COUNT_KEYS: dict[str, str] = {
    "clean_discrete_anchor": "clean_anchor_count",
    "partial_anticipation": "partial_anticipation_count",
    "scheduled_or_weak_anchor": "scheduled_or_weak_count",
    "continuation_or_thread_sibling": "thread_sibling_count",
    "duplicate_or_deferred": "duplicate_deferred_count",
    "manual_review_needed": "manual_review_count",
}


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _packet_status(paths: list[str]) -> str:
    if paths and all((ROOT / p).exists() for p in paths):
        return "packet_available"
    return "no_packet_yet"


def _paid_deferred(event_id: int) -> bool:
    doc = _PAID_DOC.get(event_id)
    if not doc:
        return False
    try:
        return "deferred" in (ROOT / doc).read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _primary_ticker(path: str, event_id: int) -> str | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        try:
            row = conn.execute(
                "SELECT market_tickers FROM events WHERE id = ?", (event_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row[0] or "[]")
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, dict):
                sym = entry.get("symbol")
                if isinstance(sym, str) and sym.strip():
                    return sym.strip().upper()
    return None


def _gate_status(path: str, event_id: int, event_date: str,
                 primary: str | None) -> str:
    try:
        from event_study_validation import (
            STATUS_AVAILABLE,
            build_event_study_validation,
        )
    except Exception:
        return "gate_unavailable"
    event = {"id": event_id, "event_date": event_date,
             "market_tickers": [{"symbol": primary}] if primary else []}
    saved = db.DB_FILE
    try:
        db.DB_FILE = path
        out = build_event_study_validation(event)
    except Exception:
        return "gate_unavailable"
    finally:
        db.DB_FILE = saved
    if out.get("status") == STATUS_AVAILABLE:
        return "computable_primary_leg"
    reasons = ",".join(out.get("blocking_reasons") or []) or "insufficient_data"
    return f"not_computable ({reasons})"


def _leg_gap(path: str, ticker: str, event_date: str) -> str:
    """Honest computability line for a transmission leg."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return f"{ticker}: cache unreadable"
    try:
        try:
            has_rows = conn.execute(
                "SELECT 1 FROM price_cache WHERE ticker=? LIMIT 1", (ticker,),
            ).fetchone() is not None
            pre = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM price_cache "
                "WHERE ticker=? AND date < ?", (ticker, event_date),
            ).fetchone()[0]
        except sqlite3.Error:
            return f"{ticker}: cache unreadable"
    finally:
        conn.close()
    rows_note = "rows cached" if has_rows else "no rows cached"
    return f"{ticker}: {rows_note}, {int(pre or 0)} pre-event dates"


def _disposition(event_id: int, label: str) -> str:
    tier = TIERS.get(event_id)
    tier_note = f" (Tier {tier})" if tier else ""
    if label == "duplicate_or_deferred":
        return ("deferred_duplicate - retired from paid consideration; "
                "resolve against the quarantined partner first")
    if label == "continuation_or_thread_sibling":
        return ("thread sibling of earlier anchors - not independent family "
                "breadth; collapse into the thread or defer")
    if label == "scheduled_or_weak_anchor":
        return (f"weak/scheduled anchor{tier_note} - residual surprise only, "
                "must not be read as a discrete-shock case")
    if label == "partial_anticipation":
        return f"usable with partial-anticipation caveat{tier_note}"
    if label == "clean_discrete_anchor":
        base = f"clean anchor{tier_note}"
        if _paid_deferred(event_id):
            base += "; paid path closed-deferred by operator"
        return base
    return "manual review needed before any use"


def _next_action(event_id: int, family: str) -> str:
    overrides = {
        302: "operator resolves the duplicate relation with row 315",
        313: ("design the bounded LEA/APTV pre-event backfill (own approval "
              "gate); read OEM legs under the anticipation caveat meanwhile"),
    }
    if event_id in overrides:
        return overrides[event_id]
    return FAMILY_REGISTRY.get(family, {}).get(
        "next_no_paid_move", "manual review")


# ---------------------------------------------------------------------------
# Report composer
# ---------------------------------------------------------------------------


def build_report(*, db_path: str | None = None, family: str = "all",
                 limit: int = 0) -> dict[str, Any]:
    """Build the staged-family coverage board. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    staged = [e for e in edq["events"] if e["corpus_status"] == "staged"]
    families = sorted({e["mechanism_family"] for e in staged})
    valid = set(families) | set(FAMILY_REGISTRY) | {"all"}
    if family not in valid:
        raise ValueError(f"unknown family {family!r}; expected one of "
                         f"{sorted(valid)}")

    accepted_rows = [e for e in edq["events"]
                     if e["corpus_status"] in ("accepted", "curated")]

    family_coverage: list[dict] = []
    for fam in families:
        rows = [e for e in staged if e["mechanism_family"] == fam]
        reg = FAMILY_REGISTRY.get(fam, {})
        counts = {key: 0 for key in _LABEL_COUNT_KEYS.values()}
        for e in rows:
            counts[_LABEL_COUNT_KEYS[e["event_date_quality"]]] += 1

        computable: list[int] = []
        not_computable: list[str] = []
        deferred: list[int] = []
        for e in rows:
            if e["event_date_quality"] == "duplicate_or_deferred":
                deferred.append(e["event_id"])
            primary = _primary_ticker(path, e["event_id"])
            status = _gate_status(path, e["event_id"], e["date"], primary)
            if status == "computable_primary_leg":
                computable.append(e["event_id"])
            else:
                not_computable.append(f"{e['event_id']}: {status}")
            for leg in KNOWN_TRANSMISSION_LEGS.get(e["event_id"], ()):
                not_computable.append(
                    f"{e['event_id']} transmission leg "
                    f"{_leg_gap(path, leg, e['date'])} - not computable at "
                    f"the event date"
                )

        family_coverage.append({
            "family": fam,
            "staged_count": len(rows),
            "accepted_count": sum(
                1 for e in accepted_rows if e["mechanism_family"] == fam),
            "packet_status": _packet_status(reg.get("packet_paths", [])),
            "packet_paths": list(reg.get("packet_paths", [])),
            **counts,
            "currently_computable_cases": sorted(computable),
            "not_currently_computable_cases": not_computable,
            "deferred_cases": sorted(deferred),
            "no_paid_status": reg.get(
                "no_paid_status",
                "No paid analysis approved for this family."),
            "next_no_paid_move": reg.get(
                "next_no_paid_move", "manual family review"),
            "what_it_adds": reg.get("what_it_adds", "unreviewed family"),
        })

    board_rows = staged if family == "all" else [
        e for e in staged if e["mechanism_family"] == family]
    case_board: list[dict] = []
    for e in sorted(board_rows, key=lambda x: x["event_id"]):
        fam = e["mechanism_family"]
        reg = FAMILY_REGISTRY.get(fam, {})
        primary = _primary_ticker(path, e["event_id"])
        case_board.append({
            "event_id": e["event_id"],
            "date": e["date"],
            "headline": e["headline"],
            "mechanism_family": fam,
            "corpus_status": e["corpus_status"],
            "event_date_quality": e["event_date_quality"],
            "anticipation_risk": e["anticipation_risk"],
            "thread_independence": e["thread_independence"],
            "family_packet_coverage": _packet_status(
                reg.get("packet_paths", [])),
            "compute_status": _gate_status(path, e["event_id"], e["date"],
                                           primary),
            "disposition": _disposition(e["event_id"],
                                        e["event_date_quality"]),
            "next_action": _next_action(e["event_id"], fam),
        })
    capped = max(int(limit), 0)
    if capped:
        case_board = case_board[:capped]

    deep_slices = {
        key: {**spec, "available": _packet_status(spec["paths"])
              == "packet_available"}
        for key, spec in DEEP_SLICES.items()
    }

    edq_denoms = edq["denominators"]
    return {
        "denominators": {
            "archive_rows": edq_denoms["archive_rows"],
            "accepted_coverage_denominator":
                edq_denoms["accepted_coverage_denominator"],
            "accepted_track_record_denominator":
                edq_denoms["accepted_track_record_denominator"],
            "staged_candidate_count": edq_denoms["staged_candidate_count"],
            "excluded_counts": edq_denoms["excluded_counts"],
            "note": (
                "Accepted vs staged stay separated; everything on this "
                "board is review staging and enters no accepted "
                "denominator."
            ),
        },
        "family_coverage": family_coverage,
        "case_board": case_board,
        "known_deep_slices": deep_slices,
        "coverage_gaps": list(COVERAGE_GAPS),
        "next_no_paid_opportunities": [dict(o) for o in
                                       NEXT_NO_PAID_OPPORTUNITIES],
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(rep: dict[str, Any]) -> str:
    d = rep["denominators"]
    lines = ["Staged-family coverage board (read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}"
    )
    lines.append("")
    lines.append("Family coverage:")
    lines.append(
        f"  {'family':<19}{'staged':>7}{'packet':>18}{'clean':>7}"
        f"{'partial':>8}{'weak':>6}{'thread':>8}{'dup':>5}"
    )
    for f in rep["family_coverage"]:
        lines.append(
            f"  {f['family']:<19}{f['staged_count']:>7}"
            f"{f['packet_status']:>18}{f['clean_anchor_count']:>7}"
            f"{f['partial_anticipation_count']:>8}"
            f"{f['scheduled_or_weak_count']:>6}"
            f"{f['thread_sibling_count']:>8}"
            f"{f['duplicate_deferred_count']:>5}"
        )
    lines.append("")
    lines.append("Case board:")
    for c in rep["case_board"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} [{c['mechanism_family']}] "
            f"{c['event_date_quality']}"
        )
        lines.append(f"      disposition: {c['disposition']}")
        lines.append(f"      compute: {c['compute_status']} | next: "
                     f"{c['next_action']}")
    lines.append("")
    lines.append("Computability warnings (rows cached is not computable-at-date):")
    warned = False
    for f in rep["family_coverage"]:
        for item in f["not_currently_computable_cases"]:
            lines.append(f"  [{f['family']}] {item}")
            warned = True
    if not warned:
        lines.append("  (every staged primary leg computes locally)")
    lines.append("")
    lines.append("Next no-paid opportunities (ranked):")
    for o in rep["next_no_paid_opportunities"]:
        gate = " [requires its own approval gate]" if o["requires_gate"] else ""
        lines.append(f"  {o['rank']}. [{o['family']}] {o['task']}{gate}")
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
            "Read-only staged-family coverage board: per-family anchor "
            "quality, packet coverage, computability, and ranked no-paid "
            "next moves. No DB write, no provider call, no paid analysis, "
            "no promotion."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--family", default="all",
                   help="Filter the case board to one family (default all).")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap surfaced case-board entries (0 = no cap).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    rep = build_report(db_path=args.db_path, family=args.family,
                       limit=args.limit)
    if args.json:
        print(_render_json(rep), file=output)
    else:
        print(_render_text(rep), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

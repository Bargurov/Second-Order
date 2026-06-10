#!/usr/bin/env python3
"""Read-only conduct-vs-structural memo: staged regulation anchors 303 vs 304.

The regulation family's two Tier-1 anchors differ on the dimension a finance
reviewer actually cares about: WHAT the state is threatening. 303 (DOJ v
Apple) is a CONDUCT case - behavioural remedies against platform-ecosystem
restrictions. 304 (DOJ v Google ad-tech) is a STRUCTURAL case - divestiture
of the ad-tech stack. This memo places the two staged n=1 windows side by
side and, crucially, explains why 304's more negative readout must NOT be
read as mechanism strength: in this pair, remedy type is confounded with the
share of the defendant's economics at risk, so the readout difference cannot
separate the two.

Inputs are live, never restated: anchor labels from the C4 layer, 304's paid
disposition from the committed B2b packet text, readouts from the SELECT-only
event-study gate. Both cases stay staged/no-paid; 304's paid path remains
closed/deferred and is not reopened here.

Usage::

    python scripts/regulation_conduct_structural_memo.py --db-path events.db --json
    python scripts/regulation_conduct_structural_memo.py --db-path events.db
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

FAMILY = "regulation"
PRIMARY_IDS: tuple[int, int] = (303, 304)

_PAID_DOC: dict[int, str] = {
    304: "stats/CANDIDATE_304_PAID_GATE_PACKET.md",
}
_DEFAULT_PAID_STATUS = (
    "no_paid_default (review staging; paid /analyze remains blocked)"
)

CASE_REGISTRY: dict[int, dict[str, str]] = {
    303: {
        "regulation_subtype": "platform_ecosystem / conduct_remedy",
        "mechanism_interpretation": (
            "Conduct case: DOJ challenges developer/ecosystem restrictions "
            "(Sherman Section 2). The threat is behavioural remedies that "
            "trim services economics at the margin - long-dated, "
            "negotiable, and a small share of the defendant's total "
            "business."
        ),
        "what_the_case_adds": (
            "A clean filing-date anchor for the conduct end of the remedy "
            "spectrum on a mega-cap platform."
        ),
        "what_the_case_does_not_show": (
            "It does not show conduct remedies are priced as immaterial - "
            "one quiet window on one defendant cannot separate 'priced as "
            "small' from 'not priced at all'."
        ),
    },
    304: {
        "regulation_subtype": "structural_remedy (ad-tech stack divestiture)",
        "mechanism_interpretation": (
            "Structural case: DOJ + 8 states seek divestiture of the "
            "ad-tech stack. The threat is breakup of a business that is a "
            "large share of the defendant's economics - the sharpest "
            "remedy form antitrust offers."
        ),
        "what_the_case_adds": (
            "A clean filing-date anchor for the structural end of the "
            "remedy spectrum, plus the operator-reviewed paid-gate packet "
            "(B1/B2b) documenting why its paid path is closed."
        ),
        "what_the_case_does_not_show": (
            "It does not show structural remedies move defendants more per "
            "se - the readout difference vs 303 is confounded with how much "
            "of each defendant's revenue the challenged business represents."
        ),
    },
}

NEXT_NO_PAID_MOVES: tuple[str, ...] = (
    "Keep 303/304 staged/no-paid; use this memo as the representative "
    "conduct-vs-structural comparison, not as evidence.",
    "Review 305/306 later only if the regulation family is deliberately "
    "expanded (Tier-2 priority stands).",
    "No paid call: the comparison is fully readable from local data, and "
    "304's paid path stays closed-deferred by operator decision.",
)

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked; 304's paid path remains closed/deferred.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "Two staged cases support no family-level inference and no "
    "recommendation of any kind.",
    "Neither defendant's move is attributed solely to its filing - same-"
    "window tape moves are never disentangled at n=1.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _paid_status(event_id: int) -> str:
    doc = _PAID_DOC.get(event_id)
    if doc:
        try:
            text = (ROOT / doc).read_text(encoding="utf-8")
        except OSError:
            text = ""
        if "deferred" in text.lower():
            return f"paid_deferred_by_operator (see {doc})"
    return _DEFAULT_PAID_STATUS


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
    base = {"available": False, "horizons": [],
            "descriptive_only": True, "n_equals_one": True}
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


def _readout_string(ro: dict) -> str:
    if not ro["available"]:
        return "not computable locally"
    return " ".join(f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                    for h in ro["horizons"])


def _disposition(label: str) -> str:
    if label == "clean_discrete_anchor":
        return ("keep_staged_no_paid - clean anchor; representative "
                "comparison case only")
    if label in ("partial_anticipation", "scheduled_or_weak_anchor"):
        return ("keep_staged_no_paid - anchor degraded per the C4 layer; "
                "use with caution and re-check before any comparison use")
    if label == "duplicate_or_deferred":
        return "deferred_duplicate - resolve before any use"
    return "manual review needed before any use"


# ---------------------------------------------------------------------------
# Memo composer
# ---------------------------------------------------------------------------


def build_memo(*, db_path: str | None = None, limit: int = 0) -> dict[str, Any]:
    """Build the conduct-vs-structural memo. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    staged_reg = [e for e in edq["events"]
                  if e["mechanism_family"] == FAMILY
                  and e["corpus_status"] == "staged"]
    by_id = {e["event_id"]: e for e in staged_reg}

    accepted_reg = sum(
        1 for e in edq["events"]
        if e["mechanism_family"] == FAMILY
        and e["corpus_status"] in ("accepted", "curated"))

    deferred_ids = sorted(
        e["event_id"] for e in staged_reg
        if e["event_date_quality"] == "duplicate_or_deferred")
    context_ids = sorted(
        e["event_id"] for e in staged_reg
        if e["event_id"] not in PRIMARY_IDS
        and e["event_id"] not in deferred_ids)

    cases: list[dict] = []
    readouts: dict[int, dict] = {}
    for cid in PRIMARY_IDS:
        e = by_id.get(cid)
        if e is None:
            continue
        spec = CASE_REGISTRY[cid]
        exposed = _exposed_tickers(path, cid)
        primary = exposed[0] if exposed else None
        ro = _local_readout(cid, e["date"], primary, db_path=path)
        readouts[cid] = ro
        cases.append({
            "event_id": cid,
            "date": e["date"],
            "headline": e["headline"],
            "stage": e["stage"],
            "corpus_status": e["corpus_status"],
            "mechanism_family": FAMILY,
            "regulation_subtype": spec["regulation_subtype"],
            "primary_ticker": primary,
            "exposed_tickers": exposed,
            "event_date_quality": e["event_date_quality"],
            "anticipation_risk": e["anticipation_risk"],
            "thread_independence": e["thread_independence"],
            "local_readout": ro,
            "mechanism_interpretation": spec["mechanism_interpretation"],
            "what_the_case_adds": spec["what_the_case_adds"],
            "what_the_case_does_not_show": spec["what_the_case_does_not_show"],
            "local_evidence_present": [
                f"clean filing-date anchor per the C4 layer"
                if e["event_date_quality"] == "clean_discrete_anchor"
                else f"anchor label: {e['event_date_quality']}",
                f"defendant window {_readout_string(ro)}",
            ],
            "local_evidence_missing": [
                "second-order ecosystem legs are not staged and mostly lack "
                "local price data (B1 packet)",
            ],
            "disposition": _disposition(e["event_date_quality"]),
            "paid_status": _paid_status(cid),
        })

    capped = max(int(limit), 0)
    surfaced = cases[:capped] if capped else cases

    contrast = {
        "conduct_303": _readout_string(readouts.get(303, {"available": False})),
        "structural_304": _readout_string(readouts.get(304, {"available": False})),
        "not_strength_statement": (
            "304's more negative defendant window does not establish "
            "mechanism strength: in this pair, remedy type is confounded "
            "with exposure share - the challenged business is a far larger "
            "slice of the 304 defendant's economics than the challenged "
            "conduct is of 303's - so the readout difference cannot "
            "separate 'structural remedies bite harder' from 'more of the "
            "company was at risk'. Different filing dates in different "
            "macro tapes add a second confound. n=1 per case."
        ),
    }

    mechanism_comparison = {
        "conduct_platform_ecosystem_case": 303,
        "structural_adtech_stack_case": 304,
        "similarities": [
            "Both are DOJ monopolization suits with clean, discrete "
            "filing-date anchors (per the C4 layer).",
            "Both are single-defendant equity reads with no staged "
            "second-order legs.",
            "Both remain staged/no-paid and outside every accepted "
            "denominator.",
        ],
        "differences": [
            "Remedy form: behavioural conduct relief (303) vs divestiture "
            "of a business line (304) - the sharpest contrast antitrust "
            "offers.",
            "Exposure share: the challenged business is a much larger part "
            "of the 304 defendant's economics, so remedy type and "
            "dollars-at-risk are confounded in this pair.",
            "Timing: filings sit in different macro tapes (early 2023 vs "
            "spring 2024), so cross-case differences may be regime, not "
            "mechanism.",
        ],
        "why_304_is_not_a_paid_candidate_now": (
            "The operator reviewed the B1 paid-gate packet and recorded a "
            "deferral (B2b): the case is not worth paid spend now. The gate "
            "stays blocked; the deferral does not retract the mechanism "
            "hypothesis, and this memo does not reopen it."
        ),
        "what_can_be_read": (
            "Two descriptive n=1 windows representing the two ends of the "
            "antitrust remedy spectrum, read side by side as research "
            "framing for the regulation family."
        ),
        "what_cannot_be_read": (
            "Any ranking of remedy-type severity, any regulation-family "
            "effect, or any causal attribution of either defendant's move "
            "to its filing."
        ),
        "readout_contrast": contrast,
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
            "regulation_staged_count": len(staged_reg),
            "regulation_accepted_count": accepted_reg,
            "note": (
                "Accepted vs staged stay separated; the memo reads two "
                "staged cases and enters no accepted denominator."
            ),
        },
        "comparison_scope": {
            "family": FAMILY,
            "primary_case_ids": list(PRIMARY_IDS),
            "context_case_ids": context_ids,
            "excluded_or_deferred_ids": deferred_ids,
            "paid_path_status": (
                "304's paid path is closed/deferred by operator decision "
                "(B2b); no paid approval exists for any regulation case."
            ),
        },
        "cases": surfaced,
        "mechanism_comparison": mechanism_comparison,
        "next_no_paid_moves": list(NEXT_NO_PAID_MOVES),
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(memo: dict[str, Any]) -> str:
    d = memo["denominators"]
    lines = ["Regulation conduct-vs-structural memo: 303 vs 304 "
             "(read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | regulation staged "
        f"{d['regulation_staged_count']} / accepted "
        f"{d['regulation_accepted_count']}"
    )
    scope = memo["comparison_scope"]
    lines.append(f"Scope: primary {scope['primary_case_ids']} | context "
                 f"{scope['context_case_ids']} | deferred "
                 f"{scope['excluded_or_deferred_ids']}")
    lines.append(f"Paid path: {scope['paid_path_status']}")
    lines.append("")
    lines.append("Cases (anchors from the C4 layer):")
    for c in memo["cases"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} {c['primary_ticker'] or '-':<6} "
            f"{c['event_date_quality']} (risk: {c['anticipation_risk']})"
        )
        lines.append(f"      subtype: {c['regulation_subtype']}")
        lines.append(f"      AR vs SPY (descriptive n=1): "
                     f"{_readout_string(c['local_readout'])}")
        lines.append(f"      {c['mechanism_interpretation']}")
        lines.append(f"      adds: {c['what_the_case_adds']}")
        lines.append(f"      does not show: {c['what_the_case_does_not_show']}")
        lines.append(f"      paid: {c['paid_status']}")
        lines.append(f"      disposition: {c['disposition']}")
    lines.append("")
    mc = memo["mechanism_comparison"]
    lines.append("Conduct vs structural regulation:")
    for s in mc["similarities"]:
        lines.append(f"  same: {s}")
    for s in mc["differences"]:
        lines.append(f"  diff: {s}")
    lines.append("")
    rc = mc["readout_contrast"]
    lines.append("Why 304 moved more than 303 - and why that is not proof:")
    lines.append(f"  303 (conduct):    {rc['conduct_303']}")
    lines.append(f"  304 (structural): {rc['structural_304']}")
    lines.append(f"  {rc['not_strength_statement']}")
    lines.append("")
    lines.append(f"Can read:    {mc['what_can_be_read']}")
    lines.append(f"Cannot read: {mc['what_cannot_be_read']}")
    lines.append(f"Paid (304):  {mc['why_304_is_not_a_paid_candidate_now']}")
    lines.append("")
    lines.append("Disposition / next no-paid moves:")
    for m in memo["next_no_paid_moves"]:
        lines.append(f"  - {m}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in memo["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(memo: dict[str, Any]) -> str:
    return json.dumps(memo, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only conduct-vs-structural memo over staged regulation "
            "anchors 303/304. No DB write, no provider call, no paid "
            "analysis, no promotion; 304's paid path stays closed."
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
    memo = build_memo(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(memo), file=output)
    else:
        print(_render_text(memo), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

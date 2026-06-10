#!/usr/bin/env python3
"""Read-only industrial-policy anchor-quality packet (staged 311/312).

The industrial_policy family's two staged cases are anchored on bill SIGNING
dates. A signing is the scheduled culmination of a months-long legislative
path - the market prices the policy as the path resolves (text, votes,
compromises), so a signing-date window mostly measures residual surprise.
This packet asks the anchor-quality question directly: what can these cases
support as-is, what alternative anchors would be needed, and what does the
local archive actually hold?

The local-evidence answer is computed, not asserted:

  * anchor labels come from the C4 event-date quality layer at run time;
  * per-ticker pre-signing price coverage is counted from the local cache;
  * the archive is scanned for any nearby rows that could serve as milestone
    anchors (votes, passage, design disclosures) - none exist today;
  * signing-window readouts run through the SELECT-only event-study gate.

Discipline: 311/312 stay staged/no-paid; nothing here promotes, approves
paid work, or treats a signing window as policy discovery. Read-only
throughout.

Usage::

    python scripts/industrial_policy_anchor_packet.py --db-path events.db --json
    python scripts/industrial_policy_anchor_packet.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - DB_FILE seam for the event-study gate
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

FAMILY = "industrial_policy"
_NEARBY_PRE_DAYS = 90
_NEARBY_POST_DAYS = 10

REQUIRED_ANCHOR_TYPES: tuple[str, ...] = (
    "first material bill text / subsidy-design disclosure (the earliest "
    "date the package's economics became knowable)",
    "major vote or passage surprise (cloture or floor outcome that moved "
    "the probability, especially a surprise compromise)",
    "conference/compromise change that altered the subsidy scope or "
    "beneficiaries",
    "final signing only if the signing itself changed uncertainty (a near "
    "formality is not an information shock)",
)

CASE_REGISTRY: dict[int, dict[str, Any]] = {
    311: {
        "policy_subtype": "semiconductor_capacity_subsidy / supply_chain_resilience",
        "why_current_anchor_is_weak": (
            "The signing followed weeks of telegraphed legislative progress; "
            "by signing day the subsidy package was largely priced, so the "
            "window measures residual surprise, not the policy's discovery."
        ),
        "alternative_anchor_types_needed": (
            "Passage/cloture vote dates or the first credible subsidy-design "
            "disclosure along the bill's path - whichever date moved the "
            "probability or economics, not the ceremony."
        ),
    },
    312: {
        "policy_subtype": "clean_energy_tax_credit / manufacturing_subsidy",
        "why_current_anchor_is_weak": (
            "The package's revival was the genuine surprise in the "
            "legislative path weeks before signing; the signing itself was "
            "largely priced, so the window measures residual surprise only."
        ),
        "alternative_anchor_types_needed": (
            "The surprise revival/compromise announcement and the passage "
            "votes - the dates when the package's probability jumped - "
            "rather than the scheduled signing."
        ),
    },
}

_UNKNOWN_CASE = {
    "policy_subtype": "other_or_manual_review",
    "why_current_anchor_is_weak": (
        "Unreviewed industrial_policy row - assess its anchor before use."
    ),
    "alternative_anchor_types_needed": (
        "Manual policy-timeline review required."
    ),
}

FAMILY_INTERPRETATION: dict[str, str] = {
    "what_can_be_read": (
        "Signing-date windows as RESIDUAL-surprise measurements only, plus "
        "longer drifts as descriptive post-passage repricing context - "
        "never attributed to the signing date itself."
    ),
    "what_cannot_be_read": (
        "Policy discovery: the signing window cannot identify when the "
        "market learned the policy's economics, and large post-signing "
        "drifts (e.g. a beneficiary rallying for months) must not be read "
        "as a signing-date event effect."
    ),
    "why_signing_windows_are_residual_surprise_only": (
        "A bill signing is the scheduled end of a public legislative path; "
        "text, votes, and compromises resolve uncertainty before it. "
        "Whatever the window shows is what was left unpriced - usually "
        "little - confounded with everything else in the tape that week."
    ),
}

NEXT_NO_PAID_MOVES: tuple[str, ...] = (
    "Keep 311/312 staged/deferred as-is; read their signing windows only as "
    "residual surprise.",
    "A later read-only policy-timeline task (D2) may identify better local "
    "anchor dates; the deep pre-signing price history already cached for "
    "the exposed tickers means re-anchored windows would be computable "
    "WITHOUT a cache backfill.",
    "Ingesting milestone rows as new anchors would be curated intake - a "
    "separately gated mutation, not part of any read-only task.",
    "No paid call: nothing in this family justifies paid analysis at the "
    "current anchor quality.",
)

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "Two weak-anchor cases support no family-level inference and no "
    "recommendation of any kind.",
    "A signing date is not treated as clean policy discovery anywhere in "
    "this packet.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


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


def _pre_event_dates(path: str, ticker: str, event_date: str) -> int:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM price_cache "
                "WHERE ticker = ? AND date < ?", (ticker, event_date),
            ).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0] or 0)
    finally:
        conn.close()


def _nearby_rows(path: str, event_date: str, exclude_ids: set[int]) -> list[dict]:
    """Archive rows near the signing date that could anchor the timeline."""
    try:
        anchor = _date.fromisoformat(event_date)
    except ValueError:
        return []
    lo = (anchor - _timedelta(days=_NEARBY_PRE_DAYS)).isoformat()
    hi = (anchor + _timedelta(days=_NEARBY_POST_DAYS)).isoformat()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, event_date, stage, headline FROM events "
                "WHERE event_date BETWEEN ? AND ? ORDER BY event_date",
                (lo, hi),
            ).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    out = []
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        out.append({
            "event_id": r["id"], "event_date": r["event_date"],
            "stage": r["stage"], "headline": (r["headline"] or "")[:70],
            "pre_signing": (r["event_date"] or "") < event_date,
        })
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


def _disposition(label: str) -> str:
    if label == "scheduled_or_weak_anchor":
        return ("keep_staged_no_paid - current window reads residual "
                "surprise only; re-anchor only via a later separate gated "
                "process")
    if label == "clean_discrete_anchor":
        return ("keep_staged_no_paid - clean anchor per the C4 layer; "
                "usable for no-paid review at the current date")
    if label == "partial_anticipation":
        return "keep_staged_no_paid - usable with the anticipation caveat"
    if label == "duplicate_or_deferred":
        return "deferred_duplicate - resolve before any use"
    return "manual review needed before any use"


# ---------------------------------------------------------------------------
# Packet composer
# ---------------------------------------------------------------------------


def build_packet(*, db_path: str | None = None, limit: int = 0) -> dict[str, Any]:
    """Build the industrial-policy anchor packet. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    rows = [e for e in edq["events"]
            if e["mechanism_family"] == FAMILY and e["corpus_status"] == "staged"]
    family_ids = {e["event_id"] for e in rows}
    accepted_count = sum(
        1 for e in edq["events"]
        if e["mechanism_family"] == FAMILY
        and e["corpus_status"] in ("accepted", "curated"))

    cases: list[dict] = []
    price_evidence_lines: list[str] = []
    milestone_missing = False
    for e in sorted(rows, key=lambda x: x["event_id"]):
        spec = CASE_REGISTRY.get(e["event_id"], _UNKNOWN_CASE)
        exposed = _exposed_tickers(path, e["event_id"])
        primary = exposed[0] if exposed else None
        nearby = _nearby_rows(path, e["date"], exclude_ids=family_ids)
        pre_rows = [n for n in nearby if n["pre_signing"]]

        present: list[str] = []
        for t in exposed:
            pre = _pre_event_dates(path, t, e["date"])
            present.append(f"{t}: {pre} pre-signing price dates cached")
            if pre:
                price_evidence_lines.append(f"{t} ({pre} pre-signing dates)")
        for n in pre_rows:
            present.append(
                f"archive row {n['event_id']} ({n['event_date']}, "
                f"{n['stage']}) sits in the pre-signing window: "
                f"{n['headline']}"
            )

        missing: list[str] = []
        if not pre_rows:
            missing.append(
                "no archive event rows exist for any pre-signing milestone "
                "(no vote, passage, or design-disclosure anchor is locally "
                "representable today)"
            )
            milestone_missing = True
        readout = _local_readout(e["event_id"], e["date"], primary,
                                 db_path=path)
        if not readout["available"]:
            missing.append("signing-date window not computable from the "
                           "local cache")

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
            "local_readout": readout,
            "why_current_anchor_is_weak": spec["why_current_anchor_is_weak"],
            "alternative_anchor_types_needed":
                spec["alternative_anchor_types_needed"],
            "local_evidence_present": present,
            "local_evidence_missing": missing,
            "disposition": _disposition(e["event_date_quality"]),
        })

    capped = max(int(limit), 0)
    surfaced = cases[:capped] if capped else cases

    reanchor_ids = sorted(
        c["event_id"] for c in cases
        if c["event_date_quality"] == "scheduled_or_weak_anchor")
    deferred_ids = sorted(
        c["event_id"] for c in cases
        if c["event_date_quality"] == "duplicate_or_deferred")

    available_locally = (
        "Deep pre-signing price history is cached for the exposed tickers ("
        + ", ".join(sorted(set(price_evidence_lines))) +
        "), so re-anchored windows would be computable without any cache "
        "backfill."
        if price_evidence_lines else
        "No pre-signing price history cached for the exposed tickers."
    )
    missing_locally = (
        "No archive event rows exist for pre-signing milestones - "
        "identifying candidate dates needs a read-only timeline task, and "
        "ingesting them as anchors would be separately-gated curated intake."
        if milestone_missing else
        "Pre-signing archive rows exist near the signing dates - review "
        "them as candidate anchors."
    )

    edq_denoms = edq["denominators"]
    return {
        "denominators": {
            "archive_rows": edq_denoms["archive_rows"],
            "accepted_coverage_denominator":
                edq_denoms["accepted_coverage_denominator"],
            "accepted_track_record_denominator":
                edq_denoms["accepted_track_record_denominator"],
            "staged_candidate_count": edq_denoms["staged_candidate_count"],
            "industrial_policy_staged_count": len(rows),
            "industrial_policy_accepted_count": accepted_count,
            "note": (
                "Accepted vs staged stay separated; both cases are review "
                "staging and enter no accepted denominator."
            ),
        },
        "cohort_scope": {
            "family": FAMILY,
            "included_staged_ids": sorted(family_ids),
            "deferred_ids": deferred_ids,
            "reanchor_needed_ids": reanchor_ids,
        },
        "cases": surfaced,
        "policy_timeline_requirements": {
            "required_anchor_types": list(REQUIRED_ANCHOR_TYPES),
            "currently_available_locally": available_locally,
            "missing_locally": missing_locally,
        },
        "family_interpretation": dict(FAMILY_INTERPRETATION),
        "next_no_paid_moves": list(NEXT_NO_PAID_MOVES),
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(pkt: dict[str, Any]) -> str:
    d = pkt["denominators"]
    lines = ["Industrial-policy anchor-quality packet (read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | industrial_policy staged "
        f"{d['industrial_policy_staged_count']} / accepted "
        f"{d['industrial_policy_accepted_count']}"
    )
    scope = pkt["cohort_scope"]
    lines.append(f"Scope: included {scope['included_staged_ids']} | "
                 f"re-anchor needed {scope['reanchor_needed_ids']}")
    lines.append("")
    lines.append("Cases (event-date quality from the C4 layer):")
    for c in pkt["cases"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} "
            f"{'/'.join(c['exposed_tickers']) or '-':<10} "
            f"{c['event_date_quality']} (risk: {c['anticipation_risk']})"
        )
        lines.append(f"      subtype: {c['policy_subtype']}")
        ro = c["local_readout"]
        if ro["available"]:
            parts = " ".join(f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                             for h in ro["horizons"])
            lines.append(f"      AR vs SPY (descriptive n=1, primary "
                         f"{c['primary_ticker']}): {parts}")
        else:
            lines.append("      AR vs SPY: not locally computable")
        for p in c["local_evidence_present"]:
            lines.append(f"      present: {p}")
        for m in c["local_evidence_missing"]:
            lines.append(f"      missing: {m}")
        lines.append(f"      disposition: {c['disposition']}")
    lines.append("")
    lines.append("Why signing anchors are weak:")
    for c in pkt["cases"]:
        lines.append(f"  #{c['event_id']}: {c['why_current_anchor_is_weak']}")
    fi = pkt["family_interpretation"]
    lines.append(f"  {fi['why_signing_windows_are_residual_surprise_only']}")
    lines.append("")
    lines.append("What alternative anchors would be needed:")
    for t in pkt["policy_timeline_requirements"]["required_anchor_types"]:
        lines.append(f"  - {t}")
    lines.append(f"  locally available: "
                 f"{pkt['policy_timeline_requirements']['currently_available_locally']}")
    lines.append(f"  locally missing:   "
                 f"{pkt['policy_timeline_requirements']['missing_locally']}")
    lines.append("")
    lines.append(f"Can read:    {fi['what_can_be_read']}")
    lines.append(f"Cannot read: {fi['what_cannot_be_read']}")
    lines.append("")
    lines.append("Disposition / next no-paid moves:")
    for m in pkt["next_no_paid_moves"]:
        lines.append(f"  - {m}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in pkt["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(pkt: dict[str, Any]) -> str:
    return json.dumps(pkt, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only industrial-policy anchor-quality packet for staged "
            "311/312: why signing dates are weak anchors, what alternative "
            "anchors would be needed, and what the local archive holds. No "
            "DB write, no provider call, no paid analysis, no promotion."
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
    pkt = build_packet(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(pkt), file=output)
    else:
        print(_render_text(pkt), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

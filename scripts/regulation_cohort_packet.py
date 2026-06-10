#!/usr/bin/env python3
"""Read-only regulation-family cohort packet (antitrust / market-structure).

Compares the staged regulation candidates AS A FAMILY rather than as isolated
notes: which cases are clean event-date anchors, which are deferred
duplicates, what market-structure mechanism each represents, what descriptive
1d/5d/20d readout exists locally, and what the family would add beyond the
tariff/sanction rows if ever promoted through a separate process.

The C4 event-date quality layer (``scripts/event_date_quality_report.py``) is
consumed directly as the anchor-label source - labels are derived, never
hardcoded. The B2b operator decision (candidate 304 paid path deferred) is
read from the committed packet note.

Discipline (non-negotiable):

  * Staged ``z1a_candidate_pack`` rows are review staging, NOT accepted
    evidence; nothing here promotes a candidate or changes a denominator.
  * Event-window numbers are descriptive n=1 point estimates; comparing them
    side by side is a research view, not family-level inference.
  * Read-only: ``mode=ro`` connections only (via the C4 layer and the
    event-study gate); no provider, no paid call, no LLM, no network.

Usage::

    python scripts/regulation_cohort_packet.py --db-path events.db --json
    python scripts/regulation_cohort_packet.py --db-path events.db
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

import db  # noqa: E402  - DB_FILE seam for the event-study gate
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

FAMILY = "regulation"

# Curated case registry - mechanism taxonomy and limits for the known staged
# regulation cases. Unknown regulation rows degrade to other_or_manual_review
# rather than inventing content.
TAXONOMY_BUCKETS: tuple[str, ...] = (
    "conduct_remedy", "structural_remedy", "platform_ecosystem",
    "market_structure", "payments_network", "other_or_manual_review",
)

CASE_REGISTRY: dict[int, dict[str, str]] = {
    302: {
        "regulation_subtype": "platform_ecosystem / conduct_remedy (marketplace)",
        "mechanism_chain": (
            "FTC + states allege marketplace monopoly maintenance "
            "(self-preferencing, anti-discounting, fulfillment bundling) -> "
            "conduct-remedy overhang on AMZN retail economics."
        ),
        "falsifiers_or_limits": (
            "Duplicate of quarantined row 315 - resolve before any cohort "
            "use; retired from future paid consideration (AX1)."
        ),
    },
    303: {
        "regulation_subtype": "platform_ecosystem / conduct_remedy",
        "mechanism_chain": (
            "DOJ + states allege smartphone-market monopolization via "
            "developer/ecosystem restrictions (Sherman Section 2) -> "
            "conduct-remedy overhang on AAPL services economics."
        ),
        "falsifiers_or_limits": (
            "Single-name depth; remedies long-dated; ecosystem second-order "
            "names not staged."
        ),
    },
    304: {
        "regulation_subtype": "structural_remedy (ad-tech stack divestiture)",
        "mechanism_chain": (
            "DOJ + 8 states allege ad-tech stack monopolization seeking "
            "divestiture -> structural-remedy (breakup) risk on the GOOGL "
            "ads business."
        ),
        "falsifiers_or_limits": (
            "Paid path closed-deferred by operator (B2b); second-order "
            "ad-tech names carry no local price data (B1 packet)."
        ),
    },
    305: {
        "regulation_subtype": "market_structure / vertical_integration (divestiture sought)",
        "mechanism_chain": (
            "DOJ + states allege live-events monopolization via the Live "
            "Nation-Ticketmaster vertical stack (promotion + venues + "
            "ticketing) -> market-structure risk on LYV."
        ),
        "falsifiers_or_limits": (
            "Smaller-cap defendant - event windows carry idiosyncratic "
            "noise; divestiture long-dated."
        ),
    },
    306: {
        "regulation_subtype": "payments_network / network_access",
        "mechanism_chain": (
            "DOJ alleges debit-network monopolization via routing/volume "
            "agreements -> network-access conduct overhang on V (the staged "
            "row also lists MA as a related beneficiary leg)."
        ),
        "falsifiers_or_limits": (
            "Network-effects litigation is long-dated; single "
            "payment-network defendant."
        ),
    },
}

_UNKNOWN_CASE = {
    "regulation_subtype": "other_or_manual_review",
    "mechanism_chain": (
        "No curated mechanism map for this row - manual review before any "
        "cohort use."
    ),
    "falsifiers_or_limits": "Unreviewed regulation row; classify before use.",
}

# Paid-status sources: committed packet notes carrying operator decisions.
_PAID_DOC: dict[int, str] = {
    304: "stats/CANDIDATE_304_PAID_GATE_PACKET.md",
}
_DEFAULT_PAID_STATUS = (
    "no_paid_default (review staging; paid /analyze remains blocked)"
)

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "No paid analysis was run and none is approved by this packet; paid "
    "/analyze remains blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "Side-by-side comparison is a research view, not family-level inference "
    "- four staged cases cannot support a pooled conclusion.",
    "Mechanism chains and subtypes are research taxonomy, illustrative and "
    "to be tested, not established causal claims.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Local readout (descriptive n=1) via the existing SELECT-only gate
# ---------------------------------------------------------------------------


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
    event = {
        "id": event_id, "event_date": event_date,
        "market_tickers": [{"symbol": primary}] if primary else [],
    }
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


def _cohort_use(label: str) -> str:
    if label == "duplicate_or_deferred":
        return "deferred_duplicate"
    if label == "clean_discrete_anchor":
        return "usable_clean_anchor"
    return "usable_with_caution"


def _linked_ids(thread_independence: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", thread_independence or "")]


# ---------------------------------------------------------------------------
# Packet composer
# ---------------------------------------------------------------------------


def build_packet(
    *, db_path: str | None = None, include_deferred: bool = True,
    limit: int = 0,
) -> dict[str, Any]:
    """Build the regulation cohort packet. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    # The C4 layer is the single source for corpus status + anchor labels.
    edq = edq_build_report(db_path=path, lens="all", limit=0)
    events = edq["events"]
    reg_rows = [e for e in events if e["mechanism_family"] == FAMILY]

    # Pending rows tied to the cohort via duplicate links (e.g. 315 <-> 302).
    reg_ids = {e["event_id"] for e in reg_rows}
    pending_related: list[int] = []
    for e in events:
        if e["corpus_status"] != "pending":
            continue
        if e["event_id"] in reg_ids:
            pending_related.append(e["event_id"])
            continue
        if e["event_date_quality"] == "duplicate_or_deferred" and (
                set(_linked_ids(e["thread_independence"])) & reg_ids):
            pending_related.append(e["event_id"])

    cases: list[dict] = []
    for e in sorted(reg_rows, key=lambda x: x["event_id"]):
        spec = CASE_REGISTRY.get(e["event_id"], _UNKNOWN_CASE)
        label = e["event_date_quality"]
        # primary_ticker / local_readout are filled after the loop in one
        # read-only pass (the C4 payload does not carry tickers).
        cases.append({
            "event_id": e["event_id"],
            "date": e["date"],
            "headline": e["headline"],
            "stage": e["stage"],
            "corpus_status": e["corpus_status"],
            "mechanism_family": e["mechanism_family"],
            "regulation_subtype": spec["regulation_subtype"],
            "primary_ticker": None,  # filled below from the DB read
            "event_date_quality": label,
            "anticipation_risk": e["anticipation_risk"],
            "thread_independence": e["thread_independence"],
            "local_readout": None,  # filled below
            "mechanism_chain": spec["mechanism_chain"],
            "falsifiers_or_limits": spec["falsifiers_or_limits"],
            "cohort_use": _cohort_use(label),
            "paid_status": _paid_status(e["event_id"]),
        })

    # One read-only pass for primary tickers (the C4 payload omits them).
    tickers = _primary_tickers(path, [c["event_id"] for c in cases])
    for c in cases:
        c["primary_ticker"] = tickers.get(c["event_id"])
        c["local_readout"] = _local_readout(
            c["event_id"], c["date"], c["primary_ticker"], db_path=path,
        )

    included = [c["event_id"] for c in cases
                if c["corpus_status"] == "staged"
                and c["cohort_use"] != "deferred_duplicate"]
    deferred = [c["event_id"] for c in cases
                if c["cohort_use"] == "deferred_duplicate"]

    if not include_deferred:
        cases = [c for c in cases if c["cohort_use"] != "deferred_duplicate"]
    capped = max(int(limit), 0)
    surfaced = cases[:capped] if capped else cases

    taxonomy = {bucket: sorted(
        c["event_id"] for c in cases if bucket in c["regulation_subtype"]
    ) for bucket in TAXONOMY_BUCKETS}

    clean = sorted(c["event_id"] for c in cases
                   if c["cohort_use"] == "usable_clean_anchor")
    caution = sorted(c["event_id"] for c in cases
                     if c["cohort_use"] == "usable_with_caution")

    edq_denoms = edq["denominators"]
    reg_accepted = sum(1 for e in reg_rows
                       if e["corpus_status"] in ("accepted", "curated"))
    reg_staged = sum(1 for e in reg_rows if e["corpus_status"] == "staged")

    return {
        "denominators": {
            "archive_rows": edq_denoms["archive_rows"],
            "accepted_coverage_denominator":
                edq_denoms["accepted_coverage_denominator"],
            "accepted_track_record_denominator":
                edq_denoms["accepted_track_record_denominator"],
            "staged_candidate_count": edq_denoms["staged_candidate_count"],
            "regulation_staged_count": reg_staged,
            "regulation_accepted_count": reg_accepted,
            "note": (
                "Accepted vs staged stay separated; the regulation cohort is "
                "review staging only and enters no accepted denominator."
            ),
        },
        "cohort_scope": {
            "family": FAMILY,
            "included_staged_ids": included,
            "deferred_ids": deferred,
            "pending_related_ids": sorted(set(pending_related)),
            "excluded_reasoning": (
                "Deferred ids are same-announcement duplicates (C4 "
                "duplicate_or_deferred) and never count as cohort evidence; "
                "pending-related ids are quarantined rows linked to the "
                "cohort and stay outside it."
            ),
        },
        "cases": surfaced,
        "family_taxonomy": taxonomy,
        "comparison_readout": {
            "clean_anchor_cases": clean,
            "caution_cases": caution,
            "deferred_cases": deferred,
            "what_comparison_can_show": (
                "Whether clean-anchor antitrust filings produced descriptively "
                "similar defendant event-window reactions (direction and rough "
                "magnitude) across conduct vs structural cases - n=1 "
                "descriptive points placed side by side."
            ),
            "what_comparison_cannot_show": (
                "No pooled statistic, no significance, no causal attribution: "
                "a handful of staged cases spanning different macro regimes "
                "cannot support family-level inference, and staged rows are "
                "not accepted evidence."
            ),
        },
        "non_claims": list(NON_CLAIMS),
    }


def _primary_tickers(path: str, ids: list[int]) -> dict[int, str | None]:
    import sqlite3
    out: dict[int, str | None] = {}
    if not ids:
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" for _ in ids)
        try:
            rows = conn.execute(
                f"SELECT id, market_tickers FROM events WHERE id IN ({marks})",
                ids,
            ).fetchall()
        except sqlite3.Error:
            return out
    finally:
        conn.close()
    for r in rows:
        ticker = None
        try:
            parsed = json.loads(r["market_tickers"] or "[]")
        except (TypeError, ValueError):
            parsed = []
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict):
                    sym = entry.get("symbol")
                    if isinstance(sym, str) and sym.strip():
                        ticker = sym.strip().upper()
                        break
        out[r["id"]] = ticker
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(pkt: dict[str, Any]) -> str:
    d = pkt["denominators"]
    scope = pkt["cohort_scope"]
    lines = ["Regulation-family cohort packet (read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | regulation staged "
        f"{d['regulation_staged_count']} / accepted "
        f"{d['regulation_accepted_count']}"
    )
    lines.append(
        f"Scope: included {scope['included_staged_ids']} | deferred "
        f"{scope['deferred_ids']} | pending-related "
        f"{scope['pending_related_ids']}"
    )
    lines.append("")
    lines.append("Cohort cases (event-date quality from the C4 layer):")
    for c in pkt["cases"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} {c['primary_ticker'] or '-':<6} "
            f"{c['event_date_quality']:<30} use={c['cohort_use']}"
        )
        lines.append(f"      subtype: {c['regulation_subtype']}")
        lines.append(f"      {c['mechanism_chain']}")
        ro = c["local_readout"]
        if ro and ro["available"]:
            parts = " ".join(
                f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                for h in ro["horizons"]
            )
            lines.append(f"      AR vs SPY (descriptive n=1): {parts}")
        else:
            lines.append("      AR vs SPY: not locally computable")
        lines.append(f"      limits: {c['falsifiers_or_limits']}")
        lines.append(f"      paid: {c['paid_status']}")
    lines.append("")

    lines.append("Family mechanism taxonomy:")
    for bucket, ids in pkt["family_taxonomy"].items():
        if ids:
            lines.append(f"  {bucket:<24} {ids}")
    lines.append("")

    cr = pkt["comparison_readout"]
    lines.append("What this family adds:")
    lines.append(
        "  The accepted archive has zero regulation rows; these staged "
        "antitrust cases would add conduct-vs-structural remedy contrasts "
        "(platform, market-structure, payments-network) beyond the existing "
        "tariff/sanction observations."
    )
    lines.append(f"  Can show:    {cr['what_comparison_can_show']}")
    lines.append(f"  Cannot show: {cr['what_comparison_cannot_show']}")
    lines.append("")
    lines.append("Why this is still staged/no-paid:")
    lines.append(
        "  Every case remains review staging - excluded from accepted "
        "denominators; 302 is a deferred duplicate of quarantined row 315; "
        "304's paid path is closed-deferred by operator decision; no paid "
        "analysis is approved and no candidate is promoted."
    )
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
            "Read-only regulation-family cohort packet over the staged "
            "antitrust cases, consuming the C4 event-date quality layer. "
            "No DB write, no provider call, no paid analysis, no promotion."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--include-deferred", dest="include_deferred",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="Include deferred-duplicate cases in the case list "
                        "(scope always discloses them).")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap surfaced case entries (0 = no cap).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    pkt = build_packet(db_path=args.db_path,
                       include_deferred=args.include_deferred,
                       limit=args.limit)
    if args.json:
        print(_render_json(pkt), file=output)
    else:
        print(_render_text(pkt), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

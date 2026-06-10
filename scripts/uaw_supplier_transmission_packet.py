#!/usr/bin/env python3
"""Read-only UAW supplier-transmission packet for staged candidate 313.

Deepens the labor-shock family with one narrow question: how does the direct
OEM exposure path (GM/F, the staged legs) compare with the second-order
supplier channel (LEA/APTV) around the 2023-09-15 strike start - using only
locally cached data?

Honesty first: the packet computes, per ticker, both a local-data flag AND
the pre-event coverage the event-study gate actually needs. A ticker can have
cached rows yet still be uncomputable at this event date (the live cache
holds 2026-only windows for the supplier legs) - that gap is reported
precisely instead of being papered over.

Discipline (non-negotiable):

  * Candidate 313 stays staged/no-paid; the packet blocks itself if the row
    is missing or no longer staged. Nothing here promotes or approves paid
    work.
  * Anchor label and horizon caution come from the C4 event-date quality
    layer at run time (313 reads as partial anticipation - windows may
    understate or misplace repricing that leaked in before the deadline).
  * All numbers are descriptive n=1 point estimates vs SPY; comparing legs
    is a research view, never family-level inference.
  * Read-only: ``mode=ro`` connections and the SELECT-only event-study gate;
    no provider, no paid call, no DB write.

Usage::

    python scripts/uaw_supplier_transmission_packet.py --db-path events.db --json
    python scripts/uaw_supplier_transmission_packet.py --db-path events.db
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

DEFAULT_CANDIDATE = 313

# Narrow, curated asset groups - only legs C2 surfaced and the staged row
# supports. Nothing is added silently; excluded names say why.
ASSET_GROUPS: dict[str, list[dict[str, str]]] = {
    "direct_oem_exposures": [
        {"ticker": "GM", "note": "struck automaker; staged primary"},
        {"ticker": "F", "note": "struck automaker; staged exposed leg"},
    ],
    "supplier_exposures": [
        {"ticker": "LEA", "note": "seating supplier - order-flow pass-through"},
        {"ticker": "APTV", "note": "electrical/harness supplier - order-flow pass-through"},
    ],
    "context_assets": [
        {"ticker": "SPY", "note": "benchmark basis for every readout"},
        {"ticker": "XLY", "note": "consumer-discretionary context only"},
    ],
    "excluded_assets": [
        {"ticker": "STLA", "note": "third struck automaker - NOT on the staged "
                                   "row; adding it silently would alter the "
                                   "staged contract"},
        {"ticker": "TSLA", "note": "non-union peer - not mechanism-linked"},
        {"ticker": "BWA", "note": "drivetrain supplier - no local price data"},
    ],
}

MECHANISM_CHAIN: dict[str, str] = {
    "strike_start": (
        "2023-09-15: simultaneous targeted walkouts at one assembly plant "
        "per Detroit automaker ('Stand Up' escalation design)."
    ),
    "production_disruption": (
        "Output stops at struck plants immediately; scope grows with each "
        "escalation round, so day-one disruption is deliberately partial."
    ),
    "inventory_buffer": (
        "Finished-vehicle inventory lets OEM revenue lag the production "
        "halt; the equity read is expectations, not current deliveries."
    ),
    "supplier_order_flow": (
        "Suppliers feel the halt through cancelled/reduced just-in-time "
        "orders for struck platforms - a volume pass-through that can be "
        "sharper than the OEM's own revenue effect but is diversified "
        "across customers and platforms."
    ),
    "wage_cost_settlement": (
        "The durable cost arrives at settlement (wage structure, COLA); "
        "during the strike it is an expectation channel only."
    ),
    "margin_pressure_or_revenue_delay": (
        "OEMs trade near-term margin (strike costs, lost units) against "
        "settlement economics; suppliers face volume deleverage with no "
        "offsetting wage savings."
    ),
}

FALSIFIERS_OR_LIMITS: tuple[str, ...] = (
    "The strike deadline was anticipated - pre-date repricing can make the "
    "1d window understate or misplace the shock (C4: partial anticipation).",
    "Targeted plants limited the initial output impact; day-one scope was "
    "deliberately small.",
    "Inventory buffers distort 1d/5d OEM moves - the tape prices "
    "expectations of duration, not current deliveries.",
    "Supplier exposure is diversified across OEMs and platforms, diluting "
    "the struck-platform pass-through.",
    "Broad auto/consumer tape moves confound any direct-vs-supplier "
    "comparison in the same window.",
    "Every readout is a descriptive n=1 point estimate vs SPY - nothing "
    "here supports inference.",
)

NON_CLAIMS: tuple[str, ...] = (
    "Candidate 313 is a staged candidate - not accepted evidence - and "
    "stays outside every accepted denominator (denominators unchanged).",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "All event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "The direct-vs-supplier comparison is illustrative, no-paid research "
    "only - not family-level inference and not a recommendation of any "
    "kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _all_tickers() -> list[str]:
    return [e["ticker"] for group in ASSET_GROUPS.values() for e in group]


def _has_local_prices(path: str, ticker: str) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        try:
            row = conn.execute(
                "SELECT 1 FROM price_cache WHERE ticker = ? LIMIT 1",
                (ticker,),
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None
    finally:
        conn.close()


def _pre_event_dates(path: str, ticker: str, event_date: str) -> int:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM price_cache "
                "WHERE ticker = ? AND date < ?",
                (ticker, event_date),
            ).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0] or 0)
    finally:
        conn.close()


def _symbol_readout(path: str, ticker: str, event_date: str) -> dict:
    base = {
        "status": "unavailable", "blocking_reasons": [], "horizons": [],
        "descriptive_only": True, "n_equals_one": True,
        "benchmark_basis": "SPY",
        "pre_event_distinct_dates": _pre_event_dates(path, ticker, event_date),
    }
    try:
        from event_study_validation import event_study_ar_for_symbol
    except Exception:
        return base
    saved = db.DB_FILE
    try:
        db.DB_FILE = path
        out = event_study_ar_for_symbol(ticker, event_date)
    except Exception:
        return base
    finally:
        db.DB_FILE = saved
    status = out.get("status") or "unavailable"
    horizons = [
        {"horizon": h.get("horizon"), "abnormal_return": h.get("abnormal_return"),
         "sar": h.get("sar"), "car": h.get("car")}
        for h in out.get("per_horizon") or [] if isinstance(h, dict)
    ] if status == "event_study_available" else []
    return {**base, "status": status,
            "blocking_reasons": list(out.get("blocking_reasons") or []),
            "horizons": horizons}


def _pattern_string(readouts: dict, tickers: list[str]) -> str:
    parts = []
    for t in tickers:
        ro = readouts.get(t) or {}
        if ro.get("status") == "event_study_available":
            hs = " ".join(
                f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                for h in ro["horizons"]
            )
            parts.append(f"{t}: {hs}")
        else:
            parts.append(f"{t}: not computable locally")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Packet composer
# ---------------------------------------------------------------------------


def _blocked(status: str, candidate: dict | None, edq_denoms: dict) -> dict:
    return {
        "packet_status": status,
        "candidate": candidate or {"event_id": None, "staged_no_paid": False},
        "denominators": edq_denoms,
        "non_claims": list(NON_CLAIMS),
    }


def build_packet(*, db_path: str | None = None,
                 candidate_id: int = DEFAULT_CANDIDATE,
                 limit: int = 0) -> dict[str, Any]:
    """Build the UAW supplier-transmission packet. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    denoms = {
        "archive_rows": edq["denominators"]["archive_rows"],
        "accepted_coverage_denominator":
            edq["denominators"]["accepted_coverage_denominator"],
        "accepted_track_record_denominator":
            edq["denominators"]["accepted_track_record_denominator"],
        "staged_candidate_count":
            edq["denominators"]["staged_candidate_count"],
        "note": (
            "Accepted vs staged stay separated; this packet reads one staged "
            "candidate and enters no accepted denominator."
        ),
    }
    row = next((e for e in edq["events"] if e["event_id"] == candidate_id), None)
    if row is None:
        return _blocked("candidate_not_found", None, denoms)

    candidate = {
        "event_id": row["event_id"],
        "date": row["date"],
        "headline": row["headline"],
        "stage": row["stage"],
        "mechanism_family": row["mechanism_family"],
        "corpus_status": row["corpus_status"],
        "staged_no_paid": row["corpus_status"] == "staged",
        "event_date_quality": row["event_date_quality"],
        "anticipation_risk": row["anticipation_risk"],
        "horizon_interpretation_caution": row["horizon_interpretation_caution"],
    }
    if not candidate["staged_no_paid"]:
        return _blocked("blocked_candidate_not_staged", candidate, denoms)

    tickers = _all_tickers()
    capped = max(int(limit), 0)
    readout_tickers = tickers[:capped] if capped else tickers
    flags = {t: _has_local_prices(path, t) for t in tickers}
    readouts = {t: _symbol_readout(path, t, row["date"]) for t in readout_tickers}

    direct = [e["ticker"] for e in ASSET_GROUPS["direct_oem_exposures"]]
    supplier = [e["ticker"] for e in ASSET_GROUPS["supplier_exposures"]]
    supplier_available = [t for t in supplier
                          if readouts.get(t, {}).get("status")
                          == "event_study_available"]

    if supplier_available:
        supplier_summary = (
            "Supplier legs computable: compare signs/magnitudes per horizon "
            "against the OEM legs - descriptively only."
        )
        cannot = (
            "No significance and no causal attribution - one strike window "
            "with confounded tape moves."
        )
    else:
        gaps = ", ".join(
            f"{t} ({readouts.get(t, {}).get('pre_event_distinct_dates', 0)} "
            f"pre-event dates cached)"
            for t in supplier
        )
        supplier_summary = (
            "The supplier transmission is NOT currently computable locally: "
            f"{gaps}. The cached supplier windows do not cover the 60 "
            "pre-event bars the gate requires, so the only readable "
            "comparison today is the intra-OEM contrast (GM vs F). A "
            "bounded, separately-approved free cache backfill (~85 bars per "
            "supplier around 2023-09-15) would close this gap."
        )
        cannot = (
            "The supplier-vs-OEM question itself - the supplier legs lack "
            "pre-event local history at this date; plus no significance and "
            "no causal attribution in any case."
        )

    comparison = {
        "direct_oem_pattern": _pattern_string(readouts, direct),
        "supplier_pattern": _pattern_string(readouts, supplier),
        "supplier_vs_oem_summary": supplier_summary,
        "delayed_or_buffered_channel_note": (
            "OEM equity reads are buffered by finished-vehicle inventory and "
            "priced on expected duration; supplier volume pass-through can "
            "be sharper but arrives through order flow with a lag and is "
            "diversified across customers."
        ),
        "what_can_be_read": (
            "Descriptive n=1 windows for the staged OEM legs (GM and F) vs "
            "SPY, read under the partial-anticipation caveat - including "
            "the intra-OEM contrast between the two."
        ),
        "what_cannot_be_read": cannot,
    }

    return {
        "packet_status": "ok",
        "denominators": denoms,
        "candidate": candidate,
        "asset_groups": ASSET_GROUPS,
        "local_price_data_flags": flags,
        "local_readouts": readouts,
        "comparison": comparison,
        "mechanism_chain": dict(MECHANISM_CHAIN),
        "falsifiers_or_limits": list(FALSIFIERS_OR_LIMITS),
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(pkt: dict[str, Any]) -> str:
    lines = ["UAW supplier-transmission packet (read-only, staged/no-paid)", ""]
    c = pkt["candidate"]
    if pkt["packet_status"] != "ok":
        lines.append(f"Packet status: {pkt['packet_status']}")
        return "\n".join(lines)
    d = pkt["denominators"]
    lines.append(
        f"Candidate #{c['event_id']} {c['date']} [{c['mechanism_family']}] "
        f"stage={c['stage']} staged/no-paid={c['staged_no_paid']}"
    )
    lines.append(f"  {c['headline']}")
    lines.append(
        f"Event-date caveat: {c['event_date_quality']} "
        f"(risk: {c['anticipation_risk']}) - "
        f"{c['horizon_interpretation_caution']}"
    )
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}"
    )
    lines.append("")
    lines.append("Direct vs supplier legs:")
    for group, tag in (("direct_oem_exposures", "direct"),
                       ("supplier_exposures", "supplier"),
                       ("context_assets", "context"),
                       ("excluded_assets", "excluded")):
        for e in pkt["asset_groups"][group]:
            t = e["ticker"]
            ro = pkt["local_readouts"].get(t, {})
            flag = pkt["local_price_data_flags"].get(t)
            lines.append(
                f"  [{tag:<9}] {t:<5} local_data={str(flag):<5} "
                f"pre_event_dates={ro.get('pre_event_distinct_dates', '-'):<4} "
                f"{e['note']}"
            )
    lines.append("")
    lines.append("Descriptive readouts (n=1 vs SPY; partial-anticipation caveat):")
    for t, ro in pkt["local_readouts"].items():
        if ro["status"] == "event_study_available":
            hs = " ".join(f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                          for h in ro["horizons"])
            lines.append(f"  {t:<5} {hs}")
        else:
            reasons = ",".join(ro["blocking_reasons"]) or ro["status"]
            lines.append(f"  {t:<5} not computable ({reasons})")
    lines.append("")
    cmp_ = pkt["comparison"]
    lines.append("Direct-vs-supplier read:")
    lines.append(f"  OEM:      {cmp_['direct_oem_pattern']}")
    lines.append(f"  Supplier: {cmp_['supplier_pattern']}")
    lines.append(f"  Summary:  {cmp_['supplier_vs_oem_summary']}")
    lines.append(f"  Channel:  {cmp_['delayed_or_buffered_channel_note']}")
    lines.append(f"  Can read: {cmp_['what_can_be_read']}")
    lines.append(f"  Cannot:   {cmp_['what_cannot_be_read']}")
    lines.append("")
    lines.append("Mechanism chain:")
    for k, v in pkt["mechanism_chain"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Interpretation limits:")
    for f in pkt["falsifiers_or_limits"]:
        lines.append(f"  - {f}")
    lines.append("")
    lines.append("What this adds to the labor family:")
    lines.append(
        "  It converts C2's 'supplier legs exist locally' into a precise "
        "statement: the OEM legs are readable now (including the GM-vs-F "
        "contrast), while the supplier channel needs a bounded pre-event "
        "backfill before it can be read at all - a concrete, no-paid next "
        "step instead of a vague aspiration."
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
            "Read-only UAW supplier-transmission packet for staged candidate "
            "313: direct OEM legs vs supplier channel, with honest local-"
            "data gaps. No DB write, no provider call, no paid analysis, no "
            "promotion."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--candidate-id", dest="candidate_id", type=int,
                   default=DEFAULT_CANDIDATE)
    p.add_argument("--limit", type=int, default=0,
                   help="Cap the number of tickers given full readouts "
                        "(0 = all).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    pkt = build_packet(db_path=args.db_path, candidate_id=args.candidate_id,
                       limit=args.limit)
    if args.json:
        print(_render_json(pkt), file=output)
    else:
        print(_render_text(pkt), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

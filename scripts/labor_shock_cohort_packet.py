#!/usr/bin/env python3
"""Read-only labor-shock cohort packet (goods production vs media pipeline).

Compares the staged ``labor_inflation`` candidates as a transmission family:
how an auto assembly strike (immediate physical output interruption, wage-cost
bargaining, inventory buffers) differs from a media labor disruption (content
pipeline delays whose financial impact lags the event window) - with the C4
event-date quality layer consumed as the anchor-label source, never hardcoded.

Discipline (non-negotiable):

  * Staged ``z1a_candidate_pack`` rows are review staging, NOT accepted
    evidence; nothing here promotes a candidate or changes a denominator.
  * Event-window numbers are descriptive n=1 point estimates; placing two
    cases side by side is a research view, not family-level inference.
  * Asset maps are conservative: every named ticker carries a computed
    ``local_price_data`` flag, and names outside the staged rows are labeled
    second-order/excluded rather than silently added.
  * Read-only: ``mode=ro`` connections only; no provider, no paid call.

Usage::

    python scripts/labor_shock_cohort_packet.py --db-path events.db --json
    python scripts/labor_shock_cohort_packet.py --db-path events.db
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

FAMILY = "labor_inflation"

TAXONOMY_BUCKETS: tuple[str, ...] = (
    "production_disruption", "wage_cost_pressure",
    "content_pipeline_disruption", "bargaining_power_shift",
    "supplier_or_inventory_buffer", "other_or_manual_review",
)

# Curated case registry. Asset categories name only mechanism-linked tickers;
# local_price_data is computed live and unsupported names stay flagged.
CASE_REGISTRY: dict[int, dict[str, Any]] = {
    313: {
        "labor_subtype": (
            "production_disruption / wage_cost_pressure "
            "(supplier_or_inventory_buffer second-order)"
        ),
        "mechanism_chain": (
            "Simultaneous targeted plant stoppages at the Detroit automakers "
            "-> immediate output interruption at struck plants + structural "
            "wage-cost pressure from the eventual settlement; transmission "
            "is buffered by finished-vehicle inventory and staggered plant "
            "selection ('Stand Up' escalation)."
        ),
        "asset_map": {
            "direct_exposures": [
                {"ticker": "GM", "note": "struck automaker; staged primary"},
                {"ticker": "F", "note": "struck automaker; staged exposed leg"},
            ],
            "second_order_exposures": [
                {"ticker": "LEA", "note": "seating supplier - volume pass-through"},
                {"ticker": "APTV", "note": "electrical/harness supplier - volume pass-through"},
                {"ticker": "BWA", "note": "drivetrain supplier - volume pass-through"},
            ],
            "noisy_or_context_assets": [
                {"ticker": "XLY", "note": "consumer-discretionary context; factor, not mechanism"},
                {"ticker": "SPY", "note": "benchmark only"},
            ],
            "excluded_assets": [
                {"ticker": "STLA", "note": "third struck automaker - NOT on the "
                                           "staged row; adding it silently would "
                                           "alter the staged contract"},
                {"ticker": "TSLA", "note": "non-union peer - not mechanism-linked"},
            ],
        },
        "falsifiers_or_limits": (
            "Telegraphed deadline = partial anticipation; targeted (not "
            "full) stoppage mutes the output shock; inventory buffers delay "
            "margin impact past the 20d window; supplier legs are not "
            "staged."
        ),
    },
    314: {
        "labor_subtype": "content_pipeline_disruption / wage_cost_pressure",
        "mechanism_chain": (
            "Performers' strike order halts scripted production -> content "
            "pipeline delays and release-slate gaps; near-term cash costs "
            "FALL (production paused) while the revenue impact arrives "
            "quarters later - so the event window measures repricing of a "
            "lagged, partly offsetting mechanism."
        ),
        "asset_map": {
            "direct_exposures": [
                {"ticker": "NFLX", "note": "streamer; staged primary"},
                {"ticker": "WBD", "note": "studio/streamer; staged exposed leg"},
            ],
            "second_order_exposures": [
                {"ticker": "DIS", "note": "struck studio - not staged on the row"},
                {"ticker": "PARA", "note": "struck studio - not staged on the row"},
            ],
            "noisy_or_context_assets": [
                {"ticker": "SPY", "note": "benchmark only"},
            ],
            "excluded_assets": [
                {"ticker": "CMCSA", "note": "diversified parent - strike channel "
                                            "diluted by broadband/parks"},
            ],
        },
        "falsifiers_or_limits": (
            "The order 'taking effect' is the culmination of an earlier "
            "vote/announcement (weak anchor); paused production cuts "
            "near-term cash costs, partly offsetting the disruption; "
            "library depth shields streamers inside the event window."
        ),
    },
}

_UNKNOWN_CASE = {
    "labor_subtype": "other_or_manual_review",
    "mechanism_chain": (
        "No curated mechanism map for this labor row - manual review before "
        "any cohort use."
    ),
    "asset_map": None,  # built from the staged tickers only
    "falsifiers_or_limits": "Unreviewed labor row; classify before use.",
}

NON_CLAIMS: tuple[str, ...] = (
    "Staged candidates are not accepted evidence and never enter accepted "
    "denominators (denominators unchanged).",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No candidate promotion, no stage change, no event_hygiene change.",
    "Event-window numbers are descriptive n=1 point estimates: no CI, "
    "p-value, FDR, or single-event significance.",
    "Two cases side by side are a research view, not family-level inference "
    "and not evidence of a labor-shock edge of any kind.",
    "Mechanism chains and subtypes are research taxonomy, illustrative and "
    "to be tested, not established causal claims.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _exposed_tickers(path: str, ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
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
        symbols: list[str] = []
        try:
            parsed = json.loads(r["market_tickers"] or "[]")
        except (TypeError, ValueError):
            parsed = []
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict):
                    sym = entry.get("symbol")
                    if isinstance(sym, str) and sym.strip():
                        symbols.append(sym.strip().upper())
        out[r["id"]] = symbols
    return out


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


def _cohort_use(label: str) -> str:
    if label == "scheduled_or_weak_anchor":
        return "weak_anchor_only"
    if label in ("duplicate_or_deferred", "manual_review_needed"):
        return "no_paid_review_only"
    return "usable_with_caution"


def _build_asset_map(spec_map: dict | None, exposed: list[str],
                     *, db_path: str) -> dict:
    if spec_map is None:
        spec_map = {
            "direct_exposures": [
                {"ticker": t, "note": "staged ticker"} for t in exposed
            ],
            "second_order_exposures": [],
            "noisy_or_context_assets": [],
            "excluded_assets": [],
        }
    out: dict[str, Any] = {}
    for cat in ("direct_exposures", "second_order_exposures",
                "noisy_or_context_assets", "excluded_assets"):
        out[cat] = [
            {**entry, "local_price_data": _has_local_prices(db_path, entry["ticker"])}
            for entry in spec_map.get(cat, [])
        ]
    out["note"] = (
        "Names outside the staged row are second-order/excluded hypotheses; "
        "local_price_data=false means not measurable without a "
        "separately-approved free cache backfill."
    )
    return out


# ---------------------------------------------------------------------------
# Packet composer
# ---------------------------------------------------------------------------


def build_packet(*, db_path: str | None = None, limit: int = 0) -> dict[str, Any]:
    """Build the labor-shock cohort packet. Read-only."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    edq = edq_build_report(db_path=path, lens="all", limit=0)
    events = edq["events"]
    labor_rows = [e for e in events if e["mechanism_family"] == FAMILY]

    ids = [e["event_id"] for e in labor_rows]
    exposed_by_id = _exposed_tickers(path, ids)

    cases: list[dict] = []
    for e in sorted(labor_rows, key=lambda x: x["event_id"]):
        spec = CASE_REGISTRY.get(e["event_id"], _UNKNOWN_CASE)
        exposed = exposed_by_id.get(e["event_id"], [])
        primary = exposed[0] if exposed else None
        label = e["event_date_quality"]
        cases.append({
            "event_id": e["event_id"],
            "date": e["date"],
            "headline": e["headline"],
            "stage": e["stage"],
            "corpus_status": e["corpus_status"],
            "mechanism_family": e["mechanism_family"],
            "labor_subtype": spec["labor_subtype"],
            "primary_ticker": primary,
            "exposed_tickers": exposed,
            "event_date_quality": label,
            "anticipation_risk": e["anticipation_risk"],
            "thread_independence": e["thread_independence"],
            "local_readout": _local_readout(e["event_id"], e["date"], primary,
                                            db_path=path),
            "mechanism_chain": spec["mechanism_chain"],
            "asset_proxy_map": _build_asset_map(spec["asset_map"], exposed,
                                                db_path=path),
            "falsifiers_or_limits": spec["falsifiers_or_limits"],
            "cohort_use": _cohort_use(label),
        })

    included = [c["event_id"] for c in cases if c["corpus_status"] == "staged"
                and c["cohort_use"] != "no_paid_review_only"]
    deferred = [c["event_id"] for c in cases
                if c["cohort_use"] == "no_paid_review_only"]

    capped = max(int(limit), 0)
    surfaced = cases[:capped] if capped else cases

    taxonomy = {bucket: sorted(
        c["event_id"] for c in cases if bucket in c["labor_subtype"]
    ) for bucket in TAXONOMY_BUCKETS}

    goods = next((c["event_id"] for c in cases
                  if "production_disruption" in c["labor_subtype"]), None)
    media = next((c["event_id"] for c in cases
                  if "content_pipeline_disruption" in c["labor_subtype"]), None)

    edq_denoms = edq["denominators"]
    labor_accepted = sum(1 for e in labor_rows
                         if e["corpus_status"] in ("accepted", "curated"))
    labor_staged = sum(1 for e in labor_rows
                       if e["corpus_status"] == "staged")

    return {
        "denominators": {
            "archive_rows": edq_denoms["archive_rows"],
            "accepted_coverage_denominator":
                edq_denoms["accepted_coverage_denominator"],
            "accepted_track_record_denominator":
                edq_denoms["accepted_track_record_denominator"],
            "staged_candidate_count": edq_denoms["staged_candidate_count"],
            "labor_staged_count": labor_staged,
            "labor_accepted_count": labor_accepted,
            "note": (
                "Accepted vs staged stay separated; the labor cohort is "
                "review staging only and enters no accepted denominator."
            ),
        },
        "cohort_scope": {
            "family": FAMILY,
            "included_staged_ids": included,
            "deferred_ids": deferred,
            "pending_related_ids": [],
            "excluded_reasoning": (
                "Cases classified duplicate or manual-review by the C4 layer "
                "drop to no_paid_review_only and never count as usable "
                "anchors."
            ),
        },
        "cases": surfaced,
        "family_taxonomy": taxonomy,
        "comparison_readout": {
            "goods_production_case": goods,
            "media_content_case": media,
            "what_comparison_can_show": (
                "How the SAME family label transmits differently: an auto "
                "strike interrupts physical output immediately (buffered by "
                "inventory), while a media labor stoppage delays a content "
                "pipeline whose financial impact lags the event window - "
                "two descriptive n=1 windows read with different "
                "anchor-quality caveats."
            ),
            "what_comparison_cannot_show": (
                "No pooled statistic, no significance, no causal attribution "
                "- two staged cases with different anchor quality cannot "
                "support family-level inference, and staged rows are not "
                "accepted evidence."
            ),
        },
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(pkt: dict[str, Any]) -> str:
    d = pkt["denominators"]
    scope = pkt["cohort_scope"]
    lines = ["Labor-shock cohort packet (read-only, staged/no-paid)", ""]
    lines.append(
        f"Denominators: archive {d['archive_rows']} | accepted coverage "
        f"{d['accepted_coverage_denominator']} | track-record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | labor staged "
        f"{d['labor_staged_count']} / accepted {d['labor_accepted_count']}"
    )
    lines.append(f"Scope: included {scope['included_staged_ids']} | "
                 f"deferred {scope['deferred_ids']}")
    lines.append("")
    lines.append("Cohort cases (event-date quality from the C4 layer):")
    for c in pkt["cases"]:
        lines.append(
            f"  #{c['event_id']} {c['date']} "
            f"{'/'.join(c['exposed_tickers']) or '-':<10} "
            f"{c['event_date_quality']:<28} use={c['cohort_use']}"
        )
        lines.append(f"      subtype: {c['labor_subtype']}")
        lines.append(f"      {c['mechanism_chain']}")
        ro = c["local_readout"]
        if ro and ro["available"]:
            parts = " ".join(
                f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                for h in ro["horizons"]
            )
            lines.append(f"      AR vs SPY (descriptive n=1, primary "
                         f"{c['primary_ticker']}): {parts}")
        else:
            lines.append("      AR vs SPY: not locally computable")
        amap = c["asset_proxy_map"]
        for cat, tag in (("direct_exposures", "direct"),
                         ("second_order_exposures", "2nd-order"),
                         ("noisy_or_context_assets", "context"),
                         ("excluded_assets", "excluded")):
            for e in amap[cat]:
                lines.append(
                    f"      [{tag:<9}] {e['ticker']:<6} "
                    f"local_data={str(e['local_price_data']):<5} {e['note']}"
                )
        lines.append(f"      limits: {c['falsifiers_or_limits']}")
    lines.append("")

    cr = pkt["comparison_readout"]
    lines.append("Goods production vs media/content pipeline:")
    lines.append(f"  goods case: #{cr['goods_production_case']} | "
                 f"media case: #{cr['media_content_case']}")
    lines.append(f"  Can show:    {cr['what_comparison_can_show']}")
    lines.append(f"  Cannot show: {cr['what_comparison_cannot_show']}")
    lines.append("")
    lines.append("What this family adds:")
    lines.append(
        "  The accepted archive has zero labor rows; these staged cases "
        "would add a wage-cost / production-disruption transmission channel "
        "- the furthest mechanism from the existing tariff/sanction/"
        "regulation coverage - with a built-in goods-vs-services contrast."
    )
    lines.append("")
    lines.append("Why this is still staged/no-paid:")
    lines.append(
        "  Both cases remain review staging - excluded from accepted "
        "denominators; 313 carries a partial-anticipation caveat and 314 a "
        "scheduled/weak-anchor caveat from the C4 layer; supplier and "
        "studio second-order legs are not staged; no paid analysis is "
        "approved and no candidate is promoted."
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
            "Read-only labor-shock cohort packet over the staged "
            "labor_inflation cases, consuming the C4 event-date quality "
            "layer. No DB write, no provider call, no paid analysis, no "
            "promotion."
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

#!/usr/bin/env python3
"""Read-only paid-gate packet for one staged candidate.

Builds a reproducible, no-paid review packet answering: is this staged
candidate mature enough to be CONSIDERED for a future, separately-approved
paid analysis? It never runs that analysis. The gate it emits is
``blocked_by_default`` and cannot be satisfied by anything in this script —
only a future task carrying the explicit operator phrase (plus a fresh
backup and a dry run) could open it.

Discipline (non-negotiable):

  * Read-only: one ``mode=ro`` connection; the optional event-study readout
    reuses the same SELECT-only gate as the coverage report and degrades to
    ``unavailable``. No DB write, no provider client, no paid credential,
    no LLM, no network. Safe to run repeatedly.
  * A staged ``z1a_candidate_pack`` row is review staging — not accepted
    evidence, excluded from every accepted denominator. If the candidate is
    no longer staged, the packet marks itself blocked rather than carrying on.
  * Event-window numbers are descriptive n=1 point estimates: no significance,
    no causal certainty, not a recommendation to transact in anything.
  * Asset/proxy classification is conservative: names without local price
    data are flagged ``local_price_data: false`` instead of being presented
    as measurable.

Usage::

    python scripts/candidate_paid_gate_packet.py --candidate-id 304 --db-path events.db --json
    python scripts/candidate_paid_gate_packet.py --candidate-id 304 --db-path events.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - stage constants + DB_FILE

_CANDIDATE_STAGE = "z1a_candidate_pack"
_DATE_WINDOW_DAYS = 10

_SEPARATION_NOTE = (
    "Staged z1a_candidate_pack rows are review staging, not accepted "
    "evidence; they are excluded from every accepted-corpus denominator "
    "(coverage 94-lens and track-record 86-lens both unaffected by this "
    "packet)."
)

NON_CLAIMS: tuple[str, ...] = (
    "No paid analysis was performed and none is approved by this packet; "
    "paid /analyze remains blocked.",
    "No promotion: the candidate stays staged and no stage or event_hygiene "
    "row was changed.",
    "A staged candidate is not accepted evidence and is excluded from every "
    "accepted denominator (denominators unchanged).",
    "The local event-window readout is a descriptive n=1 point estimate: no "
    "confidence interval, no p-value, no FDR, no significance claim.",
    "Nothing here is a recommendation to transact in any instrument; this "
    "packet is not a recommendation of any trade or position.",
    "Mechanism chains and asset maps are research hypotheses to be tested, "
    "not established causal claims.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)

# Per-candidate curated packet content. Only candidates that received a
# written no-paid review (stats/STAGED_CANDIDATE_SHORTLIST.md) get an entry;
# build_packet refuses to invent content for anything else.
CANDIDATE_REGISTRY: dict[int, dict[str, Any]] = {
    304: {
        "research_question": (
            "Did the 2023-01-24 DOJ ad-tech complaint reprice "
            "structural-remedy (divestiture) risk on GOOGL, and did any "
            "mechanism-linked ad-tech name show a consistent second-order "
            "reaction - as descriptive n=1 event-window evidence for the "
            "regulation family?"
        ),
        "mechanism_chain": {
            "event": (
                "DOJ + 8 states file in the Eastern District of Virginia "
                "(2023-01-24) alleging Google monopolizes the ad-tech stack "
                "(publisher ad server, ad exchange, advertiser network), "
                "seeking divestiture - a structural remedy."
            ),
            "first_order_channel": (
                "Regulatory/legal overhang reprices GOOGL equity: the "
                "complaint puts forced-divestiture risk on the ads business."
            ),
            "second_order_channels": [
                "Independent ad-tech competitors could reprice on a "
                "prospective forced divestiture opening the stack "
                "(possible, not locally measurable yet).",
                "The other digital-ads scale player (META) is ambiguous: "
                "shared regulatory risk vs competitive relief.",
                "Publishers/advertisers are long-dated and diffuse - too "
                "noisy for an event-window read.",
            ],
            "horizons": "1d / 5d / 20d event windows vs SPY",
            "what_would_be_measured": (
                "Whether GOOGL's event-window move is idiosyncratic rather "
                "than broad-tech-factor driven, and whether mechanism-linked "
                "second-order names moved consistently - all descriptive "
                "n=1 readouts, never significance."
            ),
        },
        # Conservative classification; local_price_data is computed live.
        "asset_map": {
            "primary_defendant": [
                {"ticker": "GOOGL", "note": "named defendant; staged primary"},
            ],
            "potential_second_order_assets": [
                {"ticker": "TTD", "note": "independent ad-tech (demand side) - "
                                          "possible divestiture beneficiary"},
                {"ticker": "PUBM", "note": "independent ad-tech (sell side) - "
                                           "possible divestiture beneficiary"},
                {"ticker": "MGNI", "note": "independent ad-tech (sell side) - "
                                           "possible divestiture beneficiary"},
                {"ticker": "META", "note": "digital-ads scale peer - direction "
                                           "ambiguous (shared risk vs relief)"},
            ],
            "noisy_or_context_assets": [
                {"ticker": "SPY", "note": "benchmark only"},
                {"ticker": "XLK", "note": "broad tech context; factor confound, "
                                          "not a mechanism asset"},
            ],
            "excluded_assets": [
                {"ticker": "GOOG", "note": "same economics as GOOGL (share "
                                           "class) - double counting"},
            ],
            "eligibility_notes": (
                "Second-order names are mechanism-linked hypotheses, not "
                "accepted assets: none currently has local price data, so "
                "none is measurable without a separately-approved free-cache "
                "backfill. Names with local_price_data=false must not appear "
                "in any readout until that changes. The map is deliberately "
                "small; an unsupported ticker would be fake sophistication."
            ),
        },
        "falsifiers": [
            "Remedy risk is too long-dated: years of litigation discount the "
            "divestiture to roughly zero at event horizons.",
            "Broad tech factor confound: Jan-2023 tech-tape moves explain the "
            "window, not the complaint.",
            "GOOGL's move is not idiosyncratic once benchmarked (SPY/tech "
            "beta absorbs it).",
            "Second-order ad-tech proxies are small-cap and noisy; their "
            "windows carry idiosyncratic earnings/flow noise.",
            "The market treats the lawsuit as low-probability or already "
            "priced, so nothing reprices on the filing date.",
        ],
        "thread_keywords": ("google", "alphabet", "ad-tech", "ad tech",
                            "adtech", "advertising"),
        "thread_ticker_prefix": "GOOG",
    },
}


# ---------------------------------------------------------------------------
# Read-only DB access
# ---------------------------------------------------------------------------


def _candidate_stage_name() -> str:
    stage = getattr(db, "CANDIDATE_PACK_STAGE", _CANDIDATE_STAGE)
    return stage if isinstance(stage, str) else _CANDIDATE_STAGE


def _load_events(path: str) -> list[dict]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, event_date, stage, mechanism_family, headline, "
                "market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "event_date": (r["event_date"] or "")[:10],
            "stage": r["stage"] if isinstance(r["stage"], str) else None,
            "family": (r["mechanism_family"] or "").strip().lower() or "none",
            "headline": r["headline"] or "",
            "primary_ticker": _primary_ticker(r["market_tickers"]),
        })
    return out


def _primary_ticker(raw: Any) -> str | None:
    if not raw:
        return None
    parsed = raw
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if isinstance(entry, dict):
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                return sym.strip().upper()
    return None


def _has_local_prices(path: str, ticker: str) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        try:
            row = conn.execute(
                "SELECT 1 FROM price_cache WHERE ticker = ? LIMIT 1", (ticker,),
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None
    finally:
        conn.close()


def _db_sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Packet sections
# ---------------------------------------------------------------------------


def _local_readout(row: dict, *, db_path: str) -> dict:
    """Descriptive per-horizon readout via the existing SELECT-only gate."""
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
        "id": row["id"],
        "event_date": row["event_date"],
        "market_tickers": (
            [{"symbol": row["primary_ticker"]}] if row["primary_ticker"] else []
        ),
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
    horizons = []
    for h in out.get("per_horizon") or []:
        if isinstance(h, dict):
            horizons.append({
                "horizon": h.get("horizon"),
                "abnormal_return": h.get("abnormal_return"),
                "sar": h.get("sar"),
                "car": h.get("car"),
            })
    return {**base, "available": bool(horizons), "horizons": horizons}


def _duplicate_thread_check(row: dict, all_rows: list[dict], spec: dict) -> dict:
    """Mechanical duplicate / thread scan over local rows only."""
    others = [r for r in all_rows if r["id"] != row["id"]]
    keywords = spec.get("thread_keywords", ())
    prefix = spec.get("thread_ticker_prefix", "")

    def _brief(r: dict) -> dict:
        return {"event_id": r["id"], "event_date": r["event_date"],
                "stage": r["stage"], "headline": r["headline"][:80]}

    exact = [
        r for r in others
        if r["event_date"] == row["event_date"]
        and (r["primary_ticker"] == row["primary_ticker"]
             or r["headline"].strip().lower() == row["headline"].strip().lower())
    ]
    siblings = [r for r in others if r["family"] == row["family"]]
    keyword_rows = [
        r for r in others
        if any(k in r["headline"].lower() for k in keywords)
        or (prefix and (r["primary_ticker"] or "").startswith(prefix))
    ]
    neighbors = []
    try:
        anchor = _date.fromisoformat(row["event_date"])
        for r in others:
            try:
                d = _date.fromisoformat(r["event_date"])
            except ValueError:
                continue
            if abs((d - anchor).days) <= _DATE_WINDOW_DAYS:
                neighbors.append(r)
    except ValueError:
        pass

    if exact:
        conclusion = (
            "exact_duplicate_present_defer: a same-date row shares the "
            "primary ticker or headline - resolve before any paid step."
        )
    else:
        conclusion = (
            "distinct_no_exact_duplicate: no same-date ticker/headline "
            "collision; keyword and family matches listed for human review."
        )
    return {
        "exact_duplicate_found": bool(exact),
        "exact_duplicates": [_brief(r) for r in exact],
        "near_thread_siblings": [_brief(r) for r in siblings],
        "existing_google_antitrust_rows": [_brief(r) for r in keyword_rows],
        "date_window_neighbors": [_brief(r) for r in neighbors],
        "conclusion": conclusion,
    }


def _asset_proxy_map(spec: dict, *, db_path: str) -> dict:
    amap = spec["asset_map"]
    out: dict[str, Any] = {}
    for cat in ("primary_defendant", "potential_second_order_assets",
                "noisy_or_context_assets", "excluded_assets"):
        out[cat] = [
            {
                "ticker": e["ticker"],
                "note": e["note"],
                "local_price_data": _has_local_prices(db_path, e["ticker"]),
                "status": ("staged_primary" if cat == "primary_defendant"
                           else "possible_no_paid" if cat == "potential_second_order_assets"
                           else "context_only" if cat == "noisy_or_context_assets"
                           else "excluded"),
            }
            for e in amap[cat]
        ]
    out["eligibility_notes"] = amap["eligibility_notes"]
    return out


def _paid_gate(candidate_id: int) -> dict:
    return {
        "status": "blocked_by_default",
        "future_required_operator_phrase": (
            f"I approve a single paid /analyze run for candidate {candidate_id} "
            f"after a fresh verified events.db backup and a passing dry run."
        ),
        "backup_required": True,
        "dry_run_required": True,
        "expected_mutation_scope": (
            "A future paid /analyze (headline-mode) would create one NEW "
            "analyzed events row at the classify stage; the staged candidate "
            "row itself stays untouched and is never auto-promoted. Free "
            "cache backfills, if any, would add price_cache rows only."
        ),
        "stop_conditions": [
            "events.db SHA-256 differs from the fresh backup baseline",
            "candidate row is no longer staged z1a_candidate_pack",
            "an exact duplicate row appears for the same announcement",
            "any accepted denominator would change",
            "operator phrase absent or paraphrased",
        ],
    }


def _blocked_packet(candidate_id: int, status: str, *, db_path: str,
                    candidate: dict | None = None) -> dict:
    return {
        "packet_status": status,
        "candidate": candidate or {
            "id": candidate_id, "stage": None, "date": None, "headline": None,
            "mechanism_family": None, "primary_ticker": None,
            "staged_no_paid": False, "separation_note": _SEPARATION_NOTE,
        },
        "repo_data_status": _repo_data_status(db_path),
        "paid_gate": _paid_gate(candidate_id),
        "non_claims": list(NON_CLAIMS),
        "recommendation": {
            "decision": "defer_paid_analysis",
            "rationale": (
                "Packet is blocked: the candidate is missing, unregistered, "
                "or no longer staged - no paid step can be considered."
            ),
        },
    }


def _repo_data_status(db_path: str) -> dict:
    return {
        "db_read_only": True,
        "db_sha256": _db_sha256(db_path),
        "paid_calls_made": False,
        "analyze_ran": False,
    }


# ---------------------------------------------------------------------------
# Packet composer
# ---------------------------------------------------------------------------


def build_packet(candidate_id: int, *, db_path: str | None = None) -> dict:
    """Build the read-only paid-gate packet for ``candidate_id``."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    rows = _load_events(path) if path else []
    row = next((r for r in rows if r["id"] == candidate_id), None)

    if row is None:
        return _blocked_packet(candidate_id, "candidate_not_found", db_path=path or "")
    spec = CANDIDATE_REGISTRY.get(candidate_id)
    if spec is None:
        return _blocked_packet(candidate_id, "no_packet_registered", db_path=path)

    staged = row["stage"] == _candidate_stage_name()
    candidate = {
        "id": row["id"],
        "stage": row["stage"],
        "date": row["event_date"],
        "headline": row["headline"][:120],
        "mechanism_family": row["family"],
        "primary_ticker": row["primary_ticker"],
        "staged_no_paid": staged,
        "separation_note": _SEPARATION_NOTE,
    }
    if not staged:
        return _blocked_packet(
            candidate_id, "blocked_candidate_not_staged",
            db_path=path, candidate=candidate,
        )

    readout = _local_readout(row, db_path=path)
    dup = _duplicate_thread_check(row, rows, spec)

    if dup["exact_duplicate_found"]:
        decision = "defer_paid_analysis"
        rationale = ("An exact same-date duplicate exists locally; resolve it "
                     "before any paid consideration.")
    elif not readout["available"]:
        decision = "requires_more_no_paid_review"
        rationale = ("The local event-study readout is unavailable, so the "
                     "no-paid evidence base is incomplete; extend the free "
                     "local review before designing any paid gate.")
    else:
        decision = "eligible_for_future_paid_gate_design_only"
        rationale = (
            "Staged, mechanically distinct, and locally readable (descriptive "
            "n=1 windows exist). Eligible only for DESIGNING a future paid "
            "gate; the gate itself stays blocked until the explicit operator "
            "phrase, a fresh backup, and a dry run all exist."
        )

    return {
        "packet_status": "ok",
        "candidate": candidate,
        "repo_data_status": _repo_data_status(path),
        "research_question": spec["research_question"],
        "local_readout": readout,
        "duplicate_thread_check": dup,
        "mechanism_chain": spec["mechanism_chain"],
        "asset_proxy_map": _asset_proxy_map(spec, db_path=path),
        "falsifiers": list(spec["falsifiers"]),
        "paid_gate": _paid_gate(candidate_id),
        "non_claims": list(NON_CLAIMS),
        "recommendation": {"decision": decision, "rationale": rationale},
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(pkt: dict) -> str:
    c = pkt["candidate"]
    lines = ["Candidate paid-gate packet (read-only, no-paid)", ""]
    lines.append(f"Packet status: {pkt['packet_status']}")
    lines.append(
        f"Candidate #{c['id']}: stage={c['stage']} date={c['date']} "
        f"family={c['mechanism_family']} primary={c['primary_ticker']} "
        f"staged/no-paid={c['staged_no_paid']}"
    )
    lines.append(f"  {c['separation_note']}")
    if pkt["packet_status"] == "ok":
        lines.append("")
        lines.append(f"Research question: {pkt['research_question']}")
        ro = pkt["local_readout"]
        lines.append("")
        lines.append(f"Local readout (descriptive n=1 only; available={ro['available']}):")
        for h in ro["horizons"]:
            lines.append(
                f"  {h['horizon']:>2}d  AR={h['abnormal_return']:+.4f} "
                f"SAR={h['sar']:+.4f} CAR={h['car']:+.4f}"
            )
        dup = pkt["duplicate_thread_check"]
        lines.append("")
        lines.append(f"Duplicate/thread: {dup['conclusion']}")
        lines.append(
            f"  exact={len(dup['exact_duplicates'])} "
            f"family-siblings={len(dup['near_thread_siblings'])} "
            f"keyword-rows={len(dup['existing_google_antitrust_rows'])} "
            f"date-neighbors={len(dup['date_window_neighbors'])}"
        )
        lines.append("")
        lines.append("Asset/proxy map (conservative; unmeasurable names flagged):")
        amap = pkt["asset_proxy_map"]
        for cat in ("primary_defendant", "potential_second_order_assets",
                    "noisy_or_context_assets", "excluded_assets"):
            for e in amap[cat]:
                lines.append(
                    f"  [{e['status']:<16}] {e['ticker']:<6} "
                    f"local_price_data={str(e['local_price_data']):<5} {e['note']}"
                )
        lines.append(f"  {amap['eligibility_notes']}")
        lines.append("")
        lines.append("Falsifiers / failure modes:")
        for f in pkt["falsifiers"]:
            lines.append(f"  - {f}")
    gate = pkt["paid_gate"]
    lines.append("")
    lines.append(f"Paid gate: {gate['status']} (backup_required={gate['backup_required']}, "
                 f"dry_run_required={gate['dry_run_required']})")
    lines.append(f"  Future operator phrase required: \"{gate['future_required_operator_phrase']}\"")
    for s in gate["stop_conditions"]:
        lines.append(f"  stop: {s}")
    rec = pkt["recommendation"]
    lines.append("")
    lines.append(f"Decision: {rec['decision']}")
    lines.append(f"  {rec['rationale']}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in pkt["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(pkt: dict) -> str:
    return json.dumps(pkt, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only paid-gate packet for one staged candidate. No paid "
            "call, no DB write, no promotion; the emitted gate is blocked by "
            "default and only a future explicit operator approval (plus "
            "backup + dry run) could open it."
        ),
    )
    p.add_argument("--candidate-id", dest="candidate_id", type=int, required=True)
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    pkt = build_packet(args.candidate_id, db_path=args.db_path)
    if args.json:
        print(_render_json(pkt), file=output)
    else:
        print(_render_text(pkt), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

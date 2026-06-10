#!/usr/bin/env python3
"""Read-only backfill gate/design for the UAW supplier-transmission read (313).

C2A established the lesson; this gate makes it durable: **rows-exist is not
compute-ready**. LEA/APTV have cached price rows, but every row is 2026-dated,
so the 2023-09-15 event window has zero pre-event coverage and the supplier
legs of candidate 313 cannot be computed locally. This script measures that
gap precisely, defines the exact bounded write a future backfill would be
allowed to make, and lists the safety sequence any mutation must pass first.

This is the gate, not the backfill. Nothing here writes to the database,
calls a provider, or approves anything:

  * ``mode=ro`` connections only; the event-study gate is SELECT-only.
  * ``mutation_status`` is ``not_approved`` and the plan says the actual
    backfill requires separate operator approval.
  * Candidate 313 stays staged/no-paid; the gate blocks itself if the row is
    missing or no longer staged.
  * The bounded scope is two supplier tickers around one event window -
    derived from the benchmark trading calendar, never a full-history fetch.

Usage::

    python scripts/uaw_supplier_backfill_gate.py --db-path events.db --json
    python scripts/uaw_supplier_backfill_gate.py --db-path events.db
    python scripts/uaw_supplier_backfill_gate.py --db-path events.db \
        --event-id 313 --suppliers LEA,APTV
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - DB_FILE seam for the event-study gate
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402

DEFAULT_EVENT = 313
DIRECT_OEM_TICKERS: tuple[str, ...] = ("GM", "F")
DEFAULT_SUPPLIERS: tuple[str, ...] = ("LEA", "APTV")
BENCHMARK_TICKER = "SPY"
CONTEXT_TICKERS: tuple[str, ...] = (BENCHMARK_TICKER, "XLY")

# What the existing event-study gate actually needs around the event date.
REQUIRED_PRE_EVENT_BARS = 60   # estimation window
FORWARD_HORIZON_BARS = 20      # longest readout horizon
# H2 lesson: size backfill windows by trading days plus a holiday buffer.
PRE_BUFFER_BARS = 15
POST_BUFFER_BARS = 10

NON_CLAIMS: tuple[str, ...] = (
    "The supplier transmission for candidate 313 is not computable locally "
    "today - LEA/APTV have zero pre-event distinct dates before 2023-09-15.",
    "Rows-exist is not compute-ready: cached 2026-only supplier rows do not "
    "make the 2023 event window readable.",
    "No DB mutation occurred: this gate is read-only and approves no write "
    "to price_cache or any other table.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No provider/API call was made and none is approved by this gate.",
    "No candidate promotion, no stage change, no event_hygiene change; "
    "candidate 313 stays staged and outside every accepted denominator "
    "(denominators unchanged).",
    "No single-event significance: any readout is a descriptive n=1 point "
    "estimate with no CI, p-value, or FDR.",
    "No family-level inference: the direct-vs-supplier framing is research "
    "design, not a labor-family result.",
    "Not a recommendation of any kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _ro_connect(path: str) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _ticker_stats(path: str, ticker: str, event_date: str,
                  horizon_end: str) -> dict[str, Any]:
    out = {"local_row_count": 0, "min_date": None, "max_date": None,
           "pre_event_distinct_dates": 0, "forward_distinct_dates": 0}
    conn = _ro_connect(path)
    if conn is None:
        return out
    try:
        try:
            # Forward coverage only counts inside the bounded event window -
            # far-future rows must not satisfy event-window coverage.
            row = conn.execute(
                "SELECT COUNT(*), MIN(date), MAX(date), "
                "COUNT(DISTINCT CASE WHEN date < ? THEN date END), "
                "COUNT(DISTINCT CASE WHEN date >= ? AND date <= ? "
                "THEN date END) "
                "FROM price_cache WHERE ticker = ?",
                (event_date, event_date, horizon_end, ticker),
            ).fetchone()
        except sqlite3.Error:
            return out
        return {"local_row_count": int(row[0] or 0), "min_date": row[1],
                "max_date": row[2], "pre_event_distinct_dates": int(row[3] or 0),
                "forward_distinct_dates": int(row[4] or 0)}
    finally:
        conn.close()


def _benchmark_dates(path: str, event_date: str) -> tuple[list[str], list[str]]:
    """Distinct benchmark trading dates strictly before / after the event."""
    conn = _ro_connect(path)
    if conn is None:
        return [], []
    try:
        try:
            pre = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM price_cache "
                "WHERE ticker = ? AND date < ? ORDER BY date",
                (BENCHMARK_TICKER, event_date))]
            post = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM price_cache "
                "WHERE ticker = ? AND date > ? ORDER BY date",
                (BENCHMARK_TICKER, event_date))]
        except sqlite3.Error:
            return [], []
        return pre, post
    finally:
        conn.close()


def _weekdays(anchor: date, n_pre: int, n_post: int) -> tuple[list[str], list[str]]:
    pre: list[str] = []
    cur = anchor
    while len(pre) < n_pre:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            pre.append(cur.isoformat())
    pre.reverse()
    post: list[str] = []
    cur = anchor
    while len(post) < n_post:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            post.append(cur.isoformat())
    return pre, post


def _bounded_range(path: str, event_date: str) -> dict[str, Any]:
    """Derive the exact bounded calendar range a future backfill would cover."""
    need_pre = REQUIRED_PRE_EVENT_BARS + PRE_BUFFER_BARS
    need_post = FORWARD_HORIZON_BARS + POST_BUFFER_BARS
    pre, post = _benchmark_dates(path, event_date)
    if len(pre) >= need_pre and len(post) >= need_post:
        start, end = pre[-need_pre], post[need_post - 1]
        event_traded = 1  # live/fixture benchmark calendars include the event day
        conn = _ro_connect(path)
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM price_cache "
                    "WHERE ticker = ? AND date = ?",
                    (BENCHMARK_TICKER, event_date)).fetchone()
                event_traded = 1 if row and row[0] else 0
            finally:
                conn.close()
        bars = need_pre + event_traded + need_post
        basis = (f"benchmark cached trading calendar ({BENCHMARK_TICKER}); "
                 "bar counts are exact local trading days")
    else:
        anchor = date.fromisoformat(event_date)
        wpre, wpost = _weekdays(anchor, need_pre, need_post)
        start, end = wpre[0], wpost[-1]
        bars = need_pre + (1 if anchor.weekday() < 5 else 0) + need_post
        basis = ("weekday approximation (benchmark calendar unavailable "
                 "locally); actual trading days may be fewer due to holidays")
    return {
        "start": start,
        "end": end,
        "trading_bars_expected": bars,
        "calendar_basis": basis,
        "rationale": (
            f"{REQUIRED_PRE_EVENT_BARS} pre-event estimation bars plus "
            f"{PRE_BUFFER_BARS} buffer bars before {event_date}, and "
            f"{FORWARD_HORIZON_BARS} forward horizon bars plus "
            f"{POST_BUFFER_BARS} buffer bars after it (H2 lesson: size "
            "windows by trading days plus a holiday buffer)."
        ),
    }


def _symbol_readout(path: str, ticker: str, event_date: str) -> dict[str, Any]:
    base = {"status": "unavailable", "blocking_reasons": [], "horizons": [],
            "benchmark_basis": BENCHMARK_TICKER}
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
        {"horizon": h.get("horizon"),
         "abnormal_return": h.get("abnormal_return"),
         "sar": h.get("sar"), "car": h.get("car")}
        for h in out.get("per_horizon") or [] if isinstance(h, dict)
    ] if status == "event_study_available" else []
    return {**base, "status": status,
            "blocking_reasons": list(out.get("blocking_reasons") or []),
            "horizons": horizons}


# ---------------------------------------------------------------------------
# Gate composer
# ---------------------------------------------------------------------------


def _blocked(status: str, candidate: dict | None, denoms: dict) -> dict:
    return {
        "gate_status": status,
        "gate_scope": candidate or {"event_id": None},
        "denominators": denoms,
        "non_claims": list(NON_CLAIMS),
    }


def build_gate(*, db_path: str | None = None,
               event_id: int = DEFAULT_EVENT,
               suppliers: Sequence[str] | None = None) -> dict[str, Any]:
    """Build the read-only backfill gate packet. Approves nothing."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    supplier_tickers = [s for s in (suppliers or DEFAULT_SUPPLIERS) if s]

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
            "Accepted vs staged stay separated; this gate reads one staged "
            "candidate and enters no accepted denominator."
        ),
    }
    row = next((e for e in edq["events"] if e["event_id"] == event_id), None)
    if row is None:
        return _blocked("candidate_not_found", None, denoms)

    scope = {
        "event_id": row["event_id"],
        "event_date": row["date"],
        "headline": row["headline"],
        "stage": row["stage"],
        "corpus_status": row["corpus_status"],
        "mechanism_family": row["mechanism_family"],
        "event_date_quality": row["event_date_quality"],
        "anticipation_risk": row["anticipation_risk"],
        "direct_oem_tickers": list(DIRECT_OEM_TICKERS),
        "supplier_tickers": supplier_tickers,
        "benchmark_or_context_tickers": list(CONTEXT_TICKERS),
        "target_table": "price_cache",
        "mutation_status": "not_approved",
    }
    if scope["corpus_status"] != "staged":
        return _blocked("blocked_candidate_not_staged", scope, denoms)

    event_date = scope["event_date"]
    bounded = _bounded_range(path, event_date)

    tickers = list(DIRECT_OEM_TICKERS) + supplier_tickers + list(CONTEXT_TICKERS)
    coverage: list[dict[str, Any]] = []
    readouts: dict[str, dict[str, Any]] = {}
    for t in tickers:
        stats = _ticker_stats(path, t, event_date, bounded["end"])
        ro = _symbol_readout(path, t, event_date)
        readouts[t] = ro
        compute_ready = ro["status"] == "event_study_available"
        if compute_ready:
            reason = None
        elif ro["blocking_reasons"]:
            reason = ", ".join(ro["blocking_reasons"])
        else:
            reason = (
                f"{stats['pre_event_distinct_dates']} pre-event distinct "
                f"dates before {event_date}; cached rows do not cover the "
                "event window"
            )
        coverage.append({
            "ticker": t,
            "role": ("direct_oem" if t in DIRECT_OEM_TICKERS else
                     "supplier" if t in supplier_tickers else
                     "benchmark_or_context"),
            "local_row_count": stats["local_row_count"],
            "min_date": stats["min_date"],
            "max_date": stats["max_date"],
            "rows_exist": stats["local_row_count"] > 0,
            "pre_event_distinct_dates": stats["pre_event_distinct_dates"],
            "has_estimation_window_coverage":
                stats["pre_event_distinct_dates"] >= REQUIRED_PRE_EVENT_BARS,
            "has_event_window_coverage":
                stats["forward_distinct_dates"] >= FORWARD_HORIZON_BARS,
            "compute_ready": compute_ready,
            "reason_if_not_compute_ready": reason,
        })

    cov_by_ticker = {c["ticker"]: c for c in coverage}
    supplier_gaps = ", ".join(
        f"{t} ({cov_by_ticker[t]['pre_event_distinct_dates']} "
        "pre-event dates)"
        for t in supplier_tickers
    )
    current_readout = {
        "direct_oem_readout": {
            t: {"status": readouts[t]["status"],
                "horizons": readouts[t]["horizons"],
                "benchmark_basis": BENCHMARK_TICKER}
            for t in DIRECT_OEM_TICKERS
        },
        "supplier_readout_status": (
            f"not computable locally: {supplier_gaps}. Cached supplier rows "
            "exist but sit outside the 2023 event window, so the gate "
            "blocks the supplier legs."
        ),
        "descriptive_only": True,
        "n_equals_one": True,
    }

    expected_per_ticker = bounded["trading_bars_expected"]
    plan = {
        "allowed_tickers": supplier_tickers,
        "allowed_date_range": bounded,
        "expected_purpose": (
            "Close the supplier-leg coverage gap for the 2023-09-15 event "
            "window only, so the existing event-study gate can compute "
            "LEA/APTV readouts locally. The backfill makes the legs "
            "computable; it does not by itself show any supplier effect."
        ),
        "expected_rows_per_ticker": expected_per_ticker,
        "expected_total_rows_max": expected_per_ticker * len(supplier_tickers)
            if supplier_tickers else 0,
        "forbidden_scope": [
            "Any ticker outside the allowed list (no STLA, no BWA, no broad "
            "auto-supplier sweep).",
            "Any date outside the bounded range (no full-history fetch).",
            "Any table other than price_cache (events, event_hygiene, and "
            "all evidence artifacts stay untouched).",
            "Any schema change.",
            "Any paid or billed provider endpoint; only a free local-cache "
            "path may be considered, and even that needs its own approval.",
            "Any rewrite of existing GM/F/SPY/XLY rows.",
            "Any paid /analyze run, candidate promotion, or stage change.",
        ],
        "no_paid_provider": True,
        "no_analyze": True,
        "no_promotion": True,
        "separate_approval_required": True,
    }

    safety = {
        "clean_tree_check": (
            "git status must be clean before the backfill starts; abort on "
            "any unexpected local change."
        ),
        "db_hash_before": (
            "Record the live events.db SHA-256 before any write and keep it "
            "in the run report."
        ),
        "local_backup_required": (
            "Take a dated local backup copy of events.db (backups/ "
            "convention) before any mutation."
        ),
        "temp_db_or_snapshot_preview_required": (
            "Run the backfill against a temp copy or snapshot first and "
            "diff the result; only after review may the live DB be touched."
        ),
        "dry_run_expected_rows": (
            f"A dry run must report expected inserts per ticker (about "
            f"{expected_per_ticker} rows each, "
            f"{plan['expected_total_rows_max']} max total) and abort if the "
            "count diverges."
        ),
        "targeted_tests_required": (
            "Targeted tests (this gate's suite plus the UAW packet suite) "
            "must pass against the previewed result before promotion to "
            "live."
        ),
        "live_probe_required": (
            "After any live write, re-run the UAW supplier packet and this "
            "gate read-only and check the supplier legs become "
            "compute-ready with no other coverage change."
        ),
        "db_hash_after_or_expected_mutation_report": (
            "Record the post-write SHA-256 and report it next to the "
            "before-hash with the exact row delta (price_cache only)."
        ),
        "staged_files_check": (
            "git status afterwards must show no DB or generated artifacts "
            "staged; only intended source/docs changes may be committed."
        ),
    }

    gate = {
        "gate_status": "ok",
        "denominators": denoms,
        "gate_scope": scope,
        "coverage": coverage,
        "current_readout": current_readout,
        "future_backfill_plan": plan,
        "required_safety_sequence_before_mutation": safety,
        "what_can_be_read_now": [
            "The intra-OEM contrast GM vs F (both compute-ready locally) as "
            "descriptive n=1 windows.",
            "The exact size of the supplier gap: per-ticker pre-event "
            "distinct dates and the bounded range that would close it.",
            "Benchmark/context coverage (SPY, XLY) for the same window.",
        ],
        "what_cannot_be_read_now": [
            "The supplier transmission itself - LEA/APTV have no pre-event "
            "local history at this date.",
            "Any supplier-vs-OEM comparison, until a separately approved "
            "bounded backfill closes the gap.",
            "Any causal attribution or significance, before or after a "
            "backfill - windows stay descriptive n=1.",
        ],
        "non_claims": list(NON_CLAIMS),
    }
    return gate


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _render_text(gate: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("UAW supplier backfill gate - candidate 313 (read-only design)")
    add("=" * 64)
    if gate["gate_status"] != "ok":
        add(f"Gate status: {gate['gate_status']}")
        add("")
        add("Non-claims:")
        for item in gate["non_claims"]:
            add(f"  - {item}")
        return "\n".join(lines)

    scope = gate["gate_scope"]
    d = gate["denominators"]
    add(f"Event {scope['event_id']} ({scope['event_date']}): "
        f"{scope['headline']}")
    add(f"Stage: {scope['stage']} (staged/no-paid) | family: "
        f"{scope['mechanism_family']} | anchor: {scope['event_date_quality']}")
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}")
    add(f"Target table: {scope['target_table']} | mutation status: "
        f"{scope['mutation_status']}")
    add("")

    add("Coverage (local price_cache, read-only):")
    add(f"  {'ticker':<7}{'role':<22}{'rows':>6}{'pre-evt':>9}"
        f"{'est-win':>9}{'evt-win':>9}{'ready':>7}")
    for c in gate["coverage"]:
        add(f"  {c['ticker']:<7}{c['role']:<22}{c['local_row_count']:>6}"
            f"{c['pre_event_distinct_dates']:>9}"
            f"{str(c['has_estimation_window_coverage']):>9}"
            f"{str(c['has_event_window_coverage']):>9}"
            f"{str(c['compute_ready']):>7}")
        if c["reason_if_not_compute_ready"]:
            add(f"          blocked: {c['reason_if_not_compute_ready']}")
    add("")

    add("Rows-exist is not compute-ready:")
    add("  A ticker can have cached rows and still be unreadable at the "
        "event date.")
    for c in gate["coverage"]:
        if c["rows_exist"] and not c["compute_ready"]:
            add(f"  - {c['ticker']}: {c['local_row_count']} rows cached "
                f"({_fmt(c['min_date'])}..{_fmt(c['max_date'])}) but "
                f"{c['pre_event_distinct_dates']} pre-event dates before "
                f"{scope['event_date']}.")
    add("")

    add("Current readout (direct OEM legs only, descriptive n=1 vs SPY):")
    for t, ro in gate["current_readout"]["direct_oem_readout"].items():
        if ro["status"] == "event_study_available":
            hs = " ".join(f"{h['horizon']}d={h['abnormal_return']:+.4f}"
                          for h in ro["horizons"])
            add(f"  {t}: {hs}")
        else:
            add(f"  {t}: not computable locally ({ro['status']})")
    add(f"  Suppliers: {gate['current_readout']['supplier_readout_status']}")
    add("")

    plan = gate["future_backfill_plan"]
    rng = plan["allowed_date_range"]
    add("Future bounded backfill scope (design only - NOT approved):")
    add(f"  Allowed tickers: {', '.join(plan['allowed_tickers'])}")
    add(f"  Allowed date range: {rng['start']} .. {rng['end']} "
        f"(~{rng['trading_bars_expected']} bars per ticker)")
    add(f"  Calendar basis: {rng['calendar_basis']}")
    add(f"  Expected rows: ~{plan['expected_rows_per_ticker']} per ticker, "
        f"{plan['expected_total_rows_max']} max total")
    add("  Forbidden:")
    for item in plan["forbidden_scope"]:
        add(f"    - {item}")
    add("")

    add("Safety sequence before mutation (all steps required):")
    safety = gate["required_safety_sequence_before_mutation"]
    for step, requirement in safety.items():
        add(f"  {step}: {requirement}")
    add("")

    add("Final disposition:")
    add("  Do not backfill yet. The actual backfill requires separate "
        "operator approval;")
    add("  if approved later, it may write only LEA/APTV rows inside the "
        "bounded window above.")
    add("  No paid analysis, no promotion, no stage change.")
    add("")

    add("What can be read now:")
    for item in gate["what_can_be_read_now"]:
        add(f"  - {item}")
    add("What cannot be read now:")
    for item in gate["what_cannot_be_read_now"]:
        add(f"  - {item}")
    add("")
    add("Non-claims:")
    for item in gate["non_claims"]:
        add(f"  - {item}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only UAW supplier backfill gate for candidate 313.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--event-id", type=int, default=DEFAULT_EVENT)
    parser.add_argument("--suppliers", default=",".join(DEFAULT_SUPPLIERS))
    args = parser.parse_args(argv)

    suppliers = tuple(s.strip() for s in args.suppliers.split(",") if s.strip())
    gate = build_gate(db_path=args.db_path, event_id=args.event_id,
                      suppliers=suppliers)
    if args.json:
        print(json.dumps(gate, indent=2, sort_keys=True))
    else:
        print(_render_text(gate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

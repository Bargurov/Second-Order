#!/usr/bin/env python3
"""Guarded, row-scoped *adjusted-ticker* cache backfill.

Sibling of ``scripts/spy_adjusted_benchmark_backfill.py``: where that tool
populates true adjusted SPY (the benchmark), this one populates true
adjusted rows for the **primary tickers** of events that are
archive-ready but not event-study compute-ready because their adjusted
ticker window has an interior hole (``non_contiguous``) or short forward
coverage (``post<20``).

Now that adjusted SPY spans the relevant period (B3C2), filling the
adjusted-ticker gaps converts these events to a **matched**
``(adjusted, adjusted)`` basis directly — no cross-flag caveat
reintroduced.

Scope guarantee
---------------
Every write is ``(target_ticker, auto_adjust=1)`` for a date inside the
derived window — nothing else:
* never SPY (SPY is the benchmark; handled by the sibling tool);
* never ``auto_adjust=0``;
* never the ``events`` table — only ``price_cache``;
* a direct ``INSERT OR REPLACE`` (idempotent), NEVER
  ``price_cache._write_rows`` / ``fetch_daily_cached`` (gap-planning,
  not row-scoped), and NEVER a raw->adjusted copy.

Window correctness (avoids the two traps B3D preflight hit)
-----------------------------------------------------------
Per recoverable event, the window is derived from the **adjusted-SPY
trading-day calendar**: ``[spy_adj[idx-60], spy_adj[idx+20]]`` where
``idx`` is the last adjusted-SPY date on/before the event.  This:
* guarantees >=60 actual TRADING days pre-event (not merely 60 business
  days, which holidays shrink to ~57); and
* guarantees the window lies inside current adjusted-SPY coverage, so a
  ticker fill lands on a matched basis rather than cross-flag.

Frontier events excluded
------------------------
Events whose adjusted-SPY window is itself not viable (``pre<60`` /
``post<20`` / non-contiguous — i.e. SPY's own forward hasn't matured)
are listed under ``excluded_frontier_event_ids`` and are NOT claimed as
recoverable.  A ticker-only backfill cannot fix them.

Safety contract (mirrors the SPY writer)
----------------------------------------
* Dry-run default: planner runs; no provider, no write.
* Writes require ``--write --confirm --backup-path`` together; the live
  DB is copied to the backup before the first INSERT; ``--backup-path``
  must differ from the live DB.  Every applied row is audit-logged.  No
  LLM, no ``market_check`` / ``market_data``, no FastAPI / ``routes.*``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
from event_study_validation import (  # noqa: E402
    _last_index_le,
    _is_contiguous,
    _primary_ticker,
    ESTIMATION_WINDOW,
    HORIZONS,
    BENCHMARK_TICKER,
)

FORWARD_HORIZON = max(HORIZONS)
TICKER_AUTO_ADJUST = 1
_REPAIR_ACTION = "insert_ticker_aa1_adjusted"


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: Optional[str]) -> Optional[str]:
    if db_path is not None:
        return db_path
    return getattr(_db, "DB_FILE", None)


def _read_aa1_dates(resolved: str, ticker: str) -> list[str]:
    """Sorted ISO dates with an adjusted (aa=1) close for ``ticker``."""
    try:
        conn = sqlite3.connect(resolved)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT date FROM price_cache "
            "WHERE ticker = ? AND auto_adjust = 1 AND close IS NOT NULL",
            (ticker.upper(),),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return sorted({d[:10] for (d,) in rows if isinstance(d, str)})


# ---------------------------------------------------------------------------
# Planner (read-only)
# ---------------------------------------------------------------------------


def plan_adjusted_ticker_backfill(*, db_path: Optional[str] = None) -> dict[str, Any]:
    """Derive the per-ticker adjusted backfill plan, read-only.

    Targets only events that are archive-ready, not compute-ready, AND
    whose adjusted-SPY window is itself viable (so a ticker fill yields a
    matched basis).  Excludes frontier events.
    """
    from event_study_validation import build_event_study_validation
    from scripts.stat_validation_readiness_report import summarize_readiness

    resolved = _resolve_db_path(db_path)
    if resolved is None:
        return _empty_plan()

    saved = _db.DB_FILE
    _db.DB_FILE = resolved  # build reads price_cache through this
    try:
        rep = summarize_readiness(db_path=resolved, limit=10**12)
        archive_ready = {
            e["event_id"] for e in rep.get("events") or [] if e.get("fully_ready")
        }
        cr = rep.get("compute_readiness") or {}
        before_ready = int(cr.get("event_study_compute_ready_count") or 0)
        before_matched = int(
            (cr.get("auto_adjust_basis_counts") or {}).get("matched") or 0
        )

        spy_adj = _read_aa1_dates(resolved, BENCHMARK_TICKER)

        try:
            conn = sqlite3.connect(resolved)
            ev_rows = conn.execute(
                "SELECT id, event_date, market_tickers FROM events ORDER BY id"
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            ev_rows = []

        targets: dict[int, dict[str, Any]] = {}
        frontier: list[int] = []
        for eid, event_date, market_tickers in ev_rows:
            if eid not in archive_ready:
                continue
            sym = _primary_ticker(market_tickers)
            if not sym or not isinstance(event_date, str):
                continue
            out = build_event_study_validation({
                "id": eid, "event_date": event_date,
                "market_tickers": [{"symbol": sym}],
            })
            if out.get("status") == "event_study_available":
                continue  # already compute-ready
            # Recoverability == adjusted-SPY standalone viability around the
            # event (a full ticker fill makes (T,T) common collapse to
            # adj-SPY's dates).
            ev_iso = event_date[:10]
            idx = _last_index_le(spy_adj, ev_iso)
            if (idx is None or idx < ESTIMATION_WINDOW
                    or (len(spy_adj) - 1 - idx) < FORWARD_HORIZON):
                frontier.append(eid)
                continue
            window = spy_adj[idx - ESTIMATION_WINDOW: idx + FORWARD_HORIZON + 1]
            if not _is_contiguous(window):
                frontier.append(eid)
                continue
            targets[eid] = {
                "ticker":     sym,
                "win_start":  spy_adj[idx - ESTIMATION_WINDOW],
                "win_end":    spy_adj[idx + FORWARD_HORIZON],
            }
    finally:
        _db.DB_FILE = saved

    # Group by ticker -> union window.
    by_ticker: dict[str, dict[str, Any]] = {}
    for eid, t in targets.items():
        bt = by_ticker.setdefault(t["ticker"], {
            "events": [], "win_start": t["win_start"], "win_end": t["win_end"],
        })
        bt["events"].append(eid)
        bt["win_start"] = min(bt["win_start"], t["win_start"])
        bt["win_end"] = max(bt["win_end"], t["win_end"])

    spy_set = set(spy_adj)
    total_fetch = 0
    for sym, bt in by_ticker.items():
        bt["events"].sort()
        # The fetch returns ~ the market trading days in the window; use the
        # adjusted-SPY calendar (the benchmark trading days) as the estimate.
        win_trading = sum(1 for d in spy_adj if bt["win_start"] <= d <= bt["win_end"])
        cached = sum(
            1 for d in _read_aa1_dates(resolved, sym)
            if bt["win_start"] <= d <= bt["win_end"]
        )
        bt["estimated_fetch_rows"] = win_trading
        bt["aa1_cached_in_window"] = cached
        bt["estimated_new_rows"] = max(0, win_trading - cached)
        total_fetch += win_trading
    del spy_set

    n_targets = len(targets)
    return {
        "target_event_ids":             sorted(targets),
        "target_event_count":           n_targets,
        "excluded_frontier_event_ids":  sorted(frontier),
        "frontier_count":               len(frontier),
        "tickers":                      by_ticker,
        "total_estimated_fetch_rows":   total_fetch,
        "expected_compute_ready_before": before_ready,
        "expected_compute_ready_after":  before_ready + n_targets,
        "expected_matched_before":       before_matched,
        "expected_matched_after":        before_matched + n_targets,
    }


def _empty_plan() -> dict[str, Any]:
    return {
        "target_event_ids":             [],
        "target_event_count":           0,
        "excluded_frontier_event_ids":  [],
        "frontier_count":               0,
        "tickers":                      {},
        "total_estimated_fetch_rows":   0,
        "expected_compute_ready_before": 0,
        "expected_compute_ready_after":  0,
        "expected_matched_before":       0,
        "expected_matched_after":        0,
    }


# ---------------------------------------------------------------------------
# Provider fetch seam (only on the confirmed write path)
# ---------------------------------------------------------------------------


def _fetch_ticker_adjusted(*, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    """Fetch ``symbol`` daily bars at ``auto_adjust=True`` for ``[start,
    end]`` inclusive.  Returns ``[{date, close, volume}, ...]``.  Tests
    patch this seam — the default shells out to yfinance and is reached
    ONLY under ``confirm=True``.
    """
    import yfinance as yf
    from datetime import date as _date, timedelta as _timedelta

    end_d = _date.fromisoformat(end) + _timedelta(days=1)  # yf end exclusive
    df = yf.download(
        symbol, start=start, end=end_d.isoformat(),
        interval="1d", auto_adjust=True, progress=False,
    )
    if df is None or df.empty:
        return []
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        try:
            out.append({
                "date":   idx.strftime("%Y-%m-%d"),
                "close":  float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            })
        except (TypeError, ValueError, KeyError):
            continue
    return out


# ---------------------------------------------------------------------------
# Guarded writer
# ---------------------------------------------------------------------------


def _default_audit_log_path() -> str:
    ts = _dt.now(tz=_tz.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return str(Path("audit_logs") / f"adjusted_ticker_backfill_{ts}.jsonl")


def apply_adjusted_ticker_backfill(
    *,
    db_path: Optional[str] = None,
    confirm: bool = False,
    backup_path: Optional[str] = None,
    audit_log_path: Optional[str] = None,
) -> dict[str, Any]:
    """Apply the adjusted-ticker backfill when ``confirm=True``.

    Default (``confirm=False``) is a strict dry-run: planner only, no
    provider, no write.  ``confirm=True`` requires ``backup_path`` (which
    must differ from the live DB); the live DB is copied there before the
    first INSERT.  Only ``(target_ticker, aa=1)`` rows are written.
    """
    if confirm and not backup_path:
        raise ValueError(
            "apply_adjusted_ticker_backfill: confirm=True requires a "
            "backup_path (snapshot the DB before any write).",
        )

    plan = plan_adjusted_ticker_backfill(db_path=db_path)
    envelope: dict[str, Any] = {
        **plan,
        "write_attempted": False,
        "fetched_rows":    0,
        "applied_count":   0,
        "backup_path":     None,
        "audit_log_path":  None,
        "refuse_reason":   None,
    }

    if not confirm:
        return envelope
    if not plan["tickers"]:
        envelope["refuse_reason"] = "no recoverable targets"
        return envelope

    resolved = _resolve_db_path(db_path)
    if resolved is None:
        envelope["refuse_reason"] = "target database not found"
        return envelope

    try:
        same_path = Path(backup_path).resolve() == Path(resolved).resolve()
    except OSError:
        same_path = False
    if same_path:
        envelope["refuse_reason"] = (
            "--backup-path must differ from the live DB (would leave no "
            "rollback artifact)"
        )
        return envelope

    shutil.copy2(resolved, backup_path)
    envelope["backup_path"] = backup_path

    # Fetch per ticker over its union window.
    fetched: list[tuple[str, dict[str, Any]]] = []
    for sym, bt in plan["tickers"].items():
        rows = _fetch_ticker_adjusted(
            symbol=sym, start=bt["win_start"], end=bt["win_end"],
        )
        for r in rows:
            fetched.append((sym, r))
    envelope["fetched_rows"] = len(fetched)
    if not fetched:
        envelope["write_attempted"] = True
        envelope["refuse_reason"] = "provider returned no rows"
        return envelope

    fetched_at = _dt.now(tz=_tz.utc).isoformat()
    applied: list[dict[str, Any]] = []
    conn = sqlite3.connect(resolved, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for sym, r in fetched:
                d = r.get("date")
                if not isinstance(d, str) or not d:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (sym.upper(), d[:10], r.get("close"), r.get("volume"),
                     TICKER_AUTO_ADJUST, fetched_at),
                )
                applied.append({"ticker": sym.upper(), "date": d[:10],
                                "close": r.get("close"), "volume": r.get("volume")})
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    resolved_audit = audit_log_path or _default_audit_log_path()
    if applied:
        audit_dir = Path(resolved_audit).parent
        if str(audit_dir) and audit_dir != Path(""):
            audit_dir.mkdir(parents=True, exist_ok=True)
        with open(resolved_audit, "a", encoding="utf-8") as fh:
            for w in applied:
                fh.write(json.dumps({
                    "ts":          fetched_at,
                    "ticker":      w["ticker"],
                    "date":        w["date"],
                    "auto_adjust": TICKER_AUTO_ADJUST,
                    "close":       w["close"],
                    "volume":      w["volume"],
                    "action":      _REPAIR_ACTION,
                }, default=str) + "\n")

    envelope["write_attempted"] = True
    envelope["applied_count"]   = len(applied)
    envelope["audit_log_path"]  = resolved_audit if applied else None
    return envelope


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines = [
        "Adjusted-ticker cache backfill "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"target events:        {report.get('target_event_count')} {report.get('target_event_ids')}",
        f"excluded frontier:    {report.get('frontier_count')} {report.get('excluded_frontier_event_ids')}",
        f"total fetch rows est: {report.get('total_estimated_fetch_rows')}",
        "",
        "Per-ticker windows:",
    ]
    for sym, bt in (report.get("tickers") or {}).items():
        lines.append(
            f"  {sym:<6} {bt['win_start']} -> {bt['win_end']}  "
            f"events={bt['events']}  cached_aa1={bt['aa1_cached_in_window']}  "
            f"new~{bt['estimated_new_rows']}  fetch~{bt['estimated_fetch_rows']}"
        )
    lines += [
        "",
        f"expected compute-ready: {report.get('expected_compute_ready_before')} "
        f"-> {report.get('expected_compute_ready_after')}",
        f"expected matched:       {report.get('expected_matched_before')} "
        f"-> {report.get('expected_matched_after')}",
    ]
    if "write_attempted" in report and report.get("write_attempted"):
        lines += [
            "",
            f"fetched_rows:         {report.get('fetched_rows')}",
            f"applied_count:        {report.get('applied_count')}",
            f"backup_path:          {report.get('backup_path')}",
            f"audit_log_path:       {report.get('audit_log_path')}",
        ]
        if report.get("refuse_reason"):
            lines.append(f"refuse_reason:        {report.get('refuse_reason')}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


_WRITE_GUIDANCE = (
    "Refusing to run: --write requires --confirm AND --backup-path.\n"
    "Dry-run is the safe default - it fetches nothing and writes nothing.\n"
    "  python scripts/adjusted_ticker_backfill.py --write --confirm "
    "--backup-path backups/events-pre-ticker.db"
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Guarded, row-scoped adjusted-ticker (aa=1) cache backfill.  "
            "Dry-run by default (no fetch, no write).  Write mode requires "
            "--write --confirm --backup-path together and writes ONLY "
            "(target_ticker, date, auto_adjust=1) rows."
        ),
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (also the default with no flags).")
    p.add_argument("--json", action="store_true",
                   help="Emit structured JSON instead of the text report.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional SQLite events.db path.  Defaults to db.DB_FILE.")
    p.add_argument("--write", action="store_true",
                   help="Persist.  Requires --confirm and --backup-path.")
    p.add_argument("--confirm", action="store_true",
                   help="Confirm an explicit --write run.")
    p.add_argument("--backup-path", dest="backup_path", default=None,
                   help="Snapshot path for the pre-write backup (required for --write).")
    p.add_argument("--audit-log-path", dest="audit_log_path", default=None,
                   help="Optional audit-log path (default: audit_logs/...).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    if args.dry_run:
        report = plan_adjusted_ticker_backfill(db_path=args.db_path)
    elif args.write and args.confirm and args.backup_path:
        report = apply_adjusted_ticker_backfill(
            db_path=args.db_path, confirm=True,
            backup_path=args.backup_path, audit_log_path=args.audit_log_path,
        )
    elif args.write or args.confirm:
        print(_WRITE_GUIDANCE, file=sys.stderr)
        return 2
    else:
        report = plan_adjusted_ticker_backfill(db_path=args.db_path)

    print(_render_json(report) if args.json else _render_text(report), file=output)
    if report.get("write_attempted") is False and report.get("refuse_reason"):
        return 1
    return 0


__all__ = (
    "plan_adjusted_ticker_backfill",
    "apply_adjusted_ticker_backfill",
    "TICKER_AUTO_ADJUST",
)


if __name__ == "__main__":
    sys.exit(main())

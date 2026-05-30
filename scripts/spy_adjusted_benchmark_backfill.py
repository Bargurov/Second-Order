#!/usr/bin/env python3
"""Guarded, row-scoped SPY *adjusted* benchmark-cache backfill.

Why this tool exists
--------------------
Event-study compute-readiness is matched-flag-blocked: the tickers are
cached predominantly *adjusted* (aa=1) while SPY is cached predominantly
*raw* (aa=0), so every compute-ready event resolves on the cross-flag
basis ``(adjusted asset, raw benchmark)`` and carries a dividend-basis
caveat.  The fix is to populate **true adjusted SPY** (aa=1) over the
estimation+forward windows of those events, so ``(adjusted, adjusted)``
becomes viable and the caveat disappears.

No existing guarded tool does this: ``benchmark_cache_backfill_*``
targets the ``missing_benchmark_proxy`` forward gap and writes only to a
temp copy; ``price_cache.fetch_daily_cached`` is a gap-planning,
non-row-scoped production path.  This module is the smallest guarded
writer that does exactly — and only — the scoped job.

Scope guarantee
---------------
Every write is ``(ticker="SPY", auto_adjust=1)`` and nothing else:
* never another ticker, never ``auto_adjust=0``;
* never the ``events`` table — only ``price_cache``;
* a direct ``INSERT OR REPLACE`` (idempotent), NOT
  ``price_cache._write_rows`` / ``fetch_daily_cached`` (which gap-plan and
  carry the corrupt-row purge / cross-contamination lock).

Safety contract (mirrors ``auto_adjust_mismatch_repair.py``)
------------------------------------------------------------
* Default behaviour is **dry-run**: the planner runs, NOTHING is fetched
  and NOTHING is written.  The provider is reached only on the confirmed
  write path.
* Writes require ``--write --confirm`` together AND ``--backup-path``.
  The live DB is copied to ``backup_path`` (``shutil.copy2``) *before*
  the first INSERT; a copy failure raises and no row is touched.
* Every applied row appends a JSONL audit record; the audit file is
  created only when ``applied_count > 0``.
* The single provider call (the SPY ``auto_adjust=True`` fetch) is reached
  only under ``confirm=True``.  No LLM, no ``market_check`` /
  ``market_data``, no FastAPI / ``routes.*``.

The required window
-------------------
By default the planner DERIVES the union window from the current
cross-flag compute-ready events (so it stays correct as the cache
changes): ``[min(event_date) - 60bd, max(event_date) + 20bd]``.  Pass
``--start`` / ``--end`` to override with an explicit window.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import date as _date, datetime as _dt, timedelta as _timedelta, timezone as _tz
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402


BENCHMARK_TICKER = "SPY"
BENCHMARK_AUTO_ADJUST = 1            # adjusted
ESTIMATION_WINDOW = 60              # mirrors stats.event_study / event_study_validation
FORWARD_HORIZON = 20               # max horizon
_REPAIR_ACTION = "insert_spy_aa1_adjusted"


# ---------------------------------------------------------------------------
# Pure date helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: Any) -> Optional[_date]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _business_day_offset(start: _date, n: int) -> _date:
    if n == 0:
        return start
    out = start
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining > 0:
        out = out + _timedelta(days=step)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _weekday_count_inclusive(start: _date, end: _date) -> int:
    if start > end:
        return 0
    count = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += _timedelta(days=1)
    return count


def _primary_symbol(raw_market_tickers: Any) -> Optional[str]:
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
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


def _resolve_db_path(db_path: Optional[str]) -> Optional[str]:
    if db_path is not None:
        return db_path
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Read-only helpers (plain SELECT through the resolved DB path)
# ---------------------------------------------------------------------------


def _cross_flag_compute_ready(db_path: Optional[str]) -> list[tuple[int, str]]:
    """Return ``[(event_id, event_date_iso)]`` for compute-ready events
    that currently resolve on a CROSS-FLAG basis — the events this
    backfill would convert to matched.

    Reuses ``event_study_validation.build_event_study_validation`` (the
    same gate the route and the readiness report use); read-only.
    """
    from event_study_validation import build_event_study_validation

    resolved = _resolve_db_path(db_path)
    if resolved is None:
        return []
    saved = _db.DB_FILE
    _db.DB_FILE = resolved  # build reads price_cache through this
    out: list[tuple[int, str]] = []
    try:
        conn = sqlite3.connect(resolved)
        try:
            rows = conn.execute(
                "SELECT id, event_date, market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        for eid, event_date, market_tickers in rows:
            sym = _primary_symbol(market_tickers)
            event = {
                "id": eid, "event_date": event_date,
                "market_tickers": [{"symbol": sym}] if sym else [],
            }
            res = build_event_study_validation(event)
            if res.get("status") != "event_study_available":
                continue
            basis = res.get("auto_adjust_basis") or {}
            if basis.get("asset") != basis.get("benchmark"):  # cross-flag
                if isinstance(eid, int) and isinstance(event_date, str):
                    out.append((eid, event_date))
    finally:
        _db.DB_FILE = saved
    return out


def _spy_aa1_dates_in_window(
    db_path: Optional[str], start: _date, end: _date,
) -> set[str]:
    """Existing SPY aa=1 cache dates within ``[start, end]``.  Read-only."""
    resolved = _resolve_db_path(db_path)
    if resolved is None:
        return set()
    try:
        conn = sqlite3.connect(resolved)
    except sqlite3.Error:
        return set()
    try:
        rows = conn.execute(
            "SELECT date FROM price_cache "
            "WHERE ticker = ? AND auto_adjust = ? AND date >= ? AND date <= ?",
            (BENCHMARK_TICKER, BENCHMARK_AUTO_ADJUST, start.isoformat(), end.isoformat()),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return {d[:10] for (d,) in rows if isinstance(d, str)}


# ---------------------------------------------------------------------------
# Provider fetch seam (only fires on the confirmed write path)
# ---------------------------------------------------------------------------


def _fetch_spy_adjusted(*, start: str, end: str) -> list[dict[str, Any]]:
    """Fetch SPY daily bars at ``auto_adjust=True`` for ``[start, end]``
    inclusive.  Returns ``[{date, close, volume}, ...]``.

    Tests patch this seam — the default implementation shells out to
    yfinance and is reached ONLY under ``confirm=True``.
    """
    import yfinance as yf  # local import — only on the confirmed write path

    end_d = _date.fromisoformat(end) + _timedelta(days=1)  # yf end is exclusive
    df = yf.download(
        BENCHMARK_TICKER, start=start, end=end_d.isoformat(),
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
# Planner (read-only)
# ---------------------------------------------------------------------------


def plan_spy_adjusted_backfill(
    *, db_path: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
) -> dict[str, Any]:
    """Compute the SPY-adjusted backfill plan.  Read-only: no fetch, no write.

    Derives the union window from the current cross-flag compute-ready
    events unless an explicit ``start``/``end`` is supplied.
    """
    targets: list[tuple[int, str]] = []
    if start and end:
        win_start = _parse_iso(start)
        win_end = _parse_iso(end)
    else:
        targets = _cross_flag_compute_ready(db_path)
        if not targets:
            return _empty_plan()
        dates = sorted(d for d in (_parse_iso(ed) for _, ed in targets) if d)
        win_start = _business_day_offset(dates[0], -ESTIMATION_WINDOW)
        win_end = _business_day_offset(dates[-1], FORWARD_HORIZON)

    if win_start is None or win_end is None or win_start > win_end:
        return _empty_plan()

    cached = _spy_aa1_dates_in_window(db_path, win_start, win_end)
    weekdays = _weekday_count_inclusive(win_start, win_end)
    # Estimate the rows the fetch would add: weekdays not already at aa=1.
    cached_weekdays = sum(
        1 for d in cached
        if (pd := _parse_iso(d)) is not None and pd.weekday() < 5
    )
    estimated_fetch_rows = max(0, weekdays - cached_weekdays)

    return {
        "benchmark_symbol":       BENCHMARK_TICKER,
        "auto_adjust":            BENCHMARK_AUTO_ADJUST,
        "target_event_ids":       sorted(eid for eid, _ in targets),
        "target_event_count":     len(targets),
        "window_start":           win_start.isoformat(),
        "window_end":             win_end.isoformat(),
        "window_weekdays":        weekdays,
        "spy_aa1_cached_in_window": cached_weekdays,
        "estimated_new_rows":     estimated_fetch_rows,
        # INSERT OR REPLACE rewrites the WHOLE window to one consistent
        # adjusted basis, so the write touches every window weekday
        # (estimated_new_rows new + spy_aa1_cached_in_window replaced),
        # not just the gaps.
        "rows_written_estimate":  weekdays,
        # Retained for back-compat: the gap count (new rows only).
        "estimated_fetch_rows":   estimated_fetch_rows,
    }


def _empty_plan() -> dict[str, Any]:
    return {
        "benchmark_symbol":         BENCHMARK_TICKER,
        "auto_adjust":              BENCHMARK_AUTO_ADJUST,
        "target_event_ids":         [],
        "target_event_count":       0,
        "window_start":             None,
        "window_end":               None,
        "window_weekdays":          0,
        "spy_aa1_cached_in_window": 0,
        "estimated_new_rows":       0,
        "rows_written_estimate":    0,
        "estimated_fetch_rows":     0,
    }


# ---------------------------------------------------------------------------
# Guarded writer
# ---------------------------------------------------------------------------


def _default_audit_log_path() -> str:
    ts = _dt.now(tz=_tz.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return str(Path("audit_logs") / f"spy_adjusted_benchmark_backfill_{ts}.jsonl")


def apply_spy_adjusted_backfill(
    *,
    db_path: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    confirm: bool = False,
    backup_path: Optional[str] = None,
    audit_log_path: Optional[str] = None,
) -> dict[str, Any]:
    """Apply the SPY-adjusted backfill when ``confirm=True``.

    Default (``confirm=False``) is a strict dry-run: the planner runs, the
    provider is NOT reached, and nothing is written.  ``confirm=True``
    additionally requires ``backup_path``; the live DB is copied there
    before the first INSERT.  Only ``(SPY, date, aa=1)`` rows are written.
    """
    if confirm and not backup_path:
        raise ValueError(
            "apply_spy_adjusted_backfill: confirm=True requires a "
            "backup_path (snapshot the DB before any write).",
        )

    plan = plan_spy_adjusted_backfill(db_path=db_path, start=start, end=end)
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
    if plan["window_start"] is None or plan["window_end"] is None:
        envelope["refuse_reason"] = "no target window (no cross-flag compute-ready events)"
        return envelope

    resolved = _resolve_db_path(db_path)
    if resolved is None:
        envelope["refuse_reason"] = "target database not found"
        return envelope

    # Same-path defense (mirrors benchmark_cache_backfill_write_smoke): a
    # backup written over the live DB leaves no rollback artifact.  Refuse
    # cleanly rather than relying on copy2's SameFileError raise.
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

    # Snapshot the live DB BEFORE any write (copy2 propagates failures).
    shutil.copy2(resolved, backup_path)
    envelope["backup_path"] = backup_path

    rows = _fetch_spy_adjusted(start=plan["window_start"], end=plan["window_end"])
    envelope["fetched_rows"] = len(rows)
    if not rows:
        envelope["write_attempted"] = True
        envelope["refuse_reason"] = "provider returned no SPY rows"
        return envelope

    fetched_at = _dt.now(tz=_tz.utc).isoformat()
    applied: list[dict[str, Any]] = []
    conn = sqlite3.connect(resolved, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for r in rows:
                d = r.get("date")
                if not isinstance(d, str) or not d:
                    continue
                close = r.get("close")
                volume = r.get("volume")
                # Hard-scoped: ticker and flag are constants, never inputs.
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (BENCHMARK_TICKER, d[:10], close, volume,
                     BENCHMARK_AUTO_ADJUST, fetched_at),
                )
                applied.append({"date": d[:10], "close": close, "volume": volume})
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
                    "ticker":      BENCHMARK_TICKER,
                    "date":        w["date"],
                    "auto_adjust": BENCHMARK_AUTO_ADJUST,
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
    is_write = "write_attempted" in report
    lines = [
        "SPY adjusted benchmark-cache backfill "
        + ("write" if report.get("write_attempted") else "dry-run"),
        "",
        f"benchmark:            {report.get('benchmark_symbol')} (auto_adjust={report.get('auto_adjust')})",
        f"target cross-flag events: {report.get('target_event_count')} {report.get('target_event_ids')}",
        f"window:               {report.get('window_start')} -> {report.get('window_end')}",
        f"window weekdays:      {report.get('window_weekdays')}",
        f"SPY aa=1 cached:      {report.get('spy_aa1_cached_in_window')}",
        f"new rows (gaps):      {report.get('estimated_new_rows')}",
        f"write touches:        all {report.get('window_weekdays')} window weekdays "
        f"({report.get('estimated_new_rows')} new + "
        f"{report.get('spy_aa1_cached_in_window')} replaced via INSERT OR REPLACE)",
    ]
    if is_write:
        lines += [
            "",
            f"write_attempted:      {report.get('write_attempted')}",
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
    "Refusing to run: --write and --confirm must be supplied together with "
    "--backup-path.\nDry-run is the safe default - it fetches nothing and "
    "writes nothing.\n  python scripts/spy_adjusted_benchmark_backfill.py "
    "--write --confirm --backup-path backups/events-pre-spy.db"
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Guarded, row-scoped SPY adjusted (aa=1) benchmark-cache "
            "backfill.  Dry-run by default (no fetch, no write).  Write "
            "mode requires --write --confirm --backup-path together and "
            "writes ONLY (SPY, date, auto_adjust=1) rows."
        ),
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (also the default with no flags).")
    p.add_argument("--json", action="store_true",
                   help="Emit structured JSON instead of the text report.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional SQLite events.db path.  Defaults to db.DB_FILE.")
    p.add_argument("--start", dest="start", default=None,
                   help="Override window start (ISO).  Requires --end.")
    p.add_argument("--end", dest="end", default=None,
                   help="Override window end (ISO).  Requires --start.")
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
        report = plan_spy_adjusted_backfill(
            db_path=args.db_path, start=args.start, end=args.end,
        )
    elif args.write and args.confirm and args.backup_path:
        report = apply_spy_adjusted_backfill(
            db_path=args.db_path, start=args.start, end=args.end,
            confirm=True, backup_path=args.backup_path,
            audit_log_path=args.audit_log_path,
        )
    elif args.write or args.confirm:
        print(_WRITE_GUIDANCE, file=sys.stderr)
        return 2
    else:
        report = plan_spy_adjusted_backfill(
            db_path=args.db_path, start=args.start, end=args.end,
        )

    print(_render_json(report) if args.json else _render_text(report), file=output)
    if report.get("write_attempted") is False and report.get("refuse_reason"):
        return 1
    return 0


__all__ = (
    "plan_spy_adjusted_backfill",
    "apply_spy_adjusted_backfill",
    "BENCHMARK_TICKER",
    "BENCHMARK_AUTO_ADJUST",
)


if __name__ == "__main__":
    sys.exit(main())

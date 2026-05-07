"""Guarded writer for ``auto_adjust_mismatch_for_20d`` cache rows.

The auto-adjust mismatch is the cleanest sub-bucket in the
``no_forward_20d`` blocker family: the cache HAS the data — it is just
filed under the wrong ``auto_adjust`` flag.  The hydrator reads
``aa=0`` (unadjusted), so any row whose data lives only at ``aa=1``
(adjusted) shows up as ``no_forward_20d_close`` even though no network
fetch is needed to fix it.

This module repairs that gap by copying the matching ``aa=1`` rows
into ``aa=0`` for every date inside ``[event_date, event_date + 20bd]``
that is missing at ``aa=0``.  Pure SQL — no provider call ever, no
``yfinance``, no LLM, no ``market_check``, no ``market_data``.

Safety contract
---------------
* Default behaviour is **preview / dry-run**.  Writes require
  ``confirm=True``.
* Writes additionally require ``backup_path`` so an operator cannot
  ever run a repair without naming the snapshot file the rollback
  would restore from.
* The backup is taken via :func:`shutil.copy2` *before* the first
  ``INSERT``.  If the copy fails the writer raises and no row is
  touched.
* Every applied row appends a JSONL record to the audit log.  The
  audit log is materialised on disk only when ``applied_count > 0``;
  the result dict surfaces the path (or ``None``) under
  ``audit_log_path``.
* ``events.market_tickers`` is never read for write — the repair
  touches ``price_cache`` only.
* Re-running the writer on an already-repaired DB is a no-op
  (``INSERT OR REPLACE`` makes the write idempotent and the
  classifier no longer flags the row as a mismatch).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly.
# ---------------------------------------------------------------------------


def _load_preview_payload(db_path: str | None) -> dict:
    """Reuse the read-only preview tool's payload.

    The preview already enumerates every mismatch row, computes the
    ``[event_date, event_date + 20bd]`` window, and lists the dates
    aa=1 has in that window minus the dates aa=0 has — exactly the
    proposal set the writer needs.  Coupling here is intentional:
    planner and writer share one source of truth for window logic and
    repairability classification.

    Lazy-imports the preview module so this writer's import surface
    stays light and tests can swap the seam without paying the
    diagnostics import cost.
    """
    import db as _db
    from scripts import auto_adjust_mismatch_repair_preview as _preview

    if db_path is not None:
        prev_path, prev_ready = _db.DB_FILE, _db._db_ready
        _db.DB_FILE = db_path
        _db._db_ready = False
        try:
            _db.init_db()
            details = _preview._load_auto_adjust_mismatch_details() or []
            specs = _preview._windows_for_details(details)
            cache_rows = (
                _preview._load_in_window_cache_rows(specs) if specs else {}
            )
            return _preview._build_payload(
                details, cache_rows, limit=10**9,
            )
        finally:
            _db.DB_FILE, _db._db_ready = prev_path, prev_ready

    if not _db._db_ready:
        try:
            _db.init_db()
        except Exception:
            return {
                "total_mismatches":  0,
                "proposed_rows":     [],
            }
    details = _preview._load_auto_adjust_mismatch_details() or []
    specs = _preview._windows_for_details(details)
    cache_rows = (
        _preview._load_in_window_cache_rows(specs) if specs else {}
    )
    return _preview._build_payload(details, cache_rows, limit=10**9)


def _load_aa1_source_rows(
    db_path: str,
    pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], dict]:
    """Return ``{(ticker_upper, iso_date): {close, volume, fetched_at}}``
    for every aa=1 cache row matching one of ``pairs``.

    Used by the planner to surface the source row data the writer
    would copy into ``aa=0``.  Single bulk SELECT — read-only.
    """
    if not pairs:
        return {}
    out: dict[tuple[str, str], dict] = {}
    with sqlite3.connect(db_path) as conn:
        # Build IN-list for tickers; per-ticker date filter happens in
        # Python because each ticker has its own window.
        tickers = sorted({t.upper() for t, _ in pairs})
        placeholders = ",".join("?" for _ in tickers)
        rows = conn.execute(
            f"SELECT ticker, date, close, volume, fetched_at "
            f"FROM price_cache "
            f"WHERE auto_adjust = 1 AND ticker IN ({placeholders})",
            tickers,
        ).fetchall()
    wanted = set(pairs)
    for raw_ticker, raw_date, close, volume, fetched_at in rows:
        if not isinstance(raw_ticker, str) or not isinstance(raw_date, str):
            continue
        key = (raw_ticker.upper(), raw_date[:10])
        if key not in wanted:
            continue
        out[key] = {
            "close":      close,
            "volume":     volume,
            "fetched_at": fetched_at,
        }
    return out


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_REPAIR_ACTION = "insert_aa0_from_aa1"
_REPAIRABLE_STATUS = "repairable_flag_fix"


def _default_audit_log_path() -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return str(Path("audit_logs") / f"auto_adjust_mismatch_repair_{ts}.jsonl")


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def plan_auto_adjust_mismatch_repair(*, db_path: str | None = None) -> dict:
    """Read-only planner.

    Returns the full set of proposed ``aa=0`` inserts the writer
    *would* apply if invoked with ``confirm=True`` and a backup path.
    Issues only ``SELECT`` statements; never writes.
    """
    payload = _load_preview_payload(db_path)
    proposed_rows = payload.get("proposed_rows") or []

    pairs: list[tuple[str, str]] = []
    pair_to_event: dict[tuple[str, str], int | None] = {}
    repairable_rows: list[dict] = []
    for row in proposed_rows:
        if row.get("repair_status") != _REPAIRABLE_STATUS:
            continue
        sym = row.get("symbol")
        if not isinstance(sym, str) or not sym:
            continue
        eid = row.get("event_id")
        repairable_rows.append(row)
        for d in row.get("proposed_row_dates") or []:
            key = (sym.upper(), d)
            pairs.append(key)
            # First event id wins — repeated (ticker, date) pairs
            # across multiple events still get logged under the first
            # event so the audit row references a real source.
            pair_to_event.setdefault(key, eid)

    # Resolve db_path for the source-row SELECT.  When the caller did
    # not pass one, fall back to the in-process default.
    if db_path is None:
        import db as _db
        target_db = _db.DB_FILE
    else:
        target_db = db_path

    # Deduplicate pairs while keeping a stable order.
    seen: set[tuple[str, str]] = set()
    unique_pairs: list[tuple[str, str]] = []
    for p in pairs:
        if p in seen:
            continue
        seen.add(p)
        unique_pairs.append(p)

    try:
        source_rows = _load_aa1_source_rows(target_db, unique_pairs)
    except sqlite3.Error:
        source_rows = {}

    planned_writes: list[dict] = []
    for ticker, iso_date in unique_pairs:
        src = source_rows.get((ticker, iso_date))
        if src is None:
            continue
        planned_writes.append({
            "ticker":          ticker,
            "date":            iso_date,
            "close":           src["close"],
            "volume":          src["volume"],
            "auto_adjust":     0,
            "fetched_at":      src["fetched_at"],
            "source_event_id": pair_to_event.get((ticker, iso_date)),
        })

    return {
        "available":           True,
        "total_mismatches":    int(payload.get("total_mismatches") or 0),
        "repairable_count":    int(payload.get("repairable_count") or 0),
        "planned_writes":      planned_writes,
        "planned_write_count": len(planned_writes),
    }


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def apply_auto_adjust_mismatch_repair(
    *,
    db_path: str | None = None,
    confirm: bool = False,
    backup_path: str | None = None,
    audit_log_path: str | None = None,
) -> dict:
    """Apply the auto-adjust mismatch repair.

    Default mode (``confirm=False``) is a strict dry-run: the planner
    runs but no row is touched and no audit log file is created.

    Write mode requires ``confirm=True`` AND ``backup_path``.  The
    function copies the live DB to ``backup_path`` (via
    :func:`shutil.copy2`) before any ``INSERT``; a copy failure raises
    and the DB is left untouched.

    Returns a dict carrying the planner output plus, on write,
    ``applied_count``, ``applied_writes``, ``backup_path`` and
    ``audit_log_path``.  The ``audit_log_path`` key is always present;
    its value is ``None`` when no row was written.
    """
    if confirm and not backup_path:
        raise ValueError(
            "apply_auto_adjust_mismatch_repair: confirm=True requires "
            "a backup_path (snapshot the DB before any write).",
        )

    plan = plan_auto_adjust_mismatch_repair(db_path=db_path)
    planned = plan["planned_writes"]

    if not confirm:
        return {
            **plan,
            "confirm":         False,
            "applied_count":   0,
            "applied_writes":  [],
            "backup_path":     None,
            "audit_log_path":  None,
        }

    target_db = db_path
    if target_db is None:
        import db as _db
        target_db = _db.DB_FILE

    # Backup BEFORE the first write — copy2 propagates IOError /
    # PermissionError naturally so the caller sees the failure.
    shutil.copy2(target_db, backup_path)

    if not planned:
        return {
            **plan,
            "confirm":         True,
            "applied_count":   0,
            "applied_writes":  [],
            "backup_path":     backup_path,
            "audit_log_path":  None,
        }

    resolved_audit = audit_log_path or _default_audit_log_path()
    audit_dir = Path(resolved_audit).parent
    if str(audit_dir) and audit_dir != Path(""):
        audit_dir.mkdir(parents=True, exist_ok=True)

    applied: list[dict] = []
    with sqlite3.connect(target_db) as conn:
        for w in planned:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    w["ticker"],
                    w["date"],
                    w["close"],
                    w["volume"],
                    int(w["auto_adjust"]),
                    w["fetched_at"],
                ),
            )
            applied.append(dict(w))
        conn.commit()

    # Append-only audit log — one JSONL record per applied write.
    ts = datetime.now(tz=timezone.utc).isoformat()
    with open(resolved_audit, "a", encoding="utf-8") as f:
        for w in applied:
            rec = {
                "ts":                    ts,
                "ticker":                w["ticker"],
                "date":                  w["date"],
                "auto_adjust":           int(w["auto_adjust"]),
                "close":                 w["close"],
                "volume":                w["volume"],
                "source_aa1_fetched_at": w["fetched_at"],
                "source_event_id":       w.get("source_event_id"),
                "action":                _REPAIR_ACTION,
            }
            f.write(json.dumps(rec, default=str) + "\n")

    return {
        **plan,
        "confirm":         True,
        "applied_count":   len(applied),
        "applied_writes":  applied,
        "backup_path":     backup_path,
        "audit_log_path":  resolved_audit,
    }


__all__: tuple[str, ...] = (
    "plan_auto_adjust_mismatch_repair",
    "apply_auto_adjust_mismatch_repair",
)

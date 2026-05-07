"""Backup-restore drift harness — pure read-only.

Compares a SQLite ``events.db`` backup against the live archive without
ever modifying either.  The backup is copied to a temp file before any
read so a downstream regression that *did* try to write can never
corrupt the operator's preserved snapshot, and the live DB is opened
``mode=ro`` so even SELECT statements can't create a side-effect
journal file.

Diagnostics computed for both sides:

  * ``schema``                  — every non-internal table's sorted
    column list.
  * ``archive_counts``          — ``COUNT(*)`` for ``events`` and
    ``price_cache``.
  * ``event_date_backfill``     — pure-SQL summary of the event-date
    backfill candidate set (mirrors
    :func:`event_date_backfill.plan_event_date_backfill` aggregates
    without invoking the planner; the planner opens the DB in
    read-write mode which would defeat the ``mode=ro`` guarantee on
    the live DB).
  * ``reaction_profile_blockers`` — deliberately skipped.  The route
    handler in :mod:`routes.diagnostics` calls
    ``hydrate_per_ticker_profile`` which transitively calls
    :func:`price_cache._ensure_table`, whose first-call
    ``_purge_corrupt_rows`` path is a write.  Calling it against the
    live DB would violate the no-mutation contract.

Drift rules:

  * **Error** when any table is missing on either side or when a
    table's column-set differs.
  * **Warning** when a row count differs by more than 5%.
  * Diagnostic-level numeric drift is reported but not classified;
    operators decide whether the change is expected.

Never imports ``yfinance`` / ``market_check`` / ``market_data`` /
``price_cache`` / ``db`` / ``api`` / FastAPI.  Pure stdlib + ``json``.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import date as _date
from pathlib import Path
from typing import Any


_DEFAULT_TABLES_OF_INTEREST: tuple[str, ...] = ("events", "price_cache")
_ROW_COUNT_DRIFT_WARN_PCT: float = 5.0

_REACTION_PROFILE_BLOCKERS_SKIP_REASON = (
    "skipped: routes.diagnostics._compute_reaction_profile_blockers "
    "transitively calls price_cache._ensure_table -> "
    "_purge_corrupt_rows, which is a write path; running it against "
    "the live DB would violate the no-mutation contract."
)


# ---------------------------------------------------------------------------
# Read-only DB helpers
# ---------------------------------------------------------------------------


def _read_only_connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-only sqlite3 connection.

    Uses the URI ``mode=ro`` form so SQLite refuses any write attempt
    AND does not create the side-effect journal file a default-mode
    connection would.  The harness must use this for every read of a
    live DB the operator wants byte-preserved.
    """
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    """Return user tables (excluding sqlite_* internal tables) sorted."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return sorted([r[0] for r in rows])


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return the sorted column-name list for ``table``.

    Uses ``pragma_table_info(?)`` so the table name is parameterised
    rather than f-string concatenated — defence in depth even though
    the table name comes from ``sqlite_master`` and not user input.
    """
    rows = conn.execute(
        "SELECT name FROM pragma_table_info(?)", (table,),
    ).fetchall()
    return sorted([r[0] for r in rows])


# ---------------------------------------------------------------------------
# Diagnostic computers — each returns a JSON-serialisable dict
# ---------------------------------------------------------------------------


def compute_schema(db_path: str | Path) -> dict[str, list[str]]:
    """Return ``{table_name: sorted([columns])}`` for every user table."""
    conn = _read_only_connect(db_path)
    try:
        tables = _list_tables(conn)
        return {t: _table_columns(conn, t) for t in tables}
    finally:
        conn.close()


def compute_archive_counts(
    db_path: str | Path,
    *,
    tables: tuple[str, ...] = _DEFAULT_TABLES_OF_INTEREST,
) -> dict[str, int]:
    """Return ``{table_name: COUNT(*)}`` for ``tables``.

    Tables that do not exist in the DB collapse to 0 rather than
    raising — a missing table is detected separately by the schema
    drift check, where it surfaces as an error.
    """
    out: dict[str, int] = {}
    conn = _read_only_connect(db_path)
    try:
        present = set(_list_tables(conn))
        for table in tables:
            if table not in present:
                out[table] = 0
                continue
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()
                out[table] = int(row[0]) if row else 0
            except sqlite3.Error:
                out[table] = 0
    finally:
        conn.close()
    return out


def compute_event_date_backfill_summary(
    db_path: str | Path,
) -> dict[str, int]:
    """Mirror the planner's aggregate counts via pure SQL.

    Returns ``{total_candidates, ticker_rows_blocked,
    proposed_updates_count}``.  Never invokes the planner directly —
    :func:`event_date_backfill.plan_event_date_backfill` opens the DB
    in read-write mode, which would defeat the ``mode=ro`` guarantee
    on the live DB.
    """
    out = {
        "total_candidates":       0,
        "ticker_rows_blocked":    0,
        "proposed_updates_count": 0,
    }
    conn = _read_only_connect(db_path)
    try:
        present = set(_list_tables(conn))
        if "events" not in present:
            return out
        try:
            rows = conn.execute(
                "SELECT timestamp, market_tickers FROM events "
                "WHERE (event_date IS NULL OR event_date = '') "
                "  AND timestamp IS NOT NULL AND timestamp != ''"
            ).fetchall()
        except sqlite3.Error:
            return out
    finally:
        conn.close()

    out["total_candidates"] = len(rows)
    for timestamp, market_tickers_blob in rows:
        symbols = _parse_ticker_symbols(market_tickers_blob)
        out["ticker_rows_blocked"] += len(symbols)
        if _parse_iso_date_prefix(timestamp) is not None:
            out["proposed_updates_count"] += 1
    return out


def _parse_ticker_symbols(blob: Any) -> list[str]:
    """Decode a stored ``market_tickers`` JSON blob into upper-cased
    symbol strings.  Tolerant of malformed input — returns an empty
    list on any parse failure.  Inlined so this module never imports
    ``db.py``."""
    if not blob:
        return []
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except (TypeError, ValueError):
            return []
    if not isinstance(blob, list):
        return []
    out: list[str] = []
    for entry in blob:
        if not isinstance(entry, dict):
            continue
        sym = str(entry.get("symbol") or "").strip().upper()
        if sym:
            out.append(sym)
    return out


def _parse_iso_date_prefix(timestamp: Any) -> str | None:
    if not (isinstance(timestamp, str) and len(timestamp) >= 10):
        return None
    try:
        return _date.fromisoformat(timestamp[:10]).isoformat()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Drift classification
# ---------------------------------------------------------------------------


def _schema_drift(
    backup_schema: dict[str, list[str]],
    live_schema:   dict[str, list[str]],
) -> dict[str, Any]:
    backup_tables = set(backup_schema)
    live_tables   = set(live_schema)
    missing_in_live   = sorted(backup_tables - live_tables)
    missing_in_backup = sorted(live_tables - backup_tables)
    column_drift: dict[str, dict[str, list[str]]] = {}
    for table in sorted(backup_tables & live_tables):
        b_cols = set(backup_schema[table])
        l_cols = set(live_schema[table])
        if b_cols == l_cols:
            continue
        column_drift[table] = {
            "missing_in_live":   sorted(b_cols - l_cols),
            "missing_in_backup": sorted(l_cols - b_cols),
        }
    drift_detected = bool(
        missing_in_live or missing_in_backup or column_drift,
    )
    return {
        "backup_tables":     sorted(backup_tables),
        "live_tables":       sorted(live_tables),
        "missing_in_live":   missing_in_live,
        "missing_in_backup": missing_in_backup,
        "column_drift":      column_drift,
        "drift_detected":    drift_detected,
    }


def _row_count_drift(
    backup_counts: dict[str, int],
    live_counts:   dict[str, int],
) -> dict[str, dict[str, float]]:
    """Compute per-table drift_pct.

    drift_pct = abs(live - backup) / max(backup, live, 1) * 100.

    The ``max(..., 1)`` denominator keeps both-zero collapsed to 0%
    drift instead of NaN, and prevents a single-row backup from
    inflating a 1-row delta to 100%.
    """
    out: dict[str, dict[str, float]] = {}
    keys = sorted(set(backup_counts) | set(live_counts))
    for key in keys:
        b = int(backup_counts.get(key, 0))
        l = int(live_counts.get(key, 0))
        denom = max(b, l, 1)
        drift = abs(l - b) / denom * 100.0
        out[key] = {
            "backup":    b,
            "live":      l,
            "drift_pct": round(drift, 4),
        }
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def diff_backup_against_live(
    *,
    backup_path: str | Path,
    live_db_path: str | Path,
    keep_temp: bool = False,
) -> dict[str, Any]:
    """Copy ``backup_path`` to a temp DB, run pure read-only diagnostics
    on both sides, and return the drift report.

    Never modifies either input file.  The live DB is read via
    ``mode=ro``; the backup is duplicated to a temp file so the read
    side cannot perturb the operator's preserved snapshot.

    Returns a dict with keys ``ok``, ``backup_path``, ``live_db_path``,
    ``temp_backup_path``, ``diagnostics``, ``warnings``, ``errors``.
    Warnings/errors lists are sorted for determinism.
    """
    backup_path = Path(backup_path)
    live_db_path = Path(live_db_path)
    warnings: list[str] = []
    errors: list[str] = []

    if not backup_path.is_file():
        errors.append(f"backup file does not exist: {backup_path}")
    if not live_db_path.is_file():
        errors.append(f"live DB does not exist: {live_db_path}")

    if errors:
        return _compose_report(
            backup_path=str(backup_path),
            live_db_path=str(live_db_path),
            temp_backup_path=None,
            diagnostics={},
            warnings=warnings,
            errors=errors,
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="backup_restore_diff_"))
    temp_backup_path = temp_dir / "backup_copy.db"
    try:
        shutil.copy2(str(backup_path), str(temp_backup_path))

        diagnostics: dict[str, Any] = {}

        backup_schema = compute_schema(temp_backup_path)
        live_schema   = compute_schema(live_db_path)
        schema_block  = _schema_drift(backup_schema, live_schema)
        diagnostics["schema"] = {
            "backup": backup_schema,
            "live":   live_schema,
            "drift":  schema_block,
        }
        if schema_block["drift_detected"]:
            for table in schema_block["missing_in_live"]:
                errors.append(f"schema drift: table missing in live: {table}")
            for table in schema_block["missing_in_backup"]:
                errors.append(f"schema drift: table missing in backup: {table}")
            for table, cols in schema_block["column_drift"].items():
                errors.append(
                    "schema drift: column set differs in "
                    f"{table!r}: missing_in_live="
                    f"{cols['missing_in_live']!r} "
                    f"missing_in_backup={cols['missing_in_backup']!r}"
                )

        backup_counts = compute_archive_counts(temp_backup_path)
        live_counts   = compute_archive_counts(live_db_path)
        archive_block = _row_count_drift(backup_counts, live_counts)
        diagnostics["archive_counts"] = archive_block
        for table, stats in archive_block.items():
            if stats["drift_pct"] > _ROW_COUNT_DRIFT_WARN_PCT:
                warnings.append(
                    f"row-count drift {stats['drift_pct']:.2f}% on "
                    f"{table!r}: backup={stats['backup']} "
                    f"live={stats['live']}"
                )

        backup_edb = compute_event_date_backfill_summary(temp_backup_path)
        live_edb   = compute_event_date_backfill_summary(live_db_path)
        diagnostics["event_date_backfill"] = {
            "backup": backup_edb,
            "live":   live_edb,
        }

        diagnostics["reaction_profile_blockers"] = {
            "skipped": True,
            "reason":  _REACTION_PROFILE_BLOCKERS_SKIP_REASON,
        }
    finally:
        if not keep_temp:
            shutil.rmtree(str(temp_dir), ignore_errors=True)

    return _compose_report(
        backup_path=str(backup_path),
        live_db_path=str(live_db_path),
        temp_backup_path=(
            str(temp_backup_path) if keep_temp else None
        ),
        diagnostics=diagnostics,
        warnings=warnings,
        errors=errors,
    )


def _compose_report(
    *,
    backup_path: str,
    live_db_path: str,
    temp_backup_path: str | None,
    diagnostics: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "ok":               len(errors) == 0,
        "backup_path":      backup_path,
        "live_db_path":     live_db_path,
        "temp_backup_path": temp_backup_path,
        "diagnostics":      diagnostics,
        "warnings":         sorted(warnings),
        "errors":           sorted(errors),
    }


# ---------------------------------------------------------------------------
# Latest-backup resolver
# ---------------------------------------------------------------------------


def resolve_latest_backup(
    backups_dir: str | Path,
    *,
    pattern: str = "events-*.db",
) -> Path | None:
    """Return the lexicographically newest backup matching ``pattern``.

    ``backup_archive.py`` writes ``events-YYYYMMDDTHHMMSS.db`` so
    lexicographic order matches chronological order.  Returns ``None``
    when the directory is missing or empty so callers can render a
    clean error.
    """
    p = Path(backups_dir)
    if not p.is_dir():
        return None
    matches = sorted(p.glob(pattern))
    return matches[-1] if matches else None

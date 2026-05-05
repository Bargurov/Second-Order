#!/usr/bin/env python3
"""scripts/schema_preflight.py

Zero-cost SQLite schema preflight checker.

Read-only inspection of ``events.db`` and the ``backups/`` directory.
Prints a human-readable summary or — with ``--json`` — a structured
dump of the same data for CI / future automation.

Never writes to the DB or filesystem; never imports the app, ``yfinance``,
``market_check``, or any provider seam.  Safe to run before any future
schema migration as a pre-flight check.

Usage::

    python scripts/schema_preflight.py
    python scripts/schema_preflight.py --db events.db --backup-dir backups/
    python scripts/schema_preflight.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_DB:                       str = "events.db"
_DEFAULT_BACKUP_DIR:               str = "backups"
_BACKUP_STALE_THRESHOLD_SECONDS:   int = 24 * 3600


# ---------------------------------------------------------------------------
# Pure collector — no I/O beyond the named DB / backup paths.
# ---------------------------------------------------------------------------

def collect(
    db_path: str,
    backup_dir: str,
    *,
    now: Optional[float] = None,
) -> dict:
    """Read-only schema + backup inspection.  Never raises.

    Returns a JSON-serialisable dict:

        database_path             — echoed input
        database_exists           — bool
        database_size_bytes       — int | None
        tables                    — list[str]
        events_columns            — list[str]
        price_cache_present       — bool
        backup_dir                — echoed input
        backup_dir_exists         — bool
        latest_backup             — str | None  (path)
        latest_backup_age_seconds — int | None
        warnings                  — list[str]

    ``now`` is injected for testability — defaults to ``time.time()``.
    """
    db = Path(db_path)
    bd = Path(backup_dir)
    now_ts = now if now is not None else time.time()

    info: dict = {
        "database_path":             str(db),
        "database_exists":           db.exists() and db.is_file(),
        "database_size_bytes":       None,
        "tables":                    [],
        "events_columns":            [],
        "price_cache_present":       False,
        "backup_dir":                str(bd),
        "backup_dir_exists":         bd.exists() and bd.is_dir(),
        "latest_backup":             None,
        "latest_backup_age_seconds": None,
        "warnings":                  [],
    }

    # --- Database read (schema only; no row data) ---
    if info["database_exists"]:
        try:
            info["database_size_bytes"] = db.stat().st_size
        except OSError as e:
            info["warnings"].append(f"could not stat database file: {e}")

        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
                tables = [r[0] for r in rows]
                info["tables"] = tables
                info["price_cache_present"] = "price_cache" in tables
                if "events" in tables:
                    info["events_columns"] = [
                        r[1] for r in conn.execute(
                            "PRAGMA table_info(events)"
                        ).fetchall()
                    ]
                else:
                    info["warnings"].append(
                        "events table missing from database"
                    )
        except sqlite3.Error as e:
            info["warnings"].append(f"sqlite read error: {e}")
    else:
        info["warnings"].append(f"database file does not exist: {db}")

    # --- Backup directory scan ---
    if info["backup_dir_exists"]:
        entries: list[Path] = []
        try:
            entries = [p for p in bd.iterdir() if p.is_file()]
        except OSError as e:
            info["warnings"].append(f"could not list backup dir: {e}")

        if entries:
            entries.sort(
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            latest = entries[0]
            try:
                mtime = latest.stat().st_mtime
            except OSError as e:
                mtime = None
                info["warnings"].append(
                    f"could not stat latest backup: {e}"
                )
            if mtime is not None:
                age = max(0, int(now_ts - mtime))
                info["latest_backup"] = str(latest)
                info["latest_backup_age_seconds"] = age
                if age > _BACKUP_STALE_THRESHOLD_SECONDS:
                    info["warnings"].append(
                        f"latest backup is {age // 3600}h old "
                        f"(>24h threshold): {latest.name}"
                    )
        else:
            info["warnings"].append(f"no backup files found in {bd}")
    else:
        info["warnings"].append(f"backup directory does not exist: {bd}")

    return info


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def render_text(info: dict) -> str:
    """Render the collector dict as a human-readable summary."""
    lines: list[str] = []
    lines.append("=== Schema Preflight ===")
    lines.append(f"Database path:    {info['database_path']}")
    lines.append(f"  exists:         {info['database_exists']}")
    if info["database_size_bytes"] is not None:
        lines.append(f"  size:           {info['database_size_bytes']} bytes")

    tables = info["tables"]
    lines.append(
        f"Tables ({len(tables)}): "
        + (", ".join(tables) if tables else "(none)")
    )
    lines.append(f"  price_cache present: {info['price_cache_present']}")

    cols = info["events_columns"]
    if cols:
        lines.append(f"events columns ({len(cols)}):")
        chunk: list[str] = []
        chunk_len = 0
        for col in cols:
            if chunk_len + len(col) + 2 > 80:
                lines.append("  " + ", ".join(chunk))
                chunk = []
                chunk_len = 0
            chunk.append(col)
            chunk_len += len(col) + 2
        if chunk:
            lines.append("  " + ", ".join(chunk))
    else:
        lines.append("events columns: (none)")

    lines.append(f"Backup dir:       {info['backup_dir']}")
    lines.append(f"  exists:         {info['backup_dir_exists']}")
    if info["latest_backup"]:
        age_h = (info["latest_backup_age_seconds"] or 0) / 3600.0
        lines.append(
            f"  latest backup:  {info['latest_backup']} ({age_h:.1f}h old)"
        )
    else:
        lines.append("  latest backup:  (none)")

    warnings = info["warnings"]
    if warnings:
        lines.append(f"Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Warnings: (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only SQLite schema + backup preflight check.  Run "
            "before any DB schema migration."
        ),
    )
    parser.add_argument(
        "--db", default=_DEFAULT_DB,
        help=f"Path to events SQLite DB (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--backup-dir", default=_DEFAULT_BACKUP_DIR,
        help=f"Path to backups directory (default: {_DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit a structured JSON dump instead of text",
    )
    args = parser.parse_args(argv)

    info = collect(args.db, args.backup_dir)
    if args.as_json:
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        print(render_text(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())

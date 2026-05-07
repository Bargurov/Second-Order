#!/usr/bin/env python3
"""scripts/backup_restore_check.py

Read-only restore validation for a SQLite archive backup.

Copies a backup file to a temporary SQLite file and inspects the copy:
required tables exist, ``events`` and ``price_cache`` are readable,
row counts are reported (zero or otherwise), and the schema shape is
compatible with ``scripts/schema_preflight.py``.  The original backup
is opened only for reading; ``events.db`` is never touched.

Out of scope (deliberately)
---------------------------
* No write back to ``events.db`` — it is never opened, read, or
  referenced.
* No FastAPI app surface.  No ``api`` / ``routes.*`` imports.
* No provider, ``yfinance``, ``market_check``, ``market_data``, or
  ``price_cache`` (the production module) imports — the script only
  speaks raw ``sqlite3`` to the temp copy.
* No LLM seam.

Usage::

    python scripts/backup_restore_check.py --backup-path backups/events-20260507T120000.db
    python scripts/backup_restore_check.py --latest
    python scripts/backup_restore_check.py --latest --json
    python scripts/backup_restore_check.py --latest --keep-temp
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional


_DEFAULT_BACKUP_DIR = Path("backups")
_BACKUP_GLOB        = "events-*.db"
_REQUIRED_TABLES    = ("events", "price_cache")


# ---------------------------------------------------------------------------
# Backup discovery
# ---------------------------------------------------------------------------


def find_latest_backup(backup_dir: Path) -> Optional[Path]:
    """Return the newest ``events-*.db`` file in ``backup_dir`` by
    mtime, or ``None`` if the directory is missing or empty."""
    if not backup_dir.exists() or not backup_dir.is_dir():
        return None
    candidates = [p for p in backup_dir.glob(_BACKUP_GLOB) if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------------


def _make_empty_result() -> dict:
    return {
        "ok":                  False,
        "backup_path":         None,
        "temp_copy_path":      None,
        "table_counts":        {},
        "warnings":            [],
        "errors":              [],
        # schema_preflight-compatible extras
        "tables":              [],
        "events_columns":      [],
        "price_cache_present": False,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def restore_check(
    *,
    backup_path: Optional[Path] = None,
    use_latest: bool = False,
    backup_dir: Path = _DEFAULT_BACKUP_DIR,
    cleanup: bool = True,
) -> dict:
    """Validate a backup file by copying it to a temp DB and inspecting
    the copy.  Read-only against the source backup; ``events.db`` is
    never touched.

    Parameters
    ----------
    backup_path
        Explicit backup file to validate.  Mutually exclusive with
        ``use_latest``.
    use_latest
        If ``True``, pick the newest ``events-*.db`` file in
        ``backup_dir``.
    backup_dir
        Directory searched when ``use_latest=True``.  Defaults to
        ``backups/``.
    cleanup
        If ``True`` (default), the temporary copy is removed before
        return.  ``temp_copy_path`` in the result still records the
        path that was used.

    Returns
    -------
    dict with keys: ``ok``, ``backup_path``, ``temp_copy_path``,
    ``table_counts``, ``warnings``, ``errors``, plus
    ``tables`` / ``events_columns`` / ``price_cache_present`` for
    ``schema_preflight``-compatible introspection.
    """
    result = _make_empty_result()

    # 1. Resolve backup path.
    if use_latest and backup_path is not None:
        result["errors"].append(
            "--backup-path and --latest are mutually exclusive",
        )
        return result
    if use_latest:
        resolved = find_latest_backup(Path(backup_dir))
        if resolved is None:
            result["errors"].append(
                f"no {_BACKUP_GLOB} backups found in {backup_dir}",
            )
            return result
    elif backup_path is not None:
        resolved = Path(backup_path)
    else:
        result["errors"].append(
            "must provide --backup-path or --latest",
        )
        return result

    result["backup_path"] = str(resolved)

    if not resolved.exists():
        result["errors"].append(f"backup file does not exist: {resolved}")
        return result
    if not resolved.is_file():
        result["errors"].append(f"backup path is not a file: {resolved}")
        return result

    # 2. Copy to a temp file (bytes verbatim; source is never written).
    fd, tmp_str = tempfile.mkstemp(prefix="backup_restore_", suffix=".db")
    os.close(fd)
    tmp = Path(tmp_str)
    result["temp_copy_path"] = str(tmp)

    try:
        try:
            shutil.copy2(str(resolved), str(tmp))
        except OSError as exc:
            result["errors"].append(
                "failed to copy backup to temp location: "
                f"{type(exc).__name__}: {exc}",
            )
            return result

        # 3. Open the copy read-only and inspect.
        try:
            uri = tmp.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            try:
                _inspect_temp_db(conn, result)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            result["errors"].append(
                "sqlite open/read error: "
                f"{type(exc).__name__}: {exc}",
            )
            return result

        # 4. Compute ok flag — errors trump warnings.
        result["ok"] = not result["errors"]
        return result
    finally:
        if cleanup:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _inspect_temp_db(conn: sqlite3.Connection, result: dict) -> None:
    """Inspect a read-only connection to the temp copy.  Mutates
    ``result`` in place."""
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name",
        ).fetchall()
    except sqlite3.Error as exc:
        result["errors"].append(
            f"could not list tables: {type(exc).__name__}: {exc}",
        )
        return

    tables = [r[0] for r in rows]
    result["tables"] = tables
    result["price_cache_present"] = "price_cache" in tables

    for required in _REQUIRED_TABLES:
        if required not in tables:
            result["errors"].append(f"required table missing: {required}")

    if "events" in tables:
        try:
            result["events_columns"] = [
                r[1] for r in conn.execute(
                    "PRAGMA table_info(events)",
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            result["errors"].append(
                "could not read events columns: "
                f"{type(exc).__name__}: {exc}",
            )

    for required in _REQUIRED_TABLES:
        if required not in tables:
            continue
        try:
            # Safe interpolation: ``required`` is from the internal
            # whitelist ``_REQUIRED_TABLES``; never user-supplied.
            count = conn.execute(
                f"SELECT COUNT(*) FROM {required}",
            ).fetchone()[0]
        except sqlite3.Error as exc:
            result["errors"].append(
                f"could not read {required}: "
                f"{type(exc).__name__}: {exc}",
            )
            continue
        result["table_counts"][required] = int(count)
        if count == 0:
            result["warnings"].append(f"{required} table is empty (0 rows)")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only restore check for a SQLite backup file.  Copies "
            "the backup to a temp file and validates it.  Never "
            "overwrites events.db."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--backup-path",
        dest="backup_path",
        default=None,
        help="Path to a specific backup file to validate.",
    )
    group.add_argument(
        "--latest",
        action="store_true",
        help=(
            f"Validate the newest {_BACKUP_GLOB} file in --backup-dir "
            f"(default: {_DEFAULT_BACKUP_DIR}/)."
        ),
    )
    parser.add_argument(
        "--backup-dir",
        dest="backup_dir",
        default=str(_DEFAULT_BACKUP_DIR),
        help=f"Backup directory (default: {_DEFAULT_BACKUP_DIR}/).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        dest="keep_temp",
        help="Do not delete the temporary copy after validation.",
    )
    return parser.parse_args(argv)


def _render_text(result: dict) -> str:
    lines = ["=== Backup Restore Check ==="]
    lines.append(f"backup_path:    {result.get('backup_path') or '(none)'}")
    lines.append(f"temp_copy_path: {result.get('temp_copy_path') or '(none)'}")
    lines.append(f"ok:             {result['ok']}")

    counts = result.get("table_counts") or {}
    if counts:
        lines.append("Table counts:")
        for k in sorted(counts):
            lines.append(f"  {k}: {counts[k]}")
    else:
        lines.append("Table counts: (none)")

    tables = result.get("tables") or []
    lines.append(
        f"Tables ({len(tables)}): "
        + (", ".join(tables) if tables else "(none)"),
    )

    cols = result.get("events_columns") or []
    lines.append(f"events columns: {len(cols)}")

    warnings = result.get("warnings") or []
    if warnings:
        lines.append(f"Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Warnings: (none)")

    errors = result.get("errors") or []
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    else:
        lines.append("Errors: (none)")

    return "\n".join(lines)


def main(argv: Optional[list[str]] = None, *, out=None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    backup_path = Path(args.backup_path) if args.backup_path else None
    backup_dir  = Path(args.backup_dir)

    result = restore_check(
        backup_path=backup_path,
        use_latest=args.latest,
        backup_dir=backup_dir,
        cleanup=not args.keep_temp,
    )

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(result), file=output)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

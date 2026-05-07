#!/usr/bin/env python3
"""scripts/event_date_backfill_write_smoke.py

Live-safety probe for ``event_date_backfill`` write mode.

Resolves a backup file (``--backup-path`` or ``--latest``), copies it
to a temp SQLite file, then runs the full write-mode flow against the
*temp copy only*: dry-run → ``apply_event_date_backfill(confirm=True)``
→ second apply (idempotency) → dry-run.  The live ``events.db`` is
hashed before and after the run and the probe fails if anything moved.

Out of scope (deliberately)
---------------------------
* No write back to the live ``events.db`` — ``db.DB_FILE`` is never
  read or referenced.  The writer is invoked with an explicit
  ``db_path`` pointing at the temp copy.
* No FastAPI app surface.  No ``api`` / ``routes.*`` imports.
* No provider, ``yfinance``, ``market_check``, ``market_data``, or
  production ``price_cache`` import — the probe only re-uses the
  planner / writer functions, which themselves never touch those
  seams.
* No LLM seam.

Usage::

    python scripts/event_date_backfill_write_smoke.py --backup-path backups/events-20260507T120000.db
    python scripts/event_date_backfill_write_smoke.py --latest
    python scripts/event_date_backfill_write_smoke.py --latest --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Module-level seams — tests patch on the probe's namespace.
from event_date_backfill          import (  # noqa: E402
    apply_event_date_backfill,
    plan_event_date_backfill,
)
from scripts.backup_restore_check import find_latest_backup  # noqa: E402


_DEFAULT_BACKUP_DIR = "backups"
_DEFAULT_LIVE_DB    = "events.db"
_BACKUP_GLOB        = "events-*.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slim_plan(plan: dict) -> dict:
    return {
        "total_candidates":    plan.get("total_candidates",    0),
        "ticker_rows_blocked": plan.get("ticker_rows_blocked", 0),
    }


def _empty_result() -> dict:
    return {
        "ok":                False,
        "backup_path":       None,
        "temp_copy_path":    None,
        "live_db_path":      None,
        "live_db_unchanged": None,
        "before":            None,
        "write":             None,
        "after":             None,
        "idempotency":       None,
        "warnings":          [],
        "errors":            [],
    }


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def run_write_smoke(
    *,
    backup_path:  Optional[Path] = None,
    use_latest:   bool = False,
    backup_dir:   str  = _DEFAULT_BACKUP_DIR,
    live_db_path: str  = _DEFAULT_LIVE_DB,
) -> dict:
    """Execute a full write-mode smoke against a temp copy of a backup.

    The live ``events.db`` is hashed before and after the run; the
    probe fails if the file changed, was created, or disappeared.
    """
    result = _empty_result()
    result["live_db_path"] = str(live_db_path)

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

    # 2. Snapshot the live events.db.
    live_db = Path(live_db_path)
    live_existed = live_db.exists() and live_db.is_file()
    live_hash_before:  Optional[str]   = None
    live_mtime_before: Optional[float] = None
    if live_existed:
        live_hash_before  = _hash_file(live_db)
        live_mtime_before = live_db.stat().st_mtime
    else:
        result["warnings"].append(
            f"live events.db not found at {live_db}; "
            "skipping byte-equality check (still asserting it stays absent)",
        )

    # 3. Copy backup → temp.
    fd, tmp_str = tempfile.mkstemp(prefix="evb_smoke_", suffix=".db")
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

        # 3a. Pre-flight: the planner swallows sqlite3.Error and
        # returns an empty plan, so a corrupt or schema-less file would
        # otherwise look like a clean run with zero candidates.  Open
        # the temp copy directly and confirm the ``events`` table is
        # readable before running the smoke flow.
        preflight_error = _preflight_temp_db(tmp)
        if preflight_error is not None:
            result["errors"].append(preflight_error)
            return result

        # 4. Dry-run BEFORE.
        try:
            before_plan = plan_event_date_backfill(db_path=str(tmp))
        except Exception as exc:
            result["errors"].append(
                f"before plan failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["before"] = _slim_plan(before_plan)

        # 5. Apply with confirm.
        try:
            write_result = apply_event_date_backfill(
                db_path=str(tmp), confirm=True,
            )
        except Exception as exc:
            result["errors"].append(
                f"apply failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["write"] = {
            "applied_count": write_result.get("applied_count", 0),
        }

        # 6. Second apply — must be a no-op.
        try:
            second = apply_event_date_backfill(
                db_path=str(tmp), confirm=True,
            )
        except Exception as exc:
            result["errors"].append(
                f"second apply failed: {type(exc).__name__}: {exc}",
            )
            return result
        second_count = second.get("applied_count", 0)
        result["idempotency"] = {
            "idempotent_second_apply_count": second_count,
            "ok":                            second_count == 0,
        }
        if second_count != 0:
            result["errors"].append(
                "idempotency violation: second apply wrote "
                f"{second_count} row(s)",
            )

        # 7. Dry-run AFTER.
        try:
            after_plan = plan_event_date_backfill(db_path=str(tmp))
        except Exception as exc:
            result["errors"].append(
                f"after plan failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["after"] = _slim_plan(after_plan)

        # 8. Live events.db unchanged check.
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )

        result["ok"] = not result["errors"]
        return result
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _preflight_temp_db(tmp: Path) -> Optional[str]:
    """Open the temp copy read-only and confirm the ``events`` table
    is present and readable.  Returns ``None`` on success, or an
    error-message string describing the failure.
    """
    try:
        uri = tmp.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return (
            "could not open temp copy as a SQLite database: "
            f"{type(exc).__name__}: {exc}"
        )
    try:
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='events'",
            ).fetchall()
        except sqlite3.Error as exc:
            return (
                "temp copy is not a valid SQLite database: "
                f"{type(exc).__name__}: {exc}"
            )
    finally:
        conn.close()
    if not rows:
        return "temp copy is missing required ``events`` table"
    return None


def _classify_live_db_unchanged(
    live_db: Path,
    existed_before: bool,
    hash_before:    Optional[str],
    mtime_before:   Optional[float],
    *,
    errors: list[str],
) -> Optional[bool]:
    exists_after = live_db.exists() and live_db.is_file()

    if existed_before and not exists_after:
        errors.append(f"live events.db disappeared during run: {live_db}")
        return False
    if not existed_before and exists_after:
        errors.append(f"live events.db was created during run: {live_db}")
        return False
    if not existed_before and not exists_after:
        return None  # skipped

    hash_after  = _hash_file(live_db)
    mtime_after = live_db.stat().st_mtime
    unchanged = (
        hash_after  == hash_before
        and mtime_after == mtime_before
    )
    if not unchanged:
        errors.append(
            f"live events.db changed during run: {live_db}",
        )
    return unchanged


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(result: dict) -> str:
    lines: list[str] = ["=== event_date Backfill Write Smoke ==="]
    lines.append(f"backup_path:       {result.get('backup_path')   or '(none)'}")
    lines.append(f"temp_copy_path:    {result.get('temp_copy_path') or '(none)'}")
    lines.append(f"live_db_path:      {result.get('live_db_path')}")
    lines.append(f"live_db_unchanged: {result.get('live_db_unchanged')}")
    lines.append(f"ok:                {result['ok']}")

    for stage in ("before", "write", "after", "idempotency"):
        section = result.get(stage)
        if section is None:
            lines.append(f"{stage}: (not run)")
            continue
        lines.append(f"--- {stage} ---")
        for k in sorted(section):
            lines.append(f"  {k}: {section[k]}")

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live-safety probe for event_date_backfill write mode. "
            "Runs the full dry-run → apply → second-apply → dry-run "
            "flow against a temp copy of a backup.  Never modifies "
            "events.db."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help="Path to a specific backup file to probe.",
    )
    group.add_argument(
        "--latest", action="store_true",
        help=(
            f"Probe the newest {_BACKUP_GLOB} file in --backup-dir "
            f"(default: {_DEFAULT_BACKUP_DIR}/)."
        ),
    )
    parser.add_argument(
        "--backup-dir", dest="backup_dir", default=_DEFAULT_BACKUP_DIR,
        help=f"Backups directory (default: {_DEFAULT_BACKUP_DIR}/).",
    )
    parser.add_argument(
        "--live-db", dest="live_db", default=_DEFAULT_LIVE_DB,
        help=(
            "Path to the live events.db whose hash/mtime must not "
            f"change during the run (default: {_DEFAULT_LIVE_DB})."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    backup_path = Path(args.backup_path) if args.backup_path else None
    backup_dir  = args.backup_dir
    live_db     = args.live_db

    result = run_write_smoke(
        backup_path=backup_path,
        use_latest=args.latest,
        backup_dir=backup_dir,
        live_db_path=live_db,
    )

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(result), file=output)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

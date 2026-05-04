"""Zero-cost local SQLite archive backup.

Copies the local events archive (default: ``events.db``) to a
timestamped file in ``backups/``.  Uses the SQLite backup API so a
running uvicorn (which holds a write connection) can't produce a
torn copy — the source DB is never modified.

Manual command only — no scheduling, no LLM, no provider calls, no
HTTP endpoints touched.

Usage:
    python scripts/backup_archive.py
    python scripts/backup_archive.py --dry-run
    python scripts/backup_archive.py --source events.db --dest-dir backups
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


_DEFAULT_SOURCE   = Path("events.db")
_DEFAULT_DEST_DIR = Path("backups")


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%dT%H%M%S")


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _backup_target_path(dest_dir: Path, source: Path, now: datetime | None = None) -> Path:
    stem = source.stem or "archive"
    return dest_dir / f"{stem}-{_timestamp(now)}.db"


def _live_safe_copy(source: Path, dest: Path) -> None:
    """Copy via sqlite3 ``Connection.backup()``.

    The backup API holds the source DB's read lock for the duration of
    the copy and tolerates a concurrent writer (e.g., a running uvicorn)
    without producing a torn / WAL-mid-flush snapshot.  The destination
    file is created atomically: a partial copy on failure is the only
    side effect, and we delete it before re-raising so the caller's
    second attempt isn't blocked by stale bytes.
    """
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def run_backup(
    source: Path,
    dest_dir: Path,
    *,
    dry_run: bool = False,
    out=sys.stdout,
) -> int:
    """Return 0 on success, non-zero on failure.  ``dry_run`` reports
    the planned source / destination / source size without writing."""
    if not source.exists():
        print(f"[backup] FAIL: source not found: {source}", file=out)
        return 2
    if not source.is_file():
        print(f"[backup] FAIL: source is not a file: {source}", file=out)
        return 2

    src_size = source.stat().st_size
    target = _backup_target_path(dest_dir, source)

    print(f"[backup] source: {source}", file=out)
    print(f"[backup] dest:   {target}", file=out)
    print(f"[backup] size:   {_format_size(src_size)} ({src_size} bytes)", file=out)

    if dry_run:
        print("[backup] dry-run: no files written.", file=out)
        return 0

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        _live_safe_copy(source, target)
    except Exception as exc:
        # Clean up a partial destination so retries start from a clean
        # slate.  We swallow the unlink error (file may not exist if
        # backup() failed before opening the destination).
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"[backup] FAIL: {type(exc).__name__}: {exc}", file=out)
        return 1

    written = target.stat().st_size
    print(f"[backup] wrote:  {_format_size(written)} ({written} bytes)", file=out)
    print("[backup] OK", file=out)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the local SQLite archive to a timestamped backup.",
    )
    parser.add_argument(
        "--source", default=str(_DEFAULT_SOURCE),
        help=f"Source SQLite file (default: {_DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--dest-dir", default=str(_DEFAULT_DEST_DIR),
        help=f"Destination directory (default: {_DEFAULT_DEST_DIR}/).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without writing anything.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run_backup(
        Path(args.source),
        Path(args.dest_dir),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())

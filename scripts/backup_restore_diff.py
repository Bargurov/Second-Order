#!/usr/bin/env python3
"""Backup-restore drift CLI.

Compares a SQLite ``events.db`` backup against the live archive and
emits a structured report.  Read-only — never modifies either input
file.  No FastAPI / no provider / no LLM / no network.

Usage::

    python scripts/backup_restore_diff.py --latest --json
    python scripts/backup_restore_diff.py --backup-path backups/events-X.db --json
    python scripts/backup_restore_diff.py --latest --keep-temp
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backup_restore_diff import (  # noqa: E402
    diff_backup_against_live,
    resolve_latest_backup,
)


_DEFAULT_LIVE_DB:    str = "events.db"
_DEFAULT_BACKUPS_DIR: str = "backups"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Backup-restore drift report", ""]
    lines.append(f"Backup:    {report['backup_path']}")
    lines.append(f"Live DB:   {report['live_db_path']}")
    if report.get("temp_backup_path"):
        lines.append(f"Temp copy: {report['temp_backup_path']} (kept)")
    lines.append("")
    lines.append(f"Status: {'OK' if report['ok'] else 'DRIFT'}")
    lines.append(f"Warnings: {len(report['warnings'])}")
    lines.append(f"Errors:   {len(report['errors'])}")
    if report["errors"]:
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    if report["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")

    diag = report.get("diagnostics") or {}
    archive = diag.get("archive_counts") or {}
    if archive:
        lines.append("")
        lines.append("Archive counts:")
        for table in sorted(archive):
            stats = archive[table]
            lines.append(
                f"  {table}: backup={stats['backup']} "
                f"live={stats['live']} drift={stats['drift_pct']:.2f}%"
            )

    edb = diag.get("event_date_backfill") or {}
    if edb:
        lines.append("")
        lines.append("Event-date backfill:")
        for side in ("backup", "live"):
            s = edb.get(side) or {}
            lines.append(
                f"  {side}: candidates={s.get('total_candidates', 0)} "
                f"ticker_rows_blocked={s.get('ticker_rows_blocked', 0)} "
                f"proposed={s.get('proposed_updates_count', 0)}"
            )

    rpb = diag.get("reaction_profile_blockers") or {}
    if rpb:
        lines.append("")
        lines.append(
            "Reaction-profile blockers: "
            + ("skipped" if rpb.get("skipped") else "computed")
        )
        if rpb.get("reason"):
            lines.append(f"  reason: {rpb['reason']}")

    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a SQLite events.db backup against the live "
            "archive.  Read-only; never modifies either input."
        ),
    )
    backup_src = parser.add_mutually_exclusive_group(required=True)
    backup_src.add_argument(
        "--backup-path",
        dest="backup_path",
        default=None,
        help="Explicit path to a backup .db file.",
    )
    backup_src.add_argument(
        "--latest",
        dest="latest",
        action="store_true",
        help=(
            "Auto-resolve the lexicographically newest "
            "events-*.db file in --backups-dir."
        ),
    )
    parser.add_argument(
        "--live-db",
        dest="live_db",
        default=_DEFAULT_LIVE_DB,
        help=f"Path to the live events.db (default: {_DEFAULT_LIVE_DB}).",
    )
    parser.add_argument(
        "--backups-dir",
        dest="backups_dir",
        default=_DEFAULT_BACKUPS_DIR,
        help=(
            "Directory to scan for --latest "
            f"(default: {_DEFAULT_BACKUPS_DIR})."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--keep-temp",
        dest="keep_temp",
        action="store_true",
        help=(
            "Do not remove the temp backup copy after diffing.  Off "
            "by default — the temp file is deleted unconditionally."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    if args.latest:
        backup = resolve_latest_backup(args.backups_dir)
        if backup is None:
            print(
                f"backup_restore_diff: no backups found in "
                f"{args.backups_dir!r}",
                file=sys.stderr,
            )
            return 2
        backup_path = backup
    else:
        backup_path = Path(args.backup_path)

    report = diff_backup_against_live(
        backup_path=backup_path,
        live_db_path=Path(args.live_db),
        keep_temp=args.keep_temp,
    )

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

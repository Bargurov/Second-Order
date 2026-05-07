#!/usr/bin/env python3
"""Read-only delta report: live ``events.db`` vs latest / named backup.

Why this exists
---------------
A live dry-run of ``scripts/auto_adjust_mismatch_repair.py`` may
surface N planned writes while the same writer run as a smoke test
against ``backups/events-*.db`` reports zero — because backups are
point-in-time snapshots taken before the cache rows that triggered
the mismatch landed.  This report makes that gap explicit.

For each side (live + backup) it surfaces:

  * ``mismatch_count``       — rows the loader classifies as
                               ``auto_adjust_mismatch_for_20d``.
  * ``preview_count``        — rows the preview tool would emit
                               (equal to ``mismatch_count`` by
                               construction; surfaced separately so
                               a delta against either tool's stdout
                               is direct).
  * ``planned_write_count``  — total ``aa=0`` INSERTs the writer's
                               planner would propose; typically
                               larger than ``mismatch_count`` because
                               each event proposes one row per date in
                               its 20bd window that lacks an aa=0
                               entry.
  * ``repairable_count``     — rows classified
                               ``repairable_flag_fix`` by the preview.

Plus per-side DB metadata (``size_bytes``, ``mtime``) and a single
``explanation`` sentence keyed off the deltas.

Read-only contract
------------------
The script copies BOTH live and backup to throwaway temp files before
running the planner, so even ``db.init_db`` migrations (which
``_handle_outdated_db`` could execute on a stale-schema backup) land
on the temp copy.  The originals are byte-identical before and after
every run.  No provider call, no ``yfinance``, no LLM, no FastAPI
seam.

Usage::

    python scripts/auto_adjust_repair_backup_delta_report.py
    python scripts/auto_adjust_repair_backup_delta_report.py --json
    python scripts/auto_adjust_repair_backup_delta_report.py --latest
    python scripts/auto_adjust_repair_backup_delta_report.py \\
        --backup-path backups/events-20260507T120000.db --json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_BACKUPS_DIR = "backups"
_BACKUP_GLOB = "events-*.db"


# ---------------------------------------------------------------------------
# DB metadata + planner runner
# ---------------------------------------------------------------------------


def _db_metadata(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {
            "db_path":   path,
            "exists":    False,
            "size_bytes": None,
            "mtime":      None,
        }
    stat = os.stat(path)
    return {
        "db_path":    path,
        "exists":     True,
        "size_bytes": int(stat.st_size),
        "mtime":      datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc,
        ).isoformat(),
    }


def _empty_counts() -> dict:
    return {
        "mismatch_count":      0,
        "preview_count":       0,
        "planned_write_count": 0,
        "repairable_count":    0,
    }


def _run_planner_against_copy(db_path: str) -> dict:
    """Copy ``db_path`` to a temp file and run the planner against the
    copy.  Guarantees the source DB is never opened for write and
    never sees ``db.init_db`` migrations.

    Returns the four delta-report counts, plus an ``ok`` bool that is
    False when the copy or planner raises (e.g., the source is not a
    valid SQLite file).
    """
    tmp = os.path.join(
        tempfile.gettempdir(),
        f"aa_delta_planner_{uuid.uuid4().hex}.db",
    )
    try:
        shutil.copy2(db_path, tmp)
    except (OSError, PermissionError, shutil.SameFileError):
        return {**_empty_counts(), "ok": False}

    try:
        # Lazy import — keeps the report's surface light when the
        # CLI is parsed but nothing is actually run (e.g. --help).
        import auto_adjust_mismatch_repair as _writer

        plan = _writer.plan_auto_adjust_mismatch_repair(db_path=tmp)
    except Exception:
        plan = None
    finally:
        try:
            os.remove(tmp)
        except (OSError, PermissionError):
            pass

    if not isinstance(plan, dict):
        return {**_empty_counts(), "ok": False}

    mismatch = int(plan.get("total_mismatches") or 0)
    return {
        "mismatch_count":      mismatch,
        "preview_count":       mismatch,
        "planned_write_count": int(plan.get("planned_write_count") or 0),
        "repairable_count":    int(plan.get("repairable_count") or 0),
        "ok": True,
    }


def _per_db_section(path: str | None) -> dict:
    meta = _db_metadata(path)
    if not meta["exists"]:
        return {**meta, **_empty_counts()}
    counts = _run_planner_against_copy(path)
    counts.pop("ok", None)
    return {**meta, **counts}


# ---------------------------------------------------------------------------
# Backup picker
# ---------------------------------------------------------------------------


def _pick_latest_backup(backups_dir: str) -> str | None:
    """Return the max-mtime ``events-*.db`` under ``backups_dir`` or
    ``None`` when the directory is missing / empty."""
    if not os.path.isdir(backups_dir):
        return None
    candidates = list(Path(backups_dir).glob(_BACKUP_GLOB))
    if not candidates:
        return None
    candidates.sort(
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    return str(candidates[0])


def _resolve_backup_path(args: argparse.Namespace) -> str | None:
    """``--backup-path`` wins over ``--latest``; if neither is given,
    behave as ``--latest`` against ``--backups-dir``."""
    if args.backup_path:
        return args.backup_path
    backups_dir = args.backups_dir or _DEFAULT_BACKUPS_DIR
    return _pick_latest_backup(backups_dir)


# ---------------------------------------------------------------------------
# Delta + explanation
# ---------------------------------------------------------------------------


def _compute_delta(live: dict, backup: dict) -> dict | None:
    if not (live.get("exists") and backup.get("exists")):
        return None
    out: dict[str, int | None] = {}
    for key in (
        "mismatch_count",
        "preview_count",
        "planned_write_count",
        "repairable_count",
    ):
        out[key] = int(live[key]) - int(backup[key])
    out["size_bytes"] = (
        int(live["size_bytes"]) - int(backup["size_bytes"])
        if live["size_bytes"] is not None
        and backup["size_bytes"] is not None
        else None
    )
    # mtime delta as integer seconds (positive = live is newer).
    try:
        live_dt = datetime.fromisoformat(live["mtime"])
        bkp_dt  = datetime.fromisoformat(backup["mtime"])
        out["mtime_seconds"] = int((live_dt - bkp_dt).total_seconds())
    except (TypeError, ValueError):
        out["mtime_seconds"] = None
    return out


def _explain(live: dict, backup: dict, delta: dict | None) -> str:
    if not live.get("exists"):
        return (
            "Live DB does not exist; cannot compare against backup."
        )
    if not backup.get("exists"):
        return (
            "No backup available to compare against — running --write "
            "as a smoke test has nothing to exercise.  Take a backup "
            "(scripts/backup_archive.py) before relying on this delta."
        )
    if delta is None:
        return "Comparison not possible."

    diff = int(delta.get("mismatch_count") or 0)
    if diff > 0:
        return (
            f"Live has {diff} more auto_adjust_mismatch row(s) than "
            f"the backup; running --write against the backup will not "
            f"exercise those rows."
        )
    if diff < 0:
        return (
            f"Backup has {-diff} more auto_adjust_mismatch row(s) "
            f"than live; the backup is stale relative to the current "
            f"cache state."
        )
    return (
        "Live and backup agree on auto_adjust_mismatch counts; the "
        "writer would propose the same set on either."
    )


# ---------------------------------------------------------------------------
# Payload + rendering
# ---------------------------------------------------------------------------


def build_report(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
) -> dict:
    if db_path is None:
        import db as _db
        db_path = _db.DB_FILE

    live   = _per_db_section(db_path)
    backup = _per_db_section(backup_path)
    delta  = _compute_delta(live, backup)

    return {
        "live":        live,
        "backup":      backup,
        "delta":       delta,
        "explanation": _explain(live, backup, delta),
        "available":   bool(live["exists"]),
    }


def _render_text(payload: dict) -> str:
    lines: list[str] = ["Auto-adjust repair backup-delta report", ""]

    def _fmt_section(name: str, section: dict) -> list[str]:
        rows = [
            f"{name}:",
            f"  db_path:              {section.get('db_path') or '-'}",
            f"  exists:               {section.get('exists')}",
            f"  size_bytes:           {section.get('size_bytes')}",
            f"  mtime:                {section.get('mtime')}",
            f"  mismatch_count:       {section.get('mismatch_count')}",
            f"  preview_count:        {section.get('preview_count')}",
            f"  planned_write_count:  {section.get('planned_write_count')}",
            f"  repairable_count:     {section.get('repairable_count')}",
        ]
        return rows

    lines.extend(_fmt_section("Live",   payload["live"]))
    lines.append("")
    lines.extend(_fmt_section("Backup", payload["backup"]))
    lines.append("")

    delta = payload.get("delta")
    if delta is None:
        lines.append("Delta: not available (one or both DBs missing)")
    else:
        lines.append("Delta (live - backup):")
        lines.append(f"  mismatch_count:       {delta['mismatch_count']}")
        lines.append(f"  preview_count:        {delta['preview_count']}")
        lines.append(
            f"  planned_write_count:  {delta['planned_write_count']}"
        )
        lines.append(
            f"  repairable_count:     {delta['repairable_count']}"
        )
        lines.append(f"  size_bytes:           {delta['size_bytes']}")
        lines.append(
            f"  mtime_seconds:        {delta['mtime_seconds']}"
        )
    lines.append("")
    lines.append(f"Explanation: {payload.get('explanation') or '-'}")
    return "\n".join(lines)


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only delta report comparing live events.db vs the "
            "selected / latest backup.  Explains why a live dry-run "
            "of the auto-adjust repair surfaces planned writes while "
            "a smoke test against the latest backup may apply zero."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as structured JSON.",
    )
    parser.add_argument(
        "--backup-path",
        default=None,
        help=(
            "Explicit backup DB path.  Wins over --latest.  When the "
            "path does not exist, backup.exists is False and delta is "
            "None."
        ),
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Pick the most recent ``events-*.db`` under "
            "--backups-dir (default ``backups/``).  Overridden by "
            "--backup-path when both are passed."
        ),
    )
    parser.add_argument(
        "--backups-dir",
        default=None,
        help=(
            "Override the default backups directory (``backups/``) "
            "the --latest picker walks."
        ),
    )
    # Live-side path override.  Not part of the documented surface,
    # but the underlying function accepts it so tests can drive the
    # CLI against an isolated fixture.
    parser.add_argument(
        "--db-path",
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    backup_path = _resolve_backup_path(args)
    payload = build_report(
        db_path=args.db_path,
        backup_path=backup_path,
    )

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

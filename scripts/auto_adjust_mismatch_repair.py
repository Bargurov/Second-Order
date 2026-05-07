#!/usr/bin/env python3
"""CLI gate for the auto-adjust mismatch repair writer.

Default mode: planner-only preview.  No DB writes, no provider call,
no ``yfinance``, no LLM, no FastAPI surface.

Write mode requires every one of:

  * ``--write``         turn write mode on
  * ``--confirm``       acknowledge the write is intentional
  * ``--backup-path X`` snapshot file the rollback would restore from

Missing any of those flags → the CLI exits non-zero before the writer
function is invoked.  The writer itself enforces the same rule
(``confirm=True`` without ``backup_path`` raises ``ValueError``); the
CLI's argparse-level gate is sugar that surfaces the violation as a
clean exit code instead of a stack trace.

Usage::

    python scripts/auto_adjust_mismatch_repair.py
    python scripts/auto_adjust_mismatch_repair.py --json
    python scripts/auto_adjust_mismatch_repair.py \\
        --write --confirm --backup-path /tmp/backup.db
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


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Guarded writer for auto_adjust_mismatch_for_20d cache "
            "rows.  Default is a planner-only preview; writes require "
            "--write --confirm --backup-path."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to the SQLite events DB (default: in-process db.DB_FILE).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the planner / write result as structured JSON.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Enable write mode.  Required to apply the repair; without "
            "this flag the CLI runs the planner only."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Acknowledge that the write is intentional.  Required when "
            "--write is set; the writer raises ValueError if missing."
        ),
    )
    parser.add_argument(
        "--backup-path",
        default=None,
        help=(
            "Snapshot file to copy the DB to before any INSERT.  "
            "Required when --write is set."
        ),
    )
    parser.add_argument(
        "--audit-log-path",
        default=None,
        help=(
            "Optional override for the JSONL audit log path.  Defaults "
            "to audit_logs/auto_adjust_mismatch_repair_<UTC>.jsonl."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _render_text(result: dict) -> str:
    lines: list[str] = ["Auto-adjust mismatch repair", ""]
    lines.append(
        f"Total mismatches:        {result.get('total_mismatches', 0)}"
    )
    lines.append(
        f"Repairable mismatches:   {result.get('repairable_count', 0)}"
    )
    lines.append(
        f"Planned writes:          {result.get('planned_write_count', 0)}"
    )
    lines.append(
        f"Confirm mode:            {bool(result.get('confirm'))}"
    )
    lines.append(
        f"Applied count:           {result.get('applied_count', 0)}"
    )
    backup = result.get("backup_path") or "-"
    audit  = result.get("audit_log_path") or "-"
    lines.append(f"Backup path:             {backup}")
    lines.append(f"Audit log path:          {audit}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    if args.write:
        if not args.confirm:
            print(
                "auto_adjust_mismatch_repair: --write requires "
                "--confirm",
                file=sys.stderr,
            )
            return 2
        if not args.backup_path:
            print(
                "auto_adjust_mismatch_repair: --write --confirm "
                "requires --backup-path",
                file=sys.stderr,
            )
            return 2

    # Lazy-import the writer module so a parser-only invocation never
    # pulls the diagnostics import graph.
    import auto_adjust_mismatch_repair as repair

    if args.write:
        result = repair.apply_auto_adjust_mismatch_repair(
            db_path=args.db_path,
            confirm=True,
            backup_path=args.backup_path,
            audit_log_path=args.audit_log_path,
        )
    else:
        plan = repair.plan_auto_adjust_mismatch_repair(db_path=args.db_path)
        result = {
            **plan,
            "confirm":         False,
            "applied_count":   0,
            "applied_writes":  [],
            "backup_path":     None,
            "audit_log_path":  None,
        }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str),
              file=output)
    else:
        print(_render_text(result), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

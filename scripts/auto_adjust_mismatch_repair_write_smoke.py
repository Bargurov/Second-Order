#!/usr/bin/env python3
"""scripts/auto_adjust_mismatch_repair_write_smoke.py

Live-safety probe for the future ``auto_adjust_mismatch_repair`` writer.

Resolves a backup file (``--backup-path`` or ``--latest``), copies it
to a temp SQLite file, then runs the full write-mode flow against the
*temp copy only*: dry-run → ``apply_auto_adjust_mismatch_repair(
confirm=True, backup_path=...)`` → second apply (idempotency) →
dry-run.  The live ``events.db`` is hashed before and after the run
and the probe fails if anything moved.

Lazy writer seam
----------------
The repair writer is resolved at call time via :func:`_load_writer`
rather than imported at module top-level.  Two reasons:

  * Tests can swap the seam for a fake plan/apply pair to exercise
    the orchestration without depending on the writer's exact
    behaviour or seeded archive state.
  * If a future refactor removes or renames the writer, the smoke
    surfaces a clean ``writer not implemented yet`` error AND still
    runs the load-bearing live-DB hash check, instead of failing to
    import altogether.

Out of scope (deliberately)
---------------------------
* No write back to the live ``events.db`` — ``db.DB_FILE`` is never
  read or referenced.  When the writer ships it is invoked with an
  explicit ``db_path`` pointing at the temp copy.
* No FastAPI app surface.  No ``api`` / ``routes.*`` imports.
* No provider, ``yfinance``, ``market_check``, ``market_data``, or
  production ``price_cache`` import — the probe only re-uses the
  planner / writer functions, which themselves never touch those
  seams.
* No LLM seam.

Usage::

    python scripts/auto_adjust_mismatch_repair_write_smoke.py \\
        --backup-path backups/events-20260507T120000.db
    python scripts/auto_adjust_mismatch_repair_write_smoke.py --latest
    python scripts/auto_adjust_mismatch_repair_write_smoke.py --latest --json
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
from typing import Any, Callable, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_restore_check import find_latest_backup  # noqa: E402


_DEFAULT_BACKUP_DIR = "backups"
_DEFAULT_LIVE_DB    = "events.db"
_BACKUP_GLOB        = "events-*.db"

_REPAIR_MODULE_NAME = "auto_adjust_mismatch_repair"
_PLAN_FN_NAME       = "plan_auto_adjust_mismatch_repair"
_APPLY_FN_NAME      = "apply_auto_adjust_mismatch_repair"


# ---------------------------------------------------------------------------
# Lazy seam — load the writer at call time.
#
# The repair writer module does not exist yet (see
# ``tests/test_auto_adjust_mismatch_repair_contract.py``).  Importing it
# at module top-level would make this script unimportable on a clean
# repo, which would in turn break the ``--latest`` runbook entry the
# operator types BEFORE the writer ships (the operator's first signal
# that the writer landed is that this probe stops failing fast).
#
# Tests patch this attribute directly to swap a fake writer pair into
# place; the production path resolves the real symbols.
# ---------------------------------------------------------------------------


def _load_writer() -> Tuple[Callable[..., Any], Callable[..., Any]]:
    """Resolve ``(plan_fn, apply_fn)`` from the writer module.

    Raises ``ImportError`` if the writer module or either expected
    callable is missing — the smoke runner catches this and surfaces a
    clean ``writer not yet implemented`` error rather than crashing.
    """
    import importlib

    module = importlib.import_module(_REPAIR_MODULE_NAME)
    plan_fn  = getattr(module, _PLAN_FN_NAME, None)
    apply_fn = getattr(module, _APPLY_FN_NAME, None)
    if not callable(plan_fn) or not callable(apply_fn):
        raise ImportError(
            f"{_REPAIR_MODULE_NAME} is importable but does not expose "
            f"callable {_PLAN_FN_NAME!r} / {_APPLY_FN_NAME!r}",
        )
    return plan_fn, apply_fn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slim_plan(plan: Any) -> dict:
    """Narrow a planner result to the fields the smoke output pins.

    The planner shape is fixed by the design doc that accompanies the
    writer; the smoke only surfaces the two count fields the runbook
    reads against so a downstream consumer is not coupled to internal
    fields that may legitimately drift.
    """
    if not isinstance(plan, dict):
        return {"total_mismatches": 0, "repairable_count": 0}
    return {
        "total_mismatches": int(plan.get("total_mismatches", 0) or 0),
        "repairable_count": int(plan.get("repairable_count", 0) or 0),
    }


def _empty_result() -> dict:
    return {
        "ok":                     False,
        "backup_path":            None,
        "temp_copy_path":         None,
        "writer_backup_target":   None,
        "live_db_path":           None,
        "live_db_unchanged":      None,
        "input_backup_unchanged": None,
        "before":                 None,
        "write":                  None,
        "after":                  None,
        "idempotency":            None,
        "warnings":               [],
        "errors":                 [],
    }


def _preflight_temp_db(tmp: Path) -> Optional[str]:
    """Open the temp copy read-only and confirm the ``events`` and
    ``price_cache`` tables are present.  Returns ``None`` on success
    or an error-message string describing the failure.

    Both tables are required: ``events`` carries the rows the planner
    classifies as mismatches and ``price_cache`` carries the rows the
    repair would reshape.  A backup missing either table is unusable
    for this smoke even though it might still be a valid SQLite file.
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
            present = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name IN ('events', 'price_cache')",
                ).fetchall()
            }
        except sqlite3.Error as exc:
            return (
                "temp copy is not a valid SQLite database: "
                f"{type(exc).__name__}: {exc}"
            )
    finally:
        conn.close()
    missing = [t for t in ("events", "price_cache") if t not in present]
    if missing:
        return (
            "temp copy is missing required table(s): "
            + ", ".join(sorted(missing))
        )
    return None


def _input_backup_unchanged(
    backup: Path,
    hash_before:  str,
    mtime_before: float,
    *,
    errors: list[str],
) -> bool:
    """Verify the input backup file is byte-identical post-run.

    The smoke MUST never overwrite the operator's input backup; this
    check is the post-run sentinel that proves the contract held even
    if a buggy writer wrote to its (throwaway) backup target.  A hash
    or mtime divergence is surfaced as a hard error so the run-wide
    ``ok`` flips to False.
    """
    if not backup.exists() or not backup.is_file():
        errors.append(
            f"input backup disappeared during run: {backup}",
        )
        return False
    hash_after  = _hash_file(backup)
    mtime_after = backup.stat().st_mtime
    unchanged = hash_after == hash_before and mtime_after == mtime_before
    if not unchanged:
        errors.append(
            f"input backup changed during run: {backup}",
        )
    return unchanged


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

    When the writer module is not yet importable, the probe still runs
    its load-bearing safety steps (backup resolution, live-DB hash
    sentinel) and returns a clean error so an operator can tell the
    difference between "smoke not yet wired" and "smoke broke."
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

    # 2. Snapshot the live events.db so the post-run hash check has a
    # baseline regardless of whether the writer is present today.
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

    # 3. Resolve the writer.  When the module is missing we still run
    # the live-DB hash check so the "live hash unchanged" contract
    # holds even on the not-yet-implemented path.
    try:
        plan_fn, apply_fn = _load_writer()
    except ImportError as exc:
        result["errors"].append(
            f"writer not implemented yet: {type(exc).__name__}: {exc}"
        )
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )
        return result

    # 4. Snapshot the input backup so the post-run check can prove it
    # is byte-identical even if the writer (legitimately) overwrites
    # its own backup-target argument.  The smoke must NEVER point the
    # writer's backup_path at the input backup file — that would let a
    # buggy or future-rewritten writer destroy the operator's only
    # on-disk pre-repair snapshot.
    input_backup_hash_before  = _hash_file(resolved)
    input_backup_mtime_before = resolved.stat().st_mtime

    # 5. Copy backup → temp.
    fd, tmp_str = tempfile.mkstemp(prefix="aa_repair_smoke_", suffix=".db")
    os.close(fd)
    tmp = Path(tmp_str)
    result["temp_copy_path"] = str(tmp)

    # 5a. Allocate a throwaway target for the writer's ``backup_path``
    # kwarg.  We pre-create it so the writer's open-for-write call
    # cannot collide with another temp file racing for the same name,
    # and we keep it distinct from both the input backup and the temp
    # DB copy so the writer can freely overwrite its target without
    # touching either operator-visible artifact.
    fd2, target_str = tempfile.mkstemp(
        prefix="aa_repair_smoke_target_", suffix=".db",
    )
    os.close(fd2)
    writer_backup_target = Path(target_str)
    result["writer_backup_target"] = str(writer_backup_target)

    try:
        try:
            shutil.copy2(str(resolved), str(tmp))
        except OSError as exc:
            result["errors"].append(
                "failed to copy backup to temp location: "
                f"{type(exc).__name__}: {exc}",
            )
            return result

        # 5b. Pre-flight: a corrupt or schema-less file would otherwise
        # look like a clean run.  Open the temp copy directly and
        # confirm the required tables are readable before invoking the
        # writer.
        preflight_error = _preflight_temp_db(tmp)
        if preflight_error is not None:
            result["errors"].append(preflight_error)
            return result

        # 6. Dry-run BEFORE.
        try:
            before_plan = plan_fn(db_path=str(tmp))
        except Exception as exc:
            result["errors"].append(
                f"before plan failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["before"] = _slim_plan(before_plan)

        # 7. Apply with confirm.  The writer requires a backup-target
        # kwarg per its safety contract; we point it at a throwaway
        # temp path (NOT the input backup) so a future writer that
        # overwrites the target cannot destroy the operator's input
        # backup file.
        try:
            write_result = apply_fn(
                db_path=str(tmp),
                confirm=True,
                backup_path=str(writer_backup_target),
            )
        except Exception as exc:
            result["errors"].append(
                f"apply failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["write"] = {
            "applied_count": int(
                (write_result or {}).get("applied_count", 0) or 0
            ),
        }

        # 8. Second apply — must be a no-op.
        try:
            second = apply_fn(
                db_path=str(tmp),
                confirm=True,
                backup_path=str(writer_backup_target),
            )
        except Exception as exc:
            result["errors"].append(
                f"second apply failed: {type(exc).__name__}: {exc}",
            )
            return result
        second_count = int((second or {}).get("applied_count", 0) or 0)
        result["idempotency"] = {
            "idempotent_second_apply_count": second_count,
            "ok":                            second_count == 0,
        }
        if second_count != 0:
            result["errors"].append(
                "idempotency violation: second apply wrote "
                f"{second_count} row(s)",
            )

        # 9. Dry-run AFTER.
        try:
            after_plan = plan_fn(db_path=str(tmp))
        except Exception as exc:
            result["errors"].append(
                f"after plan failed: {type(exc).__name__}: {exc}",
            )
            return result
        result["after"] = _slim_plan(after_plan)

        # 10. Live events.db unchanged check.
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )

        # 11. Input backup unchanged check.  The smoke pointed the
        # writer at the throwaway target — a real or fake writer that
        # overwrites its target should not have touched the input
        # backup.  Surface a hard error if anything moved.
        result["input_backup_unchanged"] = _input_backup_unchanged(
            resolved,
            input_backup_hash_before,
            input_backup_mtime_before,
            errors=result["errors"],
        )

        result["ok"] = not result["errors"]
        return result
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            writer_backup_target.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(result: dict) -> str:
    lines: list[str] = ["=== auto-adjust mismatch repair write smoke ==="]
    lines.append(f"backup_path:            {result.get('backup_path')   or '(none)'}")
    lines.append(f"temp_copy_path:         {result.get('temp_copy_path') or '(none)'}")
    lines.append(f"writer_backup_target:   {result.get('writer_backup_target') or '(none)'}")
    lines.append(f"live_db_path:           {result.get('live_db_path')}")
    lines.append(f"live_db_unchanged:      {result.get('live_db_unchanged')}")
    lines.append(f"input_backup_unchanged: {result.get('input_backup_unchanged')}")
    lines.append(f"ok:                     {result['ok']}")

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
            "Live-safety probe for the auto-adjust mismatch repair "
            "writer.  Runs the full dry-run → apply → second-apply → "
            "dry-run flow against a temp copy of a backup.  Never "
            "modifies events.db."
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

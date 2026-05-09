#!/usr/bin/env python3
"""Backup-gated archive cleanup apply-plan tool.

Default mode is a strict dry-run preview built from the
``archive_cleanup_execution_plan`` batches.  Write mode applies the
deduped delete plan to a *copy* of an operator-supplied backup file
(NEVER the live ``events.db``) and writes a JSONL audit log alongside.

The live archive is never opened for write; this script has no
"live delete" path by construction.

CLI gate.  Write mode requires every one of:

    --write            turn write mode on
    --confirm          acknowledge the write is intentional
    --backup-path X    EXISTING backup file to *copy from* and operate on

Note on ``--backup-path`` semantics.  Unlike sister write-smoke tools
that point ``--backup-path`` at the snapshot file the writer would
*create* before mutating the live DB, this script treats
``--backup-path`` as the **input** backup file: the operator must
have already taken the snapshot (e.g. via ``scripts/backup_archive.py``)
and points us at it.  We copy that file to a private temp DB and apply
deletes against the temp copy only — the input backup file itself is
never written to.

Safety contract
---------------
* The live ``events.db`` is never opened for write.  Its sha256 hash is
  taken before and after the run; a divergence flips
  ``live_db_unchanged`` to ``False`` and bumps the result into an error
  state.
* The input backup file is hash-verified pre/post — a buggy or future
  rewrite of the writer that mutated it would be surfaced.
* Writes go to a ``tempfile.mkstemp`` private copy of the input
  backup; the temp file is unlinked on exit.
* Every applied delete appends a JSONL record to the audit log.  The
  audit log is materialised on disk only when ``applied_count > 0``;
  the result dict surfaces the path (or ``None``) under
  ``audit_log_path``.
* Module source contains no ``import db`` / ``from db import`` line —
  there is no path to the project's writable in-process DB handle.
* No provider call (``yfinance``, ``market_check``, ``market_data``,
  ``price_cache``), no LLM seam (``anthropic``, ``openai``), no
  FastAPI surface (``api`` / ``routes.*``), no ``analyze_event``.
* No filesystem destructor against operator-visible paths.  The temp
  copy is the only file we ``unlink``.

Output contract (dry-run)::

    {
      "mode":                  "dry_run",
      "candidate_count":       int,
      "batches":               [...],   # from execution_plan
      "risk_notes":            [...],
      "required_confirmation_flags": [...],
      "recommended_next_action": str,
      "delete_preview": {
        "deduped_event_count": int,    # == candidate_count
        "deduped_event_ids":   [int],  # sorted ascending
      },
      "confirm":                False,
      "applied_count":          0,
      "applied_event_ids":      [],
      "backup_path":            None,
      "temp_copy_path":         None,
      "audit_log_path":         None,
      "live_db_path":           None,
      "live_db_unchanged":      None,
      "input_backup_unchanged": None,
      "warnings":               [],
      "errors":                 [],
      "ok":                     True,
    }

Output contract (write_temp_copy) — same keys, with::

      "mode":                   "write_temp_copy",
      "confirm":                True,
      "applied_count":          int,
      "applied_event_ids":      [int],   # sorted, == deduped on success
      "backup_path":            str,
      "temp_copy_path":         str,     # existed during the run
      "audit_log_path":         str | None,  # None when applied_count == 0
      "live_db_path":           str,
      "live_db_unchanged":      True | False,
      "input_backup_unchanged": True | False,
      "ok":                     bool,    # not errors

Usage::

    python scripts/archive_cleanup_apply_plan.py --dry-run
    python scripts/archive_cleanup_apply_plan.py --dry-run --json --limit 20
    python scripts/archive_cleanup_apply_plan.py \\
        --write --confirm \\
        --backup-path backups/events-20260507T095609.db
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import archive_cleanup_candidate_report as _candidate_report  # noqa: E402
from scripts import archive_cleanup_execution_plan as _execution_plan  # noqa: E402


_DEFAULT_LIMIT: int = 25
_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD: int = 3
_DEFAULT_LIVE_DB: str = "events.db"

# Internal "fetch all" sentinel for the upstream candidate-report call.
# We need every flagged event so per-event reasons metadata is available
# for the audit log; the user-facing ``--limit`` only caps the surfaced
# per-batch examples list.
_INTERNAL_FETCH_ALL: int = 10 ** 9

# SQLite hard-codes the parameter limit to ~999 in older builds; chunk
# the IN-list so a large delete plan still issues clean DELETEs without
# the operator needing to tune anything.
_DELETE_CHUNK_SIZE: int = 500

_AUDIT_ACTION = "delete_event_from_temp_copy"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_audit_log_path() -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return str(Path("audit_logs") / f"archive_cleanup_apply_{ts}.jsonl")


def _fetch_full_candidate_report(
    *,
    db_path: str | None,
    fixture_timestamp_threshold: int,
) -> dict[str, Any]:
    """Resolve the candidate report with every flagged event surfaced.

    The user-facing ``--limit`` only caps ``examples`` inside per-batch
    payloads downstream; this helper always fetches the unbounded set so
    that audit-log metadata is available for every deduped event_id we
    plan to delete.
    """
    return _candidate_report.summarize_cleanup_candidates(
        db_path=db_path,
        limit=_INTERNAL_FETCH_ALL,
        fixture_timestamp_threshold=fixture_timestamp_threshold,
    )


def _dedup_event_ids(execution_plan: dict[str, Any]) -> list[int]:
    """Collapse per-batch ``event_ids`` lists into a sorted unique set.

    An event matching N reasons appears in N batches with its id; the
    dedup invariant is ``len(result) == execution_plan["candidate_count"]``.
    """
    seen: set[int] = set()
    for batch in execution_plan.get("batches") or ():
        for eid in batch.get("event_ids") or ():
            try:
                seen.add(int(eid))
            except (TypeError, ValueError):
                continue
    return sorted(seen)


def _empty_dry_run_extras() -> dict[str, Any]:
    """The constant-shape suffix dry-run results carry on top of the
    execution plan dict.  Kept separate so the write path can override
    the relevant keys without re-stating the rest."""
    return {
        "mode":                   "dry_run",
        "confirm":                False,
        "applied_count":          0,
        "applied_event_ids":      [],
        "backup_path":            None,
        "temp_copy_path":         None,
        "audit_log_path":         None,
        "live_db_path":           None,
        "live_db_unchanged":      None,
        "input_backup_unchanged": None,
        "warnings":               [],
        "errors":                 [],
        "ok":                     True,
    }


# ---------------------------------------------------------------------------
# Dry-run / planner
# ---------------------------------------------------------------------------


def build_apply_plan(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    fixture_timestamp_threshold: int = _DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
    candidate_report: dict[str, Any] | None = None,
    execution_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the dry-run apply-plan dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Forwarded to ``summarize_cleanup_candidates`` when no
        ``candidate_report`` / ``execution_plan`` is supplied.  Read-only
        — the upstream candidate report issues only SELECT statements.
    limit
        Per-batch cap on the surfaced ``examples`` list.  The
        ``delete_preview.deduped_event_ids`` list is independent of
        ``limit`` — it always reflects every flagged event.  Negative
        values clamp to ``0``.
    fixture_timestamp_threshold
        Forwarded to the candidate report.  Values < 2 are clamped to 2
        by the upstream.
    candidate_report
        Optional pre-fetched candidate-report dict.  When supplied,
        bypasses the underlying candidate-report SELECT entirely.  The
        report must already include every flagged event (i.e. fetched
        with the internal "all" limit) for the dry-run dedup count to
        match ``candidate_count``.
    execution_plan
        Optional pre-built execution-plan dict.  When supplied,
        bypasses both the candidate-report and execution-plan calls.
    """
    if execution_plan is None:
        if candidate_report is None:
            candidate_report = _fetch_full_candidate_report(
                db_path=db_path,
                fixture_timestamp_threshold=fixture_timestamp_threshold,
            )
        execution_plan = _execution_plan.build_execution_plan(
            candidate_report=candidate_report,
            limit=limit,
        )

    deduped = _dedup_event_ids(execution_plan)
    extras = _empty_dry_run_extras()
    return {
        **execution_plan,
        **extras,
        "delete_preview": {
            "deduped_event_count": len(deduped),
            "deduped_event_ids":   deduped,
        },
    }


# ---------------------------------------------------------------------------
# Write mode (temp-copy only)
# ---------------------------------------------------------------------------


def _preflight_temp_db(tmp: Path) -> str | None:
    """Open the temp copy read-only and confirm the ``events`` table is
    present.  Returns ``None`` on success or an error-message string.

    A backup file pointed at our writer that is corrupt or schema-less
    would otherwise look like a clean run with zero applied rows; this
    pre-flight surfaces the misuse as a clean error before any write.
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
                    "WHERE type='table' AND name='events'",
                ).fetchall()
            }
        except sqlite3.Error as exc:
            return (
                "temp copy is not a valid SQLite database: "
                f"{type(exc).__name__}: {exc}"
            )
    finally:
        conn.close()
    if "events" not in present:
        return "temp copy is missing required table: events"
    return None


def _delete_in_chunks(
    conn: sqlite3.Connection,
    event_ids: Sequence[int],
) -> int:
    """Issue ``DELETE FROM events WHERE id IN (?, ?, ...)`` in chunks.

    Returns the total number of rows reported deleted by sqlite3 across
    chunks.  Chunk size keeps the IN-list under SQLite's parameter limit
    on older builds.
    """
    deleted_total = 0
    for start in range(0, len(event_ids), _DELETE_CHUNK_SIZE):
        chunk = list(event_ids[start:start + _DELETE_CHUNK_SIZE])
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        cur = conn.execute(
            f"DELETE FROM events WHERE id IN ({placeholders})",
            chunk,
        )
        deleted_total += cur.rowcount if cur.rowcount is not None else 0
    return deleted_total


def _write_audit_log(
    audit_path: Path,
    *,
    event_ids: Sequence[int],
    metadata_by_id: dict[int, dict[str, Any]],
    backup_path: Path,
    temp_copy_path: Path,
) -> None:
    """Append one JSONL record per deleted event to ``audit_path``.

    Records carry the event_id, its reasons, headline / timestamp /
    event_date metadata and the backup + temp-copy paths the deletion
    landed against.  Metadata that is not present in the candidate
    report (a future event flagged but missing from the example list)
    is recorded as ``None``.
    """
    audit_dir = audit_path.parent
    if str(audit_dir) and audit_dir != Path(""):
        audit_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=timezone.utc).isoformat()
    with audit_path.open("a", encoding="utf-8") as fh:
        for eid in event_ids:
            meta = metadata_by_id.get(int(eid)) or {}
            rec = {
                "ts":              ts,
                "event_id":        int(eid),
                "reasons":         list(meta.get("reasons") or ()),
                "headline":        meta.get("headline"),
                "timestamp":       meta.get("timestamp"),
                "event_date":      meta.get("event_date"),
                "backup_path":     str(backup_path),
                "temp_copy_path":  str(temp_copy_path),
                "action":          _AUDIT_ACTION,
            }
            fh.write(json.dumps(rec, default=str) + "\n")


def _classify_live_db_unchanged(
    live_db: Path,
    existed_before: bool,
    hash_before:    str | None,
    mtime_before:   float | None,
    *,
    errors: list[str],
) -> bool | None:
    exists_after = live_db.exists() and live_db.is_file()

    if existed_before and not exists_after:
        errors.append(f"live events.db disappeared during run: {live_db}")
        return False
    if not existed_before and exists_after:
        errors.append(f"live events.db was created during run: {live_db}")
        return False
    if not existed_before and not exists_after:
        return None  # not measured

    hash_after  = _hash_file(live_db)
    mtime_after = live_db.stat().st_mtime
    unchanged = hash_after == hash_before and mtime_after == mtime_before
    if not unchanged:
        errors.append(f"live events.db changed during run: {live_db}")
    return unchanged


def _classify_input_backup_unchanged(
    backup: Path,
    hash_before:  str,
    mtime_before: float,
    *,
    errors: list[str],
) -> bool:
    if not backup.exists() or not backup.is_file():
        errors.append(f"input backup disappeared during run: {backup}")
        return False
    hash_after  = _hash_file(backup)
    mtime_after = backup.stat().st_mtime
    unchanged = hash_after == hash_before and mtime_after == mtime_before
    if not unchanged:
        errors.append(f"input backup changed during run: {backup}")
    return unchanged


def apply_against_temp_copy(
    *,
    backup_path: str | os.PathLike[str],
    confirm: bool = False,
    audit_log_path: str | os.PathLike[str] | None = None,
    live_db_path: str | os.PathLike[str] = _DEFAULT_LIVE_DB,
    limit: int = _DEFAULT_LIMIT,
    fixture_timestamp_threshold: int = _DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
) -> dict[str, Any]:
    """Apply the deduped cleanup plan to a private copy of ``backup_path``.

    The live ``events.db`` is never opened for write — only its sha256
    hash is read, before and after the run, as a sentinel.  The input
    backup file is also hash-verified pre/post.

    Raises ``ValueError`` if ``confirm`` is False or ``backup_path`` is
    missing — the CLI gate surfaces these as a clean exit code, but the
    function-level guard ensures programmatic callers cannot bypass the
    contract.

    The result dict shape matches the dry-run shape with write-mode
    keys filled in.  ``ok=False`` whenever ``errors`` is non-empty —
    e.g. when a backup file is missing, the live DB hash drifted, or
    the audit-log write failed.
    """
    if not confirm:
        raise ValueError(
            "apply_against_temp_copy: confirm=True is required to apply "
            "the cleanup plan; default is dry-run only.",
        )
    if backup_path is None:
        raise ValueError(
            "apply_against_temp_copy: backup_path is required to apply "
            "the cleanup plan; this script never writes to events.db.",
        )

    resolved_backup = Path(backup_path)
    live_db = Path(live_db_path)

    result: dict[str, Any] = {
        "mode":                   "write_temp_copy",
        "candidate_count":        0,
        "batches":                [],
        "risk_notes":             [],
        "required_confirmation_flags": [],
        "recommended_next_action": "",
        "delete_preview": {
            "deduped_event_count": 0,
            "deduped_event_ids":   [],
        },
        "confirm":                True,
        "applied_count":          0,
        "applied_event_ids":      [],
        "backup_path":            str(resolved_backup),
        "temp_copy_path":         None,
        "audit_log_path":         None,
        "live_db_path":           str(live_db),
        "live_db_unchanged":      None,
        "input_backup_unchanged": None,
        "warnings":               [],
        "errors":                 [],
        "ok":                     False,
    }

    # 1. Live events.db sentinel — hashed before any other work so a
    # post-run divergence is always observable.
    live_existed = live_db.exists() and live_db.is_file()
    live_hash_before:  str | None   = None
    live_mtime_before: float | None = None
    if live_existed:
        live_hash_before  = _hash_file(live_db)
        live_mtime_before = live_db.stat().st_mtime
    else:
        result["warnings"].append(
            f"live events.db not found at {live_db}; skipping byte-equality "
            "check (still asserting it stays absent)",
        )

    # 2. Resolve & validate input backup.
    if not resolved_backup.exists():
        result["errors"].append(
            f"input backup file does not exist: {resolved_backup}",
        )
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )
        return result
    if not resolved_backup.is_file():
        result["errors"].append(
            f"input backup path is not a file: {resolved_backup}",
        )
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )
        return result

    input_backup_hash_before  = _hash_file(resolved_backup)
    input_backup_mtime_before = resolved_backup.stat().st_mtime

    # 3. Copy backup → private temp DB.
    fd, tmp_str = tempfile.mkstemp(prefix="archive_cleanup_apply_", suffix=".db")
    os.close(fd)
    tmp = Path(tmp_str)
    result["temp_copy_path"] = str(tmp)

    try:
        try:
            shutil.copy2(str(resolved_backup), str(tmp))
        except OSError as exc:
            result["errors"].append(
                "failed to copy backup to temp location: "
                f"{type(exc).__name__}: {exc}",
            )
            result["live_db_unchanged"] = _classify_live_db_unchanged(
                live_db, live_existed, live_hash_before, live_mtime_before,
                errors=result["errors"],
            )
            result["input_backup_unchanged"] = _classify_input_backup_unchanged(
                resolved_backup,
                input_backup_hash_before,
                input_backup_mtime_before,
                errors=result["errors"],
            )
            return result

        preflight_error = _preflight_temp_db(tmp)
        if preflight_error is not None:
            result["errors"].append(preflight_error)
            result["live_db_unchanged"] = _classify_live_db_unchanged(
                live_db, live_existed, live_hash_before, live_mtime_before,
                errors=result["errors"],
            )
            result["input_backup_unchanged"] = _classify_input_backup_unchanged(
                resolved_backup,
                input_backup_hash_before,
                input_backup_mtime_before,
                errors=result["errors"],
            )
            return result

        # 4. Build the plan against the temp copy.
        try:
            full_report = _fetch_full_candidate_report(
                db_path=str(tmp),
                fixture_timestamp_threshold=fixture_timestamp_threshold,
            )
            plan = build_apply_plan(
                limit=limit,
                fixture_timestamp_threshold=fixture_timestamp_threshold,
                candidate_report=full_report,
            )
        except Exception as exc:
            result["errors"].append(
                f"failed to build cleanup plan from temp copy: "
                f"{type(exc).__name__}: {exc}",
            )
            result["live_db_unchanged"] = _classify_live_db_unchanged(
                live_db, live_existed, live_hash_before, live_mtime_before,
                errors=result["errors"],
            )
            result["input_backup_unchanged"] = _classify_input_backup_unchanged(
                resolved_backup,
                input_backup_hash_before,
                input_backup_mtime_before,
                errors=result["errors"],
            )
            return result

        # Carry the plan's user-visible fields into the result.
        for key in (
            "candidate_count", "batches", "risk_notes",
            "required_confirmation_flags", "recommended_next_action",
            "delete_preview",
        ):
            result[key] = plan[key]

        deduped: list[int] = list(plan["delete_preview"]["deduped_event_ids"])
        metadata_by_id = {
            int(ex["event_id"]): ex
            for ex in (full_report.get("examples") or [])
            if isinstance(ex, dict) and "event_id" in ex
        }

        # 5. Apply the deletes against the temp copy only.
        if deduped:
            try:
                conn = sqlite3.connect(str(tmp))
                try:
                    deleted_total = _delete_in_chunks(conn, deduped)
                    conn.commit()
                finally:
                    # ``with sqlite3.connect()`` is a transaction ctx,
                    # not a close ctx — closing explicitly is required
                    # so the temp file's handle is released and the
                    # ``finally`` unlink below succeeds on Windows.
                    conn.close()
            except sqlite3.Error as exc:
                result["errors"].append(
                    f"DELETE against temp copy failed: "
                    f"{type(exc).__name__}: {exc}",
                )
                result["live_db_unchanged"] = _classify_live_db_unchanged(
                    live_db, live_existed, live_hash_before, live_mtime_before,
                    errors=result["errors"],
                )
                result["input_backup_unchanged"] = _classify_input_backup_unchanged(
                    resolved_backup,
                    input_backup_hash_before,
                    input_backup_mtime_before,
                    errors=result["errors"],
                )
                return result

            if deleted_total != len(deduped):
                result["warnings"].append(
                    f"DELETE rowcount {deleted_total} != deduped event count "
                    f"{len(deduped)} (some ids may not have been present in "
                    "the temp copy)",
                )

            # 6. Audit log — only materialised when a delete actually ran.
            audit_target = Path(audit_log_path) if audit_log_path else Path(
                _default_audit_log_path()
            )
            try:
                _write_audit_log(
                    audit_target,
                    event_ids=deduped,
                    metadata_by_id=metadata_by_id,
                    backup_path=resolved_backup,
                    temp_copy_path=tmp,
                )
            except OSError as exc:
                result["errors"].append(
                    f"failed to write audit log {audit_target}: "
                    f"{type(exc).__name__}: {exc}",
                )
                result["live_db_unchanged"] = _classify_live_db_unchanged(
                    live_db, live_existed, live_hash_before, live_mtime_before,
                    errors=result["errors"],
                )
                result["input_backup_unchanged"] = _classify_input_backup_unchanged(
                    resolved_backup,
                    input_backup_hash_before,
                    input_backup_mtime_before,
                    errors=result["errors"],
                )
                return result

            result["applied_count"]     = len(deduped)
            result["applied_event_ids"] = list(deduped)
            result["audit_log_path"]    = str(audit_target)
        else:
            # Zero candidates → nothing to delete and no audit file.
            # Match sister write-smoke convention: audit_log_path stays
            # None when applied_count is 0.
            result["applied_count"]     = 0
            result["applied_event_ids"] = []
            result["audit_log_path"]    = None

        # 7. Live events.db sentinel + input-backup byte-identity.
        result["live_db_unchanged"] = _classify_live_db_unchanged(
            live_db, live_existed, live_hash_before, live_mtime_before,
            errors=result["errors"],
        )
        result["input_backup_unchanged"] = _classify_input_backup_unchanged(
            resolved_backup,
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


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(result: dict[str, Any]) -> str:
    lines: list[str] = ["=== archive cleanup apply plan ==="]
    lines.append(f"mode:                   {result['mode']}")
    lines.append(f"candidate_count:        {result['candidate_count']}")
    preview = result["delete_preview"]
    lines.append(f"deduped_event_count:    {preview['deduped_event_count']}")
    visible_ids = preview["deduped_event_ids"][:10]
    tail = " ..." if len(preview["deduped_event_ids"]) > 10 else ""
    lines.append(f"deduped_event_ids[:10]: {visible_ids}{tail}")
    lines.append(f"confirm:                {result['confirm']}")
    lines.append(f"applied_count:          {result['applied_count']}")
    lines.append(f"backup_path:            {result['backup_path']    or '-'}")
    lines.append(f"temp_copy_path:         {result['temp_copy_path'] or '-'}")
    lines.append(f"audit_log_path:         {result['audit_log_path'] or '-'}")
    lines.append(f"live_db_path:           {result['live_db_path']    or '-'}")
    lines.append(f"live_db_unchanged:      {result['live_db_unchanged']}")
    lines.append(f"input_backup_unchanged: {result['input_backup_unchanged']}")

    batches = result.get("batches") or []
    if batches:
        lines.append(f"batches ({len(batches)}):")
        for batch in batches:
            lines.append(
                f"  reason={batch['reason']:30s} "
                f"size={batch['size']:5d} "
                f"examples={len(batch.get('examples', []))}"
            )
    else:
        lines.append("batches: (none)")

    warnings = result.get("warnings") or []
    if warnings:
        lines.append(f"warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
    errors = result.get("errors") or []
    if errors:
        lines.append(f"errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    lines.append(f"ok:                     {result['ok']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backup-gated archive cleanup apply-plan tool.  Default is "
            "a strict dry-run preview.  Write mode applies deletes to "
            "a private copy of an operator-supplied backup file (NEVER "
            "the live events.db) and writes a JSONL audit log."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run mode (the default).  Cannot be combined "
            "with --write."
        ),
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help=(
            "Enable write mode.  Required to apply deletes; without "
            "this flag the CLI runs the dry-run planner only.  Writes "
            "go to a private copy of --backup-path; the live events.db "
            "is never opened for write."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Acknowledge that the write is intentional.  Required when "
            "--write is set; the apply function raises ValueError if "
            "missing."
        ),
    )
    parser.add_argument(
        "--backup-path",
        dest="backup_path",
        default=None,
        help=(
            "EXISTING backup file to copy from and apply deletes "
            "against.  Required when --write is set; the operator must "
            "have already taken the snapshot via "
            "scripts/backup_archive.py.  This file is never written to."
        ),
    )
    parser.add_argument(
        "--audit-log-path",
        dest="audit_log_path",
        default=None,
        help=(
            "Optional override for the JSONL audit log path.  Defaults "
            "to audit_logs/archive_cleanup_apply_<UTC>.jsonl.  Only "
            "materialised when applied_count > 0."
        ),
    )
    parser.add_argument(
        "--live-db",
        dest="live_db",
        default=_DEFAULT_LIVE_DB,
        help=(
            "Path to the live events.db whose sha256 hash must remain "
            f"unchanged across the run (default: {_DEFAULT_LIVE_DB}).  "
            "Read-only — never opened for write."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional source DB for dry-run mode.  Forwarded to "
            "summarize_cleanup_candidates; defaults to db.DB_FILE.  "
            "Ignored in --write mode (the temp copy is the source)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-batch examples list at N entries "
            f"(default {_DEFAULT_LIMIT}).  delete_preview.deduped_event_ids "
            f"always reflects every flagged event."
        ),
    )
    parser.add_argument(
        "--fixture-timestamp-threshold",
        dest="fixture_timestamp_threshold",
        type=int,
        default=_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
        help=(
            f"Minimum cluster size for fixture_timestamp_cluster "
            f"(default {_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD}).  Forwarded "
            f"to the candidate report; values < 2 are clamped to 2."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    if args.write:
        if not args.confirm:
            print(
                "archive_cleanup_apply_plan: --write requires --confirm",
                file=sys.stderr,
            )
            return 2
        if not args.backup_path:
            print(
                "archive_cleanup_apply_plan: --write --confirm requires "
                "--backup-path",
                file=sys.stderr,
            )
            return 2

        result = apply_against_temp_copy(
            backup_path=args.backup_path,
            confirm=True,
            audit_log_path=args.audit_log_path,
            live_db_path=args.live_db,
            limit=args.limit,
            fixture_timestamp_threshold=args.fixture_timestamp_threshold,
        )
    else:
        result = build_apply_plan(
            db_path=args.db_path,
            limit=args.limit,
            fixture_timestamp_threshold=args.fixture_timestamp_threshold,
        )

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str),
              file=output)
    else:
        print(_render_text(result), file=output)

    return 0 if result["ok"] else 1


__all__: tuple[str, ...] = (
    "build_apply_plan",
    "apply_against_temp_copy",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""scripts/db_mutation_readiness_check.py

Read-only operator readiness checklist for any DB mutation.

Aggregates seven gates an operator should clear before running a write
script against the live ``events.db``.  Every gate is read-only — the
script never modifies the live archive, the backups directory, or the
git index.  Tests patch every seam at module level so the suite runs
without a real archive, real backups, or a real git checkout.

Gates
-----
* ``events_db_exists_and_readable``     — opens ``events.db`` in
  ``mode=ro`` URI form and runs ``PRAGMA schema_version``.
* ``latest_backup_exists_and_readable`` — picks the newest
  ``events-*.db`` under ``backups/`` and confirms the bytes are
  readable.
* ``backup_restore_check_ok``           — defers to
  :func:`scripts.backup_restore_check.restore_check` with
  ``use_latest=True`` and ``cleanup=True``.
* ``repo_hygiene_ok`` /
  ``no_tracked_generated_artifacts``    — share a single
  :func:`scripts.repo_hygiene_check.list_tracked_generated` call so
  ``git ls-files`` shells out only once per run.
* ``no_staged_files``                   — runs
  ``git diff --cached --name-only -z`` and fails closed when the
  index is non-empty OR git is unavailable.
* ``project_health_ok``                 — defers to
  :func:`scripts.project_health_check.run_health_check`, forwarding
  ``allow_duplicate_clusters`` so an operator-acknowledged
  duplicate-cluster baseline does not block the readiness gate.

Recommendation vocabulary
-------------------------
The ``recommended_next_action`` field carries the single most severe
blocker an operator should fix first.  Order:

    block_db_unreadable
    > block_no_backup
    > block_backup_restore_failed
    > block_repo_hygiene_dirty
    > block_staged_files_present
    > block_project_health_failed
    > ready_to_mutate

Out of scope (deliberately)
---------------------------
* No writes.  Never opens the live ``events.db`` for write, never
  copies bytes into ``backups/``, never modifies git state.
* Never imports ``yfinance``, ``market_data``, the FastAPI app, or any
  LLM seam directly.  The transitive surface inside
  ``run_health_check`` is itself isolated by that aggregator's own
  read-only contract.

Usage::

    python scripts/db_mutation_readiness_check.py
    python scripts/db_mutation_readiness_check.py --json
    python scripts/db_mutation_readiness_check.py --json \\
        --allow-duplicate-clusters 28
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Module-level seams — tests patch these on this module's namespace.
from scripts.repo_hygiene_check    import list_tracked_generated  # noqa: E402
from scripts.backup_restore_check  import (                       # noqa: E402
    find_latest_backup,
    restore_check,
)
from scripts.project_health_check  import run_health_check        # noqa: E402


_DEFAULT_DB         = "events.db"
_DEFAULT_BACKUP_DIR = "backups"


_GATE_KEYS: tuple[str, ...] = (
    "events_db_exists_and_readable",
    "latest_backup_exists_and_readable",
    "backup_restore_check_ok",
    "repo_hygiene_ok",
    "no_tracked_generated_artifacts",
    "no_staged_files",
    "project_health_ok",
)


_RECOMMEND_READY                = "ready_to_mutate"
_RECOMMEND_BLOCK_DB_UNREADABLE  = "block_db_unreadable"
_RECOMMEND_BLOCK_NO_BACKUP      = "block_no_backup"
_RECOMMEND_BLOCK_RESTORE_FAILED = "block_backup_restore_failed"
_RECOMMEND_BLOCK_REPO_DIRTY     = "block_repo_hygiene_dirty"
_RECOMMEND_BLOCK_STAGED_FILES   = "block_staged_files_present"
_RECOMMEND_BLOCK_PROJECT_HEALTH = "block_project_health_failed"


_RECOMMENDATIONS: tuple[str, ...] = (
    _RECOMMEND_READY,
    _RECOMMEND_BLOCK_DB_UNREADABLE,
    _RECOMMEND_BLOCK_NO_BACKUP,
    _RECOMMEND_BLOCK_RESTORE_FAILED,
    _RECOMMEND_BLOCK_REPO_DIRTY,
    _RECOMMEND_BLOCK_STAGED_FILES,
    _RECOMMEND_BLOCK_PROJECT_HEALTH,
)


# ---------------------------------------------------------------------------
# Per-gate seams — patched in tests via this module's namespace.
# ---------------------------------------------------------------------------


def _check_events_db_readable(db_path: str) -> tuple[bool, Optional[str]]:
    """Verify ``db_path`` exists and can be opened for reading.

    Read-only.  Opens the file via the ``file://...?mode=ro`` URI form
    and issues a single ``PRAGMA schema_version`` to confirm the bytes
    parse as a valid SQLite database.  Returns ``(False, error)`` on
    any failure so the caller can surface a precise reason.
    """
    p = Path(db_path)
    if not p.exists():
        return False, f"{db_path} does not exist"
    if not p.is_file():
        return False, f"{db_path} is not a regular file"
    try:
        uri = p.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return False, (
            f"could not open {db_path}: {type(exc).__name__}: {exc}"
        )
    try:
        try:
            conn.execute("PRAGMA schema_version").fetchone()
        except sqlite3.Error as exc:
            return False, (
                f"{db_path} is not a valid SQLite database: "
                f"{type(exc).__name__}: {exc}"
            )
    finally:
        conn.close()
    return True, None


def _check_backup_readable(path: Path) -> tuple[bool, Optional[str]]:
    """Verify ``path`` exists and the bytes are readable.  Pure file
    metadata check — does NOT open the file as SQLite (the
    ``backup_restore_check_ok`` gate owns that contract).
    """
    if not path.exists():
        return False, f"backup file does not exist: {path}"
    if not path.is_file():
        return False, f"backup path is not a regular file: {path}"
    if not os.access(str(path), os.R_OK):
        return False, f"backup file not readable: {path}"
    return True, None


def _list_staged_files(
    repo_path: Optional[str],
) -> tuple[list[str], Optional[str]]:
    """Return ``(paths, error)`` for the staged files in ``repo_path``.

    Read-only.  Shells out to ``git diff --cached --name-only -z``.
    Returns ``([], None)`` when nothing is staged, ``([], err)`` when
    git is unavailable or the cwd is not a git checkout (so the gate
    can fail closed).  Tests patch this attribute on the module's
    namespace.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            cwd=str(repo_path) if repo_path is not None else None,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return [], f"git not available: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        msg = (
            proc.stderr.decode("utf-8", errors="replace").strip()
            or f"git exited with code {proc.returncode}"
        )
        return [], f"git diff --cached failed: {msg}"
    raw = proc.stdout.decode("utf-8", errors="replace")
    paths = sorted(p for p in raw.split("\0") if p)
    return paths, None


# ---------------------------------------------------------------------------
# Per-gate runners — each returns a dict carrying ``ok`` plus enough
# context that the operator-facing text and JSON can describe the
# failure without a second tool invocation.
# ---------------------------------------------------------------------------


def _gate_events_db(*, db_path: str) -> dict[str, Any]:
    ok, err = _check_events_db_readable(db_path)
    out: dict[str, Any] = {"ok": ok, "db_path": db_path}
    if err is not None:
        out["error"] = err
    return out


def _gate_latest_backup(*, backup_dir: str) -> dict[str, Any]:
    path = find_latest_backup(Path(backup_dir))
    if path is None:
        return {
            "ok":          False,
            "backup_dir":  backup_dir,
            "backup_path": None,
            "error":       f"no events-*.db backups found in {backup_dir}",
        }
    ok, err = _check_backup_readable(path)
    out: dict[str, Any] = {
        "ok":          ok,
        "backup_dir":  backup_dir,
        "backup_path": str(path),
    }
    if err is not None:
        out["error"] = err
    return out


def _gate_backup_restore(*, backup_dir: str) -> dict[str, Any]:
    # ``cleanup=True`` removes the temp copy before return — the
    # readiness check never leaves stray bytes on disk.
    result = restore_check(
        use_latest=True,
        backup_dir=Path(backup_dir),
        cleanup=True,
    ) or {}
    return {
        "ok":          bool(result.get("ok", False)),
        "backup_path": result.get("backup_path"),
        "errors":      list(result.get("errors")   or []),
        "warnings":    list(result.get("warnings") or []),
    }


def _build_repo_hygiene_gate(matched: list[str]) -> dict[str, Any]:
    return {
        "ok":                       len(matched) == 0,
        "tracked_generated_count":  len(matched),
        "tracked_generated_paths":  list(matched),
    }


def _gate_no_staged_files(*, repo_path: Optional[str]) -> dict[str, Any]:
    paths, err = _list_staged_files(repo_path)
    out: dict[str, Any] = {
        "ok":           err is None and not paths,
        "staged_count": len(paths),
        "staged_files": list(paths),
    }
    if err is not None:
        out["error"] = err
    return out


def _gate_project_health(
    *,
    repo_path: Optional[str],
    db_path: str,
    backup_dir: str,
    allow_duplicate_clusters: int,
) -> dict[str, Any]:
    result = run_health_check(
        repo_path=repo_path,
        db_path=db_path,
        backup_dir=backup_dir,
        allow_duplicate_clusters=allow_duplicate_clusters,
    ) or {}
    return {
        "ok":                bool(result.get("ok", False)),
        "errors":            list(result.get("errors")            or []),
        "warnings":          list(result.get("warnings")          or []),
        "accepted_warnings": list(result.get("accepted_warnings") or []),
    }


# ---------------------------------------------------------------------------
# Recommendation — pick the first failing gate by spec order so the
# operator scanning the JSON always reads the most severe blocker first.
# ---------------------------------------------------------------------------


def _recommend(gates: dict[str, dict]) -> str:
    if not gates["events_db_exists_and_readable"]["ok"]:
        return _RECOMMEND_BLOCK_DB_UNREADABLE
    if not gates["latest_backup_exists_and_readable"]["ok"]:
        return _RECOMMEND_BLOCK_NO_BACKUP
    if not gates["backup_restore_check_ok"]["ok"]:
        return _RECOMMEND_BLOCK_RESTORE_FAILED
    if (
        not gates["repo_hygiene_ok"]["ok"]
        or not gates["no_tracked_generated_artifacts"]["ok"]
    ):
        return _RECOMMEND_BLOCK_REPO_DIRTY
    if not gates["no_staged_files"]["ok"]:
        return _RECOMMEND_BLOCK_STAGED_FILES
    if not gates["project_health_ok"]["ok"]:
        return _RECOMMEND_BLOCK_PROJECT_HEALTH
    return _RECOMMEND_READY


# ---------------------------------------------------------------------------
# Errors — flatten each failed gate into operator-readable lines, while
# avoiding double-counting the alias gate ``no_tracked_generated_artifacts``.
# ---------------------------------------------------------------------------


_PATH_PREVIEW_LIMIT = 5


def _preview_paths(paths: list[str], label: str) -> str:
    if not paths:
        return ""
    head = ", ".join(paths[:_PATH_PREVIEW_LIMIT])
    tail = " ..." if len(paths) > _PATH_PREVIEW_LIMIT else ""
    return f"{len(paths)} {label}: {head}{tail}"


def _gate_errors(name: str, gate: dict[str, Any]) -> list[str]:
    if gate["ok"]:
        return []
    # ``no_tracked_generated_artifacts`` is an alias over
    # ``repo_hygiene_ok``.  Reporting the same paths under both gate
    # names would double-count them in the operator-facing log.
    if name == "no_tracked_generated_artifacts":
        return []

    pieces: list[str] = []
    err = gate.get("error")
    if err:
        pieces.append(str(err))
    for e in gate.get("errors") or []:
        pieces.append(str(e))

    if name == "repo_hygiene_ok":
        preview = _preview_paths(
            list(gate.get("tracked_generated_paths") or []),
            "tracked generated artifact(s)",
        )
        if preview:
            pieces.append(preview)
    elif name == "no_staged_files":
        preview = _preview_paths(
            list(gate.get("staged_files") or []),
            "staged file(s)",
        )
        if preview:
            pieces.append(preview)

    if not pieces:
        pieces.append(f"{name} gate failed")
    return [f"{name}: {msg}" for msg in pieces]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def run_readiness_check(
    *,
    repo_path:                Optional[str] = None,
    db_path:                  str = _DEFAULT_DB,
    backup_dir:               str = _DEFAULT_BACKUP_DIR,
    allow_duplicate_clusters: int = 0,
) -> dict[str, Any]:
    """Run every readiness gate and aggregate the results.  Read-only.

    All sub-checks are read-only.  ``events.db`` and ``backups/`` are
    never mutated; ``git diff --cached`` is the only git command issued
    and it is itself read-only.

    ``allow_duplicate_clusters`` is forwarded verbatim to
    :func:`scripts.project_health_check.run_health_check` so an
    operator-acknowledged duplicate-cluster baseline does not block
    the readiness gate.  Default ``0`` preserves the strict pre-flag
    behavior.
    """
    gates: dict[str, dict[str, Any]] = {}

    gates["events_db_exists_and_readable"]     = _gate_events_db(
        db_path=db_path,
    )
    gates["latest_backup_exists_and_readable"] = _gate_latest_backup(
        backup_dir=backup_dir,
    )
    gates["backup_restore_check_ok"]           = _gate_backup_restore(
        backup_dir=backup_dir,
    )

    # Two repo-hygiene gates share a single ``list_tracked_generated``
    # call so ``git ls-files`` shells out only once per run.  Keys
    # diverge but values agree row-for-row.
    matched = list(list_tracked_generated(repo_path=repo_path))
    gates["repo_hygiene_ok"]                = _build_repo_hygiene_gate(matched)
    gates["no_tracked_generated_artifacts"] = _build_repo_hygiene_gate(matched)

    gates["no_staged_files"]    = _gate_no_staged_files(repo_path=repo_path)
    gates["project_health_ok"]  = _gate_project_health(
        repo_path=repo_path,
        db_path=db_path,
        backup_dir=backup_dir,
        allow_duplicate_clusters=allow_duplicate_clusters,
    )

    errors: list[str] = []
    for name in _GATE_KEYS:
        errors.extend(_gate_errors(name, gates[name]))

    ok = all(gates[name]["ok"] for name in _GATE_KEYS)
    return {
        "ok":                       ok,
        "gates":                    gates,
        "errors":                   errors,
        "recommended_next_action":  _recommend(gates),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["=== DB Mutation Readiness Check ==="]
    lines.append(f"ok: {payload['ok']}")
    lines.append(
        f"recommended_next_action: {payload['recommended_next_action']}",
    )
    lines.append("")
    for name in _GATE_KEYS:
        gate = payload["gates"].get(name) or {}
        status = "PASS" if gate.get("ok") else "FAIL"
        lines.append(f"  [{status}] {name}")
        for k in sorted(gate):
            if k == "ok":
                continue
            v = gate[k]
            lines.append(f"      {k}: {v}")
    errors = payload.get("errors") or []
    lines.append("")
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
            "Read-only operator readiness checklist for any DB mutation. "
            "Aggregates seven gates (events.db readable, latest backup "
            "readable, restore check, repo hygiene, tracked-artifact "
            "absence, staged-file absence, project health) and never "
            "modifies events.db, backups/, or the git index."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--repo-path", dest="repo_path", default=None,
        help="Optional repo path forwarded to repo_hygiene and staged-files "
             "gates and to project_health_check (default: cwd).",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=_DEFAULT_DB,
        help=f"SQLite events DB path (default: {_DEFAULT_DB}).",
    )
    parser.add_argument(
        "--backup-dir", dest="backup_dir", default=_DEFAULT_BACKUP_DIR,
        help=f"Backups directory (default: {_DEFAULT_BACKUP_DIR}/).",
    )
    parser.add_argument(
        "--allow-duplicate-clusters", dest="allow_duplicate_clusters",
        type=int, default=0,
        help=(
            "Acceptance threshold forwarded to "
            "scripts.project_health_check.run_health_check.  Default 0 "
            "preserves the strict pre-flag behavior."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    payload = run_readiness_check(
        repo_path=args.repo_path,
        db_path=args.db_path,
        backup_dir=args.backup_dir,
        allow_duplicate_clusters=args.allow_duplicate_clusters,
    )

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(payload), file=output)

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

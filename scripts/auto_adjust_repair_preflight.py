#!/usr/bin/env python3
"""scripts/auto_adjust_repair_preflight.py

Read-only preflight checklist for the auto-adjust mismatch repair
write run.

Aggregates the gates an operator must clear *before* invoking
``apply_auto_adjust_mismatch_repair(confirm=True, ...)`` on the live
``events.db``:

  1. ``repo_clean``     — ``git status --porcelain`` is empty so any
                          regression is recoverable via git.
  2. ``latest_backup``  — the newest ``events-*.db`` snapshot is
                          present in ``backups/``.
  3. ``repair_preview`` — the read-only repair preview loader produces
                          a usable payload (mismatch detection works,
                          no upstream regression).
  4. ``dry_run_plan``   — the writer's planner returns a non-empty
                          shape carrying ``planned_write_count``.
  5. ``no_paid_smoke``  — opt-in via ``--with-no-paid``; the
                          ``scripts.no_paid_smoke`` runner reports a
                          clean ``ok`` summary.

Out of scope (deliberately)
---------------------------
* **Never invokes the writer with ``confirm=True``.**  Only the
  planner / preview / smoke seams run.  Invariant pinned by
  ``tests/test_auto_adjust_repair_preflight.py``.
* No ``apply_auto_adjust_mismatch_repair(confirm=True)``, no
  ``--write``, no DB mutation by this script.
* No provider, ``yfinance``, ``market_check``, ``market_data``, or
  LLM seam.  No FastAPI app or ``routes.*`` import in the call path.
* The script is composition only — every gate has a module-level seam
  tests swap.  The aggregator never invents data; it summarises what
  the gates report.

Output shape (``--json``)
-------------------------
``{
   "ok": bool,
   "gates": { gate_name: { ok: bool, ... } },
   "errors": [str, …],
   "recommended_next_action": str
}``

Usage::

    python scripts/auto_adjust_repair_preflight.py
    python scripts/auto_adjust_repair_preflight.py --json
    python scripts/auto_adjust_repair_preflight.py --json --with-no-paid
    python scripts/auto_adjust_repair_preflight.py --json \\
        --repo-path . --db-path events.db --backup-dir backups
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Module-level seams — tests patch these on the preflight's namespace.
from scripts.backup_restore_check import find_latest_backup  # noqa: E402


_DEFAULT_DB_PATH    = "events.db"
_DEFAULT_BACKUP_DIR = "backups"
_DEFAULT_REPO_PATH  = "."

# Recommended-next-action vocabulary.  Pinned tightly so a runbook
# consumer can branch deterministically on the value.  Adding a new
# label requires updating ``_NEXT_ACTIONS`` *and* the test that pins
# the vocabulary so consumers aren't surprised by a new value.
_ACTION_ALL_PASS       = "all_gates_pass_review_dry_run_then_write"
_ACTION_REPO_DIRTY     = "repo_dirty_commit_or_stash_first"
_ACTION_BACKUP_MISSING = "missing_backup_run_backup_archive"
_ACTION_PREVIEW_FAILED = "preview_unavailable_check_diagnostics"
_ACTION_PLAN_FAILED    = "dry_run_failed_check_writer_module"
_ACTION_SMOKE_FAILED   = "no_paid_smoke_failed_check_smoke_log"

_NEXT_ACTIONS: tuple[str, ...] = (
    _ACTION_ALL_PASS,
    _ACTION_REPO_DIRTY,
    _ACTION_BACKUP_MISSING,
    _ACTION_PREVIEW_FAILED,
    _ACTION_PLAN_FAILED,
    _ACTION_SMOKE_FAILED,
)


# ---------------------------------------------------------------------------
# Gate seams — every external call funnels through one of these.
# Tests patch these directly on the preflight's namespace so the
# aggregator's behavior is verifiable without touching the real git
# tree, the real backups dir, or the real writer module.
# ---------------------------------------------------------------------------


def _check_repo_clean(*, repo_path: str) -> dict:
    """Run ``git status --porcelain`` against ``repo_path`` and return a
    summary.  ``ok`` is True iff the working tree has no uncommitted
    changes (staged, unstaged, or untracked).  ``git`` failures (e.g.
    not a git repo) surface as ``ok=False`` with the stderr string in
    ``error`` — the runbook can't proceed without git anyway, so an
    unreachable git binary is a hard fail rather than a soft warning.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            "ok":           False,
            "dirty_paths":  [],
            "count":        0,
            "error":        f"{type(exc).__name__}: {exc}",
        }
    if result.returncode != 0:
        return {
            "ok":           False,
            "dirty_paths":  [],
            "count":        0,
            "error":        (result.stderr or "").strip()
                            or f"git exited with code {result.returncode}",
        }
    lines = [line for line in result.stdout.splitlines() if line]
    return {
        "ok":          len(lines) == 0,
        "dirty_paths": lines,
        "count":       len(lines),
    }


def _check_latest_backup(*, backup_dir: str) -> dict:
    """Return ``{ok, path}`` describing whether the newest ``events-*.db``
    backup exists.  ``find_latest_backup`` returns ``None`` for both
    missing-dir and empty-dir; the caller can't distinguish, but the
    runbook response is the same: run ``scripts/backup_archive.py``.
    """
    backup = find_latest_backup(Path(backup_dir))
    return {
        "ok":   backup is not None,
        "path": str(backup) if backup is not None else None,
    }


def _compute_repair_preview() -> dict:
    """Default seam — best-effort lazy delegation to
    :mod:`scripts.auto_adjust_mismatch_repair_preview`.

    Tests MUST patch this attribute on the preflight's namespace so
    the lazy script import never fires inside ``run_preflight``.
    Returns ``{available: False}`` on any failure so the gate aggregator
    never crashes.
    """
    try:
        from scripts import auto_adjust_mismatch_repair_preview as _preview
    except Exception as exc:
        return {
            "available": False,
            "error":     f"{type(exc).__name__}: {exc}",
        }
    try:
        details    = _preview._load_auto_adjust_mismatch_details() or []
        specs      = _preview._windows_for_details(details)
        cache_rows = (
            _preview._load_in_window_cache_rows(specs) if specs else {}
        )
        # ``limit=0`` keeps proposed_rows empty — the aggregator only
        # surfaces the top-level counts.
        payload = _preview._build_payload(details, cache_rows, limit=0)
    except Exception as exc:
        return {
            "available": False,
            "error":     f"{type(exc).__name__}: {exc}",
        }
    payload.setdefault("available", True)
    return payload


def _compute_dry_run_plan(*, db_path: Optional[str]) -> dict:
    """Default seam — call the writer's *planner* (never the apply
    function).  ``confirm=True`` is never reachable from this script:
    the apply seam is not imported and the planner accepts no
    ``confirm`` argument.

    Tests MUST patch this attribute on the preflight's namespace via
    ``_patch_all_clean()``.  Returns ``{available: False, ...}`` on any
    failure so the gate aggregator never crashes.
    """
    try:
        from auto_adjust_mismatch_repair import (
            plan_auto_adjust_mismatch_repair,
        )
    except ImportError as exc:
        return {
            "available":            False,
            "planned_write_count":  0,
            "total_mismatches":     0,
            "error":                f"{type(exc).__name__}: {exc}",
        }
    try:
        plan = plan_auto_adjust_mismatch_repair(db_path=db_path)
    except Exception as exc:
        return {
            "available":            False,
            "planned_write_count":  0,
            "total_mismatches":     0,
            "error":                f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(plan, dict):
        return {
            "available":            False,
            "planned_write_count":  0,
            "total_mismatches":     0,
            "error":                f"plan returned non-dict: {type(plan).__name__}",
        }
    return {
        "available":            True,
        "planned_write_count":  int(plan.get("planned_write_count") or 0),
        "total_mismatches":     int(plan.get("total_mismatches")    or 0),
    }


def _compute_no_paid_smoke() -> dict:
    """Default seam — invoke ``scripts.no_paid_smoke.run_smoke`` and
    summarise.  Lazy-imported because the smoke harness pulls in the
    FastAPI test client; tests patch this seam to avoid the cost.
    """
    try:
        from scripts import no_paid_smoke as _smoke
    except Exception as exc:
        return {
            "available": False,
            "ok":        False,
            "error":     f"{type(exc).__name__}: {exc}",
        }
    try:
        results = _smoke.run_smoke()
        summary = _smoke.summarize(results)
    except Exception as exc:
        return {
            "available": False,
            "ok":        False,
            "error":     f"{type(exc).__name__}: {exc}",
        }
    inner = summary.get("summary") or {}
    return {
        "available": True,
        "ok":        bool(summary.get("ok")),
        "passed":    int(inner.get("passed") or 0),
        "total":     int(inner.get("total")  or 0),
        "failed":    int(inner.get("failed") or 0),
    }


# ---------------------------------------------------------------------------
# Gate runners — each returns a self-contained dict the aggregator
# embeds verbatim under ``gates[<name>]``.
# ---------------------------------------------------------------------------


def _gate_repo_clean(*, repo_path: str) -> tuple[dict, list[str]]:
    section = _check_repo_clean(repo_path=repo_path)
    errors: list[str] = []
    if not section.get("ok"):
        if section.get("error"):
            errors.append(f"repo_clean: {section['error']}")
        elif section.get("count", 0) > 0:
            errors.append(
                f"repo_clean: {section['count']} uncommitted path(s) "
                "in working tree"
            )
        else:
            errors.append("repo_clean: working tree not clean")
    return section, errors


def _gate_latest_backup(*, backup_dir: str) -> tuple[dict, list[str]]:
    section = _check_latest_backup(backup_dir=backup_dir)
    errors: list[str] = []
    if not section.get("ok"):
        errors.append(
            f"latest_backup: no events-*.db backup found in {backup_dir!r}"
        )
    return section, errors


def _gate_repair_preview() -> tuple[dict, list[str]]:
    raw = _compute_repair_preview() or {}
    available = bool(raw.get("available"))
    errors: list[str] = []
    if not available:
        errors.append(
            "repair_preview: preview loader unavailable"
            + (f" ({raw['error']})" if raw.get("error") else "")
        )
    return {
        "ok":                       available,
        "total_mismatches":         int(raw.get("total_mismatches")     or 0),
        "repairable_count":         int(raw.get("repairable_count")     or 0),
        "non_repairable_count":     int(raw.get("non_repairable_count") or 0),
        "preview_recommended_action":
            raw.get("recommended_next_action"),
    }, errors


def _gate_dry_run_plan(*, db_path: Optional[str]) -> tuple[dict, list[str]]:
    raw = _compute_dry_run_plan(db_path=db_path) or {}
    available = bool(raw.get("available"))
    errors: list[str] = []
    if not available:
        errors.append(
            "dry_run_plan: planner unavailable"
            + (f" ({raw['error']})" if raw.get("error") else "")
        )
    return {
        "ok":                  available,
        "planned_write_count": int(raw.get("planned_write_count") or 0),
        "total_mismatches":    int(raw.get("total_mismatches")    or 0),
    }, errors


def _gate_no_paid_smoke(*, requested: bool) -> tuple[dict, list[str]]:
    if not requested:
        return {
            "ok":        None,
            "requested": False,
            "passed":    None,
            "total":     None,
            "failed":    None,
        }, []
    raw = _compute_no_paid_smoke() or {}
    smoke_ok = bool(raw.get("ok"))
    errors: list[str] = []
    if not smoke_ok:
        errors.append(
            "no_paid_smoke: smoke run failed"
            + (f" ({raw['error']})" if raw.get("error") else "")
        )
    return {
        "ok":        smoke_ok,
        "requested": True,
        "passed":    raw.get("passed"),
        "total":     raw.get("total"),
        "failed":    raw.get("failed"),
    }, errors


# ---------------------------------------------------------------------------
# Recommendation — pure decision tree over the gates.
# ---------------------------------------------------------------------------


def _recommend_next_action(gates: dict) -> str:
    """Pure decision tree.  Priority order: repo > backup > preview >
    plan > smoke; when all gates pass, recommend reviewing the dry-run
    output before the live write.  The order is load-bearing — a
    runbook consumer reading the value decides what to *do next*, and
    the deepest recoverable problem should win.
    """
    if not gates.get("repo_clean", {}).get("ok"):
        return _ACTION_REPO_DIRTY
    if not gates.get("latest_backup", {}).get("ok"):
        return _ACTION_BACKUP_MISSING
    if not gates.get("repair_preview", {}).get("ok"):
        return _ACTION_PREVIEW_FAILED
    if not gates.get("dry_run_plan", {}).get("ok"):
        return _ACTION_PLAN_FAILED
    smoke = gates.get("no_paid_smoke", {})
    if smoke.get("requested") and not smoke.get("ok"):
        return _ACTION_SMOKE_FAILED
    return _ACTION_ALL_PASS


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_preflight(
    *,
    repo_path:    str = _DEFAULT_REPO_PATH,
    db_path:      Optional[str] = _DEFAULT_DB_PATH,
    backup_dir:   str = _DEFAULT_BACKUP_DIR,
    with_no_paid: bool = False,
) -> dict:
    """Run all gates and assemble the report.  Read-only — never mutates
    the repo, the DB, or the backups directory."""
    errors: list[str] = []

    repo_section,    repo_errs    = _gate_repo_clean(repo_path=repo_path)
    backup_section,  backup_errs  = _gate_latest_backup(backup_dir=backup_dir)
    preview_section, preview_errs = _gate_repair_preview()
    plan_section,    plan_errs    = _gate_dry_run_plan(db_path=db_path)
    smoke_section,   smoke_errs   = _gate_no_paid_smoke(requested=with_no_paid)

    errors.extend(repo_errs)
    errors.extend(backup_errs)
    errors.extend(preview_errs)
    errors.extend(plan_errs)
    errors.extend(smoke_errs)

    gates = {
        "repo_clean":     repo_section,
        "latest_backup":  backup_section,
        "repair_preview": preview_section,
        "dry_run_plan":   plan_section,
        "no_paid_smoke":  smoke_section,
    }

    return {
        "ok":                      not errors,
        "gates":                   gates,
        "errors":                  errors,
        "recommended_next_action": _recommend_next_action(gates),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict) -> str:
    lines: list[str] = ["=== auto-adjust repair preflight ==="]
    lines.append(f"ok:                       {report['ok']}")
    lines.append(
        f"recommended_next_action:  {report['recommended_next_action']}"
    )
    gates = report.get("gates") or {}
    for name in (
        "repo_clean", "latest_backup", "repair_preview",
        "dry_run_plan", "no_paid_smoke",
    ):
        section = gates.get(name) or {}
        lines.append(f"--- {name} ---")
        for k in sorted(section):
            lines.append(f"  {k}: {section[k]}")
    errors = report.get("errors") or []
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
            "Read-only preflight checklist for the auto-adjust mismatch "
            "repair write run.  Never invokes the writer with confirm=True."
        ),
    )
    parser.add_argument(
        "--repo-path", default=_DEFAULT_REPO_PATH,
        help=f"Path to the git checkout (default: {_DEFAULT_REPO_PATH}).",
    )
    parser.add_argument(
        "--db-path", default=_DEFAULT_DB_PATH,
        help=f"Path to the live events.db (default: {_DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--backup-dir", default=_DEFAULT_BACKUP_DIR,
        help=f"Backups directory (default: {_DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--with-no-paid", action="store_true",
        help=(
            "Run scripts.no_paid_smoke as part of the preflight.  Off "
            "by default because the smoke boots the FastAPI test client."
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

    report = run_preflight(
        repo_path    = args.repo_path,
        db_path      = args.db_path,
        backup_dir   = args.backup_dir,
        with_no_paid = args.with_no_paid,
    )

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(report), file=output)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

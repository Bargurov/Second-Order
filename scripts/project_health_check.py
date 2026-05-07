#!/usr/bin/env python3
"""scripts/project_health_check.py

Read-only project health aggregator.

Composes four existing local checks and produces a single structured
report.  Every underlying check is read-only.  This script never
modifies ``events.db`` or files under ``backups/``; it never imports
the FastAPI app, ``yfinance``, ``market_check``, ``market_data``, the
production ``price_cache`` module, or any LLM seam.

Composed checks
---------------
* ``repo_hygiene``                  — ``scripts.repo_hygiene_check``
* ``backup_restore``                — ``scripts.backup_restore_check``
* ``schema_preflight``              — ``scripts.schema_preflight``
* ``event_date_backfill_candidates`` — ``event_date_backfill``

Each underlying check is a single function reference re-bound at
module level so tests can patch the seam by name.

Usage::

    python scripts/project_health_check.py
    python scripts/project_health_check.py --json
    python scripts/project_health_check.py --json \\
        --repo-path . --db-path events.db --backup-dir backups
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Module-level seams — tests patch these on the aggregator's namespace.
from scripts.repo_hygiene_check  import list_tracked_generated  # noqa: E402
from scripts.backup_restore_check import restore_check          # noqa: E402
from scripts.schema_preflight     import collect as schema_preflight_collect  # noqa: E402
from event_date_backfill          import plan_event_date_backfill  # noqa: E402


_DEFAULT_DB         = "events.db"
_DEFAULT_BACKUP_DIR = "backups"


# ---------------------------------------------------------------------------
# Per-section runners
# ---------------------------------------------------------------------------


def _section_repo_hygiene(*, repo_path: Optional[str]) -> dict:
    matched = list_tracked_generated(repo_path=repo_path)
    return {
        "ok":                      len(matched) == 0,
        "tracked_generated_count": len(matched),
        "tracked_generated_paths": list(matched),
    }


def _section_backup_restore(*, backup_dir: str) -> dict:
    # ``cleanup=True`` ensures the temp copy is removed before return —
    # the aggregator never leaves stray bytes on disk.
    return restore_check(
        use_latest=True,
        backup_dir=Path(backup_dir),
        cleanup=True,
    )


def _section_schema_preflight(*, db_path: str, backup_dir: str) -> dict:
    return schema_preflight_collect(str(db_path), str(backup_dir))


def _section_event_date_backfill(*, db_path: str) -> dict:
    # Slim summary — the planner's full ``proposed_updates`` list can
    # carry hundreds of rows; the aggregator surfaces counts only and
    # leaves the full plan to the dedicated CLI.
    plan = plan_event_date_backfill(db_path=str(db_path) if db_path else None)
    return {
        "total_candidates":           plan.get("total_candidates", 0),
        "events_with_market_tickers": plan.get("events_with_market_tickers", 0),
        "ticker_rows_blocked":        plan.get("ticker_rows_blocked", 0),
        "skipped_counts":             dict(plan.get("skipped_counts") or {}),
        "confidence_note":            plan.get("confidence_note", ""),
    }


# ---------------------------------------------------------------------------
# Per-section classification — derive top-level errors/warnings.
# ---------------------------------------------------------------------------


def _classify_repo_hygiene(section: dict) -> tuple[list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    count = section.get("tracked_generated_count", 0)
    if count > 0:
        errors.append(f"{count} tracked generated artifact(s) in git index")
    return errors, warnings


def _classify_backup_restore(section: dict) -> tuple[list[str], list[str]]:
    errors   = list(section.get("errors")   or [])
    warnings = list(section.get("warnings") or [])
    return errors, warnings


def _classify_schema_preflight(section: dict) -> tuple[list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    tables = section.get("tables") or []
    if not section.get("database_exists"):
        errors.append("database file does not exist")
    elif "events" not in tables:
        errors.append("events table missing")
    if section.get("database_exists") and not section.get("price_cache_present"):
        errors.append("price_cache table missing")
    # Forward non-critical warnings; suppress duplicates of the
    # critical ones we already raised.
    for w in section.get("warnings") or []:
        wl = w.lower()
        if "events table missing" in wl or "database file does not exist" in wl:
            continue
        warnings.append(w)
    return errors, warnings


def _classify_event_date_backfill(section: dict) -> tuple[list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    count = section.get("total_candidates", 0)
    if count > 0:
        warnings.append(
            f"{count} legacy event(s) lack event_date and need backfill",
        )
    return errors, warnings


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


_SECTION_KEYS = (
    "repo_hygiene",
    "backup_restore",
    "schema_preflight",
    "event_date_backfill_candidates",
)


def _empty_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok":       True,
        "warnings": [],
        "errors":   [],
    }
    for key in _SECTION_KEYS:
        payload[key] = None
    return payload


def _run_section(
    payload: dict[str, Any],
    name: str,
    fn: Callable[[], dict],
    classify: Callable[[dict], tuple[list[str], list[str]]],
) -> None:
    try:
        section = fn()
    except Exception as exc:
        # Soft failure: capture the exception, mark the section as
        # not-ok, and continue with the remaining sections.
        payload[name] = {
            "ok":    False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        payload["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        return
    payload[name] = section
    sec_errors, sec_warnings = classify(section)
    payload["errors"].extend(f"{name}: {e}"   for e in sec_errors)
    payload["warnings"].extend(f"{name}: {w}" for w in sec_warnings)


def run_health_check(
    *,
    repo_path:  Optional[str] = None,
    db_path:    str = _DEFAULT_DB,
    backup_dir: str = _DEFAULT_BACKUP_DIR,
) -> dict[str, Any]:
    """Run every underlying check and aggregate the results.

    All sub-checks are read-only.  ``events.db`` and ``backups/`` are
    never mutated.  Sub-check exceptions are caught and surfaced in the
    top-level ``errors`` list rather than aborting the run.
    """
    payload = _empty_payload()

    _run_section(
        payload, "repo_hygiene",
        lambda: _section_repo_hygiene(repo_path=repo_path),
        _classify_repo_hygiene,
    )
    _run_section(
        payload, "backup_restore",
        lambda: _section_backup_restore(backup_dir=backup_dir),
        _classify_backup_restore,
    )
    _run_section(
        payload, "schema_preflight",
        lambda: _section_schema_preflight(
            db_path=db_path, backup_dir=backup_dir,
        ),
        _classify_schema_preflight,
    )
    _run_section(
        payload, "event_date_backfill_candidates",
        lambda: _section_event_date_backfill(db_path=db_path),
        _classify_event_date_backfill,
    )

    payload["ok"] = not payload["errors"]
    return payload


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["=== Project Health Check ==="]
    lines.append(f"ok: {payload['ok']}")
    lines.append("")
    for key in _SECTION_KEYS:
        section = payload.get(key)
        if section is None:
            lines.append(f"{key}: (not run)")
            continue
        lines.append(f"--- {key} ---")
        if "ok" in section:
            lines.append(f"  ok: {section['ok']}")
        if key == "repo_hygiene":
            lines.append(
                f"  tracked_generated_count: "
                f"{section.get('tracked_generated_count', 0)}",
            )
        elif key == "backup_restore":
            lines.append(f"  backup_path: {section.get('backup_path')}")
            counts = section.get("table_counts") or {}
            for k in sorted(counts):
                lines.append(f"  {k}: {counts[k]}")
        elif key == "schema_preflight":
            lines.append(
                f"  database_exists: {section.get('database_exists')}",
            )
            lines.append(
                f"  tables: {len(section.get('tables') or [])}",
            )
            lines.append(
                f"  price_cache_present: {section.get('price_cache_present')}",
            )
        elif key == "event_date_backfill_candidates":
            lines.append(
                f"  total_candidates: {section.get('total_candidates', 0)}",
            )
            lines.append(
                "  ticker_rows_blocked: "
                f"{section.get('ticker_rows_blocked', 0)}",
            )
        lines.append("")

    warnings = payload.get("warnings") or []
    if warnings:
        lines.append(f"Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Warnings: (none)")

    errors = payload.get("errors") or []
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
            "Read-only aggregate health check.  Composes four local "
            "checks and emits a structured report.  Never mutates "
            "events.db or backups/."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of the text summary.",
    )
    parser.add_argument(
        "--repo-path", dest="repo_path", default=None,
        help="Optional repo path for repo_hygiene_check (default: cwd).",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=_DEFAULT_DB,
        help=f"SQLite events DB path (default: {_DEFAULT_DB}).",
    )
    parser.add_argument(
        "--backup-dir", dest="backup_dir", default=_DEFAULT_BACKUP_DIR,
        help=f"Backups directory (default: {_DEFAULT_BACKUP_DIR}/).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    payload = run_health_check(
        repo_path=args.repo_path,
        db_path=args.db_path,
        backup_dir=args.backup_dir,
    )

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=output)
    else:
        print(_render_text(payload), file=output)

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

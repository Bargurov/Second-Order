#!/usr/bin/env python3
"""scripts/project_health_check.py

Read-only project health aggregator.

Composes six local checks and produces a single structured report.
Every underlying check is read-only.  This script never modifies
``events.db`` or files under ``backups/``; it never imports the FastAPI
app, ``yfinance``, ``market_check``, ``market_data``, the production
``price_cache`` module, or any LLM seam.

Composed checks
---------------
* ``repo_hygiene``                   — ``scripts.repo_hygiene_check``
* ``backup_restore``                 — ``scripts.backup_restore_check``
* ``schema_preflight``               — ``scripts.schema_preflight``
* ``event_date_backfill_candidates`` — ``event_date_backfill``
* ``archive_consistency``            — local SQL audit (inline)
* ``event_date_backfill_impact``     — ``event_date_backfill`` projection

Each underlying check is a single function reference at module level so
tests can patch the seam by name.  ``archive_consistency`` is inlined
here rather than imported from ``routes.archive_diagnostics`` because
the aggregator's import-graph guard forbids ``routes.*`` imports.

Usage::

    python scripts/project_health_check.py
    python scripts/project_health_check.py --json
    python scripts/project_health_check.py --json \\
        --repo-path . --db-path events.db --backup-dir backups
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
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
# Inline archive-consistency seam
# ---------------------------------------------------------------------------
#
# Mirrors ``routes.archive_diagnostics.compute_archive_consistency`` but
# is inlined here so the aggregator stays clear of the ``routes.*``
# import guard enforced by ``test_running_does_not_import_fastapi_routes``.
# Pure read — issues ``SELECT`` statements only.

_ARCHIVE_EXAMPLE_LIMIT = 10

_ARCHIVE_CATEGORY_KEYS: tuple[str, ...] = (
    "malformed_market_tickers_json",
    "missing_headline",
    "missing_timestamp",
    "missing_event_date",
    "malformed_event_date",
    "missing_market_tickers",
    "duplicate_headline_event_date_clusters",
)


def _empty_archive_consistency() -> dict[str, dict[str, Any]]:
    return {key: {"count": 0, "examples": []} for key in _ARCHIVE_CATEGORY_KEYS}


def _is_blank_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return False
    return True


def _is_malformed_market_tickers(value: Any) -> bool:
    if _is_blank_string(value):
        return False
    if not isinstance(value, str):
        return True
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return True
    return not isinstance(parsed, list)


def _scan_consistency_per_row(
    rows: list[tuple],
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "malformed_market_tickers_json": [],
        "missing_headline":              [],
        "missing_timestamp":             [],
        "missing_event_date":            [],
        "malformed_event_date":          [],
        "missing_market_tickers":        [],
    }
    for event_id, headline, timestamp, market_tickers, event_date_str in rows:
        common = {
            "event_id":   event_id,
            "headline":   headline,
            "timestamp":  timestamp,
            "event_date": event_date_str,
        }
        if _is_blank_string(headline):
            buckets["missing_headline"].append(dict(common))
        if _is_blank_string(timestamp):
            buckets["missing_timestamp"].append(dict(common))
        if _is_blank_string(event_date_str):
            buckets["missing_event_date"].append(dict(common))
        elif not _is_iso_date(event_date_str):
            buckets["malformed_event_date"].append(dict(common))
        if _is_blank_string(market_tickers):
            buckets["missing_market_tickers"].append(dict(common))
        elif _is_malformed_market_tickers(market_tickers):
            example = dict(common)
            example["market_tickers"] = market_tickers
            buckets["malformed_market_tickers_json"].append(example)
    return buckets


def compute_archive_consistency_local(
    *, db_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Read-only archive-consistency audit against a local SQLite DB.

    Defensive on every failure mode: a missing file, a missing
    ``events`` table, or any other ``sqlite3.Error`` returns the
    all-zero response so the aggregator never crashes on a misconfigured
    install.  Tests patch this seam on the module's namespace.
    """
    import db as _db

    path = db_path if db_path is not None else _db.DB_FILE

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return _empty_archive_consistency()

    try:
        try:
            rows = conn.execute(
                "SELECT id, headline, timestamp, market_tickers, event_date "
                "FROM events ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            return _empty_archive_consistency()

        per_row = _scan_consistency_per_row(rows)

        try:
            dup_rows = conn.execute(
                "SELECT headline, event_date, COUNT(*) AS cnt, "
                "       GROUP_CONCAT(id, ',') AS ids "
                "FROM events "
                "WHERE headline   IS NOT NULL AND TRIM(headline)   != '' "
                "  AND event_date IS NOT NULL AND TRIM(event_date) != '' "
                "GROUP BY headline, event_date "
                "HAVING cnt >= 2 "
                "ORDER BY cnt DESC, headline ASC, event_date ASC"
            ).fetchall()
        except sqlite3.Error:
            dup_rows = []
    finally:
        conn.close()

    duplicates: list[dict[str, Any]] = []
    for headline, event_date_str, cnt, ids_csv in dup_rows:
        ids = sorted(int(x) for x in (ids_csv or "").split(",") if x)
        duplicates.append({
            "headline":   headline,
            "event_date": event_date_str,
            "count":      int(cnt),
            "event_ids":  ids,
        })

    response = _empty_archive_consistency()
    for key in _ARCHIVE_CATEGORY_KEYS:
        if key == "duplicate_headline_event_date_clusters":
            response[key] = {
                "count":    len(duplicates),
                "examples": duplicates[:_ARCHIVE_EXAMPLE_LIMIT],
            }
        else:
            bucket = per_row[key]
            response[key] = {
                "count":    len(bucket),
                "examples": bucket[:_ARCHIVE_EXAMPLE_LIMIT],
            }
    return response


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


def _section_archive_consistency(*, db_path: str) -> dict:
    raw = compute_archive_consistency_local(
        db_path=str(db_path) if db_path else None,
    ) or {}
    categories: dict[str, dict[str, Any]] = {}
    for key in _ARCHIVE_CATEGORY_KEYS:
        bucket = raw.get(key) or {}
        categories[key] = {
            "count":    int(bucket.get("count")    or 0),
            "examples": list(bucket.get("examples") or []),
        }
    return {"categories": categories}


def _section_event_date_backfill_impact(*, db_path: str) -> dict:
    # Reuses the existing ``plan_event_date_backfill`` seam — the impact
    # section is a different *view* of the same underlying plan, slimmed
    # to the three projection counts an operator needs to size the
    # downstream hydration win.
    plan = plan_event_date_backfill(db_path=str(db_path) if db_path else None)
    impact = (plan.get("projected_hydration_impact") or {}) if isinstance(plan, dict) else {}
    return {
        "candidate_events":               int(impact.get("candidate_events") or 0),
        "proposed_updates":               int(impact.get("proposed_updates_count") or 0),
        "projected_ticker_rows_unblocked":
            int(impact.get("ticker_rows_unblocked_by_write") or 0),
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


def _classify_archive_consistency(section: dict) -> tuple[list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    cats = section.get("categories") or {}
    error_categories = (
        ("malformed_market_tickers_json", "row(s) with malformed market_tickers JSON"),
        ("missing_headline",              "row(s) with missing headline"),
        ("missing_timestamp",             "row(s) with missing timestamp"),
        ("malformed_event_date",          "row(s) with malformed event_date"),
    )
    for key, label in error_categories:
        count = int((cats.get(key) or {}).get("count") or 0)
        if count > 0:
            errors.append(f"{count} {label}")
    dup_count = int(
        (cats.get("duplicate_headline_event_date_clusters") or {}).get("count") or 0
    )
    if dup_count > 0:
        warnings.append(
            f"{dup_count} duplicate (headline, event_date) cluster(s)",
        )
    return errors, warnings


def _classify_event_date_backfill_impact(
    section: dict,
) -> tuple[list[str], list[str]]:
    # Operator info only — the candidates section already surfaces the
    # backlog warning when count > 0.  Surfacing it twice would
    # double-count the same root cause.
    return [], []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


_SECTION_KEYS = (
    "repo_hygiene",
    "backup_restore",
    "schema_preflight",
    "event_date_backfill_candidates",
    "archive_consistency",
    "event_date_backfill_impact",
)


def _empty_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok":                 True,
        "warnings":           [],
        "errors":             [],
        "accepted_warnings":  [],
    }
    for key in _SECTION_KEYS:
        payload[key] = None
    return payload


_DUPLICATE_WARNING_NEEDLE = "duplicate (headline, event_date) cluster"


def _waive_duplicate_clusters(
    payload: dict[str, Any], *, allow: int,
) -> None:
    """Move the duplicate-cluster warning into ``accepted_warnings``
    when the live count is non-zero but ``<= allow``.

    Default ``allow=0`` reproduces the strict pre-flag behavior — the
    warning stays in ``payload['warnings']``.  When ``allow`` is large
    enough to cover the live count, the warning is removed from
    ``warnings`` and re-emitted on ``accepted_warnings`` with the
    operator-supplied threshold appended so reviewers can see the
    waiver was deliberate.
    """
    if allow < 1:
        return
    section = payload.get("archive_consistency")
    if not isinstance(section, dict):
        return
    cats = section.get("categories") or {}
    dup = cats.get("duplicate_headline_event_date_clusters") or {}
    count = int(dup.get("count") or 0)
    if count <= 0 or count > allow:
        return

    waived: list[str] = []
    keep:   list[str] = []
    for w in payload["warnings"]:
        if (
            w.startswith("archive_consistency: ")
            and _DUPLICATE_WARNING_NEEDLE in w
        ):
            waived.append(
                f"{w} (waived: count {count} <= --allow-duplicate-clusters {allow})",
            )
        else:
            keep.append(w)
    if not waived:
        return
    payload["warnings"]          = keep
    payload["accepted_warnings"].extend(waived)


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
    repo_path:               Optional[str] = None,
    db_path:                 str = _DEFAULT_DB,
    backup_dir:              str = _DEFAULT_BACKUP_DIR,
    allow_duplicate_clusters: int = 0,
) -> dict[str, Any]:
    """Run every underlying check and aggregate the results.

    All sub-checks are read-only.  ``events.db`` and ``backups/`` are
    never mutated.  Sub-check exceptions are caught and surfaced in the
    top-level ``errors`` list rather than aborting the run.

    ``allow_duplicate_clusters`` is the operator-set acceptance
    threshold for the ``archive_consistency`` duplicate-cluster
    warning.  Default ``0`` keeps the strict behavior (any non-zero
    cluster count surfaces as a warning).  When the live count is
    ``> 0`` and ``<= allow_duplicate_clusters``, the warning is moved
    from ``payload['warnings']`` into ``payload['accepted_warnings']``
    so the operator-acknowledged baseline does not flood the
    operational warning channel.
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
    _run_section(
        payload, "archive_consistency",
        lambda: _section_archive_consistency(db_path=db_path),
        _classify_archive_consistency,
    )
    _run_section(
        payload, "event_date_backfill_impact",
        lambda: _section_event_date_backfill_impact(db_path=db_path),
        _classify_event_date_backfill_impact,
    )

    _waive_duplicate_clusters(payload, allow=int(allow_duplicate_clusters or 0))

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
        elif key == "archive_consistency":
            cats = section.get("categories") or {}
            for cat_key in _ARCHIVE_CATEGORY_KEYS:
                count = int((cats.get(cat_key) or {}).get("count") or 0)
                lines.append(f"  {cat_key}: {count}")
        elif key == "event_date_backfill_impact":
            lines.append(
                f"  candidate_events: "
                f"{section.get('candidate_events', 0)}",
            )
            lines.append(
                f"  proposed_updates: "
                f"{section.get('proposed_updates', 0)}",
            )
            lines.append(
                f"  projected_ticker_rows_unblocked: "
                f"{section.get('projected_ticker_rows_unblocked', 0)}",
            )
        lines.append("")

    warnings = payload.get("warnings") or []
    if warnings:
        lines.append(f"Warnings ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Warnings: (none)")

    accepted = payload.get("accepted_warnings") or []
    if accepted:
        lines.append(f"Accepted warnings ({len(accepted)}):")
        for w in accepted:
            lines.append(f"  - {w}")

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
    parser.add_argument(
        "--allow-duplicate-clusters", dest="allow_duplicate_clusters",
        type=int, default=0,
        help=(
            "Acceptance threshold for the archive_consistency "
            "duplicate-cluster warning.  When the live cluster count is "
            "between 1 and N (inclusive), the warning is moved into the "
            "accepted_warnings list instead of the warnings list.  "
            "Default 0 preserves the strict pre-flag behavior."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    payload = run_health_check(
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

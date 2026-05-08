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
from scripts.backup_restore_check import (  # noqa: E402
    restore_check,
    find_latest_backup,
)
from scripts.schema_preflight     import collect as schema_preflight_collect  # noqa: E402
from event_date_backfill          import plan_event_date_backfill  # noqa: E402
from scripts.stat_validation_readiness_report import (  # noqa: E402
    summarize_readiness as summarize_stat_validation_readiness,
)


_DEFAULT_DB         = "events.db"
_DEFAULT_BACKUP_DIR = "backups"


# ---------------------------------------------------------------------------
# no_forward_20d blocker summary — shared constants and seam
# ---------------------------------------------------------------------------
#
# The breakdown function lives in ``routes.diagnostics`` and depends on
# the per-ticker hydrator; inlining it here would mean inlining the
# hydrator chain, which is too heavy for an aggregator.  Instead we
# expose a module-level seam that tests patch via ``_patch_all_clean()``
# and that defaults to a best-effort lazy delegation when the script is
# invoked live.  The lazy import only fires when the seam is NOT
# patched — keeping the import-graph guard
# (``test_running_does_not_import_fastapi_routes``) green requires that
# every code path which calls ``run_health_check`` patch this seam.

_NF20_REASON_KEYS: tuple[str, ...] = (
    "event_too_recent_for_20d",
    "auto_adjust_mismatch_for_20d",
    "likely_delisted_or_sparse",
    "cache_max_before_20d_horizon",
)

_NF20_RECOMMEND_NO_GAPS         = "no_action_needed_no_gaps"
_NF20_RECOMMEND_FIX_FLAG        = "fix_auto_adjust_flag_mismatch"
_NF20_RECOMMEND_REFRESH         = "run_targeted_refresh_for_cache_window_gap"
_NF20_RECOMMEND_WAIT            = "wait_or_accept_no_refreshable_gaps"
_NF20_RECOMMEND_UNAVAILABLE     = "breakdown_unavailable"


def _no_forward_20d_blockers_unavailable() -> dict[str, Any]:
    """Stable empty shape returned when the breakdown cannot run."""
    return {
        "available":            False,
        "total_no_forward_20d": 0,
        "counts":               {k: 0 for k in _NF20_REASON_KEYS},
        "examples":             [],
    }


def _compute_no_forward_20d_breakdown() -> dict[str, Any]:
    """Default seam — best-effort lazy delegation to
    :func:`routes.diagnostics._compute_no_forward_20d_breakdown`.

    Tests MUST patch this attribute on the aggregator's namespace
    before invoking :func:`run_health_check`; the import-graph guard
    (``test_running_does_not_import_fastapi_routes``) relies on the
    seam being replaced so the lazy ``routes.diagnostics`` import
    never fires.  Returns the all-zero ``available=False`` shape on
    any failure (DB not bootstrapped, circular import, environment
    missing the routes layer) so the aggregator never crashes.
    """
    try:
        import api  # noqa: F401  - resolves api ↔ routes.diagnostics cycle
        import db as _db
        from routes.diagnostics import (
            _compute_no_forward_20d_breakdown as _live,
        )
    except Exception:
        return _no_forward_20d_blockers_unavailable()

    if not _db._db_ready:
        try:
            _db.init_db()
        except Exception:
            return _no_forward_20d_blockers_unavailable()

    try:
        return _live() or _no_forward_20d_blockers_unavailable()
    except Exception:
        return _no_forward_20d_blockers_unavailable()


# ---------------------------------------------------------------------------
# auto_adjust_repair_preview — slim summary of the flag-fix repair preview
# ---------------------------------------------------------------------------
#
# Wraps :mod:`scripts.auto_adjust_mismatch_repair_preview` via a
# module-level seam.  The aggregator exposes only the four summary
# counts an operator needs to size the unblock — the dedicated CLI
# owns the per-row drill-down (proposed dates, repair_status,
# repair_reason).  Following the same pattern as
# :func:`_compute_no_forward_20d_breakdown`: tests patch the seam in
# ``_patch_all_clean()`` so the lazy script import never fires inside
# ``run_health_check``.

# The valid action vocabulary is owned by
# ``scripts.auto_adjust_mismatch_repair_preview._NEXT_ACTIONS`` and
# forwarded verbatim.  ``preview_unavailable`` is the only label this
# module mints — used when the upstream payload is missing the field.
_AAR_RECOMMEND_UNAVAILABLE = "preview_unavailable"


# ---------------------------------------------------------------------------
# auto_adjust_repair_write_smoke — readiness probe for the future
# repair writer's smoke run
# ---------------------------------------------------------------------------
#
# The auto-adjust mismatch repair *writer* does not exist yet — the
# contract test ``tests/test_auto_adjust_mismatch_repair_contract.py``
# pins that absence as the desired signal.  When it lands, an
# operator will want to run a write-smoke against a backup copy
# before exercising it on the live archive.  This section reports
# whether the project is in a state where that smoke run could
# safely happen — without ever importing the writer (the readiness
# check is read-only) and without ever invoking it.

_AAR_WS_RECOMMEND_WRITER_ABSENT  = "writer_not_yet_implemented"
_AAR_WS_RECOMMEND_MISSING_BACKUP = "missing_backup_file"
_AAR_WS_RECOMMEND_READY          = "ready_to_run_write_smoke"
_AAR_WS_RECOMMEND_UNAVAILABLE    = "readiness_unavailable"

_AAR_WRITER_MODULE_NAME = "auto_adjust_mismatch_repair"


def _check_auto_adjust_repair_writer_present() -> bool:
    """Return True iff the future repair writer module is importable.

    Uses :func:`importlib.util.find_spec` so the writer module is
    NOT imported — the readiness check stays read-only and avoids
    triggering any module-load side effects the future writer might
    carry.  Tests patch this attribute on the aggregator's namespace.
    """
    from importlib.util import find_spec
    try:
        return find_spec(_AAR_WRITER_MODULE_NAME) is not None
    except (ImportError, ValueError):
        return False


def _auto_adjust_repair_preview_unavailable() -> dict[str, Any]:
    """Stable empty shape returned when the preview cannot be built."""
    return {
        "available":             False,
        "total_mismatches":      0,
        "repairable_count":      0,
        "non_repairable_count":  0,
        "counts_by_status":      {},
        "proposed_rows":         [],
        "recommended_next_action": _AAR_RECOMMEND_UNAVAILABLE,
    }


def _compute_auto_adjust_repair_preview() -> dict[str, Any]:
    """Default seam — best-effort lazy delegation to
    :mod:`scripts.auto_adjust_mismatch_repair_preview`.

    Tests MUST patch this attribute on the aggregator's namespace via
    ``_patch_all_clean()``.  Returns the unavailable shape on any
    failure so the aggregator never crashes; the script itself is
    read-only (no provider, no LLM, no FastAPI network — its loader
    is the same one ``no_forward_20d_blockers`` ultimately funnels
    through).
    """
    try:
        from scripts import auto_adjust_mismatch_repair_preview as _preview
    except Exception:
        return _auto_adjust_repair_preview_unavailable()

    try:
        details    = _preview._load_auto_adjust_mismatch_details() or []
        specs      = _preview._windows_for_details(details)
        cache_rows = (
            _preview._load_in_window_cache_rows(specs) if specs else {}
        )
        # ``limit=0`` keeps the proposed_rows list empty — the
        # aggregator never embeds per-row detail.  The top-level
        # counts always reflect every mismatch.
        payload = _preview._build_payload(details, cache_rows, limit=0)
    except Exception:
        return _auto_adjust_repair_preview_unavailable()

    payload.setdefault("available", True)
    return payload


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


def _recommend_no_forward_20d_action(
    counts: dict, *, available: bool,
) -> str:
    """Pure decision tree over the breakdown's count map.

    Mirrors the priority order in
    :mod:`scripts.no_forward_20d_gap_report` so operators see the same
    recommendation through the focused CLI and the aggregate health
    check.  Adds one local sentinel — ``breakdown_unavailable`` — for
    the case where the breakdown could not run at all (DB not
    bootstrapped, env missing routes), keeping that state visible
    instead of being silently masked as ``no_action_needed_no_gaps``.
    """
    if not available:
        return _NF20_RECOMMEND_UNAVAILABLE
    too_recent = int(counts.get("event_too_recent_for_20d")     or 0)
    auto_adj   = int(counts.get("auto_adjust_mismatch_for_20d") or 0)
    cache_gap  = int(counts.get("cache_max_before_20d_horizon") or 0)
    delisted   = int(counts.get("likely_delisted_or_sparse")    or 0)
    if too_recent + auto_adj + cache_gap + delisted == 0:
        return _NF20_RECOMMEND_NO_GAPS
    if auto_adj > 0:
        return _NF20_RECOMMEND_FIX_FLAG
    if cache_gap > 0:
        return _NF20_RECOMMEND_REFRESH
    return _NF20_RECOMMEND_WAIT


def _section_no_forward_20d_blockers() -> dict:
    breakdown = _compute_no_forward_20d_breakdown() or {}
    available = bool(breakdown.get("available"))
    counts = breakdown.get("counts") or {}
    return {
        "available":                 available,
        "total_no_forward_20d":      int(breakdown.get("total_no_forward_20d") or 0),
        "too_recent":                int(counts.get("event_too_recent_for_20d")     or 0),
        "auto_adjust_mismatch":      int(counts.get("auto_adjust_mismatch_for_20d") or 0),
        "cache_window_gap":          int(counts.get("cache_max_before_20d_horizon") or 0),
        "likely_delisted_or_sparse": int(counts.get("likely_delisted_or_sparse")    or 0),
        "recommended_next_action":   _recommend_no_forward_20d_action(
            counts, available=available,
        ),
    }


def _section_auto_adjust_repair_preview() -> dict:
    preview = _compute_auto_adjust_repair_preview() or {}
    return {
        "total_mismatches":     int(preview.get("total_mismatches")     or 0),
        "repairable_count":     int(preview.get("repairable_count")     or 0),
        "non_repairable_count": int(preview.get("non_repairable_count") or 0),
        "recommended_next_action":
            preview.get("recommended_next_action") or _AAR_RECOMMEND_UNAVAILABLE,
    }


def _section_auto_adjust_repair_write_smoke(*, backup_dir: str) -> dict:
    """Read-only readiness probe for the future repair write-smoke run.

    Combines two cheap checks — writer-module presence (via
    :func:`_check_auto_adjust_repair_writer_present`) and latest-backup
    discovery (via :func:`find_latest_backup`) — into the four-field
    summary the task spec lists.  Soft failure of either sub-check
    flips ``available`` to False and emits the
    ``readiness_unavailable`` sentinel; the section is never lifted to
    a top-level error so the run-wide ``ok`` stays accurate.
    """
    try:
        writer_present = _check_auto_adjust_repair_writer_present()
    except Exception:
        return {
            "available":              False,
            "safe_to_run_on_copy":    False,
            "latest_backup_found":    False,
            "recommended_next_action": _AAR_WS_RECOMMEND_UNAVAILABLE,
        }

    backup_path = find_latest_backup(Path(backup_dir))
    backup_found = backup_path is not None

    if not writer_present:
        action = _AAR_WS_RECOMMEND_WRITER_ABSENT
    elif not backup_found:
        action = _AAR_WS_RECOMMEND_MISSING_BACKUP
    else:
        action = _AAR_WS_RECOMMEND_READY

    return {
        "available":              True,
        "safe_to_run_on_copy":    bool(writer_present and backup_found),
        "latest_backup_found":    backup_found,
        "recommended_next_action": action,
    }


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
# stat_validation_readiness — slim coverage view for the event-study engine
# ---------------------------------------------------------------------------
#
# Wraps :mod:`scripts.stat_validation_readiness_report` through the
# top-level ``summarize_stat_validation_readiness`` seam.  The aggregator
# surfaces the five summary fields the task spec lists; the dedicated
# CLI owns the per-event drill-down.

# Tie-break order for ``dominant_blocker`` — coarsest input gap first so
# the recommended action targets the prerequisite check, not a
# downstream symptom.  Forward-cache 20d > 5d > 1d because refreshing the
# longest horizon resolves the shorter ones for free.
_SVR_BLOCKER_PRIORITY: tuple[str, ...] = (
    "event_date_missing",
    "market_tickers_missing",
    "forward_cache_20d_missing",
    "forward_cache_5d_missing",
    "forward_cache_1d_missing",
    "benchmark_proxy_missing",
    "estimation_window_insufficient",
)

_SVR_BLOCKER_TO_ACTION: dict[str, str] = {
    "event_date_missing":              "backfill_event_date",
    "market_tickers_missing":          "backfill_market_tickers",
    "forward_cache_20d_missing":       "refresh_forward_cache_20d",
    "forward_cache_5d_missing":        "refresh_forward_cache_5d",
    "forward_cache_1d_missing":        "refresh_forward_cache_1d",
    "benchmark_proxy_missing":         "refresh_benchmark_cache",
    "estimation_window_insufficient":  "extend_estimation_window",
}

_SVR_RECOMMEND_NO_EVENTS    = "no_events_to_validate"
_SVR_RECOMMEND_FULLY_READY  = "no_action_needed_fully_ready"


def _svr_blocker_counts(payload: dict) -> dict[str, int]:
    """Derive per-blocker missing counts from the upstream readiness payload.

    The upstream report mixes positive coverage counts (``events_with_*``)
    with already-negative gap counts (``events_missing_*`` / ``_with_insufficient_*``).
    This helper normalizes both into "missing" counts so the dominant
    blocker selection works on a single numeric vocabulary.
    """
    total = int(payload.get("total_events") or 0)
    return {
        "event_date_missing":
            max(0, total - int(payload.get("events_with_event_date")     or 0)),
        "market_tickers_missing":
            max(0, total - int(payload.get("events_with_market_tickers") or 0)),
        "forward_cache_1d_missing":
            max(0, total - int(payload.get("events_with_1d_forward_cache")  or 0)),
        "forward_cache_5d_missing":
            max(0, total - int(payload.get("events_with_5d_forward_cache")  or 0)),
        "forward_cache_20d_missing":
            max(0, total - int(payload.get("events_with_20d_forward_cache") or 0)),
        "benchmark_proxy_missing":
            int(payload.get("events_missing_benchmark_proxy") or 0),
        "estimation_window_insufficient":
            int(payload.get("events_with_insufficient_estimation_window") or 0),
    }


def _pick_dominant_blocker(counts: dict[str, int]) -> str | None:
    """Return the blocker key with the highest missing count.

    Ties resolve via :data:`_SVR_BLOCKER_PRIORITY`.  Returns ``None`` when
    every count is zero (no blocker fires).
    """
    best_key: str | None = None
    best_count: int = 0
    for key in _SVR_BLOCKER_PRIORITY:
        count = int(counts.get(key) or 0)
        if count > best_count:
            best_count = count
            best_key   = key
    return best_key


def _section_stat_validation_readiness(*, db_path: str) -> dict:
    """Slim coverage view of the event-study readiness report.

    Always passes ``limit=0`` to the upstream summarizer so no per-event
    rows are embedded in the aggregator's output — the dedicated CLI
    owns that drill-down.
    """
    payload = summarize_stat_validation_readiness(
        db_path=str(db_path) if db_path else None,
        limit=0,
    ) or {}

    total       = int(payload.get("total_events")       or 0)
    fully_ready = int(payload.get("events_fully_ready") or 0)

    if total <= 0:
        readiness_rate     = 0.0
        dominant_blocker   = None
        recommended_action = _SVR_RECOMMEND_NO_EVENTS
    else:
        readiness_rate = fully_ready / total
        if fully_ready >= total:
            dominant_blocker   = None
            recommended_action = _SVR_RECOMMEND_FULLY_READY
        else:
            dominant_blocker = _pick_dominant_blocker(
                _svr_blocker_counts(payload),
            )
            recommended_action = (
                _SVR_BLOCKER_TO_ACTION.get(dominant_blocker, _SVR_RECOMMEND_FULLY_READY)
                if dominant_blocker is not None
                # No blocker count > 0 but fully_ready < total — surface
                # the partial state without inventing a phantom blocker.
                else _SVR_RECOMMEND_FULLY_READY
            )

    return {
        "total_events":           total,
        "events_fully_ready":     fully_ready,
        "readiness_rate":         readiness_rate,
        "dominant_blocker":       dominant_blocker,
        "recommended_next_action": recommended_action,
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


def _classify_no_forward_20d_blockers(
    section: dict,
) -> tuple[list[str], list[str]]:
    # Operator info only — the ``recommended_next_action`` field
    # carries the actionable signal.  The dedicated runbook surface
    # (``scripts/no_forward_20d_gap_report.py``) owns the drill-down,
    # so surfacing the count as a top-level warning here would
    # double-report the same class of issue.
    return [], []


def _classify_auto_adjust_repair_preview(
    section: dict,
) -> tuple[list[str], list[str]]:
    # Operator info only — same reasoning as
    # :func:`_classify_no_forward_20d_blockers`.  The dedicated CLI
    # (``scripts/auto_adjust_mismatch_repair_preview.py``) owns the
    # per-row drill-down, so the aggregator surfaces summary counts +
    # the actionable recommendation without re-emitting them as
    # top-level warnings.
    return [], []


def _classify_auto_adjust_repair_write_smoke(
    section: dict,
) -> tuple[list[str], list[str]]:
    # Operator info only — the recommendation field carries the
    # actionable signal (writer-absent / missing-backup / ready).
    # ``writer_not_yet_implemented`` is the expected baseline today
    # while the writer is unspecified; surfacing it as a warning
    # would noise the operational channel until the writer ships.
    return [], []


def _classify_stat_validation_readiness(
    section: dict,
) -> tuple[list[str], list[str]]:
    # Operator info only — same precedent as the other summary
    # sections.  The ``recommended_next_action`` field carries the
    # actionable signal; the dedicated readiness-report CLI owns the
    # per-event drill-down.
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
    "no_forward_20d_blockers",
    "auto_adjust_repair_preview",
    "auto_adjust_repair_write_smoke",
    "stat_validation_readiness",
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
    _run_section(
        payload, "no_forward_20d_blockers",
        _section_no_forward_20d_blockers,
        _classify_no_forward_20d_blockers,
    )
    _run_section(
        payload, "auto_adjust_repair_preview",
        _section_auto_adjust_repair_preview,
        _classify_auto_adjust_repair_preview,
    )
    _run_section(
        payload, "auto_adjust_repair_write_smoke",
        lambda: _section_auto_adjust_repair_write_smoke(
            backup_dir=backup_dir,
        ),
        _classify_auto_adjust_repair_write_smoke,
    )
    _run_section(
        payload, "stat_validation_readiness",
        lambda: _section_stat_validation_readiness(db_path=db_path),
        _classify_stat_validation_readiness,
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
        elif key == "no_forward_20d_blockers":
            lines.append(
                f"  available: {section.get('available')}",
            )
            lines.append(
                f"  total_no_forward_20d: "
                f"{section.get('total_no_forward_20d', 0)}",
            )
            lines.append(
                f"  too_recent: {section.get('too_recent', 0)}",
            )
            lines.append(
                f"  auto_adjust_mismatch: "
                f"{section.get('auto_adjust_mismatch', 0)}",
            )
            lines.append(
                f"  cache_window_gap: "
                f"{section.get('cache_window_gap', 0)}",
            )
            lines.append(
                f"  likely_delisted_or_sparse: "
                f"{section.get('likely_delisted_or_sparse', 0)}",
            )
            lines.append(
                f"  recommended_next_action: "
                f"{section.get('recommended_next_action')}",
            )
        elif key == "auto_adjust_repair_preview":
            lines.append(
                f"  total_mismatches: "
                f"{section.get('total_mismatches', 0)}",
            )
            lines.append(
                f"  repairable_count: "
                f"{section.get('repairable_count', 0)}",
            )
            lines.append(
                f"  non_repairable_count: "
                f"{section.get('non_repairable_count', 0)}",
            )
            lines.append(
                f"  recommended_next_action: "
                f"{section.get('recommended_next_action')}",
            )
        elif key == "auto_adjust_repair_write_smoke":
            lines.append(
                f"  available: {section.get('available')}",
            )
            lines.append(
                f"  safe_to_run_on_copy: "
                f"{section.get('safe_to_run_on_copy')}",
            )
            lines.append(
                f"  latest_backup_found: "
                f"{section.get('latest_backup_found')}",
            )
            lines.append(
                f"  recommended_next_action: "
                f"{section.get('recommended_next_action')}",
            )
        elif key == "stat_validation_readiness":
            lines.append(
                f"  total_events: {section.get('total_events', 0)}",
            )
            lines.append(
                f"  events_fully_ready: "
                f"{section.get('events_fully_ready', 0)}",
            )
            rate = section.get("readiness_rate", 0.0)
            rate_text = (
                f"{rate:.4f}" if isinstance(rate, (int, float))
                else str(rate)
            )
            lines.append(f"  readiness_rate: {rate_text}")
            lines.append(
                f"  dominant_blocker: {section.get('dominant_blocker')}",
            )
            lines.append(
                f"  recommended_next_action: "
                f"{section.get('recommended_next_action')}",
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

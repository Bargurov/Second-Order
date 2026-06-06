#!/usr/bin/env python3
"""No-paid local demo smoke check.

Runs the demo-critical zero-cost endpoints that should work without
LLM, yfinance, market-data provider, or paid backfill calls.  Default
mode uses FastAPI's in-process TestClient and guards known paid/provider
seams with raisers so regressions fail loudly.  ``--base-url`` can probe
a running local server, but in-process mode is the strongest no-paid
guard because it can monkey-patch the Python seams.

Usage:
    python scripts/no_paid_smoke.py
    python scripts/no_paid_smoke.py --json
    python scripts/no_paid_smoke.py --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BodyInvariant = Callable[[Any], None]


def _assert_auto_backfill_status_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the auto-backfill-status response.

    The diagnostics surface must report a not-wired skeleton in the
    no-paid demo: ``scheduler.scheduler_started`` must be false (no
    background scheduler running) and ``ledger.used`` must be zero (no
    paid call has been reserved).  A regression on either field means
    paid execution or background scheduling slipped in — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"auto-backfill-status response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    scheduler = body.get("scheduler") or {}
    started = scheduler.get("scheduler_started")
    if started is not False:
        raise AssertionError(
            f"scheduler.scheduler_started must be false in no-paid mode, "
            f"got {started!r}"
        )
    ledger = body.get("ledger") or {}
    used = ledger.get("used")
    if used != 0:
        raise AssertionError(
            f"ledger.used must be 0 in no-paid mode, got {used!r}"
        )


_ARCHIVE_CONSISTENCY_CATEGORIES: tuple[str, ...] = (
    "malformed_market_tickers_json",
    "missing_headline",
    "missing_timestamp",
    "missing_event_date",
    "malformed_event_date",
    "missing_market_tickers",
    "duplicate_headline_event_date_clusters",
)


def _assert_archive_consistency_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the archive-consistency response.

    The diagnostic must surface every known anomaly category and each
    block must carry the ``{"count": int, "examples": list}`` contract
    the runbook reads against.  Stable zero values are accepted because
    a clean archive has no anomalies.  A regression that drops a
    category, returns a negative count, or swaps the example list for a
    non-list shape means the read-only audit contract changed — fail
    closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"archive-consistency response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    for category in _ARCHIVE_CONSISTENCY_CATEGORIES:
        block = body.get(category)
        if not isinstance(block, dict):
            raise AssertionError(
                f"archive-consistency block {category!r} must be a JSON "
                f"object with count/examples, got {type(block).__name__}"
            )
        count = block.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AssertionError(
                f"archive-consistency block {category!r}.count must be a "
                f"non-negative int, got {count!r}"
            )
        examples = block.get("examples")
        if not isinstance(examples, list):
            raise AssertionError(
                f"archive-consistency block {category!r}.examples must be "
                f"a list, got {type(examples).__name__}"
            )


def _assert_event_date_backfill_impact_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the event-date backfill impact preview.

    The impact projection must surface ``candidate_events``,
    ``proposed_updates`` and ``projected_no_event_date_after`` as
    non-negative ints so the runbook's projection math stays meaningful.
    Stable zero values are accepted because an archive with no
    candidates projects zeros across the board.  A regression that
    drops a field, returns a negative count, or swaps shapes means the
    impact-projection contract changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"event-date-backfill-impact-preview response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    for field_name in (
        "candidate_events",
        "proposed_updates",
        "projected_no_event_date_after",
    ):
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )


def _assert_event_date_backfill_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the event-date backfill candidates response.

    The dry-run diagnostic must surface a structural shape the smoke can
    rely on regardless of archive state: a non-negative
    ``total_events_missing_event_date`` candidate count and an
    ``examples`` list of proposed updates.  Stable zero values are
    accepted because a clean archive has no missing event_dates.  A
    regression that drops either field, returns negative counts, or
    swaps the proposals for a non-list shape means the dry-run output
    contract changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"event-date-backfill response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    total = body.get("total_events_missing_event_date")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise AssertionError(
            f"total_events_missing_event_date must be a non-negative int, "
            f"got {total!r}"
        )
    examples = body.get("examples")
    if not isinstance(examples, list):
        raise AssertionError(
            f"examples must be a list of proposed updates, "
            f"got {type(examples).__name__}"
        )


_NO_FORWARD_20D_GAP_REPORT_REQUIRED_INTS: tuple[str, ...] = (
    "total_no_forward_20d",
    "too_recent",
    "auto_adjust_mismatch",
    "cache_window_gap",
    "likely_delisted_or_sparse",
)


_NO_FORWARD_20D_GAP_REPORT_REQUIRED_LISTS: tuple[str, ...] = (
    "refreshable_gap_examples",
    "non_refreshable_examples",
    "auto_adjust_mismatch_details",
)


_NO_FORWARD_20D_GAP_REPORT_NEXT_ACTIONS: tuple[str, ...] = (
    "no_action_needed_no_gaps",
    "fix_auto_adjust_flag_mismatch",
    "run_targeted_refresh_for_cache_window_gap",
    "wait_or_accept_no_refreshable_gaps",
)


def _assert_no_forward_20d_gap_report_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the gap-report CLI's JSON output.

    Each count must be a non-negative int (so the runbook math reads
    correctly), each example partition must be a list (so the renderer
    can iterate without crashing), and ``recommended_next_action`` must
    come from the script's fixed vocabulary (so a runbook consumer can
    branch deterministically on the value).  Stable zero values are
    accepted because a clean archive has no gaps.  A regression that
    drops a field, returns negatives, or invents a new recommendation
    means the read-only report contract changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"no-forward-20d gap-report response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    for field_name in _NO_FORWARD_20D_GAP_REPORT_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    for list_name in _NO_FORWARD_20D_GAP_REPORT_REQUIRED_LISTS:
        value = body.get(list_name)
        if not isinstance(value, list):
            raise AssertionError(
                f"{list_name} must be a list, got "
                f"{type(value).__name__}"
            )
    action = body.get("recommended_next_action")
    if action not in _NO_FORWARD_20D_GAP_REPORT_NEXT_ACTIONS:
        raise AssertionError(
            f"recommended_next_action must be one of "
            f"{list(_NO_FORWARD_20D_GAP_REPORT_NEXT_ACTIONS)}, "
            f"got {action!r}"
        )


_NO_FORWARD_20D_REFRESHABILITY_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_date",
    "symbol",
    "diagnostic_reason",
    "cache_max_date",
    "horizon_20d_date",
    "gap_days",
    "source",
)


def _assert_no_forward_20d_refreshability_export_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the refreshability-export CLI envelope.

    The export contract is ``{ok=True, count: non-negative int,
    fields: pinned 8-tuple, rows: list}``.  Stable zero values are
    accepted because a clean archive has no refreshable rows.  A
    regression that flips ``ok`` to false, returns a negative count, or
    diverges from the pinned ``fields`` shape means the export's CSV /
    JSON contract changed — fail closed before a downstream consumer
    sees the mismatched shape.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"no-forward-20d refreshability-export response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    if body.get("ok") is not True:
        raise AssertionError(
            f"ok must be True in no-paid mode, got {body.get('ok')!r}"
        )
    count = body.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise AssertionError(
            f"count must be a non-negative int, got {count!r}"
        )
    fields = body.get("fields")
    if not isinstance(fields, list):
        raise AssertionError(
            f"fields must be a list, got {type(fields).__name__}"
        )
    if tuple(fields) != _NO_FORWARD_20D_REFRESHABILITY_FIELDS:
        raise AssertionError(
            f"fields must equal the pinned export shape "
            f"{list(_NO_FORWARD_20D_REFRESHABILITY_FIELDS)}, "
            f"got {fields!r}"
        )
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise AssertionError(
            f"rows must be a list, got {type(rows).__name__}"
        )


_AUTO_ADJUST_PREVIEW_REQUIRED_INTS: tuple[str, ...] = (
    "total_mismatches",
    "repairable_count",
    "non_repairable_count",
)


_AUTO_ADJUST_PREVIEW_NEXT_ACTIONS: tuple[str, ...] = (
    "no_action_needed_no_mismatches",
    "fix_auto_adjust_flag_mismatch",
    "investigate_non_repairable_rows",
)


def _assert_auto_adjust_mismatch_repair_preview_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the auto-adjust mismatch repair preview
    CLI's JSON output.

    Each count must be a non-negative int (so the runbook math reads
    correctly), ``counts_by_status`` must be a dict (so the renderer can
    iterate by status), ``proposed_rows`` must be a list (so the
    renderer can iterate without crashing), and ``recommended_next_action``
    must come from the script's fixed vocabulary (so a runbook consumer
    can branch deterministically on the value).  Stable zero values are
    accepted because a clean archive has no mismatches.  A regression
    that drops a field, returns negatives, or invents a new
    recommendation means the read-only preview contract changed — fail
    closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"auto-adjust mismatch repair preview response must be a "
            f"JSON object, got {type(body).__name__}"
        )
    for field_name in _AUTO_ADJUST_PREVIEW_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    counts_by_status = body.get("counts_by_status")
    if not isinstance(counts_by_status, dict):
        raise AssertionError(
            f"counts_by_status must be a dict, got "
            f"{type(counts_by_status).__name__}"
        )
    proposed_rows = body.get("proposed_rows")
    if not isinstance(proposed_rows, list):
        raise AssertionError(
            f"proposed_rows must be a list, got "
            f"{type(proposed_rows).__name__}"
        )
    action = body.get("recommended_next_action")
    if action not in _AUTO_ADJUST_PREVIEW_NEXT_ACTIONS:
        raise AssertionError(
            f"recommended_next_action must be one of "
            f"{list(_AUTO_ADJUST_PREVIEW_NEXT_ACTIONS)}, "
            f"got {action!r}"
        )
    # Partition contract: every mismatch row falls into exactly one of
    # the repairable / non-repairable buckets.  The preview enforces
    # this by construction, but pinning it in the smoke means a future
    # accounting drift trips here instead of leaking into downstream
    # math.  All three counts have already been validated as
    # non-negative ints above.
    total          = body["total_mismatches"]
    repairable     = body["repairable_count"]
    non_repairable = body["non_repairable_count"]
    if repairable + non_repairable != total:
        raise AssertionError(
            f"repairable_count + non_repairable_count must sum to "
            f"total_mismatches; got {repairable} + {non_repairable} != "
            f"{total}"
        )


_STAT_VALIDATION_SMOKE_REQUIRED_INTS: tuple[str, ...] = (
    "records_count",
    "significant_count",
)


_STAT_VALIDATION_RECORD_REQUIRED_KEYS: tuple[str, ...] = (
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "statistically_significant",
    "interpretation",
)


def _assert_stat_validation_smoke_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the stat-validation smoke CLI's JSON output.

    The smoke runs the deterministic event_study → bootstrap_ci →
    p-value → FDR → stat_validation pipeline over synthetic data, so its
    output is stable: ``ok`` is True, ``errors`` is empty, every count is
    a non-negative int, ``records_count`` matches ``len(records)``,
    ``significant_count <= records_count``, and every record carries the
    canonical nine-field stat_validation schema.  A regression that
    flips any of those means the pure-pipeline contract drifted — fail
    closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"stat-validation smoke response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    if body.get("ok") is not True:
        raise AssertionError(
            f"ok must be True for the deterministic stat-validation "
            f"smoke, got {body.get('ok')!r}"
        )
    config = body.get("config")
    if not isinstance(config, dict):
        raise AssertionError(
            f"config must be a JSON object, got {type(config).__name__}"
        )
    errors = body.get("errors")
    if not isinstance(errors, list):
        raise AssertionError(
            f"errors must be a list, got {type(errors).__name__}"
        )
    if errors:
        # The smoke's deterministic synthetic path produces no errors.
        # A non-empty errors list signals the pipeline regressed —
        # surface every entry so the diagnostic is self-explanatory.
        raise AssertionError(
            f"errors must be empty in no-paid mode, got {errors!r}"
        )
    for field_name in _STAT_VALIDATION_SMOKE_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    records = body.get("records")
    if not isinstance(records, list):
        raise AssertionError(
            f"records must be a list, got {type(records).__name__}"
        )
    if len(records) != body["records_count"]:
        raise AssertionError(
            f"records_count must equal len(records); got "
            f"records_count={body['records_count']} vs "
            f"len(records)={len(records)}"
        )
    if body["significant_count"] > body["records_count"]:
        raise AssertionError(
            f"significant_count must not exceed records_count; got "
            f"{body['significant_count']} > {body['records_count']}"
        )
    for index, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise AssertionError(
                f"records[{index}] must be a JSON object, "
                f"got {type(rec).__name__}"
            )
        for key in _STAT_VALIDATION_RECORD_REQUIRED_KEYS:
            if key not in rec:
                raise AssertionError(
                    f"records[{index}] is missing required key {key!r}"
                )


_STAT_VALIDATION_READINESS_REQUIRED_INTS: tuple[str, ...] = (
    "total_events",
    "events_with_event_date",
    "events_with_market_tickers",
    "events_with_event_date_and_tickers",
    "events_with_1d_forward_cache",
    "events_with_5d_forward_cache",
    "events_with_20d_forward_cache",
    "events_missing_benchmark_proxy",
    "events_with_insufficient_estimation_window",
    "events_fully_ready",
)


# The readiness report emits one of two prose sentences as its
# ``recommended_next_action`` — pinning the closed set means a future
# rephrase trips here so the runbook keeps its branch on the value.
_STAT_VALIDATION_READINESS_NEXT_ACTIONS: tuple[str, ...] = (
    (
        "Every event in the archive has the cache coverage needed to run "
        "the event-study engine over 1d/5d/20d horizons."
    ),
    (
        "Some events lack the cache coverage needed for the event-study "
        "engine.  Refresh the price cache for the listed primary tickers "
        "and SPY benchmark, then re-run this report."
    ),
)


def _assert_stat_validation_readiness_report_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the stat-validation readiness report
    CLI's JSON output.

    Every coverage count must be a non-negative int (so the runbook math
    reads correctly), ``events`` must be a list (so the renderer can
    iterate without crashing), and ``recommended_next_action`` must come
    from the report's two-prose-sentence vocabulary (so a runbook
    consumer can branch deterministically on the value).  Stable zero
    values are accepted because an archive without coverage produces
    zeros.  A regression that drops a field, returns negatives, or
    invents a new recommendation means the read-only report contract
    changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"stat-validation readiness response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    for field_name in _STAT_VALIDATION_READINESS_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    events = body.get("events")
    if not isinstance(events, list):
        raise AssertionError(
            f"events must be a list, got {type(events).__name__}"
        )
    action = body.get("recommended_next_action")
    if action not in _STAT_VALIDATION_READINESS_NEXT_ACTIONS:
        raise AssertionError(
            f"recommended_next_action must be one of the two pinned "
            f"prose sentences, got {action!r}"
        )
    # Cohort partition: fully_ready is a subset of total_events, so
    # the count must never exceed it.  Production code enforces this
    # via the per-event counter; the smoke pins it so a future
    # accounting drift trips here.
    if body["events_fully_ready"] > body["total_events"]:
        raise AssertionError(
            f"events_fully_ready must not exceed total_events; got "
            f"{body['events_fully_ready']} > {body['total_events']}"
        )


_ARCHIVE_CLEANUP_EXECUTION_PLAN_BATCH_REASONS: frozenset[str] = frozenset((
    "test_fixture_phrase",
    "rotating_macro_template",
    "fixture_timestamp_cluster",
    "duplicate_headline_event_date",
))


# Pinned in the source as ``_REQUIRED_CONFIRMATION_FLAGS`` —
# the operator runbook reads this exact ordered tuple, so a future
# rename / reorder must trip the smoke instead of silently breaking
# downstream consumers.
_ARCHIVE_CLEANUP_REQUIRED_CONFIRMATION_FLAGS: tuple[str, ...] = (
    "backup_taken",
    "per_event_manual_review_complete",
    "acknowledged_no_db_writes_from_this_script",
)


# Closed two-string vocabulary for ``recommended_next_action`` on the
# execution-plan report.  The "plan ready" string explicitly disclaims
# writes so an operator cannot mistake the report for a deletion tool;
# pinning both strings means a future rephrase trips here.
_ARCHIVE_CLEANUP_EXECUTION_PLAN_NEXT_ACTIONS: tuple[str, ...] = (
    "No archive cleanup candidates detected; no execution plan "
    "required.",
    "Execution plan ready.  Take a fresh backup, review every event "
    "in every batch, then delete via the operator path.  This script "
    "makes no DB writes.",
)


def _assert_archive_cleanup_execution_plan_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the archive cleanup execution-plan
    CLI's JSON output.

    The plan is a read-only batched view of cleanup candidates that an
    operator drives manually.  The smoke pins the load-bearing shape:
    ``candidate_count`` is a non-negative int, ``batches`` is a list of
    ``{reason, size, event_ids, examples, manual_review_required_before_delete,
    description}`` rows whose ``size`` equals ``len(event_ids)``,
    ``risk_notes`` is a non-empty list of non-empty strings,
    ``required_confirmation_flags`` matches the pinned three-flag
    tuple, and ``recommended_next_action`` comes from the script's
    closed two-string vocabulary.  Stable zero values are accepted
    because a clean archive emits an empty ``batches`` list and the
    "no candidates" recommendation.  A regression that drops a field,
    silently auto-deletes (``manual_review_required_before_delete=False``),
    invents a new reason, or reorders the confirmation flags means the
    read-only contract changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"archive cleanup execution-plan response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    candidate_count = body.get("candidate_count")
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 0
    ):
        raise AssertionError(
            f"candidate_count must be a non-negative int, got "
            f"{candidate_count!r}"
        )
    batches = body.get("batches")
    if not isinstance(batches, list):
        raise AssertionError(
            f"batches must be a list, got {type(batches).__name__}"
        )
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict):
            raise AssertionError(
                f"batches[{index}] must be a JSON object, got "
                f"{type(batch).__name__}"
            )
        reason = batch.get("reason")
        if reason not in _ARCHIVE_CLEANUP_EXECUTION_PLAN_BATCH_REASONS:
            raise AssertionError(
                f"batches[{index}].reason must be one of "
                f"{sorted(_ARCHIVE_CLEANUP_EXECUTION_PLAN_BATCH_REASONS)}, "
                f"got {reason!r}"
            )
        size = batch.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise AssertionError(
                f"batches[{index}].size must be a non-negative int, got "
                f"{size!r}"
            )
        event_ids = batch.get("event_ids")
        if not isinstance(event_ids, list):
            raise AssertionError(
                f"batches[{index}].event_ids must be a list, got "
                f"{type(event_ids).__name__}"
            )
        if len(event_ids) != size:
            raise AssertionError(
                f"batches[{index}].size must equal len(event_ids); "
                f"got size={size} vs len(event_ids)={len(event_ids)}"
            )
        examples = batch.get("examples")
        if not isinstance(examples, list):
            raise AssertionError(
                f"batches[{index}].examples must be a list, got "
                f"{type(examples).__name__}"
            )
        if batch.get("manual_review_required_before_delete") is not True:
            raise AssertionError(
                f"batches[{index}].manual_review_required_before_delete "
                f"must be True, got "
                f"{batch.get('manual_review_required_before_delete')!r}"
            )
        description = batch.get("description")
        if not isinstance(description, str) or not description:
            raise AssertionError(
                f"batches[{index}].description must be a non-empty "
                f"string, got {description!r}"
            )
    risk_notes = body.get("risk_notes")
    if not isinstance(risk_notes, list) or not risk_notes:
        raise AssertionError(
            f"risk_notes must be a non-empty list, got {risk_notes!r}"
        )
    for index, note in enumerate(risk_notes):
        if not isinstance(note, str) or not note:
            raise AssertionError(
                f"risk_notes[{index}] must be a non-empty string, got "
                f"{note!r}"
            )
    flags = body.get("required_confirmation_flags")
    if not isinstance(flags, list):
        raise AssertionError(
            f"required_confirmation_flags must be a list, got "
            f"{type(flags).__name__}"
        )
    if tuple(flags) != _ARCHIVE_CLEANUP_REQUIRED_CONFIRMATION_FLAGS:
        raise AssertionError(
            f"required_confirmation_flags must equal the pinned tuple "
            f"{list(_ARCHIVE_CLEANUP_REQUIRED_CONFIRMATION_FLAGS)}, got "
            f"{flags!r}"
        )
    action = body.get("recommended_next_action")
    if action not in _ARCHIVE_CLEANUP_EXECUTION_PLAN_NEXT_ACTIONS:
        raise AssertionError(
            f"recommended_next_action must be one of the two pinned "
            f"strings, got {action!r}"
        )


_ARCHIVE_CLEANUP_TICKER_READINESS_REQUIRED_INTS: tuple[str, ...] = (
    "candidate_count",
    "tickers_present_count",
    "price_cache_present_count",
    "low_information_count",
)


# Closed two-string vocabulary for ``recommended_next_action`` on the
# ticker-readiness report.  Both strings explicitly disclaim writes so
# an operator cannot mistake the report for a deletion tool.
_ARCHIVE_CLEANUP_TICKER_READINESS_NEXT_ACTIONS: tuple[str, ...] = (
    "No archive cleanup candidates detected; no ticker-readiness "
    "review required.",
    "Cleanup candidates detected.  Review per-event ticker / "
    "price_cache / low_information columns to decide whether deletion "
    "via the operator path is safe; this report makes no DB writes.",
)


def _assert_archive_cleanup_ticker_readiness_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the archive cleanup ticker-readiness
    CLI's JSON output.

    The report summarises, per cleanup candidate, whether market_tickers
    is populated, whether the primary ticker is covered by
    ``price_cache``, and whether the row is flagged ``low_signal``.
    Every count must be a non-negative int (so the runbook math reads
    correctly), ``examples`` must be a list (so the renderer can
    iterate without crashing), ``recommended_next_action`` must come
    from the script's closed two-string vocabulary (so a runbook
    consumer can branch deterministically on the value), each subset
    count must not exceed ``candidate_count`` (the partition floor),
    and ``price_cache_present_count`` must not exceed
    ``tickers_present_count`` because price-cache coverage requires a
    primary ticker.  Stable zero values are accepted because a clean
    archive has no candidates.  A regression that drops a field,
    returns negatives, or invents a new recommendation means the
    read-only report contract changed — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"archive cleanup ticker-readiness response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    for field_name in _ARCHIVE_CLEANUP_TICKER_READINESS_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    examples = body.get("examples")
    if not isinstance(examples, list):
        raise AssertionError(
            f"examples must be a list, got {type(examples).__name__}"
        )
    action = body.get("recommended_next_action")
    if action not in _ARCHIVE_CLEANUP_TICKER_READINESS_NEXT_ACTIONS:
        raise AssertionError(
            f"recommended_next_action must be one of the two pinned "
            f"strings, got {action!r}"
        )
    # Partition floor: every subset count is at most the candidate
    # cohort.  The script enforces this by construction (one walk over
    # the candidate id list); pinning it here means a future
    # accounting drift trips the smoke.
    candidate_count = body["candidate_count"]
    for subset in (
        "tickers_present_count",
        "price_cache_present_count",
        "low_information_count",
    ):
        if body[subset] > candidate_count:
            raise AssertionError(
                f"{subset} must not exceed candidate_count; got "
                f"{body[subset]} > {candidate_count}"
            )
    # Price-cache coverage requires a primary ticker, so the
    # price_cache subset is itself bounded by the tickers subset.  A
    # regression that decouples the two would return shapes the
    # runbook math cannot reconcile.
    if body["price_cache_present_count"] > body["tickers_present_count"]:
        raise AssertionError(
            f"price_cache_present_count must not exceed "
            f"tickers_present_count; got "
            f"{body['price_cache_present_count']} > "
            f"{body['tickers_present_count']}"
        )


_SHORT_HORIZON_READINESS_REQUIRED_INTS: tuple[str, ...] = (
    "total_events",
    "events_ready_1d5d",
    "delta_vs_full_ready",
    "missing_tickers_count",
    "missing_benchmark_count",
    "insufficient_estimation_window_count",
)


def _assert_short_horizon_readiness_report_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the short-horizon (1d/5d) readiness
    report CLI's JSON output.

    Every coverage count must be a non-negative int, ``examples`` must
    be a list, and ``events_ready_1d5d`` must not exceed
    ``total_events``.  Stable zero values are accepted because an
    archive with no qualifying events surfaces zeros across the board.
    A regression that drops a field, returns negatives, or surfaces a
    cohort larger than the archive means the read-only report contract
    drifted — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"short-horizon readiness response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    for field_name in _SHORT_HORIZON_READINESS_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    examples = body.get("examples")
    if not isinstance(examples, list):
        raise AssertionError(
            f"examples must be a list, got {type(examples).__name__}"
        )
    action = body.get("recommended_next_action")
    if not isinstance(action, str) or not action:
        raise AssertionError(
            f"recommended_next_action must be a non-empty string, got "
            f"{action!r}"
        )
    if body["events_ready_1d5d"] > body["total_events"]:
        raise AssertionError(
            f"events_ready_1d5d must not exceed total_events; got "
            f"{body['events_ready_1d5d']} > {body['total_events']}"
        )
    # ``delta_vs_full_ready`` is a subset of ``events_ready_1d5d``
    # (events that pass the short predicate but fail the full one),
    # so the partition floor is bounded by the short-ready cohort.
    if body["delta_vs_full_ready"] > body["events_ready_1d5d"]:
        raise AssertionError(
            f"delta_vs_full_ready must not exceed events_ready_1d5d; "
            f"got {body['delta_vs_full_ready']} > "
            f"{body['events_ready_1d5d']}"
        )


_SHORT_HORIZON_CONTAMINATION_REQUIRED_INTS: tuple[str, ...] = (
    "total_short_ready",
    "suspicious_count",
    "clean_short_ready_count",
)


_SHORT_HORIZON_CONTAMINATION_FLAG_KEYS: tuple[str, ...] = (
    "driv_lit_off_topic",
    "mechanism_family_none",
    "duplicate_date_ticker",
    "local_off_topic_headline",
)


def _assert_short_horizon_contamination_report_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the short-horizon (1d/5d) contamination
    report CLI's JSON output.

    The report flags the four heuristic problems the fully-ready
    contamination report surfaces, but on the short-horizon-ready
    cohort.  ``ok`` must be True (the report runs read-only and never
    returns an error envelope), every count must be a non-negative
    int, ``by_flag`` must carry the four pinned flag buckets,
    ``examples`` must be a list, and the partition arithmetic
    ``suspicious_count + clean_short_ready_count == total_short_ready``
    must hold.  A regression that drops a field, returns negatives,
    invents a new flag bucket, or breaks the partition arithmetic
    means the read-only report contract drifted — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"short-horizon contamination response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    if body.get("ok") is not True:
        raise AssertionError(
            f"ok must be True for the read-only short-horizon "
            f"contamination report, got {body.get('ok')!r}"
        )
    for field_name in _SHORT_HORIZON_CONTAMINATION_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    by_flag = body.get("by_flag")
    if not isinstance(by_flag, dict):
        raise AssertionError(
            f"by_flag must be a dict, got {type(by_flag).__name__}"
        )
    for flag in _SHORT_HORIZON_CONTAMINATION_FLAG_KEYS:
        flag_value = by_flag.get(flag)
        if (
            not isinstance(flag_value, int)
            or isinstance(flag_value, bool)
            or flag_value < 0
        ):
            raise AssertionError(
                f"by_flag[{flag!r}] must be a non-negative int, got "
                f"{flag_value!r}"
            )
    examples = body.get("examples")
    if not isinstance(examples, list):
        raise AssertionError(
            f"examples must be a list, got {type(examples).__name__}"
        )
    action = body.get("recommended_next_action")
    if not isinstance(action, str) or not action:
        raise AssertionError(
            f"recommended_next_action must be a non-empty string, got "
            f"{action!r}"
        )
    # Partition arithmetic: every short-ready event is either
    # suspicious or clean, never both.  The script enforces this by
    # construction; pinning it here means a future accounting drift
    # trips the smoke instead of leaking into downstream math.
    if (
        body["suspicious_count"] + body["clean_short_ready_count"]
        != body["total_short_ready"]
    ):
        raise AssertionError(
            f"suspicious_count + clean_short_ready_count must equal "
            f"total_short_ready; got "
            f"{body['suspicious_count']} + "
            f"{body['clean_short_ready_count']} != "
            f"{body['total_short_ready']}"
        )


_ARCHIVE_STAT_VALIDATION_RUN_REQUIRED_INTS: tuple[str, ...] = (
    "events_evaluated",
    "records_count",
    "significant_count",
)


def _assert_archive_short_horizon_run_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the archive short-horizon validation
    run CLI's JSON output.

    The runner walks the fully-ready short-horizon cohort and emits
    SAR/CI/p/FDR records over 1d and 5d horizons.  ``errors`` must be
    empty (the read-only pipeline produces no errors on a healthy
    archive), every count must be a non-negative int, ``by_horizon``
    and ``by_mechanism_family`` must be dicts, ``examples`` must be a
    list, and ``significant_count <= records_count``.  Stable zero
    values are accepted because a sparse archive yields zeros across
    the board.  A regression that drops a field, returns negatives, or
    breaks the significant-vs-records bound means the contract drifted
    — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"archive short-horizon run response must be a JSON "
            f"object, got {type(body).__name__}"
        )
    errors = body.get("errors")
    if not isinstance(errors, list):
        raise AssertionError(
            f"errors must be a list, got {type(errors).__name__}"
        )
    if errors:
        raise AssertionError(
            f"errors must be empty in no-paid mode, got {errors!r}"
        )
    for field_name in _ARCHIVE_STAT_VALIDATION_RUN_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    if body["significant_count"] > body["records_count"]:
        raise AssertionError(
            f"significant_count must not exceed records_count; got "
            f"{body['significant_count']} > {body['records_count']}"
        )
    for key in ("by_horizon", "by_mechanism_family"):
        value = body.get(key)
        if not isinstance(value, dict):
            raise AssertionError(
                f"{key} must be a dict, got {type(value).__name__}"
            )
    examples = body.get("examples")
    if not isinstance(examples, list):
        raise AssertionError(
            f"examples must be a list, got {type(examples).__name__}"
        )


_ARCHIVE_STAT_VALIDATION_DEDUP_SUMMARY_REQUIRED_INTS: tuple[str, ...] = (
    "records_count",
    "effective_unique_records_count",
    "duplicate_records_count",
    "duplicate_groups_count",
)


_ARCHIVE_STAT_VALIDATION_DEDUP_SUMMARY_QVALUE_REQUIRED_INTS: tuple[str, ...] = (
    "raw_significant_records",
    "raw_significant_unique_records",
    "deduped_significant_unique_records",
    "groups_gaining_significance",
    "groups_losing_significance",
)


def _assert_archive_dedup_summary_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the archive stat-validation deduped
    summary CLI's JSON output.

    The summary collapses ``(event_date, primary_ticker, horizon)``
    duplicates so the operator can see how much of the surfaced
    FDR-controlled evidence comes from independent event-windows
    versus arithmetic duplicates that share the same price-window
    inputs.  ``ok`` must be True, ``errors`` must be empty, every
    count must be a non-negative int, ``by_horizon`` must be a dict,
    ``qvalue_change`` must carry every required int sub-field plus an
    ``any_change`` boolean, ``top_abs_sar`` must be a list, and
    ``effective_unique_records_count <= records_count``.  Stable zero
    values are accepted because a sparse archive yields zeros across
    the board.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"archive dedup-summary response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    if body.get("ok") is not True:
        raise AssertionError(
            f"ok must be True for the read-only dedup summary, got "
            f"{body.get('ok')!r}"
        )
    errors = body.get("errors")
    if not isinstance(errors, list):
        raise AssertionError(
            f"errors must be a list, got {type(errors).__name__}"
        )
    if errors:
        raise AssertionError(
            f"errors must be empty in no-paid mode, got {errors!r}"
        )
    for field_name in _ARCHIVE_STAT_VALIDATION_DEDUP_SUMMARY_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    if body["effective_unique_records_count"] > body["records_count"]:
        raise AssertionError(
            f"effective_unique_records_count must not exceed "
            f"records_count; got "
            f"{body['effective_unique_records_count']} > "
            f"{body['records_count']}"
        )
    by_horizon = body.get("by_horizon")
    if not isinstance(by_horizon, dict):
        raise AssertionError(
            f"by_horizon must be a dict, got {type(by_horizon).__name__}"
        )
    qvalue_change = body.get("qvalue_change")
    if not isinstance(qvalue_change, dict):
        raise AssertionError(
            f"qvalue_change must be a dict, got "
            f"{type(qvalue_change).__name__}"
        )
    for field_name in (
        _ARCHIVE_STAT_VALIDATION_DEDUP_SUMMARY_QVALUE_REQUIRED_INTS
    ):
        value = qvalue_change.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"qvalue_change[{field_name!r}] must be a non-negative "
                f"int, got {value!r}"
            )
    any_change = qvalue_change.get("any_change")
    if not isinstance(any_change, bool):
        raise AssertionError(
            f"qvalue_change['any_change'] must be bool, got "
            f"{type(any_change).__name__}"
        )
    top_abs_sar = body.get("top_abs_sar")
    if not isinstance(top_abs_sar, list):
        raise AssertionError(
            f"top_abs_sar must be a list, got "
            f"{type(top_abs_sar).__name__}"
        )


_SHORT_HORIZON_SHOWCASE_SHORTLIST_REQUIRED_INTS: tuple[str, ...] = (
    "candidate_count",
    "excluded_contaminated_count",
)


def _assert_short_horizon_showcase_shortlist_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the short-horizon showcase candidate
    shortlist CLI's JSON output.

    The shortlist ranks short-horizon candidates by ``|sar|`` and
    surfaces the contaminated cohort separately so an operator can
    decide whether to promote or hold.  ``ok`` must be True, every
    count must be a non-negative int, ``candidates`` must be a list
    whose length matches ``candidate_count`` (the partition floor),
    ``top_abs_sar`` is either a dict (the leading candidate) or
    ``None`` (no candidates), and ``recommended_next_action`` must be
    a non-empty string.  Stable zero values are accepted because a
    contaminated archive yields ``candidate_count == 0`` and
    ``top_abs_sar is None``.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"short-horizon showcase shortlist response must be a "
            f"JSON object, got {type(body).__name__}"
        )
    if body.get("ok") is not True:
        raise AssertionError(
            f"ok must be True for the read-only shortlist, got "
            f"{body.get('ok')!r}"
        )
    for field_name in _SHORT_HORIZON_SHOWCASE_SHORTLIST_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AssertionError(
                f"{field_name} must be a non-negative int, got {value!r}"
            )
    candidates = body.get("candidates")
    if not isinstance(candidates, list):
        raise AssertionError(
            f"candidates must be a list, got {type(candidates).__name__}"
        )
    if len(candidates) != body["candidate_count"]:
        raise AssertionError(
            f"candidate_count must equal len(candidates); got "
            f"candidate_count={body['candidate_count']} vs "
            f"len(candidates)={len(candidates)}"
        )
    top_abs_sar = body.get("top_abs_sar")
    if top_abs_sar is not None and not isinstance(top_abs_sar, dict):
        raise AssertionError(
            f"top_abs_sar must be a dict or None, got "
            f"{type(top_abs_sar).__name__}"
        )
    # Partition consistency: when there are no candidates, there is
    # no leading candidate either.  The script enforces this by
    # construction; pinning it here means a future accounting drift
    # trips the smoke.
    if body["candidate_count"] == 0 and top_abs_sar is not None:
        raise AssertionError(
            f"top_abs_sar must be None when candidate_count == 0, got "
            f"{top_abs_sar!r}"
        )
    action = body.get("recommended_next_action")
    if not isinstance(action, str) or not action:
        raise AssertionError(
            f"recommended_next_action must be a non-empty string, got "
            f"{action!r}"
        )


_MANUAL_REPAIRED_COHORT_REQUIRED_INTS: tuple[str, ...] = (
    "events_evaluated",
    "records_count",
    "significant_count",
)


def _assert_manual_repaired_cohort_validation_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the manual repaired-cohort validation
    runner CLI's JSON output.

    The runner integrates with yfinance for price-cache backfill on
    retag rows, so under the no-paid guard it MUST take its
    fail-closed path: the local ``_check_provider_available`` seam is
    forced to False (so retag rows trip the pre-copy provider check),
    and the local ``_fetch_ticker_rows`` seam is replaced with a
    raiser (defense in depth — any code path that reaches the fetcher
    has bypassed the availability gate and crashes loudly).

    The expected fail-closed shape is: ``ok`` is False, ``errors``
    contains a provider-related entry, the live DB and input backup
    are byte-identical (``live_db_unchanged`` and
    ``input_backup_unchanged`` are True), and every derived count is
    zero (no work happened).  A regression that flips any of those
    means the runner has bypassed the no-paid guard or touched a file
    we promised never to touch — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"manual repaired-cohort validation response must be a "
            f"JSON object, got {type(body).__name__}"
        )
    # Load-bearing safety invariants — if either of these flips, the
    # runner has touched a file we promised never to touch.
    if body.get("live_db_unchanged") is not True:
        raise AssertionError(
            f"live_db_unchanged must be True, got "
            f"{body.get('live_db_unchanged')!r}"
        )
    if body.get("input_backup_unchanged") is not True:
        raise AssertionError(
            f"input_backup_unchanged must be True, got "
            f"{body.get('input_backup_unchanged')!r}"
        )
    # The runner must take the fail-closed path under the no-paid
    # stub; ``ok`` flips to False when ``errors`` is non-empty.
    if body.get("ok") is not False:
        raise AssertionError(
            f"ok must be False under the no-paid provider stub, got "
            f"{body.get('ok')!r}"
        )
    errors = body.get("errors")
    if not isinstance(errors, list) or not errors:
        raise AssertionError(
            f"errors must be a non-empty list under the no-paid "
            f"provider stub, got {errors!r}"
        )
    if not any(
        isinstance(e, str) and "provider" in e.lower() for e in errors
    ):
        raise AssertionError(
            f"errors must mention 'provider' under the no-paid "
            f"provider stub, got {errors!r}"
        )
    for field_name in _MANUAL_REPAIRED_COHORT_REQUIRED_INTS:
        value = body.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            raise AssertionError(
                f"{field_name} must be 0 under the no-paid provider "
                f"stub, got {value!r}"
            )
    for list_name in ("repaired_clean_event_ids", "examples"):
        value = body.get(list_name)
        if not isinstance(value, list) or value:
            raise AssertionError(
                f"{list_name} must be an empty list under the no-paid "
                f"provider stub, got {value!r}"
            )
    for dict_name in ("by_horizon", "by_mechanism_family"):
        value = body.get(dict_name)
        if not isinstance(value, dict):
            raise AssertionError(
                f"{dict_name} must be a dict, got "
                f"{type(value).__name__}"
            )


@dataclass(frozen=True)
class SmokeEndpoint:
    name: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    method: str = "GET"
    body_invariants: tuple[BodyInvariant, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SmokeScript:
    """A read-only CLI smoke check.

    The smoke runner imports ``module``, calls ``main(list(args), out=...)``
    against an in-memory buffer, and validates the JSON output via the
    attached body invariants.  Each script runs under the same
    ``guard_no_paid_provider_calls()`` context as the HTTP smoke, so a
    forbidden seam in either script trips the same raisers and lands as
    a failed row.
    """
    name: str
    module: str
    args: tuple[str, ...] = ("--json", "--limit", "5")
    body_invariants: tuple[BodyInvariant, ...] = field(default_factory=tuple)
    # Local input files the check cannot run without (e.g. a maintainer-local
    # backup that is not tracked, so it is absent on a clean clone or CI
    # runner).  When any declared path is missing the check is *skipped*
    # rather than failed — see ``_missing_required_paths``.
    required_paths: tuple[str, ...] = ()


@dataclass
class SmokeResult:
    name: str
    path: str
    ok: bool
    status_code: int | None
    elapsed_ms: int
    error: str | None = None
    skipped: bool = False


ENDPOINTS: tuple[SmokeEndpoint, ...] = (
    SmokeEndpoint("health", "/health"),
    SmokeEndpoint("config health", "/diagnostics/config-health"),
    SmokeEndpoint(
        "auto backfill status",
        "/diagnostics/auto-backfill-status",
        body_invariants=(_assert_auto_backfill_status_no_paid,),
    ),
    SmokeEndpoint("data quality", "/diagnostics/data-quality"),
    SmokeEndpoint("archive stats", "/diagnostics/archive-stats"),
    SmokeEndpoint(
        "archive consistency",
        "/diagnostics/archive-consistency",
        body_invariants=(_assert_archive_consistency_no_paid,),
    ),
    SmokeEndpoint("validation stats", "/diagnostics/validation-status-stats"),
    SmokeEndpoint("reaction stats", "/diagnostics/reaction-profile-stats"),
    SmokeEndpoint("track record", "/diagnostics/track-record"),
    SmokeEndpoint(
        "major skipped",
        "/diagnostics/major-skipped-headlines?limit=5",
    ),
    SmokeEndpoint(
        "pending archive",
        "/events?limit=3&validation_status_v2=pending",
    ),
    # Some local archives do not retain row id 1.  A JSON 404 still
    # proves the detail route is mounted and guarded; seeded tests pin
    # the 200 path.
    SmokeEndpoint("event detail", "/events/1", (200, 404)),
    SmokeEndpoint("candidate queue", "/registry/candidate-queue?limit=5"),
    SmokeEndpoint("backfill preview", "/movers/backfill-preview?limit=5"),
    SmokeEndpoint(
        "event-date backfill",
        "/diagnostics/event-date-backfill-candidates",
        body_invariants=(_assert_event_date_backfill_no_paid,),
    ),
    SmokeEndpoint(
        "event-date backfill impact",
        "/diagnostics/event-date-backfill-impact-preview",
        body_invariants=(_assert_event_date_backfill_impact_no_paid,),
    ),
    SmokeEndpoint(
        "auto backfill dry-run",
        "/diagnostics/auto-backfill-dry-run",
        method="POST",
    ),
)


SCRIPTS: tuple[SmokeScript, ...] = (
    SmokeScript(
        "no-forward gap report",
        "scripts.no_forward_20d_gap_report",
        body_invariants=(_assert_no_forward_20d_gap_report_no_paid,),
    ),
    SmokeScript(
        "no-forward refreshability",
        "scripts.no_forward_20d_refreshability_export",
        body_invariants=(_assert_no_forward_20d_refreshability_export_no_paid,),
    ),
    SmokeScript(
        "auto-adjust repair preview",
        "scripts.auto_adjust_mismatch_repair_preview",
        body_invariants=(_assert_auto_adjust_mismatch_repair_preview_no_paid,),
    ),
    SmokeScript(
        "stat validation smoke",
        "scripts.stat_validation_smoke",
        # Smoke runs on a deterministic synthetic cohort and does not
        # accept ``--limit`` — pass only ``--json``.
        args=("--json",),
        body_invariants=(_assert_stat_validation_smoke_no_paid,),
    ),
    SmokeScript(
        "stat validation readiness",
        "scripts.stat_validation_readiness_report",
        args=("--json", "--limit", "20"),
        body_invariants=(_assert_stat_validation_readiness_report_no_paid,),
    ),
    SmokeScript(
        "archive cleanup execution plan",
        "scripts.archive_cleanup_execution_plan",
        body_invariants=(_assert_archive_cleanup_execution_plan_no_paid,),
    ),
    SmokeScript(
        "archive cleanup ticker readiness",
        "scripts.archive_cleanup_candidate_ticker_readiness",
        body_invariants=(_assert_archive_cleanup_ticker_readiness_no_paid,),
    ),
    SmokeScript(
        "stat validation short-horizon readiness",
        "scripts.stat_validation_short_horizon_readiness_report",
        args=("--json", "--limit", "20"),
        body_invariants=(_assert_short_horizon_readiness_report_no_paid,),
    ),
    SmokeScript(
        "stat validation short-horizon contamination",
        "scripts.stat_validation_short_horizon_contamination_report",
        args=("--json", "--limit", "20"),
        body_invariants=(_assert_short_horizon_contamination_report_no_paid,),
    ),
    SmokeScript(
        "archive stat validation short-horizon run",
        "scripts.archive_stat_validation_short_horizon_run",
        body_invariants=(_assert_archive_short_horizon_run_no_paid,),
    ),
    SmokeScript(
        "archive stat validation dedup summary",
        "scripts.archive_stat_validation_dedup_summary",
        body_invariants=(_assert_archive_dedup_summary_no_paid,),
    ),
    SmokeScript(
        "short-horizon showcase shortlist",
        "scripts.short_horizon_showcase_candidate_shortlist",
        body_invariants=(_assert_short_horizon_showcase_shortlist_no_paid,),
    ),
    # The repaired-cohort validation runner integrates with yfinance for
    # price-cache backfill on retag rows.  Its local
    # ``_check_provider_available`` seam is forced to False via
    # ``_READONLY_STUB_SEAMS`` and its ``_fetch_ticker_rows`` seam is
    # replaced with a raiser via ``_DANGEROUS_SEAMS`` so the smoke
    # exercises the runner's fail-closed path against real CSVs without
    # touching a paid provider.  Args carry the production-shaped
    # backup + worksheet paths so the smoke validates the real input
    # plumbing, not a no-arg stub path.
    SmokeScript(
        "manual repaired cohort validation",
        "scripts.manual_repaired_cohort_validation_run",
        args=(
            "--json",
            "--backup-path", "backups/events-20260507T095609.db",
            "--high-priority-csv", "manual_ticker_repair_high_priority.csv",
            "--medium-csv", "manual_ticker_repair_medium_production_like.csv",
            "--limit", "5",
        ),
        body_invariants=(_assert_manual_repaired_cohort_validation_no_paid,),
        # Untracked maintainer-local backup: absent on a clean clone / CI.
        # Gate the check on it so a missing fixture skips (not fails) this
        # check, while a present fixture runs the full no-paid invariant
        # above unchanged.
        required_paths=("backups/events-20260507T095609.db",),
    ),
)


_BANNED_PATH_MARKERS: tuple[str, ...] = (
    "/analyze",
    "/analyze/stream",
    "/movers/backfill-recent",
    "/movers/backfill-candidate",
)


_DANGEROUS_SEAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "api",
        (
            "analyze_event",
            "market_check",
            "followup_check",
            "macro_snapshot",
            "refresh_market_for_saved_event",
        ),
    ),
    (
        "analyze_event",
        (
            "analyze_event",
            "_call_llm_provider",
            "_call_anthropic",
            "_call_openai",
        ),
    ),
    (
        "market_check",
        (
            "_fetch",
            "_fetch_since",
            "market_check",
            "followup_check",
            "macro_snapshot",
            "compute_rates_context",
            "compute_stress_regime",
            "ticker_chart",
            "ticker_info",
        ),
    ),
    ("market_data", ("get_provider", "reload_provider_from_env")),
    ("price_cache", ("fetch_daily_cached",)),
    (
        "db",
        (
            "save_event",
            "save_movers_cache",
            "clear_movers_cache",
            "delete_event",
            "update_review",
            "append_revisit_snapshot",
        ),
    ),
    ("headline_registry", ("advance_state", "stamp_expired_if_observed")),
    (
        "routes.movers",
        (
            "_fresh_analysis_market_event",
            "_refresh_existing_market_event",
            "movers_backfill_recent",
            "movers_backfill_candidate",
        ),
    ),
    # Defense in depth for the repaired-cohort runner: the
    # availability stub above routes retag rows away from the fetcher,
    # but if a regression bypasses that gate the raiser here surfaces
    # the bypass as a loud crash instead of a silent paid call.
    (
        "scripts.manual_repaired_cohort_validation_run",
        ("_fetch_ticker_rows",),
    ),
)


def _empty_mover_slices(*_args, **_kwargs) -> dict[str, list[dict]]:
    return {"today": [], "market": [], "weekly": [], "persistent": []}


def _stub_provider_unavailable(*_args, **_kwargs) -> bool:
    """Pretend yfinance is not importable so any script that branches
    on a local provider-availability seam takes its fail-closed path
    instead of reaching for a paid provider call.
    """
    return False


_READONLY_STUB_SEAMS: tuple[tuple[str, str, Any], ...] = (
    (
        "routes.movers",
        "load_ui_slices_for_event_context",
        _empty_mover_slices,
    ),
    # The repaired-cohort runner's local availability probe — forcing
    # it to False routes retag rows into the runner's pre-copy
    # fail-closed branch before any provider call would fire.
    (
        "scripts.manual_repaired_cohort_validation_run",
        "_check_provider_available",
        _stub_provider_unavailable,
    ),
)


def _guard_raiser(label: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(f"no-paid smoke attempted forbidden seam: {label}")

    return _raise


@contextlib.contextmanager
def guard_no_paid_provider_calls():
    """Temporarily replace known paid/provider/write seams with raisers.

    A small route-side cache reader used by event detail is stubbed to
    empty mover slices so the smoke remains a DB-read preflight instead
    of bootstrapping persisted mover caches.
    """
    patched: list[tuple[Any, str, Any]] = []
    for module_name, attr_name, replacement in _READONLY_STUB_SEAMS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if not hasattr(module, attr_name):
            continue
        original = getattr(module, attr_name)
        setattr(module, attr_name, replacement)
        patched.append((module, attr_name, original))
    for module_name, attr_names in _DANGEROUS_SEAMS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr_name in attr_names:
            if not hasattr(module, attr_name):
                continue
            original = getattr(module, attr_name)
            setattr(module, attr_name, _guard_raiser(f"{module_name}.{attr_name}"))
            patched.append((module, attr_name, original))
    try:
        yield
    finally:
        for module, attr_name, original in reversed(patched):
            setattr(module, attr_name, original)


@contextlib.contextmanager
def _quiet_request_loggers():
    names = ("httpx", "second_order.movers_cache")
    original: list[tuple[logging.Logger, int, bool]] = []
    for name in names:
        logger = logging.getLogger(name)
        original.append((logger, logger.level, logger.propagate))
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    try:
        yield
    finally:
        for logger, level, propagate in original:
            logger.setLevel(level)
            logger.propagate = propagate


def _assert_endpoint_inventory_is_zero_cost() -> None:
    for endpoint in ENDPOINTS:
        if endpoint.method.upper() not in {"GET", "POST"}:
            raise AssertionError(
                f"no-paid smoke inventory has unsupported method: "
                f"{endpoint.method} {endpoint.path}"
            )
        for marker in _BANNED_PATH_MARKERS:
            if endpoint.path.startswith(marker):
                raise AssertionError(
                    f"no-paid smoke inventory includes paid path: {endpoint.path}"
                )


def _assert_script_inventory_is_zero_cost() -> None:
    """Defense-in-depth: every smoke script must live under the
    ``scripts`` package and request JSON output.  A regression that
    smuggles in a non-script module or drops the ``--json`` flag would
    leak the smoke into territory the no-paid guard cannot validate.
    """
    for script in SCRIPTS:
        if not script.module.startswith("scripts."):
            raise AssertionError(
                f"no-paid smoke inventory has non-scripts module: "
                f"{script.module}"
            )
        if "--json" not in script.args:
            raise AssertionError(
                f"no-paid smoke inventory script {script.module} must "
                f"request JSON output, got args {list(script.args)}"
            )


def _make_test_client():
    from fastapi.testclient import TestClient
    import api

    return TestClient(api.app)


class _HttpResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class _LocalHttpClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str) -> _HttpResponse:
        url = self.base_url + path
        request = urllib.request.Request(url, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return _HttpResponse(exc.code, exc.read())

    def get(self, path: str) -> _HttpResponse:
        return self.request("GET", path)

    def post(self, path: str) -> _HttpResponse:
        return self.request("POST", path)


def _response_is_json_parseable(response: Any) -> tuple[bool, str | None]:
    try:
        response.json()
    except Exception as exc:
        return False, f"response was not JSON parseable: {type(exc).__name__}: {exc}"
    return True, None


def _check_body_invariants(
    response: Any,
    invariants: tuple[BodyInvariant, ...],
) -> tuple[bool, str | None]:
    """Run the per-endpoint body invariants on a successful response.

    Each invariant takes the parsed JSON body and raises on failure.
    Returns ``(ok, error)``: ``ok`` is True when every invariant
    passes; ``error`` carries the raised message verbatim so the
    smoke output explains why the check failed.
    """
    if not invariants:
        return True, None
    try:
        body = response.json()
    except Exception as exc:
        return False, (
            f"could not parse response for invariants: "
            f"{type(exc).__name__}: {exc}"
        )
    for invariant in invariants:
        try:
            invariant(body)
        except AssertionError as exc:
            return False, f"body invariant failed: {exc}"
    return True, None


def _request(client: Any, endpoint: SmokeEndpoint) -> Any:
    method = endpoint.method.upper()
    if hasattr(client, "request"):
        return client.request(method, endpoint.path)
    attr = method.lower()
    if not hasattr(client, attr):
        raise AttributeError(f"client does not support {method}")
    return getattr(client, attr)(endpoint.path)


def _format_script_path(script: SmokeScript) -> str:
    """Render the script as a runnable command string for the result
    table.  The substring includes the module name verbatim so a
    downstream filter can match results to scripts by module path.
    """
    return f"python -m {script.module} " + " ".join(script.args)


def _invoke_script_main(script: SmokeScript) -> tuple[int, str]:
    """Import the script's module and call its ``main`` against an
    in-memory buffer.  Returns ``(exit_code, captured_stdout)``.
    """
    buf = io.StringIO()
    module = importlib.import_module(script.module)
    code = module.main(list(script.args), out=buf)
    return int(code or 0), buf.getvalue()


def _run_script(script: SmokeScript) -> tuple[bool, str | None]:
    """Run a single smoke script and validate its JSON output.

    Returns ``(ok, error)``.  ``ok`` is True only when ``main`` exits
    with zero, the output parses as JSON, and every body invariant
    accepts the parsed body.  Any failure surfaces a descriptive error
    string the smoke runner copies into the ``SmokeResult.error`` slot.
    """
    code, output = _invoke_script_main(script)
    if code != 0:
        return False, f"script exited with code {code}"
    try:
        body = json.loads(output)
    except json.JSONDecodeError as exc:
        return False, (
            f"script output was not JSON parseable: "
            f"{type(exc).__name__}: {exc}"
        )
    for invariant in script.body_invariants:
        try:
            invariant(body)
        except AssertionError as exc:
            return False, f"body invariant failed: {exc}"
    return True, None


def _fixture_exists(path: str) -> bool:
    """Resolve a script's declared fixture path, CWD-relative.

    The runner invokes each script in-process from the same working
    directory the script's own CLI resolves a relative ``--backup-path``
    against, so ``Path(path).exists()`` here matches exactly how the runner
    resolves the same argument: the skip fires precisely when the runner
    itself would error on the absent input, and never when it is present.
    """
    return Path(path).exists()


def _missing_required_paths(script: SmokeScript) -> list[str]:
    """Return the script's declared local fixtures that are absent.

    A check that declares ``required_paths`` is skipped (not failed) when
    any required input is missing: the runner is never invoked, so no
    paid/provider seam can fire, and a missing local fixture is not a
    paid-safety regression.  When every required path is present the check
    runs exactly as before, with its full body invariants under the no-paid
    guard.
    """
    return [p for p in script.required_paths if not _fixture_exists(p)]


def run_smoke(
    *,
    client: Any | None = None,
    base_url: str | None = None,
    timeout: float = 5.0,
    guard_provider_seams: bool = True,
) -> list[SmokeResult]:
    """Run the smoke checks and return per-endpoint results.

    The checks are zero-cost HTTP probes.  Success means the expected
    HTTP status was returned and the response body parsed as JSON.
    """
    _assert_endpoint_inventory_is_zero_cost()
    _assert_script_inventory_is_zero_cost()
    if client is not None and base_url:
        raise ValueError("Pass either client or base_url, not both.")

    if client is None:
        client = _LocalHttpClient(base_url, timeout) if base_url else _make_test_client()

    guard = guard_no_paid_provider_calls() if guard_provider_seams and not base_url else contextlib.nullcontext()
    results: list[SmokeResult] = []
    with guard, _quiet_request_loggers():
        for endpoint in ENDPOINTS:
            start = time.perf_counter()
            status_code: int | None = None
            ok = False
            error: str | None = None
            try:
                response = _request(client, endpoint)
                status_code = int(response.status_code)
                if status_code not in endpoint.expected_statuses:
                    error = (
                        f"expected HTTP {endpoint.expected_statuses}, got "
                        f"HTTP {status_code}"
                    )
                else:
                    ok, error = _response_is_json_parseable(response)
                    if ok and endpoint.body_invariants:
                        ok, error = _check_body_invariants(
                            response, endpoint.body_invariants,
                        )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            results.append(
                SmokeResult(
                    name=endpoint.name,
                    path=endpoint.path,
                    ok=bool(ok and error is None),
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                    error=error,
                )
            )
        # Local CLI scripts probe the local archive regardless of the
        # operator's --base-url target, so running them in --base-url
        # mode contradicts the operator's intent (probe a remote
        # backend) and bypasses the no-paid guard (which is replaced
        # with a nullcontext when base_url is set).  Skip them; the
        # in-process mode remains the full local preflight.
        if not base_url:
            # Scripts run after endpoints so the smoke output reads
            # top-down from HTTP rows to CLI rows and so ``results[0]``
            # keeps its endpoint-row semantics under the bad-client
            # failure path.
            for script in SCRIPTS:
                start = time.perf_counter()
                missing = _missing_required_paths(script)
                if missing:
                    # A declared local fixture is absent (e.g. a clean clone
                    # without the maintainer's untracked backup).  The runner
                    # is never invoked, so no paid seam can fire; report the
                    # check as skipped — distinct from both pass and fail —
                    # rather than letting the runner's missing-file error read
                    # as a no-paid failure.
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    results.append(
                        SmokeResult(
                            name=script.name,
                            path=_format_script_path(script),
                            ok=False,
                            status_code=None,
                            elapsed_ms=elapsed_ms,
                            error=(
                                "skipped: required local fixture(s) absent: "
                                + ", ".join(missing)
                            ),
                            skipped=True,
                        )
                    )
                    continue
                ok = False
                error = None
                try:
                    ok, error = _run_script(script)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                results.append(
                    SmokeResult(
                        name=script.name,
                        path=_format_script_path(script),
                        ok=bool(ok and error is None),
                        status_code=None,
                        elapsed_ms=elapsed_ms,
                        error=error,
                    )
                )
    return results


def summarize(results: list[SmokeResult]) -> dict[str, Any]:
    passed = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    total = len(results)
    failed = total - passed - skipped
    return {
        # A skipped check (an absent local fixture) is neither a pass nor a
        # failure, so it never flips ``ok``; only real failures do.
        "ok": failed == 0,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        },
        "checks": [asdict(r) for r in results],
    }


def render_table(results: list[SmokeResult]) -> str:
    lines = ["No-paid demo smoke", ""]
    lines.append(f"{'check':<22} {'status':<7} {'ms':>5} endpoint")
    lines.append(f"{'-' * 22} {'-' * 7} {'-' * 5} {'-' * 48}")
    for result in results:
        if result.skipped:
            status = "SKIP"
        else:
            status = "PASS" if result.ok else "FAIL"
        code = str(result.status_code) if result.status_code is not None else "-"
        lines.append(
            f"{result.name:<22} {status:<7} {result.elapsed_ms:>5} "
            f"{result.path} ({code})"
        )
        if result.error:
            lines.append(f"  -> {result.error}")
    info = summarize(results)["summary"]
    lines.append("")
    lines.append(
        f"Summary: {info['passed']}/{info['total']} PASS, "
        f"{info['failed']} FAIL, {info['skipped']} SKIP"
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run zero-cost local demo smoke checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact table.",
    )
    parser.add_argument(
        "--base-url",
        help=(
            "Probe a running local backend instead of in-process TestClient "
            "(example: http://127.0.0.1:8000)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds for --base-url mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, out=None) -> int:
    args = _parse_args(argv)
    output = out or sys.stdout
    results = run_smoke(base_url=args.base_url, timeout=args.timeout)
    payload = summarize(results)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=output)
    else:
        print(render_table(results), file=output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

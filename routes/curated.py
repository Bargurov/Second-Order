"""Curated candidate staging routes.

Operator-facing intake for events surfaced from the existing read-only
repair / expansion / short-horizon reports.  Three endpoints:

  * ``GET  /curated/candidates/preview`` — read-only.  Walks the three
    upstream reports through patchable seams and returns the
    candidates that COULD be staged.  No DB writes.

  * ``POST /curated/candidates/stage`` — requires ``confirm=true``.
    Inserts only into ``curated_candidates`` (composite unique key on
    ``(source_event_id, source)`` so re-staging is a no-op).  NEVER
    writes to the live ``events`` table.

  * ``GET  /curated/candidates/status`` — counts by status, mechanism
    family, primary ticker, and missing-field totals.

Conservative by construction
----------------------------

* No LLM / yfinance / market-data / network calls.
* No paid actions.
* No auto-assignment of missing ticker / mechanism fields — the API
  fills a field ONLY when the upstream report payload already carries
  it; missing fields are recorded in ``validation_errors``.
* Vocabulary: ``candidate``, ``staging``, ``draft``, ``needs_review``.
  Nothing here is called "validated".

Sources
-------

  * ``repaired_cohort``         — from ``manual_repaired_cohort_validation_summary``
  * ``archive_candidate``       — from ``repaired_cohort_expansion_candidate_report``
  * ``short_horizon_candidate`` — from ``short_horizon_repair_packet``

Status vocabulary at stage time: only ``draft`` (when validation_errors
are non-empty) or ``needs_review`` (when every required field is
present).  The other two values defined on the table
(``ready_for_validation``, ``excluded``) are operator-set out-of-band
and never assigned by this API.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Depends

import api as _api
import db


router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_SOURCE_REPAIRED:       str = "repaired_cohort"
_SOURCE_ARCHIVE:        str = "archive_candidate"
_SOURCE_SHORT_HORIZON:  str = "short_horizon_candidate"

_STATUS_DRAFT:        str = "draft"
_STATUS_NEEDS_REVIEW: str = "needs_review"

_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_date",
    "headline",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
)

_DEFAULT_BENCHMARK: str = "SPY"


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  Lazy imports fire only on the un-patched path so importing
# this module (e.g. when api.py is loaded) does NOT pull in the heavy
# archive scripts.
# ---------------------------------------------------------------------------


def _run_repaired_cohort_summary() -> dict[str, Any]:
    """Wrap ``manual_repaired_cohort_validation_summary``.  Tests patch
    this seam directly with synthetic payloads — the live archive
    scripts never run on the test path."""
    try:
        from scripts.manual_repaired_cohort_validation_summary import (
            summarize_repaired_cohort_validation,
        )
    except Exception:  # noqa: BLE001 — best-effort import
        return _empty_summary_payload()
    try:
        return summarize_repaired_cohort_validation()
    except Exception:  # noqa: BLE001 — never raise to the API
        return _empty_summary_payload()


def _run_expansion_report() -> dict[str, Any]:
    """Wrap ``repaired_cohort_expansion_candidate_report``."""
    try:
        from scripts.repaired_cohort_expansion_candidate_report import (
            run_repaired_cohort_expansion_candidate_report,
        )
    except Exception:  # noqa: BLE001
        return _empty_expansion_payload()
    try:
        return run_repaired_cohort_expansion_candidate_report()
    except Exception:  # noqa: BLE001
        return _empty_expansion_payload()


def _run_short_horizon_packet() -> dict[str, Any]:
    """Wrap ``short_horizon_repair_packet``."""
    try:
        from scripts.short_horizon_repair_packet import (
            build_short_horizon_repair_packet,
        )
    except Exception:  # noqa: BLE001
        return _empty_short_horizon_payload()
    try:
        return build_short_horizon_repair_packet()
    except Exception:  # noqa: BLE001
        return _empty_short_horizon_payload()


def _empty_summary_payload() -> dict[str, Any]:
    return {
        "repaired_clean_event_ids": [],
        "events_evaluated":         0,
        "records_count":            0,
        "significant_count":        0,
        "top_abs_sar":              [],
        "by_event_verdict":         {},
        "limitations":              [],
        "recommended_next_action":  "n/a",
    }


def _empty_expansion_payload() -> dict[str, Any]:
    return {
        "candidate_count":         0,
        "groups":                  {},
        "top_candidates":          [],
        "estimated_repair_yield":  {
            "conservative_estimate": 0,
            "optimistic_estimate":   0,
            "estimate_basis":        "no upstream data",
        },
        "recommended_next_action": "n/a",
    }


def _empty_short_horizon_payload() -> dict[str, Any]:
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   [],
        "reviewed_exclusion_set_count":  0,
        "excluded_reviewed_count":       0,
        "total_short_ready":             0,
        "delta_vs_full_ready":           0,
        "total_candidates_after_filter": 0,
        "candidates":                    [],
        "recommended_next_action":       "n/a",
    }


# ---------------------------------------------------------------------------
# Candidate construction — extract per-event fields from each upstream
# report's row shape.  Auto-fill ONLY from already-present fields; do
# NOT infer anything.
# ---------------------------------------------------------------------------


def _candidate_from_summary_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a candidate dict from a repaired-cohort-summary row.

    The summary's ``top_abs_sar`` entries carry ``event_id``,
    ``ticker``, ``mechanism_family``, and ``benchmark`` (set to SPY by
    the validation runner).  We accept those and only those — never
    infer.
    """
    ev_id = _coerce_int(row.get("event_id"))
    if ev_id is None:
        return None
    return _build_candidate(
        source=_SOURCE_REPAIRED,
        source_event_id=ev_id,
        event_date=row.get("event_date"),
        headline=row.get("headline"),
        primary_ticker=row.get("primary_ticker") or row.get("ticker"),
        benchmark_ticker=row.get("benchmark"),
        mechanism_family=row.get("mechanism_family"),
        source_url=row.get("source_url"),
    )


def _candidate_from_expansion_row(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a candidate dict from an expansion-report top_candidates
    entry.  Expansion rows carry only ``event_id`` / ``headline`` /
    ``group`` / ``reason`` — ticker and mechanism fields are
    deliberately absent (the report never proposes them) so they will
    land in ``validation_errors``."""
    ev_id = _coerce_int(row.get("event_id"))
    if ev_id is None:
        return None
    return _build_candidate(
        source=_SOURCE_ARCHIVE,
        source_event_id=ev_id,
        event_date=row.get("event_date"),
        headline=row.get("headline"),
        primary_ticker=None,
        benchmark_ticker=None,
        mechanism_family=None,
        source_url=row.get("source_url"),
        curator_notes=row.get("reason"),
    )


def _candidate_from_short_horizon_row(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a candidate dict from a short-horizon-packet candidate.
    Packet rows already carry ``current_primary_ticker`` (the archive
    ticker the operator may keep or replace) — we treat that as
    "already present in existing data" and forward it.  Mechanism
    family is deliberately blank in the packet (operator input
    column) so it lands in ``validation_errors``."""
    ev_id = _coerce_int(row.get("event_id"))
    if ev_id is None:
        return None
    return _build_candidate(
        source=_SOURCE_SHORT_HORIZON,
        source_event_id=ev_id,
        event_date=row.get("event_date"),
        headline=row.get("headline"),
        primary_ticker=row.get("current_primary_ticker"),
        benchmark_ticker=None,
        mechanism_family=row.get("proposed_mechanism_family") or None,
        source_url=row.get("source_url"),
    )


def _build_candidate(
    *, source: str, source_event_id: int,
    event_date: Any, headline: Any,
    primary_ticker: Any, benchmark_ticker: Any,
    mechanism_family: Any,
    source_url: Any = None,
    mechanism_description: Any = None,
    predicted_direction: Any = None,
    prediction_rationale: Any = None,
    curator_notes: Any = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "source":                source,
        "source_event_id":       int(source_event_id),
        "event_date":            _coerce_str(event_date),
        "headline":              _coerce_str(headline),
        "source_url":            _coerce_str(source_url),
        "primary_ticker":        _coerce_str(primary_ticker),
        "benchmark_ticker":      _coerce_str(benchmark_ticker),
        "mechanism_family":      _coerce_str(mechanism_family),
        "mechanism_description": _coerce_str(mechanism_description),
        "predicted_direction":   _coerce_str(predicted_direction),
        "prediction_rationale":  _coerce_str(prediction_rationale),
        "curator_notes":         _coerce_str(curator_notes),
    }
    candidate["validation_errors"] = _missing_field_errors(candidate)
    candidate["status"] = (
        _STATUS_DRAFT if candidate["validation_errors"]
        else _STATUS_NEEDS_REVIEW
    )
    return candidate


def _missing_field_errors(candidate: dict[str, Any]) -> list[str]:
    """List the required fields that are missing or empty.  The list
    is conservative: we never substitute a default for a missing
    value, even when one would be obvious (e.g., SPY for benchmark) —
    the operator must approve the fill explicitly."""
    out: list[str] = []
    for f in _REQUIRED_FIELDS:
        v = candidate.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            out.append(f"missing_{f}")
    return out


def _coerce_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    return str(v)


# ---------------------------------------------------------------------------
# Build the full candidate list from all three seams.
# ---------------------------------------------------------------------------


def _collect_candidates() -> list[dict[str, Any]]:
    """Walk all three upstream reports through their seams and return
    the merged candidate list.  The merge preserves source identity:
    the same ``source_event_id`` may appear from multiple sources and
    each occurrence is its own candidate (matching the table's
    composite unique key)."""
    out: list[dict[str, Any]] = []

    summary = _safe_dict(_run_repaired_cohort_summary())
    for row in (summary.get("top_abs_sar") or []):
        if not isinstance(row, dict):
            continue
        cand = _candidate_from_summary_row(row)
        if cand is not None:
            out.append(cand)

    # Add events from repaired_clean_event_ids that aren't in
    # top_abs_sar (events with no records still need staging).
    surfaced_ids = {c["source_event_id"] for c in out
                    if c["source"] == _SOURCE_REPAIRED}
    for ev_id_raw in (summary.get("repaired_clean_event_ids") or []):
        ev_id = _coerce_int(ev_id_raw)
        if ev_id is None or ev_id in surfaced_ids:
            continue
        out.append(_build_candidate(
            source=_SOURCE_REPAIRED, source_event_id=ev_id,
            event_date=None, headline=None,
            primary_ticker=None, benchmark_ticker=None,
            mechanism_family=None,
        ))

    expansion = _safe_dict(_run_expansion_report())
    for row in (expansion.get("top_candidates") or []):
        if not isinstance(row, dict):
            continue
        cand = _candidate_from_expansion_row(row)
        if cand is not None:
            out.append(cand)

    short_h = _safe_dict(_run_short_horizon_packet())
    for row in (short_h.get("candidates") or []):
        if not isinstance(row, dict):
            continue
        cand = _candidate_from_short_horizon_row(row)
        if cand is not None:
            out.append(cand)

    return out


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# DB helpers — every helper opens a single connection, does its work,
# and closes.  All writes go through the SAME table; ``events`` is
# never touched.
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    return db.connect_db()


def _ensure_table() -> None:
    """Best-effort table creation.  ``init_db`` already creates the
    table at app startup; this is a belt-and-suspenders for tests
    that touch the route before lifespan fires."""
    conn = _connect()
    try:
        try:
            db.init_db()
        except Exception:  # noqa: BLE001
            pass
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_candidate(conn: sqlite3.Connection,
                      candidate: dict[str, Any]) -> bool:
    """Insert a candidate row.  Returns True if a row was inserted,
    False if the (source_event_id, source) pair already exists.
    Idempotent by construction via INSERT OR IGNORE on the composite
    UNIQUE constraint."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO curated_candidates (
            source_event_id, event_date, headline, source_url,
            primary_ticker, benchmark_ticker, mechanism_family,
            mechanism_description, predicted_direction,
            prediction_rationale, curator_notes,
            status, source, created_at, validation_errors
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate["source_event_id"],
            candidate.get("event_date"),
            candidate.get("headline"),
            candidate.get("source_url"),
            candidate.get("primary_ticker"),
            candidate.get("benchmark_ticker"),
            candidate.get("mechanism_family"),
            candidate.get("mechanism_description"),
            candidate.get("predicted_direction"),
            candidate.get("prediction_rationale"),
            candidate.get("curator_notes"),
            candidate.get("status") or _STATUS_DRAFT,
            candidate["source"],
            _now_iso(),
            json.dumps(candidate.get("validation_errors") or []),
        ),
    )
    return cursor.rowcount == 1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/curated/candidates/preview")
def preview_candidates() -> dict[str, Any]:
    """Read-only preview of the candidates that COULD be staged.

    Returns the merged list across all three sources.  No DB writes.
    The same ``source_event_id`` may appear multiple times when it
    surfaces from more than one source — each occurrence carries a
    distinct ``source`` field (matching the table's composite key).
    """
    candidates = _collect_candidates()
    return {
        "preview_count": len(candidates),
        "candidates":    candidates,
    }


@router.post("/curated/candidates/stage", dependencies=[Depends(_api.require_admin_token)])
def stage_candidates(
    confirm: bool = Query(
        False,
        description=(
            "Must be true to write.  Defaults to false so a probing "
            "client cannot accidentally stage rows."
        ),
    ),
) -> dict[str, Any]:
    """Persist preview candidates into ``curated_candidates``.

    Requires ``confirm=true`` query param — without it the call
    returns 400.  Inserts are idempotent on the composite unique key
    ``(source_event_id, source)``.  Never writes to ``events``.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "stage requires confirm=true; refusing to write "
                "without explicit operator confirmation"
            ),
        )

    _ensure_table()
    candidates = _collect_candidates()
    inserted = 0
    skipped = 0
    conn = _connect()
    try:
        for cand in candidates:
            if _insert_candidate(conn, cand):
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "ok":              True,
        "preview_count":   len(candidates),
        "staged_count":    inserted,
        "skipped_count":   skipped,
    }


@router.get("/curated/candidates/status")
def status_counts() -> dict[str, Any]:
    """Counts over the curated_candidates table.

    Returns:
      * ``total``                          — row count
      * ``counts_by_status``               — {status: int}
      * ``counts_by_mechanism_family``     — {family: int} (skips
                                              rows with empty family)
      * ``counts_by_ticker``               — {ticker: int} (skips
                                              rows with empty ticker)
      * ``missing_field_counts``           — {required_field: int}
                                              total occurrences of
                                              that field appearing in
                                              ``validation_errors``
    """
    _ensure_table()
    conn = _connect()
    try:
        try:
            rows = conn.execute(
                "SELECT status, mechanism_family, primary_ticker, "
                "validation_errors FROM curated_candidates"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()

    counts_by_status:           dict[str, int] = {}
    counts_by_mechanism_family: dict[str, int] = {}
    counts_by_ticker:           dict[str, int] = {}
    missing_field_counts:       dict[str, int] = {
        f: 0 for f in _REQUIRED_FIELDS
    }
    total = 0

    for r in rows:
        total += 1
        status, family, ticker, errors_raw = r
        if isinstance(status, str) and status:
            counts_by_status[status] = counts_by_status.get(status, 0) + 1
        if isinstance(family, str) and family.strip():
            counts_by_mechanism_family[family] = (
                counts_by_mechanism_family.get(family, 0) + 1
            )
        if isinstance(ticker, str) and ticker.strip():
            counts_by_ticker[ticker] = counts_by_ticker.get(ticker, 0) + 1
        if isinstance(errors_raw, str) and errors_raw:
            try:
                errors = json.loads(errors_raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                errors = []
            if isinstance(errors, list):
                for token in errors:
                    if not isinstance(token, str):
                        continue
                    for f in _REQUIRED_FIELDS:
                        if f in token:
                            missing_field_counts[f] = (
                                missing_field_counts.get(f, 0) + 1
                            )
                            break

    return {
        "total":                       total,
        "counts_by_status":            counts_by_status,
        "counts_by_mechanism_family":  counts_by_mechanism_family,
        "counts_by_ticker":            counts_by_ticker,
        "missing_field_counts":        missing_field_counts,
    }

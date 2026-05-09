#!/usr/bin/env python3
"""Combined temp-copy manual ticker repair + price-cache backfill smoke.

Runs the operator-facing repair pipeline end-to-end against a *copied*
backup of the events DB, never touching the live archive.  Where the
two sibling smokes
(:mod:`scripts.manual_ticker_repair_apply_smoke` and
:mod:`scripts.manual_ticker_price_backfill_smoke`) demonstrate each
half in isolation, this script demonstrates the joint effect: retag
DRIV→MS in the events table AND backfill MS price-cache rows in the
**same temp copy**, so the readiness / contamination / clean-cohort
reports see both mutations together.

Modes
-----

  * ``dry-run`` (default) — parses the CSV, categorizes each row,
    plans per-ticker fetch windows, and reports the counts.  Does
    NOT call the provider, does NOT copy any file, does NOT write
    any DB.  All ``before_*`` / ``after_*`` / ``*_delta`` fields
    are ``None`` in dry-run.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path <PATH> --csv-path <PATH>``.

Order of operations in write mode (the brief's exact 6 steps,
plus the failure-precedence guards that gate them)::

     1. validate flags
     2. reject backup_path == db_path / missing files
     3. hash live DB + input backup
     4. parse CSV
     5. categorize rows + plan per-ticker windows
     6. fail closed if CSV has neither exclusions nor retags
     7. fail closed if retag rows exist AND provider unavailable
        (BEFORE copy — don't waste a temp file)
     8. copy backup → temp_copy_path                       [step 1 of brief]
     9. schema check: low_signal column present?
        Fail closed if exclusions exist & column missing.
    10. run clean + contam reports (before counts)
    11. apply categorized rows                              [step 2 of brief]
    12. backfill price_cache for retag tickers              [step 3 of brief]
    13. run clean + contam reports (after counts)           [steps 4-6 of brief]
    14. run readiness report (sanity probe)
    15. re-hash live DB + input backup
    16. surface drift / errors; ok = (errors empty)

Reused logic
------------

The pure helpers from the two sibling smokes are imported and
called directly (no copy/paste): ``_categorize_rows``,
``_apply_categorized_to_temp``, ``_has_low_signal_column`` from
``manual_ticker_repair_apply_smoke`` and
``_plan_per_ticker_windows``, ``_insert_ticker_rows_into_temp``
from ``manual_ticker_price_backfill_smoke``.  The five seams
(three reports + provider availability + fetch) are defined
locally on **this** module so unit tests patch a single surface.

Patchable seams
---------------

  * ``_run_readiness_report``      — wraps ``summarize_readiness``.
  * ``_run_contamination_report``  — wraps ``summarize_contamination``.
  * ``_run_clean_cohort_report``   — wraps ``summarize_clean_cohort``.
  * ``_check_provider_available``  — soft import-only probe; True iff
    ``yfinance`` is importable.
  * ``_fetch_ticker_rows``         — would shell out to yfinance to
    fetch daily bars for ``(ticker, [start, end])``.

Output contract::

    {
      "ok":                                  bool,
      "mode":                                "dry-run" | "write",
      "rows_read":                           int,
      "rows_excluded":                       int,
      "rows_retagged":                       int,
      "tickers_planned":                     int,
      "price_rows_written":                  int,
      "mechanism_family_updates":            int,
      "mechanism_family_updated_event_ids":  [int, ...],
      "before_clean_fully_ready":            int | None,
      "after_clean_fully_ready":             int | None,
      "clean_fully_ready_delta":             int | None,
      "before_contaminated_fully_ready":     int | None,
      "after_contaminated_fully_ready":      int | None,
      "live_db_unchanged":                   bool,
      "input_backup_unchanged":              bool,
      "errors":                              [str, ...],
      "warnings":                            [str, ...],
    }

The output dict carries EXACTLY these 18 keys — no additive fields.
``tickers_planned`` is surfaced even on the provider-unavailable
fail-closed path so the operator can see what would have been
fetched.  The temp copy path is surfaced via a ``Temp copy at
<path>`` warning.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.
* Input backup is NEVER opened for writes.
* No LLM, no FastAPI surface — never imports ``api`` or ``routes.*``.
* No provider call in dry-run — the seams' lazy imports only fire
  on the un-patched write path.

Usage::

    python scripts/manual_ticker_repair_full_smoke.py \\
        --dry-run --json --csv-path manual_ticker_repair_high_priority.csv
    python scripts/manual_ticker_repair_full_smoke.py \\
        --write --confirm --backup-path /path/to/events.backup.db \\
        --csv-path manual_ticker_repair_high_priority.csv --json
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Reused pure helpers — both sibling modules use only lazy imports
# inside their seams, so importing the modules here does NOT pull
# yfinance / readiness / contamination / clean-cohort.
from scripts.manual_ticker_repair_apply_smoke import (  # noqa: E402
    _apply_categorized_to_temp,
    _categorize_rows,
    _has_low_signal_column,
)
from scripts.manual_ticker_price_backfill_smoke import (  # noqa: E402
    _insert_ticker_rows_into_temp,
    _plan_per_ticker_windows,
)


_REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_date",
    "proposed_primary_ticker",
    "proposed_benchmark",
    "exclude_reason",
)
_SCHEMA_MISSING_TOKEN: str = "schema_missing_exclusion_field"
_SCHEMA_MISSING_MF_TOKEN: str = "schema_missing_mechanism_family_field"

_MECHANISM_FAMILY_COLUMN: str = "mechanism_family"


# Contamination flag whose meaning genuinely depends on the duplicate
# counterpart.  When the counterpart is operator-excluded, the flag's
# signal is already resolved — the smoke layer can move the repaired
# row into the adjusted-clean set without weakening the contamination
# report.  Any other flag (e.g., mechanism_family_none,
# driv_lit_off_topic, local_off_topic_headline) keeps the row in
# remaining_contamination_reasons because the operator hasn't taken an
# action that resolves it.
_DUPLICATE_COUNTERPART_FLAG: str = "duplicate_date_ticker"
_PROPOSED_MECHANISM_FAMILY_FIELD: str = "proposed_mechanism_family"


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  Lazy imports fire only on the un-patched write path.
# ---------------------------------------------------------------------------


def _run_readiness_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_readiness_report import summarize_readiness

    return summarize_readiness(db_path=db_path, limit=0)


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(db_path=db_path, limit=0)


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the clean-cohort report with an effectively unlimited
    per-row cap.  The smoke needs every contaminated example's flags
    to compute the manual-aware adjustment — a smaller cap would
    silently drop repaired rows from the adjustment input.
    """
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(db_path=db_path, limit=10**12)


def _check_provider_available() -> bool:
    """True iff ``yfinance`` is importable.  Does NOT make a network
    call.  Tests patch this to drive the provider-unavailable branch.
    """
    try:
        import yfinance  # noqa: F401
    except Exception:
        return False
    return True


def _fetch_ticker_rows(
    *, ticker: str, start: str, end: str,
) -> list[dict[str, Any]]:
    """Fetch daily bars for ``ticker`` over ``[start, end]`` inclusive.

    Production calls ``yfinance.download``; tests MUST patch this
    seam — the smoke has no environment that would tolerate a real
    network call.
    """
    import yfinance as yf  # local import — only fires on un-patched path

    end_d = _dt.date.fromisoformat(end) + _dt.timedelta(days=1)
    df = yf.download(
        ticker, start=start, end=end_d.isoformat(), progress=False,
        auto_adjust=True,
    )
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        out.append({
            "date":   idx.strftime("%Y-%m-%d"),
            "close":  float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return out


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_full_repair(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
    csv_path: str | None = None,
    write: bool = False,
    confirm: bool = False,
    mechanism_family_decisions: list[str] | None = None,
) -> dict[str, Any]:
    """Run the combined apply + backfill smoke.  See module docstring
    for the full order of operations.
    """
    errors: list[str] = []
    warnings: list[str] = []
    mode = "write" if write else "dry-run"

    rows_read = 0
    rows_excluded = 0
    rows_retagged = 0
    tickers_planned = 0
    price_rows_written = 0
    mechanism_family_updates = 0
    mechanism_family_updated_event_ids: list[int] = []
    before_clean: int | None = None
    after_clean:  int | None = None
    before_contam: int | None = None
    after_contam:  int | None = None
    after_clean_payload: dict[str, Any] = {}

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    parsed_rows, parse_errs, parse_warns = _parse_csv_if_present(csv_path)
    errors.extend(parse_errs)
    warnings.extend(parse_warns)
    rows_read = len(parsed_rows)
    categorized = _categorize_rows(parsed_rows, errors, warnings)
    plan = _plan_per_ticker_windows(parsed_rows, warnings)
    tickers_planned = len(plan)

    operator_excluded_event_ids = _operator_excluded_ids_from_categorized(
        categorized,
    )

    cli_decisions, decision_errs = _parse_mechanism_family_decisions(
        mechanism_family_decisions,
    )
    errors.extend(decision_errs)
    csv_decisions = _extract_csv_mechanism_family_decisions(parsed_rows)
    decisions = _merge_mechanism_family_decisions(
        csv_decisions, cli_decisions,
    )

    # If decision parsing surfaced errors, fail closed BEFORE write
    # mode runs — malformed flags should never reach the temp copy.
    if write and decision_errs:
        # Skip the entire write phase; outer hash check still runs.
        rows_excluded = 0
        rows_retagged = 0
        price_rows_written = 0
    elif write:
        (
            rows_excluded, rows_retagged, price_rows_written,
            mechanism_family_updates, mechanism_family_updated_event_ids,
            before_clean, after_clean,
            before_contam, after_contam,
            after_clean_payload,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path, csv_path=csv_path,
            confirm=confirm, categorized=categorized, plan=plan,
            decisions=decisions,
            errors=errors, warnings=warnings,
        )
    else:
        # Dry-run: count categorized rows; do not touch any file.
        rows_excluded = sum(1 for r in categorized if r["kind"] == "exclude")
        rows_retagged = sum(1 for r in categorized if r["kind"] == "retag")
        # Mirror the rows_retagged dry-run pattern: surface what *would*
        # be applied (merged CSV + CLI), without touching any DB.
        mechanism_family_updates = len(decisions)
        mechanism_family_updated_event_ids = list(decisions.keys())

    live_hash_after   = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)

    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after, path=backup_path,
    )
    if not live_db_unchanged:
        errors.append(
            f"LIVE DB BYTES CHANGED during full smoke — investigate: "
            f"{db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during full smoke — investigate: "
            f"{backup_path}"
        )

    clean_delta: int | None
    if before_clean is None or after_clean is None:
        clean_delta = None
    else:
        clean_delta = after_clean - before_clean

    # Manual-aware clean-cohort metrics.  In dry-run, all four count
    # fields are None and remaining_contamination_reasons is the empty
    # dict — operators get a JSON-iterable shape regardless of mode.
    if write and after_clean is not None:
        manual_aware = _compute_manual_aware_clean_metrics(
            after_clean_payload=after_clean_payload,
            operator_excluded_ids=set(operator_excluded_event_ids),
        )
    else:
        manual_aware = {
            "raw_after_clean_fully_ready":      None,
            "adjusted_after_clean_fully_ready": None,
            "adjusted_clean_fully_ready_delta": None,
            "remaining_contamination_reasons":  {},
        }

    return {
        "ok":                                 not errors,
        "mode":                               mode,
        "rows_read":                          rows_read,
        "rows_excluded":                      rows_excluded,
        "rows_retagged":                      rows_retagged,
        "tickers_planned":                    tickers_planned,
        "price_rows_written":                 price_rows_written,
        "mechanism_family_updates":           mechanism_family_updates,
        "mechanism_family_updated_event_ids": mechanism_family_updated_event_ids,
        "before_clean_fully_ready":           before_clean,
        "after_clean_fully_ready":            after_clean,
        "clean_fully_ready_delta":            clean_delta,
        "before_contaminated_fully_ready":    before_contam,
        "after_contaminated_fully_ready":     after_contam,
        "live_db_unchanged":                  live_db_unchanged,
        "input_backup_unchanged":             input_backup_unchanged,
        "errors":                             errors,
        "warnings":                           warnings,
        "operator_excluded_event_ids":        operator_excluded_event_ids,
        "raw_after_clean_fully_ready":        manual_aware["raw_after_clean_fully_ready"],
        "adjusted_after_clean_fully_ready":   manual_aware["adjusted_after_clean_fully_ready"],
        "adjusted_clean_fully_ready_delta":   manual_aware["adjusted_clean_fully_ready_delta"],
        "remaining_contamination_reasons":    manual_aware["remaining_contamination_reasons"],
    }


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None, csv_path: str | None,
    confirm: bool,
    categorized: list[dict[str, Any]],
    plan: dict[str, dict[str, Any]],
    decisions: dict[int, str],
    errors: list[str], warnings: list[str],
) -> tuple[int, int, int,
           int, list[int],
           int | None, int | None, int | None, int | None,
           dict[str, Any]]:
    """Execute the write-mode order of operations.  Returns
    ``(rows_excluded, rows_retagged, price_rows_written,
    mechanism_family_updates, mechanism_family_updated_event_ids,
    before_clean, after_clean, before_contam, after_contam,
    after_clean_payload)`` — the trailing payload is the full
    post-apply clean-cohort report dict so the outer function can
    compute the manual-aware adjustment without re-running the report.
    """
    empty_ids: list[int] = []
    empty_payload: dict[str, Any] = {}
    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload
    if not csv_path:
        errors.append("--write requires --csv-path; refusing to write")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 2: same-path / existence guards.
    if db_path:
        try:
            same_path = (
                Path(backup_path).resolve() == Path(db_path).resolve()
            )
        except OSError:
            same_path = False
        if same_path:
            errors.append(
                "--backup-path must differ from --db-path; refusing "
                "to write (would mutate the live DB)"
            )
            return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload
    if not Path(csv_path).exists():
        errors.append(f"--csv-path does not exist: {csv_path}")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    has_exclusions = any(r["kind"] == "exclude" for r in categorized)
    has_retags     = any(r["kind"] == "retag"   for r in categorized)
    has_decisions  = bool(decisions)

    # Step 6: nothing-to-do guard.  Mechanism-family decisions count
    # as actionable too — a CSV with only decisions still warrants a
    # full smoke (apply mechanism_family + run reports).
    if not has_exclusions and not has_retags and not has_decisions:
        errors.append(
            "No actionable rows in CSV (no exclusions, no retags) "
            "and no mechanism-family decisions — refusing to write; "
            "nothing to apply or backfill"
        )
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 7: provider check BEFORE copy.  Fail-closed precedence: if
    # retag rows need backfill but yfinance isn't importable, the
    # whole run fails — apply phase doesn't run either.
    if has_retags and not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing; retag rows require a price-cache "
            "backfill which cannot run"
        )
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 8: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 9a: schema check for low_signal.  Only relevant when
    # exclusions exist.
    if has_exclusions and not _has_low_signal_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_TOKEN}: temp DB lacks 'low_signal' "
            f"column — refusing to apply any rows"
        )
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 9b: schema check for mechanism_family.  Only relevant when
    # mechanism-family decisions were supplied (CSV-derived OR
    # CLI-derived — both share this codepath).  Fail-closed precedence
    # mirrors the low_signal check: if we can't honor the decisions,
    # we run NEITHER the apply phase NOR the backfill — partial
    # apply on a fail-closed signal is a foot-gun.
    if has_decisions and not _has_mechanism_family_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_MF_TOKEN}: temp DB lacks "
            f"'{_MECHANISM_FAMILY_COLUMN}' column — refusing to apply "
            f"any rows or decisions"
        )
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 10: before counts.
    try:
        before_clean = _safe_int(
            _safe_dict(_run_clean_cohort_report(db_path=temp_copy_path))
            .get("clean_fully_ready_count")
        )
        before_contam = _safe_int(
            _safe_dict(_run_contamination_report(db_path=temp_copy_path))
            .get("suspicious_count")
        )
    except Exception as e:
        errors.append(f"Pre-apply report failed: {e}")
        return 0, 0, 0, 0, empty_ids, None, None, None, None, empty_payload

    # Step 11: apply categorized rows (events table).
    try:
        rows_excluded, rows_retagged = _apply_categorized_to_temp(
            temp_copy_path, categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB apply failed: {e}")
        return (
            0, 0, 0, 0, empty_ids,
            before_clean, None, before_contam, None,
            empty_payload,
        )

    # Step 12: apply mechanism-family decisions (events table, same
    # temp DB).  Independent of retag/exclusion — a decision can land
    # on a row that was neither retagged nor excluded.  Failure here
    # surfaces as a fatal error; the apply phase has already mutated
    # the temp copy, so we still return the post-apply counts so the
    # operator can inspect what landed.
    try:
        mf_updates, mf_updated_ids = _apply_mechanism_family_decisions(
            temp_copy_path, decisions, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB mechanism-family apply failed: {e}")
        return (
            rows_excluded, rows_retagged, 0,
            0, empty_ids,
            before_clean, None, before_contam, None,
            empty_payload,
        )

    # Step 13: backfill price_cache for retag tickers (same temp DB).
    price_rows_written = 0
    if plan:
        for ticker, window in plan.items():
            try:
                rows = _fetch_ticker_rows(
                    ticker=ticker,
                    start=window["start"], end=window["end"],
                )
            except Exception as e:
                errors.append(
                    f"Provider fetch failed for {ticker}: {e}"
                )
                return (
                    rows_excluded, rows_retagged, price_rows_written,
                    mf_updates, mf_updated_ids,
                    before_clean, None, before_contam, None,
                    empty_payload,
                )
            try:
                written = _insert_ticker_rows_into_temp(
                    temp_copy_path, ticker, rows,
                )
            except sqlite3.Error as e:
                errors.append(
                    f"Temp DB price-cache insert failed for {ticker}: {e}"
                )
                return (
                    rows_excluded, rows_retagged, price_rows_written,
                    mf_updates, mf_updated_ids,
                    before_clean, None, before_contam, None,
                    empty_payload,
                )
            price_rows_written += written

    # Step 13: after counts (clean + contam) + readiness sanity probe.
    # Capture the FULL post-apply clean payload — the outer function
    # uses it to compute the manual-aware adjustment without re-running
    # the report.
    after_clean_payload: dict[str, Any] = {}
    try:
        after_clean_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
        after_clean = _safe_int(after_clean_payload.get("clean_fully_ready_count"))
        after_contam = _safe_int(
            _safe_dict(_run_contamination_report(db_path=temp_copy_path))
            .get("suspicious_count")
        )
    except Exception as e:
        errors.append(f"Post-apply report failed: {e}")
        return (
            rows_excluded, rows_retagged, price_rows_written,
            mf_updates, mf_updated_ids,
            before_clean, None, before_contam, None,
            empty_payload,
        )

    try:
        _run_readiness_report(db_path=temp_copy_path)
    except Exception as e:
        errors.append(f"Post-apply readiness probe failed: {e}")

    return (
        rows_excluded, rows_retagged, price_rows_written,
        mf_updates, mf_updated_ids,
        before_clean, after_clean, before_contam, after_contam,
        after_clean_payload,
    )


# ---------------------------------------------------------------------------
# CSV parsing — tolerant of either smoke's column subset
# ---------------------------------------------------------------------------


def _parse_csv_if_present(
    csv_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not csv_path:
        return [], errors, warnings
    if not Path(csv_path).exists():
        return [], errors, warnings
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [
                f for f in _REQUIRED_CSV_FIELDS if f not in fieldnames
            ]
            if missing:
                errors.append(
                    f"CSV missing required columns: {', '.join(missing)}"
                )
                return [], errors, warnings
            rows = [dict(r) for r in reader]
    except OSError as e:
        errors.append(f"Failed to read CSV {csv_path}: {e}")
        return [], errors, warnings
    return rows, errors, warnings


# ---------------------------------------------------------------------------
# Hash + temp-copy plumbing
# ---------------------------------------------------------------------------


def _hash_file_safe(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _hashes_match(
    *, before: str | None, after: str | None, path: str | None,
) -> bool:
    if path is None:
        return True
    return before == after


def _copy_to_fresh_temp(src_path: str) -> str:
    src = Path(src_path)
    dst_name = f"full_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(src_path, str(dst))
    return str(dst)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# Manual-aware clean-cohort metrics
#
# The raw clean-cohort report has no notion of operator exclusions: an
# event the operator marked excluded can still appear as the duplicate
# counterpart of a repaired row in the contamination examples list,
# leaving the repaired row blocked even though every contamination
# signal hangs on a row the operator already excluded.  The smoke layer
# surfaces an operator-aware view alongside the raw counts so an
# operator can see which events are eligible for the aggregate claim
# AFTER their exclusions / retags / mechanism-family decisions land.
#
# The adjustment is intentionally narrow: a contaminated event whose
# ONLY flag is ``duplicate_date_ticker`` AND that is NOT operator-
# excluded enters the adjusted-clean set.  Every other flag combination
# stays in ``remaining_contamination_reasons`` so an operator sees
# exactly which signals still block each repaired/kept row.
# ---------------------------------------------------------------------------


def _operator_excluded_ids_from_categorized(
    categorized: list[dict[str, Any]],
) -> list[int]:
    """Return the sorted list of event ids the operator marked
    excluded (categorized rows where ``kind == "exclude"``).  Sourcing
    from the categorized list keeps the smoke's notion of "excluded"
    identical to what landed in the temp DB — malformed CSV rows that
    the categorize phase rejected do NOT appear here.
    """
    out: set[int] = set()
    for r in categorized:
        if not isinstance(r, dict):
            continue
        if r.get("kind") != "exclude":
            continue
        ev_id = r.get("event_id")
        if isinstance(ev_id, int):
            out.add(ev_id)
    return sorted(out)


def _compute_manual_aware_clean_metrics(
    *,
    after_clean_payload: dict[str, Any],
    operator_excluded_ids: set[int],
) -> dict[str, Any]:
    """Compute the four manual-aware clean-cohort metrics from the raw
    clean-cohort report payload + the operator's excluded ids.

    Returns a dict with:

      * ``raw_after_clean_fully_ready``      — the report's
        ``clean_fully_ready_count`` verbatim.
      * ``adjusted_after_clean_fully_ready`` — the count of events
        eligible for the aggregate claim after honoring operator
        exclusions (subtracts excluded ids that landed in the raw
        clean set, adds repaired rows whose only contamination flag
        is ``duplicate_date_ticker``).
      * ``adjusted_clean_fully_ready_delta`` — adjusted minus raw.
      * ``remaining_contamination_reasons`` — dict keyed by str(id),
        value is the sorted flag list, for events that are still
        contaminated and were neither operator-excluded nor moved to
        the adjusted-clean set.  Empty dict (NOT None) when there is
        nothing to surface.
    """
    raw_count = after_clean_payload.get("clean_fully_ready_count")
    if not isinstance(raw_count, int):
        raw_count = 0

    raw_clean_ids: set[int] = set()
    raw_ids_field = after_clean_payload.get("clean_fully_ready_event_ids")
    if isinstance(raw_ids_field, list):
        for i in raw_ids_field:
            if isinstance(i, int):
                raw_clean_ids.add(i)

    excluded_examples = after_clean_payload.get("excluded_fully_ready_examples")
    if not isinstance(excluded_examples, list):
        excluded_examples = []

    promoted: set[int] = set()
    remaining: dict[str, list[str]] = {}
    for entry in excluded_examples:
        if not isinstance(entry, dict):
            continue
        ev_id = entry.get("event_id")
        if not isinstance(ev_id, int):
            continue
        if ev_id in operator_excluded_ids:
            # Operator already excluded this row — neither eligible for
            # the aggregate claim nor a "remaining" blocker for them.
            continue
        flags_raw = entry.get("flags")
        if not isinstance(flags_raw, list):
            flags_raw = []
        flag_set = {f for f in flags_raw if isinstance(f, str)}
        if flag_set == {_DUPLICATE_COUNTERPART_FLAG}:
            promoted.add(ev_id)
        else:
            remaining[str(ev_id)] = sorted(flag_set)

    # Adjusted set: raw clean minus operator-excluded, plus the
    # promoted (duplicate-only) rows.  When the report supplies the
    # event_ids list, use exact set arithmetic; otherwise fall back to
    # the scalar count + #promoted (defensive default — older fakes
    # omit the list).
    if isinstance(raw_ids_field, list):
        adjusted_set = (raw_clean_ids - operator_excluded_ids) | promoted
        adjusted_count = len(adjusted_set)
    else:
        adjusted_count = raw_count + len(promoted)

    return {
        "raw_after_clean_fully_ready":      raw_count,
        "adjusted_after_clean_fully_ready": adjusted_count,
        "adjusted_clean_fully_ready_delta": adjusted_count - raw_count,
        "remaining_contamination_reasons":  remaining,
    }


# ---------------------------------------------------------------------------
# Mechanism-family manual-decision support
#
# The contamination report flags ``mechanism_family_none`` for any
# fully-ready event whose ``events.mechanism_family`` column is the
# default ``'none'``.  That flag is not a ticker problem — it is an
# operator-classification gap that retag + price-cache backfill alone
# cannot clear.  Operators can pass one or more
# ``--mechanism-family-decision event_id=family_token`` flags; this
# smoke writes those decisions into the ``mechanism_family`` column on
# the temp copy ONLY.  No ticker-vocabulary validation is performed —
# the contamination report is the authority for whether a given token
# satisfies its check.
# ---------------------------------------------------------------------------


def _parse_mechanism_family_decisions(
    raw: list[str] | None,
) -> tuple[dict[int, str], list[str]]:
    """Parse repeatable ``event_id=family_token`` strings into a dict.

    Returns ``(decisions, errors)``.  Malformed entries (no ``=``,
    non-int ``event_id``, empty family) populate ``errors`` and are
    NOT included in the returned dict.  The caller is expected to
    fail closed when ``errors`` is non-empty.
    """
    out: dict[int, str] = {}
    errors: list[str] = []
    for entry in raw or []:
        if not isinstance(entry, str) or "=" not in entry:
            errors.append(
                f"--mechanism-family-decision: malformed entry "
                f"(missing '='): {entry!r}"
            )
            continue
        ev_raw, family = entry.split("=", 1)
        ev_raw = ev_raw.strip()
        family = family.strip()
        try:
            ev_id = int(ev_raw)
        except (TypeError, ValueError):
            errors.append(
                f"--mechanism-family-decision: non-integer event_id "
                f"in {entry!r}"
            )
            continue
        if not family:
            errors.append(
                f"--mechanism-family-decision: empty family token "
                f"in {entry!r}"
            )
            continue
        out[ev_id] = family
    return out, errors


def _has_mechanism_family_column(db_path: str) -> bool:
    """True iff the events table in ``db_path`` has a
    ``mechanism_family`` column.  Returns False on any read error —
    callers treat that as schema-missing and fail closed.
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return False
    try:
        try:
            rows = conn.execute(
                "PRAGMA table_info(events)"
            ).fetchall()
        except sqlite3.Error:
            return False
        return any(
            isinstance(r, tuple) and len(r) >= 2
            and r[1] == _MECHANISM_FAMILY_COLUMN
            for r in rows
        )
    finally:
        conn.close()


def _apply_mechanism_family_decisions(
    temp_db_path: str,
    decisions: dict[int, str],
    warnings: list[str],
) -> tuple[int, list[int]]:
    """Apply mechanism_family decisions to the temp DB.  Returns
    ``(applied_count, applied_event_ids)`` — the count and ordered
    list of event ids whose ``mechanism_family`` row actually changed.
    Event ids absent from the temp DB surface as warnings and are
    NOT included in the returned list.
    """
    applied_ids: list[int] = []
    if not decisions:
        return 0, applied_ids
    conn = sqlite3.connect(temp_db_path)
    try:
        for ev_id, family in decisions.items():
            existing = conn.execute(
                "SELECT 1 FROM events WHERE id = ?", (ev_id,),
            ).fetchone()
            if existing is None:
                warnings.append(
                    f"Mechanism family decision skipped: event_id={ev_id} "
                    f"not in temp events table"
                )
                continue
            conn.execute(
                f"UPDATE events SET {_MECHANISM_FAMILY_COLUMN} = ? "
                f"WHERE id = ?",
                (family, ev_id),
            )
            applied_ids.append(ev_id)
            warnings.append(
                f"Mechanism family decision applied: event_id={ev_id} "
                f"→ {family}"
            )
        conn.commit()
    finally:
        conn.close()
    return len(applied_ids), applied_ids


def _extract_csv_mechanism_family_decisions(
    rows: list[dict[str, Any]],
) -> dict[int, str]:
    """Pull ``proposed_mechanism_family`` decisions out of parsed CSV
    rows.  Rows missing the column, with a blank/whitespace-only
    value, or with an unparseable ``event_id`` are silently skipped —
    the column is optional, so a missing column is NOT an error.
    Later rows with the same ``event_id`` overwrite earlier ones.
    """
    out: dict[int, str] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        if _PROPOSED_MECHANISM_FAMILY_FIELD not in raw:
            continue
        family = (raw.get(_PROPOSED_MECHANISM_FAMILY_FIELD) or "").strip()
        if not family:
            continue
        ev_raw = (raw.get("event_id") or "")
        if not isinstance(ev_raw, (str, int)):
            continue
        try:
            ev_id = int(str(ev_raw).strip())
        except (TypeError, ValueError):
            continue
        out[ev_id] = family
    return out


def _merge_mechanism_family_decisions(
    csv_decisions: dict[int, str],
    cli_decisions: dict[int, str],
) -> dict[int, str]:
    """Merge CSV-derived and CLI-derived mechanism-family decisions.
    CLI wins on conflict — the operator's explicit override beats the
    worksheet proposal."""
    return {**csv_decisions, **cli_decisions}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Manual ticker repair full smoke", ""]
    lines.append(f"Mode:                              {report['mode']}")
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Rows excluded:                     {report['rows_excluded']}")
    lines.append(f"Rows retagged:                     {report['rows_retagged']}")
    lines.append(f"Tickers planned:                   {report['tickers_planned']}")
    lines.append(f"Price rows written:                {report['price_rows_written']}")
    lines.append(
        f"Mechanism family updates:          "
        f"{report['mechanism_family_updates']}"
    )
    lines.append(
        f"Mechanism family updated ids:      "
        f"{report['mechanism_family_updated_event_ids']}"
    )
    lines.append(
        f"before_clean_fully_ready:          "
        f"{report['before_clean_fully_ready']}"
    )
    lines.append(
        f"after_clean_fully_ready:           "
        f"{report['after_clean_fully_ready']}"
    )
    lines.append(
        f"clean_fully_ready_delta:           "
        f"{report['clean_fully_ready_delta']}"
    )
    lines.append(
        f"before_contaminated_fully_ready:   "
        f"{report['before_contaminated_fully_ready']}"
    )
    lines.append(
        f"after_contaminated_fully_ready:    "
        f"{report['after_contaminated_fully_ready']}"
    )
    lines.append(
        f"Live DB unchanged:                 {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:            {report['input_backup_unchanged']}"
    )
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combined temp-copy manual ticker repair + price-cache "
            "backfill smoke.  Default is a read-only dry-run that "
            "categorizes the CSV and plans per-ticker fetch windows.  "
            "Write mode requires --write --confirm --backup-path "
            "--csv-path together; the smoke copies the backup to a "
            "temp file, applies categorized rows + backfills price "
            "rows for proposed tickers in the SAME temp copy, and "
            "runs the readiness / contamination / clean-cohort "
            "reports against the post-mutation temp DB."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="Run in read-only dry-run mode (default).",
    )
    mode.add_argument(
        "--write", dest="write", action="store_true",
        help=(
            "Enable write mode.  Requires --confirm, --backup-path, "
            "and --csv-path."
        ),
    )
    parser.add_argument(
        "--confirm", dest="confirm", action="store_true",
        help="Required co-flag for --write.",
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help=(
            "Path to a backup of the events DB.  Required for "
            "--write.  Must differ from --db-path."
        ),
    )
    parser.add_argument(
        "--csv-path", dest="csv_path", default=None,
        help=(
            "Path to the completed manual_ticker_repair_packet CSV."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes."
        ),
    )
    parser.add_argument(
        "--mechanism-family-decision",
        dest="mechanism_family_decisions",
        action="append", default=[],
        metavar="EVENT_ID=FAMILY",
        help=(
            "Manual mechanism-family decision (repeatable).  Format: "
            "``event_id=family_token``, e.g. ``46=bank_regulatory_capital_relief``. "
            "Writes the family token into the events.mechanism_family "
            "column on the temp copy ONLY.  Malformed entries fail "
            "the run closed.  No vocabulary validation is performed; "
            "the contamination report is the authority."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_default_db_path() -> str | None:
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    db_path = args.db_path if args.db_path else _resolve_default_db_path()

    report = smoke_full_repair(
        db_path=db_path,
        backup_path=args.backup_path,
        csv_path=args.csv_path,
        write=bool(args.write),
        confirm=bool(args.confirm),
        mechanism_family_decisions=args.mechanism_family_decisions,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

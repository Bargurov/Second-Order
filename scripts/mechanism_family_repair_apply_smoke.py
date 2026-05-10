#!/usr/bin/env python3
"""Temp-copy mechanism-family repair apply + validation smoke.

Applies all three operator-completed repair worksheets to the SAME
temp copy of the events DB — never touching the live archive — then
runs the read-only clean-cohort + archive validation pipeline against
the post-repair temp DB so the operator can see whether the repaired
cohort actually expands.

The three CSVs are required (write mode) so this smoke can measure
expansion *from the existing repaired cohort* rather than from a raw
backup.  Without the high-priority + medium ticker repair worksheets
the smoke would start from an empty repaired cohort and miss the
[46, 60, 73] baseline that the prior repair pass already established.

Inputs
------

  * ``--high-priority-csv``  — ``manual_ticker_repair_high_priority.csv``
    (ticker retags + exclusions + CSV-driven mechanism_family
    decisions).
  * ``--medium-csv``         — ``manual_ticker_repair_medium_production_like.csv``
    (same shape).
  * ``--mechanism-family-csv`` — ``mechanism_family_repair_packet.csv``
    (mechanism_family decisions + exclusions only — no retags).

Modes
-----

  * ``dry-run`` (default) — parses every CSV, counts excluded /
    decision rows, and reports what *would* be applied.  Does NOT
    copy any file, write any DB, or invoke the downstream reports.
    All ``before_*`` / ``after_*`` / ``adjusted_*`` fields are
    ``None``; ``repaired_clean_event_ids`` is ``[]``;
    ``events_evaluated`` / ``records_count`` / ``significant_count``
    are ``0``; ``top_abs_sar`` is ``None``.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path --high-priority-csv --medium-csv
    --mechanism-family-csv``.  Order of operations:

       1. validate flags
       2. reject backup_path == db_path / missing files
       3. hash live DB + input backup
       4. parse all three CSVs
       5. categorize rows from high + medium (exclude / retag);
          extract mechanism_family decisions from all three
       6. plan per-ticker price-cache fetch windows (high + medium)
       7. fail closed if retag rows exist + provider unavailable
          (BEFORE copy — don't waste a temp file)
       8. copy backup → temp_copy_path
       9. schema checks: low_signal column present (when exclusions
          exist), mechanism_family column present (when decisions
          exist).  Either miss → fail closed; no apply.
      10. snapshot pre-repair clean cohort
      11. apply categorized exclusion + retag rows from high + medium
          + mechanism-family CSV (low_signal=1 / market_tickers JSON)
      12. apply mechanism_family decisions  → events.mechanism_family
      13. backfill price_cache for retag tickers via the provider seam
      14. snapshot post-repair clean cohort + manual-aware adjustment
      15. compute repaired_clean_event_ids =
            adjusted_after - before_clean
      16. invoke validation pipeline on the temp DB
      17. filter records / aggregates to repaired set
      18. re-hash live DB + input backup
      19. surface drift / errors; ok = (errors empty)

Reused helpers
--------------

The smoke imports the canonical helpers from sibling smokes — see
the ``from`` import block at the top of the source for the full
list.  Only the seams (clean cohort, validation, provider, fetch)
are re-defined locally so unit tests can patch a single surface.

Patchable seams
---------------

  * ``_run_clean_cohort_report``   — wraps the clean-cohort report.
  * ``_run_validation_on_temp_db`` — wraps the archive validation
    pipeline against the temp DB.
  * ``_check_provider_available``  — soft import-only probe; True
    iff ``yfinance`` is importable.
  * ``_fetch_ticker_rows``         — would shell out to yfinance to
    fetch daily bars for ``(ticker, [start, end])``.

Output contract::

    {
      "ok":                              bool,
      "rows_read":                       int,
      "rows_excluded":                   int,
      "mechanism_family_updates":        int,
      "mechanism_family_updated_event_ids": [int, ...],
      "before_clean_fully_ready":        int | None,
      "after_clean_fully_ready":         int | None,
      "adjusted_after_clean_fully_ready": int | None,
      "adjusted_clean_fully_ready_delta": int | None,
      "repaired_clean_event_ids":        [int, ...],
      "events_evaluated":                int,
      "records_count":                   int,
      "significant_count":               int,
      "top_abs_sar":                     float | None,
      "live_db_unchanged":               bool,
      "input_backup_unchanged":          bool,
      "errors":                          [str, ...],
      "warnings":                        [str, ...],
    }

The output dict carries EXACTLY these 18 keys — no additive fields.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.  It is hashed read-only.
* Input backup is NEVER opened for writes.  It is hashed read-only,
  then ``shutil.copy2``'d into a fresh temp file.
* No LLM, no FastAPI surface — never imports ``api`` or ``routes.*``.
* Default dry-run never imports the clean-cohort or validation
  modules — those imports fire only on the un-patched write path
  through the seams.

Conservative wording
--------------------

The events surfaced here are "manual repair candidates"; the
validation output is "repaired cohort evidence," NOT proof.  Banned
tokens (``proof``, ``automatically``, ``deletes``, ``replaces``,
``correct ticker``) never appear in any text the smoke emits.

Usage::

    python scripts/mechanism_family_repair_apply_smoke.py \\
        --dry-run --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --mechanism-family-csv mechanism_family_repair_packet.csv

    python scripts/mechanism_family_repair_apply_smoke.py \\
        --write --confirm \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --mechanism-family-csv mechanism_family_repair_packet.csv --json
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sqlite3
import sys
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
from scripts.manual_ticker_repair_full_smoke import (  # noqa: E402
    _apply_mechanism_family_decisions,
    _compute_manual_aware_clean_metrics,
    _copy_to_fresh_temp,
    _extract_csv_mechanism_family_decisions,
    _has_mechanism_family_column,
    _hash_file_safe,
    _hashes_match,
    _operator_excluded_ids_from_categorized,
    _parse_csv_if_present,
)
from scripts.manual_repaired_cohort_validation_run import (  # noqa: E402
    _adjusted_clean_event_ids,
)


_FAMILY_REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "event_id",
    "proposed_mechanism_family",
    "exclude_reason",
)
_SCHEMA_MISSING_TOKEN:    str = "schema_missing_exclusion_field"
_SCHEMA_MISSING_MF_TOKEN: str = "schema_missing_mechanism_family_field"


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  Lazy imports fire only on the un-patched write path.
# ---------------------------------------------------------------------------


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the clean-cohort report with an effectively unlimited
    per-row cap so the manual-aware adjustment sees every contaminated
    example.  A smaller cap would silently drop repaired rows from the
    adjustment input.
    """
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(db_path=db_path, limit=10**12)


def _run_validation_on_temp_db(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the read-only archive validation runner against the
    given DB path.  Reuses the validation enrichment from
    :mod:`scripts.manual_repaired_cohort_validation_run`.
    """
    from scripts.manual_repaired_cohort_validation_run import (
        _run_validation_on_temp_db as _run_underlying,
    )

    return _run_underlying(db_path=db_path)


def _check_provider_available() -> bool:
    """True iff ``yfinance`` is importable.  Does NOT make a network
    call.  Tests patch this to drive the provider-unavailable branch.
    """
    try:
        import yfinance  # noqa: F401
    except Exception:  # noqa: BLE001 — provider absence is signal
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


def smoke_mechanism_family_apply(
    *,
    db_path:              str | None = None,
    backup_path:          str | None = None,
    high_priority_csv:    str | None = None,
    medium_csv:           str | None = None,
    mechanism_family_csv: str | None = None,
    write:                bool       = False,
    confirm:              bool       = False,
) -> dict[str, Any]:
    """Run the three-CSV mechanism-family repair apply + validation
    smoke.  See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    rows_read:                          int = 0
    rows_excluded:                      int = 0
    mechanism_family_updates:           int = 0
    mechanism_family_updated_event_ids: list[int] = []
    before_clean: int | None = None
    after_clean:  int | None = None
    adjusted_after: int | None = None
    adjusted_delta: int | None = None
    repaired_clean_event_ids: list[int] = []
    events_evaluated:  int = 0
    records_count:     int = 0
    significant_count: int = 0
    top_abs_sar:       float | None = None

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    # Step 4: parse all three CSVs.  The high/medium CSVs follow the
    # ticker-repair packet schema; the mechanism-family CSV follows
    # the family-repair packet schema.  Each parser is tolerant of
    # missing/blank optional fields.
    high_rows, e1, w1 = _parse_csv_if_present(high_priority_csv)
    medium_rows, e2, w2 = _parse_csv_if_present(medium_csv)
    family_rows, e3, w3 = _parse_family_csv(mechanism_family_csv)
    errors.extend(e1 + e2 + e3)
    warnings.extend(w1 + w2 + w3)
    rows_read = len(high_rows) + len(medium_rows) + len(family_rows)

    # Step 5: categorize.  ``_categorize_rows`` is the canonical
    # categorizer for the ticker-repair packet schema (handles
    # exclude / retag / no-op / ambiguous).  The family CSV is run
    # through the local exclude-only classifier — it never produces
    # retags.
    high_categorized   = _categorize_rows(high_rows, errors, warnings)
    medium_categorized = _categorize_rows(medium_rows, errors, warnings)
    family_excluded, family_decisions = _classify_family_rows(
        family_rows, errors, warnings,
    )
    all_categorized = (
        list(high_categorized)
        + list(medium_categorized)
        + list(family_excluded)
    )

    # CSV-driven mechanism_family decisions: high → medium → family
    # (later wins on conflict).  Mirrors the manual_repaired_cohort
    # validation_run merge pattern.
    high_mf   = _extract_csv_mechanism_family_decisions(high_rows)
    medium_mf = _extract_csv_mechanism_family_decisions(medium_rows)
    decisions: dict[int, str] = {**high_mf, **medium_mf, **family_decisions}

    # Step 6: per-ticker fetch plan (only the ticker CSVs carry retags).
    plan = _plan_per_ticker_windows(
        list(high_rows) + list(medium_rows), warnings,
    )

    if write:
        (
            rows_excluded,
            mechanism_family_updates, mechanism_family_updated_event_ids,
            before_clean, after_clean, adjusted_after, adjusted_delta,
            repaired_clean_event_ids,
            events_evaluated, records_count, significant_count, top_abs_sar,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path,
            high_priority_csv=high_priority_csv,
            medium_csv=medium_csv,
            mechanism_family_csv=mechanism_family_csv,
            confirm=confirm,
            categorized=all_categorized,
            decisions=decisions,
            plan=plan,
            errors=errors, warnings=warnings,
        )
    else:
        # Dry-run: surface what *would* be applied.
        rows_excluded = sum(
            1 for r in all_categorized if r.get("kind") == "exclude"
        )
        mechanism_family_updates = len(decisions)
        mechanism_family_updated_event_ids = sorted(decisions.keys())

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
            f"LIVE DB BYTES CHANGED during mechanism-family apply smoke "
            f"— investigate: {db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during mechanism-family apply "
            f"smoke — investigate: {backup_path}"
        )

    return {
        "ok":                                  not errors,
        "rows_read":                           rows_read,
        "rows_excluded":                       rows_excluded,
        "mechanism_family_updates":            mechanism_family_updates,
        "mechanism_family_updated_event_ids":  mechanism_family_updated_event_ids,
        "before_clean_fully_ready":            before_clean,
        "after_clean_fully_ready":             after_clean,
        "adjusted_after_clean_fully_ready":    adjusted_after,
        "adjusted_clean_fully_ready_delta":    adjusted_delta,
        "repaired_clean_event_ids":            repaired_clean_event_ids,
        "events_evaluated":                    events_evaluated,
        "records_count":                       records_count,
        "significant_count":                   significant_count,
        "top_abs_sar":                         top_abs_sar,
        "live_db_unchanged":                   live_db_unchanged,
        "input_backup_unchanged":              input_backup_unchanged,
        "errors":                              errors,
        "warnings":                            warnings,
    }


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None,
    high_priority_csv: str | None,
    medium_csv: str | None,
    mechanism_family_csv: str | None,
    confirm: bool,
    categorized: list[dict[str, Any]],
    decisions: dict[int, str],
    plan: dict[str, dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> tuple[int,
           int, list[int],
           int | None, int | None, int | None, int | None,
           list[int], int, int, int, float | None]:
    """Execute the write-mode order of operations.  Returns the
    write-mode counters in the order they appear in the outer return
    tuple.  Any fail-closed exit returns zeros / Nones / empty lists
    and appends to ``errors``.
    """
    empty_repaired: list[int] = []
    empty_metrics = (0, 0, 0, None)
    empty_ids: list[int] = []

    def _bail() -> tuple[int, int, list[int],
                         int | None, int | None, int | None, int | None,
                         list[int], int, int, int, float | None]:
        return (
            0, 0, empty_ids,
            None, None, None, None,
            empty_repaired, *empty_metrics,
        )

    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return _bail()
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return _bail()
    if not high_priority_csv:
        errors.append(
            "--write requires --high-priority-csv; refusing to write"
        )
        return _bail()
    if not medium_csv:
        errors.append(
            "--write requires --medium-csv; refusing to write"
        )
        return _bail()
    if not mechanism_family_csv:
        errors.append(
            "--write requires --mechanism-family-csv; refusing to write"
        )
        return _bail()

    # Step 2: same-path defense.
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
            return _bail()

    # Step 3: backup + every CSV must exist.
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return _bail()
    for label, p in (
        ("--high-priority-csv",   high_priority_csv),
        ("--medium-csv",          medium_csv),
        ("--mechanism-family-csv", mechanism_family_csv),
    ):
        if not Path(p).exists():
            errors.append(f"{label} does not exist: {p}")
            return _bail()

    has_exclusions = any(r.get("kind") == "exclude" for r in categorized)
    has_retags     = any(r.get("kind") == "retag"   for r in categorized)
    has_decisions  = bool(decisions)

    # Step 6: nothing-to-do guard.
    if not has_exclusions and not has_retags and not has_decisions:
        errors.append(
            "No actionable rows in any CSV (no exclusions, no retags, "
            "no mechanism-family decisions) — refusing to write; "
            "nothing to apply"
        )
        return _bail()

    # Step 7: provider check BEFORE copy.  Fail-closed precedence: if
    # retag rows need backfill but yfinance isn't importable, the run
    # fails — apply phase doesn't run either.
    if has_retags and not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing; retag rows require a price-cache "
            "backfill which cannot run"
        )
        return _bail()

    # Step 8: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return _bail()
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 9: schema checks.  Fail-closed precedence mirrors the
    # sibling smokes — partial apply on a fail-closed signal is a
    # foot-gun.
    if has_exclusions and not _has_low_signal_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_TOKEN}: temp DB lacks 'low_signal' "
            f"column — refusing to apply any rows"
        )
        return _bail()
    if has_decisions and not _has_mechanism_family_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_MF_TOKEN}: temp DB lacks "
            f"'mechanism_family' column — refusing to apply any rows "
            f"or decisions"
        )
        return _bail()

    # Step 10: pre-repair clean cohort snapshot.
    try:
        before_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Pre-apply clean-cohort report failed: {e}")
        return _bail()
    before_clean = _safe_int(before_payload.get("clean_fully_ready_count"))
    before_clean_ids = _event_ids_from_payload(before_payload)

    # Step 11: apply categorized rows (exclusions + retags from all
    # three CSVs — the mechanism-family CSV's contribution is
    # exclusions only).
    try:
        rows_excluded, _retagged = _apply_categorized_to_temp(
            temp_copy_path, categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB exclusion/retag apply failed: {e}")
        return _bail()

    # Step 12: apply mechanism_family decisions.
    try:
        mf_updates, mf_updated_ids = _apply_mechanism_family_decisions(
            temp_copy_path, decisions, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB mechanism-family apply failed: {e}")
        return _bail()

    # Step 13: backfill price_cache for retag tickers.
    if plan:
        for ticker, window in plan.items():
            try:
                rows = _fetch_ticker_rows(
                    ticker=ticker,
                    start=window["start"], end=window["end"],
                )
            except Exception as e:  # noqa: BLE001 — operator-visible
                errors.append(f"Provider fetch failed for {ticker}: {e}")
                continue
            try:
                _insert_ticker_rows_into_temp(
                    temp_copy_path, ticker, rows,
                )
            except sqlite3.Error as e:
                errors.append(
                    f"Temp DB price-cache insert failed for {ticker}: {e}"
                )
                continue

    # Step 14: post-repair clean cohort + manual-aware adjustment.
    try:
        after_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Post-apply clean-cohort report failed: {e}")
        return (
            rows_excluded, mf_updates, sorted(mf_updated_ids),
            before_clean, None, None, None,
            empty_repaired, *empty_metrics,
        )
    after_clean = _safe_int(after_payload.get("clean_fully_ready_count"))

    operator_excluded_ids = set(
        _operator_excluded_ids_from_categorized(categorized)
    )
    manual_aware = _compute_manual_aware_clean_metrics(
        after_clean_payload=after_payload,
        operator_excluded_ids=operator_excluded_ids,
    )
    adjusted_after = manual_aware.get("adjusted_after_clean_fully_ready")
    # Mirror the full-smoke convention: delta is the manual-aware shift
    # from the raw after-count (i.e., adjusted_after - after_clean).
    adjusted_delta = (
        adjusted_after - after_clean
        if isinstance(adjusted_after, int) and isinstance(after_clean, int)
        else None
    )

    # Step 15: repaired_clean_event_ids = adjusted_after_ids - before_ids.
    adjusted_after_ids = _adjusted_clean_event_ids(
        after_clean_payload=after_payload,
        operator_excluded_ids=operator_excluded_ids,
    )
    repaired_set = adjusted_after_ids - before_clean_ids
    repaired_clean_event_ids = sorted(repaired_set)

    # Step 16-17: validation pipeline + filter to repaired set.
    events_evaluated = 0
    records_count = 0
    significant_count = 0
    top_abs_sar: float | None = None
    if repaired_clean_event_ids:
        try:
            validation_payload = _safe_dict(
                _run_validation_on_temp_db(db_path=temp_copy_path)
            )
        except Exception as e:  # noqa: BLE001 — operator-visible
            errors.append(f"Validation pipeline failed: {e}")
            validation_payload = {}

        all_records = validation_payload.get("records") or []
        repaired_records = [
            r for r in all_records
            if isinstance(r, dict)
            and isinstance(r.get("event_id"), int)
            and r["event_id"] in repaired_set
        ]
        records_count = len(repaired_records)
        events_evaluated = len({
            r["event_id"] for r in repaired_records
            if isinstance(r.get("event_id"), int)
        })
        significant_count = sum(
            1 for r in repaired_records
            if r.get("statistically_significant")
        )
        top_abs_sar = _top_abs_sar(repaired_records)
        for e_str in validation_payload.get("errors") or []:
            if isinstance(e_str, str) and e_str:
                errors.append(f"validation: {e_str}")

    return (
        rows_excluded,
        mf_updates, sorted(mf_updated_ids),
        before_clean, after_clean, adjusted_after, adjusted_delta,
        repaired_clean_event_ids,
        events_evaluated, records_count, significant_count, top_abs_sar,
    )


# ---------------------------------------------------------------------------
# Family-CSV parsing + classification
# ---------------------------------------------------------------------------


def _parse_family_csv(
    csv_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Parse the mechanism-family packet CSV.  Requires only the
    three columns that drive apply decisions; everything else is
    optional ride-along.
    """
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
                f for f in _FAMILY_REQUIRED_CSV_FIELDS if f not in fieldnames
            ]
            if missing:
                errors.append(
                    f"mechanism-family CSV missing required columns: "
                    f"{', '.join(missing)}"
                )
                return [], errors, warnings
            rows = [dict(r) for r in reader]
    except OSError as e:
        errors.append(f"Failed to read mechanism-family CSV {csv_path}: {e}")
        return [], errors, warnings
    return rows, errors, warnings


def _classify_family_rows(
    rows: list[dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Bucket each parsed mechanism-family CSV row into
    ``(excluded_categorized, decisions)``.

    Categorized exclusion rows carry ``kind == "exclude"`` so the
    reused ``_apply_categorized_to_temp`` helper sets
    ``low_signal = 1`` and never touches market_tickers.

    Ambiguous rows (both ``proposed_mechanism_family`` AND
    ``exclude_reason`` set) surface an error and are NOT applied —
    they are silently dropped from the decisions dict so the
    contradictory family token can't leak into the apply phase.

    No-op rows (neither set) surface a warning and are skipped.
    """
    excluded_categorized: list[dict[str, Any]] = []
    decisions: dict[int, str] = _extract_csv_mechanism_family_decisions(rows)

    for raw in rows:
        ev_id_raw = (raw.get("event_id") or "").strip()
        try:
            ev_id = int(ev_id_raw)
        except (TypeError, ValueError):
            warnings.append(
                f"Skipping family CSV row with unparseable event_id: "
                f"{ev_id_raw!r}"
            )
            continue
        family = (raw.get("proposed_mechanism_family") or "").strip()
        exclude = (raw.get("exclude_reason") or "").strip()
        if family and exclude:
            errors.append(
                f"event_id {ev_id}: ambiguous family CSV row — both "
                f"proposed_mechanism_family and exclude_reason are set"
            )
            decisions.pop(ev_id, None)
            continue
        if not family and not exclude:
            warnings.append(
                f"event_id {ev_id}: no-op family CSV row (no "
                f"mechanism-family decision, no exclusion) — skipping"
            )
            continue
        if exclude:
            excluded_categorized.append({
                "kind": "exclude", "event_id": ev_id, "reason": exclude,
            })
        # else: family set, no exclude → already in decisions via
        # _extract_csv_mechanism_family_decisions.
    return excluded_categorized, decisions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _event_ids_from_payload(payload: dict[str, Any]) -> set[int]:
    raw = payload.get("clean_fully_ready_event_ids")
    out: set[int] = set()
    if isinstance(raw, list):
        for i in raw:
            if isinstance(i, int):
                out.add(i)
    return out


def _top_abs_sar(records: list[dict[str, Any]]) -> float | None:
    """Return the maximum absolute ``sar`` across the repaired records,
    or ``None`` when no record carries a numeric ``sar``.  ``None`` /
    NaN / non-numeric values are skipped.
    """
    best: float | None = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        sar = rec.get("sar")
        if isinstance(sar, bool):
            continue
        if not isinstance(sar, (int, float)):
            continue
        try:
            v = abs(float(sar))
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN check
            continue
        if best is None or v > best:
            best = v
    return best


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Mechanism-family repair apply smoke", ""]
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Rows excluded:                     {report['rows_excluded']}")
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
        f"{_fmt(report['before_clean_fully_ready'])}"
    )
    lines.append(
        f"after_clean_fully_ready:           "
        f"{_fmt(report['after_clean_fully_ready'])}"
    )
    lines.append(
        f"adjusted_after_clean_fully_ready:  "
        f"{_fmt(report['adjusted_after_clean_fully_ready'])}"
    )
    lines.append(
        f"adjusted_clean_fully_ready_delta:  "
        f"{_fmt(report['adjusted_clean_fully_ready_delta'])}"
    )
    lines.append(
        f"repaired_clean_event_ids:          "
        f"{report['repaired_clean_event_ids']}"
    )
    lines.append(f"Events evaluated:                  {report['events_evaluated']}")
    lines.append(f"Records count:                     {report['records_count']}")
    lines.append(
        f"Significant count:                 {report['significant_count']}"
    )
    lines.append(
        f"Top abs SAR:                       {_fmt(report['top_abs_sar'])}"
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
            "Temp-copy mechanism-family repair apply + validation "
            "smoke.  Applies all three operator worksheets "
            "(high-priority + medium ticker repair + mechanism-family "
            "repair packet) to the SAME copied backup, runs the read-"
            "only clean-cohort + archive validation pipeline against "
            "the post-repair temp DB, and surfaces SAR / records / "
            "significant for the repaired cohort.  Conservative "
            "language only — these are repaired cohort evidence, not "
            "proof."
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
            "--high-priority-csv, --medium-csv, "
            "--mechanism-family-csv."
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
        "--high-priority-csv", dest="high_priority_csv", default=None,
        help="Path to manual_ticker_repair_high_priority.csv.",
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None,
        help="Path to manual_ticker_repair_medium_production_like.csv.",
    )
    parser.add_argument(
        "--mechanism-family-csv", dest="mechanism_family_csv", default=None,
        help="Path to mechanism_family_repair_packet.csv.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes."
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
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    db_path = args.db_path if args.db_path else _resolve_default_db_path()

    report = smoke_mechanism_family_apply(
        db_path=db_path,
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        mechanism_family_csv=args.mechanism_family_csv,
        write=bool(args.write),
        confirm=bool(args.confirm),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Temp-copy short-horizon repair apply + validation smoke.

Applies four operator-completed repair worksheets to the SAME temp
copy of the events DB — never touching the live archive — then runs
the read-only short-horizon (1d/5d) archive validation pipeline
against the post-repair temp DB so an operator can see whether the
short-horizon repaired cohort actually expands beyond the existing
full-horizon cohort.

The four CSVs are applied in this fixed order to mirror the prior
repair pass and stack the new short-horizon decisions on top::

    1. manual_ticker_repair_high_priority.csv
    2. manual_ticker_repair_medium_production_like.csv
    3. mechanism_family_repair_packet.csv
    4. short_horizon_repair_packet.csv          ← new

Inputs
------

  * ``--high-priority-csv``    — high-priority ticker repair worksheet.
  * ``--medium-csv``           — medium-batch ticker repair worksheet.
  * ``--mechanism-family-csv`` — mechanism-family-only repair packet.
  * ``--short-horizon-csv``    — short-horizon repair packet (new).

Modes
-----

  * ``dry-run`` (default) — parses every CSV, counts excludes /
    retags / decisions, and reports what *would* be applied.  No
    file copy, no DB write, no downstream report invocation.
    All ``after`` / ``repaired`` / ``records`` / ``significant`` /
    ``top_abs_sar`` fields are None / 0 / [].
  * ``write`` — requires ALL of ``--write --confirm
    --backup-path --high-priority-csv --medium-csv
    --mechanism-family-csv --short-horizon-csv``.

Order of operations in write mode::

     1. validate flags
     2. reject backup_path == db_path / missing files
     3. hash live DB + input backup
     4. parse all four CSVs
     5. categorize rows from high + medium + short-horizon
        (exclude / retag); the family CSV contributes excludes only
     6. extract mechanism_family decisions from all four CSVs
     7. plan per-ticker price-cache fetch windows for retag rows
     8. fail closed if retag rows exist + provider unavailable
        (BEFORE copy — don't waste a temp file)
     9. copy backup → temp_copy_path
    10. schema checks (low_signal / mechanism_family columns)
    11. snapshot pre-repair short-horizon-ready event_ids
    12. apply categorized rows (low_signal=1 / market_tickers retag)
    13. apply mechanism_family decisions
    14. backfill price_cache for retag tickers
    15. snapshot post-repair short-horizon-ready event_ids
    16. compute repaired_short_horizon_event_ids =
            post − pre
    17. invoke short-horizon validation pipeline on the temp DB
    18. filter records / aggregates to repaired set
    19. re-hash live DB + input backup; surface drift as errors

Reused helpers
--------------

The smoke imports canonical helpers from sibling smokes — see the
``from`` import block at the top of the source.  Only the four
seams (short-horizon readiness, short-horizon validation, provider
availability, ticker fetch) are re-defined locally so unit tests
patch a single surface.

Patchable seams
---------------

  * ``_run_short_horizon_readiness_report`` — wraps the short-horizon
    readiness coverage report.
  * ``_run_short_horizon_validation_on_temp_db`` — wraps the read-
    only short-horizon archive validation runner.  Tests patch this
    seam with synthetic payloads.
  * ``_check_provider_available`` — soft import-only probe; True
    iff ``yfinance`` is importable.
  * ``_fetch_ticker_rows`` — would shell out to yfinance for retag
    backfill.  Tests MUST patch this.

Output contract::

    {
      "ok":                              bool,
      "rows_read":                       int,
      "rows_excluded":                   int,
      "rows_retagged":                   int,
      "mechanism_family_updates":        int,
      "repaired_short_horizon_event_ids": [int, ...],
      "events_evaluated":                int,
      "records_count":                   int,
      "significant_count":               int,
      "top_abs_sar":                     float | None,
      "live_db_unchanged":               bool,
      "input_backup_unchanged":          bool,
      "errors":                          [str, ...],
      "warnings":                        [str, ...],
    }

The output dict carries EXACTLY these 14 keys — no additive fields.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.  It is hashed read-only.
* Input backup is NEVER opened for writes.  It is hashed read-only,
  then copied into a fresh temp file.
* No LLM, no FastAPI surface — never imports ``api`` / ``routes.*``.
* Default dry-run never imports the readiness / validation modules
  — those imports fire only on the un-patched write path through
  the seams.

Conservative wording
--------------------

The events surfaced here are "manual repair candidates"; the
validation output is "short-horizon evidence," NOT proof, NOT
alpha, NOT a primary trading signal.  Banned tokens (``proof``,
``automatically``, ``deletes``, ``replaces``, ``correct ticker``)
never appear in any text the smoke emits.

Usage::

    python scripts/short_horizon_repair_apply_smoke.py \\
        --dry-run --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --mechanism-family-csv mechanism_family_repair_packet.csv \\
        --short-horizon-csv short_horizon_repair_packet.csv

    python scripts/short_horizon_repair_apply_smoke.py \\
        --write --confirm \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --mechanism-family-csv mechanism_family_repair_packet.csv \\
        --short-horizon-csv short_horizon_repair_packet.csv --json
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


# Reused canonical helpers — every sibling module uses lazy imports
# for its own provider / readiness / validation seams, so importing
# the modules here does NOT pull yfinance / fastapi / price_cache.
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
    _copy_to_fresh_temp,
    _extract_csv_mechanism_family_decisions,
    _has_mechanism_family_column,
    _hash_file_safe,
    _hashes_match,
    _parse_csv_if_present,
)
from scripts.mechanism_family_repair_apply_smoke import (  # noqa: E402
    _classify_family_rows,
    _parse_family_csv,
)


_SHORT_HORIZON_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_id",
    "proposed_primary_ticker",
    "proposed_mechanism_family",
    "exclude_reason",
)
_SCHEMA_MISSING_TOKEN:    str = "schema_missing_exclusion_field"
_SCHEMA_MISSING_MF_TOKEN: str = "schema_missing_mechanism_family_field"


# ---------------------------------------------------------------------------
# Patchable seams — local so tests patch a single surface.  Lazy
# imports fire only on the un-patched write path.
# ---------------------------------------------------------------------------


def _run_short_horizon_readiness_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon (1d/5d) readiness coverage report
    with an effectively unlimited per-row cap so the pre/post diff
    sees every short-horizon-ready event.
    """
    from scripts.stat_validation_short_horizon_readiness_report import (
        summarize_short_horizon_readiness,
    )

    return summarize_short_horizon_readiness(
        db_path=db_path, limit=10**12,
    )


def _run_short_horizon_validation_on_temp_db(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the read-only short-horizon archive validation runner
    against the temp DB.  Reuses the enrichment from the full
    repaired-cohort runner so records carry mechanism_family +
    statistically_significant.

    Tests patch this seam directly with synthetic payloads.
    """
    from scripts.archive_stat_validation_short_horizon_run import (
        run_archive_short_horizon_stat_validation,
    )
    from scripts.manual_repaired_cohort_validation_run import (
        _mechanism_family_by_event_id,
    )
    from stats.stat_validation import (
        DEFAULT_ALPHA, is_statistically_significant,
    )

    payload = run_archive_short_horizon_stat_validation(
        db_path=db_path, limit=10**9,
    )
    examples = payload.get("examples") or []
    family_by_id = _mechanism_family_by_event_id(db_path)

    records: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        ev_id = ex.get("event_id")
        records.append({
            "event_id":                 ev_id,
            "headline":                 ex.get("headline"),
            "ticker":                   ex.get("ticker"),
            "horizon":                  ex.get("horizon"),
            "abnormal_return":          ex.get("abnormal_return"),
            "sar":                      ex.get("sar"),
            "ci_low":                   ex.get("ci_low"),
            "ci_high":                  ex.get("ci_high"),
            "p_value":                  ex.get("p_value"),
            "fdr_q":                    ex.get("fdr_q"),
            "interpretation":           ex.get("interpretation"),
            "mechanism_family": (
                family_by_id.get(ev_id) if isinstance(ev_id, int) else None
            ),
            "statistically_significant": is_statistically_significant(
                ex.get("fdr_q"), alpha=DEFAULT_ALPHA,
            ),
        })

    enriched = dict(payload)
    enriched["records"] = records
    return enriched


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

    Production calls ``yfinance.download``; tests MUST patch this.
    """
    import yfinance as yf  # local — only fires on un-patched path

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


def smoke_short_horizon_repair_apply(
    *,
    db_path:              str | None = None,
    backup_path:          str | None = None,
    high_priority_csv:    str | None = None,
    medium_csv:           str | None = None,
    mechanism_family_csv: str | None = None,
    short_horizon_csv:    str | None = None,
    write:                bool       = False,
    confirm:              bool       = False,
) -> dict[str, Any]:
    """Run the short-horizon repair apply + validation smoke.  See
    module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    rows_read:                  int = 0
    rows_excluded:              int = 0
    rows_retagged:              int = 0
    mechanism_family_updates:   int = 0
    repaired_short_horizon_event_ids: list[int] = []
    events_evaluated:           int = 0
    records_count:              int = 0
    significant_count:          int = 0
    top_abs_sar:                float | None = None

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    # Step 4: parse every CSV.  The high/medium/short-horizon CSVs
    # use the ticker-repair packet schema; the family CSV uses its
    # own schema and is parsed via the dedicated helper.
    high_rows,   e_h, w_h = _parse_csv_if_present(high_priority_csv)
    medium_rows, e_m, w_m = _parse_csv_if_present(medium_csv)
    family_rows, e_f, w_f = _parse_family_csv(mechanism_family_csv)
    short_rows,  e_s, w_s = _parse_short_horizon_csv(short_horizon_csv)
    errors.extend(e_h + e_m + e_f + e_s)
    warnings.extend(w_h + w_m + w_f + w_s)
    rows_read = (
        len(high_rows) + len(medium_rows)
        + len(family_rows) + len(short_rows)
    )

    # Step 5: categorize.  ``_categorize_rows`` handles the ticker-
    # packet schema (high / medium / short-horizon all share it);
    # the family CSV is run through ``_classify_family_rows`` which
    # only emits exclude rows and a decisions dict.
    high_categorized   = _categorize_rows(high_rows,   errors, warnings)
    medium_categorized = _categorize_rows(medium_rows, errors, warnings)
    short_categorized  = _categorize_rows(short_rows,  errors, warnings)
    family_excluded, family_decisions = _classify_family_rows(
        family_rows, errors, warnings,
    )
    all_categorized = (
        list(high_categorized)
        + list(medium_categorized)
        + list(family_excluded)
        + list(short_categorized)
    )

    # Step 6: CSV-driven mechanism_family decisions.  Order: high →
    # medium → family → short-horizon.  Last write wins (short-
    # horizon CSV is the most recent operator decision).
    high_mf  = _extract_csv_mechanism_family_decisions(high_rows)
    med_mf   = _extract_csv_mechanism_family_decisions(medium_rows)
    short_mf = _extract_csv_mechanism_family_decisions(short_rows)
    decisions: dict[int, str] = {
        **high_mf, **med_mf, **family_decisions, **short_mf,
    }

    # Step 7: per-ticker fetch plan from every retag row across the
    # three ticker CSVs (the family CSV never carries retags).
    plan = _plan_per_ticker_windows(
        list(high_rows) + list(medium_rows) + list(short_rows),
        warnings,
    )

    if write:
        (
            rows_excluded, rows_retagged,
            mechanism_family_updates,
            repaired_short_horizon_event_ids,
            events_evaluated, records_count, significant_count, top_abs_sar,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path,
            high_priority_csv=high_priority_csv,
            medium_csv=medium_csv,
            mechanism_family_csv=mechanism_family_csv,
            short_horizon_csv=short_horizon_csv,
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
        rows_retagged = sum(
            1 for r in all_categorized if r.get("kind") == "retag"
        )
        mechanism_family_updates = len(decisions)

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
            f"LIVE DB BYTES CHANGED during short-horizon apply smoke "
            f"— investigate: {db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during short-horizon apply "
            f"smoke — investigate: {backup_path}"
        )

    return {
        "ok":                              not errors,
        "rows_read":                       rows_read,
        "rows_excluded":                   rows_excluded,
        "rows_retagged":                   rows_retagged,
        "mechanism_family_updates":        mechanism_family_updates,
        "repaired_short_horizon_event_ids": repaired_short_horizon_event_ids,
        "events_evaluated":                events_evaluated,
        "records_count":                   records_count,
        "significant_count":               significant_count,
        "top_abs_sar":                     top_abs_sar,
        "live_db_unchanged":               live_db_unchanged,
        "input_backup_unchanged":          input_backup_unchanged,
        "errors":                          errors,
        "warnings":                        warnings,
    }


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None,
    high_priority_csv: str | None,
    medium_csv: str | None,
    mechanism_family_csv: str | None,
    short_horizon_csv: str | None,
    confirm: bool,
    categorized: list[dict[str, Any]],
    decisions: dict[int, str],
    plan: dict[str, dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> tuple[int, int,
           int,
           list[int],
           int, int, int, float | None]:
    """Execute the write-mode order of operations.  Any fail-closed
    exit returns zeros / Nones / empty lists and appends to
    ``errors``.
    """
    empty_repaired: list[int] = []
    empty_metrics: tuple[int, int, int, float | None] = (0, 0, 0, None)

    def _bail() -> tuple[int, int, int,
                         list[int], int, int, int, float | None]:
        return (0, 0, 0, empty_repaired, *empty_metrics)

    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return _bail()
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return _bail()
    if not short_horizon_csv:
        errors.append(
            "--write requires --short-horizon-csv; refusing to write"
        )
        return _bail()
    # ``--high-priority-csv``, ``--medium-csv``, ``--mechanism-family-csv``
    # are optional: when omitted, the prior repair pass is treated as
    # "nothing to apply on top of the backup."  The short-horizon CSV
    # is the only operator artifact this smoke truly requires.

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
    # Existence-check only the paths the operator actually supplied.
    # Required: --short-horizon-csv.  Optional: the prior-pass CSVs.
    if not Path(short_horizon_csv).exists():
        errors.append(
            f"--short-horizon-csv does not exist: {short_horizon_csv}"
        )
        return _bail()
    for label, p in (
        ("--high-priority-csv",   high_priority_csv),
        ("--medium-csv",          medium_csv),
        ("--mechanism-family-csv", mechanism_family_csv),
    ):
        if p and not Path(p).exists():
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

    # Step 8: provider check BEFORE copy.  Fail-closed when retag
    # rows need backfill but yfinance isn't importable.
    if has_retags and not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing; retag rows require a price-cache "
            "backfill which cannot run"
        )
        return _bail()

    # Step 9: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return _bail()
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 10: schema checks.
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

    # Step 11: pre-repair short-horizon-ready snapshot.
    try:
        pre_payload = _safe_dict(
            _run_short_horizon_readiness_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Pre-apply short-horizon readiness failed: {e}")
        return _bail()
    pre_ready_ids = _ready_event_ids_from_payload(pre_payload)

    # Step 12: apply categorized rows (excludes + retags from all
    # ticker / family / short-horizon CSVs).
    try:
        rows_excluded, rows_retagged = _apply_categorized_to_temp(
            temp_copy_path, categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB exclusion/retag apply failed: {e}")
        return _bail()

    # Step 13: apply mechanism_family decisions.
    try:
        mf_updates, _mf_updated_ids = _apply_mechanism_family_decisions(
            temp_copy_path, decisions, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB mechanism-family apply failed: {e}")
        return _bail()

    # Step 14: backfill price_cache for retag tickers.
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

    # Step 15: post-repair short-horizon-ready snapshot.
    try:
        post_payload = _safe_dict(
            _run_short_horizon_readiness_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Post-apply short-horizon readiness failed: {e}")
        return (
            rows_excluded, rows_retagged, mf_updates,
            empty_repaired, *empty_metrics,
        )
    post_ready_ids = _ready_event_ids_from_payload(post_payload)

    # Step 16: repaired_short_horizon_event_ids = post − pre.
    repaired_set = post_ready_ids - pre_ready_ids
    repaired_event_ids = sorted(repaired_set)

    # Step 17-18: validation pipeline + filter to repaired set.
    events_evaluated = 0
    records_count    = 0
    significant_count = 0
    top_abs_sar:     float | None = None
    if repaired_event_ids:
        try:
            validation_payload = _safe_dict(
                _run_short_horizon_validation_on_temp_db(
                    db_path=temp_copy_path,
                )
            )
        except Exception as e:  # noqa: BLE001 — operator-visible
            errors.append(f"Short-horizon validation pipeline failed: {e}")
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
        rows_excluded, rows_retagged, mf_updates,
        repaired_event_ids,
        events_evaluated, records_count, significant_count, top_abs_sar,
    )


# ---------------------------------------------------------------------------
# Short-horizon CSV parsing
# ---------------------------------------------------------------------------


def _parse_short_horizon_csv(
    csv_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Parse the short-horizon repair packet CSV.  The packet emits
    11 columns; the smoke needs only the four that drive apply
    decisions (event_id + proposed_primary_ticker +
    proposed_mechanism_family + exclude_reason).  Other columns ride
    along untouched.

    The schema overlaps with — but is not identical to — the ticker-
    repair packet's required-column set.  ``_parse_csv_if_present``
    from the full smoke would reject this CSV because it lacks
    ``proposed_benchmark``; this helper is permissive about benchmark
    columns since the readiness pipeline only ever consults SPY.
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
                f for f in _SHORT_HORIZON_REQUIRED_FIELDS
                if f not in fieldnames
            ]
            if missing:
                errors.append(
                    f"short-horizon CSV missing required columns: "
                    f"{', '.join(missing)}"
                )
                return [], errors, warnings
            rows = []
            for raw in reader:
                row = dict(raw)
                # Synthesize a blank ``proposed_benchmark`` so the
                # reused ``_categorize_rows`` helper can read it
                # without crashing.  The readiness pipeline only
                # consults SPY, so an empty benchmark string is the
                # right default for short-horizon retags.
                row.setdefault("proposed_benchmark", "")
                rows.append(row)
    except OSError as e:
        errors.append(f"Failed to read short-horizon CSV {csv_path}: {e}")
        return [], errors, warnings
    return rows, errors, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ready_event_ids_from_payload(payload: dict[str, Any]) -> set[int]:
    """Pull the short-horizon-ready event_id set from the readiness
    report's ``examples`` list.  Only events whose ``ready_1d5d`` is
    True count.
    """
    out: set[int] = set()
    examples = payload.get("examples")
    if not isinstance(examples, list):
        return out
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        if not ex.get("ready_1d5d"):
            continue
        ev_id = ex.get("event_id")
        if isinstance(ev_id, int):
            out.add(ev_id)
    return out


def _top_abs_sar(records: list[dict[str, Any]]) -> float | None:
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
    lines: list[str] = ["Short-horizon repair apply smoke", ""]
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Rows excluded:                     {report['rows_excluded']}")
    lines.append(f"Rows retagged:                     {report['rows_retagged']}")
    lines.append(
        f"Mechanism family updates:          "
        f"{report['mechanism_family_updates']}"
    )
    lines.append(
        f"Repaired short-horizon event_ids:  "
        f"{report['repaired_short_horizon_event_ids']}"
    )
    lines.append(
        f"Events evaluated (1d/5d):          {report['events_evaluated']}"
    )
    lines.append(f"Records count (1d/5d):             {report['records_count']}")
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
            "Temp-copy short-horizon repair apply + validation smoke. "
            "Applies four operator worksheets (high-priority + medium "
            "ticker repair + mechanism-family repair + short-horizon "
            "repair) to the SAME copied backup, runs the read-only "
            "1d/5d archive validation pipeline against the post-repair "
            "temp DB, and surfaces SAR / records / significant for the "
            "events that newly entered the short-horizon repaired "
            "cohort.  Conservative language only — short-horizon "
            "evidence, candidate, not proof."
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
            "--mechanism-family-csv, --short-horizon-csv."
        ),
    )
    parser.add_argument(
        "--confirm", dest="confirm", action="store_true",
        help="Required co-flag for --write.",
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help=(
            "Path to a backup of the events DB.  Required for --write. "
            "Must differ from --db-path."
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
        "--short-horizon-csv", dest="short_horizon_csv", default=None,
        help="Path to short_horizon_repair_packet.csv.",
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

    report = smoke_short_horizon_repair_apply(
        db_path=db_path,
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        mechanism_family_csv=args.mechanism_family_csv,
        short_horizon_csv=args.short_horizon_csv,
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

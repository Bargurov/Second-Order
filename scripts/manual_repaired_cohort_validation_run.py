#!/usr/bin/env python3
"""Temp-copy manual-aware repaired cohort validation runner.

Applies the operator-completed manual ticker repair worksheets
(``manual_ticker_repair_high_priority.csv`` +
``manual_ticker_repair_medium_production_like.csv``) to a *copied*
backup of the events DB, then runs the existing read-only statistical
validation pipeline against the temp DB and surfaces SAR / CI / p /
FDR for the repaired cohort only — events that NEWLY entered the
manual-aware adjusted clean set thanks to the repair.

The runner is intentionally narrow.  Pre-existing clean events stay
out of the cohort; events that remain contaminated stay out; only the
operator-repaired candidates appear in ``records`` / ``examples``.
The aim is a tiny, defensible pilot — "repaired cohort evidence,"
"candidate," never "proof."

Operating model
---------------

* Live ``--db-path`` is hashed read-only before/after the run; never
  opened for writes.
* The input ``--backup-path`` is hashed read-only before/after; never
  opened for writes either.
* All mutations happen on a fresh copy in ``tempfile.gettempdir()``.

Order of operations::

    1. validate inputs (--backup-path, --high-priority-csv,
       --medium-csv must exist).
    2. hash live DB + input backup.
    3. parse + categorize both CSVs.
    4. extract CSV-driven mechanism_family decisions
       (medium overrides high on conflict).
    5. plan per-ticker price-cache fetch windows for the combined
       retag rows.
    6. fail closed if retag rows exist + provider unavailable
       (BEFORE copy — don't waste a temp file).
    7. copy backup → temp_copy_path.
    8. schema checks on the temp copy:
         * low_signal column required when exclusions exist.
         * mechanism_family column required when decisions exist.
       Either miss → fail closed; no apply, no backfill.
    9. snapshot pre-repair clean_fully_ready_event_ids.
   10. apply categorized rows (exclusions + retags).
   11. apply mechanism_family decisions.
   12. backfill price_cache for retag tickers.
   13. snapshot post-repair clean cohort payload, compute the
       manual-aware adjusted set + remaining contamination reasons.
   14. compute repaired_clean_event_ids =
        adjusted_after - before_clean.
   15. invoke the validation pipeline on the temp DB.
   16. filter records / examples / aggregates to the repaired set.
   17. re-hash live DB + input backup; surface drift as errors.

Reused helpers (imported from the existing smokes — NOT
re-implemented here)::

    scripts.manual_ticker_repair_apply_smoke._apply_categorized_to_temp
    scripts.manual_ticker_repair_apply_smoke._categorize_rows
    scripts.manual_ticker_repair_apply_smoke._has_low_signal_column
    scripts.manual_ticker_price_backfill_smoke._insert_ticker_rows_into_temp
    scripts.manual_ticker_price_backfill_smoke._plan_per_ticker_windows
    scripts.manual_ticker_repair_full_smoke._apply_mechanism_family_decisions
    scripts.manual_ticker_repair_full_smoke._compute_manual_aware_clean_metrics
    scripts.manual_ticker_repair_full_smoke._copy_to_fresh_temp
    scripts.manual_ticker_repair_full_smoke._extract_csv_mechanism_family_decisions
    scripts.manual_ticker_repair_full_smoke._has_mechanism_family_column
    scripts.manual_ticker_repair_full_smoke._hash_file_safe
    scripts.manual_ticker_repair_full_smoke._hashes_match
    scripts.manual_ticker_repair_full_smoke._operator_excluded_ids_from_categorized
    scripts.manual_ticker_repair_full_smoke._parse_csv_if_present

Patchable seams (local to this module so tests patch a single
surface)::

    * ``_run_clean_cohort_report``      — wraps clean cohort report.
    * ``_check_provider_available``     — soft import-only probe.
    * ``_fetch_ticker_rows``            — would shell out to yfinance.
    * ``_run_validation_on_temp_db``    — wraps the read-only archive
      validation runner against the temp DB.

Output contract::

    {
      "ok":                       bool,
      "repaired_clean_event_ids": [int, ...],
      "events_evaluated":         int,
      "records_count":            int,
      "significant_count":        int,
      "by_horizon":               {str: {...}},
      "by_mechanism_family":      {str: {...}},
      "examples":                 [{...}, ...],
      "excluded_event_ids":       [int, ...],
      "remaining_blockers":       {str: [str, ...]},
      "live_db_unchanged":        bool,
      "input_backup_unchanged":   bool,
      "errors":                   [str, ...],
      "warnings":                 [str, ...],
    }

Each example carries::

    event_id, headline, primary_ticker, benchmark, mechanism_family,
    horizon, abnormal_return, sar, ci_low, ci_high, p_value, fdr_q,
    interpretation

Out of scope (deliberately)
---------------------------
* Live DB never opened for writes.
* Input backup never opened for writes.
* No LLM, no FastAPI surface — never imports ``api`` or ``routes.*``.
* No ``--write`` / ``--confirm`` flags — the temp copy is implicit;
  the runner's purpose IS to mutate-on-temp-then-validate.

Usage::

    python scripts/manual_repaired_cohort_validation_run.py --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --limit 50
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Reused pure helpers from the sibling smokes.  Each smoke uses lazy
# imports inside its seams, so importing the modules here does NOT
# pull yfinance / readiness / contamination / clean-cohort.
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


_DEFAULT_LIMIT:       int   = 50
_DEFAULT_ALPHA:       float = 0.05
_DEFAULT_N_BOOTSTRAP: int   = 500
_DEFAULT_SEED:        int   = 42

_BENCHMARK_TICKER:                str = "SPY"
_DUPLICATE_COUNTERPART_FLAG:      str = "duplicate_date_ticker"
_SCHEMA_MISSING_TOKEN:            str = "schema_missing_exclusion_field"
_SCHEMA_MISSING_MF_TOKEN:         str = "schema_missing_mechanism_family_field"


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  Lazy imports fire only on the un-patched path.
# ---------------------------------------------------------------------------


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the clean-cohort report with an effectively unlimited
    per-row cap so the manual-aware adjustment sees every contaminated
    example.  A smaller cap would silently drop repaired rows from the
    adjustment input.
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

    Production calls ``yfinance.download``; tests MUST patch this seam
    — the runner has no environment that would tolerate a real network
    call.
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


def _run_validation_on_temp_db(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the read-only archive validation runner against the
    given DB path and return its full payload, enriched with a
    ``records`` key the outer runner uses for filtering / aggregation.

    The archive runner emits ``examples`` (capped at ``limit``) but
    not a parallel ``records`` list — and its examples carry neither
    ``mechanism_family`` nor ``statistically_significant``.  The seam
    keeps the archive runner untouched and instead:

    * passes ``limit = 10**9`` so EVERY per-(event, horizon) record
      lands in ``examples`` (no truncation);
    * looks up ``mechanism_family`` from the temp DB events table;
    * re-derives ``statistically_significant`` from ``fdr_q`` and the
      pipeline's default alpha (the same predicate
      ``stats.stat_validation.is_statistically_significant`` uses).

    Tests patch this seam directly with a synthetic payload, so the
    enrichment logic only runs on the un-patched path.
    """
    from scripts.archive_stat_validation_run import (
        run_archive_stat_validation,
    )
    from stats.stat_validation import (
        DEFAULT_ALPHA, is_statistically_significant,
    )

    payload = run_archive_stat_validation(db_path=db_path, limit=10**9)
    examples = payload.get("examples") or []
    family_by_id = _mechanism_family_by_event_id(db_path)

    records: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        ev_id = ex.get("event_id")
        records.append({
            "event_id":        ev_id,
            "headline":        ex.get("headline"),
            "ticker":          ex.get("ticker"),
            "horizon":         ex.get("horizon"),
            "abnormal_return": ex.get("abnormal_return"),
            "sar":             ex.get("sar"),
            "ci_low":          ex.get("ci_low"),
            "ci_high":         ex.get("ci_high"),
            "p_value":         ex.get("p_value"),
            "fdr_q":           ex.get("fdr_q"),
            "interpretation":  ex.get("interpretation"),
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


def _mechanism_family_by_event_id(
    db_path: str | None,
) -> dict[int, str | None]:
    """Read ``{event_id: mechanism_family}`` from a SQLite DB.  Returns
    an empty dict on any read error — callers treat the absence as
    ``None`` mechanism_family.
    """
    out: dict[int, str | None] = {}
    if not db_path:
        return out
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return out
    try:
        try:
            rows = conn.execute(
                "SELECT id, mechanism_family FROM events"
            ).fetchall()
        except sqlite3.Error:
            return out
        for row in rows:
            try:
                ev_id = int(row[0])
            except (TypeError, ValueError, IndexError):
                continue
            family = row[1] if len(row) > 1 else None
            if isinstance(family, str) and family and family != "none":
                out[ev_id] = family
            else:
                out[ev_id] = None
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_manual_repaired_cohort_validation(
    *,
    backup_path:        str | None     = None,
    high_priority_csv:  str | None     = None,
    medium_csv:         str | None     = None,
    db_path:            str | None     = None,
    limit:              int            = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the temp-copy repaired-cohort validation.  Returns the
    14-key payload described in the module docstring.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    capped_limit = max(int(limit), 0)

    repaired_clean_event_ids: list[int] = []
    excluded_event_ids:       list[int] = []
    remaining_blockers:       dict[str, list[str]] = {}
    examples:                 list[dict[str, Any]] = []
    records:                  list[dict[str, Any]] = []
    by_horizon:               dict[str, Any] = {}
    by_mechanism_family:      dict[str, Any] = {}
    events_evaluated:         int = 0
    records_count:            int = 0
    significant_count:        int = 0

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    # Step 1: validate inputs.
    if not backup_path:
        errors.append("--backup-path is required")
    elif not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
    if not high_priority_csv:
        errors.append("--high-priority-csv is required")
    elif not Path(high_priority_csv).exists():
        errors.append(
            f"--high-priority-csv does not exist: {high_priority_csv}"
        )
    if not medium_csv:
        errors.append("--medium-csv is required")
    elif not Path(medium_csv).exists():
        errors.append(f"--medium-csv does not exist: {medium_csv}")
    if errors:
        return _envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            live_db_unchanged=_hashes_match(
                before=live_hash_before, after=_hash_file_safe(db_path),
                path=db_path),
            input_backup_unchanged=_hashes_match(
                before=backup_hash_before,
                after=_hash_file_safe(backup_path), path=backup_path),
            errors=errors, warnings=warnings,
        )

    # Step 3: parse + categorize both CSVs.
    high_rows, parse_errs_h, parse_warns_h = _parse_csv_if_present(
        high_priority_csv,
    )
    errors.extend(parse_errs_h)
    warnings.extend(parse_warns_h)
    medium_rows, parse_errs_m, parse_warns_m = _parse_csv_if_present(
        medium_csv,
    )
    errors.extend(parse_errs_m)
    warnings.extend(parse_warns_m)

    high_categorized = _categorize_rows(high_rows, errors, warnings)
    medium_categorized = _categorize_rows(medium_rows, errors, warnings)
    all_categorized = list(high_categorized) + list(medium_categorized)

    # Step 4: CSV-driven mechanism_family decisions; medium overrides
    # high on conflict (last write wins) — mirrors the smoke pattern.
    high_mf = _extract_csv_mechanism_family_decisions(high_rows)
    medium_mf = _extract_csv_mechanism_family_decisions(medium_rows)
    decisions: dict[int, str] = {**high_mf, **medium_mf}

    # Step 5: combined fetch plan.
    plan = _plan_per_ticker_windows(
        list(high_rows) + list(medium_rows), warnings,
    )

    excluded_event_ids = _operator_excluded_ids_from_categorized(
        all_categorized,
    )

    has_exclusions = any(r["kind"] == "exclude" for r in all_categorized)
    has_retags     = any(r["kind"] == "retag"   for r in all_categorized)
    has_decisions  = bool(decisions)

    # Step 6: provider check BEFORE copy.  Fail-closed precedence: if
    # retag rows need backfill but yfinance isn't importable, the run
    # fails — apply phase doesn't run either.
    if has_retags and not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing; retag rows require a price-cache "
            "backfill which cannot run"
        )
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    # Step 7: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 8: schema checks on the temp copy.  Fail-closed precedence
    # mirrors the full smoke — partial apply on a fail-closed signal
    # is a foot-gun.
    if has_exclusions and not _has_low_signal_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_TOKEN}: temp DB lacks 'low_signal' "
            f"column — refusing to apply any rows"
        )
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )
    if has_decisions and not _has_mechanism_family_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_MF_TOKEN}: temp DB lacks "
            f"'mechanism_family' column — refusing to apply any rows "
            f"or decisions"
        )
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    # Step 9: pre-repair clean cohort snapshot.
    try:
        before_clean_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Pre-apply clean-cohort report failed: {e}")
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )
    before_clean_ids: set[int] = _event_ids_from_payload(before_clean_payload)

    # Step 10: apply categorized rows.
    try:
        _apply_categorized_to_temp(
            temp_copy_path, all_categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB apply failed: {e}")
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    # Step 11: apply mechanism_family decisions.
    try:
        _apply_mechanism_family_decisions(
            temp_copy_path, decisions, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB mechanism-family apply failed: {e}")
        return _final_envelope(
            ok=False, repaired_clean_event_ids=repaired_clean_event_ids,
            events_evaluated=events_evaluated,
            records_count=records_count,
            significant_count=significant_count,
            by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
            examples=examples, excluded_event_ids=excluded_event_ids,
            remaining_blockers=remaining_blockers,
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    # Step 12: backfill price_cache for retag tickers.
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

    # Step 13: post-repair clean cohort + manual-aware adjustment.
    try:
        after_clean_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Post-apply clean-cohort report failed: {e}")
        after_clean_payload = {}
    operator_excluded_set = set(excluded_event_ids)
    manual_aware = _compute_manual_aware_clean_metrics(
        after_clean_payload=after_clean_payload,
        operator_excluded_ids=operator_excluded_set,
    )
    remaining_blockers = manual_aware.get("remaining_contamination_reasons") or {}

    # Step 14: repaired_clean_event_ids = adjusted_after - before_clean.
    adjusted_after_ids = _adjusted_clean_event_ids(
        after_clean_payload=after_clean_payload,
        operator_excluded_ids=operator_excluded_set,
    )
    repaired_set = adjusted_after_ids - before_clean_ids
    repaired_clean_event_ids = sorted(repaired_set)

    # Step 15: validation pipeline.
    if repaired_clean_event_ids:
        try:
            validation_payload = _safe_dict(
                _run_validation_on_temp_db(db_path=temp_copy_path)
            )
        except Exception as e:  # noqa: BLE001 — operator-visible
            errors.append(f"Validation pipeline failed: {e}")
            validation_payload = {}

        # Step 16: filter records / examples / aggregates to the
        # repaired cohort only.
        all_records = validation_payload.get("records") or []
        repaired_records = [
            r for r in all_records
            if isinstance(r, dict)
            and isinstance(r.get("event_id"), int)
            and r["event_id"] in repaired_set
        ]
        records = repaired_records
        records_count = len(repaired_records)
        events_evaluated = len({
            r["event_id"] for r in repaired_records
            if isinstance(r.get("event_id"), int)
        })
        significant_count = sum(
            1 for r in repaired_records
            if r.get("statistically_significant")
        )
        by_horizon = _aggregate_by_horizon(repaired_records)
        by_mechanism_family = _aggregate_by_mechanism_family(repaired_records)

        # Examples: enrich with primary_ticker / benchmark /
        # mechanism_family.  The underlying validation pipeline emits
        # ``ticker`` and no benchmark column — we map ``ticker`` →
        # ``primary_ticker`` and hardcode SPY (the project's universal
        # benchmark) so operators see the full per-record drill-in.
        sorted_records = sorted(
            repaired_records,
            key=lambda rec: (rec.get("event_id", 0),
                             rec.get("horizon", 0)),
        )
        for rec in sorted_records[:capped_limit]:
            examples.append({
                "event_id":         rec.get("event_id"),
                "headline":         rec.get("headline"),
                "primary_ticker":   rec.get("ticker"),
                "benchmark":        _BENCHMARK_TICKER,
                "mechanism_family": rec.get("mechanism_family"),
                "horizon":          rec.get("horizon"),
                "abnormal_return":  rec.get("abnormal_return"),
                "sar":              rec.get("sar"),
                "ci_low":           rec.get("ci_low"),
                "ci_high":          rec.get("ci_high"),
                "p_value":          rec.get("p_value"),
                "fdr_q":            rec.get("fdr_q"),
                "interpretation":   rec.get("interpretation"),
            })
        # Surface validation pipeline errors so the operator sees them.
        for e in validation_payload.get("errors") or []:
            if isinstance(e, str) and e:
                errors.append(f"validation: {e}")

    # Hash invariants.
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
            f"LIVE DB BYTES CHANGED during validation run — "
            f"investigate: {db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during validation run — "
            f"investigate: {backup_path}"
        )

    return _envelope(
        ok=not errors, repaired_clean_event_ids=repaired_clean_event_ids,
        events_evaluated=events_evaluated, records_count=records_count,
        significant_count=significant_count,
        by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
        examples=examples, excluded_event_ids=excluded_event_ids,
        remaining_blockers=remaining_blockers,
        live_db_unchanged=live_db_unchanged,
        input_backup_unchanged=input_backup_unchanged,
        errors=errors, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Helpers — local to this module
# ---------------------------------------------------------------------------


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _event_ids_from_payload(payload: dict[str, Any]) -> set[int]:
    raw = payload.get("clean_fully_ready_event_ids")
    out: set[int] = set()
    if isinstance(raw, list):
        for i in raw:
            if isinstance(i, int):
                out.add(i)
    return out


def _adjusted_clean_event_ids(
    *, after_clean_payload: dict[str, Any],
    operator_excluded_ids: set[int],
) -> set[int]:
    """Mirror the line-arithmetic in
    ``_compute_manual_aware_clean_metrics`` but return the actual
    event_id set (not just the count): raw clean minus operator-
    excluded plus events whose ONLY contamination flag is
    ``duplicate_date_ticker``.
    """
    raw_ids = _event_ids_from_payload(after_clean_payload)
    promoted: set[int] = set()
    excluded_examples = after_clean_payload.get("excluded_fully_ready_examples")
    if isinstance(excluded_examples, list):
        for entry in excluded_examples:
            if not isinstance(entry, dict):
                continue
            ev_id = entry.get("event_id")
            if not isinstance(ev_id, int):
                continue
            if ev_id in operator_excluded_ids:
                continue
            flags_raw = entry.get("flags")
            if not isinstance(flags_raw, list):
                continue
            flag_set = {f for f in flags_raw if isinstance(f, str)}
            if flag_set == {_DUPLICATE_COUNTERPART_FLAG}:
                promoted.add(ev_id)
    return (raw_ids - operator_excluded_ids) | promoted


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        h = rec.get("horizon")
        if not isinstance(h, int):
            continue
        block = out.setdefault(str(h), {
            "records_count":     0,
            "significant_count": 0,
        })
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    seen_events: dict[str, set[int]] = {}
    for rec in records:
        family = rec.get("mechanism_family")
        if not isinstance(family, str) or not family:
            continue
        block = out.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        ev_id = rec.get("event_id")
        if isinstance(ev_id, int):
            seen = seen_events.setdefault(family, set())
            if ev_id not in seen:
                seen.add(ev_id)
                block["events_evaluated"] += 1
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _envelope(*, ok: bool,
              repaired_clean_event_ids: list[int],
              events_evaluated: int, records_count: int,
              significant_count: int,
              by_horizon: dict[str, Any],
              by_mechanism_family: dict[str, Any],
              examples: list[dict[str, Any]],
              excluded_event_ids: list[int],
              remaining_blockers: dict[str, Any],
              live_db_unchanged: bool, input_backup_unchanged: bool,
              errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return {
        "ok":                       ok,
        "repaired_clean_event_ids": repaired_clean_event_ids,
        "events_evaluated":         events_evaluated,
        "records_count":            records_count,
        "significant_count":        significant_count,
        "by_horizon":               by_horizon,
        "by_mechanism_family":      by_mechanism_family,
        "examples":                 examples,
        "excluded_event_ids":       excluded_event_ids,
        "remaining_blockers":       remaining_blockers,
        "live_db_unchanged":        live_db_unchanged,
        "input_backup_unchanged":   input_backup_unchanged,
        "errors":                   errors,
        "warnings":                 warnings,
    }


def _final_envelope(*,
                    ok: bool,
                    repaired_clean_event_ids: list[int],
                    events_evaluated: int, records_count: int,
                    significant_count: int,
                    by_horizon: dict[str, Any],
                    by_mechanism_family: dict[str, Any],
                    examples: list[dict[str, Any]],
                    excluded_event_ids: list[int],
                    remaining_blockers: dict[str, Any],
                    db_path: str | None, backup_path: str | None,
                    live_hash_before: str | None,
                    backup_hash_before: str | None,
                    errors: list[str], warnings: list[str]) -> dict[str, Any]:
    """Build the envelope after recomputing hash invariants — used on
    every fail-closed exit path so live + backup byte-identity is
    surfaced even when the run aborted."""
    live_hash_after   = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)
    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after, path=backup_path,
    )
    return _envelope(
        ok=ok and not errors,
        repaired_clean_event_ids=repaired_clean_event_ids,
        events_evaluated=events_evaluated, records_count=records_count,
        significant_count=significant_count,
        by_horizon=by_horizon, by_mechanism_family=by_mechanism_family,
        examples=examples, excluded_event_ids=excluded_event_ids,
        remaining_blockers=remaining_blockers,
        live_db_unchanged=live_db_unchanged,
        input_backup_unchanged=input_backup_unchanged,
        errors=errors, warnings=warnings,
    )


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
    lines: list[str] = ["Manual repaired cohort validation run", ""]
    lines.append(f"OK:                         {report['ok']}")
    lines.append(
        f"Repaired clean event_ids:   "
        f"{report['repaired_clean_event_ids']}"
    )
    lines.append(f"Events evaluated:           {report['events_evaluated']}")
    lines.append(f"Records count:              {report['records_count']}")
    lines.append(f"Significant count:          {report['significant_count']}")
    lines.append(
        f"Excluded event_ids:         {report['excluded_event_ids']}"
    )
    lines.append(
        f"Live DB unchanged:          {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:     {report['input_backup_unchanged']}"
    )

    by_h = report.get("by_horizon") or {}
    if by_h:
        lines.append("")
        lines.append("Per horizon:")
        for h_key in sorted(by_h.keys(), key=lambda x: int(x)):
            block = by_h[h_key]
            lines.append(
                f"  h={h_key:>3}  records={block.get('records_count', 0):>4} "
                f"significant={block.get('significant_count', 0):>4}"
            )

    fam_block = report.get("by_mechanism_family") or {}
    if fam_block:
        lines.append("")
        lines.append("Per mechanism_family:")
        for family in sorted(fam_block.keys()):
            stats = fam_block[family]
            lines.append(
                f"  {family:<30} events={stats.get('events_evaluated', 0):>3} "
                f"records={stats.get('records_count', 0):>4} "
                f"significant={stats.get('significant_count', 0):>4}"
            )

    examples = report.get("examples") or []
    if examples:
        lines.append("")
        lines.append(f"Examples ({len(examples)}):")
        for ex in examples:
            headline = (ex.get("headline") or "").strip() or "-"
            if len(headline) > 70:
                headline = headline[:67] + "..."
            lines.append(
                f"  id={ex.get('event_id')} h={_fmt(ex.get('horizon'))} "
                f"{ex.get('primary_ticker') or '-'}/{ex.get('benchmark') or '-'} "
                f"family={ex.get('mechanism_family') or '-'} "
                f"AR={_fmt(ex.get('abnormal_return'))} "
                f"SAR={_fmt(ex.get('sar'))} "
                f"CI=[{_fmt(ex.get('ci_low'))}, {_fmt(ex.get('ci_high'))}] "
                f"p={_fmt(ex.get('p_value'))} fdr_q={_fmt(ex.get('fdr_q'))} "
                f"interp={ex.get('interpretation')}"
            )
            lines.append(f"      headline: {headline}")

    if report.get("remaining_blockers"):
        lines.append("")
        lines.append("Remaining blockers:")
        for ev_id_str, flags in sorted(report["remaining_blockers"].items()):
            lines.append(f"  id={ev_id_str}  flags={flags}")

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
            "Temp-copy manual-aware repaired cohort validation runner. "
            " Applies both manual ticker repair worksheets to a copied "
            "backup, runs the read-only statistical validation pipeline "
            "against the temp DB, and surfaces SAR/CI/p/FDR for the "
            "events that newly entered the manual-aware adjusted clean "
            "cohort.  Live DB and input backup are byte-identical "
            "before and after the run.  Conservative language only — "
            "this is repaired cohort evidence, not proof."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None, required=False,
        help=(
            "Path to a backup of the events DB.  Required.  Must "
            "differ from --db-path."
        ),
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv",
        default=None, required=False,
        help=(
            "Path to the high-priority manual ticker repair CSV "
            "(``manual_ticker_repair_high_priority.csv``)."
        ),
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None, required=False,
        help=(
            "Path to the medium-batch manual ticker repair CSV "
            "(``manual_ticker_repair_medium_production_like.csv``)."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Hashed read-only "
            "before and after the run; never opened for writes.  "
            "Defaults to db.DB_FILE so the runner follows the project's "
            "configured archive."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced examples list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect every "
            f"evaluated repaired event."
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

    report = run_manual_repaired_cohort_validation(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        db_path=db_path,
        limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

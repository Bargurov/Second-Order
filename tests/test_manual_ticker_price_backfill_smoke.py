"""Tests for ``scripts/manual_ticker_price_backfill_smoke.py``.

Pin the contract:

* Default mode is ``dry-run`` — no copy, no apply, no DB writes,
  no provider call, no readiness/contamination/clean-cohort
  imports.
* Write mode requires ALL of ``--write --confirm --backup-path
  --csv-path``; any missing flag → fail closed.
* Live ``--db-path`` is hashed read-only before/after the smoke
  and must be byte-identical; same invariant for the input
  ``--backup-path``.  Both invariants hold even on every fail-
  closed path (no retag rows, provider unavailable, fetch
  failure, write failure).
* Per-ticker plan: window is
  ``[min(event_dates) - 60bd, max(event_dates) + 20bd]`` for
  each unique proposed_primary_ticker.
* ``tickers_planned`` is surfaced even on fail-closed paths so
  the operator can see what *would* have been fetched.
* ``price_rows_planned`` is the sum across tickers of business
  days in each merged window.
* If the CSV has no retag rows (only exclusions / empty), the
  run fails closed BEFORE provider check.
* If yfinance is unavailable, the run fails closed AFTER
  planning so ``tickers_planned`` reflects the would-have set.
* Output dict carries EXACTLY the 15 brief-mandated keys.
* Reports run after temp-copy write through patchable seams
  so unit tests never hit the real readiness pipeline.
* Provider seams (``_check_provider_available`` and
  ``_fetch_ticker_rows``) are patchable so tests never hit the
  network.
"""
from __future__ import annotations

import csv as csv_module
import datetime as _dt
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_ticker_price_backfill_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "mode",
    "rows_read",
    "tickers_planned",
    "price_rows_planned",
    "price_rows_written",
    "before_clean_fully_ready",
    "after_clean_fully_ready",
    "clean_fully_ready_delta",
    "before_contaminated_fully_ready",
    "after_contaminated_fully_ready",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)


# ---------------------------------------------------------------------------
# On-disk fixtures
# ---------------------------------------------------------------------------


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    low_signal      INTEGER DEFAULT 0
)
""".strip()


def _make_temp_db(suffix: str = "price_smoke") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_csv(rows: list[dict], *, suffix: str = "price_csv",
               include_header: bool = True) -> str:
    columns = (
        "event_id", "headline", "event_date", "current_primary_ticker",
        "flags", "reason", "manual_review_priority",
        "proposed_primary_ticker", "proposed_benchmark",
        "ticker_rationale", "exclude_reason",
    )
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        if include_header:
            writer.writerow(columns)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in columns])
    return path


def _csv_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    exclude_reason: str = "",
    event_date: str = "2026-04-06",
    headline: str = "h",
) -> dict:
    return {
        "event_id":                 event_id,
        "headline":                 headline,
        "event_date":               event_date,
        "current_primary_ticker":   "DRIV",
        "flags":                    "",
        "reason":                   "contaminated_fully_ready",
        "manual_review_priority":   "high",
        "proposed_primary_ticker":  proposed_primary_ticker,
        "proposed_benchmark":       proposed_benchmark,
        "ticker_rationale":         "",
        "exclude_reason":           exclude_reason,
    }


def _spy_row(date_iso: str, *, close: float = 100.0,
             volume: float = 1.0e6) -> dict:
    return {"date": date_iso, "close": close, "volume": volume}


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _clean_payload(*, count: int) -> dict:
    return {"clean_fully_ready_count": count}


def _contam_payload(*, suspicious: int) -> dict:
    return {"suspicious_count": suspicious}


def _patch_seams(
    *,
    clean_before: int = 0,
    clean_after: int | None = None,
    contam_before: int = 0,
    contam_after: int | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
):
    clean_after = clean_after if clean_after is not None else clean_before
    contam_after = contam_after if contam_after is not None else contam_before
    clean_calls = iter([
        _clean_payload(count=clean_before),
        _clean_payload(count=clean_after),
    ])
    contam_calls = iter([
        _contam_payload(suspicious=contam_before),
        _contam_payload(suspicious=contam_after),
    ])

    def fake_clean(*, db_path):
        return next(clean_calls)

    def fake_contam(*, db_path):
        return next(contam_calls)

    def fake_readiness(*, db_path):
        return {"total_events": 0, "events_fully_ready": 0}

    if fetch_side_effect is not None:
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fetch_side_effect)
    else:
        rows = fetch_rows if fetch_rows is not None else []

        def fake_fetch(*, ticker, start, end):
            return rows
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fake_fetch)

    return (
        patch.object(cli, "_run_clean_cohort_report",  side_effect=fake_clean),
        patch.object(cli, "_run_contamination_report", side_effect=fake_contam),
        patch.object(cli, "_run_readiness_report",     side_effect=fake_readiness),
        patch.object(cli, "_check_provider_available", return_value=provider_available),
        fetch_patch,
    )


def _run(*, csv_path: str | None = None, **kwargs) -> dict:
    return cli.smoke_price_backfill(csv_path=csv_path, **kwargs)


def _cleanup_temp_copy(result: dict) -> None:
    for w in result.get("warnings", []):
        if "Temp copy at " in w:
            p = w.split("Temp copy at ", 1)[1].strip()
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_dry_run_returns_dict_with_exactly_15_keys(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_no_additive_fields_on_write_mode(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-03-01"), _spy_row("2026-04-10")])
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Default dry-run
# ---------------------------------------------------------------------------


class TestDryRunDefault(unittest.TestCase):
    def test_default_mode_is_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mode"], "dry-run")

    def test_dry_run_does_not_call_provider_or_reports(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report") as clean:
                        with patch.object(cli, "_run_contamination_report") as contam:
                            with patch.object(cli, "_run_readiness_report") as ready:
                                _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertFalse(check.called)
        self.assertFalse(fetch.called)
        self.assertFalse(clean.called)
        self.assertFalse(contam.called)
        self.assertFalse(ready.called)

    def test_dry_run_before_after_are_null(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["before_clean_fully_ready"])
        self.assertIsNone(result["after_clean_fully_ready"])
        self.assertIsNone(result["clean_fully_ready_delta"])
        self.assertIsNone(result["before_contaminated_fully_ready"])
        self.assertIsNone(result["after_contaminated_fully_ready"])

    def test_dry_run_plans_per_unique_ticker(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
            _csv_row(event_id=2, proposed_primary_ticker="MS",
                     event_date="2026-04-08"),
            _csv_row(event_id=3, proposed_primary_ticker="JPM",
                     event_date="2026-04-10"),
            _csv_row(event_id=4, exclude_reason="off-topic"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_read"], 4)
        self.assertEqual(result["tickers_planned"], 2)  # MS + JPM
        # price_rows_planned = sum of merged-window business days per ticker.
        # Both windows are [-60bd, +20bd] from event_dates; MS spans
        # 2026-04-06..2026-04-08 events, JPM is single 2026-04-10.
        # Each ticker's merged window has at least 60 + 20 = 80 bdays.
        self.assertGreater(result["price_rows_planned"], 0)


# ---------------------------------------------------------------------------
# Write-mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_rejected(self) -> None:
        result = _run(write=True, confirm=False,
                      backup_path="/tmp/x.db", csv_path="/tmp/x.csv")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["price_rows_written"], 0)
        self.assertTrue(any("--confirm" in e for e in result["errors"]))

    def test_write_without_backup_path_rejected(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True, csv_path=csv_path, backup_path=None)
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("--backup-path" in e for e in result["errors"]))

    def test_write_without_csv_path_rejected(self) -> None:
        backup = _make_temp_db("price_backup")
        try:
            result = _run(
                write=True, confirm=True, backup_path=backup, csv_path=None)
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("--csv-path" in e for e in result["errors"]))

    def test_backup_path_equals_db_path_rejected(self) -> None:
        live = _make_temp_db("price_live")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                db_path=live, backup_path=live, csv_path=csv_path)
        finally:
            os.unlink(live)
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)

    def test_backup_path_nonexistent_rejected(self) -> None:
        bogus = os.path.join(tempfile.gettempdir(),
                             f"missing_{uuid.uuid4().hex}.db")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                backup_path=bogus, csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)

    def test_csv_path_nonexistent_rejected(self) -> None:
        backup = _make_temp_db("price_backup")
        bogus_csv = os.path.join(tempfile.gettempdir(),
                                 f"nope_{uuid.uuid4().hex}.csv")
        try:
            result = _run(
                write=True, confirm=True,
                backup_path=backup, csv_path=bogus_csv)
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


class TestFailClosedNoRetagRows(unittest.TestCase):
    def test_empty_csv_fails_closed_no_temp_copy(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([])
        try:
            patches = _patch_seams(provider_available=True)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["tickers_planned"],    0)
        self.assertEqual(result["price_rows_written"], 0)
        self.assertTrue(
            any("no retag" in e.lower() or "no proposed" in e.lower()
                or "no ticker" in e.lower()
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        # No temp copy on this failure path.
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )

    def test_exclusion_only_csv_fails_closed(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        try:
            patches = _patch_seams(provider_available=True)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["tickers_planned"], 0)


class TestFailClosedProviderUnavailable(unittest.TestCase):
    def test_provider_unavailable_fails_closed_no_temp_no_write(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["price_rows_written"], 0)
        # tickers_planned IS surfaced even on this fail-closed path so
        # the operator can see what would have been fetched.
        self.assertEqual(result["tickers_planned"], 1)
        self.assertTrue(
            any("provider" in e.lower() for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )


class TestFetchFailureNoPartialWrite(unittest.TestCase):
    def test_fetch_raises_no_partial_write(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                provider_available=True,
                fetch_side_effect=RuntimeError("synthetic network error"),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["price_rows_written"], 0)
        self.assertTrue(
            any("synthetic network error" in e for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------


class TestWindowMath(unittest.TestCase):
    def test_per_ticker_merged_window(self) -> None:
        """For one ticker spanning two events, the planned window is
        ``[min(ev) - _PRE_EVENT_BDAYS, max(ev) + _FORWARD_BDAYS_MAX]``.
        """
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
            _csv_row(event_id=2, proposed_primary_ticker="MS",
                     event_date="2026-04-13"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        # Single ticker → 1 planned ticker.  Window for MS is
        # [2026-04-06 - 75bd, 2026-04-13 + 20bd].  Business-day count
        # in the merged window is 75 + 5(spread) + 20 + 1(both ends
        # inclusive) = 101.  Lower bound 95 keeps the assertion robust
        # to off-by-one drift while still pinning the holiday-safe
        # buffer (>= 60-day readiness target plus cushion).
        self.assertEqual(result["tickers_planned"], 1)
        self.assertGreaterEqual(result["price_rows_planned"], 95)

    def test_pre_event_window_pads_for_holidays(self) -> None:
        """Pin the holiday-safe buffer: planning a single Monday event
        produces a window whose Mon–Fri count is at least 95 (= 75 pre
        + 1 event day + 20 forward minus inclusive-counting slack).

        The rationale: the readiness check requires 60 distinct cache
        dates strictly before event_date.  Padding the pre-event side
        from 60 → 75 Mon–Fri days absorbs ~3 US market holidays per
        60-trading-day window without weakening the readiness check.
        """
        # 2026-04-06 is a Monday (chosen to make the bday math clean).
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        # 75 (pre) + 1 (event) + 20 (forward) = 96 Mon-Fri days.
        # Allow off-by-one slack on either side.
        self.assertEqual(result["tickers_planned"], 1)
        self.assertGreaterEqual(result["price_rows_planned"], 95)
        self.assertLessEqual(result["price_rows_planned"], 97)
        # Pin the constant directly so a regression that drops the
        # buffer is caught at unit-test time.
        self.assertGreaterEqual(cli._PRE_EVENT_BDAYS, 75,
                                "_PRE_EVENT_BDAYS must stay >= 75 "
                                "to absorb US market holidays")

    def test_business_day_offset_helper(self) -> None:
        # Sanity-check the helper used to compute the window.
        d = _dt.date(2026, 4, 6)  # Monday
        # 5 business days forward from Monday = next Monday.
        out = cli._business_day_offset(d, 5)
        self.assertEqual(out, _dt.date(2026, 4, 13))
        # 5 business days backward.
        out_back = cli._business_day_offset(d, -5)
        self.assertEqual(out_back, _dt.date(2026, 3, 30))


# ---------------------------------------------------------------------------
# Apply mutates temp DB only
# ---------------------------------------------------------------------------


class TestApplyMutatesTempOnly(unittest.TestCase):
    def test_fetched_rows_inserted_into_temp_price_cache(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(
                fetch_rows=[
                    _spy_row("2026-03-01"),
                    _spy_row("2026-04-10"),
                ],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            backup_after = _sha256(backup)
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            self.assertTrue(os.path.exists(tcp))
            # Backup byte-identical.
            self.assertEqual(backup_before, backup_after)
            # Temp DB has the two MS rows.
            conn = sqlite3.connect(tcp)
            try:
                rows = conn.execute(
                    "SELECT date FROM price_cache "
                    "WHERE ticker = 'MS' ORDER BY date"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual([r[0] for r in rows], ["2026-03-01", "2026-04-10"])
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["price_rows_written"], 2)


# ---------------------------------------------------------------------------
# Hash invariants on every fail path
# ---------------------------------------------------------------------------


class TestHashInvariantsAllPaths(unittest.TestCase):
    def test_no_retag_rows_keeps_hashes(self) -> None:
        live = _make_temp_db("price_live")
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(live_before,   live_after)
        self.assertEqual(backup_before, backup_after)
        self.assertIs(result["live_db_unchanged"],     True)
        self.assertIs(result["input_backup_unchanged"], True)

    def test_provider_unavailable_keeps_hashes(self) -> None:
        live = _make_temp_db("price_live")
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(live_before,   live_after)
        self.assertEqual(backup_before, backup_after)

    def test_write_mode_success_keeps_live_and_backup_hashes(self) -> None:
        live = _make_temp_db("price_live")
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(live_before,   live_after)
        self.assertEqual(backup_before, backup_after)


# ---------------------------------------------------------------------------
# Before/after counts wired through report seams
# ---------------------------------------------------------------------------


class TestBeforeAfterCounts(unittest.TestCase):
    def test_counts_wired_to_clean_and_contam_seams(self) -> None:
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                clean_before=10, clean_after=11,
                contam_before=7, contam_after=6,
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(result["before_clean_fully_ready"],         10)
        self.assertEqual(result["after_clean_fully_ready"],          11)
        self.assertEqual(result["clean_fully_ready_delta"],           1)
        self.assertEqual(result["before_contaminated_fully_ready"],   7)
        self.assertEqual(result["after_contaminated_fully_ready"],    6)

    def test_truthful_zero_delta_against_un_retagged_backup(self) -> None:
        """Pinning the truthful behavior: backfilling MS price data
        against an un-retagged backup (event 46 still uses DRIV)
        yields ``clean_fully_ready_delta == 0``.  The reports are
        unchanged because no event has MS as primary in this temp
        copy.  This script does NOT retag — it backfills only.
        """
        backup = _make_temp_db("price_backup")
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                clean_before=0, clean_after=0,
                contam_before=11, contam_after=11,
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(result["clean_fully_ready_delta"], 0)
        self.assertEqual(result["before_contaminated_fully_ready"],
                         result["after_contaminated_fully_ready"])


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_clean_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_contamination_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_contamination_report")))

    def test_readiness_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_readiness_report")))

    def test_check_provider_available_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_ticker_rows_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_default_dry_run_does_not_import_provider_or_fastapi(
        self,
    ) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        csv_path = _write_csv([])
        try:
            cli.smoke_price_backfill(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _cli(self, argv: list[str], **patch_kwargs) -> tuple[int, str]:
        out = StringIO()
        patches = _patch_seams(**patch_kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            try:
                rc = cli.main(argv, out=out)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()

    def test_dry_run_default_emits_parseable_json(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_no_flag_defaults_to_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_write_without_confirm_fails(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--write", "--backup-path", "/tmp/x.db",
                "--csv-path", csv_path, "--json",
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertIs(parsed["ok"], False)


if __name__ == "__main__":
    unittest.main()

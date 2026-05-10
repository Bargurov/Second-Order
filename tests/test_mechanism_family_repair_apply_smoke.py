"""Tests for ``scripts/mechanism_family_repair_apply_smoke.py``.

Pin the contract:

* Operates on a copied backup only — live DB is read-only,
  byte-identical before/after every run.
* Consumes THREE CSVs and applies them to the SAME temp DB in
  this fixed order:
    1. ``manual_ticker_repair_high_priority.csv``
    2. ``manual_ticker_repair_medium_production_like.csv``
    3. ``mechanism_family_repair_packet.csv``
  The high / medium CSVs may carry retags + exclusions + CSV-driven
  mechanism_family decisions; the mechanism-family CSV is
  exclude/decision-only (no retags).
* Apply order on the temp DB:
    1. Categorize rows from all three CSVs (exclude / retag / no-op).
    2. Apply categorized rows (low_signal=1 for excludes; market_tickers
       JSON update for retags).
    3. Apply CSV-driven mechanism_family decisions (later CSV wins on
       conflict — mirrors the manual_repaired_cohort_validation_run
       merge pattern).
    4. Backfill price_cache for retag tickers via the provider seam.
* Output dict carries EXACTLY these 18 keys::

    ok, rows_read, rows_excluded,
    mechanism_family_updates, mechanism_family_updated_event_ids,
    before_clean_fully_ready, after_clean_fully_ready,
    adjusted_after_clean_fully_ready, adjusted_clean_fully_ready_delta,
    repaired_clean_event_ids, events_evaluated, records_count,
    significant_count, top_abs_sar,
    live_db_unchanged, input_backup_unchanged,
    errors, warnings

* ``rows_read`` is the SUM of rows across all three CSVs.
* Dry-run defaults: ``before_*`` / ``after_*`` / ``adjusted_*`` /
  ``repaired_clean_event_ids`` / ``events_evaluated`` /
  ``records_count`` / ``significant_count`` / ``top_abs_sar``
  are all None / 0 / [].
* Write mode requires --confirm + --backup-path + all three CSV
  paths together — partial flags fail closed.
* Schema-missing fail-closed precedence: low_signal needed for
  exclusions, mechanism_family needed for decisions.
* Provider fail-closed: retag rows + yfinance unavailable → fail
  closed BEFORE the temp copy is made.
* Conservative wording — banned tokens in any text field:
  ``proof``, ``automatically``, ``deletes``, ``replaces``,
  ``correct ticker``.
"""
from __future__ import annotations

import csv as csv_module
import hashlib
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

from scripts import mechanism_family_repair_apply_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "rows_read",
    "rows_excluded",
    "mechanism_family_updates",
    "mechanism_family_updated_event_ids",
    "before_clean_fully_ready",
    "after_clean_fully_ready",
    "adjusted_after_clean_fully_ready",
    "adjusted_clean_fully_ready_delta",
    "repaired_clean_event_ids",
    "events_evaluated",
    "records_count",
    "significant_count",
    "top_abs_sar",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)


_BANNED_WORDS = (
    "proof",
    "automatically",
    "deletes",
    "replaces",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# DDL + temp DB helpers
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


def _events_ddl(
    *, with_low_signal: bool = True, with_mechanism_family: bool = True,
) -> str:
    cols = [
        "id              INTEGER PRIMARY KEY AUTOINCREMENT",
        "headline        TEXT",
        "event_date      TEXT",
        "market_tickers  TEXT",
    ]
    if with_low_signal:
        cols.append("low_signal      INTEGER DEFAULT 0")
    if with_mechanism_family:
        cols.append("mechanism_family TEXT DEFAULT 'none'")
    return "CREATE TABLE events (\n  " + ",\n  ".join(cols) + "\n)"


def _make_temp_db(
    *,
    suffix: str = "mf_apply",
    with_low_signal: bool = True,
    with_mechanism_family: bool = True,
    seed_events: list[dict] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_events_ddl(
            with_low_signal=with_low_signal,
            with_mechanism_family=with_mechanism_family,
        ))
        conn.execute(_PRICE_CACHE_DDL)
        if seed_events:
            for e in seed_events:
                cols = ["id", "headline", "event_date", "market_tickers"]
                vals = [
                    e["id"], e.get("headline"), e.get("event_date"),
                    e.get("market_tickers", "[]"),
                ]
                if with_low_signal:
                    cols.append("low_signal")
                    vals.append(int(e.get("low_signal", 0)))
                if with_mechanism_family:
                    cols.append("mechanism_family")
                    vals.append(e.get("mechanism_family", "none"))
                placeholders = ", ".join(["?"] * len(cols))
                conn.execute(
                    f"INSERT INTO events ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    vals,
                )
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


# ---------------------------------------------------------------------------
# CSV builders.  The high/medium CSVs carry the ticker-repair packet
# schema (14 columns); the mechanism-family CSV carries the 11-column
# packet schema.  Both schemas are tolerated by the smoke's narrow
# parser (it only requires event_id + proposed_mechanism_family +
# exclude_reason for the family CSV; the high/medium CSVs are parsed
# via the existing apply_smoke parser which requires its own column
# subset).
# ---------------------------------------------------------------------------


_TICKER_PACKET_COLUMNS = (
    "event_id", "headline", "event_date", "current_primary_ticker",
    "flags", "reason", "manual_review_priority",
    "fast_to_clean_score", "fast_to_clean_reason",
    "proposed_primary_ticker", "proposed_benchmark",
    "proposed_mechanism_family", "ticker_rationale", "exclude_reason",
)


_FAMILY_PACKET_COLUMNS = (
    "event_id", "headline", "event_date",
    "current_primary_ticker", "current_benchmark",
    "flags", "repair_priority", "reason",
    "proposed_mechanism_family", "mechanism_rationale",
    "exclude_reason",
)


def _write_ticker_csv(rows: list[dict], *, suffix: str = "tk") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(_TICKER_PACKET_COLUMNS)
        for r in rows:
            writer.writerow(
                [str(r.get(c, "")) for c in _TICKER_PACKET_COLUMNS])
    return path


def _write_family_csv(rows: list[dict], *, suffix: str = "fm") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(_FAMILY_PACKET_COLUMNS)
        for r in rows:
            writer.writerow(
                [str(r.get(c, "")) for c in _FAMILY_PACKET_COLUMNS])
    return path


def _ticker_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    event_date: str = "2026-04-06",
    headline: str = "h",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "proposed_primary_ticker":   proposed_primary_ticker,
        "proposed_benchmark":        proposed_benchmark,
        "proposed_mechanism_family": proposed_mechanism_family,
        "exclude_reason":            exclude_reason,
    }


def _family_row(
    *, event_id: int,
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    headline: str = "h",
    event_date: str = "2026-04-05",
    current_primary_ticker: str = "AAPL",
    current_benchmark: str = "SPY",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "current_benchmark":         current_benchmark,
        "flags":                     "mechanism_family_none",
        "repair_priority":           "high",
        "reason":                    "Manual review candidate",
        "proposed_mechanism_family": proposed_mechanism_family,
        "mechanism_rationale":       "",
        "exclude_reason":            exclude_reason,
    }


def _empty_csv_paths() -> tuple[str, str, str]:
    """Return three empty-but-well-formed CSV paths so flag-validation
    tests can pass the path-existence checks while still asserting
    semantic fail-closed reasons."""
    high   = _write_ticker_csv([])
    medium = _write_ticker_csv([])
    family = _write_family_csv([])
    return high, medium, family


# ---------------------------------------------------------------------------
# Synthetic seam payloads
# ---------------------------------------------------------------------------


def _clean_cohort_payload(
    *,
    clean_fully_ready_count: int,
    clean_fully_ready_event_ids: list[int] | None = None,
    excluded_examples: list[dict] | None = None,
) -> dict:
    return {
        "ok":                          True,
        "clean_fully_ready_count":     clean_fully_ready_count,
        "clean_fully_ready_event_ids": list(clean_fully_ready_event_ids or []),
        "excluded_fully_ready_examples": list(excluded_examples or []),
    }


def _validation_payload(records: list[dict]) -> dict:
    return {
        "ok":      True,
        "records": list(records),
        "errors":  [],
    }


def _validation_record(
    *, event_id: int, horizon: int, sar: float,
    significant: bool = False,
    headline: str = "h", ticker: str = "AAPL",
    abnormal_return: float = 0.01,
    ci_low: float = -0.01, ci_high: float = 0.05,
    p_value: float = 0.1, fdr_q: float = 0.2,
    interpretation: str = "no_evidence",
    mechanism_family: str = "supply_shock",
) -> dict:
    return {
        "event_id":                 event_id,
        "headline":                 headline,
        "ticker":                   ticker,
        "horizon":                  horizon,
        "abnormal_return":          abnormal_return,
        "sar":                      sar,
        "ci_low":                   ci_low,
        "ci_high":                  ci_high,
        "p_value":                  p_value,
        "fdr_q":                    fdr_q,
        "interpretation":           interpretation,
        "mechanism_family":         mechanism_family,
        "statistically_significant": significant,
    }


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_eighteen_keys(self) -> None:
        report = cli.smoke_mechanism_family_apply()
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_dry_run_after_fields_are_none_or_empty(self) -> None:
        report = cli.smoke_mechanism_family_apply()
        self.assertIsNone(report["before_clean_fully_ready"])
        self.assertIsNone(report["after_clean_fully_ready"])
        self.assertIsNone(report["adjusted_after_clean_fully_ready"])
        self.assertIsNone(report["adjusted_clean_fully_ready_delta"])
        self.assertEqual(report["repaired_clean_event_ids"], [])
        self.assertEqual(report["events_evaluated"], 0)
        self.assertEqual(report["records_count"], 0)
        self.assertEqual(report["significant_count"], 0)
        self.assertIsNone(report["top_abs_sar"])

    def test_dry_run_byte_identity_invariants_default_true(self) -> None:
        report = cli.smoke_mechanism_family_apply()
        self.assertTrue(report["live_db_unchanged"])
        self.assertTrue(report["input_backup_unchanged"])


# ---------------------------------------------------------------------------
# Multi-CSV row counts in dry-run
# ---------------------------------------------------------------------------


class TestDryRunRowCounts(unittest.TestCase):
    def test_rows_read_sums_all_three_csvs(self) -> None:
        high   = _write_ticker_csv([
            _ticker_row(event_id=4, exclude_reason="off-topic"),
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_ticker_csv([
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        family = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            _family_row(event_id=44, exclude_reason="dup"),
        ])
        report = cli.smoke_mechanism_family_apply(
            high_priority_csv=high, medium_csv=medium,
            mechanism_family_csv=family,
        )
        self.assertEqual(report["rows_read"], 5)

    def test_rows_excluded_combines_all_three_csvs(self) -> None:
        high   = _write_ticker_csv([
            _ticker_row(event_id=4, exclude_reason="off-topic"),
        ])
        medium = _write_ticker_csv([
            _ticker_row(event_id=47, exclude_reason="dup"),
        ])
        family = _write_family_csv([
            _family_row(event_id=44, exclude_reason="duplicate of 40"),
            _family_row(event_id=63, exclude_reason="too indirect"),
        ])
        report = cli.smoke_mechanism_family_apply(
            high_priority_csv=high, medium_csv=medium,
            mechanism_family_csv=family,
        )
        self.assertEqual(report["rows_excluded"], 4)

    def test_mechanism_family_updates_combine_all_three_csvs(self) -> None:
        high   = _write_ticker_csv([
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        medium = _write_ticker_csv([
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
            _ticker_row(event_id=73, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        family = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40, proposed_mechanism_family="commodity_squeeze"),
        ])
        report = cli.smoke_mechanism_family_apply(
            high_priority_csv=high, medium_csv=medium,
            mechanism_family_csv=family,
        )
        self.assertEqual(report["mechanism_family_updates"], 5)
        self.assertEqual(
            sorted(report["mechanism_family_updated_event_ids"]),
            [30, 40, 46, 60, 73],
        )


# ---------------------------------------------------------------------------
# Write mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_fails_closed(self) -> None:
        h, m, f = _empty_csv_paths()
        report = cli.smoke_mechanism_family_apply(
            write=True, confirm=False, backup_path="x",
            high_priority_csv=h, medium_csv=m, mechanism_family_csv=f,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--confirm" in e for e in report["errors"]),
                        f"errors: {report['errors']}")

    def test_write_without_backup_path_fails_closed(self) -> None:
        h, m, f = _empty_csv_paths()
        report = cli.smoke_mechanism_family_apply(
            write=True, confirm=True, backup_path=None,
            high_priority_csv=h, medium_csv=m, mechanism_family_csv=f,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--backup-path" in e for e in report["errors"]),
                        f"errors: {report['errors']}")

    def test_write_without_high_priority_csv_fails_closed(self) -> None:
        _, m, f = _empty_csv_paths()
        report = cli.smoke_mechanism_family_apply(
            write=True, confirm=True, backup_path="x",
            high_priority_csv=None, medium_csv=m, mechanism_family_csv=f,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--high-priority-csv" in e for e in report["errors"]),
                        f"errors: {report['errors']}")

    def test_write_without_medium_csv_fails_closed(self) -> None:
        h, _, f = _empty_csv_paths()
        report = cli.smoke_mechanism_family_apply(
            write=True, confirm=True, backup_path="x",
            high_priority_csv=h, medium_csv=None, mechanism_family_csv=f,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--medium-csv" in e for e in report["errors"]),
                        f"errors: {report['errors']}")

    def test_write_without_mechanism_family_csv_fails_closed(self) -> None:
        h, m, _ = _empty_csv_paths()
        report = cli.smoke_mechanism_family_apply(
            write=True, confirm=True, backup_path="x",
            high_priority_csv=h, medium_csv=m, mechanism_family_csv=None,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "--mechanism-family-csv" in e for e in report["errors"]
        ), f"errors: {report['errors']}")


# ---------------------------------------------------------------------------
# Provider availability fail-closed (retag rows present)
# ---------------------------------------------------------------------------


class TestProviderFailClosed(unittest.TestCase):
    def test_retag_rows_with_provider_unavailable_fails_closed(self) -> None:
        # High-priority CSV carries a retag (DRIV→MS).  When yfinance
        # is "unavailable," the run must fail closed BEFORE any temp
        # copy is made.
        backup = _make_temp_db(seed_events=[{"id": 46}])
        try:
            high = _write_ticker_csv([
                _ticker_row(event_id=46, proposed_primary_ticker="MS",
                            proposed_benchmark="SPY",
                            proposed_mechanism_family="bank_regulatory_capital_relief"),
            ])
            medium = _write_ticker_csv([])
            family = _write_family_csv([])
            with patch.object(cli, "_check_provider_available",
                              return_value=False):
                report = cli.smoke_mechanism_family_apply(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "provider unavailable" in e.lower() for e in report["errors"]
            ), f"errors: {report['errors']}")
            # No apply happens.
            self.assertEqual(report["mechanism_family_updates"], 0)
            self.assertEqual(report["rows_excluded"], 0)
        finally:
            os.unlink(backup)

    def test_no_retag_rows_skips_provider_check(self) -> None:
        # When NO CSV carries a retag, the provider seam is never
        # consulted — running with provider "unavailable" must still
        # apply mechanism-family decisions and exclusions.
        backup = _make_temp_db(seed_events=[{"id": 30}, {"id": 44}])
        try:
            high = _write_ticker_csv([])
            medium = _write_ticker_csv([])
            family = _write_family_csv([
                _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
                _family_row(event_id=44, exclude_reason="dup"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=False), \
                 patch.object(cli, "_run_clean_cohort_report",
                              return_value=_clean_cohort_payload(
                                  clean_fully_ready_count=0)), \
                 patch.object(cli, "_run_validation_on_temp_db",
                              return_value=_validation_payload([])):
                report = cli.smoke_mechanism_family_apply(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                    write=True, confirm=True,
                )
            self.assertTrue(report["ok"], f"errors: {report['errors']}")
            self.assertEqual(report["mechanism_family_updates"], 1)
            self.assertEqual(report["rows_excluded"], 1)
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Schema check fail-closed precedence
# ---------------------------------------------------------------------------


class TestSchemaFailClosed(unittest.TestCase):
    def test_missing_low_signal_blocks_when_exclusions_exist(self) -> None:
        backup = _make_temp_db(
            with_low_signal=False, with_mechanism_family=True,
            seed_events=[{"id": 44}, {"id": 30}],
        )
        try:
            high = _write_ticker_csv([])
            medium = _write_ticker_csv([])
            family = _write_family_csv([
                _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
                _family_row(event_id=44, exclude_reason="dup"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_clean_cohort_report",
                              return_value=_clean_cohort_payload(
                                  clean_fully_ready_count=0)):
                report = cli.smoke_mechanism_family_apply(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "schema_missing_exclusion_field" in e
                for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(backup)

    def test_missing_mechanism_family_blocks_when_decisions_exist(self) -> None:
        backup = _make_temp_db(
            with_low_signal=True, with_mechanism_family=False,
            seed_events=[{"id": 30}],
        )
        try:
            high = _write_ticker_csv([])
            medium = _write_ticker_csv([])
            family = _write_family_csv([
                _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_clean_cohort_report",
                              return_value=_clean_cohort_payload(
                                  clean_fully_ready_count=0)):
                report = cli.smoke_mechanism_family_apply(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "schema_missing_mechanism_family_field" in e
                for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# End-to-end write mode against a seeded backup with all three CSVs
# ---------------------------------------------------------------------------


class TestThreeCsvWriteMode(unittest.TestCase):
    def setUp(self) -> None:
        self.backup = _make_temp_db(seed_events=[
            {"id": 4},  {"id": 46}, {"id": 47},
            {"id": 60}, {"id": 73},
            {"id": 30}, {"id": 40}, {"id": 44}, {"id": 63},
        ])
        # High-priority: retag 46 DRIV→MS + family decision; exclude 4.
        self.high = _write_ticker_csv([
            _ticker_row(event_id=4, exclude_reason="off-topic"),
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        # Medium: retag 60 + 73 (XOM kept) + family decisions; exclude 47.
        self.medium = _write_ticker_csv([
            _ticker_row(event_id=47, exclude_reason="duplicate"),
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
            _ticker_row(event_id=73, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        # Mechanism-family: 30 + 40 family decisions; 44 + 63 excluded.
        self.family = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40, proposed_mechanism_family="commodity_squeeze"),
            _family_row(event_id=44, exclude_reason="duplicate of 40"),
            _family_row(event_id=63, exclude_reason="too indirect"),
        ])

    def tearDown(self) -> None:
        if os.path.exists(self.backup):
            os.unlink(self.backup)

    def _fake_fetch(self, *, ticker, start, end):
        # Single-day synthetic bar so price-cache insert exercises the
        # backfill branch.
        return [{"date": end, "close": 100.0, "volume": 1000.0}]

    def _run_write(
        self, *,
        before_payload: dict | None = None,
        after_payload: dict | None = None,
        validation_payload: dict | None = None,
    ) -> dict:
        # Simulate the realistic scenario: pre-repair clean cohort is
        # empty; post-repair clean set is [46, 60, 73, 30, 40].
        before_payload = before_payload if before_payload is not None else (
            _clean_cohort_payload(
                clean_fully_ready_count=0,
                clean_fully_ready_event_ids=[],
            )
        )
        after_payload = after_payload if after_payload is not None else (
            _clean_cohort_payload(
                clean_fully_ready_count=5,
                clean_fully_ready_event_ids=[46, 60, 73, 30, 40],
            )
        )
        validation_payload = validation_payload if validation_payload is not None else (
            _validation_payload([
                _validation_record(event_id=46, horizon=1, sar=0.5),
                _validation_record(event_id=60, horizon=1, sar=1.2),
                _validation_record(event_id=73, horizon=1, sar=-0.8),
                _validation_record(event_id=30, horizon=1, sar=1.4),
                _validation_record(event_id=40, horizon=1, sar=2.1,
                                   significant=True),
            ])
        )

        cohort_calls: list[Any] = []

        def fake_cohort(*, db_path):
            cohort_calls.append(db_path)
            return before_payload if len(cohort_calls) == 1 else after_payload

        with patch.object(cli, "_check_provider_available",
                          return_value=True), \
             patch.object(cli, "_fetch_ticker_rows",
                          side_effect=self._fake_fetch), \
             patch.object(cli, "_run_clean_cohort_report",
                          side_effect=fake_cohort), \
             patch.object(cli, "_run_validation_on_temp_db",
                          return_value=validation_payload):
            return cli.smoke_mechanism_family_apply(
                backup_path=self.backup,
                high_priority_csv=self.high,
                medium_csv=self.medium,
                mechanism_family_csv=self.family,
                write=True, confirm=True,
            )

    def test_repaired_clean_event_ids_supersets_existing_three(self) -> None:
        report = self._run_write()
        # Pass criterion: superset of [46, 60, 73] plus new family
        # additions (30, 40).
        self.assertEqual(
            sorted(report["repaired_clean_event_ids"]),
            [30, 40, 46, 60, 73],
        )

    def test_cohort_expanded_from_three_to_five(self) -> None:
        report = self._run_write()
        self.assertEqual(len(report["repaired_clean_event_ids"]), 5)

    def test_rows_excluded_counts_all_three_csvs(self) -> None:
        report = self._run_write()
        # high: 1 (event 4); medium: 1 (event 47); family: 2 (44, 63)
        self.assertEqual(report["rows_excluded"], 4)

    def test_mechanism_family_updates_counts_all_three_csvs(self) -> None:
        report = self._run_write()
        # 46 from high; 60 + 73 from medium; 30 + 40 from family.
        self.assertEqual(report["mechanism_family_updates"], 5)
        self.assertEqual(
            sorted(report["mechanism_family_updated_event_ids"]),
            [30, 40, 46, 60, 73],
        )

    def test_temp_copy_carries_all_three_sets_of_mutations(self) -> None:
        # Inspect the temp DB after the smoke runs to confirm BOTH the
        # ticker-CSV mutations (low_signal flips, market_tickers retag,
        # family decisions) AND the mechanism-family-CSV mutations
        # landed in the same temp copy.
        report = self._run_write()
        temp_path = None
        for w in report["warnings"]:
            if isinstance(w, str) and w.startswith("Temp copy at "):
                temp_path = w[len("Temp copy at "):]
                break
        self.assertIsNotNone(temp_path)
        conn = sqlite3.connect(temp_path)
        try:
            family_rows = dict(conn.execute(
                "SELECT id, mechanism_family FROM events "
                "WHERE id IN (30, 40, 44, 46, 60, 63, 73)"
            ).fetchall())
            self.assertEqual(family_rows[30],  "supply_shock")
            self.assertEqual(family_rows[40],  "commodity_squeeze")
            self.assertEqual(family_rows[46],  "bank_regulatory_capital_relief")
            self.assertEqual(family_rows[60],  "supply_shock")
            self.assertEqual(family_rows[73],  "supply_shock")
            self.assertEqual(family_rows[44],  "none")
            self.assertEqual(family_rows[63],  "none")

            low_sig = dict(conn.execute(
                "SELECT id, low_signal FROM events "
                "WHERE id IN (4, 47, 44, 63)"
            ).fetchall())
            self.assertEqual(low_sig[4],  1)
            self.assertEqual(low_sig[47], 1)
            self.assertEqual(low_sig[44], 1)
            self.assertEqual(low_sig[63], 1)

            # Retag landed in market_tickers JSON for event 46.
            mt = conn.execute(
                "SELECT market_tickers FROM events WHERE id = 46"
            ).fetchone()[0]
            self.assertIn("MS", mt)

            # Backfill landed for MS via the patched fetch seam.
            cnt = conn.execute(
                "SELECT COUNT(*) FROM price_cache WHERE ticker = 'MS'"
            ).fetchone()[0]
            self.assertGreater(cnt, 0)
        finally:
            conn.close()

    def test_records_count_filtered_to_repaired_set(self) -> None:
        validation = _validation_payload([
            _validation_record(event_id=46, horizon=1, sar=0.5),
            _validation_record(event_id=60, horizon=1, sar=1.2),
            _validation_record(event_id=73, horizon=1, sar=-0.8),
            _validation_record(event_id=30, horizon=1, sar=1.4),
            _validation_record(event_id=40, horizon=1, sar=2.1),
            # A pre-existing clean event 99 — must NOT count.
            _validation_record(event_id=99, horizon=1, sar=99.0),
        ])
        report = self._run_write(validation_payload=validation)
        self.assertEqual(report["records_count"], 5)
        self.assertEqual(report["events_evaluated"], 5)

    def test_top_abs_sar_is_max_absolute_value(self) -> None:
        validation = _validation_payload([
            _validation_record(event_id=46, horizon=1, sar=0.5),
            _validation_record(event_id=60, horizon=1, sar=1.2),
            _validation_record(event_id=73, horizon=1, sar=-0.8),
            _validation_record(event_id=30, horizon=1, sar=1.4),
            _validation_record(event_id=40, horizon=1, sar=2.1),
        ])
        report = self._run_write(validation_payload=validation)
        self.assertAlmostEqual(report["top_abs_sar"], 2.1, places=5)

    def test_input_backup_unchanged_after_write(self) -> None:
        before = _sha256(self.backup)
        report = self._run_write()
        after = _sha256(self.backup)
        self.assertEqual(before, after)
        self.assertTrue(report["input_backup_unchanged"])


# ---------------------------------------------------------------------------
# Live DB byte identity
# ---------------------------------------------------------------------------


class TestLiveDbReadOnly(unittest.TestCase):
    def test_write_mode_does_not_touch_live_db(self) -> None:
        live = _make_temp_db(suffix="mf_live", seed_events=[{"id": 30}])
        backup = _make_temp_db(suffix="mf_backup", seed_events=[{"id": 30}])
        try:
            high = _write_ticker_csv([])
            medium = _write_ticker_csv([])
            family = _write_family_csv([
                _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
            ])
            live_before = _sha256(live)
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_clean_cohort_report",
                              return_value=_clean_cohort_payload(
                                  clean_fully_ready_count=0)), \
                 patch.object(cli, "_run_validation_on_temp_db",
                              return_value=_validation_payload([])):
                report = cli.smoke_mechanism_family_apply(
                    db_path=live, backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live), live_before)
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_text_fields(self) -> None:
        report = cli.smoke_mechanism_family_apply()
        all_text = " ".join([
            str(report.get("errors", "")),
            str(report.get("warnings", "")),
        ]).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, all_text,
                             f"banned word {w!r} in: {all_text!r}")


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_clean_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_validation_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_validation_on_temp_db")))

    def test_provider_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))


# ---------------------------------------------------------------------------
# Read-only / import isolation on dry-run
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance",
        "fastapi",
        "api",
    )

    def test_dry_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        cli.smoke_mechanism_family_apply()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set(),
                         "dry-run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    with patch.object(cli, "_check_provider_available",
                      return_value=True), \
         patch.object(cli, "_run_clean_cohort_report",
                      return_value=_clean_cohort_payload(
                          clean_fully_ready_count=0)), \
         patch.object(cli, "_run_validation_on_temp_db",
                      return_value=_validation_payload([])):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


class TestCLI(unittest.TestCase):
    def test_dry_run_json_emits_eighteen_keys(self) -> None:
        h = _write_ticker_csv([])
        m = _write_ticker_csv([])
        f = _write_family_csv([
            _family_row(event_id=30, proposed_mechanism_family="supply_shock"),
        ])
        rc, output = _run_cli([
            "--dry-run", "--json",
            "--high-priority-csv", h,
            "--medium-csv", m,
            "--mechanism-family-csv", f,
        ])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))

    def test_text_default_does_not_raise(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("ok", output.lower())


if __name__ == "__main__":
    unittest.main()

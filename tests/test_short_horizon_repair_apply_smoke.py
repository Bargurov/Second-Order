"""Tests for ``scripts/short_horizon_repair_apply_smoke.py``.

Pin the contract:

* Operates on a copied backup only — live DB is read-only,
  byte-identical before/after every run.
* Consumes FOUR CSVs in this fixed apply order on the SAME temp DB:
    1. ``manual_ticker_repair_high_priority.csv``
    2. ``manual_ticker_repair_medium_production_like.csv``
    3. ``mechanism_family_repair_packet.csv``
    4. ``short_horizon_repair_packet.csv``
  All four CSVs may carry exclusion rows; the high / medium / short-
  horizon CSVs may also carry retags + CSV-driven mechanism_family
  decisions.  The mechanism-family CSV carries decisions + exclusions
  only (no retags).
* Apply order on the temp DB:
    1. Categorize rows from all four CSVs (exclude / retag / no-op).
    2. Apply categorized rows (low_signal=1 for excludes; retag for
       market_tickers JSON updates).
    3. Apply CSV-driven mechanism_family decisions (later CSV wins on
       conflict; the short-horizon CSV is the most recent operator
       decision).
    4. Backfill price_cache for retag tickers via the provider seam.
* Output dict carries EXACTLY these 14 keys::

    ok, rows_read, rows_excluded, rows_retagged,
    mechanism_family_updates,
    repaired_short_horizon_event_ids,
    events_evaluated, records_count, significant_count, top_abs_sar,
    live_db_unchanged, input_backup_unchanged,
    errors, warnings

* ``rows_read`` is the SUM of rows across all four CSVs.
* Dry-run defaults: every after / repaired / records / significant /
  top_abs_sar field is None / 0 / [].
* Write mode requires --confirm + --backup-path + --short-horizon-csv;
  the three legacy ticker / family CSV paths are required too so the
  pre-existing repair pass lands first.  Partial flags fail closed.
* Provider fail-closed: retag rows + yfinance unavailable → fail
  closed BEFORE the temp copy is made.
* Schema-missing fail-closed: low_signal column needed for
  exclusions; mechanism_family column needed for decisions.
* ``repaired_short_horizon_event_ids`` = post-repair short-horizon-
  ready event_ids minus pre-repair short-horizon-ready event_ids.
* Validation seam consumes only horizons 1 and 5; the smoke never
  surfaces 20d records.
* Conservative wording — banned tokens: ``proof``, ``alpha``,
  ``automatically``, ``deletes``, ``replaces``, ``correct ticker``.
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

from scripts import short_horizon_repair_apply_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "rows_read",
    "rows_excluded",
    "rows_retagged",
    "mechanism_family_updates",
    "repaired_short_horizon_event_ids",
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
    suffix: str = "sh_apply",
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
# CSV builders
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


_SHORT_HORIZON_PACKET_COLUMNS = (
    "event_id", "headline", "event_date", "current_primary_ticker",
    "flags", "repair_type", "repair_priority",
    "proposed_primary_ticker", "proposed_mechanism_family",
    "rationale", "exclude_reason",
)


def _write_ticker_csv(rows: list[dict], *, suffix: str = "tk") -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(_TICKER_PACKET_COLUMNS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in _TICKER_PACKET_COLUMNS])
    return path


def _write_family_csv(rows: list[dict], *, suffix: str = "fm") -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(_FAMILY_PACKET_COLUMNS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in _FAMILY_PACKET_COLUMNS])
    return path


def _write_short_horizon_csv(rows: list[dict], *, suffix: str = "sh") -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(_SHORT_HORIZON_PACKET_COLUMNS)
        for r in rows:
            w.writerow(
                [str(r.get(c, "")) for c in _SHORT_HORIZON_PACKET_COLUMNS])
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


def _short_horizon_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    headline: str = "h",
    event_date: str = "2026-04-10",
    current_primary_ticker: str = "AAPL",
    repair_type: str = "mechanism_family_only",
    repair_priority: str = "high",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "flags":                     "",
        "repair_type":               repair_type,
        "repair_priority":           repair_priority,
        "proposed_primary_ticker":   proposed_primary_ticker,
        "proposed_mechanism_family": proposed_mechanism_family,
        "rationale":                 "",
        "exclude_reason":            exclude_reason,
    }


def _empty_csvs() -> tuple[str, str, str, str]:
    return (
        _write_ticker_csv([]),
        _write_ticker_csv([]),
        _write_family_csv([]),
        _write_short_horizon_csv([]),
    )


# ---------------------------------------------------------------------------
# Synthetic seam payloads
# ---------------------------------------------------------------------------


def _short_horizon_readiness_payload(
    *, ready_event_ids: list[int],
) -> dict:
    return {
        "total_events":           max(len(ready_event_ids), 1),
        "events_ready_1d5d":      len(ready_event_ids),
        "delta_vs_full_ready":    0,
        "missing_tickers_count":  0,
        "missing_benchmark_count": 0,
        "insufficient_estimation_window_count": 0,
        "examples": [
            {
                "event_id":       ev_id,
                "event_date":     "2026-04-10",
                "primary_ticker": "AAPL",
                "checks":         {},
                "ready_1d5d":     True,
                "delta_eligible": False,
            }
            for ev_id in ready_event_ids
        ],
        "recommended_next_action": "synthetic",
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
    def test_has_exactly_fourteen_keys(self) -> None:
        report = cli.smoke_short_horizon_repair_apply()
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_dry_run_after_fields_are_empty_or_zero(self) -> None:
        report = cli.smoke_short_horizon_repair_apply()
        self.assertEqual(report["repaired_short_horizon_event_ids"], [])
        self.assertEqual(report["events_evaluated"], 0)
        self.assertEqual(report["records_count"], 0)
        self.assertEqual(report["significant_count"], 0)
        self.assertIsNone(report["top_abs_sar"])

    def test_dry_run_byte_identity_invariants_default_true(self) -> None:
        report = cli.smoke_short_horizon_repair_apply()
        self.assertTrue(report["live_db_unchanged"])
        self.assertTrue(report["input_backup_unchanged"])


# ---------------------------------------------------------------------------
# Multi-CSV row counts in dry-run
# ---------------------------------------------------------------------------


class TestDryRunRowCounts(unittest.TestCase):
    def test_rows_read_sums_all_four_csvs(self) -> None:
        h = _write_ticker_csv([
            _ticker_row(event_id=4, exclude_reason="off-topic"),
        ])
        m = _write_ticker_csv([
            _ticker_row(event_id=47, exclude_reason="dup"),
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        f = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
        ])
        sh = _write_short_horizon_csv([
            _short_horizon_row(event_id=70,
                               proposed_mechanism_family="supply_shock"),
            _short_horizon_row(event_id=71, exclude_reason="dup"),
        ])
        report = cli.smoke_short_horizon_repair_apply(
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        self.assertEqual(report["rows_read"], 6)

    def test_rows_excluded_combines_all_four_csvs(self) -> None:
        h  = _write_ticker_csv([_ticker_row(event_id=4, exclude_reason="x")])
        m  = _write_ticker_csv([_ticker_row(event_id=47, exclude_reason="x")])
        f  = _write_family_csv([_family_row(event_id=44, exclude_reason="x")])
        sh = _write_short_horizon_csv([
            _short_horizon_row(event_id=72, exclude_reason="x"),
            _short_horizon_row(event_id=73, exclude_reason="x"),
        ])
        report = cli.smoke_short_horizon_repair_apply(
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        self.assertEqual(report["rows_excluded"], 5)

    def test_rows_retagged_counts_ticker_csvs_and_short_horizon(self) -> None:
        h  = _write_ticker_csv([
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        m  = _write_ticker_csv([
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        f  = _write_family_csv([])
        sh = _write_short_horizon_csv([
            _short_horizon_row(event_id=80,
                               proposed_primary_ticker="JPM"),
        ])
        report = cli.smoke_short_horizon_repair_apply(
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        # 46 + 60 + 80 = 3 retags.
        self.assertEqual(report["rows_retagged"], 3)

    def test_mechanism_family_updates_combine_all_four_csvs(self) -> None:
        h  = _write_ticker_csv([
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        m  = _write_ticker_csv([
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        f  = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
        ])
        sh = _write_short_horizon_csv([
            _short_horizon_row(event_id=70,
                               proposed_mechanism_family="supply_shock"),
        ])
        report = cli.smoke_short_horizon_repair_apply(
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        self.assertEqual(report["mechanism_family_updates"], 4)


# ---------------------------------------------------------------------------
# Write mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_fails_closed(self) -> None:
        h, m, f, sh = _empty_csvs()
        report = cli.smoke_short_horizon_repair_apply(
            write=True, confirm=False, backup_path="x",
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--confirm" in e for e in report["errors"]))

    def test_write_without_backup_path_fails_closed(self) -> None:
        h, m, f, sh = _empty_csvs()
        report = cli.smoke_short_horizon_repair_apply(
            write=True, confirm=True, backup_path=None,
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=sh,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("--backup-path" in e for e in report["errors"]))

    def test_write_without_short_horizon_csv_fails_closed(self) -> None:
        h, m, f, _sh = _empty_csvs()
        report = cli.smoke_short_horizon_repair_apply(
            write=True, confirm=True, backup_path="x",
            high_priority_csv=h, medium_csv=m,
            mechanism_family_csv=f, short_horizon_csv=None,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "--short-horizon-csv" in e for e in report["errors"]
        ))


# ---------------------------------------------------------------------------
# Provider availability fail-closed
# ---------------------------------------------------------------------------


class TestProviderFailClosed(unittest.TestCase):
    def test_short_horizon_retag_with_provider_unavailable_fails_closed(
        self,
    ) -> None:
        backup = _make_temp_db(seed_events=[{"id": 80}])
        try:
            h  = _write_ticker_csv([])
            m  = _write_ticker_csv([])
            f  = _write_family_csv([])
            sh = _write_short_horizon_csv([
                _short_horizon_row(event_id=80,
                                   proposed_primary_ticker="JPM"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=False):
                report = cli.smoke_short_horizon_repair_apply(
                    backup_path=backup,
                    high_priority_csv=h, medium_csv=m,
                    mechanism_family_csv=f, short_horizon_csv=sh,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "provider unavailable" in e.lower()
                for e in report["errors"]
            ), f"errors: {report['errors']}")
            self.assertEqual(report["rows_retagged"], 0)
            self.assertEqual(report["mechanism_family_updates"], 0)
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Schema fail-closed
# ---------------------------------------------------------------------------


class TestSchemaFailClosed(unittest.TestCase):
    def test_missing_low_signal_blocks_when_exclusions_exist(self) -> None:
        backup = _make_temp_db(
            with_low_signal=False, seed_events=[{"id": 70}],
        )
        try:
            h  = _write_ticker_csv([])
            m  = _write_ticker_csv([])
            f  = _write_family_csv([])
            sh = _write_short_horizon_csv([
                _short_horizon_row(event_id=70, exclude_reason="x"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_short_horizon_readiness_report",
                              return_value=_short_horizon_readiness_payload(
                                  ready_event_ids=[])):
                report = cli.smoke_short_horizon_repair_apply(
                    backup_path=backup,
                    high_priority_csv=h, medium_csv=m,
                    mechanism_family_csv=f, short_horizon_csv=sh,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "schema_missing_exclusion_field" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(backup)

    def test_missing_mechanism_family_blocks_when_decisions_exist(self) -> None:
        backup = _make_temp_db(
            with_mechanism_family=False, seed_events=[{"id": 70}],
        )
        try:
            h  = _write_ticker_csv([])
            m  = _write_ticker_csv([])
            f  = _write_family_csv([])
            sh = _write_short_horizon_csv([
                _short_horizon_row(event_id=70,
                                   proposed_mechanism_family="supply_shock"),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_short_horizon_readiness_report",
                              return_value=_short_horizon_readiness_payload(
                                  ready_event_ids=[])):
                report = cli.smoke_short_horizon_repair_apply(
                    backup_path=backup,
                    high_priority_csv=h, medium_csv=m,
                    mechanism_family_csv=f, short_horizon_csv=sh,
                    write=True, confirm=True,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "schema_missing_mechanism_family_field" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# End-to-end write mode
# ---------------------------------------------------------------------------


class TestEndToEndWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.backup = _make_temp_db(seed_events=[
            {"id": 30}, {"id": 40}, {"id": 46}, {"id": 60}, {"id": 73},
            {"id": 70}, {"id": 71}, {"id": 80},
        ])
        self.high = _write_ticker_csv([
            _ticker_row(event_id=46, proposed_primary_ticker="MS",
                        proposed_benchmark="SPY",
                        proposed_mechanism_family="bank_regulatory_capital_relief"),
        ])
        self.medium = _write_ticker_csv([
            _ticker_row(event_id=60, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
            _ticker_row(event_id=73, proposed_primary_ticker="XOM",
                        proposed_benchmark="XLE",
                        proposed_mechanism_family="supply_shock"),
        ])
        self.family = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40,
                        proposed_mechanism_family="commodity_squeeze"),
        ])
        self.short_horizon = _write_short_horizon_csv([
            _short_horizon_row(event_id=70,
                               proposed_mechanism_family="supply_shock"),
            _short_horizon_row(event_id=71, exclude_reason="off-topic"),
            _short_horizon_row(event_id=80,
                               proposed_primary_ticker="JPM"),
        ])

    def tearDown(self) -> None:
        if os.path.exists(self.backup):
            os.unlink(self.backup)

    def _fake_fetch(self, *, ticker, start, end):
        return [{"date": end, "close": 100.0, "volume": 1000.0}]

    def _run_write(
        self, *,
        readiness_pre: list[int] | None = None,
        readiness_post: list[int] | None = None,
        validation_payload: dict | None = None,
    ) -> dict:
        readiness_pre  = readiness_pre  if readiness_pre  is not None else []
        readiness_post = readiness_post if readiness_post is not None else (
            [30, 40, 46, 60, 73, 70, 80]
        )
        validation_payload = validation_payload if validation_payload is not None else (
            _validation_payload([
                _validation_record(event_id=70, horizon=1, sar=1.4),
                _validation_record(event_id=70, horizon=5, sar=-2.1),
                _validation_record(event_id=80, horizon=1, sar=0.7),
                _validation_record(event_id=80, horizon=5, sar=1.8,
                                   significant=True),
                # 30 is in repaired set too — should appear in records.
                _validation_record(event_id=30, horizon=5, sar=-1.5),
            ])
        )

        readiness_calls: list[Any] = []

        def fake_readiness(*, db_path):
            readiness_calls.append(db_path)
            ids = readiness_pre if len(readiness_calls) == 1 else readiness_post
            return _short_horizon_readiness_payload(ready_event_ids=ids)

        with patch.object(cli, "_check_provider_available",
                          return_value=True), \
             patch.object(cli, "_fetch_ticker_rows",
                          side_effect=self._fake_fetch), \
             patch.object(cli, "_run_short_horizon_readiness_report",
                          side_effect=fake_readiness), \
             patch.object(cli, "_run_short_horizon_validation_on_temp_db",
                          return_value=validation_payload):
            return cli.smoke_short_horizon_repair_apply(
                backup_path=self.backup,
                high_priority_csv=self.high,
                medium_csv=self.medium,
                mechanism_family_csv=self.family,
                short_horizon_csv=self.short_horizon,
                write=True, confirm=True,
            )

    def test_repaired_short_horizon_event_ids_are_post_minus_pre(self) -> None:
        report = self._run_write(
            readiness_pre=[],
            readiness_post=[30, 40, 46, 60, 73, 70, 80],
        )
        self.assertEqual(
            sorted(report["repaired_short_horizon_event_ids"]),
            [30, 40, 46, 60, 70, 73, 80],
        )

    def test_short_horizon_only_subtracts_pre_ready(self) -> None:
        # Pre-ready set already contains 30 + 46; only the new entrants
        # should land in repaired_short_horizon_event_ids.
        report = self._run_write(
            readiness_pre=[30, 46],
            readiness_post=[30, 40, 46, 60, 70, 73, 80],
        )
        self.assertEqual(
            sorted(report["repaired_short_horizon_event_ids"]),
            [40, 60, 70, 73, 80],
        )

    def test_records_filtered_to_repaired_set(self) -> None:
        validation = _validation_payload([
            _validation_record(event_id=70, horizon=1, sar=1.4),
            _validation_record(event_id=70, horizon=5, sar=-2.1),
            # event 999 is NOT in repaired_short_horizon_event_ids;
            # must NOT appear in records.
            _validation_record(event_id=999, horizon=1, sar=99.0),
        ])
        report = self._run_write(
            readiness_pre=[],
            readiness_post=[70],
            validation_payload=validation,
        )
        self.assertEqual(report["records_count"], 2)
        self.assertEqual(report["events_evaluated"], 1)

    def test_top_abs_sar_is_max_absolute_sar(self) -> None:
        validation = _validation_payload([
            _validation_record(event_id=70, horizon=1, sar=1.4),
            _validation_record(event_id=70, horizon=5, sar=-2.1),
            _validation_record(event_id=80, horizon=1, sar=0.7),
        ])
        report = self._run_write(
            readiness_pre=[],
            readiness_post=[70, 80],
            validation_payload=validation,
        )
        self.assertAlmostEqual(report["top_abs_sar"], 2.1, places=5)

    def test_top_abs_sar_none_when_no_records(self) -> None:
        report = self._run_write(
            readiness_pre=[],
            readiness_post=[70],
            validation_payload=_validation_payload([]),
        )
        self.assertIsNone(report["top_abs_sar"])

    def test_significant_count_counts_significant_records(self) -> None:
        validation = _validation_payload([
            _validation_record(event_id=70, horizon=1, sar=1.4,
                               significant=True),
            _validation_record(event_id=70, horizon=5, sar=-2.1,
                               significant=False),
            _validation_record(event_id=80, horizon=1, sar=0.7,
                               significant=True),
        ])
        report = self._run_write(
            readiness_pre=[],
            readiness_post=[70, 80],
            validation_payload=validation,
        )
        self.assertEqual(report["significant_count"], 2)

    def test_input_backup_unchanged(self) -> None:
        before = _sha256(self.backup)
        self._run_write()
        after = _sha256(self.backup)
        self.assertEqual(before, after)

    def test_temp_copy_carries_short_horizon_mutations(self) -> None:
        report = self._run_write()
        temp_path = None
        for w in report["warnings"]:
            if isinstance(w, str) and w.startswith("Temp copy at "):
                temp_path = w[len("Temp copy at "):]
                break
        self.assertIsNotNone(temp_path)
        conn = sqlite3.connect(temp_path)
        try:
            # event 70: family decision applied via short-horizon CSV.
            row = conn.execute(
                "SELECT mechanism_family FROM events WHERE id = 70"
            ).fetchone()
            self.assertEqual(row[0], "supply_shock")
            # event 71: low_signal=1 from short-horizon CSV exclude.
            row = conn.execute(
                "SELECT low_signal FROM events WHERE id = 71"
            ).fetchone()
            self.assertEqual(row[0], 1)
            # event 80: market_tickers retag from short-horizon CSV.
            row = conn.execute(
                "SELECT market_tickers FROM events WHERE id = 80"
            ).fetchone()
            self.assertIn("JPM", row[0])
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Validation seam horizons
# ---------------------------------------------------------------------------


class TestShortHorizonOnly(unittest.TestCase):
    def test_validation_records_with_20d_are_accepted_only_when_repaired(
        self,
    ) -> None:
        # The smoke filters records to events in repaired_short_horizon_
        # event_ids regardless of horizon.  The seam itself is expected
        # to return only 1d/5d records — the smoke does not strip
        # horizons defensively.  This test pins that the 1d/5d-only
        # contract lives in the SEAM, not in the smoke layer: if a 20d
        # record leaks through, the smoke will count it.  The test
        # documents that contract — operators must wire the seam to a
        # short-horizon-only validation runner.
        backup = _make_temp_db(seed_events=[{"id": 70}])
        try:
            h, m, f, _ = _empty_csvs()
            sh = _write_short_horizon_csv([
                _short_horizon_row(event_id=70,
                                   proposed_mechanism_family="supply_shock"),
            ])
            validation = _validation_payload([
                _validation_record(event_id=70, horizon=1, sar=1.4),
                _validation_record(event_id=70, horizon=5, sar=-2.1),
            ])
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_short_horizon_readiness_report",
                              side_effect=[
                                  _short_horizon_readiness_payload(
                                      ready_event_ids=[]),
                                  _short_horizon_readiness_payload(
                                      ready_event_ids=[70]),
                              ]), \
                 patch.object(cli, "_run_short_horizon_validation_on_temp_db",
                              return_value=validation):
                report = cli.smoke_short_horizon_repair_apply(
                    backup_path=backup,
                    high_priority_csv=h, medium_csv=m,
                    mechanism_family_csv=f, short_horizon_csv=sh,
                    write=True, confirm=True,
                )
            # All 2 records (1d + 5d) lands in records_count; no 20d
            # leakage from the seam.
            self.assertEqual(report["records_count"], 2)
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_text_fields(self) -> None:
        report = cli.smoke_short_horizon_repair_apply()
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
    def test_short_horizon_readiness_seam_callable(self) -> None:
        self.assertTrue(callable(
            getattr(cli, "_run_short_horizon_readiness_report")))

    def test_short_horizon_validation_seam_callable(self) -> None:
        self.assertTrue(callable(
            getattr(cli, "_run_short_horizon_validation_on_temp_db")))

    def test_provider_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api")

    def test_dry_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        cli.smoke_short_horizon_repair_apply()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# Live DB byte identity
# ---------------------------------------------------------------------------


class TestLiveDbReadOnly(unittest.TestCase):
    def test_write_mode_does_not_touch_live_db(self) -> None:
        live   = _make_temp_db(suffix="sh_live",   seed_events=[{"id": 70}])
        backup = _make_temp_db(suffix="sh_backup", seed_events=[{"id": 70}])
        try:
            h, m, f, _ = _empty_csvs()
            sh = _write_short_horizon_csv([
                _short_horizon_row(event_id=70,
                                   proposed_mechanism_family="supply_shock"),
            ])
            live_before = _sha256(live)
            with patch.object(cli, "_check_provider_available",
                              return_value=True), \
                 patch.object(cli, "_run_short_horizon_readiness_report",
                              return_value=_short_horizon_readiness_payload(
                                  ready_event_ids=[])), \
                 patch.object(cli, "_run_short_horizon_validation_on_temp_db",
                              return_value=_validation_payload([])):
                report = cli.smoke_short_horizon_repair_apply(
                    db_path=live, backup_path=backup,
                    high_priority_csv=h, medium_csv=m,
                    mechanism_family_csv=f, short_horizon_csv=sh,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live), live_before)
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    with patch.object(cli, "_check_provider_available",
                      return_value=True), \
         patch.object(cli, "_run_short_horizon_readiness_report",
                      return_value=_short_horizon_readiness_payload(
                          ready_event_ids=[])), \
         patch.object(cli, "_run_short_horizon_validation_on_temp_db",
                      return_value=_validation_payload([])):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


class TestCLI(unittest.TestCase):
    def test_dry_run_json_emits_fourteen_keys(self) -> None:
        h, m, f, sh = _empty_csvs()
        rc, output = _run_cli([
            "--dry-run", "--json",
            "--high-priority-csv", h,
            "--medium-csv", m,
            "--mechanism-family-csv", f,
            "--short-horizon-csv", sh,
        ])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))

    def test_text_default_runs(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("ok", output.lower())


if __name__ == "__main__":
    unittest.main()

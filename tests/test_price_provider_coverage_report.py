"""Tests for ``scripts/price_provider_coverage_report.py`` (D2D).

Pin the read-only provider-coverage contract:

* Provider grouping goes through ``db.derive_price_provider`` — NULL,
  blank, and whitespace-only ``source_provider`` all collapse to
  ``legacy_unknown``; named providers (``yfinance``, ``polygon``,
  ``fallback:yfinance`` …) pass through verbatim.
* Per-provider fields: ``row_count``, ``ticker_count``, ``raw_rows``
  (auto_adjust=0), ``adjusted_rows`` (auto_adjust=1), ``other_basis_rows``,
  ``min_date``, ``max_date``.
* Top-level ``total_rows`` equals COUNT(*) and equals the sum of
  per-provider ``row_count``; ``total_tickers`` is the distinct-ticker
  count across the whole table.
* An explicit ``caveat`` states legacy_unknown is a provenance gap, not
  a data-validity claim.
* Empty / unreadable table → honest empty shape (no crash).
* No mutation: ``price_cache`` byte-identical across repeated runs.
* ``--json`` / ``--db-path`` plumbing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from scripts import price_provider_coverage_report as report  # noqa: E402


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker          TEXT NOT NULL,
    date            TEXT NOT NULL,
    close           REAL,
    volume          REAL,
    auto_adjust     INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    source_provider TEXT,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


# (ticker, date, close, volume, auto_adjust, fetched_at, source_provider)
_FIXTURE_ROWS = [
    # legacy_unknown — NULL, blank, whitespace (all AAPL aa=0)
    ("AAPL", "2026-03-02", 100.0, 1000.0, 0, "ts", None),
    ("AAPL", "2026-03-03", 101.0, 1000.0, 0, "ts", ""),
    ("AAPL", "2026-03-04", 102.0, 1000.0, 0, "ts", "   "),
    # yfinance — one adjusted (AAPL aa=1), one raw (MSFT aa=0)
    ("AAPL", "2026-03-02", 110.0, 1000.0, 1, "ts", "yfinance"),
    ("MSFT", "2026-03-02", 200.0, 1000.0, 0, "ts", "yfinance"),
    # polygon — one raw (MSFT aa=0)
    ("MSFT", "2026-03-03", 201.0, 1000.0, 0, "ts", "polygon"),
    # fallback:yfinance — one adjusted (SPY aa=1)
    ("SPY", "2026-03-02", 300.0, 1000.0, 1, "ts", "fallback:yfinance"),
]


def _make_db(rows) -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"test_provider_cov_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_PRICE_CACHE_DDL)
        if rows:
            conn.executemany(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at, "
                "source_provider) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        conn.commit()
    finally:
        conn.close()
    return path


class ProviderCoverageReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = _make_db(_FIXTURE_ROWS)

    def tearDown(self) -> None:
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _summary(self):
        return report.summarize_provider_coverage(db_path=self.db_path)

    # ----- totals --------------------------------------------------------
    def test_total_rows_matches_count(self) -> None:
        s = self._summary()
        self.assertEqual(s["total_rows"], len(_FIXTURE_ROWS))

    def test_per_provider_row_counts_sum_to_total(self) -> None:
        s = self._summary()
        self.assertEqual(
            sum(p["row_count"] for p in s["providers"].values()),
            s["total_rows"],
        )

    def test_total_tickers_distinct_across_table(self) -> None:
        s = self._summary()
        self.assertEqual(s["total_tickers"], 3)  # AAPL, MSFT, SPY
        self.assertEqual(s["provider_count"], len(s["providers"]))

    # ----- legacy_unknown grouping ---------------------------------------
    def test_null_blank_whitespace_group_as_legacy_unknown(self) -> None:
        s = self._summary()
        legacy = s["providers"]["legacy_unknown"]
        self.assertEqual(legacy["row_count"], 3)
        self.assertEqual(legacy["ticker_count"], 1)        # AAPL only
        self.assertEqual(legacy["raw_rows"], 3)            # all aa=0
        self.assertEqual(legacy["adjusted_rows"], 0)
        self.assertEqual(legacy["min_date"], "2026-03-02")
        self.assertEqual(legacy["max_date"], "2026-03-04")

    # ----- named providers preserved -------------------------------------
    def test_named_providers_preserved(self) -> None:
        s = self._summary()
        self.assertIn("yfinance", s["providers"])
        self.assertIn("polygon", s["providers"])
        self.assertIn("fallback:yfinance", s["providers"])
        self.assertEqual(s["providers"]["yfinance"]["row_count"], 2)
        self.assertEqual(s["providers"]["polygon"]["row_count"], 1)
        self.assertEqual(s["providers"]["fallback:yfinance"]["row_count"], 1)

    def test_named_provider_ticker_count(self) -> None:
        s = self._summary()
        # yfinance spans AAPL (aa=1) + MSFT (aa=0)
        self.assertEqual(s["providers"]["yfinance"]["ticker_count"], 2)
        self.assertEqual(s["providers"]["polygon"]["ticker_count"], 1)

    # ----- auto_adjust basis split ---------------------------------------
    def test_auto_adjust_split_per_provider(self) -> None:
        s = self._summary()
        yf = s["providers"]["yfinance"]
        self.assertEqual(yf["raw_rows"], 1)        # MSFT aa=0
        self.assertEqual(yf["adjusted_rows"], 1)   # AAPL aa=1
        self.assertEqual(yf["other_basis_rows"], 0)
        fb = s["providers"]["fallback:yfinance"]
        self.assertEqual(fb["raw_rows"], 0)
        self.assertEqual(fb["adjusted_rows"], 1)

    # ----- date range ----------------------------------------------------
    def test_date_range_per_provider(self) -> None:
        s = self._summary()
        self.assertEqual(s["providers"]["polygon"]["min_date"], "2026-03-03")
        self.assertEqual(s["providers"]["polygon"]["max_date"], "2026-03-03")

    # ----- caveat --------------------------------------------------------
    def test_caveat_present_and_honest(self) -> None:
        s = self._summary()
        self.assertIn("caveat", s)
        self.assertIn("not recorded at write time", s["caveat"])
        self.assertIn("not that data is invalid", s["caveat"])

    # ----- no mutation ---------------------------------------------------
    def test_report_does_not_mutate_table(self) -> None:
        before = sqlite3.connect(self.db_path).execute(
            "SELECT COUNT(*) FROM price_cache").fetchone()[0]
        self._summary()
        self._summary()
        after = sqlite3.connect(self.db_path).execute(
            "SELECT COUNT(*) FROM price_cache").fetchone()[0]
        self.assertEqual(before, after)

    # ----- CLI plumbing --------------------------------------------------
    def test_main_json_emits_valid_payload(self) -> None:
        buf = StringIO()
        rc = report.main(["--json", "--db-path", self.db_path], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total_rows"], len(_FIXTURE_ROWS))
        self.assertIn("legacy_unknown", payload["providers"])

    def test_main_text_runs(self) -> None:
        buf = StringIO()
        rc = report.main(["--db-path", self.db_path], out=buf)
        self.assertEqual(rc, 0)
        self.assertIn("legacy_unknown", buf.getvalue())


class EmptyAndMissingTest(unittest.TestCase):
    def test_empty_table_is_honest(self) -> None:
        path = _make_db([])
        try:
            s = report.summarize_provider_coverage(db_path=path)
        finally:
            os.remove(path)
        self.assertEqual(s["total_rows"], 0)
        self.assertEqual(s["total_tickers"], 0)
        self.assertEqual(s["provider_count"], 0)
        self.assertEqual(s["providers"], {})
        self.assertIn("caveat", s)

    def test_missing_db_returns_empty_shape(self) -> None:
        s = report.summarize_provider_coverage(
            db_path=os.path.join(tempfile.gettempdir(), f"nope_{uuid.uuid4().hex}.db"),
        )
        self.assertEqual(s["total_rows"], 0)
        self.assertEqual(s["providers"], {})

    def test_other_basis_rows_counted(self) -> None:
        # Defensive branch: an auto_adjust value outside {0,1} is counted
        # under other_basis_rows, not silently dropped or miscounted as raw.
        path = _make_db([("ZZZ", "2026-03-02", 50.0, 1000.0, 2, "ts", "yfinance")])
        try:
            s = report.summarize_provider_coverage(db_path=path)
        finally:
            os.remove(path)
        yf = s["providers"]["yfinance"]
        self.assertEqual(yf["row_count"], 1)
        self.assertEqual(yf["raw_rows"], 0)
        self.assertEqual(yf["adjusted_rows"], 0)
        self.assertEqual(yf["other_basis_rows"], 1)

    def test_default_db_path_is_db_dot_db_file(self) -> None:
        # When db_path is omitted, the report follows db.DB_FILE — proven
        # by pointing DB_FILE at our fixture and reading it back.
        path = _make_db(_FIXTURE_ROWS)
        original = db.DB_FILE
        try:
            db.DB_FILE = path
            s = report.summarize_provider_coverage()
        finally:
            db.DB_FILE = original
            os.remove(path)
        self.assertEqual(s["total_rows"], len(_FIXTURE_ROWS))


if __name__ == "__main__":
    unittest.main()

"""
tests/test_price_cache_purge.py

Focused tests for price_cache._purge_corrupt_rows().

Proves three invariants:
  1) Corrupt rows (integer close < 10 + volume == 1_000_000) are purged.
  2) Repeated calls are idempotent — no error, no double-delete, no data loss.
  3) Healthy rows (real close values) are untouched by the purge.

No network calls, no market_check dependency — pure SQLite tests.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db as _db
import price_cache


# ---------------------------------------------------------------------------
# Helper — low-level DB seeding that bypasses price_cache._write_rows
# (which already rejects corrupt rows at write time, so we seed directly).
# ---------------------------------------------------------------------------

def _seed_row(
    conn: sqlite3.Connection,
    ticker: str,
    date_str: str,
    close: float,
    volume: float,
    auto_adjust: int = 0,
    fetched_at: str = "2026-01-01T00:00:00+00:00",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO price_cache
            (ticker, date, close, volume, auto_adjust, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ticker, date_str, close, volume, auto_adjust, fetched_at),
    )


def _count_rows(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]


def _get_closes(conn: sqlite3.Connection, ticker: str) -> list[float | None]:
    rows = conn.execute(
        "SELECT close FROM price_cache WHERE ticker = ? ORDER BY date",
        (ticker,),
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Base — isolated temp DB per test
# ---------------------------------------------------------------------------


class _PurgBase(unittest.TestCase):

    def setUp(self):
        self._orig_db = _db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_purge_{uuid.uuid4().hex}.db"
        )
        _db.DB_FILE = self._tmp
        # Reset the table-ready flag so _ensure_table() re-initialises
        # against the new temp file for each test.
        price_cache._reset_table_ready_for_tests()
        price_cache._ensure_table()   # create schema in the temp file

    def tearDown(self):
        _db.DB_FILE = self._orig_db
        price_cache._reset_table_ready_for_tests()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    # Convenience: seed directly into the live temp DB.
    def _seed(self, ticker, date_str, close, volume, auto_adjust=0):
        with sqlite3.connect(_db.DB_FILE) as conn:
            _seed_row(conn, ticker, date_str, close, volume, auto_adjust)

    def _count(self) -> int:
        with sqlite3.connect(_db.DB_FILE) as conn:
            return _count_rows(conn)

    def _closes(self, ticker) -> list:
        with sqlite3.connect(_db.DB_FILE) as conn:
            return _get_closes(conn, ticker)


# ---------------------------------------------------------------------------
# 1) Corrupt rows are purged
# ---------------------------------------------------------------------------


class TestCorruptRowsPurged(_PurgBase):
    """Rows with integer close < 10 and volume == 1_000_000 must be deleted."""

    def test_single_corrupt_row_deleted(self):
        self._seed("GLD", "2026-01-02", close=1.0, volume=1_000_000.0)
        self.assertEqual(self._count(), 1)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 1)
        self.assertEqual(self._count(), 0)

    def test_multiple_corrupt_rows_all_deleted(self):
        for i, d in enumerate(["2026-01-02", "2026-01-03", "2026-01-06"], start=1):
            self._seed("GLD", d, close=float(i), volume=1_000_000.0)
        self.assertEqual(self._count(), 3)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 3)
        self.assertEqual(self._count(), 0)

    def test_corrupt_rows_across_tickers_all_deleted(self):
        self._seed("GLD", "2026-01-02", close=1.0, volume=1_000_000.0)
        self._seed("TLT", "2026-01-02", close=2.0, volume=1_000_000.0)
        self._seed("GLD", "2026-01-03", close=3.0, volume=1_000_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 3)
        self.assertEqual(self._count(), 0)

    def test_returns_zero_when_nothing_to_purge(self):
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 0)

    def test_boundary_close_9_is_corrupt(self):
        """close=9.0 with volume=1M and integer close → corrupt."""
        self._seed("USO", "2026-01-02", close=9.0, volume=1_000_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 1)

    def test_boundary_close_10_is_not_corrupt(self):
        """close=10.0 is NOT flagged — fingerprint requires close < 10."""
        self._seed("USO", "2026-01-02", close=10.0, volume=1_000_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count(), 1)


# ---------------------------------------------------------------------------
# 2) Repeated calls are idempotent
# ---------------------------------------------------------------------------


class TestPurgeIdempotent(_PurgBase):
    """Calling _purge_corrupt_rows() multiple times is safe and returns 0
    on subsequent calls when no new corrupt rows have appeared."""

    def test_second_call_returns_zero(self):
        self._seed("GLD", "2026-01-02", close=2.0, volume=1_000_000.0)
        first = price_cache._purge_corrupt_rows()
        self.assertEqual(first, 1)
        second = price_cache._purge_corrupt_rows()
        self.assertEqual(second, 0)

    def test_ten_calls_no_error(self):
        self._seed("GLD", "2026-01-02", close=3.0, volume=1_000_000.0)
        results = [price_cache._purge_corrupt_rows() for _ in range(10)]
        self.assertEqual(results[0], 1)
        self.assertTrue(all(r == 0 for r in results[1:]))

    def test_purge_after_new_corrupt_rows_injected(self):
        """If corrupt rows reappear mid-session, a second purge removes them."""
        self._seed("GLD", "2026-01-02", close=1.0, volume=1_000_000.0)
        price_cache._purge_corrupt_rows()   # first purge
        self.assertEqual(self._count(), 0)

        # Corrupt rows arrive again (simulating the mid-session scenario).
        self._seed("GLD", "2026-01-03", close=2.0, volume=1_000_000.0)
        self.assertEqual(self._count(), 1)

        second = price_cache._purge_corrupt_rows()
        self.assertEqual(second, 1)
        self.assertEqual(self._count(), 0)

    def test_empty_db_repeated_purge_safe(self):
        for _ in range(5):
            result = price_cache._purge_corrupt_rows()
            self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# 3) Healthy rows are preserved
# ---------------------------------------------------------------------------


class TestHealthyRowsPreserved(_PurgBase):
    """Real price rows must survive the purge unchanged."""

    def test_healthy_close_survives(self):
        """A row with a realistic close price is not deleted."""
        self._seed("GLD", "2026-01-02", close=185.50, volume=1_000_000.0)
        price_cache._purge_corrupt_rows()
        self.assertEqual(self._count(), 1)
        self.assertAlmostEqual(self._closes("GLD")[0], 185.50)

    def test_healthy_low_volume_row_survives(self):
        """Volume != 1_000_000 with a corrupt-looking close is not flagged."""
        self._seed("SHY", "2026-01-02", close=5.0, volume=500_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count(), 1)

    def test_healthy_fractional_close_survives(self):
        """A non-integer close below 10 does not match the corrupt fingerprint."""
        self._seed("SHY", "2026-01-02", close=8.75, volume=1_000_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count(), 1)

    def test_mixed_corrupt_and_healthy_only_corrupt_removed(self):
        """With both corrupt and healthy rows, only corrupt ones are deleted."""
        # Corrupt
        self._seed("GLD", "2026-01-02", close=1.0, volume=1_000_000.0)
        self._seed("GLD", "2026-01-03", close=2.0, volume=1_000_000.0)
        # Healthy
        self._seed("GLD", "2026-01-04", close=185.50, volume=2_500_000.0)
        self._seed("TLT", "2026-01-02", close=92.30,  volume=3_000_000.0)

        self.assertEqual(self._count(), 4)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 2)
        self.assertEqual(self._count(), 2)

        gld_closes = self._closes("GLD")
        self.assertEqual(len(gld_closes), 1)
        self.assertAlmostEqual(gld_closes[0], 185.50)

        tlt_closes = self._closes("TLT")
        self.assertEqual(len(tlt_closes), 1)
        self.assertAlmostEqual(tlt_closes[0], 92.30)

    def test_null_close_row_not_flagged(self):
        """A row with close=NULL is not matched by the corrupt fingerprint."""
        self._seed("GLD", "2026-01-02", close=None, volume=1_000_000.0)
        deleted = price_cache._purge_corrupt_rows()
        self.assertEqual(deleted, 0)
        self.assertEqual(self._count(), 1)

    def test_healthy_rows_values_unchanged_after_purge(self):
        """Close values of healthy rows are byte-identical after purge."""
        self._seed("GLD",  "2026-01-02", close=185.50, volume=2_500_000.0)
        self._seed("TLT",  "2026-01-02", close=92.30,  volume=3_000_000.0)
        self._seed("SLV",  "2026-01-02", close=24.10,  volume=800_000.0)

        price_cache._purge_corrupt_rows()

        self.assertAlmostEqual(self._closes("GLD")[0], 185.50)
        self.assertAlmostEqual(self._closes("TLT")[0], 92.30)
        self.assertAlmostEqual(self._closes("SLV")[0], 24.10)


if __name__ == "__main__":
    unittest.main()

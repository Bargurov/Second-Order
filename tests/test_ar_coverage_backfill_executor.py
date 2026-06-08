"""V2B — gated AR-coverage backfill executor safety tests.

Proves the executor:
  * REFUSES to fetch/write without confirm_paid=True (no provider call, no write),
  * REFUSES to target the live archive path,
  * writes fetched rows into the COPY only and leaves db.DB_FILE + the active
    provider restored afterward (DB-copy isolation),
  * honours a request cap,
  * scrubs non-finite closes (NaN never lands as a finite cache value).

Self-contained: a fake in-process provider (no network), temp DB copies; the
live archive is never opened.
"""
import math
import os
import sqlite3
import sys
import unittest

import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from stats.ar_coverage_backfill import backfill_into_copy  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------

class _FakeProvider:
    """In-process provider — records calls, returns a clean business-day frame.

    Closes are floats > 10 with volume != 1e6 so they dodge price_cache's
    suspect-fixture fingerprint (close<10 & vol==1e6 & integer)."""
    def __init__(self):
        self.calls = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        self.calls.append((ticker, start, end, auto_adjust))
        idx = pd.bdate_range(start=start, end=end)
        if len(idx) == 0:
            return None
        close = [100.0 + i * 0.37 for i in range(len(idx))]
        vol = [2_000_000.0] * len(idx)
        return pd.DataFrame({"Close": close, "Volume": vol}, index=idx)


class _NaNProvider(_FakeProvider):
    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        df = super().fetch_daily(ticker, start=start, end=end, auto_adjust=auto_adjust)
        if df is not None and len(df):
            df.iloc[0, df.columns.get_loc("Close")] = float("nan")
        return df


def _new_copy_db() -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db", prefix="v2b_copy_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
        "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT, "
        "UNIQUE(ticker, date, auto_adjust))"
    )
    con.commit()
    con.close()
    return path


def _count(path: str) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
    finally:
        con.close()


_W = [{"symbol": "AAA", "start": "2025-01-01", "end": "2025-04-01"}]


class TestBackfillGate(unittest.TestCase):
    def setUp(self):
        self.copy = _new_copy_db()

    def tearDown(self):
        try:
            os.remove(self.copy)
        except OSError:
            pass

    def test_refuses_without_confirm_paid_and_makes_no_provider_call(self):
        fake = _FakeProvider()
        with self.assertRaises(PermissionError):
            backfill_into_copy(self.copy, _W, confirm_paid=False, provider=fake)
        self.assertEqual(len(fake.calls), 0)
        self.assertEqual(_count(self.copy), 0)

    def test_refuses_to_target_live_archive(self):
        fake = _FakeProvider()
        with self.assertRaises(ValueError):
            backfill_into_copy("events.db", _W, confirm_paid=True, provider=fake)
        self.assertEqual(len(fake.calls), 0)


class TestBackfillExecution(unittest.TestCase):
    def setUp(self):
        self.copy = _new_copy_db()

    def tearDown(self):
        try:
            os.remove(self.copy)
        except OSError:
            pass

    def test_writes_rows_into_the_copy(self):
        fake = _FakeProvider()
        summary = backfill_into_copy(self.copy, _W, confirm_paid=True, provider=fake)
        self.assertGreater(summary["rows_written"], 0)
        self.assertEqual(summary["rows_after"], _count(self.copy))
        self.assertGreater(len(fake.calls), 0)

    def test_restores_db_file_and_provider_after_run(self):
        import db as _db
        import market_data
        before_db = _db.DB_FILE
        before_provider = market_data.get_provider()
        backfill_into_copy(self.copy, _W, confirm_paid=True, provider=_FakeProvider())
        self.assertEqual(_db.DB_FILE, before_db)
        self.assertIs(market_data.get_provider(), before_provider)

    def test_request_cap_is_honoured(self):
        fake = _FakeProvider()
        windows = [{"symbol": f"S{i}", "start": "2025-01-01", "end": "2025-04-01"} for i in range(5)]
        summary = backfill_into_copy(self.copy, windows, confirm_paid=True, provider=fake, max_requests=3)
        self.assertEqual(summary["requests"], 3)
        self.assertLessEqual(len(fake.calls), 3)

    def test_nan_close_never_lands_as_a_finite_value(self):
        backfill_into_copy(self.copy, _W, confirm_paid=True, provider=_NaNProvider())
        con = sqlite3.connect(f"file:{self.copy}?mode=ro", uri=True)
        closes = [r[0] for r in con.execute("SELECT close FROM price_cache WHERE close IS NOT NULL")]
        con.close()
        self.assertGreater(len(closes), 0)
        self.assertTrue(all(math.isfinite(x) for x in closes))


if __name__ == "__main__":
    unittest.main()

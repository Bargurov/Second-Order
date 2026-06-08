"""Z1C — targeted SPY interior-gap densifier (copy-only) tests.

Pins the gated contract for ``scripts/z1c_spy_gap_densify.py``:

* REFUSES the live archive; REQUIRES an explicit copy path.
* Fetches/writes ONLY SPY (never candidate tickers) into the copy.
* Computes targeted windows from candidate event dates and fills only the
  missing (pure-empty) sub-ranges — additive, never overwriting an existing row.
* FREE-only: pins the free yfinance provider, refuses a non-free provider, and
  the module never references confirm_paid or the paid path.
* The report labels every result copied-DB-only / not promoted.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta

import pandas as pd
import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import db  # noqa: E402
from scripts import z1c_spy_gap_densify as Z  # noqa: E402


class _FakeProvider:
    provider_name = "yfinance"

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


class _PaidProvider(_FakeProvider):
    provider_name = "polygon"


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig_db = db.DB_FILE
        self._copy = os.path.join(tempfile.gettempdir(), f"z1c_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._copy
        db.init_db()
        db.DB_FILE = self._orig_db
        self._paths = [self._copy]

    def tearDown(self):
        db.DB_FILE = self._orig_db
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _pack(self, event_dates) -> str:
        cands = [{"id": f"c{i}", "event_date": d} for i, d in enumerate(event_dates)]
        path = os.path.join(tempfile.gettempdir(), f"z1c_pack_{uuid.uuid4().hex}.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"candidates": cands}, fh)
        self._paths.append(path)
        return path

    def _seed(self, ticker, dates, *, close=150.0):
        con = sqlite3.connect(self._copy)
        con.executemany(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?,?,?,?,0,?)",
            [(ticker, d, close, 2_000_000.0, "t") for d in dates],
        )
        con.commit()
        con.close()

    def _spy_dates(self):
        con = sqlite3.connect(f"file:{self._copy}?mode=ro", uri=True)
        try:
            return [r[0] for r in con.execute(
                "SELECT date FROM price_cache WHERE ticker='SPY' AND auto_adjust=0 ORDER BY date")]
        finally:
            con.close()


class TestGates(_Base):
    def test_refuses_live_target(self):
        pack = self._pack(["2024-03-21"])
        with self.assertRaises(ValueError):
            Z.densify_spy(copy_path=db.LIVE_DB_FILE, candidates_path=pack, provider=_FakeProvider())

    def test_requires_explicit_copy_path(self):
        pack = self._pack(["2024-03-21"])
        for bad in (None, ""):
            with self.assertRaises(ValueError):
                Z.densify_spy(copy_path=bad, candidates_path=pack, provider=_FakeProvider())

    def test_refuses_non_free_provider(self):
        pack = self._pack(["2024-03-21"])
        with self.assertRaises(ValueError):
            Z.densify_spy(copy_path=self._copy, candidates_path=pack, provider=_PaidProvider())


class TestDensify(_Base):
    def _window_bdays(self, ev, before, after):
        s = (date.fromisoformat(ev) - timedelta(days=before)).isoformat()
        e = (date.fromisoformat(ev) + timedelta(days=after)).isoformat()
        return [d.date().isoformat() for d in pd.bdate_range(s, e)]

    def test_fetches_only_spy_and_fills_interior_hole(self):
        ev = "2024-03-21"
        full = self._window_bdays(ev, 130, 40)
        # dense SPY except a >5d interior hole in the middle third
        hole = set(full[40:60])
        seeded = [d for d in full if d not in hole]
        self._seed("SPY", seeded)
        self._seed("AAPL", full)  # asset present; must NOT be fetched
        fake = _FakeProvider()
        pack = self._pack([ev])
        before = len(self._spy_dates())
        summary = Z.densify_spy(copy_path=self._copy, candidates_path=pack, provider=fake,
                                days_before=130, days_after=40)
        self.assertTrue(fake.calls, "expected at least one SPY fetch")
        self.assertEqual({c[0] for c in fake.calls}, {"SPY"}, "must fetch ONLY SPY")
        self.assertGreater(summary["rows_written"], 0)
        self.assertGreater(len(self._spy_dates()), before)
        # the hole is filled now
        now = set(self._spy_dates())
        self.assertTrue(hole.issubset(now), "interior hole should be filled")

    def test_targeted_windows_from_event_dates(self):
        ev = "2024-03-21"
        fake = _FakeProvider()
        pack = self._pack([ev])
        # empty SPY cache -> one big run covering the window; assert it sits in-window
        Z.densify_spy(copy_path=self._copy, candidates_path=pack, provider=fake,
                      days_before=130, days_after=40)
        lo = (date.fromisoformat(ev) - timedelta(days=131)).isoformat()
        hi = (date.fromisoformat(ev) + timedelta(days=41)).isoformat()
        for tk, s, e, aa in fake.calls:
            self.assertGreaterEqual(s, lo)
            self.assertLessEqual(e, hi)

    def test_additive_never_overwrites_existing_row(self):
        ev = "2024-03-21"
        full = self._window_bdays(ev, 130, 40)
        hole = set(full[40:60])
        seeded = [d for d in full if d not in hole]
        self._seed("SPY", seeded, close=999.0)  # sentinel close on existing rows
        pack = self._pack([ev])
        Z.densify_spy(copy_path=self._copy, candidates_path=pack, provider=_FakeProvider(),
                      days_before=130, days_after=40)
        con = sqlite3.connect(f"file:{self._copy}?mode=ro", uri=True)
        try:
            # an existing (non-hole) row keeps its sentinel close — not overwritten
            keep = full[10]
            self.assertNotIn(keep, hole)
            close = con.execute(
                "SELECT close FROM price_cache WHERE ticker='SPY' AND date=? AND auto_adjust=0",
                (keep,)).fetchone()[0]
            self.assertEqual(close, 999.0)
        finally:
            con.close()

    def test_restores_db_file_and_provider(self):
        import market_data
        pack = self._pack(["2024-03-21"])
        before_db = db.DB_FILE
        before_prov = market_data.get_provider()
        Z.densify_spy(copy_path=self._copy, candidates_path=pack, provider=_FakeProvider(),
                      days_before=130, days_after=40)
        self.assertEqual(db.DB_FILE, before_db)
        self.assertIs(market_data.get_provider(), before_prov)


class TestReportAndSafety(unittest.TestCase):
    def test_summary_labels_copy_only_not_promoted(self):
        summary = {"rows_written": 0, "requests": 0, "per_event": [], "remaining_gaps": []}
        text = Z.summarize(summary).lower()
        self.assertIn("copy", text)
        self.assertIn("not promoted", text)

    def test_module_has_no_confirm_paid_or_paid_path(self):
        with open(os.path.join(_REPO, "scripts", "z1c_spy_gap_densify.py"), encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("confirm_paid", "PolygonProvider", "Polygon", "polygon"):
            self.assertNotIn(forbidden, src, f"densifier must not reference {forbidden!r}")


if __name__ == "__main__":
    unittest.main()

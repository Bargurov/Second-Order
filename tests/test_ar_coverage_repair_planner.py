"""V2A — exposed-name AR coverage repair planner (read-only, dry-run).

Proves the planner:
  * classifies every missing-unit fixability bucket correctly (pure),
  * reproduces a coverage snapshot against a synthetic fixture DB using the
    REAL read-only event-study engine,
  * writes NOTHING (source price_cache row count unchanged — dry-run only),
  * emits bounded backfill windows for fixable units and a request estimate
    WITHOUT importing or calling any provider,
  * the CLI prints a dry-run summary and REFUSES write/fetch/backfill flags.

Self-contained: builds its own tiny SQLite fixture (clean-clone safe); never
touches the live archive.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from stats import ar_coverage_repair_planner as P  # noqa: E402

TODAY = date(2026, 6, 8)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _make_fixture() -> str:
    """A temp DB where AAA is event-study-covered and several losers are not."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="arcov_fix_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT, "
        "market_tickers TEXT, mechanism_summary TEXT, what_changed TEXT, "
        "transmission_chain TEXT)"
    )
    con.execute(
        "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
        "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT)"
    )
    bars = _bdays(date(2025, 1, 1), 90)            # ~Jan–May 2025, all past
    event_iso = bars[65].isoformat()
    def series(tk, dates, a, b):
        rows = [(tk, d.isoformat(), 100.0 + i * a + ((i * 3) % 7) * b, 1000.0, 0,
                 "2025-06-01", "test") for i, d in enumerate(dates)]
        con.executemany("INSERT INTO price_cache VALUES (?,?,?,?,?,?,?)", rows)
    series("SPY", bars, 0.08, 0.20)
    series("AAA", bars, 0.10, 0.25)               # covered beneficiary
    # E1 — one covered beneficiary + a no-cache loser + a proxy loser
    import json
    con.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        (1, event_iso, json.dumps([
            {"symbol": "AAA", "role": "beneficiary"},
            {"symbol": "BBB", "role": "loser"},          # no cache
            {"symbol": "PRX (proxy)", "role": "loser"},  # alias
        ]), "", "", "[]"),
    )
    # E2 — a future event with a missing loser (forward bars not yet elapsed)
    con.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        (2, "2026-06-05", json.dumps([
            {"symbol": "EEE", "role": "loser"},
        ]), "", "", "[]"),
    )
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------------------
# Pure classification
# ---------------------------------------------------------------------------

class TestClassifyMissing(unittest.TestCase):
    def test_proxy_symbol_is_alias_manual_review(self):
        c = P.classify_missing("DUG (proxy)", "2026-04-10",
                               ["no_cached_prices_for_primary_ticker"], None, TODAY)
        self.assertEqual(c, P.ALIAS)

    def test_future_event_is_not_yet_fixable(self):
        c = P.classify_missing("XYZ", "2026-06-05",
                               ["missing_forward_cache_20d"], ("2026-01-01", "2026-06-05"), TODAY)
        self.assertEqual(c, P.FUTURE)

    def test_no_cache_is_full_backfill(self):
        c = P.classify_missing("NIO", "2026-04-03",
                               ["no_cached_prices_for_primary_ticker"], None, TODAY)
        self.assertEqual(c, P.NO_CACHE)

    def test_short_history_is_backfill_earlier(self):
        c = P.classify_missing("DOW", "2026-04-20",
                               ["insufficient_estimation_window_primary"],
                               ("2026-04-06", "2026-04-28"), TODAY)
        self.assertEqual(c, P.BACKFILL_EARLIER)

    def test_forward_hole_is_backfill_forward(self):
        # event old enough that +20 business days is already in the past (not future)
        c = P.classify_missing("DAL", "2026-05-01",
                               ["missing_forward_cache_20d"], ("2026-01-06", "2026-05-20"), TODAY)
        self.assertEqual(c, P.BACKFILL_FORWARD)

    def test_contiguity_gap_is_maybe(self):
        c = P.classify_missing("FXI", "2026-03-10",
                               ["no_contiguous_aligned_window"], ("2026-01-12", "2026-05-29"), TODAY)
        self.assertEqual(c, P.GAP)

    def test_cache_ending_before_event_is_delisted_stale(self):
        c = P.classify_missing("ZIM", "2026-04-10",
                               ["insufficient_estimation_window_primary"],
                               ("2021-01-28", "2021-05-21"), TODAY)
        self.assertEqual(c, P.DELISTED)

    def test_fixable_set_excludes_alias_future_delisted(self):
        for cls in (P.ALIAS, P.FUTURE, P.DELISTED):
            self.assertNotIn(cls, P.FIXABLE_CLASSES)
        for cls in (P.NO_CACHE, P.BACKFILL_EARLIER, P.BACKFILL_FORWARD, P.GAP):
            self.assertIn(cls, P.FIXABLE_CLASSES)


class TestProposedWindow(unittest.TestCase):
    def test_window_brackets_the_event_with_pre_and_post_room(self):
        start, end = P.proposed_window("2026-04-20")
        self.assertLess(start, "2026-04-20")
        self.assertGreater(end, "2026-04-20")
        # enough pre-event room for a 60-bar estimation window (~3 months)
        self.assertLess(start, "2026-02-01")


# ---------------------------------------------------------------------------
# DB integration — real engine on a synthetic fixture, read-only
# ---------------------------------------------------------------------------

class TestBuildRepairPlan(unittest.TestCase):
    def setUp(self):
        self.db = _make_fixture()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _rowcount(self):
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        finally:
            con.close()

    def test_reproduces_snapshot_covered_beneficiary(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        snap = plan["snapshot"]
        self.assertEqual(snap["beneficiary"], {"covered": 1, "total": 1})
        self.assertEqual(snap["loser"]["covered"], 0)
        self.assertEqual(snap["loser"]["total"], 3)   # BBB, PRX, EEE
        self.assertEqual(snap["total"]["covered"], 1)

    def test_dry_run_writes_nothing(self):
        before = self._rowcount()
        P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        self.assertEqual(self._rowcount(), before)

    def test_enumerates_missing_loser_units_with_fields(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        losers = [u for u in plan["missing_units"] if u["role"] == "loser"]
        self.assertGreaterEqual(len(losers), 3)
        u = losers[0]
        for key in ("event_id", "event_date", "symbol", "role",
                    "blocking_reasons", "fixability_class"):
            self.assertIn(key, u)

    def test_classifies_proxy_and_no_cache_and_future(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        by_sym = {u["symbol"]: u["fixability_class"] for u in plan["missing_units"]}
        self.assertEqual(by_sym["BBB"], P.NO_CACHE)
        self.assertEqual(by_sym["PRX (proxy)"], P.ALIAS)
        self.assertEqual(by_sym["EEE"], P.FUTURE)

    def test_emits_windows_only_for_fixable_units(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        win_syms = {w["symbol"] for w in plan["planned_windows"]}
        self.assertIn("BBB", win_syms)          # no-cache → fixable → planned
        self.assertNotIn("PRX (proxy)", win_syms)  # alias → not planned
        self.assertNotIn("EEE", win_syms)          # future → not planned

    def test_request_estimate_counts_distinct_fixable_symbols(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        self.assertEqual(plan["request_estimate"], len({w["symbol"] for w in plan["planned_windows"]}))
        self.assertIsInstance(plan["est_cache_rows"], int)

    def test_disclaimer_is_representativeness_not_significance(self):
        plan = P.build_repair_plan(self.db, scenario="scored", today=TODAY)
        d = plan["disclaimer"].lower()
        self.assertIn("representativeness", d)
        self.assertIn("not", d)
        # the disclaimer explicitly disclaims each of these
        for term in ("statistical significance", "edge"):
            self.assertIn(term, d)


class TestNoProviderImports(unittest.TestCase):
    def test_planner_source_has_no_provider_write_path(self):
        with open(os.path.join(_REPO, "stats", "ar_coverage_repair_planner.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("import price_cache", "from price_cache",
                          "import market_data", "from market_data",
                          "fetch_daily", "yfinance"):
            self.assertNotIn(forbidden, src, f"planner must not reference {forbidden!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.db = _make_fixture()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join("scripts", "ar_coverage_repair_plan.py"), *args],
            cwd=_REPO, capture_output=True, text=True,
        )

    def test_dry_run_prints_summary(self):
        r = self._run("--dry-run", "--scenario", "scored", "--db", self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (r.stdout + r.stderr).lower()
        self.assertIn("coverage", out)
        self.assertIn("window", out)
        self.assertIn("representativeness", out)

    def test_backfill_flag_is_refused_nonzero(self):
        r = self._run("--backfill", "--db", self.db)
        self.assertNotEqual(r.returncode, 0)

    def test_write_flag_is_refused_nonzero(self):
        r = self._run("--write", "--db", self.db)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

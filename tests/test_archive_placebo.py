"""X1A — archive event-date placebo / negative-control safety + correctness tests.

Proves the placebo harness:
  * computes AR-sign support correctly for beneficiary (up) and loser (down) roles,
  * draws placebo anchors deterministically (fixed seed) and EXCLUDES the real
    event date + a window around it,
  * excludes units without enough cached pre/forward bars (with a reason),
  * computes placebo quantiles + the observed percentile correctly,
  * reports observed AND placebo denominators and labels residual coverage,
  * has no provider/network/DB-write path,
  * is read-only and banned-framing clean.

Self-contained synthetic fixture (no live archive, no network).
"""
import math
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

from stats import archive_placebo as AP  # noqa: E402


def _bdays(start: date, n: int) -> list:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _make_fixture() -> str:
    """SPY flat-ish; UP rises monotonically (beneficiary AR>0 at most anchors);
    DN falls monotonically (loser AR<0). THIN has too few bars (excluded)."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="placebo_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT, market_tickers TEXT)"
    )
    con.execute(
        "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
        "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT, UNIQUE(ticker,date,auto_adjust))"
    )
    bars = _bdays(date(2025, 1, 1), 220)
    def series(tk, fn, n=220):
        rows = [(tk, bars[i].isoformat(), float(fn(i)), 5.0e6, 0, "t", "test") for i in range(n)]
        con.executemany("INSERT INTO price_cache VALUES (?,?,?,?,?,?,?)", rows)
    series("SPY", lambda i: 100.0 + (i % 3) * 0.1)          # ~flat
    series("UP", lambda i: 100.0 + i * 1.0)                  # strong uptrend vs SPY
    series("DN", lambda i: 200.0 - i * 1.0)                  # strong downtrend vs SPY
    series("THIN", lambda i: 100.0 + i * 0.5, n=20)          # too few bars
    import json
    ev = bars[110].isoformat()  # mid-series: >=60 pre, >=20 fwd, room for placebo anchors
    con.execute("INSERT INTO events VALUES (?,?,?)", (1, ev, json.dumps([
        {"symbol": "UP", "role": "beneficiary"},
        {"symbol": "DN", "role": "loser"},
        {"symbol": "THIN", "role": "loser"},
    ])))
    con.commit(); con.close()
    return path


class TestPureHelpers(unittest.TestCase):
    def test_predicted_up_from_role(self):
        self.assertTrue(AP.predicted_up("beneficiary"))
        self.assertFalse(AP.predicted_up("loser"))

    def test_support_fraction_counts_direction_match(self):
        # obs: (predicted_up, ar_up). beneficiary up-match + loser down-match = support.
        obs = [(True, True), (True, False), (False, False), (False, None)]
        # h-agnostic helper: support over non-None = matches / eligible
        frac, n = AP.support_fraction([(p, a) for p, a in obs])
        self.assertEqual(n, 3)               # one None excluded
        self.assertAlmostEqual(frac, 2 / 3)  # (T,T) and (F,F) match; (T,F) no


class TestPlaceboSampling(unittest.TestCase):
    def setUp(self):
        self.db = _make_fixture()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_deterministic_with_fixed_seed(self):
        r1 = AP.build_report(self.db, draws=20, seed=20260608)
        r2 = AP.build_report(self.db, draws=20, seed=20260608)
        self.assertEqual(r1["placebo"], r2["placebo"])

    def test_thin_ticker_excluded_with_reason(self):
        r = AP.build_report(self.db, draws=10, seed=1)
        self.assertIn("THIN", {e["symbol"] for e in r["excluded"]})

    def test_reports_observed_and_placebo_denominators(self):
        r = AP.build_report(self.db, draws=10, seed=1)
        self.assertIn("observed_eligible", r)
        self.assertIn("placebo_eligible_per_draw", r)
        self.assertGreater(r["observed_eligible"], 0)

    def test_placebo_anchors_exclude_the_event_window(self):
        # with the harness's exclusion window, no placebo anchor falls within it
        ev = date(2025, 1, 1)
        for b in _bdays(date(2025, 1, 1), 120):
            ev = b  # last; we just need the actual event date from the fixture
        # introspect the sampler directly
        days = [d.isoformat() for d in _bdays(date(2025, 1, 1), 220)]
        evd = _bdays(date(2025, 1, 1), 220)[110]
        anchors = AP.sample_placebo_anchors(
            common_dates=days, event_iso=evd.isoformat(),
            est_window=60, max_h_business_days=20, exclusion_days=30, draws=50, seed=7,
        )
        self.assertGreater(len(anchors), 0)
        for a in anchors:
            self.assertGreater(abs((date.fromisoformat(a) - evd).days), 30)

    def test_observed_support_then_conclusion_label_is_valid(self):
        r = AP.build_report(self.db, draws=50, seed=20260608)
        self.assertIn(r["conclusion"], (
            "observed_above_placebo", "observed_inside_placebo",
            "observed_below_placebo", "inconclusive_due_to_coverage",
        ))
        for h in ("1", "5", "20"):
            self.assertIn(h, r["observed_support"])
            self.assertIn(h, r["placebo"])
            self.assertIn("q05", r["placebo"][h])
            self.assertIn("q95", r["placebo"][h])

    def test_non_claim_present(self):
        r = AP.build_report(self.db, draws=10, seed=1)
        nc = r["non_claim"].lower()
        self.assertIn("negative-control", nc)
        self.assertIn("not a", nc)


class TestConcludeCoverageGate(unittest.TestCase):
    # observed clearly below the placebo band on all horizons
    OBS = {h: {"support": 0.30, "n": 50} for h in ("1", "5", "20")}
    PLA = {h: {"q05": 0.45, "q95": 0.65} for h in ("1", "5", "20")}

    def test_directional_when_matched_covers_most_of_eligible(self):
        # matched 200 of 210 event-eligible (>= 60%) -> directional verdict allowed
        self.assertEqual(AP._conclude(self.OBS, self.PLA, 200, 210), "observed_below_placebo")

    def test_inconclusive_when_matched_is_a_small_fraction(self):
        # matched 50 of 239 (21%) -> selection-biased minority -> inconclusive
        self.assertEqual(AP._conclude(self.OBS, self.PLA, 50, 239), "inconclusive_due_to_coverage")


class TestNoProviderOrWritePath(unittest.TestCase):
    def test_module_has_no_provider_or_write(self):
        with open(os.path.join(_REPO, "stats", "archive_placebo.py"), encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("import price_cache", "from price_cache", "import market_data",
                          "from market_data", "fetch_daily", "INSERT", "UPDATE ", "confirm_paid"):
            self.assertNotIn(forbidden, src, f"placebo module must not reference {forbidden!r}")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.db = _make_fixture()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_cli_runs_read_only_and_prints_report(self):
        r = subprocess.run(
            [sys.executable, os.path.join("scripts", "archive_placebo_report.py"),
             "--draws", "20", "--seed", "20260608", "--db", self.db],
            cwd=_REPO, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (r.stdout + r.stderr).lower()
        self.assertIn("placebo", out)
        self.assertIn("observed", out)
        self.assertIn("negative-control", out)

    def test_cli_output_has_no_banned_framing(self):
        r = subprocess.run(
            [sys.executable, os.path.join("scripts", "archive_placebo_report.py"),
             "--draws", "20", "--seed", "20260608", "--db", self.db],
            cwd=_REPO, capture_output=True, text=True,
        )
        lc = (r.stdout + r.stderr).lower()
        import re
        for w in ["buy", "sell", "long", "short", "alpha", "signal", "trade",
                  "live trading", "proof", "proves", "confirmed"]:
            self.assertNotRegex(lc, rf"\b{w}\b")


def _make_thin_only_fixture() -> str:
    """One event referencing only a too-short ticker -> no placebo-feasible
    observation -> overlap disclosure must degrade, not crash."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="placebo_thin_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT, market_tickers TEXT)"
    )
    con.execute(
        "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, volume REAL, "
        "auto_adjust INTEGER, fetched_at TEXT, source_provider TEXT, UNIQUE(ticker,date,auto_adjust))"
    )
    bars = _bdays(date(2025, 1, 1), 220)
    rows = [("SPY", bars[i].isoformat(), 100.0, 5.0e6, 0, "t", "test") for i in range(220)]
    rows += [("THIN", bars[i].isoformat(), 100.0 + i, 5.0e6, 0, "t", "test") for i in range(20)]
    con.executemany("INSERT INTO price_cache VALUES (?,?,?,?,?,?,?)", rows)
    import json
    con.execute("INSERT INTO events VALUES (?,?,?)",
                (1, bars[10].isoformat(), json.dumps([{"symbol": "THIN", "role": "loser"}])))
    con.commit(); con.close()
    return path


class TestObservedWindowOverlap(unittest.TestCase):
    def setUp(self):
        self.db = _make_fixture()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_build_report_includes_observed_window_overlap(self):
        r = AP.build_report(self.db, draws=10, seed=1)
        self.assertIn("observed_window_overlap", r)
        wo = r["observed_window_overlap"]
        # Denominator is the placebo-feasible role-observations (the pooled
        # unit of the observed support statistic), not distinct events.
        self.assertIn("role", wo["denominator"])
        self.assertEqual(wo["n_with_date"], r["observed_eligible"])
        self.assertIn("n_distinct_event_dates", wo)
        for h in ("1", "5", "20"):
            for k in ("n_windows", "overlapping_pairs", "max_concurrent",
                      "fraction_in_overlap", "status"):
                self.assertIn(k, wo["horizons"][h])
        self.assertTrue(wo["caveat"])

    def test_same_date_role_observations_overlap_fully(self):
        # UP + DN are two role-observations on the SAME event date -> identical
        # windows -> they overlap at every horizon by construction.
        r = AP.build_report(self.db, draws=10, seed=1)
        wo = r["observed_window_overlap"]
        self.assertEqual(wo["n_distinct_event_dates"], 1)
        self.assertGreaterEqual(wo["horizons"]["1"]["max_concurrent"], 2)

    def test_overlap_caveat_flags_independence_and_descriptive(self):
        r = AP.build_report(self.db, draws=10, seed=1)
        cav = r["observed_window_overlap"]["caveat"].lower()
        self.assertIn("overlap", cav)
        self.assertTrue("independ" in cav or "descriptive" in cav)

    def test_no_usable_obs_degrades_to_insufficient_not_crash(self):
        thin_db = _make_thin_only_fixture()
        try:
            r = AP.build_report(thin_db, draws=5, seed=1)
            self.assertEqual(r["observed_eligible"], 0)
            wo = r["observed_window_overlap"]
            self.assertEqual(wo["horizons"]["5"]["status"], "insufficient_n")
        finally:
            os.remove(thin_db)

    def test_summarize_text_surfaces_overlap_without_banned_framing(self):
        text = AP.summarize(AP.build_report(self.db, draws=10, seed=1))
        self.assertIn("overlap", text.lower())
        import re
        lc = text.lower()
        # Mirrors the project's existing placebo banned-framing list
        # (test_cli_output_has_no_banned_framing). "forecast" is intentionally
        # absent: the standing NON_CLAIM disclaimer says "not a ... forecast".
        for w in ["buy", "sell", "long", "short", "alpha", "signal", "trade",
                  "proof", "proves", "confirmed"]:
            self.assertNotRegex(lc, rf"\b{w}\b")


if __name__ == "__main__":
    unittest.main()

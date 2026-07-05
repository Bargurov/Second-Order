"""Tests for the F2 basis-integrity layer.

Covers, in order:

* the ``flag_pairs`` override on ``build_event_study_validation`` — forcing a
  matched raw/raw or adjusted/adjusted basis, with NO silent fallback when the
  forced basis is not computable, and a ``None`` default that leaves the
  canonical path byte-identical;
* ``compare_bases`` — one event recomputed under both forced bases, per-horizon
  deltas (adjusted AR minus raw AR), and the cache-evidence adjustment-factor-step
  flag (a step in the adjusted/raw close ratio inside the forward window);
* the report's denominator reconciliation (70 canonical cohort vs the 78 / 94
  coverage lens) and policy-comparison shape, asserted live.

Fixture DBs only for the behavioral tests (db.DB_FILE rebound); live-archive
assertions are skipped when events.db is absent.  Read-only throughout.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402
from scripts import basis_integrity_report as bir  # noqa: E402

LIVE_DB = ROOT / "events.db"


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors tests/test_sector_relative_readout.py)
# ---------------------------------------------------------------------------


def _bdays_before(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    out.reverse()
    return out


def _bdays_after(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _make_price_db(path: str, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))"
        )
        conn.executemany(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, "
            "fetched_at) VALUES (?,?,?,?,?,?)",
            [(t, d, c, 1000.0, aa, "2026-01-01T00:00:00") for (t, d, c, aa) in rows],
        )
        conn.commit()
    finally:
        conn.close()


_EVENT_D = date(2026, 3, 16)  # a Monday
_EVENT_ISO = _EVENT_D.isoformat()


def _dividend_fixture_rows() -> tuple[list[tuple], int]:
    """XOM with an adjustment-factor step between raw and adjusted bases.

    Raw closes carry a small alternating wiggle (positive AR variance).  The
    adjusted series equals raw * 0.98 up to two sessions after the event and
    raw * 1.00 afterwards — the shape a dividend adjustment leaves in the
    adjusted/raw close ratio.  SPY is identical on both flags.  So the 1d
    horizon (before the step) agrees across bases while 5d / 20d differ by
    roughly the 2% step.
    """
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    event_index = len(pre)
    step_at = event_index + 2  # two sessions after the event close
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        spy = 100.0 * (1 + 0.0004 * i)
        raw = 80.0 * (1 + 0.0005 * i + 0.003 * ((-1) ** i))
        adj = raw * (1.0 if i >= step_at else 0.98)
        rows.append(("SPY", d.isoformat(), round(spy, 4), 0))
        rows.append(("SPY", d.isoformat(), round(spy, 4), 1))
        rows.append(("XOM", d.isoformat(), round(raw, 4), 0))
        rows.append(("XOM", d.isoformat(), round(adj, 4), 1))
    return rows, event_index


def _xom_event() -> dict:
    return {"id": 1, "event_date": _EVENT_ISO,
            "market_tickers": [{"symbol": "XOM", "role": "beneficiary"}]}


class _DbRebind:
    def __init__(self, path: str):
        self.path = path
        self._saved = None

    def __enter__(self):
        self._saved = _db.DB_FILE
        _db.DB_FILE = self.path
        return self

    def __exit__(self, *exc):
        _db.DB_FILE = self._saved


def _ar(payload: dict, h: int):
    for row in payload.get("per_horizon") or []:
        if row.get("horizon") == h:
            return row.get("abnormal_return")
    return None


# ---------------------------------------------------------------------------
# 1. flag_pairs override on the gate
# ---------------------------------------------------------------------------


class ForcedBasisTests(unittest.TestCase):
    def _db(self, dtmp):
        p = os.path.join(dtmp, "events.db")
        rows, _ = _dividend_fixture_rows()
        _make_price_db(p, rows)
        return p

    def test_forced_adjusted_resolves_matched_adjusted(self):
        with tempfile.TemporaryDirectory() as dtmp:
            with _DbRebind(self._db(dtmp)):
                out = esv.build_event_study_validation(
                    _xom_event(), flag_pairs=((True, True),))
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": True, "benchmark": True})

    def test_forced_raw_resolves_matched_raw(self):
        with tempfile.TemporaryDirectory() as dtmp:
            with _DbRebind(self._db(dtmp)):
                out = esv.build_event_study_validation(
                    _xom_event(), flag_pairs=((False, False),))
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": False, "benchmark": False})

    def test_forced_basis_missing_is_insufficient_never_fallback(self):
        # only raw bars cached: forcing adjusted must NOT fall back to raw
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            rows, _ = _dividend_fixture_rows()
            raw_only = [r for r in rows if r[3] == 0]
            _make_price_db(p, raw_only)
            with _DbRebind(p):
                forced = esv.build_event_study_validation(
                    _xom_event(), flag_pairs=((True, True),))
                default = esv.build_event_study_validation(_xom_event())
        self.assertEqual(forced["status"], "insufficient_data")
        self.assertEqual(default["status"], "event_study_available")

    def test_default_none_is_identical_to_no_argument(self):
        with tempfile.TemporaryDirectory() as dtmp:
            with _DbRebind(self._db(dtmp)):
                a = esv.build_event_study_validation(_xom_event())
                b = esv.build_event_study_validation(_xom_event(), flag_pairs=None)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# 2. compare_bases
# ---------------------------------------------------------------------------


class CompareBasesTests(unittest.TestCase):
    def test_dividend_step_produces_horizon_dependent_delta_and_flag(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            rows, _ = _dividend_fixture_rows()
            _make_price_db(p, rows)
            with _DbRebind(p):
                cmp_ = bir.compare_bases(_xom_event())
        self.assertEqual(cmp_["raw"]["status"], "event_study_available")
        self.assertEqual(cmp_["adjusted"]["status"], "event_study_available")
        d = {row["horizon"]: row for row in cmp_["deltas"]}
        # 1d precedes the ratio step: bases agree; 5d/20d carry the ~2% step
        self.assertLess(abs(d[1]["adjusted_minus_raw_ar"]), 0.002)
        self.assertGreater(d[5]["adjusted_minus_raw_ar"], 0.015)
        self.assertGreater(d[20]["adjusted_minus_raw_ar"], 0.015)
        # delta arithmetic pinned to the two payloads
        self.assertAlmostEqual(
            d[5]["adjusted_minus_raw_ar"],
            _ar(cmp_["adjusted"], 5) - _ar(cmp_["raw"], 5), places=12)
        # cache evidence: the adjusted/raw ratio steps inside the 20d window
        self.assertTrue(cmp_["ratio_step_in_window"]["20d"])
        self.assertFalse(cmp_["ratio_step_in_window"]["1d"])

    def test_no_ratio_step_means_negligible_delta_no_flag(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            rows, _ = _dividend_fixture_rows()
            # make adjusted == raw everywhere (no action)
            flat = [(t, d, c, aa) if aa == 0 else (t, d, c, aa)
                    for (t, d, c, aa) in rows]
            flat = [(t, d, (c if aa == 0 else c), aa) for (t, d, c, aa) in flat]
            # rebuild adjusted as an exact copy of raw
            raw_close = {(t, d): c for (t, d, c, aa) in rows if aa == 0}
            flat = ([(t, d, c, 0) for (t, d, c, aa) in rows if aa == 0]
                    + [(t, d, raw_close[(t, d)], 1) for (t, d, c, aa) in rows if aa == 1])
            _make_price_db(p, flat)
            with _DbRebind(p):
                cmp_ = bir.compare_bases(_xom_event())
        d = {row["horizon"]: row for row in cmp_["deltas"]}
        for h in (1, 5, 20):
            self.assertLess(abs(d[h]["adjusted_minus_raw_ar"]), 1e-9)
            self.assertFalse(cmp_["ratio_step_in_window"][f"{h}d"])

    def test_unavailable_forced_basis_is_explicit(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            rows, _ = _dividend_fixture_rows()
            _make_price_db(p, [r for r in rows if r[3] == 0])  # raw only
            with _DbRebind(p):
                cmp_ = bir.compare_bases(_xom_event())
        self.assertEqual(cmp_["raw"]["status"], "event_study_available")
        self.assertEqual(cmp_["adjusted"]["status"], "insufficient_data")
        self.assertEqual(cmp_["deltas"], [])  # no fabricated comparison


# ---------------------------------------------------------------------------
# 3. Live report: reconciliation, distribution, policy comparison
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class LiveBasisReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = bir.build_report(db_path=str(LIVE_DB))

    def test_denominator_reconciliation_is_exact(self):
        rec = self.report["denominator_reconciliation"]
        self.assertEqual(rec["accepted_track_record"], 86)
        self.assertEqual(rec["cohort_size"], 70)
        self.assertEqual(rec["accepted_no_primary"], 13)
        self.assertEqual(rec["accepted_primary_blocked"], 3)
        self.assertEqual(rec["curated_available_excluded"], 8)
        self.assertEqual(rec["coverage_lens_available"], 78)
        self.assertEqual(rec["coverage_lens_denominator"], 94)
        # 78 = 70 accepted-available + 8 curated-available
        self.assertEqual(rec["coverage_lens_available"],
                         rec["cohort_size"] + rec["curated_available_excluded"])

    def test_current_basis_mixture_reproduced(self):
        # post-F3: the canonical default is adjusted-preferred with a single
        # disclosed matched-raw fallback (#50 GLD)
        pol = self.report["policy_comparison"]["current_default_policy"]
        self.assertEqual(pol["available"], 70)
        self.assertEqual(pol["basis_mixture"]["adjusted"], 69)
        self.assertEqual(pol["basis_mixture"]["raw"], 1)

    def test_single_raw_fallback_row_is_50_gld(self):
        raw_rows = [r for r in self.report["rows"]
                    if r["default_basis"] == {"asset": False, "benchmark": False}]
        self.assertEqual([r["event_id"] for r in raw_rows], [50])
        self.assertEqual(raw_rows[0]["primary_ticker"], "GLD")

    def test_every_cohort_row_compared_or_explicitly_incomparable(self):
        rows = self.report["rows"]
        self.assertEqual(len(rows), 70)
        for r in rows:
            self.assertIn(r["comparability"],
                          ("both_bases", "raw_only", "adjusted_only", "neither"))

    def test_distribution_buckets_cover_all_compared_rows(self):
        dist = self.report["delta_distribution"]
        both = sum(1 for r in self.report["rows"]
                   if r["comparability"] == "both_bases")
        for h in ("1d", "5d", "20d"):
            self.assertEqual(sum(dist[h]["buckets"].values()), both)

    def test_default_policy_mixture_is_adjusted_preferred(self):
        # post-F3 canonical default: 69 adjusted / 1 disclosed raw fallback
        self.assertEqual(
            self.report["policy_comparison"]["current_default_policy"][
                "basis_mixture"], {"adjusted": 69, "raw": 1})
        self.assertIn("does not restate", " ".join(self.report["non_claims"]).lower())


if __name__ == "__main__":
    unittest.main()

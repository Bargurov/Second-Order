"""Tests for the F1 sector-relative readout layer.

Covers, in order:

* the ``benchmark_ticker`` parameter on
  ``event_study_validation.build_event_study_validation`` — default stays SPY
  (canonical, untouched); a custom sector ETF benchmark computes the abnormal
  return against THAT ETF with the same gates;
* the pure sector-benchmark classification (eligible / asset-is-sector-benchmark
  / asset-is-broad-benchmark / no-sector-benchmark / no-primary) reusing the
  existing conservative suggestion mapping — never extended here;
* ``build_sector_relative_readout`` — explicit benchmark identity, mapping
  version, per-horizon raw / sector / sector-relative reads, and explicit
  unavailable states (never a fake fallback);
* the reaction-matrix consumer carrying an additive ``sector_relative`` block.

Fixture DBs only (db.DB_FILE rebound); live-archive assertions are skipped when
events.db is absent.  No provider call, no write to any live database.
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
from scripts import sector_relative_readout as srr  # noqa: E402

LIVE_DB = ROOT / "events.db"


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors tests/test_event_study_validation.py)
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


def _close(i: int, base: float, *, noise: bool = True, jump_from: int | None = None) -> float:
    val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
    if jump_from is not None and i >= jump_from:
        val *= 1.04
    return round(val, 4)


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


def _sector_move_rows() -> list[tuple]:
    """XOM and XLE jump together (+4%) after the event; SPY stays flat.

    So the SPY-relative abnormal return is strongly positive while the
    XLE-relative abnormal return is near zero — the exact distinction the
    sector layer exists to surface.
    """
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    jump = len(pre) + 1
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        rows.append(("SPY", d.isoformat(), _close(i, 100.0, noise=False), 0))
        rows.append(("XLE", d.isoformat(), _close(i, 50.0, noise=False, jump_from=jump), 0))
        rows.append(("XOM", d.isoformat(), _close(i, 80.0, jump_from=jump), 0))
    return rows


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


def _hz(payload: dict, h: int) -> dict:
    for row in payload.get("per_horizon") or []:
        if row.get("horizon") == h:
            return row
    return {}


# ---------------------------------------------------------------------------
# 1. benchmark_ticker parameter on the existing gate
# ---------------------------------------------------------------------------


class BenchmarkParamTests(unittest.TestCase):
    def test_default_benchmark_remains_spy(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _sector_move_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation(_xom_event())
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["benchmark"], "SPY")

    def test_custom_benchmark_computes_relative_to_it(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _sector_move_rows())
            with _DbRebind(p):
                vs_spy = esv.build_event_study_validation(_xom_event())
                vs_xle = esv.build_event_study_validation(
                    _xom_event(), benchmark_ticker="XLE")
        self.assertEqual(vs_xle["status"], "event_study_available")
        self.assertEqual(vs_xle["benchmark"], "XLE")
        ar_spy = _hz(vs_spy, 5)["abnormal_return"]
        ar_xle = _hz(vs_xle, 5)["abnormal_return"]
        # asset and sector jumped together, SPY flat: the sector-relative AR
        # must be much smaller than the SPY-relative AR
        self.assertGreater(ar_spy, 0.03)
        self.assertLess(abs(ar_xle), 0.01)

    def test_custom_benchmark_missing_cache_is_insufficient(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _sector_move_rows())  # no XLI rows at all
            with _DbRebind(p):
                out = esv.build_event_study_validation(
                    _xom_event(), benchmark_ticker="XLI")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertTrue(any("benchmark" in r for r in out["blocking_reasons"]))


# ---------------------------------------------------------------------------
# 2. Pure sector-benchmark classification
# ---------------------------------------------------------------------------


class ClassifyTests(unittest.TestCase):
    def test_mapped_single_name_is_eligible(self):
        c = srr.classify_sector_benchmark("XOM")
        self.assertEqual(c["state"], srr.STATE_ELIGIBLE)
        self.assertEqual(c["sector"], "energy")
        self.assertEqual(c["benchmark"], "XLE")

    def test_sector_etf_is_its_own_benchmark(self):
        c = srr.classify_sector_benchmark("XLE")
        self.assertEqual(c["state"], srr.STATE_SELF_BENCHMARK)
        self.assertIsNone(c["benchmark"])

    def test_spy_is_broad_benchmark(self):
        c = srr.classify_sector_benchmark("SPY")
        self.assertEqual(c["state"], srr.STATE_BROAD_BENCHMARK)
        self.assertIsNone(c["benchmark"])

    def test_unmapped_ticker_has_no_sector_benchmark(self):
        for t in ("DRIV", "BTU", "GLD", "BDRY"):
            c = srr.classify_sector_benchmark(t)
            self.assertEqual(c["state"], srr.STATE_UNMAPPED, t)
            self.assertIsNone(c["benchmark"], t)

    def test_missing_primary(self):
        c = srr.classify_sector_benchmark(None)
        self.assertEqual(c["state"], srr.STATE_NO_PRIMARY)

    def test_mapping_is_versioned(self):
        self.assertTrue(srr.MAPPING_VERSION)
        self.assertIn("v1", srr.MAPPING_VERSION)


# ---------------------------------------------------------------------------
# 3. build_sector_relative_readout
# ---------------------------------------------------------------------------


class BuildSectorRelativeTests(unittest.TestCase):
    def test_eligible_and_cached_returns_sector_relative(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _sector_move_rows())
            with _DbRebind(p):
                out = srr.build_sector_relative_readout(_xom_event())
        self.assertEqual(out["status"], srr.STATUS_AVAILABLE)
        self.assertEqual(out["sector_benchmark"], "XLE")
        self.assertEqual(out["sector"], "energy")
        self.assertEqual(out["mapping_version"], srr.MAPPING_VERSION)
        hz = {row["horizon"]: row for row in out["per_horizon"]}
        self.assertEqual(sorted(hz), [1, 5, 20])
        for h, row in hz.items():
            self.assertIn("raw_return", row)
            self.assertIn("sector_return", row)
            self.assertIn("sector_relative_return", row)
            # internal consistency: sector-relative == raw - sector (BHAR)
            self.assertAlmostEqual(
                row["sector_relative_return"],
                row["raw_return"] - row["sector_return"], places=9)

    def test_sector_window_missing_is_explicit_unavailable(self):
        # LMT maps to XLI but the fixture has no XLI bars: the state must be
        # explicit, with reasons, and carry NO fabricated numbers
        event = {"id": 2, "event_date": _EVENT_ISO,
                 "market_tickers": [{"symbol": "LMT"}]}
        rows = _sector_move_rows() + [
            ("LMT", d, c, aa) for (t, d, c, aa) in _sector_move_rows()
            if t == "XOM"]
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, rows)
            with _DbRebind(p):
                out = srr.build_sector_relative_readout(event)
        self.assertEqual(out["status"], srr.STATUS_WINDOW_UNAVAILABLE)
        self.assertEqual(out["sector_benchmark"], "XLI")
        self.assertTrue(out["blocking_reasons"])
        self.assertNotIn("per_horizon", out)

    def test_sector_etf_primary_is_labeled_not_computed(self):
        event = {"id": 3, "event_date": _EVENT_ISO,
                 "market_tickers": [{"symbol": "XLE"}]}
        out = srr.build_sector_relative_readout(event)
        self.assertEqual(out["status"], srr.STATUS_SELF_BENCHMARK)
        self.assertNotIn("per_horizon", out)

    def test_unmapped_primary_is_labeled_spy_only(self):
        event = {"id": 4, "event_date": _EVENT_ISO,
                 "market_tickers": [{"symbol": "DRIV"}]}
        out = srr.build_sector_relative_readout(event)
        self.assertEqual(out["status"], srr.STATUS_UNMAPPED)
        self.assertNotIn("per_horizon", out)

    def test_non_claims_present_and_banned_clean(self):
        event = {"id": 4, "event_date": _EVENT_ISO,
                 "market_tickers": [{"symbol": "DRIV"}]}
        out = srr.build_sector_relative_readout(event)
        text = " ".join(out["non_claims"]).lower()
        self.assertIn("descriptive", text)
        for banned in ("buy", "sell", "alpha", "forecast"):
            self.assertNotIn(banned, text)


# ---------------------------------------------------------------------------
# 4. Archive-wide coverage summary (live, read-only)
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class LiveCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cov = srr.summarize_sector_relative_coverage(db_path=str(LIVE_DB))

    def test_states_partition_the_accepted_rows(self):
        c = self.cov["counts"]
        total = (c["eligible"] + c["self_benchmark"] + c["unmapped"]
                 + c["no_primary"] + c["broad_benchmark"])
        self.assertEqual(total, self.cov["accepted_rows"])
        self.assertEqual(self.cov["accepted_rows"], 86)

    def test_eligible_rows_report_availability(self):
        for row in self.cov["eligible_rows"]:
            self.assertIn(row["status"],
                          (srr.STATUS_AVAILABLE, srr.STATUS_WINDOW_UNAVAILABLE))
            self.assertIn(row["sector_benchmark"],
                          ("XLE", "XLI", "XLY", "XLF"))

    def test_denominators_untouched(self):
        self.assertEqual(self.cov["accepted_rows"], 86)
        self.assertIn("does not change", " ".join(self.cov["non_claims"]).lower())

    def test_sector_vs_market_component_is_basis_clean_and_window_honest(self):
        # The comparative statistic is the SECTOR-vs-MARKET component (sector
        # ETF return minus SPY return), a property of the (sector, window)
        # pair — never presented as asset-specific.  Rows where the two lenses
        # resolved different asset bases/windows are excluded and counted, and
        # duplicate windows are disclosed.
        comp = self.cov["sector_vs_market_component"]
        self.assertIn("definition", comp)
        self.assertIn("sector", comp["definition"].lower())
        for h in ("1d", "5d", "20d"):
            self.assertIn(h, comp["per_horizon"])
            self.assertIn("median", comp["per_horizon"][h])
        self.assertGreaterEqual(comp["rows_excluded_basis_mismatch"], 0)
        self.assertGreater(comp["unique_windows"], 0)
        self.assertLessEqual(comp["unique_windows"], comp["rows_included"]
                             + comp["rows_excluded_basis_mismatch"])
        # every available eligible row carries the cross-lens flag
        for row in self.cov["eligible_rows"]:
            if row["status"] == srr.STATUS_AVAILABLE:
                self.assertIn("cross_lens_basis_mismatch", row)
        # included deltas come only from basis-matched rows: for those rows the
        # two lenses' raw returns agree, so delta == sector_ret - spy_ret
        for row in self.cov["eligible_rows"]:
            if (row["status"] == srr.STATUS_AVAILABLE
                    and not row["cross_lens_basis_mismatch"]):
                for p in row["per_horizon"]:
                    if (p["raw_return"] is not None
                            and p.get("spy_raw_return") is not None):
                        self.assertAlmostEqual(
                            p["raw_return"], p["spy_raw_return"], places=9)


# ---------------------------------------------------------------------------
# 5. Reaction-matrix consumer (additive block)
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class LiveReactionMatrixConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.case_library_reaction_matrix import build_report
        cls.report = build_report(db_path=str(LIVE_DB))

    def test_every_case_row_carries_sector_relative_block(self):
        for row in self.report["matrix"]:
            self.assertIn("sector_relative", row)
            self.assertIn(row["sector_relative"]["status"], srr.ALL_STATUSES)

    def test_xle_cases_labeled_self_benchmark(self):
        by_id = {r["event_id"]: r for r in self.report["matrix"]}
        for eid in (7, 29, 38, 66):
            self.assertEqual(by_id[eid]["sector_relative"]["status"],
                             srr.STATUS_SELF_BENCHMARK, eid)

    def test_xom_case_210_has_sector_read_or_explicit_unavailable(self):
        by_id = {r["event_id"]: r for r in self.report["matrix"]}
        block = by_id[210]["sector_relative"]
        self.assertEqual(block["sector_benchmark"], "XLE")
        self.assertIn(block["status"],
                      (srr.STATUS_AVAILABLE, srr.STATUS_WINDOW_UNAVAILABLE))

    def test_unmapped_cases_labeled(self):
        by_id = {r["event_id"]: r for r in self.report["matrix"]}
        for eid in (46, 61, 211, 212):
            self.assertEqual(by_id[eid]["sector_relative"]["status"],
                             srr.STATUS_UNMAPPED, eid)

    def test_text_render_mentions_sector_relative(self):
        from scripts.case_library_reaction_matrix import render_text
        text = render_text(self.report)
        self.assertIn("sector", text.lower())


if __name__ == "__main__":
    unittest.main()

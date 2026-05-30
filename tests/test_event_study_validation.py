"""Tests for ``event_study_validation.build_event_study_validation``.

Covers the gated single-event proof:

* a ready event returns ``event_study_available`` with per-horizon
  SAR/CAR and CI explicitly unavailable at n=1;
* non-ready events return ``insufficient_data`` with specific reasons
  (no ticker, missing forward cache);
* an event that passes the date-union gates but whose intersected window
  has an interior gap is caught by the contiguity guard (the silent-wrong
  -SAR landmine);
* the module performs no provider/network call and reads no Phase 1/2
  FDR-pool artifacts.

All reads go through ``db.DB_FILE`` (rebound to a temp price-cache DB);
no live archive is touched.
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


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bdays_before(anchor: date, count: int) -> list[date]:
    """``count`` business days strictly before ``anchor`` (ascending)."""
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
    # The ticker carries an alternating idiosyncratic term the (smooth)
    # benchmark does not, so the daily abnormal-return series has a
    # non-zero variance → positive sigma in the estimation window.  The
    # optional post-event jump creates a clear abnormal return.
    val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
    if jump_from is not None and i >= jump_from:
        val *= 1.04
    return round(val, 4)


def _make_price_db(path: str, rows: list[tuple]) -> None:
    """rows: (ticker, iso_date, close, auto_adjust_int)."""
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


def _ready_rows() -> list[tuple]:
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    event_index = len(pre)
    # Jump starts the day AFTER the event so the event-date anchor close is
    # pre-jump; the abnormal return then shows up in the forward window.
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        rows.append(("SPY", d.isoformat(), _close(i, 100.0, noise=False), 0))
        rows.append(("XLE", d.isoformat(), _close(i, 50.0, jump_from=event_index + 1), 0))
    return rows


class _DbRebind:
    """Point db.DB_FILE at a temp DB for the duration of a test."""

    def __init__(self, path: str):
        self.path = path
        self._saved = None

    def __enter__(self):
        self._saved = _db.DB_FILE
        _db.DB_FILE = self.path
        return self

    def __exit__(self, *exc):
        _db.DB_FILE = self._saved


class ReadyEventTest(unittest.TestCase):
    def test_ready_event_returns_event_study_payload(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _ready_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 1, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["primary_ticker"], "XLE")
        self.assertEqual(out["benchmark"], "SPY")
        self.assertEqual(out["auto_adjust_basis"], {"asset": False, "benchmark": False})
        self.assertNotIn("basis_caveat", out)  # matched flags → no bias caveat
        self.assertGreater(out["sigma_ar_daily"], 0.0)
        horizons = {row["horizon"]: row for row in out["per_horizon"]}
        self.assertEqual(set(horizons), {1, 5, 20})
        for h in (1, 5, 20):
            self.assertIsNotNone(horizons[h]["sar"], f"sar None at h={h}")
            self.assertIsNotNone(horizons[h]["abnormal_return"])
            self.assertIsNotNone(horizons[h]["car"])
        # Post-event +4% jump → positive abnormal return at h=20.
        self.assertGreater(horizons[20]["abnormal_return"], 0.0)

    def test_ready_event_marks_ci_unavailable_at_n1_and_makes_no_significance_claim(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _ready_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 1, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        ci = out["cross_sectional_inference"]
        self.assertFalse(ci["available"])
        self.assertEqual(ci["n_events"], 1)
        self.assertEqual(ci["min_samples"], esv.MIN_COHORT_SAMPLES)
        # Never claims significance / validated for a single event.
        self.assertNotIn("statistically_significant", out)
        self.assertIn("confirmed", out["claims"]["not_claimed"])
        self.assertIn("validated", out["claims"]["not_claimed"])
        self.assertIn("confidence_interval", out["claims"]["not_claimed"])


class NonReadyEventTest(unittest.TestCase):
    def test_no_ticker_is_insufficient(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, [])
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 2, "event_date": _EVENT_ISO, "market_tickers": [],
                })
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("no_primary_ticker", out["blocking_reasons"])

    def test_missing_forward_cache_is_insufficient(self):
        # Primary ticker has a full pre-event window but no forward rows.
        pre = _bdays_before(_EVENT_D, 65)
        rows: list[tuple] = []
        for i, d in enumerate(pre + [_EVENT_D]):
            rows.append(("XLE", d.isoformat(), _close(i, 50.0), 0))
        # SPY fully covered (so the only gap is the primary's forward cache).
        for i, d in enumerate(pre + [_EVENT_D] + _bdays_after(_EVENT_D, 25)):
            rows.append(("SPY", d.isoformat(), _close(i, 100.0), 0))
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, rows)
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 3, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("missing_forward_cache_20d", out["blocking_reasons"])


class CrossFlagTest(unittest.TestCase):
    def test_cross_flag_each_series_single_flag_computes(self):
        # Asset cached ONLY adjusted (flag=1); benchmark ONLY raw (flag=0).
        # Each series is internally single-flag and complete, but they sit
        # on different flags — the matched-flag pairs find nothing and the
        # cross pair (adj asset / raw bench) must compute, with a caveat.
        cross: list[tuple] = []
        for (t, d, c, _aa) in _ready_rows():
            cross.append((t, d, c, 1 if t == "XLE" else 0))
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, cross)
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 5, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": True, "benchmark": False})
        self.assertIn("basis_caveat", out)
        self.assertGreater(out["sigma_ar_daily"], 0.0)


class ContiguityGuardTest(unittest.TestCase):
    def test_interior_gap_passes_date_gates_but_is_caught_by_contiguity(self):
        # SPY: fully contiguous 70 pre + event + 25 post.
        spy_dates = _bdays_before(_EVENT_D, 70) + [_EVENT_D] + _bdays_after(_EVENT_D, 25)
        # XLE pre-event: drop a 10-business-day run from the middle of the
        # 70, leaving 60 pre-event dates (>= ESTIMATION_WINDOW) but with a
        # ~2-week hole inside the closest-60 window the engine consumes.
        xle_pre_full = _bdays_before(_EVENT_D, 70)
        xle_pre = xle_pre_full[:25] + xle_pre_full[35:]  # remove indices 25..34
        self.assertGreaterEqual(len(xle_pre), esv.ESTIMATION_WINDOW)
        xle_dates = xle_pre + [_EVENT_D] + _bdays_after(_EVENT_D, 25)

        rows: list[tuple] = []
        for i, d in enumerate(spy_dates):
            rows.append(("SPY", d.isoformat(), _close(i, 100.0), 0))
        for i, d in enumerate(xle_dates):
            rows.append(("XLE", d.isoformat(), _close(i, 50.0), 0))

        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, rows)
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 4, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        # Date-union gates pass (>=60 pre, forward present), so the only
        # thing that can stop a wrong SAR is the contiguity guard.
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("no_contiguous_aligned_window", out["blocking_reasons"])


class IsolationTest(unittest.TestCase):
    def test_module_imports_no_provider_or_fdr_pool(self):
        import ast
        src = (ROOT / "event_study_validation.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        # Actual imports — not docstring prose — must carry no provider /
        # network seam and no Phase 1/2 FDR-pool module.
        for forbidden in (
            "yfinance", "market_data", "market_check", "cohort_evidence",
        ):
            self.assertNotIn(forbidden, imported, f"unexpected import: {forbidden}")

    def test_does_not_reimplement_sar(self):
        # SAR/CAR must come from the existing engine, not a local formula.
        src = (ROOT / "event_study_validation.py").read_text(encoding="utf-8")
        self.assertIn("from stats.event_study import compute_event_study", src)


if __name__ == "__main__":
    unittest.main()

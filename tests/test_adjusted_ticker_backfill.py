"""Tests for ``scripts/adjusted_ticker_backfill.py``.

Fixture: a calendar of 140 business days with adjusted SPY covering the
first 120.  Two archive-ready-but-compute-insufficient events:

* E1 (id 1, XLE, index 80) — adjusted-XLE window has an interior hole, so
  it is currently insufficient, but adjusted SPY is viable around it →
  RECOVERABLE.  A full XLE backfill must flip it to matched.
* E2 (id 2, VLO, index 110) — adjusted SPY's own forward is <20 there →
  FRONTIER, must be excluded from the recoverable set.

All writes run against throwaway temp DBs; the provider fetch is patched.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
from scripts import adjusted_ticker_backfill as atb  # noqa: E402
import event_study_validation as esv  # noqa: E402


def _bdays(start, n):
    out = []
    cur = start
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


CAL = _bdays(date(2026, 1, 5), 140)
E1_IDX, E2_IDX = 80, 110
HOLE = set(range(40, 51))  # interior hole in adjusted XLE (within estimation)


def _seed(conn, ticker, idxs, *, base, noise, aa):
    for j, i in enumerate(sorted(idxs)):
        val = base * (1 + 0.0005 * j + (0.003 * ((-1) ** j) if noise else 0.0))
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?,?,?,?,?,?)",
            (ticker, CAL[i].isoformat(), round(val, 4), 1000.0, aa, "seed"),
        )


def _make_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
            "event_date TEXT, market_tickers TEXT)"
        )
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))"
        )
        conn.execute("INSERT INTO events VALUES (1,'h',?,?)",
                     (CAL[E1_IDX].isoformat(), json.dumps([{"symbol": "XLE"}])))
        conn.execute("INSERT INTO events VALUES (2,'h',?,?)",
                     (CAL[E2_IDX].isoformat(), json.dumps([{"symbol": "VLO"}])))
        # Adjusted SPY covers indices 0..119 (forward gap for late events).
        _seed(conn, "SPY", range(0, 120), base=100.0, noise=False, aa=1)
        # Raw SPY: 0..119 plus an isolated +20bd proxy point for E2 (idx 130).
        _seed(conn, "SPY", list(range(0, 120)) + [130], base=100.0, noise=False, aa=0)
        # E1 XLE adjusted: 5..119 with an interior hole -> insufficient now.
        _seed(conn, "XLE", [i for i in range(5, 120) if i not in HOLE],
              base=50.0, noise=True, aa=1)
        _seed(conn, "XLE", range(81, 120), base=50.0, noise=True, aa=0)  # forward-only raw
        # E2 VLO: adjusted 50..119; raw 50..119 + isolated 130 (forward_cache).
        _seed(conn, "VLO", range(50, 120), base=60.0, noise=True, aa=1)
        _seed(conn, "VLO", list(range(50, 120)) + [130], base=60.0, noise=True, aa=0)
        conn.commit()
    finally:
        conn.close()


def _fake_fetch(*, symbol, start, end):
    cur = date.fromisoformat(start); e = date.fromisoformat(end); i = 0; rows = []
    while cur <= e:
        if cur.weekday() < 5:
            rows.append({"date": cur.isoformat(),
                         "close": round(50 * (1 + 0.0005 * i + 0.003 * ((-1) ** i)), 4),
                         "volume": 1000.0})
            i += 1
        cur += timedelta(days=1)
    return rows


def _cache_keys(path):
    conn = sqlite3.connect(path)
    try:
        return set(conn.execute(
            "SELECT ticker, date, auto_adjust FROM price_cache").fetchall())
    finally:
        conn.close()


def _events_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT * FROM events").fetchall()
    finally:
        conn.close()


class _Rebind:
    def __init__(self, path): self.path = path
    def __enter__(self):
        self._saved = _db.DB_FILE; _db.DB_FILE = self.path; return self
    def __exit__(self, *a):
        _db.DB_FILE = self._saved


class PlanTest(unittest.TestCase):
    def test_targets_recoverable_and_excludes_frontier(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            plan = atb.plan_adjusted_ticker_backfill(db_path=p)
        self.assertEqual(plan["target_event_ids"], [1])         # E1 recoverable
        self.assertEqual(plan["excluded_frontier_event_ids"], [2])  # E2 frontier
        self.assertIn("XLE", plan["tickers"])
        self.assertNotIn("VLO", plan["tickers"])
        self.assertNotIn("SPY", plan["tickers"])
        # Predicts the matched/compute-ready bump for the target only.
        self.assertEqual(plan["expected_compute_ready_after"]
                         - plan["expected_compute_ready_before"], 1)
        self.assertEqual(plan["expected_matched_after"]
                         - plan["expected_matched_before"], 1)


class DryRunSafetyTest(unittest.TestCase):
    def test_dry_run_no_provider_no_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            with mock.patch.object(atb, "_fetch_ticker_adjusted",
                                   side_effect=AssertionError("provider in dry-run")):
                rc = atb.main(["--dry-run", "--db-path", p, "--json"], out=io.StringIO())
                env = atb.apply_adjusted_ticker_backfill(db_path=p, confirm=False)
            self.assertEqual(rc, 0)
            self.assertFalse(env["write_attempted"])
            self.assertEqual(_cache_keys(p), before)


class WriteGuardTest(unittest.TestCase):
    def test_write_alone_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            self.assertEqual(atb.main(["--write", "--db-path", p], out=io.StringIO()), 2)
            self.assertEqual(_cache_keys(p), before)

    def test_write_confirm_without_backup_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            self.assertEqual(
                atb.main(["--write", "--confirm", "--db-path", p], out=io.StringIO()), 2)
            self.assertEqual(_cache_keys(p), before)

    def test_apply_confirm_without_backup_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            with self.assertRaises(ValueError):
                atb.apply_adjusted_ticker_backfill(db_path=p, confirm=True)

    def test_refuses_backup_equals_db(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            with mock.patch.object(atb, "_fetch_ticker_adjusted",
                                   side_effect=AssertionError("must not fetch")):
                env = atb.apply_adjusted_ticker_backfill(db_path=p, confirm=True, backup_path=p)
            self.assertFalse(env["write_attempted"])
            self.assertIn("must differ", env["refuse_reason"] or "")
            self.assertEqual(_cache_keys(p), before)


class WriteScopeTest(unittest.TestCase):
    def test_write_only_target_ticker_aa1_no_spy_no_aa0_no_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            ev_before = _events_rows(p)
            with mock.patch.object(atb, "_fetch_ticker_adjusted", side_effect=_fake_fetch):
                env = atb.apply_adjusted_ticker_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b.db"),
                    audit_log_path=os.path.join(d, "a.jsonl"))
            self.assertTrue(env["write_attempted"])
            self.assertGreater(env["applied_count"], 0)
            added = _cache_keys(p) - before
            self.assertTrue(added)
            for ticker, _date, aa in added:
                self.assertEqual(ticker, "XLE")   # only the target ticker
                self.assertEqual(aa, 1)           # only adjusted
                self.assertNotEqual(ticker, "SPY")
            self.assertEqual(ev_before, _events_rows(p))  # events untouched

    def test_replace_overwrites_existing_aa1_rows(self):
        # The live path REPLACEs already-cached aa=1 rows (XLE is ~98/100
        # cached).  Prove the overwrite fires, not just gap-fill.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            sentinel_date = CAL[60].isoformat()  # an existing XLE aa=1 date in-window
            conn = sqlite3.connect(p)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES ('XLE', ?, 1.0, 1000.0, 1, 'sentinel')", (sentinel_date,))
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(atb, "_fetch_ticker_adjusted", side_effect=_fake_fetch):
                atb.apply_adjusted_ticker_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b.db"),
                    audit_log_path=os.path.join(d, "a.jsonl"))
            conn = sqlite3.connect(p)
            try:
                v = conn.execute(
                    "SELECT close FROM price_cache WHERE ticker='XLE' AND "
                    "auto_adjust=1 AND date=?", (sentinel_date,)).fetchone()[0]
            finally:
                conn.close()
            self.assertGreater(v, 1.0)  # sentinel overwritten by fetched value

    def test_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            with mock.patch.object(atb, "_fetch_ticker_adjusted", side_effect=_fake_fetch):
                atb.apply_adjusted_ticker_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b1.db"),
                    audit_log_path=os.path.join(d, "a1.jsonl"))
                k1 = _cache_keys(p)
                atb.apply_adjusted_ticker_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b2.db"),
                    audit_log_path=os.path.join(d, "a2.jsonl"))
                k2 = _cache_keys(p)
        self.assertEqual(k1, k2)


class ConvertsToMatchedTest(unittest.TestCase):
    def test_backfill_converts_blocked_event_to_matched(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            event = {"id": 1, "event_date": CAL[E1_IDX].isoformat(),
                     "market_tickers": [{"symbol": "XLE"}]}
            with _Rebind(p):
                before = esv.build_event_study_validation(event)
            self.assertEqual(before["status"], "insufficient_data")  # holey adj-XLE
            with mock.patch.object(atb, "_fetch_ticker_adjusted", side_effect=_fake_fetch):
                env = atb.apply_adjusted_ticker_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b.db"),
                    audit_log_path=os.path.join(d, "a.jsonl"))
            self.assertGreater(env["applied_count"], 0)
            with _Rebind(p):
                after = esv.build_event_study_validation(event)
            self.assertEqual(after["status"], "event_study_available")
            self.assertEqual(after["auto_adjust_basis"], {"asset": True, "benchmark": True})
            self.assertNotIn("basis_caveat", after)


class IsolationTest(unittest.TestCase):
    def test_no_raw_to_adjusted_copy_path(self):
        src = (ROOT / "scripts" / "adjusted_ticker_backfill.py").read_text(encoding="utf-8")
        # Writer must fetch from the provider, never copy raw rows into aa=1.
        self.assertNotIn("auto_adjust = 0", src)
        self.assertNotIn("SELECT close FROM price_cache", src)  # no raw-row copy read
        self.assertIn("auto_adjust=True", src)  # true adjusted fetch


if __name__ == "__main__":
    unittest.main()

"""Tests for ``scripts/spy_adjusted_benchmark_backfill.py``.

Covers the guarded contract and the research goal:

* dry-run reaches no provider and mutates nothing;
* the plan derives the union window from cross-flag compute-ready events;
* the writer refuses without --write / --confirm / --backup-path;
* the write is row-scoped — only ``(SPY, aa=1)`` rows, never another
  ticker, never aa=0, never the events table — and idempotent;
* applying the backfill **converts a cross-flag event to matched basis**
  (the whole point of the tool).

All writes run against throwaway temp DBs; no live archive is touched and
the provider fetch is always patched.
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
from scripts import spy_adjusted_benchmark_backfill as bf  # noqa: E402
import event_study_validation as esv  # noqa: E402


_EVENT_D = date(2026, 4, 15)


def _bdays(event_d, n_pre, n_post):
    pre = []
    cur = event_d
    while len(pre) < n_pre:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            pre.append(cur)
    pre.reverse()
    post = []
    cur = event_d
    while len(post) < n_post:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            post.append(cur)
    return pre + [event_d] + post


def _seed(conn, ticker, dates, *, base, noise, aa, jump_from=None):
    for i, d in enumerate(dates):
        val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
        if jump_from is not None and i >= jump_from:
            val *= 1.04
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?,?,?,?,?,?)",
            (ticker, d.isoformat(), round(val, 4), 1000.0, aa, "2026-01-01T00:00:00"),
        )


def _make_db(path):
    """A cross-flag-ready archive: XLE adjusted (aa=1), SPY raw (aa=0)."""
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
        conn.execute(
            "INSERT INTO events (id, headline, event_date, market_tickers) "
            "VALUES (1, 'h', ?, ?)",
            (_EVENT_D.isoformat(), json.dumps([{"symbol": "XLE"}])),
        )
        dates = _bdays(_EVENT_D, 65, 22)
        ev_idx = 65
        _seed(conn, "XLE", dates, base=50.0, noise=True, aa=1, jump_from=ev_idx + 1)
        _seed(conn, "SPY", dates, base=100.0, noise=False, aa=0)  # raw only
        conn.commit()
    finally:
        conn.close()


def _cache_keys(path):
    conn = sqlite3.connect(path)
    try:
        return set(conn.execute(
            "SELECT ticker, date, auto_adjust FROM price_cache"
        ).fetchall())
    finally:
        conn.close()


def _events_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT * FROM events").fetchall()
    finally:
        conn.close()


def _spy_aa1_close(path, date_iso):
    conn = sqlite3.connect(path)
    try:
        r = conn.execute(
            "SELECT close FROM price_cache "
            "WHERE ticker='SPY' AND auto_adjust=1 AND date=?", (date_iso,),
        ).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def _fake_fetch(*, start, end):
    s = date.fromisoformat(start); e = date.fromisoformat(end)
    rows = []; cur = s; i = 0
    while cur <= e:
        if cur.weekday() < 5:
            rows.append({"date": cur.isoformat(),
                         "close": round(100 * (1 + 0.0004 * i), 4),
                         "volume": 1000.0})
            i += 1
        cur += timedelta(days=1)
    return rows


class _Rebind:
    def __init__(self, path): self.path = path
    def __enter__(self):
        self._saved = _db.DB_FILE; _db.DB_FILE = self.path; return self
    def __exit__(self, *a):
        _db.DB_FILE = self._saved


class PlanTest(unittest.TestCase):
    def test_plan_derives_window_from_cross_flag_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            plan = bf.plan_spy_adjusted_backfill(db_path=p)
        self.assertEqual(plan["target_event_ids"], [1])
        self.assertEqual(plan["benchmark_symbol"], "SPY")
        self.assertEqual(plan["auto_adjust"], 1)
        # window = [event-60bd, event+20bd]
        self.assertEqual(plan["window_start"], bf._business_day_offset(_EVENT_D, -60).isoformat())
        self.assertEqual(plan["window_end"], bf._business_day_offset(_EVENT_D, 20).isoformat())
        # SPY has no aa=1 rows yet -> fetch estimate equals the weekday span.
        self.assertEqual(plan["spy_aa1_cached_in_window"], 0)
        self.assertGreater(plan["estimated_fetch_rows"], 0)


class DryRunSafetyTest(unittest.TestCase):
    def test_dry_run_reaches_no_provider_and_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            before = _cache_keys(p)
            with mock.patch.object(bf, "_fetch_spy_adjusted",
                                   side_effect=AssertionError("provider called in dry-run")):
                rc = bf.main(["--dry-run", "--db-path", p, "--json"], out=io.StringIO())
                env = bf.apply_spy_adjusted_backfill(db_path=p, confirm=False)
            self.assertEqual(rc, 0)
            self.assertFalse(env["write_attempted"])
            self.assertEqual(env["fetched_rows"], 0)
            self.assertEqual(_cache_keys(p), before)


class WriteGuardTest(unittest.TestCase):
    def test_write_alone_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            rc = bf.main(["--write", "--db-path", p], out=io.StringIO())
            self.assertEqual(rc, 2)
            self.assertEqual(_cache_keys(p), before)

    def test_write_confirm_without_backup_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            rc = bf.main(["--write", "--confirm", "--db-path", p], out=io.StringIO())
            self.assertEqual(rc, 2)
            self.assertEqual(_cache_keys(p), before)

    def test_apply_confirm_without_backup_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            with self.assertRaises(ValueError):
                bf.apply_spy_adjusted_backfill(db_path=p, confirm=True)

    def test_write_refuses_when_backup_equals_db(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            before = _cache_keys(p)
            with mock.patch.object(bf, "_fetch_spy_adjusted",
                                   side_effect=AssertionError("must not fetch on refuse")):
                env = bf.apply_spy_adjusted_backfill(db_path=p, confirm=True, backup_path=p)
            self.assertFalse(env["write_attempted"])
            self.assertIn("must differ", env["refuse_reason"] or "")
            self.assertEqual(_cache_keys(p), before)


class WriteScopeTest(unittest.TestCase):
    def test_write_only_touches_spy_aa1_rows_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            backup = os.path.join(d, "backup.db")
            before = _cache_keys(p)
            ev_before = _events_rows(p)
            with mock.patch.object(bf, "_fetch_spy_adjusted", side_effect=_fake_fetch):
                env = bf.apply_spy_adjusted_backfill(
                    db_path=p, confirm=True, backup_path=backup,
                    audit_log_path=os.path.join(d, "audit.jsonl"),
                )
            self.assertTrue(env["write_attempted"])
            self.assertGreater(env["applied_count"], 0)
            self.assertTrue(os.path.exists(backup))
            after = _cache_keys(p)
            added = after - before
            # Every added row is exactly (SPY, *, aa=1).
            self.assertTrue(added)
            for ticker, _date, aa in added:
                self.assertEqual(ticker, "SPY")
                self.assertEqual(aa, 1)
            # No pre-existing row removed/changed key; events untouched.
            self.assertTrue(before.issubset(after))
            ev_after = _events_rows(p)
            self.assertEqual(ev_before, ev_after)

    def test_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            with mock.patch.object(bf, "_fetch_spy_adjusted", side_effect=_fake_fetch):
                bf.apply_spy_adjusted_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b1.db"),
                    audit_log_path=os.path.join(d, "a1.jsonl"))
                keys1 = _cache_keys(p)
                bf.apply_spy_adjusted_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b2.db"),
                    audit_log_path=os.path.join(d, "a2.jsonl"))
                keys2 = _cache_keys(p)
        self.assertEqual(keys1, keys2)


class ConvertsToMatchedTest(unittest.TestCase):
    def test_backfill_converts_cross_flag_event_to_matched(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            event = {"id": 1, "event_date": _EVENT_D.isoformat(),
                     "market_tickers": [{"symbol": "XLE"}]}
            # Before: cross-flag (adjusted XLE / raw SPY).
            with _Rebind(p):
                before = esv.build_event_study_validation(event)
            self.assertEqual(before["status"], "event_study_available")
            self.assertNotEqual(before["auto_adjust_basis"]["asset"],
                                before["auto_adjust_basis"]["benchmark"])
            self.assertIn("basis_caveat", before)
            # Apply the SPY-adjusted backfill.
            with mock.patch.object(bf, "_fetch_spy_adjusted", side_effect=_fake_fetch):
                env = bf.apply_spy_adjusted_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b.db"),
                    audit_log_path=os.path.join(d, "a.jsonl"))
            self.assertTrue(env["applied_count"] > 0)
            # After: matched (adjusted / adjusted), caveat gone.
            with _Rebind(p):
                after = esv.build_event_study_validation(event)
            self.assertEqual(after["status"], "event_study_available")
            self.assertEqual(after["auto_adjust_basis"], {"asset": True, "benchmark": True})
            self.assertNotIn("basis_caveat", after)

    def test_partial_spy_aa1_is_replaced_and_converts_to_matched(self):
        # The LIVE path: SPY aa=1 is partially populated with an interior
        # gap (sentinel closes), so (adj,adj) is currently non-viable and
        # the event is cross-flag.  The fetch returns DIFFERENT values for
        # the whole window; INSERT OR REPLACE must overwrite the sentinels
        # AND fill the gap, flipping the event to matched.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db"); _make_db(p)
            dates = _bdays(_EVENT_D, 65, 22)
            conn = sqlite3.connect(p)
            try:
                for i, dt in enumerate(dates):
                    if 30 <= i <= 45:           # interior gap → non-contiguous
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO price_cache "
                        "(ticker, date, close, volume, auto_adjust, fetched_at) "
                        "VALUES ('SPY', ?, 1.0, 1000.0, 1, 'sentinel')",
                        (dt.isoformat(),),
                    )
                conn.commit()
            finally:
                conn.close()
            event = {"id": 1, "event_date": _EVENT_D.isoformat(),
                     "market_tickers": [{"symbol": "XLE"}]}
            sentinel_date = dates[10].isoformat()
            self.assertEqual(_spy_aa1_close(p, sentinel_date), 1.0)
            with _Rebind(p):
                before = esv.build_event_study_validation(event)
            self.assertNotEqual(before["auto_adjust_basis"]["asset"],
                                before["auto_adjust_basis"]["benchmark"])  # cross-flag

            with mock.patch.object(bf, "_fetch_spy_adjusted", side_effect=_fake_fetch):
                env = bf.apply_spy_adjusted_backfill(
                    db_path=p, confirm=True, backup_path=os.path.join(d, "b.db"),
                    audit_log_path=os.path.join(d, "a.jsonl"))
            self.assertGreater(env["applied_count"], 0)
            # REPLACE fired: the sentinel date now holds a fetched value.
            self.assertGreater(_spy_aa1_close(p, sentinel_date), 1.0)
            with _Rebind(p):
                after = esv.build_event_study_validation(event)
            self.assertEqual(after["auto_adjust_basis"], {"asset": True, "benchmark": True})
            self.assertNotIn("basis_caveat", after)


if __name__ == "__main__":
    unittest.main()

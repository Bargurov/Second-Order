"""T3B — SPY benchmark basis-integrity regressions for the guarded backfill.

The canonical basis policy (F3, ``event_study_validation``) resolves the
default readout on ONE matched basis: adjusted/adjusted preferred, raw/raw
as the only disclosed fallback, never a cross-basis pair.  These tests pin
the post-F3 contract of ``scripts/spy_adjusted_benchmark_backfill.py``:

  * the planner targets events BLOCKED from (or falling back away from)
    the preferred matched-adjusted basis whose asset side is
    adjusted-viable — coverage counted per basis, never across bases;
  * replacement rewrites the full declared (SPY, aa=1, window) slice
    atomically: stale partial rows cannot survive beside fresh rows and
    splice into a complete-looking series;
  * rows are validated before write (ISO date inside the window, finite
    positive close): malformed provider data can never destroy real rows;
  * a matched result always has asset_auto_adjust == benchmark_auto_adjust;
  * incomplete replacement stays explicitly non-matched with the missing
    dates visible; coverage is recomputed after the committed write
    through the public plan/validation paths;
  * replacement is idempotent and never touches unrelated tickers, the
    opposite SPY basis, out-of-window rows, or the events table.

All scenarios run on throwaway temp DBs with the provider seam patched;
a DNS guard proves no network resolution is even attempted.
"""
from __future__ import annotations

import json
import math
import os
import socket
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
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402
from scripts import spy_adjusted_benchmark_backfill as bf  # noqa: E402

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


_DATES = _bdays(_EVENT_D, 65, 22)
_EVENT = {"id": 1, "event_date": _EVENT_D.isoformat(),
          "market_tickers": [{"symbol": "XLE"}]}


def _seed(conn, ticker, dates, *, base, noise, aa):
    for i, d in enumerate(dates):
        val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?,?,?,?,?,?)",
            (ticker, d.isoformat(), round(val, 4), 1000.0, aa,
             "2026-01-01T00:00:00"),
        )


def _make_db(path, *, partial_spy_aa1=False, extra_ticker=None):
    """Cross-basis archive: XLE adjusted complete, SPY raw complete.

    ``partial_spy_aa1`` adds sentinel (close=1.0) SPY aa=1 rows with an
    interior gap (indices 30..45 missing) — the live partial-cache shape.
    ``extra_ticker`` seeds one unrelated ticker on both bases.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
            "event_date TEXT, market_tickers TEXT)")
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))")
        conn.execute(
            "INSERT INTO events (id, headline, event_date, market_tickers) "
            "VALUES (1, 'h', ?, ?)",
            (_EVENT_D.isoformat(), json.dumps([{"symbol": "XLE"}])))
        _seed(conn, "XLE", _DATES, base=50.0, noise=True, aa=1)
        _seed(conn, "SPY", _DATES, base=100.0, noise=False, aa=0)
        if extra_ticker:
            _seed(conn, extra_ticker, _DATES, base=80.0, noise=True, aa=0)
            _seed(conn, extra_ticker, _DATES, base=80.0, noise=True, aa=1)
        if partial_spy_aa1:
            for i, dt in enumerate(_DATES):
                if 30 <= i <= 45:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES ('SPY', ?, 1.0, 1000.0, 1, 'sentinel')",
                    (dt.isoformat(),))
        conn.commit()
    finally:
        conn.close()


def _fake_fetch(*, start, end):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    rows = []
    cur = s
    i = 0
    while cur <= e:
        if cur.weekday() < 5:
            rows.append({"date": cur.isoformat(),
                         "close": round(100 * (1 + 0.0004 * i), 4),
                         "volume": 1000.0})
            i += 1
        cur += timedelta(days=1)
    return rows


def _fetch_omitting(omit_dates):
    omitted = {d.isoformat() if isinstance(d, date) else d for d in omit_dates}

    def _fetch(*, start, end):
        return [r for r in _fake_fetch(start=start, end=end)
                if r["date"] not in omitted]
    return _fetch


def _table(path, where="1=1", params=()):
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute(
            "SELECT ticker, date, auto_adjust, close, volume "
            f"FROM price_cache WHERE {where}", params).fetchall())
    finally:
        conn.close()


def _spy_aa1_dates(path):
    return {r[1] for r in _table(path, "ticker='SPY' AND auto_adjust=1")}


class _Rebind:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self._saved = _db.DB_FILE
        _db.DB_FILE = self.path
        return self

    def __exit__(self, *a):
        _db.DB_FILE = self._saved


def _validate(path, event=_EVENT):
    with _Rebind(path):
        return esv.build_event_study_validation(event)


def _apply(path, fetch, tmpdir, tag="a"):
    with mock.patch.object(bf, "_fetch_spy_adjusted", side_effect=fetch):
        return bf.apply_spy_adjusted_backfill(
            db_path=path, confirm=True,
            backup_path=os.path.join(tmpdir, f"backup_{tag}.db"),
            audit_log_path=os.path.join(tmpdir, f"audit_{tag}.jsonl"),
        )


# ---------------------------------------------------------------------------
# Planner: per-basis coverage and post-F3 target detection.
# ---------------------------------------------------------------------------


class PlanBasisSeparationTest(unittest.TestCase):

    def test_adjusted_coverage_ignores_complete_raw_rows(self):
        """88 raw SPY rows must count ZERO toward aa=1 coverage, and the
        blocked event must still be a backfill target."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            plan = bf.plan_spy_adjusted_backfill(db_path=p)
        self.assertEqual(plan["target_event_ids"], [1])
        self.assertEqual(plan["auto_adjust"], 1)
        self.assertEqual(plan["spy_aa1_cached_in_window"], 0)
        self.assertGreater(plan["estimated_fetch_rows"], 0)

    def test_partial_adjusted_with_complete_raw_stays_target(self):
        """A partial aa=1 series plus a complete aa=0 series is still
        blocked (opposite basis cannot fill holes) and still a target."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True)
            res = _validate(p)
            plan = bf.plan_spy_adjusted_backfill(db_path=p)
        self.assertEqual(res["status"], esv.STATUS_INSUFFICIENT)
        self.assertEqual(plan["target_event_ids"], [1])

    def test_complete_opposite_basis_cannot_fill_requested_basis(self):
        """The default policy never resolves (adjusted asset, raw SPY);
        forcing the adjusted pair against a raw-only SPY is insufficient."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            default_res = _validate(p)
            with _Rebind(p):
                forced_adj = esv.build_event_study_validation(
                    _EVENT, flag_pairs=((True, True),))
        self.assertEqual(default_res["status"], esv.STATUS_INSUFFICIENT)
        self.assertNotIn("auto_adjust_basis", default_res)
        self.assertEqual(forced_adj["status"], esv.STATUS_INSUFFICIENT)


# ---------------------------------------------------------------------------
# Matched implies basis equality.
# ---------------------------------------------------------------------------


class MatchedBasisEqualityTest(unittest.TestCase):

    def test_cross_only_data_is_never_matched(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            res = _validate(p)
        self.assertEqual(res["status"], esv.STATUS_INSUFFICIENT)

    def test_backfill_produces_equal_bases_no_caveat_no_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            env = _apply(p, _fake_fetch, d)
            self.assertTrue(env["write_attempted"])
            self.assertGreater(env["applied_count"], 0)
            res = _validate(p)
        self.assertEqual(res["status"], esv.STATUS_AVAILABLE)
        basis = res["auto_adjust_basis"]
        self.assertEqual(basis["asset"], basis["benchmark"])
        self.assertEqual(basis, {"asset": True, "benchmark": True})
        self.assertNotIn("basis_caveat", res)
        self.assertNotIn("basis_fallback", res)


# ---------------------------------------------------------------------------
# Replacement semantics: full-slice, validated, idempotent, scoped.
# ---------------------------------------------------------------------------


class ReplacementSliceContractTest(unittest.TestCase):

    def test_full_slice_replaced_exactly_no_duplicates(self):
        """After a complete fetch the in-window aa=1 rows are EXACTLY the
        fetched dates (sentinels replaced), PK-unique, and rows outside
        the declared window (either basis) are preserved untouched."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True)
            plan = bf.plan_spy_adjusted_backfill(db_path=p)
            out_of_window_before = _table(
                p, "ticker='SPY' AND auto_adjust=1 AND date < ?",
                (plan["window_start"],))
            self.assertTrue(out_of_window_before)  # fixture has early sentinels
            env = _apply(p, _fake_fetch, d)
            self.assertGreater(env["applied_count"], 0)
            in_window = _table(
                p, "ticker='SPY' AND auto_adjust=1 AND date >= ? AND date <= ?",
                (plan["window_start"], plan["window_end"]))
            fetched = _fake_fetch(start=plan["window_start"],
                                  end=plan["window_end"])
            self.assertEqual({r[1] for r in in_window},
                             {r["date"] for r in fetched})
            # No sentinel close survives inside the window.
            self.assertTrue(all(r[3] > 1.0 for r in in_window))
            # PK uniqueness (defensive even with the schema PK present).
            self.assertEqual(len({(r[0], r[1], r[2]) for r in in_window}),
                             len(in_window))
            out_of_window_after = _table(
                p, "ticker='SPY' AND auto_adjust=1 AND date < ?",
                (plan["window_start"],))
            self.assertEqual(out_of_window_before, out_of_window_after)

    def test_incomplete_fetch_missing_week_stays_unmatched_and_visible(self):
        """A fetch missing a full week of window dates that previously held
        stale sentinel rows must NOT splice into a complete-looking series:
        the stale rows go with the slice, the hole stays visible, the event
        stays non-matched, and the planner still lists it after re-reading
        the committed state."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True)
            omit = _DATES[10:15]  # 5 consecutive weekdays, sentinels exist
            env = _apply(p, _fetch_omitting(omit), d)
            self.assertTrue(env["write_attempted"])
            self.assertGreater(env["applied_count"], 0)
            present = _spy_aa1_dates(p)
            for dt in omit:
                self.assertNotIn(
                    dt.isoformat(), present,
                    "stale sentinel row survived an incomplete replacement "
                    "and would fake completeness at " + dt.isoformat(),
                )
            res = _validate(p)
            plan_after = bf.plan_spy_adjusted_backfill(db_path=p)
        self.assertEqual(res["status"], esv.STATUS_INSUFFICIENT)
        self.assertEqual(plan_after["target_event_ids"], [1])

    def test_replacement_is_idempotent(self):
        """Convergence to a fixed point: the first run converts the event,
        the second run recomputes coverage from the COMMITTED state, finds
        no blocked target left, and is a clean no-op — identical rows,
        identical status, no expanding range, unrelated rows untouched,
        and no second provider fetch is needed."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True, extra_ticker="TLT")
            unrelated_before = _table(p, "ticker != 'SPY' OR auto_adjust = 0")
            env1 = _apply(p, _fake_fetch, d, tag="1")
            rows1 = _table(p, "ticker='SPY' AND auto_adjust=1")
            res1 = _validate(p)
            env2 = _apply(p, _fake_fetch, d, tag="2")
            rows2 = _table(p, "ticker='SPY' AND auto_adjust=1")
            res2 = _validate(p)
            unrelated_after = _table(p, "ticker != 'SPY' OR auto_adjust = 0")
        self.assertGreater(env1["applied_count"], 0)
        # Second run: nothing left to convert — refuse cleanly, write nothing.
        self.assertEqual(env2["applied_count"], 0)
        self.assertFalse(env2["write_attempted"])
        self.assertIn("no target window", env2["refuse_reason"] or "")
        self.assertEqual(rows1, rows2)
        self.assertEqual(res1["status"], res2["status"])
        self.assertEqual(res1.get("auto_adjust_basis"),
                         res2.get("auto_adjust_basis"))
        self.assertEqual(unrelated_before, unrelated_after)

    def test_committed_write_is_observed_by_public_paths(self):
        """Freshness: the same public consumer paths (validation build and
        planner) must observe the committed replacement — the event leaves
        the target list only because the re-read sees the new rows."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            self.assertEqual(
                bf.plan_spy_adjusted_backfill(db_path=p)["target_event_ids"],
                [1])
            self.assertEqual(_validate(p)["status"], esv.STATUS_INSUFFICIENT)
            _apply(p, _fake_fetch, d)
            self.assertEqual(_validate(p)["status"], esv.STATUS_AVAILABLE)
            self.assertEqual(
                bf.plan_spy_adjusted_backfill(db_path=p)["target_event_ids"],
                [])


# ---------------------------------------------------------------------------
# Provider-result validation: empty and malformed frames.
# ---------------------------------------------------------------------------


class ProviderResultValidationTest(unittest.TestCase):

    def test_empty_frame_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True)
            before = _table(p)
            env = _apply(p, lambda *, start, end: [], d)
            after = _table(p)
        self.assertTrue(env["write_attempted"])
        self.assertEqual(env["applied_count"], 0)
        self.assertIn("no usable SPY rows", env["refuse_reason"] or "")
        self.assertEqual(before, after)

    def test_malformed_rows_never_destroy_data(self):
        """Missing close, non-finite close, non-positive close, duplicate
        dates and out-of-window dates must never be written; the affected
        dates become visible holes, never NULL/NaN closes."""
        def _malformed(*, start, end):
            rows = _fake_fetch(start=start, end=end)
            bad = {dt.isoformat() for dt in _DATES[20:25]}  # one full week
            out = []
            for r in rows:
                if r["date"] in bad:
                    r = dict(r)
                    r.pop("close", None)          # missing close column
                    out.append(r)
                    out.append({"date": r["date"], "close": float("nan"),
                                "volume": 0.0})   # non-finite duplicate
                    out.append({"date": r["date"], "close": -1.0,
                                "volume": 0.0})   # non-positive duplicate
                else:
                    out.append(r)
            far = _EVENT_D + timedelta(days=400)
            out.append({"date": far.isoformat(), "close": 100.0,
                        "volume": 0.0})           # outside declared window
            out.append({"date": "not-a-date", "close": 100.0, "volume": 0.0})
            return out

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True)
            env = _apply(p, _malformed, d)
            self.assertTrue(env["write_attempted"])
            rows = _table(p, "ticker='SPY' AND auto_adjust=1")
            far_iso = (_EVENT_D + timedelta(days=400)).isoformat()
            res = _validate(p)
        closes = [r[3] for r in rows]
        self.assertTrue(all(c is not None for c in closes))
        self.assertTrue(all(math.isfinite(c) and c > 0 for c in closes))
        dates_present = {r[1] for r in rows}
        for dt in _DATES[20:25]:
            self.assertNotIn(dt.isoformat(), dates_present)
        self.assertNotIn(far_iso, dates_present)
        self.assertNotIn("not-a-date", dates_present)
        # A one-week hole exceeds the contiguity tolerance: never matched.
        self.assertEqual(res["status"], esv.STATUS_INSUFFICIENT)


# ---------------------------------------------------------------------------
# Unrelated data preservation.
# ---------------------------------------------------------------------------


class UnrelatedDataPreservationTest(unittest.TestCase):

    def test_only_the_declared_slice_changes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p, partial_spy_aa1=True, extra_ticker="TLT")
            events_before = _table(p, "1=0")  # placeholder, events via SQL below
            conn = sqlite3.connect(p)
            try:
                events_before = conn.execute("SELECT * FROM events").fetchall()
            finally:
                conn.close()
            tlt_before = _table(p, "ticker='TLT'")
            spy_raw_before = _table(p, "ticker='SPY' AND auto_adjust=0")
            self.assertTrue(tlt_before and spy_raw_before)
            _apply(p, _fake_fetch, d)
            tlt_after = _table(p, "ticker='TLT'")
            spy_raw_after = _table(p, "ticker='SPY' AND auto_adjust=0")
            conn = sqlite3.connect(p)
            try:
                events_after = conn.execute("SELECT * FROM events").fetchall()
            finally:
                conn.close()
        self.assertEqual(tlt_before, tlt_after)
        self.assertEqual(spy_raw_before, spy_raw_after)
        self.assertEqual(events_before, events_after)


# ---------------------------------------------------------------------------
# Provider / network boundary.
# ---------------------------------------------------------------------------


class ProviderBoundaryTest(unittest.TestCase):

    def test_plan_and_dry_run_never_fetch_or_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            with mock.patch.object(
                    bf, "_fetch_spy_adjusted",
                    side_effect=AssertionError("fetch in dry-run")), \
                 mock.patch.object(
                    socket, "getaddrinfo",
                    side_effect=AssertionError("DNS in dry-run")) as dns:
                bf.plan_spy_adjusted_backfill(db_path=p)
                bf.apply_spy_adjusted_backfill(db_path=p, confirm=False)
        self.assertEqual(dns.call_count, 0)

    def test_confirmed_apply_uses_only_the_patched_seam(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_db(p)
            with mock.patch.object(
                    socket, "getaddrinfo",
                    side_effect=AssertionError("DNS on apply")) as dns:
                env = _apply(p, _fake_fetch, d)
        self.assertTrue(env["write_attempted"])
        self.assertEqual(dns.call_count, 0)


if __name__ == "__main__":
    unittest.main()

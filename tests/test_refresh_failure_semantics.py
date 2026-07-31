"""A5A-R — refresh stamps and labels describe ACQUIRED data, not attempts.

Confirmed defect (A5-0 P3, A5A-V §8/§10): when every requested symbol
returns no usable market result but the provider function returns
normally, `refresh_market_for_saved_event` still advances
``last_market_check_at``, re-persists the previous market values, and
labels the response ``stale_refreshed`` — a false success on the explicit
refresh action and on the backtest GET.  Thrown provider errors already
skip persistence; the defect is the normal-return / zero-usable-data case.

Contract pinned here: a refresh may persist, stamp, and claim
``*_refreshed`` only when at least one requested symbol yielded a usable
calculated update; a total no-data attempt leaves every stored field and
the movers cache untouched and reports an explicit
``*_refresh_failed`` state.  Success, partial-success and thrown-failure
behaviors are control-pinned unchanged.  Write detection uses full-row
fingerprints, never counts.
"""

import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import api as _api
import db as _db
import market_check_freshness as _mcf
import market_data as _md

_HEADLINE = "Pipeline outage reroutes regional crude flows"

_ANALYSIS = {
    "what_changed": "A 400kb/d pipeline went down for repairs.",
    "mechanism_summary": "Rerouting raises landed costs while repairs run.",
    "beneficiaries": ["rail shippers"], "losers": ["inland refiners"],
    "beneficiary_tickers": ["UNP"], "loser_tickers": ["VLO"],
    "assets_to_watch": ["UNP", "VLO"], "confidence": "medium",
    "key_falsifiers": ["Repair completed within a week"],
    "minimum_proof_set": ["Regional crack spread widens"],
    "quality_tier": "watch_only", "if_persists": {}, "currency_channel": {},
}

_STORED_TICKERS = [
    {"symbol": "UNP", "label": "Union Pacific", "role": "beneficiary",
     "return_1d": 0.5, "return_5d": 1.2, "return_20d": 2.0,
     "direction_tag": "supports ↑", "volume_ratio": 1.0,
     "vs_xle_5d": 0.2, "spark": [10, 11, 12]},
    {"symbol": "VLO", "label": "Valero", "role": "loser",
     "return_1d": -0.3, "return_5d": -0.9, "return_20d": -1.4,
     "direction_tag": "supports ↓", "volume_ratio": 1.1,
     "vs_xle_5d": -0.1, "spark": [30, 29, 28]},
]


class _ArmedMarketProvider:
    def fetch_daily(self, t, **k):
        raise AssertionError(f"market provider reached: {t}")

    def fetch_info(self, t):
        raise AssertionError(f"market provider reached: {t}")


def _boom(*a, **k):
    raise AssertionError("analysis provider reached")


def _all_none_rows(tickers, event_date):
    return [{"symbol": t.get("symbol"), "role": t.get("role"),
             "return_1d": None, "return_5d": None, "return_20d": None,
             "return_60d": None, "direction": None, "anchor_date": None}
            for t in tickers]


class _Base(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_refresh_fail_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.eid = self._save()
        self._age_to_stale()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _save(self) -> int:
        stack = [
            patch("routes.analyze._call_analyze_event",
                  lambda *a, **k: dict(_ANALYSIS)),
            patch.object(_api, "build_macro_context_for_prompt",
                         return_value="Macro backdrop: fixed for tests"),
            patch.object(_api, "market_check",
                         return_value={"note": "stored note",
                                       "tickers": [dict(t) for t in
                                                   _STORED_TICKERS],
                                       "details": {}}),
            patch.object(_md, "_provider", _ArmedMarketProvider()),
        ]
        for p in stack:
            p.start()
        try:
            resp = self.client.post(
                "/analyze",
                json={"headline": _HEADLINE, "confirm_paid": True}).json()
        finally:
            for p in reversed(stack):
                p.stop()
        eid = resp.get("analysis_event_id")
        self.assertIsInstance(eid, int, resp)
        return int(eid)

    def _age_to_stale(self):
        now = datetime.now()
        conn = sqlite3.connect(self._tmp)
        conn.execute(
            "UPDATE events SET event_date = ?, timestamp = ?,"
            " last_market_check_at = ? WHERE id = ?",
            ((now - timedelta(days=6)).strftime("%Y-%m-%d"),
             (now - timedelta(days=6)).isoformat(timespec="seconds"),
             (now - timedelta(hours=90)).isoformat(timespec="seconds"),
             self.eid))
        conn.commit()
        conn.close()
        staleness = _mcf.compute_staleness(_db.load_event_by_id(self.eid))
        self.assertEqual(staleness["status"], "stale", staleness)

    def _row_fingerprint(self):
        conn = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT * FROM events WHERE id = ?",
                               (self.eid,)).fetchone()
            return hashlib.sha256(repr(row).encode()).hexdigest()
        finally:
            conn.close()

    def _market_row(self):
        ev = _db.load_event_by_id(self.eid)
        return {
            "tickers": [(t.get("symbol"), t.get("return_1d"),
                         t.get("return_5d"), t.get("return_20d"),
                         t.get("direction_tag"))
                        for t in ev.get("market_tickers") or []],
            "note": ev.get("market_note"),
            "check_at": ev.get("last_market_check_at"),
            "proof_status": ev.get("proof_status"),
            "falsifier_status": ev.get("falsifier_status"),
        }

    def _refresh(self, followup, movers=None):
        stack = [patch.object(_api, "followup_check", followup),
                 patch.object(_md, "_provider", _ArmedMarketProvider()),
                 patch("routes.analyze._call_analyze_event", _boom)]
        if movers is not None:
            stack.append(patch("movers_cache.invalidate", movers))
        for p in stack:
            p.start()
        try:
            return self.client.post(f"/events/{self.eid}/refresh-market")
        finally:
            for p in reversed(stack):
                p.stop()


class TestExplicitRefreshZeroDataFailure(_Base):

    def test_zero_data_cannot_advance_the_check_timestamp(self):
        before = self._market_row()
        resp = self._refresh(_all_none_rows)
        self.assertEqual(resp.status_code, 200, resp.text)
        after = self._market_row()
        self.assertEqual(after["check_at"], before["check_at"],
                         "a refresh that obtained no data stamped the row")

    def test_zero_data_leaves_the_event_row_byte_identical(self):
        before = self._row_fingerprint()
        self._refresh(_all_none_rows)
        self.assertEqual(self._row_fingerprint(), before)

    def test_zero_data_reports_an_explicit_failed_attempt(self):
        body = self._refresh(_all_none_rows).json()
        staleness = (body.get("market") or {}).get("market_check_staleness")
        self.assertEqual(staleness, "stale_refresh_failed")
        self.assertNotIn(staleness, ("stale_refreshed", "fresh",
                                     "forced_refreshed"))

    def test_zero_data_never_touches_the_movers_cache(self):
        from unittest.mock import MagicMock
        movers = MagicMock()
        self._refresh(_all_none_rows, movers=movers)
        movers.assert_not_called()

    def test_proof_and_falsifier_survive_a_zero_data_attempt(self):
        before = self._market_row()
        self._refresh(_all_none_rows)
        after = self._market_row()
        self.assertEqual(after["proof_status"], before["proof_status"])
        self.assertEqual(after["falsifier_status"],
                         before["falsifier_status"])


class TestRefreshSuccessControls(_Base):
    """Success, partial-success and thrown-failure behavior is unchanged."""

    def test_partial_success_is_not_treated_as_total_failure(self):
        def partial(tickers, event_date):
            rows = _all_none_rows(tickers, event_date)
            rows[0] = {"symbol": tickers[0].get("symbol"),
                       "role": tickers[0].get("role"),
                       "return_1d": 10.0, "return_5d": 20.0,
                       "return_20d": 30.0, "return_60d": None,
                       "direction": "supports", "anchor_date": event_date}
            return rows

        from unittest.mock import MagicMock
        movers = MagicMock()
        before = self._market_row()
        body = self._refresh(partial, movers=movers).json()
        after = self._market_row()
        self.assertNotEqual(after["check_at"], before["check_at"])
        # The usable symbol updated; the unavailable one kept stored values.
        self.assertEqual(after["tickers"][0][1], 10.0)
        self.assertEqual(after["tickers"][1][1], before["tickers"][1][1])
        self.assertEqual((body.get("market") or {})
                         .get("market_check_staleness"), "stale_refreshed")
        movers.assert_called_once()

    def test_full_success_still_persists_and_stamps(self):
        def full(tickers, event_date):
            return [{"symbol": t.get("symbol"), "role": t.get("role"),
                     "return_1d": 5.0, "return_5d": 6.0, "return_20d": 7.0,
                     "return_60d": None, "direction": "supports",
                     "anchor_date": event_date} for t in tickers]

        before = self._market_row()
        self._refresh(full)
        after = self._market_row()
        self.assertNotEqual(after["check_at"], before["check_at"])
        self.assertEqual(after["tickers"][0][1], 5.0)

    def test_thrown_failure_still_skips_persistence(self):
        def raising(tickers, event_date):
            raise RuntimeError("total provider failure")

        before = self._row_fingerprint()
        resp = self._refresh(raising)
        self.assertEqual(self._row_fingerprint(), before)
        self.assertEqual(resp.status_code, 200)


class TestRollingModeZeroData(_Base):
    """The rolling branch (no event_date) obeys the same rule, proven at
    the shared seam with an injected persist recorder."""

    def test_rolling_zero_data_does_not_persist_or_stamp(self):
        event = _db.load_event_by_id(self.eid)
        event = dict(event)
        event["event_date"] = None  # forces the rolling market_check branch
        persists = []

        def rolling_none(bens, losers, event_date=None):
            return {"note": "attempted",
                    "tickers": _all_none_rows(
                        [{"symbol": s, "role": "beneficiary"}
                         for s in bens + losers], None)}

        result = _mcf.refresh_market_for_saved_event(
            event,
            followup_check_fn=_all_none_rows,
            market_check_fn=rolling_none,
            persist_fn=lambda *a, **k: persists.append(a))
        self.assertEqual(persists, [])
        self.assertEqual(result.get("market_check_staleness"),
                         "stale_refresh_failed")
        self.assertEqual(result.get("last_market_check_at"),
                         event.get("last_market_check_at"))


class TestBacktestZeroDataFailure(_Base):

    def _backtest(self, followup):
        stack = [patch.object(_api, "followup_check", followup),
                 patch.object(_md, "_provider", _ArmedMarketProvider()),
                 patch("routes.analyze._call_analyze_event", _boom)]
        for p in stack:
            p.start()
        try:
            return self.client.get(f"/events/{self.eid}/backtest")
        finally:
            for p in reversed(stack):
                p.stop()

    def test_backtest_zero_data_cannot_stamp_or_persist(self):
        before = self._row_fingerprint()
        check_before = self._market_row()["check_at"]
        resp = self._backtest(_all_none_rows)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._row_fingerprint(), before,
                         "a zero-data backtest GET mutated the event row")
        self.assertEqual(self._market_row()["check_at"], check_before)

    def test_backtest_zero_data_presents_no_false_refreshed_state(self):
        body = self._backtest(_all_none_rows).json()
        staleness = body.get("market_check_staleness")
        if staleness is not None:
            self.assertNotIn(staleness, ("stale_refreshed", "fresh",
                                         "legacy_refreshed",
                                         "forced_refreshed"))


if __name__ == "__main__":
    unittest.main()

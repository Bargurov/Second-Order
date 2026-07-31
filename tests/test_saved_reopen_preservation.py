"""A5A — saved reopening serves stored evidence without external work or writes.

The confirmed defect: numeric and durable reopen both route the market block
through the freshness refresher, so merely VIEWING a stale saved analysis
could fetch market data, overwrite the stored returns and direction tags,
advance ``last_market_check_at`` (even when every symbol failed), rewrite the
derived ``proof_status`` / ``falsifier_status`` columns, and invalidate the
movers cache — silently moving validation status and the live outcome ledger.

The contract pinned here: the default view path returns the saved analysis
plus the stored market fields AS SAVED with truthful stale/legacy labels,
runs its overlay recompute inside the no-provider-fetch boundary, and
performs ZERO provider calls and ZERO database writes.  Mutation belongs
only to the explicit refresh boundary (``POST /events/{id}/refresh-market``
and ``force=True``), which must keep working unchanged.

Write detection uses whole-database, full-row and per-table fingerprints —
never row counts, because UPDATEs preserve counts.
"""

import hashlib
import json
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

_DIRECT = "Refinery maintenance wave tightens summer diesel supply"

_ANALYSIS = {
    "what_changed": "Overlapping turnarounds removed 600kb/d of capacity.",
    "mechanism_summary": "Regional diesel balance tightens through Q3.",
    "beneficiaries": ["independent refiners"], "losers": ["road hauliers"],
    "beneficiary_tickers": ["VLO"], "loser_tickers": ["ODFL"],
    "assets_to_watch": ["VLO", "ODFL"], "confidence": "medium",
    "key_falsifiers": ["Diesel cracks flat after 5 sessions"],
    "minimum_proof_set": ["Diesel crack > +8%"],
    "quality_tier": "watch_only", "if_persists": {}, "currency_channel": {},
}

# Stored at save time via the patched fresh-path market_check; the view
# contract is that these exact values (returns, direction tags) survive
# every reopen untouched.
_STORED_TICKERS = [
    {"symbol": "VLO", "label": "Valero", "role": "beneficiary",
     "return_1d": 1.0, "return_5d": 2.0, "return_20d": 3.0,
     "direction_tag": "supports ↑", "volume_ratio": 1.0,
     "vs_xle_5d": 0.1, "spark": [100, 101, 102]},
    {"symbol": "ODFL", "label": "Old Dominion", "role": "loser",
     "return_1d": 0.4, "return_5d": -1.5, "return_20d": -2.2,
     "direction_tag": "contradicts ↑", "volume_ratio": 0.9,
     "vs_xle_5d": -0.3, "spark": [55, 54, 53]},
]

_TABLES = ("events", "price_cache", "movers_cache", "analysis_provenance",
           "analysis_result_snapshot", "analysis_request_cache",
           "headline_registry")


class _ArmedMarketProvider:
    """Any real provider fetch during a view is a contract violation."""

    def fetch_daily(self, ticker, **kw):
        raise AssertionError(f"market provider reached: {ticker}")

    def fetch_info(self, ticker):
        raise AssertionError(f"market provider reached: {ticker}")


def _boom(*a, **k):
    raise AssertionError("analysis provider reached")


class _Base(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_reopen_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.followup_calls: list = []
        self.eid = self._save_direct_analysis()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # -- fixture -----------------------------------------------------------

    def _post(self, body, extra=None):
        """POST /analyze with every external seam pinned.

        The macro backdrop is fixed so the durable request identity is
        deterministic (same recipe as tests/test_durable_request_cache.py);
        the market-data provider is armed so no code path can silently
        reach the network.
        """
        stack = [
            patch("routes.analyze._call_analyze_event",
                  lambda *a, **k: dict(_ANALYSIS)),
            patch.object(_api, "build_macro_context_for_prompt",
                         return_value="Macro backdrop: fixed for tests"),
            patch.object(_api, "market_check",
                         return_value={"note": "stored market note",
                                       "tickers": [dict(t) for t in
                                                   _STORED_TICKERS],
                                       "details": {}}),
            patch.object(_md, "_provider", _ArmedMarketProvider()),
        ]
        for p in (extra or []):
            stack.append(p)
        for p in stack:
            p.start()
        try:
            return self.client.post("/analyze", json=body)
        finally:
            for p in reversed(stack):
                p.stop()

    def _save_direct_analysis(self) -> int:
        resp = self._post({"headline": _DIRECT, "confirm_paid": True}).json()
        eid = resp.get("analysis_event_id")
        self.assertIsInstance(eid, int, resp)
        return int(eid)

    def _age_to_stale(self):
        """Age the saved row so the view hits the refresh window.

        Both timestamps derive from the SAME runtime clock (no fixed
        calendar dates), and the resulting status is asserted directly so
        the fixture can never silently drift into fresh/frozen.
        """
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

    # -- seams -------------------------------------------------------------

    def _followup_success(self, tickers, event_date):
        self.followup_calls.append([t.get("symbol") for t in tickers])
        return [{"symbol": t.get("symbol"), "role": t.get("role"),
                 "return_1d": 10.0, "return_5d": 20.0, "return_20d": 30.0,
                 "return_60d": None, "direction": "supports",
                 "anchor_date": event_date} for t in tickers]

    def _followup_all_none(self, tickers, event_date):
        self.followup_calls.append([t.get("symbol") for t in tickers])
        return [{"symbol": t.get("symbol"), "role": t.get("role"),
                 "return_1d": None, "return_5d": None, "return_20d": None,
                 "return_60d": None, "direction": None, "anchor_date": None}
                for t in tickers]

    # -- fingerprints ------------------------------------------------------

    def _db_sha(self):
        h = hashlib.sha256()
        with open(self._tmp, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _table_shas(self):
        conn = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            out = {}
            for t in _TABLES:
                h = hashlib.sha256()
                for row in conn.execute(f"SELECT * FROM {t} ORDER BY rowid"):
                    h.update(repr(row).encode())
                out[t] = h.hexdigest()
            return out
        finally:
            conn.close()

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


class TestNumericReopenIsNonDestructive(_Base):

    def _reopen(self, followup, force=False):
        body = {"headline": _DIRECT, "event_id": self.eid}
        if force:
            body["force"] = True
        return self._post(
            body, extra=[patch.object(_api, "followup_check", followup)])

    def test_a_stale_numeric_reopen_makes_zero_market_refresh_calls(self):
        self._age_to_stale()
        resp = self._reopen(self._followup_success)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.followup_calls, [])

    def test_a_stale_numeric_reopen_leaves_the_full_event_row_byte_identical(self):
        self._age_to_stale()
        before = self._row_fingerprint()
        self._reopen(self._followup_success)
        self.assertEqual(self._row_fingerprint(), before,
                         "viewing a saved analysis mutated its event row")

    def test_a_stale_view_leaves_every_table_fingerprint_unchanged(self):
        self._age_to_stale()
        db_before, tables_before = self._db_sha(), self._table_shas()
        self._reopen(self._followup_success)
        self.assertEqual(self._table_shas(), tables_before)
        self.assertEqual(self._db_sha(), db_before)

    def test_all_none_followup_results_cannot_advance_the_check_timestamp(self):
        # Per-symbol failures return all-None rows (the function does NOT
        # raise); the stored check timestamp must survive the view — a row
        # must never claim a check that did not succeed.
        self._age_to_stale()
        before = self._market_row()
        self._reopen(self._followup_all_none)
        after = self._market_row()
        self.assertEqual(after["check_at"], before["check_at"])
        self.assertEqual(after["tickers"], before["tickers"])

    def test_proof_and_falsifier_columns_survive_a_view(self):
        self._age_to_stale()
        before = self._market_row()
        self._reopen(self._followup_success)
        after = self._market_row()
        self.assertEqual(after["proof_status"], before["proof_status"])
        self.assertEqual(after["falsifier_status"], before["falsifier_status"])

    def test_view_path_overlays_run_inside_the_no_fetch_boundary(self):
        self._age_to_stale()
        seen: list = []

        def recording_rates_context():
            seen.append(_md.provider_fetch_blocked())
            return None

        self._reopen(self._followup_success)  # warm nothing; then observe:
        with patch.object(_api, "compute_rates_context",
                          recording_rates_context):
            self._reopen(self._followup_success)
        self.assertTrue(seen, "compute_rates_context was never reached")
        self.assertTrue(all(seen),
                        "view-path overlay recompute ran OUTSIDE the "
                        "no-provider-fetch boundary")

    def test_view_path_never_invalidates_the_movers_cache(self):
        self._age_to_stale()
        with patch("movers_cache.invalidate") as inv:
            self._reopen(self._followup_success)
        inv.assert_not_called()

    def test_a_stale_view_reports_truthful_staleness_not_a_refresh_label(self):
        self._age_to_stale()
        stored = self._market_row()
        resp = self._reopen(self._followup_success).json()
        market = resp.get("market") or {}
        self.assertEqual(market.get("market_check_staleness"), "stale")
        self.assertEqual(market.get("last_market_check_at"),
                         stored["check_at"])
        got = [(t.get("symbol"), t.get("return_1d"), t.get("return_5d"),
                t.get("return_20d"), t.get("direction_tag"))
               for t in market.get("tickers") or []]
        self.assertEqual(got, stored["tickers"])


class TestDurableReopenIsNonDestructive(_Base):
    """The same contract proven through the durable request-identity path.

    The legacy headline lookup is pinned to None and the analysis provider
    is armed, so ONLY the durable request hash can serve the reopen — a
    served response is itself proof the durable path resolved it.
    """

    def _durable_reopen(self, followup):
        return self._post(
            {"headline": _DIRECT},
            extra=[
                patch.object(_api, "followup_check", followup),
                patch("routes.analyze._legacy_headline_cached_event",
                      lambda *a, **k: None),
                patch("routes.analyze._call_analyze_event", _boom),
            ])

    def test_a_stale_durable_reopen_is_served_with_zero_refresh_calls(self):
        self._age_to_stale()
        resp = self._durable_reopen(self._followup_success)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("analysis", {}).get("mechanism_summary"),
                         _ANALYSIS["mechanism_summary"])
        self.assertEqual(self.followup_calls, [])

    def test_a_stale_durable_reopen_leaves_the_event_row_byte_identical(self):
        self._age_to_stale()
        before = self._row_fingerprint()
        self._durable_reopen(self._followup_success)
        self.assertEqual(self._row_fingerprint(), before)

    def test_a_stale_durable_reopen_reports_truthful_staleness(self):
        self._age_to_stale()
        stored = self._market_row()
        body = self._durable_reopen(self._followup_success).json()
        market = body.get("market") or {}
        self.assertEqual(market.get("market_check_staleness"), "stale")
        self.assertEqual(market.get("last_market_check_at"),
                         stored["check_at"])

    def test_durable_and_numeric_reopen_agree_on_the_saved_analysis(self):
        self._age_to_stale()
        durable = self._durable_reopen(self._followup_success).json()
        numeric = self._post(
            {"headline": _DIRECT, "event_id": self.eid},
            extra=[patch.object(_api, "followup_check",
                                self._followup_success)]).json()
        keys = ("what_changed", "mechanism_summary", "key_falsifiers",
                "minimum_proof_set", "quality_tier")
        self.assertEqual(
            {k: durable.get("analysis", {}).get(k) for k in keys},
            {k: numeric.get("analysis", {}).get(k) for k in keys})


class TestExplicitRefreshBoundaryStillWorks(_Base):
    """Mutation stays available — but only behind explicit operator intent."""

    def test_the_refresh_route_reaches_the_seam_and_persists(self):
        self._age_to_stale()
        before = self._market_row()
        with patch.object(_api, "followup_check", self._followup_success), \
             patch.object(_api, "market_check",
                          side_effect=AssertionError("rolling path reached")), \
             patch("routes.analyze._call_analyze_event", _boom), \
             patch("movers_cache.invalidate") as inv:
            resp = self.client.post(f"/events/{self.eid}/refresh-market")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(self.followup_calls), 1)
        after = self._market_row()
        self.assertNotEqual(after["check_at"], before["check_at"])
        self.assertEqual(after["tickers"][0][1], 10.0)
        inv.assert_called_once()

    def test_a_forced_reopen_still_refreshes_and_persists(self):
        self._age_to_stale()
        before = self._market_row()
        resp = self._post(
            {"headline": _DIRECT, "event_id": self.eid, "force": True},
            extra=[patch.object(_api, "followup_check",
                                self._followup_success)])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.followup_calls), 1)
        after = self._market_row()
        self.assertNotEqual(after["check_at"], before["check_at"])
        self.assertEqual(after["tickers"][0][1], 10.0)


if __name__ == "__main__":
    unittest.main()

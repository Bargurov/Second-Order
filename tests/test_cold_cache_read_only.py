"""A5A-R2 — a saved reopen must not ATTEMPT cache writes, even cold.

Inside the ``no_provider_fetch()`` view boundary, the price-cache read
path historically ran its bootstrap on first touch — CREATE TABLE /
CREATE INDEX / an ALTER migration attempt / a corrupt-row DELETE purge —
so a cold process could execute write statements merely because a
reviewer opened a saved analysis.  The protected DB survived earlier
probes only because the table already existed; a read-only view must not
attempt schema or cleanup writes at all.

Contract pinned here: with the price_cache table ABSENT and the bootstrap
flag cold, numeric and durable saved reopens complete successfully
(saved analysis + stored market fields served, overlays explicitly
unavailable) while an sqlite authorizer attached to every connection
records ZERO create/alter/insert/update/delete attempts.  Intentional
bootstrap outside the view boundary keeps working.
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
import price_cache as _pc

_HEADLINE = "Grid maintenance cuts smelter power for a week"

_ANALYSIS = {
    "what_changed": "A regional grid cut idled two aluminium smelters.",
    "mechanism_summary": "Supply tightens while power is rationed.",
    "beneficiaries": ["other smelters"], "losers": ["fabricators"],
    "beneficiary_tickers": ["AA"], "loser_tickers": ["ARNC"],
    "assets_to_watch": ["AA", "ARNC"], "confidence": "medium",
    "key_falsifiers": ["Power restored early"],
    "minimum_proof_set": ["Regional premium widens"],
    "quality_tier": "watch_only", "if_persists": {}, "currency_channel": {},
}

_STORED_TICKERS = [
    {"symbol": "AA", "label": "Alcoa", "role": "beneficiary",
     "return_1d": 0.8, "return_5d": 1.6, "return_20d": 2.4,
     "direction_tag": "supports ↑"},
    {"symbol": "ARNC", "label": "Arconic", "role": "loser",
     "return_1d": -0.2, "return_5d": -0.7, "return_20d": -1.1,
     "direction_tag": "supports ↓"},
]

# sqlite authorizer action codes for write-shaped operations.
_WRITE_ACTIONS = {
    sqlite3.SQLITE_CREATE_TABLE: "create_table",
    sqlite3.SQLITE_CREATE_INDEX: "create_index",
    sqlite3.SQLITE_ALTER_TABLE: "alter_table",
    sqlite3.SQLITE_INSERT: "insert",
    sqlite3.SQLITE_UPDATE: "update",
    sqlite3.SQLITE_DELETE: "delete",
}


class _Base(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_coldcache_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.eid = self._save()
        self._age_to_stale()
        self._drop_price_cache()
        _pc._reset_table_ready_for_tests()
        self.write_attempts: list = []

    def tearDown(self):
        _pc._reset_table_ready_for_tests()
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # -- fixture -----------------------------------------------------------

    def _post(self, body, extra=None):
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
            patch.object(_md, "_provider", _Armed()),
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

    def _save(self) -> int:
        resp = self._post({"headline": _HEADLINE, "confirm_paid": True}).json()
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

    def _drop_price_cache(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute("DROP TABLE IF EXISTS price_cache")
        conn.commit()
        conn.close()

    def _db_sha(self):
        h = hashlib.sha256()
        with open(self._tmp, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    # -- recording authorizer over every DB connection ---------------------

    def _recording_connect_db(self):
        # ``connect_db()`` returns a raw sqlite3.Connection that callers use
        # both bare and via ``with`` (transaction semantics), so the
        # recorder attaches an authorizer to the REAL connection instead of
        # wrapping it.
        real = _db.connect_db
        attempts = self.write_attempts

        def authorize(action, a1, a2, dbname, source):
            label = _WRITE_ACTIONS.get(action)
            if label and not (a1 or "").startswith("sqlite_"):
                attempts.append((label, a1))
            return sqlite3.SQLITE_OK

        def wrapped(*a, **k):
            conn = real(*a, **k)
            conn.set_authorizer(authorize)
            return conn

        return patch.object(_db, "connect_db", wrapped)


class _Armed:
    def fetch_daily(self, t, **k):
        raise AssertionError(f"market provider reached: {t}")

    def fetch_info(self, t):
        raise AssertionError(f"market provider reached: {t}")


class TestColdSavedReopenAttemptsNoWrites(_Base):

    def test_a_cold_numeric_reopen_attempts_zero_cache_writes(self):
        before = self._db_sha()
        with self._recording_connect_db():
            resp = self._post({"headline": _HEADLINE, "event_id": self.eid})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("analysis", {}).get("mechanism_summary"),
                         _ANALYSIS["mechanism_summary"])
        tickers = (body.get("market") or {}).get("tickers") or []
        self.assertEqual(tickers[0].get("return_5d"), 1.6)
        self.assertEqual(self.write_attempts, [],
                         "a saved reopen ATTEMPTED cache writes")
        self.assertEqual(self._db_sha(), before,
                         "a saved reopen changed the database file")

    def test_a_cold_durable_reopen_attempts_zero_cache_writes(self):
        before = self._db_sha()
        with self._recording_connect_db():
            resp = self._post(
                {"headline": _HEADLINE},
                extra=[patch("routes.analyze._legacy_headline_cached_event",
                             lambda *a, **k: None),
                       patch("routes.analyze._call_analyze_event",
                             lambda *a, **k: (_ for _ in ()).throw(
                                 AssertionError("analysis provider")))])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("analysis", {})
                         .get("mechanism_summary"),
                         _ANALYSIS["mechanism_summary"])
        self.assertEqual(self.write_attempts, [])
        self.assertEqual(self._db_sha(), before)

    def test_a_blocked_cache_read_returns_unavailable_without_bootstrap(self):
        with self._recording_connect_db():
            with _md.no_provider_fetch():
                out = _pc.fetch_daily_cached("SPY", period="3mo")
        self.assertIsNone(out)
        self.assertEqual(self.write_attempts, [])

    def test_bootstrap_still_works_outside_the_view_boundary(self):
        # Intentional (startup / explicit) consumers keep their existing
        # write-capable initialization: outside no_provider_fetch the
        # bootstrap creates the table again.
        with self._recording_connect_db():
            ok = _pc._ensure_table()
        self.assertTrue(ok)
        created = [a for a in self.write_attempts if a[0] == "create_table"]
        self.assertTrue(created, "bootstrap no longer creates the table")


if __name__ == "__main__":
    unittest.main()

"""G1 — cached /analyze {event_id} restore carries the sibling evidence blocks.

The saved-event restore path (POST /analyze with ``event_id`` → cache hit via
``load_event_by_id`` → ``api._build_cached_response``) must surface the same
``validation_status_v2`` and ``reaction_profile_v1`` reads that
``GET /events/{id}`` attaches, so AnalysisView shows the same sibling blocks
(and the F1 v2 caveat).

Placement: nested under ``analysis`` (``analysis.validation_status_v2`` /
``analysis.reaction_profile_v1``) — NOT a new top-level key — so the
fresh/cached top-level key-parity contract (test_freeze_policy_contract)
stays intact.  AnalysisView reads them via its
``result.validation_status_v2 ?? result.analysis?.validation_status_v2``
fallback.

Read-only: ``score_validation_status`` is a pure tape read of the stored
``market_tickers``; ``build_reaction_profile_v1`` hydrates per-ticker
profiles from the ``price_cache`` table with no provider fetch and no DB
write.  A frozen (>30d) event is used so the pre-existing market-refresh /
persist path is skipped, isolating the additive reads.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


def _mock_analyze(inp):
    return {
        "what_changed": "Stub change.",
        "mechanism_summary": "Stub mechanism.",
        "beneficiaries": ["CompanyA"],
        "losers": ["CompanyB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
        "transmission_chain": ["a", "b", "c"],
        "if_persists": {},
        "currency_channel": {},
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {"note": "stub", "details": {}, "tickers": []}


_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
]

# tables the cached restore must not mutate (all live in the one events.db)
_SNAPSHOT_TABLES = ("events", "price_cache", "movers_cache")


def _snapshot(db_path: str) -> dict:
    """Ordered dump of every row in the read-only-contract tables."""
    snap: dict[str, list] = {}
    con = sqlite3.connect(db_path)
    try:
        for table in _SNAPSHOT_TABLES:
            try:
                rows = con.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                rows = []
            snap[table] = sorted(repr(r) for r in rows)
    finally:
        con.close()
    return snap


class TestCachedAnalyzeSiblingBlocks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        for p in _PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_g1_sibling_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_frozen_event(self) -> tuple[int, str]:
        """Seed a frozen (>30d) event with directional market_tickers."""
        frozen_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        headline = f"G1 sibling-block restore {uuid.uuid4().hex[:6]}"
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "what_changed": "ctx",
            "mechanism_summary": "mech",
            "event_date": frozen_date,
            "model": self.api._active_model(),
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 2.1,
                 "direction_tag": "supports ↑"},
                {"symbol": "MSFT", "role": "loser", "return_5d": -1.4,
                 "direction_tag": "supports ↓"},
            ],
        })
        eid = db.load_recent_events(1)[0]["id"]
        return eid, headline

    def _restore(self, eid: int, headline: str) -> dict:
        """POST /analyze through the event_id (load_event_by_id) branch."""
        r = self.client.post("/analyze", json={"headline": headline, "event_id": eid})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cached_restore_carries_validation_status_v2(self):
        eid, headline = self._seed_frozen_event()
        body = self._restore(eid, headline)
        block = body["analysis"].get("validation_status_v2")
        self.assertIsInstance(block, dict, "validation_status_v2 must be present under analysis")
        self.assertIn("status", block)
        self.assertIsInstance(block["status"], str)

    def test_cached_restore_carries_reaction_profile_v1(self):
        eid, headline = self._seed_frozen_event()
        body = self._restore(eid, headline)
        block = body["analysis"].get("reaction_profile_v1")
        self.assertIsInstance(block, dict, "reaction_profile_v1 must be present under analysis")
        self.assertIn("available", block)
        self.assertIsInstance(block["available"], bool)
        self.assertIn("reason", block)
        self.assertIsInstance(block["reason"], str)
        self.assertIn("tickers", block)
        self.assertIsInstance(block["tickers"], list)
        self.assertIn("n_tickers", block)
        self.assertIsInstance(block["n_tickers"], int)
        # two seeded tickers → two per-ticker entries
        self.assertEqual(block["n_tickers"], 2)

    def test_cached_restore_is_read_only(self):
        eid, headline = self._seed_frozen_event()
        before = _snapshot(self._tmp)
        self._restore(eid, headline)
        after = _snapshot(self._tmp)
        self.assertEqual(
            before, after,
            "cached /analyze {event_id} restore must not mutate "
            "events / price_cache / movers_cache",
        )


if __name__ == "__main__":
    unittest.main()

"""
API-level tests for headline normalization.

Covers:
- Prefixed headline hits cache of clean headline (no duplicate LLM call)
- Response headline field returns the normalized (clean) form
- Event-id routing still works regardless of headline prefix
- Clean headline is unchanged through the pipeline
"""

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


# ---------------------------------------------------------------------------
# Mocks — same shape as test_event_age_policy.py
# ---------------------------------------------------------------------------

_analyze_call_count = 0


def _mock_analyze(inp):
    global _analyze_call_count
    _analyze_call_count += 1
    return {
        "what_changed": f"Stub for: {inp.headline}",
        "mechanism_summary": "Stub mechanism.",
        "beneficiaries": ["TestCo"],
        "losers": ["OtherCo"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
        "transmission_chain": ["a", "b"],
        "if_persists": {},
        "currency_channel": {},
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Stub market.",
        "details": {},
        "tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "direction_tag": "supports \u2191",
             "return_1d": 0.1, "return_5d": 0.5, "return_20d": 1.2,
             "volume_ratio": 1.0, "vs_xle_5d": None, "spark": []},
        ],
    }


_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
]


class TestHeadlineNormalizationApi(unittest.TestCase):
    """Prefixed headlines must normalize and hit the cache of the clean version."""

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
        global _analyze_call_count
        _analyze_call_count = 0
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_norm_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass

    def _post(self, headline, **extra):
        event_date = extra.pop(
            "event_date",
            (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        payload = {"headline": headline, "event_date": event_date, **extra}
        return self.client.post("/analyze", json=payload)

    # ------------------------------------------------------------------
    # Core tests
    # ------------------------------------------------------------------

    def test_prefixed_headline_hits_cache_of_clean(self):
        """Post clean headline, then post prefixed — second call is a cache hit."""
        global _analyze_call_count
        clean = f"OPEC extends output cuts {uuid.uuid4().hex[:6]}"
        prefixed = f"AP News: {clean}"
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        r1 = self._post(clean, event_date=date)
        self.assertEqual(r1.status_code, 200)
        calls_after_first = _analyze_call_count

        r2 = self._post(prefixed, event_date=date)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            _analyze_call_count, calls_after_first,
            "Prefixed headline should hit cache — no new analyze_event call",
        )

    def test_response_headline_is_normalized(self):
        """The response headline field must be the clean form, not the prefix."""
        prefixed = f"Reuters: ECB cuts rates by 25bps {uuid.uuid4().hex[:6]}"
        r = self._post(prefixed)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(
            body["headline"].startswith("Reuters:"),
            f"Response headline should be normalized, got: {body['headline']}",
        )

    def test_clean_headline_unchanged(self):
        """A headline without a source prefix must pass through unchanged."""
        clean = f"Fed holds rates steady {uuid.uuid4().hex[:6]}"
        r = self._post(clean)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["headline"], clean)

    def test_event_id_routing_unaffected_by_normalization(self):
        """event_id routing bypasses headline lookup entirely."""
        clean = f"Trade talks resume {uuid.uuid4().hex[:6]}"
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Seed via clean headline
        r1 = self._post(clean, event_date=date)
        self.assertEqual(r1.status_code, 200)

        # Get the event_id from DB
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            row = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(row)
        eid = row[0]

        # Post with event_id — should return the cached event's analysis,
        # not trigger a new LLM call.  The response headline echoes the
        # request (by design), but the analysis body comes from the DB row.
        global _analyze_call_count
        calls_before = _analyze_call_count
        r2 = self._post(clean, event_date=date, event_id=eid)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            _analyze_call_count, calls_before,
            "event_id routing should hit cache — no new analyze_event call",
        )

    def test_different_prefixes_same_clean_hit_cache(self):
        """AP News: X and Reuters: X should both resolve to the same cached X."""
        global _analyze_call_count
        clean = f"Oil prices surge {uuid.uuid4().hex[:6]}"
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        r1 = self._post(f"AP News: {clean}", event_date=date)
        self.assertEqual(r1.status_code, 200)
        calls_after_first = _analyze_call_count

        r2 = self._post(f"Reuters: {clean}", event_date=date)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            _analyze_call_count, calls_after_first,
            "Different source prefixes on the same body should share the cache",
        )

    def test_db_stores_normalized_headline(self):
        """The headline persisted in the DB should be the normalized form."""
        prefixed = f"Bloomberg: Tariffs escalate on EVs {uuid.uuid4().hex[:6]}"
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        r = self._post(prefixed, event_date=date)
        self.assertEqual(r.status_code, 200)

        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            row = conn.execute(
                "SELECT headline FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertFalse(
            row[0].startswith("Bloomberg:"),
            f"DB headline should be normalized, got: {row[0]}",
        )


if __name__ == "__main__":
    unittest.main()

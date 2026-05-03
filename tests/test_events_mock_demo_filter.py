"""tests/test_events_mock_demo_filter.py

Focused tests for the default mock/demo/degraded suppression on
``GET /events`` and the ``include_mock=true`` opt-in.

Invariants:
  1) Default ``/events`` excludes mock + demo + degraded rows; ``total``
     reflects the post-filter universe (pagination stays consistent).
  2) ``/events?include_mock=true`` brings them back.
  3) ``/events/{event_id}`` returns mock/demo/degraded rows regardless —
     detail review by id is unaffected.
  4) Real (clean) rows are unaffected on the default path.

No LLM or market calls — events are seeded directly into a temp DB.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(), f"test_events_mock_{uuid.uuid4().hex}.db",
    )


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


def _seed(
    *,
    headline: str,
    what_changed: str = "Real change description",
    model: str | None = None,
    days_old: int = 1,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "event_date": today,
        "timestamp": ts,
        "what_changed": what_changed,
        "mechanism_summary": "Mechanism summary text long enough to pass.",
        "model": model,
        "market_tickers": [
            {
                "symbol": "XLE",
                "role": "beneficiary",
                "return_5d": 4.0,
                "return_20d": 5.0,
                "direction_tag": "supports ↑",
                "spark": [0.1, 0.2, 0.3],
                "anchor_date": today,
            },
        ],
    })
    return db.load_recent_events(1)[0]["id"]


class _Base(unittest.TestCase):

    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestDefaultListingHidesPollution(_Base):

    def test_mock_row_hidden_by_default(self) -> None:
        mock_id = _seed(
            headline="Fed mock headline",
            what_changed="[mock: overloaded]",
        )
        real_id = _seed(headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(mock_id, ids)
        self.assertEqual(body["total"], 1)

    def test_demo_seed_row_hidden_by_default(self) -> None:
        demo_by_model = _seed(
            headline="Showcase real-looking headline",
            model="showcase_seed_v1",
        )
        demo_by_prefix = _seed(headline="[DEMO] Showcase headline")
        real_id = _seed(headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(demo_by_model, ids)
        self.assertNotIn(demo_by_prefix, ids)
        self.assertEqual(body["total"], 1)

    def test_degraded_row_hidden_by_default(self) -> None:
        degraded_id = _seed(
            headline="Degraded thin response headline",
            what_changed=(
                "Model returned a thin response for this headline (no "
                "mechanism). Confidence forced to low and structured "
                "sections cleared."
            ),
        )
        real_id = _seed(headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(degraded_id, ids)
        self.assertEqual(body["total"], 1)


class TestIncludeMockOptIn(_Base):

    def test_include_mock_brings_polluted_rows_back(self) -> None:
        mock_id = _seed(
            headline="Mock headline",
            what_changed="[mock: rate_limited]",
        )
        demo_id = _seed(headline="[DEMO] Showcase")
        real_id = _seed(headline="Real Fed decision")

        body = client.get("/events?include_mock=true").json()
        ids = [e["id"] for e in body["items"]]
        for eid in (mock_id, demo_id, real_id):
            self.assertIn(eid, ids)
        self.assertEqual(body["total"], 3)


class TestDetailByIdAlwaysServes(_Base):

    def test_mock_row_detail_by_id_still_works(self) -> None:
        mock_id = _seed(
            headline="Mock headline",
            what_changed="[mock: overloaded]",
        )
        # Hidden from listing
        list_ids = [e["id"] for e in client.get("/events").json()["items"]]
        self.assertNotIn(mock_id, list_ids)
        # But detail by id still 200s
        resp = client.get(f"/events/{mock_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], mock_id)

    def test_demo_row_detail_by_id_still_works(self) -> None:
        demo_id = _seed(headline="[DEMO] Showcase headline")
        resp = client.get(f"/events/{demo_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], demo_id)


class TestRealRowsUnaffected(_Base):

    def test_real_row_appears_on_default_listing(self) -> None:
        real_id = _seed(headline="Real Fed decision")
        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertEqual(body["total"], 1)


if __name__ == "__main__":
    unittest.main()

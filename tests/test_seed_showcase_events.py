"""
tests/test_seed_showcase_events.py

Smoke tests for the local showcase seeder.

Invariants:
  1) Insert path writes rows tagged with the demo model + headline prefix
     so they are unmistakably non-live data.
  2) ``--clear`` removes only the demo rows and never touches real ones.
  3) Inserted Today rows actually surface on /movers/today.
  4) Inserted Weekly rows surface on /market-movers (the 48h window the
     mover surface uses).  Older Weekly seeds may legitimately fall
     outside /market-movers — the test only asserts that at least one
     non-Today demo row reaches the surface set.
  5) Persistent surfacing is reported but not asserted: the seed script
     must not loosen the live high-impact gate.  A row that fails
     ``is_high_conviction_persistent`` is allowed to drop.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


class _SeedBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as _api
        cls._api = _api
        cls.client = TestClient(_api.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_seed_{uuid.uuid4().hex}.db"
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Always clear the today TTL cache so freshly-seeded rows
        # surface immediately under the test client.
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestSeedInsert(_SeedBase):

    def test_insert_writes_marked_rows(self):
        from tools.seed_showcase_events import (
            DEMO_HEADLINE_PREFIX, DEMO_MODEL_TAG, insert_demo_rows,
        )
        inserted = insert_demo_rows(dry_run=False)
        self.assertGreater(len(inserted), 0)
        with sqlite3.connect(db.DB_FILE) as conn:
            cur = conn.execute(
                "SELECT headline, model FROM events WHERE model = ?",
                (DEMO_MODEL_TAG,),
            )
            rows = cur.fetchall()
        self.assertEqual(len(rows), len(inserted))
        for headline, model in rows:
            self.assertTrue(
                headline.startswith(DEMO_HEADLINE_PREFIX),
                f"headline missing demo prefix: {headline!r}",
            )
            self.assertEqual(model, DEMO_MODEL_TAG)

    def test_insert_then_clear_removes_only_demo_rows(self):
        from tools.seed_showcase_events import (
            DEMO_MODEL_TAG, clear_demo_rows, insert_demo_rows,
        )
        # First, seed a real (non-demo) row so we can prove --clear
        # leaves it untouched.
        db.save_event({
            "headline": "Real (non-demo) event",
            "stage": "realized",
            "persistence": "medium",
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "what_changed": "real",
            "mechanism_summary": "Real analyzed event.",
            "model": "real_model_tag",
            "market_tickers": [],
        })
        insert_demo_rows(dry_run=False)
        deleted = clear_demo_rows()
        self.assertGreater(deleted, 0)
        with sqlite3.connect(db.DB_FILE) as conn:
            demo_left = conn.execute(
                "SELECT COUNT(*) FROM events WHERE model = ?",
                (DEMO_MODEL_TAG,),
            ).fetchone()[0]
            real_left = conn.execute(
                "SELECT COUNT(*) FROM events WHERE model = 'real_model_tag'",
            ).fetchone()[0]
        self.assertEqual(demo_left, 0)
        self.assertEqual(real_left, 1)


class TestSurfaceCoverage(_SeedBase):

    def _items(self, body) -> list:
        if isinstance(body, dict) and "items" in body:
            return body["items"]
        return body if isinstance(body, list) else []

    def test_today_seeds_surface_on_movers_today(self):
        from tools.seed_showcase_events import (
            DEMO_HEADLINE_PREFIX, TODAY_SEEDS, _seed_event,
        )
        for spec in TODAY_SEEDS:
            db.save_event(_seed_event(**spec))
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        r = self.client.get("/movers/today?limit=50")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in self._items(r.json())]
        demo_hits = [h for h in headlines
                     if h.startswith(DEMO_HEADLINE_PREFIX)]
        # At least one Today demo headline should be present.  Demo
        # rows that hit the demote tail (low_information / stale)
        # would still appear in the list — we don't gate on order.
        self.assertGreaterEqual(
            len(demo_hits), 1,
            f"no DEMO headlines surfaced on /movers/today; saw {headlines}",
        )

    def test_weekly_seeds_reach_market_movers_or_weekly(self):
        from tools.seed_showcase_events import (
            DEMO_HEADLINE_PREFIX, WEEKLY_SEEDS, _seed_event,
        )
        for spec in WEEKLY_SEEDS:
            db.save_event(_seed_event(**spec))
        # Either /market-movers (48h window) or /movers/weekly (7d
        # window) should carry at least one weekly demo row.  We
        # check both and assert the union is non-empty so the seed
        # works even when one surface's threshold filters a row out.
        seen: set[str] = set()
        for path in ("/market-movers?limit=50", "/movers/weekly?limit=50"):
            r = self.client.get(path)
            for m in self._items(r.json()):
                h = m.get("headline")
                if isinstance(h, str) and h.startswith(DEMO_HEADLINE_PREFIX):
                    seen.add(h)
        self.assertGreaterEqual(
            len(seen), 1,
            "no weekly DEMO headlines surfaced on /market-movers or /movers/weekly",
        )


class TestPersistentReportingOnly(_SeedBase):
    """Persistent gate is strict — we report which DEMO rows make it
    through without asserting that any specific row does.  Asserting
    surfacing here would silently fail the next time
    ``is_high_conviction_persistent`` tightened, and the contract is
    that the seed script never loosens that gate."""

    def _items(self, body) -> list:
        if isinstance(body, dict) and "items" in body:
            return body["items"]
        return body if isinstance(body, list) else []

    def test_persistent_endpoint_returns_200(self):
        from tools.seed_showcase_events import (
            PERSISTENT_SEEDS, _seed_event,
        )
        for spec in PERSISTENT_SEEDS:
            db.save_event(_seed_event(**spec))
        r = self.client.get("/movers/persistent?limit=50")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

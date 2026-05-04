"""tests/test_events_mock_demo_filter.py

Focused tests for the default archive-pollution suppression on
``GET /events`` and the ``include_mock=true`` opt-in.

Invariants:
  1) Default ``/events`` excludes mock + demo + degraded rows; ``total``
     reflects the post-filter universe (pagination stays consistent).
  2) ``/events?include_mock=true`` brings mock/demo/degraded rows back.
     It does NOT restore expired-low-impact rows — that is a separate
     contract (the expiry filter is independent of mock/demo suppression).
  3) ``/events/{event_id}`` returns hidden rows regardless — detail
     review by id is unaffected for mock/demo/degraded AND for
     expired-low-impact rows.
  4) Real (clean) rows are unaffected on the default path.
  5) Default ``/events`` also excludes analyzed-low-impact rows whose
     registry ``analyzed_at`` is past the configured TTL; ``total``
     reflects the post-expiry universe.

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


class _ExpiredLowImpactBase(_Base):
    """Pin a short TTL so timing-sensitive cases stay deterministic."""

    def setUp(self) -> None:
        super().setUp()
        self._orig_ttl = os.environ.get("HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS")
        os.environ["HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"] = "1"

    def tearDown(self) -> None:
        if self._orig_ttl is None:
            os.environ.pop("HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS", None)
        else:
            os.environ["HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"] = self._orig_ttl
        super().tearDown()

    def _seed_with_registry(
        self,
        *,
        headline: str,
        impact_level: str,
        days_old: int,
    ) -> int:
        from news_sources import _dedup_key
        event_id = _seed(headline=headline, days_old=days_old)
        analyzed_at = (
            datetime.now() - timedelta(days=days_old)
        ).isoformat(timespec="seconds")
        title_key = _dedup_key(headline)
        db.upsert_headline_registry_seen(
            [("Reuters", title_key, 1)], analyzed_at,
        )
        db.update_registry_state(
            title_key=title_key,
            new_state="analyzed",
            event_id=event_id,
            impact_level=impact_level,
            analyzed_at=analyzed_at,
        )
        return event_id


class TestExpiredLowImpactHidden(_ExpiredLowImpactBase):
    """Default ``/events`` suppresses analyzed-low-impact rows past the
    registry TTL.  Pure registry-driven contract — DB rows do not carry
    a ``conviction`` block, so the route relies on the bulk registry
    lookup for both ``analyzed_at`` and ``impact_level``."""

    def test_expired_low_impact_hidden_by_default(self) -> None:
        # 5d > 1d TTL — should be filtered.
        expired_id = self._seed_with_registry(
            headline="Old low-impact print",
            impact_level="low",
            days_old=5,
        )
        real_id = _seed(headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(expired_id, ids)
        # total reflects the post-expiry universe (the "real" row only).
        self.assertEqual(body["total"], 1)

    def test_fresh_low_impact_kept_by_default(self) -> None:
        # 0d < 1d TTL — must NOT be filtered.
        fresh_id = self._seed_with_registry(
            headline="Fresh low-impact print",
            impact_level="low",
            days_old=0,
        )
        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(fresh_id, ids)
        self.assertEqual(body["total"], 1)

    def test_high_impact_never_expires_on_listing(self) -> None:
        # Even when the analyzed_at is well past the TTL, high-impact
        # rows never expire.  Guards against the filter mistakenly
        # gating on age alone.
        high_id = self._seed_with_registry(
            headline="Old high-impact print",
            impact_level="high",
            days_old=5,
        )
        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(high_id, ids)
        self.assertEqual(body["total"], 1)


class TestExpiredLowImpactDetailByIdAlwaysServes(_ExpiredLowImpactBase):
    """``/events/{id}`` keeps serving expired-low-impact rows so detail
    review by id stays usable even after the listing hides them."""

    def test_expired_low_detail_by_id_still_works(self) -> None:
        expired_id = self._seed_with_registry(
            headline="Old low-impact print",
            impact_level="low",
            days_old=5,
        )
        # Hidden from listing.
        list_ids = [e["id"] for e in client.get("/events").json()["items"]]
        self.assertNotIn(expired_id, list_ids)
        # But detail by id still 200s.
        resp = client.get(f"/events/{expired_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], expired_id)


class TestIncludeMockDoesNotRestoreExpired(_ExpiredLowImpactBase):
    """``include_mock=true`` is wired to mock/demo/degraded suppression
    only — it must NOT restore expired-low-impact rows.  Encoding this
    explicitly prevents the two contracts from drifting together."""

    def test_include_mock_does_not_restore_expired_low(self) -> None:
        expired_id = self._seed_with_registry(
            headline="Old low-impact print",
            impact_level="low",
            days_old=5,
        )
        body = client.get("/events?include_mock=true").json()
        ids = [e["id"] for e in body["items"]]
        self.assertNotIn(expired_id, ids)


if __name__ == "__main__":
    unittest.main()

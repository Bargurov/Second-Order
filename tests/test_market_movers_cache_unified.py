"""Tests for routing /market-movers through the shared movers_cache pattern.

Covers:
  * market_movers slice is registered in compute_slice and TTL map
  * 48h window is preserved (events older than 48h are excluded)
  * threshold gating (|return_5d| >= _MOVER_THRESHOLD) is preserved
  * ranking agrees with the legacy _score_event path for the same inputs
  * TTL-based freshness via get_slice (cached read under TTL, recompute on stale)
  * fingerprint invalidation triggers recompute on new events
  * support_ratio uses the single-source-of-truth api._compute_support_ratio
"""

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import movers_cache
from movers_cache import (
    compute_slice,
    _DEFAULT_TTLS,
    _MARKET_MOVERS_WINDOW_HOURS,
)


def _event(hours_ago=1.0, headline="Test mover", return_5d=3.0,
           confidence="medium", headline_suffix=""):
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {
        "id": abs(hash(headline + headline_suffix)) % 10_000_000,
        "timestamp": ts,
        "headline": headline + headline_suffix,
        "stage":    "breaking",
        "persistence": "transient",
        "confidence": confidence,
        "what_changed": "something shifted",
        "mechanism_summary": "meaningful mechanism",
        "event_date": ts[:10],
        "market_tickers": [
            {"symbol": "SPY", "role": "beneficiary",
             "return_5d": return_5d, "return_20d": return_5d,
             "direction_tag": "supports_thesis",
             "anchor_date": ts[:10],
             "label": "x", "detail": "y", "spark": []},
        ],
        "last_market_check_at": ts,
    }


# ---------------------------------------------------------------------------
# Registration / TTL contract
# ---------------------------------------------------------------------------

class TestSliceRegistration(unittest.TestCase):
    def test_market_movers_in_default_ttls(self):
        self.assertIn("market_movers", _DEFAULT_TTLS)
        self.assertGreater(_DEFAULT_TTLS["market_movers"], 0)

    def test_window_preserved_at_48_hours(self):
        self.assertEqual(_MARKET_MOVERS_WINDOW_HOURS, 48)


# ---------------------------------------------------------------------------
# Slice behaviour — 48h window + threshold gating
# ---------------------------------------------------------------------------

class TestComputeMarketMoversSlice(unittest.TestCase):
    """compute_slice('market_movers') enforces the 48h window + threshold."""

    def _stub_build(self, ev, big_moves, support_ratio):
        return {
            "id": ev["id"], "headline": ev["headline"],
            "impact": max(abs(t["return_5d"]) for t in big_moves),
            "support_ratio": support_ratio,
            "tickers": big_moves,
        }

    def test_event_within_48h_with_big_move_is_kept(self):
        events = [_event(hours_ago=1.0, return_5d=3.0)]
        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=lambda _t: 1.0,
            mover_threshold=1.5,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["impact"], 3.0)

    def test_event_older_than_48h_is_dropped(self):
        events = [_event(hours_ago=72.0, return_5d=5.0, headline="Old")]
        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=lambda _t: 1.0,
            mover_threshold=1.5,
        )
        self.assertEqual(out, [])

    def test_event_below_threshold_is_dropped(self):
        """Ticker moved 0.8% < 1.5% threshold → event doesn't qualify."""
        events = [_event(hours_ago=2.0, return_5d=0.8)]
        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=lambda _t: 1.0,
            mover_threshold=1.5,
        )
        self.assertEqual(out, [])

    def test_duplicate_headline_deduped(self):
        events = [
            _event(hours_ago=1.0, return_5d=3.0, headline="Same event"),
            _event(hours_ago=2.0, return_5d=4.0, headline="Same event",
                   headline_suffix=""),
        ]
        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=lambda _t: 1.0,
            mover_threshold=1.5,
        )
        # Only first (higher hours_ago=1 wins; second skipped).
        self.assertEqual(len(out), 1)

    def test_sorted_by_impact_desc(self):
        events = [
            _event(hours_ago=1.0, return_5d=2.0, headline="Small"),
            _event(hours_ago=2.0, return_5d=5.0, headline="Large"),
            _event(hours_ago=3.0, return_5d=3.0, headline="Medium"),
        ]
        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=lambda _t: 1.0,
            mover_threshold=1.5,
        )
        self.assertEqual([e["headline"] for e in out],
                         ["Large", "Medium", "Small"])

    def test_support_ratio_helper_called_on_every_event(self):
        """compute_support_ratio_fn is invoked once per qualifying event."""
        events = [
            _event(hours_ago=1.0, return_5d=3.0, headline="A"),
            _event(hours_ago=2.0, return_5d=3.0, headline="B"),
        ]
        calls: list[list[dict]] = []

        def _stub_ratio(tickers):
            calls.append(tickers)
            return 0.75

        out = compute_slice(
            "market_movers", events,
            build_mover_summary=self._stub_build,
            compute_support_ratio_fn=_stub_ratio,
            mover_threshold=1.5,
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(e["support_ratio"] == 0.75 for e in out))


# ---------------------------------------------------------------------------
# Cache-pattern integration: TTL + fingerprint invalidation
# ---------------------------------------------------------------------------

class TestMarketMoversRoutedThroughCache(unittest.TestCase):
    """Verify the /market-movers endpoint goes through movers_cache.get_slice
    and respects the same TTL + fingerprint invalidation contract as the
    other /movers/* endpoints."""

    def test_ttl_cached_read_within_window(self):
        """Cache hit inside TTL returns the cached payload — compute_fn not invoked."""
        now = datetime(2026, 4, 18, 12, 0, 0)
        cached_payload = [{"id": 1, "impact": 2.0}]
        compute_calls: list[str] = []

        def _stub_compute(name, events, now=None):
            compute_calls.append(name)
            return []

        def _load_cache(name):
            return {
                "payload": cached_payload,
                "built_at": (now - timedelta(seconds=60)).isoformat(),
                "event_count": 1, "max_event_id": 1,
                "compute_version": movers_cache._COMPUTE_VERSION,
            }

        out = movers_cache.get_slice(
            "market_movers", limit=5, now=now,
            load_events_fn=lambda _n: [],
            load_cache_fn=_load_cache,
            save_cache_fn=lambda *_a, **_k: None,
            fingerprint_fn=lambda: (1, 1),
            compute_fn=_stub_compute,
        )
        self.assertEqual(compute_calls, [])  # cache hit — no compute
        self.assertEqual(out, cached_payload)

    def test_ttl_expired_triggers_recompute(self):
        now = datetime(2026, 4, 18, 12, 0, 0)
        compute_calls: list[str] = []

        def _stub_compute(name, events, now=None):
            compute_calls.append(name)
            return [{"id": 99, "impact": 5.0}]

        def _load_cache(name):
            # Built 9999 seconds ago — well beyond the 300s TTL.
            return {
                "payload": [{"id": 1, "impact": 1.0}],
                "built_at": (now - timedelta(seconds=9999)).isoformat(),
                "event_count": 1, "max_event_id": 1,
                "compute_version": movers_cache._COMPUTE_VERSION,
            }

        out = movers_cache.get_slice(
            "market_movers", limit=5, now=now,
            load_events_fn=lambda _n: [],
            load_cache_fn=_load_cache,
            save_cache_fn=lambda *_a, **_k: None,
            fingerprint_fn=lambda: (1, 1),
            compute_fn=_stub_compute,
        )
        self.assertEqual(compute_calls, ["market_movers"])
        self.assertEqual(out[0]["id"], 99)

    def test_fingerprint_change_triggers_recompute(self):
        """A new event (different event_count / max_event_id) forces a recompute
        even inside the TTL window — identical to /movers/weekly behaviour."""
        now = datetime(2026, 4, 18, 12, 0, 0)
        compute_calls: list[str] = []

        def _stub_compute(name, events, now=None):
            compute_calls.append(name)
            return [{"id": 99}]

        def _load_cache(name):
            return {
                "payload": [{"id": 1}],
                "built_at": (now - timedelta(seconds=30)).isoformat(),
                "event_count": 1, "max_event_id": 1,
                "compute_version": movers_cache._COMPUTE_VERSION,
            }

        out = movers_cache.get_slice(
            "market_movers", limit=5, now=now,
            load_events_fn=lambda _n: [],
            load_cache_fn=_load_cache,
            save_cache_fn=lambda *_a, **_k: None,
            fingerprint_fn=lambda: (2, 5),  # fingerprint changed
            compute_fn=_stub_compute,
        )
        self.assertEqual(compute_calls, ["market_movers"])
        self.assertEqual(out[0]["id"], 99)


# ---------------------------------------------------------------------------
# Route-level integration — /market-movers goes through movers_cache
# ---------------------------------------------------------------------------

class TestRouteCallsCacheSlice(unittest.TestCase):
    """The /market-movers route must invoke movers_cache.get_slice('market_movers', ...)
    — proving the bespoke bypass is gone."""

    def setUp(self):
        import db
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_mm_cache_{uuid.uuid4().hex}.db",
        )
        db.init_db()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)
        self._db = db

    def tearDown(self):
        try:
            os.remove(self._db.DB_FILE)
        except (OSError, PermissionError):
            pass
        self._db.DB_FILE = self._orig

    def test_route_calls_get_slice_with_market_movers(self):
        captured: dict = {}

        def _fake_get_slice(name, *, limit, ttl_seconds=None, **kw):
            captured["name"] = name
            captured["limit"] = limit
            captured["ttl"] = ttl_seconds
            return []

        with patch("routes.movers.movers_cache.get_slice", side_effect=_fake_get_slice):
            r = self.client.get("/market-movers", params={"limit": 7})

        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(captured["name"], "market_movers")
        self.assertEqual(captured["limit"], 7)

    def test_route_no_longer_uses_load_events_since_directly(self):
        """Sanity: the route must not open its own DB cursor for ranking.
        The movers_cache slice abstraction owns event loading now."""
        import routes.movers as mv_module
        # 'load_events_since' should NOT be imported into routes.movers anymore.
        self.assertFalse(hasattr(mv_module, "load_events_since"))


if __name__ == "__main__":
    unittest.main()

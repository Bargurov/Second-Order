"""
tests/test_snapshots_endpoint.py

End-to-end tests for the /snapshots API endpoint and the contract that
the frontend BenchmarkSnapshotsStrip relies on.

Covers:
  - Normalized response shape (every snapshot has the same 12 keys)
  - Includes value/change/freshness/source metadata
  - Stale snapshots are returned with stale=true (graceful degradation)
  - Unavailable markets surface as snapshots with error set, not 500
  - Partial availability: some markets fresh, some stale, some unavailable
  - Refresh query parameter triggers a synchronous refresh
  - Never raises on provider failure
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

import api as api_module
import market_check
import market_snapshots
from market_data import YFinanceProvider, get_provider, set_provider
from market_snapshots import (
    SNAPSHOT_MAX_AGE_SECONDS,
    MarketSnapshot,
    get_store,
    refresh_all,
    stop_background_refresh,
)
from market_universe import LIQUID_MARKETS

# Required keys on every snapshot dict.  This is the contract the frontend
# MarketSnapshot interface depends on.
REQUIRED_KEYS = {
    "market", "symbol", "label", "unit", "asset_class", "source",
    "value", "change_1d", "change_5d", "fetched_at", "error", "stale",
}


def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


def _good_df():
    return _make_df([100.0 + i * 0.5 for i in range(30)])


# ---------------------------------------------------------------------------
# Test fixture
# ---------------------------------------------------------------------------

class SnapshotsEndpointBase(unittest.TestCase):
    """Shared setup: ensures background thread is off and store is empty."""

    def setUp(self):
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        self._saved_provider = get_provider()
        set_provider(YFinanceProvider())
        self.client = TestClient(api_module.app)

    def tearDown(self):
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved_provider)


# ---------------------------------------------------------------------------
# Endpoint shape — every snapshot has the required keys
# ---------------------------------------------------------------------------

class TestEndpointShape(SnapshotsEndpointBase):

    def test_returns_list(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_returns_one_per_liquid_market(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        data = response.json()
        markets = [s["market"] for s in data]
        self.assertEqual(set(markets), set(LIQUID_MARKETS))
        self.assertEqual(len(data), 8)

    def test_every_snapshot_has_required_keys(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        data = response.json()
        for snap in data:
            self.assertEqual(
                set(snap.keys()), REQUIRED_KEYS,
                f"Missing keys for {snap.get('market')}: "
                f"{REQUIRED_KEYS - set(snap.keys())}",
            )

    def test_value_change_freshness_present(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        data = response.json()
        for snap in data:
            self.assertIn("value", snap)
            self.assertIsInstance(snap["value"], (int, float))
            self.assertIn("change_5d", snap)
            self.assertIn("fetched_at", snap)
            self.assertIsInstance(snap["fetched_at"], str)
            self.assertIn("source", snap)
            self.assertIn("stale", snap)
            self.assertIsInstance(snap["stale"], bool)

    def test_canonical_order(self):
        """Snapshots come back in canonical liquid-market order."""
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        markets = [s["market"] for s in response.json()]
        self.assertEqual(markets, list(LIQUID_MARKETS))

    def test_source_tag_yfinance(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        for snap in response.json():
            if snap["error"] is None:
                self.assertEqual(snap["source"], "yfinance")


# ---------------------------------------------------------------------------
# Warm-cache preference: requests prefer cached snapshots
# ---------------------------------------------------------------------------

class TestWarmCachePreference(SnapshotsEndpointBase):

    def test_request_without_refresh_returns_warm_data(self):
        """After refresh_all(), GET /snapshots returns warm data without re-fetching."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()

        # Now request without ?refresh — should not call _fetch again
        with patch("market_check._fetch") as mock_fetch:
            response = self.client.get("/snapshots")
            mock_fetch.assert_not_called()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 8)

    def test_empty_store_returns_empty_list(self):
        """When the background thread has not run, the endpoint returns []."""
        response = self.client.get("/snapshots")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_force_refresh_query_param(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        self.assertEqual(len(response.json()), 8)


# ---------------------------------------------------------------------------
# Stale fallback: stale snapshots returned with stale=true
# ---------------------------------------------------------------------------

class TestStaleFallback(SnapshotsEndpointBase):

    def test_stale_snapshot_returned_with_flag(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()

        # Backdate every entry past the freshness window
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )

        response = self.client.get("/snapshots")
        data = response.json()
        self.assertEqual(len(data), 8)
        for snap in data:
            self.assertTrue(snap["stale"], f"{snap['market']} should be stale")
            # Data still present
            self.assertIsNotNone(snap["value"])

    def test_mixed_fresh_and_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        # Backdate only ES
        with store._lock:
            snap, _ts = store._entries["ES"]
            store._entries["ES"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )
        data = self.client.get("/snapshots").json()
        es = next(s for s in data if s["market"] == "ES")
        nq = next(s for s in data if s["market"] == "NQ")
        self.assertTrue(es["stale"])
        self.assertFalse(nq["stale"])


# ---------------------------------------------------------------------------
# Unavailable markets — partial availability
# ---------------------------------------------------------------------------

class TestPartialAvailability(SnapshotsEndpointBase):

    def test_one_market_unavailable_others_fresh(self):
        """When one market fails to fetch, the others should still be returned."""
        call_count = [0]

        def _flaky(symbol):
            call_count[0] += 1
            # Make NQ=F fail; everything else succeeds
            if symbol == "NQ=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            response = self.client.get("/snapshots?refresh=true")

        data = response.json()
        self.assertEqual(len(data), 8)
        nq = next(s for s in data if s["market"] == "NQ")
        es = next(s for s in data if s["market"] == "ES")
        self.assertEqual(nq["error"], "no data")
        self.assertIsNone(nq["value"])
        # Other markets should have values
        self.assertIsNone(es["error"])
        self.assertIsNotNone(es["value"])

    def test_provider_raises_for_one_market(self):
        """A raised exception should be captured as an error snapshot."""
        def _flaky(symbol):
            if symbol == "GC=F":
                raise ConnectionError("network down")
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            response = self.client.get("/snapshots?refresh=true")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 8)
        gc = next(s for s in data if s["market"] == "GC")
        self.assertIn("fetch error", gc["error"] or "")
        self.assertIsNone(gc["value"])

    def test_all_markets_fail_endpoint_still_200(self):
        """Even with every fetch failing, the endpoint must not 500."""
        with patch("market_check._fetch", side_effect=RuntimeError("everything is down")):
            response = self.client.get("/snapshots?refresh=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 8)
        for snap in data:
            self.assertIsNotNone(snap["error"])
            self.assertIsNone(snap["value"])

    def test_partial_availability_count(self):
        """Half the markets succeed, half fail — endpoint returns all 8."""
        def _alternate(symbol):
            # ES=F, RTY=F, GC=F, 2Y SHY → fail; rest → succeed
            if symbol in {"ES=F", "RTY=F", "GC=F"}:
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_alternate):
            response = self.client.get("/snapshots?refresh=true")
        data = response.json()
        usable = [s for s in data if s["value"] is not None]
        unusable = [s for s in data if s["value"] is None]
        self.assertEqual(len(usable) + len(unusable), 8)
        self.assertGreater(len(usable), 0)
        self.assertGreater(len(unusable), 0)


# ---------------------------------------------------------------------------
# Endpoint resilience
# ---------------------------------------------------------------------------

class TestEndpointResilience(SnapshotsEndpointBase):

    def test_endpoint_does_not_raise_on_provider_failure(self):
        with patch("market_check._fetch", side_effect=Exception("kaboom")):
            response = self.client.get("/snapshots?refresh=true")
        self.assertEqual(response.status_code, 200)

    def test_repeated_calls_consistent(self):
        with patch("market_check._fetch", return_value=_good_df()):
            r1 = self.client.get("/snapshots?refresh=true").json()
            r2 = self.client.get("/snapshots").json()
        # Same set of markets across calls
        self.assertEqual(
            sorted([s["market"] for s in r1]),
            sorted([s["market"] for s in r2]),
        )


if __name__ == "__main__":
    unittest.main()

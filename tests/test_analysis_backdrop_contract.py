"""
tests/test_analysis_backdrop_contract.py

Contract tests for the /market-context endpoint as consumed by the
analysis page MarketBackdropStrip component.

The backdrop renders three pieces in one compact strip:
  1. Regime chip from ctx.stress.regime (skipped when "Unknown" or unavailable)
  2. Five key benchmark values: ES, CL, GC, DXY, 10Y (subset of LIQUID_MARKETS)
  3. One "top mover" line from ctx.highlights[0]

These tests lock the contract that:
  - All five backdrop benchmarks must be present in the snapshots payload
  - Stale state must be readable per snapshot
  - Partial availability never crashes the endpoint
  - The shape stays stable so the analysis-view consumer never NPEs
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

import api as api_module
import market_check
from market_data import YFinanceProvider, get_provider, set_provider
from market_snapshots import (
    SNAPSHOT_MAX_AGE_SECONDS,
    get_store,
    refresh_all,
    stop_background_refresh,
)


# The 5 benchmarks the analysis backdrop strip reads.
BACKDROP_MARKETS = ("ES", "CL", "GC", "DXY", "10Y")

# Per-snapshot keys the strip reads on each backdrop entry.
SNAPSHOT_KEYS_USED = {
    "market", "value", "change_5d", "unit", "stale", "error", "fetched_at",
}

# Top-level keys the strip reads on the context object.
CONTEXT_KEYS_USED = {"snapshots", "stress", "highlights", "snapshots_meta", "source"}


def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


def _good_df():
    return _make_df([100.0 + i * 0.5 for i in range(30)])


class _Base(unittest.TestCase):

    def setUp(self):
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        self.client = TestClient(api_module.app)

    def tearDown(self):
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved)


# ---------------------------------------------------------------------------
# Full data — happy path
# ---------------------------------------------------------------------------

class TestBackdropFullContext(_Base):

    def _full(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            return self.client.get("/market-context?highlight_limit=1").json()

    def test_top_level_keys_present(self):
        data = self._full()
        for key in CONTEXT_KEYS_USED:
            self.assertIn(key, data)

    def test_all_backdrop_markets_present_in_snapshots(self):
        data = self._full()
        markets = {s["market"] for s in data["snapshots"]}
        for backdrop_market in BACKDROP_MARKETS:
            self.assertIn(
                backdrop_market, markets,
                f"Backdrop market {backdrop_market} missing from snapshots",
            )

    def test_each_backdrop_snapshot_has_required_keys(self):
        data = self._full()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            for key in SNAPSHOT_KEYS_USED:
                self.assertIn(
                    key, snap,
                    f"{market} missing key {key}",
                )

    def test_full_data_no_backdrop_markets_unavailable(self):
        data = self._full()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            self.assertIsNotNone(snap["value"], f"{market} value should be set")
            self.assertIsNone(snap["error"], f"{market} should have no error")
            self.assertFalse(snap["stale"], f"{market} should be fresh")

    def test_stress_section_has_regime(self):
        data = self._full()
        self.assertIn("regime", data["stress"])
        self.assertTrue(data["stress"].get("available"))

    def test_highlights_at_least_empty_list(self):
        data = self._full()
        self.assertIsInstance(data["highlights"], list)

    def test_snapshots_meta_summed_correctly(self):
        data = self._full()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["fresh"] + meta["stale"] + meta["unavailable"], meta["total"])


# ---------------------------------------------------------------------------
# Partial availability — backdrop subset
# ---------------------------------------------------------------------------

class TestBackdropPartialAvailability(_Base):

    def test_one_backdrop_market_unavailable(self):
        """When CL fails, the backdrop strip can still render the other 4."""
        def _flaky(symbol):
            if symbol == "CL=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            data = self.client.get("/market-context").json()

        by_market = {s["market"]: s for s in data["snapshots"]}
        cl = by_market["CL"]
        self.assertIsNone(cl["value"])
        self.assertIsNotNone(cl["error"])
        # Other backdrop markets still have data
        for market in ("ES", "GC", "DXY", "10Y"):
            self.assertIsNotNone(by_market[market]["value"])

    def test_all_backdrop_markets_unavailable(self):
        """When all 5 backdrop markets fail, the strip should still get a
        valid context (it will hide itself client-side)."""
        def _flaky(symbol):
            if symbol in {"ES=F", "CL=F", "GC=F", "DX-Y.NYB", "^TNX"}:
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIsNone(by_market[market]["value"])
            self.assertIsNotNone(by_market[market]["error"])
        # Stress and highlights still rendered (different fetch path)
        self.assertIn("regime", data["stress"])

    def test_stress_unavailable_strip_still_has_snapshots(self):
        """When stress fails, backdrop falls back to benchmark-only display."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.compute_stress_regime", side_effect=RuntimeError("boom")):
            data = self.client.get("/market-context").json()

        # Stress degraded
        self.assertEqual(data["stress"]["regime"], "Unknown")
        self.assertFalse(data["stress"]["available"])
        # Snapshots intact
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertIsNotNone(by_market[market]["value"])

    def test_highlights_unavailable_strip_still_has_other_sections(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.movers_today", side_effect=RuntimeError("kaboom")):
            data = self.client.get("/market-context").json()

        self.assertEqual(data["highlights"], [])
        # Other sections present
        self.assertIn("regime", data["stress"])
        self.assertEqual(len(data["snapshots"]), 8)

    def test_warm_store_empty_endpoint_still_returns(self):
        """Most realistic dev state: snapshot store empty, other sections work."""
        with patch("market_check._fetch", return_value=_good_df()):
            data = self.client.get("/market-context").json()
        self.assertEqual(data["snapshots"], [])
        # Stress and highlights still computed
        self.assertIn("regime", data["stress"])

    def test_all_sections_fail_endpoint_still_200(self):
        """Worst case: backdrop should hide itself, never crash the page."""
        with patch("market_snapshots.get_all_snapshots", side_effect=RuntimeError("snap")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("stress")), \
             patch("api.movers_today", side_effect=RuntimeError("movers")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["highlights"], [])
        self.assertFalse(data["stress"]["available"])


# ---------------------------------------------------------------------------
# Stale state rendering
# ---------------------------------------------------------------------------

class TestBackdropStaleState(_Base):

    def test_one_backdrop_market_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        # Backdate ES (one of the backdrop markets)
        store = get_store()
        with store._lock:
            snap, _ = store._entries["ES"]
            store._entries["ES"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        es = by_market["ES"]
        self.assertTrue(es["stale"])
        self.assertIsNotNone(es["value"])
        # Other backdrop markets still fresh
        for market in ("CL", "GC", "DXY", "10Y"):
            self.assertFalse(by_market[market]["stale"])

    def test_all_backdrop_markets_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            self.assertTrue(by_market[market]["stale"])
            # Data still present so the strip can dim them visually
            self.assertIsNotNone(by_market[market]["value"])

    def test_stale_count_in_meta(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        # Backdate two of the backdrop markets
        with store._lock:
            for key in ("CL", "GC"):
                snap, _ = store._entries[key]
                store._entries[key] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["stale"], 2)
        self.assertEqual(meta["fresh"], 6)

    def test_freshness_metadata_present_on_each_backdrop_snapshot(self):
        """The strip reads stale + fetched_at to render the inline 'stale' tag."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}
        for market in BACKDROP_MARKETS:
            snap = by_market[market]
            self.assertIn("stale", snap)
            self.assertIn("fetched_at", snap)


# ---------------------------------------------------------------------------
# Mixed real-world state (one of each kind)
# ---------------------------------------------------------------------------

class TestBackdropMixedState(_Base):

    def test_mixed_fresh_stale_unavailable(self):
        """Realistic blend: most fresh, one stale, one unavailable."""
        def _flaky(symbol):
            if symbol == "GC=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
        # Make CL stale
        store = get_store()
        with store._lock:
            snap, _ = store._entries["CL"]
            store._entries["CL"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )

        data = self.client.get("/market-context").json()
        by_market = {s["market"]: s for s in data["snapshots"]}

        gc = by_market["GC"]
        self.assertIsNone(gc["value"])
        self.assertIsNotNone(gc["error"])

        cl = by_market["CL"]
        self.assertTrue(cl["stale"])
        self.assertIsNotNone(cl["value"])

        # ES, DXY, 10Y still fresh
        for market in ("ES", "DXY", "10Y"):
            snap = by_market[market]
            self.assertFalse(snap["stale"])
            self.assertIsNotNone(snap["value"])
            self.assertIsNone(snap["error"])

        meta = data["snapshots_meta"]
        self.assertEqual(meta["unavailable"], 1)
        self.assertEqual(meta["stale"], 1)
        self.assertEqual(meta["fresh"], 6)


if __name__ == "__main__":
    unittest.main()

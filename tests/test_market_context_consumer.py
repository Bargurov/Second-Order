"""
tests/test_market_context_consumer.py

Contract tests for the /market-context endpoint as consumed by the
frontend Market Overview migration.

These tests lock the contract that the new consumer (a single fetch
that distributes data to BenchmarkSnapshotsStrip, UncertaintySection,
and TodayStrip) depends on:

  - Every section the frontend reads must always be present, even when
    the underlying source failed.
  - Stale snapshots must be flagged so the UI can render them quietly.
  - Highlights must be a list of MarketMover-shaped dicts so TodayStrip
    can render them with the same code path it uses for /movers/today.
  - Partial availability never produces a 500 — frontend degrades cleanly.
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
import market_snapshots
from market_data import YFinanceProvider, get_provider, set_provider
from market_snapshots import (
    SNAPSHOT_MAX_AGE_SECONDS,
    get_store,
    refresh_all,
    stop_background_refresh,
)
from market_universe import LIQUID_MARKETS


# Frontend-required keys that must exist on every snapshot.
SNAPSHOT_REQUIRED_KEYS = {
    "market", "symbol", "label", "unit", "asset_class", "source",
    "value", "change_1d", "change_5d", "fetched_at", "error", "stale",
}

# Frontend-required keys at the top level of /market-context.
CONTEXT_REQUIRED_KEYS = {
    "built_at", "source",
    "snapshots", "snapshots_meta",
    "stress",
    "highlights", "highlights_meta",
}

# Frontend reads these from snapshots_meta to size the partial availability footer.
SNAPSHOTS_META_KEYS = {"total", "fresh", "stale", "unavailable"}


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
        self._saved_provider = get_provider()
        set_provider(YFinanceProvider())
        self.client = TestClient(api_module.app)

    def tearDown(self):
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved_provider)


# ---------------------------------------------------------------------------
# Full data — the happy path the frontend renders most of the time
# ---------------------------------------------------------------------------

class TestFullContext(_Base):

    def _full(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            return self.client.get("/market-context?highlight_limit=10").json()

    def test_top_level_keys(self):
        data = self._full()
        self.assertEqual(set(data.keys()), CONTEXT_REQUIRED_KEYS)

    def test_snapshots_array_full(self):
        data = self._full()
        self.assertEqual(len(data["snapshots"]), 8)
        markets = [s["market"] for s in data["snapshots"]]
        self.assertEqual(set(markets), set(LIQUID_MARKETS))

    def test_every_snapshot_has_required_keys(self):
        data = self._full()
        for snap in data["snapshots"]:
            self.assertEqual(
                set(snap.keys()), SNAPSHOT_REQUIRED_KEYS,
                f"Missing keys for {snap.get('market')}",
            )

    def test_snapshots_meta_shape(self):
        data = self._full()
        self.assertEqual(set(data["snapshots_meta"].keys()), SNAPSHOTS_META_KEYS)
        # Counts must add up to total
        meta = data["snapshots_meta"]
        self.assertEqual(meta["fresh"] + meta["stale"] + meta["unavailable"], meta["total"])

    def test_full_data_no_stale_no_unavailable(self):
        data = self._full()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["stale"], 0)
        self.assertEqual(meta["unavailable"], 0)
        self.assertEqual(meta["fresh"], 8)
        for snap in data["snapshots"]:
            self.assertFalse(snap["stale"])
            self.assertIsNone(snap["error"])
            self.assertIsNotNone(snap["value"])

    def test_stress_section_complete(self):
        data = self._full()
        stress = data["stress"]
        self.assertIn("regime", stress)
        self.assertIn("signals", stress)
        self.assertIn("detail", stress)
        self.assertTrue(stress.get("available"))

    def test_highlights_is_list(self):
        data = self._full()
        self.assertIsInstance(data["highlights"], list)
        self.assertIn("count", data["highlights_meta"])
        self.assertEqual(
            data["highlights_meta"]["count"], len(data["highlights"]),
        )

    def test_top_level_metadata_iso_format(self):
        data = self._full()
        self.assertIsInstance(data["built_at"], str)
        self.assertIn("T", data["built_at"])
        self.assertIn(data["source"], {"yfinance", "polygon"})


# ---------------------------------------------------------------------------
# Partial availability — frontend must degrade cleanly per section
# ---------------------------------------------------------------------------

class TestPartialAvailability(_Base):

    def test_some_snapshots_unavailable(self):
        """Half the markets fail; the other half + stress + highlights still render."""
        def _flaky(symbol):
            if symbol in {"NQ=F", "GC=F", "RTY=F"}:
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            data = self.client.get("/market-context").json()

        # Top-level keys still present
        self.assertEqual(set(data.keys()), CONTEXT_REQUIRED_KEYS)
        # Snapshots meta reflects partial state
        meta = data["snapshots_meta"]
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["unavailable"], 3)
        self.assertEqual(meta["fresh"], 5)
        # Every snapshot still has the full key set
        for snap in data["snapshots"]:
            self.assertEqual(set(snap.keys()), SNAPSHOT_REQUIRED_KEYS)

    def test_unavailable_snapshots_have_error_field(self):
        def _flaky(symbol):
            return None if symbol == "ES=F" else _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            data = self.client.get("/market-context").json()

        es = next(s for s in data["snapshots"] if s["market"] == "ES")
        self.assertIsNone(es["value"])
        self.assertIsNotNone(es["error"])

    def test_stress_unavailable_returns_degraded_shape(self):
        """When stress fails, the section must still be there with available=false."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.compute_stress_regime", side_effect=RuntimeError("boom")):
            data = self.client.get("/market-context").json()

        stress = data["stress"]
        self.assertEqual(stress["regime"], "Unknown")
        self.assertFalse(stress["available"])
        # Required nested keys present so frontend doesn't crash on access
        self.assertIn("signals", stress)
        self.assertIn("detail", stress)
        # Other sections unchanged
        self.assertEqual(len(data["snapshots"]), 8)

    def test_highlights_unavailable_returns_empty_list(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.movers_today", side_effect=RuntimeError("kaboom")):
            data = self.client.get("/market-context").json()

        self.assertEqual(data["highlights"], [])
        self.assertEqual(data["highlights_meta"]["count"], 0)
        # Snapshots and stress still present
        self.assertEqual(len(data["snapshots"]), 8)
        self.assertIn("regime", data["stress"])

    def test_all_sections_fail_endpoint_still_200(self):
        """Worst case: every fetch fails.  Endpoint returns 200 with degraded shape."""
        with patch("market_snapshots.get_all_snapshots", side_effect=RuntimeError("snap")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("stress")), \
             patch("api.movers_today", side_effect=RuntimeError("movers")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # All required keys present even when nothing succeeded
        self.assertEqual(set(data.keys()), CONTEXT_REQUIRED_KEYS)
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["snapshots_meta"]["total"], 0)
        self.assertFalse(data["stress"]["available"])
        self.assertEqual(data["highlights"], [])

    def test_snapshots_warm_store_empty_other_sections_still_work(self):
        """When the background refresh hasn't run, snapshots is [] but stress
        and highlights still come back.  This is the expected state in dev
        when MARKET_SNAPSHOTS_ENABLED is unset."""
        with patch("market_check._fetch", return_value=_good_df()):
            data = self.client.get("/market-context").json()
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["snapshots_meta"]["total"], 0)
        # Other sections still populated
        self.assertIn("regime", data["stress"])
        self.assertIsInstance(data["highlights"], list)


# ---------------------------------------------------------------------------
# Stale-state rendering — the UI must be able to mark snapshots as stale
# ---------------------------------------------------------------------------

class TestStaleStateRendering(_Base):

    def test_stale_snapshot_flag_propagated(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        # Backdate every entry
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()

        for snap in data["snapshots"]:
            self.assertTrue(snap["stale"])
            # Data is still present so the UI can render dimmed
            self.assertIsNotNone(snap["value"])
            self.assertIsNotNone(snap["fetched_at"])

    def test_stale_count_in_meta(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        # Backdate two entries
        with store._lock:
            for key in ("ES", "NQ"):
                snap, _ = store._entries[key]
                store._entries[key] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        data = self.client.get("/market-context").json()
        self.assertEqual(data["snapshots_meta"]["stale"], 2)
        self.assertEqual(data["snapshots_meta"]["fresh"], 6)

    def test_mixed_stale_unavailable_fresh(self):
        """Realistic mixed state: some fresh, some stale, some unavailable."""
        def _flaky(symbol):
            if symbol == "GC=F":
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
        # Backdate just NQ
        store = get_store()
        with store._lock:
            snap, _ = store._entries["NQ"]
            store._entries["NQ"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )

        data = self.client.get("/market-context").json()
        meta = data["snapshots_meta"]
        self.assertEqual(meta["unavailable"], 1)  # GC
        self.assertEqual(meta["stale"], 1)        # NQ
        self.assertEqual(meta["fresh"], 6)         # everything else
        self.assertEqual(meta["total"], 8)
        # Sums add up
        self.assertEqual(meta["fresh"] + meta["stale"] + meta["unavailable"], meta["total"])

    def test_freshness_metadata_present_on_each_snapshot(self):
        """The frontend reads fetched_at + stale + source per snapshot to
        decide rendering style — all three must be present even on errors."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        data = self.client.get("/market-context").json()
        for snap in data["snapshots"]:
            self.assertIn("fetched_at", snap)
            self.assertIn("stale", snap)
            self.assertIn("source", snap)


if __name__ == "__main__":
    unittest.main()

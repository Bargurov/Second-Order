"""
tests/test_market_snapshots.py

Tests for the background snapshot refresh layer.

Covers:
  - Single-market refresh produces a populated snapshot
  - refresh_all() covers every liquid market
  - SnapshotStore freshness flag
  - Stale snapshots are still returned (graceful degradation)
  - refresh_all() warms _TICKER_CACHE so subsequent _fetch calls hit cache
  - Provider failure stores an error snapshot, does not raise
  - Background thread starts/stops cleanly
  - /snapshots endpoint shape
"""

import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, ".")

import db
import market_check
import market_data
import market_snapshots
import price_cache


# ---------------------------------------------------------------------------
# Module-level SQLite isolation
# ---------------------------------------------------------------------------
# Every test in this module uses a fake/mock provider and asserts on the
# number of provider calls.  The persistent SQLite price cache would
# otherwise pollute assertions across runs, so we point db.DB_FILE at a
# fresh temp file for the lifetime of this module and wipe the price
# cache table in every class setUp.

_ORIGINAL_DB_FILE: str | None = None
_TEST_DB_FILE: str | None = None


def setUpModule() -> None:
    global _ORIGINAL_DB_FILE, _TEST_DB_FILE
    _ORIGINAL_DB_FILE = db.DB_FILE
    _TEST_DB_FILE = os.path.join(
        tempfile.gettempdir(), f"test_snapshots_pc_{uuid.uuid4().hex}.db",
    )
    db.DB_FILE = _TEST_DB_FILE
    price_cache._reset_table_ready_for_tests()


def tearDownModule() -> None:
    global _ORIGINAL_DB_FILE, _TEST_DB_FILE
    if _ORIGINAL_DB_FILE is not None:
        db.DB_FILE = _ORIGINAL_DB_FILE
    price_cache._reset_table_ready_for_tests()
    if _TEST_DB_FILE and os.path.exists(_TEST_DB_FILE):
        try:
            os.remove(_TEST_DB_FILE)
        except PermissionError:
            pass
from market_data import (
    PolygonProvider,
    YFinanceProvider,
    get_provider,
    set_provider,
)
from market_snapshots import (
    DEFAULT_REFRESH_INTERVAL,
    SNAPSHOT_MAX_AGE_SECONDS,
    MarketSnapshot,
    SnapshotStore,
    get_all_snapshots,
    get_snapshot,
    get_store,
    is_running,
    refresh_all,
    refresh_market,
    start_background_refresh,
    stop_background_refresh,
)
from market_universe import LIQUID_MARKETS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


def _good_df():
    """A DataFrame with enough rows for 5d returns to compute."""
    return _make_df([100.0 + i * 0.5 for i in range(30)])


# ---------------------------------------------------------------------------
# SnapshotStore unit tests
# ---------------------------------------------------------------------------

class TestSnapshotStore(unittest.TestCase):

    def setUp(self):
        self.store = SnapshotStore()

    def _make_snap(self, market: str, value: float = 100.0) -> MarketSnapshot:
        return MarketSnapshot(
            market=market,
            symbol=f"{market}-SYM",
            label=f"{market} label",
            unit="idx",
            asset_class="equity_index",
            source="test",
            value=value,
            change_1d=0.5,
            change_5d=2.0,
            fetched_at="2026-04-07T12:00:00+00:00",
        )

    def test_update_and_get(self):
        snap = self._make_snap("ES")
        self.store.update(snap)
        result = self.store.get("ES")
        self.assertIsNotNone(result)
        self.assertEqual(result.market, "ES")
        self.assertEqual(result.value, 100.0)
        self.assertFalse(result.stale)

    def test_get_case_insensitive(self):
        self.store.update(self._make_snap("ES"))
        self.assertIsNotNone(self.store.get("es"))
        self.assertIsNotNone(self.store.get("Es"))

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.store.get("UNKNOWN"))

    def test_get_empty_string_returns_none(self):
        self.assertIsNone(self.store.get(""))

    def test_all_returns_all_entries(self):
        self.store.update(self._make_snap("ES"))
        self.store.update(self._make_snap("CL"))
        result = self.store.all()
        markets = [s.market for s in result]
        self.assertIn("ES", markets)
        self.assertIn("CL", markets)

    def test_all_sorted_by_canonical_order(self):
        # Insert out of order
        for m in ("10Y", "ES", "CL", "DXY"):
            self.store.update(self._make_snap(m))
        result = self.store.all()
        markets = [s.market for s in result]
        # Canonical order: ES, NQ, RTY, CL, GC, DXY, 2Y, 10Y
        self.assertEqual(markets, ["ES", "CL", "DXY", "10Y"])

    def test_clear(self):
        self.store.update(self._make_snap("ES"))
        self.assertEqual(len(self.store), 1)
        self.store.clear()
        self.assertEqual(len(self.store), 0)

    def test_stale_flag_set_after_max_age(self):
        """A snapshot older than SNAPSHOT_MAX_AGE_SECONDS should report stale."""
        self.store.update(self._make_snap("ES"))
        # Backdate the entry
        with self.store._lock:
            snap, _mono = self.store._entries["ES"]
            self.store._entries["ES"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )
        result = self.store.get("ES")
        self.assertTrue(result.stale)
        # Data is still returned
        self.assertEqual(result.value, 100.0)

    def test_fresh_snapshot_not_stale(self):
        self.store.update(self._make_snap("ES"))
        result = self.store.get("ES")
        self.assertFalse(result.stale)

    def test_update_replaces_existing(self):
        self.store.update(self._make_snap("ES", value=100.0))
        self.store.update(self._make_snap("ES", value=200.0))
        self.assertEqual(self.store.get("ES").value, 200.0)
        self.assertEqual(len(self.store), 1)


# ---------------------------------------------------------------------------
# refresh_market — single market refresh
# ---------------------------------------------------------------------------

class TestRefreshMarket(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        get_store().clear()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()

    def test_known_market_populates_snapshot(self):
        with patch("market_check._fetch", return_value=_good_df()):
            snap = refresh_market("ES")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.market, "ES")
        self.assertEqual(snap.symbol, "ES=F")
        self.assertIsNotNone(snap.value)
        self.assertIsNotNone(snap.change_5d)
        self.assertIsNotNone(snap.fetched_at)
        self.assertIsNone(snap.error)

    def test_unknown_market_returns_none(self):
        snap = refresh_market("UNKNOWN")
        self.assertIsNone(snap)

    def test_provider_returns_none_stored_as_error(self):
        with patch("market_check._fetch", return_value=None):
            snap = refresh_market("CL")
        self.assertIsNotNone(snap)
        self.assertIsNone(snap.value)
        self.assertEqual(snap.error, "no data")
        # Snapshot is in the store with the error
        stored = get_snapshot("CL")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.error, "no data")

    def test_provider_raises_stored_as_error(self):
        with patch("market_check._fetch", side_effect=ConnectionError("network down")):
            snap = refresh_market("GC")
        self.assertIsNotNone(snap)
        self.assertIsNone(snap.value)
        self.assertIn("fetch error", snap.error or "")

    def test_short_data_stored_as_error(self):
        """A DataFrame with fewer than 2 rows should produce an error snapshot."""
        short = pd.DataFrame(
            {"Close": [100.0], "Volume": [1e6]},
            index=pd.date_range("2026-03-01", periods=1, freq="B"),
        )
        with patch("market_check._fetch", return_value=short):
            snap = refresh_market("DXY")
        self.assertEqual(snap.error, "no data")

    def test_change_5d_computed(self):
        df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        with patch("market_check._fetch", return_value=df):
            snap = refresh_market("ES")
        self.assertIsNotNone(snap.change_5d)
        self.assertAlmostEqual(snap.change_5d, 5.0, places=1)

    def test_change_1d_computed(self):
        df = _make_df([100.0, 102.0])
        with patch("market_check._fetch", return_value=df):
            snap = refresh_market("ES")
        self.assertIsNotNone(snap.change_1d)
        self.assertAlmostEqual(snap.change_1d, 2.0, places=1)


# ---------------------------------------------------------------------------
# refresh_all — covers every liquid market
# ---------------------------------------------------------------------------

class TestRefreshAll(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        get_store().clear()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()

    def test_refreshes_all_liquid_markets(self):
        with patch("market_check._fetch", return_value=_good_df()):
            results = refresh_all()
        self.assertEqual(len(results), len(LIQUID_MARKETS))
        markets = {s.market for s in results}
        self.assertEqual(markets, set(LIQUID_MARKETS))

    def test_one_failure_does_not_block_others(self):
        """If one market raises, the rest should still refresh."""
        call_count = [0]

        def _spy(symbol):
            call_count[0] += 1
            if call_count[0] == 2:  # second call fails
                raise RuntimeError("simulated failure")
            return _good_df()

        with patch("market_check._fetch", side_effect=_spy):
            results = refresh_all()
        self.assertEqual(len(results), len(LIQUID_MARKETS))
        # At least one error snapshot
        errors = [s for s in results if s.error is not None]
        successes = [s for s in results if s.error is None and s.value is not None]
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(successes), len(LIQUID_MARKETS) - 1)

    def test_store_populated_after_refresh_all(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        all_snaps = get_all_snapshots()
        self.assertEqual(len(all_snaps), len(LIQUID_MARKETS))


# ---------------------------------------------------------------------------
# Warm-cache contract: refresh populates _TICKER_CACHE
# ---------------------------------------------------------------------------

class TestWarmCacheContract(unittest.TestCase):
    """After refresh_all(), subsequent _fetch() calls for the same symbols
    must hit the cache and not call the provider again."""

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        get_store().clear()
        market_check._cache_clear()
        price_cache._clear_table_for_tests()

    def tearDown(self):
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()
        price_cache._clear_table_for_tests()

    def test_refresh_warms_ticker_cache(self):
        """After refresh_all, _TICKER_CACHE should hold entries for liquid market symbols."""
        df = _good_df()
        with patch("market_check._fetch", wraps=lambda s: (
            market_check._cache_set(f"fetch:{s.upper()}", df) or df
        )):
            refresh_all()
        # Cache should now contain entries
        self.assertGreater(market_check._cache_len(), 0)

    def test_subsequent_fetch_hits_cache(self):
        """After warming, calling _fetch with a warmed symbol should not invoke the underlying provider."""
        # Use a fake provider so we can count calls
        from unittest.mock import MagicMock
        df = _good_df()
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.return_value = df
        set_provider(fake)
        try:
            # Refresh once — this should cache "ES=F" via _fetch
            refresh_all()
            calls_after_refresh = fake.fetch_daily.call_count
            self.assertGreater(calls_after_refresh, 0)
            # Now call _fetch again for one of the warmed symbols
            result = market_check._fetch("ES=F")
            self.assertIsNotNone(result)
            # The provider should NOT have been called again
            self.assertEqual(fake.fetch_daily.call_count, calls_after_refresh)
        finally:
            set_provider(YFinanceProvider())

    def test_macro_snapshot_hits_warm_cache(self):
        """After refresh_all warms the cache, macro_snapshot should not re-fetch
        liquid market tickers (DX-Y.NYB, ^TNX, CL=F under YFinance)."""
        from unittest.mock import MagicMock
        df = _good_df()
        fake = MagicMock(spec=YFinanceProvider)
        fake.fetch_daily.return_value = df
        set_provider(fake)
        try:
            refresh_all()
            calls_after_refresh = fake.fetch_daily.call_count
            # Now call macro_snapshot — it should reuse the warm cache for
            # the liquid markets it now references via the resolver.
            market_check.macro_snapshot()
            calls_after_macro = fake.fetch_daily.call_count
            # macro_snapshot has 5 instruments; 3 are liquid markets that
            # were just warmed (DXY, 10Y, CL).  Only 2 (^VIX, BZ=F) should
            # be cold-fetched.  So at most 2 new provider calls.
            new_calls = calls_after_macro - calls_after_refresh
            self.assertLessEqual(new_calls, 2,
                                 f"Expected ≤2 new calls after warm refresh, got {new_calls}")
        finally:
            set_provider(YFinanceProvider())


# ---------------------------------------------------------------------------
# Stale-cache fallback
# ---------------------------------------------------------------------------

class TestStaleFallback(unittest.TestCase):
    """A stale snapshot should still be returned with stale=True."""

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        get_store().clear()

    def tearDown(self):
        set_provider(self._saved)
        get_store().clear()

    def test_stale_snapshot_still_returned(self):
        store = get_store()
        snap = MarketSnapshot(
            market="ES", symbol="ES=F", label="S&P 500 (ES)",
            unit="idx", asset_class="equity_index", source="yfinance",
            value=4500.0, change_1d=0.5, change_5d=1.5,
            fetched_at="2026-01-01T00:00:00+00:00",
        )
        store.update(snap)
        # Backdate
        with store._lock:
            stored, _ = store._entries["ES"]
            store._entries["ES"] = (
                stored, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 10,
            )
        result = get_snapshot("ES")
        self.assertIsNotNone(result)
        self.assertTrue(result.stale)
        self.assertEqual(result.value, 4500.0)  # data still there

    def test_no_snapshot_returns_none(self):
        get_store().clear()
        self.assertIsNone(get_snapshot("ES"))


# ---------------------------------------------------------------------------
# Background thread lifecycle
# ---------------------------------------------------------------------------

class TestBackgroundThread(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        set_provider(YFinanceProvider())
        get_store().clear()
        market_check._cache_clear()

    def tearDown(self):
        stop_background_refresh()
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()

    def test_start_and_stop(self):
        """Thread starts, runs at least once, then stops cleanly."""
        with patch("market_check._fetch", return_value=_good_df()):
            started = start_background_refresh(interval=1)
            self.assertTrue(started)
            self.assertTrue(is_running())
            # Give the initial refresh a moment to complete
            time.sleep(0.3)
            self.assertGreater(len(get_store()), 0)
            stop_background_refresh()
            self.assertFalse(is_running())

    def test_double_start_returns_false(self):
        with patch("market_check._fetch", return_value=_good_df()):
            self.assertTrue(start_background_refresh(interval=10))
            self.assertFalse(start_background_refresh(interval=10))
            stop_background_refresh()

    def test_stop_when_not_running_is_noop(self):
        # Should not raise
        stop_background_refresh()
        self.assertFalse(is_running())

    def test_thread_does_not_block_test_exit(self):
        """The thread is daemon=True so process exit isn't blocked."""
        with patch("market_check._fetch", return_value=_good_df()):
            start_background_refresh(interval=10)
        # Find the thread by name
        names = [t.name for t in threading.enumerate()]
        self.assertIn("snapshot-refresh", names)
        for t in threading.enumerate():
            if t.name == "snapshot-refresh":
                self.assertTrue(t.daemon)
                break
        stop_background_refresh()


# ---------------------------------------------------------------------------
# /snapshots API endpoint
# ---------------------------------------------------------------------------

class TestSnapshotsEndpoint(unittest.TestCase):

    def setUp(self):
        # Avoid starting the background thread during tests
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        # Import api lazily so the lifespan check sees current env
        from fastapi.testclient import TestClient
        import api
        self.client = TestClient(api.app)
        self._saved = get_provider()
        set_provider(YFinanceProvider())

    def tearDown(self):
        stop_background_refresh()
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()

    def test_empty_store_returns_empty_list(self):
        response = self.client.get("/snapshots")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_after_refresh_returns_all_markets(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        response = self.client.get("/snapshots")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), len(LIQUID_MARKETS))

    def test_force_refresh_query_param(self):
        """?refresh=true should populate the store synchronously."""
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), len(LIQUID_MARKETS))

    def test_response_shape(self):
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/snapshots?refresh=true")
        data = response.json()
        sample = data[0]
        for key in ("market", "symbol", "label", "unit", "asset_class",
                    "source", "value", "change_1d", "change_5d",
                    "fetched_at", "error", "stale"):
            self.assertIn(key, sample)


# ---------------------------------------------------------------------------
# Provider source tagging
# ---------------------------------------------------------------------------

class TestProviderSourceTag(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()
        get_store().clear()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._saved)
        get_store().clear()
        market_check._cache_clear()

    def test_yfinance_source(self):
        set_provider(YFinanceProvider())
        with patch("market_check._fetch", return_value=_good_df()):
            snap = refresh_market("ES")
        self.assertEqual(snap.source, "yfinance")

    def test_polygon_source(self):
        set_provider(PolygonProvider(api_key="test"))
        with patch("market_check._fetch", return_value=_good_df()):
            snap = refresh_market("ES")
        self.assertEqual(snap.source, "polygon")


if __name__ == "__main__":
    unittest.main()

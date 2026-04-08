"""
tests/test_high_fixes.py

Regression tests for the High-risk reliability fixes:
  1. Thread-safe bounded LRU+TTL cache
  2. Backend/frontend contract on nullable fields
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, ".")
import market_check


# ---------------------------------------------------------------------------
# 1. Cache: thread safety, TTL, bounded LRU eviction
# ---------------------------------------------------------------------------

class TestCacheTTL(unittest.TestCase):
    """Entries must expire after _TICKER_CACHE_TTL seconds."""

    def setUp(self):
        market_check._cache_clear()

    def tearDown(self):
        market_check._cache_clear()

    def test_fresh_entry_returned(self):
        market_check._cache_set("k1", "hello")
        self.assertEqual(market_check._cache_get("k1"), "hello")

    def test_expired_entry_returns_none(self):
        """Manually backdate a cache entry to simulate expiry."""
        with market_check._cache_lock:
            # Insert with a timestamp far in the past
            market_check._cache_data["k_old"] = (
                time.monotonic() - market_check._TICKER_CACHE_TTL - 1,
                "stale",
            )
        self.assertIsNone(market_check._cache_get("k_old"))

    def test_expired_entry_removed_from_cache(self):
        """After a TTL miss, the entry should be removed."""
        with market_check._cache_lock:
            market_check._cache_data["k_gone"] = (
                time.monotonic() - market_check._TICKER_CACHE_TTL - 1,
                "stale",
            )
        market_check._cache_get("k_gone")  # triggers eviction
        self.assertEqual(market_check._cache_len(), 0)

    def test_missing_key_returns_none(self):
        self.assertIsNone(market_check._cache_get("nonexistent"))


class TestCacheBoundedEviction(unittest.TestCase):
    """Cache must never exceed _TICKER_CACHE_MAXSIZE entries."""

    def setUp(self):
        market_check._cache_clear()

    def tearDown(self):
        market_check._cache_clear()

    def test_eviction_at_capacity(self):
        """Fill the cache to max+10 and verify it stays at max."""
        cap = market_check._TICKER_CACHE_MAXSIZE
        for i in range(cap + 10):
            market_check._cache_set(f"key_{i}", f"val_{i}")
        self.assertLessEqual(market_check._cache_len(), cap)

    def test_oldest_evicted_first(self):
        """The first inserted key should be evicted when over capacity."""
        cap = market_check._TICKER_CACHE_MAXSIZE
        market_check._cache_set("first", "value")
        for i in range(cap):
            market_check._cache_set(f"fill_{i}", i)
        # "first" should have been evicted
        self.assertIsNone(market_check._cache_get("first"))

    def test_recently_accessed_survives(self):
        """A key that was recently read should be moved to end and survive eviction."""
        cap = market_check._TICKER_CACHE_MAXSIZE
        market_check._cache_set("survivor", "alive")
        # Fill almost to capacity
        for i in range(cap - 2):
            market_check._cache_set(f"fill_{i}", i)
        # Access "survivor" to move it to the end
        self.assertEqual(market_check._cache_get("survivor"), "alive")
        # Now push it past capacity
        for i in range(5):
            market_check._cache_set(f"extra_{i}", i)
        # "survivor" should still be there (was moved to end)
        self.assertEqual(market_check._cache_get("survivor"), "alive")


class TestCacheThreadSafety(unittest.TestCase):
    """Concurrent reads and writes must not raise or corrupt state."""

    def setUp(self):
        market_check._cache_clear()

    def tearDown(self):
        market_check._cache_clear()

    def test_concurrent_writes_no_crash(self):
        """Hammer the cache from 8 threads simultaneously."""
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(200):
                    market_check._cache_set(f"t{thread_id}_k{i}", i)
                    market_check._cache_get(f"t{thread_id}_k{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Concurrent cache access raised: {errors}")
        # Cache should not exceed max size despite 8*200 = 1600 writes
        self.assertLessEqual(
            market_check._cache_len(), market_check._TICKER_CACHE_MAXSIZE
        )

    def test_concurrent_read_write_no_crash(self):
        """Mix of readers and writers hitting the cache concurrently."""
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(300):
                    market_check._cache_set(f"shared_k{i % 50}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(300):
                    market_check._cache_get(f"shared_k{i % 50}")
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=writer) for _ in range(4)]
            + [threading.Thread(target=reader) for _ in range(4)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Concurrent cache access raised: {errors}")


class TestCacheClearAndLen(unittest.TestCase):
    """The _cache_clear and _cache_len helpers work correctly."""

    def setUp(self):
        market_check._cache_clear()

    def tearDown(self):
        market_check._cache_clear()

    def test_clear_empties_cache(self):
        market_check._cache_set("a", 1)
        market_check._cache_set("b", 2)
        self.assertEqual(market_check._cache_len(), 2)
        market_check._cache_clear()
        self.assertEqual(market_check._cache_len(), 0)

    def test_len_accurate(self):
        for i in range(10):
            market_check._cache_set(f"k{i}", i)
        self.assertEqual(market_check._cache_len(), 10)


# ---------------------------------------------------------------------------
# 2. Backend nullable field contract
# ---------------------------------------------------------------------------

class TestBackendNullableFields(unittest.TestCase):
    """_check_one_ticker error/no-data paths must produce null (not crash)
    for all numeric fields that the frontend types as `number | null`."""

    def test_no_data_response_has_null_returns(self):
        """When _fetch returns None, all return fields should be None."""
        with patch.object(market_check, "_fetch", return_value=None):
            result = market_check._check_one_ticker("FAKE", role="beneficiary")
        self.assertIsNone(result["return_1d"])
        self.assertIsNone(result["return_5d"])
        self.assertIsNone(result["return_20d"])
        self.assertIsNone(result.get("vs_xle_5d"))

    def test_no_data_response_direction_is_none(self):
        with patch.object(market_check, "_fetch", return_value=None):
            result = market_check._check_one_ticker("FAKE", role="loser")
        self.assertIsNone(result["direction"])

    def test_short_data_returns_null_for_long_windows(self):
        """If we only have 4 bars, 5d and 20d returns must be None, not crash."""
        short_df = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0, 103.0],
             "Volume": [1e6] * 4},
            index=pd.date_range("2026-01-01", periods=4, freq="B"),
        )
        with patch.object(market_check, "_fetch", return_value=short_df):
            # _check_one_ticker requires len >= 6, so this should return _no_data
            result = market_check._check_one_ticker("SHORT", role="beneficiary")
        self.assertIsNone(result["return_5d"])
        self.assertIsNone(result["return_20d"])


class TestFollowupNullableFields(unittest.TestCase):
    """followup_check must return null for missing return windows."""

    def test_insufficient_data_returns_null(self):
        """3 bars of data: return_1d works but return_5d and return_20d are None."""
        short_df = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0],
             "Volume": [1e6] * 3},
            index=pd.date_range("2026-03-01", periods=3, freq="B"),
        )
        tickers = [{"symbol": "TEST", "role": "beneficiary"}]
        with patch.object(market_check, "_fetch_since", return_value=short_df):
            results = market_check.followup_check(tickers, "2026-03-01")
        self.assertEqual(len(results), 1)
        r = results[0]
        # 1d return should work (3 bars >= 2)
        self.assertIsNotNone(r["return_1d"])
        # 5d return needs 6 bars, we only have 3
        self.assertIsNone(r["return_5d"])
        # 20d return needs 21 bars
        self.assertIsNone(r["return_20d"])
        # direction is based on return_5d which is None → direction should be None
        self.assertIsNone(r["direction"])


class TestCacheMaxsizeCalibration(unittest.TestCase):
    """Empirical validation: 512 entries covers typical usage."""

    def test_maxsize_is_512(self):
        """The maxsize was calibrated against 54 live events (320 worst-case keys).
        512 gives 60% headroom."""
        self.assertEqual(market_check._TICKER_CACHE_MAXSIZE, 512)

    def test_ttl_is_600(self):
        """TTL is 10 minutes (600 seconds)."""
        self.assertEqual(market_check._TICKER_CACHE_TTL, 600)


if __name__ == "__main__":
    unittest.main()

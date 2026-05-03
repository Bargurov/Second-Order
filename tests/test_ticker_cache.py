"""
tests/test_ticker_cache.py

Focused tests for the bounded, lock-protected ticker cache in market_check.

Three scenarios:
  1) Cache hit returns the stored value without re-fetching
  2) Stale entries expire after TTL and are not returned
  3) Cache size does not grow beyond _TICKER_CACHE_MAXSIZE
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check
from market_check import (
    _cache_get,
    _cache_set,
    _cache_clear,
    _cache_len,
    _TICKER_CACHE_TTL,
    _TICKER_CACHE_MAXSIZE,
)


class TestCacheHit(unittest.TestCase):
    """Cache hit must return the stored value without re-fetching."""

    def setUp(self):
        _cache_clear()

    def test_cache_hit_returns_stored_value(self):
        sentinel = object()
        _cache_set("AAPL:full:2025-01-01", sentinel)
        result = _cache_get("AAPL:full:2025-01-01")
        self.assertIs(result, sentinel)

    def test_cache_miss_returns_none(self):
        result = _cache_get("NONEXISTENT:key:here")
        self.assertIsNone(result)

    def test_cache_hit_prevents_fetch(self):
        """A cached key returned by _cache_get must not reach the provider."""
        import pandas as pd
        import numpy as np

        dates = pd.bdate_range(end="2025-01-10", periods=20)
        df = pd.DataFrame({
            "Open": np.ones(20) * 100,
            "High": np.ones(20) * 101,
            "Low":  np.ones(20) * 99,
            "Close": np.ones(20) * 100,
            "Volume": np.ones(20) * 1_000_000,
        }, index=dates)

        call_count = 0

        def fake_provider(ticker, **kwargs):
            nonlocal call_count
            call_count += 1
            return df

        # Patch the underlying SQLite price cache so we can count provider calls
        with patch("price_cache.fetch_daily_cached", side_effect=fake_provider):
            # First call — hits provider, populates in-memory cache
            result1 = market_check._fetch("AAPL")
            self.assertEqual(call_count, 1)
            # Second call — should hit in-memory cache, provider not called again
            result2 = market_check._fetch("AAPL")
            self.assertEqual(call_count, 1,
                             "Cache hit should prevent a second provider call")
            self.assertIs(result1, result2)

    def test_lru_ordering_preserved(self):
        """Accessing a key moves it to the most-recent position."""
        _cache_set("key_A", "A")
        _cache_set("key_B", "B")
        # Access A — makes it MRU
        _cache_get("key_A")
        # Fill cache to just under maxsize to force oldest eviction
        for i in range(_TICKER_CACHE_MAXSIZE - 1):
            _cache_set(f"filler_{i}", i)
        # key_B was LRU before the fillers; it should have been evicted
        # key_A was MRU when fillers started; it should survive
        self.assertIsNotNone(_cache_get("key_A"))


# ---------------------------------------------------------------------------
# 2) Stale entries expire
# ---------------------------------------------------------------------------

class TestCacheExpiry(unittest.TestCase):
    """Entries older than TTL must not be returned."""

    def setUp(self):
        _cache_clear()

    def test_fresh_entry_returned(self):
        _cache_set("MSFT:full:2025-01-01", "fresh")
        self.assertEqual(_cache_get("MSFT:full:2025-01-01"), "fresh")

    def test_expired_entry_returns_none(self):
        """Simulate TTL expiry by back-dating the timestamp."""
        key = "EXPIRED:full:2025-01-01"
        stale_ts = market_check._time.monotonic() - (_TICKER_CACHE_TTL + 1)
        with market_check._cache_lock:
            market_check._cache_data[key] = (stale_ts, "old_value")

        result = _cache_get(key)
        self.assertIsNone(result)

    def test_expired_entry_removed_from_dict(self):
        """A TTL-expired get must also remove the entry from the dict."""
        key = "REMOVE:full:2025-01-01"
        stale_ts = market_check._time.monotonic() - (_TICKER_CACHE_TTL + 1)
        with market_check._cache_lock:
            market_check._cache_data[key] = (stale_ts, "gone")

        _cache_get(key)  # triggers removal
        with market_check._cache_lock:
            self.assertNotIn(key, market_check._cache_data)

    def test_two_entries_different_ages(self):
        """Fresh entry survives; expired sibling is evicted on access."""
        stale_ts = market_check._time.monotonic() - (_TICKER_CACHE_TTL + 10)
        fresh_val = "still_good"
        _cache_set("FRESH:k", fresh_val)
        with market_check._cache_lock:
            market_check._cache_data["STALE:k"] = (stale_ts, "dead")

        self.assertIsNone(_cache_get("STALE:k"))
        self.assertEqual(_cache_get("FRESH:k"), fresh_val)


# ---------------------------------------------------------------------------
# 3) Cache size does not grow without bound
# ---------------------------------------------------------------------------

class TestCacheBoundedSize(unittest.TestCase):
    """Inserting more than _TICKER_CACHE_MAXSIZE entries must not exceed the cap."""

    def setUp(self):
        _cache_clear()

    def test_size_never_exceeds_maxsize(self):
        overflow = _TICKER_CACHE_MAXSIZE + 50
        for i in range(overflow):
            _cache_set(f"ticker_{i}:full:2025-01-01", i)
        self.assertLessEqual(_cache_len(), _TICKER_CACHE_MAXSIZE)

    def test_oldest_evicted_first(self):
        """After filling past capacity, the earliest-inserted key is gone."""
        first_key = "first_ever:full:2025-01-01"
        _cache_set(first_key, "first")
        for i in range(_TICKER_CACHE_MAXSIZE):
            _cache_set(f"filler_{i}:full:2025-01-01", i)
        # first_key should have been evicted (LRU = oldest = first in)
        self.assertIsNone(_cache_get(first_key))

    def test_exact_maxsize_not_evicted(self):
        """Filling to exactly maxsize leaves all entries intact."""
        for i in range(_TICKER_CACHE_MAXSIZE):
            _cache_set(f"exact_{i}", i)
        self.assertEqual(_cache_len(), _TICKER_CACHE_MAXSIZE)
        # No eviction should have happened
        self.assertIsNotNone(_cache_get("exact_0"))

    def test_concurrent_writes_do_not_exceed_maxsize(self):
        """Concurrent _cache_set calls must not race past the size cap."""
        import threading

        errors = []

        def writer(start):
            try:
                for i in range(start, start + 100):
                    _cache_set(f"concurrent_{i}", i)
                    size = _cache_len()
                    if size > _TICKER_CACHE_MAXSIZE:
                        errors.append(f"size={size} exceeded maxsize={_TICKER_CACHE_MAXSIZE}")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=writer, args=(t * 200,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Concurrent write errors: {errors}")
        self.assertLessEqual(_cache_len(), _TICKER_CACHE_MAXSIZE)


if __name__ == "__main__":
    unittest.main()

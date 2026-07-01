"""
tests/test_get_provider_boundary.py

K1B boundary contract: GET market routes must never trigger provider-backed
market-data fetches or price-cache writes — regardless of provider selection
(MARKET_DATA_PROVIDER) or key presence, and regardless of cold/stale cache.

Covers:
  - GET /market-context on a cold store: no provider fetch, no cache write,
    explicit not_refreshed/unavailable metadata instead of a hidden refresh.
  - GET /snapshots (with and without ?refresh=true): no provider fetch.
  - GET /ticker/{sym}/chart and /ticker/{sym}/info: no provider fetch, and
    the ticker-info TTL cache is not poisoned by a blocked empty result.
  - GET /stress, /rates-context, /macro: no provider fetch.
  - market_snapshots.refresh_all() outside a GET handler remains capable of
    provider-backed refresh (the warmer/admin surface is not broken).
  - market_data.no_provider_fetch() guard semantics and the cache-only
    behavior of price_cache.fetch_daily_cached under the guard.

All tests are offline: the provider is an in-process recording fake, the
price-cache DB layer is patched out, and the news cache is stubbed empty.
"""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

import api as api_module
import market_check
import market_data
import price_cache
from market_data import get_provider, set_provider
from market_snapshots import get_store, refresh_all, stop_background_refresh

EMPTY_DF = pd.DataFrame(columns=["Close", "Volume"])


def _cached_df():
    n = 30
    return pd.DataFrame(
        {"Close": [100.0 + i * 0.5 for i in range(n)], "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-02", periods=n, freq="B"),
    )


class RecordingProvider:
    """Stands in for any billed/live provider; records every fetch attempt."""

    def __init__(self):
        self.fetch_daily_calls: list[str] = []
        self.fetch_info_calls: list[str] = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None,
                    auto_adjust=True):
        self.fetch_daily_calls.append(ticker)
        return None

    def fetch_info(self, ticker):
        self.fetch_info_calls.append(ticker)
        return {}


class GetBoundaryBase(unittest.TestCase):
    """Cold store, empty price cache, recording provider, offline news."""

    def setUp(self):
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        self._saved_provider = get_provider()
        self.provider = RecordingProvider()
        set_provider(self.provider)

        self.write_calls: list[tuple] = []

        def _recording_write_rows(*args, **kwargs):
            self.write_calls.append(args)
            return 0

        self._patches = [
            patch.object(price_cache, "_read_range",
                         lambda *a, **k: EMPTY_DF.copy()),
            patch.object(price_cache, "_write_rows", _recording_write_rows),
            patch.object(price_cache, "_ensure_table", lambda: True),
            patch.object(api_module, "_get_news_cached",
                         lambda: {"clusters": []}),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(api_module.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved_provider)

    def assert_no_provider_activity(self, label: str):
        self.assertEqual(
            self.provider.fetch_daily_calls, [],
            f"{label}: provider fetch_daily reached from a GET handler",
        )
        self.assertEqual(
            self.provider.fetch_info_calls, [],
            f"{label}: provider fetch_info reached from a GET handler",
        )
        self.assertEqual(
            self.write_calls, [],
            f"{label}: price-cache write attempted during a GET handler",
        )


class TestMarketContextGetBoundary(GetBoundaryBase):

    def test_market_context_get_does_not_fetch_provider(self):
        resp = self.client.get("/market-context")
        self.assertEqual(resp.status_code, 200)
        self.assert_no_provider_activity("GET /market-context")

    def test_market_context_cold_store_is_explicitly_unavailable(self):
        resp = self.client.get("/market-context")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        rows = body.get("snapshots") or []
        self.assertTrue(rows, "snapshots strip must keep its shaped rows")
        for row in rows:
            self.assertEqual(
                row.get("error"), "not_refreshed",
                "cold-store GET must surface explicit not_refreshed rows, "
                "not silently refreshed or blank ones",
            )
        meta = body.get("snapshots_meta") or {}
        self.assertEqual(meta.get("unavailable"), meta.get("total"))


class TestSnapshotsGetBoundary(GetBoundaryBase):

    def test_snapshots_get_does_not_fetch_provider(self):
        resp = self.client.get("/snapshots")
        self.assertEqual(resp.status_code, 200)
        self.assert_no_provider_activity("GET /snapshots")

    def test_snapshots_refresh_param_does_not_fetch_provider(self):
        resp = self.client.get("/snapshots?refresh=true")
        self.assertEqual(resp.status_code, 200)
        self.assert_no_provider_activity("GET /snapshots?refresh=true")


class TestTickerGetBoundary(GetBoundaryBase):

    def test_ticker_chart_get_does_not_fetch_provider(self):
        resp = self.client.get("/ticker/AAPL/chart?event_date=2026-04-15")
        self.assertEqual(resp.status_code, 200)
        self.assert_no_provider_activity("GET /ticker/AAPL/chart")

    def test_ticker_info_get_does_not_fetch_provider(self):
        resp = self.client.get("/ticker/AAPL/info")
        self.assertEqual(resp.status_code, 200)
        self.assert_no_provider_activity("GET /ticker/AAPL/info")

    def test_ticker_info_blocked_result_is_not_cached(self):
        resp = self.client.get("/ticker/AAPL/info")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(
            market_check._cache_get("info:AAPL"),
            "a blocked/empty fetch_info result must not poison the "
            "10-minute ticker-info cache",
        )


class TestOtherMarketGetBoundary(GetBoundaryBase):

    def test_stress_rates_macro_gets_do_not_fetch_provider(self):
        for path in ("/stress", "/rates-context", "/macro"):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200, path)
        self.assert_no_provider_activity("GET /stress|/rates-context|/macro")


class TestRefreshRemainsCapableOutsideGet(GetBoundaryBase):

    def test_refresh_all_outside_get_still_reaches_provider(self):
        refresh_all()
        self.assertGreater(
            len(self.provider.fetch_daily_calls), 0,
            "refresh_all() outside a GET handler must remain capable of "
            "provider-backed refresh (warmer/admin surface)",
        )


class TestNoProviderFetchGuard(GetBoundaryBase):

    def test_get_provider_returns_blocking_proxy_inside_guard(self):
        with market_data.no_provider_fetch():
            proxied = get_provider()
            self.assertIsNone(
                proxied.fetch_daily("AAPL", period="3mo"),
                "fetch_daily must be a no-op inside the guard",
            )
            self.assertEqual(proxied.fetch_info("AAPL"), {})
        self.assertEqual(self.provider.fetch_daily_calls, [])
        self.assertEqual(self.provider.fetch_info_calls, [])
        self.assertIs(get_provider(), self.provider,
                      "outside the guard the real provider is returned")

    def test_fetch_daily_cached_serves_cache_only_under_guard(self):
        df = _cached_df()
        with patch.object(price_cache, "_read_range", lambda *a, **k: df):
            with market_data.no_provider_fetch():
                out = price_cache.fetch_daily_cached("AAPL", period="3mo")
        self.assertIsNotNone(out)
        self.assertEqual(len(out), len(df))
        self.assertEqual(self.provider.fetch_daily_calls, [])
        self.assertEqual(self.write_calls, [])

    def test_fetch_daily_cached_returns_none_on_empty_cache_under_guard(self):
        with market_data.no_provider_fetch():
            out = price_cache.fetch_daily_cached("AAPL", period="3mo")
        self.assertIsNone(out)
        self.assertEqual(self.provider.fetch_daily_calls, [])
        self.assertEqual(self.write_calls, [])


if __name__ == "__main__":
    unittest.main()

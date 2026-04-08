"""
tests/test_polygon_provider.py

Tests for the PolygonProvider adapter and env-based provider selection.

Covers:
  - Provider selection from MARKET_DATA_PROVIDER / POLYGON_API_KEY
  - Missing API key falls back to yfinance
  - Unknown provider name falls back to yfinance
  - PolygonProvider.fetch_daily happy path (mocked HTTP)
  - PolygonProvider.fetch_daily graceful failures (HTTPError, URLError, JSON parse)
  - PolygonProvider.fetch_info happy path and failures
  - period→date range conversion
  - Construction validation (empty key)
"""

import json
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

sys.path.insert(0, ".")

import market_data
from market_data import (
    MarketDataProvider,
    YFinanceProvider,
    PolygonProvider,
    _build_default_provider,
    reload_provider_from_env,
    get_provider,
    set_provider,
)


# ---------------------------------------------------------------------------
# Helper to fake urlopen() responses
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(payload):
    """Return a urlopen replacement that yields the given JSON payload."""
    def _opener(req, timeout=None):
        return _FakeResponse(payload)
    return _opener


# ---------------------------------------------------------------------------
# Provider selection from env
# ---------------------------------------------------------------------------

class TestProviderSelection(unittest.TestCase):
    """The active provider should be chosen from MARKET_DATA_PROVIDER."""

    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in ("MARKET_DATA_PROVIDER", "POLYGON_API_KEY")
        }
        self._saved_provider = get_provider()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        set_provider(self._saved_provider)

    def _set_env(self, **kwargs):
        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_is_yfinance(self):
        self._set_env(MARKET_DATA_PROVIDER=None, POLYGON_API_KEY=None)
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_explicit_yfinance(self):
        self._set_env(MARKET_DATA_PROVIDER="yfinance", POLYGON_API_KEY=None)
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_polygon_with_key(self):
        self._set_env(MARKET_DATA_PROVIDER="polygon", POLYGON_API_KEY="test_key_xyz")
        provider = _build_default_provider()
        self.assertIsInstance(provider, PolygonProvider)

    def test_polygon_missing_key_falls_back(self):
        """Polygon requested but no key → fall back to YFinance, do not crash."""
        self._set_env(MARKET_DATA_PROVIDER="polygon", POLYGON_API_KEY=None)
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_polygon_empty_key_falls_back(self):
        """Empty string key is treated the same as missing."""
        self._set_env(MARKET_DATA_PROVIDER="polygon", POLYGON_API_KEY="")
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_polygon_whitespace_key_falls_back(self):
        self._set_env(MARKET_DATA_PROVIDER="polygon", POLYGON_API_KEY="   ")
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_unknown_provider_name_falls_back(self):
        self._set_env(MARKET_DATA_PROVIDER="bloomberg", POLYGON_API_KEY=None)
        provider = _build_default_provider()
        self.assertIsInstance(provider, YFinanceProvider)

    def test_case_insensitive(self):
        self._set_env(MARKET_DATA_PROVIDER="POLYGON", POLYGON_API_KEY="abc")
        provider = _build_default_provider()
        self.assertIsInstance(provider, PolygonProvider)

    def test_reload_from_env(self):
        """reload_provider_from_env should update the singleton."""
        self._set_env(MARKET_DATA_PROVIDER="polygon", POLYGON_API_KEY="test_key")
        provider = reload_provider_from_env()
        self.assertIsInstance(provider, PolygonProvider)
        self.assertIsInstance(get_provider(), PolygonProvider)

        self._set_env(MARKET_DATA_PROVIDER="yfinance", POLYGON_API_KEY=None)
        provider = reload_provider_from_env()
        self.assertIsInstance(provider, YFinanceProvider)


# ---------------------------------------------------------------------------
# PolygonProvider construction
# ---------------------------------------------------------------------------

class TestPolygonProviderInit(unittest.TestCase):

    def test_requires_api_key(self):
        with self.assertRaises(ValueError):
            PolygonProvider(api_key="")

    def test_satisfies_protocol(self):
        provider = PolygonProvider(api_key="test")
        self.assertIsInstance(provider, MarketDataProvider)


# ---------------------------------------------------------------------------
# PolygonProvider.fetch_daily — happy path
# ---------------------------------------------------------------------------

class TestPolygonFetchDailyHappy(unittest.TestCase):
    """Verify the Polygon aggregates response is correctly parsed."""

    def _payload(self, n_bars=5):
        # Polygon row shape: {t: ms epoch, o, h, l, c, v, vw, n}
        base_ms = 1_741_046_400_000  # 2026-03-04 00:00:00 UTC
        results = []
        for i in range(n_bars):
            results.append({
                "t": base_ms + i * 86_400_000,
                "o": 100.0 + i,
                "h": 101.0 + i,
                "l": 99.0 + i,
                "c": 100.5 + i,
                "v": 1_000_000 + i * 10_000,
                "vw": 100.3 + i,
                "n": 5000,
            })
        return {"status": "OK", "resultsCount": n_bars, "results": results}

    def test_period_mode(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen(self._payload(5))):
            df = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 5)
        self.assertIn("Close", df.columns)
        self.assertIn("Volume", df.columns)
        self.assertAlmostEqual(float(df["Close"].iloc[0]), 100.5)
        self.assertAlmostEqual(float(df["Close"].iloc[-1]), 104.5)

    def test_start_mode(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen(self._payload(3))):
            df = provider.fetch_daily("AAPL", start="2026-03-01")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 3)

    def test_start_and_end(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen(self._payload(2))):
            df = provider.fetch_daily("AAPL", start="2026-03-01", end="2026-03-15")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)

    def test_auto_adjust_param_in_url(self):
        provider = PolygonProvider(api_key="test")
        captured = {}
        def _capture(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse(self._payload(1))
        with patch("market_data.urlopen", side_effect=_capture):
            provider.fetch_daily("AAPL", period="3mo", auto_adjust=True)
        self.assertIn("adjusted=true", captured["url"])

        captured.clear()
        with patch("market_data.urlopen", side_effect=_capture):
            provider.fetch_daily("AAPL", period="3mo", auto_adjust=False)
        self.assertIn("adjusted=false", captured["url"])

    def test_api_key_in_url(self):
        provider = PolygonProvider(api_key="MY_SECRET")
        captured = {}
        def _capture(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse(self._payload(1))
        with patch("market_data.urlopen", side_effect=_capture):
            provider.fetch_daily("AAPL", period="3mo")
        self.assertIn("apiKey=MY_SECRET", captured["url"])

    def test_no_period_or_start_raises(self):
        provider = PolygonProvider(api_key="test")
        with self.assertRaises(ValueError):
            provider.fetch_daily("AAPL")


# ---------------------------------------------------------------------------
# PolygonProvider.fetch_daily — graceful failures
# ---------------------------------------------------------------------------

class TestPolygonFetchDailyFailures(unittest.TestCase):
    """All failures must return None, never raise."""

    def test_http_error_returns_none(self):
        provider = PolygonProvider(api_key="test")
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=429, msg="Too Many", hdrs={}, fp=None)
        with patch("market_data.urlopen", side_effect=_raise):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_url_error_returns_none(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=URLError("network down")):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_unauthorized_returns_none(self):
        provider = PolygonProvider(api_key="bad")
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=401, msg="Unauth", hdrs={}, fp=None)
        with patch("market_data.urlopen", side_effect=_raise):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        """Polygon returning malformed JSON must not crash the app."""
        provider = PolygonProvider(api_key="test")
        class _BadResp:
            def read(self): return b"not json {"
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with patch("market_data.urlopen", return_value=_BadResp()):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_empty_results_returns_none(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen({"status": "OK", "results": []})):
            result = provider.fetch_daily("ZZZ", period="3mo")
        self.assertIsNone(result)

    def test_missing_results_key_returns_none(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen({"status": "OK"})):
            result = provider.fetch_daily("ZZZ", period="3mo")
        self.assertIsNone(result)

    def test_bad_date_input_returns_none(self):
        provider = PolygonProvider(api_key="test")
        result = provider.fetch_daily("AAPL", start="not-a-date")
        self.assertIsNone(result)

    def test_unexpected_exception_returns_none(self):
        """Any other exception type should also be caught."""
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=RuntimeError("kaboom")):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# PolygonProvider.fetch_info
# ---------------------------------------------------------------------------

class TestPolygonFetchInfo(unittest.TestCase):

    def test_happy_path(self):
        provider = PolygonProvider(api_key="test")
        payload = {
            "status": "OK",
            "results": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "market_cap": 3_000_000_000_000,
                "sic_description": "Electronic Computers",
                "type": "CS",
            },
        }
        with patch("market_data.urlopen", side_effect=_fake_urlopen(payload)):
            result = provider.fetch_info("aapl")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertEqual(result["market_cap"], 3_000_000_000_000)
        self.assertEqual(result["sector"], "Electronic Computers")
        self.assertEqual(result["industry"], "CS")
        self.assertIsNone(result["avg_volume"])  # Polygon doesn't expose this

    def test_http_error_returns_fallback(self):
        provider = PolygonProvider(api_key="test")
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=404, msg="Not Found", hdrs={}, fp=None)
        with patch("market_data.urlopen", side_effect=_raise):
            result = provider.fetch_info("ZZZ")
        self.assertEqual(result["symbol"], "ZZZ")
        self.assertIsNone(result["name"])
        self.assertIsNone(result["sector"])
        self.assertIsNone(result["market_cap"])

    def test_empty_results_returns_fallback(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen({"status": "OK", "results": {}})):
            result = provider.fetch_info("ZZZ")
        self.assertEqual(result["symbol"], "ZZZ")
        self.assertIsNone(result["name"])

    def test_missing_results_key(self):
        provider = PolygonProvider(api_key="test")
        with patch("market_data.urlopen", side_effect=_fake_urlopen({"status": "OK"})):
            result = provider.fetch_info("ZZZ")
        self.assertEqual(result["symbol"], "ZZZ")
        self.assertIsNone(result["name"])


# ---------------------------------------------------------------------------
# Date range resolution
# ---------------------------------------------------------------------------

class TestPolygonDateRange(unittest.TestCase):

    def test_period_3mo(self):
        start, end = PolygonProvider._resolve_range("3mo", None, None)
        from datetime import date, timedelta
        self.assertEqual(end, date.today().isoformat())
        # 93 days back
        expected_start = (date.today() - timedelta(days=93)).isoformat()
        self.assertEqual(start, expected_start)

    def test_period_1y(self):
        start, end = PolygonProvider._resolve_range("1y", None, None)
        from datetime import date, timedelta
        expected_start = (date.today() - timedelta(days=365)).isoformat()
        self.assertEqual(start, expected_start)

    def test_unknown_period_defaults_to_3mo(self):
        start, end = PolygonProvider._resolve_range("xyz", None, None)
        from datetime import date, timedelta
        expected_start = (date.today() - timedelta(days=93)).isoformat()
        self.assertEqual(start, expected_start)

    def test_explicit_start_no_end(self):
        start, end = PolygonProvider._resolve_range(None, "2026-01-15", None)
        from datetime import date
        self.assertEqual(start, "2026-01-15")
        self.assertEqual(end, date.today().isoformat())

    def test_explicit_start_and_end(self):
        start, end = PolygonProvider._resolve_range(None, "2026-01-15", "2026-02-15")
        self.assertEqual(start, "2026-01-15")
        self.assertEqual(end, "2026-02-15")

    def test_no_period_or_start_raises(self):
        with self.assertRaises(ValueError):
            PolygonProvider._resolve_range(None, None, None)


# ---------------------------------------------------------------------------
# End-to-end: missing key fallback does not break market_check
# ---------------------------------------------------------------------------

class TestEndToEndFallback(unittest.TestCase):
    """When polygon is requested without a key, market_check should still work."""

    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in ("MARKET_DATA_PROVIDER", "POLYGON_API_KEY")
        }
        self._saved_provider = get_provider()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        set_provider(self._saved_provider)

    def test_fallback_does_not_raise(self):
        os.environ["MARKET_DATA_PROVIDER"] = "polygon"
        os.environ.pop("POLYGON_API_KEY", None)
        provider = reload_provider_from_env()
        # Should be YFinanceProvider, not crash
        self.assertIsInstance(provider, YFinanceProvider)
        # Confirm it's also the active one
        self.assertIsInstance(get_provider(), YFinanceProvider)


if __name__ == "__main__":
    unittest.main()

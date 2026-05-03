"""
tests/test_provider_hardening.py

Focused tests for provider hardening additions:

  1. PolygonProvider._get() retry on transient network failures
       - retries up to _POLYGON_MAX_RETRIES attempts on URLError / Exception
       - stops immediately on HTTPError (authoritative)
       - stops immediately on parse errors (not transient)
       - succeeds on the second attempt when the first fails transiently
       - bounded: never exceeds _POLYGON_MAX_RETRIES calls regardless of error count

  2. PolygonProvider.fetch_daily() unsupported-symbol guard
       - =F futures tickers (CL=F, BZ=F, GC=F) return None without an HTTP call
       - =X forex tickers (EURUSD=X) return None without an HTTP call
       - ^VIX / ^TNX caret guard still works (regression)
       - normal equity tickers (AAPL, SPY) still pass through to HTTP

  3. YFinanceProvider.fetch_daily() timeout
       - timeout=_YFINANCE_TIMEOUT is passed to yf.download()
"""

import sys
import unittest
from unittest.mock import patch, MagicMock, call
from urllib.error import HTTPError, URLError

import pandas as pd

sys.path.insert(0, ".")

from market_data import (
    PolygonProvider,
    YFinanceProvider,
    _POLYGON_MAX_RETRIES,
    _POLYGON_RETRY_BACKOFF_BASE,
    _YFINANCE_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n=5):
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": [100.0] * n, "Volume": [1_000_000.0] * n}, index=dates)


class _FakeResponse:
    """Minimal context-manager response for urlopen mocks."""
    def __init__(self, payload: dict):
        import json
        self._body = json.dumps(payload).encode("utf-8")

    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _good_payload(n=2):
    import time as t
    base_ms = 1_700_000_000_000
    return {
        "status": "OK",
        "results": [
            {"t": base_ms + i * 86_400_000, "c": 100.0 + i, "v": 1_000_000.0}
            for i in range(n)
        ],
    }


# ---------------------------------------------------------------------------
# 1) Retry on transient network failures
# ---------------------------------------------------------------------------

class TestPolygonRetry(unittest.TestCase):
    """_get() must retry transient failures and stay within _POLYGON_MAX_RETRIES."""

    def setUp(self):
        self.provider = PolygonProvider(api_key="test")

    def _fetch(self):
        return self.provider.fetch_daily("AAPL", period="3mo")

    def test_retries_exhaust_on_persistent_url_error(self):
        """Persistent URLError → urlopen called exactly _POLYGON_MAX_RETRIES times."""
        with patch("market_data.urlopen", side_effect=URLError("flaky network")) as mock_open, \
             patch("market_data._time.sleep"):
            result = self._fetch()
        self.assertIsNone(result)
        self.assertEqual(mock_open.call_count, _POLYGON_MAX_RETRIES)

    def test_retry_bounded_on_generic_exception(self):
        """Persistent RuntimeError is treated as transient — still bounded."""
        with patch("market_data.urlopen", side_effect=RuntimeError("kaboom")) as mock_open, \
             patch("market_data._time.sleep"):
            result = self._fetch()
        self.assertIsNone(result)
        self.assertEqual(mock_open.call_count, _POLYGON_MAX_RETRIES)

    def test_no_retry_on_http_error(self):
        """HTTPError is authoritative — urlopen called exactly once, no sleep."""
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=429, msg="Too Many", hdrs={}, fp=None)
        with patch("market_data.urlopen", side_effect=_raise) as mock_open, \
             patch("market_data._time.sleep") as mock_sleep:
            result = self._fetch()
        self.assertIsNone(result)
        self.assertEqual(mock_open.call_count, 1)
        mock_sleep.assert_not_called()

    def test_no_retry_on_http_401(self):
        """HTTP 401 Unauthorized — not a transient failure, no retry."""
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=401, msg="Unauth", hdrs={}, fp=None)
        with patch("market_data.urlopen", side_effect=_raise) as mock_open, \
             patch("market_data._time.sleep") as mock_sleep:
            result = self._fetch()
        self.assertIsNone(result)
        self.assertEqual(mock_open.call_count, 1)
        mock_sleep.assert_not_called()

    def test_no_retry_on_parse_error(self):
        """Malformed JSON is not transient — urlopen called once, no sleep."""
        class _BadResp:
            def read(self): return b"not json {"
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with patch("market_data.urlopen", return_value=_BadResp()) as mock_open, \
             patch("market_data._time.sleep") as mock_sleep:
            result = self._fetch()
        self.assertIsNone(result)
        self.assertEqual(mock_open.call_count, 1)
        mock_sleep.assert_not_called()

    def test_succeeds_on_second_attempt(self):
        """First attempt: URLError. Second: good response. Returns data."""
        calls = [0]
        def _flaky(req, timeout=None):
            calls[0] += 1
            if calls[0] == 1:
                raise URLError("transient blip")
            return _FakeResponse(_good_payload(3))
        with patch("market_data.urlopen", side_effect=_flaky), \
             patch("market_data._time.sleep"):
            result = self.provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        self.assertEqual(calls[0], 2)  # first failed, second succeeded

    def test_backoff_sleep_called_between_retries(self):
        """sleep() must be called _POLYGON_MAX_RETRIES - 1 times with increasing delays."""
        with patch("market_data.urlopen", side_effect=URLError("down")), \
             patch("market_data._time.sleep") as mock_sleep:
            self._fetch()
        expected_sleeps = [
            _POLYGON_RETRY_BACKOFF_BASE * (2 ** i)
            for i in range(_POLYGON_MAX_RETRIES - 1)
        ]
        actual_sleeps = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(actual_sleeps), _POLYGON_MAX_RETRIES - 1)
        for expected, actual in zip(expected_sleeps, actual_sleeps):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_healthy_path_no_sleep(self):
        """Successful first attempt: sleep must never be called."""
        with patch("market_data.urlopen", return_value=_FakeResponse(_good_payload(2))), \
             patch("market_data._time.sleep") as mock_sleep:
            result = self._fetch()
        self.assertIsNotNone(result)
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 2) Unsupported-symbol guard
# ---------------------------------------------------------------------------

class TestPolygonUnsupportedSymbols(unittest.TestCase):
    """=F futures, =X forex, and ^index symbols must be rejected before any HTTP call."""

    def setUp(self):
        self.provider = PolygonProvider(api_key="test")

    def _fetch(self, ticker):
        return self.provider.fetch_daily(ticker, period="3mo")

    # --- futures (=F) --------------------------------------------------------

    def test_wti_futures_returns_none(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("CL=F")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_brent_futures_returns_none(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("BZ=F")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_gold_futures_returns_none(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("GC=F")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_futures_case_insensitive(self):
        """=f lowercase is also blocked."""
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("cl=f")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    # --- forex (=X) ----------------------------------------------------------

    def test_eurusd_forex_returns_none(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("EURUSD=X")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_gbpusd_forex_returns_none(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("GBPUSD=X")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_forex_case_insensitive(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("eurusd=x")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    # --- caret-prefixed indices (regression) ---------------------------------

    def test_caret_vix_still_blocked(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("^VIX")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    def test_caret_tnx_still_blocked(self):
        with patch("market_data.urlopen") as mock_open:
            result = self._fetch("^TNX")
        self.assertIsNone(result)
        mock_open.assert_not_called()

    # --- normal equities pass through ----------------------------------------

    def test_equity_ticker_reaches_http(self):
        """AAPL must NOT be blocked by any guard."""
        with patch("market_data.urlopen", return_value=_FakeResponse(_good_payload(2))) as mock_open:
            result = self._fetch("AAPL")
        self.assertIsNotNone(result)
        mock_open.assert_called_once()

    def test_spy_etf_reaches_http(self):
        with patch("market_data.urlopen", return_value=_FakeResponse(_good_payload(2))) as mock_open:
            result = self._fetch("SPY")
        self.assertIsNotNone(result)
        mock_open.assert_called_once()

    def test_dotted_ticker_reaches_http(self):
        """BRK.B contains a dot but is not a futures/forex ticker — must pass."""
        with patch("market_data.urlopen", return_value=_FakeResponse(_good_payload(1))) as mock_open:
            result = self._fetch("BRK.B")
        mock_open.assert_called_once()

    def test_ticker_with_f_not_blocked(self):
        """'F' (Ford Motor) ends in 'F' but not '=F' — must not be blocked."""
        with patch("market_data.urlopen", return_value=_FakeResponse(_good_payload(2))) as mock_open:
            result = self._fetch("F")
        mock_open.assert_called_once()


# ---------------------------------------------------------------------------
# 3) YFinanceProvider timeout
# ---------------------------------------------------------------------------

class TestYFinanceTimeout(unittest.TestCase):
    """timeout=_YFINANCE_TIMEOUT must be forwarded to yf.download()."""

    def _make_fake_yf(self, df=None):
        fake_yf = MagicMock()
        fake_yf.download.return_value = df if df is not None else _make_df()
        return fake_yf

    def test_timeout_passed_to_period_download(self):
        fake_yf = self._make_fake_yf()
        provider = YFinanceProvider()
        with patch("market_data._PROVIDER_FETCH_LOCK"), \
             patch.dict("sys.modules", {"yfinance": fake_yf}):
            provider.fetch_daily("AAPL", period="3mo")
        call_kwargs = fake_yf.download.call_args[1]
        self.assertIn("timeout", call_kwargs)
        self.assertEqual(call_kwargs["timeout"], _YFINANCE_TIMEOUT)

    def test_timeout_passed_to_start_download(self):
        fake_yf = self._make_fake_yf()
        provider = YFinanceProvider()
        with patch("market_data._PROVIDER_FETCH_LOCK"), \
             patch.dict("sys.modules", {"yfinance": fake_yf}):
            provider.fetch_daily("AAPL", start="2026-01-01")
        call_kwargs = fake_yf.download.call_args[1]
        self.assertIn("timeout", call_kwargs)
        self.assertEqual(call_kwargs["timeout"], _YFINANCE_TIMEOUT)

    def test_timeout_value_is_positive(self):
        """Sanity check: the constant itself is a sensible positive number."""
        self.assertGreater(_YFINANCE_TIMEOUT, 0)
        self.assertLessEqual(_YFINANCE_TIMEOUT, 120)

    def test_download_exception_returns_none(self):
        """A timeout manifesting as an exception must be caught, not raised."""
        fake_yf = MagicMock()
        fake_yf.download.side_effect = Exception("timed out")
        provider = YFinanceProvider()
        with patch.dict("sys.modules", {"yfinance": fake_yf}):
            result = provider.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

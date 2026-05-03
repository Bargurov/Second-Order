"""
tests/test_polygon_index_guard.py

Focused tests for the PolygonProvider caret-prefixed index ticker guard.

  1) ^VIX, ^TNX, ^GSPC → returns None without making an HTTP call.
  2) Normal tickers (AAPL, BRK.B) → proceed to the HTTP path as before.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data import PolygonProvider


class TestPolygonIndexGuard(unittest.TestCase):
    """Caret-prefixed index tickers are rejected before any HTTP call."""

    def setUp(self):
        self.provider = PolygonProvider(api_key="test-key")

    def test_caret_vix_returns_none(self):
        result = self.provider.fetch_daily("^VIX", period="3mo")
        self.assertIsNone(result)

    def test_caret_tnx_returns_none(self):
        result = self.provider.fetch_daily("^TNX", start="2026-01-01")
        self.assertIsNone(result)

    def test_caret_gspc_returns_none(self):
        result = self.provider.fetch_daily("^GSPC", period="1mo")
        self.assertIsNone(result)

    def test_caret_ticker_does_not_call_http(self):
        with patch.object(self.provider, "_get") as mock_get:
            self.provider.fetch_daily("^VIX", period="3mo")
            mock_get.assert_not_called()

    def test_caret_ticker_logs_warning(self):
        with patch("market_data._log") as mock_log:
            self.provider.fetch_daily("^VIX", period="3mo")
            mock_log.warning.assert_called_once()
            msg = mock_log.warning.call_args[0][0]
            self.assertIn("caret-prefixed", msg)


class TestPolygonNormalTickerRegression(unittest.TestCase):
    """Non-index tickers proceed to the HTTP path normally."""

    def setUp(self):
        self.provider = PolygonProvider(api_key="test-key")

    def test_normal_ticker_calls_http(self):
        with patch.object(self.provider, "_get", return_value=None) as mock_get:
            self.provider.fetch_daily("AAPL", period="3mo")
            mock_get.assert_called_once()
            path_arg = mock_get.call_args[0][0]
            self.assertIn("AAPL", path_arg)

    def test_dotted_ticker_calls_http(self):
        """BRK.B-style class shares must not be blocked."""
        with patch.object(self.provider, "_get", return_value=None) as mock_get:
            self.provider.fetch_daily("BRK.B", period="3mo")
            mock_get.assert_called_once()
            path_arg = mock_get.call_args[0][0]
            self.assertIn("BRK.B", path_arg)

    def test_normal_ticker_with_results_returns_dataframe(self):
        import pandas as pd
        fake_payload = {
            "results": [
                {"t": 1712000000000, "c": 150.0, "v": 1000000},
                {"t": 1712086400000, "c": 152.0, "v": 1200000},
            ],
        }
        with patch.object(self.provider, "_get", return_value=fake_payload):
            df = self.provider.fetch_daily("AAPL", period="3mo")
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 2)
            self.assertIn("Close", df.columns)

    def test_normal_ticker_empty_results_returns_none(self):
        with patch.object(self.provider, "_get", return_value={"results": []}):
            result = self.provider.fetch_daily("AAPL", period="3mo")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

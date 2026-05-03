"""
tests/test_market_data_quality.py

Focused tests for the degraded market-data signal added to market_check().

Three scenarios:
  1) All tickers healthy        → data_quality == "ok", no note
  2) Partial failure < 50%      → data_quality == "ok"
  3) Majority failure >= 50%    → data_quality == "degraded", note present
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check


# ---------------------------------------------------------------------------
# Helpers — build fake _check_one_ticker results
# ---------------------------------------------------------------------------

_HEALTHY_SEED = 0

def _healthy_result(ticker: str, role: str = "beneficiary") -> dict:
    """Simulates a ticker where yfinance returned real data.

    Each call produces a distinct return_5d / spark combination so
    _suppress_duplicate_tickers won't flag them as cross-contaminated.
    """
    global _HEALTHY_SEED
    _HEALTHY_SEED += 1
    s = _HEALTHY_SEED
    return {
        "label": "in motion",
        "detail": f"1d: +{0.3 * s:.1f}%  |  5d: +{1.2 * s:.1f}%  |  vol 1.1x avg",
        "direction": "supports ↑",
        "return_1d": round(0.30 * s, 2),
        "return_5d": round(1.20 * s, 2),
        "return_20d": round(2.50 * s, 2),
        "volume_ratio": 1.10,
        "vs_xle_5d": None,
        "anchor_date": None,
        "spark": [round(0.1 * s + i * 0.05, 3) for i in range(20)],
        "verification": {"status": "unverified"},
    }


def _failed_result(ticker: str, role: str = "beneficiary") -> dict:
    """Simulates a ticker where fetch failed / returned no data."""
    return {
        "label": "needs more evidence",
        "detail": "Not enough price data.",
        "direction": None,
        "return_1d": None,
        "return_5d": None,
        "return_20d": None,
        "volume_ratio": None,
        "vs_xle_5d": None,
        "anchor_date": None,
        "spark": [],
        "verification": {"status": "unverified"},
    }


def _patch_market_check(beneficiaries, losers, results_map):
    """Call market_check with _check_one_ticker and benchmark fetches stubbed."""
    def fake_check(ticker, role="beneficiary", xle_data=None,
                   event_date=None, benchmark_cache=None, **_kwargs):
        return results_map[ticker]

    with patch.object(market_check, "_check_one_ticker", side_effect=fake_check), \
         patch.object(market_check, "_fetch_since", return_value=None), \
         patch.object(market_check, "_fetch", return_value=None):
        return market_check.market_check(beneficiaries, losers)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDataQualityHealthy(unittest.TestCase):
    """All tickers return real data → data_quality == 'ok'."""

    def setUp(self):
        global _HEALTHY_SEED
        _HEALTHY_SEED = 0

    def test_all_healthy(self):
        results_map = {
            "AAPL": _healthy_result("AAPL"),
            "MSFT": _healthy_result("MSFT"),
            "GOOG": _healthy_result("GOOG"),
            "TSLA": _healthy_result("TSLA"),
        }
        mkt = _patch_market_check(
            ["AAPL", "MSFT"], ["GOOG", "TSLA"], results_map,
        )
        self.assertEqual(mkt["data_quality"], "ok")
        self.assertNotIn("data_quality_note", mkt)


class TestDataQualityPartialBelowThreshold(unittest.TestCase):
    """One of four tickers fails (25% < 50%) → still 'ok'."""

    def setUp(self):
        global _HEALTHY_SEED
        _HEALTHY_SEED = 0

    def test_one_of_four_missing(self):
        results_map = {
            "AAPL": _healthy_result("AAPL"),
            "MSFT": _healthy_result("MSFT"),
            "GOOG": _healthy_result("GOOG"),
            "TSLA": _failed_result("TSLA"),
        }
        mkt = _patch_market_check(
            ["AAPL", "MSFT"], ["GOOG", "TSLA"], results_map,
        )
        self.assertEqual(mkt["data_quality"], "ok")
        self.assertNotIn("data_quality_note", mkt)


class TestDataQualityDegraded(unittest.TestCase):
    """Majority of tickers lack data → data_quality == 'degraded'."""

    def setUp(self):
        global _HEALTHY_SEED
        _HEALTHY_SEED = 0

    def test_three_of_four_missing(self):
        results_map = {
            "AAPL": _healthy_result("AAPL"),
            "MSFT": _failed_result("MSFT"),
            "GOOG": _failed_result("GOOG"),
            "TSLA": _failed_result("TSLA"),
        }
        mkt = _patch_market_check(
            ["AAPL", "MSFT"], ["GOOG", "TSLA"], results_map,
        )
        self.assertEqual(mkt["data_quality"], "degraded")
        self.assertIn("data_quality_note", mkt)
        self.assertIn("3/4", mkt["data_quality_note"])

    def test_all_missing(self):
        results_map = {
            "AAPL": _failed_result("AAPL"),
            "MSFT": _failed_result("MSFT"),
        }
        mkt = _patch_market_check(["AAPL"], ["MSFT"], results_map)
        self.assertEqual(mkt["data_quality"], "degraded")
        self.assertIn("2/2", mkt["data_quality_note"])

    def test_exactly_half_triggers(self):
        """50% missing meets the >= 0.5 threshold."""
        results_map = {
            "AAPL": _healthy_result("AAPL"),
            "MSFT": _failed_result("MSFT"),
        }
        mkt = _patch_market_check(["AAPL"], ["MSFT"], results_map)
        self.assertEqual(mkt["data_quality"], "degraded")

    def test_healthy_tickers_unchanged(self):
        """Degraded flag must not alter direction/return fields on healthy tickers."""
        healthy = _healthy_result("AAPL")
        expected_r5 = healthy["return_5d"]
        results_map = {
            "AAPL": healthy,
            "MSFT": _failed_result("MSFT"),
            "GOOG": _failed_result("GOOG"),
            "TSLA": _failed_result("TSLA"),
        }
        mkt = _patch_market_check(
            ["AAPL", "MSFT"], ["GOOG", "TSLA"], results_map,
        )
        aapl = next(t for t in mkt["tickers"] if t["symbol"] == "AAPL")
        self.assertEqual(aapl["return_5d"], expected_r5)
        self.assertEqual(aapl["direction_tag"], "supports ↑")


class TestDataQualityEmptyTickers(unittest.TestCase):
    """No tickers at all → data_quality == 'ok' (nothing to degrade)."""

    def test_no_tickers(self):
        mkt = market_check.market_check([], [])
        self.assertEqual(mkt["data_quality"], "ok")


if __name__ == "__main__":
    unittest.main()

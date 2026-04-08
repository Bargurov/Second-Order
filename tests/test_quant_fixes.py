"""
tests/test_quant_fixes.py

Regression tests for Quantitative Vulnerabilities fixed in this pass:
  1. classify_decay: reversed vs fading edge cases
  2. classify_decay: de minimis noise suppression
  3. find_historical_analogs: independent best_5d / best_20d selection
  4. _fetch_since: no-lookahead (auto_adjust=False) behaviour
"""

import json
import os
import sys
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, ".")
import market_check
import db


# ---------------------------------------------------------------------------
# 1. classify_decay: Reversed detection fixes
# ---------------------------------------------------------------------------

class TestDecayReversedEdgeCases(unittest.TestCase):
    """The 'Reversed' label must fire whenever 5d and 20d have opposite signs
    and at least one leg is above the de minimis threshold."""

    def test_classic_reversal(self):
        """Large opposite-sign moves — always was Reversed, still is."""
        result = market_check.classify_decay(-4.0, +5.0)
        self.assertEqual(result["label"], "Reversed")

    def test_modest_5d_large_20d(self):
        """r5=-0.3%, r20=+0.8%: old code called this Fading, should be Reversed."""
        result = market_check.classify_decay(-0.3, +0.8)
        self.assertEqual(result["label"], "Reversed")

    def test_large_5d_modest_20d(self):
        """r5=-2.0%, r20=+0.4%: clearly reversed despite small 20d leg."""
        result = market_check.classify_decay(-2.0, +0.4)
        self.assertEqual(result["label"], "Reversed")

    def test_symmetric_modest(self):
        """r5=+0.35%, r20=-0.35%: both above de minimis, opposite signs."""
        result = market_check.classify_decay(+0.35, -0.35)
        self.assertEqual(result["label"], "Reversed")

    def test_one_leg_zero_not_reversed(self):
        """If one leg is exactly zero, it should NOT be labeled Reversed."""
        result = market_check.classify_decay(0.0, +2.0)
        self.assertNotEqual(result["label"], "Reversed")

    def test_same_sign_not_reversed(self):
        """Same-sign returns must never be called Reversed."""
        result = market_check.classify_decay(+3.0, +5.0)
        self.assertNotEqual(result["label"], "Reversed")
        result2 = market_check.classify_decay(-3.0, -5.0)
        self.assertNotEqual(result2["label"], "Reversed")


# ---------------------------------------------------------------------------
# 2. classify_decay: de minimis noise suppression
# ---------------------------------------------------------------------------

class TestDecayDeMinimis(unittest.TestCase):
    """Returns below the noise floor should not receive a directional label."""

    def test_both_zero(self):
        """r5=0.0, r20=0.0: pure noise → Negligible."""
        result = market_check.classify_decay(0.0, 0.0)
        self.assertEqual(result["label"], "Negligible")

    def test_both_tiny(self):
        """r5=+0.1, r20=+0.1: both below 0.3% threshold → Negligible."""
        result = market_check.classify_decay(+0.1, +0.1)
        self.assertEqual(result["label"], "Negligible")

    def test_both_at_boundary(self):
        """r5=+0.29, r20=+0.29: just below threshold → Negligible."""
        result = market_check.classify_decay(+0.29, +0.29)
        self.assertEqual(result["label"], "Negligible")

    def test_one_above_threshold_not_negligible(self):
        """r5=+0.5, r20=+0.1: one leg meaningful → NOT Negligible."""
        result = market_check.classify_decay(+0.5, +0.1)
        self.assertNotEqual(result["label"], "Negligible")

    def test_opposite_tiny_not_reversed(self):
        """r5=+0.1, r20=-0.1: opposite but both tiny → Negligible, not Reversed."""
        result = market_check.classify_decay(+0.1, -0.1)
        self.assertEqual(result["label"], "Negligible")

    def test_meaningful_moves_still_classified(self):
        """Moves well above threshold should still get proper labels."""
        self.assertEqual(market_check.classify_decay(+5.0, +5.5)["label"], "Accelerating")
        self.assertEqual(market_check.classify_decay(+2.0, +5.0)["label"], "Holding")
        self.assertEqual(market_check.classify_decay(+0.5, +5.0)["label"], "Fading")

    def test_none_inputs_still_unknown(self):
        """None inputs should still produce Unknown, not Negligible."""
        self.assertEqual(market_check.classify_decay(None, None)["label"], "Unknown")
        self.assertEqual(market_check.classify_decay(None, +5.0)["label"], "Unknown")


# ---------------------------------------------------------------------------
# 3. find_historical_analogs: independent best_5d / best_20d
# ---------------------------------------------------------------------------

class TestAnalogIndependentBestSelection(unittest.TestCase):
    """best_5d and best_20d should be chosen independently across tickers
    so a ticker with great r5 but null r20 doesn't shadow another."""

    def setUp(self):
        self.original_db_file = db.DB_FILE
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

    def _save(self, headline, tickers_list, **kw):
        base = {
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "confidence": "medium",
            "market_tickers": tickers_list,  # save_event will json.dumps this
        }
        base.update(kw)
        db.save_event(base)

    def test_independent_best_selection(self):
        """Ticker A has r5=+8% but r20=None; Ticker B has r5=+3% and r20=+6%.
        Old code picked A for both → best_20d=None → decay=Unknown.
        Fixed code picks A's r5 and B's r20 independently."""
        tickers = [
            {"symbol": "AAA", "role": "beneficiary", "return_5d": 8.0, "return_20d": None},
            {"symbol": "BBB", "role": "beneficiary", "return_5d": 3.0, "return_20d": 6.0},
        ]
        self._save(
            "EU imposes tariffs on US steel imports",
            tickers_list=tickers,
            mechanism_summary="Tariffs raise steel prices across EU",
        )

        analogs = db.find_historical_analogs(
            "EU announces retaliatory tariffs on US steel",
            mechanism="Tariffs raise steel prices",
        )
        self.assertTrue(len(analogs) >= 1)
        analog = analogs[0]
        # best_5d should be 8.0 (from AAA), best_20d should be 6.0 (from BBB)
        self.assertAlmostEqual(analog["return_5d"], 8.0)
        self.assertAlmostEqual(analog["return_20d"], 6.0)
        # With both values available, decay should NOT be Unknown
        self.assertNotEqual(analog["decay"], "Unknown")

    def test_coupled_selection_produced_unknown_before(self):
        """Regression: verify that the old coupled logic would have
        produced Unknown here (best_5d from ticker with null r20)."""
        # This test documents the *fixed* behaviour
        tickers = [
            {"symbol": "AAA", "role": "beneficiary", "return_5d": 8.0, "return_20d": None},
            {"symbol": "BBB", "role": "beneficiary", "return_5d": 3.0, "return_20d": 6.0},
        ]
        self._save(
            "EU steel tariff escalation round one",
            tickers_list=tickers,
            mechanism_summary="EU steel tariff escalation impact",
        )

        analogs = db.find_historical_analogs(
            "EU steel tariff escalation round two",
            mechanism="EU steel tariff escalation",
        )
        self.assertTrue(len(analogs) >= 1)
        # The analog should now have valid return_20d (from BBB) not None
        self.assertIsNotNone(analogs[0]["return_20d"])


# ---------------------------------------------------------------------------
# 4. _fetch_since: auto_adjust=False (no lookahead)
# ---------------------------------------------------------------------------

class TestFetchSinceNoLookahead(unittest.TestCase):
    """_fetch_since must call yfinance with auto_adjust=False to prevent
    retroactive price adjustments from introducing lookahead bias."""

    def setUp(self):
        # Isolate the SQLite price cache to a fresh temp file so the
        # read-through layer can't satisfy reads from prior runs.
        import price_cache
        self._saved_db_file = db.DB_FILE
        self._tmp_db = os.path.join(
            tempfile.gettempdir(), f"test_quant_pc_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        price_cache._reset_table_ready_for_tests()
        market_check._cache_clear()

    def tearDown(self):
        import price_cache
        market_check._cache_clear()
        db.DB_FILE = self._saved_db_file
        price_cache._reset_table_ready_for_tests()
        if os.path.exists(self._tmp_db):
            try:
                os.remove(self._tmp_db)
            except PermissionError:
                pass

    @patch("market_check._cache_get", return_value=None)
    @patch("market_check._cache_set")
    def test_auto_adjust_false(self, mock_cache_set, mock_cache_get):
        """Verify yf.download is called with auto_adjust=False."""
        mock_df = pd.DataFrame(
            {"Close": [100.0, 101.0], "Volume": [1e6, 1e6]},
            index=pd.date_range("2026-03-01", periods=2, freq="B"),
        )
        with patch("yfinance.download", return_value=mock_df) as mock_dl:
            result = market_check._fetch_since("AAPL", "2026-03-01")
            # The cache layer may issue one fetch for the whole gap.
            self.assertGreaterEqual(mock_dl.call_count, 1)
            # Every call must carry auto_adjust=False.
            for call in mock_dl.call_args_list:
                self.assertFalse(call.kwargs.get("auto_adjust", True))

    @patch("market_check._cache_get", return_value=None)
    @patch("market_check._cache_set")
    def test_fetch_rolling_still_adjusted(self, mock_cache_set, mock_cache_get):
        """_fetch (rolling/live) should still use auto_adjust=True for current prices."""
        mock_df = pd.DataFrame(
            {"Close": [100.0, 101.0], "Volume": [1e6, 1e6]},
            index=pd.date_range("2026-03-01", periods=2, freq="B"),
        )
        with patch("yfinance.download", return_value=mock_df) as mock_dl:
            result = market_check._fetch("AAPL")
            self.assertGreaterEqual(mock_dl.call_count, 1)
            # Every call must keep auto_adjust=True.
            for call in mock_dl.call_args_list:
                self.assertTrue(call.kwargs.get("auto_adjust", False))

    @patch("market_check._cache_get", return_value=None)
    @patch("market_check._cache_set")
    def test_adj_close_fallback(self, mock_cache_set, mock_cache_get):
        """When auto_adjust=False, yfinance may use 'Adj Close' instead of 'Close'.
        _fetch_since should handle this gracefully."""
        # Simulate a DataFrame with only Adj Close (no Close column)
        mock_df = pd.DataFrame(
            {"Adj Close": [100.0, 101.0], "Volume": [1e6, 1e6]},
            index=pd.date_range("2026-03-01", periods=2, freq="B"),
        )
        with patch("yfinance.download", return_value=mock_df):
            result = market_check._fetch_since("AAPL", "2026-03-01")
            self.assertIsNotNone(result)
            self.assertIn("Close", result.columns)


# ---------------------------------------------------------------------------
# 5. Empirical validation: de minimis threshold against sample data
# ---------------------------------------------------------------------------

class TestDeMinimisCalibration(unittest.TestCase):
    """Validate the 0.3% de minimis threshold against representative cases
    from the live archive (values taken from the calibration run)."""

    def test_true_noise_filtered(self):
        """INDA +0.00% / +0.00% — the only both-tiny pair in the archive."""
        result = market_check.classify_decay(0.0, 0.0)
        self.assertEqual(result["label"], "Negligible")

    def test_modest_real_move_not_filtered(self):
        """CVX -0.56% / +21.97% — real reversal, not noise."""
        result = market_check.classify_decay(-0.56, +21.97)
        self.assertEqual(result["label"], "Reversed")

    def test_moderate_reversal_detected(self):
        """XLE -4.82% / +5.95% — clear reversal."""
        result = market_check.classify_decay(-4.82, +5.95)
        self.assertEqual(result["label"], "Reversed")

    def test_jblu_edge_case(self):
        """JBLU +0.22% / -0.88%: one leg below de minimis.
        The larger leg (-0.88%) is above threshold, so this should still
        classify as Reversed (opposite signs, meaningful 20d move)."""
        result = market_check.classify_decay(+0.22, -0.88)
        self.assertEqual(result["label"], "Reversed")


if __name__ == "__main__":
    unittest.main()

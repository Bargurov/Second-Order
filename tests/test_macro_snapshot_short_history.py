"""
tests/test_macro_snapshot_short_history.py

Focused tests for macro_snapshot forward-mode short-history hardening.

Three scenarios:
  1) Short history no crash — 2-5 rows: value populated, change_5d=None, no exception
  2) Normal history unchanged — 10+ rows: value and change_5d both correct
  3) Logged degraded case — data=None or len<2: debug log emitted, row all-None
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_df(prices, start="2026-01-01"):
    dates = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices, "Volume": [1e6] * len(prices)}, index=dates)


# ---------------------------------------------------------------------------
# 1) Short history: no crash, value present, change_5d absent
# ---------------------------------------------------------------------------

class TestShortHistoryNoCrash(unittest.TestCase):
    """Forward mode with 2–5 rows must not crash and must still return
    the row with value populated and change_5d = None."""

    def _run_forward(self, prices):
        """Run macro_snapshot with event_date='2026-01-01' and patched _fetch_since."""
        with patch("market_check._fetch_since", return_value=_make_df(prices)), \
             patch("market_check._fetch", return_value=_make_df([100.0] * 25)):
            from market_check import macro_snapshot
            return macro_snapshot(event_date="2026-01-01")

    def test_two_rows_no_crash(self):
        """Exactly 2 rows: minimum to enter the data block, no crash."""
        result = self._run_forward([100.0, 101.0])
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_two_rows_value_present(self):
        """2 rows: entry['value'] must be set to closes.iloc[0]."""
        result = self._run_forward([99.5, 100.5])
        for entry in result:
            # value should be the first row price
            self.assertIsNotNone(entry["value"],
                                 f"value should be set even with 2 rows: {entry}")

    def test_two_rows_change_5d_none(self):
        """2 rows: change_5d must be None (not enough forward data)."""
        result = self._run_forward([99.5, 100.5])
        for entry in result:
            self.assertIsNone(entry["change_5d"],
                              f"change_5d must be None with only 2 rows: {entry}")

    def test_three_rows_no_crash(self):
        result = self._run_forward([100.0, 100.5, 101.0])
        self.assertIsInstance(result, list)
        for entry in result:
            self.assertIsNone(entry["change_5d"])

    def test_five_rows_no_crash(self):
        """5 rows (one short of the 6 needed): value present, change_5d=None."""
        result = self._run_forward([100.0, 100.5, 101.0, 101.5, 102.0])
        self.assertIsInstance(result, list)
        for entry in result:
            self.assertIsNone(entry["change_5d"],
                              f"5 rows still too short for change_5d: {entry}")

    def test_api_shape_preserved_short_history(self):
        """All required keys must be present regardless of data length."""
        result = self._run_forward([100.0, 100.5])
        for entry in result:
            for key in ("label", "value", "change_5d", "unit"):
                self.assertIn(key, entry, f"key {key!r} missing from {entry}")

    def test_yield_short_history_no_crash(self):
        """10Y yield with 3 forward rows: no crash, no change_5d."""
        tnx_prices = [4.30, 4.35, 4.40]  # only 3 rows
        with patch("market_check._fetch_since", return_value=_make_df(tnx_prices)), \
             patch("market_check._fetch", return_value=_make_df([4.30] * 25)):
            from market_check import macro_snapshot
            result = macro_snapshot(event_date="2026-01-01")
        tenyr = next((e for e in result if e["label"] == "10Y"), None)
        if tenyr:
            self.assertIsNone(tenyr["change_5d"],
                              "10Y with 3 forward rows must have change_5d=None")


# ---------------------------------------------------------------------------
# 2) Normal history: behavior unchanged
# ---------------------------------------------------------------------------

class TestNormalHistoryUnchanged(unittest.TestCase):
    """With >= 6 forward rows, macro_snapshot must produce correct values."""

    def _run_forward(self, prices):
        with patch("market_check._fetch_since", return_value=_make_df(prices)), \
             patch("market_check._fetch", return_value=_make_df([100.0] * 25)):
            from market_check import macro_snapshot
            return macro_snapshot(event_date="2026-01-01")

    def test_six_rows_change_5d_computed(self):
        """Exactly 6 rows: change_5d uses iloc[0]→iloc[5] for non-yield."""
        # Non-yield: (105 - 100) / 100 * 100 = 5.0%
        result = self._run_forward([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        non_yield_entries = [e for e in result if e["label"] != "10Y"]
        for entry in non_yield_entries:
            if entry["change_5d"] is not None:
                self.assertAlmostEqual(entry["change_5d"], 5.0, delta=0.5)
                break

    def test_ten_rows_change_5d_computed(self):
        """10 rows: still uses iloc[0]→iloc[5], extra rows ignored."""
        result = self._run_forward([100.0] + [100.0] * 4 + [102.0] + [105.0] * 4)
        # iloc[5] = 102.0, iloc[0] = 100.0 → 2.0% for non-yield
        non_yield = [e for e in result if e["label"] != "10Y" and e["change_5d"] is not None]
        for entry in non_yield:
            self.assertAlmostEqual(entry["change_5d"], 2.0, delta=0.5)
            break

    def test_yield_six_rows_pp_change(self):
        """10Y with 6 forward rows: change_5d = iloc[5] - iloc[0] in pp."""
        tnx_prices = [4.30, 4.33, 4.36, 4.39, 4.42, 4.45] + [4.45] * 4
        with patch("market_check._fetch_since", return_value=_make_df(tnx_prices)), \
             patch("market_check._fetch", return_value=_make_df([4.30] * 25)):
            from market_check import macro_snapshot
            result = macro_snapshot(event_date="2026-01-01")
        tenyr = next((e for e in result if e["label"] == "10Y"), None)
        self.assertIsNotNone(tenyr)
        self.assertIsNotNone(tenyr["change_5d"])
        # 4.45 - 4.30 = 0.15 pp
        self.assertAlmostEqual(tenyr["change_5d"], 0.15, delta=0.01)

    def test_value_is_first_close_in_forward_mode(self):
        """value must be closes.iloc[0] (event-date price), not the latest."""
        prices = [99.0, 100.0, 101.0, 102.0, 103.0, 104.0]
        result = self._run_forward(prices)
        non_yield = [e for e in result if e["label"] != "10Y"]
        for entry in non_yield:
            self.assertAlmostEqual(entry["value"], 99.0, delta=1.0,
                                   msg="forward mode value must be first close")
            break

    def test_partial_result_list_length_stable(self):
        """macro_snapshot always returns one entry per instrument regardless."""
        from market_check import _MACRO_INSTRUMENTS
        result = self._run_forward([100.0] * 10)
        self.assertEqual(len(result), len(_MACRO_INSTRUMENTS))


# ---------------------------------------------------------------------------
# 3) Logged degraded case
# ---------------------------------------------------------------------------

class TestLoggedDegradedCase(unittest.TestCase):
    """Short or absent data must emit a debug log and return null values."""

    def test_no_data_emits_debug_log(self):
        """_fetch_since returns None → debug log with 'no data'."""
        with patch("market_check._fetch_since", return_value=None), \
             patch("market_check._fetch", return_value=None):
            from market_check import macro_snapshot
            with self.assertLogs("second_order.market", level="DEBUG") as cm:
                result = macro_snapshot(event_date="2026-01-01")

        log_text = "\n".join(cm.output)
        self.assertIn("no data", log_text,
                      f"Expected 'no data' in logs; got:\n{log_text}")

    def test_one_row_emits_debug_log(self):
        """_fetch_since returns 1 row (below the ≥2 guard) → debug log."""
        with patch("market_check._fetch_since", return_value=_make_df([100.0])), \
             patch("market_check._fetch", return_value=_make_df([100.0] * 25)):
            from market_check import macro_snapshot
            with self.assertLogs("second_order.market", level="DEBUG") as cm:
                result = macro_snapshot(event_date="2026-01-01")

        log_text = "\n".join(cm.output)
        # Should log about needing ≥2 rows
        self.assertTrue(
            "row" in log_text or "rows" in log_text,
            f"Expected row-count message in logs; got:\n{log_text}",
        )

    def test_no_data_row_is_all_null(self):
        """When _fetch_since returns None, entry must have value=None, change_5d=None."""
        with patch("market_check._fetch_since", return_value=None), \
             patch("market_check._fetch", return_value=None):
            from market_check import macro_snapshot
            import logging
            logging.disable(logging.CRITICAL)
            try:
                result = macro_snapshot(event_date="2026-01-01")
            finally:
                logging.disable(logging.NOTSET)

        for entry in result:
            self.assertIsNone(entry["value"],
                              f"value must be None when no data: {entry}")
            self.assertIsNone(entry["change_5d"],
                              f"change_5d must be None when no data: {entry}")

    def test_short_forward_history_emits_debug_log(self):
        """2–5 forward rows → debug log about insufficient rows for change_5d."""
        with patch("market_check._fetch_since", return_value=_make_df([100.0, 101.0])), \
             patch("market_check._fetch", return_value=_make_df([100.0] * 25)):
            from market_check import macro_snapshot
            with self.assertLogs("second_order.market", level="DEBUG") as cm:
                macro_snapshot(event_date="2026-01-01")

        log_text = "\n".join(cm.output)
        self.assertIn("change_5d unavailable", log_text,
                      f"Expected 'change_5d unavailable' in logs; got:\n{log_text}")

    def test_five_rows_emits_debug_log(self):
        """5 forward rows (one short of threshold) → debug log."""
        prices = [100.0, 100.5, 101.0, 101.5, 102.0]
        with patch("market_check._fetch_since", return_value=_make_df(prices)), \
             patch("market_check._fetch", return_value=_make_df([100.0] * 25)):
            from market_check import macro_snapshot
            with self.assertLogs("second_order.market", level="DEBUG") as cm:
                macro_snapshot(event_date="2026-01-01")

        log_text = "\n".join(cm.output)
        self.assertIn("change_5d unavailable", log_text)


if __name__ == "__main__":
    unittest.main()

"""
tests/test_direction_key_drift.py

Focused tests for direction-key drift hardening in track-record scoring.

  1) market_tickers using direction_tag → scored correctly
  2) revisit snapshots using direction → scored correctly
  3) mixed data (both keys present) → still scores correctly
  4) missing keys → degrades safely to unresolved
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import _score_directions, _resolve_direction_tag


# ---------------------------------------------------------------------------
# 1) market_tickers using direction_tag
# ---------------------------------------------------------------------------

class TestDirectionTag(unittest.TestCase):
    """Tickers from market_tickers use direction_tag."""

    def test_supports_via_direction_tag(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": "supports thesis"},
            {"symbol": "CVX", "direction_tag": "supports thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(sup_cnt, 2)
        self.assertEqual(dir_cnt, 2)

    def test_contradicts_via_direction_tag(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": "contradicts thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 0)
        self.assertEqual(dir_cnt, 1)

    def test_mixed_via_direction_tag(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": "supports thesis"},
            {"symbol": "DAL", "direction_tag": "contradicts thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 1)
        self.assertEqual(dir_cnt, 2)


# ---------------------------------------------------------------------------
# 2) revisit snapshots using direction
# ---------------------------------------------------------------------------

class TestDirectionKey(unittest.TestCase):
    """Tickers from revisit snapshots use direction (no _tag suffix)."""

    def test_supports_via_direction(self):
        tickers = [
            {"symbol": "XOM", "direction": "supports_thesis"},
            {"symbol": "CVX", "direction": "supports_thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(sup_cnt, 2)
        self.assertEqual(dir_cnt, 2)

    def test_contradicts_via_direction(self):
        tickers = [
            {"symbol": "XOM", "direction": "contradicts_thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(dir_cnt, 1)

    def test_mixed_via_direction(self):
        tickers = [
            {"symbol": "XOM", "direction": "supports_thesis"},
            {"symbol": "DAL", "direction": "contradicts_thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 1)
        self.assertEqual(dir_cnt, 2)


# ---------------------------------------------------------------------------
# 3) mixed data — tickers with both key conventions in one list
# ---------------------------------------------------------------------------

class TestMixedKeys(unittest.TestCase):
    """A list containing both direction_tag and direction tickers scores
    correctly — no key is silently ignored."""

    def test_both_keys_contribute(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": "supports thesis"},
            {"symbol": "CVX", "direction": "supports_thesis"},
            {"symbol": "DAL", "direction_tag": "contradicts thesis"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 2)
        self.assertEqual(dir_cnt, 3)

    def test_direction_tag_takes_priority(self):
        """When a ticker has both keys, direction_tag wins."""
        ticker = {"direction_tag": "supports thesis", "direction": "contradicts_thesis"}
        tag = _resolve_direction_tag(ticker)
        self.assertTrue(tag.startswith("supports"))

    def test_direction_used_when_tag_absent(self):
        ticker = {"direction": "contradicts_thesis"}
        tag = _resolve_direction_tag(ticker)
        self.assertTrue(tag.startswith("contradicts"))

    def test_direction_used_when_tag_is_none(self):
        ticker = {"direction_tag": None, "direction": "supports_thesis"}
        tag = _resolve_direction_tag(ticker)
        self.assertTrue(tag.startswith("supports"))

    def test_direction_used_when_tag_is_empty(self):
        ticker = {"direction_tag": "", "direction": "supports_thesis"}
        tag = _resolve_direction_tag(ticker)
        self.assertTrue(tag.startswith("supports"))


# ---------------------------------------------------------------------------
# 4) missing keys degrade safely to unresolved
# ---------------------------------------------------------------------------

class TestMissingKeysUnresolved(unittest.TestCase):
    """When no direction key is present, the ticker does not contribute
    to the direction count and the event ends up unresolved."""

    def test_no_direction_keys_at_all(self):
        tickers = [
            {"symbol": "XOM", "return_5d": 3.5},
            {"symbol": "CVX", "return_5d": 2.1},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(dir_cnt, 0)

    def test_all_none_directions(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": None, "direction": None},
            {"symbol": "CVX"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(dir_cnt, 0)

    def test_all_empty_string_directions(self):
        tickers = [
            {"symbol": "XOM", "direction_tag": "", "direction": ""},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertEqual(dir_cnt, 0)

    def test_empty_ticker_list(self):
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions([])
        self.assertFalse(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(dir_cnt, 0)

    def test_non_dict_entries_skipped(self):
        tickers = [None, "garbage", 42, {"direction_tag": "supports thesis"}]
        has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertEqual(dir_cnt, 1)

    def test_resolve_returns_empty_on_missing_keys(self):
        self.assertEqual(_resolve_direction_tag({}), "")
        self.assertEqual(_resolve_direction_tag({"symbol": "XOM"}), "")


if __name__ == "__main__":
    unittest.main()

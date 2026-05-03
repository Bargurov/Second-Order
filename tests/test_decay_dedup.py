"""
Tests proving db.py's find_historical_analogs delegates decay classification
to the canonical classify_decay() in market_check.py — no inline copy.

Covers:
- Analogs returned by find_historical_analogs carry the correct decay label
- Patching market_check.classify_decay is visible inside db.py (shared path)
- All canonical labels (Accelerating, Holding, Fading, Reversed, Negligible, Unknown)
  round-trip correctly through the analog builder
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import init_db, save_event, find_historical_analogs
from market_check import classify_decay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(headline, *, r5=2.0, r20=4.0, stage="developing", persistence="1w"):
    return {
        "headline": headline,
        "stage": stage,
        "persistence": persistence,
        "what_changed": "test",
        "mechanism_summary": "test mechanism",
        "beneficiaries": ["A"],
        "losers": ["B"],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "",
        "market_tickers": [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": r5, "return_20d": r20,
             "spark": [], "direction": None},
        ],
        "event_date": "2025-06-01",
        "notes": "",
    }


class _IsolatedDbTest(unittest.TestCase):

    def setUp(self):
        self._orig = db_module.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_decay_{uuid.uuid4().hex}.db",
        )
        db_module.DB_FILE = self._tmp
        db_module._db_ready = False
        init_db()

    def tearDown(self):
        db_module.DB_FILE = self._orig
        db_module._db_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnalogDecayDelegation(_IsolatedDbTest):
    """find_historical_analogs must delegate decay to market_check.classify_decay."""

    def _seed_and_query(self, r5, r20):
        """Seed one event with given returns and query analogs for a similar headline."""
        save_event(_event("OPEC extends output cuts through Q2", r5=r5, r20=r20))
        analogs = find_historical_analogs(
            "OPEC extends output cuts through Q3",
            mechanism="test mechanism",
            stage="developing",
            persistence="1w",
            exclude_headline="OPEC extends output cuts through Q3",
        )
        self.assertGreaterEqual(len(analogs), 1, "Expected at least one analog")
        return analogs[0]

    def test_accelerating_label(self):
        # r5=4.0, r20=4.5 → abs5 >= abs20 * 0.8 → Accelerating
        a = self._seed_and_query(4.0, 4.5)
        self.assertEqual(a["decay"], "Accelerating")

    def test_holding_label(self):
        # r5=2.5, r20=5.0 → abs5 >= abs20 * 0.4 but < 0.8 → Holding
        a = self._seed_and_query(2.5, 5.0)
        self.assertEqual(a["decay"], "Holding")

    def test_fading_label(self):
        # r5=0.5, r20=5.0 → abs5 < abs20 * 0.4 → Fading
        a = self._seed_and_query(0.5, 5.0)
        self.assertEqual(a["decay"], "Fading")

    def test_reversed_label(self):
        # r5=-2.0, r20=3.0 → different signs → Reversed
        a = self._seed_and_query(-2.0, 3.0)
        self.assertEqual(a["decay"], "Reversed")

    def test_negligible_label(self):
        # r5=0.05, r20=0.05 → both below de minimis → Negligible
        a = self._seed_and_query(0.05, 0.05)
        self.assertEqual(a["decay"], "Negligible")

    def test_unknown_when_no_returns(self):
        """Ticker with no return data → Unknown."""
        ev = _event("OPEC extends output cuts through Q2")
        ev["market_tickers"] = [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": None, "return_20d": None,
             "spark": [], "direction": None},
        ]
        save_event(ev)
        analogs = find_historical_analogs(
            "OPEC extends output cuts through Q3",
            mechanism="test mechanism",
            stage="developing",
            persistence="1w",
            exclude_headline="OPEC extends output cuts through Q3",
        )
        self.assertGreaterEqual(len(analogs), 1)
        self.assertEqual(analogs[0]["decay"], "Unknown")


class TestAnalogDecayUsesSharedFunction(_IsolatedDbTest):
    """Patching market_check.classify_decay must be visible inside db.py."""

    def test_patch_is_visible(self):
        """If we patch classify_decay, the analog should carry the patched label."""
        save_event(_event("Tariffs on steel imports escalate", r5=3.0, r20=5.0))

        fake = {"label": "TestLabel", "evidence": "patched"}
        with patch("market_check.classify_decay", return_value=fake):
            analogs = find_historical_analogs(
                "Tariffs on steel imports rise",
                mechanism="test mechanism",
                stage="developing",
                persistence="1w",
                exclude_headline="Tariffs on steel imports rise",
            )

        self.assertGreaterEqual(len(analogs), 1)
        self.assertEqual(analogs[0]["decay"], "TestLabel")


class TestClassifyDecayDirectRegression(unittest.TestCase):
    """Regression: canonical classify_decay still produces expected labels."""

    def test_none_inputs(self):
        self.assertEqual(classify_decay(None, None)["label"], "Unknown")

    def test_none_r5(self):
        self.assertEqual(classify_decay(None, 2.0)["label"], "Unknown")

    def test_none_r20(self):
        self.assertEqual(classify_decay(2.0, None)["label"], "Unknown")

    def test_accelerating(self):
        self.assertEqual(classify_decay(4.0, 4.5)["label"], "Accelerating")

    def test_holding(self):
        self.assertEqual(classify_decay(2.5, 5.0)["label"], "Holding")

    def test_fading(self):
        self.assertEqual(classify_decay(0.5, 5.0)["label"], "Fading")

    def test_reversed(self):
        self.assertEqual(classify_decay(-2.0, 3.0)["label"], "Reversed")

    def test_negligible(self):
        self.assertEqual(classify_decay(0.05, 0.05)["label"], "Negligible")

    def test_negative_accelerating(self):
        self.assertEqual(classify_decay(-4.0, -4.5)["label"], "Accelerating")

    def test_negative_reversed(self):
        self.assertEqual(classify_decay(2.0, -3.0)["label"], "Reversed")


if __name__ == "__main__":
    unittest.main()

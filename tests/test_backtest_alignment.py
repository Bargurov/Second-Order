"""
tests/test_backtest_alignment.py

Focused tests verifying that backtest outputs are aligned with the live
analysis path:
  1. return_60d is present in outcomes.
  2. Scrubbing (implausible returns) is applied before scoring.
  3. _sanitize_floats is applied at both exit points (no NaN in responses).
  4. market_check_freshness merges return_60d from followup_check results.
"""

import math
import os
import sys
import unittest
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api as _api_mod


# ---------------------------------------------------------------------------
# Minimal app test harness (mirrors APITestCase in test_api.py)
# ---------------------------------------------------------------------------

_PATCHES = [
    patch("analyze_event.analyze_event"),
    patch("market_check.market_check", return_value={"note": "", "details": {}, "tickers": []}),
    patch("market_check.macro_snapshot", return_value=[]),
    patch("market_check.ticker_info", return_value={}),
    patch("market_check.ticker_chart", return_value=[]),
]


class BacktestAlignmentTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        for p in _PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            os.path.dirname(__file__),
            f"test_backtest_align_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _seed_event(self, tickers=None, event_date="2025-01-15"):
        """Save a minimal event and return its id."""
        db.save_event({
            "headline": "Alignment test event",
            "stage": "realized",
            "persistence": "structural",
            "event_date": event_date,
            "market_tickers": tickers or [{"symbol": "GLD", "role": "beneficiary"}],
        })
        return db.load_recent_events(1)[0]["id"]

    # -------------------------------------------------------------------------
    # 1. return_60d present in outcomes (market_block path)
    # -------------------------------------------------------------------------

    @patch("api.followup_check", return_value=[
        {
            "symbol": "GLD", "role": "beneficiary",
            "return_1d": 0.5, "return_5d": 2.0, "return_20d": 5.0, "return_60d": 9.5,
            "direction": "supports ↑", "anchor_date": "2025-01-16",
        }
    ])
    def test_return_60d_in_outcomes(self, _mock_fc):
        eid = self._seed_event()
        r = self.client.post("/backtest/batch", json={"event_ids": [eid], "force": True})
        self.assertEqual(r.status_code, 200)
        outcome = r.json()[0]["outcomes"][0]
        self.assertIn("return_60d", outcome)
        self.assertAlmostEqual(outcome["return_60d"], 9.5)

    # -------------------------------------------------------------------------
    # 2. Scrubbing applied: implausible r5 is cleared and excluded from score
    # -------------------------------------------------------------------------

    def test_implausible_r5_scrubbed_and_excluded_from_score(self):
        """An implausibly large stored return_5d (>200%) is scrubbed to None
        and the ticker is excluded from the supporting/total score count."""
        implausible_tickers = [
            {
                "symbol": "IMPLAUS", "role": "beneficiary",
                "label": "notable move", "direction_tag": "supports ↑",
                "return_1d": 5.0,
                "return_5d": 1348.5,   # corrupt — well above 200% cap
                "return_20d": 80.0,
                "volume_ratio": 2.0, "vs_xle_5d": None, "spark": [],
            },
            {
                "symbol": "GLD", "role": "beneficiary",
                "label": "notable move", "direction_tag": "supports ↑",
                "return_1d": 1.0, "return_5d": 3.5, "return_20d": 7.0,
                "volume_ratio": 1.5, "vs_xle_5d": None, "spark": [],
            },
        ]
        eid = self._seed_event(tickers=implausible_tickers)
        # fresh event — no force needed; use the stored market_block path
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        outcomes = body["outcomes"]

        # IMPLAUS ticker: r5 scrubbed, direction cleared
        implaus = next((o for o in outcomes if o["symbol"] == "IMPLAUS"), None)
        self.assertIsNotNone(implaus)
        self.assertIsNone(implaus["return_5d"])
        self.assertIsNone(implaus["direction"])

        # Score should count only GLD (IMPLAUS excluded — no direction)
        score = body["score"]
        self.assertIsNotNone(score)
        self.assertEqual(score["total"], 1)
        self.assertEqual(score["supporting"], 1)

    # -------------------------------------------------------------------------
    # 3. _sanitize_floats applied: NaN becomes null in JSON
    # -------------------------------------------------------------------------

    def test_sanitize_floats_single_endpoint(self):
        """NaN in a stored ticker return must become null in the JSON response."""
        nan_tickers = [
            {
                "symbol": "NANTK", "role": "beneficiary",
                "label": "notable move", "direction_tag": "supports ↑",
                "return_1d": float("nan"),
                "return_5d": 2.0, "return_20d": 5.0,
                "volume_ratio": 1.0, "vs_xle_5d": None, "spark": [],
            }
        ]
        eid = self._seed_event(tickers=nan_tickers)
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        # JSON must be parseable and return_1d must be null, not NaN
        body = r.json()
        outcome = next(o for o in body["outcomes"] if o["symbol"] == "NANTK")
        self.assertIsNone(outcome["return_1d"])

    def test_sanitize_floats_batch_endpoint(self):
        """Batch endpoint also sanitizes NaN to null."""
        nan_tickers = [
            {
                "symbol": "NANTK", "role": "beneficiary",
                "label": "notable move", "direction_tag": None,
                "return_1d": None,
                "return_5d": float("inf"),   # inf should also become null
                "return_20d": None,
                "volume_ratio": None, "vs_xle_5d": None, "spark": [],
            }
        ]
        eid = self._seed_event(tickers=nan_tickers)
        r = self.client.post("/backtest/batch", json={"event_ids": [eid]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        outcome = next(o for o in body[0]["outcomes"] if o["symbol"] == "NANTK")
        self.assertIsNone(outcome["return_5d"])

    # -------------------------------------------------------------------------
    # 4. market_check_freshness merges return_60d
    # -------------------------------------------------------------------------

    @patch("api.followup_check", return_value=[
        {
            "symbol": "GLD", "role": "beneficiary",
            "return_1d": 0.4, "return_5d": 1.8, "return_20d": 4.5, "return_60d": 11.2,
            "direction": "supports ↑", "anchor_date": "2025-01-16",
        }
    ])
    def test_freshness_merge_propagates_return_60d(self, _mock_fc):
        """When the freshness layer re-runs followup_check, return_60d from the
        fresh fetch is merged onto the stored ticker and appears in outcomes."""
        eid = self._seed_event()
        r = self.client.post("/backtest/batch", json={"event_ids": [eid], "force": True})
        self.assertEqual(r.status_code, 200)
        outcome = r.json()[0]["outcomes"][0]
        self.assertAlmostEqual(outcome["return_60d"], 11.2)


if __name__ == "__main__":
    unittest.main()

"""
tests/test_mock_contamination.py

Focused tests for mock/fallback contamination prevention.

  1) Mock result not persisted (via /analyze short-circuit).
  2) Mock rows excluded from headline/overview surfaces:
     - find_cached_analysis skips mock rows
     - _is_event_low_signal rejects mock events
     - _score_event rejects mock events
     - movers surfaces exclude mock events
  3) Real rows still appear normally on all surfaces.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db
from analyze_event import _mock
from movers_cache import is_mock_event, _is_event_low_signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db() -> str:
    path = os.path.join(tempfile.gettempdir(),
                        f"test_mock_contam_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    return path


def _mock_event_record(headline: str = "Mock test headline") -> dict:
    """Build a mock event record as _persist_event would have produced
    before the mock-guard was added."""
    mock_analysis = _mock("overloaded")
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "headline": headline,
        "stage": "developing",
        "persistence": "medium",
        "what_changed": mock_analysis["what_changed"],
        "mechanism_summary": mock_analysis["mechanism_summary"],
        "beneficiaries": mock_analysis["beneficiaries"],
        "losers": mock_analysis["losers"],
        "assets_to_watch": mock_analysis["assets_to_watch"],
        "confidence": mock_analysis["confidence"],
        "market_note": "mock note",
        "market_tickers": [
            {"symbol": "GLD", "role": "beneficiary", "return_5d": 2.0,
             "direction_tag": "supports thesis", "spark": [0.5] * 20},
            {"symbol": "USO", "role": "loser", "return_5d": -1.5,
             "direction_tag": "contradicts thesis", "spark": [0.5] * 20},
        ],
        "event_date": datetime.now().strftime("%Y-%m-%d"),
    }


def _real_event_record(headline: str = "Fed raised interest rates by 50bp") -> dict:
    return {
        "id": 99,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "Fed raised interest rates by 50bp",
        "mechanism_summary": "Higher borrowing costs slow housing demand",
        "beneficiaries": ["Banks"],
        "losers": ["REITs"],
        "assets_to_watch": [],
        "confidence": "high",
        "market_note": "Strong move across financials",
        "market_tickers": [
            {"symbol": "XLF", "role": "beneficiary", "return_5d": 3.5,
             "direction_tag": "supports thesis", "spark": [0.1 * i for i in range(20)]},
        ],
        "event_date": datetime.now().strftime("%Y-%m-%d"),
    }


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = _setup_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass


# ---------------------------------------------------------------------------
# 1) Mock result not persisted
# ---------------------------------------------------------------------------

class TestMockNotPersisted(unittest.TestCase):
    """The /analyze endpoint short-circuits on mock results."""

    def test_analyze_does_not_persist_mock(self):
        import api
        persist_mock = MagicMock(return_value=(None, 1))  # (error, saved id)
        with patch("api.analyze_event", return_value=_mock("overloaded")), \
             patch("api.classify_stage", return_value="developing"), \
             patch("api.classify_persistence", return_value="medium"), \
             patch("api._persist_event", persist_mock), \
             patch("api.market_check") as mkt_mock:
            resp = api.analyze(api.AnalyzeRequest(headline="Test", confirm_paid=True))
        persist_mock.assert_not_called()
        mkt_mock.assert_not_called()
        self.assertTrue(resp["analysis_failed"])


# ---------------------------------------------------------------------------
# 2) Mock rows excluded from surfaces
# ---------------------------------------------------------------------------

class TestFindCachedAnalysisSkipsMock(_DBTestCase):
    """find_cached_analysis must not return a mock row as a cache hit."""

    def test_mock_row_not_returned_as_cache_hit(self):
        mock_ev = _mock_event_record("Fed raised rates")
        today = mock_ev["event_date"]
        db.save_event(mock_ev)

        result = db.find_cached_analysis("Fed raised rates", event_date=today)
        self.assertIsNone(result,
                          "Mock row was returned as a cache hit")

    def test_real_row_still_returned(self):
        real_ev = _real_event_record("Fed raised rates")
        today = real_ev["event_date"]
        db.save_event(real_ev)

        result = db.find_cached_analysis("Fed raised rates", event_date=today)
        self.assertIsNotNone(result)
        self.assertNotIn("[mock:", result.get("what_changed", ""))

    def test_real_preferred_over_mock(self):
        """When both mock and real rows exist, the real one wins."""
        mock_ev = _mock_event_record("Fed raised rates mock variant")
        db.save_event(mock_ev)
        # Save real with different headline so dedup doesn't skip it.
        real_ev = _real_event_record("Fed raised rates")
        today = real_ev["event_date"]
        db.save_event(real_ev)

        result = db.find_cached_analysis("Fed raised rates", event_date=today)
        self.assertIsNotNone(result)
        self.assertNotIn("[mock:", result.get("what_changed", ""))


class TestIsEventLowSignalRejectsMock(unittest.TestCase):
    """_is_event_low_signal catches mock events."""

    def test_mock_event_is_low_signal(self):
        self.assertTrue(_is_event_low_signal(_mock_event_record()))

    def test_real_event_not_low_signal(self):
        self.assertFalse(_is_event_low_signal(_real_event_record()))


class TestIsMockEventDetection(unittest.TestCase):
    """is_mock_event correctly identifies mock rows."""

    def test_mock_detected(self):
        self.assertTrue(is_mock_event({"what_changed": "[mock: overloaded]"}))

    def test_real_not_flagged(self):
        self.assertFalse(is_mock_event({"what_changed": "Fed raised rates"}))

    def test_empty_not_flagged(self):
        self.assertFalse(is_mock_event({}))
        self.assertFalse(is_mock_event({"what_changed": None}))
        self.assertFalse(is_mock_event({"what_changed": ""}))


class TestScoreEventRejectsMock(unittest.TestCase):
    """_score_event returns None for mock events."""

    def test_mock_event_scores_none(self):
        import api
        result = api._score_event(_mock_event_record(), 1.5)
        self.assertIsNone(result)

    def test_real_event_scores(self):
        import api
        result = api._score_event(_real_event_record(), 1.5)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# 3) Real rows still appear normally
# ---------------------------------------------------------------------------

class TestRealRowsAppearOnSurfaces(_DBTestCase):
    """Real events are not affected by the mock exclusion logic."""

    def test_real_event_in_find_cached_analysis(self):
        real = _real_event_record("OPEC oil supply cuts trigger price surge")
        db.save_event(real)
        result = db.find_cached_analysis(
            "OPEC oil supply cuts trigger price surge",
            event_date=real["event_date"],
        )
        self.assertIsNotNone(result)

    def test_real_event_in_load_recent_events(self):
        db.save_event(_real_event_record("OPEC oil supply cuts trigger price surge"))
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "OPEC oil supply cuts trigger price surge")

    def test_mock_event_still_in_archive(self):
        """Mock events remain in the archive (/events) for debugging.
        load_recent_events does not filter them out — only the mover
        surfaces and cache hits exclude them."""
        db.save_event(_mock_event_record("Mock headline"))
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)

    def test_mixed_db_real_surfaces_only_real(self):
        """With both mock and real events, _is_event_low_signal
        rejects the mock, keeps the real."""
        mock_ev = _mock_event_record("OPEC oil supply cuts trigger price surge")
        real_ev = _real_event_record("Fed raised interest rates by 50bp")
        filtered = [ev for ev in [mock_ev, real_ev]
                    if not _is_event_low_signal(ev)]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["headline"], "Fed raised interest rates by 50bp")


if __name__ == "__main__":
    unittest.main()

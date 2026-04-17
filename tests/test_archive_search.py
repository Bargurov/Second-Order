"""
tests/test_archive_search.py

Tests for DB-level filtered event queries.
"""
from __future__ import annotations

import os
import sys
import unittest
import uuid
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api as _api_bootstrap  # noqa: F401 — must import api before routes.events to avoid circular init
import db
from db import query_events_filtered


def _tmp_db() -> str:
    return os.path.join(tempfile.gettempdir(), f"test_archive_{uuid.uuid4().hex}.db")


def _ts(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")


class TestQueryEventsFiltered(unittest.TestCase):

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        # Event 1: headline contains "alpha-keyword", stage=realized, validated by tickers
        db.save_event({
            "headline": "alpha-keyword event",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "high",
            "timestamp": _ts(1),
            "beneficiaries": [],
            "losers": [],
            "market_tickers": [
                {"direction_tag": "supporting"},
                {"direction_tag": "supporting"},
            ],
        })
        # Event 2: beneficiaries contains "energy-sector-tag", stage=developing
        db.save_event({
            "headline": "routine market update",
            "stage": "developing",
            "persistence": "low",
            "confidence": "medium",
            "timestamp": _ts(10),
            "beneficiaries": ["energy-sector-tag"],
            "losers": [],
            "market_tickers": [],
        })
        # Event 3: losers contains "loser-tag", old timestamp in 2025, contradicted
        db.save_event({
            "headline": "old event",
            "stage": "anticipated",
            "persistence": "high",
            "confidence": "low",
            "timestamp": "2025-06-01T12:00:00",
            "beneficiaries": [],
            "losers": ["loser-tag"],
            "market_tickers": [
                {"direction_tag": "contradicting"},
                {"direction_tag": "contradicting"},
            ],
        })
        # Event 4: headline contains "alpha-keyword", stage=developing, tie → contradicted
        db.save_event({
            "headline": "alpha-keyword developing",
            "stage": "developing",
            "persistence": "medium",
            "confidence": "high",
            "timestamp": _ts(5),
            "beneficiaries": [],
            "losers": [],
            "market_tickers": [
                {"direction_tag": "supporting"},
                {"direction_tag": "contradicting"},
            ],
        })

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    def test_no_filters_returns_all_four(self):
        rows = query_events_filtered()
        self.assertEqual(len(rows), 4)

    def test_search_hits_headline(self):
        rows = query_events_filtered(search="alpha-keyword")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all("alpha-keyword" in r["headline"] for r in rows))

    def test_search_hits_beneficiaries(self):
        rows = query_events_filtered(search="energy-sector-tag")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["beneficiaries"], ["energy-sector-tag"])

    def test_search_hits_losers(self):
        rows = query_events_filtered(search="loser-tag")
        self.assertEqual(len(rows), 1)
        self.assertIn("loser-tag", rows[0]["losers"])

    def test_stage_filter(self):
        rows = query_events_filtered(stage="realized")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "realized")

    def test_persistence_filter(self):
        rows = query_events_filtered(persistence="high")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["persistence"], "high")

    def test_confidence_filter(self):
        rows = query_events_filtered(confidence="low")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["confidence"], "low")

    def test_date_from_excludes_old_event(self):
        rows = query_events_filtered(date_from="2026-01-01")
        self.assertTrue(all(r["timestamp"] >= "2026-01-01" for r in rows))
        self.assertEqual(len(rows), 3)  # Events 1, 2, 4 — not the 2025 one

    def test_date_to_returns_only_old_event(self):
        rows = query_events_filtered(date_to="2025-12-31")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["timestamp"] <= "2025-12-31T23:59:59")

    def test_combined_stage_and_search(self):
        rows = query_events_filtered(stage="developing", search="alpha-keyword")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "developing")
        self.assertIn("alpha-keyword", rows[0]["headline"])

    def test_no_match_returns_empty(self):
        rows = query_events_filtered(search="zzz-no-match-zzz")
        self.assertEqual(rows, [])


class TestScoreValidation(unittest.TestCase):
    """_score_validation derives status from direction_tags."""

    def _score(self, tags: list[str]) -> str:
        from routes.events import _score_validation
        return _score_validation({"market_tickers": [{"direction_tag": t} for t in tags]})

    def test_validated_when_supporting_majority(self):
        self.assertEqual(self._score(["supporting", "supporting", "contradicting"]), "validated")

    def test_validated_single_supporting(self):
        self.assertEqual(self._score(["supporting"]), "validated")

    def test_contradicted_when_contradicting_majority(self):
        self.assertEqual(self._score(["contradicting", "contradicting"]), "contradicted")

    def test_contradicted_on_tie(self):
        # tie: contradicting >= supporting → contradicted
        self.assertEqual(self._score(["supporting", "contradicting"]), "contradicted")

    def test_unresolved_when_no_tickers(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation({"market_tickers": []}), "unresolved")

    def test_unresolved_when_all_neutral_tags(self):
        self.assertEqual(self._score(["neutral", "neutral"]), "unresolved")

    def test_unresolved_when_market_tickers_absent(self):
        from routes.events import _score_validation
        self.assertEqual(_score_validation({}), "unresolved")


if __name__ == "__main__":
    unittest.main()

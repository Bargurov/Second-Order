"""Tests for /portfolio research-queue param + queue_counts summary."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from datetime import datetime, timedelta
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api as _api_mod


def _now_minus(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()
from portfolio_flags import QUEUE_IDS, classify_queues


def _ticker(symbol: str, *, return_5d: float = 3.0, direction_tag: str = "supports thesis",
            evidence_score: float | None = None,
            evidence_label: str | None = None,
            role: str = "beneficiary") -> dict:
    t = {
        "symbol":         symbol,
        "role":           role,
        "return_5d":      return_5d,
        "direction_tag":  direction_tag,
    }
    if evidence_score is not None:
        t["evidence_score"] = evidence_score
    if evidence_label is not None:
        t["evidence_label"] = evidence_label
    return t


def _event(
    *, event_id: int,
    mechanism_family: str = "commodity_squeeze",
    mechanism_summary: str = "Refinery outage tightens capacity.",
    confidence: str = "medium",
    rating: str = "good",
    minimum_proof_set: list | None = None,
    key_falsifiers: list | None = None,
    market_tickers: list | None = None,
    last_market_check_at: str | None = None,
    event_date: str | None = None,
) -> dict:
    return {
        "id":                   event_id,
        "headline":             f"Event {event_id}",
        "event_date":           event_date or _today(),
        "timestamp":            _now_minus(4),
        "mechanism_family":     mechanism_family,
        "mechanism_summary":    mechanism_summary,
        "stage":                "realized",
        "persistence":          "medium",
        "confidence":           confidence,
        "rating":               rating,
        "minimum_proof_set":    minimum_proof_set or [],
        "key_falsifiers":       key_falsifiers or [],
        "market_tickers":       market_tickers or [],
        "revisit_snapshots":    [],
        "low_signal":           False,
        "last_market_check_at": last_market_check_at or _now_minus(0.5),
        "regime_snapshot":      {"available": False},
    }


def _confirming(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        market_tickers=[
            _ticker("USO", evidence_score=0.85, evidence_label="supportive"),
            _ticker("XLE", evidence_score=0.80, evidence_label="supportive"),
        ],
    )


def _watch_falsifiers(event_id: int) -> dict:
    """Stale event with named falsifiers.  Lands in
    ``watch_falsifiers`` + ``refresh_needed`` queues; NOT in
    ``confirming_now`` because its market check is stale."""
    return _event(
        event_id=event_id,
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        market_tickers=[
            _ticker("USO", evidence_score=0.2, evidence_label="mixed"),
            _ticker("XLE", evidence_score=0.1, evidence_label="mixed"),
        ],
        last_market_check_at=_now_minus(24 * 90),  # 90 days old → stale
    )


def _stale_meaningful(event_id: int) -> dict:
    """Old market check but thesis is otherwise intact."""
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        market_tickers=[
            _ticker("USO", evidence_score=0.6, evidence_label="supportive"),
            _ticker("XLE", evidence_score=0.55, evidence_label="supportive"),
        ],
        last_market_check_at=_now_minus(24 * 90),  # 90 days old → stale
    )


def _falsified(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        market_tickers=[
            _ticker("USO", evidence_score=-0.8, evidence_label="contradictory",
                    direction_tag="contradicts down"),
            _ticker("XLE", evidence_score=-0.7, evidence_label="contradictory",
                    direction_tag="contradicts down"),
        ],
    )


def _low_info(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        confidence="low",
        mechanism_summary="Insufficient evidence to characterise.",
        market_tickers=[
            _ticker("USO", evidence_score=0.2, evidence_label="mixed"),
        ],
    )


def _no_proof(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        market_tickers=[
            _ticker("USO", evidence_score=0.3, evidence_label="mixed"),
        ],
    )


# ---------------------------------------------------------------------------
# Pure classifier
# ---------------------------------------------------------------------------

class TestClassifyQueues(unittest.TestCase):
    def test_enum_pinned(self):
        self.assertEqual(QUEUE_IDS, (
            "confirming_now", "watch_falsifiers",
            "refresh_needed", "low_information_cleanup",
        ))

    def test_non_dict_input_safe(self):
        self.assertEqual(classify_queues(None), [])
        self.assertEqual(classify_queues("garbage"), [])

    def test_confirming_now_rule(self):
        qs = classify_queues({
            "thesis_state":    "confirming",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "fresh",
        })
        self.assertIn("confirming_now", qs)

    def test_confirming_now_excluded_when_stale(self):
        qs = classify_queues({
            "thesis_state":    "confirming",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "stale",
        })
        self.assertNotIn("confirming_now", qs)

    def test_confirming_now_excluded_when_low_info(self):
        qs = classify_queues({
            "thesis_state":    "confirming",
            "low_information": True,
            "has_falsifiers":  True,
            "stale_signal":    "fresh",
        })
        self.assertNotIn("confirming_now", qs)

    def test_watch_falsifiers_requires_named_falsifiers(self):
        self.assertIn("watch_falsifiers", classify_queues({
            "thesis_state":    "partial",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "fresh",
        }))
        self.assertNotIn("watch_falsifiers", classify_queues({
            "thesis_state":    "partial",
            "low_information": False,
            "has_falsifiers":  False,
            "stale_signal":    "fresh",
        }))

    def test_watch_falsifiers_dropped_when_falsified(self):
        """Once the falsifier has triggered the event moves out of the
        watch queue."""
        qs = classify_queues({
            "thesis_state":    "falsified",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "fresh",
        })
        self.assertNotIn("watch_falsifiers", qs)

    def test_refresh_needed_for_stale_meaningful(self):
        qs = classify_queues({
            "thesis_state":    "stale",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "legacy",
        })
        self.assertIn("refresh_needed", qs)

    def test_refresh_needed_skipped_for_falsified(self):
        qs = classify_queues({
            "thesis_state":    "falsified",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "legacy",
        })
        self.assertNotIn("refresh_needed", qs)

    def test_low_information_cleanup(self):
        qs = classify_queues({
            "thesis_state":    "low_information",
            "low_information": True,
            "has_falsifiers":  False,
            "stale_signal":    "fresh",
        })
        self.assertEqual(qs, ["low_information_cleanup"])

    def test_multiple_memberships_possible(self):
        # Stale + falsifiers named + not falsified + not low-info →
        # watch_falsifiers + refresh_needed at the same time.
        qs = classify_queues({
            "thesis_state":    "stale",
            "low_information": False,
            "has_falsifiers":  True,
            "stale_signal":    "stale",
        })
        self.assertIn("watch_falsifiers", qs)
        self.assertIn("refresh_needed",   qs)


# ---------------------------------------------------------------------------
# Route wiring — /portfolio
# ---------------------------------------------------------------------------

class _PortfolioFixture(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_api_mod.app)

    def _get(self, rows: list[dict], **params) -> tuple[int, object]:
        with patch("routes.portfolio.load_recent_events", return_value=rows):
            resp = self.client.get("/portfolio", params=params)
        return resp.status_code, resp.json()


class TestQueueFilter(_PortfolioFixture):
    def test_invalid_queue_is_400(self):
        status, _ = self._get([], queue="not_a_queue")
        self.assertEqual(status, 400)

    def test_confirming_now_returns_only_confirming_events(self):
        rows = [
            _confirming(1),
            _watch_falsifiers(2),
            _low_info(3),
            _falsified(4),
        ]
        status, body = self._get(rows, queue="confirming_now")
        self.assertEqual(status, 200)
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {1})

    def test_watch_falsifiers_returns_only_watch_events(self):
        rows = [_confirming(1), _watch_falsifiers(2), _no_proof(3)]
        status, body = self._get(rows, queue="watch_falsifiers")
        self.assertEqual(status, 200)
        ids = {e["id"] for e in body["items"]}
        # Both event 1 and event 2 have named falsifiers and aren't
        # falsified / low-info — both belong to the watch queue.
        self.assertEqual(ids, {1, 2})

    def test_refresh_needed_returns_only_stale_events(self):
        rows = [_confirming(1), _stale_meaningful(2), _low_info(3)]
        status, body = self._get(rows, queue="refresh_needed")
        self.assertEqual(status, 200)
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {2})

    def test_low_information_cleanup_returns_only_low_info(self):
        rows = [_confirming(1), _low_info(2), _no_proof(3)]
        status, body = self._get(rows, queue="low_information_cleanup")
        self.assertEqual(status, 200)
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {2})


class TestQueueAttachment(_PortfolioFixture):
    def test_items_carry_queues_field(self):
        rows = [_confirming(1), _watch_falsifiers(2)]
        _, body = self._get(rows, queue="watch_falsifiers")
        for entry in body["items"]:
            self.assertIn("queues", entry)
            self.assertIsInstance(entry["queues"], list)
            self.assertIn("watch_falsifiers", entry["queues"])


class TestQueueCounts(_PortfolioFixture):
    def test_queue_counts_block_present_when_filter_active(self):
        _, body = self._get([_confirming(1)], queue="confirming_now")
        self.assertIn("queue_counts", body)
        self.assertEqual(set(body["queue_counts"].keys()), set(QUEUE_IDS))

    def test_queue_counts_reflect_archive_not_filtered_set(self):
        rows = [
            _confirming(1),
            _watch_falsifiers(2),
            _stale_meaningful(3),
            _low_info(4),
        ]
        _, body = self._get(rows, queue="confirming_now")
        # Only event 1 is returned under confirming_now, but the
        # queue_counts block must still tally every queue across the
        # whole archive.
        self.assertEqual(len(body["items"]), 1)
        counts = body["queue_counts"]
        self.assertEqual(counts["confirming_now"], 1)
        # Events 1 + 2 + 3 carry named falsifiers and aren't
        # falsified or low-info, so all three land in watch_falsifiers.
        # Events 2 + 3 both have stale market checks → refresh_needed.
        self.assertGreaterEqual(counts["watch_falsifiers"], 2)
        self.assertEqual(counts["refresh_needed"], 2)
        self.assertEqual(counts["low_information_cleanup"], 1)

    def test_queue_counts_emit_zero_for_empty_queue(self):
        _, body = self._get([_confirming(1)], queue="confirming_now")
        self.assertEqual(body["queue_counts"]["low_information_cleanup"], 0)

    def test_other_filters_still_trigger_queue_counts(self):
        """queue_counts always ships with a wrapped response, not
        only when ``queue`` itself is the filter."""
        rows = [_confirming(1), _low_info(2)]
        _, body = self._get(rows, low_information="false")
        self.assertIn("queue_counts", body)


# ---------------------------------------------------------------------------
# Backward compat: default shape still a list
# ---------------------------------------------------------------------------

class TestDefaultShapeStable(_PortfolioFixture):
    def test_no_queue_no_filter_returns_list(self):
        status, body = self._get([_confirming(1), _low_info(2)])
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_default_list_items_carry_queues(self):
        _, body = self._get([_confirming(1)])
        self.assertIsInstance(body, list)
        self.assertIn("queues", body[0])


if __name__ == "__main__":
    unittest.main()

"""
tests/test_movers_time_window.py

Focused tests for the time-window-based candidate selection in
/movers/today and /market-movers.

Covers:
  1) Older-but-in-window event preserved — an event near the edge of the
     time window is not dropped, even when many newer rows exist.
  2) Burst of newer rows does not crowd out — filling the DB with
     low-value events between the good event and "now" does not hide it.
  3) Endpoint behaviour stays aligned — both endpoints, given the same
     DB state, use the same time-window approach and return the same
     qualifying event when it falls inside both windows.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

# Ensure the ANTHROPIC_API_KEY env var is set (api.py reads it at import
# time; the value doesn't matter — we never call the LLM).
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    headline: str,
    *,
    hours_ago: float,
    return_5d: float | None = 3.5,
    low_signal: int = 0,
) -> dict:
    """Build a minimal event dict suitable for db.save_event."""
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    role = "beneficiary"
    tickers = [
        {
            "symbol": "XOM",
            "role": role,
            "label": "Exxon Mobil",
            "return_1d": 0.5 if return_5d is not None else None,
            "return_5d": return_5d,
            "return_20d": None,
            "direction_tag": "supports thesis" if return_5d is not None else None,
            "volume_ratio": 1.1,
            "vs_xle_5d": None,
            "spark": [100, 101, 102, 103, 104],
            "anchor_date": None,
        },
    ]
    return {
        "timestamp": ts,
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "what_changed": "Something",
        "mechanism_summary": "Mechanism text",
        "beneficiaries": ["XOM"],
        "losers": [],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "note",
        "market_tickers": tickers,
        "event_date": (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d"),
        "low_signal": low_signal,
    }


class _DBTestCase(unittest.TestCase):
    """Base that redirects db.DB_FILE to a temp database per test."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_movers_tw_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Clear the in-memory today-movers cache between tests.
        api._TODAYS_MOVERS_CACHE["data"] = None

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass


# ---------------------------------------------------------------------------
# 1) Older-but-in-window event preserved
# ---------------------------------------------------------------------------

class TestOlderInWindowEventPreserved(_DBTestCase):
    """An event near the edge of the 24h window must still appear in
    /movers/today, and near the edge of the 48h window in /market-movers."""

    def test_today_includes_23h_old_event(self):
        db.save_event(_make_event("Edge event 23h", hours_ago=23))
        # Also seed a very recent event so the surface isn't empty by luck.
        db.save_event(_make_event("Fresh event", hours_ago=0.5))

        with patch("movers_cache._is_event_low_signal", return_value=False):
            result = api.movers_today(limit=10)

        headlines = {m["headline"] for m in result}
        self.assertIn("Edge event 23h", headlines)

    def test_today_excludes_25h_old_event(self):
        db.save_event(_make_event("Expired event", hours_ago=25))

        with patch("movers_cache._is_event_low_signal", return_value=False):
            result = api.movers_today(limit=10)

        headlines = {m["headline"] for m in result}
        self.assertNotIn("Expired event", headlines)

    def test_today_honors_active_mover_window_hint(self):
        event = _make_event("Explicit active today", hours_ago=30)
        event["id"] = 4242
        event["active_mover_windows"] = ["today"]

        api._TODAYS_MOVERS_CACHE["data"] = None
        api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        with patch("api.load_events_since", return_value=[]), \
             patch("api.load_recent_events", return_value=[event]), \
             patch("movers_cache._is_event_low_signal", return_value=False):
            result = api.movers_today(limit=10)

        headlines = {m["headline"] for m in result}
        self.assertIn("Explicit active today", headlines)

    def test_market_movers_includes_47h_old_event(self):
        db.save_event(_make_event("Edge event 47h", hours_ago=47, return_5d=5.0))

        result = api.market_movers(limit=10)
        headlines = {m["headline"] for m in result}
        self.assertIn("Edge event 47h", headlines)

    def test_market_movers_excludes_49h_old_event(self):
        db.save_event(_make_event("Expired event", hours_ago=49, return_5d=5.0))

        result = api.market_movers(limit=10)
        headlines = {m["headline"] for m in result}
        self.assertNotIn("Expired event", headlines)


# ---------------------------------------------------------------------------
# 2) Burst of newer rows does not crowd out in-window events
# ---------------------------------------------------------------------------

class TestBurstDoesNotCrowdOut(_DBTestCase):
    """Inserting many newer low-value events must not hide an older
    in-window event that qualifies for the mover surface."""

    def test_today_survives_burst_of_100_low_signal_rows(self):
        # Good event from 20 hours ago.
        db.save_event(_make_event("Important event", hours_ago=20))

        # Flood with 100 more-recent events that are low-signal (no
        # return data).
        for i in range(100):
            db.save_event(_make_event(
                f"Noise event {i}",
                hours_ago=max(0.1, 19.0 - i * 0.1),
                return_5d=None,
                low_signal=1,
            ))

        with patch("movers_cache._is_event_low_signal", return_value=False) as mock_gate:
            # Let the gate accept only the important event.
            def selective_gate(ev):
                return ev.get("low_signal", 0) == 1
            mock_gate.side_effect = selective_gate

            result = api.movers_today(limit=10)

        headlines = {m["headline"] for m in result}
        self.assertIn("Important event", headlines)

    def test_market_movers_survives_burst(self):
        # Good event from 40 hours ago — inside the 48h window, with
        # a return exceeding the 1.5% threshold.
        db.save_event(_make_event("Big mover", hours_ago=40, return_5d=5.0))

        # 100 newer events that don't qualify (return below threshold).
        for i in range(100):
            db.save_event(_make_event(
                f"Small noise {i}",
                hours_ago=max(0.1, 38.0 - i * 0.3),
                return_5d=0.2,
            ))

        result = api.market_movers(limit=10)
        headlines = {m["headline"] for m in result}
        self.assertIn("Big mover", headlines)


# ---------------------------------------------------------------------------
# 3) Endpoint behaviour stays aligned across both routes
# ---------------------------------------------------------------------------

class TestEndpointAlignment(_DBTestCase):
    """Both endpoints, given the same DB state and an event that
    qualifies under both (within 24h, abs(return_5d) >= 1.5%), must
    agree on its inclusion and produce the same event_id."""

    def test_same_event_appears_in_both_endpoints(self):
        db.save_event(_make_event(
            "Aligned event",
            hours_ago=12,
            return_5d=4.0,
        ))

        with patch("movers_cache._is_event_low_signal", return_value=False):
            today = api.movers_today(limit=10)
        movers = api.market_movers(limit=10)

        today_ids = {m["event_id"] for m in today}
        movers_ids = {m["event_id"] for m in movers}
        self.assertTrue(
            today_ids & movers_ids,
            "Event qualifies for both surfaces but appeared in only one",
        )

    def test_both_endpoints_use_time_window_not_row_limit(self):
        """Insert one qualifying event, then 200 non-qualifying rows.

        Under the old row-count approach, the qualifying event would be
        pushed out of the 50/100-row limit.  Under the time-window
        approach it stays visible."""
        db.save_event(_make_event("Survivor", hours_ago=22, return_5d=6.0))

        for i in range(200):
            db.save_event(_make_event(
                f"Filler {i}",
                hours_ago=max(0.1, 21 - i * 0.1),
                return_5d=None,
                low_signal=1,
            ))

        with patch("movers_cache._is_event_low_signal", return_value=False) as mock_gate:
            mock_gate.side_effect = lambda ev: ev.get("low_signal", 0) == 1
            today = api.movers_today(limit=10)

        movers = api.market_movers(limit=10)

        today_headlines = {m["headline"] for m in today}
        movers_headlines = {m["headline"] for m in movers}
        self.assertIn("Survivor", today_headlines,
                       "/movers/today lost the event behind 200 filler rows")
        self.assertIn("Survivor", movers_headlines,
                       "/market-movers lost the event behind 200 filler rows")


if __name__ == "__main__":
    unittest.main()

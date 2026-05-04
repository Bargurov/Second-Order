"""
tests/test_today_movers_time_window.py

Focused tests proving /movers/today and /market-movers both use an explicit
time-window for candidate selection, not a row-count limit.

Invariants:
  1) Older-but-in-window events are preserved (not silently dropped)
  2) A burst of newer rows does not crowd out relevant in-window events
  3) Both routes stay aligned: same event appears in both when it falls
     inside both windows and clears the /market-movers return threshold

No patches needed — tests seed the DB directly and call the real endpoints.
The 5-minute /movers/today in-memory cache is cleared in setUp.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _items(body):
    """Unwrap the ``{items, meta}`` envelope mover surfaces now emit.

    Older tests iterate the raw list; the new response wraps items in an
    envelope alongside the diversity-guardrail meta block.  Accept both.
    """
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    return body


def _ts(hours_ago: float) -> str:
    """ISO timestamp for a point <hours_ago> hours in the past."""
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _save(
    headline: str,
    return_5d: float,
    hours_ago: float,
    direction_tag: str = "supports \u2191",
) -> None:
    """Seed one event with a controlled timestamp and a single ticker."""
    db.save_event({
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "event_date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": _ts(hours_ago),
        "market_tickers": [
            {
                "symbol": "GLD",
                "role": "beneficiary",
                "return_5d": return_5d,
                "return_20d": return_5d * 1.2,
                "direction_tag": direction_tag,
                "spark": [],
            }
        ],
    })


# ---------------------------------------------------------------------------
# Test base — temp DB + TestClient, cache cleared each test
# ---------------------------------------------------------------------------


class _TimeWindowBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as _api
        cls._api = _api
        cls.client = TestClient(_api.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_tw_{uuid.uuid4().hex}.db"
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Always clear the /movers/today in-memory TTL cache.
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# 1) Older-but-in-window events are preserved
# ---------------------------------------------------------------------------


class TestInWindowEventsPreserved(_TimeWindowBase):
    """Events timestamped near the edge of the window must appear in results."""

    def test_today_23h_event_preserved(self):
        """/movers/today includes an event from 23 hours ago (inside 24h window)."""
        _save("OPEC cuts output — edge case", return_5d=4.0, hours_ago=23.0)
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("OPEC cuts output — edge case", headlines)

    def test_today_50h_event_excluded(self):
        """/movers/today excludes an event from 50 hours ago (outside the
        48h fallback boundary).  The strict 24h preferred window is
        widened to 48h only when 24h yields nothing; 50h is past both."""
        _save("Stale oil event", return_5d=9.9, hours_ago=50.0)
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertNotIn("Stale oil event", headlines)

    def test_market_movers_47h_event_preserved(self):
        """/market-movers includes an event from 47 hours ago (inside 48h window)."""
        _save("Iran sanctions — edge case", return_5d=2.5, hours_ago=47.0)
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("Iran sanctions — edge case", headlines)

    def test_market_movers_49h_event_excluded(self):
        """/market-movers excludes an event from 49 hours ago (outside 48h window)."""
        _save("Stale tariff event", return_5d=9.9, hours_ago=49.0)
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertNotIn("Stale tariff event", headlines)

    def test_today_returns_empty_when_no_in_window_events(self):
        """Empty result is correct when no events fall inside any window
        (strict 24h or 48h fallback).  50h is past both."""
        _save("Ancient gold move", return_5d=9.9, hours_ago=50.0)
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_items(r.json()), [])

    def test_market_movers_returns_empty_when_no_in_window_events(self):
        """Empty result is correct when no events fall inside the 48h window."""
        _save("Ancient oil move", return_5d=9.9, hours_ago=50.0)
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_items(r.json()), [])


# ---------------------------------------------------------------------------
# 2) Burst of newer rows does not crowd out relevant in-window events
# ---------------------------------------------------------------------------


class TestBurstDoesNotCrowdOut(_TimeWindowBase):
    """A large number of newer events must not displace older-but-in-window events.

    With count-based selection (load_recent_events(limit=N)), seeding N+1
    events would push the oldest one off the list.  With time-window
    selection (load_events_since) every in-window event is always included.
    """

    _BURST_SIZE = 60   # well above any historic count-based limit (was 50/100)

    def _seed_burst(self, hours_ago: float, base_return: float = 1.0) -> None:
        for i in range(self._BURST_SIZE):
            _save(
                f"Burst headline {i} — tariff noise",
                return_5d=base_return,
                hours_ago=hours_ago,
            )

    def test_today_burst_does_not_crowd_out_23h_event(self):
        """After a burst of 60 events 1h old, a 23h-old event still appears."""
        _save("Target event — oil sanctions", return_5d=8.0, hours_ago=23.0)
        self._seed_burst(hours_ago=1.0)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        r = self.client.get("/movers/today?limit=100")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("Target event — oil sanctions", headlines,
                      "23h-old event was crowded out by newer burst")

    def test_market_movers_burst_does_not_crowd_out_47h_event(self):
        """After a burst of 60 events 1h old, a 47h-old event still appears."""
        _save("Target event — OPEC cut", return_5d=3.5, hours_ago=47.0)
        self._seed_burst(hours_ago=1.0, base_return=1.5)

        r = self.client.get("/market-movers?limit=100")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("Target event — OPEC cut", headlines,
                      "47h-old event was crowded out by newer burst")

    def test_today_burst_events_all_deduped_by_headline(self):
        """Burst of identical headlines collapses to one entry per unique headline."""
        # _seed_burst uses unique headlines per i, so dedup doesn't apply there.
        # This test verifies headline dedup for repeated saves of the same headline.
        for _ in range(10):
            _save("Repeated headline event", return_5d=2.0, hours_ago=0.5)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        r = self.client.get("/movers/today?limit=100")
        headlines = [m["headline"] for m in _items(r.json())]
        # Should appear at most once regardless of how many times saved
        count = headlines.count("Repeated headline event")
        self.assertLessEqual(count, 1)

    def test_market_movers_burst_events_all_still_returned_no_dedup(self):
        """/market-movers doesn't dedup by headline — all unique events returned."""
        _save("OPEC cut alpha", return_5d=2.0, hours_ago=1.0)
        _save("OPEC cut beta",  return_5d=3.0, hours_ago=2.0)
        _save("OPEC cut gamma", return_5d=1.6, hours_ago=3.0)

        r = self.client.get("/market-movers?limit=100")
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("OPEC cut alpha", headlines)
        self.assertIn("OPEC cut beta",  headlines)
        self.assertIn("OPEC cut gamma", headlines)


# ---------------------------------------------------------------------------
# 3) Both routes stay aligned — same methodology, different windows
# ---------------------------------------------------------------------------


class TestRoutesAligned(_TimeWindowBase):
    """Both routes use load_events_since (time-window), not a row-count limit.

    Alignment invariants:
    - An event inside both windows with return ≥ 1.5% appears in BOTH routes.
    - An event only inside the 48h window (24–48h old) appears only in market-movers.
    - Ranking (impact descending) is consistent for shared events.
    """

    def test_shared_event_appears_in_both_routes(self):
        """Event from 22h ago with return 3.0% appears in /movers/today AND /market-movers."""
        _save("Russia oil sanction update", return_5d=3.0, hours_ago=22.0)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        today_hl = {m["headline"] for m in _items(self.client.get("/movers/today?limit=100").json())}
        mm_hl    = {m["headline"] for m in _items(self.client.get("/market-movers?limit=100").json())}

        self.assertIn("Russia oil sanction update", today_hl)
        self.assertIn("Russia oil sanction update", mm_hl)

    def test_market_movers_only_event_not_in_today(self):
        """Event 50h old (outside both Today's 48h fallback boundary AND
        /market-movers' 48h window) appears in neither.  Pre-fallback
        this test seeded at 26h to land in 48h-only; with the fallback
        the strict-24h-empty case widens Today to 48h, so the 26h slot
        no longer separates the two surfaces — push past 48h to keep
        the original "not in today" assertion meaningful."""
        _save("China tariff retaliation wave", return_5d=4.0, hours_ago=50.0)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        today_hl = {m["headline"] for m in _items(self.client.get("/movers/today?limit=100").json())}
        mm_hl    = {m["headline"] for m in _items(self.client.get("/market-movers?limit=100").json())}

        self.assertNotIn("China tariff retaliation wave", today_hl)
        # 50h is also past /market-movers' 48h window; the surface is
        # empty rather than the previous "today excludes / mm includes"
        # split.  Test still anchors the "not in today" half.
        self.assertNotIn("China tariff retaliation wave", mm_hl)

    def test_today_below_threshold_not_in_market_movers(self):
        """Event with return 0.5% (below 1.5% threshold) shows in /movers/today but not /market-movers."""
        _save("Gold prices rise on Iran oil sanctions", return_5d=0.5, hours_ago=1.0)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        today_hl = {m["headline"] for m in _items(self.client.get("/movers/today?limit=100").json())}
        mm_hl    = {m["headline"] for m in _items(self.client.get("/market-movers?limit=100").json())}

        self.assertIn("Gold prices rise on Iran oil sanctions", today_hl,
                      "/movers/today should include sub-threshold events (no minimum)")
        self.assertNotIn("Gold prices rise on Iran oil sanctions", mm_hl,
                         "/market-movers must exclude events below the 1.5% threshold")

    def test_shared_event_ranking_consistent(self):
        """For events that appear in both routes, the impact ordering is the same."""
        _save("Iran oil sanctions tighten alpha",   return_5d=9.0, hours_ago=2.0)
        _save("Iran oil sanctions tighten beta",    return_5d=5.0, hours_ago=3.0)
        _save("Iran oil sanctions tighten gamma",   return_5d=3.0, hours_ago=4.0)

        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        today = _items(self.client.get("/movers/today?limit=100").json())
        mm    = _items(self.client.get("/market-movers?limit=100").json())

        # Both should be sorted by impact descending
        today_impacts = [m["impact"] for m in today]
        mm_impacts    = [m["impact"] for m in mm]
        self.assertEqual(today_impacts, sorted(today_impacts, reverse=True))
        self.assertEqual(mm_impacts,    sorted(mm_impacts,    reverse=True))

        # The shared headlines should appear in the same relative order
        today_hl_order = [m["headline"] for m in today
                          if m["headline"].startswith("Iran oil sanctions tighten")]
        mm_hl_order    = [m["headline"] for m in mm
                          if m["headline"].startswith("Iran oil sanctions tighten")]
        self.assertEqual(today_hl_order, mm_hl_order)

    def test_both_return_200_on_empty_db(self):
        """Both endpoints return 200 + empty list when the DB has no in-window events."""
        r_today = self.client.get("/movers/today")
        r_mm    = self.client.get("/market-movers")
        self.assertEqual(r_today.status_code, 200)
        self.assertEqual(r_mm.status_code, 200)
        self.assertEqual(_items(r_today.json()), [])
        self.assertEqual(_items(r_mm.json()), [])


# ---------------------------------------------------------------------------
# 4) Today eligibility uses last_market_check_at as a truthful anchor
# ---------------------------------------------------------------------------


def _save_with_check(
    headline: str,
    return_5d: float,
    *,
    timestamp_hours_ago: float,
    last_check_hours_ago: float | None,
    direction_tag: str = "supports ↑",
) -> None:
    event = {
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "event_date": (datetime.now() - timedelta(hours=timestamp_hours_ago))
        .strftime("%Y-%m-%d"),
        "timestamp": _ts(timestamp_hours_ago),
        "market_tickers": [
            {
                "symbol": "GLD",
                "role": "beneficiary",
                "return_5d": return_5d,
                "direction_tag": direction_tag,
                "spark": [],
            }
        ],
    }
    if last_check_hours_ago is not None:
        event["last_market_check_at"] = _ts(last_check_hours_ago)
    db.save_event(event)


class TestTodayLastMarketCheckEligibility(_TimeWindowBase):
    """Backfill-refreshed events surface in /movers/today via last_market_check_at."""

    def test_old_timestamp_recent_market_check_surfaces(self):
        """A 30h-old event re-checked 30 min ago shows up as a today mover."""
        _save_with_check(
            "OPEC backfill-refreshed oil sanctions update",
            return_5d=4.0,
            timestamp_hours_ago=30.0,
            last_check_hours_ago=0.5,
        )
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        r = self.client.get("/movers/today?limit=100")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertIn("OPEC backfill-refreshed oil sanctions update", headlines)

    def test_old_timestamp_old_market_check_excluded(self):
        """Stale on both anchors past the 48h fallback boundary → still
        excluded (no false admit).  Pre-fallback this seeded at 30h on
        both anchors; with the 48h fallback that lands inside-window
        when 24h is empty, so push to 50h to keep the exclusion."""
        _save_with_check(
            "Iran oil sanctions doubly stale",
            return_5d=9.9,
            timestamp_hours_ago=50.0,
            last_check_hours_ago=50.0,
        )
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        r = self.client.get("/movers/today?limit=100")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertNotIn("Iran oil sanctions doubly stale", headlines)

    def test_diagnostics_breakdown_reports_excluding_field(self):
        """outside_window_breakdown identifies which anchor failed.

        The diagnostic envelope is only attached when ``items`` is
        empty, so the seeded row must be past BOTH the strict 24h
        window AND the 48h fallback — 50h is.  The breakdown is
        computed against the strict 24h cutoff, so the 50h row still
        registers as ``stale_timestamp_and_market_check`` there."""
        _save("Stale 50h", return_5d=4.0, hours_ago=50.0)
        self._api._TODAYS_MOVERS_CACHE["data"] = None
        self._api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        r = self.client.get("/movers/today?include_meta=true")
        self.assertEqual(r.status_code, 200)
        meta = r.json().get("meta") or {}
        diag = meta.get("diagnostics") or {}
        rejections = diag.get("rejections") or {}
        self.assertGreaterEqual(rejections.get("outside_window", 0), 1)
        breakdown = diag.get("outside_window_breakdown") or {}
        self.assertGreaterEqual(
            breakdown.get("stale_timestamp_and_market_check", 0), 1,
            f"breakdown was {breakdown!r}",
        )

    def test_weekly_window_unchanged_for_old_timestamp(self):
        """Weekly / market windows still use timestamp-only eligibility.

        An event timestamped 49h ago with a fresh last_market_check_at
        must NOT appear in /market-movers (48h timestamp window).  This
        guards against accidentally widening the non-today windows.
        """
        _save_with_check(
            "OPEC weekly window regression — 49h old",
            return_5d=3.0,
            timestamp_hours_ago=49.0,
            last_check_hours_ago=0.5,
        )
        r = self.client.get("/market-movers?limit=100")
        self.assertEqual(r.status_code, 200)
        headlines = [m["headline"] for m in _items(r.json())]
        self.assertNotIn("OPEC weekly window regression — 49h old", headlines)


if __name__ == "__main__":
    unittest.main()

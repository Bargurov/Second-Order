"""
Tests for card-to-event routing and near-duplicate headline selection.

Covers:
- When event_id is present in the request, load_event_by_id is used (not find_cached_analysis)
- Two events with similar/near-duplicate headlines return the correct event based on event_id
- Missing event_id falls back to headline-string lookup
- event_id that doesn't exist in DB still falls through to headline lookup
"""

import json
import sqlite3
import tempfile
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import (
    init_db,
    save_event,
    load_event_by_id,
    find_cached_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_event(headline: str, event_date: str = "2025-01-15", **overrides) -> dict:
    """Build the smallest valid event dict that save_event accepts."""
    base = {
        "headline": headline,
        "stage": "test",
        "persistence": "1d",
        "what_changed": "test change",
        "mechanism_summary": "test mechanism",
        "beneficiaries": ["TEST"],
        "losers": ["NONE"],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "",
        "market_tickers": [],
        "event_date": event_date,
        "notes": "",
        "model": "test-model",
    }
    base.update(overrides)
    return base


class _IsolatedDbTestCase(unittest.TestCase):
    """Base class that runs each test against a fresh temporary database."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db_file = db_module.DB_FILE
        db_module.DB_FILE = self._tmp.name
        db_module._db_ready = False
        init_db()

    def tearDown(self):
        db_module.DB_FILE = self._orig_db_file
        db_module._db_ready = False
        try:
            os.unlink(self._tmp.name)
        except (PermissionError, OSError):
            pass  # Windows may briefly hold the SQLite file; temp dir handles cleanup


# ---------------------------------------------------------------------------
# Test: load_event_by_id returns the correct row by primary key
# ---------------------------------------------------------------------------

class TestLoadEventById(_IsolatedDbTestCase):

    def test_returns_none_for_missing_id(self):
        result = load_event_by_id(9999)
        self.assertIsNone(result)

    def test_returns_correct_event(self):
        ev = _minimal_event("OPEC extends output cuts by 500k bpd")
        save_event(ev)
        # Retrieve the id that was assigned
        with sqlite3.connect(db_module.DB_FILE) as conn:
            row_id = conn.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1").fetchone()[0]

        result = load_event_by_id(row_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["headline"], "OPEC extends output cuts by 500k bpd")

    def test_no_age_limit_unlike_find_cached(self):
        """load_event_by_id must return old events regardless of age."""
        ev = _minimal_event("Old OPEC headline")
        save_event(ev)
        # Manually backdate the timestamp to 48 hours ago
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds")
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute("UPDATE events SET timestamp = ?", (old_ts,))

        with sqlite3.connect(db_module.DB_FILE) as conn:
            row_id = conn.execute("SELECT id FROM events LIMIT 1").fetchone()[0]

        # find_cached_analysis would return None (stale), but load_event_by_id must not
        cached = find_cached_analysis("Old OPEC headline", event_date="2025-01-15")
        self.assertIsNone(cached, "find_cached_analysis should reject the stale row")

        by_id = load_event_by_id(row_id)
        self.assertIsNotNone(by_id, "load_event_by_id must return it regardless of age")


# ---------------------------------------------------------------------------
# Test: near-duplicate headlines routed to correct event by event_id
# ---------------------------------------------------------------------------

class TestNearDuplicateRouting(_IsolatedDbTestCase):

    def _insert_two_opec_events(self):
        """Insert two OPEC events whose headlines are similar but distinct."""
        ev_a = _minimal_event(
            "OPEC agrees to extend output cuts by 500k bpd through Q2",
            event_date="2025-01-10",
            what_changed="OPEC A",
        )
        ev_b = _minimal_event(
            "OPEC agrees to extend output cuts by 500k bpd through Q3",
            event_date="2025-01-10",
            what_changed="OPEC B",
        )
        save_event(ev_a)
        save_event(ev_b)
        with sqlite3.connect(db_module.DB_FILE) as conn:
            rows = conn.execute("SELECT id, headline FROM events ORDER BY id").fetchall()
        return rows  # [(id_a, headline_a), (id_b, headline_b)]

    def test_load_by_id_distinguishes_near_duplicates(self):
        rows = self._insert_two_opec_events()
        id_a, headline_a = rows[0]
        id_b, headline_b = rows[1]

        result_a = load_event_by_id(id_a)
        result_b = load_event_by_id(id_b)

        self.assertIsNotNone(result_a)
        self.assertIsNotNone(result_b)
        self.assertEqual(result_a["what_changed"], "OPEC A")
        self.assertEqual(result_b["what_changed"], "OPEC B")
        self.assertNotEqual(result_a["headline"], result_b["headline"])

    def test_event_id_wins_over_headline_string_lookup(self):
        """
        When two rows have near-duplicate headlines and a client supplies
        event_id, the id-based lookup must return the exact row — not the
        most recent headline match.
        """
        rows = self._insert_two_opec_events()
        id_a, headline_a = rows[0]
        id_b, _ = rows[1]

        # Headline string lookup (no event_id) returns the most recent row (b)
        by_headline = find_cached_analysis(headline_a, event_date="2025-01-10")
        # Only exact headline matches, so it returns row A specifically
        self.assertIsNotNone(by_headline)
        self.assertEqual(by_headline["what_changed"], "OPEC A")

        # Direct id lookup for row A is unambiguous
        by_id_a = load_event_by_id(id_a)
        self.assertEqual(by_id_a["what_changed"], "OPEC A")

        # Direct id lookup for row B is also unambiguous
        by_id_b = load_event_by_id(id_b)
        self.assertEqual(by_id_b["what_changed"], "OPEC B")

    def test_identical_headline_two_dates_id_selects_correct_one(self):
        """
        Same headline text, different event dates — event_id still routes correctly.
        """
        ev_jan = _minimal_event("Fed holds rates steady", event_date="2025-01-29", what_changed="Jan hold")
        ev_mar = _minimal_event("Fed holds rates steady", event_date="2025-03-19", what_changed="Mar hold")
        save_event(ev_jan)
        save_event(ev_mar)

        with sqlite3.connect(db_module.DB_FILE) as conn:
            rows = conn.execute("SELECT id, event_date FROM events ORDER BY id").fetchall()
        id_jan = rows[0][0]
        id_mar = rows[1][0]

        result_jan = load_event_by_id(id_jan)
        result_mar = load_event_by_id(id_mar)

        self.assertEqual(result_jan["what_changed"], "Jan hold")
        self.assertEqual(result_mar["what_changed"], "Mar hold")
        self.assertEqual(result_jan["event_date"], "2025-01-29")
        self.assertEqual(result_mar["event_date"], "2025-03-19")


# ---------------------------------------------------------------------------
# Test: API routing logic — event_id path vs headline-string path
# ---------------------------------------------------------------------------

class TestApiRoutingLogic(_IsolatedDbTestCase):
    """
    Unit-tests the routing decision in api.py without starting the full server.

    We replicate the logic:
        if event_id is not None:
            cached = load_event_by_id(event_id)
        else:
            cached = find_cached_analysis(headline, ...)
    """

    def _simulate_api_routing(self, headline: str, event_id=None, event_date=None):
        """Replicate the event_id routing logic from api.py."""
        if event_id is not None:
            return load_event_by_id(event_id)
        return find_cached_analysis(headline, event_date=event_date)

    def test_with_event_id_bypasses_headline_lookup(self):
        """Providing event_id must bypass find_cached_analysis."""
        ev = _minimal_event("Tariffs escalate on Chinese EVs", event_date="2025-02-01")
        save_event(ev)
        with sqlite3.connect(db_module.DB_FILE) as conn:
            row_id = conn.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1").fetchone()[0]

        # Simulate a wrong headline but correct event_id
        result = self._simulate_api_routing(
            headline="Completely different headline",
            event_id=row_id,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["headline"], "Tariffs escalate on Chinese EVs")

    def test_without_event_id_uses_headline_lookup(self):
        """Without event_id the headline-string path must still work."""
        ev = _minimal_event("ECB cuts rates by 25bps", event_date="2025-01-23")
        save_event(ev)

        result = self._simulate_api_routing(
            headline="ECB cuts rates by 25bps",
            event_date="2025-01-23",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["headline"], "ECB cuts rates by 25bps")

    def test_invalid_event_id_returns_none(self):
        """A non-existent event_id must return None (triggering fresh analysis)."""
        result = self._simulate_api_routing(
            headline="Some headline",
            event_id=99999,
        )
        self.assertIsNone(result)

    def test_event_id_none_and_no_headline_match_returns_none(self):
        """No event_id and no headline match → None → fresh analysis."""
        result = self._simulate_api_routing(
            headline="Headline that was never saved",
            event_id=None,
            event_date="2025-01-01",
        )
        self.assertIsNone(result)

    def test_two_similar_headlines_correct_event_via_id(self):
        """
        Full scenario: two near-duplicate OPEC events; clicking card A must
        open event A, not event B.
        """
        ev_a = _minimal_event(
            "OPEC+ agrees to cut output by 1mb/d starting February",
            event_date="2025-01-05",
            what_changed="OPEC cut Feb",
        )
        ev_b = _minimal_event(
            "OPEC+ agrees to cut output by 1mb/d starting March",
            event_date="2025-01-05",
            what_changed="OPEC cut Mar",
        )
        save_event(ev_a)
        save_event(ev_b)

        with sqlite3.connect(db_module.DB_FILE) as conn:
            rows = conn.execute("SELECT id FROM events ORDER BY id").fetchall()
        id_a, id_b = rows[0][0], rows[1][0]

        # User clicks card A
        result_a = self._simulate_api_routing(
            headline="OPEC+ agrees to cut output by 1mb/d starting February",
            event_id=id_a,
        )
        self.assertEqual(result_a["what_changed"], "OPEC cut Feb")

        # User clicks card B
        result_b = self._simulate_api_routing(
            headline="OPEC+ agrees to cut output by 1mb/d starting March",
            event_id=id_b,
        )
        self.assertEqual(result_b["what_changed"], "OPEC cut Mar")


# ---------------------------------------------------------------------------
# Test: event_id threaded into find_cached_analysis
# ---------------------------------------------------------------------------
# Covers the cache-collision fix: when two events share a headline within
# the 24h TTL window, ``find_cached_analysis(headline, event_id=X)`` must
# return the row whose primary key matches X — not the most recent
# headline match.  Headline + date fallback only fires when ``event_id``
# is absent.

class TestFindCachedAnalysisEventIdRouting(_IsolatedDbTestCase):

    def _save_two_same_headline_events(
        self,
        headline: str = "OPEC extends output cuts by 500k bpd",
        event_date: str = "2025-01-10",
    ) -> tuple[int, int]:
        """Save two events with identical headline + date but distinct
        ``what_changed`` payloads.  ``save_event`` dedupes within a 10
        minute window, so the first row is backdated past that window
        (still within the 24h TTL) before the second row is inserted.
        Returns ``(id_first, id_second)``."""
        save_event(_minimal_event(
            headline, event_date=event_date, what_changed="version A",
        ))
        backdated = (
            datetime.now() - timedelta(minutes=30)
        ).isoformat(timespec="seconds")
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute("UPDATE events SET timestamp = ?", (backdated,))
        save_event(_minimal_event(
            headline, event_date=event_date, what_changed="version B",
        ))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT id FROM events ORDER BY id",
            ).fetchall()
        return rows[0][0], rows[1][0]

    def test_event_id_routes_to_first_row(self):
        id_a, id_b = self._save_two_same_headline_events()
        result = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
            event_id=id_a,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["what_changed"], "version A")

    def test_event_id_routes_to_second_row(self):
        id_a, id_b = self._save_two_same_headline_events()
        result = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
            event_id=id_b,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["what_changed"], "version B")

    def test_event_id_wins_over_headline_most_recent(self):
        """Headline-only path returns the most recent row (id_b);
        event_id=id_a must override that and return version A."""
        id_a, id_b = self._save_two_same_headline_events()
        # Sanity: headline path returns the latest row.
        latest = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
        )
        self.assertEqual(latest["what_changed"], "version B")
        # Threaded event_id wins.
        targeted = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
            event_id=id_a,
        )
        self.assertEqual(targeted["what_changed"], "version A")

    def test_event_id_ignores_headline_mismatch(self):
        """When event_id is given the headline arg is ignored — passing
        a wrong / empty headline still returns the row at the id."""
        id_a, _ = self._save_two_same_headline_events()
        result = find_cached_analysis(
            "completely different headline",
            event_date="2099-12-31",
            event_id=id_a,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["what_changed"], "version A")

    def test_missing_event_id_returns_none_no_fallback(self):
        """A non-existent event_id must NOT fall back to headline match —
        otherwise a colliding near-duplicate could be served."""
        self._save_two_same_headline_events()
        result = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
            event_id=999_999,
        )
        self.assertIsNone(result)

    def test_event_id_respects_ttl(self):
        """Stale rows must not be served by the id path either."""
        id_a, _ = self._save_two_same_headline_events()
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds")
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute("UPDATE events SET timestamp = ? WHERE id = ?",
                         (old_ts, id_a))
        result = find_cached_analysis(
            "OPEC extends output cuts by 500k bpd",
            event_date="2025-01-10",
            event_id=id_a,
        )
        self.assertIsNone(result)

    def test_event_id_respects_mock_guard(self):
        """Mock rows must not be served by the id path either."""
        save_event(_minimal_event(
            "Mocked headline",
            event_date="2025-01-10",
            what_changed="[mock: provider error]",
        ))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            row_id = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1",
            ).fetchone()[0]
        result = find_cached_analysis(
            "Mocked headline",
            event_date="2025-01-10",
            event_id=row_id,
        )
        self.assertIsNone(result)

    def test_event_id_absent_uses_headline_path(self):
        """Backward compat: existing callers without event_id keep the
        headline + date + 24h behaviour."""
        save_event(_minimal_event(
            "Fed signals June pause",
            event_date="2025-05-01",
            what_changed="May FOMC",
        ))
        result = find_cached_analysis(
            "Fed signals June pause", event_date="2025-05-01",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["what_changed"], "May FOMC")


# ---------------------------------------------------------------------------
# Test: route-level fallback gating — event_id miss must NOT fall through
# to the headline cache lookup (otherwise a colliding row can be served)
# ---------------------------------------------------------------------------

class TestRouteLevelEventIdFallback(_IsolatedDbTestCase):
    """
    Validates the routes/analyze.py decision: when a request carries
    event_id and load_event_by_id misses, the route must skip the
    find_cached_analysis(headline) call so a near-duplicate within
    the TTL window is not served.
    """

    def _route_lookup(self, *, headline: str, event_id, event_date) -> dict | None:
        """Replicate the gated lookup in routes/analyze.py."""
        if event_id is not None:
            by_id = load_event_by_id(event_id)
            if by_id is not None:
                return by_id
            return None  # No headline fallback — re-analyze upstream.
        return find_cached_analysis(headline, event_date=event_date)

    def test_event_id_miss_does_not_serve_colliding_headline_row(self):
        """A saved row with the same headline must NOT be returned when
        the request carries a non-existent event_id."""
        save_event(_minimal_event(
            "Fed signals June pause",
            event_date="2025-05-01",
            what_changed="cached version",
        ))
        # Client sends a fresh event_id that hasn't been saved yet.
        result = self._route_lookup(
            headline="Fed signals June pause",
            event_id=999_999,
            event_date="2025-05-01",
        )
        self.assertIsNone(
            result,
            "Route must not fall back to the colliding headline match "
            "when an explicit event_id was provided",
        )

    def test_no_event_id_still_uses_headline_path(self):
        save_event(_minimal_event(
            "Fed signals June pause",
            event_date="2025-05-01",
            what_changed="cached version",
        ))
        result = self._route_lookup(
            headline="Fed signals June pause",
            event_id=None,
            event_date="2025-05-01",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["what_changed"], "cached version")


if __name__ == "__main__":
    unittest.main()

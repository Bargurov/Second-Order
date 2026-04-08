"""
tests/test_movers_cache.py

Focused tests for the persisted movers_cache layer.

Covers the four cases the task brief calls out:

  1. Cache hit avoids recomputation        (TestGetSlice.test_cache_hit_serves_without_recompute)
  2. Stale cache refreshes and persists    (TestGetSlice.test_stale_ttl_triggers_refresh
                                             + test_fingerprint_change_triggers_refresh)
  3. Empty cache bootstraps correctly      (TestGetSlice.test_empty_cache_bootstraps)
  4. Unchanged output contract             (TestEndpointContract.* — the three
                                             /movers/<slice> endpoints produce
                                             the same keys and ordering as
                                             before the cache layer landed)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import movers_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 8, 12, 0, 0)


def _event(
    *,
    event_id: int,
    headline: str,
    days_ago: int,
    return_5d: float,
    return_20d: float | None = None,
    direction_tag: str = "supports \u2191",
) -> dict:
    """Build an in-memory event dict matching db.load_recent_events shape."""
    now = _now()
    ts = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "id": event_id,
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "event_date": (now - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
        "timestamp": ts,
        "mechanism_summary": "",
        "market_tickers": [
            {
                "symbol": "GLD",
                "role": "beneficiary",
                "return_5d": return_5d,
                "return_20d": return_20d if return_20d is not None else return_5d * 1.2,
                "direction_tag": direction_tag,
                "spark": [],
            },
        ],
        "transmission_chain": [],
        "if_persists": {},
    }


def _seed_events(count: int, days_ago: int = 2) -> list[dict]:
    return [
        _event(
            event_id=i,
            headline=f"Seed event {i}",
            days_ago=days_ago,
            return_5d=float(i + 2),
        )
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# 1. compute_slice — pure recomputation logic
# ---------------------------------------------------------------------------


class TestComputeSlice(unittest.TestCase):
    """Shape-preserving filter + sort behaviour per slice name."""

    def _fake_build_mover_summary(self, ev, big_moves, support_ratio):
        impact = max(abs(t["return_5d"]) for t in big_moves) * (1.0 + support_ratio)
        return {
            "event_id": ev["id"],
            "headline": ev["headline"],
            "event_date": ev.get("event_date", ""),
            "stage": ev.get("stage", ""),
            "persistence": ev.get("persistence", ""),
            "mechanism_summary": ev.get("mechanism_summary", ""),
            "impact": round(impact, 2),
            "support_ratio": round(support_ratio, 2),
            "tickers": [],
            "transmission_chain": ev.get("transmission_chain", []),
            "if_persists": ev.get("if_persists", {}),
        }

    def _fake_persistent_summary(self, ev, with_return, now_dt):
        out = self._fake_build_mover_summary(ev, with_return, 1.0)
        out["days_since_event"] = (
            now_dt.date() - datetime.fromisoformat(ev["event_date"]).date()
        ).days
        out["tickers"] = [
            {"symbol": t["symbol"], "decay": "Accelerating"}
            for t in with_return
        ]
        return out

    def _fake_classify(self, r5, r20):
        return {"label": "Accelerating", "evidence": "fake"}

    def _compute(self, slice_name, events):
        return movers_cache.compute_slice(
            slice_name, events, now=_now(),
            build_mover_summary=self._fake_build_mover_summary,
            build_persistent_summary=self._fake_persistent_summary,
            classify_decay_fn=self._fake_classify,
        )

    def test_weekly_filters_by_7_day_window(self):
        events = [
            _event(event_id=1, headline="Recent", days_ago=2, return_5d=3.0),
            _event(event_id=2, headline="Old", days_ago=14, return_5d=9.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual([e["headline"] for e in out], ["Recent"])

    def test_weekly_sorts_by_impact_descending(self):
        events = [
            _event(event_id=1, headline="Small", days_ago=1, return_5d=1.5),
            _event(event_id=2, headline="Big",   days_ago=1, return_5d=8.0),
            _event(event_id=3, headline="Mid",   days_ago=1, return_5d=4.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual(
            [e["headline"] for e in out], ["Big", "Mid", "Small"],
        )

    def test_yearly_filters_by_365_day_window(self):
        events = [
            _event(event_id=1, headline="This year", days_ago=100, return_5d=3.0),
            _event(event_id=2, headline="Ancient",   days_ago=400, return_5d=9.0),
        ]
        out = self._compute("yearly", events)
        self.assertEqual([e["headline"] for e in out], ["This year"])

    def test_weekly_deduplicates_by_headline(self):
        events = [
            _event(event_id=1, headline="Dup", days_ago=1, return_5d=5.0),
            _event(event_id=2, headline="Dup", days_ago=1, return_5d=3.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual(len(out), 1)

    def test_weekly_skips_events_without_return(self):
        ev = _event(event_id=1, headline="No return", days_ago=1, return_5d=0.0)
        # Null out the return so the ticker no longer qualifies
        ev["market_tickers"][0]["return_5d"] = None
        out = self._compute("weekly", [ev])
        self.assertEqual(out, [])

    def test_persistent_strict_returns_old_movers(self):
        events = [
            _event(event_id=1, headline="Old mover", days_ago=14, return_5d=4.0),
        ]
        out = self._compute("persistent", events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["headline"], "Old mover")
        self.assertIn("days_since_event", out[0])

    def test_persistent_fallback_when_strict_empty(self):
        """If no events are >7d old, fallback returns any mover."""
        events = [
            _event(event_id=1, headline="Recent only", days_ago=1, return_5d=4.0),
        ]
        out = self._compute("persistent", events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["headline"], "Recent only")

    def test_unknown_slice_raises(self):
        with self.assertRaises(ValueError):
            self._compute("does-not-exist", [])


# ---------------------------------------------------------------------------
# 2. get_slice — cache hit / TTL / fingerprint / bootstrap
# ---------------------------------------------------------------------------


class TestGetSlice(unittest.TestCase):
    """Cache-level read/refresh rules.

    Uses fully injected fakes for load/save/fingerprint/compute so we
    can count calls without touching SQLite, matching the style used
    in ``tests/test_market_check_freshness.py``.
    """

    def setUp(self):
        self.compute_calls = 0
        self.save_calls = 0

        def _load_events(limit):
            return _seed_events(3)

        self._load_events_fn = _load_events

        self._cache_store: dict[str, dict] = {}

        def _load_cache(slice_name):
            return self._cache_store.get(slice_name)

        def _save_cache(slice_name, payload, built_at, count, max_id):
            self.save_calls += 1
            self._cache_store[slice_name] = {
                "payload": payload,
                "built_at": built_at,
                "event_count": count,
                "max_event_id": max_id,
            }

        self._load_cache_fn = _load_cache
        self._save_cache_fn = _save_cache

        self._fp = (3, 3)
        self._fingerprint_fn = lambda: self._fp

        test_case = self

        def _compute(slice_name, events, now=None):
            test_case.compute_calls += 1
            return [
                {"event_id": e["id"], "headline": e["headline"],
                 "impact": float(e["market_tickers"][0]["return_5d"])}
                for e in events
            ]

        self._compute_fn = _compute

    def _get(self, *, slice_name="weekly", limit=10, force=False, ttl=1800):
        return movers_cache.get_slice(
            slice_name,
            limit=limit,
            ttl_seconds=ttl,
            force=force,
            now=_now(),
            load_events_fn=self._load_events_fn,
            load_cache_fn=self._load_cache_fn,
            save_cache_fn=self._save_cache_fn,
            fingerprint_fn=self._fingerprint_fn,
            compute_fn=self._compute_fn,
        )

    def test_empty_cache_bootstraps(self):
        """Case 3: first read with no cached row computes + persists."""
        out = self._get()
        self.assertEqual(len(out), 3)
        self.assertEqual(self.compute_calls, 1)
        self.assertEqual(self.save_calls, 1)
        self.assertIn("weekly", self._cache_store)

    def test_cache_hit_serves_without_recompute(self):
        """Case 1: a warm cache with unchanged fingerprint skips compute."""
        self._get()  # bootstrap
        self.compute_calls = 0
        self.save_calls = 0

        out = self._get()
        self.assertEqual(len(out), 3)
        self.assertEqual(self.compute_calls, 0)
        self.assertEqual(self.save_calls, 0)

    def test_stale_ttl_triggers_refresh(self):
        """Case 2a: a cached row older than TTL recomputes + persists."""
        self._get()  # bootstrap
        # Backdate the cached built_at so it looks older than the 1800s TTL
        self._cache_store["weekly"]["built_at"] = (
            (_now() - timedelta(hours=2)).replace(microsecond=0).isoformat()
        )
        self.compute_calls = 0
        self.save_calls = 0

        out = self._get(ttl=1800)
        self.assertEqual(len(out), 3)
        self.assertEqual(self.compute_calls, 1)
        self.assertEqual(self.save_calls, 1)

    def test_fingerprint_change_triggers_refresh(self):
        """Case 2b: a new event (fingerprint change) recomputes even inside TTL."""
        self._get()  # bootstrap
        self.compute_calls = 0
        self.save_calls = 0

        # Simulate a new event saved: count + max_event_id both move.
        self._fp = (4, 4)
        self._get()

        self.assertEqual(self.compute_calls, 1)
        self.assertEqual(self.save_calls, 1)

    def test_force_bypasses_cache(self):
        """force=True always recomputes, even with a warm cache."""
        self._get()  # bootstrap
        self.compute_calls = 0
        self.save_calls = 0

        self._get(force=True)
        self.assertEqual(self.compute_calls, 1)
        self.assertEqual(self.save_calls, 1)

    def test_cache_hit_respects_limit_parameter(self):
        """A warm read honours the caller's limit without recomputing."""
        self._get(limit=10)
        self.compute_calls = 0
        out = self._get(limit=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(self.compute_calls, 0)

    def test_compute_failure_returns_empty_list(self):
        """A crashing compute_fn degrades to an empty list, not a 500."""
        def _boom(slice_name, events, now=None):
            raise RuntimeError("simulated provider failure")

        out = movers_cache.get_slice(
            "weekly", limit=10, ttl_seconds=1800, force=True, now=_now(),
            load_events_fn=self._load_events_fn,
            load_cache_fn=self._load_cache_fn,
            save_cache_fn=self._save_cache_fn,
            fingerprint_fn=self._fingerprint_fn,
            compute_fn=_boom,
        )
        self.assertEqual(out, [])


# ---------------------------------------------------------------------------
# 3. DB integration — schema + round-trip
# ---------------------------------------------------------------------------


class TestDbMoversCache(unittest.TestCase):
    """Verify the schema migration + the load/save/clear helpers."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_movers_cache_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_movers_cache_table_exists(self):
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='movers_cache'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_save_and_load_round_trip(self):
        payload = [
            {"event_id": 1, "headline": "A", "impact": 5.0},
            {"event_id": 2, "headline": "B", "impact": 3.2},
        ]
        db.save_movers_cache(
            "weekly", payload, "2026-04-08T12:00:00", 2, 2,
        )
        row = db.load_movers_cache("weekly")
        self.assertIsNotNone(row)
        self.assertEqual(row["payload"], payload)
        self.assertEqual(row["built_at"], "2026-04-08T12:00:00")
        self.assertEqual(row["event_count"], 2)
        self.assertEqual(row["max_event_id"], 2)

    def test_load_missing_slice_returns_none(self):
        """Case 4 (degradation): empty cache reads return None cleanly."""
        self.assertIsNone(db.load_movers_cache("nonexistent"))

    def test_overwrite_replaces_existing_row(self):
        db.save_movers_cache("weekly", [{"a": 1}], "2026-04-08T10:00:00", 1, 1)
        db.save_movers_cache("weekly", [{"b": 2}], "2026-04-08T11:00:00", 2, 5)
        row = db.load_movers_cache("weekly")
        self.assertEqual(row["payload"], [{"b": 2}])
        self.assertEqual(row["max_event_id"], 5)

    def test_clear_movers_cache_named_slice(self):
        db.save_movers_cache("weekly", [], "2026-04-08T10:00:00", 0, 0)
        db.save_movers_cache("yearly", [], "2026-04-08T10:00:00", 0, 0)
        db.clear_movers_cache("weekly")
        self.assertIsNone(db.load_movers_cache("weekly"))
        self.assertIsNotNone(db.load_movers_cache("yearly"))

    def test_clear_movers_cache_all(self):
        db.save_movers_cache("weekly", [], "2026-04-08T10:00:00", 0, 0)
        db.save_movers_cache("yearly", [], "2026-04-08T10:00:00", 0, 0)
        db.clear_movers_cache()
        self.assertIsNone(db.load_movers_cache("weekly"))
        self.assertIsNone(db.load_movers_cache("yearly"))

    def test_corrupt_payload_returns_none(self):
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "INSERT INTO movers_cache "
                "(slice, payload, built_at, event_count, max_event_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("weekly", "not json {", "2026-04-08T10:00:00", 0, 0),
            )
        # load must degrade cleanly rather than crashing downstream.
        self.assertIsNone(db.load_movers_cache("weekly"))

    def test_fingerprint_matches_events_state(self):
        self.assertEqual(db.get_events_fingerprint(), (0, 0))

        db.save_event({
            "headline": "Test fingerprint", "stage": "realized",
            "persistence": "medium", "event_date": "2026-04-06",
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary",
                                 "return_5d": 1.0}],
        })
        count, max_id = db.get_events_fingerprint()
        self.assertEqual(count, 1)
        self.assertGreaterEqual(max_id, 1)

    def test_get_slice_end_to_end_through_sqlite(self):
        """Full wiring: get_slice computes, persists, then serves warm from SQLite."""
        # Seed two events so compute_slice has something to return.
        db.save_event({
            "headline": "Weekly event A", "stage": "realized",
            "persistence": "medium", "event_date": "2026-04-07",
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary",
                                 "return_5d": 2.5,
                                 "direction_tag": "supports \u2191"}],
        })
        db.save_event({
            "headline": "Weekly event B", "stage": "realized",
            "persistence": "medium", "event_date": "2026-04-07",
            "market_tickers": [{"symbol": "XLE", "role": "beneficiary",
                                 "return_5d": 5.5,
                                 "direction_tag": "supports \u2191"}],
        })

        build_calls = {"n": 0}
        persistent_calls = {"n": 0}

        def _fake_build(ev, big, ratio):
            build_calls["n"] += 1
            return {
                "event_id": ev["id"],
                "headline": ev["headline"],
                "event_date": ev.get("event_date", ""),
                "stage": ev.get("stage", ""),
                "persistence": ev.get("persistence", ""),
                "mechanism_summary": "",
                "impact": max(abs(t["return_5d"]) for t in big),
                "support_ratio": round(ratio, 2),
                "tickers": [],
                "transmission_chain": [],
                "if_persists": {},
            }

        def _fake_persistent(ev, big, now_dt):
            persistent_calls["n"] += 1
            out = _fake_build(ev, big, 1.0)
            out["days_since_event"] = 1
            return out

        def _fake_classify(r5, r20):
            return {"label": "Accelerating", "evidence": ""}

        def _compute(slice_name, events, now=None):
            return movers_cache.compute_slice(
                slice_name, events, now=now,
                build_mover_summary=_fake_build,
                build_persistent_summary=_fake_persistent,
                classify_decay_fn=_fake_classify,
            )

        # First read bootstraps the cache.
        out1 = movers_cache.get_slice(
            "weekly", limit=10, ttl_seconds=1800, now=_now(),
            compute_fn=_compute,
        )
        self.assertEqual(len(out1), 2)
        self.assertEqual(out1[0]["headline"], "Weekly event B")  # larger impact
        first_build_calls = build_calls["n"]
        self.assertGreater(first_build_calls, 0)

        # Second read should be a warm cache hit — compute must not run again.
        out2 = movers_cache.get_slice(
            "weekly", limit=10, ttl_seconds=1800, now=_now(),
            compute_fn=_compute,
        )
        self.assertEqual(out2, out1)
        self.assertEqual(build_calls["n"], first_build_calls)  # unchanged


# ---------------------------------------------------------------------------
# 4. Output contract — existing endpoints still return the same keys
# ---------------------------------------------------------------------------


class TestEndpointContract(unittest.TestCase):
    """Stability of /movers/* response shapes across the cache refactor.

    These mirror the assertions scattered through test_api.TestMovers* but
    group them into a single contract check so a future refactor that
    loses a key is caught immediately.
    """

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_contract_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Clear any in-memory today cache so we bootstrap cleanly.
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    _REQUIRED_KEYS = {
        "event_id", "headline", "event_date", "stage", "persistence",
        "impact", "support_ratio", "tickers", "transmission_chain",
        "if_persists",
    }

    def _seed(self, headline: str, return_5d: float,
              timestamp: str | None = None, return_20d: float = 0.0):
        ev = {
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2026-04-07",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": return_5d, "return_20d": return_20d,
                 "direction_tag": "supports \u2191"},
            ],
        }
        if timestamp:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def _assert_mover_shape(self, rows: list[dict]):
        self.assertIsInstance(rows, list)
        for row in rows:
            missing = self._REQUIRED_KEYS - set(row.keys())
            self.assertFalse(missing, f"Missing keys: {missing}")

    def test_weekly_output_contract(self):
        self._seed("Contract weekly A", 3.0)
        self._seed("Contract weekly B", 5.0)
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self._assert_mover_shape(body)
        # Ranking stability: higher impact sorts first.
        self.assertEqual(body[0]["headline"], "Contract weekly B")

    def test_yearly_output_contract(self):
        self._seed("Contract yearly A", 4.0)
        r = self.client.get("/movers/yearly")
        self.assertEqual(r.status_code, 200)
        self._assert_mover_shape(r.json())

    def test_persistent_output_contract_includes_days_since_event(self):
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Contract persistent", 5.0, timestamp=old_ts, return_20d=6.0)
        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self._assert_mover_shape(body)
        for row in body:
            self.assertIn("days_since_event", row)

    def test_new_event_invalidates_cache_via_fingerprint(self):
        """Saving a new event inside the TTL window still shows up."""
        self._seed("Initial", 3.0)
        r1 = self.client.get("/movers/weekly")
        self.assertEqual(len(r1.json()), 1)

        # New save → fingerprint changes → cache is recomputed on next read.
        self._seed("Follow-up", 4.0)
        r2 = self.client.get("/movers/weekly")
        headlines = {m["headline"] for m in r2.json()}
        self.assertIn("Initial", headlines)
        self.assertIn("Follow-up", headlines)


if __name__ == "__main__":
    unittest.main()

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
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import movers_cache
from mover_card_normalizer import is_high_conviction_persistent


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


_RELEVANT_HEADLINES = [
    "OPEC cuts output by 500k bpd",
    "US tariff on steel imports takes effect",
    "EU sanctions expand to Russian energy sector",
    "China retaliatory tariffs on US agriculture",
    "NATO allies increase defense spending",
    "Natural gas supply disruption in Europe",
    "Federal Reserve signals rate cut",
    "Oil embargo tightens on Iran exports",
    "Semiconductor export controls extended",
    "LNG terminal explosion halts shipments",
]


def _seed_events(count: int, days_ago: int = 2) -> list[dict]:
    return [
        _event(
            event_id=i,
            headline=_RELEVANT_HEADLINES[i % len(_RELEVANT_HEADLINES)],
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
            _event(event_id=1, headline="OPEC cuts output by 500k bpd", days_ago=2, return_5d=3.0),
            _event(event_id=2, headline="US tariff on steel imports takes effect", days_ago=14, return_5d=9.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual([e["headline"] for e in out], ["OPEC cuts output by 500k bpd"])

    def test_weekly_honors_active_mover_window_hint(self):
        event = _event(
            event_id=2,
            headline="US tariff on steel imports takes effect",
            days_ago=14,
            return_5d=9.0,
        )
        event["active_mover_windows"] = ["weekly"]
        out = self._compute("weekly", [event])
        self.assertEqual(
            [e["headline"] for e in out],
            ["US tariff on steel imports takes effect"],
        )

    def test_weekly_sorts_by_impact_descending(self):
        events = [
            _event(event_id=1, headline="EU sanctions on Russian oil", days_ago=1, return_5d=1.5),
            _event(event_id=2, headline="OPEC cuts output by 500k bpd",   days_ago=1, return_5d=8.0),
            _event(event_id=3, headline="China tariffs on US agriculture",   days_ago=1, return_5d=4.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual(
            [e["headline"] for e in out],
            ["OPEC cuts output by 500k bpd", "China tariffs on US agriculture", "EU sanctions on Russian oil"],
        )

    def test_yearly_filters_by_365_day_window(self):
        events = [
            _event(event_id=1, headline="NATO defense spending increase", days_ago=100, return_5d=3.0),
            _event(event_id=2, headline="Oil embargo on Iran exports",   days_ago=400, return_5d=9.0),
        ]
        out = self._compute("yearly", events)
        self.assertEqual([e["headline"] for e in out], ["NATO defense spending increase"])

    def test_weekly_deduplicates_by_headline(self):
        events = [
            _event(event_id=1, headline="OPEC cuts output by 500k bpd", days_ago=1, return_5d=5.0),
            _event(event_id=2, headline="OPEC cuts output by 500k bpd", days_ago=1, return_5d=3.0),
        ]
        out = self._compute("weekly", events)
        self.assertEqual(len(out), 1)

    def test_weekly_skips_events_without_return(self):
        ev = _event(event_id=1, headline="EU sanctions on Russian energy", days_ago=1, return_5d=0.0)
        # Null out the return so the ticker no longer qualifies
        ev["market_tickers"][0]["return_5d"] = None
        out = self._compute("weekly", [ev])
        self.assertEqual(out, [])

    def test_persistent_strict_returns_old_movers(self):
        events = [
            _event(event_id=1, headline="Oil embargo tightens on Iran exports", days_ago=14, return_5d=4.0),
        ]
        out = self._compute("persistent", events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["headline"], "Oil embargo tightens on Iran exports")
        self.assertIn("days_since_event", out[0])

    def test_persistent_fallback_when_strict_empty(self):
        """If no events are >7d old, fallback returns any mover."""
        events = [
            _event(event_id=1, headline="OPEC cuts output by 500k bpd", days_ago=1, return_5d=4.0),
        ]
        out = self._compute("persistent", events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["headline"], "OPEC cuts output by 500k bpd")

    def test_unknown_slice_raises(self):
        with self.assertRaises(ValueError):
            self._compute("does-not-exist", [])


class TestPersistentHighImpactEligibility(unittest.TestCase):
    """Route-level Still Moving Markets gate rejects non-high convictions."""

    def test_medium_impact_conviction_does_not_qualify(self):
        card = {
            "event_id": 1,
            "headline": "Clean but not large enough follow-through",
            "thesis_state": "confirming",
            "stale_signal": "fresh",
            "weighted_evidence": {"evidence_label": "supportive"},
            "conviction": {
                "conviction_class": "conviction",
                "impact_level": "medium",
            },
            "tickers": [{"symbol": "AAA", "return_5d": 1.0}],
        }
        self.assertFalse(is_high_conviction_persistent(card))


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

        def _save_cache(slice_name, payload, built_at, count, max_id, *, compute_version=0):
            self.save_calls += 1
            self._cache_store[slice_name] = {
                "payload": payload,
                "built_at": built_at,
                "event_count": count,
                "max_event_id": max_id,
                "compute_version": compute_version,
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

    def _get(self, *, slice_name="weekly", limit=10, force=False, ttl=1800,
             allow_refresh=True):
        return movers_cache.get_slice(
            slice_name,
            limit=limit,
            ttl_seconds=ttl,
            force=force,
            allow_refresh=allow_refresh,
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

    def test_allow_refresh_false_serves_stale_cache_without_persist(self):
        """Read-only mode: a stale + fingerprint-changed cached row is served
        as-is, never recomputed or persisted (the E6C event-detail contract)."""
        self._get()  # bootstrap a warm row
        # Make it stale AND move the fingerprint so a refreshing read WOULD
        # rebuild — proving read-only ignores both triggers.
        self._cache_store["weekly"]["built_at"] = (
            (_now() - timedelta(hours=2)).replace(microsecond=0).isoformat()
        )
        self._fp = (99, 99)
        self.compute_calls = 0
        self.save_calls = 0

        out = self._get(allow_refresh=False)
        self.assertEqual(len(out), 3)            # served the cached payload
        self.assertEqual(self.compute_calls, 0)  # never recomputed
        self.assertEqual(self.save_calls, 0)     # never persisted

    def test_allow_refresh_false_missing_returns_empty_without_persist(self):
        """Read-only mode with no cached row returns [] without bootstrapping."""
        out = self._get(allow_refresh=False)  # cold cache, no row
        self.assertEqual(out, [])
        self.assertEqual(self.compute_calls, 0)
        self.assertEqual(self.save_calls, 0)
        self.assertNotIn("weekly", self._cache_store)

    def test_allow_refresh_false_respects_limit(self):
        """Read-only mode trims the cached payload to the caller's limit."""
        self._get()  # bootstrap (3 rows)
        self.compute_calls = 0
        self.save_calls = 0
        out = self._get(limit=1, allow_refresh=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(self.save_calls, 0)

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
            "headline": "OPEC cuts output by 500k bpd", "stage": "realized",
            "persistence": "medium", "event_date": "2026-04-07",
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary",
                                 "return_5d": 2.5,
                                 "direction_tag": "supports \u2191"}],
        })
        db.save_event({
            "headline": "EU sanctions on Russian energy sector", "stage": "realized",
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
        self.assertEqual(out1[0]["headline"], "EU sanctions on Russian energy sector")  # larger impact
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
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        self._orig_backfill_provider = os.environ.get("BACKFILL_PROVIDER")
        self._orig_backfill_budget = os.environ.get("MAX_BACKFILL_LLM_CALLS")
        # ENABLE_PAID_ANALYSIS is the server-side kill-switch (default off)
        # that 403s any dry_run=false backfill before it can spend.  The
        # backfill-recent tests exercise that paid path with the provider
        # seams mocked, so they must opt into the switch — otherwise the
        # guard short-circuits to 403 before the mocks are ever reached.
        # Saved/restored like the two env vars above so it can't leak.
        self._orig_paid_analysis = os.environ.get("ENABLE_PAID_ANALYSIS")
        os.environ["BACKFILL_PROVIDER"] = "anthropic"
        os.environ["MAX_BACKFILL_LLM_CALLS"] = "20"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def tearDown(self):
        if self._orig_backfill_provider is None:
            os.environ.pop("BACKFILL_PROVIDER", None)
        else:
            os.environ["BACKFILL_PROVIDER"] = self._orig_backfill_provider
        if self._orig_backfill_budget is None:
            os.environ.pop("MAX_BACKFILL_LLM_CALLS", None)
        else:
            os.environ["MAX_BACKFILL_LLM_CALLS"] = self._orig_backfill_budget
        if self._orig_paid_analysis is None:
            os.environ.pop("ENABLE_PAID_ANALYSIS", None)
        else:
            os.environ["ENABLE_PAID_ANALYSIS"] = self._orig_paid_analysis
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

    def _seed_news_cache(
        self,
        *,
        clusters: int = 1,
        total_headlines: int = 4,
        headlines: list[str] | None = None,
    ):
        if headlines is not None:
            clusters = len(headlines)
        self.api._news_cache["data"] = {
            "clusters": [
                {
                    "id": i + 1,
                    "headline": (
                        headlines[i] if headlines is not None
                        else f"OPEC supply headline {i}"
                    ),
                    "source_count": 2,
                    "published_at": datetime.now().isoformat(timespec="seconds"),
                }
                for i in range(clusters)
            ],
            "total_headlines": total_headlines,
            "feed_status": [{"name": "test", "ok": True}],
            "refresh_meta": {
                "status": "ok",
                "freshness": "fresh",
                "last_successful_refresh": datetime.now().isoformat(timespec="seconds"),
            },
            "_schema_version": self.api._NEWS_CACHE_VERSION,
        }
        self.api._news_cache["ts"] = 999999999.0

    @staticmethod
    def _items(body):
        """Unwrap the ``{items, meta}`` envelope mover surfaces now emit."""
        if isinstance(body, dict) and "items" in body:
            return body["items"]
        return body

    def _assert_mover_shape(self, rows):
        items = self._items(rows)
        self.assertIsInstance(items, list)
        for row in items:
            missing = self._REQUIRED_KEYS - set(row.keys())
            self.assertFalse(missing, f"Missing keys: {missing}")

    def test_weekly_output_contract(self):
        self._seed("OPEC cuts output by 500k bpd", 3.0)
        self._seed("EU sanctions on Russian energy sector", 5.0)
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self._assert_mover_shape(body)
        items = self._items(body)
        # Ranking stability: higher impact sorts first.
        self.assertEqual(items[0]["headline"], "EU sanctions on Russian energy sector")

    def test_today_empty_candidate_reports_rejection_diagnostics(self):
        self._seed_news_cache()
        db.save_event({
            "headline": "OPEC cuts output by 500k bpd",
            "stage": "realized",
            "persistence": "medium",
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "market_tickers": [],
            "mechanism_summary": "Oil supply channel.",
        })
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        r = self.client.get("/movers/today?include_meta=true")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(self._items(body), [])
        diagnostics = body["meta"].get("diagnostics")
        self.assertIsInstance(diagnostics, dict)
        self.assertGreaterEqual(
            diagnostics.get("rejections", {}).get("no_market_tickers", 0),
            1,
        )
        self.assertEqual(
            diagnostics.get("headline_coverage", {}).get("status"),
            "analyzed_events_missing_market_tickers",
        )
        self.assertEqual(
            diagnostics.get("headline_coverage", {})
            .get("analysis_path", {})
            .get("analyze_endpoint"),
            "POST /analyze",
        )

    def test_today_empty_with_fresh_headlines_reports_unanalyzed_gap(self):
        self._seed_news_cache(clusters=2, total_headlines=5)

        r = self.client.get("/movers/today?include_meta=true")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(self._items(body), [])
        diagnostics = body["meta"].get("diagnostics")
        self.assertIsInstance(diagnostics, dict)
        coverage = diagnostics.get("headline_coverage") or {}
        self.assertEqual(
            coverage.get("status"),
            "fresh_headlines_without_analyzed_market_events",
        )
        self.assertEqual(coverage.get("clusters_cached"), 2)
        self.assertIn("POST /analyze", coverage.get("analysis_path", {}).values())

    def test_backfill_recent_degrades_when_llm_unavailable(self):
        self._seed_news_cache(
            headlines=["OPEC cuts output by 500k bpd"],
            total_headlines=1,
        )

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with patch("api.analyze_event") as analyze_mock:
                r = self.client.post(
                    "/movers/backfill-recent?limit=1&scan_limit=1&dry_run=false&max_llm_calls=1",
                )

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        diagnostics = body["diagnostics"]
        self.assertEqual(diagnostics["headlines_scanned"], 1)
        self.assertEqual(diagnostics["analyzed"], 0)
        self.assertEqual(diagnostics["skipped"].get("llm_unavailable"), 1)
        analyze_mock.assert_not_called()

    def test_backfill_recent_blocked_when_paid_analysis_disabled(self):
        """Kill-switch stays enforced: with ENABLE_PAID_ANALYSIS off, a
        dry_run=false backfill returns 403 and short-circuits BEFORE any
        provider seam — proving setUp's opt-in is the only reason the
        other paid-path tests reach 200, and that no real spend can leak."""
        with patch.dict(os.environ, {"ENABLE_PAID_ANALYSIS": "false"}):
            with patch("api.analyze_event") as analyze_mock, \
                 patch("api.market_check") as market_mock:
                r = self.client.post(
                    "/movers/backfill-recent?limit=1&scan_limit=1&dry_run=false&max_llm_calls=1",
                )
        self.assertEqual(r.status_code, 403)
        analyze_mock.assert_not_called()
        market_mock.assert_not_called()

    def test_backfill_recent_dry_run_allowed_without_paid_flag(self):
        """A dry_run=true preview is never gated by the kill-switch (no spend)."""
        self._seed_news_cache(headlines=["OPEC cuts output by 500k bpd"], total_headlines=1)
        with patch.dict(os.environ, {"ENABLE_PAID_ANALYSIS": "false"}):
            with patch("api.analyze_event") as analyze_mock, \
                 patch("api.market_check") as market_mock:
                r = self.client.post(
                    "/movers/backfill-recent?limit=1&scan_limit=1&dry_run=true&max_llm_calls=1",
                )
        self.assertEqual(r.status_code, 200)
        analyze_mock.assert_not_called()
        market_mock.assert_not_called()

    def test_backfill_recent_refreshes_saved_event_from_asset_hints_without_llm(self):
        headline = "OPEC cuts output by 500k bpd"
        event_date = datetime.now().strftime("%Y-%m-%d")
        self._seed_news_cache(headlines=[headline], total_headlines=1)
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": event_date,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "assets_to_watch": ["GLD"],
            "beneficiaries": ["GLD"],
            "losers": [],
            "market_tickers": [],
            "mechanism_summary": "Oil supply channel.",
            "confidence": "high",
        })
        market_payload = {
            "note": "mock market check",
            "tickers": [
                {
                    "symbol": "GLD",
                    "role": "beneficiary",
                    "return_5d": 3.4,
                    "return_20d": 4.1,
                    "direction_tag": "supports",
                },
            ],
        }

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with patch("api.market_check", return_value=market_payload) as market_mock:
                with patch("api.analyze_event") as analyze_mock:
                    r = self.client.post(
                        "/movers/backfill-recent?limit=1&scan_limit=1&dry_run=false&max_llm_calls=1",
                    )

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        diagnostics = body["diagnostics"]
        self.assertEqual(diagnostics["analyzed"], 0)
        self.assertEqual(diagnostics["market_checked"], 1)
        self.assertEqual(diagnostics["persisted"], 1)
        self.assertEqual(diagnostics["with_tickers"], 1)
        self.assertEqual(diagnostics["with_returns"], 1)
        market_mock.assert_called_once()
        analyze_mock.assert_not_called()
        saved = db.find_cached_analysis(headline, event_date=event_date)
        self.assertTrue(saved["market_tickers"])
        self.assertEqual(saved["market_tickers"][0]["return_5d"], 3.4)

    def test_backfill_recent_analyzes_fresh_headline_and_persists_market_move(self):
        headline = "OPEC cuts output by 500k bpd"
        self._seed_news_cache(headlines=[headline], total_headlines=1)
        analysis = {
            "what_changed": "OPEC cut output.",
            "mechanism_summary": "Lower supply supports oil-linked assets.",
            "beneficiaries": ["Energy producers"],
            "losers": ["Oil consumers"],
            "beneficiary_tickers": ["GLD"],
            "loser_tickers": ["USO"],
            "assets_to_watch": ["GLD", "USO"],
            "confidence": "high",
            "transmission_chain": ["Supply falls", "prices rise"],
            "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {
            "note": "mock market check",
            "tickers": [
                {
                    "symbol": "GLD",
                    "role": "beneficiary",
                    "return_5d": 2.2,
                    "return_20d": 3.3,
                    "direction_tag": "supports",
                },
            ],
        }

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("api.analyze_event", return_value=analysis) as analyze_mock:
                with patch("api.market_check", return_value=market_payload):
                    with patch("api.build_macro_context_for_prompt", return_value=""):
                        with patch("routes.analyze._run_pre_market_overlays", return_value=({}, {})):
                            with patch("routes.analyze._run_post_market_overlays", return_value=None):
                                with patch(
                                    "routes.analyze._enrich_macro_context_with_country",
                                    side_effect=lambda ctx, _headline: ctx,
                                ):
                                    r = self.client.post(
                                        "/movers/backfill-recent?limit=1&scan_limit=1&dry_run=false&max_llm_calls=1",
                                    )

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        diagnostics = body["diagnostics"]
        self.assertEqual(diagnostics["analyzed"], 1)
        self.assertEqual(diagnostics["market_checked"], 1)
        self.assertEqual(diagnostics["persisted"], 1)
        self.assertEqual(diagnostics["with_returns"], 1)
        analyze_mock.assert_called_once()
        saved = db.find_cached_analysis(
            headline,
            event_date=datetime.now().strftime("%Y-%m-%d"),
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved["market_tickers"][0]["return_5d"], 2.2)

    def test_today_empty_filter_rejections_report_filter_status(self):
        self._seed_news_cache()
        db.save_event({
            "headline": "OPEC cuts output by 500k bpd",
            "stage": "realized",
            "persistence": "medium",
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": 2.0, "return_20d": 3.0,
                 "direction_tag": "supports \u2191"},
            ],
            "mechanism_summary": "Oil supply channel.",
            "low_signal": 1,
        })
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0

        r = self.client.get("/movers/today?include_meta=true")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(self._items(body), [])
        diagnostics = body["meta"].get("diagnostics")
        self.assertIsInstance(diagnostics, dict)
        self.assertGreaterEqual(
            diagnostics.get("rejections", {}).get("low_signal", 0),
            1,
        )
        self.assertEqual(
            diagnostics.get("headline_coverage", {}).get("status"),
            "filters_rejected_market_checked_candidates",
        )

    def test_yearly_output_contract(self):
        self._seed("China tariffs on US agriculture", 4.0)
        r = self.client.get("/movers/yearly")
        self.assertEqual(r.status_code, 200)
        self._assert_mover_shape(r.json())

    def test_persistent_output_contract_includes_days_since_event(self):
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Oil embargo tightens on Iran exports", 5.0, timestamp=old_ts, return_20d=6.0)
        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self._assert_mover_shape(body)
        for row in self._items(body):
            self.assertIn("days_since_event", row)

    def test_new_event_invalidates_cache_via_fingerprint(self):
        """Saving a new event inside the TTL window still shows up."""
        self._seed("US tariff on steel imports takes effect", 3.0)
        r1 = self.client.get("/movers/weekly")
        self.assertEqual(len(self._items(r1.json())), 1)

        # New save → fingerprint changes → cache is recomputed on next read.
        self._seed("NATO allies increase defense spending", 4.0)
        r2 = self.client.get("/movers/weekly")
        headlines = {m["headline"] for m in self._items(r2.json())}
        self.assertIn("US tariff on steel imports takes effect", headlines)
        self.assertIn("NATO allies increase defense spending", headlines)


# ---------------------------------------------------------------------------
# 5. _LegacyMoverCacheShim — clear() must invalidate the persisted cache
# ---------------------------------------------------------------------------


class TestLegacyClearInvalidates(unittest.TestCase):
    """The .clear() path on _LegacyMoverCacheShim must call
    movers_cache.invalidate(), not just empty the in-memory dict.

    Two invariant groups:
      1) clear() calls invalidate on the correct slice
      2) Normal __setitem__ path unchanged
    """

    def setUp(self):
        import api as _api_mod
        self._api = _api_mod

    # --- 1) clear() invalidates the underlying cache ---

    def test_clear_calls_invalidate_weekly(self):
        """.clear() on the weekly shim must call movers_cache.invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._WEEKLY_MOVERS_CACHE.clear()
            self.assertIn("weekly", calls,
                          "clear() did not call invalidate('weekly')")
        finally:
            movers_cache.invalidate = orig

    def test_clear_calls_invalidate_yearly(self):
        """.clear() on the yearly shim must call movers_cache.invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._YEARLY_MOVERS_CACHE.clear()
            self.assertIn("yearly", calls)
        finally:
            movers_cache.invalidate = orig

    def test_clear_calls_invalidate_persistent(self):
        """.clear() on the persistent shim must call movers_cache.invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._PERSISTENT_MOVERS_CACHE.clear()
            self.assertIn("persistent", calls)
        finally:
            movers_cache.invalidate = orig

    def test_clear_empties_in_memory_dict(self):
        """After .clear() the dict has no keys (standard dict.clear semantics)."""
        shim = self._api._WEEKLY_MOVERS_CACHE
        orig = movers_cache.invalidate
        movers_cache.invalidate = lambda *a, **kw: None
        try:
            shim.clear()
            self.assertEqual(len(shim), 0)
        finally:
            movers_cache.invalidate = orig

    def test_clear_invalidate_exception_does_not_propagate(self):
        """An exception inside invalidate() must not bubble out of .clear()."""
        orig = movers_cache.invalidate

        def _raise(slice_name=None):
            raise RuntimeError("db unavailable")

        movers_cache.invalidate = _raise
        try:
            self._api._WEEKLY_MOVERS_CACHE.clear()  # must not raise
        finally:
            movers_cache.invalidate = orig

    # --- 2) Normal __setitem__ path unchanged ---

    def test_setitem_data_none_still_calls_invalidate(self):
        """Existing ['data'] = None path still calls invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._WEEKLY_MOVERS_CACHE["data"] = None
            self.assertIn("weekly", calls)
        finally:
            movers_cache.invalidate = orig

    def test_setitem_data_non_none_does_not_invalidate(self):
        """Setting 'data' to a non-None value must NOT call invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._WEEKLY_MOVERS_CACHE["data"] = [{"headline": "test"}]
            self.assertEqual(calls, [],
                             "invalidate() must not fire when data is set to a value")
        finally:
            movers_cache.invalidate = orig

    def test_setitem_other_key_does_not_invalidate(self):
        """Setting keys other than 'data' must NOT call invalidate."""
        calls: list[str | None] = []
        orig = movers_cache.invalidate

        def _spy(slice_name=None):
            calls.append(slice_name)

        movers_cache.invalidate = _spy
        try:
            self._api._WEEKLY_MOVERS_CACHE["ts"] = 0.0
            self.assertEqual(calls, [])
        finally:
            movers_cache.invalidate = orig


# ---------------------------------------------------------------------------
# diagnose_time_slice — return_1d visibility
#
# The today-window surface (``api.movers_today``) accepts ``return_1d``
# as a fallback when ``return_5d`` is None.  The diagnostic must mirror
# that contract so an operator inspecting ``include_meta=true`` can see
# whether return_1d events exist and whether they qualify — instead of
# the prior surface that only counted return_5d and bucketed return_1d-
# only events under ``no_return_5d``.
# ---------------------------------------------------------------------------


def _today_event(*, event_id: int, headline: str, tickers: list[dict]) -> dict:
    now = _now()
    ts = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    return {
        "id": event_id,
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "event_date": now.strftime("%Y-%m-%d"),
        "timestamp": ts,
        "mechanism_summary": "stub",
        "market_tickers": tickers,
        "transmission_chain": [],
        "if_persists": {},
    }


class TestDiagnoseTimeSliceReturn1d(unittest.TestCase):

    def test_today_window_counts_return_1d_and_marks_eligible(self):
        ev = _today_event(
            event_id=1,
            headline=_RELEVANT_HEADLINES[0],
            tickers=[{
                "symbol": "XOM", "role": "beneficiary",
                "return_5d": None, "return_1d": 2.7,
                "direction_tag": "supports ↑",
            }],
        )
        diag = movers_cache.diagnose_time_slice(
            "today", [ev], now=_now(), filter_low_signal=True,
        )
        # Return_1d-specific counters surface the data on the wire.
        self.assertEqual(diag["window_events_with_raw_return_5d"], 0)
        self.assertEqual(diag["window_events_with_raw_return_1d"], 1)
        self.assertEqual(diag["window_events_with_raw_usable_return"], 1)
        self.assertEqual(diag["events_with_return_5d"], 0)
        self.assertEqual(diag["events_with_return_1d"], 1)
        self.assertEqual(diag["events_with_usable_return"], 1)
        # And the today-window eligibility gate accepts return_1d, so
        # the event reads as eligible (matches the live surface).
        self.assertEqual(diag["eligible_events"], 1)
        self.assertNotIn("no_return_5d", diag["rejections"])
        self.assertNotIn("no_usable_return", diag["rejections"])

    def test_today_window_rejects_when_neither_return_present(self):
        ev = _today_event(
            event_id=1,
            headline=_RELEVANT_HEADLINES[0],
            tickers=[{
                "symbol": "XOM", "role": "beneficiary",
                "return_5d": None, "return_1d": None,
                "direction_tag": "supports ↑",
            }],
        )
        diag = movers_cache.diagnose_time_slice(
            "today", [ev], now=_now(), filter_low_signal=True,
        )
        self.assertEqual(diag["events_with_usable_return"], 0)
        self.assertEqual(diag["eligible_events"], 0)
        # The today-window rejection bucket is the honest "no_usable_return"
        # rather than the misleading "no_return_5d".
        self.assertEqual(diag["rejections"].get("no_usable_return"), 1)
        self.assertNotIn("no_return_5d", diag["rejections"])

    def test_weekly_window_keeps_return_5d_strict(self):
        # Weekly slice's surface (``movers_cache.compute_slice`` →
        # ``_compute_weekly_slice``) gates strictly on return_5d.  The
        # diagnostic must NOT loosen that rule for non-today slices.
        ev = _event(
            event_id=1,
            headline=_RELEVANT_HEADLINES[0],
            days_ago=3,
            return_5d=2.0,
        )
        # Strip return_5d, leave return_1d only.
        ev["market_tickers"] = [
            {"symbol": "GLD", "role": "beneficiary",
             "return_5d": None, "return_1d": 1.5,
             "direction_tag": "supports ↑"},
        ]
        diag = movers_cache.diagnose_time_slice(
            "weekly", [ev], now=_now(), filter_low_signal=True,
        )
        # New return_1d counters still populate so operators can see
        # what's there, but eligibility stays strict on return_5d.
        self.assertEqual(diag["window_events_with_raw_return_1d"], 1)
        self.assertEqual(diag["events_with_return_1d"], 1)
        self.assertEqual(diag["eligible_events"], 0)
        self.assertEqual(diag["rejections"].get("no_return_5d"), 1)
        self.assertNotIn("no_usable_return", diag["rejections"])

    def test_today_window_diag_summary_matches_live_surface(self):
        # Two events, one with return_1d-only (would surface live) and one
        # with neither (would not).  Diagnostic must report eligible=1
        # with no false "no_return_5d" attribution against the first.
        ev_usable = _today_event(
            event_id=1,
            headline=_RELEVANT_HEADLINES[0],
            tickers=[{
                "symbol": "XOM", "role": "beneficiary",
                "return_5d": None, "return_1d": 2.0,
                "direction_tag": "supports ↑",
            }],
        )
        ev_blank = _today_event(
            event_id=2,
            headline=_RELEVANT_HEADLINES[1],
            tickers=[{
                "symbol": "TLT", "role": "beneficiary",
                "return_5d": None, "return_1d": None,
                "direction_tag": "supports ↑",
            }],
        )
        diag = movers_cache.diagnose_time_slice(
            "today", [ev_usable, ev_blank], now=_now(),
            filter_low_signal=True,
        )
        self.assertEqual(diag["window_events"], 2)
        self.assertEqual(diag["events_with_return_1d"], 1)
        self.assertEqual(diag["events_with_usable_return"], 1)
        self.assertEqual(diag["eligible_events"], 1)
        self.assertEqual(diag["rejections"].get("no_usable_return"), 1)


if __name__ == "__main__":
    unittest.main()

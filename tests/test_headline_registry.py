"""Tests for headline_registry feature.

Run with:
    python -m unittest tests.test_headline_registry -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: F401  — resolve circular imports (routes.movers → api → routes.candidates)


class _RegistryTestBase(unittest.TestCase):
    """Per-test temp DB so cases never share state."""

    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        # Re-bind db.DB_FILE to a fresh file for this test, then re-init.
        import db
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = self.db_path
        db._db_ready = False
        db.init_db()
        self._db = db

    def tearDown(self) -> None:
        import db
        db.DB_FILE = self._orig_db_file
        db._db_ready = False
        try:
            os.unlink(self.db_path)
        except OSError:
            pass


class TestRegistrySchema(_RegistryTestBase):

    def test_upsert_creates_seen_row(self) -> None:
        import sqlite3
        now_iso = "2026-05-03T12:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 17)],
            now_iso,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM headline_registry "
                "WHERE source = ? AND title_key = ?",
                ("Reuters", "fed-cuts-rates"),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source"],        "Reuters")
        self.assertEqual(row["title_key"],     "fed-cuts-rates")
        self.assertEqual(row["cluster_id"],    17)
        self.assertEqual(row["state"],         "seen")
        self.assertEqual(row["first_seen_at"], now_iso)
        self.assertEqual(row["last_seen_at"],  now_iso)
        self.assertIsNone(row["event_id"])
        self.assertIsNone(row["impact_level"])
        self.assertIsNone(row["analyzed_at"])
        self.assertIsNone(row["expired_at"])
        self.assertIsNone(row["last_skip_reason"])

    def test_upsert_does_not_regress_state(self) -> None:
        import sqlite3
        now_iso = "2026-05-03T12:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 17)],
            now_iso,
        )
        # Promote to analyzed.
        self._db.update_registry_state(
            title_key="fed-cuts-rates",
            new_state="analyzed",
            event_id=42,
            impact_level="high",
            analyzed_at=now_iso,
        )
        # Re-ingest with later timestamp + different cluster_id.
        later_iso = "2026-05-03T13:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 99)],
            later_iso,
        )
        # State, event_id, impact_level, analyzed_at preserved;
        # cluster_id and last_seen_at refreshed; first_seen_at unchanged.
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM headline_registry "
                "WHERE source = ? AND title_key = ?",
                ("Reuters", "fed-cuts-rates"),
            ).fetchone()
        self.assertEqual(row["state"],         "analyzed")
        self.assertEqual(row["event_id"],      42)
        self.assertEqual(row["impact_level"],  "high")
        self.assertEqual(row["analyzed_at"],   now_iso)
        self.assertEqual(row["first_seen_at"], now_iso)
        self.assertEqual(row["last_seen_at"],  later_iso)   # bumped
        self.assertEqual(row["cluster_id"],    99)           # refreshed
        # And the state-counts view still reflects the analyzed row.
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("analyzed"), 1)
        self.assertEqual(counts.get("seen", 0), 0)


class TestIsExpiredLowImpact(unittest.TestCase):

    def setUp(self) -> None:
        # Pin a stable "now" for all cases.
        self.now = datetime(2026, 5, 10, 12, 0, 0)
        self._old = "2026-05-01T00:00:00"     # 9d before now → past 5d TTL
        self._fresh = "2026-05-09T00:00:00"   # 1d before now → within TTL

    def _row(self, impact: str | None, ts: str | None) -> dict:
        return {
            "conviction": {"impact_level": impact} if impact else {},
            "timestamp":  ts,
            "headline":   "test headline",
        }

    def test_low_with_old_registry_anchor_is_expired(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertTrue(is_expired_low_impact(
            self._row("low", self._fresh),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_low_with_fresh_registry_anchor_is_not_expired(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row("low", self._old),  # event ts old, but...
            registry_analyzed_at=self._fresh,  # ...registry says fresh
            now=self.now,
        ))

    def test_low_falls_back_to_event_timestamp(self) -> None:
        from headline_registry import is_expired_low_impact
        # No registry anchor: expiry uses event timestamp.
        self.assertTrue(is_expired_low_impact(
            self._row("low", self._old),
            registry_analyzed_at=None,
            now=self.now,
        ))

    def test_high_impact_never_expires(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row("high", self._old),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_missing_impact_returns_false(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row(None, self._old),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_env_override_shrinks_window(self) -> None:
        from headline_registry import is_expired_low_impact
        with patch.dict(
            os.environ,
            {"HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS": "1"},
        ):
            # 1d TTL: a 2-day-old row is now expired.
            two_days_old = (self.now - timedelta(days=2)).isoformat(
                timespec="seconds",
            )
            self.assertTrue(is_expired_low_impact(
                self._row("low", two_days_old),
                registry_analyzed_at=None,
                now=self.now,
            ))


class TestIngestionWritesRegistry(_RegistryTestBase):

    def _fake_records(self) -> list[dict]:
        return [
            {"source": "Reuters",  "title": "Fed cuts rates by 25bp",
             "url": "u1", "published_at": "2026-05-03T10:00:00"},
            {"source": "Bloomberg", "title": "Fed cuts rates by 25bp",
             "url": "u2", "published_at": "2026-05-03T10:05:00"},
        ]

    def _stub_cluster_fn(self, records: list[dict]) -> list[dict]:
        return [{
            "headline":     records[0]["title"],
            "source_count": len(records),
            "sources":      [{"name": r["source"]} for r in records],
            "published_at": records[-1]["published_at"],
        }]

    def test_ingest_writes_seen_rows(self) -> None:
        import news_cluster_store
        records = self._fake_records()
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 10, 30, 0),
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("seen"), 2)

    def test_reingest_preserves_analyzed_state(self) -> None:
        import news_cluster_store
        records = self._fake_records()
        # First ingest → 'seen'.
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 10, 30, 0),
        )
        # Promote to 'analyzed' for the shared title_key.
        from news_sources import _dedup_key
        tk = _dedup_key(records[0]["title"])
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=99,
            impact_level="high",
            analyzed_at="2026-05-03T11:00:00",
        )
        # Re-ingest → state must stay 'analyzed' for both rows.
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 12, 0, 0),
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("analyzed"), 2)
        self.assertEqual(counts.get("seen", 0), 0)


class TestBackfillRegistryShortCircuit(_RegistryTestBase):
    """Stub the analyze + market-check + provider helpers so tests
    measure routing decisions, not LLM behaviour."""

    def _stub_route_for_test(self, monkey: dict) -> None:
        """Replace heavy collaborators in routes.movers with stubs.

        ``monkey`` is a dict mapping attr name -> stub callable.  Tests
        that need to count LLM calls inspect the registry post-call.
        """
        import routes.movers as rm
        self._original = {}
        for name, value in monkey.items():
            self._original[name] = getattr(rm, name, None)
            setattr(rm, name, value)
        self._rm = rm

    def tearDown(self) -> None:
        if hasattr(self, "_rm") and hasattr(self, "_original"):
            for name, value in self._original.items():
                if value is None:
                    if hasattr(self._rm, name):
                        delattr(self._rm, name)
                else:
                    setattr(self._rm, name, value)
        super().tearDown()

    def _seed_registry_analyzed(self, headline: str) -> str:
        from news_sources import _dedup_key
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk, 1)], "2026-05-01T10:00:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=1,
            impact_level="high",
            analyzed_at="2026-05-01T10:30:00",
        )
        return tk

    def test_pre_llm_check_skips_analyzed(self) -> None:
        headline = "Fed cuts rates by 25bp"
        self._seed_registry_analyzed(headline)

        from routes.movers import movers_backfill_recent
        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "analyzed": True, "with_returns": True,
                    "with_tickers": True, "persisted": True, "ticker_count": 1,
                    "event_id": 99, "conviction": {"impact_level": "high"}}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
            "_headline_is_market_relevant":  lambda *_: True,
        })

        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(analyze_calls["count"], 0)
        skipped = result.get("diagnostics", {}).get("skipped", {})
        self.assertEqual(skipped.get("registry_already_analyzed"), 1)

    def test_pre_llm_check_skips_expired_low(self) -> None:
        from news_sources import _dedup_key
        headline = "Old low-impact print"
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk, 1)], "2026-04-25T10:00:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=1,
            impact_level="low",
            analyzed_at="2026-04-25T10:30:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="expired_low_impact",
            expired_at="2026-05-03T00:00:00",
        )

        from routes.movers import movers_backfill_recent
        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "analyzed": True, "with_returns": True,
                    "with_tickers": True, "persisted": True, "ticker_count": 1,
                    "event_id": 99}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
            "_headline_is_market_relevant":  lambda *_: True,
        })

        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=240,
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(analyze_calls["count"], 0)
        skipped = result.get("diagnostics", {}).get("skipped", {})
        self.assertEqual(skipped.get("registry_expired_low_impact"), 1)

    def test_force_reanalyze_overrides_registry_skip(self) -> None:
        headline = "Fed cuts rates by 25bp"
        self._seed_registry_analyzed(headline)

        from routes.movers import movers_backfill_recent
        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "analyzed": True, "with_returns": True,
                    "with_tickers": True, "persisted": True, "ticker_count": 1,
                    "event_id": 99, "conviction": {"impact_level": "high"}}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
            "_headline_is_market_relevant":  lambda *_: True,
        })

        movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=True,   # <-- override
            include_low_signal=False,
        )
        self.assertGreaterEqual(analyze_calls["count"], 1)

    def test_skip_reason_stamped_without_state_regression(self) -> None:
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_recent
        import sqlite3

        headline = "Sports team wins championship"
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("ESPN", tk, 1)], "2026-05-03T08:00:00",
        )

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 1,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "ESPN"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":           fake_payload,
            "_max_backfill_llm_calls":        lambda: 5,
            "_backfill_dry_run_default":      lambda: True,
            "_llm_available":                 lambda *_: True,
            "_headline_is_market_relevant":   lambda *_: False,
        })

        movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
        )
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state, last_skip_reason FROM headline_registry "
                "WHERE title_key = ?",
                (tk,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "seen")
        self.assertEqual(row[1], "irrelevant_headline")


class TestMoversTodayExpiry(_RegistryTestBase):

    def _seed_two_rows(self) -> tuple[dict, dict]:
        """Returns (fresh_low, expired_low) row dicts in /movers/today shape."""
        fresh = {
            "id":         1,
            "headline":   "Fresh low-impact print",
            "timestamp":  "2026-05-09T12:00:00",
            "conviction": {"impact_level": "low"},
        }
        expired = {
            "id":         2,
            "headline":   "Old low-impact print",
            "timestamp":  "2026-04-25T12:00:00",
            "conviction": {"impact_level": "low"},
        }
        from news_sources import _dedup_key
        for row in (fresh, expired):
            tk = _dedup_key(row["headline"])
            self._db.upsert_headline_registry_seen(
                [("Reuters", tk, 1)], row["timestamp"],
            )
            self._db.update_registry_state(
                title_key=tk,
                new_state="analyzed",
                event_id=row["id"],
                impact_level="low",
                analyzed_at=row["timestamp"],
            )
        return fresh, expired

    def test_movers_today_hides_expired_low(self) -> None:
        from headline_registry import filter_expired_low_impact
        fresh, expired = self._seed_two_rows()
        now = datetime(2026, 5, 10, 12, 0, 0)
        survivors = filter_expired_low_impact([fresh, expired], now=now)
        self.assertEqual([r["id"] for r in survivors], [1])
        # Expired row should now be stamped.
        import sqlite3
        from news_sources import _dedup_key
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state, expired_at FROM headline_registry "
                "WHERE title_key = ?",
                (_dedup_key(expired["headline"]),),
            ).fetchone()
        self.assertEqual(row[0], "expired_low_impact")
        self.assertIsNotNone(row[1])

    def test_filter_runs_on_cached_payload(self) -> None:
        """Calling the filter twice on the same list returns the same
        survivors both times (idempotent stamp; no double-counting)."""
        from headline_registry import filter_expired_low_impact
        fresh, expired = self._seed_two_rows()
        now = datetime(2026, 5, 10, 12, 0, 0)
        first  = filter_expired_low_impact([fresh, expired], now=now)
        second = filter_expired_low_impact([fresh, expired], now=now)
        self.assertEqual([r["id"] for r in first],  [1])
        self.assertEqual([r["id"] for r in second], [1])


class TestEventsListingExpiry(_RegistryTestBase):

    def test_listing_hides_expired_low(self) -> None:
        # Filter helper-level test: rows shaped like /events listing rows.
        from headline_registry import filter_expired_low_impact
        rows = [
            {"id": 1, "headline": "Fresh low",
             "timestamp": "2026-05-09T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 2, "headline": "Expired low",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "low"}},
        ]
        survivors = filter_expired_low_impact(
            rows, now=datetime(2026, 5, 10, 12, 0, 0),
        )
        self.assertEqual([r["id"] for r in survivors], [1])

    def test_total_reflects_post_expiry_universe(self) -> None:
        """The /events listing returns total = len(post-filter rows)."""
        rows = [
            {"id": 1, "headline": "Fresh low",
             "timestamp": "2026-05-09T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 2, "headline": "Expired low",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 3, "headline": "High impact",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "high"}},
        ]
        from headline_registry import filter_expired_low_impact
        survivors = filter_expired_low_impact(
            rows, now=datetime(2026, 5, 10, 12, 0, 0),
        )
        self.assertEqual(len(survivors), 2)
        self.assertEqual({r["id"] for r in survivors}, {1, 3})

    def test_detail_does_not_call_filter(self) -> None:
        """Sanity check: get_event_detail handler does not reference
        the expiry filter (frozen CLAUDE.md contract)."""
        import inspect
        import routes.events as ev
        source = inspect.getsource(ev.get_event_detail)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact", source)


class TestRegistryDiagnostics(_RegistryTestBase):

    def _seed_cluster(
        self, cluster_id: int, headline: str, source_count: int,
        has_asset_terms: bool = False,
    ) -> None:
        import json as _json
        import sqlite3
        payload = _json.dumps({
            "headline": headline,
            "source_count": source_count,
            "has_asset_terms": has_asset_terms,
        })
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO news_clusters "
                "(id, headline, payload_json, records_json, "
                " latest_published_at, updated_at) "
                "VALUES (?, ?, ?, '[]', ?, ?)",
                (cluster_id, headline, payload,
                 "2026-05-03T08:00:00", "2026-05-03T08:00:00"),
            )

    def test_state_counts_match_synthetic_flow(self) -> None:
        from news_sources import _dedup_key
        self._db.upsert_headline_registry_seen(
            [("Reuters",  _dedup_key("h1"), None),
             ("Bloomberg", _dedup_key("h2"), None)],
            "2026-05-03T08:00:00",
        )
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("h3"), None)],
            "2026-05-03T09:00:00",
        )
        self._db.update_registry_state(
            title_key=_dedup_key("h3"),
            new_state="analyzed",
            event_id=1,
            impact_level="high",
            analyzed_at="2026-05-03T09:30:00",
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("seen"),     2)
        self.assertEqual(counts.get("analyzed"), 1)

    def test_eligible_unanalyzed_candidates_ranked_by_source_count(self) -> None:
        from news_sources import _dedup_key
        self._seed_cluster(10, "Major story", source_count=7)
        self._seed_cluster(11, "Minor story", source_count=1)
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("Major story"), 10)],
            "2026-05-03T08:00:00",
        )
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("Minor story"), 11)],
            "2026-05-03T08:01:00",
        )
        candidates = self._db.load_eligible_unanalyzed_candidates(limit=10)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["headline"], "Major story")
        self.assertEqual(candidates[0]["source_count"], 7)
        self.assertEqual(candidates[1]["headline"], "Minor story")


class TestRegistryDiagnosticsRoute(_RegistryTestBase):

    def test_endpoint_returns_expected_shape(self) -> None:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
        resp = client.get("/registry/diagnostics")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("state_counts",                   body)
        self.assertIn("skip_reason_counts",             body)
        self.assertIn("last_analyzed_at",               body)
        self.assertIn("expired_count_24h",              body)
        self.assertIn("eligible_unanalyzed_candidates", body)
        self.assertIsInstance(
            body["eligible_unanalyzed_candidates"], list,
        )


class TestRegistryDiagnosticsDemoReadiness(_RegistryTestBase):
    """Demo-readiness counts surface eligible / analyzed / surfaced /
    expired in a single ``counts`` block, plus ``last_surfaced_at`` at
    the top level when at least one row sits in the surfaced state."""

    def _seed(self, source: str, headline: str, ts: str) -> str:
        from news_sources import _dedup_key
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen([(source, tk, None)], ts)
        return tk

    def test_counts_block_carries_all_demo_readiness_keys(self) -> None:
        from datetime import datetime, timedelta
        from fastapi.testclient import TestClient
        from api import app

        now = datetime.now()
        recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        old    = (now - timedelta(hours=48)).isoformat(timespec="seconds")

        # Eligible / unanalyzed
        self._seed("Reuters",   "eligible-1", recent)
        self._seed("Bloomberg", "eligible-2", recent)
        # Analyzed recently
        tk_a = self._seed("Reuters", "analyzed-recent", recent)
        self._db.update_registry_state(
            title_key=tk_a, new_state="analyzed",
            event_id=10, impact_level="high", analyzed_at=recent,
        )
        # Analyzed but outside the recent window
        tk_old = self._seed("Reuters", "analyzed-old", old)
        self._db.update_registry_state(
            title_key=tk_old, new_state="analyzed",
            event_id=11, impact_level="high", analyzed_at=old,
        )
        # Surfaced recently — last_seen_at is the surfaced proxy
        tk_s = self._seed("Reuters", "surfaced-recent", recent)
        self._db.update_registry_state(
            title_key=tk_s, new_state="surfaced",
            event_id=12, impact_level="high", analyzed_at=recent,
        )
        # Expired low impact
        tk_e = self._seed("Reuters", "expired-row", old)
        self._db.update_registry_state(
            title_key=tk_e, new_state="analyzed",
            event_id=13, impact_level="low", analyzed_at=old,
        )
        self._db.update_registry_state(
            title_key=tk_e, new_state="expired_low_impact",
            expired_at=old,
        )

        body = TestClient(app).get("/registry/diagnostics").json()

        self.assertIn("counts", body)
        counts = body["counts"]
        for key in (
            "eligible_unanalyzed", "analyzed_recent",
            "surfaced_recent",     "expired_low_impact",
        ):
            self.assertIn(key, counts)
            self.assertIsInstance(counts[key], int)

        self.assertEqual(counts["eligible_unanalyzed"], 2)
        # Recent analyzed window covers analyzed-recent + surfaced-recent.
        # The expired row was analyzed in the old window AND has since
        # advanced to expired_low_impact, so it is excluded by state.
        self.assertEqual(counts["analyzed_recent"], 2)
        self.assertEqual(counts["surfaced_recent"], 1)
        self.assertEqual(counts["expired_low_impact"], 1)
        self.assertIn("last_surfaced_at", body)
        self.assertEqual(body["last_surfaced_at"], recent)
        self.assertIn("recent_window_hours", body)
        self.assertEqual(body["recent_window_hours"], 24)

    def test_last_surfaced_at_none_when_no_surfaced_rows(self) -> None:
        from fastapi.testclient import TestClient
        from api import app
        # Seed a single eligible row only — no surfaced state in registry.
        self._seed("Reuters", "eligible-only", "2026-05-03T10:00:00")
        body = TestClient(app).get("/registry/diagnostics").json()
        self.assertIsNone(body["last_surfaced_at"])
        self.assertEqual(body["counts"]["surfaced_recent"], 0)

    def test_recent_hours_param_widens_window(self) -> None:
        """``recent_hours=72`` covers a row analyzed 48h ago that the
        default 24h window excludes — proves the param is wired through."""
        from datetime import datetime, timedelta
        from fastapi.testclient import TestClient
        from api import app
        ts_48h = (
            datetime.now() - timedelta(hours=48)
        ).isoformat(timespec="seconds")
        tk = self._seed("Reuters", "analyzed-48h-ago", ts_48h)
        self._db.update_registry_state(
            title_key=tk, new_state="analyzed",
            event_id=20, impact_level="high", analyzed_at=ts_48h,
        )
        client = TestClient(app)
        default_body = client.get("/registry/diagnostics").json()
        wide_body    = client.get(
            "/registry/diagnostics?recent_hours=72",
        ).json()
        self.assertEqual(default_body["counts"]["analyzed_recent"], 0)
        self.assertEqual(wide_body["counts"]["analyzed_recent"], 1)
        self.assertEqual(wide_body["recent_window_hours"], 72)


class TestPersistentYearlyUntouched(unittest.TestCase):
    """Regression: /movers/persistent and /movers/yearly handlers must
    NOT call the expiry filter.  Source-level inspection guard so a
    future refactor that accidentally wires the filter in is caught."""

    def test_persistent_handler_does_not_use_expiry_filter(self) -> None:
        import inspect
        import routes.movers as rm
        source = inspect.getsource(rm.movers_persistent)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact",     source)

    def test_yearly_handler_does_not_use_expiry_filter(self) -> None:
        import inspect
        import routes.movers as rm
        source = inspect.getsource(rm.movers_yearly)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact",     source)

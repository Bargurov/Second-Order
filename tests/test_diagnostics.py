"""Tests for ``GET /diagnostics/data-quality``.

Skeleton-level contract:

  * Endpoint returns 200 on a fresh DB with no rows seeded.
  * Each top-level block carries an ``available`` flag so the consumer
    can branch on partial state.
  * ``registry_counts`` reflects the demo-readiness counts even when
    the registry has zero rows.
  * ``archive_counts`` reflects ``db.get_events_fingerprint()``.
  * ``snapshot_freshness`` reads the warm SnapshotStore without
    refreshing — patched to be empty so the test never touches a
    provider.
  * Block-level failure isolation: when one helper raises, only that
    block's ``available`` flips false; the other blocks are intact.

No LLM, no yfinance, no provider, no DB writes.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(api.app)


class _Base(unittest.TestCase):

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_diag_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()
        # Snapshot store + news cache: empty for deterministic readings.
        from market_snapshots import get_store
        get_store().clear()
        api._news_cache["data"] = None
        api._news_cache["ts"] = 0.0

    def tearDown(self) -> None:
        from market_snapshots import get_store
        get_store().clear()
        api._news_cache["data"] = None
        api._news_cache["ts"] = 0.0
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestDataQualityEndpointShape(_Base):

    def test_returns_200_with_full_block_keyset(self) -> None:
        r = client.get("/diagnostics/data-quality")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in (
            "registry_counts", "archive_counts",
            "snapshot_freshness", "candidate_queue_counts",
            "latest_analyzed_at",
        ):
            self.assertIn(key, body, f"missing top-level key: {key}")
        for block_key in (
            "registry_counts", "archive_counts",
            "snapshot_freshness", "candidate_queue_counts",
        ):
            self.assertIn(
                "available", body[block_key],
                f"block {block_key!r} missing ``available`` flag",
            )

    def test_archive_counts_reflect_fingerprint(self) -> None:
        # Cold DB: 0 events.
        body = client.get("/diagnostics/data-quality").json()
        ac = body["archive_counts"]
        self.assertTrue(ac["available"])
        self.assertEqual(ac["total"],  0)
        self.assertEqual(ac["max_id"], 0)

        # Seed one event and confirm the count moves.
        db.save_event({
            "headline":   "Stub event for archive_counts",
            "stage":      "realized",
            "persistence":"medium",
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "market_tickers": [],
        })
        body = client.get("/diagnostics/data-quality").json()
        self.assertEqual(body["archive_counts"]["total"], 1)
        self.assertGreaterEqual(body["archive_counts"]["max_id"], 1)

    def test_registry_counts_present_on_empty_registry(self) -> None:
        body = client.get("/diagnostics/data-quality").json()
        rc = body["registry_counts"]
        self.assertTrue(rc["available"])
        # Demo-readiness shape — zeros across the board on a fresh DB.
        for k in ("eligible_unanalyzed", "analyzed_recent",
                  "surfaced_recent", "expired_low_impact"):
            self.assertEqual(rc["counts"].get(k, 0), 0)
        self.assertIsNone(body["latest_analyzed_at"])

    def test_snapshot_freshness_is_zero_cost_on_empty_store(self) -> None:
        # Patch ``market_check._fetch`` to a raiser to prove the
        # endpoint never refreshes — the snapshot store is empty and
        # must stay so.
        with patch("market_check._fetch",
                   side_effect=AssertionError("must not refresh")):
            body = client.get("/diagnostics/data-quality").json()
        sf = body["snapshot_freshness"]
        self.assertTrue(sf["available"])
        self.assertEqual(sf["total"],       0)
        self.assertEqual(sf["fresh"],       0)
        self.assertEqual(sf["stale"],       0)
        self.assertEqual(sf["unavailable"], 0)

    def test_candidate_queue_counts_zero_on_empty_news_cache(self) -> None:
        body = client.get("/diagnostics/data-quality").json()
        q = body["candidate_queue_counts"]
        self.assertTrue(q["available"])
        for k in ("eligible", "skipped",
                  "already_analyzed", "expired_low_impact"):
            self.assertEqual(q.get(k, 0), 0)


class TestDataQualityBlockIsolation(_Base):

    def test_archive_block_failure_does_not_break_response(self) -> None:
        # Simulate a fingerprint-helper crash: ``archive_counts`` flips
        # to ``available=false`` while every other block stays intact.
        with patch("db.get_events_fingerprint",
                   side_effect=RuntimeError("disk gone")):
            r = client.get("/diagnostics/data-quality")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["archive_counts"]["available"])
        # Other blocks unaffected.
        self.assertTrue(body["registry_counts"]["available"])
        self.assertTrue(body["snapshot_freshness"]["available"])
        self.assertTrue(body["candidate_queue_counts"]["available"])

    def test_registry_block_failure_isolated(self) -> None:
        with patch("routes.diagnostics.compose_diagnostics",
                   side_effect=RuntimeError("registry fail")):
            r = client.get("/diagnostics/data-quality")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["registry_counts"]["available"])
        self.assertIsNone(body["latest_analyzed_at"])
        # Other blocks still computed normally.
        self.assertTrue(body["archive_counts"]["available"])
        self.assertTrue(body["snapshot_freshness"]["available"])


class _ConfigHealthBase(_Base):
    """Saves + restores every env var the config-health endpoint
    reads so cases never leak state across the suite."""

    _MANAGED_ENV_VARS = (
        "ENABLE_PAID_ANALYSIS",
        "BACKFILL_DRY_RUN_DEFAULT",
        "MOVERS_BACKFILL_DRY_RUN",
        "MAX_BACKFILL_LLM_CALLS",
        "MOVERS_BACKFILL_MAX_LLM_CALLS",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    )

    def setUp(self) -> None:
        super().setUp()
        self._orig_env = {
            k: os.environ.get(k) for k in self._MANAGED_ENV_VARS
        }
        # Wipe to a clean baseline — tests opt into specific flags.
        for k in self._MANAGED_ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


class TestConfigHealthShape(_ConfigHealthBase):

    def test_returns_required_keys_with_safe_defaults(self) -> None:
        body = client.get("/diagnostics/config-health").json()
        for key in (
            "paid_analysis_enabled", "backfill_dry_run_default",
            "max_backfill_llm_calls",
            "anthropic_key_present", "openai_key_present",
            "warnings",
        ):
            self.assertIn(key, body, f"missing key: {key}")
        # Safe defaults: paid disabled, dry-run on, no key present.
        self.assertFalse(body["paid_analysis_enabled"])
        self.assertTrue(body["backfill_dry_run_default"])
        self.assertFalse(body["anthropic_key_present"])
        self.assertFalse(body["openai_key_present"])
        self.assertIsInstance(body["warnings"], list)

    def test_response_never_contains_secret_bytes(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-supersecret-do-not-leak"
        os.environ["OPENAI_API_KEY"]    = "sk-openai-also-secret"
        raw = client.get("/diagnostics/config-health").text
        self.assertNotIn("sk-ant-supersecret-do-not-leak", raw)
        self.assertNotIn("sk-openai-also-secret",         raw)
        body = client.get("/diagnostics/config-health").json()
        # Booleans only — keys reported as present without leaking bytes.
        self.assertTrue(body["anthropic_key_present"])
        self.assertTrue(body["openai_key_present"])

    def test_placeholder_keys_are_treated_as_absent(self) -> None:
        # The ``_llm_available`` helper rejects placeholder values like
        # "your_api_key_here" so a fresh ``.env.example`` setup never
        # reports a false-positive present-key.
        os.environ["ANTHROPIC_API_KEY"] = "your_anthropic_api_key_here"
        body = client.get("/diagnostics/config-health").json()
        self.assertFalse(body["anthropic_key_present"])


class TestConfigHealthWarnings(_ConfigHealthBase):

    def test_no_warnings_on_safe_defaults(self) -> None:
        body = client.get("/diagnostics/config-health").json()
        self.assertEqual(body["warnings"], [])

    def test_paid_enabled_but_no_keys_warns(self) -> None:
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        body = client.get("/diagnostics/config-health").json()
        joined = " ".join(body["warnings"])
        self.assertIn("no provider API key", joined)

    def test_paid_enabled_with_zero_cap_warns(self) -> None:
        os.environ["ENABLE_PAID_ANALYSIS"]    = "true"
        os.environ["MAX_BACKFILL_LLM_CALLS"]  = "0"
        os.environ["ANTHROPIC_API_KEY"]       = "sk-real-key"
        body = client.get("/diagnostics/config-health").json()
        joined = " ".join(body["warnings"])
        self.assertIn("max_backfill_llm_calls=0", joined)
        self.assertEqual(body["max_backfill_llm_calls"], 0)

    def test_paid_enabled_high_cap_no_dryrun_warns(self) -> None:
        os.environ["ENABLE_PAID_ANALYSIS"]      = "true"
        os.environ["MAX_BACKFILL_LLM_CALLS"]    = "20"
        os.environ["BACKFILL_DRY_RUN_DEFAULT"]  = "false"
        os.environ["ANTHROPIC_API_KEY"]         = "sk-real-key"
        body = client.get("/diagnostics/config-health").json()
        joined = " ".join(body["warnings"])
        self.assertIn("could spend up to 20 LLM calls", joined)

    def test_paid_disabled_silences_warnings(self) -> None:
        # Even a wide-open cap + no key is not a warning while the
        # server-side kill-switch is off — that env path can't spend.
        os.environ["MAX_BACKFILL_LLM_CALLS"]    = "20"
        os.environ["BACKFILL_DRY_RUN_DEFAULT"]  = "false"
        body = client.get("/diagnostics/config-health").json()
        self.assertFalse(body["paid_analysis_enabled"])
        self.assertEqual(body["warnings"], [])


# ---------------------------------------------------------------------------
# /diagnostics/archive-stats — zero-cost archive aggregates
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3  # noqa: E402


_ARCHIVE_TOP_KEYS = (
    "total_events",
    "events_with_tickers",
    "events_with_returns",
    "events_by_stage",
    "events_by_persistence",
    "events_by_thesis_state",
    "market_checked_count",
    "latest_event_timestamp",
)

_ARCHIVE_BLOCKS_WITH_AVAILABLE = (
    "total_events",
    "events_with_tickers",
    "events_with_returns",
    "events_by_stage",
    "events_by_persistence",
    "events_by_thesis_state",
    "market_checked_count",
)


class _ArchiveBase(_Base):
    def setUp(self) -> None:
        super().setUp()
        self._seed_counter = 0

    def _seed(self, **overrides) -> None:
        # ``save_event`` dedups by headline; give each row a unique headline
        # so seed() actually inserts every time.
        self._seed_counter += 1
        event = {
            "headline":       f"Stub headline {self._seed_counter} {uuid.uuid4().hex[:8]}",
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     datetime.now().strftime("%Y-%m-%d"),
            "market_tickers": [],
        }
        event.update(overrides)
        db.save_event(event)


class TestArchiveStatsShape(_ArchiveBase):
    def test_returns_200_with_full_top_keyset(self) -> None:
        r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ARCHIVE_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_each_block_has_available_flag(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        for key in _ARCHIVE_BLOCKS_WITH_AVAILABLE:
            self.assertIn(
                "available", body[key],
                f"block {key!r} missing ``available`` flag",
            )


class TestArchiveStatsEmptyDB(_ArchiveBase):
    def test_total_events_zero(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertTrue(body["total_events"]["available"])
        self.assertEqual(body["total_events"]["count"], 0)

    def test_events_with_tickers_zero(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertTrue(body["events_with_tickers"]["available"])
        self.assertEqual(body["events_with_tickers"]["count"], 0)

    def test_events_with_returns_zero(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertTrue(body["events_with_returns"]["available"])
        self.assertEqual(body["events_with_returns"]["count"], 0)

    def test_market_checked_count_zero(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertTrue(body["market_checked_count"]["available"])
        self.assertEqual(body["market_checked_count"]["count"], 0)

    def test_groupings_empty_dicts(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertTrue(body["events_by_stage"]["available"])
        self.assertEqual(body["events_by_stage"]["counts"], {})
        self.assertTrue(body["events_by_persistence"]["available"])
        self.assertEqual(body["events_by_persistence"]["counts"], {})

    def test_latest_event_timestamp_none(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        self.assertIsNone(body["latest_event_timestamp"])

    def test_thesis_state_block_present_with_zero_counts(self) -> None:
        body = client.get("/diagnostics/archive-stats").json()
        block = body["events_by_thesis_state"]
        self.assertIn("available", block)
        if block["available"]:
            counts = block["counts"]
            self.assertIsInstance(counts, dict)
            self.assertEqual(sum(counts.values()), 0)


class TestArchiveStatsSeededRows(_ArchiveBase):
    def test_total_events_increments(self) -> None:
        self._seed()
        self._seed()
        body = client.get("/diagnostics/archive-stats").json()
        self.assertEqual(body["total_events"]["count"], 2)

    def test_events_with_tickers_counts_only_non_empty(self) -> None:
        self._seed(market_tickers=[])
        self._seed(market_tickers=[{"symbol": "AAPL"}])
        body = client.get("/diagnostics/archive-stats").json()
        self.assertEqual(body["events_with_tickers"]["count"], 1)
        # Tickers without any numeric return → excluded.
        self.assertEqual(body["events_with_returns"]["count"], 0)

    def test_events_with_returns_requires_numeric_return_value(self) -> None:
        self._seed(market_tickers=[{"symbol": "AAPL", "return_5d": 1.23}])
        self._seed(market_tickers=[{"symbol": "MSFT", "return_5d": None}])
        self._seed(market_tickers=[{"symbol": "NVDA", "return_1d": -0.4}])
        body = client.get("/diagnostics/archive-stats").json()
        self.assertEqual(body["events_with_tickers"]["count"], 3)
        self.assertEqual(body["events_with_returns"]["count"], 2)

    def test_events_by_stage_groups_correctly(self) -> None:
        self._seed(stage="realized")
        self._seed(stage="realized")
        self._seed(stage="anticipation")
        body = client.get("/diagnostics/archive-stats").json()
        counts = body["events_by_stage"]["counts"]
        self.assertEqual(counts.get("realized"),    2)
        self.assertEqual(counts.get("anticipation"), 1)

    def test_events_by_persistence_groups_correctly(self) -> None:
        self._seed(persistence="medium")
        self._seed(persistence="structural")
        self._seed(persistence="structural")
        body = client.get("/diagnostics/archive-stats").json()
        counts = body["events_by_persistence"]["counts"]
        self.assertEqual(counts.get("medium"),     1)
        self.assertEqual(counts.get("structural"), 2)

    def test_market_checked_count_uses_last_market_check_at(self) -> None:
        # ``save_event`` auto-stamps ``last_market_check_at``; clear one
        # row directly via SQL so the count distinguishes stamped from
        # unstamped rows.  No provider call, no market_check invocation.
        self._seed()
        self._seed()
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET last_market_check_at = NULL "
                "WHERE id = (SELECT MIN(id) FROM events)"
            )
            conn.commit()
        body = client.get("/diagnostics/archive-stats").json()
        self.assertEqual(body["market_checked_count"]["count"], 1)

    def test_latest_event_timestamp_is_max(self) -> None:
        self._seed()
        self._seed()
        body = client.get("/diagnostics/archive-stats").json()
        ts = body["latest_event_timestamp"]
        self.assertIsInstance(ts, str)
        self.assertGreater(len(ts), 0)


class TestArchiveStatsNoMutation(_ArchiveBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        self._seed()
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/archive-stats")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        self._seed(
            stage="realized", persistence="structural",
            market_tickers=[{"symbol": "AAPL", "return_5d": 1.0}],
        )
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [dict(r) for r in
                      conn.execute("SELECT * FROM events").fetchall()]
        client.get("/diagnostics/archive-stats")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [dict(r) for r in
                     conn.execute("SELECT * FROM events").fetchall()]
        self.assertEqual(before, after)


class TestArchiveStatsZeroCostSeams(_ArchiveBase):
    """Endpoint must not invoke market_check / yfinance / provider seams."""

    def test_market_check_fetch_is_not_called(self) -> None:
        self._seed(market_tickers=[{"symbol": "AAPL", "return_5d": 1.0}])
        with patch(
            "market_check._fetch",
            side_effect=AssertionError("must not call market_check._fetch"),
        ):
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_check_one_ticker_is_not_called(self) -> None:
        self._seed(market_tickers=[{"symbol": "AAPL", "return_5d": 1.0}])
        with patch(
            "market_check._check_one_ticker",
            side_effect=AssertionError("must not call _check_one_ticker"),
        ):
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_data_provider_is_not_called(self) -> None:
        self._seed(market_tickers=[{"symbol": "AAPL", "return_5d": 1.0}])
        try:
            import market_data
            target = "market_data.get_provider"
            patched = hasattr(market_data, "get_provider")
        except ImportError:
            patched = False
        if patched:
            with patch(
                target,
                side_effect=AssertionError("must not call provider"),
            ):
                r = client.get("/diagnostics/archive-stats")
        else:
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)


class TestArchiveStatsBlockIsolation(_ArchiveBase):
    def test_total_events_failure_does_not_break_response(self) -> None:
        self._seed()
        with patch(
            "db.get_events_fingerprint",
            side_effect=RuntimeError("disk gone"),
        ):
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["total_events"]["available"])
        # Aggregator-owned blocks unaffected (separate code path).
        self.assertTrue(body["events_by_stage"]["available"])
        self.assertTrue(body["events_with_tickers"]["available"])

    def test_aggregator_failure_isolated(self) -> None:
        self._seed()
        with patch(
            "routes.diagnostics._compute_archive_aggregates",
            side_effect=RuntimeError("aggregate fail"),
        ):
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # total_events still works (not aggregator-owned).
        self.assertTrue(body["total_events"]["available"])
        # All aggregator blocks fall back to unavailable.
        for key in (
            "events_with_tickers", "events_with_returns",
            "events_by_stage", "events_by_persistence",
            "events_by_thesis_state", "market_checked_count",
        ):
            with self.subTest(block=key):
                self.assertFalse(body[key]["available"])
        self.assertIsNone(body["latest_event_timestamp"])

    def test_thesis_state_per_event_failure_keeps_other_aggregates(self) -> None:
        # Per-event derivation errors are skipped; the block stays available
        # with whatever counts accumulated, and the other aggregates remain
        # intact.
        self._seed()
        with patch(
            "thesis_state.derive_thesis_state",
            side_effect=RuntimeError("derive fail"),
        ):
            r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Other aggregates still computed normally.
        self.assertTrue(body["events_by_stage"]["available"])
        self.assertEqual(body["events_by_stage"]["counts"].get("realized"), 1)
        # Thesis state block stays available with empty counts (every per-event
        # call raised → nothing accumulated).
        self.assertTrue(body["events_by_thesis_state"]["available"])
        self.assertEqual(
            body["events_by_thesis_state"]["counts"], {},
        )


# ---------------------------------------------------------------------------
# /diagnostics/validation-status-stats — archive-aggregate validation stats
# ---------------------------------------------------------------------------


_VAL_TOP_KEYS = (
    "available",
    "total_events",
    "counts_by_status",
    "counts_by_reason",
    "pending_count",
    "unresolved_count",
    "latest_event_timestamp",
)

_VAL_STATUS_KEYS = ("validated", "contradicted", "unresolved", "pending")


class TestValidationStatusStatsShape(_ArchiveBase):
    def test_returns_200_with_top_keys(self) -> None:
        r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _VAL_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_counts_by_status_has_all_four_labels(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(set(body["counts_by_status"].keys()),
                         set(_VAL_STATUS_KEYS))


class TestValidationStatusStatsEmptyDB(_ArchiveBase):
    def test_available_true_on_empty_db(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 0)

    def test_all_status_counts_zero(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        for status in _VAL_STATUS_KEYS:
            self.assertEqual(body["counts_by_status"][status], 0)

    def test_pending_unresolved_top_level_zero(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(body["pending_count"], 0)
        self.assertEqual(body["unresolved_count"], 0)

    def test_counts_by_reason_empty_dict(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(body["counts_by_reason"], {})

    def test_latest_event_timestamp_none(self) -> None:
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertIsNone(body["latest_event_timestamp"])


class TestValidationStatusStatsSeeded(_ArchiveBase):
    """One representative seeded row per status, plus a mixed-archive case."""

    def test_validated_row_increments_validated(self) -> None:
        # Majority supports → validated.
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
            {"symbol": "MSFT", "direction_tag": "supports thesis"},
            {"symbol": "NVDA", "direction_tag": "contradicts thesis"},
        ])
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 1)
        self.assertEqual(body["counts_by_status"]["validated"], 1)

    def test_contradicted_row_increments_contradicted(self) -> None:
        # Contradicts >= supports → contradicted.
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "contradicts thesis"},
            {"symbol": "MSFT", "direction_tag": "contradicts thesis"},
            {"symbol": "NVDA", "direction_tag": "supports thesis"},
        ])
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(body["counts_by_status"]["contradicted"], 1)

    def test_unresolved_row_via_tagged_no_direction(self) -> None:
        # Tag present but neither supports/contradicts → classifier_abstained.
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "needs more evidence"},
        ])
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(body["counts_by_status"]["unresolved"], 1)
        self.assertEqual(body["unresolved_count"], 1)
        self.assertIn("classifier_abstained", body["counts_by_reason"])

    def test_pending_row_fresh_event_with_thesis(self) -> None:
        # Hot/warm event with a thesis but no direction tags → pending.
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            mechanism_summary="A real thesis about transmission.",
            market_tickers=[{"symbol": "AAPL"}],
        )
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertEqual(body["counts_by_status"]["pending"], 1)
        self.assertEqual(body["pending_count"], 1)
        self.assertIn("pending_within_window", body["counts_by_reason"])

    def test_mixed_archive_aggregates_all_four_buckets(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        # validated
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
            {"symbol": "MSFT", "direction_tag": "supports thesis"},
        ])
        # contradicted
        self._seed(market_tickers=[
            {"symbol": "TSLA", "direction_tag": "contradicts thesis"},
            {"symbol": "GOOG", "direction_tag": "contradicts thesis"},
        ])
        # unresolved (tagged but neutral)
        self._seed(market_tickers=[
            {"symbol": "META", "direction_tag": "needs more evidence"},
        ])
        # pending (fresh + thesis)
        self._seed(
            event_date=today,
            mechanism_summary="Real thesis.",
            market_tickers=[{"symbol": "NVDA"}],
        )
        body = client.get("/diagnostics/validation-status-stats").json()
        s = body["counts_by_status"]
        self.assertEqual(s["validated"],    1)
        self.assertEqual(s["contradicted"], 1)
        self.assertEqual(s["unresolved"],   1)
        self.assertEqual(s["pending"],      1)
        self.assertEqual(body["total_events"],     4)
        self.assertEqual(body["pending_count"],    1)
        self.assertEqual(body["unresolved_count"], 1)
        # Reason histogram populated, sums to total_events.
        self.assertEqual(
            sum(body["counts_by_reason"].values()),
            body["total_events"],
        )
        self.assertIn("majority_rule", body["counts_by_reason"])
        self.assertIn("classifier_abstained", body["counts_by_reason"])
        self.assertIn("pending_within_window", body["counts_by_reason"])

    def test_latest_event_timestamp_populated(self) -> None:
        self._seed()
        body = client.get("/diagnostics/validation-status-stats").json()
        self.assertIsInstance(body["latest_event_timestamp"], str)
        self.assertGreater(len(body["latest_event_timestamp"]), 0)


class TestValidationStatusStatsNoMutation(_ArchiveBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        self._seed()
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/validation-status-stats")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
        ])
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [dict(r) for r in
                      conn.execute("SELECT * FROM events").fetchall()]
        client.get("/diagnostics/validation-status-stats")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [dict(r) for r in
                     conn.execute("SELECT * FROM events").fetchall()]
        self.assertEqual(before, after)


class TestValidationStatusStatsZeroCost(_ArchiveBase):
    """Endpoint must not invoke market_check / yfinance / provider seams."""

    def test_market_check_fetch_not_called(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
        ])
        with patch(
            "market_check._fetch",
            side_effect=AssertionError("must not call market_check._fetch"),
        ):
            r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_check_one_ticker_not_called(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
        ])
        with patch(
            "market_check._check_one_ticker",
            side_effect=AssertionError("must not call _check_one_ticker"),
        ):
            r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_data_provider_not_called(self) -> None:
        self._seed()
        try:
            import market_data
            patched = hasattr(market_data, "get_provider")
        except ImportError:
            patched = False
        if patched:
            with patch(
                "market_data.get_provider",
                side_effect=AssertionError("must not call provider"),
            ):
                r = client.get("/diagnostics/validation-status-stats")
        else:
            r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)


class TestValidationStatusStatsPartialFailure(_ArchiveBase):
    def test_aggregator_failure_flips_available_false(self) -> None:
        self._seed()
        with patch(
            "routes.diagnostics._compute_validation_status_stats",
            side_effect=RuntimeError("read fail"),
        ):
            r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])
        self.assertEqual(body["total_events"],     0)
        self.assertEqual(body["pending_count"],    0)
        self.assertEqual(body["unresolved_count"], 0)
        self.assertEqual(body["counts_by_reason"], {})
        for status in _VAL_STATUS_KEYS:
            self.assertEqual(body["counts_by_status"][status], 0)
        self.assertIsNone(body["latest_event_timestamp"])

    def test_per_event_scoring_failure_keeps_aggregate_available(self) -> None:
        # Per-event score errors are caught — the row counts toward
        # total_events but contributes no status / reason.  Block stays
        # available so consumers don't lose the panel over one bad row.
        self._seed()
        with patch(
            "validation_status.score_validation_status",
            side_effect=RuntimeError("score fail"),
        ):
            r = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 1)
        self.assertEqual(sum(body["counts_by_status"].values()), 0)
        self.assertEqual(body["counts_by_reason"], {})


class TestExistingDiagnosticsEndpointsPreserved(_ArchiveBase):
    """Sanity check — adding the new route must not regress the others."""

    def test_data_quality_still_responds(self) -> None:
        r = client.get("/diagnostics/data-quality")
        self.assertEqual(r.status_code, 200)

    def test_archive_stats_still_responds(self) -> None:
        r = client.get("/diagnostics/archive-stats")
        self.assertEqual(r.status_code, 200)

    def test_config_health_still_responds(self) -> None:
        r = client.get("/diagnostics/config-health")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# /diagnostics/reaction-profile-stats — reaction_profile_v1 readiness
# ---------------------------------------------------------------------------


_RP_TOP_KEYS = (
    "available",
    "total_events",
    "events_with_market_tickers",
    "events_with_profile_input_ready",
    "events_unscorable",
    "ticker_count",
    "tickers_with_scalar_returns",
    "profile_basis_counts",
    "latest_event_timestamp",
)


class TestReactionProfileStatsShape(_ArchiveBase):
    def test_returns_200_with_top_keys(self) -> None:
        r = client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _RP_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_profile_basis_counts_is_dict(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertIsInstance(body["profile_basis_counts"], dict)


class TestReactionProfileStatsEmptyDB(_ArchiveBase):
    def test_available_true_on_empty_db(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 0)

    def test_all_event_counts_zero(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["events_with_market_tickers"],      0)
        self.assertEqual(body["events_with_profile_input_ready"], 0)
        self.assertEqual(body["events_unscorable"],               0)

    def test_all_ticker_counts_zero(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["ticker_count"],                0)
        self.assertEqual(body["tickers_with_scalar_returns"], 0)

    def test_basis_counts_empty_dict(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["profile_basis_counts"], {})

    def test_latest_event_timestamp_none(self) -> None:
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertIsNone(body["latest_event_timestamp"])


class TestReactionProfileStatsSeeded(_ArchiveBase):
    def test_event_with_no_tickers_is_unscorable(self) -> None:
        self._seed(market_tickers=[])
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["total_events"],                    1)
        self.assertEqual(body["events_with_market_tickers"],      0)
        self.assertEqual(body["events_with_profile_input_ready"], 0)
        self.assertEqual(body["events_unscorable"],               1)
        self.assertEqual(body["ticker_count"],                    0)
        self.assertEqual(body["tickers_with_scalar_returns"],     0)
        self.assertEqual(body["profile_basis_counts"], {"unscorable": 1})

    def test_event_with_tickers_but_no_returns_is_unscorable(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
        ])
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["events_with_market_tickers"],      1)
        self.assertEqual(body["events_with_profile_input_ready"], 0)
        self.assertEqual(body["events_unscorable"],               1)
        self.assertEqual(body["ticker_count"],                    2)
        self.assertEqual(body["tickers_with_scalar_returns"],     0)
        self.assertEqual(body["profile_basis_counts"], {"unscorable": 1})

    def test_event_with_one_ticker_with_return_is_input_ready(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.23},
            {"symbol": "MSFT"},  # no return — does not disqualify the event
        ])
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["events_with_market_tickers"],      1)
        self.assertEqual(body["events_with_profile_input_ready"], 1)
        self.assertEqual(body["events_unscorable"],               0)
        self.assertEqual(body["ticker_count"],                    2)
        self.assertEqual(body["tickers_with_scalar_returns"],     1)
        self.assertEqual(
            body["profile_basis_counts"], {"scalar_returns_only": 1},
        )

    def test_mixed_archive_aggregates_correctly(self) -> None:
        # Unscorable: no tickers.
        self._seed(market_tickers=[])
        # Unscorable: tickers but no numeric returns.
        self._seed(market_tickers=[{"symbol": "TSLA"}])
        # Input-ready: at least one ticker with a numeric return.
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_1d": 0.5},
            {"symbol": "MSFT", "return_5d": 1.0},
        ])
        # Input-ready: only one of three tickers has returns.
        self._seed(market_tickers=[
            {"symbol": "META"},
            {"symbol": "GOOG", "return_20d": -0.3},
            {"symbol": "AMZN"},
        ])
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(body["total_events"],                    4)
        self.assertEqual(body["events_with_market_tickers"],      3)
        self.assertEqual(body["events_with_profile_input_ready"], 2)
        self.assertEqual(body["events_unscorable"],               2)
        self.assertEqual(body["ticker_count"],                    6)
        self.assertEqual(body["tickers_with_scalar_returns"],     3)
        self.assertEqual(
            body["profile_basis_counts"],
            {"unscorable": 2, "scalar_returns_only": 2},
        )

    def test_input_ready_plus_unscorable_equals_total(self) -> None:
        # Invariant: every event lands in exactly one bucket.
        for _ in range(3):
            self._seed(market_tickers=[])
        for _ in range(2):
            self._seed(market_tickers=[
                {"symbol": "AAPL", "return_5d": 1.0},
            ])
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertEqual(
            body["events_with_profile_input_ready"]
            + body["events_unscorable"],
            body["total_events"],
        )
        self.assertEqual(
            sum(body["profile_basis_counts"].values()),
            body["total_events"],
        )

    def test_latest_event_timestamp_populated(self) -> None:
        self._seed()
        body = client.get("/diagnostics/reaction-profile-stats").json()
        self.assertIsInstance(body["latest_event_timestamp"], str)
        self.assertGreater(len(body["latest_event_timestamp"]), 0)


class TestReactionProfileStatsNoMutation(_ArchiveBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.0},
        ])
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.0},
        ])
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [dict(r) for r in
                      conn.execute("SELECT * FROM events").fetchall()]
        client.get("/diagnostics/reaction-profile-stats")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [dict(r) for r in
                     conn.execute("SELECT * FROM events").fetchall()]
        self.assertEqual(before, after)


class TestReactionProfileStatsZeroCost(_ArchiveBase):
    """Endpoint must not invoke market_check / yfinance / provider seams."""

    def test_market_check_fetch_not_called(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.0},
        ])
        with patch(
            "market_check._fetch",
            side_effect=AssertionError("must not call market_check._fetch"),
        ):
            r = client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_check_one_ticker_not_called(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.0},
        ])
        with patch(
            "market_check._check_one_ticker",
            side_effect=AssertionError("must not call _check_one_ticker"),
        ):
            r = client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(r.status_code, 200)

    def test_market_data_provider_not_called(self) -> None:
        self._seed()
        try:
            import market_data
            patched = hasattr(market_data, "get_provider")
        except ImportError:
            patched = False
        if patched:
            with patch(
                "market_data.get_provider",
                side_effect=AssertionError("must not call provider"),
            ):
                r = client.get("/diagnostics/reaction-profile-stats")
        else:
            r = client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(r.status_code, 200)


class TestReactionProfileStatsPartialFailure(_ArchiveBase):
    def test_aggregator_failure_flips_available_false(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "return_5d": 1.0},
        ])
        with patch(
            "routes.diagnostics._compute_reaction_profile_stats",
            side_effect=RuntimeError("read fail"),
        ):
            r = client.get("/diagnostics/reaction-profile-stats")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])
        self.assertEqual(body["total_events"],                    0)
        self.assertEqual(body["events_with_market_tickers"],      0)
        self.assertEqual(body["events_with_profile_input_ready"], 0)
        self.assertEqual(body["events_unscorable"],               0)
        self.assertEqual(body["ticker_count"],                    0)
        self.assertEqual(body["tickers_with_scalar_returns"],     0)
        self.assertEqual(body["profile_basis_counts"], {})
        self.assertIsNone(body["latest_event_timestamp"])

    def test_other_diagnostics_unaffected_by_reaction_failure(self) -> None:
        self._seed()
        with patch(
            "routes.diagnostics._compute_reaction_profile_stats",
            side_effect=RuntimeError("read fail"),
        ):
            r_rp = client.get("/diagnostics/reaction-profile-stats")
            r_arch = client.get("/diagnostics/archive-stats")
            r_val = client.get("/diagnostics/validation-status-stats")
        self.assertEqual(r_rp.status_code,   200)
        self.assertEqual(r_arch.status_code, 200)
        self.assertEqual(r_val.status_code,  200)
        self.assertFalse(r_rp.json()["available"])
        # Other endpoints unaffected.
        self.assertTrue(r_arch.json()["events_by_stage"]["available"])
        self.assertTrue(r_val.json()["available"])


# ---------------------------------------------------------------------------
# /diagnostics/major-skipped-headlines — high-priority unanalyzed view
# ---------------------------------------------------------------------------


_MS_TOP_KEYS = (
    "available",
    "items",
    "counts",
    "counts_by_skip_reason",
    "counts_by_registry_state",
    "filters",
    "news_source",
)

_MS_COUNT_KEYS = (
    "eligible", "skipped", "already_analyzed", "expired_low_impact",
)

_MS_ITEM_KEYS = (
    "headline", "source_count", "published_at", "event_date",
    "registry_state", "skip_reason", "skip_reason_label",
    "rank_score", "rank_factors", "rank_explanation", "why_visible",
)


class _MajorSkippedBase(_ArchiveBase):
    """Shared setup — wipes the news cache so per-test patches are
    deterministic and don't leak from one case to the next."""

    def setUp(self) -> None:
        super().setUp()
        api._news_cache["data"] = None
        api._news_cache["ts"]   = 0.0

    def _payload(self, *clusters) -> tuple[dict, str]:
        return ({"clusters": list(clusters)}, "synthetic-test")

    def _cluster(
        self,
        headline: str,
        source_count: int = 5,
        *,
        published_at: str | None = None,
        low_signal: bool = False,
    ) -> dict:
        return {
            "headline":     headline,
            "source_count": source_count,
            "published_at": published_at or datetime.now().isoformat(),
            "low_signal":   low_signal,
        }


class TestMajorSkippedHeadlinesShape(_MajorSkippedBase):
    def test_returns_200(self) -> None:
        r = client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(r.status_code, 200)

    def test_top_keys_present(self) -> None:
        body = client.get("/diagnostics/major-skipped-headlines").json()
        for k in _MS_TOP_KEYS:
            self.assertIn(k, body, f"missing top-level key: {k}")

    def test_counts_block_has_all_four_keys(self) -> None:
        body = client.get("/diagnostics/major-skipped-headlines").json()
        for k in _MS_COUNT_KEYS:
            self.assertIn(k, body["counts"], f"missing counts key: {k}")

    def test_filters_echo_query_defaults(self) -> None:
        body = client.get("/diagnostics/major-skipped-headlines").json()
        f = body["filters"]
        self.assertEqual(f["limit"],              25)
        self.assertEqual(f["since_hours"],        72)
        self.assertEqual(f["min_source_count"],   2)
        self.assertFalse(f["include_low_signal"])


class TestMajorSkippedHeadlinesEmptyCache(_MajorSkippedBase):
    def test_no_items_when_cache_empty(self) -> None:
        body = client.get("/diagnostics/major-skipped-headlines").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["items"], [])
        for v in body["counts"].values():
            self.assertEqual(v, 0)
        self.assertEqual(body["counts_by_skip_reason"],    {})
        self.assertEqual(body["counts_by_registry_state"], {})


class TestMajorSkippedHeadlinesSeeded(_MajorSkippedBase):
    """Patch the news payload + registry helpers with synthetic clusters."""

    def test_eligible_high_source_count_appears_in_items(self) -> None:
        cluster = self._cluster("Federal Reserve cuts rates 50bps", 5)
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(cluster),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        self.assertTrue(body["available"])
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        for k in _MS_ITEM_KEYS:
            self.assertIn(k, item, f"item missing key: {k}")
        self.assertEqual(item["headline"], cluster["headline"])
        self.assertEqual(body["counts"]["eligible"], 1)
        self.assertEqual(body["counts"]["already_analyzed"], 0)

    def test_already_analyzed_counted_but_excluded_from_items(self) -> None:
        cluster = self._cluster("Federal Reserve cuts rates 50bps", 5)
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(cluster),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=("analyzed", 123),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["counts"]["already_analyzed"], 1)
        self.assertEqual(body["counts"]["skipped"],          1)
        self.assertEqual(body["counts_by_registry_state"], {"analyzed": 1})

    def test_expired_low_impact_appears_in_items_with_why_visible(self) -> None:
        cluster = self._cluster("Federal Reserve announces QE tapering", 4)
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(cluster),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=("expired_low_impact", 9),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["registry_state"], "expired_low_impact")
        self.assertIn("expired", item["why_visible"])
        self.assertEqual(body["counts"]["expired_low_impact"], 1)
        self.assertEqual(body["counts"]["skipped"],            1)
        self.assertEqual(body["counts"]["eligible"],           0)

    def test_skip_reason_populates_counts_and_why_visible(self) -> None:
        cluster = self._cluster("Federal Reserve hikes rates by 25bps", 6)
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(cluster),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ), patch(
            "routes.diagnostics._last_skip_reason_for_title_key",
            return_value="llm_budget_exhausted",
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["skip_reason"], "llm_budget_exhausted")
        self.assertIn("llm_budget_exhausted", item["why_visible"])
        # skip_reason_label populated by routes.movers._skip_reason_label.
        self.assertIsInstance(item["skip_reason_label"], str)
        self.assertEqual(
            body["counts_by_skip_reason"]["llm_budget_exhausted"], 1,
        )

    def test_mixed_states_partition_correctly(self) -> None:
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps",        7),
            self._cluster("Federal Reserve hikes rates by 25bps",    6),
            self._cluster("Federal Reserve announces QE tapering",   4),
        ]
        # Map each headline to a different registry state.
        state_map = {
            "Federal Reserve cuts rates 50bps":      (None, None),
            "Federal Reserve hikes rates by 25bps":  ("analyzed", 1),
            "Federal Reserve announces QE tapering": ("expired_low_impact", 2),
        }
        def _state(title_key):
            for h, s in state_map.items():
                if title_key and title_key in h.lower().replace(" ", ""):
                    return s
            for h, s in state_map.items():
                if h.lower() in title_key or title_key in h.lower():
                    return s
            return (None, None)

        with patch(
            "routes.movers._cached_news_payload",
            return_value=({"clusters": clusters}, "synthetic-test"),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            side_effect=lambda tk: _state(tk),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        # Two items surfaced (eligible + expired_low_impact); analyzed excluded.
        self.assertEqual(len(body["items"]), 2)
        states = {it["registry_state"] for it in body["items"]}
        self.assertIn("expired_low_impact", states)
        self.assertIn(None, states)
        self.assertEqual(body["counts"]["eligible"],           1)
        self.assertEqual(body["counts"]["already_analyzed"],   1)
        self.assertEqual(body["counts"]["expired_low_impact"], 1)
        self.assertEqual(body["counts"]["skipped"],            2)


class TestMajorSkippedHeadlinesRanking(_MajorSkippedBase):
    def test_items_sorted_by_rank_score_descending(self) -> None:
        # All three are market-relevant Federal Reserve headlines so
        # only source_count differentiates the rank score.
        clusters = [
            self._cluster("Federal Reserve cuts rates amid recession fears", 2),
            self._cluster("Federal Reserve hikes rates by 25bps",            10),
            self._cluster("Federal Reserve announces QE tapering",           5),
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=({"clusters": clusters}, "synthetic-test"),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        scores = [it["rank_score"] for it in body["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Highest source_count should be at the top.
        self.assertEqual(body["items"][0]["source_count"], 10)
        # Lowest source_count at the bottom.
        self.assertEqual(body["items"][-1]["source_count"], 2)


class TestMajorSkippedHeadlinesMinSourceCount(_MajorSkippedBase):
    def test_below_threshold_excluded(self) -> None:
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps",     5),
            # source_count=1 is below default min_source_count=2.
            self._cluster("Federal Reserve hikes rates by 25bps", 1),
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=({"clusters": clusters}, "synthetic-test"),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.get("/diagnostics/major-skipped-headlines").json()
        headlines = [it["headline"] for it in body["items"]]
        self.assertEqual(len(headlines), 1)
        self.assertEqual(headlines[0], "Federal Reserve cuts rates 50bps")

    def test_min_source_count_query_param_overrides_default(self) -> None:
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps",     2),
            self._cluster("Federal Reserve hikes rates by 25bps", 4),
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=({"clusters": clusters}, "synthetic-test"),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.get(
                "/diagnostics/major-skipped-headlines?min_source_count=3"
            ).json()
        # Only the source_count=4 cluster survives the raised threshold.
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["source_count"], 4)
        self.assertEqual(body["filters"]["min_source_count"], 3)


class TestMajorSkippedHeadlinesLimit(_MajorSkippedBase):
    def test_limit_caps_items_but_counts_reflect_full_universe(self) -> None:
        clusters = [
            self._cluster(f"Federal Reserve hikes rates by {i}bps", 5)
            for i in (10, 20, 30, 40, 50)
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=({"clusters": clusters}, "synthetic-test"),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.get(
                "/diagnostics/major-skipped-headlines?limit=2"
            ).json()
        self.assertEqual(len(body["items"]), 2)
        # Counts cover all 5 clusters even though items are capped.
        self.assertEqual(body["counts"]["eligible"], 5)


class TestMajorSkippedHeadlinesZeroCost(_MajorSkippedBase):
    def test_market_check_fetch_not_called(self) -> None:
        with patch(
            "market_check._fetch",
            side_effect=AssertionError("must not call market_check._fetch"),
        ):
            r = client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(r.status_code, 200)

    def test_market_check_one_ticker_not_called(self) -> None:
        with patch(
            "market_check._check_one_ticker",
            side_effect=AssertionError("must not call _check_one_ticker"),
        ):
            r = client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(r.status_code, 200)

    def test_market_data_provider_not_called(self) -> None:
        try:
            import market_data
            patched = hasattr(market_data, "get_provider")
        except ImportError:
            patched = False
        if patched:
            with patch(
                "market_data.get_provider",
                side_effect=AssertionError("must not call provider"),
            ):
                r = client.get("/diagnostics/major-skipped-headlines")
        else:
            r = client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(r.status_code, 200)


class TestMajorSkippedHeadlinesNoMutation(_MajorSkippedBase):
    def test_repeated_calls_do_not_change_archive_fingerprint(self) -> None:
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        self._seed()
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [dict(r) for r in
                      conn.execute("SELECT * FROM events").fetchall()]
        for _ in range(3):
            client.get("/diagnostics/major-skipped-headlines")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [dict(r) for r in
                     conn.execute("SELECT * FROM events").fetchall()]
        self.assertEqual(before, after)


class TestMajorSkippedHeadlinesPartialFailure(_MajorSkippedBase):
    def test_internal_failure_returns_unavailable_shape(self) -> None:
        with patch(
            "routes.diagnostics._compute_major_skipped",
            side_effect=RuntimeError("compute fail"),
        ):
            r = client.get("/diagnostics/major-skipped-headlines")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])
        self.assertEqual(body["items"], [])
        for v in body["counts"].values():
            self.assertEqual(v, 0)
        # Filters echo the request even on failure.
        self.assertEqual(body["filters"]["limit"], 25)


# ---------------------------------------------------------------------------
# /diagnostics/track-record — validation status × hydrated reaction profile
# ---------------------------------------------------------------------------


_TR_TOP_KEYS = (
    "available",
    "total_events",
    "counts_by_validation_status",
    "reaction_profile_available_count",
    "average_return_5d_by_validation_status",
    "average_peak_move_20d_by_validation_status",
    "fade_or_hold_counts_by_validation_status",
    "coverage_notes",
    "latest_event_timestamp",
)


def _seed_price_cache(
    db_path: str, *, ticker: str, start: str, closes: list[float],
) -> None:
    """Hand-write rows into the temp DB's price_cache table."""
    from datetime import timedelta as _td
    base = datetime.fromisoformat(start)
    rows: list[tuple] = []
    cursor = base
    for c in closes:
        while cursor.weekday() >= 5:
            cursor = cursor + _td(days=1)
        rows.append((
            ticker.upper(), cursor.strftime("%Y-%m-%d"),
            float(c), 1_000_000.0, 0,
            datetime.now().isoformat(timespec="seconds"),
        ))
        cursor = cursor + _td(days=1)
    with _sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


class _TrackRecordBase(_ArchiveBase):
    """Adds price_cache reset around the events-archive base."""

    def setUp(self) -> None:
        super().setUp()
        import price_cache as _pc
        _pc._reset_table_ready_for_tests()

    def tearDown(self) -> None:
        import price_cache as _pc
        _pc._reset_table_ready_for_tests()
        super().tearDown()


class TestTrackRecordShape(_TrackRecordBase):
    def test_returns_200_with_full_top_keyset(self) -> None:
        r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _TR_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_counts_by_validation_status_has_all_four_labels(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        self.assertEqual(
            set(body["counts_by_validation_status"].keys()),
            set(_VAL_STATUS_KEYS),
        )

    def test_average_dicts_keyed_by_validation_status(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        for key in (
            "average_return_5d_by_validation_status",
            "average_peak_move_20d_by_validation_status",
            "fade_or_hold_counts_by_validation_status",
        ):
            self.assertEqual(set(body[key].keys()), set(_VAL_STATUS_KEYS))


class TestTrackRecordEmptyDB(_TrackRecordBase):
    def test_available_true_on_empty_db(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 0)
        self.assertEqual(body["reaction_profile_available_count"], 0)

    def test_all_status_counts_zero(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        for status in _VAL_STATUS_KEYS:
            self.assertEqual(body["counts_by_validation_status"][status], 0)

    def test_averages_all_none(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        for status in _VAL_STATUS_KEYS:
            self.assertIsNone(
                body["average_return_5d_by_validation_status"][status]
            )
            self.assertIsNone(
                body["average_peak_move_20d_by_validation_status"][status]
            )
            self.assertIsInstance(
                body["fade_or_hold_counts_by_validation_status"][status], dict,
            )

    def test_coverage_notes_present(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        self.assertIsInstance(body["coverage_notes"], dict)

    def test_latest_event_timestamp_none(self) -> None:
        body = client.get("/diagnostics/track-record").json()
        self.assertIsNone(body["latest_event_timestamp"])


class TestTrackRecordSeededRows(_TrackRecordBase):
    """Per-status bucketing + per-status average rollups, hydrated from cache."""

    def test_validation_status_buckets_count_correctly(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        # validated
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
            {"symbol": "MSFT", "direction_tag": "supports thesis"},
        ])
        # contradicted
        self._seed(market_tickers=[
            {"symbol": "TSLA", "direction_tag": "contradicts thesis"},
            {"symbol": "GOOG", "direction_tag": "contradicts thesis"},
        ])
        # unresolved
        self._seed(market_tickers=[
            {"symbol": "META", "direction_tag": "needs more evidence"},
        ])
        # pending
        self._seed(
            event_date=today,
            mechanism_summary="Real thesis.",
            market_tickers=[{"symbol": "NVDA"}],
        )
        body = client.get("/diagnostics/track-record").json()
        self.assertEqual(body["total_events"], 4)
        c = body["counts_by_validation_status"]
        self.assertEqual(c["validated"],    1)
        self.assertEqual(c["contradicted"], 1)
        self.assertEqual(c["unresolved"],   1)
        self.assertEqual(c["pending"],      1)

    def test_reaction_profile_available_count_reflects_cache_hits(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[
                {"symbol": "AAPL", "direction_tag": "supports thesis",
                 "anchor_date": today},
                {"symbol": "MSFT", "direction_tag": "supports thesis",
                 "anchor_date": today},
            ],
        )
        self._seed(
            event_date=today,
            market_tickers=[
                {"symbol": "ZZZ_NO_CACHE", "direction_tag": "supports thesis",
                 "anchor_date": today},
                {"symbol": "QQQ_NO_CACHE", "direction_tag": "supports thesis",
                 "anchor_date": today},
            ],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
        )
        body = client.get("/diagnostics/track-record").json()
        self.assertEqual(body["total_events"], 2)
        self.assertEqual(body["reaction_profile_available_count"], 1)

    def test_average_return_5d_aggregates_per_status(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[
                {"symbol": "AAPL", "direction_tag": "supports thesis",
                 "anchor_date": today},
                {"symbol": "MSFT", "direction_tag": "supports thesis",
                 "anchor_date": today},
            ],
        )
        self._seed(
            event_date=today,
            market_tickers=[
                {"symbol": "NVDA", "direction_tag": "supports thesis",
                 "anchor_date": today},
                {"symbol": "GOOG", "direction_tag": "supports thesis",
                 "anchor_date": today},
            ],
        )
        # AAPL: anchor 100, +5% at bar 5.
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 100.0, 100.0, 100.0, 100.0, 105.0, 105.0],
        )
        # NVDA: anchor 100, -3% at bar 5.
        _seed_price_cache(
            self._tmp, ticker="NVDA", start=today,
            closes=[100.0, 100.0, 100.0, 100.0, 100.0, 97.0, 97.0],
        )
        body = client.get("/diagnostics/track-record").json()
        avg_5d = body["average_return_5d_by_validation_status"]["validated"]
        self.assertIsNotNone(avg_5d)
        # AAPL +5, NVDA -3 → average across the two scorable tickers = 1.0.
        self.assertAlmostEqual(avg_5d, 1.0, places=2)

    def test_fade_or_hold_counts_populated_for_hydrated_status(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[
                {"symbol": "AAPL", "direction_tag": "supports thesis",
                 "anchor_date": today},
                {"symbol": "MSFT", "direction_tag": "supports thesis",
                 "anchor_date": today},
            ],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0] + [100.0 + i * 0.5 for i in range(1, 22)],
        )
        body = client.get("/diagnostics/track-record").json()
        counts = body["fade_or_hold_counts_by_validation_status"]["validated"]
        self.assertGreater(sum(counts.values()), 0)

    def test_coverage_notes_track_unscorable_and_signal(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        # Event A: tickers but no cache rows.
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "ZZZ_MISS",
                             "direction_tag": "supports thesis",
                             "anchor_date": today}],
        )
        # Event B: empty market_tickers.
        self._seed(market_tickers=[])
        # Event C: tickers with seeded cache rows that hydrate.
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL",
                             "direction_tag": "supports thesis",
                             "anchor_date": today}],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        )
        body = client.get("/diagnostics/track-record").json()
        notes = body["coverage_notes"]
        self.assertEqual(notes["events_with_no_tickers"], 1)
        self.assertGreaterEqual(notes["events_unscorable"], 1)
        self.assertGreaterEqual(notes["events_with_5d_signal"], 1)

    def test_latest_event_timestamp_populated(self) -> None:
        self._seed()
        body = client.get("/diagnostics/track-record").json()
        self.assertIsInstance(body["latest_event_timestamp"], str)
        self.assertGreater(len(body["latest_event_timestamp"]), 0)


class TestTrackRecordNoMutation(_TrackRecordBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        self._seed()
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/track-record")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_or_cache_rows(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL",
                             "direction_tag": "supports thesis",
                             "anchor_date": today}],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        )
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            ev_before = [dict(r) for r in
                         conn.execute("SELECT * FROM events").fetchall()]
            pc_before = list(conn.execute(
                "SELECT ticker, date, close, volume, auto_adjust "
                "FROM price_cache ORDER BY ticker, date"
            ))
        client.get("/diagnostics/track-record")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            ev_after = [dict(r) for r in
                        conn.execute("SELECT * FROM events").fetchall()]
            pc_after = list(conn.execute(
                "SELECT ticker, date, close, volume, auto_adjust "
                "FROM price_cache ORDER BY ticker, date"
            ))
        self.assertEqual(ev_before, ev_after)
        self.assertEqual(pc_before, pc_after)


class TestTrackRecordZeroCost(_TrackRecordBase):
    """Endpoint must not invoke market_check / yfinance / provider seams."""

    def test_market_check_not_called(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
        ])
        with patch(
            "market_check._fetch",
            side_effect=AssertionError("must not call market_check._fetch"),
        ), patch(
            "market_check._check_one_ticker",
            side_effect=AssertionError("must not call _check_one_ticker"),
        ):
            r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)

    def test_provider_not_called(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL",
                             "direction_tag": "supports thesis",
                             "anchor_date": today}],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        )
        try:
            import market_data
            patched = hasattr(market_data, "get_provider")
        except ImportError:
            patched = False
        if patched:
            with patch(
                "market_data.get_provider",
                side_effect=AssertionError("must not call provider"),
            ), patch(
                "yfinance.download",
                side_effect=AssertionError("must not call yfinance.download"),
            ), patch(
                "yfinance.Ticker",
                side_effect=AssertionError("must not call yfinance.Ticker"),
            ):
                r = client.get("/diagnostics/track-record")
        else:
            r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Hydration must have completed from cache without provider help.
        self.assertGreaterEqual(body["reaction_profile_available_count"], 1)


class TestTrackRecordPartialFailure(_TrackRecordBase):
    def test_aggregator_failure_flips_available_false(self) -> None:
        self._seed()
        with patch(
            "routes.diagnostics._compute_track_record",
            side_effect=RuntimeError("aggregator fail"),
        ):
            r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])
        self.assertEqual(body["total_events"], 0)
        self.assertEqual(body["reaction_profile_available_count"], 0)
        for status in _VAL_STATUS_KEYS:
            self.assertEqual(body["counts_by_validation_status"][status], 0)
            self.assertIsNone(
                body["average_return_5d_by_validation_status"][status]
            )
        self.assertIsNone(body["latest_event_timestamp"])

    def test_per_event_hydration_failure_keeps_aggregate_available(self) -> None:
        self._seed(market_tickers=[
            {"symbol": "AAPL", "direction_tag": "supports thesis"},
        ])
        self._seed(market_tickers=[
            {"symbol": "MSFT", "direction_tag": "supports thesis"},
        ])

        from reaction_profile_hydration import (
            hydrate_per_ticker_profile as _real_hpp,
        )
        call_count = {"n": 0}

        def _flaky(saved_ticker, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("hydrate fail")
            return _real_hpp(saved_ticker, **kwargs)

        with patch(
            "routes.diagnostics.hydrate_per_ticker_profile",
            side_effect=_flaky,
        ):
            r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 2)
        # Both events were validated; the hydration failure on one
        # ticker doesn't change the validation-status histogram.
        self.assertEqual(
            body["counts_by_validation_status"]["validated"], 2,
        )

    def test_per_event_score_failure_keeps_aggregate_available(self) -> None:
        self._seed()
        self._seed()
        from itertools import count as _count
        counter = _count()

        def _flaky(event, **kwargs):
            if next(counter) == 0:
                raise RuntimeError("score fail")
            return {"status": "validated", "reason": "ok"}

        with patch(
            "routes.diagnostics.score_validation_status",
            side_effect=_flaky,
        ):
            r = client.get("/diagnostics/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 2)


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-config — env-driven config snapshot
# ---------------------------------------------------------------------------


_ABF_TOP_KEYS = (
    "enabled",
    "paid_analysis_enabled",
    "interval_hours",
    "max_calls_per_run",
    "max_calls_per_day",
    "model",
    "effective_status",
    "warnings",
)

_ABF_ENV_VARS = (
    "ENABLE_AUTO_BACKFILL",
    "ENABLE_PAID_ANALYSIS",
    "AUTO_BACKFILL_INTERVAL_HOURS",
    "AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN",
    "AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY",
    "AUTO_BACKFILL_MODEL",
)


class _AutoBackfillEnvBase(_Base):
    """Snapshot the relevant env vars per test so global state can't leak
    between cases.  The diagnostics endpoint reads from ``os.environ`` at
    call time, so each test's ``patch.dict`` window covers exactly the
    request it makes.
    """

    def setUp(self) -> None:
        super().setUp()
        self._env_backup = {
            k: os.environ.get(k) for k in _ABF_ENV_VARS
        }
        for k in _ABF_ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


class TestAutoBackfillConfigShape(_AutoBackfillEnvBase):
    def test_returns_200_with_full_top_keyset(self) -> None:
        r = client.get("/diagnostics/auto-backfill-config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ABF_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_warnings_is_a_list(self) -> None:
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertIsInstance(body["warnings"], list)

    def test_effective_status_in_known_vocabulary(self) -> None:
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertIn(
            body["effective_status"],
            {"disabled", "blocked_paid_guard", "configured"},
        )


class TestAutoBackfillDefaultDisabled(_AutoBackfillEnvBase):
    def test_default_disabled_no_env_set(self) -> None:
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertFalse(body["enabled"])
        self.assertFalse(body["paid_analysis_enabled"])
        self.assertEqual(body["effective_status"], "disabled")
        # No warning is emitted in the disabled-default case — the panel
        # should be quiet for an unconfigured environment.
        self.assertEqual(body["warnings"], [])

    def test_defaults_for_caps_and_model(self) -> None:
        body = client.get("/diagnostics/auto-backfill-config").json()
        # Values come from auto_backfill_config.DEFAULT_*; pin the
        # primitives directly so a future re-tune touches the test.
        self.assertEqual(body["interval_hours"],     6)
        self.assertEqual(body["max_calls_per_run"],  3)
        self.assertEqual(body["max_calls_per_day"], 12)
        self.assertIsInstance(body["model"], str)
        self.assertGreater(len(body["model"]), 0)


class TestAutoBackfillBlockedByPaidGuard(_AutoBackfillEnvBase):
    def test_enabled_without_paid_is_blocked(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        # ENABLE_PAID_ANALYSIS deliberately not set.
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertTrue(body["enabled"])
        self.assertFalse(body["paid_analysis_enabled"])
        self.assertEqual(body["effective_status"], "blocked_paid_guard")
        self.assertGreater(
            len(body["warnings"]), 0,
            "blocked_paid_guard must emit at least one operator warning",
        )
        joined = " ".join(body["warnings"])
        self.assertIn("ENABLE_PAID_ANALYSIS", joined)

    def test_enabled_with_paid_explicitly_false_is_blocked(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "false"
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertEqual(body["effective_status"], "blocked_paid_guard")


class TestAutoBackfillConfigured(_AutoBackfillEnvBase):
    def test_both_gates_true_yields_configured(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertTrue(body["enabled"])
        self.assertTrue(body["paid_analysis_enabled"])
        self.assertEqual(body["effective_status"], "configured")
        # No paid-guard warning when both gates agree; cross-field
        # sanity warnings (per-run > per-day) may still appear and are
        # tested separately.
        joined = " ".join(body["warnings"])
        self.assertNotIn("ENABLE_PAID_ANALYSIS is false", joined)


class TestAutoBackfillInvalidEnvFallback(_AutoBackfillEnvBase):
    def test_negative_interval_falls_back_to_default(self) -> None:
        os.environ["AUTO_BACKFILL_INTERVAL_HOURS"] = "-1"
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertEqual(body["interval_hours"], 6)  # default
        joined = " ".join(body["warnings"])
        self.assertIn("AUTO_BACKFILL_INTERVAL_HOURS", joined)

    def test_non_integer_interval_falls_back(self) -> None:
        os.environ["AUTO_BACKFILL_INTERVAL_HOURS"] = "lots"
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertEqual(body["interval_hours"], 6)
        joined = " ".join(body["warnings"])
        self.assertIn("AUTO_BACKFILL_INTERVAL_HOURS", joined)
        self.assertIn("not an integer", joined)

    def test_per_run_above_max_clamps(self) -> None:
        os.environ["AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN"] = "9999"
        body = client.get("/diagnostics/auto-backfill-config").json()
        # Module clamps per-run to a hard maximum (10 today).  Test
        # against that primitive without re-importing the constant so a
        # future bump only touches the module.
        self.assertLessEqual(body["max_calls_per_run"], 10)
        joined = " ".join(body["warnings"])
        self.assertIn("AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN", joined)

    def test_unknown_model_passes_through(self) -> None:
        # Unknown model strings are not validated against a registry —
        # the diagnostics surface returns whatever the operator set.
        # Validation against a known-model list is the scheduler's job
        # at boot time.
        os.environ["AUTO_BACKFILL_MODEL"] = "operator-typo-model"
        body = client.get("/diagnostics/auto-backfill-config").json()
        self.assertEqual(body["model"], "operator-typo-model")

    def test_per_run_above_per_day_emits_warning(self) -> None:
        os.environ["AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN"] = "5"
        os.environ["AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY"] = "3"
        body = client.get("/diagnostics/auto-backfill-config").json()
        joined = " ".join(body["warnings"])
        self.assertIn("PER_RUN", joined)
        self.assertIn("PER_DAY", joined)


class TestAutoBackfillNoSideEffects(_AutoBackfillEnvBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/auto-backfill-config")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [dict(r) for r in
                      conn.execute("SELECT * FROM events").fetchall()]
        client.get("/diagnostics/auto-backfill-config")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [dict(r) for r in
                     conn.execute("SELECT * FROM events").fetchall()]
        self.assertEqual(before, after)

    def test_endpoint_does_not_invoke_paid_or_provider_seams(self) -> None:
        # The diagnostics surface must remain zero-cost.  Patch the same
        # banlist the other diagnostics endpoints use.
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        with patch("api.analyze_event",
                   side_effect=AssertionError("must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("must not call yfinance.Ticker")):
            r = client.get("/diagnostics/auto-backfill-config")
        self.assertEqual(r.status_code, 200)


class TestAutoBackfillNeverExposesSecrets(_AutoBackfillEnvBase):
    def test_response_does_not_carry_api_keys(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-secret-DO-NOT-LEAK"
        os.environ["OPENAI_API_KEY"]    = "sk-openai-secret-DO-NOT-LEAK"
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        try:
            body = client.get("/diagnostics/auto-backfill-config").text
            self.assertNotIn("sk-test-secret-DO-NOT-LEAK", body)
            self.assertNotIn("sk-openai-secret-DO-NOT-LEAK", body)
            self.assertNotIn("ANTHROPIC_API_KEY", body)
            self.assertNotIn("OPENAI_API_KEY",    body)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY",    None)


if __name__ == "__main__":
    unittest.main()

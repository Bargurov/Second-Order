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


if __name__ == "__main__":
    unittest.main()

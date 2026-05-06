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


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-status — config + ledger + state composition
# ---------------------------------------------------------------------------


_ABF_STATUS_TOP_KEYS = (
    "config",
    "ledger",
    "state",
    "scheduler",
    "effective_status",
    "last_skip_reason",
    "last_error",
    "daily_remaining",
)

_ABF_STATUS_SCHEDULER_KEYS = (
    "scheduler_available",
    "scheduler_started",
    "job_count",
    "mode",
)

_ABF_STATUS_LEDGER_KEYS = (
    "daily_cap",
    "used",
    "remaining",
    "day",
)

_ABF_STATUS_STATE_KEYS = (
    "lock_held",
    "lock_owner",
    "lock_acquired_at",
    "lock_expires_at",
    "last_run_id",
    "last_started_at",
    "last_completed_at",
    "last_skip_reason",
    "last_error",
    "last_selected_count",
    "last_spent_calls",
)


class _AutoBackfillStatusBase(_AutoBackfillEnvBase):
    """Resets the route's lazy singletons each test so per-test config
    overrides are observable without ordering coupling.
    """

    def setUp(self) -> None:
        super().setUp()
        from routes import diagnostics as _diag
        _diag._AUTO_BACKFILL_LEDGER = None
        _diag._AUTO_BACKFILL_LEDGER_CAP = None
        _diag._AUTO_BACKFILL_STATE = None

    def tearDown(self) -> None:
        from routes import diagnostics as _diag
        _diag._AUTO_BACKFILL_LEDGER = None
        _diag._AUTO_BACKFILL_LEDGER_CAP = None
        _diag._AUTO_BACKFILL_STATE = None
        super().tearDown()


class TestAutoBackfillStatusShape(_AutoBackfillStatusBase):
    def test_returns_200_with_full_top_keyset(self) -> None:
        r = client.get("/diagnostics/auto-backfill-status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ABF_STATUS_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_config_block_carries_full_config_keyset(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        for key in _ABF_TOP_KEYS:
            self.assertIn(
                key, body["config"],
                f"missing config sub-key: {key}",
            )

    def test_ledger_block_has_stable_keyset(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        for key in _ABF_STATUS_LEDGER_KEYS:
            self.assertIn(key, body["ledger"], f"missing ledger key: {key}")

    def test_state_block_has_stable_keyset(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        for key in _ABF_STATUS_STATE_KEYS:
            self.assertIn(key, body["state"], f"missing state key: {key}")

    def test_effective_status_in_known_vocabulary(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIn(
            body["effective_status"],
            {"disabled", "blocked_paid_guard", "configured"},
        )

    def test_top_level_mirrors_match_state_and_ledger_blocks(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(
            body["last_skip_reason"], body["state"]["last_skip_reason"],
        )
        self.assertEqual(body["last_error"], body["state"]["last_error"])
        self.assertEqual(body["daily_remaining"], body["ledger"]["remaining"])


class TestAutoBackfillStatusDefaultDisabled(_AutoBackfillStatusBase):
    def test_default_disabled_no_env_set(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["effective_status"], "disabled")
        self.assertFalse(body["config"]["enabled"])
        self.assertFalse(body["config"]["paid_analysis_enabled"])

    def test_idle_state_block_is_all_none_or_false(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        state = body["state"]
        self.assertFalse(state["lock_held"])
        self.assertIsNone(state["lock_owner"])
        self.assertIsNone(state["lock_acquired_at"])
        self.assertIsNone(state["lock_expires_at"])
        self.assertIsNone(state["last_run_id"])
        self.assertIsNone(state["last_started_at"])
        self.assertIsNone(state["last_completed_at"])
        self.assertIsNone(state["last_skip_reason"])
        self.assertIsNone(state["last_error"])
        self.assertIsNone(state["last_selected_count"])
        self.assertIsNone(state["last_spent_calls"])

    def test_fresh_ledger_reports_full_remaining(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        ledger = body["ledger"]
        # Default daily cap is 12 (auto_backfill_config.DEFAULT_MAX_PER_DAY).
        self.assertEqual(ledger["daily_cap"], 12)
        self.assertEqual(ledger["used"], 0)
        self.assertEqual(ledger["remaining"], 12)
        self.assertEqual(body["daily_remaining"], 12)
        self.assertIsInstance(ledger["day"], str)
        self.assertGreater(len(ledger["day"]), 0)


class TestAutoBackfillStatusConfiguredEnv(_AutoBackfillStatusBase):
    def test_both_gates_true_yields_configured(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["effective_status"], "configured")
        self.assertTrue(body["config"]["enabled"])
        self.assertTrue(body["config"]["paid_analysis_enabled"])

    def test_enabled_without_paid_is_blocked_by_paid_guard(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["effective_status"], "blocked_paid_guard")

    def test_per_day_env_drives_ledger_cap(self) -> None:
        os.environ["AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY"] = "7"
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["ledger"]["daily_cap"], 7)
        self.assertEqual(body["ledger"]["remaining"], 7)
        self.assertEqual(body["daily_remaining"], 7)


class TestAutoBackfillStatusNoSideEffects(_AutoBackfillStatusBase):
    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/auto-backfill-status")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM events"
                ).fetchall()
            ]
        for _ in range(3):
            client.get("/diagnostics/auto-backfill-status")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM events"
                ).fetchall()
            ]
        self.assertEqual(before, after)

    def test_endpoint_does_not_invoke_paid_or_provider_seams(self) -> None:
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
            r = client.get("/diagnostics/auto-backfill-status")
        self.assertEqual(r.status_code, 200)

    def test_endpoint_does_not_advance_ledger_used(self) -> None:
        # Calling the diagnostics surface must never reserve a call.
        for _ in range(5):
            client.get("/diagnostics/auto-backfill-status")
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["ledger"]["used"], 0)
        self.assertEqual(
            body["ledger"]["remaining"], body["ledger"]["daily_cap"],
        )


class TestAutoBackfillStatusKeepsConfigEndpointWorking(_AutoBackfillStatusBase):
    def test_config_endpoint_still_returns_full_keyset(self) -> None:
        # The new status endpoint must not regress the existing config
        # endpoint — they share helpers but stay independent.
        body = client.get("/diagnostics/auto-backfill-config").json()
        for key in _ABF_TOP_KEYS:
            self.assertIn(key, body, f"config endpoint missing key: {key}")


class TestAutoBackfillStatusFallback(_AutoBackfillStatusBase):
    def test_loader_failure_falls_back_to_unavailable_shape(self) -> None:
        # When the underlying loader raises, the endpoint must return a
        # 200 with the stable unavailable shape rather than 500.
        with patch(
            "routes.diagnostics.load_auto_backfill_config",
            side_effect=RuntimeError("boom"),
        ):
            r = client.get("/diagnostics/auto-backfill-status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ABF_STATUS_TOP_KEYS:
            self.assertIn(key, body)
        self.assertEqual(body["effective_status"], "disabled")
        self.assertEqual(body["ledger"]["daily_cap"], 0)
        self.assertEqual(body["ledger"]["remaining"], 0)
        self.assertEqual(body["daily_remaining"], 0)


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-dry-run — operator-triggered simulated tick
# ---------------------------------------------------------------------------


_ABF_DRY_TOP_KEYS = (
    "config",
    "selected",
    "selected_count",
    "skip_counts",
    "skip_reasons",
    "candidates_considered",
    "eligible_count",
    "effective_call_cap",
    "decision_reason",
    "started",
    "completed",
    "skip_reason",
    "run_id",
    "spent_calls",
    "now",
    "candidate_queue_counts",
    "news_source",
    "ledger",
    "state",
    "filters",
    "available",
)


class _AutoBackfillDryRunBase(_AutoBackfillEnvBase):
    """Snapshots env vars + clears the news cache + resets the
    /auto-backfill-status singletons so the dry-run endpoint cannot
    contaminate or be contaminated by neighbouring tests.

    The dry-run endpoint itself uses ephemeral state/ledger per call, but
    we still reset the long-lived singletons exposed by the status
    endpoint so the "no side-effect on the status singletons"
    invariant is observable in this fixture.
    """

    def setUp(self) -> None:
        super().setUp()
        api._news_cache["data"] = None
        api._news_cache["ts"]   = 0.0
        from routes import diagnostics as _diag
        _diag._AUTO_BACKFILL_LEDGER = None
        _diag._AUTO_BACKFILL_LEDGER_CAP = None
        _diag._AUTO_BACKFILL_STATE = None

    def tearDown(self) -> None:
        api._news_cache["data"] = None
        api._news_cache["ts"]   = 0.0
        from routes import diagnostics as _diag
        _diag._AUTO_BACKFILL_LEDGER = None
        _diag._AUTO_BACKFILL_LEDGER_CAP = None
        _diag._AUTO_BACKFILL_STATE = None
        super().tearDown()

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


class TestAutoBackfillDryRunDisabled(_AutoBackfillDryRunBase):
    """With both env gates off (default), the runner must skip with
    ``decision_reason=disabled`` and surface no selected candidates.
    """

    def test_default_env_yields_disabled_skip(self) -> None:
        r = client.post("/diagnostics/auto-backfill-dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ABF_DRY_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(body["decision_reason"], "disabled")
        self.assertEqual(body["skip_reason"],     "disabled")
        self.assertFalse(body["started"])
        self.assertFalse(body["completed"])
        self.assertEqual(body["selected"], [])
        self.assertEqual(body["selected_count"], 0)
        # Lock never acquired on the disabled skip path.
        self.assertFalse(body["state"]["lock_held"])
        # Ledger snapshot reflects the ephemeral instance — used=0,
        # remaining=cap.  Spent calls is always 0 in dry-run.
        self.assertEqual(body["ledger"]["used"], 0)
        self.assertEqual(body["spent_calls"],    0)
        # State stamp records the skip reason for diagnostic visibility.
        self.assertEqual(body["state"]["last_skip_reason"], "disabled")

    def test_paid_guard_blocked_when_only_auto_backfill_set(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        # ENABLE_PAID_ANALYSIS deliberately not set.
        body = client.post("/diagnostics/auto-backfill-dry-run").json()
        self.assertEqual(body["decision_reason"], "paid_guard_blocked")
        self.assertEqual(body["skip_reason"],     "paid_guard_blocked")
        self.assertFalse(body["started"])
        self.assertFalse(body["completed"])
        self.assertEqual(body["selected_count"], 0)


class TestAutoBackfillDryRunConfigured(_AutoBackfillDryRunBase):
    """With both gates enabled and mock candidates injected, the runner
    completes a dry-run tick and surfaces the planner selection.
    """

    def setUp(self) -> None:
        super().setUp()
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def test_configured_with_mock_candidates_completes(self) -> None:
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps",        7),
            self._cluster("Federal Reserve hikes rates by 25bps",    6),
            self._cluster("Federal Reserve announces QE tapering",   4),
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.post("/diagnostics/auto-backfill-dry-run").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["decision_reason"], "configured")
        self.assertTrue(body["started"])
        self.assertTrue(body["completed"])
        self.assertIsNone(body["skip_reason"])
        # Default max_calls_per_run=3 — all 3 candidates fit.
        self.assertEqual(body["selected_count"], 3)
        self.assertEqual(len(body["selected"]),  3)
        selected_headlines = {c["headline"] for c in body["selected"]}
        self.assertEqual(
            selected_headlines,
            {c["headline"] for c in clusters},
        )
        # candidate_queue_counts reflect the eligible pool the planner saw.
        self.assertEqual(body["candidate_queue_counts"]["eligible"], 3)
        # Run id is stamped; spent_calls is always 0 in dry-run.
        self.assertIsNotNone(body["run_id"])
        self.assertEqual(body["spent_calls"], 0)

    def test_already_analyzed_filtered_from_selection(self) -> None:
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps",        7),
            self._cluster("Federal Reserve hikes rates by 25bps",    6),
        ]
        # First headline is registry-state ``analyzed`` → excluded; the
        # second survives.
        analyzed_first_headline = clusters[0]["headline"]

        def _state(title_key):
            from routes.movers import _hr_dedup_key as _key
            if title_key == _key(analyzed_first_headline):
                return ("analyzed", 1)
            return (None, None)

        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            side_effect=_state,
        ):
            body = client.post("/diagnostics/auto-backfill-dry-run").json()
        self.assertEqual(body["selected_count"], 1)
        self.assertEqual(
            body["selected"][0]["headline"],
            "Federal Reserve hikes rates by 25bps",
        )
        self.assertEqual(body["candidate_queue_counts"]["already_analyzed"], 1)
        self.assertEqual(body["candidate_queue_counts"]["eligible"],         1)


class TestAutoBackfillDryRunCapEnforcement(_AutoBackfillDryRunBase):
    """The planner's run cap (env-driven ``max_calls_per_run``) caps the
    selection.  Excess candidates land in ``skip_counts`` under
    ``run_cap_exhausted`` (or ``daily_cap_exhausted``) so the response
    is self-explaining.
    """

    def test_run_cap_caps_selection_and_records_overflow(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        # Force the planner to a 2-per-run cap; 5 candidates ⇒ 3
        # overflow into the skip-count bucket.
        os.environ["AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN"] = "2"
        clusters = [
            self._cluster(f"Federal Reserve hikes rates by {i}bps", 5 + i)
            for i in range(5)
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.post("/diagnostics/auto-backfill-dry-run").json()
        self.assertTrue(body["completed"])
        self.assertEqual(body["selected_count"], 2)
        self.assertEqual(len(body["selected"]),  2)
        # 5 considered → 2 selected → 3 overflow.  Per-run cap is the
        # binding constraint here; daily_cap (default 12) is not.
        overflow = (
            body["skip_counts"].get("run_cap_exhausted", 0)
            + body["skip_counts"].get("daily_cap_exhausted", 0)
        )
        self.assertEqual(overflow, 3)
        self.assertEqual(body["effective_call_cap"], 2)
        # Top-ranked clusters survive the cap (highest source_count).
        survivors = [c["source_count"] for c in body["selected"]]
        self.assertEqual(sorted(survivors, reverse=True), survivors)
        self.assertEqual(survivors, [9, 8])


class TestAutoBackfillDryRunNoLedgerMutation(_AutoBackfillDryRunBase):
    """The dry-run endpoint must NEVER reserve a ledger call against the
    long-lived ``/auto-backfill-status`` singleton.  Per request a
    fresh ephemeral ledger is constructed; the status singleton stays
    untouched.
    """

    def test_status_singleton_ledger_stays_at_zero_after_repeated_dry_runs(
        self,
    ) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        clusters = [
            self._cluster(f"Federal Reserve cuts rates {i}bps", 5)
            for i in range(3)
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            for _ in range(4):
                r = client.post("/diagnostics/auto-backfill-dry-run")
                self.assertEqual(r.status_code, 200)
                # spent_calls is the contract-level guarantee.
                self.assertEqual(r.json()["spent_calls"], 0)
        # The /auto-backfill-status singleton ledger was never touched —
        # either still None (lazy) or, if a status call landed first,
        # used=0.
        from routes import diagnostics as _diag
        if _diag._AUTO_BACKFILL_LEDGER is not None:
            snap = _diag._AUTO_BACKFILL_LEDGER.snapshot()
            self.assertEqual(snap.used, 0)
        # Cross-check via the status endpoint.
        status = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(status["ledger"]["used"], 0)

    def test_per_request_ledger_remaining_equals_cap_after_dry_run(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        clusters = [self._cluster("Federal Reserve cuts rates 50bps", 7)]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            body = client.post("/diagnostics/auto-backfill-dry-run").json()
        # The ephemeral ledger is reported in the response: used=0,
        # remaining=daily_cap.  This is the load-bearing assertion that
        # no call was reserved during the tick.
        self.assertEqual(body["ledger"]["used"], 0)
        self.assertEqual(body["ledger"]["remaining"], body["ledger"]["daily_cap"])
        self.assertEqual(body["spent_calls"], 0)


class TestAutoBackfillDryRunNoProviderCalls(_AutoBackfillDryRunBase):
    """Zero-cost guarantee: no LLM, no ``yfinance``, no
    ``market_check``, no provider seam may be invoked even on the
    happy-path completed tick.
    """

    def test_no_provider_or_paid_seams_invoked(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        clusters = [
            self._cluster("Federal Reserve cuts rates 50bps", 7),
            self._cluster("Federal Reserve hikes rates by 25bps", 6),
        ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ), patch(
            "api.analyze_event",
            side_effect=AssertionError("must not call analyze_event"),
        ), patch(
            "api.market_check",
            side_effect=AssertionError("must not call market_check"),
        ), patch(
            "yfinance.download",
            side_effect=AssertionError("must not call yfinance.download"),
        ), patch(
            "yfinance.Ticker",
            side_effect=AssertionError("must not call yfinance.Ticker"),
        ), patch(
            "auto_backfill_runner.execute_paid_candidate",
            side_effect=AssertionError("must not call execute_paid_candidate"),
        ):
            r = client.post("/diagnostics/auto-backfill-dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["completed"])
        self.assertGreater(body["selected_count"], 0)


class TestAutoBackfillDryRunNoDBMutation(_AutoBackfillDryRunBase):
    """The endpoint must never write to SQLite.  Repeated dry-run hits
    leave the events table byte-identical and the fingerprint stable.
    """

    def setUp(self) -> None:
        super().setUp()
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def test_repeated_calls_do_not_change_archive_fingerprint(self) -> None:
        clusters = [self._cluster("Federal Reserve cuts rates 50bps", 7)]
        before = db.get_events_fingerprint()
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            for _ in range(3):
                client.post("/diagnostics/auto-backfill-dry-run")
        self.assertEqual(db.get_events_fingerprint(), before)

    def test_repeated_calls_do_not_modify_event_rows(self) -> None:
        clusters = [self._cluster("Federal Reserve hikes rates by 25bps", 6)]
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            before = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM events"
                ).fetchall()
            ]
        with patch(
            "routes.movers._cached_news_payload",
            return_value=self._payload(*clusters),
        ), patch(
            "routes.movers._registry_state_for_title_key",
            return_value=(None, None),
        ):
            for _ in range(3):
                client.post("/diagnostics/auto-backfill-dry-run")
        with _sqlite3.connect(db.DB_FILE) as conn:
            conn.row_factory = _sqlite3.Row
            after = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM events"
                ).fetchall()
            ]
        self.assertEqual(before, after)


class TestAutoBackfillDryRunFallback(_AutoBackfillDryRunBase):
    def test_loader_failure_falls_back_to_unavailable_shape(self) -> None:
        # When the underlying loader raises, the endpoint must return
        # 200 with the stable unavailable shape rather than 500.
        with patch(
            "routes.diagnostics.load_auto_backfill_config",
            side_effect=RuntimeError("boom"),
        ):
            r = client.post("/diagnostics/auto-backfill-dry-run")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _ABF_DRY_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertFalse(body["available"])
        self.assertEqual(body["selected"], [])
        self.assertEqual(body["selected_count"], 0)
        self.assertEqual(body["decision_reason"], "unavailable")


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-status — scheduler skeleton block
# ---------------------------------------------------------------------------


# Snapshot threads BEFORE and AFTER importing routes.diagnostics so the
# "no scheduler thread spawned by import" check below is order-
# independent.  Both snapshots are taken at module load time, so a
# later test that starts a real scheduler cannot pollute them.
import threading as _threading  # noqa: E402

_DIAG_THREADS_BEFORE_IMPORT: set[str] = {
    (t.name or "").lower() for t in _threading.enumerate()
}
import routes.diagnostics as _diagnostics_module  # noqa: E402,F401
_DIAG_THREADS_AFTER_IMPORT: set[str] = {
    (t.name or "").lower() for t in _threading.enumerate()
}


class TestAutoBackfillStatusSchedulerBlock(_AutoBackfillStatusBase):
    """The status endpoint exposes a scheduler skeleton block.  The
    diagnostics layer must never start an APScheduler thread — neither
    on module import nor on endpoint hit.
    """

    def test_scheduler_block_present_with_required_keys(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIn("scheduler", body)
        for key in _ABF_STATUS_SCHEDULER_KEYS:
            self.assertIn(
                key, body["scheduler"],
                f"missing scheduler sub-key: {key}",
            )

    def test_scheduler_started_defaults_false(self) -> None:
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIs(body["scheduler"]["scheduler_started"], False)
        self.assertEqual(body["scheduler"]["job_count"], 0)
        self.assertEqual(body["scheduler"]["mode"], "not_wired")

    def test_scheduler_available_when_module_importable(self) -> None:
        # ``auto_backfill_scheduler.py`` lives in the repo and imports
        # cleanly in the test environment, so the block reports
        # available=True.
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIs(body["scheduler"]["scheduler_available"], True)

    def test_scheduler_started_unchanged_under_configured_env(self) -> None:
        # Even when both env gates are true, the diagnostics layer
        # never starts a scheduler — lifespan wiring is out of scope
        # for this skeleton.
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["effective_status"], "configured")
        self.assertIs(body["scheduler"]["scheduler_started"], False)
        self.assertEqual(body["scheduler"]["job_count"], 0)
        self.assertEqual(body["scheduler"]["mode"], "not_wired")

    def test_scheduler_unavailable_when_module_import_fails(self) -> None:
        # Patch the late-import path so the block reports unavailable
        # without requiring the file to actually be missing.
        builtins_import = __import__

        def _raising_import(name, *args, **kwargs):
            if name == "auto_backfill_scheduler":
                raise ImportError("simulated missing dep")
            return builtins_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_raising_import):
            body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIs(body["scheduler"]["scheduler_available"], False)
        # Even when unavailable, scheduler_started/job_count/mode stay
        # at their conservative defaults.
        self.assertIs(body["scheduler"]["scheduler_started"], False)
        self.assertEqual(body["scheduler"]["job_count"], 0)
        self.assertEqual(body["scheduler"]["mode"], "not_wired")

    def test_unavailable_fallback_carries_full_scheduler_block(self) -> None:
        # When the upstream loader raises, the unavailable shape must
        # still carry every scheduler sub-key so consumers never have
        # to branch on key presence.
        with patch(
            "routes.diagnostics.load_auto_backfill_config",
            side_effect=RuntimeError("boom"),
        ):
            body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertIn("scheduler", body)
        for key in _ABF_STATUS_SCHEDULER_KEYS:
            self.assertIn(key, body["scheduler"])
        self.assertIs(body["scheduler"]["scheduler_started"], False)
        self.assertEqual(body["scheduler"]["job_count"], 0)
        self.assertEqual(body["scheduler"]["mode"], "not_wired")


class TestAutoBackfillStatusReflectsAttachedScheduler(_AutoBackfillStatusBase):
    """When the FastAPI lifespan publishes a scheduler to
    ``app.state.auto_backfill_scheduler``, the status endpoint reports
    ``mode="dry_run_only"`` and reflects the scheduler's ``running`` /
    ``get_jobs()`` accessors.  Tests use fake scheduler objects — no
    real ``BackgroundScheduler`` is constructed and no thread spawns.
    """

    def setUp(self) -> None:
        super().setUp()
        # Defensively clear any leftover scheduler from prior tests so
        # this class always starts from the not-wired state.
        self._clear_scheduler()

    def tearDown(self) -> None:
        self._clear_scheduler()
        super().tearDown()

    @staticmethod
    def _clear_scheduler() -> None:
        # Starlette's State.__delattr__ raises KeyError on a missing
        # key; guard both KeyError and AttributeError so this stays a
        # true no-op when nothing was attached.
        try:
            delattr(api.app.state, "auto_backfill_scheduler")
        except (AttributeError, KeyError):
            pass

    def _attach(self, **kwargs) -> object:
        """Attach a fake scheduler to ``app.state`` and return it."""
        from unittest.mock import MagicMock
        fake = MagicMock(**kwargs)
        api.app.state.auto_backfill_scheduler = fake
        return fake

    def test_running_attached_scheduler_reports_dry_run_only(self) -> None:
        self._attach(running=True, get_jobs=lambda: [object()])
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], True)
        self.assertEqual(block["job_count"], 1)

    def test_running_scheduler_reflects_multiple_jobs(self) -> None:
        self._attach(
            running=True,
            get_jobs=lambda: [object(), object(), object()],
        )
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], True)
        self.assertEqual(block["job_count"], 3)

    def test_attached_but_not_running_reports_not_started(self) -> None:
        self._attach(running=False, get_jobs=lambda: [object()])
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], False)
        # job_count still reports the planned jobs even when not started.
        self.assertEqual(block["job_count"], 1)

    def test_get_jobs_exception_falls_back_to_zero(self) -> None:
        from unittest.mock import MagicMock
        fake = MagicMock(running=True)
        fake.get_jobs.side_effect = RuntimeError("get_jobs blew up")
        api.app.state.auto_backfill_scheduler = fake
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        # The attachment is real, so mode stays dry_run_only — only the
        # enumeration broke.
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], True)
        self.assertEqual(block["job_count"], 0)

    def test_get_jobs_returns_none_safely(self) -> None:
        self._attach(running=True, get_jobs=lambda: None)
        body = client.get("/diagnostics/auto-backfill-status").json()
        self.assertEqual(body["scheduler"]["job_count"], 0)
        self.assertEqual(body["scheduler"]["mode"], "dry_run_only")

    def test_attribute_missing_falls_back_to_not_wired(self) -> None:
        # Explicit absence — no attach call.  This is the default state
        # when the lifespan did not publish a scheduler.
        self._clear_scheduler()
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "not_wired")
        self.assertIs(block["scheduler_started"], False)
        self.assertEqual(block["job_count"], 0)

    def test_running_attribute_missing_treated_as_not_started(self) -> None:
        # A scheduler-shaped object lacking ``running`` is still a
        # legitimate attachment (mode dry_run_only) but cannot be
        # reported as started.
        from unittest.mock import MagicMock
        fake = MagicMock(spec=[])  # no attributes
        fake.get_jobs = lambda: []
        api.app.state.auto_backfill_scheduler = fake
        body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], False)

    def test_diagnostics_does_not_invoke_scheduler_start(self) -> None:
        # Strict invariant: the diagnostics path must never call
        # start/shutdown on the attached scheduler.  A start() call
        # here would be a regression on "diagnostics is read-only".
        from unittest.mock import MagicMock
        fake = MagicMock(running=False, get_jobs=lambda: [])
        api.app.state.auto_backfill_scheduler = fake
        client.get("/diagnostics/auto-backfill-status")
        client.get("/diagnostics/auto-backfill-status")
        fake.start.assert_not_called()
        fake.shutdown.assert_not_called()


class TestAutoBackfillStatusNoSchedulerThread(_AutoBackfillStatusBase):
    def test_importing_routes_diagnostics_does_not_spawn_scheduler_thread(
        self,
    ) -> None:
        new_threads = (
            _DIAG_THREADS_AFTER_IMPORT - _DIAG_THREADS_BEFORE_IMPORT
        )
        for name in new_threads:
            self.assertNotIn(
                "apscheduler", name,
                f"importing routes.diagnostics spawned an APScheduler "
                f"thread: {name!r}",
            )

    def test_status_endpoint_call_does_not_spawn_scheduler_thread(
        self,
    ) -> None:
        # Snapshot threads immediately before the request, then
        # immediately after.  Any APScheduler-named thread that
        # appeared would mean the diagnostics path instantiated and
        # started a scheduler — a regression on the "do not start
        # scheduler" contract.
        before = {(t.name or "").lower() for t in _threading.enumerate()}
        client.get("/diagnostics/auto-backfill-status")
        after = {(t.name or "").lower() for t in _threading.enumerate()}
        new = after - before
        for name in new:
            self.assertNotIn("apscheduler", name)

    def test_repeated_status_calls_do_not_accumulate_threads(self) -> None:
        before = len(_threading.enumerate())
        for _ in range(5):
            client.get("/diagnostics/auto-backfill-status")
        after = len(_threading.enumerate())
        # Allow small fluctuations from FastAPI / TestClient internals,
        # but reject monotonic growth — a per-request scheduler would
        # leak threads on every call.
        self.assertLess(
            after - before, 3,
            f"thread count grew by {after - before} after 5 status "
            f"calls — possible scheduler leak",
        )

# ---------------------------------------------------------------------------
# /diagnostics/price-cache-coverage — pure-SQL coverage view
# ---------------------------------------------------------------------------


_PRICE_CACHE_TOP_KEYS = (
    "total_events",
    "events_with_market_tickers",
    "unique_tickers",
    "tickers_with_cache_rows",
    "tickers_without_cache_rows",
    "events_with_any_forward_cache",
    "events_with_5d_forward_cache",
    "events_with_20d_forward_cache",
    "coverage_by_event_age_bucket",
    "latest_cache_date",
)

_PRICE_CACHE_BUCKET_KEYS = ("0_7d", "8_30d", "31_90d", "91d_plus", "unknown")

_PRICE_CACHE_BUCKET_FIELDS = (
    "total_events",
    "events_with_market_tickers",
    "events_with_any_forward_cache",
    "events_with_5d_forward_cache",
    "events_with_20d_forward_cache",
)


def _insert_price_cache_row_for_coverage(
    db_path: str,
    ticker: str,
    iso_date: str,
    *,
    auto_adjust: int = 1,
    close: float = 100.0,
    volume: float = 5_000_000.0,
) -> None:
    """Direct INSERT into ``price_cache``.

    Bypasses ``price_cache.fetch_daily_cached`` so the test never
    touches the provider or cache-write side-effect path.  ``init_db``
    creates the table at setUp; we just upsert.
    """
    conn = _sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO price_cache
                (ticker, date, close, volume, auto_adjust, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ticker.upper(),
                iso_date,
                close,
                volume,
                auto_adjust,
                "2026-05-06T12:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _snapshot_tables_for_coverage(db_path: str) -> tuple[list[tuple], list[tuple]]:
    conn = _sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class _PriceCacheCoverageBase(_Base):
    """Adds a ``today_minus`` helper anchored on ``date.today()``.

    Tests that need deterministic age-bucket placement compute their
    ``event_date`` relative to today, so the bucket assignment stays
    stable regardless of when the suite runs.
    """

    @staticmethod
    def _today_minus(days: int) -> str:
        from datetime import date as _date, timedelta as _td
        return (_date.today() - _td(days=days)).isoformat()

    @staticmethod
    def _seed_event(
        *,
        event_date: str | None,
        symbols: list[str],
        headline: str | None = None,
    ) -> None:
        head = headline or f"Coverage seed {uuid.uuid4().hex[:10]}"
        db.save_event({
            "headline":       head,
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     event_date,
            "market_tickers": [{"symbol": s.upper()} for s in symbols],
        })


class TestPriceCacheCoverageEmptyDB(_PriceCacheCoverageBase):
    def test_returns_200_with_full_top_keyset(self) -> None:
        r = client.get("/diagnostics/price-cache-coverage")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _PRICE_CACHE_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_all_counts_zero_on_empty_db(self) -> None:
        body = client.get("/diagnostics/price-cache-coverage").json()
        for key in (
            "total_events",
            "events_with_market_tickers",
            "unique_tickers",
            "tickers_with_cache_rows",
            "tickers_without_cache_rows",
            "events_with_any_forward_cache",
            "events_with_5d_forward_cache",
            "events_with_20d_forward_cache",
        ):
            self.assertEqual(body[key], 0, f"{key} should be zero")
        self.assertIsNone(body["latest_cache_date"])

    def test_bucket_keyset_and_fields_stable_on_empty_db(self) -> None:
        body = client.get("/diagnostics/price-cache-coverage").json()
        buckets = body["coverage_by_event_age_bucket"]
        self.assertEqual(set(buckets.keys()), set(_PRICE_CACHE_BUCKET_KEYS))
        for label in _PRICE_CACHE_BUCKET_KEYS:
            self.assertEqual(
                set(buckets[label].keys()),
                set(_PRICE_CACHE_BUCKET_FIELDS),
                f"bucket {label!r} missing one of the required fields",
            )
            self.assertEqual(sum(buckets[label].values()), 0)


class TestPriceCacheCoverageSeededRows(_PriceCacheCoverageBase):
    def test_total_and_unique_counts_reflect_seeded_events(self) -> None:
        self._seed_event(
            event_date=self._today_minus(2),
            symbols=["AAPL", "MSFT"],
        )
        self._seed_event(
            event_date=self._today_minus(20),
            symbols=["AAPL", "GOOG"],
        )
        # Event with no tickers contributes only to ``total_events``.
        db.save_event({
            "headline":       "No-ticker coverage seed",
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     self._today_minus(1),
            "market_tickers": [],
        })

        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["total_events"],               3)
        self.assertEqual(body["events_with_market_tickers"], 2)
        self.assertEqual(body["unique_tickers"],             3)
        self.assertEqual(body["tickers_with_cache_rows"],    0)
        self.assertEqual(body["tickers_without_cache_rows"], 3)
        self.assertEqual(body["events_with_any_forward_cache"], 0)
        self.assertEqual(body["events_with_5d_forward_cache"],  0)
        self.assertEqual(body["events_with_20d_forward_cache"], 0)

    def test_ticker_split_with_and_without_cache_rows(self) -> None:
        self._seed_event(
            event_date=self._today_minus(2),
            symbols=["AAPL", "TSLA"],
        )
        # Only AAPL has a cache row; TSLA does not.
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )

        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["unique_tickers"],             2)
        self.assertEqual(body["tickers_with_cache_rows"],    1)
        self.assertEqual(body["tickers_without_cache_rows"], 1)
        self.assertEqual(body["latest_cache_date"], self._today_minus(1))

    def test_forward_cache_satisfied_at_long_horizon(self) -> None:
        # Event 60 calendar days ago — well past +20 business days, so
        # any cache row from yesterday satisfies all three horizons.
        self._seed_event(
            event_date=self._today_minus(60),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )

        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["events_with_any_forward_cache"], 1)
        self.assertEqual(body["events_with_5d_forward_cache"],  1)
        self.assertEqual(body["events_with_20d_forward_cache"], 1)

    def test_forward_cache_zero_when_cache_predates_event(self) -> None:
        # Event today, cache row dated yesterday → cache max is BEFORE
        # the event date, so no horizon (including ``any``) is satisfied.
        self._seed_event(
            event_date=self._today_minus(0),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )
        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["events_with_any_forward_cache"], 0)
        self.assertEqual(body["events_with_5d_forward_cache"],  0)
        self.assertEqual(body["events_with_20d_forward_cache"], 0)

    def test_5d_horizon_can_pass_while_20d_horizon_fails(self) -> None:
        # Event ~1 calendar week ago.  +5 business days from then is
        # near today (covered by a cache row dated today); +20 business
        # days lands ~3 weeks in the future, which the cache cannot
        # satisfy.
        self._seed_event(
            event_date=self._today_minus(7),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(0),
        )
        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["events_with_any_forward_cache"], 1)
        self.assertEqual(body["events_with_5d_forward_cache"],  1)
        self.assertEqual(body["events_with_20d_forward_cache"], 0)

    def test_or_across_tickers_for_per_event_truth(self) -> None:
        # One event with two tickers; only one ticker has a recent
        # cache row.  Per-event truth is OR across tickers, so the
        # event still counts once for each satisfied horizon.
        self._seed_event(
            event_date=self._today_minus(60),
            symbols=["AAPL", "TSLA"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )
        # TSLA cached only at a date that PRECEDES the event.
        _insert_price_cache_row_for_coverage(
            self._tmp, "TSLA", self._today_minus(120),
        )
        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["events_with_any_forward_cache"], 1)
        self.assertEqual(body["events_with_5d_forward_cache"],  1)
        self.assertEqual(body["events_with_20d_forward_cache"], 1)

    def test_event_without_event_date_lands_in_unknown_bucket(self) -> None:
        # Event with no ``event_date`` contributes to the ``unknown``
        # bucket and counts toward ``total_events`` /
        # ``events_with_market_tickers`` / ``unique_tickers`` but
        # NEVER toward forward-cache counters.
        db.save_event({
            "headline":       "Date-less event",
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     None,
            "market_tickers": [{"symbol": "AAPL"}],
        })
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(0),
        )

        body = client.get("/diagnostics/price-cache-coverage").json()
        self.assertEqual(body["total_events"],                  1)
        self.assertEqual(body["events_with_market_tickers"],    1)
        self.assertEqual(body["unique_tickers"],                1)
        self.assertEqual(body["tickers_with_cache_rows"],       1)
        self.assertEqual(body["events_with_any_forward_cache"], 0)
        self.assertEqual(body["events_with_5d_forward_cache"],  0)
        self.assertEqual(body["events_with_20d_forward_cache"], 0)
        unknown = body["coverage_by_event_age_bucket"]["unknown"]
        self.assertEqual(unknown["total_events"],               1)
        self.assertEqual(unknown["events_with_market_tickers"], 1)
        for f in (
            "events_with_any_forward_cache",
            "events_with_5d_forward_cache",
            "events_with_20d_forward_cache",
        ):
            self.assertEqual(unknown[f], 0)

    def test_age_bucket_totals_sum_to_archive_total(self) -> None:
        # Every event must land in exactly one bucket — across-bucket
        # sums of ``total_events`` and ``events_with_market_tickers``
        # must equal the top-level totals.
        self._seed_event(
            event_date=self._today_minus(1),    # 0_7d
            symbols=["AAPL"],
        )
        self._seed_event(
            event_date=self._today_minus(15),   # 8_30d
            symbols=["MSFT"],
        )
        self._seed_event(
            event_date=self._today_minus(45),   # 31_90d
            symbols=["GOOG"],
        )
        self._seed_event(
            event_date=self._today_minus(180),  # 91d_plus
            symbols=["TSLA"],
        )
        # No event_date → unknown bucket; counts toward total_events.
        db.save_event({
            "headline":       "Bucket-sum no-date",
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     None,
            "market_tickers": [],
        })

        body = client.get("/diagnostics/price-cache-coverage").json()
        buckets = body["coverage_by_event_age_bucket"]
        self.assertEqual(
            sum(b["total_events"] for b in buckets.values()),
            body["total_events"],
        )
        self.assertEqual(
            sum(b["events_with_market_tickers"] for b in buckets.values()),
            body["events_with_market_tickers"],
        )
        # Each dated event falls in its expected bucket.
        self.assertEqual(buckets["0_7d"]["total_events"],     1)
        self.assertEqual(buckets["8_30d"]["total_events"],    1)
        self.assertEqual(buckets["31_90d"]["total_events"],   1)
        self.assertEqual(buckets["91d_plus"]["total_events"], 1)
        self.assertEqual(buckets["unknown"]["total_events"],  1)


class TestPriceCacheCoverageNoMutation(_PriceCacheCoverageBase):
    def test_repeated_calls_do_not_modify_events_or_price_cache(self) -> None:
        self._seed_event(
            event_date=self._today_minus(10),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(2),
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )

        before = _snapshot_tables_for_coverage(self._tmp)
        for _ in range(3):
            r = client.get("/diagnostics/price-cache-coverage")
            self.assertEqual(r.status_code, 200)
        after = _snapshot_tables_for_coverage(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache rows must be byte-identical "
            "before and after repeated endpoint calls",
        )

    def test_corrupt_fingerprint_row_is_not_purged(self) -> None:
        # The endpoint must NOT invoke ``price_cache._ensure_table``
        # (which would trigger ``_purge_corrupt_rows``) — verify by
        # seeding a row matching the corrupt fingerprint and asserting
        # it survives.
        self._seed_event(
            event_date=self._today_minus(10),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(2),
            close=2.0, volume=1_000_000.0,
        )
        before = _snapshot_tables_for_coverage(self._tmp)
        client.get("/diagnostics/price-cache-coverage")
        after = _snapshot_tables_for_coverage(self._tmp)
        self.assertEqual(
            before, after,
            "corrupt-fingerprint row must survive — endpoint must not "
            "trigger price_cache._purge_corrupt_rows",
        )


class TestPriceCacheCoverageNoProviderCalls(_PriceCacheCoverageBase):
    """Endpoint must never call market_check, market_data, yfinance,
    fetch_daily_cached, or any LLM seam.  Patches every plausible
    provider seam with a raiser so a regression that pulls one in
    blows up loudly.
    """

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        self._seed_event(
            event_date=self._today_minus(10),
            symbols=["AAPL"],
        )
        _insert_price_cache_row_for_coverage(
            self._tmp, "AAPL", self._today_minus(1),
        )

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
            ("price_cache",  "_ensure_table"),
        )

        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"price-cache-coverage must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "price-cache-coverage must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            r = client.get("/diagnostics/price-cache-coverage")

        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Sanity: the seeded event + cache row are reflected in the
        # response, proving the endpoint produced real output rather
        # than degrading to the empty fallback.
        self.assertEqual(body["total_events"],            1)
        self.assertEqual(body["unique_tickers"],          1)
        self.assertEqual(body["tickers_with_cache_rows"], 1)


# ---------------------------------------------------------------------------
# /diagnostics/reaction-profile-blockers — per-event/ticker hydration triage
# ---------------------------------------------------------------------------


_RPB_TOP_KEYS = (
    "available",
    "total_events",
    "counts",
    "examples",
)

_RPB_REASON_KEYS = (
    "no_market_tickers",
    "no_event_date",
    "no_anchor_close",
    "no_forward_1d_close",
    "no_forward_5d_close",
    "no_forward_20d_close",
    "scalar_returns_only_fallback",
    "hydrated_from_price_cache",
    "invalid_ticker",
)


class TestReactionProfileBlockersShape(_TrackRecordBase):
    def test_returns_200_with_top_keyset(self) -> None:
        r = client.get("/diagnostics/reaction-profile-blockers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in _RPB_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_counts_carries_every_reason_key(self) -> None:
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(set(body["counts"].keys()), set(_RPB_REASON_KEYS))


class TestReactionProfileBlockersEmptyDB(_TrackRecordBase):
    def test_available_true_on_empty_db(self) -> None:
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertTrue(body["available"])
        self.assertEqual(body["total_events"], 0)
        for reason in _RPB_REASON_KEYS:
            self.assertEqual(
                body["counts"][reason], 0,
                f"{reason} should be zero on empty DB",
            )
        self.assertEqual(body["examples"], [])


class TestReactionProfileBlockersClassification(_TrackRecordBase):
    def test_no_market_tickers_counts_events_with_empty_tickers(self) -> None:
        self._seed(market_tickers=[])
        self._seed(market_tickers=[])
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_market_tickers"], 2)

    def test_no_event_date_counts_each_ticker_when_date_missing(self) -> None:
        self._seed(
            event_date=None,
            market_tickers=[
                {"symbol": "AAPL"},
                {"symbol": "MSFT"},
            ],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_event_date"], 2)

    def test_invalid_ticker_counts_dicts_missing_symbol(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[
                {"direction_tag": "supports thesis"},   # no symbol field
                {"symbol": ""},                          # empty symbol
                {"symbol": "AAPL", "anchor_date": today},  # valid
            ],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["invalid_ticker"], 2)

    def test_no_anchor_close_counts_tickers_without_cache_rows(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "ZZZ_NO_CACHE",
                             "anchor_date": today}],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_anchor_close"], 1)
        self.assertEqual(body["counts"]["scalar_returns_only_fallback"], 0)

    def test_scalar_returns_only_fallback_counts_legacy_returns(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{
                "symbol":      "ZZZ_NO_CACHE",
                "anchor_date": today,
                "return_5d":   1.23,
            }],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["scalar_returns_only_fallback"], 1)
        self.assertEqual(body["counts"]["no_anchor_close"], 0)

    def test_no_forward_1d_close_when_only_anchor_bar_cached(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        # Single bar at the anchor; composer sees < 2 closes → all returns None.
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today, closes=[100.0],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_forward_1d_close"], 1)

    def test_no_forward_5d_close_when_window_short_of_5d_bar(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        # Anchor + 1 bar → return_1d populates, return_5d / 20d are None.
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today, closes=[100.0, 101.0],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_forward_5d_close"], 1)

    def test_no_forward_20d_close_when_window_short_of_20d_bar(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        # Anchor + 5 bars → return_5d populates, return_20d is None.
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_forward_20d_close"], 1)

    def test_hydrated_when_full_forward_window_present(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        # Anchor + 21 bars → return_1d / 5d / 20d all populate.
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0] + [100.0 + i * 0.5 for i in range(1, 22)],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["hydrated_from_price_cache"], 1)
        self.assertEqual(body["counts"]["no_forward_20d_close"], 0)


class TestReactionProfileBlockersExamples(_TrackRecordBase):
    def test_examples_capped_at_10(self) -> None:
        for _ in range(12):
            self._seed(market_tickers=[])
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["no_market_tickers"], 12)
        self.assertEqual(len(body["examples"]), 10)

    def test_example_carries_required_fields(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "ZZZ_NO_CACHE",
                             "anchor_date": today}],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertGreaterEqual(len(body["examples"]), 1)
        ex = body["examples"][0]
        for key in ("event_id", "headline", "ticker", "missing_reason"):
            self.assertIn(key, ex, f"example missing field: {key}")
        self.assertEqual(ex["ticker"], "ZZZ_NO_CACHE")
        self.assertEqual(ex["missing_reason"], "no_anchor_close")
        self.assertIsInstance(ex["event_id"], int)
        self.assertIsInstance(ex["headline"], str)

    def test_no_market_tickers_example_has_null_ticker(self) -> None:
        self._seed(market_tickers=[])
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(len(body["examples"]), 1)
        ex = body["examples"][0]
        self.assertIsNone(ex["ticker"])
        self.assertEqual(ex["missing_reason"], "no_market_tickers")

    def test_examples_exclude_hydrated_success_rows(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0] + [100.0 + i * 0.5 for i in range(1, 22)],
        )
        body = client.get("/diagnostics/reaction-profile-blockers").json()
        self.assertEqual(body["counts"]["hydrated_from_price_cache"], 1)
        self.assertEqual(body["examples"], [])


class TestReactionProfileBlockersNoMutation(_TrackRecordBase):
    def test_repeated_calls_do_not_modify_event_or_cache_rows(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
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
        for _ in range(3):
            client.get("/diagnostics/reaction-profile-blockers")
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

    def test_repeated_calls_do_not_change_fingerprint(self) -> None:
        self._seed()
        before = db.get_events_fingerprint()
        for _ in range(3):
            client.get("/diagnostics/reaction-profile-blockers")
        self.assertEqual(db.get_events_fingerprint(), before)


class TestReactionProfileBlockersZeroCost(_TrackRecordBase):
    """Endpoint must not invoke market_check / yfinance / provider /
    LLM seams.  Patches every plausible network seam with a raiser so a
    regression that pulls one in blows up loudly."""

    def test_no_provider_yfinance_or_market_check_seam(self) -> None:
        from contextlib import ExitStack

        today = datetime.now().strftime("%Y-%m-%d")
        self._seed(
            event_date=today,
            market_tickers=[{"symbol": "AAPL", "anchor_date": today}],
        )
        _seed_price_cache(
            self._tmp, ticker="AAPL", start=today,
            closes=[100.0, 101.0, 102.0],
        )

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("price_cache",  "fetch_daily_cached"),
        )
        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"reaction-profile-blockers must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "reaction-profile-blockers must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            r = client.get("/diagnostics/reaction-profile-blockers")
        self.assertEqual(r.status_code, 200)


class TestReactionProfileBlockersPartialFailure(_TrackRecordBase):
    def test_aggregator_failure_flips_available_false(self) -> None:
        self._seed()
        with patch(
            "routes.diagnostics._compute_reaction_profile_blockers",
            side_effect=RuntimeError("aggregator fail"),
        ):
            r = client.get("/diagnostics/reaction-profile-blockers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["available"])
        self.assertEqual(body["total_events"], 0)
        self.assertEqual(body["examples"], [])
        for reason in _RPB_REASON_KEYS:
            self.assertEqual(body["counts"][reason], 0)


if __name__ == "__main__":
    unittest.main()

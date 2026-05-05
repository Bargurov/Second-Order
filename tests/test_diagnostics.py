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


if __name__ == "__main__":
    unittest.main()

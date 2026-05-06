"""Tests for ``scripts/no_paid_smoke.py``.

The smoke script is the local demo preflight: it should hit only
zero-cost read endpoints, fail closed if any paid/provider seam is
called, and leave the archive DB untouched.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402
import db  # noqa: E402
import movers_cache  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from scripts import no_paid_smoke  # noqa: E402


client = TestClient(api.app)


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_no_paid_smoke_{uuid.uuid4().hex}.db",
    )


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


def _seed_event_1() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    db.save_event({
        "headline": "No-paid smoke seed event",
        "stage": "realized",
        "persistence": "medium",
        "event_date": today,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "what_changed": "A realistic local smoke fixture changed.",
        "mechanism_summary": "Fixture mechanism text long enough to read.",
        "transmission_chain": ["headline", "market expectation"],
        "if_persists": {"thesis": "local smoke only"},
        "market_tickers": [],
        "confidence": "medium",
    })
    return db.load_recent_events(1)[0]["id"]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _snapshot_db(path: str) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        snapshot: dict[str, list[tuple]] = {}
        for table in tables:
            quoted = _quote_ident(table)
            snapshot[table] = list(
                conn.execute(f"SELECT * FROM {quoted} ORDER BY rowid")
            )
        return snapshot


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()
        _reset_caches()
        self.event_id = _seed_event_1()
        self.assertEqual(self.event_id, 1)

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestNoPaidSmokeInventory(unittest.TestCase):
    def test_endpoint_inventory_matches_demo_critical_zero_cost_set(self) -> None:
        paths = [endpoint.path for endpoint in no_paid_smoke.ENDPOINTS]
        self.assertEqual(paths, [
            "/health",
            "/diagnostics/config-health",
            "/diagnostics/auto-backfill-status",
            "/diagnostics/data-quality",
            "/diagnostics/archive-stats",
            "/diagnostics/validation-status-stats",
            "/diagnostics/reaction-profile-stats",
            "/diagnostics/track-record",
            "/diagnostics/major-skipped-headlines?limit=5",
            "/events?limit=3&validation_status_v2=pending",
            "/events/1",
            "/registry/candidate-queue?limit=5",
            "/movers/backfill-preview?limit=5",
            "/diagnostics/auto-backfill-dry-run",
        ])
        methods = [endpoint.method for endpoint in no_paid_smoke.ENDPOINTS]
        self.assertEqual(methods[-1], "POST")

    def test_inventory_rejects_paid_paths(self) -> None:
        for endpoint in no_paid_smoke.ENDPOINTS:
            for marker in no_paid_smoke._BANNED_PATH_MARKERS:
                self.assertFalse(
                    endpoint.path.startswith(marker),
                    f"paid path leaked into smoke inventory: {endpoint.path}",
                )


class TestNoPaidSmokeRunner(_Base):
    def test_smoke_passes_with_guarded_provider_and_paid_seams(self) -> None:
        before = _snapshot_db(self._tmp)
        results = no_paid_smoke.run_smoke(client=client)
        after = _snapshot_db(self._tmp)

        failures = [r for r in results if not r.ok]
        self.assertEqual(failures, [])
        self.assertEqual(len(results), len(no_paid_smoke.ENDPOINTS))
        self.assertEqual(before, after, "smoke endpoints must not mutate DB")

    def test_json_summary_shape(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        payload = no_paid_smoke.summarize(results)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(
            payload["summary"]["total"],
            len(no_paid_smoke.ENDPOINTS),
        )
        self.assertEqual(len(payload["checks"]), len(no_paid_smoke.ENDPOINTS))
        for check in payload["checks"]:
            self.assertIn("path", check)
            self.assertIn("ok", check)
            self.assertIn("status_code", check)

    def test_main_json_outputs_valid_payload_and_zero_exit(self) -> None:
        out = io.StringIO()
        code = no_paid_smoke.main(["--json"], out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["failed"], 0)

    def test_guard_context_fails_closed_on_provider_seam(self) -> None:
        with no_paid_smoke.guard_no_paid_provider_calls():
            import market_check

            with self.assertRaisesRegex(RuntimeError, "forbidden seam"):
                market_check._fetch("SPY")

    def test_failure_row_and_nonzero_summary_for_bad_client(self) -> None:
        class BadClient:
            def get(self, _path):
                raise AssertionError("unexpected paid/provider call")

        results = no_paid_smoke.run_smoke(
            client=BadClient(),
            guard_provider_seams=False,
        )
        self.assertEqual(len(results), len(no_paid_smoke.ENDPOINTS))
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])
        self.assertIn("unexpected paid/provider call", results[0].error or "")

    def test_text_table_mentions_pass_summary(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        table = no_paid_smoke.render_table(results)
        self.assertIn("No-paid demo smoke", table)
        self.assertIn("Summary:", table)
        self.assertIn("PASS", table)


class TestAutoBackfillStatusInvariants(unittest.TestCase):
    """The smoke runner pins ``scheduler.scheduler_started=false`` and
    ``ledger.used=0`` on the auto-backfill-status response.  These are
    the load-bearing assertions that catch an unwired scheduler being
    started or a paid ledger being touched.
    """

    def test_invariant_passes_on_clean_no_paid_status(self) -> None:
        body = {
            "scheduler": {
                "scheduler_available": True,
                "scheduler_started":   False,
                "job_count":           0,
                "mode":                "not_wired",
            },
            "ledger": {"used": 0, "remaining": 12, "daily_cap": 12},
        }
        # No exception expected.
        no_paid_smoke._assert_auto_backfill_status_no_paid(body)

    def test_invariant_fails_when_scheduler_started_true(self) -> None:
        body = {
            "scheduler": {
                "scheduler_started": True,
            },
            "ledger": {"used": 0},
        }
        with self.assertRaisesRegex(
            AssertionError, "scheduler.scheduler_started must be false",
        ):
            no_paid_smoke._assert_auto_backfill_status_no_paid(body)

    def test_invariant_fails_when_ledger_used_nonzero(self) -> None:
        body = {
            "scheduler": {"scheduler_started": False},
            "ledger":    {"used": 1},
        }
        with self.assertRaisesRegex(
            AssertionError, "ledger.used must be 0",
        ):
            no_paid_smoke._assert_auto_backfill_status_no_paid(body)

    def test_invariant_fails_when_scheduler_block_missing(self) -> None:
        # Defensive: if the response structure regresses (e.g. a
        # refactor drops the scheduler block), the invariant must
        # still trip on the missing field, not silently pass.
        body = {"ledger": {"used": 0}}
        with self.assertRaisesRegex(
            AssertionError, "scheduler.scheduler_started must be false",
        ):
            no_paid_smoke._assert_auto_backfill_status_no_paid(body)

    def test_inventory_attaches_invariant_to_status_endpoint(self) -> None:
        # Find the auto-backfill-status entry in the smoke inventory
        # and verify the invariant is wired to it.
        match = next(
            (e for e in no_paid_smoke.ENDPOINTS
             if e.path == "/diagnostics/auto-backfill-status"),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_auto_backfill_status_no_paid,
            match.body_invariants,
        )


class TestAutoBackfillStatusSmokeRunFails(_Base):
    """End-to-end: a smoke run with a tampered status response that
    violates the invariant must surface the failure on that endpoint
    AND fail the overall smoke summary.
    """

    def test_smoke_marks_status_failed_when_invariant_fails(self) -> None:
        from unittest.mock import patch

        bad_body = {
            "scheduler": {"scheduler_started": True},
            "ledger":    {"used": 0},
        }

        class _BadStatusBody:
            status_code = 200

            def json(self):
                return bad_body

        real_request = no_paid_smoke._request

        def _patched_request(client_, endpoint):
            if endpoint.path == "/diagnostics/auto-backfill-status":
                return _BadStatusBody()
            return real_request(client_, endpoint)

        with patch.object(no_paid_smoke, "_request", _patched_request):
            results = no_paid_smoke.run_smoke(client=client)
        status_result = next(
            r for r in results
            if r.path == "/diagnostics/auto-backfill-status"
        )
        self.assertFalse(status_result.ok)
        self.assertIn("body invariant failed", status_result.error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

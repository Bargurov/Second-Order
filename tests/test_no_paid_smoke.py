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
            "/diagnostics/archive-consistency",
            "/diagnostics/validation-status-stats",
            "/diagnostics/reaction-profile-stats",
            "/diagnostics/track-record",
            "/diagnostics/major-skipped-headlines?limit=5",
            "/events?limit=3&validation_status_v2=pending",
            "/events/1",
            "/registry/candidate-queue?limit=5",
            "/movers/backfill-preview?limit=5",
            "/diagnostics/event-date-backfill-candidates",
            "/diagnostics/event-date-backfill-impact-preview",
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

        expected_total = (
            len(no_paid_smoke.ENDPOINTS) + len(no_paid_smoke.SCRIPTS)
        )
        failures = [r for r in results if not r.ok and not r.skipped]
        self.assertEqual(failures, [])
        self.assertEqual(len(results), expected_total)
        self.assertEqual(before, after, "smoke endpoints must not mutate DB")

    def test_json_summary_shape(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        payload = no_paid_smoke.summarize(results)
        expected_total = (
            len(no_paid_smoke.ENDPOINTS) + len(no_paid_smoke.SCRIPTS)
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(payload["summary"]["total"], expected_total)
        self.assertEqual(len(payload["checks"]), expected_total)
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
        expected_total = (
            len(no_paid_smoke.ENDPOINTS) + len(no_paid_smoke.SCRIPTS)
        )
        self.assertEqual(len(results), expected_total)
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])
        # Endpoints run first; the first failed result must be an endpoint
        # row carrying the bad-client error verbatim.
        self.assertIn("unexpected paid/provider call", results[0].error or "")

    def test_text_table_mentions_pass_summary(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        table = no_paid_smoke.render_table(results)
        self.assertIn("No-paid demo smoke", table)
        self.assertIn("Summary:", table)
        self.assertIn("PASS", table)


class TestNoPaidSmokeBaseUrlSkipsLocalScripts(unittest.TestCase):
    """In ``--base-url`` mode the smoke must NOT run local CLI scripts.

    Codex review flagged: scripts probe the local archive regardless of
    the operator's --base-url target, contradicting the operator's
    intent (probe a remote backend).  They also bypass the no-paid
    guard in base-url mode (the guard is replaced with a nullcontext),
    so a script regression could reach a forbidden seam silently.
    Skip them entirely; the in-process mode remains the full local
    preflight (and these tests pin the local mode regression guard).
    """

    def _stub_response(self, status: int = 200) -> object:
        class _R:
            status_code = status
            @property
            def text(_self) -> str:
                return "{}"
            def json(_self):
                return {}
        return _R()

    def test_base_url_mode_returns_only_endpoint_results(self) -> None:
        from unittest.mock import patch
        with patch.object(
            no_paid_smoke, "_request",
            return_value=self._stub_response(),
        ):
            results = no_paid_smoke.run_smoke(
                base_url="http://0.0.0.0:1",
                timeout=0.1,
            )
        self.assertEqual(len(results), len(no_paid_smoke.ENDPOINTS))

    def test_base_url_mode_omits_every_script_module_from_results(self) -> None:
        from unittest.mock import patch
        with patch.object(
            no_paid_smoke, "_request",
            return_value=self._stub_response(),
        ):
            results = no_paid_smoke.run_smoke(
                base_url="http://0.0.0.0:1",
                timeout=0.1,
            )
        for script in no_paid_smoke.SCRIPTS:
            self.assertFalse(
                any(script.module in (r.path or "") for r in results),
                f"--base-url mode must not run local script "
                f"{script.module!r}; results: "
                f"{[r.path for r in results]}",
            )

    def test_base_url_mode_does_not_invoke_run_script(self) -> None:
        from unittest.mock import patch

        seen: list[object] = []

        def _spy(script):
            seen.append(script)
            return True, None

        with patch.object(
            no_paid_smoke, "_request",
            return_value=self._stub_response(),
        ):
            with patch.object(
                no_paid_smoke, "_run_script", side_effect=_spy,
            ):
                no_paid_smoke.run_smoke(
                    base_url="http://0.0.0.0:1",
                    timeout=0.1,
                )
        self.assertEqual(
            seen, [],
            "--base-url mode must not invoke _run_script for any local "
            f"script; saw: {seen}",
        )

    def test_local_mode_still_invokes_run_script_for_each_script(self) -> None:
        # Regression guard: skipping scripts in --base-url mode must not
        # leak into the default in-process mode.  The local preflight
        # remains the full HTTP+CLI smoke.
        from unittest.mock import patch

        seen: list[str] = []

        def _spy(script):
            seen.append(script.module)
            return True, None

        class _NoopClient:
            def get(self, _path):
                return self._resp()
            def post(self, _path):
                return self._resp()
            def request(self, _method, _path):
                return self._resp()
            def _resp(self):
                class _R:
                    status_code = 200
                    @property
                    def text(self): return "{}"
                    def json(self): return {}
                return _R()

        with patch.object(no_paid_smoke, "_run_script", side_effect=_spy):
            no_paid_smoke.run_smoke(
                client=_NoopClient(),
                guard_provider_seams=False,
            )
        self.assertEqual(
            seen, [s.module for s in no_paid_smoke.SCRIPTS],
            "default local mode must still run every local script in order",
        )

    def test_main_with_base_url_skips_local_scripts(self) -> None:
        # End-to-end: the CLI surface threading --base-url through
        # main() must produce a payload that contains only endpoint
        # rows, never script rows.
        from unittest.mock import patch
        out = io.StringIO()
        with patch.object(
            no_paid_smoke, "_request",
            return_value=self._stub_response(),
        ):
            code = no_paid_smoke.main(
                ["--json", "--base-url", "http://0.0.0.0:1",
                 "--timeout", "0.1"],
                out=out,
            )
        payload = json.loads(out.getvalue())
        self.assertIsInstance(payload["checks"], list)
        self.assertEqual(
            len(payload["checks"]), len(no_paid_smoke.ENDPOINTS),
            f"base_url payload must omit script rows; saw "
            f"{len(payload['checks'])} checks",
        )
        for script in no_paid_smoke.SCRIPTS:
            self.assertFalse(
                any(script.module in (c.get("path") or "")
                    for c in payload["checks"]),
                f"--base-url payload must not include local script "
                f"{script.module!r}",
            )
        # Exit code is orthogonal to script-skip: the stubbed bodies
        # satisfy the JSON-parseable check but not every per-endpoint
        # body invariant, so the run-wide ``ok`` may be False.  The
        # load-bearing pin is the absence of script rows above.
        self.assertIsInstance(code, int)


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


class TestEventDateBackfillInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on the
    ``/diagnostics/event-date-backfill-candidates`` response: the
    candidates count must be a non-negative int and the proposal list
    must be a list.  Stable zero values are accepted because a clean
    archive has no missing event_dates.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        body = {
            "total_events_missing_event_date":    0,
            "events_with_market_tickers":         0,
            "ticker_rows_blocked":                0,
            "timestamp_same_day_confidence_note": "...",
            "examples":                           [],
        }
        no_paid_smoke._assert_event_date_backfill_no_paid(body)

    def test_invariant_passes_when_candidates_and_proposals_present(self) -> None:
        body = {
            "total_events_missing_event_date": 3,
            "events_with_market_tickers":      2,
            "ticker_rows_blocked":             4,
            "examples": [
                {
                    "event_id":            7,
                    "headline":            "h",
                    "timestamp":           "2026-04-01T13:00:00",
                    "proposed_event_date": "2026-04-01",
                    "ticker_count":        1,
                    "tickers":             ["AAPL"],
                },
            ],
        }
        no_paid_smoke._assert_event_date_backfill_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(
            AssertionError, "must be a JSON object",
        ):
            no_paid_smoke._assert_event_date_backfill_no_paid([])

    def test_invariant_fails_when_candidates_count_missing(self) -> None:
        body = {"examples": []}
        with self.assertRaisesRegex(
            AssertionError, "total_events_missing_event_date",
        ):
            no_paid_smoke._assert_event_date_backfill_no_paid(body)

    def test_invariant_fails_when_candidates_count_negative(self) -> None:
        body = {
            "total_events_missing_event_date": -1,
            "examples":                        [],
        }
        with self.assertRaisesRegex(
            AssertionError, "total_events_missing_event_date",
        ):
            no_paid_smoke._assert_event_date_backfill_no_paid(body)

    def test_invariant_fails_when_examples_not_list(self) -> None:
        body = {
            "total_events_missing_event_date": 0,
            "examples":                        "nope",
        }
        with self.assertRaisesRegex(
            AssertionError, "examples",
        ):
            no_paid_smoke._assert_event_date_backfill_no_paid(body)

    def test_inventory_attaches_invariant_to_event_date_endpoint(self) -> None:
        match = next(
            (e for e in no_paid_smoke.ENDPOINTS
             if e.path == "/diagnostics/event-date-backfill-candidates"),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.method, "GET")
        self.assertIn(
            no_paid_smoke._assert_event_date_backfill_no_paid,
            match.body_invariants,
        )


class TestArchiveConsistencyInvariants(unittest.TestCase):
    """The smoke runner pins per-category ``count``/``examples`` shape on
    the ``/diagnostics/archive-consistency`` response.  Stable zero
    counts are accepted because a clean archive has no anomalies.
    """

    def _empty_blocks(self) -> dict[str, dict[str, object]]:
        return {
            category: {"count": 0, "examples": []}
            for category in no_paid_smoke._ARCHIVE_CONSISTENCY_CATEGORIES
        }

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_archive_consistency_no_paid(self._empty_blocks())

    def test_invariant_passes_when_categories_populated(self) -> None:
        body = self._empty_blocks()
        body["missing_event_date"] = {
            "count": 2,
            "examples": [
                {"event_id": 1, "headline": "h", "timestamp": "t",
                 "event_date": None},
                {"event_id": 2, "headline": "h2", "timestamp": "t2",
                 "event_date": ""},
            ],
        }
        body["duplicate_headline_event_date_clusters"] = {
            "count": 1,
            "examples": [
                {"headline": "dup", "event_date": "2026-04-01",
                 "count": 2, "event_ids": [3, 4]},
            ],
        }
        no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_archive_consistency_no_paid([])

    def test_invariant_fails_when_category_missing(self) -> None:
        body = self._empty_blocks()
        body.pop("missing_headline")
        with self.assertRaisesRegex(
            AssertionError, "missing_headline.*must be a JSON object",
        ):
            no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_invariant_fails_when_block_not_object(self) -> None:
        body = self._empty_blocks()
        body["missing_timestamp"] = [{"count": 0, "examples": []}]
        with self.assertRaisesRegex(
            AssertionError, "missing_timestamp.*must be a JSON object",
        ):
            no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_invariant_fails_when_count_missing(self) -> None:
        body = self._empty_blocks()
        body["missing_event_date"] = {"examples": []}
        with self.assertRaisesRegex(
            AssertionError, "missing_event_date.*count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_invariant_fails_when_count_negative(self) -> None:
        body = self._empty_blocks()
        body["missing_event_date"] = {"count": -1, "examples": []}
        with self.assertRaisesRegex(
            AssertionError, "missing_event_date.*count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_invariant_fails_when_examples_not_list(self) -> None:
        body = self._empty_blocks()
        body["malformed_event_date"] = {"count": 0, "examples": "nope"}
        with self.assertRaisesRegex(
            AssertionError, "malformed_event_date.*examples must be a list",
        ):
            no_paid_smoke._assert_archive_consistency_no_paid(body)

    def test_inventory_attaches_invariant_to_archive_consistency_endpoint(
        self,
    ) -> None:
        match = next(
            (e for e in no_paid_smoke.ENDPOINTS
             if e.path == "/diagnostics/archive-consistency"),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.method, "GET")
        self.assertIn(
            no_paid_smoke._assert_archive_consistency_no_paid,
            match.body_invariants,
        )


class TestEventDateBackfillImpactInvariants(unittest.TestCase):
    """The smoke runner pins the impact-projection contract on
    ``/diagnostics/event-date-backfill-impact-preview``: ``candidate_events``,
    ``proposed_updates`` and ``projected_no_event_date_after`` must all
    be non-negative ints so the runbook math stays meaningful.  Stable
    zero values are accepted because an archive with no candidates
    projects zeros across the board.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        body = {
            "candidate_events":                0,
            "ticker_rows_blocked":             0,
            "proposed_updates":                0,
            "projected_no_event_date_after":   0,
            "projected_ticker_rows_unblocked": 0,
            "examples":                        [],
        }
        no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_passes_when_projection_nonzero(self) -> None:
        body = {
            "candidate_events":                3,
            "ticker_rows_blocked":             5,
            "proposed_updates":                2,
            "projected_no_event_date_after":   1,
            "projected_ticker_rows_unblocked": 4,
            "examples": [
                {
                    "event_id":            7,
                    "headline":            "h",
                    "timestamp":           "2026-04-01T13:00:00",
                    "proposed_event_date": "2026-04-01",
                    "ticker_count":        2,
                    "tickers":             ["AAPL", "MSFT"],
                },
            ],
        }
        no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid([])

    def test_invariant_fails_when_candidate_events_missing(self) -> None:
        body = {
            "proposed_updates":              0,
            "projected_no_event_date_after": 0,
        }
        with self.assertRaisesRegex(
            AssertionError, "candidate_events must be a non-negative int",
        ):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_fails_when_proposed_updates_missing(self) -> None:
        body = {
            "candidate_events":              0,
            "projected_no_event_date_after": 0,
        }
        with self.assertRaisesRegex(
            AssertionError, "proposed_updates must be a non-negative int",
        ):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_fails_when_projected_after_missing(self) -> None:
        body = {
            "candidate_events": 0,
            "proposed_updates": 0,
        }
        with self.assertRaisesRegex(
            AssertionError,
            "projected_no_event_date_after must be a non-negative int",
        ):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_fails_when_projected_after_negative(self) -> None:
        body = {
            "candidate_events":              0,
            "proposed_updates":              0,
            "projected_no_event_date_after": -1,
        }
        with self.assertRaisesRegex(
            AssertionError,
            "projected_no_event_date_after must be a non-negative int",
        ):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_invariant_fails_when_candidate_events_is_bool(self) -> None:
        body = {
            "candidate_events":              True,
            "proposed_updates":              0,
            "projected_no_event_date_after": 0,
        }
        with self.assertRaisesRegex(
            AssertionError, "candidate_events must be a non-negative int",
        ):
            no_paid_smoke._assert_event_date_backfill_impact_no_paid(body)

    def test_inventory_attaches_invariant_to_impact_endpoint(self) -> None:
        match = next(
            (e for e in no_paid_smoke.ENDPOINTS
             if e.path == "/diagnostics/event-date-backfill-impact-preview"),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.method, "GET")
        self.assertIn(
            no_paid_smoke._assert_event_date_backfill_impact_no_paid,
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


# ---------------------------------------------------------------------------
# No-forward-20d CLI smoke coverage — script-level smoke for the two new
# read-only diagnostics CLIs.  Every entry in ``SCRIPTS`` is invoked
# in-process under the same ``guard_no_paid_provider_calls()`` context as
# the HTTP smoke, so a forbidden seam in either script trips the same
# raisers and lands as a failed row.
# ---------------------------------------------------------------------------


_GAP_REPORT_MODULE = "scripts.no_forward_20d_gap_report"
_REFRESHABILITY_EXPORT_MODULE = "scripts.no_forward_20d_refreshability_export"
_AUTO_ADJUST_PREVIEW_MODULE = "scripts.auto_adjust_mismatch_repair_preview"
_STAT_VALIDATION_SMOKE_MODULE = "scripts.stat_validation_smoke"
_STAT_VALIDATION_READINESS_MODULE = "scripts.stat_validation_readiness_report"
_ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE = (
    "scripts.archive_cleanup_execution_plan"
)
_ARCHIVE_CLEANUP_TICKER_READINESS_MODULE = (
    "scripts.archive_cleanup_candidate_ticker_readiness"
)
_SHORT_HORIZON_READINESS_MODULE = (
    "scripts.stat_validation_short_horizon_readiness_report"
)
_SHORT_HORIZON_CONTAMINATION_MODULE = (
    "scripts.stat_validation_short_horizon_contamination_report"
)
_ARCHIVE_SHORT_HORIZON_RUN_MODULE = (
    "scripts.archive_stat_validation_short_horizon_run"
)
_ARCHIVE_DEDUP_SUMMARY_MODULE = (
    "scripts.archive_stat_validation_dedup_summary"
)
_SHORT_HORIZON_SHOWCASE_SHORTLIST_MODULE = (
    "scripts.short_horizon_showcase_candidate_shortlist"
)
_MANUAL_REPAIRED_COHORT_MODULE = (
    "scripts.manual_repaired_cohort_validation_run"
)


_VALID_GAP_REPORT_BODY = {
    "total_no_forward_20d":          0,
    "too_recent":                    0,
    "auto_adjust_mismatch":          0,
    "cache_window_gap":              0,
    "likely_delisted_or_sparse":     0,
    "refreshable_gap_examples":      [],
    "non_refreshable_examples":      [],
    "auto_adjust_mismatch_details":  [],
    "recommended_next_action":       "no_action_needed_no_gaps",
}


_VALID_REFRESHABILITY_BODY = {
    "ok":     True,
    "count":  0,
    "fields": [
        "event_id",
        "event_date",
        "symbol",
        "diagnostic_reason",
        "cache_max_date",
        "horizon_20d_date",
        "gap_days",
        "source",
    ],
    "rows":   [],
}


class TestNoPaidSmokeScriptInventory(unittest.TestCase):
    """The script smoke inventory must pin exactly the read-only no-paid
    CLIs the runbook depends on (the two no-forward-20d helpers and the
    auto-adjust mismatch repair preview).  Adding an unintended script
    here would leak the smoke into territory the no-paid guard cannot
    reason about, so the inventory is pinned tightly.
    """

    def test_script_inventory_matches_pinned_set(self) -> None:
        modules = [s.module for s in no_paid_smoke.SCRIPTS]
        self.assertEqual(modules, [
            _GAP_REPORT_MODULE,
            _REFRESHABILITY_EXPORT_MODULE,
            _AUTO_ADJUST_PREVIEW_MODULE,
            _STAT_VALIDATION_SMOKE_MODULE,
            _STAT_VALIDATION_READINESS_MODULE,
            _ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE,
            _ARCHIVE_CLEANUP_TICKER_READINESS_MODULE,
            _SHORT_HORIZON_READINESS_MODULE,
            _SHORT_HORIZON_CONTAMINATION_MODULE,
            _ARCHIVE_SHORT_HORIZON_RUN_MODULE,
            _ARCHIVE_DEDUP_SUMMARY_MODULE,
            _SHORT_HORIZON_SHOWCASE_SHORTLIST_MODULE,
            _MANUAL_REPAIRED_COHORT_MODULE,
        ])

    def test_stat_validation_smoke_passes_only_json_arg(self) -> None:
        # The stat-validation smoke does not accept ``--limit`` — its
        # cohort size is fixed by the synthetic generator. The runner
        # must therefore pass only ``--json`` for that script.
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _STAT_VALIDATION_SMOKE_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.args, ("--json",))

    def test_stat_validation_readiness_passes_limit_20(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _STAT_VALIDATION_READINESS_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn("--json", match.args)
        self.assertIn("--limit", match.args)
        self.assertIn("20", match.args)

    def test_each_script_passes_json_arg_for_machine_parseable_output(self) -> None:
        for script in no_paid_smoke.SCRIPTS:
            self.assertIn(
                "--json", script.args,
                f"script {script.module!r} must request JSON output for "
                f"the smoke runner to validate body invariants",
            )

    def test_each_script_resolves_under_scripts_package(self) -> None:
        # Defense-in-depth: a future regression that smuggles a non-script
        # module into the smoke must trip here.
        for script in no_paid_smoke.SCRIPTS:
            self.assertTrue(
                script.module.startswith("scripts."),
                f"script module {script.module!r} must live under "
                f"the ``scripts`` package",
            )

    def test_assert_script_inventory_is_zero_cost_passes_on_clean_inventory(
        self,
    ) -> None:
        # No exception expected on the production inventory.
        no_paid_smoke._assert_script_inventory_is_zero_cost()


class TestNoForwardGapReportInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.no_forward_20d_gap_report --json``: every count must be a
    non-negative int, every example list must be a list, and the
    recommendation must come from the script's fixed vocabulary.  Stable
    zero values are accepted because a clean archive has no gaps.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(
            _VALID_GAP_REPORT_BODY,
        )

    def test_invariant_passes_when_counts_and_examples_populated(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["total_no_forward_20d"] = 5
        body["cache_window_gap"]     = 3
        body["auto_adjust_mismatch"] = 2
        body["refreshable_gap_examples"] = [
            {"event_id": 1, "ticker": "AAPL",
             "diagnostic_reason": "cache_max_before_20d_horizon"},
        ]
        body["recommended_next_action"] = "fix_auto_adjust_flag_mismatch"
        no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid([])

    def test_invariant_fails_when_total_missing(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body.pop("total_no_forward_20d")
        with self.assertRaisesRegex(
            AssertionError, "total_no_forward_20d must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_count_negative(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["cache_window_gap"] = -1
        with self.assertRaisesRegex(
            AssertionError, "cache_window_gap must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_count_is_bool(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["too_recent"] = True
        with self.assertRaisesRegex(
            AssertionError, "too_recent must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_examples_not_list(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["refreshable_gap_examples"] = "nope"
        with self.assertRaisesRegex(
            AssertionError, "refreshable_gap_examples must be a list",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_auto_adjust_details_not_list(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["auto_adjust_mismatch_details"] = {"oops": True}
        with self.assertRaisesRegex(
            AssertionError, "auto_adjust_mismatch_details must be a list",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_invariant_fails_when_recommendation_outside_vocabulary(self) -> None:
        body = dict(_VALID_GAP_REPORT_BODY)
        body["recommended_next_action"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError, "recommended_next_action must be one of",
        ):
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid(body)

    def test_inventory_attaches_invariant_to_gap_report_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS if s.module == _GAP_REPORT_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_no_forward_20d_gap_report_no_paid,
            match.body_invariants,
        )


class TestNoForwardRefreshabilityExportInvariants(unittest.TestCase):
    """The smoke runner pins the export envelope on
    ``scripts.no_forward_20d_refreshability_export --json``:
    ``{ok=True, count: non-negative int, fields: pinned 8-tuple,
    rows: list}``.  Stable zero values are accepted because a clean
    archive has no refreshable rows.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
            _VALID_REFRESHABILITY_BODY,
        )

    def test_invariant_passes_when_rows_populated(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["count"] = 1
        body["rows"] = [{
            "event_id":          7,
            "event_date":        "2026-04-01",
            "symbol":            "AAPL",
            "diagnostic_reason": "cache_max_before_20d_horizon",
            "cache_max_date":    "2026-04-15",
            "horizon_20d_date":  "2026-04-29",
            "gap_days":          14,
            "source":            "no_forward_20d_blockers",
        }]
        no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                [],
            )

    def test_invariant_fails_when_ok_not_true(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["ok"] = False
        with self.assertRaisesRegex(AssertionError, "ok must be True"):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_count_missing(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body.pop("count")
        with self.assertRaisesRegex(
            AssertionError, "count must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_count_negative(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "count must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_count_is_bool(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["count"] = True
        with self.assertRaisesRegex(
            AssertionError, "count must be a non-negative int",
        ):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_fields_not_list(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["fields"] = "nope"
        with self.assertRaisesRegex(AssertionError, "fields must be a list"):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_fields_diverge_from_pinned_set(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["fields"] = ["event_id", "symbol"]  # missing the rest
        with self.assertRaisesRegex(
            AssertionError, "fields must equal the pinned export shape",
        ):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_invariant_fails_when_rows_not_list(self) -> None:
        body = dict(_VALID_REFRESHABILITY_BODY)
        body["rows"] = {"oops": True}
        with self.assertRaisesRegex(AssertionError, "rows must be a list"):
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_export_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _REFRESHABILITY_EXPORT_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_no_forward_20d_refreshability_export_no_paid,
            match.body_invariants,
        )


_VALID_AUTO_ADJUST_PREVIEW_BODY = {
    "total_mismatches":        0,
    "repairable_count":        0,
    "non_repairable_count":    0,
    "counts_by_status":        {},
    "proposed_rows":           [],
    "recommended_next_action": "no_action_needed_no_mismatches",
}


class TestAutoAdjustMismatchRepairPreviewInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.auto_adjust_mismatch_repair_preview --json``: every count
    must be a non-negative int, ``counts_by_status`` must be a dict,
    ``proposed_rows`` must be a list, and ``recommended_next_action``
    must come from the script's fixed vocabulary.  Stable zero values
    are accepted because a clean archive has no mismatches.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
            _VALID_AUTO_ADJUST_PREVIEW_BODY,
        )

    def test_invariant_passes_when_counts_and_rows_populated(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["total_mismatches"]     = 4
        body["repairable_count"]     = 3
        body["non_repairable_count"] = 1
        body["counts_by_status"] = {
            "repairable_flag_fix":               3,
            "not_repairable_no_in_window_data":  1,
        }
        body["proposed_rows"] = [
            {
                "event_id":      7,
                "event_date":    "2026-04-01",
                "symbol":        "AAPL",
                "repair_status": "repairable_flag_fix",
            },
        ]
        body["recommended_next_action"] = "fix_auto_adjust_flag_mismatch"
        no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                [],
            )

    def test_invariant_fails_when_total_missing(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body.pop("total_mismatches")
        with self.assertRaisesRegex(
            AssertionError, "total_mismatches must be a non-negative int",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_repairable_count_negative(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["repairable_count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "repairable_count must be a non-negative int",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_non_repairable_count_is_bool(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["non_repairable_count"] = True
        with self.assertRaisesRegex(
            AssertionError, "non_repairable_count must be a non-negative int",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_counts_by_status_not_dict(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["counts_by_status"] = ["nope"]
        with self.assertRaisesRegex(
            AssertionError, "counts_by_status must be a dict",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_proposed_rows_not_list(self) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["proposed_rows"] = {"oops": True}
        with self.assertRaisesRegex(
            AssertionError, "proposed_rows must be a list",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_recommendation_outside_vocabulary(
        self,
    ) -> None:
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["recommended_next_action"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError, "recommended_next_action must be one of",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_invariant_fails_when_partition_does_not_sum_to_total(
        self,
    ) -> None:
        # ``total_mismatches`` is a partition of
        # ``repairable_count + non_repairable_count`` by construction.
        # Production code enforces this; the smoke pins it so a future
        # accounting drift in the preview tripwires here, not silently in
        # downstream consumers' math.
        body = dict(_VALID_AUTO_ADJUST_PREVIEW_BODY)
        body["total_mismatches"]     = 5
        body["repairable_count"]     = 3
        body["non_repairable_count"] = 1  # 3 + 1 != 5
        with self.assertRaisesRegex(
            AssertionError,
            "repairable_count.*non_repairable_count.*must sum to total_mismatches",
        ):
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_preview_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _AUTO_ADJUST_PREVIEW_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_auto_adjust_mismatch_repair_preview_no_paid,
            match.body_invariants,
        )


class TestNoPaidSmokeScriptRunner(_Base):
    """End-to-end: ``run_smoke`` must run every script in the inventory
    in-process, under the same provider/paid guard as the HTTP smoke,
    and surface a SmokeResult per script in the same shape as endpoint
    results.
    """

    def _script_results(self, results: list) -> list:
        script_modules = {s.module for s in no_paid_smoke.SCRIPTS}
        return [
            r for r in results
            if any(mod in r.path for mod in script_modules)
        ]

    def test_smoke_includes_one_result_per_script(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        script_results = self._script_results(results)
        self.assertEqual(len(script_results), len(no_paid_smoke.SCRIPTS))

    def test_each_script_smoke_result_passes_against_clean_archive(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        script_results = self._script_results(results)
        for r in script_results:
            self.assertTrue(
                r.ok or r.skipped,
                f"script smoke unexpectedly failed: name={r.name!r} "
                f"path={r.path!r} error={r.error!r}",
            )

    def test_script_results_appear_after_endpoint_results(self) -> None:
        # Endpoint smoke is the established baseline; scripts run after
        # so a smoke output reads top-down from endpoints to CLIs and so
        # ``results[0].error`` keeps its existing semantics under the
        # bad-client failure test.
        results = no_paid_smoke.run_smoke(client=client)
        endpoint_paths = {e.path for e in no_paid_smoke.ENDPOINTS}
        endpoint_indices = [
            i for i, r in enumerate(results) if r.path in endpoint_paths
        ]
        script_indices = [
            i for i, r in enumerate(results)
            if r not in [results[j] for j in endpoint_indices]
        ]
        if script_indices and endpoint_indices:
            self.assertGreater(min(script_indices), max(endpoint_indices))

    def test_total_results_equals_endpoints_plus_scripts(self) -> None:
        results = no_paid_smoke.run_smoke(client=client)
        self.assertEqual(
            len(results),
            len(no_paid_smoke.ENDPOINTS) + len(no_paid_smoke.SCRIPTS),
        )

    def test_failed_script_main_is_reported_as_failed_result(self) -> None:
        from unittest.mock import patch

        bad_module = no_paid_smoke.SCRIPTS[0].module

        def _broken_main(_argv, *, out=None):
            raise RuntimeError("synthetic script failure")

        target_module = __import__(bad_module, fromlist=["main"])
        with patch.object(target_module, "main", _broken_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [r for r in results if bad_module in r.path]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("synthetic script failure", broken[0].error or "")

    def test_script_invariant_failure_marks_only_that_script_failed(self) -> None:
        from unittest.mock import patch

        bad_module = no_paid_smoke.SCRIPTS[0].module
        target_module = __import__(bad_module, fromlist=["main"])

        def _bad_main(_argv, *, out=None):
            print(json.dumps({"unexpected": "shape"}), file=out)
            return 0

        with patch.object(target_module, "main", _bad_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [r for r in results if bad_module in r.path]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("body invariant failed", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_smoke_run_does_not_mutate_db(self) -> None:
        before = _snapshot_db(self._tmp)
        results = no_paid_smoke.run_smoke(client=client)
        after = _snapshot_db(self._tmp)
        self.assertEqual(
            before, after,
            "script smoke must not mutate the archive — "
            f"failures: {[r for r in results if not r.ok]}",
        )


class TestNoPaidSmokeScriptGuardFailsClosed(_Base):
    """The script smoke must run under the same provider/paid guard as the
    HTTP smoke.  If a script's main attempts a forbidden seam, the guard
    raises and the script's SmokeResult must surface the failure.
    """

    def test_script_invoking_forbidden_seam_marks_smoke_failed(self) -> None:
        from unittest.mock import patch

        bad_module = no_paid_smoke.SCRIPTS[0].module
        target_module = __import__(bad_module, fromlist=["main"])

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            # This is exactly what the no-paid guard pins.  If the
            # script's main reaches a forbidden seam, the raiser fires
            # and the smoke marks the script result failed.
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [r for r in results if bad_module in r.path]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_auto_adjust_preview_under_guard_fails_closed_on_seam(
        self,
    ) -> None:
        # Symmetric pin for the auto-adjust mismatch repair preview:
        # adding it to ``SCRIPTS`` must wire it through the same
        # provider/paid guard as the older smoke scripts.  If a future
        # regression has the preview reach ``market_check`` /
        # ``yfinance`` / LLM seams, the guard fires and the smoke marks
        # the result failed.
        from unittest.mock import patch

        target_module = __import__(
            _AUTO_ADJUST_PREVIEW_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results if _AUTO_ADJUST_PREVIEW_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_stat_validation_smoke_under_guard_fails_closed_on_seam(
        self,
    ) -> None:
        # Symmetric pin for the stat-validation pipeline smoke. The
        # smoke is meant to run pure (no DB / provider / LLM); if a
        # future regression reaches a forbidden seam, the no-paid guard
        # must catch it and the smoke must mark the result failed.
        from unittest.mock import patch

        target_module = __import__(
            _STAT_VALIDATION_SMOKE_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results if _STAT_VALIDATION_SMOKE_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_stat_validation_readiness_under_guard_fails_closed_on_seam(
        self,
    ) -> None:
        # Symmetric pin for the stat-validation readiness report. It
        # reads the archive but must never reach a provider / yfinance /
        # LLM seam. If a regression has it reach one, the guard fires
        # and the smoke result is marked failed.
        from unittest.mock import patch

        target_module = __import__(
            _STAT_VALIDATION_READINESS_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results if _STAT_VALIDATION_READINESS_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_archive_cleanup_execution_plan_under_guard_fails_closed_on_seam(
        self,
    ) -> None:
        # Symmetric pin for the archive cleanup execution-plan CLI.
        # The plan is documented as strictly read-only — no provider,
        # yfinance, LLM or DB-write seam.  If a regression reaches one
        # of those, the no-paid guard must fire and the smoke result
        # must surface the failure.
        from unittest.mock import patch

        target_module = __import__(
            _ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results
            if _ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_archive_cleanup_ticker_readiness_under_guard_fails_closed_on_seam(
        self,
    ) -> None:
        # Symmetric pin for the archive cleanup ticker-readiness CLI.
        # The report issues only ``SELECT`` statements; any provider /
        # yfinance / LLM seam contact would be a regression.  Guard
        # must fire and the smoke must mark the result failed.
        from unittest.mock import patch

        target_module = __import__(
            _ARCHIVE_CLEANUP_TICKER_READINESS_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        with patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results
            if _ARCHIVE_CLEANUP_TICKER_READINESS_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])


# ---------------------------------------------------------------------------
# Stat-validation smoke + readiness report invariants
# ---------------------------------------------------------------------------


_VALID_STAT_VALIDATION_SMOKE_BODY: dict = {
    "ok":     True,
    "errors": [],
    "config": {
        "alpha":         0.05,
        "drift":         0.0001,
        "horizons":      [1, 5, 20],
        "n_bootstrap":   500,
        "n_events":      12,
        "seed":          42,
    },
    "records_count":     3,
    "significant_count": 3,
    "records": [
        {
            "horizon":                   1,
            "abnormal_return":           0.04,
            "sar":                       5.0,
            "ci_low":                    0.03,
            "ci_high":                   0.05,
            "p_value":                   0.0,
            "fdr_q":                     0.0,
            "statistically_significant": True,
            "interpretation":            "significant_positive",
        },
        {
            "horizon":                   5,
            "abnormal_return":           0.04,
            "sar":                       2.6,
            "ci_low":                    0.03,
            "ci_high":                   0.05,
            "p_value":                   0.0,
            "fdr_q":                     0.0,
            "statistically_significant": True,
            "interpretation":            "significant_positive",
        },
        {
            "horizon":                   20,
            "abnormal_return":           0.04,
            "sar":                       1.3,
            "ci_low":                    0.02,
            "ci_high":                   0.05,
            "p_value":                   0.00001,
            "fdr_q":                     0.00001,
            "statistically_significant": True,
            "interpretation":            "significant_positive",
        },
    ],
}


class TestStatValidationSmokeInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.stat_validation_smoke --json``: ``ok`` must be True,
    ``errors`` must be empty, ``records_count`` must equal
    ``len(records)``, ``significant_count`` must not exceed
    ``records_count``, and every record must carry the canonical
    nine-field stat_validation schema. Stable values are accepted
    because the smoke runs over a deterministic synthetic cohort.
    """

    def test_invariant_passes_on_valid_body(self) -> None:
        no_paid_smoke._assert_stat_validation_smoke_no_paid(
            _VALID_STAT_VALIDATION_SMOKE_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_stat_validation_smoke_no_paid([])

    def test_invariant_fails_when_ok_is_false(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["ok"] = False
        with self.assertRaisesRegex(AssertionError, "ok must be True"):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_errors_non_empty(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["errors"] = ["unexpected"]
        with self.assertRaisesRegex(
            AssertionError, "errors must be empty in no-paid mode",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_errors_not_list(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["errors"] = {"oops": True}
        with self.assertRaisesRegex(
            AssertionError, "errors must be a list",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_config_not_dict(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["config"] = "nope"
        with self.assertRaisesRegex(
            AssertionError, "config must be a JSON object",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_records_count_negative(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["records_count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "records_count must be a non-negative int",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_significant_count_is_bool(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["significant_count"] = True
        with self.assertRaisesRegex(
            AssertionError,
            "significant_count must be a non-negative int",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_records_count_mismatches_len(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["records_count"] = 99  # len(records) is 3
        with self.assertRaisesRegex(
            AssertionError, "records_count must equal len\\(records\\)",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_significant_exceeds_total(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["significant_count"] = body["records_count"] + 1
        with self.assertRaisesRegex(
            AssertionError,
            "significant_count must not exceed records_count",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_records_not_list(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["records"] = {"oops": True}
        with self.assertRaisesRegex(
            AssertionError, "records must be a list",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_record_missing_canonical_key(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["records"] = [dict(_VALID_STAT_VALIDATION_SMOKE_BODY["records"][0])]
        body["records_count"] = 1
        body["significant_count"] = 1
        body["records"][0].pop("fdr_q")
        with self.assertRaisesRegex(
            AssertionError, "missing required key 'fdr_q'",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_invariant_fails_when_record_is_not_dict(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_SMOKE_BODY)
        body["records"] = [["not", "a", "dict"]]
        body["records_count"] = 1
        body["significant_count"] = 1
        with self.assertRaisesRegex(
            AssertionError, "records\\[0\\] must be a JSON object",
        ):
            no_paid_smoke._assert_stat_validation_smoke_no_paid(body)

    def test_inventory_attaches_invariant_to_smoke_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _STAT_VALIDATION_SMOKE_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_stat_validation_smoke_no_paid,
            match.body_invariants,
        )


_RECOMMENDED_OK_PROSE = (
    "Every event in the archive has the cache coverage needed to run "
    "the event-study engine over 1d/5d/20d horizons."
)
_RECOMMENDED_GAPS_PROSE = (
    "Some events lack the cache coverage needed for the event-study "
    "engine.  Refresh the price cache for the listed primary tickers "
    "and SPY benchmark, then re-run this report."
)


_VALID_STAT_VALIDATION_READINESS_BODY: dict = {
    "total_events":                                0,
    "events_with_event_date":                      0,
    "events_with_market_tickers":                  0,
    "events_with_event_date_and_tickers":          0,
    "events_with_1d_forward_cache":                0,
    "events_with_5d_forward_cache":                0,
    "events_with_20d_forward_cache":               0,
    "events_missing_benchmark_proxy":              0,
    "events_with_insufficient_estimation_window":  0,
    "events_fully_ready":                          0,
    "events":                                      [],
    "recommended_next_action":                     _RECOMMENDED_GAPS_PROSE,
}


class TestStatValidationReadinessReportInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.stat_validation_readiness_report --json --limit 20``:
    every coverage count must be a non-negative int,
    ``recommended_next_action`` must come from the report's two-prose
    vocabulary, ``events`` must be a list, and the partition invariant
    ``events_fully_ready <= total_events`` must hold. Stable zero
    values are accepted because an archive without coverage produces
    zeros across the board.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
            _VALID_STAT_VALIDATION_READINESS_BODY,
        )

    def test_invariant_passes_when_counts_populated(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["total_events"]                              = 271
        body["events_with_event_date"]                    = 271
        body["events_with_market_tickers"]                = 89
        body["events_with_event_date_and_tickers"]        = 89
        body["events_with_1d_forward_cache"]              = 82
        body["events_with_5d_forward_cache"]              = 65
        body["events_with_20d_forward_cache"]             = 35
        body["events_missing_benchmark_proxy"]            = 199
        body["events_with_insufficient_estimation_window"] = 215
        body["events_fully_ready"]                        = 15
        body["events"]                                    = [
            {"event_id": 1, "fully_ready": False},
        ]
        no_paid_smoke._assert_stat_validation_readiness_report_no_paid(body)

    def test_invariant_passes_when_recommendation_is_ok_prose(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["recommended_next_action"] = _RECOMMENDED_OK_PROSE
        no_paid_smoke._assert_stat_validation_readiness_report_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                ["not", "a", "dict"],
            )

    def test_invariant_fails_when_total_events_missing(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body.pop("total_events")
        with self.assertRaisesRegex(
            AssertionError, "total_events must be a non-negative int",
        ):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_invariant_fails_when_count_is_negative(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["events_fully_ready"] = -1
        with self.assertRaisesRegex(
            AssertionError, "events_fully_ready must be a non-negative int",
        ):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_invariant_fails_when_count_is_bool(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["events_with_market_tickers"] = True
        with self.assertRaisesRegex(
            AssertionError,
            "events_with_market_tickers must be a non-negative int",
        ):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_invariant_fails_when_events_not_list(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["events"] = {"oops": True}
        with self.assertRaisesRegex(AssertionError, "events must be a list"):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_invariant_fails_when_recommendation_outside_vocabulary(
        self,
    ) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["recommended_next_action"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError,
            "recommended_next_action must be one of the two pinned",
        ):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_invariant_fails_when_fully_ready_exceeds_total(self) -> None:
        body = dict(_VALID_STAT_VALIDATION_READINESS_BODY)
        body["total_events"]       = 5
        body["events_fully_ready"] = 7
        with self.assertRaisesRegex(
            AssertionError,
            "events_fully_ready must not exceed total_events",
        ):
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_readiness_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _STAT_VALIDATION_READINESS_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_stat_validation_readiness_report_no_paid,
            match.body_invariants,
        )


# ---------------------------------------------------------------------------
# Archive cleanup execution-plan + ticker-readiness invariants
# ---------------------------------------------------------------------------


_EXECUTION_PLAN_OK_RECOMMENDATION = (
    "No archive cleanup candidates detected; no execution plan "
    "required."
)
_EXECUTION_PLAN_READY_RECOMMENDATION = (
    "Execution plan ready.  Take a fresh backup, review every event "
    "in every batch, then delete via the operator path.  This script "
    "makes no DB writes."
)


_VALID_EXECUTION_PLAN_BODY: dict = {
    "candidate_count":             0,
    "batches":                     [],
    "risk_notes": [
        "This script is read-only and makes no DB writes; deletion of "
        "any flagged event remains a manual operator task.",
        "An event matching multiple reasons appears in multiple "
        "batches; deduplicate by event_id before issuing any DELETE "
        "statement.",
    ],
    "required_confirmation_flags": [
        "backup_taken",
        "per_event_manual_review_complete",
        "acknowledged_no_db_writes_from_this_script",
    ],
    "recommended_next_action":     _EXECUTION_PLAN_OK_RECOMMENDATION,
}


def _execution_plan_with_one_batch() -> dict:
    body = dict(_VALID_EXECUTION_PLAN_BODY)
    body["candidate_count"] = 2
    body["batches"] = [{
        "reason":                               "duplicate_headline_event_date",
        "size":                                 2,
        "event_ids":                            [3, 4],
        "examples": [
            {"event_id": 3, "headline": "h", "event_date": "2026-04-01",
             "reasons": ["duplicate_headline_event_date"]},
        ],
        "manual_review_required_before_delete": True,
        "description":                          "Multiple events share an "
                                                "identical (headline, "
                                                "event_date) pair.",
    }]
    body["recommended_next_action"] = _EXECUTION_PLAN_READY_RECOMMENDATION
    return body


class TestArchiveCleanupExecutionPlanInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.archive_cleanup_execution_plan --json --limit 5``: the
    plan is read-only by construction, so the smoke verifies the load-
    bearing shape (counts non-negative, batches well-formed,
    ``manual_review_required_before_delete=True`` on every batch,
    pinned confirmation flags, closed two-string recommendation
    vocabulary).  Stable zero values are accepted because a clean
    archive emits an empty ``batches`` list.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(
            _VALID_EXECUTION_PLAN_BODY,
        )

    def test_invariant_passes_when_batch_present(self) -> None:
        no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(
            _execution_plan_with_one_batch(),
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid([])

    def test_invariant_fails_when_candidate_count_missing(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body.pop("candidate_count")
        with self.assertRaisesRegex(
            AssertionError, "candidate_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_candidate_count_negative(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["candidate_count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "candidate_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_candidate_count_is_bool(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["candidate_count"] = True
        with self.assertRaisesRegex(
            AssertionError, "candidate_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_batches_not_list(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["batches"] = {"oops": True}
        with self.assertRaisesRegex(AssertionError, "batches must be a list"):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_batch_reason_outside_vocabulary(self) -> None:
        body = _execution_plan_with_one_batch()
        body["batches"][0]["reason"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError, "batches\\[0\\].reason must be one of",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_batch_size_mismatches_event_ids(self) -> None:
        body = _execution_plan_with_one_batch()
        body["batches"][0]["size"] = 99
        with self.assertRaisesRegex(
            AssertionError, "size must equal len\\(event_ids\\)",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_batch_event_ids_not_list(self) -> None:
        body = _execution_plan_with_one_batch()
        body["batches"][0]["event_ids"] = "nope"
        with self.assertRaisesRegex(
            AssertionError, "event_ids must be a list",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_manual_review_flag_not_true(self) -> None:
        # Auto-delete regression check: the plan must explicitly
        # disclaim writes on every batch.
        body = _execution_plan_with_one_batch()
        body["batches"][0]["manual_review_required_before_delete"] = False
        with self.assertRaisesRegex(
            AssertionError,
            "manual_review_required_before_delete must be True",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_batch_description_empty(self) -> None:
        body = _execution_plan_with_one_batch()
        body["batches"][0]["description"] = ""
        with self.assertRaisesRegex(
            AssertionError, "description must be a non-empty string",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_risk_notes_empty(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["risk_notes"] = []
        with self.assertRaisesRegex(
            AssertionError, "risk_notes must be a non-empty list",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_risk_note_not_string(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["risk_notes"] = [42]
        with self.assertRaisesRegex(
            AssertionError, "risk_notes\\[0\\] must be a non-empty string",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_required_flags_diverge_from_pin(self) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["required_confirmation_flags"] = [
            "backup_taken", "per_event_manual_review_complete",
        ]
        with self.assertRaisesRegex(
            AssertionError,
            "required_confirmation_flags must equal the pinned tuple",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_invariant_fails_when_recommendation_outside_vocabulary(
        self,
    ) -> None:
        body = dict(_VALID_EXECUTION_PLAN_BODY)
        body["recommended_next_action"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError, "recommended_next_action must be one of",
        ):
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid(body)

    def test_inventory_attaches_invariant_to_execution_plan_script(
        self,
    ) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_archive_cleanup_execution_plan_no_paid,
            match.body_invariants,
        )

    def test_execution_plan_script_passes_only_read_only_args(self) -> None:
        # Defense-in-depth: the smoke must call the script with --json
        # and --limit only.  No write-mode flag may be smuggled into
        # the args tuple.
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_CLEANUP_EXECUTION_PLAN_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn("--json", match.args)
        for arg in match.args:
            self.assertNotIn(
                "apply",  arg.lower(),
                f"execution-plan smoke args must not include a write "
                f"flag, got {match.args!r}",
            )
            self.assertNotIn(
                "delete", arg.lower(),
                f"execution-plan smoke args must not include a write "
                f"flag, got {match.args!r}",
            )
            self.assertNotIn(
                "write",  arg.lower(),
                f"execution-plan smoke args must not include a write "
                f"flag, got {match.args!r}",
            )


_TICKER_READINESS_OK_RECOMMENDATION = (
    "No archive cleanup candidates detected; no ticker-readiness "
    "review required."
)
_TICKER_READINESS_REVIEW_RECOMMENDATION = (
    "Cleanup candidates detected.  Review per-event ticker / "
    "price_cache / low_information columns to decide whether deletion "
    "via the operator path is safe; this report makes no DB writes."
)


_VALID_TICKER_READINESS_BODY: dict = {
    "candidate_count":           0,
    "tickers_present_count":     0,
    "price_cache_present_count": 0,
    "low_information_count":     0,
    "examples":                  [],
    "recommended_next_action":   _TICKER_READINESS_OK_RECOMMENDATION,
}


class TestArchiveCleanupTickerReadinessInvariants(unittest.TestCase):
    """The smoke runner pins structural invariants on
    ``scripts.archive_cleanup_candidate_ticker_readiness --json --limit 5``:
    counts are non-negative ints bounded by ``candidate_count``,
    ``price_cache_present_count <= tickers_present_count`` (price-cache
    coverage requires a primary ticker), and the recommendation comes
    from the closed two-string vocabulary.  Stable zero values are
    accepted because a clean archive has no candidates.
    """

    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
            _VALID_TICKER_READINESS_BODY,
        )

    def test_invariant_passes_when_counts_populated(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["candidate_count"]           = 203
        body["tickers_present_count"]     = 25
        body["price_cache_present_count"] = 22
        body["low_information_count"]     = 1
        body["examples"] = [{
            "event_id": 3, "headline": "h", "primary_ticker": "XLE",
            "has_market_tickers": True, "has_price_cache": True,
            "low_information": False,
            "reasons": ["duplicate_headline_event_date"],
        }]
        body["recommended_next_action"] = _TICKER_READINESS_REVIEW_RECOMMENDATION
        no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                ["not", "a", "dict"],
            )

    def test_invariant_fails_when_candidate_count_missing(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body.pop("candidate_count")
        with self.assertRaisesRegex(
            AssertionError, "candidate_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_count_is_bool(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["tickers_present_count"] = True
        with self.assertRaisesRegex(
            AssertionError, "tickers_present_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_count_negative(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["low_information_count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "low_information_count must be a non-negative int",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_examples_not_list(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["examples"] = {"oops": True}
        with self.assertRaisesRegex(AssertionError, "examples must be a list"):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_recommendation_outside_vocabulary(
        self,
    ) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["recommended_next_action"] = "drop_everything_and_panic"
        with self.assertRaisesRegex(
            AssertionError, "recommended_next_action must be one of",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_subset_count_exceeds_candidate_count(
        self,
    ) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["candidate_count"]       = 5
        body["tickers_present_count"] = 7
        body["recommended_next_action"] = _TICKER_READINESS_REVIEW_RECOMMENDATION
        with self.assertRaisesRegex(
            AssertionError,
            "tickers_present_count must not exceed candidate_count",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_invariant_fails_when_price_cache_exceeds_tickers(self) -> None:
        body = dict(_VALID_TICKER_READINESS_BODY)
        body["candidate_count"]           = 10
        body["tickers_present_count"]     = 5
        body["price_cache_present_count"] = 7
        body["recommended_next_action"] = _TICKER_READINESS_REVIEW_RECOMMENDATION
        with self.assertRaisesRegex(
            AssertionError,
            "price_cache_present_count must not exceed "
            "tickers_present_count",
        ):
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_ticker_readiness_script(
        self,
    ) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_CLEANUP_TICKER_READINESS_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_archive_cleanup_ticker_readiness_no_paid,
            match.body_invariants,
        )

    def test_ticker_readiness_script_passes_only_read_only_args(self) -> None:
        # Defense-in-depth: the smoke must call the script with --json
        # and --limit only.  No write-mode flag may be smuggled into
        # the args tuple.
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_CLEANUP_TICKER_READINESS_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn("--json", match.args)
        for arg in match.args:
            self.assertNotIn(
                "apply",  arg.lower(),
                f"ticker-readiness smoke args must not include a write "
                f"flag, got {match.args!r}",
            )
            self.assertNotIn(
                "delete", arg.lower(),
                f"ticker-readiness smoke args must not include a write "
                f"flag, got {match.args!r}",
            )
            self.assertNotIn(
                "write",  arg.lower(),
                f"ticker-readiness smoke args must not include a write "
                f"flag, got {match.args!r}",
            )


# ---------------------------------------------------------------------------
# Repaired-cohort + summary/short-horizon invariant tests
#
# Each new script gets the same triplet of pins as the older smoke
# scripts: a structural pass on a stable zero-shape body, a handful of
# fail-closed assertions that trip when a regression drops a field /
# returns negatives / breaks a partition floor, and an inventory pin
# proving the smoke runner attaches the matching invariant to the
# script entry.
# ---------------------------------------------------------------------------


_VALID_SHORT_HORIZON_READINESS_BODY = {
    "total_events":                          0,
    "events_ready_1d5d":                     0,
    "delta_vs_full_ready":                   0,
    "missing_tickers_count":                 0,
    "missing_benchmark_count":               0,
    "insufficient_estimation_window_count":  0,
    "examples":                              [],
    "recommended_next_action":               "synthetic",
}


class TestShortHorizonReadinessReportInvariants(unittest.TestCase):
    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_short_horizon_readiness_report_no_paid(
            _VALID_SHORT_HORIZON_READINESS_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid([])

    def test_invariant_fails_when_count_negative(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_READINESS_BODY)
        body["events_ready_1d5d"] = -1
        with self.assertRaisesRegex(
            AssertionError, "events_ready_1d5d must be a non-negative int",
        ):
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid(body)

    def test_invariant_fails_when_examples_not_list(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_READINESS_BODY)
        body["examples"] = "nope"
        with self.assertRaisesRegex(AssertionError, "examples must be a list"):
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid(body)

    def test_invariant_fails_when_short_ready_exceeds_total(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_READINESS_BODY)
        body["total_events"]      = 3
        body["events_ready_1d5d"] = 5
        with self.assertRaisesRegex(
            AssertionError, "events_ready_1d5d must not exceed total_events",
        ):
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid(body)

    def test_invariant_fails_when_delta_exceeds_short_ready(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_READINESS_BODY)
        body["total_events"]         = 10
        body["events_ready_1d5d"]    = 3
        body["delta_vs_full_ready"]  = 5
        with self.assertRaisesRegex(
            AssertionError,
            "delta_vs_full_ready must not exceed events_ready_1d5d",
        ):
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid(body)

    def test_inventory_attaches_invariant_to_short_horizon_readiness_script(
        self,
    ) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _SHORT_HORIZON_READINESS_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_short_horizon_readiness_report_no_paid,
            match.body_invariants,
        )


_VALID_SHORT_HORIZON_CONTAMINATION_BODY = {
    "ok":                       True,
    "total_short_ready":        0,
    "suspicious_count":         0,
    "clean_short_ready_count":  0,
    "by_flag": {
        "driv_lit_off_topic":       0,
        "mechanism_family_none":    0,
        "duplicate_date_ticker":    0,
        "local_off_topic_headline": 0,
    },
    "examples":                 [],
    "recommended_next_action":  "synthetic",
}


class TestShortHorizonContaminationReportInvariants(unittest.TestCase):
    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_short_horizon_contamination_report_no_paid(
            _VALID_SHORT_HORIZON_CONTAMINATION_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid([])

    def test_invariant_fails_when_ok_is_false(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_CONTAMINATION_BODY)
        body["ok"] = False
        with self.assertRaisesRegex(AssertionError, "ok must be True"):
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid(
                body,
            )

    def test_invariant_fails_when_count_negative(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_CONTAMINATION_BODY)
        body["suspicious_count"] = -1
        with self.assertRaisesRegex(
            AssertionError, "suspicious_count must be a non-negative int",
        ):
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid(
                body,
            )

    def test_invariant_fails_when_by_flag_missing_bucket(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_CONTAMINATION_BODY)
        by_flag = dict(body["by_flag"])
        by_flag.pop("driv_lit_off_topic")
        body["by_flag"] = by_flag
        with self.assertRaisesRegex(
            AssertionError,
            "by_flag\\['driv_lit_off_topic'\\] must be a non-negative int",
        ):
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid(
                body,
            )

    def test_invariant_fails_when_partition_arithmetic_breaks(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_CONTAMINATION_BODY)
        body["total_short_ready"]       = 10
        body["suspicious_count"]        = 4
        body["clean_short_ready_count"] = 5  # 4+5 != 10
        with self.assertRaisesRegex(
            AssertionError,
            "suspicious_count \\+ clean_short_ready_count must equal "
            "total_short_ready",
        ):
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_contamination_script(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _SHORT_HORIZON_CONTAMINATION_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_short_horizon_contamination_report_no_paid,
            match.body_invariants,
        )


_VALID_ARCHIVE_SHORT_HORIZON_RUN_BODY = {
    "events_evaluated":     0,
    "records_count":        0,
    "significant_count":    0,
    "by_horizon":           {},
    "by_mechanism_family":  {},
    "examples":             [],
    "errors":               [],
}


class TestArchiveShortHorizonRunInvariants(unittest.TestCase):
    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_archive_short_horizon_run_no_paid(
            _VALID_ARCHIVE_SHORT_HORIZON_RUN_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_archive_short_horizon_run_no_paid([])

    def test_invariant_fails_when_errors_non_empty(self) -> None:
        body = dict(_VALID_ARCHIVE_SHORT_HORIZON_RUN_BODY)
        body["errors"] = ["pipeline error"]
        with self.assertRaisesRegex(AssertionError, "errors must be empty"):
            no_paid_smoke._assert_archive_short_horizon_run_no_paid(body)

    def test_invariant_fails_when_significant_exceeds_records(self) -> None:
        body = dict(_VALID_ARCHIVE_SHORT_HORIZON_RUN_BODY)
        body["records_count"]     = 3
        body["significant_count"] = 5
        with self.assertRaisesRegex(
            AssertionError, "significant_count must not exceed records_count",
        ):
            no_paid_smoke._assert_archive_short_horizon_run_no_paid(body)

    def test_invariant_fails_when_by_horizon_not_dict(self) -> None:
        body = dict(_VALID_ARCHIVE_SHORT_HORIZON_RUN_BODY)
        body["by_horizon"] = []
        with self.assertRaisesRegex(AssertionError, "by_horizon must be a dict"):
            no_paid_smoke._assert_archive_short_horizon_run_no_paid(body)

    def test_inventory_attaches_invariant_to_archive_short_horizon_run(
        self,
    ) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_SHORT_HORIZON_RUN_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_archive_short_horizon_run_no_paid,
            match.body_invariants,
        )


_VALID_ARCHIVE_DEDUP_SUMMARY_BODY = {
    "ok":                              True,
    "records_count":                   0,
    "effective_unique_records_count":  0,
    "duplicate_records_count":         0,
    "duplicate_groups_count":          0,
    "by_horizon":                      {},
    "qvalue_change": {
        "raw_significant_records":            0,
        "raw_significant_unique_records":     0,
        "deduped_significant_unique_records": 0,
        "groups_gaining_significance":        0,
        "groups_losing_significance":         0,
        "any_change":                         False,
    },
    "top_abs_sar":                     [],
    "errors":                          [],
}


class TestArchiveDedupSummaryInvariants(unittest.TestCase):
    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_archive_dedup_summary_no_paid(
            _VALID_ARCHIVE_DEDUP_SUMMARY_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_archive_dedup_summary_no_paid([])

    def test_invariant_fails_when_ok_is_false(self) -> None:
        body = dict(_VALID_ARCHIVE_DEDUP_SUMMARY_BODY)
        body["ok"] = False
        with self.assertRaisesRegex(AssertionError, "ok must be True"):
            no_paid_smoke._assert_archive_dedup_summary_no_paid(body)

    def test_invariant_fails_when_unique_exceeds_records(self) -> None:
        body = dict(_VALID_ARCHIVE_DEDUP_SUMMARY_BODY)
        body["records_count"]                  = 3
        body["effective_unique_records_count"] = 5
        with self.assertRaisesRegex(
            AssertionError,
            "effective_unique_records_count must not exceed records_count",
        ):
            no_paid_smoke._assert_archive_dedup_summary_no_paid(body)

    def test_invariant_fails_when_qvalue_change_missing(self) -> None:
        body = dict(_VALID_ARCHIVE_DEDUP_SUMMARY_BODY)
        body["qvalue_change"] = {}  # missing every required sub-int
        with self.assertRaisesRegex(
            AssertionError,
            "qvalue_change\\['raw_significant_records'\\] must be a "
            "non-negative int",
        ):
            no_paid_smoke._assert_archive_dedup_summary_no_paid(body)

    def test_invariant_fails_when_top_abs_sar_not_list(self) -> None:
        body = dict(_VALID_ARCHIVE_DEDUP_SUMMARY_BODY)
        body["top_abs_sar"] = {}
        with self.assertRaisesRegex(AssertionError, "top_abs_sar must be a list"):
            no_paid_smoke._assert_archive_dedup_summary_no_paid(body)

    def test_inventory_attaches_invariant_to_dedup_summary(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _ARCHIVE_DEDUP_SUMMARY_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_archive_dedup_summary_no_paid,
            match.body_invariants,
        )


_VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY = {
    "ok":                          True,
    "candidate_count":             0,
    "candidates":                  [],
    "excluded_contaminated_count": 0,
    "top_abs_sar":                 None,
    "recommended_next_action":     "synthetic",
}


class TestShortHorizonShowcaseShortlistInvariants(unittest.TestCase):
    def test_invariant_passes_on_stable_zero_response(self) -> None:
        no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid(
            _VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY,
        )

    def test_invariant_passes_when_candidates_populated(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY)
        body["candidate_count"] = 1
        body["candidates"]      = [{"event_id": 1, "abs_sar": 0.5}]
        body["top_abs_sar"]     = {"event_id": 1, "abs_sar": 0.5}
        no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid(body)

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid([])

    def test_invariant_fails_when_candidate_count_mismatch(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY)
        body["candidate_count"] = 2
        body["candidates"]      = [{"event_id": 1}]
        with self.assertRaisesRegex(
            AssertionError, "candidate_count must equal len\\(candidates\\)",
        ):
            no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid(
                body,
            )

    def test_invariant_fails_when_top_abs_sar_set_but_no_candidates(
        self,
    ) -> None:
        body = dict(_VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY)
        body["top_abs_sar"] = {"event_id": 99, "abs_sar": 1.0}
        with self.assertRaisesRegex(
            AssertionError,
            "top_abs_sar must be None when candidate_count == 0",
        ):
            no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid(
                body,
            )

    def test_invariant_fails_when_top_abs_sar_wrong_type(self) -> None:
        body = dict(_VALID_SHORT_HORIZON_SHOWCASE_SHORTLIST_BODY)
        body["candidate_count"] = 1
        body["candidates"]      = [{"event_id": 1}]
        body["top_abs_sar"]     = "leader"
        with self.assertRaisesRegex(
            AssertionError, "top_abs_sar must be a dict or None",
        ):
            no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_showcase_shortlist(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _SHORT_HORIZON_SHOWCASE_SHORTLIST_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_short_horizon_showcase_shortlist_no_paid,
            match.body_invariants,
        )


_VALID_MANUAL_REPAIRED_COHORT_BODY = {
    "ok":                       False,
    "repaired_clean_event_ids": [],
    "events_evaluated":         0,
    "records_count":            0,
    "significant_count":        0,
    "by_horizon":               {},
    "by_mechanism_family":      {},
    "examples":                 [],
    "excluded_event_ids":       [],
    "remaining_blockers":       {},
    "live_db_unchanged":        True,
    "input_backup_unchanged":   True,
    "errors": [
        "Provider unavailable (yfinance not importable) — failing closed",
    ],
    "warnings":                 [],
}


class TestManualRepairedCohortValidationInvariants(unittest.TestCase):
    def test_invariant_passes_on_fail_closed_response(self) -> None:
        no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
            _VALID_MANUAL_REPAIRED_COHORT_BODY,
        )

    def test_invariant_fails_when_body_not_object(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be a JSON object"):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid([])

    def test_invariant_fails_when_live_db_changed(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["live_db_unchanged"] = False
        with self.assertRaisesRegex(
            AssertionError, "live_db_unchanged must be True",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_backup_changed(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["input_backup_unchanged"] = False
        with self.assertRaisesRegex(
            AssertionError, "input_backup_unchanged must be True",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_ok_is_true_under_stub(self) -> None:
        # ``ok=True`` under the no-paid stub means the runner reached
        # provider code and succeeded — exactly the regression the
        # smoke must catch.
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["ok"] = True
        body["errors"] = []
        with self.assertRaisesRegex(
            AssertionError, "ok must be False under the no-paid",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_errors_empty_under_stub(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["errors"] = []
        with self.assertRaisesRegex(
            AssertionError, "errors must be a non-empty list",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_errors_lack_provider_keyword(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["errors"] = ["unrelated failure"]
        with self.assertRaisesRegex(
            AssertionError, "errors must mention 'provider'",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_records_nonzero_under_stub(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["records_count"] = 3
        with self.assertRaisesRegex(
            AssertionError, "records_count must be 0 under the no-paid",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_invariant_fails_when_examples_populated_under_stub(self) -> None:
        body = dict(_VALID_MANUAL_REPAIRED_COHORT_BODY)
        body["examples"] = [{"event_id": 1}]
        with self.assertRaisesRegex(
            AssertionError, "examples must be an empty list",
        ):
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid(
                body,
            )

    def test_inventory_attaches_invariant_to_repaired_cohort_runner(
        self,
    ) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _MANUAL_REPAIRED_COHORT_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertIn(
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid,
            match.body_invariants,
        )

    def test_repaired_cohort_runner_args_carry_required_inputs(self) -> None:
        # The runner needs --backup-path, --high-priority-csv,
        # --medium-csv to do anything other than emit "missing input"
        # errors.  Pinning the args here means a future regression that
        # drops one of the inputs trips the smoke instead of silently
        # leaving the runner in its no-arg fail-closed branch.
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _MANUAL_REPAIRED_COHORT_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        args = list(match.args)
        for required_flag in (
            "--backup-path",
            "--high-priority-csv",
            "--medium-csv",
        ):
            self.assertIn(required_flag, args)


# ---------------------------------------------------------------------------
# Provider seam wiring for the repaired-cohort runner
#
# The runner's ``_check_provider_available`` seam must be force-False
# under the no-paid guard and ``_fetch_ticker_rows`` must be a raiser
# (defense in depth).  Pin both wires here so a future regression that
# drops the stub or the raiser trips a unit test before the smoke runs
# the runner against real backups.
# ---------------------------------------------------------------------------


class TestRepairedCohortRunnerNoPaidWiring(unittest.TestCase):
    def test_check_provider_available_is_stubbed_to_false_under_guard(
        self,
    ) -> None:
        target_module = __import__(
            _MANUAL_REPAIRED_COHORT_MODULE, fromlist=["main"],
        )
        with no_paid_smoke.guard_no_paid_provider_calls():
            self.assertIs(target_module._check_provider_available(), False)
        # Original seam restored after the guard exits.
        self.assertTrue(callable(target_module._check_provider_available))

    def test_fetch_ticker_rows_raises_under_guard(self) -> None:
        target_module = __import__(
            _MANUAL_REPAIRED_COHORT_MODULE, fromlist=["main"],
        )
        with no_paid_smoke.guard_no_paid_provider_calls():
            with self.assertRaisesRegex(
                RuntimeError, "no-paid smoke attempted forbidden seam",
            ):
                target_module._fetch_ticker_rows(
                    ticker="MS", start="2026-01-01", end="2026-01-02",
                )


class TestRepairedCohortRunnerGuardFailsClosed(_Base):
    """Symmetric pin for the manual repaired-cohort validation runner.
    The runner must run under the same provider/paid guard as the
    older smoke scripts; if a future regression has it reach
    ``market_check`` / ``yfinance`` / LLM seams, the guard fires and
    the smoke marks the result failed.
    """

    def test_runner_invoking_forbidden_seam_marks_smoke_failed(self) -> None:
        from unittest.mock import patch

        target_module = __import__(
            _MANUAL_REPAIRED_COHORT_MODULE, fromlist=["main"],
        )

        def _seam_invoking_main(_argv, *, out=None):
            import market_check
            market_check._fetch("SPY")
            return 0

        # Force the required-fixture gate to "present" so the seam path runs
        # even on a clean clone where the untracked backup is absent.  The
        # skip-gate must never mask a paid seam when the fixture is present.
        with patch.object(
            no_paid_smoke, "_fixture_exists", return_value=True,
        ), patch.object(target_module, "main", _seam_invoking_main):
            results = no_paid_smoke.run_smoke(client=client)

        broken = [
            r for r in results
            if _MANUAL_REPAIRED_COHORT_MODULE in r.path
        ]
        self.assertEqual(len(broken), 1)
        self.assertFalse(broken[0].skipped)
        self.assertFalse(broken[0].ok)
        self.assertIn("forbidden seam", broken[0].error or "")
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])


class TestSummarizeSkipSemantics(unittest.TestCase):
    """A skipped check is counted separately from passed and failed, and a
    skip alone never flips the overall ``ok`` to False.  Pins the summary
    contract independently of the live archive.
    """

    def _result(self, name, *, ok, skipped=False, error=None):
        return no_paid_smoke.SmokeResult(
            name=name,
            path=f"python -m scripts.{name}",
            ok=ok,
            status_code=None,
            elapsed_ms=1,
            error=error,
            skipped=skipped,
        )

    def test_skipped_counted_separately_and_not_as_failure(self) -> None:
        results = [
            self._result("passing", ok=True),
            self._result("failing", ok=False, error="boom"),
            self._result(
                "skipped",
                ok=False,
                skipped=True,
                error="skipped: required local fixture(s) absent: x",
            ),
        ]
        summary = no_paid_smoke.summarize(results)["summary"]
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["total"], 3)

    def test_real_failure_alongside_skip_flips_overall_ok_false(self) -> None:
        results = [
            self._result("failing", ok=False, error="boom"),
            self._result("skipped", ok=False, skipped=True, error="skipped: x"),
        ]
        self.assertFalse(no_paid_smoke.summarize(results)["ok"])

    def test_skip_alone_keeps_overall_ok_true(self) -> None:
        results = [
            self._result("passing", ok=True),
            self._result("skipped", ok=False, skipped=True, error="skipped: x"),
        ]
        payload = no_paid_smoke.summarize(results)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["skipped"], 1)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertEqual(payload["summary"]["passed"], 1)

    def test_render_table_marks_skipped_rows(self) -> None:
        table = no_paid_smoke.render_table([
            self._result("passing", ok=True),
            self._result("skipped", ok=False, skipped=True, error="skipped: x"),
        ])
        self.assertIn("SKIP", table)


class TestRequiredFixtureGate(unittest.TestCase):
    """``_missing_required_paths`` drives the skip decision through the
    patchable ``_fixture_exists`` seam.  Scripts without ``required_paths``
    never skip, and check #30 pins the untracked backup while keeping its
    no-paid invariant attached.
    """

    def test_missing_when_fixture_absent(self) -> None:
        from unittest.mock import patch

        script = no_paid_smoke.SmokeScript(
            "demo", "scripts.demo", required_paths=("backups/nope.db",),
        )
        with patch.object(no_paid_smoke, "_fixture_exists", return_value=False):
            self.assertEqual(
                no_paid_smoke._missing_required_paths(script),
                ["backups/nope.db"],
            )

    def test_empty_when_fixture_present(self) -> None:
        from unittest.mock import patch

        script = no_paid_smoke.SmokeScript(
            "demo", "scripts.demo", required_paths=("backups/nope.db",),
        )
        with patch.object(no_paid_smoke, "_fixture_exists", return_value=True):
            self.assertEqual(no_paid_smoke._missing_required_paths(script), [])

    def test_script_without_required_paths_never_skips(self) -> None:
        script = no_paid_smoke.SmokeScript("demo", "scripts.demo")
        self.assertEqual(no_paid_smoke._missing_required_paths(script), [])

    def test_manual_repaired_pins_backup_path_and_keeps_invariant(self) -> None:
        match = next(
            (s for s in no_paid_smoke.SCRIPTS
             if s.module == _MANUAL_REPAIRED_COHORT_MODULE),
            None,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            match.required_paths,
            ("backups/events-20260507T095609.db",),
        )
        # the gated fixture is exactly the runner's --backup-path input
        self.assertIn("backups/events-20260507T095609.db", match.args)
        # the no-paid invariant must remain attached (not stripped)
        self.assertIn(
            no_paid_smoke._assert_manual_repaired_cohort_validation_no_paid,
            match.body_invariants,
        )


class TestSkipMissingFixtureEndToEnd(_Base):
    """End-to-end: with the untracked backup absent (clean clone / CI),
    check #30 is skipped — reported distinctly, not failed, not silently
    passed — and the overall smoke stays ``ok``.  With the fixture present
    the check reaches the runner (the seam-fails-closed pin above proves it
    still enforces the no-paid invariant when present).
    """

    def test_manual_repaired_skipped_when_backup_absent(self) -> None:
        from unittest.mock import patch

        # _fixture_exists is consulted only for scripts that declare
        # required_paths (today only check #30), so forcing it False skips
        # exactly that check and nothing else.
        with patch.object(no_paid_smoke, "_fixture_exists", return_value=False):
            results = no_paid_smoke.run_smoke(client=client)

        manual = [
            r for r in results if _MANUAL_REPAIRED_COHORT_MODULE in r.path
        ]
        self.assertEqual(len(manual), 1)
        self.assertTrue(manual[0].skipped)
        self.assertFalse(manual[0].ok)
        self.assertIn("skipped", (manual[0].error or "").lower())

        payload = no_paid_smoke.summarize(results)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["skipped"], 1)
        self.assertEqual(payload["summary"]["failed"], 0)

    def test_manual_repaired_runs_when_backup_present(self) -> None:
        from unittest.mock import patch

        ran: list[str] = []

        def _spy(script):
            ran.append(script.module)
            return True, None

        with patch.object(
            no_paid_smoke, "_fixture_exists", return_value=True,
        ), patch.object(no_paid_smoke, "_run_script", side_effect=_spy):
            results = no_paid_smoke.run_smoke(client=client)

        # present fixture -> check #30 reaches the runner (not skipped)
        self.assertIn(_MANUAL_REPAIRED_COHORT_MODULE, ran)
        manual = [
            r for r in results if _MANUAL_REPAIRED_COHORT_MODULE in r.path
        ]
        self.assertEqual(len(manual), 1)
        self.assertFalse(manual[0].skipped)

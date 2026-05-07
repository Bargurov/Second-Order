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
        failures = [r for r in results if not r.ok]
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
        ])

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
                r.ok,
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

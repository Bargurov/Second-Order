"""Tests for archive_rebuild — selection, validation, dry-run, write.

The composer pulls in ``frozen_overlay_refresh`` as the overlay runner,
and that composer makes live macro calls.  To keep these tests fast +
hermetic we monkeypatch the ``_OPERATION_RUNNERS`` dict so the runner
becomes a deterministic stub.  That also lets us assert exact
behaviour around eligibility / error-handling without needing real
macro data.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import archive_rebuild
from archive_rebuild import (
    SUPPORTED_OPERATIONS,
    execute_rebuild,
    format_rebuild_report,
    run_archive_rebuild,
    select_events,
    validate_rebuild,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = date(2026, 4, 19)


def _ev(
    eid: int,
    days_ago: int = 10,
    family: str = "tariff",
    low_signal: bool = False,
) -> dict:
    from datetime import timedelta
    d = (NOW - timedelta(days=days_ago)).isoformat()
    return {
        "id": eid,
        "headline": f"Event {eid}",
        "event_date": d,
        "mechanism_family": family,
        "low_signal": low_signal,
    }


class _StubRunner:
    """Deterministic runner that mimics the composer contract."""

    def __init__(self):
        self.persist_calls: list[int] = []
        self.dry_calls: list[int] = []

    def __call__(self, event: dict, *, persist: bool, now=None) -> dict:
        if persist:
            self.persist_calls.append(event.get("id"))
        else:
            self.dry_calls.append(event.get("id"))
        # Derive eligibility from a test hook on the event itself.
        if event.get("_force_error"):
            return {
                "event_id": event.get("id"),
                "refreshed": [],
                "skipped": [],
                "eligibility": {"eligible": False, "reason": "composer_error"},
                "written": False,
                "error": "boom",
            }
        if event.get("_ineligible_reason"):
            return {
                "event_id": event.get("id"),
                "refreshed": [],
                "skipped": ["policy_sensitivity"],
                "eligibility": {
                    "eligible": False,
                    "reason":   event["_ineligible_reason"],
                },
                "written": False,
            }
        return {
            "event_id":  event.get("id"),
            "refreshed": ["policy_sensitivity", "real_yield_context"],
            "skipped":   [],
            "eligibility": {"eligible": True, "reason": "eligible"},
            "written":   persist,
        }


class _RunnerPatched(unittest.TestCase):
    """Base class that swaps the overlay runner with a stub per test."""

    def setUp(self):
        self.stub = _StubRunner()
        self._saved = archive_rebuild._OPERATION_RUNNERS["overlays"]
        archive_rebuild._OPERATION_RUNNERS["overlays"] = self.stub

    def tearDown(self):
        archive_rebuild._OPERATION_RUNNERS["overlays"] = self._saved


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class TestSelection(unittest.TestCase):
    def test_empty_events_safe(self):
        r = select_events([], now=NOW)
        self.assertEqual(r["candidates"], [])
        self.assertEqual(r["total_considered"], 0)

    def test_none_events_safe(self):
        r = select_events(None, now=NOW)
        self.assertEqual(r["candidates"], [])

    def test_filter_by_event_ids(self):
        evs = [_ev(1), _ev(2), _ev(3)]
        r = select_events(evs, event_ids=[1, 3], now=NOW)
        self.assertEqual({e["id"] for e in r["candidates"]}, {1, 3})

    def test_filter_by_family(self):
        evs = [_ev(1, family="tariff"), _ev(2, family="sanction")]
        r = select_events(evs, mechanism_family=["tariff"], now=NOW)
        self.assertEqual(len(r["candidates"]), 1)
        self.assertEqual(r["candidates"][0]["id"], 1)

    def test_filter_by_date_range(self):
        evs = [_ev(1, days_ago=5), _ev(2, days_ago=40), _ev(3, days_ago=100)]
        start = (NOW.fromisoformat("2026-02-20")).isoformat()
        end   = (NOW.fromisoformat("2026-04-15")).isoformat()
        r = select_events(evs, date_range=(start, end), now=NOW)
        ids = {e["id"] for e in r["candidates"]}
        self.assertIn(2, ids)

    def test_filter_by_age_bounds(self):
        evs = [_ev(1, days_ago=5), _ev(2, days_ago=45), _ev(3, days_ago=90)]
        r = select_events(evs, min_age_days=30, max_age_days=60, now=NOW)
        self.assertEqual({e["id"] for e in r["candidates"]}, {2})

    def test_filter_low_signal(self):
        evs = [_ev(1, low_signal=True), _ev(2, low_signal=False)]
        r = select_events(evs, low_signal=False, now=NOW)
        self.assertEqual({e["id"] for e in r["candidates"]}, {2})

    def test_limit_caps_output(self):
        evs = [_ev(i, days_ago=i) for i in range(1, 20)]
        r = select_events(evs, limit=5, now=NOW)
        self.assertEqual(len(r["candidates"]), 5)

    def test_order_is_deterministic_recent_first(self):
        evs = [_ev(1, days_ago=60), _ev(2, days_ago=10), _ev(3, days_ago=30)]
        r = select_events(evs, now=NOW)
        ids = [e["id"] for e in r["candidates"]]
        self.assertEqual(ids, [2, 3, 1])

    def test_events_without_date_skipped_by_age_filter(self):
        evs = [{"id": 1, "headline": "no date", "mechanism_family": "tariff"}]
        r = select_events(evs, min_age_days=10, now=NOW)
        self.assertEqual(r["candidates"], [])

    def test_non_dict_events_skipped(self):
        r = select_events(["garbage", None, _ev(1)], now=NOW)
        self.assertEqual(len(r["candidates"]), 1)

    def test_filter_echo_in_output(self):
        evs = [_ev(1)]
        r = select_events(evs, mechanism_family=["tariff"], limit=10, now=NOW)
        self.assertIn("mechanism_family", r["filter"])
        self.assertIn("anchor_date", r["filter"])
        self.assertEqual(r["filter"]["limit"], 10)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(_RunnerPatched):
    def test_unknown_operation_raises(self):
        with self.assertRaises(ValueError):
            validate_rebuild([_ev(1)], operation="not_a_thing")

    def test_supported_operations_pinned(self):
        self.assertIn("overlays", SUPPORTED_OPERATIONS)

    def test_all_eligible(self):
        r = validate_rebuild([_ev(1), _ev(2)], operation="overlays")
        self.assertEqual(r["counts"]["eligible"], 2)
        self.assertEqual(r["counts"]["ineligible"], 0)
        self.assertEqual(r["counts"]["errored"], 0)

    def test_mixed_eligibility(self):
        evs = [
            _ev(1),
            {**_ev(2), "_ineligible_reason": "too_recent"},
            {**_ev(3), "_force_error": True},
        ]
        r = validate_rebuild(evs, operation="overlays")
        self.assertEqual(r["counts"]["eligible"], 1)
        self.assertEqual(r["counts"]["ineligible"], 1)
        self.assertEqual(r["counts"]["errored"], 1)
        self.assertIn("too_recent", r["by_reason"])
        self.assertIn("composer_error", r["by_reason"])

    def test_validation_never_persists(self):
        evs = [_ev(1), _ev(2)]
        validate_rebuild(evs, operation="overlays")
        self.assertEqual(self.stub.persist_calls, [])
        self.assertEqual(self.stub.dry_calls, [1, 2])

    def test_samples_capped_at_five(self):
        evs = [_ev(i) for i in range(1, 12)]
        r = validate_rebuild(evs, operation="overlays")
        self.assertLessEqual(len(r["samples"]["eligible"]), 5)


# ---------------------------------------------------------------------------
# Execute — dry run + write
# ---------------------------------------------------------------------------

class TestExecute(_RunnerPatched):
    def test_dry_run_never_persists(self):
        evs = [_ev(1), _ev(2)]
        report = execute_rebuild(evs, operation="overlays", dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["write"]["attempted"], 0)
        self.assertEqual(self.stub.persist_calls, [])

    def test_write_mode_persists_only_eligible(self):
        evs = [
            _ev(1),
            {**_ev(2), "_ineligible_reason": "too_recent"},
            _ev(3),
        ]
        report = execute_rebuild(evs, operation="overlays", dry_run=False)
        self.assertFalse(report["dry_run"])
        self.assertEqual(report["write"]["attempted"], 2)
        self.assertEqual(report["write"]["written"], 2)
        self.assertEqual(report["write"]["errored"], 0)
        self.assertEqual(set(self.stub.persist_calls), {1, 3})

    def test_write_mode_captures_errors(self):
        evs = [_ev(1), {**_ev(2), "_force_error": True}]
        report = execute_rebuild(evs, operation="overlays", dry_run=False)
        # Errored row was classified as ineligible in validation, so the
        # write loop never touches it — errored count stays 0 here and
        # the validation block carries the error signal.
        self.assertEqual(report["write"]["written"], 1)
        self.assertEqual(report["validation"]["counts"]["errored"], 1)

    def test_unknown_operation_raises(self):
        with self.assertRaises(ValueError):
            execute_rebuild([_ev(1)], operation="not_a_thing")

    def test_report_shape(self):
        report = execute_rebuild([_ev(1)], operation="overlays")
        for key in (
            "operation", "dry_run", "generated_at", "validation", "write",
        ):
            self.assertIn(key, report)


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

class TestRunArchiveRebuild(_RunnerPatched):
    def test_defaults_to_dry_run(self):
        evs = [_ev(1), _ev(2)]
        report = run_archive_rebuild(evs)
        self.assertTrue(report["dry_run"])
        self.assertEqual(self.stub.persist_calls, [])

    def test_write_flag_persists(self):
        evs = [_ev(1), _ev(2)]
        report = run_archive_rebuild(evs, write=True)
        self.assertFalse(report["dry_run"])
        self.assertEqual(set(self.stub.persist_calls), {1, 2})

    def test_selection_block_attached(self):
        evs = [_ev(1, family="tariff"), _ev(2, family="sanction")]
        report = run_archive_rebuild(evs, mechanism_family=["tariff"])
        self.assertIn("selection", report)
        self.assertEqual(report["selection"]["candidate_count"], 1)
        self.assertEqual(report["selection"]["total_considered"], 2)

    def test_empty_events_returns_empty_candidates(self):
        report = run_archive_rebuild([])
        self.assertEqual(report["validation"]["candidate_count"], 0)


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

class TestMarkdownReport(_RunnerPatched):
    def test_empty_report_safe(self):
        self.assertEqual(format_rebuild_report(None), "")
        self.assertEqual(format_rebuild_report("garbage"), "")

    def test_dry_run_report_flags_dry_mode(self):
        report = run_archive_rebuild([_ev(1), _ev(2)])
        md = format_rebuild_report(report)
        self.assertIn("dry-run", md.lower())
        self.assertIn("Dry-run", md)

    def test_write_report_shows_counts(self):
        report = run_archive_rebuild([_ev(1), _ev(2)], write=True)
        md = format_rebuild_report(report)
        self.assertIn("written=2", md)

    def test_report_mentions_eligibility_reasons(self):
        evs = [_ev(1), {**_ev(2), "_ineligible_reason": "too_recent"}]
        report = run_archive_rebuild(evs)
        md = format_rebuild_report(report)
        self.assertIn("too_recent", md)

    def test_report_ends_with_newline(self):
        report = run_archive_rebuild([_ev(1)])
        md = format_rebuild_report(report)
        self.assertTrue(md.endswith("\n"))


# ---------------------------------------------------------------------------
# Composer-adapter error capture
# ---------------------------------------------------------------------------

class TestRunnerAdapter(unittest.TestCase):
    def test_adapter_catches_exceptions(self):
        # Swap the real frozen_overlay_refresh import with one that raises
        import frozen_overlay_refresh as mod
        saved = mod.refresh_overlays_for_event

        def _boom(_event, **_kw):
            raise RuntimeError("simulated")

        try:
            mod.refresh_overlays_for_event = _boom
            result = archive_rebuild._run_overlay_rebuild(
                {"id": 1}, persist=False, now=None,
            )
        finally:
            mod.refresh_overlays_for_event = saved

        self.assertFalse(result["eligibility"]["eligible"])
        self.assertEqual(result["eligibility"]["reason"], "composer_error")
        self.assertIn("simulated", result["error"])


if __name__ == "__main__":
    unittest.main()

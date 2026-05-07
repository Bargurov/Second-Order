"""Tests for ``scripts/project_health_check.py``.

The aggregator composes four read-only checks; every test patches the
underlying seams so the suite never depends on a real archive.  Pins:

* All-pass case yields top-level ``ok=True`` with every section
  populated.
* Each failure mode lands in either ``errors`` (top-level ``ok=False``)
  or ``warnings`` (top-level ``ok=True``) per the classification rules.
* A sub-check that raises is captured as an error and does not abort
  the run — every other section still executes.
* JSON output carries every required top-level key and is valid JSON.
* Aggregator never invokes a provider/yfinance/LLM/FastAPI seam.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import project_health_check as phc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture payloads — all four seams produce these dicts.  Every test
# starts from a clean copy via ``dict(...)`` so mutations don't bleed.
# ---------------------------------------------------------------------------


_OK_REPO_HYGIENE = {
    "ok":                      True,
    "tracked_generated_count": 0,
    "tracked_generated_paths": [],
}

_OK_BACKUP_RESTORE = {
    "ok":                  True,
    "backup_path":         "backups/events-20260507T120000.db",
    "temp_copy_path":      "/tmp/restore_check.db",
    "table_counts":        {"events": 271, "price_cache": 10_440},
    "warnings":            [],
    "errors":              [],
    "tables":              ["events", "price_cache"],
    "events_columns":      ["id", "headline", "event_date"],
    "price_cache_present": True,
}

_OK_SCHEMA_PREFLIGHT = {
    "database_path":             "events.db",
    "database_exists":           True,
    "database_size_bytes":       4096,
    "tables":                    ["events", "price_cache"],
    "events_columns":            ["id", "headline"],
    "price_cache_present":       True,
    "backup_dir":                "backups",
    "backup_dir_exists":         True,
    "latest_backup":             "backups/events-20260507T120000.db",
    "latest_backup_age_seconds": 3600,
    "warnings":                  [],
}

_OK_PLAN = {
    "total_candidates":           0,
    "events_with_market_tickers": 0,
    "ticker_rows_blocked":        0,
    "proposed_updates":           [],
    "skipped_counts":             {"timestamp_unparseable": 0},
    "confidence_note":            "stub note",
    "projected_hydration_impact": {
        "candidate_events":               0,
        "proposed_updates_count":         0,
        "ticker_rows_blocked":            0,
        "ticker_rows_unblocked_by_write": 0,
        "remaining_ticker_rows_blocked":  0,
        "skipped_counts":                 {"timestamp_unparseable": 0},
    },
}


_ARCHIVE_CATEGORY_KEYS = (
    "malformed_market_tickers_json",
    "missing_headline",
    "missing_timestamp",
    "missing_event_date",
    "malformed_event_date",
    "missing_market_tickers",
    "duplicate_headline_event_date_clusters",
)


def _ok_archive_consistency() -> dict:
    return {key: {"count": 0, "examples": []} for key in _ARCHIVE_CATEGORY_KEYS}


def _archive_with(**counts) -> dict:
    """Build an archive-consistency response with selected categories
    populated.  Categories not named keep their zero-count default."""
    base = _ok_archive_consistency()
    for cat, count in counts.items():
        examples = [
            {"event_id": i, "headline": f"row {i}", "timestamp": "x",
             "event_date": "x"}
            for i in range(min(count, 10))
        ]
        base[cat] = {"count": count, "examples": examples}
    return base


def _patch_all_clean():
    """Return a context-manager-like ExitStack that patches every
    aggregator seam to a clean fixture."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch.object(
        phc, "list_tracked_generated",
        return_value=[],
    ))
    stack.enter_context(patch.object(
        phc, "restore_check",
        return_value=dict(_OK_BACKUP_RESTORE),
    ))
    stack.enter_context(patch.object(
        phc, "schema_preflight_collect",
        return_value=dict(_OK_SCHEMA_PREFLIGHT),
    ))
    stack.enter_context(patch.object(
        phc, "plan_event_date_backfill",
        return_value=dict(_OK_PLAN),
    ))
    stack.enter_context(patch.object(
        phc, "compute_archive_consistency_local",
        return_value=_ok_archive_consistency(),
    ))
    return stack


# ---------------------------------------------------------------------------
# All-pass aggregation
# ---------------------------------------------------------------------------


class TestAllPass(unittest.TestCase):
    def test_all_clean_seams_yield_top_level_ok(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertTrue(payload["ok"], f"errors={payload['errors']}")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["warnings"], [])

    def test_all_sections_populated(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        for key in (
            "repo_hygiene",
            "backup_restore",
            "schema_preflight",
            "event_date_backfill_candidates",
            "archive_consistency",
            "event_date_backfill_impact",
        ):
            self.assertIsNotNone(
                payload.get(key),
                f"section missing or None: {key}",
            )


# ---------------------------------------------------------------------------
# Required top-level shape
# ---------------------------------------------------------------------------


class TestPayloadShape(unittest.TestCase):
    def test_all_required_top_level_keys_present(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        for key in (
            "ok",
            "repo_hygiene",
            "backup_restore",
            "schema_preflight",
            "event_date_backfill_candidates",
            "archive_consistency",
            "event_date_backfill_impact",
            "warnings",
            "errors",
            "accepted_warnings",
        ):
            self.assertIn(key, payload, f"missing top-level key: {key}")

    def test_warnings_and_errors_are_lists(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertIsInstance(payload["warnings"],          list)
        self.assertIsInstance(payload["errors"],            list)
        self.assertIsInstance(payload["accepted_warnings"], list)

    def test_accepted_warnings_present_and_empty_by_default(self) -> None:
        # The new key exists on every payload and starts empty so JSON
        # consumers can rely on it without a presence check.
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertIn("accepted_warnings", payload)
        self.assertEqual(payload["accepted_warnings"], [])

    def test_event_date_section_is_slim(self) -> None:
        # The aggregator must not embed the full ``proposed_updates``
        # list — it slims to summary counts only.
        bulky_plan = dict(_OK_PLAN, proposed_updates=[
            {"event_id": i} for i in range(500)
        ])
        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                return_value=bulky_plan,
            ):
                payload = phc.run_health_check()
        section = payload["event_date_backfill_candidates"]
        self.assertNotIn("proposed_updates", section)


# ---------------------------------------------------------------------------
# Classification — repo_hygiene
# ---------------------------------------------------------------------------


class TestClassifyRepoHygiene(unittest.TestCase):
    def test_tracked_generated_paths_become_top_level_error(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "list_tracked_generated",
                return_value=["events.db", "backups/events-x.db"],
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any("repo_hygiene" in e for e in payload["errors"]),
            f"expected repo_hygiene error, got {payload['errors']}",
        )

    def test_repo_hygiene_section_carries_paths(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "list_tracked_generated",
                return_value=["events.db"],
            ):
                payload = phc.run_health_check()
        section = payload["repo_hygiene"]
        self.assertEqual(section["tracked_generated_count"], 1)
        self.assertEqual(section["tracked_generated_paths"], ["events.db"])
        self.assertFalse(section["ok"])


# ---------------------------------------------------------------------------
# Classification — backup_restore
# ---------------------------------------------------------------------------


class TestClassifyBackupRestore(unittest.TestCase):
    def test_failed_restore_check_lifts_errors(self) -> None:
        bad = dict(_OK_BACKUP_RESTORE,
                   ok=False,
                   errors=["no events-*.db backups found in backups"])
        with _patch_all_clean():
            with patch.object(
                phc, "restore_check",
                return_value=bad,
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("backup_restore",        joined)
        self.assertIn("no events-",            joined)

    def test_restore_check_warnings_lift_to_top_level(self) -> None:
        warn = dict(_OK_BACKUP_RESTORE,
                    warnings=["events table is empty (0 rows)"])
        with _patch_all_clean():
            with patch.object(
                phc, "restore_check",
                return_value=warn,
            ):
                payload = phc.run_health_check()
        # Warnings do not flip ok=False.
        self.assertTrue(payload["ok"])
        joined = " | ".join(payload["warnings"])
        self.assertIn("backup_restore",        joined)
        self.assertIn("events table is empty", joined)


# ---------------------------------------------------------------------------
# Classification — schema_preflight
# ---------------------------------------------------------------------------


class TestClassifySchemaPreflight(unittest.TestCase):
    def test_missing_database_is_error(self) -> None:
        bad = dict(_OK_SCHEMA_PREFLIGHT,
                   database_exists=False,
                   tables=[],
                   events_columns=[],
                   price_cache_present=False,
                   warnings=["database file does not exist: events.db"])
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                return_value=bad,
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("schema_preflight",        joined)
        self.assertIn("database file does not", joined)

    def test_missing_events_table_is_error(self) -> None:
        bad = dict(_OK_SCHEMA_PREFLIGHT,
                   tables=["price_cache"],
                   warnings=["events table missing from database"])
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                return_value=bad,
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("schema_preflight",   joined)
        self.assertIn("events table",       joined)

    def test_missing_price_cache_is_error(self) -> None:
        bad = dict(_OK_SCHEMA_PREFLIGHT,
                   tables=["events"],
                   price_cache_present=False)
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                return_value=bad,
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("schema_preflight", joined)
        self.assertIn("price_cache",       joined)

    def test_non_critical_warnings_are_warnings_not_errors(self) -> None:
        warn = dict(_OK_SCHEMA_PREFLIGHT,
                    warnings=["latest backup is 48h old (>24h threshold): x"])
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                return_value=warn,
            ):
                payload = phc.run_health_check()
        self.assertTrue(payload["ok"])
        joined = " | ".join(payload["warnings"])
        self.assertIn("schema_preflight",      joined)
        self.assertIn("latest backup is 48h",  joined)

    def test_critical_warning_does_not_double_count(self) -> None:
        # The "events table missing" string already lifts to errors via
        # our explicit table check; the upstream warning string must
        # not also leak into top-level warnings.
        bad = dict(_OK_SCHEMA_PREFLIGHT,
                   tables=["price_cache"],
                   warnings=["events table missing from database"])
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                return_value=bad,
            ):
                payload = phc.run_health_check()
        self.assertFalse(any(
            "events table missing" in w for w in payload["warnings"]
        ), f"duplicate in warnings: {payload['warnings']}")


# ---------------------------------------------------------------------------
# Classification — event_date_backfill_candidates
# ---------------------------------------------------------------------------


class TestClassifyEventDateBackfill(unittest.TestCase):
    def test_zero_candidates_produces_no_warning(self) -> None:
        # Live event-date backfill is complete; with zero candidates the
        # health check must stay quiet on both backfill sections.
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertTrue(payload["ok"])
        for w in payload["warnings"]:
            self.assertNotIn("event_date_backfill_candidates", w)
            self.assertNotIn("event_date_backfill_impact",     w)

    def test_nonzero_candidates_surface_as_warning_not_error(self) -> None:
        plan = dict(_OK_PLAN, total_candidates=25,
                    events_with_market_tickers=20,
                    ticker_rows_blocked=60,
                    projected_hydration_impact={
                        "candidate_events":               25,
                        "proposed_updates_count":         24,
                        "ticker_rows_blocked":            60,
                        "ticker_rows_unblocked_by_write": 56,
                        "remaining_ticker_rows_blocked":  4,
                        "skipped_counts": {"timestamp_unparseable": 1},
                    })
        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                return_value=plan,
            ):
                payload = phc.run_health_check()
        # Candidates are operator info, not a hard error.
        self.assertTrue(payload["ok"])
        joined = " | ".join(payload["warnings"])
        self.assertIn("event_date_backfill_candidates", joined)
        self.assertIn("25", joined)


# ---------------------------------------------------------------------------
# Classification — archive_consistency
# ---------------------------------------------------------------------------


class TestClassifyArchiveConsistency(unittest.TestCase):
    def test_clean_archive_yields_no_warnings_or_errors(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertTrue(payload["ok"])
        for msg in payload["warnings"] + payload["errors"]:
            self.assertNotIn("archive_consistency", msg)

    def test_malformed_market_tickers_json_is_error(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(malformed_market_tickers_json=3),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("archive_consistency", joined)
        self.assertIn("malformed market_tickers JSON", joined)
        self.assertIn("3", joined)

    def test_missing_headline_is_error(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(missing_headline=2),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("archive_consistency", joined)
        self.assertIn("missing headline",    joined)

    def test_missing_timestamp_is_error(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(missing_timestamp=4),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("archive_consistency", joined)
        self.assertIn("missing timestamp",   joined)

    def test_malformed_event_date_is_error(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(malformed_event_date=5),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        joined = " | ".join(payload["errors"])
        self.assertIn("archive_consistency",   joined)
        self.assertIn("malformed event_date",  joined)

    def test_duplicate_headline_event_date_clusters_is_warning(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=2,
                ),
            ):
                payload = phc.run_health_check()
        # Duplicates are a remediation flag, not a hard data-corruption
        # error — the rows themselves may individually parse fine.
        self.assertTrue(payload["ok"])
        joined = " | ".join(payload["warnings"])
        self.assertIn("archive_consistency",        joined)
        self.assertIn("duplicate",                  joined)
        self.assertNotIn("archive_consistency",
                         " | ".join(payload["errors"]))

    def test_missing_event_date_alone_does_not_error_or_warn(self) -> None:
        # The event_date_backfill_candidates section already covers
        # missing event_date.  archive_consistency surfaces the count in
        # its categories block but must not double-report it as an
        # error or warning.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(missing_event_date=7),
            ):
                payload = phc.run_health_check()
        self.assertTrue(payload["ok"])
        for msg in payload["warnings"] + payload["errors"]:
            self.assertNotIn("archive_consistency", msg)

    def test_default_threshold_zero_keeps_duplicate_cluster_warning(self) -> None:
        # No flag → strict default → cluster count > 0 stays a warning.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=2,
                ),
            ):
                payload = phc.run_health_check()
        joined = " | ".join(payload["warnings"])
        self.assertIn("archive_consistency",        joined)
        self.assertIn("duplicate",                  joined)
        self.assertEqual(payload["accepted_warnings"], [])

    def test_threshold_above_count_waives_warning_to_accepted(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=28,
                ),
            ):
                payload = phc.run_health_check(allow_duplicate_clusters=30)
        # No duplicate-cluster line in active warnings.
        for w in payload["warnings"]:
            self.assertNotIn("duplicate", w)
        # Waiver line carries section name + threshold + live count.
        joined = " | ".join(payload["accepted_warnings"])
        self.assertIn("archive_consistency", joined)
        self.assertIn("duplicate",           joined)
        self.assertIn("28",                  joined)
        self.assertIn("30",                  joined)
        self.assertTrue(payload["ok"])

    def test_threshold_at_count_waives_warning(self) -> None:
        # Boundary: count == threshold → waived.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=2,
                ),
            ):
                payload = phc.run_health_check(allow_duplicate_clusters=2)
        for w in payload["warnings"]:
            self.assertNotIn("duplicate", w)
        self.assertEqual(len(payload["accepted_warnings"]), 1)

    def test_threshold_below_count_keeps_warning_active(self) -> None:
        # Boundary: count > threshold → still a warning.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=5,
                ),
            ):
                payload = phc.run_health_check(allow_duplicate_clusters=3)
        joined = " | ".join(payload["warnings"])
        self.assertIn("duplicate", joined)
        self.assertEqual(payload["accepted_warnings"], [])

    def test_zero_count_with_threshold_emits_no_waiver(self) -> None:
        # No live duplicates → nothing to waive even with a generous
        # threshold; both lists stay empty for this section.
        with _patch_all_clean():
            payload = phc.run_health_check(allow_duplicate_clusters=99)
        self.assertEqual(payload["accepted_warnings"], [])
        for w in payload["warnings"]:
            self.assertNotIn("duplicate", w)

    def test_waiver_does_not_affect_other_archive_errors(self) -> None:
        # A high threshold for duplicate clusters must NOT mask
        # malformed-data errors from the same section.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=4,
                    malformed_event_date=2,
                ),
            ):
                payload = phc.run_health_check(allow_duplicate_clusters=10)
        # malformed_event_date stays as an error → ok=False.
        self.assertFalse(payload["ok"])
        joined_errors = " | ".join(payload["errors"])
        self.assertIn("malformed event_date", joined_errors)
        # Duplicate warning was waived.
        for w in payload["warnings"]:
            self.assertNotIn("duplicate", w)
        joined_accepted = " | ".join(payload["accepted_warnings"])
        self.assertIn("duplicate", joined_accepted)

    def test_section_carries_all_seven_category_counts(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(missing_headline=2,
                                           malformed_event_date=1),
            ):
                payload = phc.run_health_check()
        cats = payload["archive_consistency"]["categories"]
        self.assertEqual(set(cats.keys()), set(_ARCHIVE_CATEGORY_KEYS))
        self.assertEqual(cats["missing_headline"]["count"],     2)
        self.assertEqual(cats["malformed_event_date"]["count"], 1)
        self.assertEqual(cats["missing_timestamp"]["count"],    0)


# ---------------------------------------------------------------------------
# Classification — event_date_backfill_impact
# ---------------------------------------------------------------------------


class TestEventDateBackfillImpact(unittest.TestCase):
    def test_zero_impact_produces_no_warning_or_error(self) -> None:
        with _patch_all_clean():
            payload = phc.run_health_check()
        self.assertTrue(payload["ok"])
        for msg in payload["warnings"] + payload["errors"]:
            self.assertNotIn("event_date_backfill_impact", msg)

    def test_section_carries_three_documented_keys(self) -> None:
        plan = dict(_OK_PLAN, projected_hydration_impact={
            "candidate_events":               17,
            "proposed_updates_count":         15,
            "ticker_rows_blocked":            42,
            "ticker_rows_unblocked_by_write": 38,
            "remaining_ticker_rows_blocked":  4,
            "skipped_counts":                 {"timestamp_unparseable": 2},
        })
        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                return_value=plan,
            ):
                payload = phc.run_health_check()
        section = payload["event_date_backfill_impact"]
        self.assertEqual(section["candidate_events"],                17)
        self.assertEqual(section["proposed_updates"],                15)
        self.assertEqual(section["projected_ticker_rows_unblocked"], 38)

    def test_section_is_slim_with_no_proposed_updates_list(self) -> None:
        # Mirror ``test_event_date_section_is_slim`` — the impact
        # section must not embed the planner's full ``proposed_updates``
        # list and must report the three counts as integers.
        bulky = dict(_OK_PLAN,
                     proposed_updates=[{"event_id": i} for i in range(500)])
        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                return_value=bulky,
            ):
                payload = phc.run_health_check()
        section = payload["event_date_backfill_impact"]
        self.assertEqual(set(section.keys()), {
            "candidate_events",
            "proposed_updates",
            "projected_ticker_rows_unblocked",
        })
        self.assertIsInstance(section["proposed_updates"], int)

    def test_impact_uses_existing_plan_seam(self) -> None:
        # The impact section must share the existing
        # ``plan_event_date_backfill`` seam — patching only that seam
        # should drive both backfill sections without any new patch.
        seen_calls = []

        def fake_plan(*, db_path=None):
            seen_calls.append(db_path)
            return dict(_OK_PLAN)

        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                side_effect=fake_plan,
            ):
                phc.run_health_check()
        self.assertGreaterEqual(
            len(seen_calls), 2,
            "expected plan_event_date_backfill to drive both backfill sections",
        )


# ---------------------------------------------------------------------------
# Exception handling — one section blowing up must not poison the rest
# ---------------------------------------------------------------------------


class TestExceptionHandling(unittest.TestCase):
    def test_repo_hygiene_exception_captured_others_run(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "list_tracked_generated",
                side_effect=RuntimeError("git missing"),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any("repo_hygiene" in e and "git missing" in e
                for e in payload["errors"]),
            f"missing repo_hygiene exception in errors: {payload['errors']}",
        )
        # Other sections still ran.
        self.assertIsNotNone(payload["backup_restore"])
        self.assertIsNotNone(payload["schema_preflight"])
        self.assertIsNotNone(payload["event_date_backfill_candidates"])

    def test_backup_restore_exception_captured(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "restore_check",
                side_effect=OSError("disk full"),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        self.assertTrue(any(
            "backup_restore" in e and "disk full" in e
            for e in payload["errors"]
        ))

    def test_schema_preflight_exception_captured(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "schema_preflight_collect",
                side_effect=ValueError("bad path"),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        self.assertTrue(any(
            "schema_preflight" in e and "bad path" in e
            for e in payload["errors"]
        ))

    def test_event_date_backfill_exception_captured(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "plan_event_date_backfill",
                side_effect=KeyError("market_tickers"),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        # Both backfill sections share the seam, so both record the
        # failure and stay inert rather than partially populating.
        for key in ("event_date_backfill_candidates",
                    "event_date_backfill_impact"):
            self.assertTrue(any(
                key in e for e in payload["errors"]
            ), f"missing exception line for {key}: {payload['errors']}")

    def test_archive_consistency_exception_captured(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                side_effect=RuntimeError("db locked"),
            ):
                payload = phc.run_health_check()
        self.assertFalse(payload["ok"])
        self.assertTrue(any(
            "archive_consistency" in e and "db locked" in e
            for e in payload["errors"]
        ), f"missing archive_consistency exception: {payload['errors']}")
        # Other sections still ran.
        self.assertIsNotNone(payload["repo_hygiene"])
        self.assertIsNotNone(payload["event_date_backfill_impact"])


# ---------------------------------------------------------------------------
# Safety — never mutates events.db or backup files
# ---------------------------------------------------------------------------


class TestSafety(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="test_phc_")
        self._tmp = Path(self._td)
        self._sentinel_db = self._tmp / "events.db"
        self._sentinel_db.write_bytes(b"events.db must not change")
        self._sentinel_backup_dir = self._tmp / "backups"
        self._sentinel_backup_dir.mkdir()
        self._sentinel_backup = self._sentinel_backup_dir / "events-x.db"
        self._sentinel_backup.write_bytes(b"backup must not change")

    def tearDown(self) -> None:
        for p in (self._sentinel_db, self._sentinel_backup):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            self._sentinel_backup_dir.rmdir()
        except OSError:
            pass
        try:
            self._tmp.rmdir()
        except OSError:
            pass

    def test_run_does_not_modify_events_db_or_backups(self) -> None:
        before_db_bytes  = self._sentinel_db.read_bytes()
        before_db_mtime  = self._sentinel_db.stat().st_mtime
        before_bk_bytes  = self._sentinel_backup.read_bytes()
        before_bk_mtime  = self._sentinel_backup.stat().st_mtime

        with _patch_all_clean():
            phc.run_health_check(
                db_path=str(self._sentinel_db),
                backup_dir=str(self._sentinel_backup_dir),
            )

        self.assertEqual(self._sentinel_db.read_bytes(),     before_db_bytes)
        self.assertEqual(self._sentinel_db.stat().st_mtime,  before_db_mtime)
        self.assertEqual(self._sentinel_backup.read_bytes(), before_bk_bytes)
        self.assertEqual(self._sentinel_backup.stat().st_mtime,
                         before_bk_mtime)

    def test_backup_restore_invoked_with_cleanup_true(self) -> None:
        seen: dict = {}

        def fake_restore(**kwargs):
            seen.update(kwargs)
            return dict(_OK_BACKUP_RESTORE)

        with _patch_all_clean():
            with patch.object(phc, "restore_check", side_effect=fake_restore):
                phc.run_health_check()
        # Aggregator must always pass cleanup=True so no temp file is
        # left behind.
        self.assertIs(seen.get("cleanup"), True)
        self.assertIs(seen.get("use_latest"), True)


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(unittest.TestCase):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

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
            stack.enter_context(_patch_all_clean())
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
                        f"project_health_check must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "project_health_check must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            payload = phc.run_health_check()

        # Sanity: real composed result, not a fallback.
        self.assertTrue(payload["ok"])

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(phc, "app"))
        self.assertFalse(hasattr(phc, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard.  Earlier suites in the same process
        # (e.g. ``tests.test_diagnostics``) legitimately import
        # ``routes.diagnostics`` and ``api`` and leave them in
        # ``sys.modules``; a snapshot-style ``assertNotIn`` would then
        # fire on cached state the aggregator never touched.
        #
        # Two complementary signals catch a real regression instead:
        #   1. ``builtins.__import__`` is instrumented for the duration
        #      of ``run_health_check`` so any actual import statement
        #      targeting ``api`` / ``routes`` / ``routes.*`` (including
        #      ``from routes import diagnostics``) is recorded — this
        #      catches violations even when the target is already
        #      cached, because Python still routes through __import__.
        #   2. A ``sys.modules`` delta around the call catches the rare
        #      paths that bypass __import__ (e.g. ``importlib.util``).
        import builtins

        def _is_forbidden(name: str) -> bool:
            return (
                name == "api" or name.startswith("api.")
                or name == "routes" or name.startswith("routes.")
            )

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(
            name, globals=None, locals=None, fromlist=(), level=0,
        ):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            # ``from routes import diagnostics`` calls __import__
            # with name="routes" and fromlist=("diagnostics",); record
            # the resolved submodule so the guard doesn't slip through.
            if name == "routes":
                for sub in fromlist or ():
                    forbidden_imports.append(f"routes.{sub}")
            return real_import(name, globals, locals, fromlist, level)

        before_modules = set(sys.modules.keys())
        with _patch_all_clean():
            with patch("builtins.__import__", side_effect=tracing_import):
                phc.run_health_check()
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )

        self.assertEqual(
            forbidden_imports, [],
            "run_health_check performed forbidden imports during the "
            f"call: {forbidden_imports}",
        )
        self.assertEqual(
            newly_loaded_forbidden, [],
            "run_health_check loaded forbidden modules into "
            f"sys.modules: {newly_loaded_forbidden}",
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = phc.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_cli_all_clean_exits_zero(self) -> None:
        with _patch_all_clean():
            rc, _ = self._run_cli([])
        self.assertEqual(rc, 0)

    def test_cli_failure_exits_nonzero(self) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "list_tracked_generated",
                return_value=["events.db"],
            ):
                rc, _ = self._run_cli([])
        self.assertEqual(rc, 1)

    def test_cli_json_output_is_valid_json(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in (
            "ok",
            "repo_hygiene",
            "backup_restore",
            "schema_preflight",
            "event_date_backfill_candidates",
            "archive_consistency",
            "event_date_backfill_impact",
            "warnings",
            "errors",
            "accepted_warnings",
        ):
            self.assertIn(key, body, f"missing JSON key: {key}")

    def test_cli_allow_duplicate_clusters_waives_warning(self) -> None:
        # End-to-end CLI run: with the flag, the duplicate warning lands
        # in accepted_warnings and the run still exits zero.
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=28,
                ),
            ):
                rc, output = self._run_cli([
                    "--json", "--allow-duplicate-clusters", "30",
                ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["ok"])
        for w in body["warnings"]:
            self.assertNotIn("duplicate", w)
        joined = " | ".join(body["accepted_warnings"])
        self.assertIn("duplicate", joined)
        self.assertIn("28",        joined)
        self.assertIn("30",        joined)

    def test_cli_text_output_renders_accepted_warnings_when_present(
        self,
    ) -> None:
        with _patch_all_clean():
            with patch.object(
                phc, "compute_archive_consistency_local",
                return_value=_archive_with(
                    duplicate_headline_event_date_clusters=4,
                ),
            ):
                rc, output = self._run_cli([
                    "--allow-duplicate-clusters", "10",
                ])
        self.assertEqual(rc, 0)
        self.assertIn("Accepted warnings", output)

    def test_cli_text_output_summarises_each_section(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli([])
        self.assertEqual(rc, 0)
        for needle in (
            "repo_hygiene",
            "backup_restore",
            "schema_preflight",
            "event_date_backfill_candidates",
            "archive_consistency",
            "event_date_backfill_impact",
            "Warnings",
            "Errors",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_cli_forwards_paths_to_aggregator(self) -> None:
        seen: dict = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return {
                "ok": True,
                "repo_hygiene": _OK_REPO_HYGIENE,
                "backup_restore": _OK_BACKUP_RESTORE,
                "schema_preflight": _OK_SCHEMA_PREFLIGHT,
                "event_date_backfill_candidates": _OK_PLAN,
                "archive_consistency": {
                    "categories": _ok_archive_consistency(),
                },
                "event_date_backfill_impact": {
                    "candidate_events": 0,
                    "proposed_updates": 0,
                    "projected_ticker_rows_unblocked": 0,
                },
                "warnings": [],
                "errors": [],
                "accepted_warnings": [],
            }

        with patch.object(phc, "run_health_check", side_effect=fake_run):
            rc, _ = self._run_cli([
                "--repo-path", "/tmp/repo",
                "--db-path",   "/tmp/x.db",
                "--backup-dir", "/tmp/bks",
                "--allow-duplicate-clusters", "7",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["repo_path"],                "/tmp/repo")
        self.assertEqual(seen["db_path"],                  "/tmp/x.db")
        self.assertEqual(seen["backup_dir"],               "/tmp/bks")
        self.assertEqual(seen["allow_duplicate_clusters"], 7)

    def test_cli_default_threshold_is_zero(self) -> None:
        seen: dict = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return {
                "ok": True,
                "repo_hygiene": _OK_REPO_HYGIENE,
                "backup_restore": _OK_BACKUP_RESTORE,
                "schema_preflight": _OK_SCHEMA_PREFLIGHT,
                "event_date_backfill_candidates": _OK_PLAN,
                "archive_consistency": {
                    "categories": _ok_archive_consistency(),
                },
                "event_date_backfill_impact": {
                    "candidate_events": 0,
                    "proposed_updates": 0,
                    "projected_ticker_rows_unblocked": 0,
                },
                "warnings": [],
                "errors": [],
                "accepted_warnings": [],
            }

        with patch.object(phc, "run_health_check", side_effect=fake_run):
            rc, _ = self._run_cli([])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["allow_duplicate_clusters"], 0)


if __name__ == "__main__":
    unittest.main()

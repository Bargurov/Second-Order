"""Tests for ``scripts/section_c_regression_smoke.py``.

Pin the contract:

* Read-only smoke.  No DB writes, no provider, no LLM, no FastAPI.
  The smoke's module-level import surface stays stdlib-only; the
  three diagnostic seams and the weekly canonicalization helper are
  lazy-imported behind patchable seams.
* Output dict has EXACTLY these 10 keys::

    ok, daily_summary, weekly_summary, still_moving_summary,
    weekly_duplicate_check, still_moving_gate_check,
    daily_mechanism_check, regressions, warnings, errors

* Required checks:
    - Weekly canonicalization reduces a 3-card duplicate cluster to
      one canonical card on a synthetic input.
    - The canonical card carries ``duplicate_count >= 1`` and a
      sorted ``grouped_event_ids`` list that names every cluster
      member.
    - Daily ``candidates_checked`` count is unchanged by the Weekly
      canonicalization step (the Weekly step never touches Daily).
    - Still Moving does not surface candidates failing required
      gates once Task 1 lands (``task1_landed=True`` and zero
      failures).
    - Missing ``mechanism_family`` in the Daily inbox surfaces as a
      schema warning OR a non-zero ``missing_mechanism_cases``
      bucket — never silently hidden.
* Conservative wording — banned tokens are absent from any prose the
  smoke emits in ``regressions`` / ``warnings`` / ``errors`` /
  per-block ``notes`` lists.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_regression_smoke as cli  # noqa: E402

# Shared subprocess import-isolation helper.
sys.path.insert(0, os.path.dirname(__file__))
from _import_isolation_check import assert_module_import_does_not_leak  # noqa: E402,I100


_REQUIRED_TOP_KEYS = (
    "ok",
    "daily_summary",
    "weekly_summary",
    "still_moving_summary",
    "weekly_duplicate_check",
    "still_moving_gate_check",
    "daily_mechanism_check",
    "regressions",
    "warnings",
    "errors",
)


_DAILY_SUMMARY_KEYS = (
    "candidates_checked",
    "accepted_like",
    "junk",
    "raw_legal",
    "off_topic",
    "vague",
    "duplicates",
    "missing_mechanism",
    "warnings",
)


_WEEKLY_SUMMARY_KEYS = (
    "candidates_checked",
    "duplicate_groups",
    "repeated_headline_groups",
    "repeated_date_ticker_groups",
    "warnings",
)


_STILL_MOVING_SUMMARY_KEYS = (
    "candidates_checked",
    "defensible",
    "weak_ticker",
    "bad_proxy",
    "missing_price_cache",
    "no_persistence",
    "duplicate_narrative",
    "warnings",
)


_WEEKLY_DUPLICATE_CHECK_KEYS = (
    "groups_reduced",
    "duplicate_count_preserved",
    "grouped_event_ids_preserved",
    "synthetic_input_size",
    "synthetic_output_size",
    "notes",
)


_STILL_MOVING_GATE_CHECK_KEYS = (
    "candidates_failing_required_gates",
    "gate_failures_by_axis",
    "task1_landed",
    "notes",
)


_DAILY_MECHANISM_CHECK_KEYS = (
    "mechanism_family_warning_in_daily",
    "missing_mechanism_cases",
    "surfaced_as_limitation",
    "notes",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "guaranteed",
    "automatically",
    "alpha generated",
    "correct ticker",
    "definitely",
    "causes",
)


# ---------------------------------------------------------------------------
# Synthetic diagnostic payloads
# ---------------------------------------------------------------------------


def _daily_report(
    *,
    candidates_checked:   int = 0,
    accepted_like:        int = 0,
    junk:                 int = 0,
    raw_legal:            int = 0,
    off_topic:            int = 0,
    vague:                int = 0,
    duplicates:           int = 0,
    missing_mechanism:    int = 0,
    warnings:             list[str] | None = None,
    errors:               list[str] | None = None,
) -> dict[str, Any]:
    """Mirror the Daily diagnostic's envelope shape."""
    def _pad(n: int, tag: str) -> list[dict[str, Any]]:
        return [
            {
                "event_id":               i,
                "headline":               f"{tag} headline {i}",
                "event_date":             "2026-05-08",
                "primary_ticker":         "AAA",
                "mechanism_family":       "supply_shock",
                "market_relevance_score": 0.5,
                "diagnostic_tags":        [],
                "inclusion_reason":       None,
                "exclusion_reason":       None,
            }
            for i in range(n)
        ]
    return {
        "ok":                              not (errors or []),
        "candidates_checked":              candidates_checked,
        "accepted_like_candidates":        _pad(accepted_like, "ok"),
        "junk_headlines":                  _pad(junk, "junk"),
        "raw_legal_text_cases":            _pad(raw_legal, "legal"),
        "off_topic_cases":                 _pad(off_topic, "off"),
        "vague_cases":                     _pad(vague, "vague"),
        "duplicate_cases":                 _pad(duplicates, "dup"),
        "missing_mechanism_cases":         _pad(missing_mechanism, "no_mech"),
        "recommended_daily_filter_rules":  [],
        "warnings":                        list(warnings or []),
        "errors":                          list(errors or []),
    }


def _weekly_report(
    *,
    candidates_checked: int = 0,
    duplicate_groups:   int = 0,
    warnings:           list[str] | None = None,
    errors:             list[str] | None = None,
) -> dict[str, Any]:
    """Mirror the Weekly diagnostic's envelope shape."""
    groups = [
        {
            "duplicate_group_id":          f"headline_{i:03d}",
            "event_ids":                   [10 * (i + 1), 10 * (i + 1) + 1],
            "headlines":                   ["A", "A and more"],
            "dates":                       ["2026-05-08"],
            "tickers":                     [],
            "mechanism_families":          [],
            "suggested_canonical_event_id": 10 * (i + 1),
            "reason":                       "headline",
        }
        for i in range(duplicate_groups)
    ]
    return {
        "ok":                            not (errors or []),
        "candidates_checked":            candidates_checked,
        "duplicate_groups":              groups,
        "repeated_date_ticker_groups":   [],
        "repeated_headline_groups":      groups,
        "mechanism_theme_candidates":    [],
        "canonical_headline_suggestions":[],
        "recommended_weekly_filter_rules":[],
        "window":                        {"reference_date": "2026-05-12",
                                          "window_days":    7,
                                          "window_start":   "2026-05-05"},
        "warnings":                      list(warnings or []),
        "errors":                        list(errors or []),
    }


def _still_moving_report(
    *,
    candidates:        list[dict[str, Any]] | None = None,
    warnings:          list[str] | None = None,
    errors:            list[str] | None = None,
) -> dict[str, Any]:
    """Mirror the Still Moving diagnostic's envelope shape."""
    cands = list(candidates or [])
    # Aggregate counters from the per-candidate tags.
    weak = sum(1 for c in cands if "weak_ticker" in (c.get("diagnostic_tags") or []))
    bad  = sum(1 for c in cands if "bad_proxy" in (c.get("diagnostic_tags") or []))
    mpc  = sum(1 for c in cands if "missing_price_cache" in (c.get("diagnostic_tags") or []))
    nop  = sum(1 for c in cands if "no_persistence_signal" in (c.get("diagnostic_tags") or []))
    dup  = sum(1 for c in cands if "duplicate_narrative" in (c.get("diagnostic_tags") or []))
    defensible = sum(1 for c in cands if not (c.get("diagnostic_tags") or []))
    return {
        "ok":                                    not (errors or []),
        "candidates_checked":                    len(cands),
        "defensible_candidates":                 defensible,
        "weak_ticker_cases":                     weak,
        "bad_proxy_cases":                       bad,
        "missing_price_cache_cases":             mpc,
        "no_persistence_cases":                  nop,
        "duplicate_narrative_cases":             dup,
        "recommended_still_moving_filter_rules": [],
        "warnings":                              list(warnings or []),
        "errors":                                list(errors or []),
        "candidates":                            cands,
    }


def _sm_candidate(
    *,
    event_id: int,
    tags:     list[str] | None = None,
) -> dict[str, Any]:
    return {
        "event_id":                              event_id,
        "headline":                              f"Curated event {event_id}",
        "event_date":                            "2026-04-08",
        "primary_ticker":                        "XOM",
        "benchmark_ticker":                      "XLE",
        "mechanism_family":                      "supply_shock",
        "ticker_quality":                        "ok",
        "price_cache_available":                 True,
        "benchmark_adjusted_evidence_available": True,
        "persistence_signal":                    "active",
        "diagnostic_tags":                       list(tags or []),
        "inclusion_reason":                      "ok",
        "exclusion_reason":                      "",
    }


# ---------------------------------------------------------------------------
# Seam-patching helpers
# ---------------------------------------------------------------------------


class _PatchStack:
    def __init__(self, patches):
        self._patches = list(patches)

    def __enter__(self):
        self._entered = [p.__enter__() for p in self._patches]
        return self._entered

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.__exit__(*args)


def _patch_all(
    *,
    daily:               dict[str, Any] | None = None,
    weekly:              dict[str, Any] | None = None,
    still_moving:        dict[str, Any] | None = None,
    collapsed:           list[dict[str, Any]] | None = None,
):
    """Patch the four seams with deterministic synthetic payloads."""
    def _daily_seam(*, input_path):  # noqa: ANN001
        return daily if daily is not None else _daily_report()

    def _weekly_seam(*, db_path, window_days, reference_date):  # noqa: ANN001
        return weekly if weekly is not None else _weekly_report()

    def _sm_seam(
        *,
        yaml_path, db_path, evidence_artifact_path,
        persistence_signals_path,
    ):  # noqa: ANN001
        return (still_moving if still_moving is not None
                else _still_moving_report())

    def _collapse_seam(cards):  # noqa: ANN001
        if collapsed is not None:
            return list(collapsed)
        # Default: a faithful canonicalization of the smoke's synthetic
        # input — collapse the 3-card duplicate cluster down to one
        # canonical card with the required metadata.
        return [
            {
                "event_id":          11,
                "headline":          (
                    "Turkey lira weakens as reserves slip further"
                ),
                "event_date":        "2026-05-08",
                "primary_ticker":    "TUR",
                "duplicate_count":   2,
                "grouped_event_ids": [11, 12, 13],
            },
            {
                "event_id":         20,
                "headline":         "Fed minutes show divided committee",
                "event_date":       "2026-05-09",
                "primary_ticker":   "SPY",
            },
        ]

    return _PatchStack([
        patch.object(cli, "_run_daily",         side_effect=_daily_seam),
        patch.object(cli, "_run_weekly",        side_effect=_weekly_seam),
        patch.object(cli, "_run_still_moving",  side_effect=_sm_seam),
        patch.object(cli, "_collapse_weekly_duplicates",
                     side_effect=_collapse_seam),
    ])


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_top_level_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_daily_summary_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["daily_summary"].keys()), set(_DAILY_SUMMARY_KEYS),
        )

    def test_weekly_summary_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["weekly_summary"].keys()),
            set(_WEEKLY_SUMMARY_KEYS),
        )

    def test_still_moving_summary_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["still_moving_summary"].keys()),
            set(_STILL_MOVING_SUMMARY_KEYS),
        )

    def test_weekly_duplicate_check_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["weekly_duplicate_check"].keys()),
            set(_WEEKLY_DUPLICATE_CHECK_KEYS),
        )

    def test_still_moving_gate_check_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["still_moving_gate_check"].keys()),
            set(_STILL_MOVING_GATE_CHECK_KEYS),
        )

    def test_daily_mechanism_check_keys(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            set(report["daily_mechanism_check"].keys()),
            set(_DAILY_MECHANISM_CHECK_KEYS),
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_clean_inputs_pass_with_ok_true(self) -> None:
        # Daily surfaces missing-mechanism via a schema warning, so the
        # limitation is surfaced.  Still Moving has zero failing
        # candidates, so task1_landed=True.  Weekly canonicalization
        # works as designed.
        daily = _daily_report(
            candidates_checked=5,
            accepted_like=5,
            warnings=[
                "inbox entries do not carry a mechanism_family field; "
                "missing_mechanism_cases is reported as zero for this run"
            ],
        )
        sm = _still_moving_report(candidates=[_sm_candidate(event_id=1)])
        with _patch_all(daily=daily, still_moving=sm):
            report = cli.run_section_c_regression_smoke()
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertEqual(report["regressions"], [])
        self.assertEqual(report["errors"], [])
        self.assertTrue(
            report["weekly_duplicate_check"]["groups_reduced"]
        )
        self.assertTrue(
            report["weekly_duplicate_check"]["duplicate_count_preserved"]
        )
        self.assertTrue(
            report["weekly_duplicate_check"]["grouped_event_ids_preserved"]
        )
        self.assertEqual(
            report["still_moving_gate_check"][
                "candidates_failing_required_gates"
            ], 0,
        )
        self.assertTrue(report["still_moving_gate_check"]["task1_landed"])
        self.assertTrue(
            report["daily_mechanism_check"]["surfaced_as_limitation"]
        )


# ---------------------------------------------------------------------------
# Required check 1+2: Weekly duplicate canonicalization
# ---------------------------------------------------------------------------


class TestWeeklyDuplicateCheck(unittest.TestCase):
    def test_groups_reduced_when_canonicalization_collapses(self) -> None:
        # Default seam collapses 3 duplicates + 1 singleton → 2 cards.
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        wdc = report["weekly_duplicate_check"]
        self.assertEqual(wdc["synthetic_input_size"], 4)
        self.assertEqual(wdc["synthetic_output_size"], 2)
        self.assertTrue(wdc["groups_reduced"])

    def test_duplicate_count_and_grouped_event_ids_preserved(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        wdc = report["weekly_duplicate_check"]
        self.assertTrue(wdc["duplicate_count_preserved"])
        self.assertTrue(wdc["grouped_event_ids_preserved"])

    def test_no_reduction_triggers_regression(self) -> None:
        # Canonicalizer returns the input unchanged — same number of
        # cards out as in.  The smoke must flag this as a regression.
        passthrough = cli._build_weekly_synthetic_input()
        with _patch_all(collapsed=passthrough):
            report = cli.run_section_c_regression_smoke()
        self.assertFalse(
            report["weekly_duplicate_check"]["groups_reduced"]
        )
        joined = " | ".join(report["regressions"]).lower()
        self.assertIn("canonicalization", joined)
        self.assertFalse(report["ok"])

    def test_missing_duplicate_count_triggers_regression(self) -> None:
        # Canonicalizer collapses correctly but forgets to attach the
        # duplicate_count metadata field.  The smoke must flag this.
        collapsed = [
            {
                "event_id":          11,
                "headline":          (
                    "Turkey lira weakens as reserves slip further"
                ),
                "event_date":        "2026-05-08",
                "primary_ticker":    "TUR",
                # duplicate_count missing
                "grouped_event_ids": [11, 12, 13],
            },
            {
                "event_id":         20,
                "headline":         "Fed minutes show divided committee",
                "event_date":       "2026-05-09",
                "primary_ticker":   "SPY",
            },
        ]
        with _patch_all(collapsed=collapsed):
            report = cli.run_section_c_regression_smoke()
        self.assertFalse(
            report["weekly_duplicate_check"]["duplicate_count_preserved"]
        )
        joined = " | ".join(report["regressions"]).lower()
        self.assertIn("duplicate_count", joined)

    def test_missing_grouped_event_ids_triggers_regression(self) -> None:
        collapsed = [
            {
                "event_id":          11,
                "headline":          (
                    "Turkey lira weakens as reserves slip further"
                ),
                "event_date":        "2026-05-08",
                "primary_ticker":    "TUR",
                "duplicate_count":   2,
                # grouped_event_ids missing
            },
            {
                "event_id":         20,
                "headline":         "Fed minutes show divided committee",
                "event_date":       "2026-05-09",
                "primary_ticker":   "SPY",
            },
        ]
        with _patch_all(collapsed=collapsed):
            report = cli.run_section_c_regression_smoke()
        self.assertFalse(
            report["weekly_duplicate_check"]["grouped_event_ids_preserved"]
        )
        joined = " | ".join(report["regressions"]).lower()
        self.assertIn("grouped_event_ids", joined)

    def test_helper_raise_is_surfaced_as_error(self) -> None:
        with _PatchStack([
            patch.object(
                cli, "_collapse_weekly_duplicates",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(cli, "_run_daily",
                         return_value=_daily_report()),
            patch.object(cli, "_run_weekly",
                         return_value=_weekly_report()),
            patch.object(cli, "_run_still_moving",
                         return_value=_still_moving_report()),
        ]):
            report = cli.run_section_c_regression_smoke()
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("weekly canonicalization", joined)
        self.assertFalse(report["ok"])


# ---------------------------------------------------------------------------
# Required check 3: Daily candidate count unchanged by Weekly step
# ---------------------------------------------------------------------------


class TestDailyCountUnchangedByWeeklyStep(unittest.TestCase):
    def test_daily_count_carried_through_unchanged(self) -> None:
        # Daily reports 17 candidates checked.  After the Weekly
        # canonicalization step runs on a synthetic in-memory input,
        # the smoke must still report 17 in daily_summary — the
        # Weekly step does not touch the Daily inbox.
        daily = _daily_report(
            candidates_checked=17,
            accepted_like=10,
            junk=3,
            warnings=[
                "inbox entries do not carry a mechanism_family field; "
                "missing_mechanism_cases is reported as zero for this run"
            ],
        )
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        self.assertEqual(
            report["daily_summary"]["candidates_checked"], 17,
        )

    def test_seam_called_with_input_path(self) -> None:
        # The Daily seam must be invoked exactly once with the
        # configured input path.
        with patch.object(
            cli, "_run_daily",
            return_value=_daily_report(),
        ) as daily_mock, patch.object(
            cli, "_run_weekly",
            return_value=_weekly_report(),
        ), patch.object(
            cli, "_run_still_moving",
            return_value=_still_moving_report(),
        ), patch.object(
            cli, "_collapse_weekly_duplicates",
            return_value=cli._build_weekly_synthetic_input(),
        ):
            cli.run_section_c_regression_smoke(
                daily_input_path="custom_inbox.json",
            )
        daily_mock.assert_called_once_with(input_path="custom_inbox.json")


# ---------------------------------------------------------------------------
# Required check 4: Still Moving gate check
# ---------------------------------------------------------------------------


class TestStillMovingGateCheck(unittest.TestCase):
    def test_zero_failures_marks_task1_landed_true(self) -> None:
        sm = _still_moving_report(candidates=[
            _sm_candidate(event_id=1),
            _sm_candidate(event_id=2),
        ])
        with _patch_all(still_moving=sm):
            report = cli.run_section_c_regression_smoke()
        gate = report["still_moving_gate_check"]
        self.assertEqual(gate["candidates_failing_required_gates"], 0)
        self.assertTrue(gate["task1_landed"])
        # No regression flagged on the zero-failure path.
        joined = " | ".join(report["regressions"]).lower()
        self.assertNotIn("still moving", joined)

    def test_empty_curated_input_does_not_claim_task1_landed(self) -> None:
        # An empty curated YAML reports zero failures trivially.  The
        # smoke must NOT then claim Task 1 has landed — there is no
        # evidence either way from an empty input.
        sm = _still_moving_report(candidates=[])
        with _patch_all(still_moving=sm):
            report = cli.run_section_c_regression_smoke()
        gate = report["still_moving_gate_check"]
        self.assertEqual(gate["candidates_failing_required_gates"], 0)
        self.assertFalse(gate["task1_landed"])
        joined = " | ".join(gate["notes"]).lower()
        self.assertIn("no still moving candidates", joined)

    def test_failures_marks_task1_landed_false_and_warns(self) -> None:
        sm = _still_moving_report(candidates=[
            _sm_candidate(event_id=1, tags=["weak_ticker", "bad_proxy"]),
            _sm_candidate(event_id=2, tags=["missing_price_cache"]),
            _sm_candidate(event_id=3),
        ])
        with _patch_all(still_moving=sm):
            report = cli.run_section_c_regression_smoke()
        gate = report["still_moving_gate_check"]
        # Two distinct candidates fail at least one required gate.
        self.assertEqual(gate["candidates_failing_required_gates"], 2)
        self.assertFalse(gate["task1_landed"])
        # The per-axis tally must distinguish weak_ticker from
        # missing_price_cache.
        self.assertEqual(gate["gate_failures_by_axis"]["weak_ticker"], 1)
        self.assertEqual(
            gate["gate_failures_by_axis"]["missing_price_cache"], 1,
        )
        # Surface as a warning, NOT a regression, until Task 1 lands.
        joined_warn = " | ".join(report["warnings"]).lower()
        self.assertIn("still moving", joined_warn)
        joined_regs = " | ".join(report["regressions"]).lower()
        self.assertNotIn("still moving", joined_regs)


# ---------------------------------------------------------------------------
# Required check 5: Daily mechanism limitation surfaced, not hidden
# ---------------------------------------------------------------------------


class TestDailyMechanismCheck(unittest.TestCase):
    def test_schema_warning_path_surfaces_limitation(self) -> None:
        daily = _daily_report(
            candidates_checked=4,
            accepted_like=4,
            warnings=[
                "inbox entries do not carry a mechanism_family field; "
                "missing_mechanism_cases is reported as zero for this run"
            ],
        )
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        dmc = report["daily_mechanism_check"]
        self.assertTrue(dmc["mechanism_family_warning_in_daily"])
        self.assertEqual(dmc["missing_mechanism_cases"], 0)
        self.assertTrue(dmc["surfaced_as_limitation"])

    def test_bucketed_cases_path_surfaces_limitation(self) -> None:
        daily = _daily_report(
            candidates_checked=4,
            accepted_like=2,
            missing_mechanism=2,
        )
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        dmc = report["daily_mechanism_check"]
        self.assertFalse(dmc["mechanism_family_warning_in_daily"])
        self.assertEqual(dmc["missing_mechanism_cases"], 2)
        self.assertTrue(dmc["surfaced_as_limitation"])

    def test_hidden_limitation_flagged_as_regression(self) -> None:
        # Non-empty inbox, no warning, zero bucketed cases — the
        # limitation is hidden.  The smoke must flag a regression.
        daily = _daily_report(
            candidates_checked=4,
            accepted_like=4,
        )
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        dmc = report["daily_mechanism_check"]
        self.assertFalse(dmc["surfaced_as_limitation"])
        joined = " | ".join(report["regressions"]).lower()
        self.assertIn("mechanism", joined)
        self.assertFalse(report["ok"])

    def test_empty_inbox_does_not_flag_regression(self) -> None:
        # Empty inbox: there is nothing to surface; the absence of
        # warnings is not a regression.
        daily = _daily_report(candidates_checked=0)
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        self.assertTrue(
            report["daily_mechanism_check"]["surfaced_as_limitation"]
        )
        joined = " | ".join(report["regressions"]).lower()
        self.assertNotIn("mechanism", joined)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _collect_prose(self, report: dict[str, Any]) -> list[str]:
        out: list[str] = []
        out.extend(report.get("regressions") or [])
        out.extend(report.get("warnings") or [])
        out.extend(report.get("errors") or [])
        for block_key in (
            "weekly_duplicate_check",
            "still_moving_gate_check",
            "daily_mechanism_check",
        ):
            block = report.get(block_key) or {}
            out.extend(block.get("notes") or [])
        return [s for s in out if isinstance(s, str)]

    def test_no_banned_tokens_on_happy_path(self) -> None:
        with _patch_all():
            report = cli.run_section_c_regression_smoke()
        prose = " ".join(self._collect_prose(report)).lower()
        for banned in _BANNED_WORDS:
            self.assertNotIn(
                banned, prose,
                f"banned token {banned!r} surfaced in prose: {prose!r}",
            )

    def test_no_banned_tokens_under_failure(self) -> None:
        # Drive the smoke into the failure paths so the regression
        # prose is exercised.
        with _patch_all(
            daily=_daily_report(candidates_checked=4, accepted_like=4),
            collapsed=cli._build_weekly_synthetic_input(),
        ):
            report = cli.run_section_c_regression_smoke()
        prose = " ".join(self._collect_prose(report)).lower()
        for banned in _BANNED_WORDS:
            self.assertNotIn(
                banned, prose,
                f"banned token {banned!r} surfaced in failure prose: "
                f"{prose!r}",
            )


# ---------------------------------------------------------------------------
# Required check 6: no provider / LLM / FastAPI surface in the import
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    """Pin that importing the smoke does not pull in any banned module.

    The smoke lazy-imports every diagnostic seam, so a bare ``import
    scripts.section_c_regression_smoke`` in a fresh Python subprocess
    must not load ``api`` / ``yfinance`` / ``fastapi`` / ``routes.*``
    / ``market_data`` / ``news_relevance`` into ``sys.modules``.
    """

    def test_module_import_does_not_leak_paid_surfaces(self) -> None:
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.section_c_regression_smoke",
            blocked=(
                "yfinance",
                "fastapi",
                "api",
                "market_data",
                "news_relevance",
            ),
            blocked_starts_with=("routes.",),
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_main_emits_valid_json(self) -> None:
        with _patch_all():
            buf = io.StringIO()
            rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))

    def test_text_main_renders_compact_summary(self) -> None:
        with _patch_all():
            buf = io.StringIO()
            rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        self.assertIn("Section C", buf.getvalue())
        self.assertIn("weekly_duplicate_check", buf.getvalue())

    def test_main_returns_nonzero_on_regression(self) -> None:
        # Force a regression via the canonicalizer pass-through.
        with _patch_all(
            collapsed=cli._build_weekly_synthetic_input(),
        ):
            buf = io.StringIO()
            rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 1)

    def test_output_path_writes_json_envelope(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_regression_smoke_{uuid.uuid4().hex}.json",
        )
        try:
            with _patch_all():
                report = cli.run_section_c_regression_smoke(
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))
            self.assertEqual(payload["ok"], report["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# Cross-cutting: diagnostic errors propagate
# ---------------------------------------------------------------------------


class TestErrorPropagation(unittest.TestCase):
    def test_daily_errors_propagate_into_envelope(self) -> None:
        daily = _daily_report(
            candidates_checked=0,
            errors=["inbox path does not exist on disk: 'missing.json'"],
        )
        with _patch_all(daily=daily):
            report = cli.run_section_c_regression_smoke()
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("daily", joined)
        self.assertIn("inbox", joined)
        self.assertFalse(report["ok"])

    def test_daily_seam_raise_is_surfaced(self) -> None:
        with _PatchStack([
            patch.object(cli, "_run_daily",
                         side_effect=RuntimeError("daily-bad")),
            patch.object(cli, "_run_weekly",
                         return_value=_weekly_report()),
            patch.object(cli, "_run_still_moving",
                         return_value=_still_moving_report()),
            patch.object(
                cli, "_collapse_weekly_duplicates",
                return_value=cli._build_weekly_synthetic_input(),
            ),
        ]):
            report = cli.run_section_c_regression_smoke()
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("daily diagnostic raised", joined)
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()

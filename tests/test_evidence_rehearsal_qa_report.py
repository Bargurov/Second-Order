"""Tests for ``scripts/evidence_rehearsal_qa_report.py``.

Pin the contract:

* Read-only — never mutates the artifacts on disk.  No DB, no provider,
  no yfinance, no LLM, no FastAPI.
* Output dict has EXACTLY these 8 keys::

    ok, current_evidence_summary, hard_questions, suggested_answers,
    weak_points, must_not_say, warnings, errors

* The eight required questions are all present, in order, with stable
  IDs.  Every ``hard_questions[*].id`` has a matching answer in
  ``suggested_answers``.
* Conservative wording: banned tokens absent.  The literal pipeline
  label ``validated_raw_only`` is the only place the substring
  ``validated`` is allowed.
* ``current_evidence_summary`` is computed from the artifacts at run
  time (12 events / 31 records / 0 FDR / 4 raw-p / 20-of-28 excluded
  on the captured live truth).
* The Q2 answer explicitly states that ``validated_raw_only`` does NOT
  mean the record cleared the FDR bar.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import evidence_rehearsal_qa_report as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "current_evidence_summary",
    "hard_questions",
    "suggested_answers",
    "weak_points",
    "must_not_say",
    "warnings",
    "errors",
)


# Banned tokens for the rehearsal report.  ``validated_raw_only`` is
# the literal pipeline label cited verbatim — strip that substring
# before scanning so the carve-out is testable in one place.
_BANNED_WORDS = (
    "proof",
    "proven",
    "automatically",
    "alpha generated",
    "correct ticker",
    "guaranteed",
)


_REQUIRED_QUESTION_IDS = (
    "q_zero_fdr",
    "q_validated_raw_only",
    "q_events_vs_records",
    "q_manual_exclusions",
    "q_benchmark_sensitivity",
    "q_xle_benchmark_status",
    "q_next_evidence",
    "q_what_not_to_claim",
)


_REQUIRED_QUESTION_SUBSTRINGS = {
    "q_zero_fdr":              "0 FDR-significant",
    "q_validated_raw_only":    "validated_raw_only",
    "q_events_vs_records":     "event-sources and records",
    "q_manual_exclusions":     "20 of 28",
    "q_benchmark_sensitivity": "benchmark sensitivity test",
    "q_xle_benchmark_status":  "what happened with xle benchmark sensitivity",
    "q_next_evidence":         "improve the evidence",
    "q_what_not_to_claim":     "should not be claimed",
}


# ---------------------------------------------------------------------------
# Fixture artifact bundle
# ---------------------------------------------------------------------------


def _fixture_bundle() -> dict[str, Any]:
    """Synthetic 5-artifact bundle reflecting the live evidence
    captured on 2026-05-12 (12 events / 31 records / 0 FDR / 4 raw-p /
    20-of-28 short-horizon exclusions).  Used by the seam-patching
    tests so they do not depend on the on-disk artifacts."""
    return {
        "freeze": {
            "cohort_summary": {
                "events_evaluated":      12,
                "fdr_significant_count": 0,
                "raw_p_candidate_count": 4,
                "total_records":         31,
                "horizons_covered":      [1, 5, 20],
                "mechanism_families_covered": [
                    "bank_regulatory_capital_relief",
                    "chokepoint_relief",
                    "commodity_squeeze",
                    "opec_coordination_breakdown",
                    "refined_product_supply_disruption",
                    "supply_shock",
                ],
            },
            "verdict_counts": {
                "fdr_significant":      0,
                "inconclusive_fdr":     27,
                "insufficient":         0,
                "raw_p_only_candidate": 4,
            },
            "review_completion": [
                {
                    "name": "top10",
                    "accepted_count": 4, "excluded_count": 6,
                    "worksheet_total_rows": 10,
                    "events_evaluated": 4, "records_count": 8,
                    "significant_count": 0, "pending_count": 0,
                },
                {
                    "name": "next10",
                    "accepted_count": 4, "excluded_count": 6,
                    "worksheet_total_rows": 10,
                    "events_evaluated": 4, "records_count": 8,
                    "significant_count": 0, "pending_count": 0,
                },
                {
                    "name": "final8",
                    "accepted_count": 0, "excluded_count": 8,
                    "worksheet_total_rows": 8,
                    "events_evaluated": 0, "records_count": 0,
                    "significant_count": 0, "pending_count": 0,
                },
            ],
            "duplicate_event_ids": [30],
            "benchmark_sensitivity_status": {
                "status":                   "comparison_uncomputable",
                "blocked_events":           [],
                "required_dates":           [],
                "local_backfill_available": False,
                "online_backfill_required": False,
                "limitations": [
                    "comparison artifact is present, but no event has "
                    "both SPY and XLE results computed; benchmark "
                    "sensitivity is not meaningfully complete and no "
                    "SPY-vs-XLE inference is supported."
                ],
                "comparison_summary": {
                    "ok":             True,
                    "checked_events": 2,
                    "blocked_count":  0,
                    "comparisons": [
                        {
                            "event_id":               60,
                            "event_date":             "2026-04-08",
                            "primary_ticker":         "XOM",
                            "spy_result":             None,
                            "xle_result":             None,
                            "changed_interpretation": False,
                            "note": (
                                "Descriptive sensitivity uncomputable "
                                "on one side; interpretation "
                                "comparison not made."
                            ),
                        },
                        {
                            "event_id":               73,
                            "event_date":             "2026-04-06",
                            "primary_ticker":         "XOM",
                            "spy_result":             None,
                            "xle_result":             None,
                            "changed_interpretation": False,
                            "note": (
                                "Descriptive sensitivity uncomputable "
                                "on one side; interpretation "
                                "comparison not made."
                            ),
                        },
                    ],
                    "interpretation_changes": 0,
                },
            },
        },
        "curated": {},
        "top10":   {},
        "next10":  {},
        "final8":  {},
    }


def _bench_status_block(
    *,
    status: str = "comparison_uncomputable",
    comparison_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct a synthetic ``benchmark_sensitivity_status`` block for
    use by the status-branch tests below.  Defaults reflect the
    "preflight clear, comparison uncomputable" steady state."""
    return {
        "status":                   status,
        "blocked_events":           [],
        "required_dates":           [],
        "local_backfill_available": False,
        "online_backfill_required": status == "blocked",
        "limitations":              [],
        "comparison_summary": (
            {"comparisons": comparison_rows}
            if comparison_rows is not None else None
        ),
    }


def _patch_load(bundle: dict[str, Any], load_warnings: list[str] | None = None):
    return patch.object(
        cli, "_load_artifacts",
        return_value=(bundle, list(load_warnings or [])),
    )


def _patch_methodology_missing():
    return patch.object(
        cli, "_load_methodology_report",
        return_value=(None, "ImportError: synthetic"),
    )


def _patch_methodology(report: dict[str, Any]):
    return patch.object(
        cli, "_load_methodology_report",
        return_value=(report, None),
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_eight_keys(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        self.assertEqual(
            set(report.keys()), set(_REQUIRED_KEYS),
            f"unexpected keys: {sorted(report.keys())}",
        )

    def test_ok_true_when_artifacts_load_cleanly(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        self.assertTrue(report["ok"], report.get("errors"))


# ---------------------------------------------------------------------------
# Question coverage
# ---------------------------------------------------------------------------


class TestQuestionCoverage(unittest.TestCase):
    def test_all_required_questions_present_with_stable_ids(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        ids_in_order = [
            entry["id"] for entry in report["hard_questions"]
        ]
        self.assertEqual(ids_in_order, list(_REQUIRED_QUESTION_IDS))

    def test_every_question_has_matching_answer(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        for entry in report["hard_questions"]:
            q_id = entry["id"]
            self.assertIn(
                q_id, report["suggested_answers"],
                f"missing answer for {q_id}",
            )
            self.assertIsInstance(report["suggested_answers"][q_id], str)
            self.assertTrue(
                len(report["suggested_answers"][q_id]) >= 50,
                f"answer for {q_id} is suspiciously short",
            )

    def test_question_texts_match_required_substrings(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        text_by_id = {
            entry["id"]: entry["question"]
            for entry in report["hard_questions"]
        }
        for q_id, needle in _REQUIRED_QUESTION_SUBSTRINGS.items():
            self.assertIn(
                needle.lower(), text_by_id[q_id].lower(),
                f"question {q_id} text missing substring {needle!r}: "
                f"{text_by_id[q_id]!r}",
            )


# ---------------------------------------------------------------------------
# Answer content
# ---------------------------------------------------------------------------


class TestAnswerContent(unittest.TestCase):
    def test_q_validated_raw_only_explicitly_denies_fdr_claim(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_validated_raw_only"]
        lowered = answer.lower()
        self.assertIn("validated_raw_only", lowered)
        # Must clearly deny the FDR-significance reading.
        denial_signals = ("not", "did not", "does not")
        self.assertTrue(
            any(s in lowered for s in denial_signals),
            f"q_validated_raw_only answer must deny FDR claim: {answer!r}",
        )
        # Must mention raw p-value vs FDR distinction.
        self.assertIn("fdr", lowered)
        self.assertIn("raw", lowered)

    def test_q_zero_fdr_answer_includes_actual_numbers(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_zero_fdr"]
        # Pulled from the fixture's cohort_summary, not hardcoded
        # English.
        self.assertIn("31", answer)
        self.assertIn("12", answer)
        # And it explicitly says zero is the correct conservative
        # output, not a failure.
        self.assertIn("conservative", answer.lower())

    def test_q_manual_exclusions_cites_exact_counts(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_manual_exclusions"]
        # 20 excluded of 28 candidates derived from the fixture's
        # review_completion totals.
        self.assertIn("20", answer)
        self.assertIn("28", answer)

    def test_q_xle_benchmark_status_surfaces_three_pillars(self) -> None:
        # Required behavior: the answer distinguishes preflight/data
        # readiness, the SPY-vs-XLE comparison result, and what null
        # comparison payloads mean.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        # Pillar 1 — preflight / data readiness is named.
        self.assertIn("preflight", lowered)
        # Pillar 2 — SPY-vs-XLE comparison result is named.
        self.assertIn("spy-vs-xle comparison", lowered)
        # Pillar 3 — null comparison payloads explained.
        self.assertIn("null", lowered)
        self.assertIn("no inference", lowered)

    def test_q_xle_benchmark_status_reports_preflight_clear_when_uncomputable(
        self,
    ) -> None:
        # Fixture default is the comparison_uncomputable steady state:
        # preflight clears, but the comparison legs returned null.  The
        # answer must say preflight clears AND that the comparison
        # produced null spy_result / xle_result.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        self.assertIn("preflight now clears", lowered)
        self.assertIn("spy_result", lowered)
        self.assertIn("xle_result", lowered)
        # And the answer never claims the comparison itself succeeded.
        for forbidden in (
            "comparison succeeded",
            "spy-vs-xle interpretation is supported",
            "spy outperforms",
            "xle outperforms",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_q_xle_benchmark_status_blocked_branch_says_preflight_blocked(
        self,
    ) -> None:
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block(status="blocked", comparison_rows=None)
        )
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        self.assertIn("preflight is still blocked", lowered)
        # The comparison has not run.
        self.assertIn("has not run", lowered)

    def test_q_xle_benchmark_status_preview_ready_branch_distinguishes(
        self,
    ) -> None:
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block(status="preview_ready", comparison_rows=None)
        )
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        # Preflight is ready but the comparison has not yet executed.
        self.assertIn("preflight now clears", lowered)
        self.assertIn("has not yet been executed", lowered)

    def test_q_xle_benchmark_status_comparison_available_uses_event_ids(
        self,
    ) -> None:
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block(
                status="comparison_available",
                comparison_rows=[{
                    "event_id":   77,
                    "spy_result": {"abnormal_return": 0.01},
                    "xle_result": {"abnormal_return": 0.02},
                }],
            )
        )
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        # The computable event_id should appear so the operator can
        # find the per-event detail in the source artifact.
        self.assertIn("77", answer)

    def test_q_benchmark_sensitivity_does_not_claim_proof(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_benchmark_sensitivity"]
        lowered = answer.lower()
        # The answer must explicitly say a different benchmark does
        # NOT prove a record real.
        self.assertIn("does not prove", lowered)

    def test_q_next_evidence_lists_concrete_improvements(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_next_evidence"]
        # Three concrete next steps: expand cohort, XLE backfill,
        # second-reviewer.
        for needle in ("expand", "xle", "reviewer"):
            self.assertIn(
                needle, answer.lower(),
                f"q_next_evidence missing {needle!r}: {answer!r}",
            )

    def test_q_what_not_to_claim_pins_critical_refusals(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_what_not_to_claim"].lower()
        self.assertIn("validated_raw_only", answer)
        self.assertIn("xle", answer)
        self.assertIn("not claim", answer)


# ---------------------------------------------------------------------------
# Current evidence summary
# ---------------------------------------------------------------------------


class TestCurrentEvidenceSummary(unittest.TestCase):
    def test_summary_carries_cohort_numbers_from_freeze(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        summary = report["current_evidence_summary"]
        self.assertEqual(summary["events_evaluated"], 12)
        self.assertEqual(summary["total_records"], 31)
        self.assertEqual(summary["fdr_significant_count"], 0)
        self.assertEqual(summary["raw_p_candidate_count"], 4)
        self.assertEqual(summary["horizons"], [1, 5, 20])
        self.assertEqual(len(summary["mechanism_families"]), 6)
        self.assertEqual(summary["duplicate_event_ids"], [30])

    def test_summary_carries_verdict_counts(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        verdicts = report["current_evidence_summary"]["verdict_counts"]
        self.assertEqual(verdicts.get("fdr_significant"), 0)
        self.assertEqual(verdicts.get("inconclusive_fdr"), 27)
        self.assertEqual(verdicts.get("raw_p_only_candidate"), 4)

    def test_short_horizon_totals_derived_not_hardcoded(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        sh = report["current_evidence_summary"]["short_horizon_review"]
        # 4 + 4 + 0 = 8 accepted; 6 + 6 + 8 = 20 excluded;
        # 10 + 10 + 8 = 28 candidates.
        self.assertEqual(sh["accepted_total"], 8)
        self.assertEqual(sh["excluded_total"], 20)
        self.assertEqual(sh["candidate_total"], 28)
        self.assertIn("top10",  sh["by_batch"])
        self.assertIn("next10", sh["by_batch"])
        self.assertIn("final8", sh["by_batch"])

    def test_summary_adapts_when_artifacts_change(self) -> None:
        # Pin that the summary is computed from the bundle, not
        # hardcoded.  Change one number and watch it flow through.
        bundle = _fixture_bundle()
        bundle["freeze"]["cohort_summary"]["total_records"] = 99
        bundle["freeze"]["cohort_summary"]["events_evaluated"] = 42
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        summary = report["current_evidence_summary"]
        self.assertEqual(summary["total_records"], 99)
        self.assertEqual(summary["events_evaluated"], 42)
        # And the answers reflect the new numbers.
        answer = report["suggested_answers"]["q_zero_fdr"]
        self.assertIn("99", answer)
        self.assertIn("42", answer)


# ---------------------------------------------------------------------------
# Weak points
# ---------------------------------------------------------------------------


class TestWeakPoints(unittest.TestCase):
    def test_weak_points_have_name_and_detail(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        self.assertGreaterEqual(len(report["weak_points"]), 5)
        for wp in report["weak_points"]:
            self.assertIsInstance(wp, dict)
            self.assertIn("name", wp)
            self.assertIn("detail", wp)
            self.assertTrue(wp["name"])
            self.assertTrue(wp["detail"])

    def test_critical_weak_points_are_named(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        names = {wp["name"] for wp in report["weak_points"]}
        for required in (
            "zero_fdr_significant",
            "small_operator_curated_cohort",
            "manual_exclusion_rate",
            "duplicate_event_ids",
            "xle_benchmark_sensitivity_status",
            "single_reviewer_workflow",
            "raw_p_only_label_misread_risk",
        ):
            self.assertIn(
                required, names,
                f"weak point {required!r} must appear",
            )

    def test_uncomputable_weak_point_only_when_status_warrants_it(
        self,
    ) -> None:
        # When the freeze artifact reports comparison_uncomputable,
        # the rehearsal report must surface a dedicated weak point so
        # the operator does not gloss over the null comparison legs.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        names = {wp["name"] for wp in report["weak_points"]}
        self.assertIn(
            "xle_benchmark_sensitivity_comparison_uncomputable", names,
            "uncomputable weak point must appear when fixture status "
            "is comparison_uncomputable",
        )

        # When the freeze artifact reports a clean preflight with no
        # comparison run, the uncomputable weak point must NOT appear.
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block(
                status="preview_ready", comparison_rows=None,
            )
        )
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        names = {wp["name"] for wp in report["weak_points"]}
        self.assertNotIn(
            "xle_benchmark_sensitivity_comparison_uncomputable", names,
            "uncomputable weak point must not appear when comparison "
            "has not been attempted",
        )


# ---------------------------------------------------------------------------
# Must-not-say
# ---------------------------------------------------------------------------


class TestMustNotSay(unittest.TestCase):
    def test_must_not_say_has_five_or_more_items(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        self.assertGreaterEqual(len(report["must_not_say"]), 5)

    def test_must_not_say_pins_critical_refusals(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = " | ".join(report["must_not_say"]).lower()
        # Five canonical things the rehearsal report refuses to claim.
        self.assertIn("fdr-significant", blob)
        self.assertIn("validated_raw_only", blob)
        self.assertIn("future returns", blob)
        self.assertIn("xle", blob)
        self.assertIn("generalises", blob)

    # -- comparison_uncomputable branch (the legacy default) ------------------

    def test_must_not_say_retains_null_warning_when_uncomputable(self) -> None:
        # Fixture defaults to comparison_uncomputable.  The legacy
        # null-comparison wording must be present verbatim so a
        # downstream consumer can still pin it as a substring.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = " | ".join(report["must_not_say"]).lower()
        # The legacy XLE-vs-SPY null-result line, fragment-pinned.
        self.assertIn(
            "currently returns null spy_result/xle_result", blob,
            "uncomputable branch must keep the legacy null-result "
            "warning verbatim",
        )
        self.assertIn("no directional inference is supported", blob)

    def test_must_not_say_does_not_emit_causality_warning_when_uncomputable(
        self,
    ) -> None:
        # Conversely, the new comparison_available-only warnings must
        # NOT appear when the comparison legs are still null.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = " | ".join(report["must_not_say"]).lower()
        for forbidden in (
            "proves mechanism causality",
            "validates or invalidates",
            "per-event interpretation rollup can be ignored",
        ):
            self.assertNotIn(
                forbidden, blob,
                f"uncomputable branch must not surface the "
                f"comparison_available wording {forbidden!r}",
            )

    # -- comparison_available + rollup branch ---------------------------------

    def _build_complete(self) -> dict[str, Any]:
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block_with_rollup()
        )
        with _patch_load(bundle), _patch_methodology_missing():
            return cli.build_rehearsal_report()

    def test_must_not_say_drops_null_warning_when_comparison_complete(
        self,
    ) -> None:
        # When the freeze block reports comparison_available AND the
        # comparison_summary rows carry computed SPY/XLE legs, the
        # stale "currently returns null" wording must NOT appear.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"]).lower()
        self.assertNotIn(
            "currently returns null spy_result/xle_result", blob,
            "comparison_available branch must drop the stale null-"
            "result warning",
        )

    def test_must_not_say_emits_causality_warning_when_complete(self) -> None:
        # And the three replacement warnings the task pins must be
        # present so the speaker is reminded NOT to claim causality,
        # NOT to read XLE as a validate/invalidate verdict, and NOT
        # to gloss over the per-event flip.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"]).lower()
        self.assertIn("proves mechanism causality", blob)
        self.assertIn("validates or invalidates", blob)
        self.assertIn("per-event interpretation rollup can be ignored", blob)

    def test_must_not_say_names_event_60_under_comparison_complete(
        self,
    ) -> None:
        # The rehearsal warning must name event 60 (the descriptive
        # flip) so the speaker knows which event to cite when
        # describing the change.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"])
        self.assertIn("60", blob)

    def test_must_not_say_preserves_raw_p_vs_fdr_distinction(self) -> None:
        # Under the comparison_available branch the warning about
        # event 60's interpretation flip must call out both axes
        # separately — raw-p and FDR — so the listener cannot collapse
        # them into one threshold.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"]).lower()
        self.assertIn("raw-p", blob)
        self.assertIn("fdr", blob)

    def test_must_not_say_does_not_claim_event_60_proves_mechanism(
        self,
    ) -> None:
        # The warning is the negation: it says "do not claim
        # mechanism causality".  The text must therefore not, in any
        # branch, positively assert that event 60 proves the
        # mechanism or carries a causal reading.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"]).lower()
        for forbidden in (
            "event 60 proves the mechanism",
            "event 60 is a finding",
            "event_id(s) [60] establishes",
            "event 60 validates significance",
        ):
            self.assertNotIn(forbidden, blob)

    def test_must_not_say_under_complete_branch_avoids_banned_tokens(
        self,
    ) -> None:
        # The new wording must pass the same banned-token bar as the
        # rest of the report.  Strip the literal pipeline label first
        # so the carve-out is honoured.
        report = self._build_complete()
        blob = " | ".join(report["must_not_say"]).lower()
        sanitised = blob.replace("validated_raw_only", "")
        for token in _BANNED_WORDS:
            self.assertNotIn(
                token, sanitised,
                f"banned token {token!r} in must_not_say (complete branch)",
            )
        # And the bare ``validated`` word never appears outside the
        # literal pipeline label even in the new wording.
        sentinel = blob.replace("validated_raw_only", "@@LABEL@@")
        self.assertIsNone(
            re.search(r"\bvalidated\b", sentinel),
            "bare 'validated' word leaked into must_not_say",
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class _BannedWordMixin:
    """Strip the literal pipeline label ``validated_raw_only`` before
    scanning text for banned tokens.  The label is allowed verbatim
    everywhere; outside the label, no form of ``validated`` may appear.
    """

    @staticmethod
    def _strip_label(text: str) -> str:
        # Drop the literal label.  Also drop the substring "validated"
        # only when it is part of the label — but never elsewhere.  We
        # rely on the test that bans bare "validated " (with trailing
        # space) to enforce the second half.
        return text.replace("validated_raw_only", "")


class TestConservativeWording(unittest.TestCase, _BannedWordMixin):
    def test_no_banned_tokens_in_json_render(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = self._strip_label(cli._render_json(report).lower())
        for token in _BANNED_WORDS:
            self.assertNotIn(
                token, blob,
                f"banned token {token!r} in JSON render",
            )

    def test_no_banned_tokens_in_text_render(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = self._strip_label(cli._render_text(report).lower())
        for token in _BANNED_WORDS:
            self.assertNotIn(token, blob,
                             f"banned token {token!r} in text render")

    def test_no_bare_validated_word_outside_pipeline_label(self) -> None:
        # The substring ``validated`` outside the literal pipeline
        # label is banned.  Pin via regex: any ``validated`` that is
        # NOT followed by ``_raw_only`` is a violation.
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        blob = cli._render_json(report).lower()
        # Replace the literal label with a sentinel so the regex never
        # matches it.
        sanitised = blob.replace("validated_raw_only", "@@LABEL@@")
        match = re.search(r"\bvalidated\b", sanitised)
        self.assertIsNone(
            match,
            f"bare 'validated' found outside pipeline label: "
            f"{sanitised[max(0, match.start()-30): match.end()+30] if match else ''}",
        )


# ---------------------------------------------------------------------------
# Methodology companion
# ---------------------------------------------------------------------------


class TestMethodologyCompanion(unittest.TestCase):
    def test_missing_methodology_surfaces_warning(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("methodology", joined)
        # The rehearsal still completes — ok stays True; methodology
        # is optional context, not a hard dependency.
        self.assertTrue(report["ok"])

    def test_methodology_terms_flow_into_q_validated_raw_only(self) -> None:
        meth_report = {
            "ok":               True,
            "statistical_terms": {
                "validated_raw_only": (
                    "synthetic methodology stanza about the label."
                ),
            },
            "likely_questions": [],
        }
        with _patch_load(_fixture_bundle()), _patch_methodology(meth_report):
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_validated_raw_only"]
        self.assertIn(
            "synthetic methodology stanza about the label.", answer,
            "methodology term must be cited verbatim in Q2 answer",
        )

    def test_methodology_failure_does_not_break_report(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        # Every required question still has an answer.
        for q_id in _REQUIRED_QUESTION_IDS:
            self.assertIn(q_id, report["suggested_answers"])


# ---------------------------------------------------------------------------
# Artifact immutability
# ---------------------------------------------------------------------------


class TestNoArtifactMutation(unittest.TestCase):
    def test_run_against_real_artifacts_does_not_change_bytes(self) -> None:
        # Hash each of the five canonical artifacts before / after a
        # real run.  Bytes must match.
        artifacts_dir = Path(os.path.dirname(__file__), "..", "artifacts").resolve()
        files = [
            "freeze_candidate_evidence.json",
            "curated_stage_validation_evidence.json",
            "short_horizon_review_validation_top10.json",
            "short_horizon_review_validation_next10.json",
            "short_horizon_review_validation_final8.json",
        ]
        before: dict[str, bytes] = {}
        for fname in files:
            p = artifacts_dir / fname
            if p.exists():
                with open(p, "rb") as fh:
                    before[fname] = fh.read()
        # Run a real report (no patches) against the on-disk artifacts.
        report = cli.build_rehearsal_report()
        self.assertTrue(report["ok"], report.get("errors"))
        for fname, content in before.items():
            p = artifacts_dir / fname
            with open(p, "rb") as fh:
                after = fh.read()
            self.assertEqual(
                content, after,
                f"artifact {fname} mutated by rehearsal report run",
            )


# ---------------------------------------------------------------------------
# No paid-surface imports
# ---------------------------------------------------------------------------


class TestNoPaidSurfaceImports(unittest.TestCase):
    def test_rehearsal_module_does_not_bind_yfinance_anthropic_openai(
        self,
    ) -> None:
        for attr in ("yfinance", "anthropic", "openai"):
            self.assertFalse(
                hasattr(cli, attr),
                f"rehearsal report must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# --output and CLI
# ---------------------------------------------------------------------------


class TestOutputPersistence(unittest.TestCase):
    def test_output_path_writes_report(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"rehearsal_qa_{uuid.uuid4().hex}.json",
        )
        try:
            with _patch_load(_fixture_bundle()), _patch_methodology_missing():
                report = cli.build_rehearsal_report(output_path=out_path)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            self.assertEqual(set(blob.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(blob["ok"], report["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


class TestCLIEntryPoint(unittest.TestCase):
    def test_main_json_default(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            buf = StringIO()
            rc = cli.main([], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(rc, 0)

    def test_main_json_flag(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            buf = StringIO()
            rc = cli.main(["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(rc, 0)

    def test_main_text_flag(self) -> None:
        with _patch_load(_fixture_bundle()), _patch_methodology_missing():
            buf = StringIO()
            rc = cli.main(["--text"], out=buf)
        text = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Evidence rehearsal Q&A report", text)
        # Text mode numbers each question 1-8 for interview reference.
        for n in range(1, 9):
            self.assertIn(f"Q{n}.", text,
                          f"text render missing question marker Q{n}.")


# ---------------------------------------------------------------------------
# Per-event interpretation rollup — comparison_available + rollup branch.
#
# Pins the rehearsal Q&A's behaviour when the freeze artifact's
# benchmark_sensitivity_status block surfaces a populated per-event
# rollup (changed_event_ids, unchanged_event_ids, per_event_summary).
# Mirrors the live SPY-vs-XLE comparison artifact's shape: event 60
# flipped interpretation under XLE, event 73 did not.
# ---------------------------------------------------------------------------


def _bench_status_block_with_rollup() -> dict[str, Any]:
    """Freeze ``benchmark_sensitivity_status`` block with the per-event
    rollup populated.  Event 60 flips interpretation under XLE; event
    73 is unchanged."""
    return {
        "status":                       "comparison_available",
        "blocked_events":               [],
        "required_dates":               [],
        "local_backfill_available":     False,
        "online_backfill_required":     False,
        "limitations":                  [],
        "changed_interpretation_count": 1,
        "changed_event_ids":             [60],
        "unchanged_event_ids":           [73],
        "per_event_summary": [
            {
                "event_id":               60,
                "event_date":             "2026-04-08",
                "primary_ticker":         "XOM",
                "changed_interpretation": True,
                "changed_fields": [
                    {"field": "raw_p_threshold",
                     "spy": 0.028, "xle": 0.268, "alpha": 0.05},
                    {"field": "fdr_q_threshold",
                     "spy": 0.028, "xle": 0.268, "alpha": 0.05},
                    {"field": "significant_flag",
                     "spy": True,  "xle": False},
                ],
                "note": (
                    "SPY and XLE differ on both raw-p threshold and "
                    "FDR significance for this event."
                ),
            },
            {
                "event_id":               73,
                "event_date":             "2026-04-06",
                "primary_ticker":         "XOM",
                "changed_interpretation": False,
                "changed_fields":         [],
                "note": (
                    "SPY and XLE agree on both raw-p threshold and "
                    "FDR significance."
                ),
            },
        ],
        "comparison_summary": {
            "ok":             True,
            "checked_events": 2,
            "blocked_count":  0,
            "comparisons": [
                {
                    "event_id":   60,
                    "spy_result": {
                        "raw_p": 0.028, "fdr_q": 0.028,
                        "significant": True,  "sar": -0.205,
                    },
                    "xle_result": {
                        "raw_p": 0.268, "fdr_q": 0.268,
                        "significant": False, "sar": -0.039,
                    },
                    "changed_interpretation": True,
                },
                {
                    "event_id":   73,
                    "spy_result": {
                        "raw_p": 0.145, "fdr_q": 0.145,
                        "significant": False, "sar": -0.138,
                    },
                    "xle_result": {
                        "raw_p": 0.198, "fdr_q": 0.198,
                        "significant": False, "sar": -0.046,
                    },
                    "changed_interpretation": False,
                },
            ],
        },
    }


class TestPerEventInterpretationInRehearsalAnswer(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block_with_rollup()
        )
        with _patch_load(bundle), _patch_methodology_missing():
            return cli.build_rehearsal_report()

    def test_answer_names_changed_event_60(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        # Event 60 (the changed one) is named explicitly so the
        # operator can point to the specific event whose descriptive
        # interpretation flips.
        self.assertIn("60", answer)

    def test_answer_names_unchanged_event_73(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        self.assertIn("73", answer)

    def test_answer_says_benchmark_choice_materially_changes(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        self.assertIn("materially changes", answer.lower())

    def test_answer_says_not_significant_under_both(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        # Event 73 must be described as not significant under both
        # benchmarks so the operator does not infer that XLE rescues
        # the event from non-significance.
        self.assertIn("not significant under both", answer.lower())

    def test_answer_says_does_not_prove_mechanism_causality(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        # Mirrors the freeze artifact's descriptive / no-causality
        # framing verbatim so the two reports stay in lockstep.
        self.assertIn(
            "does not prove mechanism causality", answer.lower(),
        )

    def test_answer_preserves_raw_p_vs_fdr_distinction(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        # The raw-p vs FDR distinction must be preserved — surfacing
        # both axes shows the operator that benchmark choice changes
        # event 60 on both axes, not just one.
        self.assertIn("raw-p", lowered)
        self.assertIn("fdr", lowered)

    def test_answer_does_not_claim_event_60_is_a_finding(self) -> None:
        report = self._build()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        lowered = answer.lower()
        # The block surfacing "spy.significant=True / xle.significant=
        # False" must not be read as a top-level FDR-significance
        # claim for event 60.
        for forbidden in (
            "event 60 is fdr-significant",
            "event 60 is a finding",
            "validates significance",
            "confirms significance",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_changed_event_ids_flow_into_summary(self) -> None:
        # The summary surface that drives the answer must carry the
        # rollup so a downstream consumer can introspect it without
        # re-parsing the freeze block.
        report = self._build()
        bench = report["current_evidence_summary"]["benchmark_sensitivity"]
        self.assertEqual(bench["changed_event_ids"],   [60])
        self.assertEqual(bench["unchanged_event_ids"], [73])
        self.assertEqual(bench["changed_interpretation_count"], 1)

    def test_comparison_available_without_rollup_still_names_event(self) -> None:
        # Graceful degradation: when the freeze block does not surface
        # the rollup keys (older fixture / partial bundle), the answer
        # still names the computable event from the comparison_summary
        # so the existing comparison_available behaviour is preserved.
        bundle = _fixture_bundle()
        bundle["freeze"]["benchmark_sensitivity_status"] = (
            _bench_status_block(
                status="comparison_available",
                comparison_rows=[{
                    "event_id":   77,
                    "spy_result": {"abnormal_return": 0.01},
                    "xle_result": {"abnormal_return": 0.02},
                }],
            )
        )
        with _patch_load(bundle), _patch_methodology_missing():
            report = cli.build_rehearsal_report()
        answer = report["suggested_answers"]["q_xle_benchmark_status"]
        self.assertIn("77", answer)
        # And without a populated rollup, the answer does not
        # fabricate a "materially changes" claim.
        self.assertNotIn(
            "materially changes", answer.lower(),
            "answer must not invent an interpretation change when "
            "the freeze block does not surface one",
        )

    def test_rendered_blob_has_no_banned_tokens(self) -> None:
        report = self._build()
        for renderer in (cli._render_json, cli._render_text):
            blob = renderer(report).lower()
            sanitised = blob.replace("validated_raw_only", "")
            for token in _BANNED_WORDS:
                self.assertNotIn(
                    token, sanitised,
                    f"banned token {token!r} in {renderer.__name__}",
                )
            # And the bare ``validated`` word never appears outside
            # the literal pipeline label.
            sentinel = blob.replace("validated_raw_only", "@@LABEL@@")
            self.assertIsNone(
                re.search(r"\bvalidated\b", sentinel),
                "bare 'validated' word leaked into rendered output",
            )


if __name__ == "__main__":
    unittest.main()

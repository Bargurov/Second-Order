"""Tests for ``scripts/validate_cohort_integration_review.py``.

Pin the contract:

* Read-only validator.  No DB writes, no provider, no LLM, no
  ``yfinance``, no FastAPI surface.  The artifact file is never
  mutated by validation -- every byte stays where it was on disk.
* Validates a per-candidate ``cohort_integration_review`` block (or an
  artifact embedding one or more blocks) against the eight-gate rule
  defined in ``docs/expansion_cohort_integration_rule.md``.
* Output dict has EXACTLY these 5 keys::

    ok, artifact_path, blocks_count, errors, warnings

* ``ok`` is True iff ``errors`` is empty.
* Unknown gate names are warnings, not errors (additive evolution
  tolerated).  Missing required gate names are errors.
* v1 advisory fields (``event_anchor_date``,
  ``first_tradable_reaction_date``, ``mechanism_family``,
  ``predicted_direction``, ``rule_version``, ``rule_commit_sha``)
  produce warnings, not errors, so v0.1-shaped blocks remain valid.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import validate_cohort_integration_review as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "artifact_path",
    "blocks_count",
    "errors",
    "warnings",
)


_REQUIRED_GATE_NAMES = (
    "G1_source_quality",
    "G2_ticker_benchmark",
    "G3_direction_pretest",
    "G4_not_result_selected",
    "G5_fdr_significant",
    "G6_horizon_defensible",
    "G7_no_confound",
    "G8_interview_defensible",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _good_block(**overrides: Any) -> dict[str, Any]:
    """Build a minimum-viable cohort_integration_review block that
    the validator should accept (all eight gates 'yes', graduates,
    metadata populated, anti-hindsight notes plausible).
    """
    base: dict[str, Any] = {
        "candidate_id": "next-five-006",
        "reviewed_at": "2026-06-01",
        "reviewer": "operator",
        "event_anchor_date": "2018-03-07",
        "first_tradable_reaction_date": "2018-03-08",
        "mechanism_family": "tariffs_industrial_policy",
        "predicted_direction": "positive",
        "rule_version": "v1",
        "rule_commit_sha": "0000000000000000000000000000000000000000",
        "gates": {
            "G1_source_quality": {
                "answer": "yes",
                "note": "USTR official proclamation; timestamp unambiguous.",
            },
            "G2_ticker_benchmark": {
                "answer": "yes",
                "note": (
                    "NUE is the largest US steel producer; "
                    "SLX-ex-NUE benchmark; alternatives "
                    "considered: X (paired-petitioner, would "
                    "amplify AR), STLD (smaller cap, less liquid)."
                ),
            },
            "G3_direction_pretest": {
                "answer": "yes",
                "note": (
                    "Positive direction registered before smoke ran; "
                    "matches realized SAR sign."
                ),
            },
            "G4_not_result_selected": {
                "answer": "yes",
                "note": (
                    "NUE was on the candidate list before any "
                    "per-event statistic was computed."
                ),
            },
            "G5_fdr_significant": {
                "answer": "yes",
                "note": "horizon=1, q=0.0042",
            },
            "G6_horizon_defensible": {
                "answer": "yes",
                "note": (
                    "h=1 matches the tariff-announcement repricing "
                    "timescale; intraday equity reaction to a "
                    "regulatory action."
                ),
            },
            "G7_no_confound": {
                "answer": "yes",
                "pre_test_note": (
                    "No concurrent FOMC, earnings, or M&A within "
                    "+/- 2 trading days; scan committed prior to "
                    "smoke run."
                ),
                "post_test_note": (
                    "SLX benchmark behaved consistently with "
                    "broader steel sector; no anomalous "
                    "benchmark move."
                ),
            },
            "G8_interview_defensible": {
                "answer": "yes",
                "note": (
                    "Section 232 steel tariff to direct domestic "
                    "petitioner; clean falsifier; explanation "
                    "holds even if test had returned null."
                ),
            },
        },
        "graduation_decision": "graduate",
        "graduation_status": "clean",
        "reason": (
            "All eight gates yes; clean graduation under v1 rule."
        ),
    }
    base.update(overrides)
    return base


def _write_block(payload: dict[str, Any]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"cohort_review_test_{uuid.uuid4().hex}.json",
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# --artifact required + file existence + JSON parsing
# ---------------------------------------------------------------------------


class TestArtifactPathRequired(unittest.TestCase):
    def test_missing_path_returns_failure(self) -> None:
        report = cli.run_validate_cohort_integration_review(
            artifact_path=None,
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "artifact" in e.lower() for e in report["errors"]
        ))
        self.assertEqual(report["blocks_count"], 0)

    def test_nonexistent_path_returns_failure(self) -> None:
        report = cli.run_validate_cohort_integration_review(
            artifact_path="/nonexistent/cohort_review.json",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "does not exist" in e.lower()
            for e in report["errors"]
        ))
        self.assertEqual(report["blocks_count"], 0)

    def test_malformed_json_returns_failure(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"cohort_review_malformed_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "failed to parse" in e.lower()
                for e in report["errors"]
            ))
            self.assertEqual(report["blocks_count"], 0)
        finally:
            os.unlink(path)

    def test_non_object_root_returns_failure(self) -> None:
        path = _write_block({})  # write {} then overwrite with list
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "must be a JSON object" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Envelope shape + byte identity
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):
    def test_envelope_has_exactly_required_keys(self) -> None:
        path = _write_block(_good_block())
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertEqual(
                set(report.keys()), set(_REQUIRED_KEYS),
                f"unexpected envelope shape: {sorted(report.keys())}",
            )
            self.assertEqual(report["artifact_path"], path)
            self.assertIsInstance(report["errors"], list)
            self.assertIsInstance(report["warnings"], list)
        finally:
            os.unlink(path)

    def test_byte_identity_preserved(self) -> None:
        path = _write_block(_good_block())
        try:
            before = _sha256(path)
            cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            after = _sha256(path)
            self.assertEqual(
                before, after,
                "validator must not mutate the artifact",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_standalone_good_block_passes(self) -> None:
        path = _write_block(_good_block())
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors on happy-path block: "
                f"{report['errors']}",
            )
            self.assertEqual(report["blocks_count"], 1)
            self.assertEqual(report["warnings"], [])
        finally:
            os.unlink(path)

    def test_embedded_single_block_passes(self) -> None:
        path = _write_block({
            "cohort_integration_review": _good_block(),
        })
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
            self.assertEqual(report["blocks_count"], 1)
        finally:
            os.unlink(path)

    def test_embedded_block_list_passes(self) -> None:
        path = _write_block({
            "cohort_integration_review": [
                _good_block(candidate_id="next-five-006"),
                _good_block(candidate_id="next-five-007"),
            ],
        })
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
            self.assertEqual(report["blocks_count"], 2)
        finally:
            os.unlink(path)

    def test_empty_object_reports_no_block_found(self) -> None:
        path = _write_block({})
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["blocks_count"], 0)
            self.assertTrue(any(
                "no cohort_integration_review block found" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Gate schema
# ---------------------------------------------------------------------------


class TestGateSchema(unittest.TestCase):
    def test_missing_gate_is_error(self) -> None:
        block = _good_block()
        del block["gates"]["G5_fdr_significant"]
        # set graduation_decision to 'hold' so aggregation doesn't
        # double-report (gates incomplete -> aggregation skipped)
        block["graduation_decision"] = "hold"
        block["graduation_status"] = "clean"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G5_fdr_significant" in e
                and "missing required entry" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_unknown_gate_is_warning_not_error(self) -> None:
        block = _good_block()
        block["gates"]["G9_unknown_gate"] = {
            "answer": "yes",
            "note": "n",
        }
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unknown gate should not produce errors, got: "
                f"{report['errors']}",
            )
            self.assertTrue(any(
                "G9_unknown_gate" in w for w in report["warnings"]
            ))
        finally:
            os.unlink(path)

    def test_invalid_answer_is_error(self) -> None:
        block = _good_block()
        block["gates"]["G1_source_quality"]["answer"] = "maybe"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G1_source_quality" in e and "maybe" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_no_answer_with_empty_note_is_error(self) -> None:
        block = _good_block()
        block["gates"]["G1_source_quality"] = {
            "answer": "no",
            "note": "",
        }
        block["graduation_decision"] = "hold"
        block["graduation_status"] = "clean"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G1_source_quality" in e
                and "non-empty 'note'" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_g7_yes_requires_pre_test_note(self) -> None:
        block = _good_block()
        block["gates"]["G7_no_confound"]["pre_test_note"] = ""
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G7_no_confound" in e and "pre_test_note" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_g7_yes_requires_post_test_note(self) -> None:
        block = _good_block()
        del block["gates"]["G7_no_confound"]["post_test_note"]
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G7_no_confound" in e and "post_test_note" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_g7_no_does_not_require_pre_post_notes(self) -> None:
        # When G7 is answered 'no', the special pre/post note check
        # does not apply; only the standard 'no requires non-empty
        # note' rule applies.
        block = _good_block()
        block["gates"]["G7_no_confound"] = {
            "answer": "no",
            "note": "Concurrent FOMC release inside window.",
            "pre_test_note": "",
            "post_test_note": "",
        }
        block["graduation_decision"] = "hold"
        block["graduation_status"] = "clean"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"G7 answered 'no' should not require pre/post "
                f"notes; got errors: {report['errors']}",
            )
        finally:
            os.unlink(path)

    def test_gate_not_an_object_is_error(self) -> None:
        block = _good_block()
        block["gates"]["G1_source_quality"] = "not an object"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G1_source_quality" in e
                and "must be a JSON object" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_gates_not_an_object_is_error(self) -> None:
        block = _good_block()
        block["gates"] = "not an object"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "gates must be a JSON object" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation(unittest.TestCase):
    def test_all_yes_must_graduate(self) -> None:
        block = _good_block(graduation_decision="hold")
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "all eight required gates answered 'yes'" in e
                and "'hold'" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_any_no_must_not_graduate(self) -> None:
        block = _good_block()
        block["gates"]["G3_direction_pretest"] = {
            "answer": "no",
            "note": "Direction was edited after smoke ran.",
        }
        # graduation_decision stays 'graduate' -> aggregation violation
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "at least one required gate answered 'no'" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_any_no_with_hold_is_ok(self) -> None:
        block = _good_block()
        block["gates"]["G1_source_quality"] = {
            "answer": "no",
            "note": "Source page no longer resolves.",
        }
        block["graduation_decision"] = "hold"
        block["graduation_status"] = "clean"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
        finally:
            os.unlink(path)

    def test_all_no_with_reject_is_ok(self) -> None:
        block = _good_block()
        for gate_name in _REQUIRED_GATE_NAMES:
            if gate_name == "G7_no_confound":
                block["gates"][gate_name] = {
                    "answer": "no",
                    "note": "Concurrent FOMC release inside window.",
                    "pre_test_note": "",
                    "post_test_note": "",
                }
            else:
                block["gates"][gate_name] = {
                    "answer": "no",
                    "note": "Failed; see note.",
                }
        block["graduation_decision"] = "reject"
        block["graduation_status"] = "clean"
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
        finally:
            os.unlink(path)

    def test_unknown_graduation_decision_is_error(self) -> None:
        block = _good_block(graduation_decision="definitely_yes")
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "graduation_decision" in e
                and "definitely_yes" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_unknown_graduation_status_is_error(self) -> None:
        block = _good_block(graduation_status="extra_clean")
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "graduation_status" in e
                and "extra_clean" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_with_caveat_requires_borderline_gate(self) -> None:
        block = _good_block(graduation_status="with_caveat")
        # No borderline_gate field set
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "borderline_gate" in e and "with_caveat" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_with_caveat_borderline_gate_must_be_required_name(self) -> None:
        block = _good_block(
            graduation_status="with_caveat",
            borderline_gate="G9_not_a_real_gate",
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "borderline_gate" in e
                and "G9_not_a_real_gate" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_with_caveat_valid_borderline_gate_is_ok(self) -> None:
        block = _good_block(
            graduation_status="with_caveat",
            borderline_gate="G2_ticker_benchmark",
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Anti-hindsight invariants
# ---------------------------------------------------------------------------


class TestAntiHindsight(unittest.TestCase):
    def test_g5_horizon_out_of_preregistered_set_is_error(self) -> None:
        block = _good_block()
        block["gates"]["G5_fdr_significant"]["note"] = (
            "horizon=7, q=0.0042"
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "G5_fdr_significant" in e
                and "horizon=7" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_g5_horizon_in_preregistered_set_is_ok(self) -> None:
        block = _good_block()
        block["gates"]["G5_fdr_significant"]["note"] = (
            "horizon=5, q=0.0123"
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
        finally:
            os.unlink(path)

    def test_g5_missing_horizon_declaration_is_warning(self) -> None:
        block = _good_block()
        block["gates"]["G5_fdr_significant"]["note"] = (
            "FDR significant, see batch artifact."
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            # Should pass (warning only, not error)
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
            self.assertTrue(any(
                "G5_fdr_significant" in w
                and "horizon=N" in w
                for w in report["warnings"]
            ))
        finally:
            os.unlink(path)

    def test_g6_short_note_is_warning(self) -> None:
        block = _good_block()
        block["gates"]["G6_horizon_defensible"]["note"] = "Yes."
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(any(
                "G6_horizon_defensible" in w
                for w in report["warnings"]
            ))
        finally:
            os.unlink(path)

    def test_g6_horizon_reference_present_is_ok(self) -> None:
        block = _good_block()
        # already has "h=1 matches the tariff-announcement..." in the
        # good block fixture; confirm no G6 warning
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(any(
                "G6_horizon_defensible" in w
                for w in report["warnings"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata(unittest.TestCase):
    def test_missing_reviewer_is_error(self) -> None:
        block = _good_block()
        del block["reviewer"]
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "'reviewer'" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_empty_reviewer_is_error(self) -> None:
        block = _good_block(reviewer="")
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "'reviewer'" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_missing_reviewed_at_is_error(self) -> None:
        block = _good_block()
        del block["reviewed_at"]
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "'reviewed_at'" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_unparseable_reviewed_at_is_error(self) -> None:
        block = _good_block(reviewed_at="next thursday")
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "'reviewed_at'" in e
                and "not parseable" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_iso_8601_reviewed_at_is_ok(self) -> None:
        block = _good_block(
            reviewed_at="2026-06-01T15:30:00+00:00",
        )
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"unexpected errors: {report['errors']}",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# v1 advisory fields
# ---------------------------------------------------------------------------


class TestV1AdvisoryFields(unittest.TestCase):
    def test_missing_v1_field_is_warning_not_error(self) -> None:
        block = _good_block()
        del block["event_anchor_date"]
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"missing v1 advisory field should not produce "
                f"errors; got: {report['errors']}",
            )
            self.assertTrue(any(
                "event_anchor_date" in w
                and "advisory" in w
                for w in report["warnings"]
            ))
        finally:
            os.unlink(path)

    def test_all_v1_fields_missing_block_still_passes(self) -> None:
        block = _good_block()
        for field in (
            "event_anchor_date",
            "first_tradable_reaction_date",
            "mechanism_family",
            "predicted_direction",
            "rule_version",
            "rule_commit_sha",
        ):
            del block[field]
        path = _write_block(block)
        try:
            report = cli.run_validate_cohort_integration_review(
                artifact_path=path,
            )
            self.assertTrue(
                report["ok"],
                f"v0.1-shaped block should remain valid in v1 "
                f"validator; got: {report['errors']}",
            )
            self.assertEqual(len(report["warnings"]), 6)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------


class TestCliMain(unittest.TestCase):
    def test_main_returns_zero_on_good_block(self) -> None:
        path = _write_block(_good_block())
        from io import StringIO
        try:
            buf = StringIO()
            rc = cli.main(["--artifact", path], out=buf)
            self.assertEqual(rc, 0)
            self.assertIn("OK:", buf.getvalue())
        finally:
            os.unlink(path)

    def test_main_returns_one_on_missing_file(self) -> None:
        from io import StringIO
        buf = StringIO()
        rc = cli.main(["--artifact", "/nonexistent"], out=buf)
        self.assertEqual(rc, 1)

    def test_main_json_flag_emits_json(self) -> None:
        path = _write_block(_good_block())
        from io import StringIO
        try:
            buf = StringIO()
            rc = cli.main(["--artifact", path, "--json"], out=buf)
            self.assertEqual(rc, 0)
            parsed = json.loads(buf.getvalue())
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

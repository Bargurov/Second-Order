"""Tests for ``scripts/validate_rejection_log_summary.py``.

Pin the contract for the sanitized rejection-log summary validator:

* Read-only validator.  No DB writes, no provider, no LLM, no
  ``yfinance``, no FastAPI surface.  The artifact file is never
  mutated by validation.
* Validates the tracked sanitized rejection summary at
  ``demo_artifacts/section_c_v2/rejection_log_summary_v1.json``
  against the public-summary schema:

  - identifiable_rejections_count equals len(identifiable_rejections)
  - no item carries the operator-only fields ``reason_note`` or
    ``source_files``
  - decision_counts, stage_counts, reason_category_counts each match
    the actual entries
  - CENX, NUE, NOC are deferred_methodology_lesson
  - AMAT is rejected at post_screen_canonical_test for
    g5_not_significant and is flagged phase2_pool_count=true
  - no statistics / returns / p-value tokens leak into tracked summary
  - no forbidden overclaim language
    (proof/proven/validated/alpha/prediction/predicted)
* Output dict has EXACTLY these 5 keys::

    ok, artifact_path, identifiable_rejections_count, errors, warnings

* ``ok`` is True iff ``errors`` is empty.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import validate_rejection_log_summary as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "artifact_path",
    "identifiable_rejections_count",
    "errors",
    "warnings",
)


def _good_summary() -> dict[str, Any]:
    """Build a sanitized rejection summary the validator must accept.

    Matches the public schema of
    ``demo_artifacts/section_c_v2/rejection_log_summary_v1.json``.
    """
    return {
        "artifact_type": "rejection_log_summary",
        "schema_version": "v1",
        "generated_at": "2026-05-27T00:00:00Z",
        "summary": {
            "identifiable_rejections_count": 4,
            "unresolved_records_count": 0,
            "decision_counts": {
                "rejected": 1,
                "deferred_methodology_lesson": 3,
            },
            "stage_counts": {
                "post_validation": 3,
                "post_screen_canonical_test": 1,
            },
            "reason_category_counts": {
                "source_quality": 3,
                "g5_not_significant": 1,
            },
            "superseded_by_tracked_candidate_count": 0,
        },
        "identifiable_rejections": [
            {
                "rejection_id": "rej-005",
                "primary_ticker": "CENX",
                "benchmark_ticker": "XME",
                "decision": "deferred_methodology_lesson",
                "stage": "post_validation",
                "reason_category": "source_quality",
                "recorded_on": "2026-05-27",
            },
            {
                "rejection_id": "rej-008",
                "primary_ticker": "NUE",
                "benchmark_ticker": None,
                "decision": "deferred_methodology_lesson",
                "stage": "post_validation",
                "reason_category": "source_quality",
                "recorded_on": "2026-05-27",
            },
            {
                "rejection_id": "rej-009",
                "primary_ticker": "NOC",
                "benchmark_ticker": "BA",
                "decision": "deferred_methodology_lesson",
                "stage": "post_validation",
                "reason_category": "source_quality",
                "recorded_on": "2026-05-28",
            },
            {
                "rejection_id": "rej-010",
                "primary_ticker": "AMAT",
                "benchmark_ticker": "SPY",
                "decision": "rejected",
                "stage": "post_screen_canonical_test",
                "reason_category": "g5_not_significant",
                "recorded_on": "2026-05-28",
                "phase2_pool_count": True,
            },
        ],
        "notes": [
            "Sanitized public summary; operator reason_note prose and "
            "source-file paths are intentionally excluded.",
        ],
    }


def _write_tmp(payload: Any) -> str:
    """Serialize ``payload`` to a temp file and return its path."""
    fh = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    try:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh)
    finally:
        fh.close()
    return fh.name


def _run(path: str) -> dict[str, Any]:
    return cli.run_validate_rejection_log_summary(artifact_path=path)


class EnvelopeContract(unittest.TestCase):
    """The output envelope must have exactly the five documented keys."""

    def test_envelope_keys_on_success(self) -> None:
        path = _write_tmp(_good_summary())
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["identifiable_rejections_count"], 4)


class TrackedArtifactPasses(unittest.TestCase):
    """The committed tracked artifact must validate cleanly."""

    def test_tracked_rejection_summary_passes(self) -> None:
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        tracked = os.path.join(
            repo_root,
            "demo_artifacts",
            "section_c_v2",
            "rejection_log_summary_v1.json",
        )
        report = _run(tracked)
        self.assertTrue(
            report["ok"],
            msg=f"tracked rejection summary must validate: {report}",
        )
        self.assertEqual(report["errors"], [])


class ValidSummaryPasses(unittest.TestCase):
    """A synthetic, schema-conforming summary passes cleanly."""

    def test_minimal_valid_summary_passes(self) -> None:
        path = _write_tmp(_good_summary())
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertTrue(report["ok"], msg=str(report))
        self.assertEqual(report["errors"], [])


class CountMismatchFails(unittest.TestCase):
    """identifiable_rejections_count != len(identifiable_rejections)."""

    def test_identifiable_count_mismatch(self) -> None:
        payload = _good_summary()
        payload["summary"]["identifiable_rejections_count"] = 99
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("identifiable_rejections_count", joined)


class ReasonNoteLeakFails(unittest.TestCase):
    """No item in identifiable_rejections may carry ``reason_note``."""

    def test_reason_note_in_item_is_an_error(self) -> None:
        payload = _good_summary()
        payload["identifiable_rejections"][0]["reason_note"] = (
            "Operator-only prose that must never be published."
        )
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("reason_note", joined)


class SourceFilesLeakFails(unittest.TestCase):
    """No item in identifiable_rejections may carry ``source_files``."""

    def test_source_files_in_item_is_an_error(self) -> None:
        payload = _good_summary()
        payload["identifiable_rejections"][0]["source_files"] = [
            "artifacts/some_local_only_path.csv",
        ]
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("source_files", joined)


class WrongDecisionCountFails(unittest.TestCase):
    """decision_counts must match the entries' decisions exactly."""

    def test_decision_counts_mismatch(self) -> None:
        payload = _good_summary()
        payload["summary"]["decision_counts"] = {
            "rejected": 99,
            "deferred_methodology_lesson": 3,
        }
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("decision_counts", joined)

    def test_stage_counts_mismatch(self) -> None:
        payload = _good_summary()
        payload["summary"]["stage_counts"] = {
            "post_validation": 1,
            "post_screen_canonical_test": 1,
        }
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("stage_counts", joined)

    def test_reason_category_counts_mismatch(self) -> None:
        payload = _good_summary()
        payload["summary"]["reason_category_counts"] = {
            "source_quality": 1,
            "g5_not_significant": 1,
        }
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("reason_category_counts", joined)


class DeferredMethodologyTickersFixed(unittest.TestCase):
    """CENX, NUE, NOC must each be deferred_methodology_lesson."""

    def test_cenx_must_be_deferred(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "CENX":
                item["decision"] = "rejected"
                # keep the summary counts consistent so this is the
                # *only* failure:
                payload["summary"]["decision_counts"] = {
                    "rejected": 2,
                    "deferred_methodology_lesson": 2,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("CENX", joined)
        self.assertIn("deferred_methodology_lesson", joined)

    def test_nue_must_be_deferred(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "NUE":
                item["decision"] = "rejected"
                payload["summary"]["decision_counts"] = {
                    "rejected": 2,
                    "deferred_methodology_lesson": 2,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("NUE", joined)

    def test_noc_must_be_deferred(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "NOC":
                item["decision"] = "rejected"
                payload["summary"]["decision_counts"] = {
                    "rejected": 2,
                    "deferred_methodology_lesson": 2,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("NOC", joined)


class AmatRequirements(unittest.TestCase):
    """AMAT must be rejected/post_screen_canonical_test/g5; pool=true."""

    def test_missing_phase2_pool_count_fails(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "AMAT":
                item.pop("phase2_pool_count", None)
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("AMAT", joined)
        self.assertIn("phase2_pool_count", joined.lower())

    def test_amat_phase2_pool_count_false_fails(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "AMAT":
                item["phase2_pool_count"] = False
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])

    def test_amat_wrong_decision_fails(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "AMAT":
                item["decision"] = "deferred_methodology_lesson"
                payload["summary"]["decision_counts"] = {
                    "rejected": 0,
                    "deferred_methodology_lesson": 4,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("AMAT", joined)
        self.assertIn("rejected", joined)

    def test_amat_wrong_stage_fails(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "AMAT":
                item["stage"] = "post_validation"
                payload["summary"]["stage_counts"] = {
                    "post_validation": 4,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("AMAT", joined)
        self.assertIn("post_screen_canonical_test", joined)

    def test_amat_wrong_reason_category_fails(self) -> None:
        payload = _good_summary()
        for item in payload["identifiable_rejections"]:
            if item["primary_ticker"] == "AMAT":
                item["reason_category"] = "source_quality"
                payload["summary"]["reason_category_counts"] = {
                    "source_quality": 4,
                }
                break
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"])
        self.assertIn("AMAT", joined)
        self.assertIn("g5_not_significant", joined)


class ForbiddenLanguageFails(unittest.TestCase):
    """No overclaim tokens in tracked summary text."""

    def _set_note(self, payload: dict[str, Any], text: str) -> None:
        payload["notes"] = [text]

    def test_proof_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "This is proof of the result.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        self.assertIn(
            "proof",
            " ".join(report["errors"]).lower(),
        )

    def test_proven_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "Mechanism proven across the cohort.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])

    def test_validated_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "Validated by canonical test.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])

    def test_alpha_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "Generated alpha across the names.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])

    def test_prediction_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "Used the prediction to size.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])

    def test_predicted_fails(self) -> None:
        payload = _good_summary()
        self._set_note(payload, "Predicted positive reaction.")
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])


class StatsLeakFails(unittest.TestCase):
    """No statistics/returns/p-values may appear in the tracked summary."""

    def test_p_value_key_in_item_fails(self) -> None:
        payload = _good_summary()
        payload["identifiable_rejections"][0]["p_value"] = 0.06
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("p_value", joined)

    def test_t_stat_key_in_item_fails(self) -> None:
        payload = _good_summary()
        payload["identifiable_rejections"][0]["t_stat"] = 1.43
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("t_stat", joined)

    def test_return_value_key_in_item_fails(self) -> None:
        payload = _good_summary()
        payload["identifiable_rejections"][0]["cumulative_return"] = 0.012
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("cumulative_return", joined)

    def test_p_value_token_in_notes_fails(self) -> None:
        payload = _good_summary()
        payload["notes"] = ["p-value 0.06 not significant"]
        path = _write_tmp(payload)
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])


class MalformedJsonFailsClearly(unittest.TestCase):
    """A non-JSON artifact must yield a clear, structured error."""

    def test_invalid_json(self) -> None:
        path = _write_tmp("{ not valid json :")
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])
        # Envelope shape still intact:
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        joined = " ".join(report["errors"]).lower()
        self.assertTrue(
            "json" in joined or "parse" in joined,
            msg=f"errors should mention JSON parsing: {report['errors']}",
        )

    def test_missing_path(self) -> None:
        report = _run("/no/such/path/rejection.json")
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertTrue(
            "exist" in joined or "not found" in joined,
            msg=f"errors should mention nonexistent path: {report['errors']}",
        )

    def test_root_not_object_fails(self) -> None:
        path = _write_tmp([1, 2, 3])
        try:
            report = _run(path)
        finally:
            os.unlink(path)
        self.assertFalse(report["ok"])


class CliJsonOutput(unittest.TestCase):
    """The --json CLI surface emits parseable JSON and returns 0 on ok."""

    def test_cli_json_round_trip(self) -> None:
        path = _write_tmp(_good_summary())
        try:
            import io
            buf = io.StringIO()
            rc = cli.main(["--artifact", path, "--json"], out=buf)
            self.assertEqual(rc, 0)
            doc = json.loads(buf.getvalue())
            self.assertTrue(doc["ok"])
            self.assertEqual(set(doc.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(path)

    def test_cli_nonzero_on_error(self) -> None:
        payload = _good_summary()
        payload["summary"]["identifiable_rejections_count"] = 99
        path = _write_tmp(payload)
        try:
            import io
            buf = io.StringIO()
            rc = cli.main(["--artifact", path, "--json"], out=buf)
            self.assertNotEqual(rc, 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

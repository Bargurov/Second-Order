"""Tests for ``scripts/validate_freeze_candidate_artifact.py``.

Pin the contract:

* Read-only validator.  No DB writes, no provider, no LLM, no
  ``yfinance``, no FastAPI surface.  The artifact file is never
  mutated by validation — every byte stays where it was on disk.
* Validates ``artifacts/freeze_candidate_evidence.json`` (or any
  artifact passed via ``--artifact``) against the freeze-candidate
  schema before downstream demo-backend consumption.
* Output dict has EXACTLY these 5 keys::

    ok, artifact_path, records_count, errors, warnings

* ``ok`` is True iff ``errors`` is empty.
* The validator must accept the current live artifact at
  ``artifacts/freeze_candidate_evidence.json`` — if it rejects the
  live artifact, the validator is the suspect, not the artifact.
* Conservative wording.  The validator never calls the artifact
  "frozen"; ``artifact_type`` must read exactly
  ``freeze_candidate_evidence``.
* No banned overclaim tokens in ``limitations`` text:
  ``proof``, ``proven``, ``guaranteed``, ``alpha generated``,
  ``correct ticker``, ``automatically``, ``validated`` (as a
  standalone claim).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import validate_freeze_candidate_artifact as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "artifact_path",
    "records_count",
    "errors",
    "warnings",
)


_REQUIRED_RECORD_FIELDS = (
    "source",
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "mechanism_family",
    "horizon",
    "p_value",
    "fdr_q",
    "raw_p_candidate",
    "fdr_significant",
    "verdict",
)


_VALID_VERDICTS = (
    "fdr_significant",
    "raw_p_only_candidate",
    "inconclusive_fdr",
    "insufficient",
)


_VALID_BENCH_STATUSES = (
    "unknown",
    "blocked",
    "preview_ready",
    "comparison_uncomputable",
    "comparison_available",
)


_BANNED_LIMITATION_TOKENS = (
    "proof",
    "proven",
    "guaranteed",
    "alpha generated",
    "correct ticker",
    "automatically",
    "validated",
)


_LIVE_ARTIFACT_PATH = "artifacts/freeze_candidate_evidence.json"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _good_record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source":           "curated_stage_validation",
        "event_id":         30,
        "headline":         "Sample headline",
        "primary_ticker":   "XOM",
        "benchmark":        "SPY",
        "mechanism_family": "supply_shock",
        "horizon":          1,
        "p_value":          0.57,
        "fdr_q":            0.76,
        "raw_p_candidate":  False,
        "fdr_significant":  False,
        "verdict":          "inconclusive_fdr",
    }
    base.update(overrides)
    return base


def _good_artifact(**overrides: Any) -> dict[str, Any]:
    """Build a minimum-viable freeze-candidate artifact that the
    validator should accept."""
    base: dict[str, Any] = {
        "artifact_type": "freeze_candidate_evidence",
        "cohort_summary": {
            "total_records":          1,
            "fdr_significant_count":  0,
            "raw_p_candidate_count":  0,
            "events_evaluated":       1,
            "horizons_covered":       [1],
            "mechanism_families_covered": ["supply_shock"],
        },
        "records": [_good_record()],
        "benchmark_sensitivity_status": {
            "status":                    "comparison_uncomputable",
            "blocked_events":            [],
            "required_dates":            [],
            "local_backfill_available":  False,
            "online_backfill_required":  False,
            "comparison_summary":        {},
            "limitations":               [],
        },
        "duplicate_event_ids": [],
        "limitations": [
            "freeze-candidate only - awaiting operator approval before "
            "any downstream demo backend may consume this artifact.",
            "no FDR-significant claim is supported by this evidence "
            "set; every surfaced record is either raw-p-only candidate, "
            "inconclusive_fdr, or insufficient.",
        ],
    }
    base.update(overrides)
    return base


def _write_artifact(payload: dict[str, Any]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"freeze_candidate_test_{uuid.uuid4().hex}.json",
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
# --artifact required + file existence
# ---------------------------------------------------------------------------


class TestArtifactPathRequired(unittest.TestCase):
    def test_missing_path_returns_failure(self) -> None:
        report = cli.run_validate_freeze_candidate_artifact(
            artifact_path=None,
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "artifact" in e.lower() for e in report["errors"]
        ))

    def test_nonexistent_path_returns_failure(self) -> None:
        report = cli.run_validate_freeze_candidate_artifact(
            artifact_path="/nonexistent/freeze.json",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "does not exist" in e.lower() or "not found" in e.lower()
            for e in report["errors"]
        ))
        self.assertEqual(report["records_count"], 0)

    def test_malformed_json_returns_failure(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"freeze_bad_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["records_count"], 0)
            self.assertTrue(any(
                "json" in e.lower() for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_cli_without_artifact_exits_nonzero(self) -> None:
        buf = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--json"], out=buf)
        self.assertNotEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_good_artifact(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(report["ok"], report["errors"])
            self.assertEqual(report["records_count"], 1)
            self.assertEqual(report["artifact_path"], path)
        finally:
            os.unlink(path)

    def test_required_keys_on_failure(self) -> None:
        report = cli.run_validate_freeze_candidate_artifact(
            artifact_path="/missing/freeze.json",
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Required top-level keys
# ---------------------------------------------------------------------------


class TestTopLevelKeys(unittest.TestCase):
    def test_artifact_type_must_be_freeze_candidate_evidence(self) -> None:
        artifact = _good_artifact()
        artifact["artifact_type"] = "frozen_evidence"
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "artifact_type" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_missing_required_key_fails(self) -> None:
        for required in (
            "artifact_type", "cohort_summary", "records",
            "benchmark_sensitivity_status", "duplicate_event_ids",
            "limitations",
        ):
            with self.subTest(missing=required):
                artifact = _good_artifact()
                artifact.pop(required, None)
                path = _write_artifact(artifact)
                try:
                    report = cli.run_validate_freeze_candidate_artifact(
                        artifact_path=path,
                    )
                    self.assertFalse(report["ok"])
                    joined = " | ".join(report["errors"]).lower()
                    self.assertIn(required, joined)
                finally:
                    os.unlink(path)

    def test_records_must_be_list(self) -> None:
        artifact = _good_artifact()
        artifact["records"] = {"not": "a list"}
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "records" in e.lower() and "list" in e.lower()
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_cohort_summary_must_exist(self) -> None:
        artifact = _good_artifact()
        artifact["cohort_summary"] = None
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "cohort_summary" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


class TestRecordShape(unittest.TestCase):
    def test_missing_field_in_record_fails(self) -> None:
        for field in _REQUIRED_RECORD_FIELDS:
            with self.subTest(missing=field):
                rec = _good_record()
                rec.pop(field)
                artifact = _good_artifact(records=[rec])
                path = _write_artifact(artifact)
                try:
                    report = cli.run_validate_freeze_candidate_artifact(
                        artifact_path=path,
                    )
                    self.assertFalse(
                        report["ok"],
                        f"validator accepted record missing {field!r}",
                    )
                    joined = " | ".join(report["errors"]).lower()
                    self.assertIn(field, joined)
                finally:
                    os.unlink(path)

    def test_unknown_verdict_fails(self) -> None:
        rec = _good_record(verdict="approved")
        artifact = _good_artifact(records=[rec])
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "verdict" in e.lower() for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_each_valid_verdict_token_accepted(self) -> None:
        for verdict in _VALID_VERDICTS:
            with self.subTest(verdict=verdict):
                rec = _good_record(verdict=verdict)
                # raw_p_only_candidate must NOT also flag fdr_significant
                if verdict == "raw_p_only_candidate":
                    rec["raw_p_candidate"] = True
                    rec["fdr_significant"] = False
                if verdict == "fdr_significant":
                    rec["fdr_significant"] = True
                cohort = {
                    "total_records":          1,
                    "fdr_significant_count":  1 if verdict == "fdr_significant" else 0,
                    "raw_p_candidate_count":  1 if verdict == "raw_p_only_candidate" else 0,
                    "events_evaluated":       1,
                    "horizons_covered":       [1],
                    "mechanism_families_covered": ["supply_shock"],
                }
                artifact = _good_artifact(records=[rec], cohort_summary=cohort)
                if verdict != "fdr_significant":
                    # No-FDR caveat is required when fdr_significant_count==0.
                    pass  # _good_artifact already supplies it.
                else:
                    artifact["limitations"] = [
                        "freeze-candidate only - awaiting operator approval.",
                    ]
                path = _write_artifact(artifact)
                try:
                    report = cli.run_validate_freeze_candidate_artifact(
                        artifact_path=path,
                    )
                    self.assertTrue(
                        report["ok"],
                        f"valid verdict {verdict!r} rejected: "
                        f"{report['errors']}",
                    )
                finally:
                    os.unlink(path)


# ---------------------------------------------------------------------------
# fdr_significant_count consistency
# ---------------------------------------------------------------------------


class TestFdrSignificantCount(unittest.TestCase):
    def test_count_must_match_records(self) -> None:
        # Two FDR-significant records but cohort_summary says 0.
        rec1 = _good_record(verdict="fdr_significant", fdr_significant=True,
                            event_id=1)
        rec2 = _good_record(verdict="fdr_significant", fdr_significant=True,
                            event_id=2)
        artifact = _good_artifact(
            records=[rec1, rec2],
            cohort_summary={
                "total_records":          2,
                "fdr_significant_count":  0,    # wrong!
                "raw_p_candidate_count":  0,
                "events_evaluated":       2,
                "horizons_covered":       [1],
                "mechanism_families_covered": ["supply_shock"],
            },
        )
        artifact["limitations"] = [
            "freeze-candidate only - awaiting operator approval.",
            "no FDR-significant claim disclaimer placeholder.",
        ]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("fdr_significant_count", joined)
        finally:
            os.unlink(path)

    def test_raw_p_only_records_not_counted_as_fdr_significant(self) -> None:
        # A raw-p-only candidate flagged with fdr_significant=True is
        # forbidden: the validator must surface this contradiction.
        rec = _good_record(
            verdict="raw_p_only_candidate",
            raw_p_candidate=True,
            fdr_significant=True,    # contradiction!
        )
        artifact = _good_artifact(records=[rec])
        artifact["cohort_summary"]["raw_p_candidate_count"] = 1
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("raw_p_only_candidate", joined)
            self.assertIn("fdr_significant", joined)
        finally:
            os.unlink(path)

    def test_fdr_significant_verdict_requires_flag_true(self) -> None:
        # Symmetric guardrail: a record carrying verdict="fdr_significant"
        # but fdr_significant=False is internally inconsistent.  The
        # validator must surface it before the demo backend depends on
        # the count.
        rec = _good_record(
            verdict="fdr_significant",
            fdr_significant=False,    # contradiction!
        )
        artifact = _good_artifact(
            records=[rec],
            cohort_summary={
                "total_records":          1,
                "fdr_significant_count":  1,
                "raw_p_candidate_count":  0,
                "events_evaluated":       1,
                "horizons_covered":       [1],
                "mechanism_families_covered": ["supply_shock"],
            },
        )
        artifact["limitations"] = [
            "freeze-candidate only - awaiting operator approval.",
        ]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("fdr_significant", joined)
        finally:
            os.unlink(path)

    def test_count_matches_passes(self) -> None:
        rec = _good_record(verdict="fdr_significant", fdr_significant=True)
        artifact = _good_artifact(
            records=[rec],
            cohort_summary={
                "total_records":          1,
                "fdr_significant_count":  1,
                "raw_p_candidate_count":  0,
                "events_evaluated":       1,
                "horizons_covered":       [1],
                "mechanism_families_covered": ["supply_shock"],
            },
        )
        # With fdr_significant_count > 0 we no longer need the no-FDR
        # caveat, just the freeze-candidate-only disclaimer.
        artifact["limitations"] = [
            "freeze-candidate only - awaiting operator approval.",
        ]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# benchmark_sensitivity_status
# ---------------------------------------------------------------------------


class TestBenchmarkSensitivityStatus(unittest.TestCase):
    def test_each_valid_status_accepted(self) -> None:
        for status in _VALID_BENCH_STATUSES:
            with self.subTest(status=status):
                artifact = _good_artifact()
                artifact["benchmark_sensitivity_status"]["status"] = status
                path = _write_artifact(artifact)
                try:
                    report = cli.run_validate_freeze_candidate_artifact(
                        artifact_path=path,
                    )
                    self.assertTrue(
                        report["ok"],
                        f"valid status {status!r} rejected: "
                        f"{report['errors']}",
                    )
                finally:
                    os.unlink(path)

    def test_unknown_status_fails(self) -> None:
        artifact = _good_artifact()
        artifact["benchmark_sensitivity_status"]["status"] = "approved"
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "benchmark_sensitivity_status" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_missing_status_field_fails(self) -> None:
        artifact = _good_artifact()
        artifact["benchmark_sensitivity_status"].pop("status")
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "status" in e.lower() for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# duplicate_event_ids
# ---------------------------------------------------------------------------


class TestDuplicateEventIds(unittest.TestCase):
    def test_must_be_present(self) -> None:
        artifact = _good_artifact()
        artifact.pop("duplicate_event_ids")
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "duplicate_event_ids" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_present_as_list_passes(self) -> None:
        artifact = _good_artifact()
        artifact["duplicate_event_ids"] = [30]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Limitations / no-FDR caveat / overclaim language
# ---------------------------------------------------------------------------


class TestLimitations(unittest.TestCase):
    def test_no_fdr_caveat_required_when_count_zero(self) -> None:
        artifact = _good_artifact()
        # fdr_significant_count==0 (default) but the no-FDR caveat is
        # absent — the validator must error.
        artifact["limitations"] = [
            "freeze-candidate only - awaiting operator approval.",
        ]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("no fdr-significant", joined)
        finally:
            os.unlink(path)

    def test_no_fdr_caveat_not_required_when_count_positive(self) -> None:
        rec = _good_record(verdict="fdr_significant", fdr_significant=True)
        artifact = _good_artifact(
            records=[rec],
            cohort_summary={
                "total_records":          1,
                "fdr_significant_count":  1,
                "raw_p_candidate_count":  0,
                "events_evaluated":       1,
                "horizons_covered":       [1],
                "mechanism_families_covered": ["supply_shock"],
            },
        )
        artifact["limitations"] = [
            "freeze-candidate only - awaiting operator approval.",
        ]
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)

    def test_limitations_must_be_list_of_strings(self) -> None:
        artifact = _good_artifact()
        artifact["limitations"] = "this is a string, not a list"
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "limitations" in e.lower() and "list" in e.lower()
                for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_banned_overclaim_token_in_limitations_fails(self) -> None:
        for banned in _BANNED_LIMITATION_TOKENS:
            with self.subTest(banned=banned):
                artifact = _good_artifact()
                artifact["limitations"] = list(artifact["limitations"]) + [
                    f"this evidence is {banned} beyond reasonable doubt.",
                ]
                path = _write_artifact(artifact)
                try:
                    report = cli.run_validate_freeze_candidate_artifact(
                        artifact_path=path,
                    )
                    self.assertFalse(
                        report["ok"],
                        f"banned token {banned!r} accepted in "
                        f"limitations",
                    )
                    joined = " | ".join(report["errors"]).lower()
                    self.assertIn("limitations", joined)
                finally:
                    os.unlink(path)

    def test_clean_limitations_passes(self) -> None:
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            report = cli.run_validate_freeze_candidate_artifact(
                artifact_path=path,
            )
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_artifact_byte_identity_preserved(self) -> None:
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            before = _sha256(path)
            cli.run_validate_freeze_candidate_artifact(artifact_path=path)
            after = _sha256(path)
            self.assertEqual(
                before, after,
                "validator must not mutate the artifact file",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Live truth — the existing live artifact must validate cleanly
# ---------------------------------------------------------------------------


class TestLiveArtifactPasses(unittest.TestCase):
    def test_live_freeze_candidate_artifact_validates(self) -> None:
        if not Path(_LIVE_ARTIFACT_PATH).exists():
            self.skipTest(
                f"live artifact {_LIVE_ARTIFACT_PATH!r} not present"
            )
        report = cli.run_validate_freeze_candidate_artifact(
            artifact_path=_LIVE_ARTIFACT_PATH,
        )
        self.assertTrue(
            report["ok"],
            f"validator rejected the live artifact — likely a validator "
            f"bug: {report['errors']}",
        )
        self.assertGreater(report["records_count"], 0)


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"validator must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            rc, output = self._run([
                "--artifact", path, "--json",
            ])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(parsed["ok"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_text_render_does_not_crash(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            rc, output = self._run(["--artifact", path])
            self.assertEqual(rc, 0)
            self.assertIn("freeze-candidate", output.lower())
        finally:
            os.unlink(path)

    def test_main_returns_nonzero_when_invalid(self) -> None:
        artifact = _good_artifact()
        artifact["artifact_type"] = "frozen_evidence"
        path = _write_artifact(artifact)
        try:
            rc, output = self._run([
                "--artifact", path, "--json",
            ])
            parsed = json.loads(output)
            self.assertFalse(parsed["ok"])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

"""Tests for the tracked Section C demo artifact bundle.

Pin the contract that ``evidence_artifacts/section_c_v1/`` is a stable
on-disk demo input set the Section C demo backend can rely on even
when the operator's local ``artifacts/`` directory is empty or
untracked.

The bundle must:

* contain exactly the five whitelisted demo inputs plus a ``README.md``
  — never the whole local ``artifacts/`` tree;
* keep file sizes small (each file well under 1 MB) because the bundle
  is tracked in git;
* contain three artifact-backed Daily candidate JSON files with the
  four artifact-gate-enforced fields (``mechanism_family`` /
  ``primary_ticker`` / ``benchmark_ticker`` / ``candidate_id``)
  populated;
* contain a freeze-candidate evidence artifact whose top-level keys
  include the two distinct counts ``fdr_significant`` and
  ``raw_p_only_candidate`` (under ``verdict_counts``);
* contain a reviewed-candidates CSV with the operator-review header
  the worksheet pipeline produces;
* ship a ``README.md`` that states, verbatim, the four conservative
  framing points the demo language depends on:
    1. that this is a demo artifact bundle,
    2. that ``freeze_candidate_evidence.json`` is freeze-candidate
       evidence,
    3. that no FDR-significant claim is made unless the artifact
       itself supports one,
    4. that raw-p and FDR are separate measures,
    5. that the bundle is a local demo input and not final research
       truth.

Read-only by construction
-------------------------

The tests never spawn a subprocess, never read provider / LLM / DB,
never start a server, and never write files outside the test's own
``unittest`` scratch space.  Every assertion is a pure file-system
read on the tracked bundle directory.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "evidence_artifacts" / "section_c_v1"

_DAILY_FILES = (
    "analyzed_event_artifact_daily-demo-001.json",
    "analyzed_event_artifact_daily-demo-002.json",
    "analyzed_event_artifact_daily-demo-003.json",
)
_FREEZE_FILE = "freeze_candidate_evidence.json"
_CSV_FILE    = "daily_reviewed_candidates.csv"
_README_FILE = "README.md"

_REQUIRED_ARTIFACT_FIELDS = (
    "candidate_id",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)

# Soft cap so a sloppy paste of a multi-MB artifact does not silently
# enter the tracked bundle.  None of the legitimate inputs approaches
# this.
_MAX_FILE_BYTES = 1_000_000


# ---------------------------------------------------------------------------
# Directory shape
# ---------------------------------------------------------------------------


class BundleDirectoryShapeTests(unittest.TestCase):
    """The tracked bundle directory contains exactly the expected files."""

    def test_bundle_directory_exists(self) -> None:
        self.assertTrue(
            BUNDLE_DIR.is_dir(),
            f"demo artifact bundle directory missing: {BUNDLE_DIR}",
        )

    def test_all_required_files_present(self) -> None:
        expected = {*_DAILY_FILES, _FREEZE_FILE, _CSV_FILE, _README_FILE}
        for name in expected:
            with self.subTest(file=name):
                self.assertTrue(
                    (BUNDLE_DIR / name).is_file(),
                    f"required bundle file missing: {name}",
                )

    def test_no_unexpected_files_in_bundle(self) -> None:
        expected = {*_DAILY_FILES, _FREEZE_FILE, _CSV_FILE, _README_FILE}
        actual = {p.name for p in BUNDLE_DIR.iterdir() if p.is_file()}
        unexpected = actual - expected
        self.assertEqual(
            unexpected,
            set(),
            (
                "Bundle directory must contain only the five whitelisted "
                f"demo inputs plus README.md; found extra files: {unexpected}"
            ),
        )

    def test_every_file_is_small(self) -> None:
        for p in BUNDLE_DIR.iterdir():
            if not p.is_file():
                continue
            with self.subTest(file=p.name):
                size = p.stat().st_size
                self.assertLess(
                    size,
                    _MAX_FILE_BYTES,
                    (
                        f"{p.name} is {size} bytes; tracked bundle files "
                        f"should stay well under {_MAX_FILE_BYTES} bytes"
                    ),
                )


# ---------------------------------------------------------------------------
# Daily artifact JSON shape
# ---------------------------------------------------------------------------


class DailyArtifactShapeTests(unittest.TestCase):
    """Every Daily artifact carries the four gate-enforced fields."""

    def test_each_daily_artifact_is_valid_json(self) -> None:
        for name in _DAILY_FILES:
            with self.subTest(file=name):
                payload = json.loads(
                    (BUNDLE_DIR / name).read_text(encoding="utf-8"),
                )
                self.assertIsInstance(payload, dict)

    def test_each_daily_artifact_has_gate_enforced_fields(self) -> None:
        for name in _DAILY_FILES:
            payload = json.loads(
                (BUNDLE_DIR / name).read_text(encoding="utf-8"),
            )
            for field in _REQUIRED_ARTIFACT_FIELDS:
                with self.subTest(file=name, field=field):
                    self.assertIn(field, payload)
                    self.assertTrue(
                        isinstance(payload[field], str)
                        and payload[field].strip(),
                        f"{name}: field {field!r} must be a non-empty string",
                    )

    def test_each_daily_artifact_has_consistent_candidate_id(self) -> None:
        for name in _DAILY_FILES:
            payload = json.loads(
                (BUNDLE_DIR / name).read_text(encoding="utf-8"),
            )
            with self.subTest(file=name):
                self.assertIn(payload["candidate_id"], name)


# ---------------------------------------------------------------------------
# Freeze-candidate evidence shape
# ---------------------------------------------------------------------------


class FreezeCandidateEvidenceShapeTests(unittest.TestCase):
    """The freeze-candidate evidence artifact keeps raw-p and FDR distinct."""

    def setUp(self) -> None:
        self.payload = json.loads(
            (BUNDLE_DIR / _FREEZE_FILE).read_text(encoding="utf-8"),
        )

    def test_freeze_candidate_evidence_is_valid_json(self) -> None:
        self.assertIsInstance(self.payload, dict)

    def test_freeze_candidate_evidence_has_verdict_counts(self) -> None:
        self.assertIn("verdict_counts", self.payload)
        self.assertIsInstance(self.payload["verdict_counts"], dict)

    def test_raw_p_and_fdr_are_separate_buckets(self) -> None:
        counts = self.payload["verdict_counts"]
        self.assertIn(
            "fdr_significant",
            counts,
            "verdict_counts must keep fdr_significant as its own bucket",
        )
        self.assertIn(
            "raw_p_only_candidate",
            counts,
            (
                "verdict_counts must keep raw_p_only_candidate as its "
                "own bucket distinct from fdr_significant"
            ),
        )


# ---------------------------------------------------------------------------
# Reviewed-candidates CSV shape
# ---------------------------------------------------------------------------


class DailyReviewedCandidatesCsvShapeTests(unittest.TestCase):
    """The reviewed-candidate worksheet keeps the operator-review header."""

    def test_csv_header_carries_operator_review_columns(self) -> None:
        with (BUNDLE_DIR / _CSV_FILE).open(
            encoding="utf-8", newline="",
        ) as fh:
            reader = csv.reader(fh)
            header = next(reader)
        for col in (
            "candidate_id",
            "headline",
            "mechanism_family",
            "primary_ticker",
            "benchmark_ticker",
            "include_in_daily_section_c",
        ):
            with self.subTest(column=col):
                self.assertIn(col, header)


# ---------------------------------------------------------------------------
# README conservative language
# ---------------------------------------------------------------------------


class ReadmeConservativeLanguageTests(unittest.TestCase):
    """The README states the four pinned conservative framing points."""

    def setUp(self) -> None:
        self.text = (BUNDLE_DIR / _README_FILE).read_text(encoding="utf-8")
        self.lower = self.text.lower()

    def test_readme_states_demo_artifact_bundle(self) -> None:
        self.assertIn("demo artifact bundle", self.lower)

    def test_readme_states_freeze_candidate_evidence(self) -> None:
        self.assertIn("freeze-candidate evidence", self.lower)

    def test_readme_states_no_fdr_significant_claims_unless_artifact_says_so(
        self,
    ) -> None:
        # The README must qualify FDR-significant language with the
        # underlying artifact's own record — never assert one
        # unconditionally.
        self.assertIn("fdr-significant", self.lower)
        self.assertTrue(
            "no fdr-significant" in self.lower,
            "README must state that no FDR-significant claim is made",
        )

    def test_readme_states_raw_p_and_fdr_are_separate(self) -> None:
        self.assertIn("raw-p", self.lower)
        self.assertIn("fdr", self.lower)
        self.assertIn("separate", self.lower)

    def test_readme_states_local_demo_input_not_research_truth(self) -> None:
        self.assertIn("demo input", self.lower)
        self.assertIn("not final research truth", self.lower)

    def test_readme_does_not_leak_overclaim_vocabulary(self) -> None:
        # Word-boundary checks so legitimate vocabulary (e.g. the heading
        # "Provenance") does not collide with an overclaim substring
        # like "proven".
        banned_words = (
            r"\bproven\b",
            r"\bguaranteed\b",
            r"\balpha generated\b",
            r"\bvalidated trade\b",
            r"\bproduction[- ]ready\b",
            r"\bdemo[- ]ready\b",
        )
        for pattern in banned_words:
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, self.lower),
                    f"overclaim vocabulary {pattern!r} leaked into README",
                )


if __name__ == "__main__":
    unittest.main()

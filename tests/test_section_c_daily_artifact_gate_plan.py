"""Tests for ``scripts/section_c_daily_artifact_gate_plan.py``.

Pin the contract:

* Read-only planner.  No DB writes, no provider, no LLM, no FastAPI.
  The planner emits a stable design — no live state is read at
  runtime.
* Output dict has EXACTLY these 11 keys::

    ok, proposed_gate, required_fields, candidate_sources,
    rejected_sources, implementation_targets, example_allowed_case,
    example_blocked_case, false_positive_risks, warnings, errors

* ``proposed_gate`` carries the spec-pinned eight keys and names the
  four required artifact fields (``mechanism_family``,
  ``primary_ticker``, ``benchmark_ticker``, ``market_relevance``)
  in its ``required_field_names`` list.
* ``required_fields`` lists those four fields in spec order, each
  with a non-empty rationale.  An additional ``candidate_id`` field
  is allowed (it links inbox rows to artifacts).
* ``rejected_sources`` MUST include ``fuzzy_headline_matching`` with
  an explicit reason — this is the spec invariant the planner exists
  to enforce.
* ``implementation_targets`` names real production files in the repo
  (``news_fetch.py``, ``routes/movers.py``, the manual worksheet
  generator) and a concrete responsibility per path.  The planner
  does NOT edit those files.
* ``example_blocked_case`` describes a row that is HELD for review
  rather than surfaced (``promotion_outcome == "held_for_review"``);
  ``example_allowed_case`` describes a row that is admitted.
* Conservative wording: banned tokens absent from any prose the
  planner emits.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_daily_artifact_gate_plan as cli  # noqa: E402

# Shared subprocess import-isolation helper.
sys.path.insert(0, os.path.dirname(__file__))
from _import_isolation_check import assert_module_import_does_not_leak  # noqa: E402,I100


_REQUIRED_TOP_KEYS = (
    "ok",
    "proposed_gate",
    "required_fields",
    "candidate_sources",
    "rejected_sources",
    "implementation_targets",
    "example_allowed_case",
    "example_blocked_case",
    "false_positive_risks",
    "warnings",
    "errors",
)


_PROPOSED_GATE_KEYS = (
    "gate_id",
    "scope",
    "behavior",
    "required_artifact_kind",
    "required_field_names",
    "held_for_review_behavior",
    "fuzzy_matching_default",
    "promotion_criteria",
)


_REQUIRED_FIELD_KEYS = ("field", "type", "rationale")


_CANDIDATE_SOURCE_KEYS = (
    "source_id",
    "surface",
    "description",
    "operator_review_required",
)


_REJECTED_SOURCE_KEYS = (
    "source_id",
    "description",
    "reason_rejected",
)


_IMPLEMENTATION_TARGET_KEYS = (
    "path",
    "responsibility",
    "note",
)


_EXAMPLE_ALLOWED_KEYS = (
    "inbox_headline",
    "artifact_present",
    "artifact_fields_present",
    "promotion_outcome",
    "rationale",
)


_EXAMPLE_BLOCKED_KEYS = (
    "inbox_headline",
    "artifact_present",
    "missing_fields",
    "promotion_outcome",
    "rationale",
)


# The four spec-pinned required fields.  The order is the order the
# task spec lists them; the planner emits them in this order.
_SPEC_REQUIRED_FIELDS = (
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "broken",
    "wrong",
    "must fix",
    "guaranteed",
    "automatically",
    "definitely",
    "causes",
    "causation",
    "will assign",
    "will enrich",
    "correct mechanism",
    "rule guarantees",
    "alpha generated",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_top_level_keys(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_proposed_gate_carries_spec_keys(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        gate = report["proposed_gate"]
        self.assertEqual(set(gate.keys()), set(_PROPOSED_GATE_KEYS))

    def test_required_fields_entry_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertIsInstance(report["required_fields"], list)
        self.assertGreater(len(report["required_fields"]), 0)
        for entry in report["required_fields"]:
            self.assertEqual(set(entry.keys()), set(_REQUIRED_FIELD_KEYS))
            self.assertIsInstance(entry["field"], str)
            self.assertTrue(entry["field"])
            self.assertIsInstance(entry["rationale"], str)
            self.assertTrue(entry["rationale"])

    def test_candidate_sources_entry_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertIsInstance(report["candidate_sources"], list)
        self.assertGreater(len(report["candidate_sources"]), 0)
        for entry in report["candidate_sources"]:
            self.assertEqual(set(entry.keys()), set(_CANDIDATE_SOURCE_KEYS))
            self.assertIsInstance(entry["operator_review_required"], bool)

    def test_rejected_sources_entry_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertIsInstance(report["rejected_sources"], list)
        self.assertGreater(len(report["rejected_sources"]), 0)
        for entry in report["rejected_sources"]:
            self.assertEqual(set(entry.keys()), set(_REJECTED_SOURCE_KEYS))
            self.assertIsInstance(entry["reason_rejected"], str)
            self.assertTrue(entry["reason_rejected"])

    def test_implementation_targets_entry_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertIsInstance(report["implementation_targets"], list)
        self.assertGreater(len(report["implementation_targets"]), 0)
        for entry in report["implementation_targets"]:
            self.assertEqual(
                set(entry.keys()), set(_IMPLEMENTATION_TARGET_KEYS),
            )

    def test_example_allowed_case_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertEqual(
            set(report["example_allowed_case"].keys()),
            set(_EXAMPLE_ALLOWED_KEYS),
        )

    def test_example_blocked_case_shape(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        self.assertEqual(
            set(report["example_blocked_case"].keys()),
            set(_EXAMPLE_BLOCKED_KEYS),
        )


# ---------------------------------------------------------------------------
# Required-fields invariant: the four spec-pinned fields appear in
# order and the proposed_gate.required_field_names mirrors them.
# ---------------------------------------------------------------------------


class TestRequiredFieldsInvariant(unittest.TestCase):
    def test_four_spec_fields_present_in_order(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        names = [
            entry["field"] for entry in report["required_fields"]
        ]
        # The four spec fields appear, in spec order, as the FIRST
        # four entries.  Additional fields (candidate_id) may follow.
        self.assertEqual(names[:4], list(_SPEC_REQUIRED_FIELDS))

    def test_proposed_gate_names_match_required_fields(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        gate_names = list(
            report["proposed_gate"]["required_field_names"]
        )
        field_names = [
            entry["field"] for entry in report["required_fields"]
        ]
        # Every name in proposed_gate.required_field_names is a real
        # required_fields entry, in the same order.
        self.assertEqual(gate_names, field_names)

    def test_proposed_gate_behavior_mentions_section_c(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        gate = report["proposed_gate"]
        self.assertIn("section c", gate["behavior"].lower())
        # Behavior should reference the artifact concept, not just the gate name.
        self.assertIn("artifact", gate["behavior"].lower())

    def test_held_for_review_behavior_describes_no_surfacing(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        held = report["proposed_gate"]["held_for_review_behavior"].lower()
        # A held row is NOT surfaced — the prose must say so.
        self.assertTrue(
            "not surface" in held
            or "would not show" in held
            or "not show" in held
            or "would not surface" in held,
            f"held_for_review_behavior prose does not state the row "
            f"is kept off the surface: {held!r}",
        )
        # And the operator review queue / worklist must be named.
        self.assertTrue(
            "review" in held and "worklist" in held,
            f"held_for_review_behavior prose does not name the "
            f"operator review worklist: {held!r}",
        )


# ---------------------------------------------------------------------------
# Required behavior: fuzzy headline matching MUST appear in
# rejected_sources with a real reason.
# ---------------------------------------------------------------------------


class TestRejectedSourcesPinFuzzyMatching(unittest.TestCase):
    def test_fuzzy_headline_matching_is_rejected(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        rejected_ids = {
            entry["source_id"] for entry in report["rejected_sources"]
        }
        self.assertIn("fuzzy_headline_matching", rejected_ids)

    def test_fuzzy_rejection_carries_real_reason(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        fuzzy = next(
            entry for entry in report["rejected_sources"]
            if entry["source_id"] == "fuzzy_headline_matching"
        )
        # The reason must mention the auditability gap that
        # motivates the rejection.
        self.assertIn("auditable", fuzzy["reason_rejected"].lower())

    def test_proposed_gate_fuzzy_default_says_rejected(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        body = report["proposed_gate"]["fuzzy_matching_default"].lower()
        self.assertIn("reject", body)


# ---------------------------------------------------------------------------
# Required behavior: implementation_targets names production files
# the gate would touch — without editing them.
# ---------------------------------------------------------------------------


class TestImplementationTargets(unittest.TestCase):
    def test_targets_name_real_repo_paths(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        target_paths = {
            entry["path"] for entry in report["implementation_targets"]
        }
        # The two production-critical paths must appear: the inbox
        # loader and the movers route.
        self.assertIn("news_fetch.py", target_paths)
        self.assertIn("routes/movers.py", target_paths)

    def test_targets_name_artifact_emitter_workflow(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        target_paths = {
            entry["path"] for entry in report["implementation_targets"]
        }
        # The worksheet generator is the existing operator-facing
        # surface that would emit the analyzed-event artifact.
        self.assertIn(
            "scripts/manual_event_intake_worksheet.py",
            target_paths,
        )

    def test_targets_carry_non_empty_responsibility_and_note(
        self,
    ) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        for entry in report["implementation_targets"]:
            self.assertTrue(
                entry["responsibility"],
                f"target {entry['path']!r} has empty responsibility",
            )
            self.assertTrue(
                entry["note"],
                f"target {entry['path']!r} has empty note",
            )


# ---------------------------------------------------------------------------
# Required behavior: example_allowed_case and example_blocked_case
# describe the gate's outcomes.
# ---------------------------------------------------------------------------


class TestWorkedExamples(unittest.TestCase):
    def test_allowed_case_outcome_is_admitted(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        allowed = report["example_allowed_case"]
        self.assertEqual(allowed["promotion_outcome"], "admitted")
        self.assertTrue(allowed["artifact_present"])
        # Every required field must appear in artifact_fields_present.
        for f in _SPEC_REQUIRED_FIELDS:
            self.assertIn(f, allowed["artifact_fields_present"])

    def test_blocked_case_outcome_is_held_for_review(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        blocked = report["example_blocked_case"]
        self.assertEqual(
            blocked["promotion_outcome"], "held_for_review",
        )
        # The blocked example must name the missing fields.
        self.assertIsInstance(blocked["missing_fields"], list)
        self.assertGreater(len(blocked["missing_fields"]), 0)


# ---------------------------------------------------------------------------
# Candidate sources MUST require operator review.
# ---------------------------------------------------------------------------


class TestCandidateSourcesRequireReview(unittest.TestCase):
    def test_every_candidate_source_requires_operator_review(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        for entry in report["candidate_sources"]:
            self.assertTrue(
                entry["operator_review_required"],
                f"candidate source {entry['source_id']!r} does not "
                f"require operator review; the gate would inherit an "
                f"unreviewed artifact source",
            )

    def test_no_candidate_source_is_fuzzy_or_llm(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        for entry in report["candidate_sources"]:
            blob = " ".join([
                entry.get("source_id", ""),
                entry.get("description", ""),
                entry.get("surface", ""),
            ]).lower()
            self.assertNotIn("fuzzy", blob)
            # "llm" appears as a token; allow it inside longer words
            # such as "all means" by checking word-boundary-ish.
            self.assertNotIn(" llm ", " " + blob + " ")


# ---------------------------------------------------------------------------
# Conservative wording — no banned token leaks into any prose the
# planner emits.
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _all_prose(self, report: dict[str, Any]) -> str:
        parts: list[str] = []
        parts.extend(report.get("warnings") or [])
        parts.extend(report.get("errors") or [])
        parts.extend(report.get("false_positive_risks") or [])
        gate = report["proposed_gate"]
        parts.append(gate.get("behavior", ""))
        parts.append(gate.get("scope", ""))
        parts.append(gate.get("required_artifact_kind", ""))
        parts.append(gate.get("held_for_review_behavior", ""))
        parts.append(gate.get("fuzzy_matching_default", ""))
        parts.extend(gate.get("promotion_criteria") or [])
        for f in report.get("required_fields") or []:
            parts.append(f.get("rationale", ""))
        for s in report.get("candidate_sources") or []:
            parts.append(s.get("description", ""))
        for s in report.get("rejected_sources") or []:
            parts.append(s.get("description", ""))
            parts.append(s.get("reason_rejected", ""))
        for t in report.get("implementation_targets") or []:
            parts.append(t.get("note", ""))
        for k in ("example_allowed_case", "example_blocked_case"):
            ex = report.get(k) or {}
            parts.append(ex.get("rationale", ""))
        return " ".join(s for s in parts if isinstance(s, str)).lower()

    def test_no_banned_tokens_in_prose(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_plan()
        blob = self._all_prose(report)
        for banned in _BANNED_WORDS:
            self.assertNotIn(
                banned, blob,
                f"banned token {banned!r} surfaced in planner prose",
            )


# ---------------------------------------------------------------------------
# Read-only contract: no DB write / provider / LLM / FastAPI surface
# is loaded by importing the planner.
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_import_does_not_leak_paid_surfaces(self) -> None:
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.section_c_daily_artifact_gate_plan",
            blocked=(
                "yfinance",
                "fastapi",
                "api",
                "market_data",
                "news_relevance",
                "news_fetch",
            ),
            blocked_starts_with=("routes.",),
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_main_emits_valid_json(self) -> None:
        buf = io.StringIO()
        rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))

    def test_text_main_renders_compact_summary(self) -> None:
        buf = io.StringIO()
        rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Section C", text)
        self.assertIn("Gate id:", text)
        self.assertIn("Required fields", text)

    def test_output_path_writes_json_envelope(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_daily_artifact_gate_plan_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.run_section_c_daily_artifact_gate_plan(
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

    def test_main_returns_zero_on_happy_path(self) -> None:
        # The planner emits a stable design with no errors today —
        # the CLI exits 0.
        buf = io.StringIO()
        rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

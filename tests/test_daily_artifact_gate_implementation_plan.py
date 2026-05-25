"""Tests for ``scripts/daily_artifact_gate_implementation_plan.py``.

Pin the contract:

* Read-only planner.  No DB writes, no provider, no LLM, no FastAPI.
  The planner emits a stable design — no live state is read at
  runtime.
* Output dict has EXACTLY these 11 keys::

    ok, target_files, proposed_data_contract,
    proposed_filter_behavior, allowed_daily_candidate_shape,
    blocked_daily_candidate_shape, migration_steps, tests_to_add,
    false_positive_risks, warnings, errors

* ``target_files`` names the exact production files an implementer
  would inspect or change later (``news_fetch.py``,
  ``news_inbox.json``, ``routes/movers.py``,
  ``scripts/manual_event_intake_worksheet.py``, ``artifacts/``).  Each
  entry carries a non-empty ``role`` and ``change_summary``.
* ``proposed_data_contract`` lists the four spec-pinned required
  fields (``mechanism_family``, ``primary_ticker``,
  ``benchmark_ticker``, ``market_relevance``) in spec order, each
  with a non-empty ``source`` describing where the value comes from.
  A ``link_field`` (``candidate_id``) carries inbox-to-artifact
  linkage.
* ``proposed_filter_behavior`` describes a promotion-boundary gate
  that admits rows whose artifact carries every required field and
  HOLDS rows whose artifact is missing or incomplete.  The behavior
  prose names Section C and the artifact concept.
* ``proposed_filter_behavior.fuzzy_matching_default`` MUST say the
  fuzzy / LLM path is rejected as a default source — this is the
  spec invariant the planner exists to enforce.
* ``allowed_daily_candidate_shape`` and
  ``blocked_daily_candidate_shape`` describe the two outcomes; the
  blocked outcome is ``"held_for_review"``, not ``"dropped"``.
* ``migration_steps`` is a non-empty ordered list where each step
  carries a stable ``step`` integer (starting at 1), a non-empty
  ``title``, a non-empty ``description``, and a non-empty list of
  ``files`` it touches.
* ``tests_to_add`` is a non-empty list naming the tests the
  implementer would add later, each with a non-empty ``scope`` and
  ``description``.
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

from scripts import daily_artifact_gate_implementation_plan as cli  # noqa: E402

# Shared subprocess import-isolation helper.
sys.path.insert(0, os.path.dirname(__file__))
from _import_isolation_check import assert_module_import_does_not_leak  # noqa: E402,I100


_REQUIRED_TOP_KEYS = (
    "ok",
    "target_files",
    "proposed_data_contract",
    "proposed_filter_behavior",
    "allowed_daily_candidate_shape",
    "blocked_daily_candidate_shape",
    "migration_steps",
    "tests_to_add",
    "false_positive_risks",
    "warnings",
    "errors",
)


_TARGET_FILE_KEYS = ("path", "role", "change_summary")


_DATA_CONTRACT_KEYS = (
    "artifact_kind",
    "required_fields",
    "link_field",
    "storage_location",
)


_DATA_FIELD_KEYS = ("name", "type", "source", "rationale")


_LINK_FIELD_KEYS = ("name", "type", "rationale")


_FILTER_BEHAVIOR_KEYS = (
    "where",
    "when",
    "behavior_on_complete_artifact",
    "behavior_on_missing_artifact",
    "behavior_on_incomplete_artifact",
    "fuzzy_matching_default",
)


_ALLOWED_SHAPE_KEYS = (
    "inbox_row",
    "artifact",
    "promotion_outcome",
    "rationale",
)


_BLOCKED_SHAPE_KEYS = (
    "inbox_row",
    "artifact",
    "missing_fields",
    "promotion_outcome",
    "rationale",
)


_MIGRATION_STEP_KEYS = (
    "step",
    "title",
    "description",
    "files",
    "verification",
)


_TESTS_TO_ADD_KEYS = ("test_id", "scope", "description", "asserts")


# The four spec-pinned required fields, in spec order.
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
        report = cli.run_daily_artifact_gate_implementation_plan()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_target_files_entry_shape(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        self.assertIsInstance(report["target_files"], list)
        self.assertGreater(len(report["target_files"]), 0)
        for entry in report["target_files"]:
            self.assertEqual(set(entry.keys()), set(_TARGET_FILE_KEYS))
            self.assertIsInstance(entry["path"], str)
            self.assertTrue(entry["path"])
            self.assertTrue(entry["role"])
            self.assertTrue(entry["change_summary"])

    def test_proposed_data_contract_keys(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        contract = report["proposed_data_contract"]
        self.assertEqual(set(contract.keys()), set(_DATA_CONTRACT_KEYS))

    def test_data_contract_required_fields_shape(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        fields = report["proposed_data_contract"]["required_fields"]
        self.assertIsInstance(fields, list)
        self.assertGreater(len(fields), 0)
        for entry in fields:
            self.assertEqual(set(entry.keys()), set(_DATA_FIELD_KEYS))
            for k in _DATA_FIELD_KEYS:
                self.assertIsInstance(entry[k], str)
                self.assertTrue(entry[k])

    def test_data_contract_link_field_shape(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        link = report["proposed_data_contract"]["link_field"]
        self.assertEqual(set(link.keys()), set(_LINK_FIELD_KEYS))
        self.assertEqual(link["name"], "candidate_id")

    def test_proposed_filter_behavior_keys(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        behavior = report["proposed_filter_behavior"]
        self.assertEqual(set(behavior.keys()), set(_FILTER_BEHAVIOR_KEYS))
        for k in _FILTER_BEHAVIOR_KEYS:
            self.assertIsInstance(behavior[k], str)
            self.assertTrue(behavior[k])

    def test_allowed_shape_keys(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        self.assertEqual(
            set(report["allowed_daily_candidate_shape"].keys()),
            set(_ALLOWED_SHAPE_KEYS),
        )

    def test_blocked_shape_keys(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        self.assertEqual(
            set(report["blocked_daily_candidate_shape"].keys()),
            set(_BLOCKED_SHAPE_KEYS),
        )

    def test_migration_steps_entry_shape(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        steps = report["migration_steps"]
        self.assertIsInstance(steps, list)
        self.assertGreater(len(steps), 0)
        for entry in steps:
            self.assertEqual(set(entry.keys()), set(_MIGRATION_STEP_KEYS))
            self.assertIsInstance(entry["step"], int)
            self.assertTrue(entry["title"])
            self.assertTrue(entry["description"])
            self.assertIsInstance(entry["files"], list)
            self.assertGreater(len(entry["files"]), 0)
            self.assertTrue(entry["verification"])

    def test_tests_to_add_entry_shape(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        tests = report["tests_to_add"]
        self.assertIsInstance(tests, list)
        self.assertGreater(len(tests), 0)
        for entry in tests:
            self.assertEqual(set(entry.keys()), set(_TESTS_TO_ADD_KEYS))
            self.assertTrue(entry["test_id"])
            self.assertTrue(entry["scope"])
            self.assertTrue(entry["description"])
            self.assertIsInstance(entry["asserts"], list)
            self.assertGreater(len(entry["asserts"]), 0)


# ---------------------------------------------------------------------------
# Target files: must name the exact likely production files.
# ---------------------------------------------------------------------------


class TestTargetFiles(unittest.TestCase):
    def test_inbox_loader_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        paths = {entry["path"] for entry in report["target_files"]}
        self.assertIn("news_fetch.py", paths)

    def test_inbox_file_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        paths = {entry["path"] for entry in report["target_files"]}
        self.assertIn("news_inbox.json", paths)

    def test_movers_route_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        paths = {entry["path"] for entry in report["target_files"]}
        self.assertIn("routes/movers.py", paths)

    def test_manual_worksheet_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        paths = {entry["path"] for entry in report["target_files"]}
        self.assertIn(
            "scripts/manual_event_intake_worksheet.py", paths,
        )

    def test_artifacts_storage_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        paths = {entry["path"] for entry in report["target_files"]}
        self.assertIn("artifacts/", paths)


# ---------------------------------------------------------------------------
# Data contract: the four spec-pinned fields appear in spec order
# and the source string names an operator-reviewed origin.
# ---------------------------------------------------------------------------


class TestDataContract(unittest.TestCase):
    def test_four_spec_fields_present_in_order(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        names = [
            entry["name"]
            for entry in report["proposed_data_contract"]["required_fields"]
        ]
        self.assertEqual(names[:4], list(_SPEC_REQUIRED_FIELDS))

    def test_mechanism_family_source_names_operator_artifact(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        mech = next(
            f
            for f in report["proposed_data_contract"]["required_fields"]
            if f["name"] == "mechanism_family"
        )
        source = mech["source"].lower()
        # The source must name the reviewed-artifact origin and the
        # operator review step — not "events table lookup".
        self.assertTrue(
            "artifact" in source,
            f"mechanism_family.source must name the artifact origin: "
            f"{source!r}",
        )
        self.assertTrue(
            "operator" in source or "worksheet" in source,
            f"mechanism_family.source must name the operator-reviewed "
            f"workflow: {source!r}",
        )

    def test_artifact_kind_is_named(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        kind = report["proposed_data_contract"]["artifact_kind"]
        self.assertIsInstance(kind, str)
        self.assertIn("analyzed_event_artifact", kind)

    def test_storage_location_under_artifacts(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        loc = report["proposed_data_contract"]["storage_location"]
        self.assertIsInstance(loc, str)
        self.assertIn("artifacts/", loc)


# ---------------------------------------------------------------------------
# Filter behavior: rejects fuzzy default and surfaces the
# held-for-review outcome.
# ---------------------------------------------------------------------------


class TestFilterBehavior(unittest.TestCase):
    def test_fuzzy_matching_default_says_rejected(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        body = report["proposed_filter_behavior"][
            "fuzzy_matching_default"
        ].lower()
        self.assertIn("reject", body)

    def test_behavior_prose_mentions_section_c_and_artifact(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        where = report["proposed_filter_behavior"]["where"].lower()
        self.assertIn("section c", where)

    def test_missing_artifact_holds_for_review(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        missing = report["proposed_filter_behavior"][
            "behavior_on_missing_artifact"
        ].lower()
        # An inbox row without an artifact MUST be held for review,
        # not dropped silently — the prose must say so.
        self.assertIn("held", missing)
        self.assertIn("review", missing)

    def test_incomplete_artifact_holds_for_review(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        incomplete = report["proposed_filter_behavior"][
            "behavior_on_incomplete_artifact"
        ].lower()
        self.assertIn("held", incomplete)
        self.assertIn("review", incomplete)

    def test_complete_artifact_admitted(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        complete = report["proposed_filter_behavior"][
            "behavior_on_complete_artifact"
        ].lower()
        self.assertIn("admit", complete)

    def test_promotion_boundary_not_ingestion(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        when = report["proposed_filter_behavior"]["when"].lower()
        # The gate runs at the promotion boundary, not at ingestion —
        # the inbox loader keeps writing rows; the gate just filters.
        self.assertIn("promotion", when)


# ---------------------------------------------------------------------------
# Worked candidate shapes.
# ---------------------------------------------------------------------------


class TestCandidateShapes(unittest.TestCase):
    def test_allowed_outcome_is_admitted(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        allowed = report["allowed_daily_candidate_shape"]
        self.assertEqual(allowed["promotion_outcome"], "admitted")
        self.assertIsInstance(allowed["inbox_row"], dict)
        self.assertIsInstance(allowed["artifact"], dict)
        # The artifact must carry every spec-pinned required field.
        for f in _SPEC_REQUIRED_FIELDS:
            self.assertIn(f, allowed["artifact"])

    def test_blocked_outcome_is_held_for_review(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        blocked = report["blocked_daily_candidate_shape"]
        self.assertEqual(blocked["promotion_outcome"], "held_for_review")
        self.assertIsInstance(blocked["inbox_row"], dict)
        # The blocked example must name missing fields.
        self.assertIsInstance(blocked["missing_fields"], list)
        self.assertGreater(len(blocked["missing_fields"]), 0)

    def test_allowed_inbox_row_carries_candidate_id(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        allowed = report["allowed_daily_candidate_shape"]
        self.assertIn("candidate_id", allowed["inbox_row"])


# ---------------------------------------------------------------------------
# Migration steps: an ordered sequence with at least the inbox-id
# step before the gate-wiring step.
# ---------------------------------------------------------------------------


class TestMigrationSteps(unittest.TestCase):
    def test_steps_numbered_starting_at_one_strictly_increasing(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        steps = report["migration_steps"]
        numbers = [entry["step"] for entry in steps]
        self.assertEqual(numbers[0], 1)
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(len(set(numbers)), len(numbers))

    def test_id_tag_step_precedes_gate_wiring_step(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        steps = report["migration_steps"]
        # The candidate_id-tagging step must come before any step
        # whose files include routes/movers.py.  Otherwise the gate
        # would land with no link between inbox rows and artifacts.
        id_step: int | None = None
        gate_step: int | None = None
        for entry in steps:
            text = (entry["title"] + " " + entry["description"]).lower()
            if "candidate_id" in text and id_step is None:
                id_step = entry["step"]
            if "routes/movers.py" in entry["files"] and gate_step is None:
                gate_step = entry["step"]
        self.assertIsNotNone(
            id_step,
            "no migration step mentions candidate_id; the gate cannot "
            "link inbox rows to artifacts without one",
        )
        self.assertIsNotNone(
            gate_step,
            "no migration step touches routes/movers.py; the gate has "
            "nowhere to land",
        )
        self.assertLess(
            id_step, gate_step,
            "candidate_id tagging step must precede the gate-wiring "
            "step",
        )

    def test_artifact_emitter_step_precedes_gate_wiring_step(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        steps = report["migration_steps"]
        emit_step: int | None = None
        gate_step: int | None = None
        for entry in steps:
            if (
                "scripts/manual_event_intake_worksheet.py" in entry["files"]
                and emit_step is None
            ):
                emit_step = entry["step"]
            if "routes/movers.py" in entry["files"] and gate_step is None:
                gate_step = entry["step"]
        self.assertIsNotNone(
            emit_step,
            "no migration step touches the manual-worksheet artifact "
            "emitter; the gate would have no inputs",
        )
        self.assertIsNotNone(gate_step)
        self.assertLess(
            emit_step, gate_step,
            "artifact emitter step must precede the gate-wiring step",
        )


# ---------------------------------------------------------------------------
# Tests to add: every entry names a real assertion the implementer
# would write later.  No production-code change is proposed here.
# ---------------------------------------------------------------------------


class TestTestsToAdd(unittest.TestCase):
    def test_at_least_one_test_targets_routes_movers(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        blob = " ".join(
            (entry["scope"] + " " + entry["description"]).lower()
            for entry in report["tests_to_add"]
        )
        self.assertIn("routes/movers.py", blob)

    def test_at_least_one_test_targets_held_for_review(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
        blob = " ".join(
            (entry["scope"] + " " + entry["description"]).lower()
            for entry in report["tests_to_add"]
        )
        self.assertIn("held_for_review", blob.replace(" ", "_"))


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
        behavior = report["proposed_filter_behavior"]
        for k in _FILTER_BEHAVIOR_KEYS:
            parts.append(behavior.get(k, ""))
        contract = report["proposed_data_contract"]
        parts.append(contract.get("artifact_kind", ""))
        parts.append(contract.get("storage_location", ""))
        for f in contract.get("required_fields") or []:
            parts.append(f.get("source", ""))
            parts.append(f.get("rationale", ""))
        link = contract.get("link_field") or {}
        parts.append(link.get("rationale", ""))
        for t in report.get("target_files") or []:
            parts.append(t.get("role", ""))
            parts.append(t.get("change_summary", ""))
        for s in report.get("migration_steps") or []:
            parts.append(s.get("title", ""))
            parts.append(s.get("description", ""))
            parts.append(s.get("verification", ""))
        for t in report.get("tests_to_add") or []:
            parts.append(t.get("scope", ""))
            parts.append(t.get("description", ""))
            for a in t.get("asserts") or []:
                parts.append(a)
        for k in (
            "allowed_daily_candidate_shape",
            "blocked_daily_candidate_shape",
        ):
            ex = report.get(k) or {}
            parts.append(ex.get("rationale", ""))
        return " ".join(s for s in parts if isinstance(s, str)).lower()

    def test_no_banned_tokens_in_prose(self) -> None:
        report = cli.run_daily_artifact_gate_implementation_plan()
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
            module_name="scripts.daily_artifact_gate_implementation_plan",
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
        self.assertIn("Daily artifact-gate", text)
        self.assertIn("Target files", text)
        self.assertIn("Migration steps", text)

    def test_output_path_writes_json_envelope(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"daily_artifact_gate_impl_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.run_daily_artifact_gate_implementation_plan(
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
        buf = io.StringIO()
        rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

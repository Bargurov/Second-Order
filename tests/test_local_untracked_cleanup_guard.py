"""Tests for ``scripts/local_untracked_cleanup_guard.py``.

The cleanup guard inspects the repo's untracked files and produces
a per-path operator decision list.  It must be read-only:

* never ``git add`` / ``git commit`` / ``git push``
* never delete, rename, or mutate any file (only ``--output`` writes,
  and only when explicitly passed)
* never connect to a DB or import yfinance / market_data / paid
  provider / LLM / FastAPI surfaces

The guard classifies each untracked path into EXACTLY one of four
operator-decision categories:

    - keep_local
    - future_commit_candidate
    - safe_to_delete_manually
    - risky_or_unknown

This is intentionally narrower than the grouping report: the guard
produces a decision list, not a commit plan.  The operator owns
every action.

Pinned contract:

* JSON envelope has EXACTLY these 8 keys::

    ok, repo_status_summary, decisions, by_category,
    recommended_next_action, generated_at_marker, warnings, errors

* Each decision dict carries EXACTLY these 4 keys::

    path, category, rationale, operator_action

* The four canonical categories appear under ``by_category`` even
  when empty, so the operator sees a complete decision surface.

* Each untracked path appears in EXACTLY one decisions entry and
  EXACTLY one by_category bucket.

* Modified-file lines (``M `` / `` M``) are ignored — the guard
  groups only ``??`` entries.

* Conservative wording — banned tokens absent from every rendered
  string.

* The script source carries no ``git add`` / ``git commit`` /
  ``git push`` call site, and no ``os.remove`` / ``shutil.rmtree``
  / ``Path.unlink`` call site.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import local_untracked_cleanup_guard as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Canonical fixture — mirrors the actual `git status --porcelain` output
# captured at the time this guard was written.
# ---------------------------------------------------------------------------


_STATUS_LINES: tuple[str, ...] = (
    "?? DEMO_SCRIPT_SECTION_C.md",
    "?? ULTRA_REVIEW.md",
    "?? artifacts/",
    "?? examples/",
    "?? scripts/curated_archive_status.py",
    "?? scripts/curated_event_loader.py",
    "?? scripts/curated_event_validator.py",
    "?? scripts/daily_artifact_gate_implementation_plan.py",
    "?? scripts/demo_readiness_blocker_inspection.py",
    "?? scripts/section_c_daily_artifact_gate_plan.py",
    "?? scripts/section_c_demo_readiness_checklist.py",
    "?? scripts/short_horizon_repair_apply_smoke.py",
    "?? scripts/untracked_tool_grouping_report.py",
    "?? scripts/validate_freeze_candidate_artifact.py",
    "?? scripts/xle_benchmark_sensitivity_compare_smoke.py",
    "?? short_horizon_repair_packet.csv",
    "?? tests/test_curated_archive_status.py",
    "?? tests/test_curated_event_loader.py",
    "?? tests/test_curated_event_validator.py",
    "?? tests/test_daily_artifact_gate_implementation_plan.py",
    "?? tests/test_demo_readiness_blocker_inspection.py",
    "?? tests/test_manual_event_intake_worksheet.py",
    "?? tests/test_section_c_daily_artifact_gate_plan.py",
    "?? tests/test_section_c_demo_readiness_checklist.py",
    "?? tests/test_short_horizon_repair_apply_smoke.py",
    "?? tests/test_untracked_tool_grouping_report.py",
    "?? tests/test_validate_freeze_candidate_artifact.py",
    "?? tests/test_xle_benchmark_sensitivity_compare_smoke.py",
)


_REQUIRED_TOP_KEYS = (
    "ok",
    "repo_status_summary",
    "decisions",
    "by_category",
    "recommended_next_action",
    "generated_at_marker",
    "warnings",
    "errors",
)


_REQUIRED_DECISION_KEYS = (
    "path",
    "category",
    "rationale",
    "operator_action",
)


_REQUIRED_CATEGORIES = (
    "keep_local",
    "future_commit_candidate",
    "safe_to_delete_manually",
    "risky_or_unknown",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "approved",
    "production ready",
    "production-ready",
    "definitely",
    # The guard must never claim it staged, committed, or deleted
    # anything on the operator's behalf.
    "staged automatically",
    "committed automatically",
    "deleted automatically",
)


# Spec-pinned per-path expectations.
_EXPECTED_KEEP_LOCAL: frozenset[str] = frozenset({
    "DEMO_SCRIPT_SECTION_C.md",
    "ULTRA_REVIEW.md",
    "artifacts/",
    "examples/",
})


_EXPECTED_FUTURE_COMMIT: frozenset[str] = frozenset({
    "scripts/curated_archive_status.py",
    "scripts/curated_event_loader.py",
    "scripts/curated_event_validator.py",
    "tests/test_curated_archive_status.py",
    "tests/test_curated_event_loader.py",
    "tests/test_curated_event_validator.py",
})


_EXPECTED_DELETE: frozenset[str] = frozenset({
    "scripts/daily_artifact_gate_implementation_plan.py",
    "scripts/demo_readiness_blocker_inspection.py",
    "scripts/section_c_daily_artifact_gate_plan.py",
    "scripts/section_c_demo_readiness_checklist.py",
    "scripts/untracked_tool_grouping_report.py",
    "tests/test_daily_artifact_gate_implementation_plan.py",
    "tests/test_demo_readiness_blocker_inspection.py",
    "tests/test_section_c_daily_artifact_gate_plan.py",
    "tests/test_section_c_demo_readiness_checklist.py",
    "tests/test_untracked_tool_grouping_report.py",
    "short_horizon_repair_packet.csv",
})


_EXPECTED_RISKY: frozenset[str] = frozenset({
    "scripts/short_horizon_repair_apply_smoke.py",
    "scripts/validate_freeze_candidate_artifact.py",
    "scripts/xle_benchmark_sensitivity_compare_smoke.py",
    "tests/test_manual_event_intake_worksheet.py",
    "tests/test_short_horizon_repair_apply_smoke.py",
    "tests/test_validate_freeze_candidate_artifact.py",
    "tests/test_xle_benchmark_sensitivity_compare_smoke.py",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    *,
    status_lines: tuple[str, ...] | list[str] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    return cli.run_local_untracked_cleanup_guard(
        status_lines=list(status_lines) if status_lines is not None
        else list(_STATUS_LINES),
        output_path=output_path,
    )


def _all_strings(node: Any) -> list[str]:
    """Recursively collect every string inside a JSON-ish payload."""
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            out.extend(_all_strings(v))
    elif isinstance(node, (list, tuple)):
        for item in node:
            out.extend(_all_strings(item))
    return out


def _decision_for(report: dict[str, Any], path: str) -> dict[str, Any]:
    for entry in report["decisions"]:
        if isinstance(entry, dict) and entry.get("path") == path:
            return entry
    raise AssertionError(
        f"path {path!r} not found in decisions"
    )


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):

    def test_top_level_keys_exactly(self) -> None:
        report = _run()
        self.assertEqual(
            sorted(report.keys()), sorted(_REQUIRED_TOP_KEYS),
            f"expected exactly {_REQUIRED_TOP_KEYS}, got {sorted(report.keys())}",
        )

    def test_ok_is_true_on_canonical_input(self) -> None:
        report = _run()
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_repo_status_summary_carries_counts(self) -> None:
        report = _run()
        summary = report["repo_status_summary"]
        self.assertIsInstance(summary, dict)
        # 28 untracked lines in the canonical fixture.
        self.assertEqual(summary.get("untracked_line_count"), 28)
        self.assertEqual(
            summary.get("keep_local_count"), len(_EXPECTED_KEEP_LOCAL),
        )
        self.assertEqual(
            summary.get("future_commit_candidate_count"),
            len(_EXPECTED_FUTURE_COMMIT),
        )
        self.assertEqual(
            summary.get("safe_to_delete_manually_count"),
            len(_EXPECTED_DELETE),
        )
        self.assertEqual(
            summary.get("risky_or_unknown_count"),
            len(_EXPECTED_RISKY),
        )

    def test_recommended_next_action_is_conservative_string(self) -> None:
        report = _run()
        action = report["recommended_next_action"]
        self.assertIsInstance(action, str)
        self.assertGreater(len(action), 10)
        lower = action.lower()
        self.assertTrue(
            "operator" in lower or "review" in lower or "inspect" in lower,
            f"recommended_next_action does not surface operator review: {action!r}",
        )


# ---------------------------------------------------------------------------
# Decision shape and total coverage
# ---------------------------------------------------------------------------


class TestDecisionShape(unittest.TestCase):

    def test_every_untracked_path_has_one_decision(self) -> None:
        report = _run()
        decisions = report["decisions"]
        self.assertIsInstance(decisions, list)
        paths_seen = [d["path"] for d in decisions]
        # Total decisions must equal total untracked paths.
        self.assertEqual(
            len(decisions),
            len(_STATUS_LINES),
            f"expected {len(_STATUS_LINES)} decisions, got {len(decisions)}",
        )
        # No duplicates.
        self.assertEqual(
            len(paths_seen), len(set(paths_seen)),
            f"duplicate paths in decisions: {paths_seen!r}",
        )

    def test_each_decision_carries_required_keys(self) -> None:
        report = _run()
        for entry in report["decisions"]:
            self.assertIsInstance(entry, dict)
            self.assertEqual(
                sorted(entry.keys()), sorted(_REQUIRED_DECISION_KEYS),
                f"decision for {entry.get('path')!r} has wrong keys: "
                f"{sorted(entry.keys())}",
            )

    def test_each_decision_category_is_canonical(self) -> None:
        report = _run()
        for entry in report["decisions"]:
            self.assertIn(
                entry["category"], _REQUIRED_CATEGORIES,
                f"unknown category for {entry['path']!r}: {entry['category']!r}",
            )

    def test_each_decision_rationale_is_non_empty_string(self) -> None:
        report = _run()
        for entry in report["decisions"]:
            self.assertIsInstance(entry["rationale"], str)
            self.assertGreater(
                len(entry["rationale"]), 5,
                f"rationale for {entry['path']!r} too short: "
                f"{entry['rationale']!r}",
            )

    def test_each_decision_operator_action_is_non_empty_string(self) -> None:
        report = _run()
        for entry in report["decisions"]:
            self.assertIsInstance(entry["operator_action"], str)
            self.assertGreater(
                len(entry["operator_action"]), 5,
                f"operator_action for {entry['path']!r} too short: "
                f"{entry['operator_action']!r}",
            )


# ---------------------------------------------------------------------------
# by_category coverage
# ---------------------------------------------------------------------------


class TestByCategory(unittest.TestCase):

    def test_all_four_categories_present(self) -> None:
        report = _run()
        bc = report["by_category"]
        self.assertIsInstance(bc, dict)
        self.assertEqual(
            sorted(bc.keys()), sorted(_REQUIRED_CATEGORIES),
            f"by_category keys mismatch: {sorted(bc.keys())}",
        )

    def test_category_lists_match_decisions(self) -> None:
        report = _run()
        bc = report["by_category"]
        for cat in _REQUIRED_CATEGORIES:
            from_bucket = set(bc[cat])
            from_decisions = {
                d["path"] for d in report["decisions"]
                if d["category"] == cat
            }
            self.assertEqual(
                from_bucket, from_decisions,
                f"by_category[{cat!r}] disagrees with decisions: "
                f"bucket={sorted(from_bucket)} vs "
                f"decisions={sorted(from_decisions)}",
            )

    def test_path_appears_in_exactly_one_bucket(self) -> None:
        report = _run()
        bc = report["by_category"]
        all_buckets = [(p, c) for c, paths in bc.items() for p in paths]
        paths_only = [p for p, _ in all_buckets]
        self.assertEqual(
            len(paths_only), len(set(paths_only)),
            f"path appears in more than one bucket: {sorted(paths_only)}",
        )


# ---------------------------------------------------------------------------
# Pinned per-path categorisation
# ---------------------------------------------------------------------------


class TestKeepLocalAssignment(unittest.TestCase):

    def test_artifacts_dir_is_keep_local(self) -> None:
        report = _run()
        d = _decision_for(report, "artifacts/")
        self.assertEqual(d["category"], "keep_local")

    def test_demo_script_section_c_is_keep_local(self) -> None:
        report = _run()
        d = _decision_for(report, "DEMO_SCRIPT_SECTION_C.md")
        self.assertEqual(d["category"], "keep_local")

    def test_ultra_review_is_keep_local(self) -> None:
        report = _run()
        d = _decision_for(report, "ULTRA_REVIEW.md")
        self.assertEqual(d["category"], "keep_local")
        # Per spec: operator may also delete manually.
        action = d["operator_action"].lower()
        self.assertTrue(
            "delete" in action or "manual" in action or "leave" in action,
            f"ULTRA_REVIEW.md operator_action should mention manual delete "
            f"or leave: {d['operator_action']!r}",
        )

    def test_examples_dir_is_keep_local(self) -> None:
        report = _run()
        d = _decision_for(report, "examples/")
        self.assertEqual(d["category"], "keep_local")
        # Per spec: defer unless tied to curated loader commit.
        rationale = d["rationale"].lower()
        self.assertIn("curated", rationale)

    def test_keep_local_bucket_matches_expected_set(self) -> None:
        report = _run()
        self.assertEqual(
            set(report["by_category"]["keep_local"]),
            _EXPECTED_KEEP_LOCAL,
        )


class TestFutureCommitCandidateAssignment(unittest.TestCase):

    def test_curated_loader_is_future_commit_candidate(self) -> None:
        report = _run()
        d = _decision_for(report, "scripts/curated_event_loader.py")
        self.assertEqual(d["category"], "future_commit_candidate")

    def test_curated_validator_is_future_commit_candidate(self) -> None:
        report = _run()
        d = _decision_for(report, "scripts/curated_event_validator.py")
        self.assertEqual(d["category"], "future_commit_candidate")

    def test_curated_archive_status_is_future_commit_candidate(self) -> None:
        report = _run()
        d = _decision_for(report, "scripts/curated_archive_status.py")
        self.assertEqual(d["category"], "future_commit_candidate")

    def test_curated_tests_are_future_commit_candidate(self) -> None:
        report = _run()
        for path in (
            "tests/test_curated_event_loader.py",
            "tests/test_curated_event_validator.py",
            "tests/test_curated_archive_status.py",
        ):
            d = _decision_for(report, path)
            self.assertEqual(
                d["category"], "future_commit_candidate",
                f"{path!r} not flagged as future_commit_candidate",
            )

    def test_future_commit_bucket_matches_expected_set(self) -> None:
        report = _run()
        self.assertEqual(
            set(report["by_category"]["future_commit_candidate"]),
            _EXPECTED_FUTURE_COMMIT,
        )


class TestSafeToDeleteManuallyAssignment(unittest.TestCase):

    def test_planning_scripts_are_delete_candidates(self) -> None:
        report = _run()
        for path in (
            "scripts/daily_artifact_gate_implementation_plan.py",
            "scripts/demo_readiness_blocker_inspection.py",
            "scripts/section_c_daily_artifact_gate_plan.py",
            "scripts/section_c_demo_readiness_checklist.py",
            "scripts/untracked_tool_grouping_report.py",
        ):
            d = _decision_for(report, path)
            self.assertEqual(
                d["category"], "safe_to_delete_manually",
                f"{path!r} should be safe_to_delete_manually",
            )

    def test_planning_tests_are_delete_candidates(self) -> None:
        report = _run()
        for path in (
            "tests/test_daily_artifact_gate_implementation_plan.py",
            "tests/test_demo_readiness_blocker_inspection.py",
            "tests/test_section_c_daily_artifact_gate_plan.py",
            "tests/test_section_c_demo_readiness_checklist.py",
            "tests/test_untracked_tool_grouping_report.py",
        ):
            d = _decision_for(report, path)
            self.assertEqual(
                d["category"], "safe_to_delete_manually",
                f"{path!r} should be safe_to_delete_manually",
            )

    def test_short_horizon_packet_csv_is_delete_candidate(self) -> None:
        report = _run()
        d = _decision_for(report, "short_horizon_repair_packet.csv")
        self.assertEqual(d["category"], "safe_to_delete_manually")
        action = d["operator_action"].lower()
        self.assertTrue(
            "delete" in action or "archive" in action,
            f"short_horizon_repair_packet.csv operator_action should "
            f"mention delete or archive: {d['operator_action']!r}",
        )

    def test_delete_bucket_matches_expected_set(self) -> None:
        report = _run()
        self.assertEqual(
            set(report["by_category"]["safe_to_delete_manually"]),
            _EXPECTED_DELETE,
        )

    def test_delete_action_is_manual_only(self) -> None:
        # The guard must never instruct deletion to happen on its own.
        report = _run()
        for path in report["by_category"]["safe_to_delete_manually"]:
            d = _decision_for(report, path)
            action = d["operator_action"].lower()
            self.assertIn(
                "manual", action,
                f"{path!r} operator_action does not flag the delete as "
                f"manual: {d['operator_action']!r}",
            )


class TestRiskyOrUnknownAssignment(unittest.TestCase):

    def test_unspec_smoke_scripts_are_risky(self) -> None:
        # Smoke / validator surfaces are not explicitly addressed in
        # the guard spec — the conservative default is risky_or_unknown.
        report = _run()
        for path in (
            "scripts/short_horizon_repair_apply_smoke.py",
            "scripts/validate_freeze_candidate_artifact.py",
            "scripts/xle_benchmark_sensitivity_compare_smoke.py",
        ):
            d = _decision_for(report, path)
            self.assertEqual(
                d["category"], "risky_or_unknown",
                f"{path!r} should fall under risky_or_unknown",
            )

    def test_unspec_smoke_tests_are_risky(self) -> None:
        report = _run()
        for path in (
            "tests/test_short_horizon_repair_apply_smoke.py",
            "tests/test_validate_freeze_candidate_artifact.py",
            "tests/test_xle_benchmark_sensitivity_compare_smoke.py",
        ):
            d = _decision_for(report, path)
            self.assertEqual(
                d["category"], "risky_or_unknown",
                f"{path!r} should fall under risky_or_unknown",
            )

    def test_orphan_test_is_risky(self) -> None:
        # tests/test_manual_event_intake_worksheet.py has no companion
        # script in the untracked set — the operator should see this
        # surfaced rather than silently bucketed.
        report = _run()
        d = _decision_for(
            report,
            "tests/test_manual_event_intake_worksheet.py",
        )
        self.assertEqual(d["category"], "risky_or_unknown")

    def test_risky_bucket_matches_expected_set(self) -> None:
        report = _run()
        self.assertEqual(
            set(report["by_category"]["risky_or_unknown"]),
            _EXPECTED_RISKY,
        )

    def test_risky_action_directs_operator_to_inspect(self) -> None:
        report = _run()
        for path in report["by_category"]["risky_or_unknown"]:
            d = _decision_for(report, path)
            action = d["operator_action"].lower()
            self.assertTrue(
                "inspect" in action or "review" in action or "decide" in action,
                f"{path!r} operator_action should direct manual review: "
                f"{d['operator_action']!r}",
            )


# ---------------------------------------------------------------------------
# Unknown paths fall through to risky_or_unknown
# ---------------------------------------------------------------------------


class TestUnknownPathFallsThrough(unittest.TestCase):

    def test_unspec_path_is_risky_or_unknown(self) -> None:
        report = _run(status_lines=[
            "?? scripts/totally_new_unspec_tool.py",
        ])
        d = _decision_for(report, "scripts/totally_new_unspec_tool.py")
        self.assertEqual(d["category"], "risky_or_unknown")
        # The guard refuses to take a stance — that refusal is its
        # whole job for unknown paths.
        rationale = d["rationale"].lower()
        self.assertTrue(
            "unknown" in rationale or "operator" in rationale
            or "inspect" in rationale or "review" in rationale,
            f"unknown-path rationale should flag operator review: "
            f"{d['rationale']!r}",
        )


# ---------------------------------------------------------------------------
# Status parsing — modified files ignored, empty input handled
# ---------------------------------------------------------------------------


class TestStatusParsing(unittest.TestCase):

    def test_modified_lines_are_ignored(self) -> None:
        # `git status --porcelain` uses ' M' / 'M ' / 'MM' for
        # modified files — the guard must only consume '??' entries.
        lines = list(_STATUS_LINES) + [
            " M scripts/already_tracked.py",
            "M  routes/movers.py",
            "MM frontend/src/App.tsx",
        ]
        report = _run(status_lines=lines)
        paths_seen = {d["path"] for d in report["decisions"]}
        self.assertNotIn("scripts/already_tracked.py", paths_seen)
        self.assertNotIn("routes/movers.py", paths_seen)
        self.assertNotIn("frontend/src/App.tsx", paths_seen)

    def test_empty_status_yields_empty_decisions(self) -> None:
        report = _run(status_lines=[])
        self.assertEqual(report["decisions"], [])
        for cat in _REQUIRED_CATEGORIES:
            self.assertEqual(report["by_category"][cat], [])
        self.assertTrue(report["ok"])

    def test_blank_and_garbage_lines_are_ignored(self) -> None:
        report = _run(status_lines=[
            "",
            "   ",
            "not a porcelain line",
            "?? DEMO_SCRIPT_SECTION_C.md",
        ])
        paths_seen = {d["path"] for d in report["decisions"]}
        self.assertEqual(paths_seen, {"DEMO_SCRIPT_SECTION_C.md"})


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):

    def test_banned_tokens_absent_from_every_string(self) -> None:
        report = _run()
        for s in _all_strings(report):
            lower = s.lower()
            for banned in _BANNED_WORDS:
                self.assertNotIn(
                    banned, lower,
                    f"banned token {banned!r} found in string: {s!r}",
                )


# ---------------------------------------------------------------------------
# Read-only — source-level assertions
# ---------------------------------------------------------------------------


class TestReadOnlySourceLevel(unittest.TestCase):
    """Verify the script never *calls* git add / commit / push or any
    filesystem-delete API.  The docstring may legitimately *name* these
    operations when documenting what the guard refuses to do, so we
    look for call-site patterns instead of substring sweeps.
    """

    def _source(self) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "local_untracked_cleanup_guard.py"
        )
        return path.read_text(encoding="utf-8")

    def _forbidden_git_patterns(self, verb: str) -> tuple[str, ...]:
        return (
            f'"git", "{verb}"',
            f"'git', '{verb}'",
            f'"git {verb}"',
            f"'git {verb}'",
        )

    def test_source_has_no_git_add_call_site(self) -> None:
        text = self._source().lower()
        for pat in self._forbidden_git_patterns("add"):
            self.assertNotIn(pat.lower(), text)

    def test_source_has_no_git_commit_call_site(self) -> None:
        text = self._source().lower()
        for pat in self._forbidden_git_patterns("commit"):
            self.assertNotIn(pat.lower(), text)

    def test_source_has_no_git_push_call_site(self) -> None:
        text = self._source().lower()
        for pat in self._forbidden_git_patterns("push"):
            self.assertNotIn(pat.lower(), text)

    def test_source_has_no_filesystem_delete_call_site(self) -> None:
        text = self._source()
        # Call-site patterns — never the bare words inside docstrings.
        for forbidden in (
            "os.remove(",
            "os.unlink(",
            "shutil.rmtree(",
            ".unlink(",
            "Path.unlink",
        ):
            self.assertNotIn(
                forbidden, text,
                f"forbidden filesystem-delete call site seen: {forbidden!r}",
            )

    def test_source_has_no_paid_or_fastapi_surface(self) -> None:
        text = self._source().lower()
        for banned in (
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "from fastapi",
            "import fastapi",
            "openai",
            "anthropic",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden import seen in script: {banned!r}",
            )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):

    def test_main_json_emits_envelope_to_stdout(self) -> None:
        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.txt"
            status_file.write_text(
                "\n".join(_STATUS_LINES) + "\n", encoding="utf-8",
            )
            rc = cli.main(
                ["--json", "--status-file", str(status_file)],
                out=buf,
            )
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(
            sorted(payload.keys()), sorted(_REQUIRED_TOP_KEYS),
        )

    def test_no_filesystem_side_effect_when_output_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.txt"
            status_file.write_text(
                "\n".join(_STATUS_LINES) + "\n", encoding="utf-8",
            )
            sentinel_dir = Path(tmp) / "expected_empty"
            sentinel_dir.mkdir()
            buf = StringIO()
            rc = cli.main(
                ["--json", "--status-file", str(status_file)],
                out=buf,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(list(sentinel_dir.iterdir()), [])

    def test_output_flag_writes_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.txt"
            status_file.write_text(
                "\n".join(_STATUS_LINES) + "\n", encoding="utf-8",
            )
            out_path = Path(tmp) / "report.json"
            buf = StringIO()
            rc = cli.main(
                [
                    "--json",
                    "--status-file", str(status_file),
                    "--output", str(out_path),
                ],
                out=buf,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.is_file())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(payload.keys()), sorted(_REQUIRED_TOP_KEYS),
            )

    def test_text_render_mentions_each_category(self) -> None:
        # When `--json` is omitted the CLI emits a human-readable
        # render; it should label all four categories.
        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.txt"
            status_file.write_text(
                "\n".join(_STATUS_LINES) + "\n", encoding="utf-8",
            )
            rc = cli.main(
                ["--status-file", str(status_file)],
                out=buf,
            )
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        for cat in _REQUIRED_CATEGORIES:
            self.assertIn(cat, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

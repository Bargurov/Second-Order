"""Tests for ``scripts/auto_adjust_repair_preflight.py``.

Operates entirely against patched seams.  Pins:

* Happy path: every gate green → ``ok=True``, action
  ``all_gates_pass_review_dry_run_then_write``.
* Per-gate failure paths: each failing gate flips ``ok`` to False and
  selects the matching recommendation from the fixed vocabulary.
* Recommendation priority: ``repo > backup > preview > plan > smoke``;
  the deepest-recoverable failing gate wins.
* ``--with-no-paid`` opt-in: smoke is skipped by default and surfaces
  ``requested=False`` with neutral counts; when requested its result
  contributes to overall ``ok`` and the recommendation.
* Defense-in-depth: the preflight never invokes
  ``apply_auto_adjust_mismatch_repair`` (write path).  Any attempt
  raises and the test fails.
* No provider / yfinance / LLM / FastAPI seam is reached during
  ``run_preflight`` — instrumented via ``builtins.__import__`` and a
  ``sys.modules`` delta.
* CLI plumbing: ``--json``, ``--with-no-paid``, exit codes, default
  args.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import auto_adjust_repair_preflight as preflight  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic "all-clean" gate states — tests compose these into patches
# so each test only overrides the gate it cares about.
# ---------------------------------------------------------------------------


def _clean_repo() -> dict:
    return {"ok": True, "dirty_paths": [], "count": 0}


def _clean_backup() -> dict:
    return {"ok": True, "path": "backups/events-20260507T120000.db"}


def _clean_preview() -> dict:
    return {
        "available":              True,
        "total_mismatches":       4,
        "repairable_count":       4,
        "non_repairable_count":   0,
        "counts_by_status":       {"repairable_flag_fix": 4},
        "proposed_rows":          [],
        "recommended_next_action": "fix_auto_adjust_flag_mismatch",
    }


def _clean_plan() -> dict:
    return {
        "available":            True,
        "planned_write_count":  9,
        "total_mismatches":     4,
    }


def _clean_smoke() -> dict:
    return {
        "available": True,
        "ok":        True,
        "passed":    20,
        "total":     20,
        "failed":    0,
    }


@contextmanager
def _patch_all_clean(*, smoke: dict | None = None):
    """Patch every gate seam to a clean response.  Tests override
    individual seams inside this context to simulate failure modes."""
    smoke_payload = smoke if smoke is not None else _clean_smoke()
    with patch.object(
        preflight, "_check_repo_clean",
        return_value=_clean_repo(),
    ), patch.object(
        preflight, "_check_latest_backup",
        return_value=_clean_backup(),
    ), patch.object(
        preflight, "_compute_repair_preview",
        return_value=_clean_preview(),
    ), patch.object(
        preflight, "_compute_dry_run_plan",
        return_value=_clean_plan(),
    ), patch.object(
        preflight, "_compute_no_paid_smoke",
        return_value=smoke_payload,
    ):
        yield


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):

    def test_all_gates_clean_returns_ok_true(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        self.assertTrue(
            report["ok"],
            f"errors: {report['errors']}",
        )
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_ALL_PASS,
        )
        self.assertEqual(report["errors"], [])

    def test_all_gate_keys_present(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        for key in (
            "repo_clean",
            "latest_backup",
            "repair_preview",
            "dry_run_plan",
            "no_paid_smoke",
        ):
            self.assertIn(key, report["gates"], f"missing gate: {key}")

    def test_top_level_keys_present(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        for key in ("ok", "gates", "errors", "recommended_next_action"):
            self.assertIn(key, report, f"missing top-level key: {key}")

    def test_smoke_gate_inactive_by_default(self) -> None:
        # ``--with-no-paid`` is off by default; the smoke gate must
        # surface ``requested=False`` and not contribute to errors.
        with _patch_all_clean():
            report = preflight.run_preflight()
        smoke = report["gates"]["no_paid_smoke"]
        self.assertFalse(smoke["requested"])
        self.assertIsNone(smoke["ok"])
        self.assertIsNone(smoke["passed"])
        self.assertIsNone(smoke["total"])

    def test_smoke_gate_active_when_requested(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight(with_no_paid=True)
        smoke = report["gates"]["no_paid_smoke"]
        self.assertTrue(smoke["requested"])
        self.assertTrue(smoke["ok"])
        self.assertEqual(smoke["passed"], 20)
        self.assertEqual(smoke["total"],  20)


# ---------------------------------------------------------------------------
# Per-gate failure paths
# ---------------------------------------------------------------------------


class TestRepoCleanGate(unittest.TestCase):

    def test_dirty_repo_flips_ok_and_selects_action(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_repo_clean",
            return_value={
                "ok":          False,
                "dirty_paths": [" M src/foo.py"],
                "count":       1,
            },
        ):
            report = preflight.run_preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_REPO_DIRTY,
        )
        self.assertTrue(
            any("repo_clean" in e for e in report["errors"]),
        )

    def test_git_failure_surfaces_error_string(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_repo_clean",
            return_value={
                "ok":          False,
                "dirty_paths": [],
                "count":       0,
                "error":       "fatal: not a git repository",
            },
        ):
            report = preflight.run_preflight()
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("not a git repository" in e for e in report["errors"]),
        )


class TestLatestBackupGate(unittest.TestCase):

    def test_missing_backup_flips_ok_and_selects_action(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_latest_backup",
            return_value={"ok": False, "path": None},
        ):
            report = preflight.run_preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_BACKUP_MISSING,
        )

    def test_present_backup_carries_path_in_section(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        self.assertEqual(
            report["gates"]["latest_backup"]["path"],
            "backups/events-20260507T120000.db",
        )


class TestRepairPreviewGate(unittest.TestCase):

    def test_unavailable_preview_flips_ok_and_selects_action(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_compute_repair_preview",
            return_value={
                "available": False,
                "error":     "loader raised RuntimeError: bad",
            },
        ):
            report = preflight.run_preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_PREVIEW_FAILED,
        )
        self.assertTrue(
            any("repair_preview" in e for e in report["errors"]),
        )

    def test_available_preview_carries_counts_in_section(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        section = report["gates"]["repair_preview"]
        self.assertTrue(section["ok"])
        self.assertEqual(section["total_mismatches"], 4)
        self.assertEqual(section["repairable_count"], 4)


class TestDryRunPlanGate(unittest.TestCase):

    def test_unavailable_plan_flips_ok_and_selects_action(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_compute_dry_run_plan",
            return_value={
                "available":           False,
                "planned_write_count": 0,
                "total_mismatches":    0,
                "error":               "ImportError: writer absent",
            },
        ):
            report = preflight.run_preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_PLAN_FAILED,
        )
        self.assertTrue(
            any("dry_run_plan" in e for e in report["errors"]),
        )

    def test_available_plan_surfaces_planned_write_count(self) -> None:
        with _patch_all_clean():
            report = preflight.run_preflight()
        section = report["gates"]["dry_run_plan"]
        self.assertTrue(section["ok"])
        self.assertEqual(section["planned_write_count"], 9)
        self.assertEqual(section["total_mismatches"],    4)


class TestNoPaidSmokeGate(unittest.TestCase):

    def test_smoke_not_requested_does_not_affect_overall_ok(self) -> None:
        # Even if the smoke seam *would* report a failure, the gate
        # must not contribute to errors when ``--with-no-paid`` is
        # off.  This pins that the opt-in flag is the only way the
        # smoke can flip the overall ok.
        bad_smoke = {
            "available": True, "ok": False, "passed": 0, "total": 1,
            "failed": 1,
        }
        with _patch_all_clean(smoke=bad_smoke):
            report = preflight.run_preflight(with_no_paid=False)
        self.assertTrue(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_ALL_PASS,
        )

    def test_smoke_requested_failure_flips_ok(self) -> None:
        bad_smoke = {
            "available": True, "ok": False, "passed": 19, "total": 20,
            "failed": 1,
        }
        with _patch_all_clean(smoke=bad_smoke):
            report = preflight.run_preflight(with_no_paid=True)
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_SMOKE_FAILED,
        )

    def test_smoke_unavailable_when_requested_flips_ok(self) -> None:
        unavail = {
            "available": False, "ok": False,
            "error":     "ImportError: no_paid_smoke missing",
        }
        with _patch_all_clean(smoke=unavail):
            report = preflight.run_preflight(with_no_paid=True)
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_SMOKE_FAILED,
        )


# ---------------------------------------------------------------------------
# Recommendation priority — the order load-bears for the runbook.
# ---------------------------------------------------------------------------


class TestRecommendationPriority(unittest.TestCase):
    """Pin the ``repo > backup > preview > plan > smoke`` ordering so a
    runbook consumer reading ``recommended_next_action`` reliably gets
    the deepest recoverable problem."""

    def test_repo_dirty_outranks_backup_missing(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_repo_clean",
            return_value={
                "ok": False, "dirty_paths": [" M f.py"], "count": 1,
            },
        ), patch.object(
            preflight, "_check_latest_backup",
            return_value={"ok": False, "path": None},
        ):
            report = preflight.run_preflight()
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_REPO_DIRTY,
        )

    def test_backup_missing_outranks_preview_failure(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_latest_backup",
            return_value={"ok": False, "path": None},
        ), patch.object(
            preflight, "_compute_repair_preview",
            return_value={"available": False},
        ):
            report = preflight.run_preflight()
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_BACKUP_MISSING,
        )

    def test_preview_failure_outranks_plan_failure(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_compute_repair_preview",
            return_value={"available": False},
        ), patch.object(
            preflight, "_compute_dry_run_plan",
            return_value={
                "available":           False,
                "planned_write_count": 0,
                "total_mismatches":    0,
            },
        ):
            report = preflight.run_preflight()
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_PREVIEW_FAILED,
        )

    def test_plan_failure_outranks_smoke_failure(self) -> None:
        bad_smoke = {
            "available": True, "ok": False, "passed": 0, "total": 20,
            "failed": 20,
        }
        with _patch_all_clean(smoke=bad_smoke), patch.object(
            preflight, "_compute_dry_run_plan",
            return_value={
                "available":           False,
                "planned_write_count": 0,
                "total_mismatches":    0,
            },
        ):
            report = preflight.run_preflight(with_no_paid=True)
        self.assertEqual(
            report["recommended_next_action"],
            preflight._ACTION_PLAN_FAILED,
        )


# ---------------------------------------------------------------------------
# Vocabulary pin — pin the fixed action labels so a runbook consumer
# can branch on the value safely.
# ---------------------------------------------------------------------------


class TestNextActionVocabulary(unittest.TestCase):

    def test_vocabulary_is_exactly_six_labels(self) -> None:
        self.assertEqual(len(preflight._NEXT_ACTIONS), 6)

    def test_vocabulary_contains_each_named_label(self) -> None:
        for label in (
            preflight._ACTION_ALL_PASS,
            preflight._ACTION_REPO_DIRTY,
            preflight._ACTION_BACKUP_MISSING,
            preflight._ACTION_PREVIEW_FAILED,
            preflight._ACTION_PLAN_FAILED,
            preflight._ACTION_SMOKE_FAILED,
        ):
            self.assertIn(label, preflight._NEXT_ACTIONS)

    def test_recommendation_always_in_vocabulary(self) -> None:
        # Every code path must yield a label from the vocabulary; any
        # accidental free-form string would break a runbook consumer.
        scenarios = [
            ("clean", _patch_all_clean(), False),
            (
                "dirty",
                patch.multiple(
                    preflight,
                    _check_repo_clean=lambda **kw: {
                        "ok": False, "dirty_paths": [], "count": 1,
                    },
                    _check_latest_backup=lambda **kw: _clean_backup(),
                    _compute_repair_preview=lambda: _clean_preview(),
                    _compute_dry_run_plan=lambda **kw: _clean_plan(),
                    _compute_no_paid_smoke=lambda: _clean_smoke(),
                ),
                False,
            ),
        ]
        for label, ctx, with_no_paid in scenarios:
            with self.subTest(scenario=label):
                with ctx:
                    report = preflight.run_preflight(
                        with_no_paid=with_no_paid,
                    )
                self.assertIn(
                    report["recommended_next_action"],
                    preflight._NEXT_ACTIONS,
                )


# ---------------------------------------------------------------------------
# Defense-in-depth: writer apply must NEVER be invoked.
# ---------------------------------------------------------------------------


class TestNeverInvokesWriter(unittest.TestCase):

    def test_apply_function_not_called_during_run(self) -> None:
        # Patch the writer's apply function to raise; the preflight
        # must run without ever reaching it.
        try:
            from auto_adjust_mismatch_repair import (
                apply_auto_adjust_mismatch_repair,  # noqa: F401
            )
        except ImportError:
            self.skipTest("writer module not importable")
        import auto_adjust_mismatch_repair as _writer

        def _explode(**kwargs):
            raise AssertionError(
                "preflight invoked apply_auto_adjust_mismatch_repair "
                f"with kwargs={kwargs!r}",
            )

        with patch.object(
            _writer, "apply_auto_adjust_mismatch_repair", _explode,
        ):
            with _patch_all_clean():
                report = preflight.run_preflight()
        self.assertTrue(report["ok"])

    def test_preflight_module_does_not_import_apply_at_top_level(
        self,
    ) -> None:
        # The preflight should not bind the apply function at module
        # load: a future regression that ``from auto_adjust_mismatch_repair
        # import apply_auto_adjust_mismatch_repair`` at top level would
        # leak the write entry point into the preflight's namespace.
        self.assertFalse(
            hasattr(preflight, "apply_auto_adjust_mismatch_repair"),
            "preflight must not bind apply_auto_adjust_mismatch_repair "
            "in its module namespace",
        )

    def test_preflight_source_never_passes_confirm_true_to_a_call(
        self,
    ) -> None:
        # Static defense-in-depth: walk the preflight's AST and assert
        # no ``Call`` node carries ``confirm=True`` as a keyword
        # argument.  Inspecting the AST (rather than the raw source)
        # ignores docstring prose and comments — the literal
        # ``confirm=True`` legitimately appears in the docstring's
        # description of what the preflight refuses to do.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(preflight))
        bad_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "confirm":
                    continue
                if (
                    isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    bad_calls.append(ast.dump(node))
        self.assertEqual(
            bad_calls, [],
            "preflight source must not pass `confirm=True` to any "
            "Call expression; the writer's write mode must never be "
            f"reachable from this script.  Found: {bad_calls}",
        )


# ---------------------------------------------------------------------------
# Import-graph guard — no provider / yfinance / LLM / FastAPI seams
# are pulled in during a run.
# ---------------------------------------------------------------------------


class TestNoForbiddenImports(unittest.TestCase):

    def test_run_does_not_import_forbidden_modules(self) -> None:
        # Earlier suites in the same process (e.g. tests.test_diagnostics)
        # legitimately import ``api`` / ``routes.diagnostics`` / etc.
        # Two complementary signals catch a real regression instead:
        #   1. ``builtins.__import__`` is instrumented for the duration
        #      of ``run_preflight`` so any actual import statement
        #      targeting a forbidden top-level is recorded — this
        #      catches violations even when the target is already
        #      cached.
        #   2. A ``sys.modules`` delta around the call catches the
        #      rare paths that bypass __import__ (e.g.
        #      ``importlib.util``).
        import builtins

        forbidden_prefixes = (
            "api",
            "routes",
            "yfinance",
            "market_check",
            "market_data",
            "analyze_event",
            "auto_backfill_runner",
        )

        def _is_forbidden(name: str) -> bool:
            if not isinstance(name, str):
                return False
            for prefix in forbidden_prefixes:
                if name == prefix or name.startswith(prefix + "."):
                    return True
            return False

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(
            name, globals=None, locals=None, fromlist=(), level=0,
        ):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            if name == "routes":
                for sub in fromlist or ():
                    forbidden_imports.append(f"routes.{sub}")
            return real_import(name, globals, locals, fromlist, level)

        before_modules = set(sys.modules.keys())
        with _patch_all_clean():
            with patch("builtins.__import__", side_effect=tracing_import):
                preflight.run_preflight()
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )

        self.assertEqual(
            forbidden_imports, [],
            "preflight performed forbidden imports during the call: "
            f"{forbidden_imports}",
        )
        self.assertEqual(
            newly_loaded_forbidden, [],
            "preflight loaded forbidden modules into sys.modules: "
            f"{newly_loaded_forbidden}",
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = preflight.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_cli_clean_run_exits_zero(self) -> None:
        with _patch_all_clean():
            rc, _ = self._run_cli([])
        self.assertEqual(rc, 0)

    def test_cli_dirty_run_exits_nonzero(self) -> None:
        with _patch_all_clean(), patch.object(
            preflight, "_check_repo_clean",
            return_value={
                "ok": False, "dirty_paths": [" M f.py"], "count": 1,
            },
        ):
            rc, _ = self._run_cli([])
        self.assertEqual(rc, 1)

    def test_cli_json_carries_required_keys(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in ("ok", "gates", "errors", "recommended_next_action"):
            self.assertIn(key, body)

    def test_cli_text_output_lists_each_gate(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli([])
        self.assertEqual(rc, 0)
        for needle in (
            "repo_clean", "latest_backup", "repair_preview",
            "dry_run_plan", "no_paid_smoke",
        ):
            self.assertIn(needle, output, f"missing gate line: {needle}")

    def test_cli_with_no_paid_flag_activates_smoke_gate(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli(["--with-no-paid", "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["gates"]["no_paid_smoke"]["requested"])

    def test_cli_default_does_not_request_smoke(self) -> None:
        with _patch_all_clean():
            rc, output = self._run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertFalse(body["gates"]["no_paid_smoke"]["requested"])

    def test_cli_passes_repo_path_through(self) -> None:
        captured: dict[str, str] = {}

        def _capture(*, repo_path):
            captured["repo_path"] = repo_path
            return _clean_repo()

        with patch.object(
            preflight, "_check_repo_clean", side_effect=_capture,
        ), patch.object(
            preflight, "_check_latest_backup",
            return_value=_clean_backup(),
        ), patch.object(
            preflight, "_compute_repair_preview",
            return_value=_clean_preview(),
        ), patch.object(
            preflight, "_compute_dry_run_plan",
            return_value=_clean_plan(),
        ):
            rc, _ = self._run_cli(["--repo-path", "/tmp/somewhere"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["repo_path"], "/tmp/somewhere")

    def test_cli_passes_db_path_through(self) -> None:
        captured: dict[str, object] = {}

        def _capture(*, db_path):
            captured["db_path"] = db_path
            return _clean_plan()

        with patch.object(
            preflight, "_check_repo_clean", return_value=_clean_repo(),
        ), patch.object(
            preflight, "_check_latest_backup",
            return_value=_clean_backup(),
        ), patch.object(
            preflight, "_compute_repair_preview",
            return_value=_clean_preview(),
        ), patch.object(
            preflight, "_compute_dry_run_plan", side_effect=_capture,
        ):
            rc, _ = self._run_cli(["--db-path", "/tmp/events.db"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["db_path"], "/tmp/events.db")

    def test_cli_passes_backup_dir_through(self) -> None:
        captured: dict[str, str] = {}

        def _capture(*, backup_dir):
            captured["backup_dir"] = backup_dir
            return _clean_backup()

        with patch.object(
            preflight, "_check_repo_clean", return_value=_clean_repo(),
        ), patch.object(
            preflight, "_check_latest_backup", side_effect=_capture,
        ), patch.object(
            preflight, "_compute_repair_preview",
            return_value=_clean_preview(),
        ), patch.object(
            preflight, "_compute_dry_run_plan",
            return_value=_clean_plan(),
        ):
            rc, _ = self._run_cli(["--backup-dir", "/tmp/backups"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["backup_dir"], "/tmp/backups")


if __name__ == "__main__":
    unittest.main()

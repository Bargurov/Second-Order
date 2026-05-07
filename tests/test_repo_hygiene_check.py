"""Tests for ``scripts/repo_hygiene_check.py`` — tracked local guard.

Each test spins up a throw-away workspace path and feeds the checker a
mocked ``git ls-files -z`` response.  The guard still sees
exactly the index-shaped byte stream it uses in production, without
creating nested Git repositories during the test run.  The tests assert
the checker:

  * Catches each generated-artifact pattern (``*.db``, ``*.sqlite``,
    ``*.sqlite3``, ``*.tsbuildinfo``, ``frontend/dist/*``,
    ``backups/*``).
  * Catches local-only docs/config (``docs/``, ``design/``,
    ``.githooks/``, ``AGENTS.md``, ``CLAUDE.md``,
    ``future_ideas.md``).
  * Returns an empty list on a clean repo.
  * Does NOT report files that are gitignored and not added.
  * Surfaces a JSON shape with the required top-level keys.
  * Exits 0 on clean, non-zero on violations.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import repo_hygiene_check as guard  # noqa: E402


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TEST_TMP_ROOT = os.path.join(_PROJECT_ROOT, ".tmp_repo_hygiene_tests")
_TRACKED_BY_REPO: dict[str, set[str]] = {}

_TOP_KEYS = (
    "ok",
    "tracked_generated_count",
    "tracked_generated_paths",
    "tracked_disallowed_count",
    "tracked_disallowed_paths",
    "checked_patterns",
)


def _make_repo() -> str:
    repo = os.path.join(_TEST_TMP_ROOT, f"repo_hyg_{uuid.uuid4().hex}")
    _TRACKED_BY_REPO[os.path.abspath(repo)] = set()
    return repo


def _write(repo: str, relpath: str, content: str = "x") -> str:
    # The checker reads the git index, not file bytes.  Tests keep the
    # filesystem out of the loop and let ``_add`` decide what is tracked.
    _ = (repo, content)
    return relpath


def _add(repo: str, relpath: str) -> None:
    _TRACKED_BY_REPO.setdefault(os.path.abspath(repo), set()).add(relpath)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    rc = guard.main(argv, out=out)
    return rc, out.getvalue()


class _RepoBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _make_repo()
        self._run_patch = patch.object(
            guard.subprocess,
            "run",
            side_effect=self._fake_git_ls_files,
        )
        self._run_patch.start()

    def tearDown(self) -> None:
        self._run_patch.stop()
        _TRACKED_BY_REPO.pop(os.path.abspath(self.repo), None)
        try:
            shutil.rmtree(self.repo, ignore_errors=True)
        except (OSError, PermissionError):
            pass
        try:
            os.rmdir(_TEST_TMP_ROOT)
        except OSError:
            pass

    def _fake_git_ls_files(self, args, cwd=None, **_kwargs):
        if args != ["git", "ls-files", "-z"]:
            return subprocess.CompletedProcess(args, 1, b"", b"unexpected git command")
        repo = os.path.abspath(str(cwd)) if cwd is not None else ""
        if repo not in _TRACKED_BY_REPO:
            return subprocess.CompletedProcess(args, 1, b"", b"not a git repo")
        paths = sorted(_TRACKED_BY_REPO[repo])
        stdout = ("\0".join(paths) + ("\0" if paths else "")).encode("utf-8")
        return subprocess.CompletedProcess(args, 0, stdout, b"")


class TestCleanRepo(_RepoBase):
    def test_no_tracked_files_returns_empty(self) -> None:
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])

    def test_only_clean_files_tracked_returns_empty(self) -> None:
        _write(self.repo, "src/app.py", "print(1)\n")
        _write(self.repo, "README.md", "# project")
        _add(self.repo, "src/app.py")
        _add(self.repo, "README.md")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])


class TestCatchesEachPattern(_RepoBase):
    def test_catches_db_file_at_root(self) -> None:
        _write(self.repo, "events.db")
        _add(self.repo, "events.db")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("events.db", matched)

    def test_catches_db_file_nested(self) -> None:
        _write(self.repo, "data/events.db")
        _add(self.repo, "data/events.db")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("data/events.db", matched)

    def test_catches_sqlite_file(self) -> None:
        _write(self.repo, "store.sqlite")
        _add(self.repo, "store.sqlite")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("store.sqlite", matched)

    def test_catches_sqlite3_file(self) -> None:
        _write(self.repo, "store.sqlite3")
        _add(self.repo, "store.sqlite3")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("store.sqlite3", matched)

    def test_catches_tsbuildinfo(self) -> None:
        _write(self.repo, "frontend/tsconfig.app.tsbuildinfo")
        _add(self.repo, "frontend/tsconfig.app.tsbuildinfo")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("frontend/tsconfig.app.tsbuildinfo", matched)

    def test_catches_frontend_dist_files_at_top_and_nested(self) -> None:
        _write(self.repo, "frontend/dist/index.html", "<html></html>")
        _write(self.repo, "frontend/dist/assets/app.js", "console.log(1)")
        _add(self.repo, "frontend/dist/index.html")
        _add(self.repo, "frontend/dist/assets/app.js")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("frontend/dist/index.html",     matched)
        self.assertIn("frontend/dist/assets/app.js",  matched)

    def test_catches_backups_at_top_and_nested(self) -> None:
        _write(self.repo, "backups/2026-05-06.sql.gz", "compressed")
        _write(self.repo, "backups/older/dump.tar",    "old")
        _add(self.repo, "backups/2026-05-06.sql.gz")
        _add(self.repo, "backups/older/dump.tar")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertIn("backups/2026-05-06.sql.gz", matched)
        self.assertIn("backups/older/dump.tar",    matched)


class TestCatchesLocalOnlyDocsAndConfig(_RepoBase):
    def test_catches_root_local_docs(self) -> None:
        for relpath in ("AGENTS.md", "CLAUDE.md", "future_ideas.md"):
            _write(self.repo, relpath, "local notes")
            _add(self.repo, relpath)

        matched = guard.list_tracked_generated(repo_path=self.repo)

        self.assertIn("AGENTS.md", matched)
        self.assertIn("CLAUDE.md", matched)
        self.assertIn("future_ideas.md", matched)

    def test_catches_docs_design_and_githooks_trees(self) -> None:
        for relpath in (
            "docs/private_runbook.md",
            "docs/nested/local.md",
            "design/sketch.md",
            "design/wireframes/home.md",
            ".githooks/pre-commit",
            ".githooks/hooks/pre-push",
        ):
            _write(self.repo, relpath, "local artifact")
            _add(self.repo, relpath)

        matched = guard.list_tracked_generated(repo_path=self.repo)

        for relpath in (
            "docs/private_runbook.md",
            "docs/nested/local.md",
            "design/sketch.md",
            "design/wireframes/home.md",
            ".githooks/pre-commit",
            ".githooks/hooks/pre-push",
        ):
            self.assertIn(relpath, matched)


class TestAdjacentNamesNotMisclassified(_RepoBase):
    """``frontend/distance/`` and ``foo.db.bak`` should NOT match."""

    def test_frontend_distance_not_matched(self) -> None:
        _write(self.repo, "frontend/distance/calc.py", "pass")
        _add(self.repo, "frontend/distance/calc.py")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])

    def test_db_with_trailing_extension_not_matched(self) -> None:
        _write(self.repo, "events.db.bak", "x")
        _add(self.repo, "events.db.bak")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])

    def test_backups_path_substring_not_matched(self) -> None:
        # ``mybackups/`` must not match ``backups/*``.
        _write(self.repo, "mybackups/dump.sql", "x")
        _add(self.repo, "mybackups/dump.sql")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])

    def test_docs_and_design_substrings_not_matched(self) -> None:
        for relpath in (
            "mydocs/private.md",
            "docs_archive/readme.md",
            "product_design_notes.md",
            ".githooks-local/pre-commit",
        ):
            _write(self.repo, relpath, "x")
            _add(self.repo, relpath)

        matched = guard.list_tracked_generated(repo_path=self.repo)

        self.assertEqual(matched, [])


class TestIgnoredButUntrackedNotReported(_RepoBase):
    """Files matching the patterns but ignored AND not added must not
    be reported — the guard scans the index, not the working tree."""

    def test_ignored_files_invisible_to_guard(self) -> None:
        _write(
            self.repo,
            ".gitignore",
            "*.db\n*.sqlite\n*.sqlite3\n*.tsbuildinfo\n"
            "frontend/dist/\nbackups/\n",
        )
        _add(self.repo, ".gitignore")
        # Generated artifacts on disk — but never ``git add``-ed.
        _write(self.repo, "events.db", "raw")
        _write(self.repo, "store.sqlite3", "raw")
        _write(self.repo, "frontend/dist/index.html", "x")
        _write(self.repo, "backups/dump.sql", "x")
        _write(self.repo, "frontend/tsconfig.app.tsbuildinfo", "x")

        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, [])


class TestResultShape(_RepoBase):
    def test_results_deterministic_sorted_order(self) -> None:
        _write(self.repo, "z.db")
        _write(self.repo, "a.db")
        _write(self.repo, "m.db")
        _add(self.repo, "z.db")
        _add(self.repo, "a.db")
        _add(self.repo, "m.db")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched, sorted(matched))

    def test_no_duplicate_paths_when_multiple_patterns_could_match(self) -> None:
        # Each path appears at most once even if multiple patterns
        # could match (defensive — the loop short-circuits).
        _write(self.repo, "frontend/dist/db.sqlite3", "x")
        _add(self.repo, "frontend/dist/db.sqlite3")
        matched = guard.list_tracked_generated(repo_path=self.repo)
        self.assertEqual(matched.count("frontend/dist/db.sqlite3"), 1)


class TestCliJSON(_RepoBase):
    def test_json_top_level_keys_present(self) -> None:
        _write(self.repo, "events.db")
        _add(self.repo, "events.db")
        rc, output = _run_cli(["--json", "--repo-path", self.repo])
        self.assertEqual(rc, 1)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing JSON key: {key}")
        self.assertFalse(body["ok"])
        self.assertEqual(body["tracked_generated_count"], 1)
        self.assertEqual(body["tracked_generated_paths"], ["events.db"])
        self.assertEqual(body["tracked_disallowed_count"], 1)
        self.assertEqual(body["tracked_disallowed_paths"], ["events.db"])

    def test_json_ok_true_on_clean_repo(self) -> None:
        rc, output = _run_cli(["--json", "--repo-path", self.repo])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["ok"])
        self.assertEqual(body["tracked_generated_count"], 0)
        self.assertEqual(body["tracked_generated_paths"], [])
        self.assertEqual(body["tracked_disallowed_count"], 0)
        self.assertEqual(body["tracked_disallowed_paths"], [])

    def test_json_carries_all_checked_patterns(self) -> None:
        rc, output = _run_cli(["--json", "--repo-path", self.repo])
        body = json.loads(output)
        for pat in (
            "*.db", "*.sqlite", "*.sqlite3", "*.tsbuildinfo",
            "frontend/dist/*", "backups/*", "docs/*", "design/*",
            ".githooks/*", "AGENTS.md", "CLAUDE.md", "future_ideas.md",
        ):
            self.assertIn(pat, body["checked_patterns"])


class TestCliExitCodes(_RepoBase):
    def test_exit_zero_on_clean_repo(self) -> None:
        rc, _ = _run_cli(["--repo-path", self.repo])
        self.assertEqual(rc, 0)

    def test_exit_nonzero_on_violations(self) -> None:
        _write(self.repo, "events.db")
        _add(self.repo, "events.db")
        rc, _ = _run_cli(["--repo-path", self.repo])
        self.assertNotEqual(rc, 0)


class TestCliText(_RepoBase):
    def test_text_lists_violation_paths(self) -> None:
        _write(self.repo, "frontend/dist/index.html", "x")
        _add(self.repo, "frontend/dist/index.html")
        rc, output = _run_cli(["--repo-path", self.repo])
        self.assertNotEqual(rc, 0)
        self.assertIn("frontend/dist/index.html", output)
        self.assertIn("Tracked disallowed paths", output)

    def test_text_status_indicates_clean(self) -> None:
        rc, output = _run_cli(["--repo-path", self.repo])
        self.assertEqual(rc, 0)
        self.assertIn("OK", output)


class TestCiWorkflowConfig(unittest.TestCase):
    """Pin CI to the no-paid repo-health surface."""

    def _ci_text(self) -> str:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, ".github", "workflows", "ci.yml")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _ci_step_text(self, name: str) -> str:
        text = self._ci_text()
        marker = f"      - name: {name}"
        start = text.index(marker)
        next_start = text.find("\n      - name:", start + len(marker))
        if next_start == -1:
            return text[start:]
        return text[start:next_start]

    def test_ci_runs_repo_hygiene_project_health_and_no_paid_only(self) -> None:
        text = self._ci_text()

        for needle in (
            "python -m unittest tests.test_repo_hygiene_check -v",
            "python scripts/repo_hygiene_check.py --json",
            "python -m unittest tests.test_event_study -v",
            "python -m unittest tests.test_bootstrap_ci -v",
            "python -m unittest tests.test_fdr -v",
            "python -m unittest tests.test_stat_validation -v",
            "Run synthetic statistical validation smoke",
            "from stats.event_study import compute_event_study",
            "from stats.bootstrap_ci import bootstrap_ar_ci, bootstrap_sar_ci",
            "from stats.fdr import bh_adjust",
            "from stats.stat_validation import compose_validation_records",
            "python scripts/no_forward_20d_gap_report.py --json",
            "python scripts/auto_adjust_mismatch_repair_preview.py --json",
            "python scripts/auto_adjust_mismatch_consistency_check.py --json",
            "scripts/auto_adjust_mismatch_repair_write_smoke.py",
            "ci_tmp/backups/events-20260507T000000.db",
            "ci_tmp/events.db",
            "python scripts/no_forward_20d_refreshability_export.py --json --limit 100",
            "python scripts/project_health_check.py --json",
            "--allow-duplicate-clusters 28",
            "python scripts/no_paid_smoke.py --json",
        ):
            self.assertIn(needle, text, f"missing CI command: {needle}")

        for forbidden in (
            "tests.test_diagnostics",
            "unittest discover",
            "npm --prefix frontend",
            "npm ci",
            "backup_archive.py",
            "refresh_price_cache.py",
            "rebuild_archive.py",
            "eval.py",
            "price_cache_auto_adjust_coverage_report.py",
            "auto_adjust_repair_backup_delta_report.py",
            "auto_adjust_repair_preflight.py",
            "db_mutation_readiness_check.py",
            "auto_adjust_mismatch_repair.py",
            "apply_auto_adjust_mismatch_repair",
            "plan_auto_adjust_mismatch_repair",
            "--apply",
            "--write",
            "--repair",
            "--commit",
            "--confirm",
        ):
            self.assertNotIn(
                forbidden,
                text,
                f"CI should not run broad or provider-risky command: {forbidden}",
            )

    def test_ci_runs_no_forward_diagnostics_after_repo_hygiene(self) -> None:
        text = self._ci_text()

        hygiene_idx = text.index("python scripts/repo_hygiene_check.py --json")
        report_idx = text.index("python scripts/no_forward_20d_gap_report.py --json")
        export_idx = text.index(
            "python scripts/no_forward_20d_refreshability_export.py --json --limit 100"
        )
        health_idx = text.index("python scripts/project_health_check.py --json")

        self.assertLess(hygiene_idx, report_idx)
        self.assertLess(hygiene_idx, export_idx)
        self.assertLess(report_idx, health_idx)
        self.assertLess(export_idx, health_idx)

    def test_ci_runs_pure_stats_after_hygiene_before_db_fixture(self) -> None:
        text = self._ci_text()

        hygiene_idx = text.index("python scripts/repo_hygiene_check.py --json")
        stats_tests_idx = text.index("Run pure statistical utility tests")
        stats_smoke_idx = text.index("Run synthetic statistical validation smoke")
        fixture_idx = text.index("Build runner-local health fixtures")

        self.assertLess(hygiene_idx, stats_tests_idx)
        self.assertLess(stats_tests_idx, stats_smoke_idx)
        self.assertLess(stats_smoke_idx, fixture_idx)

        stats_step = self._ci_step_text("Run pure statistical utility tests")
        smoke_step = self._ci_step_text("Run synthetic statistical validation smoke")

        for needle in (
            "python -m unittest tests.test_event_study -v",
            "python -m unittest tests.test_bootstrap_ci -v",
            "python -m unittest tests.test_fdr -v",
            "python -m unittest tests.test_stat_validation -v",
        ):
            self.assertIn(needle, stats_step)

        for needle in (
            "compute_event_study",
            "bootstrap_ar_ci",
            "bootstrap_sar_ci",
            "bh_adjust",
            "compose_validation_records",
            "asset_prices",
            "benchmark_prices",
        ):
            self.assertIn(needle, smoke_step)

        for forbidden in (
            "sqlite3",
            "db.",
            "events.db",
            "ci_tmp",
            "scripts/",
            "yfinance",
            "market_data",
            "market_check",
            "analyze_event",
            "ANTHROPIC",
            "OPENAI",
        ):
            self.assertNotIn(
                forbidden,
                stats_step + smoke_step,
                f"pure stats CI step should not touch DB/provider seams: {forbidden}",
            )

    def test_ci_runs_auto_adjust_dry_run_status_and_temp_copy_after_hygiene(self) -> None:
        text = self._ci_text()

        hygiene_idx = text.index("python scripts/repo_hygiene_check.py --json")
        preview_idx = text.index(
            "python scripts/auto_adjust_mismatch_repair_preview.py --json"
        )
        check_idx = text.index(
            "python scripts/auto_adjust_mismatch_consistency_check.py --json"
        )
        smoke_idx = text.index("Run safe auto-adjust temp-copy smoke")
        report_idx = text.index("python scripts/no_forward_20d_gap_report.py --json")
        health_idx = text.index("python scripts/project_health_check.py --json")

        self.assertIn("Run safe auto-adjust repair dry-run status", text)
        self.assertIn("Run safe auto-adjust consistency check", text)
        self.assertIn("scripts/auto_adjust_mismatch_repair_write_smoke.py", text)
        self.assertIn("ci_tmp/backups/events-20260507T000000.db", text)
        self.assertIn("ci_tmp/events.db", text)
        self.assertIn("writer not implemented yet:", text)
        self.assertIn("live_db_unchanged", text)
        self.assertLess(hygiene_idx, preview_idx)
        self.assertLess(preview_idx, check_idx)
        self.assertLess(check_idx, smoke_idx)
        self.assertLess(smoke_idx, report_idx)
        self.assertLess(smoke_idx, health_idx)

    def test_ci_is_keyless_and_providerless(self) -> None:
        text = self._ci_text()

        for forbidden in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "ANALYSIS_PROVIDER",
            "BACKFILL_PROVIDER",
            "MARKET_DATA_PROVIDER",
            "yfinance",
            "market_check",
            "market_data",
            "analyze_event",
            "ANTHROPIC_MODEL",
            "OPENAI_MODEL",
            "price_cache_refresh.py",
        ):
            self.assertNotIn(
                forbidden,
                text,
                f"CI must not expose or configure provider surface: {forbidden}",
            )

        for safe_gate in (
            "ENABLE_PAID_ANALYSIS: \"false\"",
            "ENABLE_AUTO_BACKFILL: \"false\"",
            "BACKFILL_DRY_RUN_DEFAULT: \"true\"",
            "MAX_BACKFILL_LLM_CALLS: \"0\"",
        ):
            self.assertIn(safe_gate, text)

    def test_ci_uses_runner_created_health_fixture(self) -> None:
        text = self._ci_text()

        self.assertIn("ci_tmp/events.db", text)
        self.assertIn("ci_tmp/backups", text)
        self.assertIn("db.init_db()", text)
        self.assertIn("INSERT INTO events", text)
        self.assertIn("CREATE TABLE IF NOT EXISTS price_cache", text)
        self.assertNotIn("docs/", text)
        self.assertNotIn("design/", text)
        self.assertNotIn("AGENTS.md", text)
        self.assertNotIn("CLAUDE.md", text)
        self.assertNotIn("future_ideas.md", text)
        self.assertNotIn(".githooks/", text)


if __name__ == "__main__":
    unittest.main()

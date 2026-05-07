"""Tests for ``scripts/repo_hygiene_check.py`` — tracked-generated guard.

Each test spins up a throw-away git repo via ``git init`` in a temp
directory, ``git add``-s fake generated files (the index is what
``git ls-files`` reads, so a commit is unnecessary), and asserts the
checker:

  * Catches each pattern (``*.db``, ``*.sqlite``, ``*.sqlite3``,
    ``*.tsbuildinfo``, ``frontend/dist/*``, ``backups/*``).
  * Returns an empty list on a clean repo.
  * Does NOT report files that are gitignored and not added.
  * Surfaces a JSON shape with the four required top-level keys.
  * Exits 0 on clean, non-zero on violations.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import repo_hygiene_check as guard  # noqa: E402


_TOP_KEYS = (
    "ok",
    "tracked_generated_count",
    "tracked_generated_paths",
    "checked_patterns",
)


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _make_repo() -> str:
    repo = tempfile.mkdtemp(prefix="repo_hyg_")
    _git(["init", "-q"], cwd=repo)
    return repo


def _write(repo: str, relpath: str, content: str = "x") -> str:
    full = os.path.join(repo, relpath)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return relpath


def _add(repo: str, relpath: str) -> None:
    _git(["add", "--", relpath], cwd=repo)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    rc = guard.main(argv, out=out)
    return rc, out.getvalue()


class _RepoBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _make_repo()

    def tearDown(self) -> None:
        try:
            shutil.rmtree(self.repo, ignore_errors=True)
        except (OSError, PermissionError):
            pass


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

    def test_json_ok_true_on_clean_repo(self) -> None:
        rc, output = _run_cli(["--json", "--repo-path", self.repo])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["ok"])
        self.assertEqual(body["tracked_generated_count"], 0)
        self.assertEqual(body["tracked_generated_paths"], [])

    def test_json_carries_all_checked_patterns(self) -> None:
        rc, output = _run_cli(["--json", "--repo-path", self.repo])
        body = json.loads(output)
        for pat in (
            "*.db", "*.sqlite", "*.sqlite3", "*.tsbuildinfo",
            "frontend/dist/*", "backups/*",
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

    def test_text_status_indicates_clean(self) -> None:
        rc, output = _run_cli(["--repo-path", self.repo])
        self.assertEqual(rc, 0)
        self.assertIn("OK", output)


if __name__ == "__main__":
    unittest.main()

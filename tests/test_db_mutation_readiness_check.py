"""Tests for ``scripts/db_mutation_readiness_check.py``.

Read-only operator readiness checklist for any DB mutation.  Each gate
seam is patched in isolation so the suite never touches the real
``events.db``, the real ``backups/`` directory, or the real git index.
Pins:

* All-pass case yields top-level ``ok=True`` with every gate
  ``ok=True`` and ``recommended_next_action="ready_to_mutate"``.
* Each failure mode flips ``ok=False``, lifts a precise error line, and
  emits the matching ``block_*`` recommendation.
* The two repo-hygiene gates share a single underlying source — they
  always agree.
* Recommendation priority: events_db > backup > restore > repo > staged
  > project_health.  Defense-in-depth so an operator scanning the JSON
  always reads the most severe blocker first.
* JSON output carries every required top-level key and is valid JSON.
* CLI exit code matches ``payload["ok"]``.
* ``--allow-duplicate-clusters N`` is forwarded to
  ``scripts.project_health_check.run_health_check``.
* The module never imports a provider/yfinance/LLM seam directly.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import db_mutation_readiness_check as drc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture payloads — every test starts from a clean copy via ``dict(...)``
# so per-test mutations never bleed into sibling tests.
# ---------------------------------------------------------------------------


_OK_BACKUP_RESTORE = {
    "ok":                  True,
    "backup_path":         "backups/events-20260507T120000.db",
    "temp_copy_path":      "/tmp/restore_check.db",
    "table_counts":        {"events": 271, "price_cache": 10_440},
    "warnings":            [],
    "errors":              [],
    "tables":              ["events", "price_cache"],
    "events_columns":      ["id", "headline", "event_date"],
    "price_cache_present": True,
}


_OK_BACKUP_PATH = Path("backups/events-20260507T120000.db")


def _ok_project_health() -> dict:
    return {
        "ok":                True,
        "warnings":          [],
        "errors":            [],
        "accepted_warnings": [],
    }


def _bad_project_health(error_msg: str) -> dict:
    return {
        "ok":                False,
        "warnings":          [],
        "errors":            [error_msg],
        "accepted_warnings": [],
    }


def _patch_all_clean():
    """Return an ExitStack that patches every readiness gate seam to a
    clean fixture.  Tests layer further patches over this baseline to
    drive specific failure modes.
    """
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch.object(
        drc, "_check_events_db_readable",
        return_value=(True, None),
    ))
    stack.enter_context(patch.object(
        drc, "find_latest_backup",
        return_value=_OK_BACKUP_PATH,
    ))
    stack.enter_context(patch.object(
        drc, "_check_backup_readable",
        return_value=(True, None),
    ))
    stack.enter_context(patch.object(
        drc, "restore_check",
        return_value=dict(_OK_BACKUP_RESTORE),
    ))
    stack.enter_context(patch.object(
        drc, "list_tracked_generated",
        return_value=[],
    ))
    stack.enter_context(patch.object(
        drc, "_list_staged_files",
        return_value=([], None),
    ))
    stack.enter_context(patch.object(
        drc, "run_health_check",
        return_value=_ok_project_health(),
    ))
    return stack


# ---------------------------------------------------------------------------
# All-pass aggregation
# ---------------------------------------------------------------------------


class TestAllPass(unittest.TestCase):
    def test_all_clean_seams_yield_top_level_ok(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertTrue(payload["ok"], f"errors={payload['errors']}")
        self.assertEqual(payload["errors"], [])

    def test_every_gate_ok_when_all_clean(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        for key in drc._GATE_KEYS:
            gate = payload["gates"][key]
            self.assertTrue(gate["ok"], f"{key} should pass; gate={gate}")

    def test_recommended_next_action_is_ready_when_all_clean(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "ready_to_mutate",
        )


# ---------------------------------------------------------------------------
# Required top-level shape
# ---------------------------------------------------------------------------


class TestPayloadShape(unittest.TestCase):
    def test_required_top_level_keys_present(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        for key in ("ok", "gates", "errors", "recommended_next_action"):
            self.assertIn(key, payload, f"missing top-level key: {key}")

    def test_gates_carry_seven_named_entries(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertEqual(set(payload["gates"].keys()), {
            "events_db_exists_and_readable",
            "latest_backup_exists_and_readable",
            "backup_restore_check_ok",
            "repo_hygiene_ok",
            "no_tracked_generated_artifacts",
            "no_staged_files",
            "project_health_ok",
        })

    def test_each_gate_has_bool_ok(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        for name, gate in payload["gates"].items():
            self.assertIn("ok", gate, f"{name} missing ok")
            self.assertIsInstance(
                gate["ok"], bool,
                f"{name}.ok must be bool, got {type(gate['ok']).__name__}",
            )

    def test_errors_is_list(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertIsInstance(payload["errors"], list)

    def test_recommended_next_action_in_pinned_vocabulary(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertIn(
            payload["recommended_next_action"],
            drc._RECOMMENDATIONS,
        )

    def test_payload_is_json_serializable(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        # Must round-trip — the CLI's --json mode dumps this same dict.
        text = json.dumps(payload, sort_keys=True)
        self.assertEqual(json.loads(text), payload)


# ---------------------------------------------------------------------------
# Gate — events_db_exists_and_readable
# ---------------------------------------------------------------------------


class TestEventsDbGate(unittest.TestCase):
    def test_unreadable_db_blocks(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "_check_events_db_readable",
                return_value=(False, "events.db does not exist"),
            ):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        self.assertFalse(
            payload["gates"]["events_db_exists_and_readable"]["ok"],
        )
        self.assertEqual(
            payload["recommended_next_action"],
            "block_db_unreadable",
        )
        joined = " | ".join(payload["errors"])
        self.assertIn("events_db_exists_and_readable", joined)
        self.assertIn("events.db", joined)

    def test_db_path_field_carried_in_gate(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check(db_path="custom/path.db")
        gate = payload["gates"]["events_db_exists_and_readable"]
        self.assertEqual(gate.get("db_path"), "custom/path.db")


# ---------------------------------------------------------------------------
# Gate — latest_backup_exists_and_readable
# ---------------------------------------------------------------------------


class TestLatestBackupGate(unittest.TestCase):
    def test_no_backup_found_blocks(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "find_latest_backup",
                return_value=None,
            ):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        gate = payload["gates"]["latest_backup_exists_and_readable"]
        self.assertFalse(gate["ok"])
        self.assertIsNone(gate.get("backup_path"))
        self.assertEqual(
            payload["recommended_next_action"],
            "block_no_backup",
        )

    def test_unreadable_backup_blocks(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "_check_backup_readable",
                return_value=(False, "permission denied"),
            ):
                payload = drc.run_readiness_check()
        gate = payload["gates"]["latest_backup_exists_and_readable"]
        self.assertFalse(gate["ok"])
        self.assertEqual(
            payload["recommended_next_action"],
            "block_no_backup",
        )

    def test_backup_path_carried_in_gate_when_found(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        gate = payload["gates"]["latest_backup_exists_and_readable"]
        self.assertTrue(gate["ok"])
        self.assertEqual(gate.get("backup_path"), str(_OK_BACKUP_PATH))


# ---------------------------------------------------------------------------
# Gate — backup_restore_check_ok
# ---------------------------------------------------------------------------


class TestBackupRestoreGate(unittest.TestCase):
    def test_failed_restore_blocks(self) -> None:
        bad = dict(
            _OK_BACKUP_RESTORE,
            ok=False,
            errors=["required table missing: events"],
        )
        with _patch_all_clean():
            with patch.object(drc, "restore_check", return_value=bad):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        gate = payload["gates"]["backup_restore_check_ok"]
        self.assertFalse(gate["ok"])
        self.assertEqual(
            payload["recommended_next_action"],
            "block_backup_restore_failed",
        )
        joined = " | ".join(payload["errors"])
        self.assertIn("backup_restore_check_ok", joined)
        self.assertIn("required table missing", joined)

    def test_restore_uses_latest_with_cleanup(self) -> None:
        seen: list[dict] = []

        def fake_restore(**kwargs):
            seen.append(kwargs)
            return dict(_OK_BACKUP_RESTORE)

        with _patch_all_clean():
            with patch.object(drc, "restore_check", side_effect=fake_restore):
                drc.run_readiness_check(backup_dir="bk")
        self.assertEqual(len(seen), 1)
        # The readiness check must invoke restore_check with the safe
        # contract: ``use_latest=True`` and ``cleanup=True`` so the
        # temp copy is removed before return.
        self.assertTrue(seen[0].get("use_latest"))
        self.assertTrue(seen[0].get("cleanup"))


# ---------------------------------------------------------------------------
# Gate — repo_hygiene_ok / no_tracked_generated_artifacts (shared source)
# ---------------------------------------------------------------------------


class TestRepoHygieneGates(unittest.TestCase):
    def test_tracked_artifacts_block_both_gates(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db", "backups/events-x.db"],
            ):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["gates"]["repo_hygiene_ok"]["ok"])
        self.assertFalse(
            payload["gates"]["no_tracked_generated_artifacts"]["ok"],
        )
        self.assertEqual(
            payload["recommended_next_action"],
            "block_repo_hygiene_dirty",
        )
        joined = " | ".join(payload["errors"])
        self.assertIn("repo_hygiene_ok", joined)
        self.assertIn("events.db", joined)

    def test_clean_repo_passes_both_gates(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        self.assertTrue(payload["gates"]["repo_hygiene_ok"]["ok"])
        self.assertTrue(
            payload["gates"]["no_tracked_generated_artifacts"]["ok"],
        )

    def test_both_gates_carry_same_paths(self) -> None:
        # The two gates are aliases over a single ``list_tracked_generated``
        # call.  Their counts and paths must agree row-for-row so a
        # downstream JSON consumer can use either.
        with _patch_all_clean():
            with patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db"],
            ):
                payload = drc.run_readiness_check()
        a = payload["gates"]["repo_hygiene_ok"]
        b = payload["gates"]["no_tracked_generated_artifacts"]
        self.assertEqual(
            a.get("tracked_generated_paths"),
            b.get("tracked_generated_paths"),
        )
        self.assertEqual(
            a.get("tracked_generated_count"),
            b.get("tracked_generated_count"),
        )

    def test_list_tracked_generated_called_once(self) -> None:
        # Both alias gates must reuse a single call so the underlying
        # ``git ls-files`` shell-out fires only once per readiness run.
        seen = []

        def fake(*args, **kwargs):
            seen.append((args, kwargs))
            return []

        with _patch_all_clean():
            with patch.object(
                drc, "list_tracked_generated", side_effect=fake,
            ):
                drc.run_readiness_check()
        self.assertEqual(
            len(seen), 1,
            f"expected list_tracked_generated to fire once; saw {len(seen)}",
        )


# ---------------------------------------------------------------------------
# Gate — no_staged_files
# ---------------------------------------------------------------------------


class TestNoStagedFilesGate(unittest.TestCase):
    def test_staged_files_block(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py", "bar.py"], None),
            ):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        gate = payload["gates"]["no_staged_files"]
        self.assertFalse(gate["ok"])
        self.assertEqual(gate.get("staged_count"), 2)
        self.assertIn("foo.py", gate.get("staged_files") or [])
        self.assertEqual(
            payload["recommended_next_action"],
            "block_staged_files_present",
        )
        joined = " | ".join(payload["errors"])
        self.assertIn("no_staged_files", joined)

    def test_git_error_blocks_gate(self) -> None:
        # If git is unavailable we cannot prove the index is clean,
        # so the gate must fail closed.
        with _patch_all_clean():
            with patch.object(
                drc, "_list_staged_files",
                return_value=([], "git: command not found"),
            ):
                payload = drc.run_readiness_check()
        gate = payload["gates"]["no_staged_files"]
        self.assertFalse(gate["ok"])
        self.assertIn("git", " ".join(payload["errors"]).lower())

    def test_clean_index_passes_gate(self) -> None:
        with _patch_all_clean():
            payload = drc.run_readiness_check()
        gate = payload["gates"]["no_staged_files"]
        self.assertTrue(gate["ok"])
        self.assertEqual(gate.get("staged_count"), 0)


# ---------------------------------------------------------------------------
# Gate — project_health_ok (with duplicate-cluster waiver)
# ---------------------------------------------------------------------------


class TestProjectHealthGate(unittest.TestCase):
    def test_unhealthy_project_blocks(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check",
                return_value=_bad_project_health(
                    "backup_restore: empty events table",
                ),
            ):
                payload = drc.run_readiness_check()
        self.assertFalse(payload["ok"])
        gate = payload["gates"]["project_health_ok"]
        self.assertFalse(gate["ok"])
        self.assertEqual(
            payload["recommended_next_action"],
            "block_project_health_failed",
        )
        joined = " | ".join(payload["errors"])
        self.assertIn("project_health_ok", joined)
        self.assertIn("empty events", joined)

    def test_allow_duplicate_clusters_forwarded(self) -> None:
        seen: list[dict] = []

        def fake(*args, **kwargs):
            seen.append(kwargs)
            return _ok_project_health()

        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check", side_effect=fake,
            ):
                drc.run_readiness_check(allow_duplicate_clusters=28)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].get("allow_duplicate_clusters"), 28)

    def test_default_allow_duplicate_clusters_is_zero(self) -> None:
        seen: list[dict] = []

        def fake(*args, **kwargs):
            seen.append(kwargs)
            return _ok_project_health()

        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check", side_effect=fake,
            ):
                drc.run_readiness_check()
        self.assertEqual(seen[0].get("allow_duplicate_clusters"), 0)

    def test_db_and_backup_dir_forwarded_to_project_health(self) -> None:
        seen: list[dict] = []

        def fake(*args, **kwargs):
            seen.append(kwargs)
            return _ok_project_health()

        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check", side_effect=fake,
            ):
                drc.run_readiness_check(
                    db_path="x.db",
                    backup_dir="bk",
                    repo_path="/work",
                )
        self.assertEqual(seen[0].get("db_path"),    "x.db")
        self.assertEqual(seen[0].get("backup_dir"), "bk")
        self.assertEqual(seen[0].get("repo_path"),  "/work")


# ---------------------------------------------------------------------------
# Recommendation priority — first failing gate by spec order wins
# ---------------------------------------------------------------------------


class TestRecommendationPriority(unittest.TestCase):
    def test_db_unreadable_takes_priority_over_everything(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "_check_events_db_readable",
                return_value=(False, "missing"),
            ), patch.object(
                drc, "find_latest_backup", return_value=None,
            ), patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py"], None),
            ), patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db"],
            ):
                payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "block_db_unreadable",
        )

    def test_no_backup_priority_over_repo_and_staged(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "find_latest_backup", return_value=None,
            ), patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db"],
            ), patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py"], None),
            ):
                payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "block_no_backup",
        )

    def test_backup_restore_priority_over_repo_and_staged(self) -> None:
        bad = dict(_OK_BACKUP_RESTORE, ok=False, errors=["x"])
        with _patch_all_clean():
            with patch.object(
                drc, "restore_check", return_value=bad,
            ), patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db"],
            ), patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py"], None),
            ):
                payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "block_backup_restore_failed",
        )

    def test_repo_priority_over_staged_and_project_health(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "list_tracked_generated",
                return_value=["events.db"],
            ), patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py"], None),
            ), patch.object(
                drc, "run_health_check",
                return_value=_bad_project_health("anything"),
            ):
                payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "block_repo_hygiene_dirty",
        )

    def test_staged_priority_over_project_health(self) -> None:
        with _patch_all_clean():
            with patch.object(
                drc, "_list_staged_files",
                return_value=(["foo.py"], None),
            ), patch.object(
                drc, "run_health_check",
                return_value=_bad_project_health("anything"),
            ):
                payload = drc.run_readiness_check()
        self.assertEqual(
            payload["recommended_next_action"],
            "block_staged_files_present",
        )


# ---------------------------------------------------------------------------
# CLI plumbing — exit code, --json, arg forwarding
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_json_output_is_valid_json(self) -> None:
        out = StringIO()
        with _patch_all_clean():
            rc = drc.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["recommended_next_action"], "ready_to_mutate")

    def test_exit_code_nonzero_on_block(self) -> None:
        out = StringIO()
        with _patch_all_clean():
            with patch.object(
                drc, "_check_events_db_readable",
                return_value=(False, "missing"),
            ):
                rc = drc.main(["--json"], out=out)
        self.assertNotEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])

    def test_text_output_lists_every_gate_name(self) -> None:
        out = StringIO()
        with _patch_all_clean():
            drc.main([], out=out)
        text = out.getvalue()
        for key in drc._GATE_KEYS:
            self.assertIn(key, text, f"text output missing {key}")

    def test_allow_duplicate_clusters_cli_flag_forwards_to_health_check(self) -> None:
        seen: list[dict] = []

        def fake(*args, **kwargs):
            seen.append(kwargs)
            return _ok_project_health()

        out = StringIO()
        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check", side_effect=fake,
            ):
                rc = drc.main(
                    ["--json", "--allow-duplicate-clusters", "28"],
                    out=out,
                )
        self.assertEqual(rc, 0)
        self.assertEqual(seen[0].get("allow_duplicate_clusters"), 28)

    def test_db_path_and_backup_dir_cli_flags_forward(self) -> None:
        seen: list[dict] = []

        def fake(*args, **kwargs):
            seen.append(kwargs)
            return _ok_project_health()

        out = StringIO()
        with _patch_all_clean():
            with patch.object(
                drc, "run_health_check", side_effect=fake,
            ):
                drc.main(
                    [
                        "--json",
                        "--db-path", "x.db",
                        "--backup-dir", "bk",
                    ],
                    out=out,
                )
        self.assertEqual(seen[0].get("db_path"),    "x.db")
        self.assertEqual(seen[0].get("backup_dir"), "bk")


# ---------------------------------------------------------------------------
# Banned imports — readiness script must never pull in
# provider/yfinance/LLM seams directly.
# ---------------------------------------------------------------------------


class TestNoBannedImports(unittest.TestCase):
    def test_module_does_not_import_banned_seams(self) -> None:
        # Walk the module's AST and inspect every ``import`` /
        # ``from ... import`` statement.  Looking at imports rather
        # than raw source so the docstring's "out of scope" callouts
        # (which legitimately *name* the banned seams to document the
        # contract) do not trip the guard.
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(drc))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])

        # Direct-import banned set: provider/yfinance/LLM seams the
        # readiness contract pins out of scope.  ``api`` and
        # ``routes`` are also banned because they would pull the
        # FastAPI app surface into the readiness namespace.
        banned = {
            "yfinance", "openai", "anthropic",
            "market_data", "market_check", "price_cache",
            "api", "routes",
        }
        self.assertEqual(
            imported & banned, set(),
            f"readiness script must not directly import: "
            f"{imported & banned}",
        )


if __name__ == "__main__":
    unittest.main()

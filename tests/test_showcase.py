"""End-to-end offline showcase and command-line checks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from second_order.demo import run_demo
from second_order.scoring import Rules

ROOT = Path(__file__).resolve().parent.parent


class ShowcaseTests(unittest.TestCase):
    def test_manual_recipe_provenance_matches_the_actual_file(self):
        import hashlib
        recipe_hash = hashlib.sha256((ROOT / "fixtures" / "manual_recipe.txt").read_bytes()).hexdigest()
        cases = json.loads((ROOT / "fixtures" / "showcase.json").read_text(encoding="utf-8"))
        self.assertTrue(all(case["engine"]["prompt_hash"] == recipe_hash for case in cases))

    def test_fictional_showcases_run_offline_and_do_not_enter_research(self):
        # Any accidental network attempt fails this test immediately.
        with patch("socket.socket.connect", side_effect=AssertionError("No network in showcase")):
            result = run_demo()
        self.assertEqual(len(result["dossiers"]), 2)
        for dossier in result["dossiers"]:
            self.assertEqual((dossier["evidence_class"], dossier["usage"]), ("replay", "showcase"))
            self.assertEqual(len(dossier["legs"]), 2)
            self.assertEqual(dossier["legs"][0]["placebo"]["selected"], 50)
            self.assertIn(dossier["verdict"], {"supported", "contradicted", "inconclusive", "mixed"})
            self.assertTrue(dossier["headline"].startswith("Demonstration: the fictional Central Bank of Demoland"))
            self.assertEqual([leg["observable_id"] for leg in dossier["legs"]], ["demo:rate", "demo:fx-index"])
        # The invented rate moves give one supported and one contradicted replay. The October fx verdict comes from the
        # recurrence alone (no invented move): re-pin it whenever demo_market.py's generator changes.
        self.assertEqual({dossier["story_id"]: [leg["verdict"] for leg in dossier["legs"]]
                          for dossier in result["dossiers"]},
                         {"demo-2024-06": ["supported", "supported"], "demo-2024-10": ["contradicted", "contradicted"]})
        self.assertIn("FICTIONAL demonstration series", result["mode"])
        for summary in result["research_scoreboards"].values():
            self.assertEqual(summary["hypotheses"], 0)
            self.assertIsNone(summary["rates"]["supported"])

    def test_persistent_demo_does_not_duplicate_frozen_records(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "demo.db")
            first, second = run_demo(path), run_demo(path)
            self.assertEqual(first, second)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 2)
            finally:
                connection.close()

    def test_schema_command_and_invalid_input_failure(self):
        result = subprocess.run([sys.executable, "-m", "second_order", "schema"], cwd=ROOT,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("legs", json.loads(result.stdout)["properties"])
        with tempfile.TemporaryDirectory() as folder:
            malformed = Path(folder) / "bad.json"
            malformed.write_text('{"not": "a hypothesis"}', encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "second_order", "freeze", str(malformed),
                                     "--db", str(Path(folder) / "test.db")],
                                    cwd=ROOT, text=True, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Failed:", result.stderr)

    def test_scoreboard_command_lists_then_selects_one_configuration_read_only(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "demo.db"
            run_demo(str(path))
            fingerprint = lambda: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                                   sorted(p.name for p in Path(folder).iterdir()))
            before = fingerprint()
            command = [sys.executable, "-m", "second_order", "scoreboard", "--db", str(path)]
            listed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=20)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            configurations = json.loads(listed.stdout)["configurations"]
            self.assertEqual([(c["rules_version"], c["hypotheses"]) for c in configurations], [(Rules().version, 2)])
            chosen = subprocess.run(command + ["--rules-hash", configurations[0]["rules_hash"]],
                                    cwd=ROOT, text=True, capture_output=True, timeout=20)
            self.assertEqual(chosen.returncode, 0, chosen.stderr)
            summaries = json.loads(chosen.stdout)
            self.assertEqual({kind: summary["hypotheses"] for kind, summary in summaries.items()},
                             {"prospective": 0, "replay": 0})  # Showcases never enter research summaries.
            refused = subprocess.run(command + ["--rules-hash", "not-a-hash"], cwd=ROOT,
                                     text=True, capture_output=True, timeout=20)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(fingerprint(), before)

    def test_foreign_database_is_rejected_without_schema_mutation(self):
        import sqlite3
        from second_order.store import open_store
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "foreign.db")
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE events(id INTEGER)")
            connection.commit()
            connection.close()
            with self.assertRaises(ValueError):
                open_store(path)
            connection = sqlite3.connect(path)
            try:
                names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                self.assertEqual(names, ["events"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()

"""Store-backed Dossier: draft -> freeze -> not yet evaluated -> outcome -> stored evaluation -> evaluated."""
from dataclasses import replace
from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fred_fixtures import FakeFred, datasets
from second_order.api import create_app
from second_order.dossier import prepare
from second_order.scoring import Rules, percentile_rank
from second_order.snapshots import evaluate_bound
from second_order.store import SCHEMA_1_SQL, open_store, save_evaluation
from test_core import snapshot
from test_daily import cmt_hypothesis, ny
from test_drafts import CLOCK
from test_fred import run_import
from test_lifecycle import AS_OF, when
from store_records import stored_before_policy_b

ROOT = Path(__file__).resolve().parent.parent
# Captured store-backed views the frontend tests read; rewritten only when WRITE_FIXTURES is set to 1.
FRONTEND_FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"


class StoreDossierTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.db_dir, self.out = root / "store", root / "prepared"
        self.db_dir.mkdir()
        self.db = str(self.db_dir / "store.db")
        connection = open_store(self.db)
        self.baseline = run_import(connection, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                                   when(date(2025, 6, 2)))["snapshot_id"]
        # A record frozen before freshness policy B (its baseline ends May 30), exactly as the freeze helper stored
        # it at CLOCK; the captured views are of this record and must not change.
        self.identity = stored_before_policy_b(connection, cmt_hypothesis(ny(2025, 6, 3, 9), CLOCK), CLOCK,
                                               self.baseline)
        connection.close()

    def tearDown(self):
        self.folder.cleanup()

    def evaluate(self, vintage=date(2025, 6, 20), rules=None, tamper=None, through=date(2025, 6, 18)) -> tuple[str, dict]:
        connection = open_store(self.db)
        try:
            outcome = run_import(connection, FakeFred(datasets(through), vintage), vintage,
                                 when(vintage))["snapshot_id"]
            payload = evaluate_bound(connection, self.identity, outcome, AS_OF, rules)
            if tamper:
                payload = tamper(json.loads(json.dumps(payload)))
            return save_evaluation(connection, self.identity, payload, AS_OF), payload
        finally:
            connection.close()

    def prepared(self, **kwargs) -> tuple[dict, dict]:
        before = snapshot(self.db_dir)
        index = prepare(self.out, db=self.db, **kwargs)
        self.assertEqual(snapshot(self.db_dir), before)  # Preparation never writes the store.
        views = {row["id"]: json.loads((self.out / f"{row['id']}.json").read_text(encoding="utf-8"))
                 for row in index["dossiers"]}
        return index, views

    def entry(self, index: dict) -> dict:
        return next(row for row in index["dossiers"] if row["id"] == self.identity)

    def test_a_frozen_case_is_shown_as_not_yet_evaluated(self):
        index, views = self.prepared()
        self.assertEqual({key: self.entry(index)[key] for key in ("source", "state", "verdict", "evaluation_id")},
                         {"source": "store", "state": "not_evaluated", "verdict": None, "evaluation_id": None})
        view = views[self.identity]
        self.assertIsNone(view["evaluation"])
        self.assertTrue(all(leg["reference"] is None and leg["series"] is None for leg in view["legs"]))
        self.assertEqual(view["label"], "Manual prospective hypothesis · showcase illustration")
        titles = [item["title"] for item in view["limitations"]]
        self.assertNotIn("Retrospective hypothesis", titles)
        self.assertNotIn("Illustrative daily timestamps", titles)
        self.assertIn("Daily measurement convention", titles)
        self.assertEqual(view["data_provenance"]["baseline"]["snapshot_id"], self.baseline)
        self.assertIsNone(view["data_provenance"]["outcome"])
        self.assertIn("FRED® API", view["data_provenance"]["attribution"])
        self.assertEqual(datetime.fromisoformat(view["hypothesis"]["frozen_at"]), CLOCK)
        fixtures = [row for row in index["dossiers"] if row["source"] == "fixture"]
        self.assertEqual([row["verdict"] for row in fixtures], ["supported", "contradicted"])

    def test_manual_wording_separates_the_model_adapter_from_ai_assistance(self):
        index, views = self.prepared()
        labels = {row["source"]: row["label"] for row in index["dossiers"]}
        self.assertEqual(labels, {"fixture": "Manually reconstructed replay · showcase illustration",
                                  "store": "Manual prospective hypothesis · showcase illustration"})
        for view in views.values():
            items = {item["title"]: item["text"] for item in view["limitations"]}
            title = "Manual submission" if view["hypothesis"]["evidence_class"] == "prospective" \
                else "Retrospective hypothesis"
            self.assertIn("outside the project's model adapter", items[title])
            self.assertIn("does not rule out AI assistance", items[title])
            # Manual means outside the adapter; the views must not claim that no AI or model was involved.
            text = json.dumps(view, ensure_ascii=False).lower()
            for claim in ("written by hand", "not a model run"):
                self.assertNotIn(claim, text)
        retrospective = [view for view in views.values() if view["hypothesis"]["evidence_class"] == "replay"]
        self.assertEqual(len(retrospective), 2)
        for view in retrospective:  # The fixture showcases stay labelled as retrospective, not blinded runs.
            text = {item["title"]: item["text"] for item in view["limitations"]}["Retrospective hypothesis"]
            self.assertIn("after the event from the committed recipe", text)
            self.assertIn("not a blinded model run", text)

    def test_the_stored_evaluation_is_shown_exactly_as_recorded(self):
        evaluation_id, payload = self.evaluate()
        index, views = self.prepared()
        view = views[self.identity]
        connection = sqlite3.connect(f"{Path(self.db).resolve().as_uri()}?mode=ro", uri=True)
        stored = json.loads(connection.execute("SELECT payload FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()[0])
        connection.close()
        self.assertEqual((view["state"], view["evaluation_id"], view["evaluation"]), ("evaluated", evaluation_id, stored))
        outcome = view["data_provenance"]["outcome"]
        self.assertEqual((outcome["snapshot_id"], outcome["vintage_date"]), (payload["snapshots"]["outcome"], "2025-06-20"))
        self.assertEqual(datetime.fromisoformat(outcome["retrieved_at"]), when(date(2025, 6, 20)))
        primary = view["legs"][0]
        self.assertEqual(primary["anchor_dates"], {"event_anchor": "2025-05-30", "reference_end": "2025-05-30",
                                                   "score_anchor": "2025-06-04", "target_at": "2025-06-11"})
        series = primary["series"]
        dates = [point[0] for point in series["points"]]
        self.assertEqual(series["time_basis"], "daily_date")
        self.assertTrue(all(len(day) == 10 for day in dates))  # New York dates, never a time of day.
        self.assertLessEqual({"2025-05-30", "2025-06-04", "2025-06-11"}, set(dates))
        self.assertIn("FRED® API", series["attribution"])
        result = view["evaluation"]["legs"][0]
        self.assertEqual(percentile_rank(result["signed_move"], primary["reference"]["values"]), result["percentile_rank"])
        self.assertEqual((self.entry(index)["verdict"], self.entry(index)["rules_version"]),
                         (payload["verdict"], Rules().version))

    def test_several_stored_evaluations_need_an_explicit_selection(self):
        self.evaluate()
        second, _ = self.evaluate(vintage=date(2025, 6, 21))
        with self.assertRaisesRegex(ValueError, "choose one with --evaluation"):
            prepare(self.out, db=self.db)
        _, views = self.prepared(selections={self.identity: second})
        self.assertEqual(views[self.identity]["evaluation_id"], second)
        with self.assertRaisesRegex(ValueError, "is not stored for hypothesis"):
            prepare(self.out, db=self.db, selections={self.identity: "0" * 64})

    def test_a_stored_evaluation_is_never_rescored_under_the_current_rules(self):
        self.evaluate(rules=replace(Rules(), version="0.4.9", upper=.9))
        _, views = self.prepared()
        rules = views[self.identity]["evaluation"]["rules"]
        self.assertEqual((rules["version"], rules["upper"]), ("0.4.9", .9))

    def test_an_irreproducible_stored_evaluation_fails_clearly(self):
        def tamper(payload):
            payload["legs"][0]["percentile_rank"] = 0.5
            return payload
        tampered, _ = self.evaluate(tamper=tamper)
        with self.assertRaisesRegex(ValueError, "cannot be reproduced"):
            prepare(self.out, db=self.db)
        self.assertFalse(self.out.exists())  # Nothing is written when any view fails.

    def test_prepared_reads_never_touch_the_store_or_prepare(self):
        self.evaluate()
        self.prepared()
        before = snapshot(self.db_dir)
        forbidden = AssertionError("A read path evaluated, prepared, opened the store or fetched")
        with TestClient(create_app(self.out, None), base_url="http://127.0.0.1:8000") as client, \
                patch("second_order.snapshots.evaluate_bound", side_effect=forbidden), \
                patch("second_order.dossier.prepare", side_effect=forbidden), \
                patch("sqlite3.connect", side_effect=forbidden), \
                patch("socket.socket.connect", side_effect=forbidden):
            listed = client.get("/api/dossiers").json()
            self.assertIn(self.identity, [row["id"] for row in listed["dossiers"]])
            response = client.get(f"/api/dossiers/{self.identity}")
            self.assertEqual(response.content, (self.out / f"{self.identity}.json").read_bytes())
        self.assertEqual(snapshot(self.db_dir), before)

    def test_a_schema_1_store_contributes_no_cases_and_is_not_migrated(self):
        old_dir = Path(self.folder.name) / "old"
        old_dir.mkdir()
        connection = sqlite3.connect(old_dir / "old.db")
        connection.executescript(SCHEMA_1_SQL)
        connection.close()
        before = snapshot(old_dir)
        index = prepare(Path(self.folder.name) / "old-prepared", db=str(old_dir / "old.db"))
        self.assertEqual({row["source"] for row in index["dossiers"]}, {"fixture"})
        self.assertEqual(snapshot(old_dir), before)

    def captured_views(self) -> dict[str, dict]:
        """Real prepared output for one case: frozen, then a pending evaluation, then a complete one."""
        index_frozen, frozen = self.prepared()
        self.evaluate(vintage=date(2025, 6, 9), through=date(2025, 6, 6))  # The outcome ends before the horizon.
        index_pending, pending = self.prepared()
        complete, _ = self.evaluate()
        _, evaluated = self.prepared(selections={self.identity: complete})
        return {"store-not-evaluated.json": frozen[self.identity], "store-pending.json": pending[self.identity],
                "store-evaluated.json": evaluated[self.identity],
                "index-not-evaluated.json": index_frozen, "index-pending.json": index_pending}

    def test_an_evaluation_before_the_horizon_is_recorded_as_pending(self):
        evaluation_id, payload = self.evaluate(vintage=date(2025, 6, 9), through=date(2025, 6, 6))
        index, views = self.prepared()
        entry = self.entry(index)
        self.assertEqual((entry["state"], entry["verdict"], entry["evaluation_id"]),
                         ("evaluated", "pending", evaluation_id))
        primary = payload["legs"][0]
        self.assertEqual((primary["verdict"], primary["reason"]),
                         ("pending", "The scored horizon is not in the imported data yet"))
        self.assertNotIn("target_at", primary)
        self.assertIsNone(views[self.identity]["legs"][0]["reference"])  # Nothing was ranked for it.

    def test_the_frontend_fixtures_are_the_captured_prepared_views(self):
        captured = self.captured_views()
        if os.environ.get(WRITE_FIXTURES) == "1":  # Explicit opt-in; a default run only compares.
            FRONTEND_FIXTURES.mkdir(parents=True, exist_ok=True)
            for name, view in captured.items():
                text = json.dumps(view, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
                (FRONTEND_FIXTURES / name).write_bytes(text.encode("utf-8"))
        for name, view in captured.items():
            committed = json.loads((FRONTEND_FIXTURES / name).read_text(encoding="utf-8"))
            self.assertEqual(view, committed, f"frontend/tests/fixtures/{name} is stale; regenerate it with "
                                              f"{WRITE_FIXTURES}=1 python -m unittest discover -s tests "
                                              "-p test_store_dossier.py")

    def test_the_cli_prepares_store_cases_and_validates_selections(self):
        run = lambda *arguments: subprocess.run([sys.executable, "-m", "second_order", "prepare", "--out",
                                                 str(self.out), *arguments], cwd=ROOT, text=True,
                                                capture_output=True, timeout=60)
        prepared = run("--db", self.db)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual([row["source"] for row in json.loads(prepared.stdout)["dossiers"]], ["fixture", "fixture", "store"])
        refused = run("--evaluation", f"{self.identity}=x")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("name the store with --db", refused.stderr)


if __name__ == "__main__":
    unittest.main()

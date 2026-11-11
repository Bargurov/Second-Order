"""Outcome readiness, explicit assessment, Dossier preparation and the journal (A3), through the app's own routes on
temporary folders. SYNTHETIC data only.

Kept packages are SYNTHETIC release packages (market_fakes) kept directly in a temporary market folder; FRED snapshots
come from the mocked FRED fixture. No network is reached, no real store is opened and nothing real is frozen or
assessed. Counts of stored records and comparisons of every file under the temporary root show what each action wrote.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from fred_fixtures import FakeFred, datasets
from market_fakes import keep_package, release_data, release_zip
from second_order import assessment, market_retrieval
from second_order.api import create_app
from second_order.assessment_records import PreparationFailed
from second_order.schema import Hypothesis
from second_order.store import (SCHEMA_1_SQL, SCHEMA_2_SQL, SCHEMA_3_SQL, SCHEMA_3_TABLES, append_only_triggers,
                                digest, open_store)
from store_records import stored_before_policy_b
from test_daily import cmt_hypothesis, ny
from test_fred import run_import
from test_lifecycle_freeze import BASE, FIRST, LIFECYCLE, ROOT, STALE, Harness, manual, tree

UTC = timezone.utc
T0 = datetime(2026, 9, 15, 19, tzinfo=UTC)  # 3 p.m. in New York on the publication date, Tuesday 15 September.
OUTCOME = (date(2026, 9, 30), datetime(2026, 10, 1, 12, tzinfo=UTC))  # Data through, requested at.
AFTER = datetime(2026, 10, 1, 13, tzinfo=UTC)


def second_form() -> dict:
    return manual(headline="Synthetic second release for an isolation check", story_id="synthetic-second",
                  source_url="https://example.com/second-release")


class AssessmentHarness(Harness):
    def setUp(self):
        super().setUp()
        self.clock.moment = T0
        self._baseline = None
        self.dossiers = self.store.parent / "research-dossiers"

    def at(self, moment: datetime) -> None:
        self.clock.moment = moment

    def shared_baseline(self) -> str:
        if self._baseline is None:
            self._baseline = self.baseline()
        return self._baseline

    def frozen(self, form: dict | None = None, at: datetime = T0) -> str:
        baseline = self.shared_baseline()
        self.at(at)
        inputs = self.inputs(baseline, form)
        shown = self.preview(inputs)
        self.assertTrue(shown["freezable"], shown["blockers"])
        response = self.approve(inputs, shown)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["hypothesis_id"]

    def outcome_package(self, through: date = OUTCOME[0], requested: datetime = OUTCOME[1],
                        overrides: dict | None = None, revise: bool = False) -> str:
        package_id = keep_package(self.market, release_zip(release_data(FIRST, through, overrides, revise)), requested)
        market_retrieval.validate_packages(self.market, lambda: requested + timedelta(minutes=1))
        return package_id

    def import_outcome(self, hypothesis_id: str, package_id: str, expect: int = 201) -> dict:
        response = self.client.post("/api/lifecycle/outcome-imports", headers=LIFECYCLE,
                                    content=json.dumps({"hypothesis_id": hypothesis_id, "package_id": package_id}))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def readiness(self, hypothesis_id: str) -> dict:
        response = self.client.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/readiness")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assessment_preview(self, hypothesis_id: str, snapshot_id: str, expect: int = 200) -> dict:
        response = self.client.post("/api/lifecycle/assessment-preview", headers=LIFECYCLE, content=json.dumps(
            {"inputs": {"hypothesis_id": hypothesis_id, "outcome_snapshot_id": snapshot_id}}))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def body(self, shown: dict, reassessment: bool | None = None, sha: str | None = None) -> str:
        bound = shown["binding"]
        return json.dumps({"inputs": {"hypothesis_id": bound["hypothesis_id"],
                                      "outcome_snapshot_id": bound["outcome_snapshot_id"]},
                           "preview_sha256": sha or shown["preview_sha256"], "approve_assessment": True,
                           "reassessment": bound["reassessment"] if reassessment is None else reassessment,
                           "previewed_binding": bound})

    def assess(self, shown: dict, **changes):
        return self.client.post("/api/lifecycle/assessments", headers=LIFECYCLE, content=self.body(shown, **changes))

    def ready(self, form: dict | None = None) -> tuple[str, str]:
        """A hypothesis frozen at T0 and an outcome snapshot imported at AFTER that covers every target."""
        hypothesis_id = self.frozen(form)
        package_id = self.outcome_package()
        self.at(AFTER)
        return hypothesis_id, self.import_outcome(hypothesis_id, package_id)["snapshot"]["snapshot_id"]

    def recorded(self, form: dict | None = None) -> tuple[str, str, dict]:
        hypothesis_id, snapshot = self.ready(form)
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(shown["assessable"], shown["blockers"])
        response = self.assess(shown)
        self.assertEqual(response.status_code, 201, response.text)
        return hypothesis_id, snapshot, response.json()

    def counts(self) -> dict:
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("hypotheses", "freeze_actions", "evaluations", "assessment_actions",
                                  "market_snapshots") if table in present}
        finally:
            connection.close()

    def evaluation_rows(self) -> list[tuple]:
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return list(connection.execute("SELECT id, hypothesis_id, recorded_at, payload FROM evaluations ORDER BY "
                                           "recorded_at, id"))
        finally:
            connection.close()


class ReadinessTests(AssessmentHarness):
    def test_states_are_kept_apart_and_reads_write_nothing(self):
        hypothesis_id = self.frozen()
        self.at(datetime(2026, 9, 22, 15, tzinfo=UTC))
        before = tree(self.root)
        shown = self.readiness(hypothesis_id)
        self.assertEqual(tree(self.root), before)
        self.assertEqual(shown["state"], "horizon_not_elapsed")
        self.assertEqual(self.client.get("/api/lifecycle").json()["hypotheses"][0]["state"], "horizon_not_elapsed")
        self.assertEqual((shown["expected"]["expected_score_anchor"], shown["expected"]["latest_expected_target"],
                          shown["expected"]["counts_after"]), ("2026-09-16", "2026-09-23", "2026-09-23T23:59:59-04:00"))
        self.assertEqual(shown["candidates"], [])  # The baseline bound at freeze is never an outcome.
        self.at(datetime(2026, 9, 24, 15, tzinfo=UTC))
        self.assertEqual(self.readiness(hypothesis_id)["state"], "outcome_missing")
        early = self.outcome_package(date(2026, 9, 21), datetime(2026, 9, 22, 12, tzinfo=UTC))
        imported = self.import_outcome(hypothesis_id, early)
        shown = self.readiness(hypothesis_id)
        self.assertEqual(shown["state"], "outcome_missing")
        [candidate] = shown["candidates"]
        self.assertEqual((candidate["snapshot_id"], candidate["usable"], candidate["state"]),
                         (imported["snapshot"]["snapshot_id"], True, "outcome_missing"))
        self.assertIn("end on 2026-09-21", candidate["legs"][0]["detail"])
        complete = self.outcome_package()
        self.at(AFTER)
        journal = lambda: self.client.get("/api/lifecycle").json()["hypotheses"][0]  # noqa: E731
        self.assertEqual((journal()["state"], journal()["state_label"]),
                         ("outcome_in_package", "Outcome data in a kept package · import it"))
        snapshot = self.import_outcome(hypothesis_id, complete)["snapshot"]["snapshot_id"]
        self.assertEqual(journal()["state"], "outcome_held")
        before = tree(self.root)
        shown = self.readiness(hypothesis_id)
        self.assertEqual(tree(self.root), before)
        self.assertEqual(shown["state"], "ready")
        ready = next(item for item in shown["candidates"] if item["snapshot_id"] == snapshot)
        self.assertEqual({(leg["event_anchor"], leg["score_anchor"], leg["target"], leg["state"]) for leg in ready["legs"]},
                         {("2026-09-14", "2026-09-16", "2026-09-23", "ready")})
        package = next(row for row in shown["packages"] if row["package_id"] == complete)
        self.assertEqual((package["serving_snapshot"], package["importable"]), (snapshot, False))
        self.assertEqual((self.counts()["evaluations"], self.dossiers.exists()), (0, False))

    def test_a_date_only_target_counts_only_after_its_new_york_date_ends(self):
        hypothesis_id = self.frozen()
        # Received at 10 p.m. in New York on the target date, stating that date's value.
        package_id = self.outcome_package(date(2026, 9, 23), datetime(2026, 9, 24, 2, tzinfo=UTC))
        self.at(datetime(2026, 9, 24, 3, tzinfo=UTC))  # 11 p.m. in New York: the target date has not ended.
        snapshot = self.import_outcome(hypothesis_id, package_id)["snapshot"]["snapshot_id"]
        shown = self.readiness(hypothesis_id)
        self.assertEqual((shown["state"], shown["candidates"][0]["state"]), ("horizon_not_elapsed", "horizon_not_elapsed"))
        early = self.assessment_preview(hypothesis_id, snapshot)
        self.assertFalse(early["assessable"])
        self.assertIn("has not ended", " ".join(early["blockers"]))
        self.assertEqual(self.assess(early).status_code, 409)
        self.at(datetime(2026, 9, 24, 4, tzinfo=UTC))  # Midnight in New York.
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(shown["assessable"], shown["blockers"])
        # The cutoff is the end of the target date, after the receipt time; it is never the arrival of a request.
        self.assertEqual(shown["binding"]["cutoff"], "2026-09-24T03:59:59+00:00")
        response = self.assess(shown)
        self.assertEqual(response.status_code, 201, response.text)
        [(_, _, _, payload)] = self.evaluation_rows()
        stored = json.loads(payload)
        self.assertEqual(stored["as_of"], "2026-09-24T03:59:59+00:00")
        self.assertNotIn("pending", {leg["verdict"] for leg in stored["legs"]})

    def test_genuine_missing_values_are_recorded_as_unavailable_and_never_filled(self):
        hypothesis_id = self.frozen()
        package_id = self.outcome_package(overrides={date(2026, 9, 18): ("ND", "ND")})  # A session stated with no value.
        self.at(AFTER)
        snapshot = self.import_outcome(hypothesis_id, package_id)["snapshot"]["snapshot_id"]
        shown = self.readiness(hypothesis_id)
        self.assertEqual(shown["state"], "missing_values")
        self.assertEqual(shown["candidates"][0]["legs"][0]["gaps"], [{"date": "2026-09-18", "status": "session_missing"}])
        previewed = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(previewed["assessable"], previewed["blockers"])
        response = self.assess(previewed)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["dossier"]["state"], "prepared")
        [(_, _, _, payload)] = self.evaluation_rows()
        legs = json.loads(payload)["legs"]
        self.assertEqual({(leg["verdict"], leg["reason"]) for leg in legs},
                         {("unavailable", "Missing observation inside the required window")})
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        stored = connection.execute("SELECT value, raw_value, status FROM market_observations WHERE snapshot_id=? AND "
                                    "date='2026-09-18'", (snapshot,)).fetchall()
        connection.close()
        self.assertEqual(set(stored), {(None, "ND", "session_missing")})


class RefusalTests(AssessmentHarness):
    def test_cross_provider_incomplete_and_corrupted_outcomes_are_refused(self):
        hypothesis_id, snapshot = self.ready()
        connection = sqlite3.connect(self.store)
        fred = run_import(connection, FakeFred(datasets(date(2026, 9, 30)), date(2026, 10, 1)), date(2026, 10, 1),
                          OUTCOME[1])["snapshot_id"]
        connection.close()
        refused = self.assessment_preview(hypothesis_id, fred, expect=422)
        self.assertIn("never measured on another provider's data", refused["detail"])
        package_id = self.outcome_package(requested=OUTCOME[1] + timedelta(minutes=5))
        late_start = self.import_baseline(package_id, start="2026-09-17")["snapshot"]["snapshot_id"]
        incomplete = self.assessment_preview(hypothesis_id, late_start)
        self.assertFalse(incomplete["assessable"])
        self.assertIn("only from 2026-09-17, after the publication date 2026-09-15", " ".join(incomplete["blockers"]))
        listed = {item["snapshot_id"]: item for item in self.readiness(hypothesis_id)["candidates"]}
        self.assertEqual((listed[late_start]["usable"], listed[snapshot]["usable"]), (False, True))
        self.assertNotIn(fred, listed)  # Only the hypothesis's own provider is offered.
        # A stored row changed after import: the snapshot no longer verifies and is never used.
        writer = sqlite3.connect(self.store)
        writer.execute("DROP TRIGGER market_observations_no_update")
        writer.execute("UPDATE market_observations SET value = value + 1 WHERE snapshot_id=? AND date='2026-09-17'",
                       (snapshot,))
        writer.commit()
        writer.close()
        counts = self.counts()
        corrupted = self.assessment_preview(hypothesis_id, snapshot, expect=409)
        self.assertIn("does not verify", corrupted["detail"])
        self.assertFalse({item["snapshot_id"]: item for item in self.readiness(hypothesis_id)["candidates"]}[snapshot]
                         ["usable"])
        # A kept package whose bytes changed is refused by the import, and nothing is written.
        damaged = self.outcome_package(requested=OUTCOME[1] + timedelta(minutes=10))
        archive = self.market / "packages" / damaged / "package.zip"
        os.chmod(archive, stat.S_IWRITE | stat.S_IREAD)
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        archive.write_bytes(bytes(data))
        refused = self.import_outcome(hypothesis_id, damaged, expect=409)
        self.assertIn("does not verify", refused["detail"])
        self.assertEqual(self.counts(), counts)

    def test_a_schema_3_store_needs_the_explicit_upgrade_before_an_assessment(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        connection.executescript("BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + SCHEMA_3_SQL
                                 + append_only_triggers(sorted(SCHEMA_3_TABLES))
                                 + "INSERT INTO store_meta VALUES ('schema_version', '3'); COMMIT;")
        connection.close()
        hypothesis_id, snapshot = self.ready()  # Freezing works on schema 3.
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertFalse(shown["assessable"])
        self.assertIn("This store uses schema 3", " ".join(shown["blockers"]))
        self.assertEqual(self.assess(shown).status_code, 409)
        self.assertEqual(self.counts()["evaluations"], 0)
        upgraded = self.client.post("/api/lifecycle/store-upgrade", headers=LIFECYCLE,
                                    content=json.dumps({"upgrade_to": 4}))
        self.assertEqual(upgraded.status_code, 201, upgraded.text)
        self.assertEqual(upgraded.json()["migrated_from_schema"], 3)
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(shown["assessable"], shown["blockers"])
        self.assertEqual(self.assess(shown).status_code, 201)


class AssessmentTests(AssessmentHarness):
    def test_one_approval_evaluates_records_and_prepares_only_the_selected_hypothesis(self):
        other = self.frozen(second_form())
        hypothesis_id, snapshot = self.ready()
        before, counts = tree(self.root), self.counts()
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertEqual((tree(self.root), self.counts()), (before, counts))  # A preview writes and evaluates nothing.
        self.assertEqual((shown["written"], shown["evaluated"], shown["provider_called"]), (False, False, False))
        self.assertNotIn('"verdict"', json.dumps(shown))  # The result is not computed before an approval.
        self.assertNotIn("measured_change", json.dumps(shown))
        bound = shown["binding"]
        self.assertEqual((bound["hypothesis_id"], bound["hypothesis_sha256"], bound["baseline_snapshot_id"],
                          bound["outcome_snapshot_id"], bound["provider"], bound["reassessment"]),
                         (hypothesis_id, hypothesis_id, self.shared_baseline(), snapshot, "board-h15", False))
        self.assertEqual(bound["rules"]["version"], "0.5.0")
        self.assertIn("does not pin scoring rules", shown["rules"]["note"])
        self.assertEqual(bound["cutoff"], shown["outcome"]["retrieved_at"])  # Receipt is later than the targets' ends.
        self.assertEqual(len(shown["creates"]), 3)
        self.at(AFTER + timedelta(minutes=10))  # Elapsed minutes change nothing an approval binds.
        response = self.assess(shown)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual((result["headline"], result["created"], result["dossier"]["state"]),
                         ("Evaluation saved and Dossier prepared", True, "prepared"))
        self.assertEqual({row[1] for row in self.evaluation_rows()}, {hypothesis_id})
        self.assertEqual({key: value for key, value in self.counts().items() if key != "market_snapshots"},
                         {**{key: value for key, value in counts.items() if key != "market_snapshots"},
                          "evaluations": 1, "assessment_actions": 1})
        self.assertEqual(sorted(tree(self.dossiers)), [f"{hypothesis_id}/{result['evaluation_id']}.json"])
        stored = json.loads(self.evaluation_rows()[0][3])
        self.assertEqual((stored["as_of"], stored["rules_hash"], stored["snapshots"]["outcome"]),
                         (bound["cutoff"], bound["rules_hash"], snapshot))
        self.assertEqual(self.readiness(other)["assessments"], [])  # The other hypothesis was not assessed.

    def test_changed_inputs_need_a_new_preview(self):
        hypothesis_id, snapshot = self.ready()
        shown = self.assessment_preview(hypothesis_id, snapshot)
        tampered = self.assess(shown, sha="0" * 64)
        self.assertEqual(tampered.status_code, 409)
        self.assertIn("has changed", tampered.json()["detail"])
        refused = self.client.post("/api/lifecycle/assessments", headers=LIFECYCLE, content=json.dumps(
            {**json.loads(self.body(shown)), "approve_assessment": False}))
        self.assertEqual(refused.status_code, 422)
        # Another tab records an assessment on another outcome; this approval is now about a different situation.
        newer = self.outcome_package(requested=OUTCOME[1] + timedelta(minutes=20), revise=True)
        self.at(AFTER + timedelta(minutes=30))
        other_snapshot = self.import_outcome(hypothesis_id, newer)["snapshot"]["snapshot_id"]
        first = self.assessment_preview(hypothesis_id, other_snapshot)
        self.assertEqual(self.assess(first).status_code, 201)
        stale = self.assess(shown)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("the recorded assessments", stale.json()["detail"])
        self.assertTrue(stale.json()["preview"]["binding"]["reassessment"])
        self.assertEqual(self.counts()["evaluations"], 1)

    def test_concurrent_approvals_record_one_assessment(self):
        hypothesis_id, snapshot = self.ready()
        shown = self.assessment_preview(hypothesis_id, snapshot)
        body = self.body(shown).encode("utf-8")
        start, results, errors = threading.Barrier(4), [], []

        def tab():
            start.wait()
            try:
                results.append(assessment.assess(body, self.folders(), self.clock))
            except Exception as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)
        threads = [threading.Thread(target=tab) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result["created"] for result in results), [False, False, False, True])
        self.assertEqual(len({result["evaluation_id"] for result in results}), 1)
        self.assertEqual((self.counts()["evaluations"], self.counts()["assessment_actions"]), (1, 1))
        self.assertEqual(len(tree(self.dossiers)), 1)

    def test_concurrent_worker_processes_with_one_fresh_approval_record_exactly_once(self):
        hypothesis_id, snapshot = self.ready()
        body = self.body(self.assessment_preview(hypothesis_id, snapshot))
        worker = ("import json, sys; from datetime import datetime; from pathlib import Path; "
                  "from second_order import assessment, lifecycle; args = json.loads(sys.argv[1]); "
                  "folders = lifecycle.Folders(**{k: Path(v) for k, v in args['folders'].items()}); "
                  "clock = datetime.fromisoformat(args['clock']); "
                  "print(json.dumps(assessment.assess(args['body'].encode(), folders, lambda: clock)['created']))")
        argument = json.dumps({"body": body, "clock": self.clock().isoformat(), "folders": {
            "store": str(self.store), "market": str(self.market), "intake": str(self.intake),
            "attempts": str(self.attempts), "drafts": str(self.drafts), "published": str(self.published),
            "reviews": str(self.reviews)}})
        processes = [subprocess.Popen([sys.executable, "-c", worker, argument], cwd=ROOT, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(3)]
        created = []
        for process in processes:
            out, err = process.communicate(timeout=180)
            self.assertEqual(process.returncode, 0, err)
            created.append(json.loads(out))
        self.assertEqual(sorted(created), [False, False, True])
        self.assertEqual((self.counts()["evaluations"], self.counts()["assessment_actions"]), (1, 1))
        self.assertEqual(len(tree(self.dossiers)), 1)

    def test_concurrent_approvals_on_different_outcomes_record_only_one(self):
        hypothesis_id, snapshot = self.ready()
        newer = self.outcome_package(requested=OUTCOME[1] + timedelta(minutes=20), revise=True)
        self.at(AFTER + timedelta(minutes=30))
        other = self.import_outcome(hypothesis_id, newer)["snapshot"]["snapshot_id"]
        bodies = [self.body(self.assessment_preview(hypothesis_id, sid)).encode("utf-8") for sid in (snapshot, other)]
        start, outcomes = threading.Barrier(2), []

        def tab(body):
            start.wait()
            try:
                outcomes.append(("recorded", assessment.assess(body, self.folders(), self.clock)["created"]))
            except assessment.LifecycleRefused as exc:
                outcomes.append(("refused", exc.status))
        threads = [threading.Thread(target=tab, args=(body,)) for body in bodies]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(sorted(outcomes), [("recorded", True), ("refused", 409)])
        self.assertEqual(self.counts()["evaluations"], 1)

    def test_a_lost_reply_is_resolved_by_reads_that_never_resend(self):
        hypothesis_id, snapshot = self.ready()
        shown = self.assessment_preview(hypothesis_id, snapshot)
        path = f"/api/lifecycle/assessment-actions/{shown['preview_sha256']}"
        before = tree(self.root)
        self.assertEqual(self.client.get(path).json()["state"], "not_recorded")
        self.assertEqual(tree(self.root), before)
        recorded = self.assess(shown).json()
        settled = tree(self.root)
        state = self.client.get(path).json()
        self.assertEqual((state["state"], state["evaluation_id"], state["dossier"]["state"]),
                         ("recorded", recorded["evaluation_id"], "prepared"))
        repeat = self.assess(shown)  # A deliberate second click returns the saved result; nothing is recomputed.
        self.assertEqual((repeat.status_code, repeat.json()["created"], repeat.json()["evaluation_id"]),
                         (200, False, recorded["evaluation_id"]))
        self.assertEqual(tree(self.root), settled)

    def test_an_identical_assessment_is_shown_as_saved_not_recomputed(self):
        hypothesis_id, snapshot, recorded = self.recorded()
        with patch("second_order.assessment.evaluate_bound", side_effect=AssertionError("recomputed")):
            again = self.assessment_preview(hypothesis_id, snapshot)
            self.assertEqual((again["state"], again["assessable"]), ("recorded", False))
            self.assertIn(recorded["evaluation_id"], " ".join(again["blockers"]))
            self.assertEqual(self.assess(again).status_code, 409)
        self.assertEqual(self.counts()["evaluations"], 1)

    def test_a_reassessment_appends_and_needs_its_own_decision(self):
        hypothesis_id, snapshot, first = self.recorded()
        rows = self.evaluation_rows()
        revised = self.outcome_package(requested=OUTCOME[1] + timedelta(hours=1), revise=True)
        self.at(AFTER + timedelta(hours=2))
        other = self.import_outcome(hypothesis_id, revised)["snapshot"]["snapshot_id"]
        shown = self.assessment_preview(hypothesis_id, other)
        self.assertTrue(shown["assessable"], shown["blockers"])
        self.assertEqual((shown["binding"]["reassessment"], shown["binding"]["prior_assessments"]),
                         (True, [first["evaluation_id"]]))
        self.assertEqual(self.assess(shown, reassessment=False).status_code, 422)
        second = self.assess(shown)
        self.assertEqual(second.status_code, 201, second.text)
        later = self.evaluation_rows()
        self.assertEqual(len(later), 2)
        self.assertIn(rows[0], later)  # The earlier assessment is unchanged.
        listed = self.client.get("/api/lifecycle").json()["hypotheses"][0]
        self.assertEqual([row["evaluation_id"] for row in listed["assessments"]],
                         [first["evaluation_id"], second.json()["evaluation_id"]])
        self.assertEqual({row["dossier"]["state"] for row in listed["assessments"]}, {"prepared"})

    def test_a_failed_preparation_keeps_the_evaluation_and_explicit_preparation_completes_it(self):
        hypothesis_id, snapshot = self.ready()
        shown = self.assessment_preview(hypothesis_id, snapshot)
        with patch("second_order.assessment.prepare_dossier", side_effect=PreparationFailed("simulated failure")):
            response = self.assess(shown)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual((result["headline"], result["dossier"]["state"]),
                         ("Evaluation saved; Dossier not prepared", "not_prepared"))
        self.assertIn("simulated failure", result["dossier"]["detail"])
        self.assertEqual((self.counts()["evaluations"], self.dossiers.exists()), (1, False))
        view = self.client.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/assessments/{result['evaluation_id']}")
        self.assertEqual(view.json()["dossier"]["state"], "not_prepared")
        self.assertEqual(self.client.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/"
                                         f"{result['evaluation_id']}").status_code, 404)
        rows = self.evaluation_rows()
        prepare = json.dumps({"hypothesis_id": hypothesis_id, "evaluation_id": result["evaluation_id"],
                              "approve_preparation": True})
        prepared = self.client.post("/api/lifecycle/dossier-preparations", headers=LIFECYCLE, content=prepare)
        self.assertEqual(prepared.status_code, 201, prepared.text)
        self.assertEqual((prepared.json()["evaluated"], self.evaluation_rows()), (False, rows))  # Nothing re-recorded.
        files = tree(self.dossiers)
        again = self.client.post("/api/lifecycle/dossier-preparations", headers=LIFECYCLE, content=prepare)
        self.assertEqual((again.status_code, again.json()["created"], tree(self.dossiers)), (200, False, files))


class ReopenTests(AssessmentHarness):
    def test_the_journal_assessment_and_dossier_reopen_after_a_restart_without_writes(self):
        hypothesis_id, snapshot, recorded = self.recorded()
        evaluation_id = recorded["evaluation_id"]
        restarted = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                          self.attempts, market=self.market, store=self.store,
                                          lifecycle_clock=self.clock), base_url=BASE)
        self.addCleanup(restarted.close)
        before = tree(self.root)
        journal = restarted.get("/api/lifecycle").json()
        [row] = journal["hypotheses"]
        self.assertEqual((row["state"], row["provider"], row["origin"]), ("recorded", "board-h15", "manual"))
        self.assertEqual([item["evaluation_id"] for item in row["assessments"]], [evaluation_id])
        view = restarted.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/assessments/{evaluation_id}").json()
        self.assertEqual((view["recorded_by"], view["action"]["binding"]["outcome_snapshot_id"], view["position"]),
                         ("interface approval", snapshot, 1))
        # New York dates, never the UTC date of a stored end-of-day placeholder (which is the next day).
        self.assertEqual({(dates["score_anchor"], dates["target_at"]) for dates in view["anchor_dates"].values()},
                         {("2026-09-16", "2026-09-23")})
        dossier = restarted.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{evaluation_id}").json()
        stored = json.loads(self.evaluation_rows()[0][3])
        self.assertEqual(dossier["view"]["evaluation"], stored)
        self.assertEqual(dossier["view"]["state"], "evaluated")
        self.assertEqual({role: (item["verifies"], item["raw_source"]["held"])
                          for role, item in dossier["snapshots"].items()},
                         {"baseline": (True, True), "outcome": (True, True)})
        self.assertEqual(tree(self.root), before)  # Reopening read everything and wrote nothing.
        # Without the package folders the copied observations still serve; only the raw source is no longer held.
        shutil.move(str(self.market / "packages"), str(self.root / "packages-moved-aside"))
        dossier = restarted.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{evaluation_id}").json()
        self.assertEqual({role: (item["verifies"], item["raw_source"]["held"])
                          for role, item in dossier["snapshots"].items()},
                         {"baseline": (True, False), "outcome": (True, False)})

    def test_a_tampered_dossier_file_is_not_shown(self):
        hypothesis_id, _, recorded = self.recorded()
        path = self.dossiers / hypothesis_id / f"{recorded['evaluation_id']}.json"
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["view"]["evaluation"]["verdict"] = "supported" if record["view"]["evaluation"]["verdict"] != \
            "supported" else "contradicted"
        path.write_text(json.dumps(record), encoding="utf-8")
        response = self.client.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{recorded['evaluation_id']}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.readiness(hypothesis_id)["assessments"][0]["dossier"]["state"], "problem")

    def test_a_dossier_file_prepared_at_view_0_2_is_still_shown_and_an_unknown_version_is_not(self):
        hypothesis_id, _, recorded = self.recorded()
        evaluation_id = recorded["evaluation_id"]
        path = self.dossiers / hypothesis_id / f"{evaluation_id}.json"
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["view_version"], "dossier-view-0.3")  # New files carry the current version.
        address = f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{evaluation_id}"
        for version, status, state in (("dossier-view-0.2", 200, "prepared"), ("dossier-view-0.1", 409, "problem")):
            with self.subTest(version=version):
                # A file as an earlier version wrote it: a store case's view is the same in 0.2 and 0.3.
                view = {**record["view"], "view_version": version}
                path.write_text(json.dumps({**record, "view_version": version, "view": view,
                                            "view_sha256": digest(view)}), encoding="utf-8")
                response = self.client.get(address)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(self.readiness(hypothesis_id)["assessments"][0]["dossier"]["state"], state)
                if status == 200:
                    self.assertEqual(response.json()["view"]["view_version"], version)


class LegacyTests(AssessmentHarness):
    def test_a_fred_hypothesis_is_assessed_only_on_local_fred_snapshots(self):
        self.store.parent.mkdir(parents=True)
        writer = open_store(str(self.store))
        baseline = run_import(writer, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                              datetime(2025, 6, 2, 22, tzinfo=UTC))["snapshot_id"]
        published, frozen = ny(2025, 6, 3, 9), ny(2025, 6, 3, 9, 30)
        hypothesis_id = stored_before_policy_b(writer, cmt_hypothesis(published, frozen), frozen, baseline)
        outcome = run_import(writer, FakeFred(datasets(date(2025, 6, 18)), date(2025, 6, 20)), date(2025, 6, 20),
                             datetime(2025, 6, 20, 22, tzinfo=UTC))["snapshot_id"]
        writer.close()
        h15 = self.outcome_package(requested=datetime(2025, 6, 21, 12, tzinfo=UTC), through=date(2025, 6, 20))
        self.at(datetime(2025, 6, 22, 12, tzinfo=UTC))
        shown = self.readiness(hypothesis_id)
        self.assertEqual((shown["provider"], shown["state"], shown["packages"]), ("fred", "ready", []))
        self.assertIn("never substituted", shown["fred_note"])
        self.assertIn("frozen outside this interface", shown["rules_note"])
        refused = self.import_outcome(hypothesis_id, h15, expect=409)  # No H.15 outcome for FRED-bound legs.
        self.assertIn("FRED", refused["detail"])
        previewed = self.assessment_preview(hypothesis_id, outcome)
        self.assertTrue(previewed["assessable"], previewed["blockers"])
        response = self.assess(previewed)
        self.assertEqual(response.status_code, 201, response.text)
        dossier = self.client.get(f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/"
                                  f"{response.json()['evaluation_id']}").json()
        self.assertEqual(dossier["view"]["data_provenance"]["provider"], "FRED")
        self.assertIsNone(dossier["snapshots"]["outcome"]["raw_source"]["held"])

    def test_a_record_frozen_before_policy_b_is_assessed_as_stored(self):
        stale = self.import_baseline(self.keep(*STALE))["snapshot"]["snapshot_id"]
        hypothesis = json.loads(json.dumps(self.preview(self.inputs(stale))["binding"]["effective_hypothesis"]))
        self.assertTrue(self.preview(self.inputs(stale))["blockers"])  # Policy B refuses this baseline today.
        record = Hypothesis.model_validate({**hypothesis, "frozen_at": T0.isoformat()})
        writer = open_store(str(self.store))
        hypothesis_id = stored_before_policy_b(writer, record, T0, stale)
        writer.close()
        package_id = self.outcome_package()
        self.at(AFTER)
        snapshot = self.import_outcome(hypothesis_id, package_id)["snapshot"]["snapshot_id"]
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(shown["assessable"], shown["blockers"])
        self.assertEqual(shown["legs"][0]["event_anchor"], "2026-09-11")  # Its own older anchor, never filled in.
        self.assertEqual(self.assess(shown).status_code, 201)


class DraftLinkTests(AssessmentHarness):
    def setUp(self):
        super().setUp()
        self.clock.moment = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1)

    def test_a_frozen_draft_is_linked_from_its_freeze_record_and_no_draft_record_changes(self):
        baseline = self.baseline()
        draft_id = self.paid("Paid draft that will be frozen")
        self.review(draft_id)
        unfrozen = self.client.get("/api/lifecycle/draft-links").json()
        self.assertEqual(unfrozen["links"], [])
        inputs = self.inputs(baseline, draft_id=draft_id)
        shown = self.preview(inputs)
        frozen = self.approve(inputs, shown).json()
        later_review = self.review(draft_id, notes="Checked again after the freeze.")
        watched = {name: tree(folder) for name, folder in (("drafts", self.drafts), ("reviews", self.reviews),
                                                           ("intake", self.intake), ("attempts", self.attempts))}
        links = self.client.get("/api/lifecycle/draft-links").json()
        self.assertEqual(links["problems"], [])
        [link] = links["links"]
        self.assertEqual((link["draft_id"], link["hypothesis_id"], link["action_id"]),
                         (draft_id, frozen["hypothesis_id"], shown["preview_sha256"]))
        self.assertEqual(link["review_at_freeze"]["sequence"], 1)
        self.assertEqual(later_review["sequence"], 2)  # The current review differs from the one used at freeze.
        self.assertEqual(links["problems"], [])
        self.assertEqual({name: tree(folder) for name, folder in (("drafts", self.drafts), ("reviews", self.reviews),
                                                                  ("intake", self.intake), ("attempts", self.attempts))},
                         watched)
        view = self.client.get(f"/api/drafts/{draft_id}").json()
        self.assertEqual(view["review_status"], "Not frozen · Requires human review")  # The draft record is unchanged.

    def test_a_damaged_freeze_record_links_nothing_and_is_reported(self):
        baseline = self.baseline()
        draft_id = self.paid("Paid draft whose freeze record is damaged")
        self.review(draft_id)
        inputs = self.inputs(baseline, draft_id=draft_id)
        shown = self.preview(inputs)
        self.assertEqual(self.approve(inputs, shown).status_code, 201)
        writer = sqlite3.connect(self.store)
        writer.execute("DROP TRIGGER freeze_actions_no_update")
        record = json.loads(writer.execute("SELECT payload FROM freeze_actions").fetchone()[0])
        record["binding"]["origin"]["draft_id"] = "f" * 64  # Pointing it at another draft breaks its identity.
        writer.execute("UPDATE freeze_actions SET payload=?", (json.dumps(record),))
        writer.commit()
        writer.close()
        links = self.client.get("/api/lifecycle/draft-links").json()
        self.assertEqual(links["links"], [])
        self.assertIn("does not verify", links["problems"][0]["problem"])


if __name__ == "__main__":
    unittest.main()

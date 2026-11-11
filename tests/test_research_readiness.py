"""Research readiness: what can be frozen prospectively now, what is missing and the next explicit action.

SYNTHETIC data only: temporary stores and folders, SYNTHETIC release packages (market_fakes) and SYNTHETIC hypotheses.
Nothing reaches a network, no real store or package is opened, and nothing real is frozen. Each readiness claim is
checked against the path it describes: a baseline reported ready is accepted by the freeze, one reported stale or short
is refused by the freeze for the same reason, and a registry concept reported as not operational yields only
unavailable legs.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from market_fakes import keep_package, release_data, release_zip
from second_order import market_retrieval, research_readiness
from second_order.api import create_app
from second_order.demo import load_market
from second_order.drafts import freeze_draft
from second_order.evaluation import evaluate
from second_order.freeze_origins import Folders, LifecycleRefused, manual_draft
from second_order.lifecycle import scoring_window
from second_order.package_snapshots import import_package
from second_order.registry import binding, registry_ids
from second_order.data import NEW_YORK
from second_order.h15_release import earliest_release
from second_order.research_readiness import (CONCEPT_ACTION, DAILY_GATE, NO_PROVIDER_GATE, UPGRADE_ACTION,
                                             inclusion_status, parse_published, report)
from second_order.schema import Hypothesis
from second_order.store import SCHEMA_1_SQL, SCHEMA_2_SQL, append_only_triggers, freeze, open_store
from test_daily import cmt_hypothesis, daily_series, ny
from test_lifecycle_freeze import manual
from test_package_snapshots import NoNetwork, h15_hypothesis, snapshot

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8137"
LIFECYCLE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Lifecycle": "1"}
UTC = timezone.utc
PUBLISHED_AT = "2026-09-15T14:00:00-04:00"  # SYNTHETIC event, a Tuesday: the last expected session before it is Sept 14.
PUBLISHED, REQUIRED = date(2026, 9, 15), date(2026, 9, 14)
FIRST = date(2025, 1, 2)
FRESH = (date(2026, 9, 14), datetime(2026, 9, 15, 12, tzinfo=UTC))  # Data through, package requested at.
STALE = (date(2026, 9, 11), datetime(2026, 9, 14, 12, tzinfo=UTC))
NOW = datetime(2026, 9, 15, 19, tzinfo=UTC)  # 15:00 in New York, an hour after the synthetic publication.
AFTER_RELEASE = datetime(2026, 9, 15, 21, tzinfo=UTC)  # 17:00 in New York, after the Board's 4:15 p.m. release.
H15 = ("yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15")
FRED_IDS = ("yield:ust2y_cmt", "yield:ust10y_cmt")
SECRET = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CONTACT", re.IGNORECASE)
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.


class Clock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


class Watched(dict):
    """A stand-in for os.environ that records every name read."""

    def __init__(self, base):
        super().__init__(base)
        self.read: list[str] = []

    def __getitem__(self, key):
        self.read.append(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.append(key)
        return super().get(key, default)

    def __contains__(self, key):
        self.read.append(key)
        return super().__contains__(key)


class Readiness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.market, self.store = self.root / "market", self.root / "store" / "research.db"

    def folders(self) -> Folders:
        return Folders(store=self.store, market=self.market)

    def keep(self, which=FRESH, validate: bool = True) -> str:
        through, requested = which
        package_id = keep_package(self.market, release_zip(release_data(FIRST, through)), requested)
        if validate:
            market_retrieval.validate_packages(self.market, lambda: requested + timedelta(minutes=1))
        return package_id

    def baseline(self, which=FRESH, start: date = FIRST) -> str:
        package_id = self.keep(which)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        connection = open_store(str(self.store))
        try:
            return import_package(connection, package_id, start, self.market,
                                  lambda: which[1] + timedelta(minutes=30))["snapshot_id"]
        finally:
            connection.close()

    def check(self, published: date | None = PUBLISHED, moment: datetime = NOW) -> dict:
        return report(self.folders(), Clock(moment), published)

    @staticmethod
    def row(result: dict, observable_id: str) -> dict:
        return next(row for row in result["observables"] if row["observable_id"] == observable_id)

    @staticmethod
    def provider(result: dict, provider: str) -> dict:
        return next(item for item in result["providers"] if item["provider"] == provider)

    def freeze_h15(self, snapshot_id: str, usage: str = "showcase") -> str:
        connection = open_store(str(self.store))
        try:
            return freeze(connection, h15_hypothesis(ny(2026, 9, 15, 14), NOW, usage=usage), NOW, snapshot_id)
        finally:
            connection.close()


class ConceptTests(Readiness):
    def test_registry_concepts_are_never_presented_as_operational(self):
        result = self.check()
        concepts = [row for row in result["observables"] if row["kind"] == "concept_only"]
        expected = [key for key in registry_ids() if "<TICKER>" in key or binding(key) is None]
        self.assertEqual([row["observable_id"] for row in concepts], expected)
        self.assertTrue({"index:dxy", "fx:usdils", "futures:wti", "futures:brent", "us_equity:<TICKER>",
                         "us_etf:<TICKER>"} <= set(expected))
        for row in concepts:
            self.assertEqual((row["status"], row["provider"], row["outcome"], row["freeze"]["ready"]),
                             ("concept_only", None, None, False))
            self.assertTrue(row["plain"].startswith("Registry concept only: no provider is connected."))
            self.assertEqual(row["next_action"], CONCEPT_ACTION)
            self.assertEqual(row["research"]["reasons"], [NO_PROVIDER_GATE])
        self.assertEqual([row["retained"] for row in concepts], [{}] * len(concepts))  # No fixture coverage shown.
        self.assertTrue(all("No data for it are held anywhere in the project." in row["plain"] for row in concepts))
        self.assertIn("observed regular-session close times", self.row(result, "us_equity:<TICKER>")["plain"])

    def test_the_demo_fixture_is_reported_as_demonstration_series_that_cover_no_registry_concept(self):
        result = self.check()
        demo = result["demonstration"]
        self.assertEqual((demo["fixture"], demo["version"], demo["registry_concepts_covered"]),
                         ("demo-market.json", "demo-market-0.1", []))
        self.assertEqual(result["provenance"]["fixture"], "demo-market.json")
        self.assertEqual([(item["observable_id"], item["provider"], item["first_date"], item["last_date"])
                          for item in demo["series"]],
                         [("demo:rate", "fictional-demo", "2022-01-03", "2024-12-31"),
                          ("demo:fx-index", "fictional-demo", "2022-01-03", "2024-12-31")])
        self.assertIn("FICTIONAL demonstration series", demo["plain"])
        self.assertIn("They cover no registry concept", demo["plain"])
        listed = {row["observable_id"] for row in result["observables"]}
        self.assertFalse({item["observable_id"] for item in demo["series"]} & listed)
        # Every row that is not measurable says why, so none is listed as measurable for research.
        self.assertTrue(all(row["research"]["reasons"] for row in result["observables"]))
        self.assertEqual(result["research"]["measurable_observables"], [])

    def test_a_prospective_freeze_on_concepts_could_be_stored_but_every_leg_would_be_unavailable(self):
        payload = cmt_hypothesis(ny(2026, 9, 15, 14), NOW).model_dump(mode="json")
        payload["legs"][0]["observable_id"], payload["legs"][1]["observable_id"] = "yield:us10y", "index:dxy"
        hypothesis = Hypothesis.model_validate(payload)
        connection = open_store()
        try:
            self.assertTrue(freeze(connection, hypothesis, NOW))  # The general freeze stores it, unbound.
        finally:
            connection.close()
        result = evaluate(hypothesis, load_market(), NOW + timedelta(days=60))
        self.assertEqual({leg["verdict"] for leg in result["legs"]}, {"unavailable"})


class FreezeReadinessTests(Readiness):
    def test_a_fresh_baseline_with_history_is_ready_and_the_freeze_accepts_it(self):
        snapshot_id = self.baseline()
        result = self.check()
        board = self.provider(result, "board-h15")
        self.assertEqual((board["status"], board["baselines"]), ("freeze_ready", [snapshot_id]))
        self.assertEqual(board["scorable_horizons"], {key: [1, 5, 20] for key in H15})
        for observable_id in H15:
            row = self.row(result, observable_id)
            self.assertEqual((row["status"], row["freeze"]["blockers"]), ("freeze_ready", []))
            entry = row["retained"]["snapshots"][0]
            self.assertEqual((entry["classified_through"], entry["required_session_status"]),
                             ("2026-09-14", "session_value"))
        fred = self.provider(result, "fred")
        self.assertEqual(fred["status"], "needs_baseline")
        self.assertEqual(self.row(result, FRED_IDS[0])["freeze"]["blockers"],
                         ["No snapshot of this provider is in the store."])
        self.assertTrue(result["answer"]["freeze_now"].startswith(
            "You can freeze a prospective showcase hypothesis for 2026-09-15 on the 2-year Treasury yield (Board H.15) "
            f"and 10-year Treasury yield (Board H.15), with baseline {snapshot_id[:12]}."))
        self.assertTrue(result["answer"]["next_action"].startswith("Nothing is missing for a prospective showcase"))
        self.assertTrue(self.freeze_h15(snapshot_id))  # The freeze's own checks agree.

    def test_a_stale_baseline_needs_a_newer_one_and_the_freeze_refuses_it_for_the_same_reason(self):
        snapshot_id = self.baseline(STALE)
        result = self.check()
        board = self.provider(result, "board-h15")
        self.assertEqual((board["status"], board["baselines"]), ("needs_baseline", []))
        blocker = self.row(result, H15[0])["freeze"]["blockers"][0]
        self.assertIn("through 2026-09-11; a baseline must classify 2026-09-14", blocker)
        # At 3 p.m. in New York the Board's release that can first state September 14 is not out yet (4:15 p.m.).
        self.assertTrue(board["action"].startswith("Wait until 2026-09-15 16:15 New York time before downloading"))
        self.assertTrue(self.provider(self.check(moment=AFTER_RELEASE), "board-h15")["action"].startswith(
            "Approve one download of the Board's H.15 release package"))
        self.assertIn("Held now: ", result["answer"]["freeze_now"])
        with self.assertRaisesRegex(ValueError, "Freshness policy B: .* through 2026-09-11, .* is 2026-09-14"):
            self.freeze_h15(snapshot_id)

    def test_too_little_history_is_reported_and_the_freeze_refuses_it(self):
        snapshot_id = self.baseline(start=date(2026, 6, 1))
        result = self.check()
        row = self.row(result, H15[1])
        self.assertEqual(row["status"], "needs_baseline")
        self.assertIn("gives too few usable reference windows", row["freeze"]["blockers"][0])
        self.assertIn("the rules require 120", row["freeze"]["blockers"][0])
        self.assertIn("again with an earlier start", row["next_action"])
        with self.assertRaisesRegex(ValueError, "Baseline history is insufficient"):
            self.freeze_h15(snapshot_id)

    def test_a_baseline_received_after_this_moment_is_not_ready_and_the_freeze_refuses_it(self):
        snapshot_id = self.baseline()  # Received at 12:00:01 UTC on September 15.
        early = datetime(2026, 9, 15, 11, tzinfo=UTC)
        result = self.check(moment=early)
        self.assertEqual(self.provider(result, "board-h15")["status"], "needs_baseline")
        self.assertEqual(self.row(result, H15[0])["freeze"]["blockers"],
                         [f"Snapshot {snapshot_id[:12]} was received after this moment."])
        payload = h15_hypothesis(ny(2026, 9, 15, 6), early).model_dump(mode="json")
        connection = open_store(str(self.store))
        self.addCleanup(connection.close)
        with self.assertRaisesRegex(ValueError, "must have been retrieved before the freeze"):
            freeze(connection, Hypothesis.model_validate(payload), early, snapshot_id)

    def test_the_next_action_follows_what_is_held(self):
        nothing = self.check(moment=AFTER_RELEASE)
        self.assertTrue(nothing["answer"]["next_action"].startswith("Approve one download"))
        self.assertEqual(nothing["next_actions"][-1]["action"],
                         "No store exists yet: importing a baseline (Hypotheses page) creates one at schema 4.")
        self.assertTrue(self.provider(nothing, "fred")["action"].startswith("Run `python -m second_order market import"))
        unvalidated = self.keep(validate=False)
        self.assertTrue(self.check()["answer"]["next_action"].startswith("Validate the kept package locally"))
        market_retrieval.validate_packages(self.market, lambda: FRESH[1] + timedelta(minutes=1))
        importable = self.check()
        self.assertTrue(importable["answer"]["next_action"].startswith(f"Import kept package {unvalidated} into"))
        self.assertIn(f"kept H.15 package {unvalidated} through 2026-09-14, not imported",
                      importable["answer"]["freeze_now"])

    def test_a_schema_2_store_names_the_explicit_upgrade(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        connection.executescript("BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + append_only_triggers(["hypotheses"]) +
                                 "INSERT INTO store_meta VALUES ('schema_version', '2'); COMMIT;")
        connection.close()
        result = self.check()
        self.assertEqual(result["store"]["schema"], 2)
        self.assertEqual(result["next_actions"][-1]["action"], UPGRADE_ACTION)

    def test_a_future_publication_date_waits_for_its_last_session(self):
        self.baseline()
        result = self.check(date(2026, 9, 17))
        self.assertEqual((result["required_session"], result["required_session_ended"]), ("2026-09-16", False))
        for observable_id in H15 + FRED_IDS:
            self.assertEqual(self.row(result, observable_id)["status"], "waiting_for_session")
        self.assertTrue(result["answer"]["next_action"].startswith(
            "Wait until 2026-09-16 has ended and the Board's H.15 release states it, no earlier than 2026-09-17 16:15 "
            "New York time (the Board posts"))
        self.assertTrue(self.provider(result, "fred")["action"].startswith("Wait until 2026-09-16 has ended and its "
                                                                           "value is published"))
        self.assertEqual(self.row(result, FRED_IDS[0])["outcome"]["freeze_date_new_york"], "2026-09-17")

    def test_a_download_is_proposed_only_once_the_board_can_have_posted_the_required_session(self):
        # The Board posts H.15 on business days at 4:15 p.m. New York time with the previous business day's values.
        self.assertEqual(earliest_release(date(2026, 9, 14)), datetime(2026, 9, 15, 16, 15, tzinfo=NEW_YORK))
        self.assertEqual(earliest_release(date(2026, 11, 6)), datetime(2026, 11, 9, 16, 15, tzinfo=NEW_YORK))  # Friday.
        self.assertEqual(earliest_release(date(2026, 12, 8)), datetime(2026, 12, 9, 16, 15, tzinfo=NEW_YORK))
        self.keep(STALE)  # Accepted, through September 11: it cannot serve, and an import would not help.
        before = self.provider(self.check(moment=datetime(2026, 9, 15, 20, 14, tzinfo=UTC)), "board-h15")
        self.assertEqual(before["status"], "needs_baseline")
        self.assertIn("a download before then returns data through an earlier session", before["action"])
        at = self.provider(self.check(moment=datetime(2026, 9, 15, 20, 15, tzinfo=UTC)), "board-h15")
        self.assertTrue(at["action"].startswith("Approve one download"))
        # Over a weekend: a Monday publication needs Friday's session, posted no earlier than Monday 4:15 p.m.
        saturday = self.check(date(2026, 9, 21), moment=datetime(2026, 9, 19, 15, tzinfo=UTC))
        self.assertEqual(saturday["required_session"], "2026-09-18")
        self.assertTrue(self.provider(saturday, "board-h15")["action"].startswith(
            "Wait until 2026-09-21 16:15 New York time before downloading"))
        self.assertTrue(self.provider(saturday, "fred")["action"].startswith("Run `python -m second_order market "
                                                                             "import"))


class OutcomeAndResearchTests(Readiness):
    def test_outcome_readiness_follows_the_lifecycle_rule_and_never_blocks_a_freeze(self):
        self.baseline()
        result = self.check()
        outcome = self.row(result, H15[0])["outcome"]
        self.assertEqual((outcome["state"], outcome["blocks_freeze"]), ("not_due", False))
        window = scoring_window(h15_hypothesis(ny(2026, 9, 15, 14), NOW), PUBLISHED)
        self.assertEqual(outcome["expected_score_anchor"], window["expected_score_anchor"])
        self.assertEqual(outcome["targets"]["5"]["expected_target"], window["legs"]["primary"]["expected_target"])
        self.assertEqual(outcome["targets"]["1"]["expected_target"], window["legs"]["secondary"]["expected_target"])
        self.assertTrue(self.provider(result, "board-h15")["status"] == "freeze_ready")  # Outcome data not needed.
        self.assertIn("never blocks a freeze", result["answer"]["outcomes"])

    def test_research_use_is_a_separate_gate_from_freeze_readiness(self):
        self.baseline()
        result = self.check()
        research = result["research"]
        self.assertEqual(research["measurable_observables"], [])
        self.assertEqual(research["inclusion_status"], inclusion_status(ROOT / "INCLUSION.md"))
        self.assertEqual(research["inclusion_status"], "research intake has not started.")
        self.assertTrue(result["answer"]["research"].startswith("Not possible now. INCLUSION.md: research intake has "
                                                                "not started."))
        self.assertIn("The 4 connected observables are dated, not timed", result["answer"]["research"])
        self.assertIn("The 8 registry concepts have no provider", result["answer"]["research"])
        for observable_id in H15 + FRED_IDS:
            row = self.row(result, observable_id)
            self.assertEqual((row["registry"]["anchor_policy"], row["research"]["reasons"]),
                             ("daily_ny_date", [DAILY_GATE]))
        self.assertEqual(self.provider(result, "board-h15")["status"], "freeze_ready")  # Freezable, yet not research.
        # What the report says about research use is what the code does:
        hypothesis = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5), usage="research")
        leg = evaluate(hypothesis, {"yield:ust10y_cmt": daily_series()}, ny(2025, 7, 1, 12))["legs"][0]
        self.assertEqual((leg["verdict"], leg["reason"]), ("unavailable", "Research requires verified observation "
                                                                          "timestamps"))
        draft = {key: value for key, value in hypothesis.model_dump(mode="json").items()
                 if key not in ("frozen_at", "replay_as_of", "supersedes")}
        connection = open_store()
        self.addCleanup(connection.close)
        with self.assertRaisesRegex(ValueError, "accepts only prospective showcase drafts"):
            freeze_draft(connection, draft, None)
        built, _ = manual_draft(manual(), lambda: NOW)
        self.assertEqual((built["usage"], built["evidence_class"]), ("showcase", "prospective"))

    def test_the_inclusion_status_is_read_from_its_status_line_only(self):
        path = self.root / "INCLUSION.md"
        path.write_text("# Rule\n\nIntake status: elsewhere\nStatus: research intake has not started.\n", "utf-8")
        self.assertEqual(inclusion_status(path), "research intake has not started.")
        path.write_text("# Rule\n\nNo status here.\n", "utf-8")
        self.assertIsNone(inclusion_status(path))
        self.assertIsNone(inclusion_status(self.root / "missing.md"))


class BoundaryTests(Readiness):
    def test_the_check_reads_only_fetches_nothing_and_reads_no_key(self):
        self.baseline()
        self.keep(STALE)
        before = snapshot(self.root)
        watched = Watched(os.environ)
        with NoNetwork() as network, patch("os.environ", watched):
            result = self.check()
        self.assertEqual(network.attempts, [])
        self.assertEqual(snapshot(self.root), before)  # Same bytes, size and modification time.
        self.assertEqual([name for name in watched.read if SECRET.search(name)], [])
        self.assertEqual((result["provider_called"], result["written"]), (False, False))
        missing = Folders(store=self.root / "absent" / "research.db", market=self.root / "absent-market")
        self.assertFalse(report(missing, Clock(NOW), PUBLISHED)["store"]["exists"])
        self.assertFalse((self.root / "absent").exists())  # A read never creates a store or a folder.

    def test_a_published_date_must_be_a_date(self):
        self.assertEqual(parse_published("2026-09-15"), PUBLISHED)
        self.assertIsNone(parse_published(None))
        for bad in ("15-09-2026", "2026-9-15", "2026-02-30", "2026-09-15T00:00", ""):
            with self.assertRaises(LifecycleRefused) as refused:
                parse_published(bad)
            self.assertEqual(refused.exception.status, 422)

    def test_the_route_and_the_command(self):
        self.baseline()
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", market=self.market,
                                       store=self.store, lifecycle_clock=Clock(NOW)), base_url=BASE)
        self.addCleanup(client.close)
        before = snapshot(self.root)
        reply = client.get("/api/lifecycle/readiness", params={"published": "2026-09-15"})
        self.assertEqual(reply.status_code, 200, reply.text)
        body = reply.json()
        self.assertEqual((body["readiness_version"], body["lifecycle_version"]),
                         (research_readiness.READINESS_VERSION, "lifecycle-freeze-0.1"))
        self.assertEqual(self.provider(body, "board-h15")["status"], "freeze_ready")
        self.assertEqual(client.get("/api/lifecycle/readiness").json()["published_date"], "2026-09-15")  # Today.
        self.assertEqual(client.get("/api/lifecycle/readiness", params={"published": "15/09/2026"}).status_code, 422)
        self.assertEqual(snapshot(self.root), before)
        bare = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", market=self.market),
                          base_url=BASE)
        self.addCleanup(bare.close)
        self.assertEqual(bare.get("/api/lifecycle/readiness").status_code, 503)
        absent = self.root / "nowhere" / "research.db"
        run = subprocess.run([sys.executable, "-m", "second_order", "research-readiness", "--db", str(absent),
                              "--packages-dir", str(self.market), "--published", "2026-09-15"],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        printed = json.loads(run.stdout)
        self.assertEqual((printed["required_session"], printed["store"]["exists"]), ("2026-09-14", False))
        self.assertFalse(absent.parent.exists())


class FrontendFixtureTests(Readiness):
    """The page's reader is tested against these exact served replies (frontend/tests/readiness.test.ts)."""

    def served(self) -> dict:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", market=self.market,
                                       store=self.store, lifecycle_clock=Clock(NOW)), base_url=BASE)
        self.addCleanup(client.close)
        reply = client.get("/api/lifecycle/readiness", params={"published": PUBLISHED.isoformat()})
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def compare(self, name: str, served: dict) -> None:
        path = FIXTURES / name
        if os.environ.get(WRITE_FIXTURES) == "1":
            path.write_bytes((json.dumps(served, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        self.assertEqual(served, json.loads(path.read_text(encoding="utf-8")),
                         f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover -s tests "
                         "-p test_research_readiness.py")

    def test_a_ready_reply_matches_the_committed_fixture(self):
        self.baseline()
        self.compare("research-readiness-ready.json", self.served())

    def test_a_not_ready_reply_matches_the_committed_fixture(self):
        self.keep(STALE)
        self.compare("research-readiness-not-ready.json", self.served())


class SyntheticDryRunTests(Readiness):
    """A SYNTHETIC pilot case end to end through the interface's own routes: readiness, freeze, outcome readiness."""

    def test_dry_run_of_one_synthetic_case(self):
        clock = Clock(NOW)
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", market=self.market,
                                       store=self.store, lifecycle_clock=clock), base_url=BASE)
        self.addCleanup(client.close)
        package_id = self.keep()
        imported = client.post("/api/lifecycle/baselines", headers=LIFECYCLE,
                               content=json.dumps({"package_id": package_id, "start": FIRST.isoformat()}))
        self.assertEqual(imported.status_code, 201, imported.text)
        baseline = imported.json()["snapshot"]["snapshot_id"]
        ready = client.get("/api/lifecycle/readiness").json()
        self.assertEqual(self.provider(ready, "board-h15")["baselines"], [baseline])
        form = manual(headline="SYNTHETIC dry run: a policy statement for the pilot protocol",
                      story_id="synthetic-dry-run-1", authoring="SYNTHETIC: written by the test author")
        inputs = {"origin": "manual", "manual": form, "draft_id": None, "baseline_snapshot_id": baseline}
        preview = client.post("/api/lifecycle/preview", headers=LIFECYCLE, content=json.dumps({"inputs": inputs}))
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual((preview.json()["freezable"], preview.json()["blockers"]), (True, []))
        frozen = client.post("/api/lifecycle/freezes", headers=LIFECYCLE, content=json.dumps({
            "inputs": inputs, "preview_sha256": preview.json()["preview_sha256"], "approve_freeze": True,
            "previewed_binding": preview.json()["binding"]}))
        self.assertEqual(frozen.status_code, 201, frozen.text)
        identity = frozen.json()["hypothesis_id"]
        # Frozen with no outcome data held: outcome readiness is a later, separate question.
        waiting = client.get(f"/api/lifecycle/hypotheses/{identity}/readiness").json()
        self.assertEqual(waiting["state"], "horizon_not_elapsed")
        after = client.get("/api/lifecycle/readiness").json()
        self.assertEqual(self.row(after, H15[0])["outcome"]["targets"]["5"]["expected_target"],
                         waiting["expected"]["legs"]["two-year"]["expected_target"])  # The 2-year leg: horizon 5.
        # Once the targets have ended, a newer SYNTHETIC package is kept and imported as the outcome.
        clock.moment = datetime(2026, 10, 1, 13, tzinfo=UTC)
        outcome = self.keep((date(2026, 9, 30), datetime(2026, 10, 1, 12, tzinfo=UTC)))
        imported = client.post("/api/lifecycle/outcome-imports", headers=LIFECYCLE,
                               content=json.dumps({"hypothesis_id": identity, "package_id": outcome}))
        self.assertIn(imported.status_code, (200, 201), imported.text)
        self.assertEqual(client.get(f"/api/lifecycle/hypotheses/{identity}/readiness").json()["state"], "ready")


if __name__ == "__main__":
    unittest.main()

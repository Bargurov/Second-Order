"""The interface's freeze (A2), driven through the app's own routes on temporary folders. SYNTHETIC data only.

Kept packages are SYNTHETIC release packages (market_fakes); the model path runs the Tracker's paid route against a
fake provider (an httpx MockTransport with a dummy key) that answers by headline with the observables the request
offers. Nothing reaches a network, no real store is opened and nothing real is frozen.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from fred_fixtures import FakeFred, datasets
from market_fakes import keep_package, release_data, release_zip
from model_fixtures import FAKE_KEY, THINKING, encoded, message, output_for, tool_call
from second_order import draft_catalog, lifecycle, market_retrieval
from second_order.api import create_app
from second_order.event_intake import capture_text
from second_order.analysis_flow import MODEL
from second_order.paid_drafts import PaidSender
from second_order.store import SCHEMA_1_SQL, SCHEMA_2_SQL, SCHEMA_2_TABLES, append_only_triggers, open_store
from store_records import stored_before_policy_b
from test_daily import cmt_hypothesis, ny
from test_fred import run_import

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8137"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
LIFECYCLE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Lifecycle": "1"}
PUBLISHED = "2026-09-15T14:00:00-04:00"  # Tuesday: the last expected session before it is Monday, September 14.
FIRST = date(2025, 1, 2)
FRESH = (date(2026, 9, 14), datetime(2026, 9, 15, 12, tzinfo=timezone.utc))  # Data through, requested at.
STALE = (date(2026, 9, 11), datetime(2026, 9, 14, 12, tzinfo=timezone.utc))
ANSWERS = {  # Headline prefix -> what the fake provider answers.
    "Paid refusal": (200, encoded(message(model=MODEL, stop_reason="end_turn", content=[
        dict(THINKING), {"type": "text", "text": "No hypothesis: the source states too little to support one."}]))),
    "Paid invalid": (200, encoded(message(model=MODEL, content=[{"type": "text", "text": "Here is my draft."},
                                                               tool_call()]))),
    "Paid provider error": (529, encoded({"type": "error", "error": {"type": "overloaded_error", "message": "Busy"}})),
}


def tree(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(root.rglob("*")) if path.is_file()}


def form(headline: str) -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": PUBLISHED,
                       "source_text": f"Synthetic published text for {headline}.\nSecond line."}).encode("utf-8")


def manual(**changes) -> dict:
    legs = [{"observable_id": "yield:ust2y_cmt_h15", "primary": True, "expected": "down", "horizon": 5,
             "link": "direct", "channel": "Expected policy path",
             "rationale": "The 2-year yield is most tied to the expected policy path.",
             "falsifier": "The 2-year yield rises unusually over the scored window.", "headline_reports_move": False},
            {"observable_id": "yield:ust10y_cmt_h15", "primary": False, "expected": "down", "horizon": 5,
             "link": "proxy", "channel": "Expected policy path",
             "rationale": "The 10-year yield also carries term premium and supply.",
             "falsifier": "The 10-year yield rises unusually over the scored window.", "headline_reports_move": False}]
    return {"headline": "Synthetic payrolls release for a manual freeze", "source_url": "https://example.com/release",
            "published_at": PUBLISHED, "story_id": "synthetic-manual-freeze",
            "summary": "A synthetic weaker payrolls print may lower Treasury yields; energy prices compete.",
            "authoring": "Written by the test author without AI assistance", "legs": legs, **changes}


class Clock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


class Harness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.market, self.store = self.root / "market", self.root / "store" / "research.db"
        self.drafts, self.reviews = self.root / "prepared-drafts", self.root / "reviews"
        self.intake, self.attempts = self.root / "intake", self.root / "attempts"
        self.published = draft_catalog.tracker_dir(self.drafts)
        self.calls: list[httpx.Request] = []
        self.clock = Clock(datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1))
        self.client = self.app()

    def app(self) -> TestClient:
        sender = PaidSender(api_key=lambda: FAKE_KEY, client_factory=lambda observe: httpx.Client(
            transport=httpx.MockTransport(self.answer), follow_redirects=False, trust_env=False,
            event_hooks={"response": [observe]}))
        client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                       self.attempts, paid=sender, market=self.market, store=self.store,
                                       lifecycle_clock=self.clock), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def folders(self) -> lifecycle.Folders:
        return lifecycle.Folders(store=self.store, market=self.market, intake=self.intake, attempts=self.attempts,
                                 drafts=self.drafts, published=self.published, reviews=self.reviews)

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        content = json.loads(request.content)["messages"][0]["content"]
        headline = next(line[len("Headline: "):] for line in content.splitlines() if line.startswith("Headline: "))
        status, body = next((value for prefix, value in ANSWERS.items() if headline.startswith(prefix)),
                            (200, encoded(message(output_for(request.content), model=MODEL))))
        return httpx.Response(status, content=body, headers={"content-type": "application/json",
                                                             "request-id": f"req_fake{len(self.calls):04d}"})

    # -- packages and baselines
    def keep(self, through: date, requested: datetime, overrides: dict | None = None) -> str:
        package_id = keep_package(self.market, release_zip(release_data(FIRST, through, overrides)), requested)
        market_retrieval.validate_packages(self.market, lambda: requested + timedelta(minutes=1))
        return package_id

    def import_baseline(self, package_id: str, start: str = "2025-01-02", expect: int = 201) -> dict:
        response = self.client.post("/api/lifecycle/baselines", headers=LIFECYCLE,
                                    content=json.dumps({"package_id": package_id, "start": start}))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def baseline(self, which=FRESH, overrides=None) -> str:
        return self.import_baseline(self.keep(*which, overrides))["snapshot"]["snapshot_id"]

    # -- the Tracker's drafts
    def capture(self, headline: str) -> dict:
        response = self.client.post("/api/intake", content=form(headline), headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def paid(self, headline: str) -> str:
        preview = self.capture(headline)
        body = json.dumps({"request_sha256": preview["request_sha256"], "approve_paid_request": True,
                           "estimated_max_usd": preview["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"]})
        response = self.client.post(f"/api/intake/{preview['capture_id']}/paid-drafts", content=body, headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["draft_id"]

    def mock(self, headline: str, capture: dict | None = None) -> str:
        preview = capture or self.capture(headline)
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": "draft"})
        response = self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", content=body, headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["draft_id"]

    def review(self, draft_id: str, status: str | None = "human_reviewed", notes: str = "Checked.",
               corrections: dict | None = None) -> dict:
        loaded = self.client.get(f"/api/drafts/{draft_id}")
        history = self.client.get(f"/api/drafts/{draft_id}/reviews").json()["reviews"]
        provenance = loaded.json()["provenance"]
        body = {"parent_review_id": history[-1]["review_id"] if history else None, "status": status, "notes": notes,
                "corrections": corrections or {"summary": None, "legs": {}},
                "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                            "prompt_hash": provenance["prompt_hash"], "response_sha256": provenance["response_sha256"]}}
        saved = self.client.post(f"/api/drafts/{draft_id}/reviews", content=json.dumps(body), headers=REVIEW)
        self.assertEqual(saved.status_code, 201, saved.text)
        return saved.json()

    # -- the lifecycle
    def inputs(self, baseline: str, form_content: dict | None = None, draft_id: str | None = None) -> dict:
        if draft_id is not None:
            return {"origin": "model", "manual": None, "draft_id": draft_id, "baseline_snapshot_id": baseline}
        return {"origin": "manual", "manual": form_content or manual(), "draft_id": None,
                "baseline_snapshot_id": baseline}

    def preview(self, inputs: dict, expect: int = 200) -> dict:
        response = self.client.post("/api/lifecycle/preview", headers=LIFECYCLE, content=json.dumps({"inputs": inputs}))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def approve(self, inputs: dict, shown: dict) -> httpx.Response:
        return self.client.post("/api/lifecycle/freezes", headers=LIFECYCLE, content=json.dumps(
            {"inputs": inputs, "preview_sha256": shown["preview_sha256"], "approve_freeze": True,
             "previewed_binding": shown["binding"]}))

    def counts(self) -> dict:
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("hypotheses", "freeze_bindings", "freeze_actions", "evaluations", "market_snapshots")}
        finally:
            connection.close()


class BaselineImportTests(Harness):
    def test_an_explicit_import_creates_the_store_and_a_repeat_reuses_the_snapshot(self):
        package_id = self.keep(*FRESH)
        before = tree(self.root)
        listed = self.client.get("/api/lifecycle/baselines").json()  # Reads never import or create a store.
        self.assertEqual(tree(self.root), before)
        self.assertFalse(self.store.exists())
        self.assertEqual(([row["package_id"] for row in listed["packages"]], listed["snapshots"]), ([package_id], []))
        self.assertTrue(listed["packages"][0]["importable"])
        first = self.import_baseline(package_id)
        snapshot = first["snapshot"]
        self.assertEqual((first["created"], snapshot["provider"], snapshot["vintage_date"]), (True, "board-h15", None))
        self.assertEqual(snapshot["package"]["package_id"], package_id)
        self.assertEqual(snapshot["coverage"]["RIFLGFCY02_N.B"]["classified_through"], "2026-09-14")
        self.assertEqual(self.client.get("/api/lifecycle").json()["store"]["schema"], 4)
        stored = tree(self.root)
        again = self.import_baseline(package_id, expect=200)
        self.assertEqual((again["created"], again["snapshot"]["snapshot_id"]), (False, snapshot["snapshot_id"]))
        self.assertEqual(tree(self.root), stored)
        listed = self.client.get("/api/lifecycle/baselines").json()
        self.assertEqual(listed["packages"][0]["snapshots"], [snapshot["snapshot_id"]])

    def test_an_unvalidated_package_is_refused_and_writes_nothing(self):
        package_id = keep_package(self.market, release_zip(release_data(FIRST, FRESH[0])), FRESH[1])
        before = tree(self.root)
        response = self.client.post("/api/lifecycle/baselines", headers=LIFECYCLE,
                                    content=json.dumps({"package_id": package_id, "start": "2025-01-02"}))
        self.assertEqual(response.status_code, 409)
        self.assertIn("not validated", response.json()["detail"])
        self.assertEqual({key: value for key, value in tree(self.root).items() if not key.startswith("store/")},
                         before)

    def test_writes_need_the_local_page_and_reads_need_a_configured_store(self):
        package_id = self.keep(*FRESH)
        for headers in ({"Content-Type": "application/json", "X-Second-Order-Lifecycle": "1"},
                        {"Origin": "http://evil.example", "Content-Type": "application/json",
                         "X-Second-Order-Lifecycle": "1"},
                        {"Origin": BASE, "Content-Type": "application/json"}):
            response = self.client.post("/api/lifecycle/baselines", headers=headers,
                                        content=json.dumps({"package_id": package_id, "start": "2025-01-02"}))
            self.assertEqual(response.status_code, 403, headers)
        self.assertFalse(self.store.exists())
        bare = TestClient(create_app(self.root / "no-dossiers", None, self.drafts), base_url=BASE)
        self.addCleanup(bare.close)
        self.assertEqual(bare.get("/api/lifecycle").status_code, 503)  # No store chosen at startup: nothing read.


class ManualFreezeTests(Harness):
    def test_a_manual_hypothesis_is_previewed_frozen_once_and_reopened_after_a_restart(self):
        baseline = self.baseline()
        inputs = self.inputs(baseline)
        before = tree(self.root)
        shown = self.preview(inputs)
        self.assertEqual(tree(self.root), before)  # A preview writes nothing.
        self.assertTrue(shown["freezable"], shown["blockers"])
        self.assertEqual((shown["provider_called"], shown["written"]), (False, False))
        effective = shown["binding"]["effective_hypothesis"]
        self.assertEqual(effective["engine"]["provider"], "manual")
        self.assertIn("Written by the test author without AI assistance", effective["engine"]["model"])
        self.assertEqual(effective["engine"]["prompt_hash"], shown["binding"]["origin"]["manual_input_sha256"])
        self.assertNotIn("frozen_at", effective)
        self.assertEqual(shown["freshness"]["required_session"], "2026-09-14")
        self.assertEqual(shown["freshness"]["series"]["RIFLGFCY02_N.B"]["required_session_status"], "session_value")
        self.assertIn("excluded from research summaries and rates", shown["classification"])
        self.assertEqual(shown["binding"]["source_bindings"], {"yield:ust2y_cmt_h15": "board-h15:RIFLGFCY02_N.B",
                                                               "yield:ust10y_cmt_h15": "board-h15:RIFLGFCY10_N.B"})
        frozen = self.approve(inputs, shown)
        self.assertEqual(frozen.status_code, 201, frozen.text)
        result = frozen.json()
        self.assertEqual((result["created"], result["status"], result["evaluated"], result["prepared"]),
                         (True, "Frozen · Not evaluated", False, False))
        self.assertEqual(result["recorded_at"], self.clock().isoformat())  # The server's time, not the client's.
        self.assertEqual(self.counts(), {"hypotheses": 1, "freeze_bindings": 1, "freeze_actions": 1,
                                         "evaluations": 0, "market_snapshots": 1})
        self.assertFalse((self.root / "no-dossiers").exists())  # Nothing was prepared.
        restarted = self.app()  # A new server process reads the same store.
        view = restarted.get(f"/api/lifecycle/hypotheses/{result['hypothesis_id']}").json()
        self.assertEqual((view["status"], view["frozen_at"], view["action_id"]),
                         ("Frozen · Not evaluated", self.clock().isoformat().replace("+00:00", "Z"),
                          shown["preview_sha256"]))
        self.assertEqual(view["origin"]["manual_input"]["published_at"], PUBLISHED)  # As supplied, with its offset.
        self.assertEqual(view["effective_sha256"], shown["effective_sha256"])
        self.assertEqual((view["baseline"]["provider"], view["baseline"]["vintage_date"]), ("board-h15", None))
        self.assertEqual(view["hypothesis"]["usage"], "showcase")
        listed = restarted.get("/api/lifecycle").json()["hypotheses"]
        self.assertEqual([(row["hypothesis_id"], row["origin"], row["status"]) for row in listed],
                         [(result["hypothesis_id"], "manual", "Frozen · Not evaluated")])

    def test_the_form_is_strict_and_uses_only_the_registered_h15_observables(self):
        baseline = self.baseline()
        fred = manual()
        fred["legs"][0]["observable_id"] = "yield:ust2y_cmt"
        two_primaries = manual()
        two_primaries["legs"][1]["primary"] = True
        no_flag = manual()
        no_flag["legs"][0]["headline_reports_move"] = None
        cases = {"FRED observable": fred, "two primaries": two_primaries, "no default flag": no_flag,
                 "no offset": manual(published_at="2026-09-15T14:00:00"), "future": manual(published_at=
                 (self.clock() + timedelta(days=1)).astimezone(timezone(timedelta(hours=-4))).strftime(
                     "%Y-%m-%dT%H:%M:%S-04:00")),
                 "a freeze time": {**manual(), "frozen_at": "2026-09-15T20:00:00Z"}}
        for name, content in cases.items():
            with self.subTest(name):
                response = self.client.post("/api/lifecycle/preview", headers=LIFECYCLE,
                                            content=json.dumps({"inputs": self.inputs(baseline, content)}))
                self.assertEqual(response.status_code, 422, response.text)
        approval = {"inputs": self.inputs(baseline), "preview_sha256": "a" * 64, "approve_freeze": True,
                    "previewed_binding": None, "frozen_at": "2026-09-15T20:00:00Z"}
        response = self.client.post("/api/lifecycle/freezes", headers=LIFECYCLE, content=json.dumps(approval))
        self.assertEqual(response.status_code, 422)  # No client-supplied freeze time is accepted.
        self.assertEqual(self.counts()["hypotheses"], 0)

    def test_a_fred_baseline_is_refused_for_h15_legs(self):
        self.baseline()
        connection = open_store(str(self.store))
        fred = run_import(connection, FakeFred(datasets(date(2026, 9, 14)), date(2026, 9, 15)), date(2026, 9, 15),
                          FRESH[1])["snapshot_id"]
        connection.close()
        response = self.client.post("/api/lifecycle/preview", headers=LIFECYCLE,
                                    content=json.dumps({"inputs": self.inputs(fred)}))
        self.assertEqual(response.status_code, 422)
        self.assertIn("comes from fred", response.json()["detail"])

    def test_freshness_policy_b_refuses_a_stale_baseline_and_a_stated_missing_value_is_covered(self):
        stale = self.baseline(STALE)
        shown = self.preview(self.inputs(stale))
        self.assertFalse(shown["freezable"])
        self.assertIn("the last expected session before the publication date 2026-09-15 is 2026-09-14",
                      " ".join(shown["blockers"]))
        refused = self.approve(self.inputs(stale), shown)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.counts()["hypotheses"], 0)
        missing = self.import_baseline(self.keep(FRESH[0], FRESH[1] + timedelta(hours=1),
                                                 {date(2026, 9, 14): ("ND", "ND")}))["snapshot"]["snapshot_id"]
        shown = self.preview(self.inputs(missing))
        self.assertTrue(shown["freezable"], shown["blockers"])
        self.assertEqual({entry["required_session_status"] for entry in shown["freshness"]["series"].values()},
                         {"session_missing"})
        self.assertEqual(self.approve(self.inputs(missing), shown).status_code, 201)

    def test_a_changed_hypothesis_baseline_or_new_york_date_needs_a_new_preview(self):
        baseline, other = self.baseline(), self.baseline(overrides={date(2025, 3, 3): ("3.33", "4.44")})
        inputs = self.inputs(baseline)
        shown = self.preview(inputs)
        edited = self.inputs(baseline, manual(summary="An edited summary after the preview."))
        for name, changed, label in (("hypothesis", edited, "the hypothesis"),
                                     ("baseline", self.inputs(other), "the baseline")):
            with self.subTest(name):
                response = self.approve(changed, shown)
                self.assertEqual(response.status_code, 409)
                self.assertIn(label, response.json()["detail"])
                self.assertNotEqual(response.json()["preview"]["preview_sha256"], shown["preview_sha256"])
        # 23:59:59 in New York, then two seconds later: the freeze date, and with it the scoring anchor, moves.
        self.clock.moment = datetime(2026, 9, 16, 3, 59, 59, tzinfo=timezone.utc)
        before_midnight = self.preview(inputs)
        self.clock.moment += timedelta(seconds=2)
        response = self.approve(inputs, before_midnight)
        self.assertEqual(response.status_code, 409)
        self.assertIn("the New York freeze date", response.json()["detail"])
        after = response.json()["preview"]
        self.assertEqual((before_midnight["scoring"]["freeze_date_new_york"], after["scoring"]["freeze_date_new_york"]),
                         ("2026-09-15", "2026-09-16"))
        self.assertEqual(self.counts()["hypotheses"], 0)
        frozen = self.approve(inputs, after)
        self.assertEqual(frozen.status_code, 201, frozen.text)

    def test_a_repeated_approval_returns_the_original_freeze_and_a_lost_reply_is_read_back(self):
        inputs = self.inputs(self.baseline())
        shown = self.preview(inputs)
        unknown = self.client.get(f"/api/lifecycle/actions/{shown['preview_sha256']}").json()
        self.assertEqual(unknown["state"], "not_recorded")
        first = self.approve(inputs, shown).json()
        self.clock.moment += timedelta(seconds=30)
        second = self.approve(inputs, shown)  # A double click, or a resubmission by hand.
        self.assertEqual(second.status_code, 200)
        self.assertEqual((second.json()["created"], second.json()["hypothesis_id"], second.json()["recorded_at"]),
                         (False, first["hypothesis_id"], first["recorded_at"]))  # Never restamped.
        before = tree(self.root)
        recovered = self.client.get(f"/api/lifecycle/actions/{shown['preview_sha256']}").json()
        self.assertEqual(tree(self.root), before)
        self.assertEqual((recovered["state"], recovered["hypothesis_id"]), ("frozen", first["hypothesis_id"]))
        self.assertEqual(self.counts()["hypotheses"], 1)
        other = self.baseline(overrides={date(2025, 3, 3): ("3.33", "4.44")})
        changed = self.preview(self.inputs(other))  # The same request with another baseline is another approval.
        self.assertFalse(changed["freezable"])
        self.assertIn(f"already frozen as {first['hypothesis_id']}", " ".join(changed["blockers"]))
        self.assertEqual(self.approve(self.inputs(other), changed).status_code, 409)
        self.assertEqual(self.counts()["hypotheses"], 1)

    def test_concurrent_tabs_and_workers_freeze_once(self):
        inputs = self.inputs(self.baseline())
        shown = self.preview(inputs)
        body = json.dumps({"inputs": inputs, "preview_sha256": shown["preview_sha256"], "approve_freeze": True,
                           "previewed_binding": shown["binding"]}).encode("utf-8")
        start, results, errors = threading.Barrier(4), [], []

        def tab():
            start.wait()
            try:
                results.append(lifecycle.freeze(body, self.folders(), self.clock))
            except Exception as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)
        threads = [threading.Thread(target=tab) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result["created"] for result in results), [False, False, False, True])
        self.assertEqual(len({result["hypothesis_id"] for result in results}), 1)
        # Separate worker processes, after the threads: the same approval still freezes nothing new.
        worker = ("import json, sys; from datetime import datetime; from pathlib import Path; "
                  "from second_order import lifecycle; args = json.loads(sys.argv[1]); "
                  "folders = lifecycle.Folders(**{k: Path(v) for k, v in args['folders'].items()}); "
                  "clock = datetime.fromisoformat(args['clock']); "
                  "print(json.dumps(lifecycle.freeze(args['body'].encode(), folders, lambda: clock)))")
        argument = json.dumps({"body": body.decode(), "clock": self.clock().isoformat(), "folders": {
            "store": str(self.store), "market": str(self.market), "intake": str(self.intake),
            "attempts": str(self.attempts), "drafts": str(self.drafts), "published": str(self.published),
            "reviews": str(self.reviews)}})
        processes = [subprocess.Popen([sys.executable, "-c", worker, argument], cwd=ROOT, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(3)]
        outputs = [process.communicate(timeout=120) for process in processes]
        for process, (out, err) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(json.loads(out)["created"], False)
        self.assertEqual(self.counts()["hypotheses"], 1)
        self.assertEqual(self.counts()["freeze_actions"], 1)

    def test_concurrent_workers_with_a_fresh_approval_freeze_exactly_once(self):
        inputs = self.inputs(self.baseline())
        shown = self.preview(inputs)
        body = json.dumps({"inputs": inputs, "preview_sha256": shown["preview_sha256"], "approve_freeze": True,
                           "previewed_binding": shown["binding"]})
        worker = ("import json, sys; from datetime import datetime; from pathlib import Path; "
                  "from second_order import lifecycle; args = json.loads(sys.argv[1]); "
                  "folders = lifecycle.Folders(**{k: Path(v) for k, v in args['folders'].items()}); "
                  "clock = datetime.fromisoformat(args['clock']); "
                  "print(json.dumps(lifecycle.freeze(args['body'].encode(), folders, lambda: clock)))")
        argument = json.dumps({"body": body, "clock": self.clock().isoformat(), "folders": {
            "store": str(self.store), "market": str(self.market), "intake": str(self.intake),
            "attempts": str(self.attempts), "drafts": str(self.drafts), "published": str(self.published),
            "reviews": str(self.reviews)}})
        processes = [subprocess.Popen([sys.executable, "-c", worker, argument], cwd=ROOT, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(3)]
        outputs = [process.communicate(timeout=120) for process in processes]
        created = []
        for process, (out, err) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, err)
            created.append(json.loads(out)["created"])
        self.assertEqual(sorted(created), [False, False, True])
        self.assertEqual((self.counts()["hypotheses"], self.counts()["freeze_actions"]), (1, 1))


class ModelFreezeTests(Harness):
    def test_a_reviewed_h15_model_draft_freezes_with_its_derivation_and_no_provider_call(self):
        baseline = self.baseline()
        draft_id = self.paid("Paid draft for a reviewed freeze")
        calls = len(self.calls)
        capture = next(row for row in self.client.get("/api/intake").json()["captures"])
        self.assertEqual(capture["prompt_version"], "draft-prompt-6")
        saved_request = (self.intake / capture["capture_id"] / "request.json").read_bytes()
        offered = json.loads(saved_request)["tools"][0]["input_schema"]["properties"]["legs"]["items"]["properties"][
            "observable_id"]["enum"]
        self.assertEqual(offered, ["yield:ust10y_cmt_h15", "yield:ust2y_cmt_h15"])
        listed = self.client.get("/api/lifecycle/drafts").json()["drafts"]
        self.assertEqual([(row["draft_id"], row["eligible"]) for row in listed], [(draft_id, False)])
        self.assertIn("No human review is saved.", listed[0]["reasons"])
        review = self.review(draft_id, corrections={"summary": "A reviewer's corrected summary of the draft.",
                                                    "legs": {"primary": {"rationale": "Corrected rationale."}}})
        self.assertTrue(self.client.get("/api/lifecycle/drafts").json()["drafts"][0]["eligible"])
        inputs = self.inputs(baseline, draft_id=draft_id)
        shown = self.preview(inputs)
        self.assertTrue(shown["freezable"], shown["blockers"])
        effective, origin = shown["binding"]["effective_hypothesis"], shown["binding"]["origin"]
        view = self.client.get(f"/api/drafts/{draft_id}").json()
        self.assertEqual(effective["engine"], {"provider": "anthropic", "model": MODEL,
                                               "prompt_hash": view["provenance"]["prompt_hash"], "schema_version": "0.2"})
        self.assertEqual(effective["summary"], "A reviewer's corrected summary of the draft.")
        self.assertEqual(next(leg for leg in effective["legs"] if leg["id"] == "primary")["rationale"],
                         "Corrected rationale.")
        self.assertEqual(view["draft"]["summary"], output_for(saved_request)["summary"])  # The model's words stay.
        self.assertEqual((origin["review"]["review_id"], origin["draft_view_sha256"], origin["prompt_version"]),
                         (review["review_id"], review["binding"]["draft_view_sha256"], "draft-prompt-6"))
        frozen = self.approve(inputs, shown)
        self.assertEqual(frozen.status_code, 201, frozen.text)
        self.assertEqual(len(self.calls), calls)  # Importing, previewing and freezing called no provider.
        self.assertEqual((self.intake / capture["capture_id"] / "request.json").read_bytes(), saved_request)
        reopened = self.client.get(f"/api/lifecycle/hypotheses/{frozen.json()['hypothesis_id']}").json()
        self.assertEqual((reopened["origin"]["kind"], reopened["origin"]["draft_id"]), ("model", draft_id))

    def test_a_changed_or_unapproved_review_blocks_the_freeze(self):
        baseline = self.baseline()
        draft_id = self.paid("Paid draft whose review changes")
        self.review(draft_id, status="needs_revision", notes="Not yet.")
        inputs = self.inputs(baseline, draft_id=draft_id)
        response = self.client.post("/api/lifecycle/preview", headers=LIFECYCLE, content=json.dumps({"inputs": inputs}))
        self.assertEqual(response.status_code, 409)
        self.assertIn("does not have the status Human-reviewed", response.json()["detail"])
        self.review(draft_id, notes="Checked again.")
        shown = self.preview(inputs)
        self.review(draft_id, notes="A later version, saved after the preview.")
        response = self.approve(inputs, shown)
        self.assertEqual(response.status_code, 409)
        self.assertIn("its origin or review", response.json()["detail"])
        self.assertEqual(self.counts()["hypotheses"], 0)
        self.assertEqual(self.approve(inputs, response.json()["preview"]).status_code, 201)

    def test_mock_declined_invalid_failed_and_fred_contract_drafts_are_never_eligible(self):
        baseline = self.baseline()
        made = {"mock": self.mock("Mock draft for a refused freeze"),
                "refusal": self.paid("Paid refusal for a refused freeze"),
                "invalid": self.paid("Paid invalid for a refused freeze"),
                "failure": self.paid("Paid provider error for a refused freeze")}
        old = capture_text("Earlier capture under the FRED contract", "https://example.com/older", PUBLISHED, "older",
                           "Synthetic older text.", MODEL, self.intake)  # The default contract, draft-prompt-5.
        old_bytes = (self.intake / old["capture_id"] / "request.json").read_bytes()
        made["fred contract"] = self.mock("", {**old, "request_sha256": old["request"]["sha256"]})
        reasons = {"mock": "local mock", "refusal": "declined", "invalid": "validation",
                   "failure": "failed technically", "fred contract": "draft-prompt-5"}
        for name, draft_id in made.items():
            with self.subTest(name):
                self.review(draft_id)
                row = next(row for row in self.client.get("/api/lifecycle/drafts").json()["drafts"]
                           if row["draft_id"] == draft_id)
                self.assertFalse(row["eligible"])
                self.assertIn(reasons[name], " ".join(row["reasons"]))
                response = self.client.post("/api/lifecycle/preview", headers=LIFECYCLE,
                                            content=json.dumps({"inputs": self.inputs(baseline, draft_id=draft_id)}))
                self.assertEqual(response.status_code, 409)
        self.assertEqual((self.intake / old["capture_id"] / "request.json").read_bytes(), old_bytes)  # Never rebuilt.
        self.assertEqual(self.counts()["hypotheses"], 0)


class EligibilityTests(unittest.TestCase):
    """The eligibility rule for every review state, including a stale one (saved against an earlier view)."""

    def entry(self, **changes) -> dict:
        base = {"mode": "paid", "outcome": "draft", "provenance": {"prompt_version": "draft-prompt-6"},
                "review": {"state": "current", "status": "human_reviewed"}}
        return {**base, **changes}

    def test_only_a_current_human_reviewed_paid_h15_draft_is_eligible(self):
        self.assertEqual(lifecycle.draft_eligibility(self.entry()), [])
        cases = {"no review": ({"review": {"state": "none"}}, "No human review"),
                 "stale review": ({"review": {"state": "stale"}}, "saved against an earlier view"),
                 "invalid history": ({"review": {"state": "invalid", "problem": "gap"}}, "does not verify"),
                 "needs revision": ({"review": {"state": "current", "status": "needs_revision"}}, "Human-reviewed"),
                 "notes only": ({"review": {"state": "current", "status": None}}, "Human-reviewed"),
                 "mock": ({"mode": "mock"}, "local mock"),
                 "decline": ({"outcome": "no_draft"}, "declined"),
                 "FRED contract": ({"provenance": {"prompt_version": "draft-prompt-5"}}, "never rebuilt or remapped")}
        for name, (change, reason) in cases.items():
            with self.subTest(name):
                reasons = lifecycle.draft_eligibility(self.entry(**change))
                self.assertTrue(reasons)
                self.assertIn(reason, " ".join(reasons))


class StoreTests(Harness):
    def test_a_schema_2_store_keeps_its_records_and_is_upgraded_only_by_an_explicit_action(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        connection.executescript("BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + append_only_triggers(sorted(SCHEMA_2_TABLES))
                                 + "INSERT INTO store_meta VALUES ('schema_version', '2'); COMMIT;")
        connection.execute("PRAGMA foreign_keys = ON")
        fred = run_import(connection, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                          datetime(2025, 6, 2, 22, tzinfo=timezone.utc))["snapshot_id"]
        legacy = stored_before_policy_b(connection, cmt_hypothesis(ny(2025, 6, 3, 9), ny(2025, 6, 3, 9, 30)),
                                        ny(2025, 6, 3, 9, 30), fred)
        connection.close()
        rows_before = self.rows()
        before = tree(self.root)
        overview = self.client.get("/api/lifecycle").json()
        legacy_view = self.client.get(f"/api/lifecycle/hypotheses/{legacy}").json()
        self.assertEqual(tree(self.root), before)  # No read migrates, writes or adds a sidecar.
        self.assertEqual((overview["store"]["schema"], overview["store"]["interface_freezes"]), (2, False))
        self.assertEqual([(row["hypothesis_id"], row["origin"], row["status"]) for row in overview["hypotheses"]],
                         [(legacy, "outside_interface", "Frozen · Not evaluated")])
        self.assertEqual((legacy_view["baseline"]["provider"], legacy_view["origin"]["kind"]), ("fred", "outside_interface"))
        baseline = self.baseline()  # Importing into a schema-2 store adds a snapshot; it does not migrate.
        shown = self.preview(self.inputs(baseline))
        self.assertFalse(shown["freezable"])
        self.assertIn("Interface freezes need schema 3", " ".join(shown["blockers"]))
        upgraded = self.client.post("/api/lifecycle/store-upgrade", headers=LIFECYCLE,
                                    content=json.dumps({"upgrade_to": 4}))
        self.assertEqual(upgraded.status_code, 201, upgraded.text)
        self.assertEqual((upgraded.json()["schema_version"], upgraded.json()["migrated_from_schema"]), (4, 2))
        after = self.rows()
        for table in ("hypotheses", "freeze_bindings", "evaluations"):
            self.assertEqual(after[table], rows_before[table], table)  # The legacy record and its ID are unchanged.
        self.assertLessEqual(set(rows_before["market_snapshots"]), set(after["market_snapshots"]))
        self.assertEqual(self.approve(self.inputs(baseline), self.preview(self.inputs(baseline))).status_code, 201)
        self.assertEqual(self.client.get(f"/api/lifecycle/hypotheses/{legacy}").json()["hypothesis"],
                         legacy_view["hypothesis"])

    def rows(self) -> dict:
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return {table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                    for table in ("hypotheses", "freeze_bindings", "evaluations", "market_snapshots")}
        finally:
            connection.close()

    def test_lifecycle_reads_and_writes_make_no_outside_connection(self):
        attempts = []
        original = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        package_id = self.keep(*FRESH)
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo",
                                                               side_effect=AssertionError("name lookup")):
            baseline = self.import_baseline(package_id)["snapshot"]["snapshot_id"]
            inputs = self.inputs(baseline)
            shown = self.preview(inputs)
            frozen = self.approve(inputs, shown).json()
            for path in ("/api/lifecycle", "/api/lifecycle/baselines", "/api/lifecycle/drafts",
                         f"/api/lifecycle/hypotheses/{frozen['hypothesis_id']}",
                         f"/api/lifecycle/actions/{shown['preview_sha256']}"):
                self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual((attempts, self.calls), ([], []))


if __name__ == "__main__":
    unittest.main()

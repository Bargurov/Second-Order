"""My analyses: the Tracker's analyses with a published review view, read only through the verified readers.

SYNTHETIC records in temporary folders, made through the app's own routes: mock attempts, and paid attempts against a
fake provider (an httpx MockTransport with a dummy key) that answers by headline. Nothing reaches a network.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from draft_attempts import write_attempt
from model_fixtures import FAKE_KEY, THINKING, encoded, message, output_for, tool_call
from second_order import draft_catalog, human_review
from second_order.analysis_library import LIBRARY_VIEW_VERSION
from second_order.api import create_app
from second_order.draft_views import build_view, prepare_drafts
from second_order.paid_drafts import PaidSender

BASE = "http://127.0.0.1:8137"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
MODEL = "claude-sonnet-5-5"
ANSWERS = {  # Headline prefix -> what the fake provider answers: (HTTP status, body).
    "Paid refusal": (200, encoded(message(model=MODEL, stop_reason="end_turn", content=[
        dict(THINKING), {"type": "text", "text": "No hypothesis: the source states too little to support one."}]))),
    "Paid invalid": (200, encoded(message(model=MODEL, content=[{"type": "text", "text": "Here is my draft."},
                                                               tool_call()]))),
    "Paid provider error": (529, encoded({"type": "error", "error": {"type": "overloaded_error", "message": "Busy"}})),
}


def form(headline: str) -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": "2026-09-15T14:00:00-04:00",
                       "source_text": f"Synthetic published text for {headline}.\nSecond line."}).encode("utf-8")


def snapshot(root: Path) -> dict:
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                                          path.stat().st_mtime_ns) for path in sorted(root.rglob("*"))}


class AnalysisLibraryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.drafts, self.reviews = self.root / "prepared-drafts", self.root / "reviews"
        self.intake, self.attempts = self.root / "intake", self.root / "attempts"
        self.published = draft_catalog.tracker_dir(self.drafts)
        pilots = [write_attempt(self.root / "pilot" / kind, kind, kind) for kind in ("draft", "no-draft")]
        self.pilot_ids = {row["id"] for row in prepare_drafts(pilots, self.drafts, self.root / "pilot")["drafts"]}
        self.pilot_attempt = pilots[0]
        self.calls: list[httpx.Request] = []
        sender = PaidSender(api_key=lambda: FAKE_KEY, client_factory=lambda observe: httpx.Client(
            transport=httpx.MockTransport(self.answer), follow_redirects=False, trust_env=False,
            event_hooks={"response": [observe]}))
        self.client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                            self.attempts, paid=sender), base_url=BASE)
        self.addCleanup(self.client.close)

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        content = json.loads(request.content)["messages"][0]["content"]
        headline = next(line[len("Headline: "):] for line in content.splitlines() if line.startswith("Headline: "))
        status, body = next((value for prefix, value in ANSWERS.items() if headline.startswith(prefix)),
                            (200, encoded(message(output_for(request.content), model=MODEL))))
        return httpx.Response(status, content=body, headers={"content-type": "application/json",
                                                             "request-id": f"req_fake{len(self.calls):04d}"})

    def capture(self, headline: str) -> dict:
        response = self.client.post("/api/intake", content=form(headline), headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def mock(self, headline: str, outcome: str = "draft") -> str:
        preview = self.capture(headline)
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": outcome})
        response = self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", content=body, headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["draft_id"]

    def paid(self, headline: str) -> str:
        preview = self.capture(headline)
        body = json.dumps({"request_sha256": preview["request_sha256"], "approve_paid_request": True,
                           "estimated_max_usd": preview["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"]})
        response = self.client.post(f"/api/intake/{preview['capture_id']}/paid-drafts", content=body, headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["draft_id"]

    def review(self, draft_id: str, status: str | None, notes: str, parent: str | None = None) -> dict:
        loaded = self.client.get(f"/api/drafts/{draft_id}")
        provenance = loaded.json()["provenance"]
        body = {"parent_review_id": parent, "status": status, "notes": notes,
                "corrections": {"summary": None, "legs": {}},
                "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                            "prompt_hash": provenance["prompt_hash"], "response_sha256": provenance["response_sha256"]}}
        saved = self.client.post(f"/api/drafts/{draft_id}/reviews", content=json.dumps(body), headers=REVIEW)
        self.assertEqual(saved.status_code, 201, saved.text)
        return saved.json()

    def library(self) -> dict:
        response = self.client.get("/api/analyses")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["view_version"], body["provider_called"]), (LIBRARY_VIEW_VERSION, False))
        return body

    def entry(self, draft_id: str) -> dict:
        return next(entry for entry in self.library()["entries"] if entry["draft_id"] == draft_id)

    def test_an_empty_library_is_an_empty_collection_and_reading_creates_nothing(self):
        before = snapshot(self.root)
        body = self.library()
        self.assertEqual((body["entries"], body["damaged"]), ([], []))
        self.assertEqual(body["not_listed"], {"saved_events": {"none": 0, "incomplete": 0, "awaiting_publication": 0},
                                              "prepared_drafts": 2})
        self.assertEqual(snapshot(self.root), before)

    def test_each_outcome_and_mode_is_listed_from_its_verified_records(self):
        headlines = {"mock draft": "Mock draft event", "mock refusal": "Mock refusal event",
                     "paid draft": "Paid draft event", "paid refusal": "Paid refusal event",
                     "paid invalid": "Paid invalid event", "paid failure": "Paid provider error event"}
        made = {name: self.mock(headline, "no_draft" if name == "mock refusal" else "draft") if name.startswith("mock")
                else self.paid(headline) for name, headline in headlines.items()}
        self.capture("Captured but never sent")
        body = self.library()
        listed = {entry["draft_id"]: entry for entry in body["entries"]}
        self.assertEqual(set(listed), set(made.values()))
        self.assertFalse(self.pilot_ids & set(listed))  # Prepared pilot drafts are not Tracker analyses...
        self.assertEqual(body["not_listed"]["prepared_drafts"], 2)  # ...they are only counted,
        self.assertEqual(body["not_listed"]["saved_events"]["none"], 1)  # as is the capture that was never sent.
        self.assertEqual(body["damaged"], [])
        expected = {"mock draft": ("draft", "mock", "summary"), "mock refusal": ("no_draft", "mock", "explanation"),
                    "paid draft": ("draft", "paid", "summary"), "paid refusal": ("no_draft", "paid", "explanation"),
                    "paid invalid": ("invalid", "paid", "problem"), "paid failure": ("technical_failure", "paid", "problem")}
        for name, (outcome, mode, kind) in expected.items():
            entry = listed[made[name]]
            with self.subTest(name):
                self.assertEqual((entry["outcome"], entry["mode"], entry["model_output"]["kind"]), (outcome, mode, kind))
                self.assertEqual(entry["event"], {"headline": headlines[name],
                                                  "source_url": "https://example.com/published-statement",
                                                  "published_at": "2026-09-15T18:00:00Z",
                                                  "published_at_as_supplied": "2026-09-15T14:00:00-04:00"})
                self.assertEqual(entry["provenance"]["model"], MODEL)
                self.assertEqual(entry["review"], {"state": "none", "versions": 0})
                self.assertEqual(entry["draft_view_sha256"],
                                 human_review.fingerprint((self.published / f"draft-{entry['draft_id']}.json").read_bytes()))
        self.assertEqual(listed[made["mock draft"]]["provenance"]["http_status"], None)  # No provider was contacted.
        self.assertEqual(listed[made["paid draft"]]["provenance"]["request_id"], "req_fake0001")
        self.assertEqual(listed[made["paid failure"]]["provenance"]["http_status"], 529)
        self.assertIn("Mock workflow draft", listed[made["mock draft"]]["model_output"]["text"])
        self.assertIn("states too little", listed[made["paid refusal"]]["model_output"]["text"])
        self.assertEqual([entry["provenance"]["sent_at"] for entry in body["entries"]],
                         sorted((entry["provenance"]["sent_at"] for entry in body["entries"]), reverse=True))

    def test_review_status_comes_only_from_reviews_of_the_current_view(self):
        draft_id = self.mock("Reviewed event")
        self.assertEqual(self.entry(draft_id)["review"]["state"], "none")
        first = self.review(draft_id, "needs_revision", "The second leg needs a source quote.")
        review = self.entry(draft_id)["review"]
        self.assertEqual((review["state"], review["status"], review["versions"], review["notes_excerpt"]),
                         ("current", "needs_revision", 1, "The second leg needs a source quote."))
        second = self.review(draft_id, "human_reviewed", "Checked against the source.", first["review_id"])
        self.assertEqual((self.entry(draft_id)["review"]["status"], self.entry(draft_id)["review"]["versions"]),
                         ("human_reviewed", 2))
        third = self.review(draft_id, None, "A note without a status.", second["review_id"])
        review = self.entry(draft_id)["review"]
        self.assertEqual((review["state"], review["status"], review["versions"]), ("current", None, 3))
        # A later version saved against another view (here written directly, as a valid chain): this view has no
        # current review, and the earlier "human reviewed" judgment is not carried over.
        stale = {**{key: third[key] for key in ("record_version", "draft_id", "attributed_to", "corrections")},
                 "sequence": 4, "parent_review_id": third["review_id"], "saved_at": "2026-10-08T12:00:00+00:00",
                 "status": "human_reviewed", "notes": "Saved against an earlier view.",
                 "binding": {**third["binding"], "draft_view_sha256": "0" * 64}}
        stale["review_id"] = human_review.review_id(stale)
        (self.reviews / draft_id / "000004.json").write_text(json.dumps(stale), encoding="utf-8")
        self.assertEqual(self.entry(draft_id)["review"],
                         {"state": "stale", "versions": 4, "latest_saved_at": "2026-10-08T12:00:00+00:00"})
        # A history that does not verify is reported as such: never as "not reviewed", and the entry stays listed.
        (self.reviews / draft_id / "000004.json").write_text("{not json", encoding="utf-8")
        review = self.entry(draft_id)["review"]
        self.assertEqual((review["state"], review["versions"]), ("invalid", None))
        self.assertIn("not strict JSON", review["problem"])

    def test_one_damaged_record_is_reported_and_the_rest_stay_listed(self):
        kept, tampered, mislabelled = self.mock("Kept event"), self.mock("Tampered event"), self.mock("Mislabelled event")
        unverified = self.mock("Unverified capture event")
        view_file = self.published / f"draft-{tampered}.json"
        view_file.write_bytes(view_file.read_bytes().replace(b"Tampered event", b"Tampered EVENT"))
        capture_of = {self.entry(draft)["capture_id"]: draft for draft in (mislabelled, unverified)}
        mislabelled_capture = next(key for key, value in capture_of.items() if value == mislabelled)
        unverified_capture = next(key for key, value in capture_of.items() if value == unverified)
        reservation = self.attempts / mislabelled_capture / "reservation.json"
        reservation.write_text(reservation.read_text(encoding="utf-8").replace('"mode": "mock"', '"mode": "paid"'),
                               encoding="utf-8")
        source = self.intake / unverified_capture / "source.txt"
        os.chmod(source, stat.S_IREAD | stat.S_IWRITE)  # Captures are saved read-only; this edit is the damage.
        source.write_bytes(source.read_bytes() + b" edited")
        orphan = build_view(self.pilot_attempt)  # A Tracker-folder view no verified capture and attempt produced.
        draft_catalog.publish_view(orphan, self.published, self.drafts)
        body = self.library()
        self.assertEqual([entry["draft_id"] for entry in body["entries"]], [kept])
        problems = {(item["capture_id"], item["draft_id"]): item["problem"] for item in body["damaged"]}
        self.assertEqual(len(body["damaged"]), 4, body["damaged"])
        self.assertIn("different prepared view", next(text for key, text in problems.items() if key[1] == tampered))
        self.assertIn("the attempt records the paid mode, but its view records the run 'tracker-mock-1'",
                      next(text for key, text in problems.items() if key[0] == mislabelled_capture))
        self.assertIn("source.txt no longer matches", next(text for key, text in problems.items()
                                                           if key[0] == unverified_capture))
        self.assertIn("not backed by a verified capture and attempt", problems[(orphan["provenance"]["case"], orphan["id"])])

    def test_library_reads_send_nothing_write_nothing_and_keep_the_local_host_check(self):
        self.mock("Read-only event")
        self.paid("Paid read-only event")
        before, calls = snapshot(self.root), len(self.calls)
        blocked = AssertionError("a library read tried to open a network connection")
        with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
            for _ in range(3):
                self.assertEqual(len(self.library()["entries"]), 2)
        self.assertEqual((snapshot(self.root), len(self.calls)), (before, calls))
        self.assertEqual(self.client.get("/api/analyses", headers={"Host": "attacker.example:8137"}).status_code, 403)
        self.assertEqual(self.client.post("/api/analyses", content=b"{}", headers=INTAKE).status_code, 405)


if __name__ == "__main__":
    unittest.main()

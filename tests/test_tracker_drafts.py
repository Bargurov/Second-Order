"""Tracker-published mock drafts beside prepare-drafts: ownership, concurrent publication, recovery from the
saved records, interrupted attempts and lost replies.

Synthetic records in temporary folders only. Network connections, request rebuilding and new mock responses are
made to fail wherever recovery runs, so a passing test shows none of them was used.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from draft_attempts import write_attempt
from second_order.analysis_flow import FlowRefused, dispatch_mock, publish_recorded
from second_order.api import create_app
from second_order.draft_views import INDEX_NAME, prepare_drafts

BASE = "http://127.0.0.1:8131"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
CLOCK = lambda: datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)  # noqa: E731
NOT_ALLOWED = AssertionError("recovery must not reach a provider, rebuild the request or regenerate the mock")


def form(headline: str) -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": "2026-10-04T14:00:00+03:00",
                       "source_text": f"Synthetic published text for {headline}.\nSecond line."}).encode("utf-8")


def files(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


class TrackerDraftTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pilot = self.root / "pilot"
        self.drafts, self.reviews = self.root / "prepared-drafts", self.root / "reviews"
        self.intake, self.attempts = self.root / "intake", self.root / "attempts"
        self.pilot_attempt = write_attempt(self.pilot / "draft", "draft", "draft")
        self.pilot_id = prepare_drafts([self.pilot_attempt], self.drafts, self.pilot)["drafts"][0]["id"]
        self.client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                            self.attempts), base_url=BASE)
        self.addCleanup(self.client.close)

    def capture(self, headline: str = "Synthetic committee holds its rate") -> dict:
        response = self.client.post("/api/intake", content=form(headline), headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def dispatch(self, preview: dict, outcome: str = "draft"):
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": outcome})
        return self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", content=body, headers=INTAKE)

    def state(self, capture_id: str) -> dict:
        response = self.client.get(f"/api/intake/{capture_id}/attempt")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def publish(self, capture_id: str, request_sha256: str):
        return self.client.post(f"/api/intake/{capture_id}/publish",
                                content=json.dumps({"request_sha256": request_sha256}), headers=INTAKE)

    def listed(self) -> list[str]:
        response = self.client.get("/api/drafts")
        self.assertEqual(response.status_code, 200, response.text)
        return [row["id"] for row in response.json()["drafts"]]

    def review(self, draft_id: str, notes: str) -> dict:
        loaded = self.client.get(f"/api/drafts/{draft_id}")
        provenance = loaded.json()["provenance"]
        body = {"parent_review_id": None, "status": "needs_revision", "notes": notes,
                "corrections": {"summary": None, "legs": {}},
                "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                            "prompt_hash": provenance["prompt_hash"], "response_sha256": provenance["response_sha256"]}}
        saved = self.client.post(f"/api/drafts/{draft_id}/reviews", content=json.dumps(body), headers=REVIEW)
        self.assertEqual(saved.status_code, 201, saved.text)
        return saved.json()

    def test_foreign_hosts_cannot_read_saved_events_drafts_or_reviews(self):
        preview = self.capture("PRIVATE synthetic event")
        draft_id = self.dispatch(preview).json()["draft_id"]
        self.review(draft_id, "PRIVATE synthetic review")
        paths = ["/api/intake", f"/api/intake/{preview['capture_id']}",
                 f"/api/intake/{preview['capture_id']}/attempt", "/api/drafts",
                 f"/api/drafts/{draft_id}", f"/api/drafts/{draft_id}/reviews"]
        before = {folder: files(folder) for folder in (self.intake, self.attempts, self.drafts, self.reviews)}
        for host in ("attacker.example:8131", "127.0.0.1.attacker.example:8131", "localhost:bad", ""):
            for path in paths:
                with self.subTest(host=host, path=path):
                    response = self.client.get(path, headers={"Host": host, "Origin": f"http://{host}"})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("PRIVATE", response.text)
        self.assertEqual({folder: files(folder) for folder in before}, before)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_tracker_drafts_and_their_reviews_survive_prepare_drafts(self):
        preview = self.capture()
        sent = self.dispatch(preview)
        self.assertEqual(sent.status_code, 201, sent.text)
        draft_id = sent.json()["draft_id"]
        view_before = self.client.get(f"/api/drafts/{draft_id}")
        saved = self.review(draft_id, "Reviewed before the pilot drafts were prepared again.")
        self.assertEqual(set(self.listed()), {self.pilot_id, draft_id})

        prepare_drafts([self.pilot_attempt], self.drafts, self.pilot)  # The documented step, run again.

        self.assertEqual(set(self.listed()), {self.pilot_id, draft_id})
        view_after = self.client.get(f"/api/drafts/{draft_id}")
        self.assertEqual(view_after.status_code, 200)
        self.assertEqual((view_after.content, view_after.headers["x-draft-view-sha256"]),
                         (view_before.content, view_before.headers["x-draft-view-sha256"]))
        history = self.client.get(f"/api/drafts/{draft_id}/reviews").json()
        self.assertEqual(history["reviews"], [saved])  # The saved review is still bound to the current view.
        self.assertEqual(history["draft_view_sha256"], saved["binding"]["draft_view_sha256"])
        prepared_rows = json.loads((self.drafts / INDEX_NAME).read_text(encoding="utf-8"))["drafts"]
        self.assertEqual([row["id"] for row in prepared_rows], [self.pilot_id])  # prepare-drafts owns its index.

    def test_concurrent_publications_keep_every_entry(self):
        previews = [self.capture(f"Concurrent event {number}") for number in range(8)]
        start, outcomes = threading.Barrier(len(previews)), []

        def run(preview: dict) -> None:
            body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": "draft"}).encode()
            start.wait()
            try:
                outcomes.append(dispatch_mock(preview["capture_id"], body, self.intake, self.attempts, self.drafts,
                                              CLOCK)["draft_id"])
            except FlowRefused as exc:
                outcomes.append(f"refused {exc.status}: {exc}")

        with open(self.drafts / INDEX_NAME, "rb"):  # A reader holding the prepared index does not block publishing.
            threads = [threading.Thread(target=run, args=(preview,)) for preview in previews]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(set(outcomes)), len(previews), outcomes)
        self.assertTrue(all(len(outcome) == 64 for outcome in outcomes), outcomes)
        self.assertEqual(set(self.listed()), {self.pilot_id, *outcomes})
        leftovers = [path.name for path in self.root.rglob(".tmp*")] + [path.name for path in self.root.rglob("*.tmp")]
        self.assertEqual(leftovers, [])

    def test_a_failed_publication_is_recovered_from_the_saved_records_without_a_second_attempt(self):
        preview = self.capture()
        lock = PermissionError(13, "Access is denied (simulated Windows file lock)")
        with patch("second_order.draft_catalog.publish_view", side_effect=lock):
            failed = self.dispatch(preview)
        self.assertEqual(failed.status_code, 500)
        self.assertIn("recorded", failed.json()["detail"])
        state = self.state(preview["capture_id"])
        self.assertEqual(state["state"], "awaiting_publication")
        self.assertNotIn(state.get("draft_id"), self.listed())
        attempt = self.attempts / preview["capture_id"]
        recorded = files(attempt)

        body = json.dumps({"request_sha256": preview["request_sha256"]}).encode()
        with patch("second_order.analysis_flow.mock_response", side_effect=NOT_ALLOWED), \
                patch("second_order.event_intake.build_request", side_effect=NOT_ALLOWED):
            self.assertEqual(self.publish(preview["capture_id"], "0" * 64).status_code, 409)
            # The recovery itself, with network connections also refused (the test client needs sockets, so the
            # action is called directly here; the HTTP route below must then agree with it).
            with patch.object(socket.socket, "connect", side_effect=NOT_ALLOWED):
                result = publish_recorded(preview["capture_id"], body, self.intake, self.attempts, self.drafts)
            again = self.publish(preview["capture_id"], preview["request_sha256"])
        self.assertEqual((result["status"], result["recovered"], result["provider_called"], result["attempts"],
                          result["retries"], result["cost_usd"]),
                         ("prepared_for_human_review", True, False, 1, 0, 0))
        self.assertEqual((again.status_code, again.json()["draft_id"]), (201, result["draft_id"]))  # Idempotent.
        self.assertEqual(files(attempt), recorded)  # The recorded request and response were used as they are.
        self.assertEqual(sorted(path.name for path in self.attempts.iterdir()), [preview["capture_id"]])
        self.assertIn(result["draft_id"], self.listed())
        self.assertEqual(self.state(preview["capture_id"])["state"], "ready")
        self.assertEqual(self.dispatch(preview).status_code, 409)  # Still never attempted twice.
        self.assertEqual(files(attempt), recorded)

    def test_an_interrupted_attempt_is_reported_and_blocks_another_attempt(self):
        preview = self.capture()
        with patch("second_order.analysis_flow.mock_response", side_effect=OSError("interrupted")):
            failed = self.dispatch(preview)
        self.assertEqual(failed.status_code, 500)
        self.assertNotIn("could not be recorded", failed.json()["detail"])  # Part of the attempt was recorded.
        attempt = self.attempts / preview["capture_id"]
        recorded = files(attempt)
        state = self.state(preview["capture_id"])
        self.assertEqual(state["state"], "incomplete")
        self.assertIn("reservation.json", state["files"])
        self.assertNotIn("response.json", state["files"])
        self.assertEqual(self.dispatch(preview).status_code, 409)
        self.assertEqual(self.publish(preview["capture_id"], preview["request_sha256"]).status_code, 409)
        self.assertEqual(files(attempt), recorded)
        self.assertEqual(set(self.listed()), {self.pilot_id})

    def test_a_failure_while_writing_a_record_leaves_no_partial_file(self):
        preview = self.capture()
        with patch("second_order.analysis_flow.os.fsync", side_effect=OSError("disk full")):
            failed = self.dispatch(preview)
        self.assertEqual(failed.status_code, 500)
        attempt = self.attempts / preview["capture_id"]
        self.assertEqual(sorted(path.name for path in attempt.iterdir()), [])  # No partial or temporary file.
        state = self.state(preview["capture_id"])
        self.assertEqual((state["state"], state["files"]), ("incomplete", []))
        self.assertEqual(self.dispatch(preview).status_code, 409)  # The reservation still holds.

    def test_a_lost_reply_is_settled_by_reading_the_attempt_state(self):
        preview = self.capture()
        self.assertEqual(self.state(preview["capture_id"])["state"], "none")
        wrong = self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", headers=INTAKE,
                                 content=json.dumps({"request_sha256": "0" * 64, "mock_outcome": "draft"}))
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(self.state(preview["capture_id"])["state"], "none")  # Refused before any attempt.
        sent = self.dispatch(preview, "no_draft")  # Its reply is "lost": the page only knows it sent it.
        self.assertEqual(sent.status_code, 201)
        state = self.state(preview["capture_id"])
        self.assertEqual((state["state"], state["draft_id"], state["outcome"]),
                         ("ready", sent.json()["draft_id"], "no_draft"))
        self.assertEqual(self.dispatch(preview, "no_draft").status_code, 409)
        self.assertEqual(sorted(path.name for path in self.attempts.iterdir()), [preview["capture_id"]])

    def test_state_and_listing_reads_never_write(self):
        preview = self.capture()
        before = files(self.root)
        for path in (f"/api/intake/{preview['capture_id']}/attempt", "/api/drafts", "/api/intake"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/api/intake/not-a-capture/attempt").status_code, 404)
        self.assertEqual(files(self.root), before)
        self.assertFalse(self.attempts.exists())
        for method in ("put", "delete"):
            self.assertEqual(getattr(self.client, method)(f"/api/intake/{preview['capture_id']}/attempt",
                                                          headers=INTAKE).status_code, 405)

    def test_publication_is_a_local_write_with_an_exact_confirmation(self):
        preview = self.capture()
        path = f"/api/intake/{preview['capture_id']}/publish"
        body = json.dumps({"request_sha256": preview["request_sha256"]})
        self.assertEqual(self.client.post(path, content=body, headers={**INTAKE, "Origin": "http://evil.example"})
                         .status_code, 403)
        self.assertEqual(self.client.post(path, content=body, headers={**INTAKE, "Content-Type": "text/plain"})
                         .status_code, 415)
        for bad in ('{"request_sha256": 5}', '{"request_sha256": "%s", "retry": true}' % preview["request_sha256"],
                    "[]"):
            self.assertEqual(self.client.post(path, content=bad, headers=INTAKE).status_code, 422, bad)
        self.assertEqual(self.client.post(path, content=body, headers=INTAKE).status_code, 409)  # No attempt yet.
        self.assertFalse(self.attempts.exists())


if __name__ == "__main__":
    unittest.main()

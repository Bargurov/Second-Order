"""Tracker event -> exact request -> one local mock -> prepared review -> saved human judgment."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from second_order.analysis_flow import (FLOW_VERSION, MODEL, FlowRefused, capture_from_form, dispatch_mock,
                                        preview_capture)
from second_order.api import create_app
from second_order.draft_catalog import listing, tracker_dir
from second_order.draft_views import DRAFT_VIEW_VERSION
from second_order.human_review import RECORD_VERSION

BASE = "http://127.0.0.1:8129"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW_HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
CLOCK = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)


def form(headline: str = "Synthetic committee signals a slower policy pace") -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": "2026-10-04T14:00:00+03:00",
                       "source_text": "Synthetic published text for the zero-cost interface test.\nSecond line."}) \
        .encode("utf-8")


class AnalysisFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.intake, self.attempts = root / "intake", root / "attempts"
        self.drafts, self.reviews = root / "drafts", root / "reviews"

    def tearDown(self):
        self.folder.cleanup()

    def capture(self, headline: str = "Synthetic committee signals a slower policy pace") -> dict:
        return capture_from_form(form(headline), self.intake, lambda: CLOCK)

    @staticmethod
    def confirmation(preview: dict, outcome: str = "draft") -> bytes:
        return json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": outcome}).encode()

    def test_capture_previews_the_exact_saved_sonnet_request_and_zero_cost_mock(self):
        preview = self.capture()
        folder = self.intake / preview["capture_id"]
        request = (folder / "request.json").read_bytes()
        self.assertEqual((preview["flow_version"], preview["model"], preview["provider_called"]),
                         (FLOW_VERSION, MODEL, False))
        self.assertEqual(preview["cost_estimate"]["mock_run_usd"], 0)
        self.assertGreater(preview["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"], 0)
        self.assertEqual(preview["request_sha256"], hashlib.sha256(request).hexdigest())
        self.assertEqual(json.dumps(preview["request"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                         .encode("utf-8"), request)
        self.assertFalse(self.attempts.exists() or self.drafts.exists())

    def test_dispatch_copies_the_approved_request_bytes_and_attempts_once_without_a_provider(self):
        preview = self.capture()
        capture = self.intake / preview["capture_id"]
        forbidden = AssertionError("the mock path reached a provider or rebuilt the request")
        with patch("second_order.event_intake.build_request", side_effect=forbidden), \
                patch.object(socket.socket, "connect", side_effect=forbidden):
            result = dispatch_mock(preview["capture_id"], self.confirmation(preview), self.intake, self.attempts,
                                   self.drafts, lambda: CLOCK)
        attempt = self.attempts / preview["capture_id"]
        self.assertEqual((result["status"], result["provider_called"], result["cost_usd"], result["attempts"],
                          result["retries"], result["frozen"], result["evaluated"]),
                         ("prepared_for_human_review", False, 0, 1, 0, False, False))
        self.assertEqual((attempt / "request.json").read_bytes(), (capture / "request.json").read_bytes())
        manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["attempts"], manifest["retries"], manifest["fallbacks"]), (1, 0, None))
        self.assertIn("No provider was contacted", manifest["provenance"])
        index = listing(self.drafts, tracker_dir(self.drafts))  # Published to the Tracker's own folder.
        self.assertEqual((index["view_version"], [row["id"] for row in index["drafts"]]),
                         (DRAFT_VIEW_VERSION, [result["draft_id"]]))
        self.assertFalse(self.drafts.exists())  # prepare-drafts' folder is never written by the Tracker.
        before = (attempt / "response.json").read_bytes()
        with self.assertRaisesRegex(FlowRefused, "never sent or mocked twice") as refused:
            dispatch_mock(preview["capture_id"], self.confirmation(preview), self.intake, self.attempts,
                          self.drafts, lambda: CLOCK)
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual((attempt / "response.json").read_bytes(), before)

    def test_wrong_hash_is_refused_before_an_attempt_and_a_mock_decline_is_reviewable(self):
        first = self.capture()
        wrong = json.dumps({"request_sha256": "0" * 64, "mock_outcome": "draft"}).encode()
        with self.assertRaisesRegex(FlowRefused, "does not match"):
            dispatch_mock(first["capture_id"], wrong, self.intake, self.attempts, self.drafts, lambda: CLOCK)
        self.assertFalse(self.attempts.exists())

        second = self.capture("Synthetic source is insufficient for a hypothesis")
        result = dispatch_mock(second["capture_id"], self.confirmation(second, "no_draft"), self.intake,
                               self.attempts, self.drafts, lambda: CLOCK)
        view = json.loads((tracker_dir(self.drafts) / f"draft-{result['draft_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual((result["outcome"], view["outcome"], view["draft"]),
                         ("no_draft", "no_draft", None))
        self.assertIn("No provider was contacted", " ".join(view["explanation"]["text"]))

    def test_http_path_reaches_the_existing_review_save_without_files_or_commands(self):
        app = create_app(Path(self.folder.name) / "no-dossiers", None, self.drafts, self.reviews,
                         self.intake, self.attempts)
        with TestClient(app, base_url=BASE) as client:
            self.assertEqual(client.post("/api/intake", content=form()).status_code, 403)
            captured = client.post("/api/intake", content=form(), headers=HEADERS)
            self.assertEqual(captured.status_code, 201)
            preview = captured.json()
            sent = client.post(f"/api/intake/{preview['capture_id']}/mock-drafts",
                               content=self.confirmation(preview), headers=HEADERS)
            self.assertEqual(sent.status_code, 201)
            result = sent.json()
            loaded = client.get(f"/api/drafts/{result['draft_id']}")
            self.assertEqual(loaded.status_code, 200)
            view = loaded.json()
            review = {"parent_review_id": None, "status": "needs_revision",
                      "notes": "Saved through the complete interface path.",
                      "corrections": {"summary": None, "legs": {}},
                      "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                                  "prompt_hash": view["provenance"]["prompt_hash"],
                                  "response_sha256": view["provenance"]["response_sha256"]}}
            saved = client.post(f"/api/drafts/{result['draft_id']}/reviews", content=json.dumps(review),
                                headers=REVIEW_HEADERS)
            self.assertEqual((saved.status_code, saved.json()["record_version"]), (201, RECORD_VERSION))
            self.assertEqual(client.get(f"/api/drafts/{result['draft_id']}/reviews").json()["reviews"][0]["notes"],
                             review["notes"])


if __name__ == "__main__":
    unittest.main()

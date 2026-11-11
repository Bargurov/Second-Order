"""One paid Sonnet request from the Tracker, verified only against a fake provider with a dummy key.

The fake provider is an httpx MockTransport injected through PaidSender: nothing here can reach the network.
Each test checks what the fake received, what was recorded and what the review screen can open.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from model_fixtures import FAKE_KEY, THINKING, encoded, escaped, h15_output, message, tool_call
from second_order import paid_drafts
from second_order.analysis_flow import FlowRefused
from second_order.api import create_app
from second_order.draft_pilot import live_client
from second_order.model_draft import API_VERSION, MESSAGES_URL
from second_order.accounts import create_store
from second_order.paid_drafts import PAID_RUN, PaidSender, dispatch_paid

BASE = "http://127.0.0.1:8135"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
REVIEW = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Review": "1"}
MODEL = "claude-sonnet-5-5"
REQUEST_ID = "req_simulated0123456789"
NOT_ALLOWED = AssertionError("this step must not contact the provider")


class FakeProvider:
    """A MockTransport stand-in for the Claude API: records each request and answers as configured."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status, self.headers = 200, {"request-id": REQUEST_ID}
        self.body = encoded(message(h15_output(), model=MODEL))  # New Tracker requests offer the H.15 IDs.
        self.error: Exception | None = None
        self.gate: threading.Event | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.gate is not None:
            self.gate.wait(10)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, content=self.body,
                              headers={"content-type": "application/json", **self.headers})

    def factory(self, observe):
        """The same client settings as the real sender (no redirects, no environment), with a fake transport."""
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False, trust_env=False,
                            event_hooks={"response": [observe]})


def form(headline: str, text: str = "Synthetic published text for a paid-path test.\nSecond line.") -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": "2026-09-15T14:00:00-04:00", "source_text": text}).encode("utf-8")


def every_file(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class PaidDraftTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.intake, self.attempts = self.root / "intake", self.root / "attempts"
        self.drafts, self.reviews = self.root / "prepared-drafts", self.root / "reviews"
        self.provider = FakeProvider()
        self.sender = PaidSender(api_key=lambda: FAKE_KEY, client_factory=self.provider.factory)
        self.client = self.app(self.sender)

    def app(self, sender: PaidSender | None) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                       self.attempts, paid=sender), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def capture(self, headline: str = "Synthetic committee holds its rate", text: str | None = None) -> dict:
        response = self.client.post("/api/intake", content=form(headline) if text is None else form(headline, text),
                                    headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def approval(preview: dict, **changes) -> dict:
        return {"request_sha256": preview["request_sha256"], "approve_paid_request": True,
                "estimated_max_usd": preview["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"],
                **changes}

    def send(self, preview: dict, client: TestClient | None = None, **changes):
        return (client or self.client).post(f"/api/intake/{preview['capture_id']}/paid-drafts", headers=INTAKE,
                                            content=json.dumps(self.approval(preview, **changes)))

    def manifest(self, preview: dict) -> dict:
        return json.loads((self.attempts / preview["capture_id"] / "manifest.json").read_text(encoding="utf-8"))

    def state(self, preview: dict) -> dict:
        response = self.client.get(f"/api/intake/{preview['capture_id']}/attempt")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_no_key_anywhere(self):
        for name, data in every_file(self.root).items():
            self.assertNotIn(FAKE_KEY.encode(), data, name)
            self.assertNotIn(escaped(FAKE_KEY).encode(), data, name)

    def test_a_paid_draft_sends_the_saved_bytes_once_and_is_reviewable(self):
        preview = self.capture()
        self.assertEqual(preview["modes"]["paid"]["enabled"], True)
        self.assertEqual(preview["modes"]["mock"]["enabled"], True)
        saved_request = (self.intake / preview["capture_id"] / "request.json").read_bytes()
        sent = self.send(preview)
        self.assertEqual(sent.status_code, 201, sent.text)
        result = sent.json()
        self.assertEqual((result["mode"], result["provider_called"], result["recorded_outcome"], result["outcome"],
                          result["attempts"], result["retries"]), ("paid", True, "draft", "draft", 1, 0))
        self.assertEqual(result["cost_usd"], 0.0084)  # From the response usage: 1,200 in at $2, 600 out at $10.

        (request,) = self.provider.requests
        self.assertEqual((request.method, str(request.url)), ("POST", MESSAGES_URL))
        self.assertEqual(request.content, saved_request)  # Exactly the approved saved bytes, never reserialized.
        self.assertEqual((request.headers["x-api-key"], request.headers["anthropic-version"],
                          request.headers["content-type"]), (FAKE_KEY, API_VERSION, "application/json"))
        attempt = self.attempts / preview["capture_id"]
        self.assertEqual((attempt / "request.json").read_bytes(), saved_request)
        self.assertEqual((attempt / "response.json").read_bytes(), self.provider.body)
        manifest = self.manifest(preview)
        self.assertEqual((manifest["pilot"], manifest["http_status"], manifest["request_id"], manifest["outcome"],
                          manifest["synthetic_case"], manifest["response"]["sha256"]),
                         (PAID_RUN, 200, REQUEST_ID, "draft", False, hashlib.sha256(self.provider.body).hexdigest()))
        self.assertEqual(manifest["response"]["usage"], {"input_tokens": 1200, "output_tokens": 600})

        loaded = self.client.get(f"/api/drafts/{result['draft_id']}")
        self.assertEqual(loaded.status_code, 200)
        provenance = loaded.json()["provenance"]
        self.assertEqual((provenance["pilot"], provenance["model"], provenance["request_id"],
                          provenance["http_status"]), (PAID_RUN, MODEL, REQUEST_ID, 200))
        review = {"parent_review_id": None, "status": "needs_revision", "notes": "Reviewed the paid draft.",
                  "corrections": {"summary": None, "legs": {}},
                  "binding": {"draft_view_sha256": loaded.headers["x-draft-view-sha256"],
                              "prompt_hash": provenance["prompt_hash"],
                              "response_sha256": provenance["response_sha256"]}}
        saved = self.client.post(f"/api/drafts/{result['draft_id']}/reviews", content=json.dumps(review),
                                 headers=REVIEW)
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(len(self.provider.requests), 1)
        self.assert_no_key_anywhere()

    def test_refusal_invalid_response_and_provider_error_are_recorded_and_reviewable(self):
        cases = {
            "refusal": (200, encoded(message(model=MODEL, stop_reason="end_turn", content=[
                dict(THINKING), {"type": "text", "text": "No hypothesis: the source does not support one."}])),
                "no draft", "no_draft"),
            "invalid": (200, encoded(message(model=MODEL, content=[
                {"type": "text", "text": "Here is my draft."}, tool_call()])), "refused", "invalid"),
            "provider error": (529, encoded({"type": "error", "error": {"type": "overloaded_error",
                                                                        "message": "Overloaded"}}),
                               "provider error", "technical_failure"),
        }
        for name, (status, body, recorded, outcome) in cases.items():
            with self.subTest(name):
                self.provider.status, self.provider.body = status, body
                before = len(self.provider.requests)
                preview = self.capture(f"Paid {name} event")
                sent = self.send(preview)
                self.assertEqual(sent.status_code, 201, sent.text)
                self.assertEqual((sent.json()["recorded_outcome"], sent.json()["outcome"]), (recorded, outcome))
                self.assertEqual(len(self.provider.requests), before + 1)
                manifest = self.manifest(preview)
                self.assertEqual((manifest["http_status"], manifest["request_id"]), (status, REQUEST_ID))
                attempt = self.attempts / preview["capture_id"]
                self.assertEqual((attempt / "response.json").exists(), status == 200)  # Error bodies are not kept.
                view = self.client.get(f"/api/drafts/{sent.json()['draft_id']}").json()
                self.assertEqual(view["outcome"], outcome)
                if name == "provider error":
                    self.assertIn("HTTP 529 (overloaded_error)", view["problem"])
                    self.assertIsNone(manifest["estimated_cost"])  # No usage, so no cost is invented.
                    self.assertEqual({key: manifest["provider_error"][key] for key in (
                        "http_status", "error_type", "message", "request_id")},
                        {"http_status": 529, "error_type": "overloaded_error", "message": "Overloaded",
                         "request_id": REQUEST_ID})  # Bounded diagnostics of the error reply (provider-error-0.1).
                else:
                    self.assertIsNone(manifest["provider_error"])
                self.assertEqual(self.state(preview)["state"], "ready")
        self.assert_no_key_anywhere()

    def test_configuration_approval_and_capture_are_checked_before_any_reservation(self):
        preview = self.capture()
        path = f"/api/intake/{preview['capture_id']}/paid-drafts"
        disabled = self.app(None)
        refused = self.send(preview, client=disabled)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("not enabled", refused.json()["detail"])
        self.assertEqual(disabled.get(f"/api/intake/{preview['capture_id']}").json()["modes"]["paid"]["enabled"],
                         False)
        for key in ("", " sk-ant-padded", "sk-ant-with space"):
            with self.subTest(key=key):
                self.assertEqual(self.send(preview, client=self.app(PaidSender(api_key=lambda key=key: key,
                                                                               client_factory=self.provider.factory)))
                                 .status_code, 409)
        bad = {
            "wrong hash": (self.approval(preview, request_sha256="0" * 64), 409),
            "not approved": (self.approval(preview, approve_paid_request=False), 422),
            "approval as text": (self.approval(preview, approve_paid_request="yes"), 422),
            "estimate changed": (self.approval(preview, estimated_max_usd=0.01), 409),
            "estimate missing": ({key: value for key, value in self.approval(preview).items()
                                  if key != "estimated_max_usd"}, 422),
            "extra field": (self.approval(preview, retry=True), 422),
        }
        for name, (body, status) in bad.items():
            with self.subTest(name):
                self.assertEqual(self.client.post(path, content=json.dumps(body), headers=INTAKE).status_code, status)
        self.assertEqual(self.client.post(path, content=json.dumps(self.approval(preview)),
                                          headers={**INTAKE, "Origin": "http://evil.example"}).status_code, 403)
        altered = self.capture("An event whose saved source is altered after preview")
        source = self.intake / altered["capture_id"] / "source.txt"
        os.chmod(source, 0o666)
        source.write_bytes(b"Altered after the preview.")
        self.assertEqual(self.send(altered).status_code, 409)
        carrying = self.capture("An event whose text carries the key", f"Pasted by mistake: {FAKE_KEY}")
        self.assertIn("would carry the credential", self.send(carrying).json()["detail"])
        self.assertFalse(self.attempts.exists())
        self.assertEqual(self.provider.requests, [])

    def test_previews_never_send_or_reserve_and_paid_availability_is_not_an_approval(self):
        self.provider.error = NOT_ALLOWED
        disabled = self.app(None)
        captured_by = {}
        for paid, client in ((True, self.client), (False, disabled)):
            with self.subTest(paid_enabled=paid):
                captured = client.post("/api/intake", content=form(f"Preview only, paid enabled: {paid}"),
                                       headers=INTAKE)
                self.assertEqual(captured.status_code, 201, captured.text)
                capture_id = captured.json()["capture_id"]
                saved = every_file(self.intake / capture_id)
                for response in (captured, client.get(f"/api/intake/{capture_id}")):
                    preview = response.json()
                    self.assertIs(preview.get("provider_called"), False)  # Previewing itself sends nothing.
                    self.assertNotIn("mode", preview)  # `modes` alone says what this server offers.
                    self.assertNotIn("provider_will_be_contacted", preview)
                    self.assertEqual({name: mode["enabled"] for name, mode in preview["modes"].items()},
                                     {"mock": True, "paid": paid})
                self.assertEqual(every_file(self.intake / capture_id), saved)  # The saved bytes are unchanged.
                captured_by[paid] = capture_id
        # One capture previewed by both servers: only modes.paid differs, so offering paid sending changes nothing else.
        path = f"/api/intake/{captured_by[True]}"
        offered, not_offered = self.client.get(path).json(), disabled.get(path).json()
        self.assertEqual(offered.pop("modes")["mock"], not_offered.pop("modes")["mock"])
        self.assertEqual(offered, not_offered)
        self.assertFalse(self.attempts.exists())  # No preview reserved an attempt.
        self.assertEqual(self.provider.requests, [])

    def test_double_activation_and_concurrent_requests_make_one_transport_call(self):
        preview = self.capture()
        body = json.dumps(self.approval(preview)).encode()
        self.provider.gate = threading.Event()  # Holds the first request in flight while the others arrive.
        start, outcomes = threading.Barrier(6), []

        def run():
            start.wait()
            try:
                outcomes.append(dispatch_paid(preview["capture_id"], body, self.sender, self.intake, self.attempts,
                                              self.drafts)["mode"])
            except FlowRefused as exc:
                outcomes.append(exc.status)
                if len(outcomes) == 5:
                    self.provider.gate.set()

        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(sorted(outcomes, key=str), [409, 409, 409, 409, 409, "paid"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.send(preview).status_code, 409)  # Activating again later is refused too.
        mock = self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", headers=INTAKE,
                                content=json.dumps({"request_sha256": preview["request_sha256"],
                                                    "mock_outcome": "draft"}))
        self.assertEqual(mock.status_code, 409)  # One attempt per capture across mock and paid modes.
        mocked = self.capture("Mocked first")
        self.client.post(f"/api/intake/{mocked['capture_id']}/mock-drafts", headers=INTAKE,
                         content=json.dumps({"request_sha256": mocked["request_sha256"], "mock_outcome": "draft"}))
        self.assertEqual(self.send(mocked).status_code, 409)
        self.assertEqual(len(self.provider.requests), 1)

    def test_a_timeout_or_interruption_keeps_the_reservation_and_never_retries(self):
        timed_out = self.capture("Timed out event")
        self.provider.error = httpx.ReadTimeout("simulated timeout")
        sent = self.send(timed_out)
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(sent.json()["recorded_outcome"], "transport error")
        manifest = self.manifest(timed_out)
        self.assertEqual((manifest["http_status"], manifest["request_id"], manifest["response"],
                          manifest["estimated_cost"]), (None, None, None, None))  # Nothing is invented.
        self.assertIn("may have received and billed", manifest["adapter_message"])
        view = self.client.get(f"/api/drafts/{sent.json()['draft_id']}").json()
        self.assertEqual(view["outcome"], "technical_failure")
        self.assertIn("outcome is unknown", view["problem"])
        state = self.state(timed_out)
        self.assertEqual((state["state"], state["recorded_outcome"], state["mode"]), ("ready", "transport error", "paid"))
        self.assertEqual(self.send(timed_out).status_code, 409)
        self.assertEqual(len(self.provider.requests), 1)

        self.provider.error = None
        interrupted = self.capture("Interrupted after sending")
        with patch("second_order.paid_drafts.response_summary", side_effect=RuntimeError("process stopped")):
            failed = self.send(interrupted)
        self.assertEqual(failed.status_code, 500)
        self.assertIn("after it was sent", failed.json()["detail"])
        self.assertIn("may have received and billed", failed.json()["detail"])
        state = self.state(interrupted)
        self.assertEqual((state["state"], state["mode"], state["sent"]), ("incomplete", "paid", True))
        self.assertIn("may have received and billed", state["detail"])
        self.assertEqual(self.send(interrupted).status_code, 409)
        self.assertEqual(len(self.provider.requests), 2)

        not_sent = self.capture("Interrupted before sending")
        writes = []

        def fail_second_write(path, data, secret=None):  # The reservation is written; the request copy fails.
            writes.append(path.name)
            if len(writes) == 2:
                raise OSError("disk full")
            return keep(path, data, secret)

        from second_order.analysis_flow import keep_record as keep
        with patch("second_order.paid_drafts.keep_record", side_effect=fail_second_write):
            failed = self.send(not_sent)
        self.assertEqual(failed.status_code, 500)
        self.assertIn("before it was sent", failed.json()["detail"])
        state = self.state(not_sent)
        self.assertEqual((state["state"], state["mode"], state["sent"]), ("incomplete", "paid", False))
        self.assertEqual(self.send(not_sent).status_code, 409)
        self.assertEqual(len(self.provider.requests), 2)  # Nothing was sent for it, then or later.

    def test_a_lost_reply_is_settled_by_reads_that_never_send(self):
        preview = self.capture()
        self.assertEqual(self.send(preview).status_code, 201)  # Its reply is "lost": the page only knows it sent.
        self.provider.error = NOT_ALLOWED
        for path in (f"/api/intake/{preview['capture_id']}/attempt", f"/api/intake/{preview['capture_id']}",
                     "/api/intake", "/api/drafts"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.state(preview)["state"], "ready")
        self.assertEqual(len(self.provider.requests), 1)

    def test_a_publication_failure_is_recovered_from_unchanged_records_without_the_provider(self):
        preview = self.capture()
        with patch("second_order.draft_catalog.publish_view", side_effect=PermissionError(13, "Access is denied")):
            failed = self.send(preview)
        self.assertEqual(failed.status_code, 500)
        self.assertIn("recorded", failed.json()["detail"])
        self.assertEqual(self.state(preview)["state"], "awaiting_publication")
        attempt = self.attempts / preview["capture_id"]
        recorded = every_file(attempt)
        self.provider.error = NOT_ALLOWED
        with patch.object(socket.socket, "connect", side_effect=NOT_ALLOWED):
            body = json.dumps({"request_sha256": preview["request_sha256"]}).encode()
            from second_order.analysis_flow import publish_recorded
            recovered = publish_recorded(preview["capture_id"], body, self.intake, self.attempts, self.drafts)
        self.assertEqual((recovered["recovered"], recovered["provider_called"], recovered["mode"]),
                         (True, False, "paid"))
        self.assertEqual(every_file(attempt), recorded)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.state(preview)["state"], "ready")

    def test_credential_echoes_are_never_retained(self):
        echoes = {
            "in the reply text": (200, encoded(message(model=MODEL, stop_reason="end_turn", content=[
                {"type": "text", "text": f"Your key is {FAKE_KEY}"}]))),
            "JSON-escaped": (200, encoded(message(model=MODEL, stop_reason="end_turn", content=[
                {"type": "text", "text": "placeholder"}])).replace(b"placeholder", escaped(FAKE_KEY).encode())),
            "in an error body": (401, encoded({"type": "error", "error": {"type": "authentication_error",
                                                                          "message": f"invalid key {FAKE_KEY}"}})),
        }
        for name, (status, body) in echoes.items():
            with self.subTest(name):
                self.provider.status, self.provider.body = status, body
                preview = self.capture(f"Echo {name}")
                sent = self.send(preview)
                self.assertEqual(sent.status_code, 201, sent.text)
                self.assertEqual(sent.json()["recorded_outcome"], "credential echo")
                self.assertFalse((self.attempts / preview["capture_id"] / "response.json").exists())
                for text in (sent.text, self.client.get(f"/api/drafts/{sent.json()['draft_id']}").text,
                             self.client.get(f"/api/intake/{preview['capture_id']}/attempt").text):
                    self.assertNotIn(FAKE_KEY, text)
        self.provider.status, self.provider.body = 200, encoded(message(model=MODEL))
        self.provider.headers = {"request-id": f"req_{FAKE_KEY}"}  # An ID that carries the key is not recorded.
        preview = self.capture("Echo in the request ID")
        self.send(preview)
        self.assertIsNone(self.manifest(preview)["request_id"])
        self.assert_no_key_anywhere()

    def test_the_server_needs_an_explicit_flag_and_a_key_and_mock_stays_the_default(self):
        from second_order.__main__ import main
        self.assertIs(PaidSender.from_environment().client_factory, live_client)
        with live_client(lambda response: None) as client:
            self.assertEqual((client.follow_redirects, client.trust_env), (False, False))
        accounts = self.root / "accounts.db"  # A SYNTHETIC, empty accounts store: serve needs one to start.
        create_store(accounts)
        with patch.dict(os.environ, {}, clear=False), patch("uvicorn.run") as run, \
                patch("second_order.api.create_app") as create:
            os.environ.pop("SECOND_ORDER_ANTHROPIC_API_KEY", None)
            with patch("sys.argv", ["second_order", "serve", "--enable-paid-drafts", "--accounts", str(accounts)]), \
                    patch("sys.stderr"):
                self.assertEqual(main(), 1)
            run.assert_not_called()
            with patch("sys.argv", ["second_order", "serve", "--accounts", str(accounts)]):
                self.assertEqual(main(), 0)
            self.assertIsNone(create.call_args.kwargs["paid"])
            self.assertEqual(create.call_args.kwargs["accounts"], accounts)
            os.environ["SECOND_ORDER_ANTHROPIC_API_KEY"] = FAKE_KEY
            with patch("sys.argv", ["second_order", "serve", "--enable-paid-drafts", "--accounts", str(accounts)]):
                self.assertEqual(main(), 0)
            self.assertIsInstance(create.call_args.kwargs["paid"], PaidSender)
            os.environ.pop("SECOND_ORDER_ANTHROPIC_API_KEY", None)
        self.assertEqual(self.provider.requests, [])
        self.assertIs(paid_drafts.PaidSender, PaidSender)


if __name__ == "__main__":
    unittest.main()

"""What is kept of a provider's non-success reply: bounded, credential-checked diagnostics (provider-error-0.1).

Every reply here is SYNTHETIC: made-up messages, made-up request IDs and a made-up key. None reproduces the error of
the 2026-10-27 T-MED trial, whose message and request ID were not kept and are not reconstructed.
"""
import json
import unittest
from unittest.mock import patch

import httpx
from model_fixtures import FAKE_KEY, encoded, escaped
from second_order.model_draft import (MAX_ERROR_MESSAGE, DraftRefused, ProviderError, error_diagnostics,
                                      kept_outcome, observer, send_bytes)

SYNTHETIC_ID = "req_SYNTHETIC0000000000000001"
BODY = b'{"synthetic": "request"}'
SHA = "0" * 64


def error(kind: str = "invalid_request_error", message: str = "SYNTHETIC: a field of this request is invalid.",
          **extra) -> bytes:
    return encoded({"type": "error", "error": {"type": kind, "message": message}, **extra})


class Provider:
    """MockTransport handler: one canned reply with chosen headers; records each request."""

    def __init__(self, body: bytes, status: int = 400, headers: dict | None = None):
        self.body, self.status, self.headers, self.requests = body, status, headers or {}, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.content)
        return httpx.Response(self.status, content=self.body,
                              headers={"content-type": "application/json", **self.headers})

    def client(self, seen: dict | None = None) -> httpx.Client:
        hooks = {"response": [observer(seen, FAKE_KEY)]} if seen is not None else {}
        return httpx.Client(transport=httpx.MockTransport(self.handler), event_hooks=hooks)


def failure(provider: Provider, seen: dict | None = None) -> DraftRefused:
    try:
        with provider.client(seen) as client:
            send_bytes(client, BODY, FAKE_KEY)
    except DraftRefused as exc:
        return exc
    raise AssertionError("the reply was accepted")


class ProviderErrorTests(unittest.TestCase):
    def setUp(self):
        guard = patch("socket.socket.connect", side_effect=AssertionError("A test attempted a network connection"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_an_ordinary_error_keeps_status_type_message_and_request_id_and_its_text_is_unchanged(self):
        provider = Provider(error(), headers={"request-id": SYNTHETIC_ID, "set-cookie": "synthetic-cookie=1",
                                              "x-synthetic-header": "synthetic-header-value"})
        exc = failure(provider)
        self.assertIsInstance(exc, ProviderError)
        # The text callers record (and match on) is the one used before diagnostics existed.
        self.assertEqual(str(exc), "The model provider returned HTTP 400 (invalid_request_error); no draft was produced")
        self.assertEqual(exc.diagnostics, {
            "diagnostics_version": "provider-error-0.1", "http_status": 400, "error_type": "invalid_request_error",
            "message": "SYNTHETIC: a field of this request is invalid.", "message_truncated": False,
            "request_id": SYNTHETIC_ID, "body_bytes": len(provider.body), "body_readable": True})
        kept = json.dumps(exc.diagnostics)
        for header in ("synthetic-cookie", "synthetic-header-value", "application/json"):
            self.assertNotIn(header, kept)  # No header other than the request ID is kept.
        self.assertEqual(len(provider.requests), 1)  # One attempt; nothing is retried.

    def test_a_request_id_in_the_body_is_kept_when_the_header_is_absent(self):
        exc = failure(Provider(error(request_id=SYNTHETIC_ID), status=529))
        self.assertEqual(exc.diagnostics["request_id"], SYNTHETIC_ID)
        self.assertEqual(exc.diagnostics["http_status"], 529)

    def test_malformed_replies_keep_only_their_status_and_size(self):
        cases = {"html": b"<html>SYNTHETIC bad gateway</html>", "empty": b"",
                 "json without an error": encoded({"synthetic": True}),
                 "error is a string": encoded({"type": "error", "error": "SYNTHETIC"}),
                 "message is not text": encoded({"type": "error", "error": {"type": "api_error", "message": [1]}})}
        for name, body in cases.items():
            with self.subTest(name):
                exc = failure(Provider(body, status=502))
                self.assertIsInstance(exc, ProviderError)
                self.assertIsNone(exc.diagnostics["message"])
                self.assertEqual(exc.diagnostics["body_bytes"], len(body))
                self.assertEqual(exc.diagnostics["http_status"], 502)
                self.assertNotIn("SYNTHETIC bad gateway", json.dumps(exc.diagnostics))  # Raw bodies are never kept.

    def test_an_oversized_message_is_cut_to_the_bound(self):
        long = "SYNTHETIC: " + "x" * 20_000
        exc = failure(Provider(error(message=long)))
        message = exc.diagnostics["message"]
        self.assertTrue(exc.diagnostics["message_truncated"])
        self.assertLessEqual(len(message), MAX_ERROR_MESSAGE + 1)
        self.assertTrue(message.endswith("…") and message.startswith("SYNTHETIC: xxx"))
        self.assertLess(len(json.dumps(exc.diagnostics)), 1_000)

    def test_control_characters_and_line_breaks_are_flattened(self):
        exc = failure(Provider(error(message="SYNTHETIC:\nline two\r\n\tthree" + chr(0) + chr(27) + "[31m end")))
        self.assertEqual(exc.diagnostics["message"], "SYNTHETIC: line two three [31m end")

    def test_a_reply_carrying_the_key_is_refused_and_nothing_of_it_is_kept(self):
        cases = {"plain": error(message=f"SYNTHETIC: key {FAKE_KEY}"),
                 "escaped": ('{"type": "error", "error": {"type": "authentication_error", "message": "key %s"}}'
                             % escaped(FAKE_KEY)).encode(),
                 "in another field": error(detail=FAKE_KEY)}
        for name, body in cases.items():
            with self.subTest(name):
                seen = {}
                exc = failure(Provider(body, headers={"request-id": SYNTHETIC_ID}), seen)
                self.assertNotIsInstance(exc, ProviderError)
                self.assertIn("contained the credential", str(exc))
                self.assertNotIn(FAKE_KEY, str(exc))
                self.assertIsNone(error_diagnostics(exc, FAKE_KEY))
                outcome = kept_outcome({"outcome": "invalid"}, exc, seen, SHA, "t0", "t1", FAKE_KEY)
                self.assertNotIn("provider_error", outcome)
                self.assertNotIn(FAKE_KEY, json.dumps(outcome))

    def test_other_credential_shaped_text_is_redacted_from_a_message(self):
        other = "sk-ant-synthetic-other-key-9999999999"
        exc = failure(Provider(error(message=f"SYNTHETIC: the header {other} is not valid")))
        self.assertEqual(exc.diagnostics["message"], "SYNTHETIC: the header [redacted] is not valid")

    def test_unsafe_error_types_and_request_ids_are_not_kept(self):
        cases = {"injected header": "req_SYNTHETIC; other=1", "not a request id": "SYNTHETIC-0001",
                 "the key": FAKE_KEY, "too long": "req_" + "A" * 200}
        for name, value in cases.items():
            with self.subTest(name):
                seen = {}
                exc = failure(Provider(error(kind="Invalid Type!"), headers={"request-id": value}), seen)
                self.assertIsNone(exc.diagnostics["request_id"])
                self.assertIsNone(exc.diagnostics["error_type"])
                self.assertNotIn("request_id", seen)
                self.assertEqual(str(exc), "The model provider returned HTTP 400; no draft was produced")

    def test_the_exchange_records_fingerprint_timing_status_and_request_id(self):
        seen = {}
        exc = failure(Provider(error(), headers={"request-id": SYNTHETIC_ID}), seen)
        base = {"outcome": "provider_error", "detail": str(exc)}
        outcome = kept_outcome(base, exc, seen, SHA, "2026-10-27T01:00:00+00:00", "2026-10-27T01:00:02+00:00",
                               FAKE_KEY)
        self.assertEqual(outcome["exchange"], {"request_sha256": SHA, "sent_at": "2026-10-27T01:00:00+00:00",
                                               "answered_at": "2026-10-27T01:00:02+00:00", "http_status": 400,
                                               "request_id": SYNTHETIC_ID})
        self.assertEqual(outcome["provider_error"], exc.diagnostics)
        self.assertEqual(outcome["detail"], base["detail"])

    def test_without_any_reply_only_the_fingerprint_and_timing_are_kept(self):
        def unreachable(request):
            raise httpx.ConnectError("SYNTHETIC: refused")
        seen = {}
        with httpx.Client(transport=httpx.MockTransport(unreachable),
                          event_hooks={"response": [observer(seen, FAKE_KEY)]}) as client:
            with self.assertRaises(DraftRefused) as caught:
                send_bytes(client, BODY, FAKE_KEY)
        self.assertNotIsInstance(caught.exception, ProviderError)
        outcome = kept_outcome({"outcome": "unknown"}, caught.exception, seen, SHA, "t0", "t1", FAKE_KEY)
        self.assertEqual(outcome["exchange"]["http_status"], None)
        self.assertEqual(outcome["exchange"]["request_id"], None)
        self.assertNotIn("provider_error", outcome)

    def test_diagnostics_that_would_carry_the_key_are_dropped_whole(self):
        tainted = ProviderError("The model provider returned HTTP 400; no draft was produced",
                                {"message": f"SYNTHETIC {FAKE_KEY}"})
        self.assertIsNone(error_diagnostics(tainted, FAKE_KEY))
        base = {"outcome": "provider_error"}
        self.assertEqual(kept_outcome(base, tainted, {}, SHA, "t0", "t1", FAKE_KEY), base)
        self.assertEqual(kept_outcome(base, None, {}, f"{FAKE_KEY}", "t0", "t1", FAKE_KEY), base)


if __name__ == "__main__":
    unittest.main()

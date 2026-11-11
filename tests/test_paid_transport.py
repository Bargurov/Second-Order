"""The production client's no-retry and no-redirect guarantees, exercised through the paid send.

Every send here uses PaidSender's default client factory, draft_pilot.live_client, unchanged, with a dummy key.
Only the network beneath it is replaced: the httpcore connection pool that live_client's transport builds is
created with an in-process network backend (the one constructor intercepted), and socket connections and DNS
lookups are refused, so nothing can leave this process. The pool keeps the retry count live_client chose, and
the client keeps its redirect setting, so a regression in that factory changes what these tests observe.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpcore

from second_order.api import create_app
from second_order.draft_pilot import live_client
from second_order.paid_drafts import PaidSender

BASE = "http://127.0.0.1:8135"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
DUMMY_KEY = "sk-ant-dummy-transport-test-key-0000"
PROVIDER = ("api.anthropic.com", 443)
REQUEST_HEAD = re.compile(rb"[A-Z]+ \S+ HTTP/1\.1\r\n")


def redirect(location: str) -> bytes:
    return (b"HTTP/1.1 307 Temporary Redirect\r\nLocation: " + location.encode() +
            b"\r\nrequest-id: req_redirect0001\r\nContent-Length: 0\r\n\r\n")


class Connection(httpcore.NetworkStream):
    """One in-process connection: keeps every byte written to it and replays one canned reply."""

    def __init__(self, reply: bytes):
        self.written, self.requests, self._reply = bytearray(), 0, [reply]

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._reply.pop(0) if self._reply else b""

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.requests += bool(REQUEST_HEAD.match(buffer))  # A request line starts each request sent.
        self.written += buffer

    def close(self) -> None:
        pass

    def start_tls(self, ssl_context, server_hostname: str | None = None, timeout: float | None = None):
        return self  # The in-process peer needs no TLS.

    def get_extra_info(self, info: str):
        return None


class Network(httpcore.NetworkBackend):
    """Records every connection attempt; refuses them all (reply None) or answers each with ``reply``."""

    def __init__(self, reply: bytes | None):
        self.reply, self.attempts, self.connections, self.waits = reply, [], [], []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.attempts.append((host, port))
        if self.reply is None:
            raise httpcore.ConnectError("simulated: the connection was refused")
        connection = Connection(self.reply)
        self.connections.append(((host, port), connection))
        return connection

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)  # httpcore waits here before each connection retry.


@contextmanager
def production_client_over(network: Network):
    """live_client as shipped, its connection pool built on ``network``; yields the pool options it chose."""
    chosen, real_pool = [], httpcore.ConnectionPool

    def pool(**options):
        chosen.append(options)
        return real_pool(**options, network_backend=network)

    blocked = AssertionError("a test tried to reach the real network")
    with patch("httpcore.ConnectionPool", pool), patch("socket.create_connection", side_effect=blocked), \
            patch("socket.getaddrinfo", side_effect=blocked):
        yield chosen


class ProductionTransportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.intake, self.attempts = root / "intake", root / "attempts"
        sender = PaidSender(api_key=lambda: DUMMY_KEY)
        self.assertIs(sender.client_factory, live_client)  # The factory `serve --enable-paid-drafts` uses.
        self.client = TestClient(create_app(root / "no-dossiers", None, root / "prepared-drafts", root / "reviews",
                                            self.intake, self.attempts, paid=sender), base_url=BASE)
        self.addCleanup(self.client.close)

    def capture(self, headline: str) -> dict:
        form = {"headline": headline, "source_url": "https://example.com/published-statement",
                "published_at": "2026-09-15T14:00:00-04:00", "source_text": "Synthetic text for a transport test."}
        response = self.client.post("/api/intake", content=json.dumps(form), headers=INTAKE)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def send(self, preview: dict):
        approval = {"request_sha256": preview["request_sha256"], "approve_paid_request": True,
                    "estimated_max_usd": preview["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"]}
        return self.client.post(f"/api/intake/{preview['capture_id']}/paid-drafts", headers=INTAKE,
                                content=json.dumps(approval))

    def mock(self, preview: dict):
        return self.client.post(f"/api/intake/{preview['capture_id']}/mock-drafts", headers=INTAKE,
                                content=json.dumps({"request_sha256": preview["request_sha256"],
                                                    "mock_outcome": "draft"}))

    def manifest(self, preview: dict) -> dict:
        return json.loads((self.attempts / preview["capture_id"] / "manifest.json").read_text(encoding="utf-8"))

    def assert_reviewable_and_blocked(self, preview: dict, sent, network: Network) -> dict:
        """The recorded failure opens for review, and neither mode can dispatch this capture again."""
        attempts = list(network.attempts)
        with production_client_over(network):
            self.assertEqual(self.send(preview).status_code, 409)
            self.assertEqual(self.mock(preview).status_code, 409)
        self.assertEqual(network.attempts, attempts)  # Refused before any connection.
        state = self.client.get(f"/api/intake/{preview['capture_id']}/attempt").json()
        self.assertEqual((state["state"], state["mode"]), ("ready", "paid"))
        view = self.client.get(f"/api/drafts/{sent.json()['draft_id']}")
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view.json()["outcome"], "technical_failure")
        return view.json()

    def test_the_production_transport_has_zero_retries_so_a_failed_connection_is_tried_once(self):
        network = Network(reply=None)
        preview = self.capture("Connection refused event")
        with production_client_over(network) as pools:
            sent = self.send(preview)
        self.assertEqual(network.attempts, [PROVIDER])  # One attempt, no retry...
        self.assertEqual(network.waits, [])  # ...and no wait before one...
        self.assertEqual([options["retries"] for options in pools], [0])  # ...because live_client sets zero.
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(sent.json()["recorded_outcome"], "transport error")
        manifest = self.manifest(preview)
        self.assertEqual((manifest["attempts"], manifest["retries"], manifest["http_status"]), (1, 0, None))
        self.assertIn("may have received and billed", manifest["adapter_message"])
        view = self.assert_reviewable_and_blocked(preview, sent, network)
        self.assertIn("outcome is unknown", view["problem"])

    def test_a_307_is_not_followed_to_the_same_or_another_host_and_is_recorded_as_a_provider_failure(self):
        for target in ("https://elsewhere.example/v1/messages", "https://api.anthropic.com/v1/elsewhere"):
            with self.subTest(target=target):
                network = Network(reply=redirect(target))
                preview = self.capture(f"Redirected to {target}")
                saved = (self.intake / preview["capture_id"] / "request.json").read_bytes()
                with production_client_over(network):
                    sent = self.send(preview)
                # One connection, to the provider: the redirect target was never contacted, so it received
                # neither a request nor the key.
                self.assertEqual([address for address, _ in network.connections], [PROVIDER])
                connection = network.connections[0][1]
                self.assertEqual(connection.requests, 1)  # Nor was the redirect followed on this connection.
                self.assertTrue(connection.written.startswith(b"POST /v1/messages HTTP/1.1\r\n"))
                self.assertTrue(connection.written.endswith(saved))  # The saved bytes, sent once.
                self.assertEqual(connection.written.count(DUMMY_KEY.encode()), 1)  # The key went only here.

                self.assertEqual(sent.status_code, 201, sent.text)
                self.assertEqual(sent.json()["recorded_outcome"], "provider error")
                manifest = self.manifest(preview)
                self.assertEqual((manifest["http_status"], manifest["request_id"], manifest["response"]),
                                 (307, "req_redirect0001", None))
                self.assertIn("HTTP 307", manifest["adapter_message"])
                view = self.assert_reviewable_and_blocked(preview, sent, network)
                self.assertIn("HTTP 307", view["problem"])
                self.assertEqual(len(network.connections), 1)


if __name__ == "__main__":
    unittest.main()

"""Live drafting pilot, verified on mocked transports only: no request leaves the process.

These tests check the contract (explicit Sonnet model, exact bytes, atomic one-time reservation, no retry,
credential-echo protection, provenance), not the quality of any reasoning. Responses are synthetic.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import httpx
from model_fixtures import (FAKE_KEY, THINKING, FakeAnthropic, encoded, escaped, message, tool_call,
                            valid_output)
from second_order import model_draft
from second_order.draft_pilot import (CASES, KEY_VARIABLE, MODEL, PILOT_DIR, PILOT_ID, PILOT_PROMPT_VERSION, main, plan,
                                      preview, send_case, state, status)

ROOT = Path(__file__).resolve().parent.parent
CLOCK = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # After every synthetic case was published.
REQUEST_ID = "req_011SyntheticPilot0001"
CASE = "conflicting-labor-inflation"  # The pilot-4 case most tests send.
# The CLI runs in a child process whose sockets refuse to connect, so any network attempt fails loudly.
NO_NETWORK = ("import runpy, socket, sys\n"
              "def blocked(*args, **kwargs): raise SystemExit('network attempted')\n"
              "socket.socket.connect = blocked\n"
              "sys.argv = ['draft_pilot'] + sys.argv[1:]\n"
              "runpy.run_module('second_order.draft_pilot', run_name='__main__', alter_sys=True)\n")


def sonnet(output: dict | None = None, **overrides) -> bytes:
    """A Claude Sonnet 5.5-shaped reply: an omitted-display thinking block, then the call."""
    return encoded(message(output, model=MODEL, **overrides))


class FakeProvider(FakeAnthropic):
    """Records each request and answers once, with a request ID header; it can also wait or fail."""

    def __init__(self, body: bytes | None = None, status: int = 200, raise_error: BaseException | None = None,
                 request_id: str = REQUEST_ID, delay: float = 0.0, during=None):
        super().__init__(sonnet() if body is None else body, status, raise_error)
        self.request_id, self.delay, self.during = request_id, delay, during

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        time.sleep(self.delay)
        if self.during is not None:
            self.during()  # Something that happens while the request is in flight.
        if self.raise_error is not None:
            raise self.raise_error
        return httpx.Response(self.status, content=self.body,
                              headers={"content-type": "application/json", "request-id": self.request_id})

    def factory(self, observe) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), event_hooks={"response": [observe]})


def never(observe) -> httpx.Client:
    raise AssertionError("A client was created")


def pilot_files() -> dict[str, str]:
    """SHA-256 of every file under data/pilot: the CLI checks must leave every run's records as they were."""
    return {str(path.relative_to(PILOT_DIR.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(PILOT_DIR.parent.rglob("*")) if path.is_file()}


class DraftPilotTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "sqlite3.connect"):
            guard = patch(target, side_effect=AssertionError(f"The pilot called {target}"))
            guard.start()
            self.addCleanup(guard.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "pilot"
        self.hashes = {case: plan(case, lambda: CLOCK)[3] for case in CASES}

    def send(self, fake: FakeProvider, case: str = CASE, key: str = FAKE_KEY) -> dict:
        return send_case(case, key, self.hashes[case], self.root, fake.factory, lambda: CLOCK)

    def files(self, case: str = CASE) -> dict[str, bytes]:
        folder = self.root / case
        return {path.name: path.read_bytes() for path in folder.iterdir()} if folder.exists() else {}

    def assert_key_absent(self) -> None:
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertFalse(model_draft.exposes(path.read_bytes(), FAKE_KEY), path.name)

    def test_the_pilot_names_sonnet_explicitly_and_leaves_the_adapter_default(self):
        self.assertEqual((MODEL, CASES), ("claude-sonnet-5-5", ("conflicting-labor-inflation", "ambiguous-wording",
                                                                "headline-reports-move")))
        self.assertEqual(model_draft.DEFAULT_MODEL, "claude-opus-5-5")
        for other in ("clear-policy", "insufficient-source", "no-connection", "prompt-injection",
                      "unsupported-observables"):  # Not part of pilot-4.
            with self.assertRaisesRegex(ValueError, "covers only conflicting-labor-inflation, ambiguous-wording, "
                                                    "headline-reports-move"):
                plan(other, lambda: CLOCK)

    def test_pilot_4_is_a_separate_run_bound_to_draft_prompt_5(self):
        self.assertEqual((PILOT_ID, PILOT_PROMPT_VERSION), ("pilot-4-claude-sonnet-5-5", "draft-prompt-5"))
        self.assertEqual(PILOT_PROMPT_VERSION, model_draft.PROMPT_VERSION)
        self.assertEqual((PILOT_DIR.name, PILOT_DIR.parent), (PILOT_ID, ROOT / "data" / "pilot"))  # Own directory,
        self.assertNotIn(PILOT_DIR.name, ("pilot-1-claude-sonnet-5-5", "pilot-2-claude-sonnet-5-5",
                                          "pilot-3-claude-sonnet-5-5"))  # Never an earlier run's.
        self.assertEqual(preview(CASE, self.root, lambda: CLOCK)["pilot"], PILOT_ID)
        with patch("second_order.draft_pilot.PROMPT_VERSION", "draft-prompt-6"):  # A later prompt edit...
            for attempt in (lambda: preview(CASE, self.root, lambda: CLOCK),
                            lambda: send_case(CASE, FAKE_KEY, self.hashes[CASE], self.root,
                                              never, lambda: CLOCK)):
                with self.assertRaisesRegex(ValueError, "bound to draft-prompt-5, but the adapter now builds "
                                                        "draft-prompt-6"):
                    attempt()  # ...cannot go out under this run's name.
        self.assertFalse(self.root.exists())

    def test_the_request_follows_the_documented_sonnet_contract(self):
        _, request, body, prompt_hash = plan(CASE, lambda: CLOCK)
        self.assertEqual(json.loads(body), request)
        self.assertEqual(prompt_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual((request["model"], request["max_tokens"], request["output_config"], request["tool_choice"]),
                         (MODEL, 16_000, {"effort": "medium"}, {"type": "auto"}))  # Medium set explicitly.
        self.assertEqual([(tool["name"], tool["strict"]) for tool in request["tools"]],
                         [(model_draft.TOOL_NAME, True)])
        # Each of these returns a 400 on Claude Sonnet 5.5 (or, for thinking, would change its default).
        for absent in ("thinking", "temperature", "top_p", "top_k", "fallbacks", "stream"):
            self.assertNotIn(absent, request)
        self.assertIn("Declining is an acceptable outcome", request["system"])  # Conditional drafting.
        self.assertEqual(request["messages"][-1]["role"], "user")  # No assistant prefill.

    def test_preview_shows_the_exact_request_and_writes_nothing(self):
        result = preview("ambiguous-wording", self.root, lambda: CLOCK)
        self.assertEqual(result["prompt_hash"], self.hashes["ambiguous-wording"])
        self.assertEqual(result["reservation"]["state"], "unreserved")
        self.assertIn(f"--confirm-prompt-hash {result['prompt_hash']}", result["send_command"])
        self.assertIn("not a guaranteed ceiling", result["cost_estimate"]["caveat"])
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        self.assertFalse(self.root.exists())
        with redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(main(["preview", CASE], self.root, never, {KEY_VARIABLE: FAKE_KEY},
                                  lambda: CLOCK), 0)
        self.assertEqual(json.loads(printed.getvalue())["prompt_hash"], self.hashes[CASE])
        self.assertFalse(self.root.exists())

    def test_nothing_is_reserved_or_sent_without_the_key_the_hash_and_a_clean_key(self):
        cases = {"no key": ("", self.hashes[CASE], "is not set"),
                 "another request's hash": (FAKE_KEY, self.hashes["ambiguous-wording"], "must equal the hash"),
                 "malformed hash": (FAKE_KEY, "abc", "must equal the hash"),
                 "key with a trailing space": (FAKE_KEY + " ", self.hashes[CASE], "whitespace"),
                 "key found in the request": (f"example.com/synthetic/{CASE}", self.hashes[CASE],
                                              "would carry the credential")}
        for name, (key, confirmed, pattern) in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, pattern):
                    send_case(CASE, key, confirmed, self.root, never, lambda: CLOCK)
                self.assertFalse((self.root / CASE).exists())

    def test_a_draft_is_kept_byte_for_byte_with_its_provenance(self):
        fake = FakeProvider()
        result = self.send(fake)
        kept = self.files()
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(kept["request.json"], fake.requests[0].content)  # Exactly the bytes sent.
        self.assertEqual(kept["response.json"], fake.body)  # Exactly the bytes received.
        self.assertEqual(sorted(kept), ["attempt.json", "draft.json", "manifest.json", "request.json",
                                        "reservation.json", "response.json"])
        manifest = json.loads(kept["manifest.json"])
        self.assertEqual(manifest, {key: result[key] for key in manifest})
        self.assertEqual((manifest["outcome"], manifest["model"], manifest["http_status"], manifest["request_id"]),
                         ("draft", MODEL, 200, REQUEST_ID))
        self.assertEqual(manifest["prompt_hash"], hashlib.sha256(kept["request.json"]).hexdigest())
        self.assertEqual(manifest["response"]["sha256"], hashlib.sha256(kept["response.json"]).hexdigest())
        self.assertEqual(manifest["response"]["usage"], {"input_tokens": 1200, "output_tokens": 600})
        self.assertEqual(manifest["estimated_cost"]["usd"], round((1200 * 2 + 600 * 10) / 1_000_000, 6))
        self.assertEqual((manifest["attempts"], manifest["retries"], manifest["fallbacks"]), (1, 0, None))
        self.assertIn("model_draft.py", " ".join(manifest["code"]["sha256"]))
        draft = json.loads(kept["draft.json"])
        self.assertEqual(draft["draft"]["engine"], {"provider": "anthropic", "model": MODEL,
                                                    "prompt_hash": manifest["prompt_hash"], "schema_version": "0.2"})
        self.assertEqual(draft["review"]["engine"]["response_origin"], "sent in this process")
        self.assertNotIn("frozen_at", draft["draft"])
        self.assert_key_absent()

    def test_a_decline_or_refusal_is_kept_as_no_draft(self):
        decline = {"type": "text", "text": "No hypothesis: the source reports only that a meeting ended."}
        cases = {"ambiguous-wording": (sonnet(content=[THINKING, decline], stop_reason="end_turn"),
                                         "without calling the draft tool"),
                 CASE: (sonnet(content=[THINKING], stop_reason="refusal",
                                         stop_details={"category": "general_harms"}),
                                  r"declined to draft \(category general_harms\)")}
        for case, (body, pattern) in cases.items():
            with self.subTest(case):
                fake = FakeProvider(body)
                result = self.send(fake, case)
                self.assertEqual((result["outcome"], len(fake.requests)), ("no draft", 1))
                self.assertRegex(result["adapter_message"], pattern)
                self.assertEqual(self.files(case)["response.json"], body)  # The decline text is kept verbatim.
                self.assertNotIn("draft.json", self.files(case))

    def test_invalid_responses_are_kept_and_refused_without_repair(self):
        prose = {"type": "text", "text": "Here is my draft."}
        unoffered = valid_output()
        unoffered["legs"][1]["observable_id"] = "index:dxy"
        cases = {"the adapter's default model answered": (encoded(message()), "not the requested"),
                 "text beside the call": (sonnet(content=[THINKING, prose, tool_call()]), "Unexpected text"),
                 "unoffered observable": (sonnet(unoffered), "not offered: index:dxy"),
                 "truncated": (sonnet(stop_reason="max_tokens"), "truncated at max_tokens")}
        for name, (body, pattern) in cases.items():
            with self.subTest(name):
                case_root = self.root / name.replace(" ", "-").replace("'", "")
                fake = FakeProvider(body)
                result = send_case(CASE, FAKE_KEY, self.hashes[CASE], case_root, fake.factory,
                                   lambda: CLOCK)
                self.assertEqual((result["outcome"], len(fake.requests)), ("refused", 1))
                self.assertRegex(result["adapter_message"], pattern)
                self.assertEqual((case_root / CASE / "response.json").read_bytes(), body)

    def test_failures_are_recorded_once_and_leave_the_case_reserved(self):
        overloaded = encoded({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        cases = {"provider error": (FakeProvider(overloaded, status=529), r"HTTP 529 \(overloaded_error\)"),
                 "transport error": (FakeProvider(raise_error=httpx.ReadTimeout("timed out")), "ReadTimeout")}
        for outcome, (fake, pattern) in cases.items():
            with self.subTest(outcome):
                case_root = self.root / outcome.replace(" ", "-")
                result = send_case(CASE, FAKE_KEY, self.hashes[CASE], case_root, fake.factory,
                                   lambda: CLOCK)
                self.assertEqual(result["outcome"], outcome)
                self.assertRegex(result["adapter_message"], pattern)
                self.assertNotIn("response.json", result["files"])
                again = FakeProvider()
                with self.assertRaisesRegex(ValueError, "already reserved .*completed"):
                    send_case(CASE, FAKE_KEY, self.hashes[CASE], case_root, again.factory,
                              lambda: CLOCK)
                self.assertEqual((len(fake.requests), len(again.requests)), (1, 0))  # No retry, no second send.
        self.assertIn("may still have been processed and billed", result["outcome_note"])

    def test_the_code_identity_is_captured_before_sending_and_survives_a_change_or_crash(self):
        reported = {"git_head": "a" * 40, "uncommitted_changes": False, "sha256": {"second_order/draft_pilot.py": "1"}}
        before = json.loads(json.dumps(reported))

        def code_changes():  # The working tree moves to another revision while the request waits.
            reported.update(git_head="b" * 40, uncommitted_changes=True, sha256={"second_order/draft_pilot.py": "2"})

        cases = {CASE: FakeProvider(during=code_changes),
                 "ambiguous-wording": FakeProvider(during=code_changes, raise_error=KeyboardInterrupt())}
        for case, fake in cases.items():
            with self.subTest(case), patch("second_order.draft_pilot.code_identity",
                                           side_effect=lambda: json.loads(json.dumps(reported))) as identity:
                reported.update(json.loads(json.dumps(before)))
                if fake.raise_error is None:
                    self.assertEqual(self.send(fake, case)["code"], before)
                    self.assertEqual(json.loads(self.files(case)["manifest.json"])["code"], before)
                else:
                    with self.assertRaises(KeyboardInterrupt):  # A crash mid-request: no manifest is written.
                        self.send(fake, case)
                    self.assertNotIn("manifest.json", self.files(case))
                self.assertEqual(json.loads(self.files(case)["reservation.json"])["code"], before)
                self.assertEqual(reported["git_head"], "b" * 40)  # The identity did change during the request.
                self.assertEqual(identity.call_count, 1)  # Captured once, before sending.

    def test_a_crash_after_sending_keeps_the_case_reserved_as_unknown(self):
        crashing = FakeProvider(raise_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.send(crashing)
        self.assertEqual(state(self.root / CASE)["state"], "sent, outcome unknown")
        self.assertEqual(sorted(self.files()), ["attempt.json", "request.json", "reservation.json"])
        later = FakeProvider()
        with self.assertRaisesRegex(ValueError, "already reserved \\(sent, outcome unknown\\)"):
            self.send(later)
        self.assertEqual((len(crashing.requests), len(later.requests)), (1, 0))

    def test_a_reservation_made_elsewhere_blocks_the_send(self):
        (self.root / "ambiguous-wording").mkdir(parents=True)  # Another process reserved it, then stopped.
        self.assertEqual({case: shown["state"] for case, shown in status(self.root)["cases"].items()},
                         {**{case: "unreserved" for case in CASES}, "ambiguous-wording": "reserved, not sent"})
        self.assertEqual(state(self.root / "ambiguous-wording")["state"], "reserved, not sent")
        fake = FakeProvider()
        with self.assertRaisesRegex(ValueError, "already reserved"):
            self.send(fake, "ambiguous-wording")
        self.assertEqual(fake.requests, [])

    def test_concurrent_attempts_send_once(self):
        fake = FakeProvider(delay=0.3)
        outcomes, start = [], threading.Barrier(2)

        def attempt():
            start.wait()
            try:
                outcomes.append(self.send(fake)["outcome"])
            except ValueError as exc:
                outcomes.append(str(exc))

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(outcomes.count("draft"), 1)
        self.assertEqual(len([text for text in outcomes if "already reserved" in text]), 1)

    def test_a_credential_echo_keeps_nothing_from_the_response(self):
        error = '{"type": "error", "error": {"type": "api_error", "message": "key %s"}}' % escaped(FAKE_KEY)
        cases = {"echo in the body": FakeProvider(sonnet(id=FAKE_KEY)),
                 "escaped echo in an error": FakeProvider(error.encode(), status=500)}
        for name, fake in cases.items():
            with self.subTest(name):
                case_root = self.root / name.replace(" ", "-")
                result = send_case(CASE, FAKE_KEY, self.hashes[CASE], case_root, fake.factory,
                                   lambda: CLOCK)
                self.assertEqual(result["outcome"], "credential echo")
                self.assertNotIn("response.json", result["files"])
        leaky = FakeProvider(request_id="req_" + FAKE_KEY)
        self.assertIsNone(send_case("ambiguous-wording", FAKE_KEY, self.hashes["ambiguous-wording"], self.root,
                                    leaky.factory, lambda: CLOCK)["request_id"])
        self.assert_key_absent()


class DraftPilotCliTests(unittest.TestCase):
    def run_pilot(self, *arguments: str, key: str | None = None) -> subprocess.CompletedProcess:
        env = {name: value for name, value in os.environ.items() if name != KEY_VARIABLE}
        if key is not None:
            env[KEY_VARIABLE] = key
        return subprocess.run([sys.executable, "-c", NO_NETWORK, *arguments], cwd=ROOT, text=True,
                              capture_output=True, encoding="utf-8", timeout=60, env=env)

    def test_preview_status_and_refusals_run_offline_and_reserve_nothing(self):
        before = pilot_files()  # Every run: pilot-1 to pilot-3 and the archive.
        preview_run = self.run_pilot("preview", CASE)
        self.assertEqual(preview_run.returncode, 0, preview_run.stderr)
        self.assertTrue(preview_run.stdout.isascii())
        printed = json.loads(preview_run.stdout)
        self.assertEqual((printed["model"], printed["effort"], printed["max_tokens"]), (MODEL, "medium", 16_000))
        self.assertEqual(printed["prompt_hash"], hashlib.sha256(
            json.dumps(printed["request"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
        status_run = self.run_pilot("status")
        self.assertEqual((status_run.returncode, sorted(json.loads(status_run.stdout)["cases"])), (0, sorted(CASES)))
        for arguments, key, pattern in (
                (("send", CASE, "--confirm-prompt-hash", printed["prompt_hash"]), None, "is not set"),
                (("send", CASE, "--confirm-prompt-hash", "0" * 64), FAKE_KEY, "must equal the hash")):
            with self.subTest(pattern):
                run = self.run_pilot(*arguments, key=key)
                self.assertEqual((run.returncode, run.stdout), (1, ""))
                self.assertIn(pattern, run.stderr)
                self.assertNotIn(FAKE_KEY, run.stderr)
        other = self.run_pilot("preview", "clear-policy")
        self.assertEqual(other.returncode, 2)  # Only this run's six cases are accepted.
        self.assertEqual(pilot_files(), before)


if __name__ == "__main__":
    unittest.main()

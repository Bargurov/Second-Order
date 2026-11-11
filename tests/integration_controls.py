"""Test-only controls for the joint Admin/Client browser check (frontend/tests/browser/admin-client-integration-check.mjs).

Not a test module and not part of the application. tests/review_browser_server.py installs these only when it is started
with ``--controls PORT`` together with ``--accounts synthetic --simulated-provider``. The controls answer on their own
HTTP server at 127.0.0.1:PORT, apart from the application's port, so no application route reaches them and the
application's identity, role and origin checks are untouched. They change only test fakes inside the launcher's process:

- the accounts clock (sessions, quotes, quota days and attempt ages): an instant that advances with real time, or stays
  frozen, and that the check sets or moves forward;
- three gates, each holding every call that reaches it while it is held: ``after_reserve`` (a user's run, after its
  reservation is committed and before its worker takes the attempt's execution lock), ``before_send`` (with the lock held,
  before the send is recorded as started) and ``provider`` (inside the fake provider, after it recorded the request it
  received and before it answers);
- a read of the clock, the gates (held, waiting, passed) and the number of requests the fake provider received.

Nothing here reads a key or an environment credential, or reaches the network.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time


class Clock:
    """The accounts clock: ``start``, advancing with real time unless frozen."""

    def __init__(self, start: datetime):
        self._lock = threading.Lock()
        self._base, self._mark, self._frozen = start, time.monotonic(), False

    def __call__(self) -> datetime:
        with self._lock:
            return self._base if self._frozen else self._base + timedelta(seconds=time.monotonic() - self._mark)

    def set(self, instant: datetime, frozen: bool) -> None:
        if instant.tzinfo is None:
            raise ValueError("the clock needs an instant with an offset")
        with self._lock:
            self._base, self._mark, self._frozen = instant.astimezone(timezone.utc), time.monotonic(), frozen

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._base += timedelta(seconds=seconds)


class Gate:
    """Holds every caller of ``wait`` while held; releasing lets them all continue."""

    def __init__(self):
        self._condition = threading.Condition()
        self.held, self.waiting, self.passed = False, 0, 0

    def wait(self) -> None:
        with self._condition:
            self.waiting += 1
            try:
                while self.held:
                    self._condition.wait()
            finally:
                self.waiting -= 1
            self.passed += 1

    def hold(self, held: bool) -> None:
        with self._condition:
            self.held = held
            self._condition.notify_all()

    def state(self) -> dict:
        with self._condition:
            return {"held": self.held, "waiting": self.waiting, "passed": self.passed}


class Controls:
    def __init__(self, start: datetime, provider_record: Path):
        self.clock = Clock(start)
        self.gates = {"after_reserve": Gate(), "before_send": Gate(), "provider": Gate()}
        self.provider_record = provider_record

    def state(self) -> dict:
        return {"now": self.clock().isoformat(), "gates": {name: gate.state() for name, gate in self.gates.items()},
                "provider_requests": len(list(self.provider_record.glob("request-*.json")))}


def install(start: datetime, provider_record: Path) -> Controls:
    """Wrap the two points of a user's run that the gates hold. The wrappers call the application's own functions
    unchanged; only the waiting is added."""
    from second_order import entitlements
    controls = Controls(start, provider_record)
    reserve, mark_sent = entitlements.reserve, entitlements.mark_sent

    def held_reserve(*args, **kwargs):
        attempt, duplicate = reserve(*args, **kwargs)
        if not duplicate:
            controls.gates["after_reserve"].wait()
        return attempt, duplicate

    def held_mark_sent(*args, **kwargs):
        controls.gates["before_send"].wait()
        return mark_sent(*args, **kwargs)

    entitlements.reserve, entitlements.mark_sent = held_reserve, held_mark_sent
    return controls


def serve(controls: Controls, port: int) -> None:
    """The control server, on loopback only, in a daemon thread."""

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/state":
                return self.reply(404, {"problem": "unknown control"})
            self.reply(200, controls.state())

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/clock":
                    if "set" in body:
                        controls.clock.set(datetime.fromisoformat(body["set"]), bool(body.get("frozen")))
                    if "advance_seconds" in body:
                        controls.clock.advance(float(body["advance_seconds"]))
                elif self.path.startswith("/gates/") and self.path[len("/gates/"):] in controls.gates:
                    controls.gates[self.path[len("/gates/"):]].hold(bool(body["hold"]))
                else:
                    return self.reply(404, {"problem": "unknown control"})
            except (KeyError, TypeError, ValueError) as exc:
                return self.reply(422, {"problem": str(exc)})
            self.reply(200, controls.state())

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

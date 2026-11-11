"""SYNTHETIC accounts, credit policy and provider for the accounts tests and the admin browser check.

Not a test module. Everything is written in a temporary folder: an accounts store with one administrator and two users
(passwords are synthetic test strings), a synthetic credit policy, grants and daily limits chosen for the tests (not
production values), and a fake of the Claude API (an httpx MockTransport) that answers each research request with a
SYNTHETIC reply quoting the request's own source text. Nothing can reach the network and no real key is used.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
import threading
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from model_fixtures import FAKE_KEY, THINKING, encoded
from second_order import accounts as acc, entitlements, research_analysis as ra, usage
from second_order.api import create_app
from second_order.paid_drafts import PaidSender

BASE = "http://127.0.0.1:8151"
PASSWORDS = {"admin": "synthetic-admin-pass", "reader-a": "synthetic-reader-a", "reader-b": "synthetic-reader-b"}
SESSION_WRITE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Session": "1"}
USER_WRITE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-User": "1"}
ADMIN_WRITE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Admin": "1"}
ACCOUNT = "X-Second-Order-Account"  # The account a page was opened for (docs/account-binding-contract.md).
# SYNTHETIC test terms, not production values: a small policy so the arithmetic is easy to check.
POLICY = {"model": ra.MODEL, "efforts": {"low": {"extra_credits": 0}, "medium": {"extra_credits": 1},
                                          "high": {"extra_credits": 2}},
          "credits": {"base": 1, "per_1k_input_tokens": 1, "per_1k_output_tokens": 0},
          "max_request_usd": 5.0, "quote_valid_seconds": 900}
# SYNTHETIC usage limits for tests and browser checks, set high enough that only the tests about limits reach them;
# not production values (docs/news-usage-contract.md: the administrator types the real ones).
USAGE_POLICY = {"account": {"searches_per_day": 50, "imports_per_day": 10, "sources_per_day": 60,
                            "preparations_per_day": 60, "max_sources": 500, "max_source_bytes": 60_000_000,
                            "requests_per_minute": 600, "concurrent_requests": 16},
                "server": {"publication_fetches_per_day": 20, "refreshes_per_day": 20, "refresh_cooldown_seconds": 0}}
START = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)  # Noon in Jerusalem (IDT, UTC+3).
SOURCE = ("October 13, 2026\n\nSimulated statistics office publishes its quarterly survey\n\n"
          "The Simulated Statistics Office reported that output in the surveyed sector rose 1.2 percent in the third "
          "quarter, after a 0.4 percent decline in the second quarter.\n\n"
          "The office said it expects to revise the estimate when late responses arrive.\n\n"
          "SYNTHETIC TEST SOURCE written for the accounts tests.")


def source_form(headline: str = "Simulated statistics office publishes its quarterly survey",
                text: str = SOURCE) -> dict:
    return {"headline": headline, "source_url": "https://example.org/synthetic/survey",
            "published_at": "2026-10-13T10:00:00+03:00", "source_text": text}


GO_DEEPER = "Material for a deeper analysis of a news story, assembled by Second Order"
FRAMING_LINE = re.compile(r"(Report \d+ of \d+|Publisher:|Published \(|Address:|Headline:|Excerpt:|Text of the "
                          r"publication|Credit:|Story:|What this is:|The shared brief|Left out:|Evidence:|\[Shortened)")


def deeper_passages(source: str) -> list[str]:
    """The passages a careful reader quotes from a Go deeper source: its excerpts and the paragraphs of publication
    text that carry no framing line. Any other source: its paragraphs of 40 characters or more."""
    if not source.startswith(GO_DEEPER):
        return [part.strip() for part in source.split("\n\n") if len(part.strip()) >= 40]
    excerpts = [line[len("Excerpt: "):] for line in source.splitlines() if line.startswith("Excerpt: ")]
    texts = [part.strip() for part in source.split("\n\n")
             if not any(FRAMING_LINE.match(line) for line in part.splitlines()) and len(part.strip()) >= 40]
    return [passage for passage in texts + excerpts if len(passage) >= 40]


def research_reply(request_body: bytes, outcome: str = "analysis") -> bytes:
    """A SYNTHETIC reply quoting the request's own source text, in the shape of the Messages API: its publishers'
    passages (deeper_passages). ``framing`` quotes a Go deeper source's opening lines instead, as a careless reply
    would. A request with a tool (research-prompt-1) gets the analysis as the tool's input; one without
    (research-prompt-2) gets it as the response's text, and a decline as a refusal."""
    request = json.loads(request_body)
    content = request["messages"][0]["content"]
    source = content.split("<source_text>\n", 1)[1].rsplit("\n</source_text>", 1)[0]
    passages = [passage[:120].rstrip() for passage in deeper_passages(source)][:2]
    if outcome == "framing":
        passages = [source.split("\n\n", 1)[0][:120].rstrip()]
    if outcome == "invalid":
        passages = ["A synthetic passage that the source text does not contain."]
    tool = "tools" in request
    analysis = {
        "established": [{"statement": f"Synthetic statement {number}.", "basis": "data", "quotes": [passage]}
                        for number, passage in enumerate(passages, start=1)],
        "interpretation": {"kind": "no_additional_finding", "based_on": [],
                           "text": "Synthetic: nothing beyond what the source states."}
        if outcome == "no_additional_finding" else
        {"kind": "finding", "based_on": [1], "text": "Synthetic interpretation of statement 1."},
        "assumptions": ["Synthetic assumption."],
        "competing_explanations": [{"explanation": "Synthetic reading.", "would_distinguish": "Synthetic check."}],
        "missing_information": ["Synthetic missing information."],
        "tests": [{"check": "Synthetic test.", "counts_against_if": "Synthetic counter-observation."}]}
    if outcome == "declined":
        reply_content = [{"type": "text", "text": "SYNTHETIC decline: the source cannot support an analysis."}]
        stop = "end_turn" if tool else "refusal"
    elif tool:
        reply_content = [dict(THINKING), {"type": "tool_use", "id": "toolu_synthetic_account", "name": ra.TOOL_NAME,
                                          "input": analysis}]
        stop = "tool_use"
    else:
        reply_content = [dict(THINKING), {"type": "text", "text": json.dumps(analysis)}]
        stop = "end_turn"
    return encoded({"id": "msg_synthetic_account", "type": "message", "role": "assistant", "model": request["model"],
                    "content": reply_content, "stop_reason": stop, "stop_sequence": None,
                    "usage": {"input_tokens": 2100, "output_tokens": 700}})


class ProviderFake:
    """Answers each request by its own body; records every request; can hold a request open, fail or time out."""

    def __init__(self):
        self.requests: list[bytes] = []
        self.headers: list[dict] = []  # Each request's header names and protocol headers; never a key's value.
        self.outcome = "analysis"
        self.reply = None  # A function of the request bytes giving the reply bytes, in place of research_reply.
        self.status = 200
        self.error: Exception | None = None
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.arrivals = threading.Semaphore(0)  # One release per request that reached the fake.
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request.content)
            self.headers.append({"names": sorted(request.headers.keys()),
                                 **{name: request.headers.get(name) for name in ("anthropic-version", "content-type")}})
        self.entered.set()
        self.arrivals.release()
        if self.gate is not None:
            self.gate.wait(20)
        if self.error is not None:
            raise self.error
        answer = self.reply or (lambda content: research_reply(content, self.outcome))
        body = answer(request.content) if self.status == 200 else \
            json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Synthetic"}}).encode()
        return httpx.Response(self.status, content=body,
                              headers={"content-type": "application/json", "request-id": "req_synthetic0001"})

    def factory(self, observe):
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False, trust_env=False,
                            event_hooks={"response": [observe]})


@dataclass
class Clock:
    """A settable clock shared by the app and the tests."""
    moment: datetime = START

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta) -> None:
        self.moment += timedelta(**delta)


@dataclass
class World:
    root: Path
    clock: Clock = field(default_factory=Clock)
    provider: ProviderFake = field(default_factory=ProviderFake)
    sending: bool = True
    ids: dict = field(default_factory=dict)

    def __post_init__(self):
        self.store_path = self.root / "accounts" / "accounts.db"
        acc.create_store(self.store_path)
        self.accounts = acc.Accounts.open(self.store_path)
        for username, role in (("admin", "admin"), ("reader-a", "user"), ("reader-b", "user")):
            created = acc.create_user(self.accounts, username, f"{username} (synthetic)", role, PASSWORDS[username],
                                      "test-setup", self.clock())
            self.ids[username] = created["user_id"]

    @property
    def folders(self) -> ra.Folders:
        return ra.Folders(research=self.root / "research-analyses", intake=self.root / "intake",
                          links=self.root / "links")

    def standard_terms(self, credits: int = 40, limit: int = 3) -> None:
        """A synthetic credit policy and usage policy, a grant and a daily limit for both users (test values only)."""
        admin = self.ids["admin"]
        entitlements.add_policy(self.accounts, POLICY, admin, "synthetic test policy", self.clock())
        self.usage_terms()
        for user in ("reader-a", "reader-b"):
            entitlements.add_credits(self.accounts, self.ids[user], "grant", credits, admin, "synthetic grant",
                                     f"grant-{user}-0001", self.clock())
            entitlements.set_daily_limit(self.accounts, self.ids[user], limit, admin, "synthetic limit", self.clock())

    def usage_terms(self, policy: dict | None = None) -> None:
        """A synthetic usage policy (USAGE_POLICY unless another is given)."""
        usage.add_policy(self.accounts, policy or USAGE_POLICY, self.ids["admin"], "synthetic usage policy",
                         self.clock())

    def sender(self) -> PaidSender | None:
        return PaidSender(api_key=lambda: FAKE_KEY, client_factory=self.provider.factory) if self.sending else None

    def app(self, static: Path | None = None, client_static: Path | None = None, **options):
        """The application over this world's folders; the Event Inbox is always event-inbox/ inside it (never the
        operator's), and `options` are passed on (a publication fetcher, feeds, a tick clock)."""
        return create_app(self.root / "no-dossiers", static, self.root / "prepared-drafts", self.root / "reviews",
                          self.root / "intake", self.root / "attempts", paid=self.sender(), links=self.root / "links",
                          research_analyses=self.root / "research-analyses", accounts=self.store_path,
                          client_static=client_static, accounts_clock=self.clock,
                          inbox=options.pop("inbox", self.root / "event-inbox"), **options)

    def client(self, username: str | None = None, bind: bool = True, **app_options) -> TestClient:
        """A signed-in client sends its account's binding on every request, as a page opened for it does; ``bind``
        false sends none, as a page from before account binding did."""
        client = TestClient(self.app(**app_options), base_url=BASE)
        if username is not None:
            reply = client.post("/api/session/login", headers=SESSION_WRITE,
                                json={"username": username, "password": PASSWORDS[username]})
            assert reply.status_code == 200, reply.text
            if bind:
                bind_to(client, reply)
        return client


def bind_to(client: TestClient, signed_in) -> None:
    """From now on ``client`` names the account a sign-in reply signed in, as a page opened for that account does."""
    body = signed_in.json()
    if signed_in.status_code == 200 and body.get("state") == "signed_in":
        client.headers[ACCOUNT] = body["user"]["user_id"]


def every_file(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}

"""The user research flow over HTTP (user-api-0.2), against a fake provider and SYNTHETIC accounts (see account_fakes).

One approved run sends the exact saved bytes once and charges the quoted credits; Effort changes prepare separate
immutable requests and invalidate quotes; tampered, expired or superseded quotes and unoffered levels fail before any
provider contact; double clicks, lost replies and restarts never send or debit twice; a run that provably sent nothing
returns its credits and slot once, while an uncertain one keeps its hold for an administrator, who resolves it once;
reads, reviews and exports consume nothing; operator routes never attempt a user's request; historical operator records
stay byte-identical; and the served payloads have the published contract's shape and pass the Client's own readers.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, USER_WRITE, World, every_file, source_form
from second_order import auth, entitlements as ent, model_draft, research_analysis as ra, user_research
from second_order.api import create_app
from second_order.schema import Event
from pydantic import HttpUrl

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
RESEARCH = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Research": "1"}


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms(credits=40, limit=3)
        self.user = self.client("reader-a")

    def client(self, username: str | None = None) -> TestClient:
        client = self.world.client(username)
        self.addCleanup(client.close)
        return client

    def twin(self, client: TestClient) -> TestClient:
        """Another tab of the same browser: a new connection with the same session cookie."""
        other = TestClient(self.world.app(), base_url=BASE)
        self.addCleanup(other.close)
        other.cookies.set(auth.SESSION_COOKIE, client.cookies.get(auth.SESSION_COOKIE))
        if ACCOUNT in client.headers:  # The same page, opened for the same account.
            other.headers[ACCOUNT] = client.headers[ACCOUNT]
        return other

    def source(self, client: TestClient | None = None, **form) -> str:
        self.world.clock.advance(seconds=1)  # Two identical sources at one instant would be one capture.
        reply = (client or self.user).post("/api/user/sources", headers=USER_WRITE, json=source_form(**form))
        self.assertEqual(reply.status_code, 201, reply.text)
        return reply.json()["source"]["source_id"]

    def prepare(self, source_id: str, effort: str = "high", client: TestClient | None = None) -> httpx.Response:
        return (client or self.user).post("/api/user/analyses", headers=USER_WRITE,
                                          json={"source_id": source_id, "effort": effort})

    def quote(self, analysis_id: str, client: TestClient | None = None) -> httpx.Response:
        return (client or self.user).post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={})

    def approve(self, analysis_id: str, quote: dict, client: TestClient | None = None, **changes) -> httpx.Response:
        body = {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                "approve": True} | changes
        return (client or self.user).post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json=body)

    def prepared(self, effort: str = "high") -> tuple[str, dict]:
        analysis_id = self.prepare(self.source(), effort).json()["analysis"]["analysis_id"]
        reply = self.quote(analysis_id)
        self.assertEqual(reply.status_code, 201, reply.text)
        return analysis_id, reply.json()["quote"]

    def account(self) -> dict:
        return self.user.get("/api/user/account").json()

    def analysis(self, analysis_id: str) -> dict:
        return self.user.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]

    def admin(self) -> TestClient:
        return self.client("admin")


class Flow(Base):
    # ---------------------------------------------------------------- sources

    def post_form(self, text: str, headline: str = "Simulated statistics office publishes its quarterly survey"
                  ) -> httpx.Response:
        """A source form sent as a browser sends it: UTF-8 JSON, characters beyond ASCII unescaped."""
        self.world.clock.advance(seconds=1)
        body = json.dumps(source_form(headline=headline, text=text), ensure_ascii=False).encode("utf-8")
        return self.user.post("/api/user/sources", headers=USER_WRITE, content=body)

    def test_a_source_of_50000_characters_fits_in_any_script(self):
        texts = {"English": ("Synthetic text for a check. " * 1_800)[:50_000],
                 "Hebrew": ("טקסט סינתטי לבדיקה. " * 2_700)[:50_000],  # SYNTHETIC: "synthetic text for a check."
                 "Chinese": ("合成测试文本。" * 7_200)[:50_000],  # SYNTHETIC: "synthetic test text."
                 "emoji": "\U0001F4C8" * 50_000}
        for script, text in texts.items():
            reply = self.post_form(text)
            self.assertEqual(reply.status_code, 201, (script, reply.text[:300]))
            source_id = reply.json()["source"]["source_id"]
            source = self.user.get(f"/api/user/sources/{source_id}").json()["source"]
            self.assertEqual((source["characters"], source["text"]), (50_000, text), script)
        sent = {script: len(json.dumps(source_form(text=text), ensure_ascii=False).encode("utf-8"))
                for script, text in texts.items()}
        self.assertGreater(sent["Chinese"], 150_000)  # Three bytes a character, four for the emoji: both are past
        self.assertGreater(sent["emoji"], 200_000)    # the 120,000 bytes a form had before.
        for text in ("x" * 50_001, "\U0001F4C8" * 50_001):
            longer = self.post_form(text, "Simulated longer source")
            self.assertEqual((longer.status_code, longer.json()["code"]), (422, "invalid_source"))
            self.assertIn("50,001 characters", longer.json()["detail"])
        self.assertEqual(len(self.user.get("/api/user/sources").json()["sources"]), 4)
        self.assertEqual(self.world.provider.requests, [])

    def test_the_largest_form_a_browser_sends_fits_and_a_larger_body_is_not_read(self):
        emoji = "\U0001F4C8"  # Four bytes in UTF-8, the most any character takes.
        form = source_form(headline=emoji * 1_500, text=emoji * 50_000) | {  # Every field at its own limit.
            "source_url": "https://example.org/synthetic/" + "s" * (2_083 - 30)}
        body = json.dumps(form, ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(body), 208_000)
        for padding in (270_000 - len(body), 270_001 - len(body)):  # JSON allows the trailing spaces.
            self.world.clock.advance(seconds=1)
            sent = self.user.post("/api/user/sources", headers=USER_WRITE, content=body + b" " * padding)
            if len(body) + padding <= 270_000:
                self.assertEqual(sent.status_code, 201, sent.text[:300])
                source = self.user.get(f"/api/user/sources/{sent.json()['source']['source_id']}").json()["source"]
                self.assertEqual((source["headline"], source["characters"]), (emoji * 1_500, 50_000))
            else:
                self.assertEqual((sent.status_code, sent.json()["code"]), (413, "payload_too_large"))
        self.assertEqual(len(self.user.get("/api/user/sources").json()["sources"]), 1)
        too_long = self.post_form("Synthetic text for a check. ", emoji * 1_501)  # Each field keeps its own limit.
        self.assertEqual((too_long.status_code, too_long.json()["code"]), (422, "invalid_source"))
        self.assertIn("1,500 characters", too_long.json()["detail"])
        unpaired = json.dumps(source_form(text="Synthetic \ud800 text")).encode("utf-8")  # \ud800 is not a character.
        refused = self.user.post("/api/user/sources", headers=USER_WRITE, content=unpaired)
        self.assertEqual((refused.status_code, refused.json()["code"]), (422, "invalid_source"))
        self.assertEqual(self.admin().post("/api/intake", headers=INTAKE, content=unpaired).status_code, 422)
        self.assertEqual(len(self.user.get("/api/user/sources").json()["sources"]), 1)
        self.assertEqual(self.world.provider.requests, [])

    def test_the_clients_source_limits_are_the_servers(self):
        published = (ROOT / "frontend" / "src" / "contracts" / "user.ts").read_text(encoding="utf-8")
        shown = {name: int(value.replace("_", "")) for name, value in
                 re.findall(r"export const (MAX_\w+) = ([\d_]+);", published)}
        self.assertEqual({name: shown.get(name) for name in ("MAX_SOURCE_CHARACTERS", "MAX_HEADLINE_CHARACTERS",
                                                             "MAX_SOURCE_FORM_BYTES", "MAX_SOURCE_URL_CHARACTERS")},
                         {"MAX_SOURCE_CHARACTERS": model_draft.MAX_SOURCE_CHARS,
                          "MAX_HEADLINE_CHARACTERS": next(rule.max_length for rule in
                                                          Event.model_fields["headline"].metadata
                                                          if hasattr(rule, "max_length")),
                          "MAX_SOURCE_FORM_BYTES": user_research.MAX_SOURCE_BODY,
                          "MAX_SOURCE_URL_CHARACTERS": HttpUrl._constraints.max_length})
        self.assertEqual(user_research.MAX_SOURCE_URL, HttpUrl._constraints.max_length)
        for letter, count, status in (("a", 2_063, 201), ("a", 2_064, 422), ("é", 1_031, 201), ("é", 1_032, 422)):
            self.world.clock.advance(seconds=1)  # UTF-8 bytes of the address as sent: 2,083 is the most.
            address = "https://example.org/" + letter * count
            sent = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | {"source_url": address})
            self.assertEqual(sent.status_code, status, sent.text[:200])

    def test_a_refused_source_is_explained_in_the_users_words(self):
        """invalid_source names the field and the rule; it never speaks of operator events, drafts or a validation
        library's internals."""
        long_text = "x" * 50_001
        cases = {"published_at": ("2030-01-01T10:00:00+03:00", "The publication time is in the future."),
                 "source_url": ("ftp://example.org/x", "The source address must start with https:// or http://."),
                 "headline": ("", "Write the source's headline.")}
        replies = {name: self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | {name: value})
                   for name, (value, _) in cases.items()}
        replies["not_a_url"] = self.user.post("/api/user/sources", headers=USER_WRITE,
                                              json=source_form() | {"source_url": "example"})
        replies["long_url"] = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | {
            "source_url": "https://example.org/" + "é" * 1_100})
        replies["long_text"] = self.user.post("/api/user/sources", headers=USER_WRITE,
                                              json=source_form() | {"source_text": long_text})
        replies["typed"] = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | {"headline": 5})
        for name, reply in replies.items():
            self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_source"), name)
            self.assertNotRegex(reply.json()["detail"], r"(?i)operator|\bevent|draft|String should|Input should|"
                                                        r"source_url|published_at", name)
        for name, (_, expected) in cases.items():
            self.assertTrue(replies[name].json()["detail"].startswith(expected), replies[name].json()["detail"])
        self.assertIn("is not a web address", replies["not_a_url"].json()["detail"])
        self.assertIn("too long: at most 2,083 characters", replies["long_url"].json()["detail"])
        self.assertIn("50,001 characters; the limit is 50,000", replies["long_text"].json()["detail"])
        self.assertEqual(replies["typed"].json()["detail"], "Every field of a source must be text.")
        self.assertEqual(self.user.get("/api/user/sources").json()["sources"], [])

    def test_a_larger_source_is_quoted_by_its_bytes_and_every_other_limit_still_holds(self):
        english = self.post_form(("Synthetic text for a check. " * 1_800)[:50_000]).json()["source"]["source_id"]
        emoji = self.post_form("\U0001F4C8" * 50_000).json()["source"]["source_id"]
        quotes = {}
        for name, source_id in (("English", english), ("emoji", emoji)):
            analysis_id = self.prepare(source_id, "low").json()["analysis"]["analysis_id"]
            quotes[name] = (analysis_id, self.quote(analysis_id).json()["quote"])
        self.assertGreaterEqual(quotes["emoji"][1]["credits"] - quotes["English"][1]["credits"], 74)  # 150,000 bytes
        short = self.approve(*quotes["emoji"])  # More points than the account holds: refused before any send.
        self.assertEqual((short.status_code, short.json()["code"]), (409, "insufficient_credits"))
        terms = {key: ent.current_policy(self.world.accounts)[key] for key in ent.POLICY_FIELDS}
        self.admin().post("/api/admin/policy", headers=ADMIN_WRITE,
                          json={"policy": terms | {"max_request_usd": 0.3}, "reason": "synthetic",
                                "idempotency_key": "policy-lower-limit"})
        self.assertEqual(self.quote(quotes["English"][0]).status_code, 201)
        over = self.quote(quotes["emoji"][0])  # Its planning estimate is over the per-request limit.
        self.assertEqual((over.status_code, over.json()["code"]), (409, "request_over_budget"))
        self.assertEqual(self.world.provider.requests, [])
        self.assertEqual(self.account()["credits"], {"available": 40, "held": 0})
        form = json.dumps(source_form("Operator synthetic statement", "\U0001F4C8" * 50_000),
                          ensure_ascii=False).encode("utf-8")
        operator = self.admin().post("/api/intake", headers=INTAKE, content=form)
        self.assertEqual(operator.status_code, 413)  # The operator's Tracker form keeps 120,000 bytes, as before.
        analysis = self.user.post("/api/user/analyses", headers=USER_WRITE, content=b" " * 120_001)
        self.assertEqual((analysis.status_code, analysis.json()["code"]), (413, "payload_too_large"))

    # ---------------------------------------------------------------- one run

    def test_one_approved_run_sends_the_exact_saved_bytes_once_and_charges_the_quote(self):
        analysis_id, quote = self.prepared()
        reply = self.approve(analysis_id, quote)
        self.assertEqual(reply.status_code, 201, reply.text)
        body = reply.json()
        saved = (self.world.folders.requests / analysis_id / "request.json").read_bytes()
        self.assertEqual(self.world.provider.requests, [saved])
        self.assertEqual((self.world.root / "research-analyses" / "attempts" / analysis_id / "request.json")
                         .read_bytes(), saved)
        self.assertEqual(json.loads(saved)["output_config"], {"effort": "high", "format": {
            "type": "json_schema", "schema": ra.output_schema()}})
        self.assertEqual((body["duplicate"], body["analysis"]["state"], body["analysis"]["result"]["outcome"]),
                         (False, "recorded", "analysis"))
        self.assertEqual(body["analysis"]["charge"], {"credits_reserved": quote["credits"],
                                                      "credits_charged": quote["credits"], "credits_returned": 0,
                                                      "state": "charged", "quota_day": "2026-10-14"})
        self.assertEqual(body["account"]["credits"], {"available": 40 - quote["credits"], "held": 0})
        self.assertEqual(body["account"]["daily"]["used"], 1)
        kinds = [entry["kind"] for entry in ent.ledger(self.world.accounts, self.world.ids["reader-a"])]
        self.assertEqual(kinds, ["grant", "hold", "settle"])
        self.assertTrue(ent.balance(self.world.accounts, self.world.ids["reader-a"])["reconciles"])

    def test_changing_effort_prepares_a_separate_immutable_request_and_invalidates_the_quote(self):
        source_id = self.source()
        high = self.prepare(source_id, "high").json()["analysis"]["analysis_id"]
        quote = self.quote(high).json()["quote"]
        low_reply = self.prepare(source_id, "low")
        low = low_reply.json()["analysis"]["analysis_id"]
        self.assertEqual((low_reply.status_code, low_reply.json()["created"]), (201, True))
        self.assertNotEqual(low, high)
        requests = self.world.folders.requests
        high_bytes, low_bytes = (requests / high / "request.json").read_bytes(), (requests / low / "request.json") \
            .read_bytes()
        high_request = json.loads(high_bytes)
        high_request["output_config"]["effort"] = "low"
        self.assertEqual(high_request, json.loads(low_bytes))  # The bytes differ only in the Effort.
        for tampered in (self.approve(low, quote), self.approve(high, quote, effort="low"),
                         self.approve(high, quote, credits=quote["credits"] - 1)):
            self.assertEqual((tampered.status_code, tampered.json()["code"]), (409, "quote_mismatch"))
        before = every_file(requests)
        again = self.prepare(source_id, "high")
        self.assertEqual((again.status_code, again.json()["created"]), (200, False))
        self.assertEqual(every_file(requests), before)
        self.assertEqual(self.world.provider.requests, [])
        self.assertEqual(self.approve(high, quote).status_code, 201)

    def test_unoffered_levels_and_policy_changes_fail_before_any_provider_call(self):
        source_id = self.source()
        for effort in ("max", "ultra", "xhigh"):
            refused = self.prepare(source_id, effort)
            self.assertEqual((refused.status_code, refused.json()["code"]), (409, "unsupported_effort"), effort)
            self.assertEqual([option["effort"] for option in refused.json()["efforts"]], ["low", "medium", "high"])
        analysis_id = self.prepare(source_id, "high").json()["analysis"]["analysis_id"]
        quote = self.quote(analysis_id).json()["quote"]
        changed = {**ent.current_policy(self.world.accounts)}
        terms = {key: changed[key] for key in ent.POLICY_FIELDS} | {"efforts": {"low": {"extra_credits": 0}}}
        self.admin().post("/api/admin/policy", headers=ADMIN_WRITE, json={"policy": terms, "reason": "synthetic",
                                                                          "idempotency_key": "policy-low-only"})
        superseded = self.approve(analysis_id, quote)
        self.assertEqual((superseded.status_code, superseded.json()["code"]), (409, "quote_superseded"))
        self.assertEqual(self.quote(analysis_id).json()["code"], "unsupported_effort")
        self.assertEqual(self.analysis(analysis_id)["quote"]["state"], "superseded")
        self.assertEqual(self.world.provider.requests, [])
        self.assertEqual(self.account()["credits"], {"available": 40, "held": 0})

    def test_an_expired_quote_is_refused_and_a_new_quote_runs(self):
        analysis_id, quote = self.prepared()
        self.world.clock.advance(seconds=900)
        expired = self.approve(analysis_id, quote)
        self.assertEqual((expired.status_code, expired.json()["code"]), (409, "quote_expired"))
        self.assertEqual(self.analysis(analysis_id)["quote"]["state"], "expired")
        self.assertEqual((self.account()["credits"]["available"], self.account()["daily"]["used"]), (40, 0))
        fresh = self.quote(analysis_id).json()["quote"]
        self.assertEqual(self.approve(analysis_id, fresh).status_code, 201)
        self.assertEqual(len(self.world.provider.requests), 1)

    def test_approve_must_be_true_and_the_body_exact(self):
        analysis_id, quote = self.prepared()
        for body in ({"quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"], "approve": False},
                     {"quote_id": quote["quote_id"], "effort": "high", "credits": str(quote["credits"]),
                      "approve": True},
                     {"quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"]}):
            reply = self.user.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json=body)
            self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_request"))
        self.assertEqual(self.world.provider.requests, [])

    # ---------------------------------------------------------------- duplicates, interruptions, uncertainty

    def test_a_double_click_another_tab_and_a_lost_reply_never_send_or_debit_twice(self):
        analysis_id, quote = self.prepared()
        self.world.provider.gate = threading.Event()
        first: dict = {}
        worker = threading.Thread(target=lambda: first.setdefault("reply", self.approve(analysis_id, quote)))
        worker.start()
        self.assertTrue(self.world.provider.entered.wait(20))
        tab = self.twin(self.user)
        repeat = self.approve(analysis_id, quote, client=tab)
        self.assertEqual((repeat.status_code, repeat.json()["duplicate"]), (200, True))
        self.assertEqual(repeat.json()["analysis"]["state"], "running")
        self.assertEqual(repeat.json()["analysis"]["charge"]["state"], "held")
        self.assertEqual(self.analysis(analysis_id)["state"], "running")
        self.world.provider.gate.set()
        worker.join(30)
        self.assertEqual(first["reply"].status_code, 201)
        lost = self.approve(analysis_id, quote, client=tab)  # The first reply was lost; the user clicks again.
        self.assertEqual((lost.status_code, lost.json()["duplicate"], lost.json()["analysis"]["state"]),
                         (200, True, "recorded"))
        self.assertEqual(len(self.world.provider.requests), 1)
        holds = [row for row in ent.ledger(self.world.accounts) if row["kind"] == "hold"]
        self.assertEqual(len(holds), 1)

    def test_a_run_that_stopped_before_sending_returns_its_credits_and_slot_once(self):
        analysis_id, quote = self.prepared()
        original = ra.keep_record

        def failing(path, data, secret=None):
            if path.name == "request.json" and "attempts" in path.parts:
                raise OSError("synthetic disk failure before the send")
            return original(path, data, secret)
        with patch("second_order.research_analysis.keep_record", side_effect=failing):
            reply = self.approve(analysis_id, quote)
        self.assertEqual((reply.status_code, reply.json()["code"]), (500, "internal_error"))
        self.assertEqual(self.world.provider.requests, [])
        shown = self.analysis(analysis_id)
        self.assertEqual((shown["state"], shown["charge"]["state"], shown["charge"]["credits_returned"]),
                         ("not_sent", "returned", quote["credits"]))
        self.assertEqual((self.account()["credits"], self.account()["daily"]["used"]),
                         ({"available": 40, "held": 0}, 0))
        self.assertEqual(self.quote(analysis_id).json()["code"], "already_attempted")  # Still one attempt, ever.
        again = self.approve(analysis_id, quote)
        self.assertEqual((again.status_code, again.json()["duplicate"]), (200, True))
        returned = [row for row in ent.ledger(self.world.accounts) if row["kind"] == "release"]
        self.assertEqual(len(returned), 1)

    def test_a_run_whose_attempt_folder_cannot_be_reserved_returns_its_credits(self):
        analysis_id, quote = self.prepared()
        with patch("second_order.research_analysis._reserve", side_effect=PermissionError("synthetic")):
            reply = self.approve(analysis_id, quote)
        self.assertEqual((reply.status_code, reply.json()["code"]), (500, "internal_error"))
        self.assertEqual(self.world.provider.requests, [])
        self.assertEqual((self.account()["credits"], self.account()["daily"]["used"]),
                         ({"available": 40, "held": 0}, 0))
        self.assertEqual(self.analysis(analysis_id)["state"], "not_sent")

    def test_an_uncertain_send_keeps_its_hold_until_an_administrator_resolves_it_once(self):
        analysis_id, quote = self.prepared()
        self.world.provider.error = httpx.ReadTimeout("synthetic timeout after the request left")
        reply = self.approve(analysis_id, quote)
        self.assertEqual(reply.status_code, 201, reply.text)
        shown = reply.json()["analysis"]
        self.assertEqual((shown["state"], shown["charge"]["state"]), ("failed", "under_review"))
        self.assertEqual(reply.json()["account"]["credits"], {"available": 40 - quote["credits"],
                                                              "held": quote["credits"]})
        self.world.clock.advance(days=2)  # A new calendar day releases nothing.
        self.user = self.client("reader-a")  # The earlier session has expired by now.
        self.assertEqual(self.account()["credits"]["held"], quote["credits"])
        self.assertEqual(self.quote(analysis_id).json()["code"], "already_attempted")
        admin = self.admin()
        holds = admin.get("/api/admin/holds").json()["holds"]
        self.assertEqual([(row["request_id"], row["resolvable"], row["entitlement"]["state"]) for row in holds],
                         [(analysis_id, True, "needs_review")])
        attempt, observed = holds[0]["attempt_id"], holds[0]["observed"]  # The state the Admin screen shows.
        too_much = admin.post(f"/api/admin/attempts/{attempt}/resolve", headers=ADMIN_WRITE, json={
            "resolution": "charge", "credits_charged": quote["credits"] + 1, "reason": "synthetic",
            "observed": observed})
        self.assertEqual(too_much.status_code, 422)
        resolved = admin.post(f"/api/admin/attempts/{attempt}/resolve", headers=ADMIN_WRITE, json={
            "resolution": "return", "credits_charged": 0, "reason": "synthetic: the Console shows no charge",
            "observed": observed})
        self.assertEqual(resolved.status_code, 201)
        twice = admin.post(f"/api/admin/attempts/{attempt}/resolve", headers=ADMIN_WRITE, json={
            "resolution": "charge", "credits_charged": 1, "reason": "again", "observed": observed})
        self.assertEqual((twice.status_code, twice.json()["code"]), (409, "already_resolved"))
        shown = self.analysis(analysis_id)
        self.assertEqual((shown["state"], shown["charge"]["state"]), ("failed", "returned"))
        self.assertIn("returned", shown["state_detail"])
        self.assertEqual(self.account()["credits"], {"available": 40, "held": 0})
        self.assertEqual(len(self.world.provider.requests), 1)

    def test_a_provider_error_can_be_settled_for_part_of_the_quote(self):
        analysis_id, quote = self.prepared()
        self.world.provider.status = 529
        reply = self.approve(analysis_id, quote)
        self.assertEqual(reply.json()["analysis"]["state"], "failed")
        admin = self.admin()
        hold = admin.get("/api/admin/holds").json()["holds"][0]
        admin.post(f"/api/admin/attempts/{hold['attempt_id']}/resolve", headers=ADMIN_WRITE,
                   json={"resolution": "charge", "credits_charged": 2, "reason": "synthetic partial settlement",
                         "observed": hold["observed"]})
        charge = self.analysis(analysis_id)["charge"]
        self.assertEqual((charge["state"], charge["credits_charged"], charge["credits_returned"]),
                         ("charged", 2, quote["credits"] - 2))
        self.assertEqual(self.account()["daily"]["used"], 1)  # A charged attempt keeps its daily slot.

    def test_a_send_with_no_recorded_outcome_becomes_unresolved_and_is_never_sent_again(self):
        analysis_id, quote = self.prepared()
        original = ra.keep_record

        def failing(path, data, secret=None):
            if path.name == "manifest.json" and "attempts" in path.parts:
                raise OSError("synthetic stop after the send")
            return original(path, data, secret)
        with patch("second_order.research_analysis.keep_record", side_effect=failing):
            reply = self.approve(analysis_id, quote)
        self.assertEqual((reply.status_code, reply.json()["code"]), (500, "internal_error"))
        self.assertEqual(len(self.world.provider.requests), 1)
        self.assertEqual(self.analysis(analysis_id)["state"], "running")  # It could still be in flight.
        admin = self.admin()
        hold = admin.get("/api/admin/holds").json()["holds"][0]
        attempt, observed = hold["attempt_id"], hold["observed"]
        early = admin.post(f"/api/admin/attempts/{attempt}/resolve", headers=ADMIN_WRITE,
                           json={"resolution": "return", "credits_charged": 0, "reason": "too early",
                                 "observed": observed})
        self.assertEqual((early.status_code, early.json()["code"]), (409, "in_flight"))
        self.world.clock.advance(minutes=16)
        shown = self.analysis(analysis_id)
        self.assertEqual((shown["state"], shown["charge"]["state"]), ("unresolved", "under_review"))
        self.assertIn("was sent", shown["state_detail"])
        self.assertEqual(self.approve(analysis_id, quote).json()["duplicate"], True)
        self.assertEqual(len(self.world.provider.requests), 1)
        settled = admin.post(f"/api/admin/attempts/{attempt}/resolve", headers=ADMIN_WRITE, json={
            "resolution": "charge", "credits_charged": quote["credits"], "reason": "synthetic: billed per Console",
            "observed": observed})
        self.assertEqual(settled.status_code, 201)
        self.assertEqual(self.analysis(analysis_id)["charge"]["state"], "charged")

    # ---------------------------------------------------------------- reads, reviews, limits, restarts

    def test_reads_reviews_and_exports_consume_no_credits_or_allowance(self):
        analysis_id, quote = self.prepared()
        recorded = self.approve(analysis_id, quote).json()["analysis"]
        ledger, account = ent.ledger(self.world.accounts), self.account()
        for _ in range(3):
            self.user.get(f"/api/user/analyses/{analysis_id}")
            self.user.get(f"/api/user/analyses/{analysis_id}/export")
            self.user.get("/api/user/analyses")
            self.user.get("/api/user/sources")
            self.user.get("/api/user/account")
        self.user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "human_reviewed",
            "notes": "Synthetic review."})
        self.assertEqual(ent.ledger(self.world.accounts), ledger)
        self.assertEqual(self.account(), account)
        self.assertEqual(len(self.world.provider.requests), 1)

    def test_reviews_are_the_owners_append_only_versions_bound_to_the_loaded_result(self):
        source_id = self.source()
        prepared = self.prepare(source_id).json()["analysis"]
        early = self.user.post(f"/api/user/analyses/{prepared['analysis_id']}/reviews", headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": "0" * 64, "status": None, "notes": "x"})
        self.assertEqual(early.json()["code"], "no_result")
        analysis_id = prepared["analysis_id"]
        recorded = self.approve(analysis_id, self.quote(analysis_id).json()["quote"]).json()["analysis"]
        review = lambda **form: self.user.post(f"/api/user/analyses/{analysis_id}/reviews",  # noqa: E731
                                               headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "needs_revision",
            "notes": "First pass."} | form)
        self.assertEqual(review(result_sha256="f" * 64).json()["code"], "result_changed")
        first = review()
        self.assertEqual(first.status_code, 201)
        saved = first.json()["review"]
        self.assertEqual((saved["sequence"], saved["reviewer"]["user_id"]), (1, self.world.ids["reader-a"]))
        self.assertEqual(review().json()["code"], "review_conflict")
        self.assertEqual(review(parent_review_id=saved["review_id"]).json()["code"], "invalid_review")
        second = review(parent_review_id=saved["review_id"], status="human_reviewed", notes="Checked.")
        self.assertEqual(second.json()["review"]["sequence"], 2)
        record = json.loads((self.world.folders.reviews / analysis_id / "000002.json").read_text(encoding="utf-8"))
        self.assertEqual((record["record_version"], record["reviewer"]),
                         ("research-review-0.2", {"user_id": self.world.ids["reader-a"], "role": "user"}))
        self.assertEqual(len(self.analysis(analysis_id)["reviews"]), 2)

    def test_review_notes_are_limited_in_characters_in_any_script_and_encoding(self):
        """QA-1: the route reads every valid review: 20,000 characters in four-byte UTF-8 (raw, or escaped as two
        \\uXXXX each); 20,001 characters are refused for their length, and a body past the byte bound before parsing."""
        analysis_id, quote = self.prepared()
        recorded = self.approve(analysis_id, quote).json()["analysis"]
        path = f"/api/user/analyses/{analysis_id}/reviews"
        parent = None

        def send(notes: str, ascii_only: bool = False):
            form = {"parent_review_id": parent, "result_sha256": recorded["result_sha256"], "status": None,
                    "notes": notes}
            return self.user.post(path, headers=USER_WRITE, content=json.dumps(form, ensure_ascii=ascii_only))
        for notes, ascii_only in (("\U0001F4C8" * 20_000, False), ("\U0001F4C9" * 20_000, True),
                                  ("é" * 19_999 + "\U0001F4C8", False)):
            body = json.dumps({"notes": notes}, ensure_ascii=ascii_only).encode("utf-8")
            self.assertGreater(len(body), 39_000)
            saved = send(notes, ascii_only)
            self.assertEqual(saved.status_code, 201, saved.text[:300])
            parent = saved.json()["review"]["review_id"]
            self.assertEqual(saved.json()["review"]["notes"], notes)
        longer = send("\U0001F4C8" * 20_001)
        self.assertEqual((longer.status_code, longer.json()["code"]), (422, "invalid_review"))
        self.assertIn("limited to 20,000 characters; these have 20,001", longer.json()["detail"])
        too_big = self.user.post(path, headers=USER_WRITE, content=b'{"notes": "' + b"x" * ra.MAX_REVIEW_BODY + b'"}')
        self.assertEqual((too_big.status_code, too_big.json()["code"]), (413, "payload_too_large"))
        self.assertEqual(len(self.analysis(analysis_id)["reviews"]), 3)

    def recorded_result(self) -> tuple[str, dict]:
        analysis_id, quote = self.prepared()
        return analysis_id, self.approve(analysis_id, quote).json()["analysis"]

    def review_form(self, recorded: dict, parent: str | None = None, **form) -> dict:
        return {"parent_review_id": parent, "result_sha256": recorded["result_sha256"], "status": "human_reviewed",
                "notes": "Synthetic review."} | form

    def test_rewording_a_server_note_keeps_reviews_bound_to_the_unchanged_result(self):
        """QA-3: the result's fingerprint names its content, not the server's fixed sentences about it."""
        analysis_id, recorded = self.recorded_result()
        path = f"/api/user/analyses/{analysis_id}/reviews"
        saved = self.user.post(path, headers=USER_WRITE, json=self.review_form(recorded))
        self.assertEqual(saved.status_code, 201, saved.text)
        record = json.loads((self.world.folders.reviews / analysis_id / "000001.json").read_text(encoding="utf-8"))
        self.assertEqual(record["binding"]["user_result_binding"], "user-result-2")
        reworded = dict(user_research.NOTES, analysis="Each quoted passage appears in your source text. Judging "
                                                      "whether the reading is sound is up to you.")
        with patch.dict(user_research.NOTES, reworded):
            shown = self.analysis(analysis_id)
            self.assertNotEqual(shown["result"]["note"], recorded["result"]["note"])
            self.assertEqual(shown["result_sha256"], recorded["result_sha256"])
            self.assertEqual(shown["reviews"][0]["result_sha256"], shown["result_sha256"])
            again = self.user.post(path, headers=USER_WRITE, json=self.review_form(  # Loaded before the rewording.
                recorded, parent=saved.json()["review"]["review_id"], status="needs_revision"))
            self.assertEqual(again.status_code, 201, again.text)

    def test_a_review_saved_before_the_content_binding_stays_bound_and_is_never_rewritten(self):
        """A user-result-1 review (written as the earlier server wrote it) is bound exactly while the content is the
        same; reading it changes no byte; a page loaded then can still save; a real change detaches it."""
        analysis_id, recorded = self.recorded_result()
        verified = ra.verified_request(analysis_id, self.world.folders)
        view = ra.result_view(verified, self.world.folders)
        result = user_research.user_result(view)
        legacy = {"record_version": ra.USER_RECORD_VERSION, "request_id": analysis_id, "sequence": 1,
                  "parent_review_id": None, "saved_at": "2026-10-14T09:05:00+00:00",
                  "reviewer": {"user_id": self.world.ids["reader-a"], "role": "user"}, "status": "needs_revision",
                  "notes": "Synthetic review saved under user-result-1.",
                  "binding": {"user_result_sha256": user_research.sha256_of(result),
                              "result_view_sha256": ra.fingerprint(view), "request_sha256": verified["request_sha256"],
                              "response_sha256": view["provenance"]["response_sha256"],
                              "result_view_version": ra.VIEW_VERSION, "outcome": view["outcome"], "mode": view["mode"]}}
        legacy["review_id"] = ra.review_id(legacy)
        folder = self.world.folders.reviews / analysis_id
        folder.mkdir(parents=True)
        written = json.dumps(legacy, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
        (folder / "000001.json").write_bytes(written)
        shown = self.analysis(analysis_id)
        self.assertEqual(shown["result_sha256"], recorded["result_sha256"])
        self.assertEqual(shown["reviews"][0]["result_sha256"], shown["result_sha256"])  # Still the current result.
        self.assertEqual((folder / "000001.json").read_bytes(), written)
        old_page = {**self.review_form(recorded, parent=legacy["review_id"]),
                    "result_sha256": legacy["binding"]["user_result_sha256"]}  # A page loaded under user-result-1.
        saved = self.user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json=old_page)
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["review"]["result_sha256"], shown["result_sha256"])
        changed = dict(view, analysis={**view["analysis"], "assumptions": ["A different synthetic assumption."]})
        with patch.object(ra, "result_view", return_value=changed):  # The recorded content itself differs.
            after = self.analysis(analysis_id)
            self.assertNotEqual(after["result_sha256"], shown["result_sha256"])
            self.assertTrue(all(review["result_sha256"] != after["result_sha256"] for review in after["reviews"]))
            stale = self.user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json=self.review_form(
                recorded, parent=saved.json()["review"]["review_id"]))
            self.assertEqual((stale.status_code, stale.json()["code"]), (409, "result_changed"))
        self.assertEqual((folder / "000001.json").read_bytes(), written)

    def test_a_control_character_in_review_notes_is_refused_as_such_and_nothing_is_saved(self):
        """QA-4: a control character is refused with a message about control characters, not about length; tabs and
        line breaks are kept; nothing is saved by a refusal."""
        analysis_id, quote = self.prepared()
        recorded = self.approve(analysis_id, quote).json()["analysis"]

        def send(notes: str, parent: str | None = None):
            return self.user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json={
                "parent_review_id": parent, "result_sha256": recorded["result_sha256"], "status": None,
                "notes": notes})
        for control in ("\x00", "\x07", "\x1b", "\x7f", "\x0b"):
            refused = send(f"Short note {control} here.")
            self.assertEqual((refused.status_code, refused.json()["code"]), (422, "invalid_review"), repr(control))
            self.assertIn("control characters other than tabs and line breaks", refused.json()["detail"])
            self.assertNotIn("characters;", refused.json()["detail"])  # Not attributed to length.
        self.assertEqual(self.analysis(analysis_id)["reviews"], [])
        kept = send("Line one\nline two\r\n\tindented.")
        self.assertEqual(kept.status_code, 201, kept.text)
        self.assertEqual(kept.json()["review"]["notes"], "Line one\nline two\r\n\tindented.")

    def test_operator_routes_never_attempt_or_review_a_users_request(self):
        analysis_id, quote = self.prepared()
        admin = self.admin()
        sha = admin.get(f"/api/research-analyses/{analysis_id}").json()["request_sha256"]
        self.assertEqual(admin.get(f"/api/research-analyses/{analysis_id}").json()["prepared_by"],
                         self.world.ids["reader-a"])
        mock = admin.post(f"/api/research-analyses/{analysis_id}/mock", headers=RESEARCH,
                          json={"request_sha256": sha, "mock_outcome": "analysis"})
        estimate = ra.research_cost((self.world.folders.requests / analysis_id / "request.json").read_bytes())
        paid = admin.post(f"/api/research-analyses/{analysis_id}/paid", headers=RESEARCH, json={
            "request_sha256": sha, "approve_paid_request": True,
            "estimated_max_usd": estimate["estimated_real_run_if_output_reaches_max_usd"]})
        for reply in (mock, paid):
            self.assertEqual(reply.status_code, 409, reply.text)
            self.assertIn("user account", reply.json()["detail"])
        self.assertFalse((self.world.folders.attempts / analysis_id).exists())
        self.assertEqual(self.approve(analysis_id, quote).status_code, 201)
        recorded = admin.get(f"/api/research-analyses/{analysis_id}").json()
        review = admin.post(f"/api/research-analyses/{analysis_id}/reviews", headers=RESEARCH, json={
            "parent_review_id": None, "binding": {"result_view_sha256": recorded["result_view_sha256"],
                                                  "request_sha256": sha,
                                                  "response_sha256": recorded["result"]["provenance"][
                                                      "response_sha256"]},
            "status": None, "notes": "operator"})
        self.assertEqual(review.status_code, 409)

    def test_the_daily_limit_resets_at_the_next_jerusalem_midnight(self):
        ent.set_daily_limit(self.world.accounts, self.world.ids["reader-a"], 1, self.world.ids["admin"], "x",
                            self.world.clock())
        first, quote = self.prepared("high")
        self.approve(first, quote)
        second, quote = self.prepared("low")
        refused = self.approve(second, quote)
        self.assertEqual((refused.status_code, refused.json()["code"], refused.json()["resets_at"]),
                         (409, "daily_limit_reached", "2026-10-14T21:00:00+00:00"))
        self.assertEqual(refused.json()["daily"]["remaining"], 0)
        self.world.clock.advance(hours=12)  # 21:00 UTC: midnight on 15 October in Jerusalem.
        self.user = self.client("reader-a")  # The 12-hour session has ended; sign in again.
        fresh = self.quote(second).json()["quote"]
        self.assertEqual(self.approve(second, fresh).status_code, 201)
        self.assertEqual(self.account()["daily"], {"timezone": "Asia/Jerusalem", "day": "2026-10-15", "limit": 1,
                                                    "used": 1, "remaining": 0,
                                                    "resets_at": "2026-10-15T21:00:00+00:00"})

    def test_a_restarted_server_keeps_sessions_balances_and_duplicate_protection(self):
        analysis_id, quote = self.prepared()
        self.approve(analysis_id, quote)
        before = self.account()
        restarted = self.twin(self.user)  # A new app over the same folders and accounts store.
        self.assertEqual(restarted.get("/api/user/account").json(), before)
        again = self.approve(analysis_id, quote, client=restarted)
        self.assertEqual((again.status_code, again.json()["duplicate"]), (200, True))
        self.assertEqual(len(self.world.provider.requests), 1)

    def test_historical_operator_records_stay_byte_identical(self):
        admin = self.admin()
        capture = admin.post("/api/intake", headers=INTAKE, json=source_form("Operator synthetic statement")).json()
        prepared = admin.post("/api/research-analyses", headers=RESEARCH,
                              json={"capture_id": capture["capture_id"]}).json()
        admin.post(f"/api/research-analyses/{prepared['request_id']}/mock", headers=RESEARCH,
                   json={"request_sha256": prepared["request_sha256"], "mock_outcome": "analysis"})
        shown = admin.get(f"/api/research-analyses/{prepared['request_id']}").json()
        admin.post(f"/api/research-analyses/{prepared['request_id']}/reviews", headers=RESEARCH, json={
            "parent_review_id": None, "binding": {"result_view_sha256": shown["result_view_sha256"],
                                                  "request_sha256": prepared["request_sha256"],
                                                  "response_sha256": shown["result"]["provenance"]["response_sha256"]},
            "status": "human_reviewed", "notes": "Synthetic operator review."})
        before = every_file(self.world.root)
        analysis_id, quote = self.prepared()
        self.approve(analysis_id, quote)
        admin.get("/api/admin/actions")
        after = every_file(self.world.root)
        changed = [name for name, data in before.items() if after.get(name) != data and "accounts" not in name]
        self.assertEqual(changed, [])
        rows = {row["request_id"]: row for row in admin.get("/api/admin/actions").json()["actions"]}
        self.assertEqual((rows[prepared["request_id"]]["action"], rows[prepared["request_id"]]["requested_by"]),
                         ("local_mock", {"kind": "operator"}))
        self.assertEqual(rows[prepared["request_id"]]["usage_cost_usd"], 0)
        self.assertEqual(self.user.get(f"/api/user/sources/{capture['capture_id']}").status_code, 404)


def key_problems(served: object, published: object, path: str = "$") -> list[str]:
    """Where a served payload's structure differs from the published fixture's: the same keys in every object, the
    same kinds of value (null matches either way, since a field may be null in one state and set in another)."""
    if served is None or published is None:
        return []
    if isinstance(published, dict):
        if not isinstance(served, dict):
            return [f"{path}: an object was published"]
        problems = [f"{path}: keys {sorted(set(served) ^ set(published))} differ"] if set(served) != set(published) \
            else []
        return problems + [problem for key in set(served) & set(published)
                           for problem in key_problems(served[key], published[key], f"{path}.{key}")]
    if isinstance(published, list):
        if not isinstance(served, list):
            return [f"{path}: a list was published"]
        return [problem for item in served[:1] for sample in published[:1]
                for problem in key_problems(item, sample, f"{path}[0]")]
    kinds = (bool, int, float, str)
    same = next((kind for kind in kinds if isinstance(published, kind)), None)
    return [] if isinstance(served, same) and not (same is int and isinstance(served, bool)) else \
        [f"{path}: {type(served).__name__} served, {type(published).__name__} published"]


class PublishedContract(Base):
    """The real server's payloads, from a SYNTHETIC scenario, against the published user-contract fixtures."""

    def published(self, name: str) -> object:
        return json.loads((FIXTURES / f"user-contract-{name}.json").read_text(encoding="utf-8"))

    def scenario(self) -> dict[str, tuple[str, object]]:
        """fixture name -> (reader, served body), covering every published fixture."""
        served = {"session-signed-in": ("session", self.user.get("/api/session").json()),
                  "session-signed-out": ("session", self.client().get("/api/session").json()),
                  "account": ("account", self.account())}
        expired = self.client("reader-b")
        self.world.clock.advance(hours=13)
        served["session-expired"] = ("session", expired.get("/api/session").json())
        self.world.clock.advance(hours=-13)
        self.user = self.client("reader-a")
        created = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form())
        served["source-created"] = ("sourceCreated", created.json())
        source_id = created.json()["source"]["source_id"]
        prepared = self.prepare(source_id, "high")
        served["analysis-prepared"] = ("prepared", prepared.json())
        analysis_id = prepared.json()["analysis"]["analysis_id"]
        quote = self.quote(analysis_id)
        served["quote"] = ("quote", quote.json())
        served["analysis-quoted"] = ("analysis", self.user.get(f"/api/user/analyses/{analysis_id}").json())
        self.world.provider.gate = threading.Event()
        worker = threading.Thread(target=lambda: self.approve(analysis_id, quote.json()["quote"], client=tab))
        tab = self.twin(self.user)
        worker.start()
        self.world.provider.entered.wait(20)
        served["analysis-running"] = ("analysis", self.user.get(f"/api/user/analyses/{analysis_id}").json())
        self.world.provider.gate.set()
        worker.join(30)
        self.world.provider.gate = None
        duplicate = self.approve(analysis_id, quote.json()["quote"])
        served["run-duplicate"] = ("run", duplicate.json())
        recorded = duplicate.json()["analysis"]
        review = self.user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "human_reviewed",
            "notes": "Synthetic review."})
        served["review-saved"] = ("reviewSaved", review.json())
        served["analysis-recorded"] = ("analysis", self.user.get(f"/api/user/analyses/{analysis_id}").json())
        served["export"] = ("export", self.user.get(f"/api/user/analyses/{analysis_id}/export").json())
        for name, effort, setup in (("analysis-no-finding", "low", {"outcome": "no_additional_finding"}),
                                    ("analysis-declined", "medium", {"outcome": "declined"})):
            for key, value in setup.items():
                setattr(self.world.provider, key, value)
            other = self.prepare(source_id, effort).json()["analysis"]["analysis_id"]
            reply = self.approve(other, self.quote(other).json()["quote"])
            served[name] = ("analysis", {"contract": "user-api-0.4", "analysis": reply.json()["analysis"]})
            if name == "analysis-no-finding":
                served["run-recorded"] = ("run", reply.json())
        ent.set_daily_limit(self.world.accounts, self.world.ids["reader-a"], 10, self.world.ids["admin"], "x",
                            self.world.clock())
        second = self.source(headline="Simulated second source")
        self.world.provider.outcome = "invalid"
        invalid = self.prepare(second, "low").json()["analysis"]["analysis_id"]
        served["analysis-invalid"] = ("analysis", {"contract": "user-api-0.4", "analysis": self.approve(
            invalid, self.quote(invalid).json()["quote"]).json()["analysis"]})
        self.world.provider.status = 529
        failed = self.prepare(second, "high").json()["analysis"]["analysis_id"]
        served["analysis-failed"] = ("analysis", {"contract": "user-api-0.4", "analysis": self.approve(
            failed, self.quote(failed).json()["quote"]).json()["analysis"]})
        self.world.provider.status = 200
        original = ra.keep_record

        def stop(on: str):
            def failing(path, data, secret=None):
                if path.name == on and "attempts" in path.parts:
                    raise OSError("synthetic stop")
                return original(path, data, secret)
            return failing
        for name, effort, on in (("analysis-not-sent", "medium", "request.json"),):
            other = self.prepare(second, effort).json()["analysis"]["analysis_id"]
            quoted = self.quote(other).json()["quote"]
            with patch("second_order.research_analysis.keep_record", side_effect=stop(on)):
                self.approve(other, quoted)
            served[name] = ("analysis", self.user.get(f"/api/user/analyses/{other}").json())
        third = self.source(headline="Simulated third source")
        unresolved = self.prepare(third, "low").json()["analysis"]["analysis_id"]
        quoted = self.quote(unresolved).json()["quote"]
        with patch("second_order.research_analysis.keep_record", side_effect=stop("manifest.json")):
            self.approve(unresolved, quoted)
        self.world.clock.advance(minutes=16)
        served["analysis-unresolved"] = ("analysis", self.user.get(f"/api/user/analyses/{unresolved}").json())
        served["analyses"] = ("analyses", self.user.get("/api/user/analyses").json())
        served["sources"] = ("sources", self.user.get("/api/user/sources").json())
        served["source-detail"] = ("sourceDetail", self.user.get(f"/api/user/sources/{source_id}").json())
        operator = TestClient(create_app(self.world.root / "p", None, intake=self.world.root / "other-intake"),
                              base_url=BASE)
        self.addCleanup(operator.close)
        served["session-local-operator"] = ("session", operator.get("/api/session").json())
        created_user = self.admin().post("/api/admin/users", headers=ADMIN_WRITE, json={  # No daily limit yet.
            "username": "reader-c", "display_name": "reader-c (synthetic)", "role": "user",
            "password": "synthetic-reader-c"}).json()["user"]
        reader_c = TestClient(self.world.app(), base_url=BASE)
        self.addCleanup(reader_c.close)
        reader_c.post("/api/session/login", headers={"Origin": BASE, "Content-Type": "application/json",
                                                     "X-Second-Order-Session": "1"},
                      json={"username": "reader-c", "password": "synthetic-reader-c"})
        self.assertEqual(reader_c.get("/api/session").json()["user"]["user_id"], created_user["user_id"])
        served["account-unavailable"] = ("account", reader_c.get("/api/user/account").json())
        ent.set_daily_limit(self.world.accounts, created_user["user_id"], 1, self.world.ids["admin"], "x",
                            self.world.clock())  # A limit, but no credits ever allocated.
        served["account-unallocated"] = ("account", reader_c.get("/api/user/account").json())
        return served

    def errors(self) -> dict[str, object]:
        source_id = self.source(headline="Simulated error source")
        analysis_id = self.prepare(source_id, "low").json()["analysis"]["analysis_id"]
        bodies = {"not_signed_in": self.client().get("/api/user/account").json(),
                  "forbidden": self.user.get("/api/admin/users").json(),
                  "not_found": self.user.get("/api/user/analyses/unknown").json(),
                  "unsupported_effort": self.prepare(source_id, "max").json(),
                  "quote_mismatch": self.approve(analysis_id, {"quote_id": "q-unknown-0000", "effort": "low",
                                                               "credits": 1}).json(),
                  "invalid_source": self.user.post("/api/user/sources", headers=USER_WRITE,
                                                   json={**source_form(), "published_at": "x"}).json(),
                  "invalid_credentials": self.client().post("/api/session/login", headers={
                      "Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Session": "1"},
                      json={"username": "reader-a", "password": "wrong-password"}).json()}
        ent.set_daily_limit(self.world.accounts, self.world.ids["reader-a"], 0, self.world.ids["admin"], "x",
                            self.world.clock())
        bodies["daily_limit_reached"] = self.approve(analysis_id, self.quote(analysis_id).json()["quote"]).json()
        return bodies

    def test_served_payloads_have_the_published_shape(self):
        served = self.scenario()
        published = {path.stem[len("user-contract-"):] for path in FIXTURES.glob("user-contract-*.json")} - {"errors"}
        self.assertEqual(set(served), published)
        for name, (_, body) in served.items():
            self.assertEqual(key_problems(body, self.published(name)), [], name)
        published_errors = self.published("errors")
        for code, body in self.errors().items():
            self.assertEqual(body["code"], code, body)
            self.assertEqual(key_problems(body, published_errors[code]), [], code)

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run the Client's readers")
    def test_served_payloads_pass_the_clients_own_readers(self):
        payloads = [{"name": name, "reader": reader, "body": body} for name, (reader, body) in self.scenario().items()]
        payloads += [{"name": f"error {code}", "reader": "error", "body": body} for code, body in self.errors().items()]
        path = self.world.root / "served.json"
        path.write_text(json.dumps(payloads), encoding="utf-8")
        run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "tests/user-contract-read.ts",
                              str(path)], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        results = json.loads(run.stdout)
        self.assertEqual([(row["name"], row["problem"]) for row in results if row["problem"]], [])
        self.assertEqual(len(results), len(payloads))


if __name__ == "__main__":
    unittest.main()

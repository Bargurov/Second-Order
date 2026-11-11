"""The operator's selected pilot terms (14 October 2026) as administrator presets, over HTTP.

SYNTHETIC accounts in temporary stores and the fake provider (see account_fakes); every number below except the presets
is a test value. A preset is data an administrator reads and copies into an explicit action: reading it, starting the
server, registering and approving apply nothing. Published as a new policy version with the administrator's own
per-request limit and quote validity, it quotes Low 10, Medium 15, High 20, Extra High 25 and Maximum 30 points for any
accepted source, whatever its length or language, and supersedes earlier quotes, while the planning limit still refuses.
The initial allocation (100 credits once, 3 analyses a day) is two separate explicit actions. The general mechanism
(size rates, other Efforts and extras, limits) keeps its own tests in test_entitlements, test_registration and
test_user_research.
"""
import json
import secrets
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from account_fakes import ADMIN_WRITE, SESSION_WRITE, USER_WRITE, World, bind_to, source_form
from second_order import credit_terms, entitlements as ent, research_analysis as ra

FLAT = {"low": 10, "medium": 15, "high": 20, "xhigh": 25, "max": 30}
SELECTED = {"credits": {"base": 10, "per_1k_input_tokens": 0, "per_1k_output_tokens": 0},
            "efforts": {"low": {"extra_credits": 0}, "medium": {"extra_credits": 5}, "high": {"extra_credits": 10},
                        "xhigh": {"extra_credits": 15}, "max": {"extra_credits": 20}}}
ENGLISH = ("Synthetic text for a check. " * 1_800)[:50_000]
HEBREW = ("טקסט סינתטי לבדיקה. " * 2_700)[:50_000]  # SYNTHETIC: "synthetic text for a check."
EMOJI = "\U0001F4C8" * 50_000
REGISTRANT = {"username": "reader-c", "display_name": "Reader C (synthetic)", "password": "synthetic-reader-c-pass",
              "note": "SYNTHETIC registration for the preset tests."}


def pilot_version(max_request_usd: float = 1.0, quote_valid_seconds: int = 900) -> dict:
    """A new version from the preset, with the administrator's own choices (here test values) for the rest."""
    preset = credit_terms.PILOT_POLICY_PRESET
    return {"model": ra.MODEL, "credits": preset["credits"], "efforts": preset["efforts"],
            "max_request_usd": max_request_usd, "quote_valid_seconds": quote_valid_seconds}


class PilotPreset(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.usage_terms()  # The usage limits are their own explicit policy; these tests are about credits.

    def client(self, username: str | None = None) -> TestClient:
        client = self.world.client(username)
        self.addCleanup(client.close)
        return client

    def publish(self, admin: TestClient, version: dict) -> dict:
        reply = admin.post("/api/admin/policy", headers=ADMIN_WRITE, json={
            "policy": version, "reason": "SYNTHETIC", "idempotency_key": f"policy-{secrets.token_hex(8)}"})
        self.assertEqual(reply.status_code, 201, reply.text)
        return reply.json()["current"]

    def allocate(self, admin: TestClient, user_id: str, credits: int, limit: int) -> None:
        """The two separate actions: a grant, then a daily limit, each with its own reason."""
        grant = admin.post(f"/api/admin/users/{user_id}/credits", headers=ADMIN_WRITE, json={
            "kind": "grant", "credits": credits, "reason": "SYNTHETIC initial grant", "idempotency_key": f"init-{user_id}"})
        self.assertEqual(grant.status_code, 201, grant.text)
        limited = admin.post(f"/api/admin/users/{user_id}/daily-limit", headers=ADMIN_WRITE,
                             json={"limit": limit, "reason": "SYNTHETIC initial limit"})
        self.assertIn(limited.status_code, (200, 201), limited.text)

    def source(self, user: TestClient, text: str) -> str:
        self.world.clock.advance(seconds=1)
        body = json.dumps(source_form(text=text), ensure_ascii=False).encode("utf-8")  # As a browser sends it.
        reply = user.post("/api/user/sources", headers=USER_WRITE, content=body)
        self.assertEqual(reply.status_code, 201, reply.text[:300])
        return reply.json()["source"]["source_id"]

    def quote(self, user: TestClient, source_id: str, effort: str) -> tuple[str, dict]:
        prepared = user.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id, "effort": effort})
        analysis_id = prepared.json()["analysis"]["analysis_id"]
        reply = user.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={})
        return analysis_id, reply.json().get("quote") or reply.json()

    def approve(self, user: TestClient, analysis_id: str, quote: dict):
        return user.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})

    def reasons(self, user: TestClient) -> list[str]:
        return [row["reason"] for row in user.get("/api/user/account").json()["analysis"]["reasons"]]

    # ---------------------------------------------------------------- the presets themselves

    def test_the_presets_are_the_selected_terms_on_the_existing_formula_without_a_monetary_limit(self):
        preset = credit_terms.PILOT_POLICY_PRESET
        self.assertEqual({key: preset[key] for key in ("credits", "efforts")}, SELECTED)
        self.assertEqual(set(preset), {"preset", "label", "note", "credits", "efforts"})  # No model, limit or validity.
        checked = ent.checked_policy(pilot_version())
        for assumed in (100, 29_397, 104_396):  # A tiny request, 50,000 English characters and 50,000 emoji.
            self.assertEqual({effort: ent.credits_for(checked, effort, assumed, ra.MAX_TOKENS)
                              for effort in ent.EFFORT_ORDER}, FLAT)
        self.assertEqual({key: credit_terms.INITIAL_ALLOCATION_PRESET[key] for key in ("credits", "daily_limit")},
                         {"credits": 100, "daily_limit": 3})
        refused = self.client("admin").post("/api/admin/policy", headers=ADMIN_WRITE, json={"policy": {
            key: value for key, value in pilot_version().items() if key != "max_request_usd"}, "reason": "SYNTHETIC",
            "idempotency_key": "policy-without-limit"})
        self.assertEqual((refused.status_code, refused.json()["code"]), (422, "invalid_request"))  # Still required.
        self.assertEqual(ent.policies(self.world.accounts), [])

    def test_presets_are_shown_to_administrators_only_and_reading_starting_or_approving_applies_nothing(self):
        admin, public = self.client("admin"), self.client()
        policy = admin.get("/api/admin/policy").json()
        self.assertEqual((policy["current"], policy["versions"], policy["presets"]),
                         (None, [], [credit_terms.PILOT_POLICY_PRESET]))
        users = admin.get("/api/admin/users").json()
        self.assertEqual(users["allocation_presets"], [credit_terms.INITIAL_ALLOCATION_PRESET])
        readers = [row for row in users["users"] if row["role"] == "user"]
        self.assertTrue(readers and all(not row["allocated"] and row["credits"]["available"] == 0 and
                                        row["daily"]["limit"] is None for row in readers))
        for path in ("/api/admin/policy", "/api/admin/users"):
            self.assertEqual(self.client("reader-a").get(path).status_code, 403, path)
        self.assertEqual(public.get("/api/public/credit-terms").json()["state"], "no_credit_policy")
        self.assertEqual(public.post("/api/public/registrations", headers=SESSION_WRITE, json=REGISTRANT).status_code,
                         201)
        registrant = next(row["user_id"] for row in admin.get("/api/admin/users").json()["users"]
                          if row["username"] == "reader-c")
        decided = admin.post(f"/api/admin/registrations/{registrant}/decision", headers=ADMIN_WRITE,
                             json={"decision": "approve", "reason": "SYNTHETIC approval"})
        self.assertEqual(decided.status_code, 201, decided.text)
        self.client("admin").get("/api/admin/policy")  # Another server start and read.
        self.assertEqual(ent.policies(self.world.accounts), [])
        self.assertEqual(ent.ledger(self.world.accounts, None), [])
        row = next(row for row in admin.get("/api/admin/users").json()["users"] if row["username"] == "reader-c")
        self.assertEqual((row["status"], row["allocated"], row["daily"]["limit"]), ("active", False, None))

    # ---------------------------------------------------------------- published explicitly

    def test_published_with_the_administrators_limit_it_quotes_flat_points_for_any_accepted_source(self):
        admin = self.client("admin")
        preview = admin.post("/api/admin/policy/preview", headers=ADMIN_WRITE, json={"policy": pilot_version()}).json()
        self.assertEqual([[quote["credits"] for quote in example["quotes"]] for example in preview["examples"]],
                         [list(FLAT.values())] * 3)
        self.assertEqual(ent.policies(self.world.accounts), [])  # A preview records nothing.
        self.publish(admin, pilot_version())
        terms = self.client().get("/api/public/credit-terms").json()
        self.assertEqual((terms["state"], [option["effort"] for option in terms["efforts"]]),
                         ("configured", list(FLAT)))
        self.assertEqual([[quote["credits"] for quote in example["quotes"]] for example in terms["examples"]],
                         [list(FLAT.values())] * 3)
        self.assertIn("does not change the quote", terms["size_note"])
        self.allocate(admin, self.world.ids["reader-a"], 100, 3)
        user = self.client("reader-a")
        short = source_form()["source_text"]
        for name, text in (("short English", short), ("English", ENGLISH), ("Hebrew", HEBREW), ("emoji", EMOJI)):
            source_id = self.source(user, text)
            quoted = {effort: self.quote(user, source_id, effort)[1]["credits"] for effort in FLAT}
            self.assertEqual(quoted, FLAT, name)
        self.assertEqual(self.world.provider.requests, [])
        self.assertEqual(user.get("/api/user/account").json()["credits"], {"available": 100, "held": 0})

    def test_an_approved_registrant_is_allocated_only_by_two_explicit_actions_and_runs_once_at_the_flat_quote(self):
        admin, public = self.client("admin"), self.client()
        self.publish(admin, pilot_version())
        public.post("/api/public/registrations", headers=SESSION_WRITE, json=REGISTRANT)
        registrant = next(row["user_id"] for row in admin.get("/api/admin/users").json()["users"]
                          if row["username"] == "reader-c")
        admin.post(f"/api/admin/registrations/{registrant}/decision", headers=ADMIN_WRITE,
                   json={"decision": "approve", "reason": "SYNTHETIC approval"})
        user = self.client()
        signed_in = user.post("/api/session/login", headers=SESSION_WRITE, json={
            "username": "reader-c", "password": REGISTRANT["password"]})
        self.assertEqual(signed_in.status_code, 200)
        bind_to(user, signed_in)
        self.assertEqual(self.reasons(user), ["no_daily_limit", "no_credits_allocated"])
        analysis_id, quote = self.quote(user, self.source(user, source_form()["source_text"]), "high")
        self.assertEqual(quote["credits"], 20)
        early = self.approve(user, analysis_id, quote)
        self.assertEqual((early.status_code, early.json()["code"]), (409, "no_daily_limit"))
        preset = admin.get("/api/admin/users").json()["allocation_presets"][0]
        grant = admin.post(f"/api/admin/users/{registrant}/credits", headers=ADMIN_WRITE, json={
            "kind": "grant", "credits": preset["credits"], "reason": "SYNTHETIC initial grant",
            "idempotency_key": "initial-reader-c"})
        self.assertEqual(grant.status_code, 201, grant.text)
        self.assertEqual(self.reasons(user), ["no_daily_limit"])  # The grant alone sets no limit.
        admin.post(f"/api/admin/users/{registrant}/daily-limit", headers=ADMIN_WRITE,
                   json={"limit": preset["daily_limit"], "reason": "SYNTHETIC initial limit"})
        account = user.get("/api/user/account").json()
        self.assertEqual((self.reasons(user), account["credits"], account["daily"]["limit"]),
                         ([], {"available": 100, "held": 0}, 3))
        run = self.approve(user, analysis_id, quote)
        self.assertEqual(run.status_code, 201, run.text)
        self.assertEqual((run.json()["analysis"]["charge"]["credits_charged"], run.json()["account"]["credits"],
                          run.json()["account"]["daily"]["used"]), (20, {"available": 80, "held": 0}, 1))
        self.assertEqual(len(self.world.provider.requests), 1)
        again = admin.post(f"/api/admin/users/{registrant}/credits", headers=ADMIN_WRITE, json={
            "kind": "grant", "credits": 100, "reason": "SYNTHETIC repeated", "idempotency_key": "initial-reader-c"})
        self.assertEqual(user.get("/api/user/account").json()["credits"]["available"], 80, again.text)  # Once.
        row = next(row for row in admin.get("/api/admin/users").json()["users"] if row["username"] == "reader-c")
        self.assertEqual((row["allocated"], row["credits"]["granted"], row["credits"]["charged"]), (True, 100, 20))

    def test_publishing_it_supersedes_earlier_quotes_keeps_balances_and_the_planning_limit_still_refuses(self):
        self.world.standard_terms(credits=40, limit=3)  # An earlier, size-rated synthetic policy and allocations.
        user, admin = self.client("reader-a"), self.client("admin")
        analysis_id, before = self.quote(user, self.source(user, ENGLISH), "high")
        self.assertNotEqual(before["credits"], 20)  # The earlier policy counted the source's size.
        ledger = ent.ledger(self.world.accounts, None)
        self.publish(admin, pilot_version(max_request_usd=0.3))
        stale = self.approve(user, analysis_id, before)
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "quote_superseded"))
        self.assertEqual(self.quote(user, self.source(user, ENGLISH), "high")[1]["credits"], 20)
        _, over = self.quote(user, self.source(user, EMOJI), "high")  # Planning estimate about 0.37 USD.
        self.assertEqual(over.get("code"), "request_over_budget")
        self.assertEqual(ent.ledger(self.world.accounts, None), ledger)  # A new version changes no balance.
        self.assertEqual(user.get("/api/user/account").json()["credits"], {"available": 40, "held": 0})
        self.assertEqual(self.world.provider.requests, [])


if __name__ == "__main__":
    unittest.main()

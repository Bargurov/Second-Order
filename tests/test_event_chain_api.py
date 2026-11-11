"""The event-chain routes (event_chain_api) on a SYNTHETIC world: a read writes nothing, the two owner writes save one
record each, every refusal has its exact reply shape (a 409 is exactly {detail, latest}), and in accounts mode the
administrator's identity is recorded. The replies the frontend reader is tested against are captured here
(SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 writes them; otherwise they are compared by parsed JSON)."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import account_fakes  # noqa: E402
import event_chain_fakes as fakes  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from second_order import event_chain_evidence as evidence, event_chain_records as records  # noqa: E402
from second_order.api import create_app  # noqa: E402
from test_event_chain_view import (fcx_file, flip_byte, read_json, shorter_version_two, tree,  # noqa: E402
                                   write_json)

ROOT = HERE.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "x-second-order-event-chain": "1", "Content-Type": "application/json"}
FIXED = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
PATH = "/api/theses/copper/event-chains"
CHAIN = fakes.WORLD_CHAIN
NOTE = "Label step 3 as the company's expectation, not a result."
LINE = "Test line: the company expects 85% in 2026, see step 3."
STEP_FIVE = "Test line: the company expects 85% in 2026, see step 5."
MASKED_STEP_FIVE = "Test line: the company expects [figure withheld] in [figure withheld], see step 5."
CITED = "k25-mud-rush-85pct"
EDITED = "Synthetic: an edited quote of the record."


class Api(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folders = fakes.write_world(self.root / "world")
        self.pinned = evidence.pin(fakes.world_chain(None), self.folders)
        fakes.write_chain(self.folders.theses, CHAIN, [fakes.world_chain(self.pinned)], ["2026-11-09"])

    def options(self):
        f = self.folders
        return dict(theses=f.theses, thesis_sources_dir=f.thesis_sources, metals_dir=f.metals,
                    metals_sources_dir=f.metals_sources, company_research_dir=f.research,
                    company_sources_dir=f.company_sources, event_chain_records=f.records, copper_clock=lambda: FIXED)

    def app(self) -> TestClient:
        r = self.root
        return TestClient(create_app(r / "prepared", None, r / "drafts", r / "reviews", r / "intake", r / "attempts",
                                     inbox=r / "inbox", triage=r / "triage", links=r / "links", market=r / "market",
                                     related_records=r / "related", enrichment_sources=r / "es",
                                     snapshot_sources=r / "snap", snapshot_index=r / "index", **self.options()),
                          base_url=BASE)

    @staticmethod
    def chain(client) -> dict:
        return client.get(PATH).json()["chains"][0]

    @staticmethod
    def post(client, kind, body, headers=HEADERS, chain=CHAIN):
        return client.post(f"{PATH}/{chain}/{kind}", content=json.dumps(body).encode("utf-8"), headers=headers)

    def review_body(self, client, status="approved", notes="Checked each step.", **over):
        binding = self.chain(client)["binding"]
        body = {"parent_review_id": binding["parent_review_id"], "chain_sha256": binding["chain_sha256"],
                "status": status, "notes": notes}
        return body | over

    def reading_body(self, client, **over):
        binding = self.chain(client)["binding"]
        body = {"parent_reading_id": binding["parent_reading_id"], "chain_sha256": binding["chain_sha256"],
                "approval_id": binding["approval_id"], "short_term": "not_sure", "long_term": "neither", "line": LINE}
        return body | over

    def approve_and_read(self, client):
        self.assertEqual(self.post(client, "reviews", self.review_body(client, "needs_revision", NOTE)).status_code, 201)
        self.assertEqual(self.post(client, "reviews", self.review_body(client)).status_code, 201)
        return self.post(client, "readings", self.reading_body(client))

    def edit_facts(self):
        path = self.folders.research / "facts.json"
        original = path.read_bytes()
        data = read_json(path)
        next(i for i in data["passages"] if i["id"] == CITED).update(quote=EDITED, printed_page="24")
        write_json(path, data)
        return original


class Tests(Api):
    def test_get_serves_and_writes_nothing(self):
        before = tree(self.root / "world")
        with self.app() as client:
            reply = client.get(PATH)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual([item["id"] for item in reply.json()["chains"]], [CHAIN])
            self.assertEqual(reply.json()["view_version"], "event-chains-view-0.1")
        self.assertEqual(before, tree(self.root / "world"))
        self.assertFalse(self.folders.records.exists())

    def test_get_503_without_a_published_thesis(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.folders = self.folders.__class__(**{**self.folders.__dict__, "theses": empty})
        with self.app() as client:
            reply = client.get(PATH)
        self.assertEqual(reply.status_code, 503)
        self.assertEqual(list(reply.json()), ["detail"])

    def test_review_then_reading_201(self):
        with self.app() as client:
            first = self.post(client, "reviews", self.review_body(client, "needs_revision", NOTE))
            self.assertEqual((first.status_code, list(first.json())), (201, ["record"]))
            self.assertEqual(first.json()["record"]["account"], {"user_id": "local-operator", "username": "operator"})
            self.assertEqual(self.post(client, "reviews", self.review_body(client)).status_code, 201)
            reading = self.post(client, "readings", self.reading_body(client))
            self.assertEqual((reading.status_code, list(reading.json())), (201, ["record"]))
            self.assertEqual(reading.json()["record"]["line"], LINE)
        written = sorted(p.relative_to(self.folders.records).as_posix() for p in self.folders.records.rglob("*.json"))
        self.assertEqual(written, [f"readings/{CHAIN}/000001.json", f"reviews/{CHAIN}/000001.json",
                                   f"reviews/{CHAIN}/000002.json"])

    def test_local_write_checks(self):
        with self.app() as client:
            body = self.review_body(client)
            no_header = {k: v for k, v in HEADERS.items() if k != "x-second-order-event-chain"}
            self.assertEqual(self.post(client, "reviews", body, no_header).status_code, 403)
            foreign = {**HEADERS, "Origin": "http://evil.example"}
            self.assertEqual(self.post(client, "reviews", body, foreign).status_code, 403)
            self.assertEqual(client.post(f"{PATH}/{CHAIN}/reviews", content=b"x=1",
                                         headers={**HEADERS, "Content-Type": "text/plain"}).status_code, 415)
            self.assertEqual(client.post(f"{PATH}/{CHAIN}/reviews", content=b"x" * 16_385,
                                         headers=HEADERS).status_code, 413)
        self.assertFalse(self.folders.records.exists())

    def assert_409(self, reply, latest):
        self.assertEqual(reply.status_code, 409)
        body = reply.json()
        self.assertEqual(set(body), {"detail", "latest"})
        self.assertIsInstance(body["detail"], str)
        self.assertEqual(body["latest"], latest)

    def test_409s(self):
        with self.app() as client:
            latest = self.post(client, "reviews", self.review_body(client, "needs_revision", NOTE)) \
                .json()["record"]["review_id"]
            self.assert_409(self.post(client, "reviews", self.review_body(client, parent_review_id=None)), latest)
            self.assert_409(self.post(client, "reviews", self.review_body(client, chain_sha256="0" * 64)), latest)
            self.edit_facts()
            changed = self.post(client, "reviews", self.review_body(client, notes="Checked each step again."))
            self.assertEqual(self.chain(client)["state"], "evidence_changed")
            self.assert_409(changed, latest)
        self.assertEqual(len(list(self.folders.records.rglob("*.json"))), 1)

    def test_422(self):
        with self.app() as client:
            reply = self.post(client, "reviews", self.review_body(client, status="maybe"))
            self.assertEqual((reply.status_code, list(reply.json())), (422, ["detail"]))
            reply = self.post(client, "reviews", self.review_body(client, notes="x" * 1_001))
            self.assertEqual((reply.status_code, list(reply.json())), (422, ["detail"]))
            reply = client.post(f"{PATH}/{CHAIN}/reviews", content=b"[]", headers=HEADERS)
            self.assertEqual((reply.status_code, list(reply.json())), (422, ["detail"]))
        self.assertFalse(self.folders.records.exists())

    def test_a_digit_of_another_script_is_refused_and_a_record_holding_one_is_masked_as_the_page_reads_it(self):
        """ "see step ٠3": the server once read step 3 and kept the text while the page's reader saw a bare 3 and
        refused the whole reply. Only the digits 0 to 9 are read now, on both sides."""
        with self.app() as client:
            refused = self.post(client, "reviews", self.review_body(client, "needs_revision", "see step ٠3"))
            self.assertEqual((refused.status_code, refused.json()), (422, {
                "detail": "the notes hold the digit '٠'; write numbers with the digits 0 to 9"}))
            self.assertFalse(self.folders.records.exists())
            # A record that holds one anyway, written as the app wrote records before this rule, with its content id.
            saved = self.post(client, "reviews", self.review_body(client, "needs_revision", "see step 3"))
            self.assertEqual(saved.status_code, 201)
            path = self.folders.records / "reviews" / CHAIN / "000001.json"
            record = read_json(path) | {"notes": "see step ٠3"}
            record["review_id"] = records.record_id("reviews", record)
            write_json(path, record)
            self.assertEqual(self.chain(client)["history"]["reviews"][0]["notes"], "see step ٠3")
            flip_byte(fcx_file(self.folders, "10q-2026q3"))
            served = self.chain(client)["history"]["reviews"][0]
            # The same text frontend/tests/eventChains.test.ts reads in a record whose basis fails.
            self.assertEqual((served["notes"], served["masked"]), ("see step ٠[figure withheld]", True))

    def test_the_line_may_state_the_change_the_card_shows_for_the_target(self):
        """The card shows the target's measure with its years and the computed change. The thesis lets its own author
        text state these (thesis_sections.shown and the change), and the line is held to that same rule."""
        with self.app() as client:
            self.assertEqual(self.post(client, "reviews", self.review_body(client)).status_code, 201)
            target = self.chain(client)["target"]
            self.assertEqual((target["change_pct"], target["measure"]["latest"]["year"]), ("0.9", "2024"))
            saved = self.post(client, "readings",
                              self.reading_body(client, line="Test line: a change of 0.9% in 2024, see step 3."))
            self.assertEqual(saved.status_code, 201, saved.json())
            other = self.post(client, "readings", self.reading_body(client, line="Test line: a change of 0.8%."))
            self.assertEqual((other.status_code, other.json()),
                             (422, {"detail": "the line states figures its sources do not: ['8']"}))

    def test_a_forged_record_leaves_the_read_200_and_refuses_the_save_500(self):
        with self.app() as client:
            self.assertEqual(self.approve_and_read(client).status_code, 201)
            path = self.folders.records / "reviews" / CHAIN / "000002.json"
            record = read_json(path)
            record.pop("notes")
            record["review_id"] = records.record_id("reviews", record)
            write_json(path, record)
            reply = client.get(PATH)
            self.assertEqual(reply.status_code, 200)
            history = reply.json()["chains"][0]["history"]
            self.assertEqual((history["state"], history["reviews"], history["readings"]), ("invalid", [], []))
            self.assertIn("cannot be verified", history["problem"])
            saved = self.post(client, "reviews", self.review_body(client, parent_review_id=record["review_id"],
                                                                  notes="Checked again."))
            self.assertEqual((saved.status_code, list(saved.json())), (500, ["detail"]))
            self.assertIn("cannot be verified", saved.json()["detail"])
        self.assertEqual(len(list(self.folders.records.rglob("*.json"))), 3)

    def test_404_unknown_chain(self):
        with self.app() as client:
            body = self.review_body(client)
            reply = self.post(client, "reviews", body, chain="no-such-chain")
            self.assertEqual((reply.status_code, list(reply.json())), (404, ["detail"]))
            self.assertEqual(self.post(client, "readings", body, chain="no-such-chain").status_code, 404)


class Accounts(Api):
    def sign_in(self, client, username):
        login = client.post("/api/session/login", headers=account_fakes.SESSION_WRITE,
                            json={"username": username, "password": account_fakes.PASSWORDS[username]})
        self.assertEqual(login.status_code, 200)

    def test_accounts_mode_requires_binding_428_and_records_the_identity(self):
        world = account_fakes.World(self.root / "accounts-world")
        admin, reader = world.ids["admin"], world.ids["reader-a"]
        write = {**HEADERS, "Origin": account_fakes.BASE, "X-Second-Order-Admin": "1"}
        with self.app() as local:
            body = self.review_body(local)  # The binding of a chain nobody has reviewed yet.
        with TestClient(world.app(**self.options()), base_url=account_fakes.BASE) as client:
            self.sign_in(client, "admin")
            unbound = self.post(client, "reviews", body, write)
            self.assertEqual(unbound.status_code, 428)
            self.assertEqual(unbound.json()["code"], "account_binding_required")
            self.assertEqual(unbound.json()["detail"], "This request did not say which account it was made for, so "
                                                      "nothing was changed. Reload the page and try again.")
            other = self.post(client, "reviews", body, {**write, account_fakes.ACCOUNT: reader})
            self.assertEqual((other.status_code, other.json()["code"]), (401, "account_changed"))
            self.assertFalse(self.folders.records.exists())
            right = self.post(client, "reviews", body, {**write, account_fakes.ACCOUNT: admin})
            self.assertEqual(right.status_code, 201)
            self.assertEqual(right.json()["record"]["account"], {"user_id": admin, "username": "admin"})
        with TestClient(world.app(**self.options()), base_url=account_fakes.BASE) as user:
            self.sign_in(user, "reader-a")
            refused = self.post(user, "reviews", body, {**write, account_fakes.ACCOUNT: reader})
            self.assertEqual((refused.status_code, refused.json()["code"]), (403, "forbidden"))
        self.assertEqual(len(list(self.folders.records.rglob("*.json"))), 1)


class Fixtures(Api):
    def test_frontend_fixtures(self):
        """The replies the frontend reader is tested against: captured from this producer, never hand-written."""
        served = {}
        with self.app() as client:
            self.assertEqual(self.approve_and_read(client).status_code, 201)
            served["event-chains-available.json"] = client.get(PATH).json()
            original = self.edit_facts()
            served["event-chains-evidence-changed.json"] = client.get(PATH).json()
            (self.folders.research / "facts.json").write_bytes(original)
            quarter = flip_byte(fcx_file(self.folders, "10q-2026q3"))
            served["event-chains-withheld.json"] = client.get(PATH).json()
            # A second reading on version 1 names its step 5; version 2 has four steps; the 10-Q fails again.
            fcx_file(self.folders, "10q-2026q3").write_bytes(quarter)
            self.assertEqual(self.post(client, "readings", self.reading_body(client, line=STEP_FIVE)).status_code, 201)
            fakes.write_chain(self.folders.theses, CHAIN, [fakes.world_chain(self.pinned),
                                                           shorter_version_two(self.folders)], ["2026-11-09"] * 2)
            flip_byte(fcx_file(self.folders, "10q-2026q3"))
            served["event-chains-two-versions.json"] = client.get(PATH).json()
        states = {name: reply["chains"][0]["state"] for name, reply in served.items()}
        self.assertEqual(states, {"event-chains-available.json": "available",
                                  "event-chains-evidence-changed.json": "evidence_changed",
                                  "event-chains-withheld.json": "needs_revalidation",
                                  "event-chains-two-versions.json": "needs_revalidation"})
        two = served["event-chains-two-versions.json"]["chains"][0]
        self.assertEqual(([item["steps"] for item in two["history"]["versions"]], len(two["steps"])), ([5, 4], 4))
        self.assertEqual([(item["line"], item["masked"], item["basis"]["chain"]["version"])
                          for item in two["history"]["readings"]],
                         [(LINE.replace("85%", "[figure withheld]").replace("2026", "[figure withheld]"), True, 1),
                          (MASKED_STEP_FIVE, True, 1)])
        for name, reply in served.items():
            text = json.dumps(reply, ensure_ascii=False)
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn(tempfile.gettempdir(), text, name)
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            else:
                self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_event_chain_api.py")


if __name__ == "__main__":
    unittest.main()

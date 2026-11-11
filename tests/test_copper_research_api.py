"""The copper research routes (copper_research_api) on the SYNTHETIC world: the read writes nothing, a note is one new
record, every refusal has its exact reply shape, and the view follows the documents' states. The replies the frontend
reader is tested against are captured here (SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 writes them; otherwise they are
compared by parsed JSON). Every note text is a marked test value, never a view of the owner's."""
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
from second_order import copper_research_view as research_view, publication_comparison as pc  # noqa: E402
from test_event_chain_api import BASE, FIXTURES, WRITE_FIXTURES, Api  # noqa: E402
from test_event_chain_view import fcx_file, flip_byte, read_json, tree, write_json  # noqa: E402

PATH = "/api/theses/copper/research"
CHAIN_PATH = "/api/theses/copper/event-chains"
HEADERS = {"Origin": BASE, "x-second-order-research-note": "1", "Content-Type": "application/json"}
COMPARISON = fakes.WORLD_COMPARISON
CHAIN = fakes.WORLD_CHAIN
NOTE = "TEST VALUE, not the owner's view: the two lines may not be one measure; 85% against 80%."
EXPECTATION = {"text": "TEST VALUE, not the owner's view: prices will rise by 5% before the next report.",
               "check_by": "2027-02-28"}
QUESTION = "TEST VALUE: does the next annual report keep the 80% line?"


class Research(Api):
    def setUp(self):
        super().setUp()
        self.notes = self.root / "research-notes"
        fakes.write_comparison(self.folders.theses, COMPARISON,
                               [dict(fakes.world_comparison(None),
                                     evidence=pc.pin(fakes.world_comparison(None), self.folders))], ["2026-11-10"])

    def options(self):
        return super().options() | {"research_notes_dir": self.notes}

    @staticmethod
    def view(client) -> dict:
        reply = client.get(PATH)
        assert reply.status_code == 200, reply.text
        return reply.json()

    def body(self, client, kind="comparison", ident=COMPARISON, **over) -> dict:
        shown = self.view(client)
        subject = next(item for item in shown["subjects"] if (item["kind"], item["id"]) == (kind, ident))
        return {"parent_note_id": shown["notes"]["latest"], "about": {"kind": kind, "id": ident},
                "subject_sha256": subject["sha256"], "follows": None, "text": NOTE, "expectation": None,
                "question": None} | over

    @staticmethod
    def post(client, body, headers=HEADERS):
        return client.post(f"{PATH}/notes", content=json.dumps(body).encode("utf-8"), headers=headers)

    def files(self) -> list[str]:
        return sorted(path.name for path in self.notes.iterdir()) if self.notes.is_dir() else []


class Read(Research):
    def test_get_serves_the_desk_the_comparison_and_no_notes_and_writes_nothing(self):
        before = tree(self.root / "world")
        with self.app() as client:
            shown = self.view(client)
        self.assertEqual((shown["view_version"], shown["provider_called"]), ("copper-research-view-0.1", False))
        pages = {item["id"]: item for item in shown["desk"]["pages"]}
        self.assertEqual(list(pages), ["thesis", "tools", "fcx", "metals", "events"])
        self.assertEqual([pages[key]["path"] for key in pages],
                         ["/theses/copper", "/theses/copper/tools", "/companies/fcx", "/metals",
                          "/theses/copper/events"])
        self.assertRegex(pages["thesis"]["status"], r"^Version 1, published \d{4}-\d{2}-\d{2}\.$")
        self.assertEqual(pages["fcx"]["status"],
                         "4 documents, 4 verified on this machine; the latest is dated 2026-11-06.")
        self.assertEqual(pages["events"]["status"], "1 chain: 1 awaiting your review.")
        self.assertEqual((pages["tools"]["status"], pages["metals"]["status"]), (None, None))
        self.assertEqual({item["problem"] for item in pages.values()}, {None})
        self.assertEqual([(item["kind"], item["id"], item["state"]) for item in shown["subjects"]],
                         [("thesis", "copper", "available"), ("chain", CHAIN, "available"),
                          ("comparison", COMPARISON, "available")])
        self.assertEqual(shown["notes"], {"state": "valid", "problem": None, "latest": None, "items": []})
        self.assertEqual(before, tree(self.root / "world"))
        self.assertFalse(self.notes.exists())

    def test_a_comparison_shows_both_lines_as_written_and_never_a_change(self):
        with self.app() as client:
            found = self.view(client)["comparisons"][0]
        self.assertEqual((found["id"], found["state"], found["reasons"], found["historical"]),
                         (COMPARISON, "available", [], True))
        self.assertEqual((found["ai_assisted"], found["prepared_by"]), (True, "assistant"))
        self.assertEqual(found["historical_note"],
                         "Historical: both publications were already retained when this comparison was prepared.")
        self.assertEqual([(found[side]["ref"], found[side]["dated"], found[side]["dated_as"], found[side]["state"])
                          for side in ("earlier", "later")],
                         [("fcx:10k-2025", "2026-02-13", "signature date", "verified"),
                          ("fcx:10q-2026q3", "2026-11-06", "signature date", "verified")])
        first, second = found["rows"]
        self.assertEqual((first["same_measure"], first["sentence"]),
                         ("not_established", "No retained source establishes that the two lines measure the same "
                                             "thing. No change is computed between them."))
        self.assertEqual((second["same_measure"], second["sentence"], second["note"]),
                         ("not_applicable", "Two statements, each shown as written.", None))
        self.assertIn("85%", first["earlier"]["quote"])
        self.assertIn("80%", first["later"]["quote"])
        self.assertEqual((first["earlier"]["state"], first["later"]["document"]["name"]),
                         ("verified", "the FCX 10-Q"))
        # The owner's clarification: a row carries each line's wording, place and date and nothing derived from both.
        self.assertEqual(sorted(first), ["earlier", "id", "label", "later", "note", "note_withheld", "same_measure",
                                         "sentence"])
        figures = {item["id"]: item for item in found["prices"]["figures"]}
        self.assertEqual((figures["k25-copper-realized-price-fy2025"]["display"],
                          figures["k25-copper-realized-price-fy2025"]["period"]),
                         ("4.75", {"label": "FY2025", "start": "2025-01-01", "end": "2025-12-31"}))
        self.assertEqual(figures["q3-cu-realized-price-q3-2026"]["period"]["end"], "2026-09-30")
        self.assertEqual((found["prices"]["covered_to"], found["prices"]["text"]),
                         ("2026-09-30", "Retained prices cover up to 2026-09-30. No retained price covers a later "
                                        "date."))

    def test_a_price_of_another_document_is_never_shown(self):
        """A note's basis pins the two publications; a figure of any other document could not be masked with them."""
        version = dict(fakes.world_comparison(None), evidence=pc.pin(fakes.world_comparison(None), self.folders))
        version["prices"] = [*version["prices"], "r3-cu-price-q3-2026"]  # Written past the pin command's refusal.
        fakes.write_comparison(self.folders.theses, COMPARISON, [version], ["2026-11-10"])
        with self.app() as client:
            figures = {item["id"]: item for item in self.view(client)["comparisons"][0]["prices"]["figures"]}
        other = figures["r3-cu-price-q3-2026"]
        self.assertEqual((other["state"], other["display"], other["period"], other["problem"]),
                         ("withheld", None, None, "Not shown: the record is not from one of the two publications"))
        self.assertEqual(figures["q3-cu-realized-price-q3-2026"]["state"], "available")


class Write(Research):
    def test_a_note_is_saved_once_and_read_back_with_its_basis_and_its_real_time(self):
        with self.app() as client:
            saved = self.post(client, self.body(client, expectation=EXPECTATION, question=QUESTION))
            self.assertEqual((saved.status_code, list(saved.json())), (201, ["record"]))
            record = saved.json()["record"]
            self.assertEqual((record["saved_at"], record["account"]),
                             ("2026-11-10T09:00:00+00:00", {"user_id": "local-operator", "username": "operator"}))
            self.assertEqual(sorted(record["basis"]), ["comparison", "documents", "evidence_sha256"])
            self.assertEqual([item["ref"] for item in record["basis"]["documents"]],
                             ["fcx:10k-2025", "fcx:10q-2026q3"])
            self.assertEqual(self.files(), ["000001.json"])
            follow = self.post(client, self.body(client, follows=record["note_id"], text="TEST VALUE: a later note."))
            self.assertEqual(follow.status_code, 201)
            first, second = self.view(client)["notes"]["items"]
        self.assertEqual((first["state"], first["differs"], first["masked"], first["text"]),
                         ("current", [], False, NOTE))
        self.assertEqual(first["hindsight"], "Written after both publications were known: saved on 2026-11-10, the "
                                             "later publication is dated 2026-11-06.")
        self.assertEqual(first["expectation"], {**EXPECTATION, "state": "not_yet_checked",
                                                "status": "Not yet checked: nothing retained after this note was "
                                                          "saved has been compared with it."})
        self.assertEqual((first["question"], first["followed_by"], second["follows"]),
                         (QUESTION, second["note_id"], first["note_id"]))
        self.assertEqual((first["subject_title"], [item["state"] for item in first["basis_documents"]]),
                         ("Synthetic: the annual report against the quarterly report", ["verified", "verified"]))

    def test_notes_on_a_chain_and_on_the_thesis_bind_their_own_basis(self):
        with self.app() as client:
            chain = self.post(client, self.body(client, "chain", CHAIN, text="TEST VALUE: see step 3 and the 85%."))
            self.assertEqual(chain.status_code, 201, chain.text)
            self.assertEqual(sorted(chain.json()["record"]["basis"]),
                             ["chain", "documents", "evidence_sha256", "thesis"])
            thesis = self.post(client, self.body(client, "thesis", "copper", text="TEST VALUE: on the whole thesis."))
            self.assertEqual(thesis.status_code, 201, thesis.text)
            self.assertEqual(sorted(thesis.json()["record"]["basis"]), ["documents", "thesis"])
            self.assertTrue(all(item["ref"].startswith("copper:")
                                for item in thesis.json()["record"]["basis"]["documents"]))
            self.assertEqual([item["state"] for item in self.view(client)["notes"]["items"]], ["current", "current"])

    def test_a_changed_document_withholds_its_lines_masks_note_figures_and_closes_saving(self):
        with self.app() as client:
            self.assertEqual(self.post(client, self.body(client, expectation=EXPECTATION, question=QUESTION))
                             .status_code, 201)
            self.assertEqual(self.post(client, self.body(client, "chain", CHAIN,
                                                         text="TEST VALUE: see step 3 and the 85%.")).status_code, 201)
            stale = self.body(client)
            before = tree(self.root)
            quarter = fcx_file(self.folders, "10q-2026q3")
            original = flip_byte(quarter)
            shown = self.view(client)
            found = shown["comparisons"][0]
            self.assertEqual((found["state"], found["later"]["state"]), ("needs_revalidation", "changed"))
            row = found["rows"][0]
            self.assertEqual((row["earlier"]["state"], row["later"]["state"], row["later"]["quote"]),
                             ("verified", "changed", None))
            self.assertIn("no longer matches its acquisition record", row["later"]["problem"])
            # The assistant's note says what each line states, so it is withheld with a withheld line, digits or not.
            self.assertEqual((row["note"], row["note_withheld"]), (None, True))
            self.assertEqual((found["rows"][1]["note"], found["rows"][1]["note_withheld"]), (None, False))
            self.assertNotIn("80%", json.dumps(found, ensure_ascii=False))
            figures = {item["id"]: item for item in found["prices"]["figures"]}
            self.assertEqual((figures["q3-cu-realized-price-q3-2026"]["state"],
                              figures["q3-cu-realized-price-q3-2026"]["display"],
                              figures["k25-copper-realized-price-fy2025"]["state"]), ("withheld", None, "available"))
            self.assertEqual(found["prices"]["covered_to"], "2025-12-31")
            first, second = shown["notes"]["items"]
            self.assertEqual((first["masked"], first["state"]), (True, "earlier_basis"))
            masked = "[figure withheld]"
            self.assertEqual(first["text"], NOTE.replace("85%", masked).replace("80%", masked))
            self.assertEqual(first["expectation"]["text"], EXPECTATION["text"].replace("5%", "[figure withheld]"))
            self.assertEqual(first["question"], QUESTION.replace("80%", "[figure withheld]"))
            self.assertEqual(first["expectation"]["check_by"], "2027-02-28")  # A date the owner set, not a figure.
            self.assertEqual(second["text"], "TEST VALUE: see step 3 and the [figure withheld].")
            refused = self.post(client, stale)
            self.assertEqual((refused.status_code, set(refused.json())), (409, {"detail", "latest"}))
            self.assertEqual(refused.json()["latest"], second["note_id"])
            self.assertIn("is not available", refused.json()["detail"])
            quarter.write_bytes(original)
            self.assertEqual(before, tree(self.root))  # Nothing was written in between.
            again = self.view(client)
            self.assertEqual((again["comparisons"][0]["state"], again["notes"]["items"][0]["text"]),
                             ("available", NOTE))

    def test_refusals_have_their_exact_shapes(self):
        with self.app() as client:
            body = self.body(client)
            for change, status in (({"about": {"kind": "comparison", "id": "no-such-comparison"}}, 404),
                                   ({"about": {"kind": "chain", "id": "no-such-chain"}}, 404),
                                   ({"about": {"kind": "thesis", "id": "nickel"}}, 404),
                                   ({"text": "x" * 2001}, 422),
                                   ({"expectation": {"text": "TEST VALUE.", "check_by": "2026-11-09"}}, 422),
                                   ({"follows": "f" * 64}, 422)):
                reply = self.post(client, body | change)
                self.assertEqual((reply.status_code, list(reply.json())), (status, ["detail"]), change)
            for reply in (self.post(client, body | {"parent_note_id": "0" * 64}),
                          self.post(client, body | {"subject_sha256": "0" * 64})):
                self.assertEqual((reply.status_code, reply.json()["latest"], set(reply.json())),
                                 (409, None, {"detail", "latest"}))
            extra = client.post(f"{PATH}/notes", content=json.dumps(body | {"saved_at": "2026-01-01"}).encode(),
                                headers=HEADERS)
            self.assertEqual(extra.status_code, 422)
            no_header = {key: value for key, value in HEADERS.items() if key != "x-second-order-research-note"}
            self.assertEqual(self.post(client, body, no_header).status_code, 403)
            self.assertEqual(self.post(client, body, {**HEADERS, "Origin": "http://evil.example"}).status_code, 403)
            self.assertEqual(client.post(f"{PATH}/notes", content=b"x" * 16_385, headers=HEADERS).status_code, 413)
        self.assertFalse(self.notes.exists())

    def test_a_note_repeats_no_six_words_of_any_recorded_passage_of_the_two_publications(self):
        """Not only the rows' passages: a sentence of the same documents that no row cites would otherwise stay shown
        as the owner's words while its document does not verify."""
        other = next(item for item in read_json(self.folders.research / "facts.json")["passages"]
                     if item["id"] == "q3-p-smelter-restart")
        self.assertNotIn("fcx:q3-p-smelter-restart", json.dumps(fakes.world_comparison(None)))
        six = " ".join(other["quote"].split()[:6])
        with self.app() as client:
            refused = self.post(client, self.body(client, text=f"TEST VALUE: {six}"))
            self.assertEqual((refused.status_code, list(refused.json())), (422, ["detail"]))
            self.assertIn("repeats 6 words of a source", refused.json()["detail"])
        self.assertFalse(self.notes.exists())

    def test_the_desk_counts_each_chain_by_its_review_state(self):
        with self.app() as client:
            self.assertEqual(self.post_chain(client, "needs_revision").status_code, 201)
            pages = {item["id"]: item for item in self.view(client)["desk"]["pages"]}
            self.assertEqual(pages["events"]["status"], "1 chain: 1 with a revision asked.")
            self.assertEqual(self.post_chain(client, "approved").status_code, 201)
            pages = {item["id"]: item for item in self.view(client)["desk"]["pages"]}
            self.assertEqual(pages["events"]["status"], "1 chain: 1 approved.")
            flip_byte(fcx_file(self.folders, "10q-2026q3"))
            pages = {item["id"]: item for item in self.view(client)["desk"]["pages"]}
            self.assertEqual(pages["events"]["status"],
                             "1 chain: 1 approved on an earlier basis. 1 not available now.")

    def post_chain(self, client, status):
        binding = client.get(CHAIN_PATH).json()["chains"][0]["binding"]
        body = {"parent_review_id": binding["parent_review_id"], "chain_sha256": binding["chain_sha256"],
                "status": status, "notes": "TEST VALUE, not the owner's review."}
        return client.post(f"{CHAIN_PATH}/{CHAIN}/reviews", content=json.dumps(body).encode("utf-8"),
                           headers={**HEADERS, "x-second-order-event-chain": "1"})

    def test_a_history_that_cannot_be_verified_is_shown_as_invalid_and_refuses_saves(self):
        with self.app() as client:
            self.assertEqual(self.post(client, self.body(client)).status_code, 201)
            body = self.body(client)
            path = self.notes / "000001.json"
            record = read_json(path)
            record["text"] = "TEST VALUE: edited after it was saved."
            write_json(path, record)
            shown = self.view(client)
            self.assertEqual((shown["notes"]["state"], shown["notes"]["items"], shown["notes"]["latest"]),
                             ("invalid", [], None))
            self.assertIn("inconsistent", shown["notes"]["problem"])
            self.assertEqual(shown["comparisons"][0]["state"], "available")  # The rest of the read goes on.
            refused = self.post(client, body)
            self.assertEqual((refused.status_code, list(refused.json())), (500, ["detail"]))
        self.assertEqual(self.files(), ["000001.json"])


class Accounts(Research):
    def test_accounts_mode_requires_the_binding_and_records_the_identity(self):
        world = account_fakes.World(self.root / "accounts-world")
        admin, reader = world.ids["admin"], world.ids["reader-a"]
        write = {**HEADERS, "Origin": account_fakes.BASE, "X-Second-Order-Admin": "1"}
        with self.app() as local:
            body = self.body(local)
        with TestClient(world.app(**self.options()), base_url=account_fakes.BASE) as client:
            login = client.post("/api/session/login", headers=account_fakes.SESSION_WRITE,
                                json={"username": "admin", "password": account_fakes.PASSWORDS["admin"]})
            self.assertEqual(login.status_code, 200)
            unbound = self.post(client, body, write)
            self.assertEqual((unbound.status_code, unbound.json()["code"]), (428, "account_binding_required"))
            other = self.post(client, body, {**write, account_fakes.ACCOUNT: reader})
            self.assertEqual((other.status_code, other.json()["code"]), (401, "account_changed"))
            self.assertFalse(self.notes.exists())
            right = self.post(client, body, {**write, account_fakes.ACCOUNT: admin})
            self.assertEqual(right.status_code, 201)
            self.assertEqual(right.json()["record"]["account"], {"user_id": admin, "username": "admin"})
        with TestClient(world.app(**self.options()), base_url=account_fakes.BASE) as user:
            login = user.post("/api/session/login", headers=account_fakes.SESSION_WRITE,
                              json={"username": "reader-a", "password": account_fakes.PASSWORDS["reader-a"]})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(user.get(PATH).status_code, 403)
        self.assertEqual(self.files(), ["000001.json"])


class Fixtures(Research):
    def test_frontend_fixtures(self):
        """The replies the frontend reader is tested against: captured from this producer, never hand-written."""
        served = {}
        with self.app() as client:
            served["copper-research-empty.json"] = self.view(client)
            first = self.post(client, self.body(client, expectation=EXPECTATION, question=QUESTION)).json()["record"]
            self.assertEqual(self.post(client, self.body(client, follows=first["note_id"],
                                                         text="TEST VALUE: a later note on the same comparison."))
                             .status_code, 201)
            self.assertEqual(self.post(client, self.body(client, "chain", CHAIN,
                                                         text="TEST VALUE: see step 3 and the 85%.")).status_code, 201)
            self.assertEqual(self.post(client, self.body(client, "thesis", "copper",
                                                         text="TEST VALUE: a note on the whole thesis."))
                             .status_code, 201)
            served["copper-research-available.json"] = self.view(client)
            quarter = flip_byte(fcx_file(self.folders, "10q-2026q3"))
            served["copper-research-withheld.json"] = self.view(client)
            # A second version of the comparison, then one cited record edited and another removed: the notes rest on
            # an older version, and two lines are no longer the pinned records.
            fcx_file(self.folders, "10q-2026q3").write_bytes(quarter)
            first_version = dict(fakes.world_comparison(None),
                                 evidence=pc.pin(fakes.world_comparison(None), self.folders))
            second = dict(first_version, version=2, previous_version=1,
                          change={"note": "The wording of one label was revised"})
            fakes.write_comparison(self.folders.theses, COMPARISON, [first_version, second], ["2026-11-10"] * 2)
            facts = read_json(self.folders.research / "facts.json")
            next(item for item in facts["passages"] if item["id"] == "q3-p-iupk-extension").update(printed_page="99")
            facts["passages"].remove(next(item for item in facts["passages"]
                                          if item["id"] == "q3-p-gbc-capacity-targets"))
            write_json(self.folders.research / "facts.json", facts)
            served["copper-research-changed.json"] = self.view(client)
        states = {name: reply["comparisons"][0]["state"] for name, reply in served.items()}
        self.assertEqual(states, {"copper-research-empty.json": "available",
                                  "copper-research-available.json": "available",
                                  "copper-research-withheld.json": "needs_revalidation",
                                  "copper-research-changed.json": "evidence_changed"})
        self.assertEqual([len(reply["notes"]["items"]) for reply in served.values()], [0, 4, 4, 4])
        changed = served["copper-research-changed.json"]
        self.assertEqual([row["later"]["state"] for row in changed["comparisons"][0]["rows"]],
                         ["record_gone", "record_changed"])
        self.assertEqual([item["state"] for item in changed["notes"]["items"]],
                         ["earlier_basis", "earlier_basis", "earlier_basis", "current"])
        self.assertIn("newer version (2)", changed["notes"]["items"][0]["differs"][0])
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
                                 "-s tests -p test_copper_research_api.py")


class Subject(Research):
    def test_the_thesis_subject_closes_while_one_of_its_sources_does_not_verify(self):
        found = research_view.subject(self.folders, "thesis", "copper")
        self.assertEqual((found["state"], found["reasons"]), ("available", []))
        source = next(path for path in sorted(self.folders.thesis_sources.rglob("*"))
                      if path.is_file() and "acquisitions" not in path.parts)
        flip_byte(source)
        closed = research_view.subject(self.folders, "thesis", "copper")
        self.assertEqual(closed["state"], "needs_revalidation")
        self.assertEqual(len(closed["reasons"]), 1)


if __name__ == "__main__":
    unittest.main()

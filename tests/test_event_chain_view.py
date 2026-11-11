"""The served event-chain view on a SYNTHETIC world: the measured price block, the withholding guarantee (quotes
withheld whole while their document does not verify, digit labels withheld with them, the owner's figures masked while
a basis document fails), the pinned wording beside the current one, the history on an older acquisition, the approval
and reading states, and a read that writes nothing."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import event_chain_fakes as fakes  # noqa: E402
import metals_fakes  # noqa: E402
import thesis_fakes  # noqa: E402
from second_order import event_chain_evidence as evidence, event_chain_price as price, metals_view  # noqa: E402
from second_order import event_chain_records as records, event_chain_view as chain_view  # noqa: E402
from second_order.event_chain_schema import ChainRefused  # noqa: E402

ACCOUNT = {"user_id": "u1", "username": "owner"}
NOT_YET = "Not yet measured: the retained series ends at 2025 (estimate)"
SHORT_TERM = "Not measured: no monthly or daily price source is retained"
CONTEXT = [{"from": 2021, "to": 2022, "change_pct": "-5.0"}, {"from": 2022, "to": 2023, "change_pct": "-3.8"},
           {"from": 2023, "to": 2024, "change_pct": "9.2"}, {"from": 2024, "to": 2025, "change_pct": "13.5"}]
# Spec section 9, steps 2, 5 and 7 (test values only, not the owner's reading).
NOTE = "Label step 3 as the company's expectation, not a result."
LINE = "Test line: the company expects 85% in 2026, see step 3."
MASKED_LINE = "Test line: the company expects [figure withheld] in [figure withheld], see step 3."
WITHHELD_10Q = "Withheld: the FCX 10-Q no longer matches its acquisition record"
QUARTER = "fcx:10q-2026q3"
CITED = "k25-mud-rush-85pct"
EDITED = "Synthetic: an edited quote of the record."
DIGIT_LABEL = "The company names a date for 80% of capacity at the block cave"
ABSENT = "names a review that is not on this machine"
STEP_FIVE = "Test line: the company expects 85% in 2026, see step 5."
MASKED_STEP_FIVE = "Test line: the company expects [figure withheld] in [figure withheld], see step 5."


def clock():
    return datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def read_json(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"))


def write_json(path: Path, data) -> None:
    path.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def fcx_file(folders, source_id: str) -> Path:
    entry = next(item for item in read_json(folders.research / "sources.json")["sources"] if item["id"] == source_id)
    return folders.company_sources / entry["folder"] / entry["name"]


def flip_byte(path: Path) -> bytes:
    original = path.read_bytes()
    data = bytearray(original)
    data[len(data) // 2] ^= 1
    path.write_bytes(bytes(data))
    return original


def shorter_version_two(folders) -> dict:
    """The world chain's version 2 without its not-stated step: four steps where version 1 has five."""
    v2 = dict(fakes.world_chain(None), version=2, previous_version=1,
              change={"answers_review": None, "note": "The line on what no source states is left out"})
    v2["steps"] = [step for step in v2["steps"] if step["kind"] != "not_stated"]
    return dict(v2, evidence=evidence.pin(v2, folders))


def tree(root: Path) -> str:
    found = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        found.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return found.hexdigest()


class World(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folders = fakes.write_world(self.root / "world")
        self.pinned = evidence.pin(fakes.world_chain(None), self.folders)
        self.publish([fakes.world_chain(self.pinned)])

    def publish(self, versions):
        fakes.write_chain(self.folders.theses, fakes.WORLD_CHAIN, versions, ["2026-11-09"] * len(versions))

    def chain(self) -> dict:
        got = chain_view.view(self.folders)
        self.assertEqual([item["id"] for item in got["chains"]], [fakes.WORLD_CHAIN])
        return got["chains"][0]

    def latest(self, kind):
        found = records.history(self.folders.records, kind, fakes.WORLD_CHAIN)
        return found[-1][records.KINDS[kind]["id"]] if found else None

    def review(self, status, notes):
        current = chain_view.current(self.folders, fakes.WORLD_CHAIN)
        body = {"parent_review_id": self.latest("reviews"), "chain_sha256": current["sha256"], "status": status,
                "notes": notes}
        return records.save_review(self.folders.records, current, json.dumps(body).encode(), ACCOUNT, clock)

    def reading(self, line=LINE, short="not_sure", long="neither"):
        current = chain_view.current(self.folders, fakes.WORLD_CHAIN)
        body = {"parent_reading_id": self.latest("readings"), "chain_sha256": current["sha256"],
                "approval_id": current["approval_id"], "short_term": short, "long_term": long, "line": line}
        return records.save_reading(self.folders.records, current, json.dumps(body).encode(), ACCOUNT, clock)

    def approve_and_read(self, line=LINE):
        self.review("needs_revision", NOTE)
        self.review("approved", "Checked each step.")
        return self.reading(line)

    def forge(self, kind, number, change) -> dict:
        """Edit a saved record and recompute its id, as a hand edit that knows the digest would."""
        path = self.folders.records / kind / fakes.WORLD_CHAIN / f"{number:06d}.json"
        record = read_json(path)
        change(record)
        record[records.KINDS[kind]["id"]] = records.record_id(kind, record)
        write_json(path, record)
        return record

    def refused_save(self, kind, parent) -> records.RecordRefused:
        """A save on ``parent`` (the history's latest record), which the server must refuse."""
        current = chain_view.current(self.folders, fakes.WORLD_CHAIN)
        if kind == "reviews":
            save = records.save_review
            body = {"parent_review_id": parent, "chain_sha256": current["sha256"], "status": "approved",
                    "notes": "Checked once more."}
        else:
            save = records.save_reading
            body = {"parent_reading_id": parent, "chain_sha256": current["sha256"], "approval_id": "e" * 64,
                    "short_term": "refutes", "long_term": "refutes", "line": "Another line."}
        with self.assertRaises(records.RecordRefused) as raised:
            save(self.folders.records, current, json.dumps(body).encode(), ACCOUNT, clock)
        return raised.exception

    def assert_invalid(self, chain, problem):
        history = chain["history"]
        self.assertEqual((history["state"], history["reviews"], history["readings"]), ("invalid", [], []))
        self.assertIn(problem, history["problem"])
        self.assertEqual(chain["approval"], {"state": None, "review_id": None, "saved_at": None, "account": None,
                                             "notes": None, "masked": None, "differs": []})
        self.assertIsNone(chain["reading"])
        self.assertEqual({key: chain["binding"][key] for key in ("approval_id", "parent_review_id",
                                                                  "parent_reading_id")},
                         {"approval_id": None, "parent_review_id": None, "parent_reading_id": None})

    def facts(self, change):
        path = self.folders.research / "facts.json"
        data = read_json(path)
        change(data)
        write_json(path, data)

    def write_prices(self, prices):
        rows = metals_fakes.usgs_rows(prices=prices)
        metals_fakes.retain(self.folders.metals_sources, "usgs-csv-2026", metals_fakes.usgs_bytes(rows))
        write_json(self.folders.metals / "sources.json", metals_fakes.sources_file(self.folders.metals_sources))

    @staticmethod
    def step(chain, ref):
        return next(item for item in chain["steps"] if item.get("ref") == ref)

    @staticmethod
    def pinned_passage(chain, version, ref):
        entry = next(item for item in chain["history"]["versions"] if item["version"] == version)
        return next(item for item in entry["passages"] if item["ref"] == ref)


class PriceTests(World):
    def test_default_price_is_not_yet_measured(self):
        got = price.price_after("September 2025", self.folders)
        self.assertEqual(got["state"], "not_yet_measured")
        self.assertEqual(got["text"], NOT_YET)
        self.assertEqual((got["event_year"], got["last_year"], got["last_estimated"]), (2025, 2025, True))
        self.assertEqual(got["changes"], [])
        self.assertEqual(got["context"], CONTEXT)
        self.assertEqual(got["short_term"], SHORT_TERM)
        self.assertIsNone(got["problem"])
        self.assertEqual(got["series"]["label"], metals_fakes.PRICE_DETAIL)
        later = price.price_after("November 2026", self.folders)
        self.assertEqual((later["state"], later["text"], later["context"]), ("not_yet_measured", NOT_YET, CONTEXT))
        chain = self.chain()
        self.assertEqual(chain["measured"], {
            "target_note": "The thesis's own measure of this reason. It does not measure this event.",
            "price": price.price_after("2025", self.folders)})

    def test_later_year_is_measured_exactly(self):
        self.write_prices({**metals_fakes.PRICES, 2026: ("500.0", "")})
        got = price.price_after("2025", self.folders)
        self.assertEqual(got["state"], "measured")
        self.assertEqual(got["changes"], [{"year": 2026, "change_pct": "2.0"}])
        self.assertEqual(got["context"][-1], {"from": 2024, "to": 2025, "change_pct": "13.5"})
        self.assertEqual(got["context"], CONTEXT)
        self.assertEqual((got["event_year"], got["last_year"], got["last_estimated"]), (2025, 2026, False))
        self.assertEqual(got["short_term"], SHORT_TERM)
        self.assertNotIn("event did", got["text"])
        self.assertIn("what the price did after", got["text"].lower())
        earlier = price.price_after("2023", self.folders)
        self.assertEqual(earlier["changes"], [{"year": 2024, "change_pct": "9.2"}, {"year": 2025, "change_pct": "24.0"},
                                              {"year": 2026, "change_pct": "26.5"}])
        self.assertEqual(earlier["context"], CONTEXT[:2])

    def test_the_series_is_found_by_its_source_id(self):
        entries = metals_view.load_sources(self.folders.metals)
        with mock.patch.object(price.metals_view, "load_sources", return_value=list(reversed(entries))):
            self.assertEqual(price.price_after("2025", self.folders)["state"], "not_yet_measured")
        with mock.patch.object(price.metals_view, "load_sources", return_value=entries[1:]):
            got = price.price_after("2025", self.folders)
        self.assertEqual((got["state"], got["changes"], got["context"], got["last_year"]), ("withheld", [], [], None))
        self.assertEqual(got["problem"], "The metals sources file names no entry usgs-csv-2026")
        self.assertEqual(got["short_term"], SHORT_TERM)

    def test_changed_csv_withholds_price(self):
        metals_fakes.change_byte(self.folders.metals_sources, "usgs-csv-2026")
        got = price.price_after("2025", self.folders)
        self.assertEqual(got["state"], "withheld")
        self.assertEqual((got["changes"], got["context"], got["last_year"], got["last_estimated"]),
                         ([], [], None, None))
        self.assertTrue(got["problem"])
        self.assertEqual(got["short_term"], SHORT_TERM)
        for figure in ("490", "431.8", "13.5", "Estimated"):
            self.assertNotIn(figure, json.dumps(got))
        chain = self.chain()
        self.assertEqual(chain["measured"]["price"], got)
        self.assertEqual(chain["state"], "available")  # The price file is not part of the chain's evidence.


class WithholdingTests(World):
    def test_withheld_step_has_no_quote_and_digit_label_is_withheld(self):
        version = fakes.world_chain(self.pinned)
        version["steps"][2]["label"] = DIGIT_LABEL
        self.publish([version])
        chain = self.chain()
        third = self.step(chain, fakes.THIRD)
        quote = self.pinned["passages"][2]["quote"]
        self.assertEqual((third["state"], third["label"], third["quote"]), ("verified", DIGIT_LABEL, quote))
        flip_byte(fcx_file(self.folders, "10q-2026q3"))
        chain = self.chain()
        self.assertEqual(chain["state"], "needs_revalidation")
        third = self.step(chain, fakes.THIRD)
        self.assertEqual(third["state"], "changed")
        self.assertEqual(third["problem"], WITHHELD_10Q)
        self.assertEqual(third["document"], {"ref": QUARTER, "name": "the FCX 10-Q", "state": "changed"})
        for key in ("label", "quote", "pinned_quote", "current_quote"):
            self.assertIsNone(third[key], key)
        self.assertTrue(third["where"].startswith("page 43"))
        self.assertIsNone(self.pinned_passage(chain, 1, fakes.THIRD)["quote"])
        served = json.dumps(chain, ensure_ascii=False)
        self.assertNotIn(quote, served)
        self.assertNotIn("80%", served)
        second = self.step(chain, fakes.SECOND)
        self.assertEqual((second["state"], second["quote"]), ("verified", self.pinned["passages"][1]["quote"]))
        self.assertEqual(self.step(chain, fakes.EVENT)["label"], fakes.world_chain(None)["steps"][0]["label"])
        self.assertEqual(chain["steps"][3], {"kind": "not_stated", "text": fakes.world_chain(None)["steps"][3]["text"]})
        self.assertEqual(chain["steps"][4], {"kind": "mechanism", "id": "restart-takes-time",
                                             "text": fakes.MECHANISMS["restart-takes-time"]})

    def test_changed_item_shows_pinned_and_current_side_by_side_only_while_document_verifies(self):
        self.facts(lambda facts: next(item for item in facts["passages"] if item["id"] == CITED).update(
            quote=EDITED, printed_page="24"))
        chain = self.chain()
        self.assertEqual(chain["state"], "evidence_changed")
        second = self.step(chain, fakes.SECOND)
        pinned = self.pinned["passages"][1]
        self.assertEqual(second["state"], "record_changed")
        self.assertIsNone(second["quote"])
        self.assertEqual((second["pinned_quote"], second["current_quote"]), (pinned["quote"], EDITED))
        self.assertIn("printed page 23", second["pinned_where"])
        self.assertIn("printed page 24", second["current_where"])
        self.assertEqual(second["problem"], f"{fakes.SECOND}: its wording and location differ from the pinned version")
        self.assertEqual(self.pinned_passage(chain, 1, fakes.SECOND)["quote"], pinned["quote"])
        self.assertEqual({item["ref"]: item["state"] for item in chain["items"] if item["kind"] == "passage"},
                         {fakes.EVENT: "same", fakes.SECOND: "changed", fakes.THIRD: "same"})
        flip_byte(fcx_file(self.folders, "10k-2025"))
        chain = self.chain()
        second = self.step(chain, fakes.SECOND)
        self.assertEqual(second["state"], "changed")
        for key in ("quote", "pinned_quote", "current_quote"):
            self.assertIsNone(second[key], key)
        self.assertIsNone(self.pinned_passage(chain, 1, fakes.SECOND)["quote"])
        served = json.dumps(chain, ensure_ascii=False)
        self.assertNotIn(EDITED, served)
        self.assertNotIn(pinned["quote"], served)

    def test_a_gone_record_and_a_quote_not_found_where_cited_show_no_quote_in_the_card(self):
        self.facts(lambda facts: facts.update(passages=[item for item in facts["passages"] if item["id"] != CITED]))
        moved = thesis_fakes.changed(fakes.world_thesis(self.folders),
                                     lambda body: body["passages"][0]["locator"].update(paragraph=1))
        self.assertEqual(moved["passages"][0]["id"], fakes.EVENT.split(":")[1])
        thesis_fakes.write_theses(self.folders.theses, [moved], [thesis_fakes.OPENED_ON], thesis_id="copper")
        chain = self.chain()
        self.assertEqual(chain["state"], "needs_revalidation")
        gone = self.step(chain, fakes.SECOND)
        self.assertEqual(gone["state"], "record_gone")
        self.assertEqual((gone["quote"], gone["pinned_quote"], gone["current_quote"]), (None, None, None))
        self.assertIn("printed page 23", gone["pinned_where"])
        self.assertEqual(self.pinned_passage(chain, 1, fakes.SECOND)["quote"], self.pinned["passages"][1]["quote"])
        lost = self.step(chain, fakes.EVENT)
        self.assertEqual((lost["state"], lost["quote"]), ("not_found", None))
        self.assertTrue(lost["problem"].startswith(f"Withheld: the passage {fakes.EVENT} is not found where it is "
                                                   "cited"))
        self.assertEqual(self.pinned_passage(chain, 1, fakes.EVENT)["state"], "not_found")
        self.assertNotIn(self.pinned["passages"][0]["quote"], json.dumps(chain, ensure_ascii=False))

    def test_owner_text_masked_only_while_a_basis_document_fails(self):
        self.approve_and_read()
        listing = sorted(path.name for path in self.folders.records.rglob("*.json"))
        chain = self.chain()
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"], reading["state"]), (LINE, False, "current"))
        self.assertEqual(chain["reading"]["line"], LINE)
        original = flip_byte(fcx_file(self.folders, "10q-2026q3"))
        chain = self.chain()
        self.assertEqual(chain["state"], "needs_revalidation")
        self.assertEqual(self.step(chain, fakes.THIRD)["problem"], WITHHELD_10Q)
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"], reading["state"]), (MASKED_LINE, True, "earlier_basis"))
        self.assertIn(QUARTER, reading["mask_reason"])
        self.assertEqual({item["ref"]: item["state"] for item in reading["basis_documents"]}[QUARTER], "changed")
        self.assertIsNone(chain["reading"])
        first = chain["history"]["reviews"][0]
        self.assertEqual((first["notes"], first["masked"]), (NOTE, True))
        self.assertEqual(self.step(chain, fakes.SECOND)["state"], "verified")  # The 10-K, which quotes 85%, verifies.
        self.assertNotIn("85", reading["line"])
        fcx_file(self.folders, "10q-2026q3").write_bytes(original)
        chain = self.chain()
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"], reading["state"]), (LINE, False, "current"))
        self.assertIsNone(reading["mask_reason"])
        self.assertEqual(sorted(path.name for path in self.folders.records.rglob("*.json")), listing)

    def test_history_stays_readable_after_the_acquisition_is_replaced(self):
        self.approve_and_read()
        old = next(item for item in self.pinned["documents"] if item["ref"] == QUARTER)["acquisition"]
        fakes.replace_fcx_acquisition(self.folders, "10q-2026q3")
        chain = self.chain()
        self.assertEqual(chain["state"], "needs_revalidation")
        self.assertEqual(self.step(chain, fakes.THIRD)["state"], "superseded")
        self.assertIsNone(self.step(chain, fakes.THIRD)["quote"])
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"], reading["state"]), (LINE, False, "earlier_basis"))
        self.assertEqual(self.pinned_passage(chain, 1, fakes.THIRD)["quote"], self.pinned["passages"][2]["quote"])
        self.assertEqual(self.pinned_passage(chain, 1, fakes.SECOND)["quote"], self.pinned["passages"][1]["quote"])
        (self.folders.company_sources / old["folder"] / old["name"]).unlink()
        chain = self.chain()
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"]), (MASKED_LINE, True))
        self.assertIsNone(self.pinned_passage(chain, 1, fakes.THIRD)["quote"])
        self.assertEqual(self.pinned_passage(chain, 1, fakes.THIRD)["state"], "missing")
        self.assertEqual(self.pinned_passage(chain, 1, fakes.SECOND)["quote"], self.pinned["passages"][1]["quote"])
        self.assertNotIn(self.pinned["passages"][2]["quote"], json.dumps(chain, ensure_ascii=False))


class RecordStateTests(World):
    def test_approval_and_reading_states(self):
        chain = self.chain()
        self.assertEqual(chain["approval"]["state"], "awaiting_review")
        self.assertIsNone(chain["approval"]["review_id"])
        self.assertIsNone(chain["reading"])
        self.assertEqual(chain["binding"], {"chain_sha256": chain["history"]["versions"][0]["sha256"],
                                            "approval_id": None, "parent_review_id": None, "parent_reading_id": None})
        first = self.review("needs_revision", NOTE)
        chain = self.chain()
        self.assertEqual((chain["approval"]["state"], chain["approval"]["notes"]), ("needs_revision", NOTE))
        self.assertEqual(chain["history"]["reviews"][0]["state"], "needs_revision")
        second = self.review("approved", "Checked each step.")
        chain = self.chain()
        self.assertEqual((chain["approval"]["state"], chain["approval"]["review_id"]),
                         ("approved", second["review_id"]))
        self.assertEqual(chain["approval"]["account"], ACCOUNT)
        self.assertEqual(chain_view.current(self.folders, fakes.WORLD_CHAIN)["approval_id"], second["review_id"])
        reading = self.reading()
        chain = self.chain()
        self.assertEqual((chain["reading"]["reading_id"], chain["reading"]["state"]),
                         (reading["reading_id"], "current"))
        self.assertEqual(chain["binding"], {"chain_sha256": chain["history"]["versions"][0]["sha256"],
                                            "approval_id": second["review_id"], "parent_review_id": second["review_id"],
                                            "parent_reading_id": reading["reading_id"]})
        self.assertEqual([item["state"] for item in chain["history"]["reviews"]], ["needs_revision", "approved"])
        self.assertEqual(chain["history"]["reviews"][0]["review_id"], first["review_id"])
        self.facts(lambda facts: next(item for item in facts["passages"] if item["id"] == CITED).update(
            printed_page="24"))
        chain = self.chain()
        self.assertEqual(chain["state"], "evidence_changed")
        self.assertEqual(chain["approval"]["state"], "approved_earlier_basis")
        self.assertEqual(chain["approval"]["differs"], chain["reasons"])
        self.assertIsNone(chain["reading"])
        earlier = chain["history"]["readings"][0]
        self.assertEqual(earlier["state"], "earlier_basis")
        self.assertEqual((earlier["line"], earlier["masked"]), (LINE, False))
        self.assertTrue(any(fakes.SECOND in text for text in earlier["differs"]))
        self.assertEqual([item["state"] for item in chain["history"]["reviews"]],
                         ["needs_revision", "approved_earlier_basis"])
        self.assertIsNone(chain_view.current(self.folders, fakes.WORLD_CHAIN)["approval_id"])
        self.assertEqual(chain["binding"]["approval_id"], None)
        self.assertEqual(chain["binding"]["parent_reading_id"], reading["reading_id"])

    def test_answers_review_not_on_this_machine_is_noted(self):
        asked = self.review("needs_revision", NOTE)

        def version_two(answers):
            v2 = dict(fakes.world_chain(None), version=2, previous_version=1,
                      change={"answers_review": answers, "note": "The second label now names the company's view"})
            return dict(v2, evidence=evidence.pin(v2, self.folders))

        self.publish([fakes.world_chain(self.pinned), version_two(asked["review_id"])])
        chain = self.chain()
        self.assertEqual(chain["latest_version"], 2)
        self.assertIsNone(chain["history"]["versions"][1]["change"]["review_note"])
        self.publish([fakes.world_chain(self.pinned), version_two("f" * 64)])
        chain = self.chain()
        change = chain["history"]["versions"][1]["change"]
        self.assertEqual((change["answers_review"], change["review_note"]), ("f" * 64, ABSENT))
        self.assertIsNone(chain["history"]["versions"][0]["change"])
        self.assertEqual(chain["approval"]["state"], "awaiting_review")
        self.assertEqual(chain["history"]["reviews"][0]["state"], "needs_revision")
        self.assertTrue(any("newer version" in text for text in chain["history"]["reviews"][0]["differs"]))

    def test_each_version_serves_its_step_count_and_a_record_is_masked_by_its_own_versions(self):
        self.approve_and_read(STEP_FIVE)  # Version 1 has five steps, so "step 5" names one of them.
        self.publish([fakes.world_chain(self.pinned), shorter_version_two(self.folders)])
        chain = self.chain()
        self.assertEqual([item["steps"] for item in chain["history"]["versions"]], [5, 4])
        self.assertEqual(len(chain["steps"]), 4)
        self.assertEqual(chain["history"]["readings"][0]["line"], STEP_FIVE)
        flip_byte(fcx_file(self.folders, "10q-2026q3"))
        chain = self.chain()
        reading = chain["history"]["readings"][0]
        self.assertEqual((reading["line"], reading["masked"], reading["basis"]["chain"]["version"]),
                         (MASKED_STEP_FIVE, True, 1))

    def test_a_record_naming_a_version_not_in_the_history_makes_it_invalid(self):
        self.review("needs_revision", NOTE)
        forged = self.forge("reviews", 1, lambda record: record["basis"]["chain"].update(version=2))
        chain = self.chain()
        self.assert_invalid(chain, "names chain version 2, which is not in the chain's history")
        self.assertEqual(len(chain["history"]["versions"]), 1)
        error = self.refused_save("reviews", forged["review_id"])
        self.assertEqual(error.status, 500)
        self.assertIn("cannot be verified", error.message)
        self.assertEqual(len(records.history(self.folders.records, "reviews", fakes.WORLD_CHAIN)), 1)

    def test_a_forged_record_of_the_wrong_shape_is_an_invalid_history_on_its_chain_and_refuses_saves(self):
        forgeries = {
            "notes missing": ("reviews", 2, lambda record: record.pop("notes")),
            "acquisition sha256 a number": ("readings", 1, lambda record: record["basis"]["documents"][0]
                                            ["acquisition"].update(sha256=5)),
            "acquisition sha256 a number in a review": ("reviews", 2, lambda record: record["basis"]["documents"][0]
                                                        ["acquisition"].update(sha256=5)),
        }
        for name, (kind, number, change) in forgeries.items():
            with self.subTest(name):
                shutil.rmtree(self.folders.records, ignore_errors=True)
                self.approve_and_read()
                forged = self.forge(kind, number, change)
                chain = self.chain()  # Neither KeyError nor TypeError, and the other parts are served.
                self.assert_invalid(chain, "cannot be verified")
                self.assertEqual((chain["state"], len(chain["steps"])), ("available", 5))
                listing = sorted(path.name for path in self.folders.records.rglob("*.json"))
                error = self.refused_save(kind, forged[records.KINDS[kind]["id"]])
                self.assertEqual(error.status, 500)
                self.assertIn("cannot be verified", error.message)
                self.assertEqual(sorted(path.name for path in self.folders.records.rglob("*.json")), listing)

    def test_one_chains_records_failing_never_break_the_read(self):
        self.approve_and_read()
        with mock.patch.object(chain_view._Records, "readings", side_effect=KeyError("line")):
            chain = self.chain()
        self.assert_invalid(chain, "The saved records of this chain could not be read (KeyError)")
        self.assertEqual((chain["state"], len(chain["history"]["versions"])), ("available", 1))
        self.assertEqual(self.chain()["history"]["state"], "valid")

    def test_an_invalid_history_is_shown_and_the_read_goes_on(self):
        self.review("needs_revision", NOTE)
        path = self.folders.records / "reviews" / fakes.WORLD_CHAIN / "000001.json"
        path.write_bytes(path.read_bytes().replace(b"Label", b"Lable"))
        chain = self.chain()
        history = chain["history"]
        self.assertEqual((history["state"], history["reviews"], history["readings"]), ("invalid", [], []))
        self.assertIn("inconsistent", history["problem"])
        self.assertEqual(len(history["versions"]), 1)
        self.assertIsNone(chain["approval"]["state"])
        self.assertEqual((chain["binding"]["parent_review_id"], chain["binding"]["parent_reading_id"]), (None, None))
        self.assertEqual(chain["state"], "available")


class ReadTests(World):
    def test_reading_changes_nothing(self):
        self.approve_and_read()
        before = tree(self.root)
        chain_view.view(self.folders)
        chain_view.current(self.folders, fakes.WORLD_CHAIN)
        price.price_after("2025", self.folders)
        self.assertEqual(tree(self.root), before)

    def test_current_binds_the_latest_version_and_refuses_an_unknown_chain(self):
        current = chain_view.current(self.folders, fakes.WORLD_CHAIN)
        index = read_json(self.folders.theses / "copper" / "event-chains" / fakes.WORLD_CHAIN / "index.json")
        self.assertEqual((current["id"], current["version"], current["sha256"]),
                         (fakes.WORLD_CHAIN, 1, index["versions"][0]["sha256"]))
        self.assertEqual(current["basis"], {
            "chain": {"id": fakes.WORLD_CHAIN, "version": 1, "sha256": index["versions"][0]["sha256"]},
            "evidence_sha256": evidence.evidence_sha256(self.pinned), "thesis": self.pinned["thesis"],
            "documents": self.pinned["documents"]})
        self.assertEqual((current["state"], current["reasons"], current["steps"]), ("available", [], 5))
        self.assertEqual(current["target"], {"kind": "reason", "id": "mine-supply-slow"})
        for item in self.pinned["passages"]:
            self.assertIn(item["quote"], current["quotes"])
        self.assertIn("22,900", current["allowed"])
        with self.assertRaises(ChainRefused) as raised:
            chain_view.current(self.folders, "no-such-chain")
        self.assertEqual(raised.exception.status, 404)

    def test_no_published_thesis_is_503(self):
        thesis_fakes.write_theses(self.folders.theses, [fakes.world_thesis(self.folders)], [None], thesis_id="copper")
        with self.assertRaises(ChainRefused) as raised:
            chain_view.view(self.folders)
        self.assertEqual(raised.exception.status, 503)

    def test_the_reply_shape(self):
        got = chain_view.view(self.folders)
        self.assertEqual(set(got), {"view_version", "provider_called", "thesis", "chains"})
        self.assertEqual((got["view_version"], got["provider_called"]), ("event-chains-view-0.1", False))
        self.assertEqual(got["thesis"], {"id": "copper", "latest_version": 1})
        chain = got["chains"][0]
        self.assertEqual((chain["title"], chain["latest_version"], chain["state"], chain["reasons"]),
                         (fakes.world_chain(None)["title"], 1, "available", []))
        stated = self.step(chain, fakes.EVENT)
        self.assertEqual(set(stated), {"kind", "label", "ref", "quote", "pinned_quote", "current_quote", "where",
                                       "pinned_where", "current_where", "document", "state", "problem"})
        target = chain["target"]
        self.assertEqual((target["kind"], target["id"], target["state"], target["status"], target["change_pct"]),
                         ("reason", "mine-supply-slow", "available", "unchanged", "0.9"))
        self.assertEqual(target["title"], "Synthetic mine supply responds slowly")
        self.assertEqual(set(chain["approval"]), {"state", "review_id", "saved_at", "account", "notes", "masked",
                                                  "differs"})
        self.assertEqual(set(chain["history"]), {"state", "problem", "versions", "reviews", "readings"})


if __name__ == "__main__":
    unittest.main()

"""Event-chain evidence on a SYNTHETIC world: the pin copies the live records from raw files, and the comparison finds a
changed cited record with its document unchanged, a changed or missing document, a replaced acquisition and a newer
thesis, while an edit to any record the chain does not cite changes nothing."""
import dataclasses
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import event_chain_fakes as fakes  # noqa: E402
import fcx_fakes  # noqa: E402
import thesis_fakes  # noqa: E402
from second_order import company_research_view, event_chain_evidence as evidence, event_chain_schema  # noqa: E402
from second_order import thesis_schema, thesis_sources  # noqa: E402

DOCUMENTS = ["copper:sec-producer-2025", "copper:usgs-2025", "copper:usgs-2026", "fcx:10k-2025", "fcx:10q-2026q3"]
CITED = "k25-mud-rush-85pct"
QUARTER = "fcx:10q-2026q3"


def read_json(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"))


def write_json(path: Path, data) -> None:
    path.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def edit_json(path: Path, change) -> None:
    data = read_json(path)
    change(data)
    write_json(path, data)


def passage(facts: dict, passage_id: str) -> dict:
    return next(item for item in facts["passages"] if item["id"] == passage_id)


def fcx_file(folders, source_id: str) -> Path:
    entry = next(item for item in read_json(folders.research / "sources.json")["sources"] if item["id"] == source_id)
    return folders.company_sources / entry["folder"] / entry["name"]


def flip_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(bytes(data))


def document(pinned: dict, ref: str) -> dict:
    return next(item for item in pinned["documents"] if item["ref"] == ref)


class World(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.worlds = 0
        self.folders, self.pinned = self.world()

    def world(self):
        """A new synthetic world in its own folder, and the world chain's pin taken on it."""
        self.worlds += 1
        folders = fakes.write_world(self.base / f"world-{self.worlds}")
        return folders, evidence.pin(fakes.world_chain(None), folders)

    def compare(self, folders=None, pinned=None):
        pinned = self.pinned if pinned is None else pinned
        return evidence.compare(pinned, evidence.live(fakes.world_chain(pinned), folders or self.folders))

    def facts(self, change, folders=None):
        edit_json((folders or self.folders).research / "facts.json", change)

    def register(self, change):
        edit_json(self.folders.metals / "research.json", change)

    def states(self, got) -> dict:
        return {item["ref"]: item["state"] for item in got["documents"]}

    def assert_all_verified(self, got):
        self.assertEqual(self.states(got), dict.fromkeys(DOCUMENTS, "verified"))


class PinTests(World):
    def test_fresh_pin_is_available(self):
        got = self.compare()
        self.assertEqual(got["state"], "available")
        self.assertEqual(got["reasons"], [])
        self.assert_all_verified(got)
        self.assertEqual([(item["ref"], item["kind"], item["state"]) for item in got["items"]],
                         [(fakes.EVENT, "event", "same"), (fakes.EVENT, "passage", "same"),
                          (fakes.SECOND, "passage", "same"), (fakes.THIRD, "passage", "same")])
        for item in got["items"]:
            self.assertEqual(item["pinned"], item["current"])

    def test_pin_copies_the_raw_records_restricted_to_their_pinned_fields(self):
        pinned = self.pinned
        self.assertEqual(pinned["event"], {"passage": fakes.EVENT, "kind": "Synthetic sales report", "when": "2025"})
        self.assertEqual(pinned["passages"][0], {
            "ref": fakes.EVENT, "source": "sec-producer-2025", "location": {"paragraph": 3},
            "quote": "Synthetic copper sales were 4,120 million pounds in 2025."})
        raw = passage(read_json(self.folders.research / "facts.json"), CITED)
        self.assertEqual(pinned["passages"][1], {
            "ref": fakes.SECOND, "source": "10k-2025",
            "location": {"page": raw["page"], "printed_page": "23", "location": raw["location"]},
            "quote": raw["quote"]})
        self.assertEqual([item["ref"] for item in pinned["passages"]], [fakes.EVENT, fakes.SECOND, fakes.THIRD])
        self.assertEqual([item["ref"] for item in pinned["documents"]], DOCUMENTS)
        for item in pinned["documents"]:
            kind = item["ref"].split(":")[0]
            self.assertEqual(tuple(item["acquisition"]), event_chain_schema.ACQUISITION_FIELDS[kind])
        index = read_json(self.folders.theses / "copper" / "index.json")
        self.assertEqual(pinned["thesis"], {"id": "copper", "version": 1, "sha256": index["versions"][0]["sha256"]})
        mechanisms = read_json(self.folders.metals / "mechanisms" / "index.json")
        self.assertEqual(pinned["mechanisms"], {"version": 1, "sha256": mechanisms["versions"][0]["sha256"]})

    def test_pin_loads_as_a_chain_version_and_its_sha256_is_of_canonical_json(self):
        fakes.write_chain(self.folders.theses, fakes.WORLD_CHAIN, [fakes.world_chain(self.pinned)], ["2026-11-09"])
        mechanisms = event_chain_schema.load_mechanisms(event_chain_schema.mechanisms_dir(self.folders.metals))
        chains = event_chain_schema.load_chains(event_chain_schema.chains_dir(self.folders.theses), mechanisms)
        self.assertEqual(chains[fakes.WORLD_CHAIN]["versions"][0]["evidence"], self.pinned)
        canonical = json.dumps(self.pinned, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(evidence.evidence_sha256(self.pinned), hashlib.sha256(canonical).hexdigest())

    def test_pin_is_the_same_with_a_document_missing(self):
        (self.folders.thesis_sources / "sec-producer-2025" / "10k.htm").unlink()
        (self.folders.thesis_sources / "usgs-2025" / "copper.csv").unlink()
        fcx_file(self.folders, "10k-2025").unlink()
        self.assertEqual(evidence.pin(fakes.world_chain(None), self.folders), self.pinned)

    def test_a_second_world_pins_the_same_evidence(self):
        self.assertEqual(self.world()[1], self.pinned)

    def test_pin_refuses_a_record_that_is_not_there(self):
        unknown_target = dict(fakes.world_chain(None), target={"kind": "risk", "id": "mine-supply-slow"})
        broken, _ = fcx_fakes.synthetic_package(self.base / "broken", "facts-broken")
        cases = {
            "target": (lambda: evidence.pin(unknown_target, self.folders), "target: "),
            "passages": (lambda: evidence.pin(fakes.world_chain(None), dataclasses.replace(self.folders,
                                                                                          research=broken)),
                         f"passages: {fakes.SECOND} "),
            "event": (lambda: (self.register(lambda content: content["metals"]["copper"]["events"].pop(0)),
                               evidence.pin(fakes.world_chain(None), self.folders)), f"event: {fakes.EVENT} "),
        }
        for name, (call, prefix) in cases.items():
            with self.subTest(name):
                with self.assertRaises(event_chain_schema.ChainRefused) as raised:
                    call()
                self.assertEqual(raised.exception.status, 422)
                self.assertTrue(raised.exception.message.startswith(prefix), raised.exception.message)


class ItemTests(World):
    def test_cited_record_quote_edit_with_same_document_is_evidence_changed(self):
        self.facts(lambda facts: passage(facts, CITED).update(quote="Synthetic: an edited quote of the record."))
        got = self.compare()
        self.assert_all_verified(got)
        self.assertEqual(got["state"], "evidence_changed")
        item = next(item for item in got["items"] if item["ref"] == fakes.SECOND)
        self.assertEqual(item["state"], "changed")
        self.assertEqual(item["pinned"]["quote"], self.pinned["passages"][1]["quote"])
        self.assertEqual(item["current"]["quote"], "Synthetic: an edited quote of the record.")
        self.assertEqual([other["state"] for other in got["items"] if other is not item], ["same"] * 3)
        self.assertEqual(len(got["reasons"]), 1)

    def test_cited_record_location_edit_is_evidence_changed(self):
        self.facts(lambda facts: passage(facts, CITED).update(printed_page="24"))
        got = self.compare()
        self.assert_all_verified(got)
        self.assertEqual(got["state"], "evidence_changed")
        item = next(item for item in got["items"] if item["ref"] == fakes.SECOND)
        self.assertEqual(item["state"], "changed")
        self.assertEqual((item["pinned"]["location"]["printed_page"], item["current"]["location"]["printed_page"]),
                         ("23", "24"))

    def test_event_kind_or_when_edit_is_evidence_changed(self):
        original = (self.folders.metals / "research.json").read_bytes()
        for field, value in (("kind", "Synthetic sales record"), ("when", "fiscal 2025")):
            with self.subTest(field):
                (self.folders.metals / "research.json").write_bytes(original)
                self.register(lambda content: content["metals"]["copper"]["events"][0].update({field: value}))
                got = self.compare()
                self.assertEqual(got["state"], "evidence_changed")
                self.assertEqual(got["items"][0]["kind"], "event")
                self.assertEqual(got["items"][0]["state"], "changed")
                self.assertEqual(got["items"][0]["current"][field], value)
                self.assertEqual(got["items"][0]["pinned"][field], self.pinned["event"][field])

    def test_removed_record_and_removed_event_are_gone(self):
        self.facts(lambda facts: facts.update(passages=[item for item in facts["passages"] if item["id"] != CITED]))
        self.register(lambda content: content["metals"]["copper"].update(
            events=[event for event in content["metals"]["copper"]["events"] if event["passage"] != fakes.EVENT]))
        got = self.compare()
        self.assertEqual(got["state"], "evidence_changed")
        gone = {(item["kind"], item["ref"]): item for item in got["items"] if item["state"] == "gone"}
        self.assertEqual(set(gone), {("event", fakes.EVENT), ("passage", fakes.SECOND)})
        for item in gone.values():
            self.assertIsNone(item["current"])
            self.assertTrue(item["pinned"])
        self.assertEqual(len(got["reasons"]), 2)

    def test_uncited_record_edit_changes_nothing(self):
        def change(facts):
            passage(facts, "k25-bagdad")["quote"] = "Synthetic: an edited quote of an uncited record."
            passage(facts, CITED)["topic"] = "synthetic-topic"
            passage(facts, fakes.THIRD.split(":")[1])["topic"] = "synthetic-topic"
        self.facts(change)
        self.register(lambda content: content["metals"]["nickel"]["events"][0].update(kind="Synthetic edited kind"))
        got = self.compare()
        self.assertEqual(got["state"], "available")
        self.assertEqual(got["reasons"], [])
        self.assertEqual({item["state"] for item in got["items"]}, {"same"})

    def test_undoing_the_edit_restores_available(self):
        path = self.folders.research / "facts.json"
        original = path.read_bytes()
        self.facts(lambda facts: passage(facts, CITED).update(quote="Synthetic: an edited quote of the record."))
        self.assertEqual(self.compare()["state"], "evidence_changed")
        path.write_bytes(original)
        got = self.compare()
        self.assertEqual(got["state"], "available")
        self.assertEqual({item["state"] for item in got["items"]}, {"same"})


class DocumentTests(World):
    def test_document_states(self):
        cases = {
            "flipped byte, copper": (lambda f: flip_byte(f.thesis_sources / "sec-producer-2025" / "10k.htm"),
                                     {"copper:sec-producer-2025": "changed"}, "needs_revalidation"),
            "flipped byte, fcx": (lambda f: flip_byte(fcx_file(f, "10k-2025")), {"fcx:10k-2025": "changed"},
                                  "needs_revalidation"),
            "removed file": (lambda f: fcx_file(f, "10k-2025").unlink(), {"fcx:10k-2025": "missing"}, "unavailable"),
            "removed target file": (lambda f: (f.thesis_sources / "usgs-2025" / "copper.csv").unlink(),
                                    {"copper:usgs-2025": "missing"}, "unavailable"),
            "sources.json sha256": (lambda f: edit_json(f.research / "sources.json", lambda listing: next(
                item for item in listing["sources"] if item["id"] == "10q-2026q3").update(sha256="0" * 64)),
                {QUARTER: "superseded"}, "needs_revalidation"),
        }
        for name, (change, expected, state) in cases.items():
            with self.subTest(name):
                folders, pinned = self.world()
                change(folders)
                got = self.compare(folders, pinned)
                self.assertEqual(self.states(got), {ref: expected.get(ref, "verified") for ref in DOCUMENTS})
                self.assertEqual(got["state"], state)
                self.assertEqual({item["state"] for item in got["items"]}, {"same"})
                self.assertTrue(got["reasons"])
        with self.subTest("facts-broken: every fcx item and document unreadable"):
            research, documents = fcx_fakes.synthetic_package(self.base / "broken", "facts-broken")
            broken = dataclasses.replace(self.folders, research=research, company_sources=documents)
            got = self.compare(broken)
            self.assertEqual(self.states(got), {ref: "unreadable" if ref.startswith("fcx:") else "verified"
                                                for ref in DOCUMENTS})
            self.assertEqual(got["state"], "unavailable")
            self.assertEqual({item["ref"]: item["state"] for item in got["items"] if item["kind"] == "passage"},
                             {fakes.EVENT: "same", fakes.SECOND: "unreadable", fakes.THIRD: "unreadable"})
            self.assertEqual(got["items"][0]["state"], "same")

    def test_newer_thesis_version_is_thesis_newer(self):
        v1 = fakes.world_thesis(self.folders)
        v2 = thesis_fakes.thesis_v2(v1, self.folders.thesis_sources)
        thesis_fakes.write_theses(self.folders.theses, [v1, v2], [thesis_fakes.OPENED_ON, thesis_fakes.V2_ON],
                                  thesis_id="copper")
        got = self.compare()
        self.assertEqual(got["state"], "thesis_newer")
        self.assertEqual(len(got["reasons"]), 1)
        self.assert_all_verified(got)
        self.assertEqual({item["state"] for item in got["items"]}, {"same"})

    def test_a_draft_thesis_version_is_not_the_basis(self):
        v1 = fakes.world_thesis(self.folders)
        v2 = thesis_fakes.thesis_v2(v1, self.folders.thesis_sources)
        thesis_fakes.write_theses(self.folders.theses, [v1, v2], [thesis_fakes.OPENED_ON, None], thesis_id="copper")
        self.assertEqual(evidence.pin(fakes.world_chain(None), self.folders), self.pinned)
        got = self.compare()
        self.assertEqual(got["state"], "available")
        self.assertEqual(got["reasons"], [])
        with self.subTest("a draft's wording is never compared"):
            edited = thesis_fakes.changed(v2, lambda body: body["passages"][0]["locator"].update(
                quote="Synthetic copper sales were 4,120 million pounds in fiscal 2025."))
            thesis_fakes.write_theses(self.folders.theses, [v1, edited], [thesis_fakes.OPENED_ON, None],
                                      thesis_id="copper")
            got = self.compare()
            self.assertEqual(got["state"], "available")
            self.assertEqual({item["state"] for item in got["items"]}, {"same"})
        with self.subTest("the same version published is newer"):
            thesis_fakes.write_theses(self.folders.theses, [v1, v2], [thesis_fakes.OPENED_ON, thesis_fakes.V2_ON],
                                      thesis_id="copper")
            got = self.compare()
            self.assertEqual(got["state"], "thesis_newer")
            self.assertEqual(len(got["reasons"]), 1)

    def test_no_published_thesis_version_refuses_the_pin_and_makes_the_target_unavailable(self):
        thesis_fakes.write_theses(self.folders.theses, [fakes.world_thesis(self.folders)], [None], thesis_id="copper")
        with self.assertRaises(event_chain_schema.ChainRefused) as raised:
            evidence.pin(fakes.world_chain(None), self.folders)
        self.assertEqual(raised.exception.status, 422)
        self.assertTrue(raised.exception.message.startswith("thesis: "), raised.exception.message)
        current = evidence.live(fakes.world_chain(self.pinned), self.folders)
        self.assertEqual(current["target"], {"state": "unavailable", "sources": [], "element": None})
        got = evidence.compare(self.pinned, current)
        self.assertEqual(got["state"], "unavailable")
        self.assertIn("The thesis has no published version", got["reasons"])

    def test_every_reason_is_listed_and_the_first_in_order_is_the_state(self):
        v1 = fakes.world_thesis(self.folders)
        thesis_fakes.write_theses(self.folders.theses, [v1, thesis_fakes.thesis_v2(v1, self.folders.thesis_sources)],
                                  [thesis_fakes.OPENED_ON, thesis_fakes.V2_ON], thesis_id="copper")
        self.facts(lambda facts: passage(facts, CITED).update(printed_page="24"))
        flip_byte(fcx_file(self.folders, "10q-2026q3"))
        got = self.compare()
        self.assertEqual(got["state"], "needs_revalidation")
        self.assertEqual(len(got["reasons"]), 3)
        fcx_file(self.folders, "10k-2025").unlink()
        got = self.compare()
        self.assertEqual(got["state"], "unavailable")
        self.assertEqual(len(got["reasons"]), 4)


class AcquisitionTests(World):
    def replace(self):
        old = document(self.pinned, QUARTER)
        entry = fakes.replace_fcx_acquisition(self.folders, "10q-2026q3")
        return old, entry

    def test_replaced_acquisition_keeps_the_old_basis_verifiable(self):
        old, entry = self.replace()
        self.assertNotEqual(entry["attempt"], old["acquisition"]["attempt"])
        got = self.compare()
        self.assertEqual(self.states(got), {ref: "superseded" if ref == QUARTER else "verified" for ref in DOCUMENTS})
        self.assertEqual(got["state"], "needs_revalidation")
        self.assertEqual(evidence.verify_pinned(old, self.folders)["state"], "verified")
        repinned = evidence.pin(fakes.world_chain(None), self.folders)
        self.assertEqual(document(repinned, QUARTER)["acquisition"]["sha256"], entry["sha256"])
        self.assertEqual(self.compare(pinned=repinned)["state"], "available")

    def test_removing_the_old_file_fails_its_pinned_verification(self):
        old, _ = self.replace()
        acquisition = old["acquisition"]
        (self.folders.company_sources / acquisition["folder"] / acquisition["name"]).unlink()
        self.assertEqual(evidence.verify_pinned(old, self.folders)["state"], "missing")
        repinned = evidence.pin(fakes.world_chain(None), self.folders)
        self.assertEqual(evidence.verify_pinned(document(repinned, QUARTER), self.folders)["state"], "verified")

    def test_pinned_acquisition_verifies_like_the_live_entry(self):
        def live_state(folders, ref):
            kind, source_id = ref.split(":")
            if kind == "copper":
                version = thesis_schema.load_version("copper", 1, folders.theses)
                entry = next(item for item in version["sources"] if item["id"] == source_id)
                return thesis_sources.verify(entry, folders.thesis_sources)[0]["state"]
            entry = next(item for item in company_research_view.load_sources(folders.research)
                         if item["id"] == source_id)
            return company_research_view.verify(entry, folders.research, folders.company_sources)["state"]

        folders, pinned = self.world()
        flip_byte(folders.thesis_sources / "usgs-2026" / "copper.csv")
        fcx_file(folders, "10k-2025").unlink()
        seen = set()
        for world, evidence_block in ((self.folders, self.pinned), (folders, pinned)):
            for item in evidence_block["documents"]:
                with self.subTest(world=world.theses.parent.name, ref=item["ref"]):
                    state = evidence.verify_pinned(item, world)["state"]
                    self.assertEqual(state, live_state(world, item["ref"]))
                    seen.add(state)
        self.assertEqual(seen, {"verified", "changed", "missing"})


if __name__ == "__main__":
    unittest.main()

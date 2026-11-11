"""Publication comparisons (publication_comparison): strict loading, the pin and its comparison with live records, on
the SYNTHETIC world of tests/event_chain_fakes.py; the committed comparison against the committed records; and, opt-in
(SECOND_ORDER_FCX_SOURCES, read only), against the real retained FCX folder."""
import copy
import dataclasses
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import event_chain_fakes as fakes  # noqa: E402
from second_order import company_research_view, publication_comparison as pc, thesis_schema  # noqa: E402
from second_order.event_chain_schema import ChainRefused  # noqa: E402
from test_event_chain_view import fcx_file, flip_byte, read_json, write_json  # noqa: E402

FCX_OPT_IN = "SECOND_ORDER_FCX_SOURCES"
ID = fakes.WORLD_COMPARISON
COMMITTED = "fcx-annual-2025-to-q3-2026"


class World(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folders = fakes.write_world(Path(tmp.name) / "world")
        self.pinned = pc.pin(fakes.world_comparison(None), self.folders)

    def publish(self, version: dict | None = None) -> None:
        version = version or dict(fakes.world_comparison(None), evidence=self.pinned)
        fakes.write_comparison(self.folders.theses, ID, [version], ["2026-11-10"])

    def load(self) -> dict:
        return pc.load_comparisons(pc.comparisons_dir(self.folders.theses))[ID]["versions"][-1]

    def compared(self) -> dict:
        version = self.load()
        return pc.compare(version["evidence"], pc.live(version, self.folders))


class Pin(World):
    def test_the_pin_copies_each_passage_document_and_publication_and_the_version_loads(self):
        self.assertEqual([item["ref"] for item in self.pinned["passages"]],
                         [fakes.SECOND, fakes.THIRD, "fcx:k25-iupk-application-2026", "fcx:q3-p-iupk-extension"])
        self.assertEqual([item["ref"] for item in self.pinned["documents"]], ["fcx:10k-2025", "fcx:10q-2026q3"])
        self.assertEqual([(item["ref"], item["date"]) for item in self.pinned["publications"]],
                         [("fcx:10k-2025", "2026-02-13"), ("fcx:10q-2026q3", "2026-11-06")])
        self.publish()
        loaded = self.load()
        self.assertEqual((loaded["id"], loaded["version"], loaded["published_on"]), (ID, 1, "2026-11-10"))
        found = self.compared()
        self.assertEqual((found["state"], found["reasons"]), ("available", []))
        self.assertEqual({item["state"] for item in found["items"]}, {"same"})
        self.assertEqual({item["state"] for item in found["documents"]}, {"verified"})

    def test_a_row_must_take_its_earlier_line_from_the_earlier_publication(self):
        swapped = fakes.world_comparison(None)
        swapped["rows"][0]["earlier"], swapped["rows"][0]["later"] = fakes.THIRD, fakes.SECOND
        with self.assertRaises(ChainRefused) as raised:
            pc.pin(swapped, self.folders)
        self.assertEqual(raised.exception.status, 422)
        self.assertIn("rows[0].earlier", raised.exception.message)

    def test_an_unknown_passage_is_not_pinned(self):
        missing = fakes.world_comparison(None)
        missing["rows"][1]["later"] = "fcx:no-such-passage"
        with self.assertRaises(ChainRefused) as raised:
            pc.pin(missing, self.folders)
        self.assertEqual(raised.exception.status, 422)

    def test_a_listed_price_is_a_published_dated_figure_of_one_of_the_two_publications(self):
        # A figure of the results release, a passage id and an unknown id: a note's basis would not pin their document.
        for ident in ("r3-cu-price-q3-2026", "k25-mud-rush-85pct", "no-such-record"):
            other = fakes.world_comparison(None)
            other["prices"].append(ident)
            with self.subTest(ident=ident), self.assertRaises(ChainRefused) as raised:
                pc.pin(other, self.folders)
            self.assertEqual(raised.exception.status, 422)
            self.assertIn("prices[2]", raised.exception.message)

    def test_a_listed_price_names_its_measure_and_a_period_of_real_days_in_order(self):
        """What the page's reader requires of a price figure is required here, where a version is published."""
        listed = "q3-cu-realized-price-q3-2026"
        facts = self.folders.research / "facts.json"
        original = facts.read_bytes()
        changes = (lambda record: record["period"].update(start="July 2026"),
                   lambda record: record["period"].update(start="2026-10-01"),  # After its last day.
                   lambda record: record["period"].update(end="2026-09-31"),
                   lambda record: record["period"].update(label=""),
                   lambda record: record.update(metric=""))
        for change in changes:
            data = read_json(facts)
            change(next(item for item in data["records"] if item["id"] == listed))
            write_json(facts, data)
            with self.assertRaises(ChainRefused) as raised:
                pc.pin(fakes.world_comparison(None), self.folders)
            self.assertIn("prices[1]", raised.exception.message)
            facts.write_bytes(original)
        self.assertEqual(pc.pin(fakes.world_comparison(None), self.folders), self.pinned)


class PinCommand(World):
    def test_the_pin_command_fills_the_evidence_and_the_index_once(self):
        from datetime import date
        from second_order import publication_comparison_cli as cli
        folder = pc.comparisons_dir(self.folders.theses) / ID
        folder.mkdir(parents=True)
        write_json(folder / "v1.json", fakes.world_comparison(None))
        args = (ID, 1, date(2026, 11, 10), self.folders.theses, self.folders.research, self.folders.company_sources)
        done = cli.pin_version(*args)
        self.assertEqual((done["comparison"], done["version"]), (ID, 1))
        loaded = self.load()
        self.assertEqual((loaded["evidence"], loaded["sha256"]), (self.pinned, done["sha256"]))
        self.assertNotIn(bytes([13, 10]), (folder / "v1.json").read_bytes())  # LF only.
        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        with self.assertRaises(ChainRefused) as raised:  # A published version never changes.
            cli.pin_version(*args)
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)


class Loading(World):
    def refused(self, change) -> str:
        version = dict(fakes.world_comparison(None), evidence=copy.deepcopy(self.pinned))
        change(version)
        self.publish(version)
        with self.assertRaises(ChainRefused) as raised:
            self.load()
        self.assertEqual(raised.exception.status, 500)
        return raised.exception.message

    def test_no_row_holds_or_computes_a_change(self):
        """The owner's clarification of 2026-11-10: two lines are shown with their own definitions and dates; an
        arithmetic fall or rise between them is never derived. A row has no field for one."""
        for field in ("change", "change_pct", "difference", "delta"):
            message = self.refused(lambda v: v["rows"][0].update({field: "-5"}))
            self.assertIn("rows[0]", message)
            self.assertIn("exactly the fields", message)

    def test_the_assistants_words_on_a_row_never_state_a_change_between_its_lines(self):
        """The rule on fields is not enough: a note, a label or the title could say the change in words. Every figure
        below is in the row's quotes, so only this rule refuses them."""
        notes = ("The expected share fell from 85% to 80%.", "Down from 85% to 80%, a decrease.",
                 "The later line is lower than the earlier one.", "85% -> 80%", "85% → 80%",
                 "The later line is a reduction of the earlier one.", "The share went up between the two reports.")
        for note in notes:
            with self.subTest(note=note):
                self.assertIn("states a change between the two lines",
                              self.refused(lambda v: v["rows"][0].update(note=note)))
        self.assertIn("states a change between the two lines",
                      self.refused(lambda v: v["rows"][0].update(label="The cut in the restart share")))
        self.assertIn("states a change between the two lines",
                      self.refused(lambda v: v.update(title="Synthetic: the annual report -> the quarterly report")))
        # A hyphenated compound such as "ramp-up" is a name, not a direction.
        version = dict(fakes.world_comparison(None), evidence=copy.deepcopy(self.pinned))
        version["rows"][0]["label"] = "The ramp-up of the block cave"
        self.publish(version)
        self.assertEqual(self.load()["rows"][0]["label"], "The ramp-up of the block cave")

    def test_a_row_says_whether_its_two_lines_are_the_same_measure(self):
        self.assertIn("same_measure", self.refused(lambda v: v["rows"][0].update(same_measure="yes")))
        # Unless the question does not apply, the row carries the assistant's note on what each line measures.
        self.assertIn("rows[0].note", self.refused(lambda v: v["rows"][0].update(note=None)))

    def test_the_assistants_text_keeps_its_rules(self):
        cases = {
            "a claim word": lambda v: v["rows"][0].update(label="What caused the delay"),
            "a view on a price's direction": lambda v: v.update(title="Synthetic: prices will rise after the report"),
            "states no figures": lambda v: v["rows"][0].update(label="The 85 percent line"),
            "holds figures its quotes do not": lambda v: v["rows"][0].update(
                note="The earlier line is about 999 units; the later is about capacity."),
            "repeats six words": lambda v: v["rows"][0].update(
                note="PTFI continues to expect to reach the same capacity as planned."),
        }
        for rule, change in cases.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, self.refused(change))

    def test_the_shape_is_exact(self):
        self.assertIn("fcx: reference", self.refused(lambda v: v["rows"][0].update(earlier="copper:fcx-mud-rush-2025")))
        self.assertIn("rows", self.refused(lambda v: v.update(rows=[])))
        self.assertIn("repeats", self.refused(lambda v: v["rows"][1].update(id="return-to-operation")))
        self.assertIn("expected true or false", self.refused(lambda v: v.update(historical="yes")))
        self.assertIn("excluded", self.refused(lambda v: v["provenance"].update(research_use="included")))
        self.assertIn("evidence.passages", self.refused(lambda v: v["evidence"]["passages"].pop()))
        self.assertIn("SHA-256", self._index_mismatch())

    def _index_mismatch(self) -> str:
        self.publish()
        path = pc.comparisons_dir(self.folders.theses) / ID / "v1.json"
        data = read_json(path)
        data["title"] = "Synthetic: another title"
        write_json(path, data)
        with self.assertRaises(ChainRefused) as raised:
            self.load()
        return raised.exception.message


class Compare(World):
    def setUp(self):
        super().setUp()
        self.publish()

    def test_a_changed_record_is_evidence_changed_and_an_unrelated_one_is_not(self):
        facts = self.folders.research / "facts.json"
        data = read_json(facts)
        next(i for i in data["passages"] if i["id"] == "q3-p-smelter-restart").update(printed_page="99")
        write_json(facts, data)
        self.assertEqual(self.compared()["state"], "available")
        next(i for i in data["passages"] if i["id"] == "q3-p-iupk-extension").update(printed_page="99")
        write_json(facts, data)
        found = self.compared()
        self.assertEqual(found["state"], "evidence_changed")
        self.assertEqual([item["ref"] for item in found["items"] if item["state"] == "changed"],
                         ["fcx:q3-p-iupk-extension"])

    def test_a_changed_document_needs_revalidation_and_a_missing_one_is_unavailable(self):
        quarter = fcx_file(self.folders, "10q-2026q3")
        original = flip_byte(quarter)
        found = self.compared()
        self.assertEqual(found["state"], "needs_revalidation")
        self.assertEqual({item["ref"]: item["state"] for item in found["documents"]},
                         {"fcx:10k-2025": "verified", "fcx:10q-2026q3": "changed"})
        quarter.unlink()
        self.assertEqual(self.compared()["state"], "unavailable")
        quarter.write_bytes(original)
        self.assertEqual(self.compared()["state"], "available")

    def test_an_unreadable_research_file_makes_everything_unreadable(self):
        (self.folders.research / "facts.json").write_bytes(b"{")
        found = self.compared()
        self.assertEqual(found["state"], "unavailable")
        self.assertEqual({item["state"] for item in found["items"] if item["kind"] == "passage"}, {"unreadable"})

    def test_a_later_date_of_a_publication_is_evidence_changed(self):
        sources = self.folders.research / "sources.json"
        data = read_json(sources)
        next(i for i in data["sources"] if i["id"] == "10q-2026q3").update(date="2026-11-07")
        write_json(sources, data)
        found = self.compared()
        self.assertEqual(found["state"], "evidence_changed")
        self.assertEqual([(item["kind"], item["ref"]) for item in found["items"] if item["state"] == "changed"],
                         [("publication", "fcx:10q-2026q3")])


class Committed(unittest.TestCase):
    """The committed comparison is valid content, and its pins are the committed records' wording."""

    def test_version_two_changes_only_the_evidence_and_the_note(self):
        """The private tree's version 2 (re-pinned to the SEC copies); the public tree holds one version, so it skips."""
        versions = pc.load_comparisons(pc.comparisons_dir(thesis_schema.THESES_DIR))[COMMITTED]["versions"]
        if len(versions) < 2:
            self.skipTest("one version here (the public tree renumbers the SEC version to 1)")
        first, later = versions[0], versions[1]
        self.assertEqual((later["version"], later["previous_version"], later["published_on"]), (2, 1, "2026-11-11"))
        self.assertEqual(later["change"], {"note": "Evidence re-pinned to the SEC EDGAR copies of the quarterly "
                                                   "report and the releases; wording and places checked."})
        keys = ("title", "earlier", "later", "historical", "rows", "prices", "provenance")
        self.assertEqual({k: later[k] for k in keys}, {k: first[k] for k in keys})

    def test_committed_content_loads_and_its_pins_match_the_committed_records(self):
        comparisons = pc.load_comparisons(pc.comparisons_dir(thesis_schema.THESES_DIR))
        self.assertEqual(sorted(comparisons), [COMMITTED])
        versions = comparisons[COMMITTED]["versions"]  # the public tree may hold one version, renumbered to 1
        first, version = versions[0], versions[-1]
        self.assertEqual((first["version"], first["previous_version"], first["change"]), (1, None, None))
        self.assertEqual(version["version"], len(versions))
        self.assertEqual((version["historical"], len(version["rows"])), (True, 7))
        self.assertEqual((version["earlier"], version["later"]),
                         ({"document": "fcx:10k-2025"}, {"document": "fcx:10q-2026q3"}))
        self.assertEqual(version["provenance"]["research_use"], "excluded")
        with tempfile.TemporaryDirectory() as tmp:
            folders = dataclasses.replace(fakes.world_folders(Path(tmp)), research=company_research_view.RESEARCH_DIR)
            found = pc.compare(version["evidence"], pc.live(version, folders))
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual({item["state"] for item in found["items"]}, {"same"})
        # Without the retained documents every document is missing and nothing is available.
        self.assertEqual((found["state"], {item["state"] for item in found["documents"]}), ("unavailable", {"missing"}))


@unittest.skipUnless(os.environ.get(FCX_OPT_IN), f"set {FCX_OPT_IN} to the retained FCX folder to check it, read-only")
class RealSources(unittest.TestCase):
    def test_real_documents_make_the_committed_comparison_available(self):
        company = Path(os.environ[FCX_OPT_IN])
        self.assertTrue(company.is_absolute() and company.is_dir(), f"{company} names no folder")
        version = pc.load_comparisons(pc.comparisons_dir(thesis_schema.THESES_DIR))[COMMITTED]["versions"][-1]
        with tempfile.TemporaryDirectory() as tmp:
            folders = dataclasses.replace(fakes.world_folders(Path(tmp)), research=company_research_view.RESEARCH_DIR,
                                          company_sources=company)
            found = pc.compare(version["evidence"], pc.live(version, folders))
        self.assertEqual((found["state"], found["reasons"]), ("available", []))
        self.assertEqual({item["state"] for item in found["documents"]}, {"verified"})


if __name__ == "__main__":
    unittest.main()

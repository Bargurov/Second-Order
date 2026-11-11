"""Event-chain content: the mechanism list and chain versions load strictly, and every content rule refuses with 500
at a precise place and with a distinctive rule text."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from second_order import bis_snapshot, event_chain_schema as schema  # noqa: E402
from tests import event_chain_fakes as fakes  # noqa: E402
from tests.thesis_fakes import changed  # noqa: E402

DAY = "2026-11-05"
CHAIN = "event-chains/synthetic-chain"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.metals, self.theses = Path(self.tmp.name) / "metals", Path(self.tmp.name) / "theses"
        fakes.write_mechanisms(self.metals)
        self.evidence = fakes.shape_evidence(self.metals)

    def write(self, versions, published=None):
        fakes.write_chain(self.theses, "synthetic-chain", versions, published or [DAY] * len(versions))

    def load_written(self):
        mechanisms = schema.load_mechanisms(schema.mechanisms_dir(self.metals))
        return schema.load_chains(schema.chains_dir(self.theses), mechanisms)

    def load(self, versions, published=None):
        self.write(versions, published)
        return self.load_written()

    def refused(self, call, prefix, rule):
        """``call`` must raise ChainRefused(500) whose message starts with ``prefix + ': '`` and holds ``rule``."""
        with self.assertRaises(schema.ChainRefused) as caught:
            call()
        message = caught.exception.message
        self.assertEqual(caught.exception.status, 500)
        self.assertTrue(message.startswith(f"{prefix}: "), message)
        self.assertIn(rule, message)

    def expect(self, versions, place, rule):
        self.refused(lambda: self.load(versions), f"{CHAIN}/v{len(versions)}.json{place}", rule)


class ChainTests(Base):
    def test_valid_synthetic_chain_loads(self):
        chain = fakes.chain_v1(self.evidence)
        version = self.load([chain])["synthetic-chain"]["versions"][0]
        self.assertEqual(version["sha256"], bis_snapshot.sha256(bis_snapshot.canonical(chain)))
        self.assertEqual(version["published_on"], DAY)

    def test_each_content_rule_refuses_with_500(self):
        v1 = fakes.chain_v1(self.evidence)
        v2 = changed(v1, lambda c: c.update(version=2, previous_version=1,
                                            change={"answers_review": None, "note": "A corrected record"}))
        ev = ".evidence"
        cases = {
            "an extra field": (v1, lambda c: c.update(extra=1), "", "expected exactly the fields"),
            "a measured step": (v1, lambda c: c["steps"].insert(2, {"kind": "measured"}), ".steps[2].kind",
                                "expected stated, not_stated or mechanism"),
            "mechanism before stated": (v1, lambda c: c["steps"].insert(1, {"kind": "mechanism",
                                                                            "id": "thin-stocks"}),
                                        ".steps[2]", "may not follow a later kind"),
            "no mechanism": (v1, lambda c: c["steps"].pop(), ".steps", "expected at least one mechanism step"),
            "first step not the event": (v1, lambda c: c["steps"][0].update(passage=fakes.SECOND),
                                         ".steps[0].passage", "differs from the chain's event"),
            "caused": (v1, lambda c: c["steps"][1].update(label="The release caused a halt"), ".steps[1].label",
                       "a claim word"),
            "digit absent from quote": (v1, lambda c: c["steps"][1].update(label="One pit lost 7 weeks"),
                                        ".steps[1].label", "holds figures its quote does not"),
            "six words repeated": (v1, lambda c: c["steps"][1].update(
                label="a made-up wet-material release halted one"), ".steps[1].label",
                                   "repeats six words of its quote"),
            "not_stated prefix": (v1, lambda c: c["steps"][2].update(text="The source is silent on the return"),
                                  ".steps[2].text", 'expected to start "No retained source states "'),
            "not_stated digit": (v1, lambda c: c["steps"][2].update(text="No retained source states 3 returns"),
                                 ".steps[2].text", "states no figures"),
            "title digit": (v1, lambda c: c.update(title="A halted pit in 2025"), ".title", "states no figures"),
            "title too long": (v1, lambda c: c.update(title="a" * 101), ".title", "at most 100 characters"),
            "label too long": (v1, lambda c: c["steps"][1].update(label="a" * 81), ".steps[1].label",
                               "at most 80 characters"),
            "label with a line separator": (v1, lambda c: c["steps"][1].update(label="A halted pit and a mill"),
                                            ".steps[1].label", "expected one line of text"),
            "label with a paragraph separator": (v1, lambda c: c["steps"][1].update(
                label="A halted pit and a mill"), ".steps[1].label", "expected one line of text"),
            "label with a control character": (v1, lambda c: c["steps"][1].update(label="A halted pit\x85and a mill"),
                                               ".steps[1].label", "expected one line of text"),
            "passages differ from steps": (v1, lambda c: c["evidence"]["passages"].reverse(), ev + ".passages",
                                           "exactly the stated steps' passages, in step order"),
            "evidence event differs": (v1, lambda c: c["evidence"]["event"].update(passage=fakes.SECOND),
                                       ev + ".event.passage", "differs from the chain's event"),
            "mechanism id missing": (v1, lambda c: c["steps"][3].update(id="unknown-mechanism"), ".steps[3].id",
                                     "names a mechanism the pinned mechanisms version lacks"),
            "mechanisms sha differs": (v1, lambda c: c["evidence"]["mechanisms"].update(sha256="0" * 64),
                                       ev + ".mechanisms.sha256", "differs from the SHA-256 its mechanisms index"),
            "mechanisms version not published": (v1, lambda c: c["evidence"]["mechanisms"].update(version=2),
                                                 ev + ".mechanisms.version", "is not published"),
            "v1 change not null": (v1, lambda c: c.update(change={"answers_review": None, "note": "x"}),
                                   ".change", "expected null in version 1"),
            "v2 change null": (v2, lambda c: c.update(change=None), ".change", "expected an object"),
            "wrong previous_version": (v2, lambda c: c.update(previous_version=5), ".previous_version",
                                       "expected 1"),
            "change note digit": (v2, lambda c: c["change"].update(note="A fix in 2026"), ".change.note",
                                  "states no figures"),
            "answers_review bad": (v2, lambda c: c["change"].update(answers_review="ABC"),
                                   ".change.answers_review", "64 lowercase hex characters"),
            "ai_assisted false": (v1, lambda c: c["provenance"].update(ai_assisted=False),
                                  ".provenance.ai_assisted", "expected true"),
            "research_use": (v1, lambda c: c["provenance"].update(research_use="included"),
                             ".provenance.research_use", 'expected "excluded"'),
            "acquisition missing key": (v1, lambda c: c["evidence"]["documents"][0]["acquisition"].pop("origin"),
                                        ev + ".documents[0].acquisition", "expected exactly the fields"),
            "documents unsorted": (v1, lambda c: c["evidence"]["documents"].reverse(), ev + ".documents",
                                   "sorted by ref, each once"),
            # Wrong-typed values refuse; they never raise TypeError or KeyError.
            "steps as a dict": (v1, lambda c: c.update(steps={}), ".steps", "expected a list of steps"),
            "a step as a string": (v1, lambda c: c["steps"].__setitem__(1, "stated"), ".steps[1]",
                                   "expected an object"),
            "label as a number": (v1, lambda c: c["steps"][1].update(label=5), ".steps[1].label",
                                  "expected one line of text"),
            "document as a list": (v1, lambda c: c["evidence"]["documents"].__setitem__(0, []),
                                   ev + ".documents[0]", "expected an object"),
            "attempt as a string": (v1, lambda c: c["evidence"]["documents"][0]["acquisition"].update(attempt="1"),
                                    ev + ".documents[0].acquisition.attempt", "expected a whole number"),
        }
        for name, (base, edit, place, rule) in cases.items():
            with self.subTest(name):
                bad = changed(base, edit)
                self.expect([v1, bad] if base is v2 else [bad], place, rule)

    def test_a_published_on_of_null_refuses(self):
        self.refused(lambda: self.load([fakes.chain_v1(self.evidence)], [None]),
                     f"{CHAIN}/index.json.versions[0].published_on", "expected a date")

    def test_a_root_that_is_not_an_object_refuses(self):
        self.expect([[]], "", "expected an object")

    def test_malformed_json_refuses(self):
        self.write([fakes.chain_v1(self.evidence)])
        (schema.chains_dir(self.theses) / "synthetic-chain" / "v1.json").write_bytes(b"{")
        self.refused(self.load_written, f"{CHAIN}/v1.json", "not strict UTF-8 JSON")

    def test_index_sha_mismatch_refuses(self):
        self.write([fakes.chain_v1(self.evidence)])
        path = schema.chains_dir(self.theses) / "synthetic-chain" / "index.json"
        index = json.loads(path.read_bytes())
        index["versions"][0]["sha256"] = "0" * 64
        path.write_bytes(json.dumps(index).encode())
        self.refused(self.load_written, f"{CHAIN}/v1.json", "does not match the SHA-256 its index records")

    def test_crlf_copy_of_a_version_still_matches_its_index(self):
        self.write([fakes.chain_v1(self.evidence)])
        path = schema.chains_dir(self.theses) / "synthetic-chain" / "v1.json"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertIn("synthetic-chain", self.load_written())

    def test_a_missing_chains_folder_is_no_chains(self):
        self.assertEqual(schema.load_chains(self.theses / "none", {}), {})


class MechanismTests(Base):
    folder = property(lambda self: schema.mechanisms_dir(self.metals))

    def load_refused(self, prefix, rule):
        self.refused(lambda: schema.load_mechanisms(self.folder), prefix, rule)

    def test_valid_list_loads(self):
        self.assertEqual(schema.load_mechanisms(self.folder)[1]["entries"], fakes.MECHANISMS)

    def test_text_rules(self):
        cases = {"Stocks are thin.": 'starting with "When " or "If "',
                 "When 5 mines halt, supply is short.": "states no figures",
                 "When a pit halts, the move was caused by it.": "a claim word",
                 "When a pit halts,\nsupply is short.": "expected one line of text"}
        for text, rule in cases.items():
            with self.subTest(text):
                fakes.write_mechanisms(self.metals, {"one": text})
                self.load_refused("mechanisms/v1.json.entries[0].text", rule)

    def test_text_over_240_characters_refuses(self):
        fakes.write_mechanisms(self.metals, {"one": "When " + "a" * 236})
        self.load_refused("mechanisms/v1.json.entries[0].text", "at most 240 characters")

    def test_duplicate_ids_refuse(self):
        version = json.loads((self.folder / "v1.json").read_bytes())
        version["entries"].append(dict(version["entries"][0]))
        (self.folder / "v1.json").write_bytes(json.dumps(version).encode())
        index = json.loads((self.folder / "index.json").read_bytes())
        index["versions"][0]["sha256"] = bis_snapshot.sha256(bis_snapshot.canonical(version))
        (self.folder / "index.json").write_bytes(json.dumps(index).encode())
        self.load_refused("mechanisms/v1.json.entries[2].id", "repeats an earlier mechanism")

    def test_index_sha_mismatch_with_the_version_file_refuses(self):
        index = json.loads((self.folder / "index.json").read_bytes())
        index["versions"][0]["sha256"] = "0" * 64
        (self.folder / "index.json").write_bytes(json.dumps(index).encode())
        self.load_refused("mechanisms/v1.json", "does not match the SHA-256 its index records")


if __name__ == "__main__":
    unittest.main()

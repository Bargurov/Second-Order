"""The committed copper event chains: the pin command on a SYNTHETIC world, the committed content against spec
section 8, the committed pins against the committed records, and the chains without retained sources. One opt-in test
reads the real retained copper and FCX folders (SECOND_ORDER_THESIS_SOURCES and SECOND_ORDER_FCX_SOURCES, both read
only): every chain is then available, and reading changes nothing."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import event_chain_fakes as fakes  # noqa: E402
from second_order import company_research_view, event_chain_evidence as evidence, metals_research  # noqa: E402
from second_order import metals_view, thesis_schema  # noqa: E402
from second_order.__main__ import main  # noqa: E402
from second_order.event_chain_evidence import Folders  # noqa: E402
from second_order.event_chain_schema import chains_dir, load_chains, load_mechanisms, mechanisms_dir  # noqa: E402
from second_order.event_chain_view import view  # noqa: E402

THESES, METALS, RESEARCH = thesis_schema.THESES_DIR, metals_view.METALS_DIR, company_research_view.RESEARCH_DIR
THESIS_OPT_IN, FCX_OPT_IN = "SECOND_ORDER_THESIS_SOURCES", "SECOND_ORDER_FCX_SOURCES"
PUBLISHED_ON = "2026-11-09"
PREPARED_BY = "the assistant (Claude), AI draft for the owner's review"
# Spec section 8, verbatim: the mechanism list, version 1.
MECHANISMS = {
    "output-offset": "When output at one mine falls and other mines do not add the same amount, world mine output is "
                     "lower than it would otherwise have been.",
    "restart-timing": "When a stopped mine is expected to restart in stages, how long the lost output lasts depends on "
                      "when each stage restarts.",
    "ore-grade": "When ore grades at operating mines fall, each tonne of ore holds less copper, so output falls unless "
                 "more ore is mined and processed.",
    "expansion-counting": "When a producer approves an expansion, the added output enters future mine supply only "
                          "if it is built as planned, and a projection includes it only if its method counts approved "
                          "projects.",
}
# Spec section 8: each chain's register event, its stated steps in order (the event first), its not-stated lines, its
# mechanisms in order and its target.
CASES = {
    "bagdad-expansion": {
        "event": {"passage": "fcx:q3-p-bagdad-approval", "kind": "Investment decision", "when": "November 2026"},
        "stated": ["fcx:q3-p-bagdad-approval", "fcx:nr-p-double-rates"],
        "not_stated": ["No retained source states whether the IEA base case already counts this expansion."],
        "mechanisms": ["expansion-counting"], "target": {"kind": "reason", "id": "mine-pipeline"}},
    "grasberg-mud-rush": {
        "event": {"passage": "copper:fcx-mud-rush-2025", "kind": "Supply disruption", "when": "September 2025"},
        "stated": ["copper:fcx-mud-rush-2025", "fcx:k25-mud-rush-gbc-restart", "fcx:k25-mud-rush-85pct",
                   "fcx:q3-p-gbc-capacity-targets"],
        "not_stated": [], "mechanisms": ["output-offset", "restart-timing"],
        "target": {"kind": "reason", "id": "world-mine-output"}},
    "us-ore-grades": {
        "event": {"passage": "copper:usgs26-mine-events", "kind": "Supply disruption", "when": "2025"},
        "stated": ["copper:usgs26-mine-events"], "not_stated": [], "mechanisms": ["ore-grade", "output-offset"],
        "target": {"kind": "reason", "id": "world-mine-output"}},
}
# The steps that state a company's expectation are labelled as one, apart from the board's approval (spec 8 and 9).
EXPECTATIONS = ("fcx:k25-mud-rush-85pct", "fcx:q3-p-gbc-capacity-targets", "fcx:nr-p-double-rates")


def read_json(path: Path):
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def run_main(argv: list[str]) -> tuple[int, str, str]:
    with (mock.patch.object(sys, "argv", ["second_order", *argv]),
          mock.patch("sys.stdout", new_callable=io.StringIO) as out,
          mock.patch("sys.stderr", new_callable=io.StringIO) as err):
        code = main()
    return code, out.getvalue(), err.getvalue()


def committed(sources: Path, company_sources: Path, records: Path) -> Folders:
    """The committed content (theses, register, mechanisms, FCX research) with the given retained-source roots."""
    return Folders(theses=THESES, thesis_sources=sources, metals=METALS, metals_sources=sources, research=RESEARCH,
                   company_sources=company_sources, records=records)


def fingerprint(*folders: Path) -> dict:
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            for folder in folders for path in sorted(Path(folder).rglob("*")) if path.is_file()}


def chains() -> dict:
    return load_chains(chains_dir(THESES), load_mechanisms(mechanisms_dir(METALS)))


class PinCommand(unittest.TestCase):
    def test_pin_command_fills_evidence_and_index(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folders = fakes.write_world(Path(tmp.name))
        folder = chains_dir(folders.theses) / fakes.WORLD_CHAIN
        folder.mkdir(parents=True)
        (folder / "v1.json").write_bytes(
            (json.dumps(fakes.world_chain(None), indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        argv = ["event-chains", "pin", "--chain", fakes.WORLD_CHAIN, "--version", "1", "--published-on", PUBLISHED_ON,
                "--theses", str(folders.theses), "--thesis-sources", str(folders.thesis_sources),
                "--metals", str(folders.metals), "--research", str(folders.research),
                "--company-sources", str(folders.company_sources)]

        code, out, err = run_main(argv)
        self.assertEqual(code, 0, err)
        pinned = evidence.pin(fakes.world_chain(None), folders)
        expected = fakes.world_chain(pinned)
        self.assertEqual((folder / "v1.json").read_bytes(),
                         (json.dumps(expected, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        sha256 = canonical_sha256(expected)
        self.assertEqual(json.loads(out), {"chain": fakes.WORLD_CHAIN, "version": 1, "sha256": sha256})
        index = (folder / "index.json").read_bytes()
        self.assertNotIn(b"\r", index)
        self.assertEqual(json.loads(index.decode("utf-8")), {
            "index_version": "event-chain-index-0.1", "id": fakes.WORLD_CHAIN,
            "versions": [{"version": 1, "file": "v1.json", "sha256": sha256, "published_on": PUBLISHED_ON}]})
        loaded = load_chains(chains_dir(folders.theses), load_mechanisms(mechanisms_dir(folders.metals)))
        self.assertEqual(loaded[fakes.WORLD_CHAIN]["versions"][0]["evidence"], pinned)

        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        code, out, err = run_main(argv)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Failed: ", err)
        self.assertIn("version 1 is already in the index", err)
        self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)


REPINNED = ("grasberg-mud-rush", "bagdad-expansion")
REPIN_NOTE = ("Evidence re-pinned to the SEC EDGAR copies of the quarterly report and the releases; wording and "
              "places checked.")


class Committed(unittest.TestCase):
    def test_a_repinned_version_two_changes_only_the_evidence_and_the_note(self):
        """The private tree's version 2 of each re-pinned chain; the public tree holds one version, so it skips."""
        found = chains()
        for chain_id in REPINNED:
            versions = found[chain_id]["versions"]
            if len(versions) < 2:
                self.skipTest(f"{chain_id} holds one version here (the public tree renumbers the SEC version to 1)")
            first, later = versions[0], versions[1]
            self.assertEqual((later["version"], later["previous_version"], later["published_on"]),
                             (2, 1, "2026-11-11"))
            self.assertEqual(later["change"], {"answers_review": None, "note": REPIN_NOTE})
            keys = ("title", "event", "target", "steps", "provenance")
            self.assertEqual({k: later[k] for k in keys}, {k: first[k] for k in keys})

    def test_committed_content_loads_and_matches_the_spec_cases(self):
        mechanisms = load_mechanisms(mechanisms_dir(METALS))
        self.assertEqual(list(mechanisms), [1])
        self.assertEqual(list(mechanisms[1]["entries"].items()), list(MECHANISMS.items()))
        self.assertEqual(mechanisms[1]["published_on"], PUBLISHED_ON)
        register = metals_research.load(METALS)["metals"]["copper"]["events"]
        found = chains()
        self.assertEqual(sorted(found), sorted(CASES))
        for chain_id, case in CASES.items():
            with self.subTest(chain=chain_id):
                versions = found[chain_id]["versions"]
                self.assertTrue(versions)
                first, version = versions[0], versions[-1]  # the public tree may hold one version, renumbered to 1
                self.assertEqual((first["version"], first["previous_version"], first["change"]), (1, None, None))
                self.assertEqual(version["version"], len(versions))
                self.assertEqual(version["provenance"], {"prepared_by": PREPARED_BY, "ai_assisted": True,
                                                         "research_use": "excluded"})
                self.assertEqual(version["event"], case["event"]["passage"])
                self.assertIn(case["event"], register)
                self.assertEqual(version["evidence"]["event"], case["event"])
                self.assertEqual(version["target"], case["target"])
                steps = version["steps"]
                kinds = [step["kind"] for step in steps]
                self.assertEqual(kinds, ["stated"] * len(case["stated"]) + ["not_stated"] * len(case["not_stated"])
                                 + ["mechanism"] * len(case["mechanisms"]))
                self.assertEqual([step["passage"] for step in steps if step["kind"] == "stated"], case["stated"])
                self.assertEqual([step["text"] for step in steps if step["kind"] == "not_stated"], case["not_stated"])
                self.assertEqual([step["id"] for step in steps if step["kind"] == "mechanism"], case["mechanisms"])
                self.assertEqual(version["evidence"]["mechanisms"], {"version": 1, "sha256": mechanisms[1]["sha256"]})
                for step in steps:
                    if step["kind"] == "stated" and step["passage"] in EXPECTATIONS:
                        self.assertIn("expectation", step["label"], step["passage"])
        bagdad = found["bagdad-expansion"]["versions"][-1]["steps"][0]["label"]
        self.assertIn("approval", bagdad)
        self.assertNotIn("expect", bagdad)

    def test_committed_pins_match_the_committed_records(self):
        """Fails whenever a cited record, the register event, a document's source entry or the thesis version changes
        without a new chain version."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            folders = committed(empty, empty, empty / "records")
            published = evidence.latest_published(THESES)
            committed_chains = chains()
            self.assertEqual(sorted(committed_chains), sorted(CASES))
            for chain_id, chain in committed_chains.items():
                with self.subTest(chain=chain_id):
                    version = chain["versions"][-1]
                    pinned = version["evidence"]
                    now = evidence.live(version, folders)
                    compared = evidence.compare(pinned, now)
                    # Exactly the pinned event and each pinned passage, each the same as its record now.
                    expected = [("event", pinned["event"]["passage"], "same")] + [
                        ("passage", item["ref"], "same") for item in pinned["passages"]]
                    self.assertTrue(pinned["passages"])
                    self.assertEqual([(item["kind"], item["ref"], item["state"]) for item in compared["items"]],
                                     expected)
                    self.assertEqual(sorted(now["documents"]), [item["ref"] for item in pinned["documents"]])
                    for document in pinned["documents"]:
                        self.assertEqual(now["documents"][document["ref"]]["acquisition"], document["acquisition"],
                                         document["ref"])
                    self.assertEqual({item["state"] for item in compared["documents"]}, {"missing"})
                    self.assertEqual(pinned["thesis"], {"id": "copper", "version": published["version"],
                                                        "sha256": published["sha256"]})

    def test_without_retained_sources_every_chain_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            served = view(committed(empty, empty, empty / "records"))
            self.assertEqual(sorted(chain["id"] for chain in served["chains"]), sorted(CASES))
            for chain in served["chains"]:
                with self.subTest(chain=chain["id"]):
                    self.assertEqual(chain["state"], "unavailable")
                    self.assertEqual({item["state"] for item in chain["documents"]}, {"missing"})
                    self.assertEqual(chain["approval"]["state"], "awaiting_review")
                    for step in chain["steps"]:
                        if step["kind"] == "stated":
                            self.assertIsNone(step["quote"])
                            self.assertEqual(step["state"], "missing")
            self.assertEqual(list(empty.iterdir()), [])


@unittest.skipUnless(os.environ.get(THESIS_OPT_IN) and os.environ.get(FCX_OPT_IN),
                     f"set {THESIS_OPT_IN} to the retained copper folder and {FCX_OPT_IN} to the retained FCX folder "
                     "to check them, read-only")
class RealSources(unittest.TestCase):
    def test_real_sources_make_every_chain_available(self):
        sources, company = (Path(os.environ[name]) for name in (THESIS_OPT_IN, FCX_OPT_IN))
        for folder in (sources, company):
            self.assertTrue(folder.is_absolute() and folder.is_dir(), f"{folder} names no folder")
        content = (THESES, METALS, RESEARCH)
        before = fingerprint(sources, company, *content)
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp) / "records"
            served = view(committed(sources, company, records))
            self.assertFalse(records.exists())
        self.assertEqual(sorted(chain["id"] for chain in served["chains"]), sorted(CASES))
        for chain in served["chains"]:
            with self.subTest(chain=chain["id"]):
                self.assertEqual((chain["state"], chain["reasons"]), ("available", []))
                self.assertEqual({item["state"] for item in chain["documents"]}, {"verified"})
                self.assertEqual({item["state"] for item in chain["items"]}, {"same"})
                self.assertEqual(chain["target"]["state"], "available")
                for step in chain["steps"]:
                    if step["kind"] == "stated":
                        self.assertEqual(step["state"], "verified", step["ref"])
                        self.assertTrue(step["quote"])
        self.assertEqual(fingerprint(sources, company, *content), before)


if __name__ == "__main__":
    unittest.main()

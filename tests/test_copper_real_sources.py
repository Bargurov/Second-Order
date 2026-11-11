"""The copper tools on the committed catalogue. In the default run: thesis v1's files and hashes are unchanged by the
tools. As an explicit opt-in (SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper folder>, the same
folder the thesis's opt-in check reads): every catalogue item verifies against the real retained sources, the design's
worked example reproduces from them, and the folder is proved unchanged (every file's size, mtime and SHA-256), with
scenarios saved only in a temporary folder."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from second_order import (bis_snapshot, copper_coverage as cc, copper_inputs, copper_producers as cp,
                          copper_tools_view)
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
OPT_IN = "SECOND_ORDER_THESIS_SOURCES"
COMMITTED = ROOT / "content" / "tools" / "copper-coverage"
THESIS = ROOT / "content" / "theses" / "copper"
INDEX_SHA256 = "6c9e5464496500fca39536d41690eff8412d81a51a8dfacc50008930fc0c9b5a"  # index.json's bytes
V1_CANONICAL = "4893928f936d3dd3a75ffb37238526d69c809131c72351f938b134d2249e956f"  # v1.json's canonical JSON
SET_A = {"ev": {"source": "scenario", "scenario": "cps"},
         "networks": {"source": "technology_case", "scenario": "steps"},
         "mine": {"source": "total", "kt": "-294.8350405", "reference": "ptfi-sales-change"}}
HEADERS = {"Origin": "http://127.0.0.1:8137", "x-second-order-scenario": "1", "Content-Type": "application/json"}


def fingerprint(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns,
                                                  hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(folder.rglob("*")) if path.is_file()}


class ThesisUnchanged(unittest.TestCase):
    def test_thesis_v1_and_its_index_are_unchanged(self):
        self.assertEqual(hashlib.sha256((THESIS / "index.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                         INDEX_SHA256)
        v1 = json.loads((THESIS / "v1.json").read_text(encoding="utf-8"))
        self.assertEqual(bis_snapshot.sha256(bis_snapshot.canonical(v1)), V1_CANONICAL)
        # No other thesis version file; the event chains have their own folder below (event-chains/).
        self.assertEqual(sorted(path.name for path in THESIS.iterdir() if path.is_file()), ["index.json", "v1.json"])

    def test_the_catalogue_copies_the_thesis_source_entries_unchanged(self):
        catalog, _ = copper_inputs.load_catalog(COMMITTED)
        v1 = json.loads((THESIS / "v1.json").read_text(encoding="utf-8"))
        entries = {source["id"]: source for source in v1["sources"]}
        for source in catalog["sources"]:
            self.assertEqual(source, entries[source["id"]], source["id"])


@unittest.skipUnless(os.environ.get(OPT_IN), f"set {OPT_IN} to the retained copper folder to check it, read-only")
class RealSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(os.environ[OPT_IN])
        if not cls.folder.is_absolute():
            cls.folder = ROOT / cls.folder
        if not cls.folder.is_dir():
            raise AssertionError(f"{OPT_IN} names no folder")
        cls.before = fingerprint(cls.folder)

    @classmethod
    def tearDownClass(cls):
        after = fingerprint(cls.folder)
        if after != cls.before:
            raise AssertionError("The retained copper folder changed during a read-only check")

    def setUp(self):
        self.catalog, self.digest, self.sources, self.states, self.values = copper_tools_view.loaded(COMMITTED,
                                                                                                     self.folder)

    def test_every_item_verifies(self):
        copper_tools_view.required(self.catalog)
        self.assertEqual({state["state"] for state in self.sources.values()}, {"verified"})
        self.assertEqual({state["state"] for state in self.states.values()}, {"verified"})
        self.assertEqual(len(self.states), 223)

    def test_the_worked_example_reproduces(self):
        base = cc.baseline(self.values, "steps", "2035")
        self.assertEqual(base["coverage"]["residual"]["value"], "12789")
        self.assertEqual(base["coverage"]["share_pct"]["shown"], "38.2")
        self.assertEqual(base["decomposition"]["residual_change"]["value"], "8241")
        self.assertEqual(base["epsilon"]["value"], "-2.0132")
        self.assertEqual(base["decomposition"]["epsilon_change"]["value"], "39.79265")
        result = cc.assess(self.values, "steps", "2035", SET_A)
        self.assertEqual(result["residual"]["value"], "12622.8350405")
        hybrid = cc.assess(self.values, "steps", "2035", {"ev": {"source": "scenario", "scenario": "hd"},
                                                          "networks": {"source": "scenario", "scenario": "hd"}})
        self.assertEqual(hybrid["demand"]["value"], "34694")
        effects = [[case["effect"]["value"] for case in row["cases"]] for row in base["perturbations"]
                   if "effect" in row["cases"][0]]
        self.assertEqual(effects, [["-415", "697"], ["-51", "475"], ["-46"], ["-1163", "772"]])

    def test_the_producer_example_reproduces(self):
        rows = cp.cost_rows(self.values)
        self.assertEqual({row["state"] for row in rows}, {"available"})
        margins = {margin["row"]: margin["shown"] for margin in cp.margins(self.values, rows)}
        self.assertEqual(margins, {"fcx-us": "1.86", "fcx-south-america": "2.36", "fcx-indonesia": "5.08",
                                   "scco": None})
        panel = cp.capital_charge(self.values, "0", "20")
        tia = next(row for row in panel["projects"] if row["project"] == "tia-maria")
        self.assertEqual(tia["charges"][0]["shown"], "0.341")
        panel = cp.capital_charge(self.values, "8", "20")
        bagdad = next(row for row in panel["projects"] if row["project"] == "bagdad")
        self.assertEqual([charge["shown"] for charge in bagdad["charges"]], ["1.782", "1.426"])

    def test_the_routes_on_the_real_sources_save_only_where_told(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            app = create_app(temp / "prepared", None, temp / "drafts", temp / "reviews", temp / "intake",
                             temp / "attempts", inbox=temp / "inbox", triage=temp / "triage", links=temp / "links",
                             market=temp / "market", related_records=temp / "related", enrichment_sources=temp / "es",
                             snapshot_sources=temp / "snap", snapshot_index=temp / "index", theses=temp / "theses",
                             thesis_sources_dir=self.folder, copper_scenarios_dir=temp / "scenarios")
            with TestClient(app, base_url="http://127.0.0.1:8137") as client:
                view = client.get("/api/tools/copper").json()
                self.assertEqual(view["catalog"]["verified"], view["catalog"]["items"])
                body = json.dumps({"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "Real set A"})
                self.assertEqual(client.post("/api/tools/copper/preview", content=body, headers=HEADERS).status_code,
                                 200)
                self.assertFalse((temp / "scenarios").exists())
                saved = client.post("/api/tools/copper/scenarios", content=body, headers=HEADERS)
                self.assertEqual(saved.status_code, 201)
                self.assertEqual(saved.json()["state"], "verified")
            self.assertEqual(len(list((temp / "scenarios").iterdir())), 1)
        self.assertFalse((ROOT / "data" / "scenarios" / "copper").exists() and
                         any((ROOT / "data" / "scenarios" / "copper").iterdir()))


if __name__ == "__main__":
    unittest.main()

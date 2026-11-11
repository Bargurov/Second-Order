"""GET /api/metals (metals_api, metals_view) on SYNTHETIC retained files in temporary folders: both files are verified
against their acquisition records on every read, a part whose file differs is withheld alone and shows frames only,
and reads write nothing. As an explicit opt-in (SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper
folder>) the real files are read, read-only; SECOND_ORDER_FCX_SOURCES=<the retained data/company-sources/fcx folder>
adds the FCX documents a register event cites. Otherwise the FCX documents root is an absent folder, so a reply never
depends on the checkout. The replies the frontend reader is tested against are captured here
(SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 writes them; otherwise they are compared by parsed JSON)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

import metals_fakes
import thesis_fakes
from second_order import metals_iea_uses, metals_research, metals_usgs, metals_view
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
OPT_IN = "SECOND_ORDER_THESIS_SOURCES"
FCX_OPT_IN = "SECOND_ORDER_FCX_SOURCES"
COMMITTED = ROOT / "content" / "metals"
THESIS_V1 = ROOT / "content" / "theses" / "copper" / "v1.json"
USGS, IEA = "usgs-csv-2026", "iea-dataset-2026"
QUARTERLY = "Freeport-McMoRan Inc., Quarterly Report on Form 10-Q for the quarterly period ended September 30, 2026"
BASE = "http://127.0.0.1:8137"


def fingerprint(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns,
                                                  hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(folder.rglob("*")) if path.is_file()}


def app(root: Path, metals: Path, sources: Path, theses: Path | None = None,
        company_sources: Path | None = None) -> TestClient:
    """The app on these folders; the FCX documents root is ``company_sources``, else an absent folder below root."""
    return TestClient(create_app(root / "prepared", None, root / "drafts", root / "reviews", root / "intake",
                                 root / "attempts", inbox=root / "inbox", triage=root / "triage", links=root / "links",
                                 market=root / "market", related_records=root / "related",
                                 enrichment_sources=root / "es", snapshot_sources=root / "snap",
                                 snapshot_index=root / "index", theses=theses or root / "theses",
                                 thesis_sources_dir=sources, metals_dir=metals,
                                 company_sources_dir=company_sources or root / "company-sources"), base_url=BASE)


class Committed(unittest.TestCase):
    def test_committed_sources_equal_the_thesis_entries(self):
        v1 = json.loads(THESIS_V1.read_text(encoding="utf-8"))
        entries = {source["id"]: source for source in v1["sources"]}
        committed = json.loads((COMMITTED / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["sources_version"], "metals-sources-0.1")
        self.assertEqual([source["id"] for source in committed["sources"]], [USGS, IEA])
        for source in committed["sources"]:
            self.assertEqual(source, entries[source["id"]], source["id"])

    def test_the_sources_file_is_lf(self):
        self.assertNotIn(b"\r", (COMMITTED / "sources.json").read_bytes())


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-metals-api-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sources = metals_fakes.write_sources(self.root / "sources")
        self.metals = self.root / "metals"
        self.metals.mkdir()
        shutil.copyfile(COMMITTED / "research.json", self.metals / "research.json")
        (self.metals / "sources.json").write_text(json.dumps(metals_fakes.sources_file(self.sources), indent=1) + "\n",
                                                  encoding="utf-8", newline="\n")

    def assert_withheld(self, body, part, key, keys, whole=False):
        """Every entry of the withheld part is a bare frame, and no value or label only the file holds appears in the
        withheld part or the source states (or in the whole reply when both parts are withheld)."""
        self.assertEqual(body[part]["state"], "withheld")
        self.assertTrue(body[part][key])
        for frame in body[part][key]:
            self.assertEqual(set(frame), keys)
        text = json.dumps(body if whole else {"part": body[part], "sources": body["sources"]}, ensure_ascii=False)
        for printed in LEAKS:
            self.assertNotIn(printed, text if printed not in RESEARCH_LABELS else json.dumps(
                {key: value for key, value in body.items() if key != "research"} if whole else
                {"part": body[part], "sources": body["sources"]}, ensure_ascii=False))
        # the research part is scanned too: every figure, and every label the notes do not themselves contain
        research = json.dumps(body["research"], ensure_ascii=False)
        for printed in LEAKS if whole else LEAKS_BY_PART[part]:
            if printed not in RESEARCH_LABELS:
                self.assertNotIn(printed, research)

    def rewrite_sources(self):
        (self.metals / "sources.json").write_text(json.dumps(metals_fakes.sources_file(self.sources), indent=1) + "\n",
                                                  encoding="utf-8", newline="\n")

    def get(self, sources: Path | None = None, theses: Path | None = None) -> dict:
        with app(self.root, self.metals, sources or self.sources, theses) as client:
            reply = client.get("/api/metals")
            self.assertEqual(reply.status_code, 200, reply.text)
            return reply.json()


USGS_FRAME, IEA_FRAME = {"id", "chapter", "name"}, {"id", "name", "chapter"}
LEAKS_USGS = ("230,000", "310,000", "980,000", "74.2", "Congo (Kinshasa)", "Synthetic note", "Mine production")
LEAKS_IEA = ("84.5", "48.3", "20.3", "65.6", "210", "Democratic Republic of Congo", "Total energy technologies",
             "Electric vehicles")
LEAKS = (*LEAKS_USGS, *LEAKS_IEA, "Alpha")  # "Alpha" is a label in both files
LEAKS_BY_PART = {"usgs": LEAKS_USGS, "risk": LEAKS_USGS, "iea": LEAKS_IEA, "uses": LEAKS_IEA}
RESEARCH_TEXT = (COMMITTED / "research.json").read_text(encoding="utf-8")
# A file-only label that the assistant-written research notes themselves contain (computed from the notes, so a figure
# can never be exempt): "Electric vehicles" and "Electricity networks" are link text and refs there, not file content.
RESEARCH_LABELS = tuple(item for item in LEAKS if item in RESEARCH_TEXT and not any(c.isdigit() for c in item))


class Reads(Folders):
    def test_verified_read(self):
        body = self.get()
        self.assertEqual(body["view_version"], "metals-view-0.5")
        self.assertEqual(body["usgs"]["engine"], "metals-usgs-0.3")
        self.assertIs(body["provider_called"], False)
        self.assertEqual(body["deep"], metals_view.DEFAULT_PICKS)
        self.assertEqual((body["usgs"]["state"], body["iea"]["state"]), ("available", "available"))
        self.assertEqual(len(body["usgs"]["chapters"]), 45)
        self.assertEqual(len(body["iea"]["minerals"]), 6)
        self.assertEqual([source["state"] for source in body["sources"]], ["verified", "verified"])
        self.assertEqual(set(body["sources"][0]), {*metals_view.copper_tools_view.SOURCE_SHOWN, "state", "detail"})

    def test_missing_folder_withholds_both(self):
        empty = self.root / "empty"
        empty.mkdir()
        body = self.get(empty)
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME, whole=True)
        self.assert_withheld(body, "iea", "minerals", IEA_FRAME, whole=True)
        self.assertEqual([source["state"] for source in body["sources"]], ["missing", "missing"])

    def test_one_changed_byte_withholds_only_that_part(self):
        metals_fakes.change_byte(self.sources, USGS)
        body = self.get()
        self.assertEqual((body["usgs"]["state"], body["iea"]["state"]), ("withheld", "available"))
        self.assertEqual(body["usgs"]["problem"], body["sources"][0]["detail"])
        self.assertEqual(body["sources"][0]["state"], "changed")
        self.assertIn("record", body["usgs"]["problem"])
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME)
        self.assertEqual(len(body["iea"]["minerals"]), 6)

    def test_one_changed_workbook_byte_withholds_only_the_workbook(self):
        metals_fakes.change_byte(self.sources, IEA)
        body = self.get()
        self.assertEqual((body["usgs"]["state"], body["iea"]["state"]), ("available", "withheld"))
        self.assertEqual(body["iea"]["problem"], body["sources"][1]["detail"])
        self.assert_withheld(body, "iea", "minerals", IEA_FRAME)
        self.assertEqual(len(body["usgs"]["chapters"]), 45)

    def test_a_differing_layout_withholds_with_its_place(self):
        rows = metals_fakes.usgs_rows()
        rows[0] = [*rows[0][:-1], "Renamed"]
        metals_fakes.retain(self.sources, USGS, metals_fakes.usgs_bytes(rows))
        self.metals_rewrite()
        body = self.get()
        self.assertEqual(body["usgs"]["state"], "withheld")
        self.assertEqual(body["iea"]["state"], "available")
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME)
        self.assertEqual(body["usgs"]["problem"], metals_view.USGS_LAYOUT_PROBLEM)

    def test_a_usgs_refusal_that_would_echo_file_labels_is_fixed_text(self):
        rows = metals_fakes.usgs_rows()
        # a second cobalt series whose detail differs only in punctuation: the same id, so the reader refuses with a
        # message built from file labels
        header = rows[0]
        detail = header.index("Statistics_detail")
        copy = next(list(row) for row in rows[1:] if row[0] == "COBALT" and row[detail] == "Mine production")
        copy[detail] = "Mine-production"
        rows.append(copy)
        metals_fakes.retain(self.sources, USGS, metals_fakes.usgs_bytes(rows))
        self.metals_rewrite()
        body = self.get()
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME)
        self.assertEqual(body["usgs"]["problem"], metals_view.USGS_LAYOUT_PROBLEM)

    def metals_rewrite(self):
        (self.metals / "sources.json").write_text(json.dumps(metals_fakes.sources_file(self.sources), indent=1) + "\n",
                                                  encoding="utf-8", newline="\n")

    def test_a_missing_sources_file_is_503_and_a_wrong_one_500(self):
        (self.metals / "sources.json").unlink()
        with app(self.root, self.metals, self.sources) as client:
            self.assertEqual(client.get("/api/metals").status_code, 503)
        data = metals_fakes.sources_file(self.sources)
        data["sources"].reverse()
        (self.metals / "sources.json").write_text(json.dumps(data), encoding="utf-8")
        with app(self.root, self.metals, self.sources) as client:
            self.assertEqual(client.get("/api/metals").status_code, 500)

    def test_reads_write_nothing(self):
        before = fingerprint(self.root)
        with app(self.root, self.metals, self.sources) as client:
            for _ in range(3):
                self.assertEqual(client.get("/api/metals").status_code, 200)
        self.assertEqual(fingerprint(self.root), before)

    def test_no_post(self):
        with app(self.root, self.metals, self.sources) as client:
            self.assertEqual(client.post("/api/metals", json={}).status_code, 405)


USES_FRAME, RISK_FRAME = {"name", "chapter"}, {"id", "chapter", "name"}


class Parts(Folders):
    """The risk, uses and research parts (metals-view-0.3; 0.4: each event carries its date)."""

    def test_verified_read_has_the_three_new_parts(self):
        body = self.get()
        self.assertEqual((body["risk"]["state"], body["uses"]["state"], body["research"]["state"]),
                         ("available", "available", "available"))
        self.assertEqual(body["risk"]["engine"], "metals-risk-0.1")
        self.assertEqual(len(body["risk"]["chapters"]), 45)
        self.assertEqual([item["name"] for item in body["uses"]["entries"]][:3], ["Cadmium", "Copper", "Iridium"])
        self.assertEqual(body["research"]["written_by"], metals_research.WRITTEN_BY)
        self.assertIn("copper", body["research"]["metals"])

    def test_an_unreadable_thesis_withholds_stated_links_only(self):
        body = self.get()  # no theses folder in the synthetic root
        links = [link for entry in body["research"]["metals"].values() for chain in entry["chains"]
                 for link in chain["links"]]
        stated = [link for link in links if link["kind"] == "stated"]
        self.assertTrue(stated)
        for link in stated:
            self.assertEqual(link["evidence"]["state"], "unavailable")
            for key in ("quote", "source", "title", "publisher", "edition", "edition_date", "where"):
                self.assertIsNone(link["evidence"][key], key)
            self.assertEqual(link["unavailable"], metals_view.THESIS_UNAVAILABLE)
        measured = [link for link in links if link["kind"] == "measured"]
        self.assertTrue(any(link["shown"] is not None for link in measured))

    def test_committed_thesis_on_synthetic_sources_is_not_verified(self):
        body = self.get(theses=ROOT / "content" / "theses")
        self.assertEqual(body["research"]["state"], "available")
        cited = [item["evidence"] for entry in body["research"]["metals"].values() for item in entry["uses"]]
        self.assertTrue(cited and "verified" not in {evidence["state"] for evidence in cited})
        # A passage that is not verified still names its source entry; only its quote is withheld.
        end_uses = next(evidence for evidence in cited if evidence["id"] == "usgs26-end-uses")
        self.assertEqual((end_uses["title"], end_uses["publisher"], end_uses["edition"], end_uses["edition_date"]),
                         ("Mineral Commodity Summaries 2026: Copper", "U.S. Geological Survey", "2026", "2026-02-01"))
        self.assertIsNone(end_uses["quote"])

    def assert_links_follow(self, body, usgs_withheld, iea_withheld):
        """A measured link whose source is withheld shows nothing and names that part's problem; one whose source is
        available shows a figure or its own reason; a stated link is the same whatever source is withheld."""
        seen = {"usgs": 0, "iea": 0}
        for entry in body["research"]["metals"].values():
            for chain in entry["chains"]:
                for link in chain["links"]:
                    if link["kind"] == "stated":
                        self.assertEqual(link["evidence"]["problem"], metals_view.THESIS_UNAVAILABLE)
                        self.assertEqual(link["unavailable"], metals_view.THESIS_UNAVAILABLE)
                        continue
                    if link["kind"] != "measured":
                        continue
                    part = "iea" if "iea" in link["ref"] else "usgs"
                    seen[part] += 1
                    if (usgs_withheld, iea_withheld)[part == "iea"]:
                        self.assertIsNone(link["shown"], link["ref"])
                        self.assertIn(body["uses" if part == "iea" else "usgs"]["problem"], link["unavailable"])
        self.assertTrue(seen["usgs"] and seen["iea"], seen)

    def test_both_withheld_leaves_no_measured_link_shown(self):
        body = self.get(self.root / "empty")
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME, whole=True)
        self.assert_withheld(body, "uses", "entries", USES_FRAME, whole=True)
        self.assert_links_follow(body, usgs_withheld=True, iea_withheld=True)

    def test_a_changed_usgs_file_withholds_risk_and_unavails_its_links(self):
        metals_fakes.change_byte(self.sources, USGS)
        body = self.get()
        self.assertEqual((body["risk"]["state"], body["uses"]["state"]), ("withheld", "available"))
        self.assertEqual(body["risk"]["problem"], body["usgs"]["problem"])
        self.assertTrue(all(set(frame) == RISK_FRAME for frame in body["risk"]["chapters"]))
        self.assertEqual(len(body["risk"]["chapters"]), 45)
        self.assertEqual(body["research"]["state"], "available")
        measured = [link for entry in body["research"]["metals"].values() for chain in entry["chains"]
                    for link in chain["links"] if link["kind"] == "measured" and "iea" not in link["ref"]]
        self.assertTrue(measured)
        self.assert_links_follow(body, usgs_withheld=True, iea_withheld=False)
        self.assert_withheld(body, "usgs", "chapters", USGS_FRAME)

    def test_a_changed_workbook_withholds_uses_with_its_problem(self):
        metals_fakes.change_byte(self.sources, IEA)
        body = self.get()
        self.assertEqual((body["uses"]["state"], body["risk"]["state"]), ("withheld", "available"))
        self.assertEqual(body["uses"]["problem"], body["sources"][1]["detail"])
        self.assertTrue(all(set(frame) == USES_FRAME for frame in body["uses"]["entries"]))
        self.assertEqual([f["name"] for f in body["uses"]["entries"]], list(metals_iea_uses.MAPPING))
        self.assertNotIn("Electricity networks", json.dumps(body["uses"]))
        # the research notes themselves say "Electricity networks" (link text and ref), so only the part is scanned
        self.assertIn("Electricity networks", RESEARCH_TEXT)
        self.assert_withheld(body, "uses", "entries", USES_FRAME)
        self.assert_links_follow(body, usgs_withheld=False, iea_withheld=True)

    def test_a_uses_layout_refusal_withholds_uses_alone(self):
        sheets = {**metals_fakes.iea_sheets(), **metals_fakes.iea_uses_sheets()}
        sheets[metals_iea_uses.BY_MINERAL] = {**sheets[metals_iea_uses.BY_MINERAL], "A3": "Renamed"}
        metals_fakes.retain(self.sources, IEA, thesis_fakes.workbook(sheets))
        self.rewrite_sources()
        body = self.get()
        self.assertEqual((body["iea"]["state"], body["uses"]["state"]), ("available", "withheld"))
        self.assertEqual(body["uses"]["problem"], metals_view.USES_LAYOUT_PROBLEM)
        self.assertNotIn("Renamed", json.dumps(body))

    def test_a_research_schema_refusal_withholds_the_whole_part(self):
        data = json.loads((self.metals / "research.json").read_text(encoding="utf-8"))
        data["surprise"] = 1
        (self.metals / "research.json").write_text(json.dumps(data), encoding="utf-8")
        body = self.get()
        self.assertEqual(body["research"], {"engine": metals_research.ENGINE, "state": "withheld",
                                            "problem": metals_research.RESEARCH_PROBLEM,
                                            "written_by": metals_research.WRITTEN_BY, "metals": {}})
        self.assertEqual(body["risk"]["state"], "available")


class Fixtures(Folders):
    def test_frontend_fixtures(self):
        """The replies the frontend reader is tested against: captured from this producer, never hand-written."""
        served = {"metals-view.json": self.get()}
        metals_fakes.change_byte(self.sources, USGS)
        served["metals-usgs-changed.json"] = self.get()
        metals_fakes.write_sources(self.sources)  # restore both files, then change the workbook
        metals_fakes.change_byte(self.sources, IEA)
        served["metals-iea-changed.json"] = self.get()
        metals_fakes.write_sources(self.sources)
        empty = self.root / "empty"
        empty.mkdir()
        served["metals-unavailable.json"] = self.get(empty)
        for name, reply in served.items():
            text = json.dumps(reply, ensure_ascii=False)
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn("second-order-metals-api", text, name)
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            else:
                self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_metals_api.py")


@unittest.skipUnless(os.environ.get(OPT_IN), f"set {OPT_IN} to the retained copper folder to check it, read-only")
class RealSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(os.environ[OPT_IN])
        if not cls.folder.is_absolute():
            cls.folder = ROOT / cls.folder
        if not cls.folder.is_dir():
            raise AssertionError(f"{OPT_IN} names no folder")
        cls.fcx = Path(os.environ[FCX_OPT_IN]) if os.environ.get(FCX_OPT_IN) else None
        if cls.fcx is not None and not (cls.fcx.is_absolute() and cls.fcx.is_dir()):
            raise AssertionError(f"{FCX_OPT_IN} names no folder")
        cls.before = fingerprint(cls.folder)
        cls.fcx_before = fingerprint(cls.fcx) if cls.fcx else None
        cls.root = Path(tempfile.mkdtemp(prefix="second-order-metals-real-"))
        with app(cls.root, COMMITTED, cls.folder, ROOT / "content" / "theses", cls.fcx) as client:
            reply = client.get("/api/metals")
        assert reply.status_code == 200, reply.text
        cls.body = reply.json()
        cls.chapters = {chapter["id"]: chapter for chapter in cls.body["usgs"]["chapters"]}
        cls.minerals = {mineral["id"]: mineral for mineral in cls.body["iea"]["minerals"]}
        cls.risk = {entry["id"]: entry for entry in cls.body["risk"]["chapters"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, True)
        if fingerprint(cls.folder) != cls.before:
            raise AssertionError("The retained copper folder changed during a read-only check")
        if cls.fcx and fingerprint(cls.fcx) != cls.fcx_before:
            raise AssertionError("The retained FCX folder changed during a read-only check")

    def series(self, chapter, statistic, word):
        found = [item for item in self.chapters[chapter]["series"]
                 if item["statistic"] == statistic and item["year"] == "2025" and word in item["detail"].lower()]
        self.assertEqual(len(found), 1, (chapter, statistic, word, [i["detail"] for i in found]))
        return found[0]

    def share(self, series, country):
        return next(cell for cell in series["countries"] if cell["country"] == country)["share"]["shown"]

    def test_both_parts_are_available_and_complete(self):
        self.assertEqual((self.body["usgs"]["state"], self.body["iea"]["state"]), ("available", "available"))
        self.assertEqual([source["state"] for source in self.body["sources"]], ["verified", "verified"])
        self.assertEqual(len(self.chapters), 45)
        self.assertTrue(all(chapter["present"] for chapter in self.chapters.values()))

    def test_world_table_is_absent_for_three_chapters(self):
        self.assertEqual(sorted(key for key, chapter in self.chapters.items() if not chapter["world_table"]),
                         ["germanium", "rare-earths-heavy", "thallium"])

    def test_published_shares(self):
        self.assertEqual(self.share(self.series("cobalt", "Production", "mine production"), "Congo (Kinshasa)"), "74.2")
        self.assertEqual(self.share(self.series("rare-earths", "Production", "mine"), "China"), "69.2")
        self.assertEqual(self.share(self.series("nickel", "Production", "mine"), "Indonesia"), "66.7")
        self.assertEqual(self.share(self.series("aluminum", "Production", "smelter"), "China"), "60.8")
        self.assertEqual(self.share(self.series("lithium", "Reserves", "reserves"), "Chile"), "24.9")

    def test_lithium_mine_top3_reason(self):
        top3 = self.series("lithium", "Production", "mine production")["top3"]
        self.assertIn("United States", top3["reason"])
        self.assertIn("“W”", top3["reason"])

    def test_copper_mine_leader_and_top3_read_a_dash_as_zero(self):
        mine = self.series("copper", "Production", "mine production")
        germany = next(cell for cell in mine["countries"] if cell["country"] == "Germany")
        self.assertEqual((germany["value"], germany["share"]), ("—", {"shown": None, "reason": "Printed as “—”"}))
        self.assertEqual(mine["leader"], {"countries": ["Chile"], "shown": "23.0", "reason": None})
        self.assertEqual(mine["top3"], {"countries": ["Chile", "Congo (Kinshasa)", "Peru"], "shown": "48.7",
                                        "reason": None})
        self.assertIs(mine["world"]["rounded"], True)

    def test_years_of_reserves(self):
        def shown(chapter):
            return [entry["shown"] for entry in self.chapters[chapter]["years_of_reserves"]]
        self.assertEqual(shown("copper"), ["43"])
        self.assertEqual(shown("lithium"), ["128"])

    def test_vanadium_reserves_carry_their_known_unit_issue(self):
        """The real file labels vanadium's 2025 reserves metric tons (world 21,000, Australia 10,000); the printed
        chapter heads the column thousand metric tons. The series is flagged, its years withheld, its shares kept."""
        sid = "vanadium/reserves/reserves/metric-tons/2025"
        issue = metals_usgs.UNIT_ISSUES[sid]
        reserves = next(item for item in self.chapters["vanadium"]["series"] if item["id"] == sid)
        self.assertEqual((reserves["unit"], reserves["world"]["value"], reserves["unit_issue"]),
                         ("metric tons", "21,000", issue))
        self.assertEqual(self.share(reserves, "Australia"), "47.6")
        (entry,) = self.chapters["vanadium"]["years_of_reserves"]
        self.assertEqual((entry["reserves"], entry["shown"], entry["reason"]), (sid, None, "Reserves: " + issue))

    def test_every_unit_issue_names_a_real_series_and_only_those_are_flagged(self):
        flagged = {item["id"] for chapter in self.chapters.values() for item in chapter["series"] if item["unit_issue"]}
        self.assertEqual(flagged, set(metals_usgs.UNIT_ISSUES))

    def test_no_real_years_figure_is_under_one(self):
        shown = [entry["shown"] for chapter in self.chapters.values() for entry in chapter["years_of_reserves"]]
        self.assertNotIn(metals_usgs.YEARS_UNDER_ONE, shown)

    def test_the_three_new_parts_are_available(self):
        self.assertEqual([self.body[key]["state"] for key in ("risk", "uses", "research")], ["available"] * 3)

    def test_copper_mine_hhi_bounds_and_coverage(self):
        mine = self.risk["copper"]["series"]["copper/production/mine-production/thousand-metric-tons/2025"]
        self.assertEqual((mine["hhi_low"], mine["hhi_high"], mine["named_share"], mine["named"]),
                         ("1037", "1206", "87.0", 14))

    def test_copper_leaders_differ(self):
        copper = self.risk["copper"]
        self.assertIs(copper["leaders_differ"], True)
        self.assertEqual([(stage["stage"], stage["leader"]["countries"]) for stage in copper["stages"]],
                         [("mining", ["Chile"]), ("refining", ["China"])])

    def test_cobalt_mine_hhi(self):
        mine = self.risk["cobalt"]["series"]["cobalt/production/mine-production/metric-tons/2025"]
        self.assertEqual((mine["hhi_low"], mine["hhi_high"]), ("5720", "5722"))

    def test_copper_net_import_reliance(self):
        self.assertEqual(self.risk["copper"]["us"]["reliance"]["value"], "57")

    def test_reliance_names_its_commodity_where_a_chapter_prints_two(self):
        # Same detail, two commodities: the headline is the first 2025 row, named by its Commodity as printed.
        detail = "Net import reliance as a percentage of apparent consumption"
        self.assertEqual(self.risk["bauxite-and-alumina"]["us"]["reliance"],
                         {"commodity": "Bauxite", "detail": detail, "value": ">75"})
        self.assertEqual(self.risk["titanium-and-titanium-dioxide"]["us"]["reliance"],
                         {"commodity": "Titanium sponge metal", "detail": detail, "value": "100"})
        self.assertEqual([(row["commodity"], row["value"]) for row in self.chapters["bauxite-and-alumina"]["reliance"]
                          if row["year"] == "2025"], [("Bauxite", ">75"), ("Alumina", "71")])

    def test_mercury_exports_are_not_the_mining_stage(self):
        stages = {stage["detail"]: stage["stage"] for stage in self.risk["mercury"]["stages"]}
        exports = [detail for detail in stages if "export" in detail.lower()]
        self.assertTrue(exports, stages)
        self.assertTrue(all(stages[detail] == "other" for detail in exports), stages)

    def test_copper_iea_electricity_networks_share(self):
        copper = next(entry for entry in self.body["uses"]["entries"] if entry["name"] == "Copper")
        networks = next(item for item in copper["technologies"] if item["label"] == "Electricity networks")
        self.assertEqual(networks["share_2025"], "56.8")

    def test_every_copper_passage_is_verified(self):
        cited = set()
        for entry in self.body["research"]["metals"].values():
            listed = [item for name in ("uses", "substitution", "recycling", "events") for item in entry[name]
                      if item["passage"].startswith("copper:")]  # An FCX event is checked against the FCX folder.
            cited.update(item["passage"] for item in listed)
            for chain in entry["chains"]:
                cited.update(link["passage"] for link in chain["links"] if link["kind"] == "stated")
                for link in chain["links"]:
                    if link["kind"] == "stated":
                        self.assertEqual(link["evidence"]["state"], "verified", link["passage"])
                        self.assertIsNone(link["unavailable"])
            for item in listed:
                self.assertEqual(item["evidence"]["state"], "verified", item["passage"])
        self.assertEqual(len(cited), 8)

    def test_the_fcx_event_is_verified_only_with_the_retained_fcx_folder(self):
        (event,) = [event for event in self.body["research"]["metals"]["copper"]["events"]
                    if event["passage"].startswith("fcx:")]
        if self.fcx is None:
            self.assertEqual((event["evidence"]["state"], event["evidence"]["quote"]), ("missing", None))
        else:
            self.assertEqual(event["evidence"]["state"], "verified")
            self.assertIn(event["when"], event["evidence"]["quote"])

    def test_events_name_their_source(self):
        # One official publication and two filings, each named by its source entry, not its id.
        named = {event["evidence"]["id"]: tuple(event["evidence"][key] for key in ("title", "publisher", "edition"))
                 for event in self.body["research"]["metals"]["copper"]["events"]}
        self.assertEqual(named, {
            "usgs26-mine-events": ("Mineral Commodity Summaries 2026: Copper", "U.S. Geological Survey", "2026"),
            "fcx-mud-rush-2025": ("Annual report on Form 10-K for fiscal 2025", "Freeport-McMoRan Inc.", "Fiscal 2025"),
            "q3-p-bagdad-approval": (QUARTERLY, "Freeport-McMoRan Inc.", "10-Q")})

    def test_each_event_is_dated_as_its_verified_quote_dates_it(self):
        events = self.body["research"]["metals"]["copper"]["events"]
        self.assertEqual([(event["evidence"]["id"], event["when"]) for event in events],
                         [("usgs26-mine-events", "2025"), ("fcx-mud-rush-2025", "September 2025"),
                          ("q3-p-bagdad-approval", "November 2026")])
        for event in events:
            if event["evidence"]["state"] == "verified":  # The FCX event's quote is shown only with its folder.
                self.assertIn(event["when"], event["evidence"]["quote"])

    def test_iea_cobalt_mining(self):
        mining = self.minerals["cobalt"]["supply"][0]
        congo = mining["countries"][0]
        self.assertEqual((congo["country"], congo["shares"]["2025"]), ("Democratic Republic of Congo", "65.6"))


if __name__ == "__main__":
    unittest.main()

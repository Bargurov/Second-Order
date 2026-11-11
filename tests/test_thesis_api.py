"""The thesis routes (thesis_api): reads only, no outside request, no POST, and the replies the frontend validator is
tested against, captured from the SYNTHETIC sources and versions (tests/thesis_fakes.py) in temporary folders.
Fixtures are written with SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 and compared by parsed JSON otherwise.

The committed copper thesis (content/theses/copper) is checked as content only in the default run; one opt-in class
(SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper folder>) checks it against the real retained
sources, read-only.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import thesis_fakes
from second_order import event_inbox, headline_triage, thesis_schema, thesis_sources, thesis_view, thesis_workbook
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
BASE = "http://127.0.0.1:8137"
ID = thesis_fakes.THESIS_ID
PUBLISHED = ["2026-11-02", "2026-11-16"]


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-thesis-api-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sources = thesis_fakes.write_sources(self.root / "sources")
        self.content = self.root / "content"
        v1 = thesis_fakes.thesis_v1(self.sources)
        thesis_fakes.write_theses(self.content, [v1, thesis_fakes.thesis_v2(v1, self.sources)], PUBLISHED)

    def app(self, sources: Path | None = None, content: Path | None = None) -> TestClient:
        return TestClient(create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                     self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                     triage=self.root / "triage", links=self.root / "links",
                                     market=self.root / "market", related_records=self.root / "related",
                                     enrichment_sources=self.root / "es", snapshot_sources=self.root / "snap",
                                     snapshot_index=self.root / "index", theses=content or self.content,
                                     thesis_sources_dir=sources or self.sources), base_url=BASE)


class ApiTests(Folders):
    def test_reading_writes_nothing_and_makes_no_outside_request_or_model_call(self):
        calls = []
        connect = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                calls.append(("connect", address))
                raise AssertionError("an outside connection was attempted")
            return connect(sock, address)

        def counted(name):
            def call(*args, **kwargs):
                calls.append((name, None))
                raise AssertionError(f"{name} was called")
            return call
        watched = [self.root / "sources", self.root / "content", ROOT / "content", FIXTURES]
        before = [tree(folder) for folder in watched]
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo", counted("name lookup")), \
                patch.object(event_inbox.FeedFetcher, "fetch", counted("feed fetch")), \
                patch.object(headline_triage, "build_request", counted("model request")), \
                patch("second_order.triage_flow.dispatch", counted("triage dispatch")):
            with self.app() as client:
                first = client.get(f"/api/theses/{ID}")
                again = client.get(f"/api/theses/{ID}")
                old = client.get(f"/api/theses/{ID}/versions/1")
                listed = client.get("/api/theses")
        self.assertEqual(calls, [])
        self.assertEqual([r.status_code for r in (first, again, old, listed)], [200, 200, 200, 200])
        self.assertEqual(first.json(), again.json())
        self.assertEqual((first.json()["version"], old.json()["version"]), (2, 1))
        self.assertIs(first.json()["provider_called"], False)
        self.assertIs(listed.json()["provider_called"], False)
        self.assertEqual([tree(folder) for folder in watched], before)
        self.assertFalse((self.root / "inbox").exists())

    def test_the_catalog_lists_the_latest_versions_from_content_alone(self):
        shutil.rmtree(self.sources)  # No retained source is needed to list the theses.
        with self.app() as client:
            catalog = client.get("/api/theses").json()
        self.assertEqual(catalog["view_version"], thesis_schema.CATALOG_VERSION)
        self.assertEqual([(item["id"], item["latest_version"], item["href"]) for item in catalog["theses"]],
                         [(ID, 2, f"/theses/{ID}")])

    def test_unknown_or_malformed_routes_are_not_found(self):
        with self.app() as client:
            for path in ("/api/theses/x", "/api/theses/Bad_Id", "/api/theses/x/versions/1",
                         f"/api/theses/{ID}/versions/0", f"/api/theses/{ID}/versions/01",
                         f"/api/theses/{ID}/versions/a", f"/api/theses/{ID}/versions/-1",
                         f"/api/theses/{ID}/versions/10000", f"/api/theses/{ID}/versions/3",
                         f"/api/theses/{ID}/versions/1.0", f"/api/theses/{ID}/versions/1٣", f"/api/theses/{ID}/versions/%20"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.get(f"/api/theses/{ID}/versions/0").json()["detail"],
                             "This thesis has no such version")

    def test_there_is_no_post(self):
        with self.app() as client:
            for path in ("/api/theses", f"/api/theses/{ID}", f"/api/theses/{ID}/versions/1"):
                for method in ("post", "put", "delete", "patch"):
                    with self.subTest(path=path, method=method):
                        self.assertEqual(getattr(client, method)(path).status_code, 405)
        routes = [route for route in self.app().app.routes if getattr(route, "path", "").startswith("/api/theses")
                  and "/event-chains" not in route.path  # The owner's event-chain records have their own routes,
                  and "/copper/research" not in route.path]  # and so have the copper research view and the notes.
        self.assertEqual([(route.path, route.methods) for route in routes],
                         [("/api/theses", {"GET"}), ("/api/theses/{thesis_id}", {"GET"}),
                          ("/api/theses/{thesis_id}/versions/{version}", {"GET"})])

    def test_an_unreadable_record_is_a_500_naming_only_its_type(self):
        with self.app() as client, patch("second_order.thesis_view.view", side_effect=PermissionError("secret path")):
            reply = client.get(f"/api/theses/{ID}")
        self.assertEqual((reply.status_code, reply.json()["detail"]),
                         (500, "The local records could not be read (PermissionError)"))

    def test_served_replies_match_the_committed_frontend_fixtures(self):
        def get(client, path):
            reply = client.get(path)
            self.assertEqual(reply.status_code, 200, path)
            return reply.json()
        served = {}
        with self.app() as client:  # Every source present: version 2 (published) and version 1.
            served["thesis-available.json"] = get(client, f"/api/theses/{ID}")
            served["thesis-version-1.json"] = get(client, f"/api/theses/{ID}/versions/1")
            served["thesis-catalog.json"] = get(client, "/api/theses")
        drafts = self.root / "draft-content"  # Version 1 published and version 2 a draft (published_on null).
        v1 = thesis_fakes.thesis_v1(self.sources)
        thesis_fakes.write_theses(drafts, [v1, thesis_fakes.thesis_v2(v1, self.sources)], [PUBLISHED[0], None])
        with self.app(content=drafts) as client:
            served["thesis-draft.json"] = get(client, f"/api/theses/{ID}")
        # Two kinds of revalidation: the maker's paragraph 5 is edited and re-recorded (its bytes match the record, the
        # cited figure is no longer found there), and the IEA workbook's bytes change after they were recorded.
        changed, edited = self.root / "changed", self.root / "changed-content"
        shutil.copytree(self.sources, changed)
        thesis_fakes.retain(changed, "sec-maker-2025", thesis_fakes.maker_html().replace(b"210,000", b"220,000"))
        v1 = thesis_fakes.thesis_v1(changed)
        thesis_fakes.write_theses(edited, [v1, thesis_fakes.thesis_v2(v1, changed)], PUBLISHED)
        dataset = changed / "iea-2026" / "dataset.xlsx"
        dataset.write_bytes(dataset.read_bytes() + b"\0")
        with self.app(changed, edited) as client:
            served["thesis-revalidation.json"] = get(client, f"/api/theses/{ID}")
        empty = self.root / "empty"  # A machine with no retained source at all.
        empty.mkdir()
        with self.app(empty) as client:
            served["thesis-unavailable.json"] = get(client, f"/api/theses/{ID}")
        counts = {name: body["counts"] for name, body in served.items() if "counts" in body}
        self.assertEqual(counts["thesis-available.json"]["elements"], {"available": 18, "needs_revalidation": 0,
                                                                       "unavailable": 0})
        self.assertEqual(counts["thesis-revalidation.json"]["elements"],
                         {"available": 8, "needs_revalidation": 10, "unavailable": 0})
        self.assertEqual(counts["thesis-revalidation.json"]["sources"], {"verified": 8, "changed": 1, "missing": 0})
        draft = served["thesis-draft.json"]
        self.assertEqual((draft["version"], draft["draft"], draft["published_on"], draft["counts"]["elements"]),
                         (2, True, None, {"available": 18, "needs_revalidation": 0, "unavailable": 0}))
        self.assertEqual([item["published_on"] for item in draft["versions"]], [PUBLISHED[0], None])
        revalidation = served["thesis-revalidation.json"]
        every = [revalidation["view"], *revalidation["balance"]["tables"], *revalidation["differs"],
                 *revalidation["reasons"], *revalidation["risks"], *revalidation["conditions"],
                 *revalidation["exposure"]["movers"], *revalidation["exposure"]["moved"], revalidation["price_record"]]
        states = {item["id"]: item["state"] for item in revalidation["sources"]}
        # Both kinds are present: an element not found where cited whose sources all verify, and one on a changed source.
        self.assertTrue([e for e in every if e["not_found"] and {states[s] for s in e["sources"]} == {"verified"}])
        self.assertTrue([e for e in every if "changed" in {states[s] for s in e["sources"]}])
        self.assertEqual(counts["thesis-unavailable.json"]["elements"],
                         {"available": 0, "needs_revalidation": 0, "unavailable": 18})
        for name, body in served.items():
            text = json.dumps(body, ensure_ascii=False)
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn("second-order-thesis-api", text, name)
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            else:
                self.assertEqual(body, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_thesis_api.py")


# ---------------------------------------------------------------- the committed copper thesis (Task 11)

COPPER = "copper"
REAL_SOURCES = "SECOND_ORDER_THESIS_SOURCES"  # Explicit opt-in: the retained data/sector-sources/copper folder.


# R16: the edition dates the publishers state, and where (stated here, independently of v1.json).
EDITION_DATES = {
    "iea-dataset-2026": "2026-01-01",       # year only: "2026" in the publisher's file name; no month or day stated
    "usgs-csv-2026": "2026-02-06",          # data release publication date (copper-usgs-csv-01 plan, editions[0])
    "usgs-2026": "2026-02-01",              # chapter footer: "Mineral Commodity Summaries, February 2026"
    "usgs-2025": "2025-01-01",              # chapter footer: "Mineral Commodity Summaries, January 2025"
    "worldbank-cmo-2026-10": "2026-10-01",  # page header: "Commodity Markets Outlook | October 2026"
    "sec-fcx-2025": "2026-02-13", "sec-fcx-2024": "2025-02-14",    # signature blocks
    "sec-scco-2025": "2026-02-27", "sec-scco-2024": "2025-03-03",
    "sec-mli-2025": "2026-02-25", "sec-mli-2024": "2025-02-26",
    "sec-tsla-2025": "2026-01-28", "sec-tsla-2024": "2025-01-29",
}


def every_element(body: dict) -> list[dict]:
    return [body["view"], *body["balance"]["tables"], *body["differs"], *body["reasons"], *body["risks"],
            *body["conditions"], *body["exposure"]["movers"], *body["exposure"]["moved"], body["price_record"]]


class CommittedContentTests(unittest.TestCase):
    """The committed content/theses/copper files, read as content only (default run: no retained source is read)."""

    def test_the_committed_thesis_is_valid_and_matches_its_index(self):
        index = thesis_schema.load_index(COPPER)
        self.assertEqual([(entry["version"], entry["file"], entry["published_on"]) for entry in index["versions"]],
                         [(1, "v1.json", "2026-11-03")])  # Published at Checkpoint 2 (the owner approved).
        thesis = thesis_schema.load_version(COPPER, 1)  # Checks the file, its canonical SHA-256 and every section.
        self.assertEqual((thesis["id"], thesis["version"], thesis["opened_on"], thesis["prepared_on"]),
                         (COPPER, 1, "2026-11-03", "2026-11-03"))
        listed = [item for item in thesis_schema.catalog()["theses"] if item["id"] == COPPER]
        self.assertEqual([(item["latest_version"], item["published_on"]) for item in listed], [(1, "2026-11-03")])
        # The content minimums of the plan's Task 11, as far as the retained sources allow (see the task report).
        # No table computes a gap: no retained publication gives both sides on one world basis, and the United States
        # refined table is context, met by trade and stocks (controller ruling, fix round 2). That minimum reads short.
        tables = thesis["balance"]["tables"]
        self.assertEqual([(table["id"], table["gap"]) for table in tables],
                         [("balance-iea", "not_computed"), ("us-refined-context", "not_computed")])
        self.assertGreaterEqual(len(thesis["differs"]), 1)
        self.assertTrue(3 <= len(thesis["reasons"]) <= 5)
        self.assertGreaterEqual(len(thesis["risks"]), 3)
        self.assertTrue(any(risk["measure"] is None for risk in thesis["risks"]))
        self.assertGreaterEqual(len(thesis["conditions"]), 1)
        self.assertGreaterEqual(len(thesis["exposure"]["movers"]), 2)
        moved = thesis["exposure"]["moved"]
        self.assertGreaterEqual(len(moved), 3)
        self.assertEqual({item["side"] for item in moved}, {"producer", "consumer"})
        self.assertEqual(thesis["log"][0]["kind"], "opened")
        self.assertTrue(thesis["not_claimed"])
        # No source is an IEA file flagged third-party, and the Pink Sheet copper series is not cited (decision 3).
        self.assertNotIn("worldbank-pink", {source["id"] for source in thesis["sources"]})
        self.assertNotIn("iea-2021", {source["id"] for source in thesis["sources"]})
        # The price record is the USGS producer cathode annual average, in cents per pound (ruling R18), one figure.
        figures = {figure["id"]: figure for figure in thesis["figures"]}
        record = thesis["price_record"]
        self.assertEqual((record["opening"], record["latest"]), ("usgs26-producer-price-2025",) * 2)
        self.assertEqual((figures[record["opening"]]["source"], figures[record["opening"]]["unit"]),
                         ("usgs-csv-2026", "usd_cents_per_lb"))
        self.assertNotIn("cmo-copper-2025", figures)
        # Every PDF figure and passage was read from the PDF's text layer (R17), and the provenance says so exactly.
        method = "transcribed from the PDF's text layer"
        self.assertEqual({source["transcription"]["method"] for source in thesis["sources"] if source["kind"] == "pdf"},
                         {method})
        self.assertIn(method, thesis["provenance"]["method"])
        # R16: each edition date is the day (or first day of the month or year) its publisher states.
        self.assertEqual({source["id"]: source["edition_date"] for source in thesis["sources"]}, EDITION_DATES)

    def test_without_retained_sources_nothing_is_shown_as_checked(self):
        with tempfile.TemporaryDirectory(prefix="second-order-thesis-empty-") as empty:
            body = thesis_view.view(COPPER, sources_root=Path(empty))
        elements = every_element(body)
        self.assertEqual(body["counts"]["sources"], {"verified": 0, "changed": 0, "missing": len(body["sources"])})
        self.assertEqual(body["counts"]["elements"],
                         {"available": 0, "needs_revalidation": 0, "unavailable": len(elements)})
        self.assertTrue(all(element["state"] == "unavailable" and element["problems"] for element in elements))
        self.assertIsNone(body["view"]["statement"])
        self.assertTrue(all(reason["status"] is None and reason["statement"] is None for reason in body["reasons"]))
        self.assertFalse(body["draft"])

    def test_the_content_names_no_contact_address(self):
        folder = thesis_schema.THESES_DIR / COPPER
        own = sorted(path.name for path in folder.iterdir() if path.is_file())
        self.assertEqual(own, ["index.json", "v1.json"])  # The thesis's own files; its event chains sit below.
        for path in sorted(path for path in folder.rglob("*") if path.is_file()):
            with self.subTest(file=path.relative_to(folder).as_posix()):
                self.assertNotIn("@", path.read_text(encoding="utf-8"))


def real_sources() -> Path:
    folder = Path(os.environ[REAL_SOURCES])
    return folder if folder.is_absolute() else ROOT / folder


# R14: each figure cited from the long-format MCS 2026 CSV, with the Country, Statistics_detail and Year its row must
# hold, and whether its Notes cell marks it "Estimated." (an estimated figure must say so in its measure or basis).
# Stated here, independently of the locators in v1.json.
US, TMT = "United States", "thousand metric tons"
USGS_CSV_2026_ROWS = {
    "usgs26-world-mine-2024": ("World total", "Mine production: rounded", "2024", False),
    "usgs26-world-mine-2025": ("World total", "Mine production: rounded", "2025", True),
    "usgs26-us-refinery-2024": (US, "Refinery production", "2024", False),
    "usgs26-us-refinery-2025": (US, "Refinery production", "2025", True),
    "usgs26-us-consumption-2024": (US, "Consumption: Reported, refined copper", "2024", False),
    "usgs26-us-consumption-2025": (US, "Consumption: Reported, refined copper", "2025", True),
    "usgs26-us-primary-2024": (US, "Production, Refinery: Primary (from ore)", "2024", False),
    "usgs26-us-primary-2025": (US, "Production, Refinery: Primary (from ore)", "2025", True),
    "usgs26-us-secondary-2024": (US, "Production, Refinery: Secondary (from scrap)", "2024", False),
    "usgs26-us-secondary-2025": (US, "Production, Refinery: Secondary (from scrap)", "2025", True),
    "usgs26-us-imports-2024": (US, "Imports for consumption: Refined", "2024", False),
    "usgs26-us-imports-2025": (US, "Imports for consumption: Refined", "2025", True),
    "usgs26-us-exports-2024": (US, "Exports: Refined", "2024", False),
    "usgs26-us-exports-2025": (US, "Exports: Refined", "2025", True),
    "usgs26-us-stocks-2024": (US, "Stocks, refined, held by U.S. producers, consumers, and metal exchanges, yearend",
                              "2024", False),
    "usgs26-us-stocks-2025": (US, "Stocks, refined, held by U.S. producers, consumers, and metal exchanges, yearend",
                              "2025", True),
    "usgs26-us-old-scrap-2024": (US, "Copper recovered from old (post-consumer) scrap", "2024", True),
    "usgs26-us-old-scrap-2025": (US, "Copper recovered from old (post-consumer) scrap", "2025", True),
    "usgs26-producer-price-2025": (US, "Price, annual average, cents per pound: U.S. producer, cathode (COMEX + premium)",
                                   "2025", True),
}
CSV_UNITS = {"kt": TMT, "usd_cents_per_lb": "cents per pound"}  # A figure's unit and the CSV's Unit cell for it.
# The IEA workbook's layout, read independently: per sheet, the header row of years, the cell naming each column
# block's scenario (None: the base year, which no scenario heads) and the cell naming each column block's mineral.
IEA_DEMAND, IEA_SUPPLY = "1 Total demand for key minerals", "2 Total supply for key minerals"
IEA_YEAR_ROW = {IEA_DEMAND: 5, IEA_SUPPLY: 4}
IEA_SCENARIO_CELL = {IEA_DEMAND: {"B": None, **{c: "D4" for c in "DEFGH"}, **{c: "J4" for c in "JKLMN"},
                                  **{c: "P4" for c in "PQRST"}},
                     IEA_SUPPLY: {c: "A2" for c in "BCDEHIJK"}}
# Each copper block runs from the row after its title to the row before the next block's title (cobalt), so a figure
# pointed at another mineral's row fails.
IEA_BLOCK = {IEA_DEMAND: {c: ("A7", "Copper", "A21", "Cobalt") for c in "BDEFGHJKLMNPQRST"},
             IEA_SUPPLY: {**{c: ("A6", "Copper - Mining", "A17", "Cobalt - Mining") for c in "BCDE"},
                          **{c: ("G6", "Copper - Refining", "G17", "Cobalt - Refining") for c in "HIJK"}}}
STATUSES = {"reasons": {"grid-demand": "strengthening", "ev-demand": "strengthening", "mine-pipeline": "strengthening",
                        "producer-plans": "strengthening", "world-mine-output": "unchanged"},
            "risks": {"aluminium-substitution": "not_tracked", "recycling": "materialising",
                      "china-construction": "not_tracked", "other-uses-fall": "unchanged"},
            "conditions": {"mine-meets-demand": "not_happened", "refinery-falls-short": "not_happened"}}


@unittest.skipUnless(os.environ.get(REAL_SOURCES), f"opt-in: set {REAL_SOURCES} to the retained "
                                                   "data/sector-sources/copper folder")
class RetainedSourcesTests(unittest.TestCase):
    """The committed copper thesis against the real retained sources. Read-only."""

    def setUp(self):
        self.folder = real_sources()
        self.assertTrue((self.folder / "acquisitions").is_dir(),
                        f"{REAL_SOURCES} must name the folder holding acquisitions/ and the retained files")

    def test_every_element_is_available_against_the_retained_sources(self):
        thesis_sources._MEMO.clear()
        body = thesis_view.view(COPPER, sources_root=self.folder)
        elements = every_element(body)
        self.assertEqual(body["counts"]["sources"], {"verified": len(body["sources"]), "changed": 0, "missing": 0})
        self.assertEqual(body["counts"]["elements"],
                         {"available": len(elements), "needs_revalidation": 0, "unavailable": 0},
                         [(element["id"], element["problems"]) for element in elements if element["problems"]])
        for section, expected in STATUSES.items():
            self.assertEqual({item["id"]: item["status"] for item in body[section]}, expected, section)
        thesis = thesis_schema.load_version(COPPER, 1)
        sources = {source["id"]: source for source in thesis["sources"]}
        # R14: every figure cited from the MCS 2026 CSV sits on a row of the country, statistic and year it claims.
        cited = {figure["id"]: figure for figure in thesis["figures"] if figure["source"] == "usgs-csv-2026"}
        self.assertEqual(set(cited), set(USGS_CSV_2026_ROWS))
        source = sources["usgs-csv-2026"]
        rows = thesis_sources.csv_rows((self.folder / source["folder"] / source["name"]).read_bytes(),
                                       source["encoding"])
        header = rows[0]
        for figure_id, (country, detail, year, estimated) in USGS_CSV_2026_ROWS.items():
            with self.subTest(figure=figure_id):
                figure = cited[figure_id]
                row = rows[figure["locator"]["row"] - 1]
                self.assertEqual((row[header.index("Country")], row[header.index("Statistics_detail")],
                                  row[header.index("Year")]), (country, detail, year))
                self.assertEqual(figure["year"], year)
                self.assertEqual(row[header.index("Unit")], CSV_UNITS[figure["unit"]])
                self.assertEqual(row[header.index("Notes")].startswith("Estimated."), estimated)
                if estimated:  # An estimate says so where the figure is described.
                    self.assertIn("estimate", f"{figure['measure']} {figure['basis'] or ''}".lower())
        # The IEA figures: each cell's column is headed by the figure's year and scenario, in the copper block.
        source = sources["iea-dataset-2026"]
        raw = (self.folder / source["folder"] / source["name"]).read_bytes()
        workbook, refused = thesis_workbook.read_sheets(raw, (IEA_DEMAND, IEA_SUPPLY))
        self.assertEqual(refused, {})
        for figure in (item for item in thesis["figures"] if item["source"] == "iea-dataset-2026"):
            with self.subTest(figure=figure["id"]):
                sheet, cell = figure["locator"]["sheet"], figure["locator"]["cell"]
                cells, column = workbook[sheet], cell.rstrip("0123456789")
                row = int(cell[len(column):])
                self.assertEqual(cells[f"{column}{IEA_YEAR_ROW[sheet]}"], figure["year"])
                block_cell, block, next_cell, next_block = IEA_BLOCK[sheet][column]
                self.assertEqual((cells[block_cell], cells[next_cell]), (block, next_block))
                self.assertTrue(int(block_cell[1:]) < row < int(next_cell[1:]), "outside the copper block")
                self.assertEqual(figure["unit"], "kt")
                self.assertTrue(cells["A2"].endswith("(kt)"))
                scenario_cell = IEA_SCENARIO_CELL[sheet][column]
                if sheet == IEA_SUPPLY:
                    self.assertIn(figure["scenario"], cells[scenario_cell])
                else:
                    self.assertEqual(figure["scenario"], None if scenario_cell is None else cells[scenario_cell])

    def test_reading_the_retained_sources_changes_nothing(self):
        watched = [self.folder, thesis_schema.THESES_DIR]
        before = [tree(folder) for folder in watched]
        thesis_sources._MEMO.clear()
        first = thesis_view.view(COPPER, sources_root=self.folder)
        self.assertEqual(thesis_view.view(COPPER, sources_root=self.folder), first)
        self.assertEqual([tree(folder) for folder in watched], before)


if __name__ == "__main__":
    unittest.main()

"""The copper tools' routes (copper_tools_api) on SYNTHETIC sources in temporary folders: reads write nothing and make
no outside request, a preview writes nothing, a save writes one record once, and every refusal is made before anything
is written. The replies the frontend reader is tested against are captured here (SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1
writes them; otherwise they are compared by parsed JSON)."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import copper_fakes
import fcx_fakes
from second_order import copper_coverage as cc, copper_linked
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
COMMITTED = ROOT / "content" / "tools" / "copper-coverage"
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "x-second-order-scenario": "1", "Content-Type": "application/json"}
SET_A = {"ev": {"source": "scenario", "scenario": "cps"},
         "networks": {"source": "technology_case", "scenario": "steps"},
         "mine": {"source": "total", "kt": "-294.8350405", "reference": "ptfi-sales-change"}}
PART = "all"
FIXED = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
CURRENT = "bagdad-2026-11-04"
TERMS_LINE = "SEC EDGAR copy (exhibit 99.1 to Form 8-K); public filing"


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


class Folders(unittest.TestCase):
    part = PART
    fcx_variant = "verified"  # The SYNTHETIC FCX package (fcx_fakes); no default run reads data/company-sources.

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-copper-tools-api-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sources = copper_fakes.write_sources(self.root / "sources")
        self.inputs = copper_fakes.write_catalog(self.root / "inputs", copper_fakes.catalog(self.sources, self.part))
        self.scenarios = self.root / "scenarios"
        self.fcx_research, self.fcx_sources = fcx_fakes.synthetic_package(self.root / "fcx", self.fcx_variant)

    def app(self, sources: Path | None = None, inputs: Path | None = None, fcx_sources: Path | None = None,
            fcx_research: Path | None = None) -> TestClient:
        return TestClient(create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                     self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                     triage=self.root / "triage", links=self.root / "links",
                                     market=self.root / "market", related_records=self.root / "related",
                                     enrichment_sources=self.root / "es", snapshot_sources=self.root / "snap",
                                     snapshot_index=self.root / "index", theses=self.root / "theses",
                                     thesis_sources_dir=sources or self.sources,
                                     copper_inputs_dir=inputs or self.inputs, copper_scenarios_dir=self.scenarios,
                                     copper_clock=lambda: FIXED,
                                     company_research_dir=fcx_research or self.fcx_research,
                                     company_sources_dir=fcx_sources or self.fcx_sources), base_url=BASE)

    def post(self, client, path, body, headers=HEADERS):
        return client.post(path, content=json.dumps(body).encode("utf-8"), headers=headers)


class Reads(Folders):
    def test_reading_writes_nothing_and_makes_no_outside_request(self):
        attempts = []
        connect = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return connect(sock, address)
        before = tree(self.root)
        with mock.patch.object(socket.socket, "connect", local_only), self.app() as client:
            for path in ("/api/tools/copper", "/api/tools/copper/scenarios"):
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200, reply.text)
                self.assertIs(reply.json()["provider_called"], False)
        self.assertEqual(attempts, [])
        self.assertEqual(tree(self.root), before)

    def test_the_view(self):
        with self.app() as client:
            view = client.get("/api/tools/copper").json()
        self.assertEqual(view["view_version"], "copper-tools-view-0.2")
        self.assertEqual(view["catalog"]["items"], view["catalog"]["verified"])
        self.assertEqual({source["state"] for source in view["sources"]}, {"verified"})
        coverage = view["coverage"]
        self.assertEqual(len(coverage["baselines"]), 9)
        steps = next(b for b in coverage["baselines"] if (b["scenario"], b["year"]) == ("steps", "2035"))
        self.assertEqual(steps["coverage"]["residual"]["value"], "12789")
        self.assertEqual(coverage["refining"]["source_name"], "Copper - Refining")
        self.assertEqual(len(coverage["refining"]["unknowns"]), 3)
        self.assertEqual([control["id"] for control in coverage["controls"]], ["ev", "networks", "mine"])
        self.assertEqual(view["passages"]["iea-supply-note-pipeline"]["text"], copper_fakes.NOTE_PIPELINE)

    def test_without_sources_everything_is_withheld(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.app(sources=empty, inputs=COMMITTED) as client:
            view = client.get("/api/tools/copper").json()
        self.assertEqual(view["catalog"]["verified"], 0)
        self.assertEqual({source["state"] for source in view["sources"]}, {"missing"})
        self.assertEqual({figure["value"] for figure in view["figures"].values()}, {None})
        for baseline in view["coverage"]["baselines"]:
            self.assertIsNone(baseline["coverage"]["residual"]["value"])
            self.assertIsNone(baseline["coverage"]["share_pct"]["shown"])

    def test_a_catalogue_that_does_not_match_the_tools_is_refused(self):
        catalog = copper_fakes.catalog(self.sources, self.part)
        catalog["figures"] = [f for f in catalog["figures"] if f["id"] != "iea-demand-ev-hd-2040"]
        copper_fakes.write_catalog(self.inputs, catalog)
        with self.app() as client:
            reply = client.get("/api/tools/copper")
        self.assertEqual(reply.status_code, 500)
        self.assertIn("does not hold exactly what the tools read", reply.json()["detail"])

    def test_a_missing_catalogue_is_503(self):
        with self.app(inputs=self.root / "nowhere") as client:
            self.assertEqual(client.get("/api/tools/copper").status_code, 503)


class Linked(Folders):
    """Bagdad's later statement, read from the (SYNTHETIC) FCX research beside the catalogue's earlier statement."""

    def test_the_view_links_the_current_statement(self):
        with self.app() as client:
            view = client.get("/api/tools/copper").json()
        self.assertEqual(view["view_version"], "copper-tools-view-0.2")
        self.assertEqual(view["linked"]["state"], "available")
        self.assertEqual(view["linked"]["records"]["nr-bagdad-breakeven-cu"]["display"], "4.00")
        projects = {project["id"]: project for project in view["producers"]["projects"]}
        self.assertEqual([project["id"] for project in view["producers"]["projects"]][:2], [CURRENT, "bagdad"])
        self.assertEqual(projects[CURRENT]["statement"],
                         {"kind": "company_estimates", "text": "Company estimates", "date_text": "stated",
                          "date": "2026-11-04", "document": "Freeport-McMoRan news release",
                          "source": "news-2026-11-04", "terms": TERMS_LINE})
        figure = view["figures"]["fcx-bagdad-capital-2025"]
        source = next(item for item in view["sources"] if item["id"] == figure["source"])
        self.assertEqual(projects["bagdad"]["statement"],
                         {"kind": "earlier_statement", "text": "Earlier statement", "date_text": "signed",
                          "date": source["edition_date"], "document": source["title"], "source": source["id"],
                          "terms": None})
        self.assertEqual([item["shown"] for item in projects[CURRENT]["capital_per_annual_tonne"]], ["44,092"])
        self.assertEqual([item["shown"] for item in projects["bagdad"]["capital_per_annual_tonne"]],
                         ["38,581", "30,865"])
        self.assertTrue(all(project["statement"] is None for key, project in projects.items()
                            if key not in (CURRENT, "bagdad")))

    def test_reading_and_the_panel_write_nothing_in_the_fcx_package(self):
        before = tree(self.root / "fcx")
        with self.app() as client:
            self.assertIs(client.get("/api/tools/copper").json()["provider_called"], False)
            self.assertEqual(self.post(client, "/api/tools/copper/capital-charge",
                                       {"rate_pct": "8", "years": "20"}).status_code, 200)
        self.assertEqual(tree(self.root / "fcx"), before)


class FcxFailures(Folders):
    """Every fault in the FCX package withholds only the current Bagdad row; the copper read stays 200."""

    def test_each_fault_withholds_only_the_current_row(self):
        with self.app() as client:
            verified = client.get("/api/tools/copper").json()
        for variant in fcx_fakes.VARIANTS[1:]:
            with self.subTest(variant=variant):
                research, documents = fcx_fakes.synthetic_package(self.root / f"fcx-{variant}", variant)
                with self.app(fcx_research=research, fcx_sources=documents) as client:
                    reply = client.get("/api/tools/copper")
                self.assertEqual(reply.status_code, 200, reply.text)
                view = reply.json()
                self.assertEqual(view["linked"]["state"], "withheld")
                projects = {project["id"]: project for project in view["producers"]["projects"]}
                self.assertEqual([item["shown"] for item in projects[CURRENT]["capital_per_annual_tonne"]], [None])
                self.assertEqual([item["shown"] for item in projects["bagdad"]["capital_per_annual_tonne"]],
                                 ["38,581", "30,865"])
                self.assertEqual(view["coverage"], verified["coverage"])
                self.assertEqual(view["figures"], verified["figures"])

    def test_an_unrelated_malformed_record_keeps_both_reads(self):
        """An unrelated FCX record whose inputs are a list: the page read and the capital charge stay 200, only the
        current Bagdad row is withheld, and every other value is as with the verified package."""
        body = {"rate_pct": "8", "years": "20"}
        with self.app() as client:
            verified = client.get("/api/tools/copper").json()
            verified_charge = self.post(client, "/api/tools/copper/capital-charge", body).json()
        research, documents = fcx_fakes.synthetic_package(self.root / "fcx-inputs-list", "inputs-list")
        with self.app(fcx_research=research, fcx_sources=documents) as client:
            read = client.get("/api/tools/copper")
            charge = self.post(client, "/api/tools/copper/capital-charge", body)
        self.assertEqual((read.status_code, charge.status_code), (200, 200), f"{read.text[:300]} | {charge.text[:300]}")
        view = read.json()
        self.assertEqual(view["linked"]["state"], "withheld")
        self.assertIn("(AttributeError)", view["linked"]["problem"])
        projects = {project["id"]: project for project in view["producers"]["projects"]}
        self.assertEqual([item["shown"] for item in projects[CURRENT]["capital_per_annual_tonne"]], [None])
        before = {project["id"]: project for project in verified["producers"]["projects"]}
        others = lambda rows: {key: item["capital_per_annual_tonne"] for key, item in rows.items() if key != CURRENT}
        self.assertEqual(others(projects), others(before))
        self.assertEqual(view["coverage"], verified["coverage"])
        self.assertEqual(view["figures"], verified["figures"])
        rows = {row["project"]: row for row in charge.json()["projects"]}
        self.assertEqual([item["shown"] for item in rows[CURRENT]["charges"]], [None])
        earlier = {row["project"]: row for row in verified_charge["projects"]}
        self.assertEqual({key: row for key, row in rows.items() if key != CURRENT},
                         {key: row for key, row in earlier.items() if key != CURRENT})
        self.assertEqual([item["shown"] for item in rows["bagdad"]["charges"]], ["1.782", "1.426"])

    def test_scenarios_do_not_depend_on_fcx(self):
        research, documents = fcx_fakes.synthetic_package(self.root / "fcx-broken", "record-no-value")
        body = {"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "Set A"}
        with self.app(fcx_research=research, fcx_sources=documents) as client:
            saved = self.post(client, "/api/tools/copper/scenarios", body)
            listed = client.get("/api/tools/copper/scenarios").json()
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual([record["state"] for record in listed["records"]], ["verified"])


class Writes(Folders):
    def test_new_records_hold_no_linked_id(self):
        with self.app() as client:
            reply = self.post(client, "/api/tools/copper/preview", {"scenario": "steps", "year": "2035",
                                                                    "assumptions": SET_A, "label": "Set A"}).json()
        ids = {figure["id"] for figure in reply["record"]["figures"]}
        self.assertFalse(ids & (set(copper_linked.FIGURES) | set(copper_linked.PASSAGES)))

    def test_a_preview_writes_nothing(self):
        before = tree(self.root)
        with self.app() as client:
            reply = self.post(client, "/api/tools/copper/preview", {"scenario": "steps", "year": "2035",
                                                                    "assumptions": SET_A})
            self.assertEqual(reply.status_code, 200, reply.text)
            body = reply.json()
            self.assertEqual((body["record"], body["id"], body["written"]), (None, None, False))
            self.assertEqual(body["result"]["residual"]["value"], "12622.8350405")
            labelled = self.post(client, "/api/tools/copper/preview", {"scenario": "steps", "year": "2035",
                                                                       "assumptions": SET_A, "label": "Set A"}).json()
        self.assertRegex(labelled["id"], "^[0-9a-f]{64}$")
        self.assertIs(labelled["exists"], False)
        self.assertIs(labelled["complete"], True)
        self.assertEqual(tree(self.root), before)

    def test_save_once(self):
        body = {"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "Set A"}
        with self.app() as client:
            first = self.post(client, "/api/tools/copper/scenarios", body)
            self.assertEqual(first.status_code, 201, first.text)
            again = self.post(client, "/api/tools/copper/scenarios", body)
            self.assertEqual(again.status_code, 200)
            listed = client.get("/api/tools/copper/scenarios").json()
            preview = self.post(client, "/api/tools/copper/preview", body).json()
        self.assertEqual(first.json()["status"], "created")
        self.assertEqual(again.json()["status"], "unchanged")
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(first.json()["state"], "verified")
        self.assertEqual([item["state"] for item in listed["records"]], ["verified"])
        self.assertIs(preview["exists"], True)
        self.assertEqual(sorted(path.name for path in self.scenarios.iterdir()), [f"{first.json()['id']}.json"])

    def test_refusals_write_nothing(self):
        cases = [
            ({"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "x", "recycling": "160"}, 422,
             cc.RECYCLING_REFUSED),
            ({"scenario": "steps", "year": "2035", "assumptions": {**SET_A, "recycling": {"kt": "1"}}, "label": "x"},
             422, cc.RECYCLING_REFUSED),
            ({"scenario": "steps", "year": "2035", "assumptions": SET_A}, 422, "a label is required"),
            ({"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "x", "note": "free text"}, 422,
             "holds exactly"),
            ({"scenario": "steps", "year": "2035", "assumptions": {"ev": {"source": "value", "kt": "-5"}},
              "label": "x"}, 422, "cannot be negative"),
            ({"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "This proves it"}, 422,
             "claim word"),
        ]
        before = tree(self.root)
        with self.app() as client:
            for body, status, fragment in cases:
                reply = self.post(client, "/api/tools/copper/scenarios", body)
                self.assertEqual(reply.status_code, status, body)
                self.assertIn(fragment, reply.json()["detail"])
            reply = client.post("/api/tools/copper/scenarios", content=b"{not json", headers=HEADERS)
            self.assertEqual(reply.status_code, 400)
            reply = client.post("/api/tools/copper/scenarios", content=b"x" * 20_000, headers=HEADERS)
            self.assertEqual(reply.status_code, 413)
            for headers in ({**HEADERS, "Origin": "https://example.org"},
                            {key: value for key, value in HEADERS.items() if key != "x-second-order-scenario"},
                            {**HEADERS, "Content-Type": "text/plain"}):
                for path in ("/api/tools/copper/scenarios", "/api/tools/copper/preview"):
                    reply = self.post(client, path, {"scenario": "steps", "year": "2035", "assumptions": SET_A,
                                                     "label": "x"}, headers)
                    self.assertIn(reply.status_code, (403, 415), (headers, path))
        self.assertEqual(tree(self.root), before)

    def test_a_withheld_scenario_is_not_saved(self):
        shutil.rmtree(self.sources / "fcx-synthetic-2024")
        with self.app() as client:
            reply = self.post(client, "/api/tools/copper/scenarios", {"scenario": "steps", "year": "2035",
                                                                      "assumptions": SET_A, "label": "x"})
        self.assertEqual(reply.status_code, 409)
        self.assertFalse(self.scenarios.exists())


class Panel(Folders):
    def test_the_panel_writes_nothing_and_refuses_bad_inputs(self):
        before = tree(self.root)
        with self.app() as client:
            reply = self.post(client, "/api/tools/copper/capital-charge", {"rate_pct": "0", "years": "20"})
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertEqual((reply.json()["method"], reply.json()["crf"]), ("limit_at_zero_rate", "0.050000"))
            for body, status in (({"rate_pct": "-1", "years": "20"}, 422), ({"rate_pct": "8", "years": "0"}, 422),
                                 ({"rate_pct": "8"}, 422), ({"rate_pct": "8", "years": "20", "save": True}, 422),
                                 ({"rate_pct": 8, "years": 20}, 422)):
                self.assertEqual(self.post(client, "/api/tools/copper/capital-charge", body).status_code, status)
            no_header = {key: value for key, value in HEADERS.items() if key != "x-second-order-scenario"}
            reply = self.post(client, "/api/tools/copper/capital-charge", {"rate_pct": "8", "years": "20"}, no_header)
            self.assertEqual(reply.status_code, 403)
        self.assertEqual(tree(self.root), before)

    def test_two_bagdad_rows(self):
        with self.app() as client:
            reply = self.post(client, "/api/tools/copper/capital-charge", {"rate_pct": "8", "years": "20"}).json()
        charges = {row["project"]: [charge["shown"] for charge in row["charges"]] for row in reply["projects"]}
        self.assertEqual((charges[CURRENT], charges["bagdad"]), (["2.037"], ["1.782", "1.426"]))
        research, documents = fcx_fakes.synthetic_package(self.root / "fcx-news-missing", "news-missing")
        with self.app(fcx_research=research, fcx_sources=documents) as client:
            reply = self.post(client, "/api/tools/copper/capital-charge", {"rate_pct": "8", "years": "20"}).json()
        charges = {row["project"]: [charge["shown"] for charge in row["charges"]] for row in reply["projects"]}
        self.assertEqual((charges[CURRENT], charges["bagdad"]), ([None], ["1.782", "1.426"]))

    def test_the_view_carries_the_comparison(self):
        with self.app() as client:
            producers = client.get("/api/tools/copper").json()["producers"]
        self.assertEqual(producers["title"], "Published producer unit-cost comparison")
        self.assertEqual({row["state"] for row in producers["rows"]}, {"available"})
        self.assertEqual((producers["capital_panel"]["rate_pct"], producers["capital_panel"]["years"]), (None, None))


class Fixtures(Folders):
    def test_frontend_fixtures(self):
        """The replies the frontend reader is tested against: captured from this producer, never hand-written."""
        empty = self.root / "empty"
        empty.mkdir()
        body = {"scenario": "steps", "year": "2035", "assumptions": SET_A, "label": "Set A: CPS EV copper"}
        with self.app() as client:
            saved = self.post(client, "/api/tools/copper/scenarios", body).json()
            served = {"copper-tools-view.json": client.get("/api/tools/copper").json(),
                      "copper-preview.json": self.post(client, "/api/tools/copper/preview", body).json(),
                      "copper-saved.json": saved,
                      "copper-scenarios.json": client.get("/api/tools/copper/scenarios").json(),
                      "copper-capital-charge.json": self.post(client, "/api/tools/copper/capital-charge",
                                                              {"rate_pct": "8", "years": "20"}).json(),
                      "copper-capital-charge-zero.json": self.post(client, "/api/tools/copper/capital-charge",
                                                                   {"rate_pct": "0", "years": "20"}).json()}
        with self.app(sources=empty, inputs=COMMITTED, fcx_sources=empty) as client:
            served["copper-tools-unavailable.json"] = client.get("/api/tools/copper").json()
        for name, reply in served.items():
            text = json.dumps(reply, ensure_ascii=False)
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn("second-order-copper-tools-api", text, name)
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            else:
                self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_copper_tools_api.py")


class Preservation(Folders):
    """A scenario record saved at 87425ba, before the Bagdad refresh, still reads as verified on the current catalogue."""

    def test_a_record_saved_at_87425ba_still_verifies(self):
        frozen = ROOT / "tests" / "fixtures" / "copper-record-87425ba.json"
        envelope = json.loads(frozen.read_text(encoding="utf-8"))
        self.scenarios.mkdir(parents=True)
        (self.scenarios / f"{envelope['id']}.json").write_bytes(frozen.read_bytes())
        with self.app() as client:
            listed = client.get("/api/tools/copper/scenarios").json()
        item = next(record for record in listed["records"] if record["id"] == envelope["id"])
        self.assertEqual((item["state"], item["catalog_current"], item["problems"]), ("verified", True, []))


if __name__ == "__main__":
    unittest.main()

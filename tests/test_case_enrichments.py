"""Case enrichments (case-enrichment-0.1): the two committed enrichments read strictly against the committed case
library, and the mechanics of binding, statuses, references, claim coverage and retained-copy checks.

Three input layers stay apart. The committed enrichments are read as committed, against an empty sources folder, so a
default run never depends on the maintainer's retained pages. Binding, status and copy-check mechanics run on a
temporary copy of the library and on SYNTHETIC stand-in pages, so they prove the checks, not the history. The retained
BIS pages are read only by one opt-in test (SECOND_ORDER_ENRICHMENT_SOURCES=<the retained folder>), read-only, which
also proves that nothing in that folder changed.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

from fastapi.testclient import TestClient

from second_order import case_enrichments, case_library, related_cases
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = case_library.LIBRARY_DIR
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
REAL_SOURCES = "SECOND_ORDER_ENRICHMENT_SOURCES"  # Explicit opt-in: the maintainer's retained BIS folder, read-only.
BASE = "http://127.0.0.1:8137"
UAE, AMAT, BOSCH = "bis-2026-07-10", "bis-2026-02-12", "bis-2026-06-17"
ENRICHED = (UAE, AMAT)


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Folders(unittest.TestCase):
    """A temporary copy of the committed library (with its enrichments) and an empty retained-sources folder."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-enrichment-"))
        self.addCleanup(shutil.rmtree, self.root, onexc=lambda remove, path, _: (os.chmod(path, stat.S_IWRITE),
                                                                                 remove(path)))
        self.library = self.root / "library"
        shutil.copytree(LIBRARY, self.library)
        self.sources = self.root / "sources"
        self.sources.mkdir()

    def view(self, case_id: str, library: Path | None = None, sources: Path | None = None) -> dict:
        return case_enrichments.enrichment_view(case_id, library or self.library, sources or self.sources)

    def enrichment_file(self, case_id: str) -> Path:
        return self.library / case_enrichments.FOLDER / f"{case_id}.json"

    def edit(self, case_id: str, change) -> None:
        path = self.enrichment_file(case_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        change(raw)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def refused(self, case_id: str, fragment: str = "") -> str:
        with self.assertRaises(case_library.LibraryRefused) as caught:
            self.view(case_id)
        self.assertEqual(caught.exception.status, 500)
        self.assertIn(f"The enrichment of case {case_id} is invalid", str(caught.exception))
        self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)


class CommittedEnrichmentTests(Folders):
    def test_two_enrichments_bind_to_the_unchanged_case_files_and_every_other_case_has_none(self):
        files = sorted(path.stem for path in (LIBRARY / case_enrichments.FOLDER).glob("*.json"))
        self.assertEqual(files, sorted(ENRICHED))
        for case_id in ENRICHED:
            view = self.view(case_id, LIBRARY)
            self.assertEqual((view["state"], view["enrichment"]["case_file_sha256"]),
                             ("bound", sha(LIBRARY / f"{case_id}.json")))
        others = [case["id"] for case in case_library.load_library()["cases"] if case["id"] not in ENRICHED]
        self.assertEqual(len(others), 25)
        for case_id in others:
            self.assertEqual(self.view(case_id, LIBRARY)["state"], "none", case_id)

    def test_every_required_claim_is_checked_and_the_counts_are_derived_from_the_checks(self):
        cases = {case["id"]: case for case in case_library.load_library()["cases"]}
        for case_id in ENRICHED:
            enrichment = self.view(case_id, LIBRARY)["enrichment"]
            targets = [check["target"] for check in enrichment["claim_checks"]]
            self.assertTrue(set(case_enrichments.required_targets(cases[case_id])) <= set(targets))
            self.assertEqual(enrichment["counts"], {state: sum(c["status"] == state for c in enrichment["claim_checks"])
                                                    for state in case_enrichments.CHECK_STATES})

    def test_the_discrepancies_found_are_served_with_their_sources(self):
        def discrepancies(case_id):
            return [(check["target"], check["source"]) for check in self.view(case_id, LIBRARY)["enrichment"]["claim_checks"]
                    if check["status"] == "discrepancy"]
        self.assertEqual(discrepancies(UAE), [("channels[2].source_fact", "release")])
        self.assertEqual(discrepancies(AMAT), [("competing_explanations[0].detail", "listing"),
                                               ("source_notes[2].detail", "listing")])
        uae = {check["target"]: check for check in self.view(UAE, LIBRARY)["enrichment"]["claim_checks"]}
        self.assertIn("a stated reason, not a stated condition", uae["channels[2].source_fact"]["note"])

    def test_the_view_serves_no_private_location_or_passage(self):
        for case_id in ENRICHED:
            view = self.view(case_id, LIBRARY)
            text = json.dumps(view)
            for private in ("folder", "attempt", "sector-sources", "source.html", "data/", "\\\\"):
                self.assertNotIn(private, text, (case_id, private))
            for source in view["enrichment"]["sources"]:
                self.assertEqual(set(source["retained"]), {"approval_id", "sha256", "bytes", "retrieved_at", "charset"})
            self.assertIs(view["provider_called"], False)

    def test_chain_placement_is_labelled_the_curators_reading(self):
        for case_id in ENRICHED:
            enrichment = self.view(case_id, LIBRARY)["enrichment"]
            self.assertEqual((enrichment["chain"]["attribution"], enrichment["chain_label"]),
                             ("curator_interpretation", "Curator's reading, not BIS's wording"))

    def test_the_penalty_is_not_connected_to_the_october_2022_rules(self):
        enrichment = self.view(AMAT, LIBRARY)["enrichment"]
        stated = [item["text"] for item in enrichment["readout"] if item["status"] == "stated"]
        self.assertFalse([text for text in stated if "2022 rules" in text or "October 2022" in text])
        self.assertIn(("instrument", "not_stated", "Any reference to the October 2022 rules on advanced computing and "
                                                  "semiconductor manufacturing items."),
                      [(item["aspect"], item["status"], item["text"]) for item in enrichment["readout"]])
        self.assertIn("does not cite the October 2022 rules", enrichment["comparison"]["text"])

    def test_an_unread_document_is_named_only_where_the_source_refers_to_it(self):
        uae = self.view(UAE, LIBRARY)["enrichment"]
        timing = [item for item in uae["readout"] if item["aspect"] == "timing"]
        self.assertEqual([item["status"] for item in timing], ["stated", "not_stated"])  # Never "in the notice".
        for case_id in ENRICHED:
            enrichment = self.view(case_id, LIBRARY)["enrichment"]
            declared = {reference["id"] for reference in enrichment["references"]}
            self.assertTrue(all(reference["read"] is False for reference in enrichment["references"]))
            for item in enrichment["readout"]:
                self.assertEqual(item["reference"] in declared, item["status"] == "referenced_unread", item)

    def test_the_comparison_cites_facts_of_the_retained_historical_case(self):
        historical = {fact["id"]: fact["text"] for case in related_cases.load()["cases"]
                      if case["id"] == "bis-2022-10-07" for fact in case["facts"]}
        for case_id in ENRICHED:
            comparison = self.view(case_id, LIBRARY)["enrichment"]["comparison"]
            self.assertEqual(comparison["href"], "/library/historical/bis-2022-10-07")
            self.assertEqual({fact["id"]: fact["text"] for fact in comparison["facts"]},
                             {fact["id"]: historical[fact["id"]] for fact in comparison["facts"]})

    def test_in_a_checkout_without_the_retained_pages_every_copy_is_absent(self):
        for case_id in ENRICHED:
            copies = self.view(case_id, LIBRARY)["enrichment"]["copies"]
            self.assertEqual({(copy["state"], copy["acquisition_record"]) for copy in copies}, {("absent", "absent")})


class BindingTests(Folders):
    def test_a_changed_case_file_makes_its_enrichment_stale_and_unshown(self):
        path = self.library / f"{UAE}.json"
        path.write_bytes(path.read_bytes() + b"\n")  # Still a valid case; different bytes.
        case_library.load_library(self.library)
        view = self.view(UAE)
        self.assertEqual((view["state"], view["enrichment"]), ("stale", None))
        self.assertIn("different version of the case file", view["note"])
        self.assertEqual(self.view(AMAT)["state"], "bound")

    def test_a_case_without_an_enrichment_has_none_and_an_unknown_case_is_not_found(self):
        self.enrichment_file(AMAT).unlink()
        self.assertEqual((self.view(AMAT)["state"], self.view(AMAT)["enrichment"]), ("none", None))
        for unknown in ("bis-2099-01-01", "../collection", ""):
            with self.assertRaises(case_library.LibraryRefused) as caught:
                self.view(unknown)
            self.assertEqual(caught.exception.status, 404)

    def test_the_case_view_itself_is_unchanged_by_an_enrichment(self):
        with_enrichment = case_library.case_view(UAE, self.library)
        shutil.rmtree(self.library / case_enrichments.FOLDER)
        self.assertEqual(case_library.case_view(UAE, self.library), with_enrichment)
        self.assertNotIn("enrichment", json.dumps(with_enrichment))


class StatusAndRecordTests(Folders):
    """Each change keeps the binding intact, so the enrichment is read and must be refused in full."""

    def check(self, case_id: str, change, fragment: str) -> None:
        self.edit(case_id, change)
        self.refused(case_id, fragment)

    def test_statement_statuses_and_references(self):
        def unknown(raw): raw["readout"][0]["status"] = "implied"
        def silent_reference(raw): raw["readout"][3]["reference"] = None
        def undeclared(raw): raw["readout"][3]["reference"] = "the-rule-text"
        def silence_sent_to_a_document(raw): raw["readout"][7]["reference"] = "federal-register-notice"
        def read_reference(raw): raw["references"][0]["read"] = True
        def no_timing(raw): raw["readout"] = [item for item in raw["readout"] if item["aspect"] != "timing"]
        def nothing_unstated(raw): raw["readout"] = [item for item in raw["readout"] if item["status"] != "not_stated"]
        for change, fragment in ((unknown, "readout[0].status"), (silent_reference, "readout[3].reference"),
                                 (undeclared, "readout[3].reference"),
                                 (silence_sent_to_a_document, "readout[7].reference"),
                                 (read_reference, "references[0].read"), (no_timing, "readout"),
                                 (nothing_unstated, "does not state")):
            with self.subTest(change=change.__name__):
                self.setUp()
                self.check(UAE, change, fragment)

    def test_claim_check_statuses_coverage_and_labels(self):
        def unknown(raw): raw["claim_checks"][2]["status"] = "verified"
        def noted_consistent(raw): raw["claim_checks"][2]["note"] = "Fine."
        def silent_discrepancy(raw): raw["claim_checks"][10]["note"] = None
        def unchecked_key_fact(raw): del raw["claim_checks"][2]
        def unchecked_channel(raw): del raw["claim_checks"][10]
        def out_of_range(raw): raw["claim_checks"][2]["target"] = "key_facts[9]"
        def unknown_section(raw): raw["claim_checks"][2]["target"] = "overview[0]"
        def repeated(raw): raw["claim_checks"][3]["target"] = raw["claim_checks"][2]["target"]
        def wrong_label(raw): raw["claim_checks"][2]["label"] = "Penalty"
        def undeclared_source(raw): raw["claim_checks"][2]["source"] = "listing"
        for change, fragment in ((unknown, "claim_checks[2].status"), (noted_consistent, "claim_checks[2].note"),
                                 (silent_discrepancy, "claim_checks[10].note"),
                                 (unchecked_key_fact, "key_facts[0]"), (unchecked_channel, "channels[2].source_fact"),
                                 (out_of_range, "claim_checks[2].target"), (unknown_section, "claim_checks[2].target"),
                                 (repeated, "claim_checks[3].target"), (wrong_label, "claim_checks[2].label"),
                                 (undeclared_source, "claim_checks[2].source")):
            with self.subTest(change=change.__name__):
                self.setUp()
                self.check(UAE, change, fragment)

    def test_sources_and_their_records(self):
        def no_sources(raw): raw["sources"] = []
        def no_release(raw): raw["sources"] = [source for source in raw["sources"] if source["id"] != "release"]
        def other_address(raw): raw["sources"][0]["url"] = "https://www.bis.gov/press-release/another-release"
        def other_date(raw): raw["sources"][0]["date_as_stated"] = "FOR IMMEDIATE RELEASE | July 11, 2026"
        def foreign_host(raw): raw["sources"][1]["url"] = "https://www.commerce.gov/news"
        def other_approval(raw): raw["sources"][0]["retained"]["approval_id"] = "wto-trade-sources-01"
        def bad_hash(raw): raw["sources"][0]["retained"]["sha256"] = "abc"
        def no_offset(raw): raw["sources"][0]["retained"]["retrieved_at"] = "2026-10-12T14:47:55"
        def repeated_id(raw): raw["sources"][1]["id"] = "release"
        def prepared_before_retrieval(raw): raw["provenance"]["prepared_on"] = "2026-10-11"
        for change, fragment in ((no_sources, "sources"), (no_release, "sources"), (other_address, "url"),
                                 (other_date, "date_as_stated"), (foreign_host, "sources[1].url"),
                                 (other_approval, "approval_id"), (bad_hash, "sha256"), (no_offset, "retrieved_at"),
                                 (repeated_id, "sources[1].id"), (prepared_before_retrieval, "prepared_on")):
            with self.subTest(change=change.__name__):
                self.setUp()
                self.check(AMAT, change, fragment)

    def test_examination_chain_comparison_and_provenance(self):
        def renamed_channel(raw): raw["examination"][0]["channel"] = "AI hardware demand"
        def missing_channel(raw): del raw["examination"][2]
        def reordered(raw): raw["examination"].reverse()
        def empty_observations(raw): raw["examination"][1]["observations"] = []
        def attributed_to_bis(raw): raw["chain"]["attribution"] = "stated_by_source"
        def unknown_case(raw): raw["comparison"]["historical_case"] = "bis-2023-10-17"
        def unknown_fact(raw): raw["comparison"]["facts"] = ["two-rules", "invented"]
        def reviewed(raw): raw["provenance"]["human_review"] = "reviewed"
        def research_use(raw): raw["provenance"]["research_use"] = "included"
        def current_rules(raw): raw["currency"] = "current"
        def extra_field(raw): raw["verdict"] = "confirmed"
        def other_case(raw): raw["case_id"] = AMAT
        for change, fragment in ((renamed_channel, "examination"), (missing_channel, "examination"),
                                 (reordered, "examination"), (empty_observations, "examination[1].observations"),
                                 (attributed_to_bis, "chain.attribution"), (unknown_case, "comparison.historical_case"),
                                 (unknown_fact, "comparison.facts"), (reviewed, "provenance.human_review"),
                                 (research_use, "provenance.research_use"), (current_rules, "currency"),
                                 (extra_field, "enrichment"), (other_case, "case_id")):
            with self.subTest(change=change.__name__):
                self.setUp()
                self.check(UAE, change, fragment)

    def test_a_file_that_is_not_strict_json_is_refused(self):
        path = self.enrichment_file(UAE)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('"currency": "historical",', '"currency": "historical", "currency": "historical",'),
                        encoding="utf-8")
        self.refused(UAE, "strict UTF-8 JSON")

    def test_a_comparison_whose_historical_cases_cannot_be_read_is_refused_not_dropped(self):
        with self.assertRaises(case_library.LibraryRefused) as caught:
            case_enrichments.enrichment_view(UAE, self.library, self.sources, self.root / "no-historical-cases")
        self.assertIn("comparison: the historical cases it compares with cannot be read", str(caught.exception))


class CopyCheckTests(Folders):
    """SYNTHETIC stand-in pages: the record is rewritten to describe them, so the mechanics, not the history, are proven."""

    PAGE = b"<!DOCTYPE html><html><body><p>Synthetic stand-in page.</p></body></html>"

    def stand_in(self, with_record: bool) -> Path:
        page = self.sources / "bis-2026-07-10" / "source.html"
        page.parent.mkdir(parents=True)
        page.write_bytes(self.PAGE)

        def describe(raw):
            raw["sources"][0]["retained"].update(sha256=hashlib.sha256(self.PAGE).hexdigest(), bytes=len(self.PAGE))
        self.edit(UAE, describe)
        if with_record:
            record = self.sources / "acquisitions" / "bis-semis-sources-01" / "outcome-2.json"
            record.parent.mkdir(parents=True)
            retained = json.loads(self.enrichment_file(UAE).read_text(encoding="utf-8"))["sources"][0]
            record.write_text(json.dumps({
                "outcome": "complete", "http_status": 200, "url": retained["url"], "approval_id": "bis-semis-sources-01",
                "sha256": retained["retained"]["sha256"], "bytes": retained["retained"]["bytes"],
                "retained": "data/sector-sources/bis/bis-2026-07-10/source.html",
                "body_completed_at": retained["retained"]["retrieved_at"]}), encoding="utf-8")
        return page

    def copy(self) -> dict:
        (copy,) = self.view(UAE)["enrichment"]["copies"]
        return copy

    def test_a_matching_copy_and_record_verify(self):
        self.stand_in(with_record=True)
        self.assertEqual((self.copy()["state"], self.copy()["acquisition_record"]), ("verified", "matches"))

    def test_a_matching_copy_without_its_record_verifies_and_says_so(self):
        self.stand_in(with_record=False)
        copy = self.copy()
        self.assertEqual((copy["state"], copy["acquisition_record"]), ("verified", "absent"))
        self.assertIn("not on this machine", copy["detail"])

    def test_a_copy_that_differs_from_its_record_is_reported_never_trusted(self):
        page = self.stand_in(with_record=True)
        page.write_bytes(self.PAGE.replace(b"Synthetic", b"Altered!!"))
        copy = self.copy()
        self.assertEqual((copy["state"], copy["acquisition_record"]), ("different", "not_compared"))
        self.assertIn("not this file", copy["detail"])

    def test_a_record_that_disagrees_is_reported(self):
        self.stand_in(with_record=True)
        record = self.sources / "acquisitions" / "bis-semis-sources-01" / "outcome-2.json"
        record.write_text(record.read_text(encoding="utf-8").replace('"complete"', '"oversized"'), encoding="utf-8")
        self.assertEqual((self.copy()["state"], self.copy()["acquisition_record"]), ("different", "differs"))

    def test_a_missing_copy_is_absent(self):
        self.assertEqual(self.copy()["state"], "absent")

    def test_reading_writes_nothing(self):
        self.stand_in(with_record=True)
        before = (tree(self.library), tree(self.sources))
        for case_id in (UAE, AMAT, BOSCH):
            self.view(case_id)
        self.assertEqual((tree(self.library), tree(self.sources)), before)


class ApiTests(Folders):
    def client(self, library: Path | None = None) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                       triage=self.root / "triage", links=self.root / "links",
                                       market=self.root / "market", library=library or self.library,
                                       related_sources=self.root / "related-sources",
                                       related_records=self.root / "related", enrichment_sources=self.sources),
                            base_url=BASE)
        self.addCleanup(client.close)
        return client

    def test_the_route_serves_bound_none_and_not_found_and_writes_nothing(self):
        before = (tree(self.library), tree(self.sources), tree(self.root))
        with self.client() as client:
            self.assertEqual(client.get(f"/api/case-library/{UAE}/enrichment").json()["state"], "bound")
            self.assertEqual(client.get(f"/api/case-library/{BOSCH}/enrichment").json()["state"], "none")
            self.assertEqual(client.get("/api/case-library/bis-2099-01-01/enrichment").status_code, 404)
            case = client.get(f"/api/case-library/{UAE}")
            self.assertEqual((case.status_code, case.json()["view_version"]), (200, case_library.VIEW_VERSION))
        self.assertEqual((tree(self.library), tree(self.sources), tree(self.root)), before)

    def test_an_invalid_enrichment_refuses_its_view_but_not_the_case(self):
        self.edit(UAE, lambda raw: raw.update(currency="current"))
        with self.client() as client:
            refused = client.get(f"/api/case-library/{UAE}/enrichment")
            self.assertEqual(refused.status_code, 500)
            self.assertIn("is not served", refused.json()["detail"])
            self.assertEqual(client.get(f"/api/case-library/{UAE}").status_code, 200)
            self.assertEqual(client.get(f"/api/case-library/{AMAT}/enrichment").json()["state"], "bound")


class FrontendFixtureTests(Folders):
    """The client tests read these captured views; they are rewritten only with the explicit opt-in."""

    def compare(self, name: str, served: dict) -> None:
        path = FIXTURES / name
        text = json.dumps(served, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        if os.environ.get(WRITE_FIXTURES) == "1":
            path.write_bytes(text.encode("utf-8"))
        else:
            self.assertEqual(served, json.loads(path.read_text(encoding="utf-8")),
                             f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                             "-s tests -p test_case_enrichments.py")

    def test_served_views_match_the_committed_frontend_fixtures(self):
        self.compare(f"library-enrichment-{UAE}.json", self.view(UAE, LIBRARY))
        self.compare(f"library-enrichment-{AMAT}.json", self.view(AMAT, LIBRARY))
        self.compare("library-enrichment-none.json", self.view(BOSCH, LIBRARY))


@unittest.skipUnless(os.environ.get(REAL_SOURCES), f"opt-in: set {REAL_SOURCES} to the retained BIS folder")
class RetainedSourceTests(unittest.TestCase):
    """The committed enrichments against the maintainer's retained BIS pages and acquisition records. Read-only."""

    def test_every_retained_copy_and_acquisition_record_agrees(self):
        folder = Path(os.environ[REAL_SOURCES])
        self.assertTrue((folder / "acquisitions" / "bis-semis-sources-01").is_dir(), folder)
        before = tree(folder)
        for case_id in ENRICHED:
            with self.subTest(case=case_id):
                for copy in case_enrichments.enrichment_view(case_id, sources=folder)["enrichment"]["copies"]:
                    self.assertEqual((copy["state"], copy["acquisition_record"]), ("verified", "matches"), copy)
        self.assertEqual(tree(folder), before)


if __name__ == "__main__":
    unittest.main()

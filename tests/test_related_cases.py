"""Related Cases: the two committed historical cases, read strictly, and Related Cases for one event, on SYNTHETIC Event
Inbox entries, captures and headline-triage results in temporary folders.

Three input layers stay apart. The committed case files are read as committed. Source-check mechanics run on SYNTHETIC
stand-in pages built from a case's own quotes, so they prove the checks, not the history. The retained official pages
are never part of a default run: one opt-in test (SECOND_ORDER_RELATED_SOURCES=<the retained folder>) checks the
committed cases against them, read-only, and proves that nothing in that folder changed.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_event_inbox import (CPI, EIA, EMPSIT, FED, WTO, Network, atom, clock, eia_item, eia_rss, rss, rss_item,
                              wto_item, wto_rss)
from test_headline_triage import PREPARED_AT, Provider, reply
from second_order import event_inbox, event_intake, related_cases, related_rules, triage_flow, triage_plan
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
REAL_SOURCES = "SECOND_ORDER_RELATED_SOURCES"  # Explicit opt-in: the maintainer's retained folder, read-only.
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Related": "1"}
FIND = json.dumps({"find_related_cases": True})
CLOCK = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
BIS, OFAC = "bis-2022-10-07", "ofac-pdvsa-2019-01-28"
# SYNTHETIC feed entries: invented titles and excerpts in the shape of the WTO, EIA and Fed feeds.
CONTROLS = "Members discuss new export controls on advanced semiconductors"
RUSSIA = "Sanctions on Russian crude oil exports shift trade flows"
CRUDE = "U.S. crude oil production reached a record in July"
OIL_SANCTIONS = "Oil sanctions"
VAGUE = "Members review recent trade measures"
STATEMENT = "Federal Reserve issues FOMC statement"
FED_LINK = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{}.htm"


def feeds(controls_excerpt: str = "Delegations raised concerns about new restrictions on chips (synthetic).") -> dict:
    return {
        FED: [(200, rss([rss_item(1, STATEMENT, FED_LINK.format("20260916a"), pub="Wed, 16 Sep 2026 18:00:00 GMT"),
                         rss_item(2, STATEMENT, FED_LINK.format("20260729a"), pub="Wed, 29 Jul 2026 18:00:00 GMT")]))],
        EIA: [(200, eia_rss([eia_item(1, RUSSIA, description="Russian crude oil exports were redirected after sanctions "
                                                             "(synthetic)."),
                             eia_item(2, CRUDE, description="Crude oil production rose to a record (synthetic)."),
                             eia_item(3, OIL_SANCTIONS, description=None)]))],
        EMPSIT: [(200, atom([]))], CPI: [(200, atom([]))],
        WTO: [(200, wto_rss([wto_item(1, CONTROLS, description=controls_excerpt),
                             wto_item(2, CONTROLS, pub="Thu, 01 Oct 2026 00:00:00 GMT",
                                      description="Members returned to the topic (synthetic)."),
                             wto_item(3, VAGUE, description="Members exchanged views (synthetic).")]))],
    }


def tree(folder: Path) -> dict:
    found = {}
    if folder.exists():
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                found[path.relative_to(folder).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(),
                                                             path.stat().st_mtime_ns)
    return found


def stand_in_page(quotes: list[str]) -> bytes:
    """A SYNTHETIC page holding a case's quotes, each in its own paragraph, with a script that must be ignored."""
    paragraphs = "".join(f"<p>{quote.replace('&', '&amp;')}</p>" for quote in quotes)
    return (f"<!DOCTYPE html><html><head><title>Synthetic</title><script>var x = 'not text';</script></head>"
            f"<body><main>{paragraphs}</main></body></html>").encode("utf-8")


class Harness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.inbox, self.intake, self.triage = self.root / "inbox", self.root / "intake", self.root / "triage"
        self.links, self.records, self.sources = self.root / "links", self.root / "related", self.root / "sources"
        self.cases = self.root / "cases"
        shutil.copytree(related_cases.CASES_DIR, self.cases)
        self.refresh(feeds())
        self.client = self.app()

    def refresh(self, answers: dict, start: datetime = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)) -> None:
        event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock(start))
        view = event_inbox.inbox_view(self.inbox)
        self.items = view["items"] + view["retained"]

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.intake, self.root / "attempts", inbox=self.inbox, triage=self.triage,
                                       links=self.links, market=self.root / "market", related=self.cases,
                                       related_sources=self.sources, related_records=self.records,
                                       related_clock=lambda: CLOCK), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def id(self, title: str, part: str = "") -> str:
        (found,) = [item["id"] for item in self.items if item["title"] == title and part in item["link"]]
        return found

    def capture(self, headline: str, link: str, text: str, minute: int = 0) -> str:
        return event_intake.capture_text(headline, link, "2026-10-01T10:00:00-04:00", "synthetic-story", text,
                                         "claude-sonnet-5-5", self.intake,
                                         lambda: datetime(2026, 10, 2, 9, minute, tzinfo=timezone.utc))["capture_id"]

    def view(self, kind: str, event_id: str, client: TestClient | None = None) -> dict:
        response = (client or self.client).get(f"/api/related-cases/events/{kind}/{event_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def find(self, kind: str, event_id: str, client: TestClient | None = None, status: int = 201) -> dict:
        response = (client or self.client).post(f"/api/related-cases/events/{kind}/{event_id}/matches",
                                                headers=HEADERS, content=FIND)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def checked(self, kind: str, event_id: str) -> dict:
        self.find(kind, event_id)
        page = self.view(kind, event_id)
        self.assertEqual(page["state"], "checked", page["detail"])
        return page["match"]

    def stored(self) -> list[Path]:
        folder = self.records / "matches"
        return sorted(folder.glob("*.json")) if folder.is_dir() else []

    def classify(self, item_id: str, mode: str, event_type: str, summary: str) -> None:
        """One accepted triage result for the entry's current version, from the fake provider (SYNTHETIC)."""
        provider = Provider(lambda request: reply([{"id": item_id, "category": "Policy decision",
                                                    "event_type": event_type, "summary": summary}]))
        prepared = triage_plan.prepare(json.dumps({"item_ids": [item_id], "mode": mode, "reprocess_ids": []}).encode(),
                                       self.inbox, self.triage, lambda: PREPARED_AT)
        plan = prepared["plan"]
        fields = {"request_sha256": plan["request_sha256"], "reprocess_ids": plan["reprocess"],
                  "comparison_pairs": plan["pairs"]["needed"]}
        fields |= {"approve_simulated_response": True} if mode == "simulated" else {
            "approve_paid_request": True,
            "estimated_max_usd": plan["cost_estimate"]["estimated_paid_if_output_reaches_max_usd"]}
        triage_flow.dispatch(plan["triage_id"], mode, json.dumps(fields).encode(),
                             provider.senders(paid=mode == "paid"), self.triage, lambda: PREPARED_AT)
        self.assertEqual(len(provider.requests), 1)


# ---------------------------------------------------------------- the committed cases

class CollectionTests(unittest.TestCase):
    def test_the_committed_cases_keep_facts_interpretation_and_review_status_apart(self):
        loaded = related_cases.load()
        self.assertEqual([case["id"] for case in loaded["cases"]], [OFAC, BIS])  # Announcement order.
        for case in loaded["cases"]:
            self.assertEqual({key: case["provenance"][key] for key in related_cases.FIXED_PROVENANCE},
                             {"ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded",
                              "currency": "historical"})
            self.assertTrue(all(fact["quotes"] for fact in case["facts"]))
            texts = [channel["text"] for channel in case["interpretation"]["channels"]]
            self.assertFalse(any(char.isdigit() for text in texts + [case["interpretation"]["why_read"]]
                                 for char in text))
            self.assertEqual(case["provenance"]["sources_read"], [case["source"]["url"]])
        bis = next(case for case in loaded["cases"] if case["id"] == BIS)
        dates = [(item["kind"], item["date"]) for item in bis["dates"]]
        self.assertEqual(dates, [("announcement", "2022-10-07"), ("effective", "2022-10-07"), ("effective", "2022-10-07"),
                                 ("effective", "2022-10-12"), ("effective", "2022-10-21"), ("publication", None),
                                 ("deadline", None)])
        ofac = next(case for case in loaded["cases"] if case["id"] == OFAC)
        self.assertEqual([(item["kind"], item["date"]) for item in ofac["dates"]],
                         [("announcement", "2019-01-28"), ("action", "2019-01-28"), ("effective", None)])
        self.assertEqual([item["topic"] for item in loaded["collection"]["unfinished"]],
                         ["Tariffs and international trade", "Competition and regulatory policy", "Labor disruptions"])

    def test_the_library_view_lists_both_cases_and_the_coverage_not_built(self):
        view = related_cases.collection_view()
        self.assertEqual([(row["id"], row["announced"]) for row in view["cases"]],
                         [(OFAC, "2019-01-28"), (BIS, "2022-10-07")])
        self.assertIn("most events will have no related case", view["coverage_note"])
        self.assertTrue(all(item["outcome"].startswith("Not built yet.") for item in view["unfinished"]))

    def test_the_tags_use_the_rules_vocabulary(self):
        self.assertEqual(related_cases.match_cases(related_cases.load()), [
            {"id": OFAC, "tags": {"instrument": ["sanctions"], "sector": ["oil"], "geography": ["venezuela"],
                                  "agency": ["treasury"]}},
            {"id": BIS, "tags": {"instrument": ["export-controls"], "sector": ["semiconductors"],
                                 "geography": ["prc"], "agency": ["bis"]}}])


class ContentGuardTests(unittest.TestCase):
    """Each edit to a copy of the committed content must refuse the whole collection."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cases = Path(folder.name) / "cases"
        shutil.copytree(related_cases.CASES_DIR, self.cases)

    def edit(self, name: str, change) -> None:
        path = self.cases / name
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_bytes(json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))

    def refused(self, name: str, change, expected: str) -> None:
        self.edit(name, change)
        with self.assertRaises(related_cases.RelatedRefused) as caught:
            related_cases.load(self.cases)
        self.assertEqual(caught.exception.status, 500)
        self.assertIn(expected, str(caught.exception))

    def fact(self, case: dict, fact_id: str) -> dict:
        return next(fact for fact in case["facts"] if fact["id"] == fact_id)

    def test_a_figure_its_quotes_do_not_state_is_refused(self):
        self.refused(f"{BIS}.json", lambda case: self.fact(case, "uvl-changes").update(
            text="That rule adds 32 entities to the Unverified List."), "figures its cited quotes do not: ['32']")

    def test_a_summary_figure_must_come_from_the_facts_it_cites(self):
        def change(case):
            case["summary"]["facts"] = ["designation"]  # Drops the fact that quotes the date.
        self.refused(f"{OFAC}.json", change, "figures its cited quotes do not")

    def test_interpretation_states_no_figures(self):
        def change(case):
            case["interpretation"]["why_read"] += " It mattered in 2022."
        self.refused(f"{BIS}.json", change, "interpretation states no figures")

    def test_a_date_needs_the_sources_own_wording(self):
        def change(case):
            case["dates"][3]["date"] = "2022-10-13"
        self.refused(f"{BIS}.json", change, "the source's own wording must state October 13, 2022")

    def test_a_dateline_must_be_part_of_a_cited_quote(self):
        def change(case):
            case["dates"][0]["as_stated"] = "October 7, 2022, 10:00 a.m."
        self.refused(f"{BIS}.json", change, "must be part of a quote of the facts it cites")

    def test_an_unstated_date_needs_a_note(self):
        def change(case):
            case["dates"][5]["note"] = None
        self.refused(f"{BIS}.json", change, "needs a note")

    def test_a_citation_must_name_a_fact_of_the_case(self):
        def change(case):
            case["scope"][0]["facts"] = ["not-a-fact"]
        self.refused(f"{BIS}.json", change, "expected distinct IDs of this case's facts")

    def test_a_tag_must_come_from_the_rules_vocabulary(self):
        def change(case):
            case["tags"]["sector"][0]["slug"] = "steel"
        self.refused(f"{OFAC}.json", change, "related-match-rules-0.1")

    def test_review_status_cannot_be_relabelled(self):
        def change(case):
            case["provenance"]["human_review"] = "reviewed"
        self.refused(f"{OFAC}.json", change, 'human_review: must be "not_reviewed"')

    def test_a_quote_keeps_the_pages_single_spaces(self):
        self.refused(f"{BIS}.json", lambda case: self.fact(case, "allies").update(
            quotes=["The Department of Commerce  briefed"]), "a quote keeps single spaces")

    def test_files_must_match_the_listed_cases_in_announcement_order(self):
        (self.cases / "extra-case.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(related_cases.RelatedRefused) as caught:
            related_cases.load(self.cases)
        self.assertIn("differ from the case files", str(caught.exception))
        (self.cases / "extra-case.json").unlink()
        self.refused("collection.json", lambda collection: collection["cases"].reverse(), "announcement order")

    def test_a_repeated_key_is_refused(self):
        path = self.cases / f"{OFAC}.json"
        path.write_bytes(path.read_bytes().replace(b'"topic": "Sanctions",', b'"topic": "Sanctions", "topic": "X",'))
        with self.assertRaises(related_cases.RelatedRefused) as caught:
            related_cases.load(self.cases)
        self.assertIn("a JSON key is repeated", str(caught.exception))


# ---------------------------------------------------------------- the retained copy

class SourceCheckTests(unittest.TestCase):
    """SYNTHETIC stand-in pages: these prove the checks, not the history."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.sources = Path(folder.name) / "sources"
        self.case = json.loads(json.dumps(next(case for case in related_cases.load()["cases"] if case["id"] == BIS)))

    def keep(self, page: bytes) -> None:
        retained = self.case["source"]["retained"]
        path = self.sources / retained["folder"] / retained["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(page)
        retained.update(sha256=hashlib.sha256(page).hexdigest(), bytes=len(page))

    def outcome(self, **changes) -> None:
        retained = self.case["source"]["retained"]
        record = {"outcome": "complete", "http_status": 200, "url": self.case["source"]["url"],
                  "sha256": retained["sha256"], "bytes": retained["bytes"], "approval_id": retained["approval_id"],
                  "retained": f"data/sector-sources/related-cases/{retained['folder']}/{retained['file']}",
                  "dispatched_at": retained["requested_at"], "body_completed_at": retained["received_at"],
                  "named_headers": {"content-type": retained["media_type"]}, **changes}
        path = self.sources / "acquisitions" / retained["approval_id"] / f"outcome-{retained['attempt']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_page_text_skips_scripts_decodes_entities_and_keeps_blocks_apart(self):
        blocks = related_cases.page_blocks(b"<html><head><title>T</title><style>p{}</style></head><body>"
                                           b"<p>One &amp; <a href='#'>two</a>.</p><script>three</script>"
                                           b"<div>Four\n   five</div><li>six</li></body></html>")
        self.assertEqual(blocks, ["One & two.", "Four five", "six"])
        self.assertFalse(related_cases.quoted("two. Four", blocks))  # Never across a block boundary.

    def test_a_matching_stand_in_is_verified_and_an_agreeing_acquisition_record_is_reported(self):
        self.keep(stand_in_page(related_cases.case_quotes(self.case)))
        check = related_cases.source_check(self.case, self.sources)
        self.assertEqual((check["state"], check["acquisition_record"], check["quotes"]), ("verified", "absent", 37))
        self.outcome()
        self.assertEqual(related_cases.source_check(self.case, self.sources)["acquisition_record"], "matches")
        self.outcome(sha256="0" * 64)
        self.assertEqual(related_cases.source_check(self.case, self.sources)["state"], "different")

    def test_a_missing_quote_refuses_the_case(self):
        quotes = related_cases.case_quotes(self.case)
        for page in (stand_in_page(quotes[:-1]),  # One quote absent.
                     stand_in_page(quotes[:-1]).replace(b"</head>", f"<script>{quotes[-1]}</script></head>".encode())):
            with self.subTest(page=len(page)):
                self.keep(page)
                with self.assertRaises(related_cases.RelatedRefused) as caught:
                    related_cases.source_check(self.case, self.sources)
                self.assertIn("do not appear in its retained copy", str(caught.exception))

    def test_a_different_file_is_reported_and_not_checked(self):
        self.keep(stand_in_page(related_cases.case_quotes(self.case)))
        path = self.sources / "bis-2022-10-07" / "source.html"
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(related_cases.source_check(self.case, self.sources)["state"], "different")

    def test_without_a_copy_the_case_says_it_was_not_checked_here(self):
        check = related_cases.source_check(self.case, self.sources)
        self.assertEqual(check["state"], "absent")
        self.assertIn("could not be checked here", check["detail"])


@unittest.skipUnless(os.environ.get(REAL_SOURCES), f"opt-in: set {REAL_SOURCES} to the retained related-cases folder")
class RetainedSourceTests(unittest.TestCase):
    """The committed cases against the maintainer's retained official pages. Read-only."""

    def test_every_quote_is_in_the_retained_page_and_the_acquisition_records_agree(self):
        folder = Path(os.environ[REAL_SOURCES])
        self.assertTrue((folder / "acquisitions" / "related-cases-sources-01").is_dir(), folder)
        before = tree(folder)
        for case_id in (OFAC, BIS):
            with self.subTest(case=case_id):
                check = related_cases.case_view(case_id, sources=folder)["source_check"]
                self.assertEqual((check["state"], check["acquisition_record"]), ("verified", "matches"),
                                 check["detail"])
        self.assertEqual(tree(folder), before)


# ---------------------------------------------------------------- the rule

class RuleTests(unittest.TestCase):
    cases = related_cases.match_cases(related_cases.load())

    def tags(self, text: str, field: str = "title") -> dict:
        return {dimension: sorted(values) for dimension, values in related_rules.tag({field: text}).items() if values}

    def related(self, **fields) -> list[str]:
        return [row["case_id"] for row in related_rules.match(related_rules.tag(fields), self.cases)["related"]]

    def test_terms_are_whole_words_and_acronyms_keep_their_case(self):
        self.assertEqual(self.tags("Blue-chip stocks rally; palm oil and soil, Indiana"), {})
        self.assertEqual(self.tags("the prc and an entity list"), {})
        self.assertEqual(self.tags("The PRC Entity List"), {"instrument": ["export-controls"], "geography": ["prc"]})
        self.assertEqual(self.tags("Chips, chipmakers and oil refiners"), {"sector": ["oil", "semiconductors"]})
        self.assertEqual(self.tags("People’s Republic of China"), {"geography": ["prc"]})

    def test_a_related_case_needs_its_instrument_and_its_sector_or_country(self):
        self.assertEqual(self.related(title="New export controls on chips"), [BIS])
        self.assertEqual(self.related(title="New export controls on China"), [BIS])
        self.assertEqual(self.related(title="Treasury sanctions Venezuelan officials"), [OFAC])
        self.assertEqual(self.related(title="New export controls announced"), [])  # Instrument only.
        self.assertEqual(self.related(title="China's chip output rises"), [])  # Sector and country, no instrument.
        self.assertEqual(self.related(title="The Bureau of Industry and Security hires staff"), [])  # Agency only.

    def test_overlaps_are_listed_with_what_is_missing(self):
        result = related_rules.match(related_rules.tag({"title": "Crude oil prices rose"}), self.cases)
        self.assertEqual(result["related"], [])
        self.assertEqual([(row["case_id"], row["missing"]) for row in result["overlaps"]], [(OFAC, "instrument")])
        result = related_rules.match(related_rules.tag({"title": "New export controls announced"}), self.cases)
        self.assertEqual([(row["case_id"], row["missing"]) for row in result["overlaps"]],
                         [(BIS, "sector_or_country")])

    def test_differences_come_only_from_what_the_event_names(self):
        (row,) = related_rules.match(related_rules.tag({"title": "Sanctions on Russian oil and Iranian oil"}),
                                     self.cases)["related"]
        self.assertEqual([(item["dimension"], item["kind"], item["event"]) for item in row["differs"]],
                         [("geography", "different", ["Iran", "Russia"])])
        self.assertEqual([item["dimension"] for item in row["unknown"]], ["agency"])
        (row,) = related_rules.match(related_rules.tag({"title": "Export controls on chips for China and Russia"}),
                                     self.cases)["related"]
        self.assertEqual([(item["kind"], item["event"]) for item in row["differs"]], [("also_names", ["Russia"])])

    def test_a_match_found_only_in_a_hint_says_so(self):
        found = related_rules.tag({"title": "Members review measures", "hint_summary": "Export controls on chips."})
        (row,) = related_rules.match(found, self.cases)["related"]
        self.assertTrue(row["rests_on_hint"])
        found = related_rules.tag({"title": "Export controls on chips", "hint_summary": "Export controls on chips."})
        self.assertFalse(related_rules.match(found, self.cases)["related"][0]["rests_on_hint"])

    def test_related_cases_are_ordered_by_shared_dimensions(self):
        result = related_rules.match(related_rules.tag({"title": "Sanctions and export controls on Venezuelan oil "
                                                                  "and Chinese chips by the Commerce Department"}),
                                     self.cases)
        self.assertEqual([(row["case_id"], row["shared_dimensions"]) for row in result["related"]],
                         [(BIS, 4), (OFAC, 3)])


# ---------------------------------------------------------------- one event

class EventMatchTests(Harness):
    def test_reads_write_nothing_and_the_explicit_check_is_stored_once(self):
        item = self.id(CONTROLS, "synth_01")
        page = self.view("inbox", item)
        self.assertEqual((page["state"], page["match"], page["written"], page["provider_called"]),
                         ("not_checked", None, False, False))
        self.assertEqual(self.stored(), [])
        first = self.find("inbox", item)
        self.assertEqual((first["created"], first["related"], first["overlaps"]), (True, 1, 0))
        again = self.find("inbox", item, status=200)
        self.assertEqual((again["created"], again["match_id"]), (False, first["match_id"]))
        (path,) = self.stored()
        self.assertEqual(path.stem, first["match_id"])
        self.assertFalse(os.stat(path).st_mode & stat.S_IWRITE)
        self.assertEqual(self.view("inbox", item)["match"]["computed_at"], CLOCK.isoformat())

    def test_a_useful_match_explains_what_is_shared_what_differs_and_what_is_unknown(self):
        match = self.checked("inbox", self.id(CONTROLS, "synth_01"))
        (row,) = match["related"]
        self.assertEqual((row["case_id"], row["shared_dimensions"], row["rests_on_hint"]), (BIS, 2, False))
        shared = {item["dimension"]: item["text"] for item in row["shared"]}
        self.assertIn("“export controls” in the entry's title", shared["instrument"])
        self.assertIn("“chips” in the feed excerpt", shared["sector"])
        self.assertEqual(row["differs"], [])
        self.assertEqual([item["dimension"] for item in row["unknown"]], ["geography", "agency"])
        self.assertIn("names no country or area; whether it concerns China (PRC), as the case does, is unknown",
                      row["unknown"][0]["text"])
        self.assertEqual([point["label"] for point in row["not_compared"]],
                         ["Items covered", "End uses and destinations", "Licensing policy",
                          "Reach beyond U.S.-made items and firms", "Exceptions", "Timing"])
        self.assertIn("The case was announced on October 7, 2022. This event's feed timestamp is Thu, 08 Oct 2026",
                      row["timing"])

    def test_a_different_country_is_stated_as_a_difference(self):
        (row,) = self.checked("inbox", self.id(RUSSIA))["related"]
        self.assertEqual(row["case_id"], OFAC)
        self.assertEqual([item["text"] for item in row["differs"]],
                         ["This event names Russia as its country or area; the case concerns Venezuela."])

    def test_a_shared_topic_alone_is_an_overlap_and_not_a_related_case(self):
        match = self.checked("inbox", self.id(CRUDE))
        self.assertEqual(match["related"], [])
        (overlap,) = match["overlaps"]
        self.assertEqual((overlap["case_id"], overlap["missing"]), (OFAC, "instrument"))
        self.assertIn("names none of the case's policy instruments (Sanctions), so it is not presented as related",
                      overlap["text"])

    def test_an_unrelated_event_has_no_related_case_and_no_overlap(self):
        match = self.checked("inbox", self.id(STATEMENT, "20260916a"))
        self.assertEqual((match["related"], match["overlaps"]), ([], []))

    def test_recurring_titles_are_separate_events_with_their_own_dates(self):
        first, second = self.id(CONTROLS, "synth_01"), self.id(CONTROLS, "synth_02")
        a, b = self.find("inbox", first), self.find("inbox", second)
        self.assertNotEqual(a["match_id"], b["match_id"])
        self.assertEqual(len(self.stored()), 2)
        dates = [self.view("inbox", item)["event"]["date_value"] for item in (first, second)]
        self.assertEqual(dates, ["Thu, 08 Oct 2026 00:00:00 GMT", "Thu, 01 Oct 2026 00:00:00 GMT"])

    def test_missing_context_stays_unknown(self):
        page = self.view("inbox", self.id(OIL_SANCTIONS))
        self.assertEqual([(item["field"], item["present"]) for item in page["event"]["inputs"]],
                         [("title", True), ("excerpt", False)])
        (row,) = self.checked("inbox", self.id(OIL_SANCTIONS))["related"]
        self.assertEqual([item["dimension"] for item in row["unknown"]], ["geography", "agency"])

    def test_a_capture_uses_its_headline_source_text_and_source_address(self):
        capture = self.capture("Commerce adds chipmakers to the Entity List",
                               "https://www.bis.gov/press-release/synthetic-entity-list",
                               "SYNTHETIC: entities located in the People’s Republic of China were added.")
        (row,) = self.checked("capture", capture)["related"]
        self.assertEqual((row["case_id"], row["shared_dimensions"]), (BIS, 4))
        agency = next(item for item in row["shared"] if item["dimension"] == "agency")
        self.assertIn("“www.bis.gov” in the capture's source address", agency["text"])
        none = self.capture(STATEMENT, FED_LINK.format("20260916a"), "SYNTHETIC: the Committee kept rates.", 5)
        self.assertEqual(self.checked("capture", none)["related"], [])

    def test_a_paid_classification_is_a_labelled_hint_and_a_simulated_one_is_never_used(self):
        vague = self.id(VAGUE)
        self.classify(vague, "simulated", "Export controls", "New export controls on chips for China.")
        page = self.view("inbox", vague)
        self.assertIsNone(page["event"]["hint"])
        self.assertEqual(self.checked("inbox", vague)["related"], [])
        self.classify(vague, "paid", "Export controls", "New export controls on chips for China.")
        page = self.view("inbox", vague)
        self.assertEqual(page["state"], "not_checked")  # The hint is part of the identity: a new check is needed.
        self.assertIn("1 earlier check is kept", page["detail"])
        self.assertEqual((page["event"]["hint"]["mode"], page["event"]["hint"]["event_type"]), ("paid", "Export controls"))
        (row,) = self.checked("inbox", vague)["related"]
        self.assertTrue(row["rests_on_hint"])
        self.assertIn("a hint, not a fact", row["hint_note"])
        self.assertTrue(all("(a hint)" in item["text"] for item in row["shared"]))

    def test_a_new_entry_version_or_new_case_content_needs_a_new_check_and_keeps_the_old_one(self):
        item = self.id(CONTROLS, "synth_01")
        self.find("inbox", item)
        triage_before = tree(self.triage)
        self.refresh(feeds("A different excerpt about chips (synthetic)."), datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
        page = self.view("inbox", item)
        self.assertEqual((page["state"], page["kept_records"]), ("not_checked", 1))
        self.find("inbox", item)
        path = self.cases / f"{BIS}.json"
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.write_bytes(path.read_bytes().replace("It does not show what happened afterwards.".encode(),
                                                   "It does not show what came next.".encode(), 1))
        page = self.view("inbox", item)
        self.assertEqual((page["state"], page["kept_records"]), ("not_checked", 2))
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual(tree(self.triage), triage_before)

    def test_a_tampered_record_is_not_shown_and_never_overwritten(self):
        item = self.id(RUSSIA)
        created = self.find("inbox", item)
        (path,) = self.stored()
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["result"]["related"] = []
        path.write_text(json.dumps(record), encoding="utf-8")
        page = self.view("inbox", item)
        self.assertEqual((page["state"], page["match"]), ("problem", None))
        response = self.client.post(f"/api/related-cases/events/inbox/{item}/matches", headers=HEADERS, content=FIND)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["result"]["related"], [])
        self.assertEqual(path.stem, created["match_id"])

    def test_requests_are_refused_before_anything_is_written(self):
        item = self.id(RUSSIA)
        url = f"/api/related-cases/events/inbox/{item}/matches"
        cases = [({**HEADERS, "X-Second-Order-Related": "0"}, FIND, 403),
                 ({**HEADERS, "Origin": "http://evil.example"}, FIND, 403),
                 (HEADERS, json.dumps({"find_related_cases": 1}), 422),
                 (HEADERS, json.dumps({"find_related_cases": True, "extra": 1}), 422),
                 (HEADERS, "not json", 422)]
        for headers, body, status in cases:
            with self.subTest(status=status, body=body):
                self.assertEqual(self.client.post(url, headers=headers, content=body).status_code, status)
        for path in ("/api/related-cases/events/other/x", "/api/related-cases/events/inbox/fed-monetary:00",
                     "/api/related-cases/events/capture/20990101T000000000000Z-000000000000",
                     "/api/related-cases/unknown-case", "/api/related-cases/%2E%2E"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.stored(), [])

    def test_case_routes_serve_both_cases_and_say_when_no_copy_is_here(self):
        listed = self.client.get("/api/related-cases").json()
        self.assertEqual([row["id"] for row in listed["cases"]], [OFAC, BIS])
        page = self.client.get(f"/api/related-cases/{BIS}").json()
        self.assertEqual((page["position"], page["count"], page["previous"]["id"], page["next"]),
                         (2, 2, OFAC, None))
        self.assertEqual(page["source_check"]["state"], "absent")
        self.assertIn("not reviewed by a person", page["interpretation_label"])

    def test_concurrent_checks_store_the_result_once(self):
        item = self.id(CRUDE)
        replies, errors = [], []

        def run():
            try:
                with TestClient(self.client.app, base_url=BASE) as client:
                    replies.append(client.post(f"/api/related-cases/events/inbox/{item}/matches", headers=HEADERS,
                                               content=FIND).json())
            except Exception as exc:  # Reported below.
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for reply_ in replies if reply_["created"]), 1)
        self.assertEqual(len(self.stored()), 1)

    def test_no_network_and_no_model_during_checks_reads_and_restart(self):
        item, capture = self.id(RUSSIA), self.capture(CONTROLS, "https://www.bis.gov/x", "SYNTHETIC chips text.")
        attempts, original = [], socket.socket.connect

        def local_only(sock, address):  # The event loop's own loopback pair is allowed; nothing else.
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        forbidden = AssertionError("Related Cases must not build or send a model request")
        with patch("socket.socket.connect", local_only), \
                patch("socket.getaddrinfo", side_effect=AssertionError("name lookup")), \
                patch("second_order.headline_triage.build_request", side_effect=forbidden), \
                patch("second_order.triage_flow.dispatch", side_effect=forbidden), \
                patch("second_order.event_inbox.refresh", side_effect=forbidden):
            for kind, event_id in (("inbox", item), ("capture", capture)):
                self.find(kind, event_id)
                first = self.view(kind, event_id)
                restarted = self.app()
                self.assertEqual(self.view(kind, event_id, restarted), first)
                self.assertFalse(self.find(kind, event_id, restarted, status=200)["created"])
            self.assertEqual(self.client.get(f"/api/related-cases/{OFAC}").status_code, 200)
        self.assertEqual(attempts, [])
        self.assertEqual(len(self.stored()), 2)


class FrontendFixtureTests(Harness):
    """The client tests read these captured views; they are rewritten only with the explicit opt-in."""

    def compare(self, name: str, served: dict) -> None:
        path = FIXTURES / name
        text = json.dumps(served, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        if os.environ.get(WRITE_FIXTURES) == "1":
            path.write_bytes(text.encode("utf-8"))
        else:
            self.assertEqual(served, json.loads(path.read_text(encoding="utf-8")),
                             f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                             "-s tests -p test_related_cases.py")

    def test_served_views_match_the_committed_frontend_fixtures(self):
        self.compare("related-cases-collection.json", self.client.get("/api/related-cases").json())
        self.compare("related-case-bis.json", self.client.get(f"/api/related-cases/{BIS}").json())
        self.compare("related-case-ofac.json", self.client.get(f"/api/related-cases/{OFAC}").json())
        controls = self.id(CONTROLS, "synth_01")
        self.compare("related-match-not-checked.json", self.view("inbox", controls))
        self.find("inbox", controls)
        self.compare("related-match-related.json", self.view("inbox", controls))
        self.find("inbox", self.id(CRUDE))
        self.compare("related-match-overlap.json", self.view("inbox", self.id(CRUDE)))


if __name__ == "__main__":
    unittest.main()

"""Related research: navigation from an event to existing case-library content, on SYNTHETIC Event Inbox entries and
captures in temporary folders, against the committed case library and historical cases (read only).

Covers exact-event identity by address and date (never by headline), conflicting dates, generic and reused addresses,
release families against shared publishers, topics against unrelated or generic text, undated and title-only events,
later-case exclusion, provenance labels, deduplication (including cases shown in the historical section), and reads
that write nothing and contact no network or model.
"""
from datetime import date, datetime, timezone
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

from test_event_inbox import (CPI, EIA, EMPSIT, FED, WTO, Network, atom, clock, eia_item, eia_rss, rss, rss_item,
                              wto_item, wto_rss)
from second_order import case_library, event_inbox, event_intake, related_cases, related_research
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
BASE = "http://127.0.0.1:8137"
RELATED_HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Related": "1"}
EV = "https://www.eia.gov/todayinenergy/detail.php?id=68224"
FED_LINK = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{}.htm"
EIA_LINK = "https://www.eia.gov/todayinenergy/detail.php?id={}"
STATEMENT = "Federal Reserve issues FOMC statement"
TITLES = {"ev": "U.S. electricity use for electric vehicles increasing at a slower pace in 2026",
          "winter": "Mixed outlook for energy expenditures this winter",
          "new-england": "New England natural gas prices have been trading near record discounts",
          "generic": "Energy markets update", "undated": "Natural gas production rose",
          "minutes": "Minutes of the Federal Open Market Committee, September 15-16, 2026",
          "discount": "Minutes of the Board's discount rate meetings on July 20 and July 29, 2026",
          "taskforce": "Federal Reserve announces the leadership of its task forces",
          "trade": "Members discuss trade and climate measures"}


def feeds(ev_date: str = "Wed, 30 Sep 2026 09:00:00 EST") -> dict:
    """SYNTHETIC feeds: invented excerpts in the shape of the EIA, Fed and WTO feeds."""
    return {
        FED: [(200, rss([rss_item(1, STATEMENT, FED_LINK.format("20260916a"), pub="Wed, 16 Sep 2026 18:00:00 GMT"),
                         rss_item(2, TITLES["minutes"], FED_LINK.format("20261007a"), pub="Wed, 7 Oct 2026 18:00:00 GMT"),
                         rss_item(3, TITLES["discount"], FED_LINK.format("20260825a"), pub="Tue, 25 Aug 2026 18:00:00 GMT"),
                         rss_item(4, TITLES["taskforce"], FED_LINK.format("20260709a"),
                                  pub="Thu, 9 Jul 2026 19:00:00 GMT")]))],
        EMPSIT: [(200, atom([]))], CPI: [(200, atom([]))],
        EIA: [(200, eia_rss([
            eia_item(1, TITLES["ev"], EV, pub=ev_date,
                     description="Synthetic: electric vehicles consumed more electricity in 2026."),
            eia_item(2, TITLES["winter"], EIA_LINK.format(98001), pub="Wed, 07 Oct 2026 09:00:00 EST",
                     description="Synthetic: lower prices for natural gas will reduce heating expenditures."),
            eia_item(3, TITLES["new-england"], EIA_LINK.format(98002), pub="Wed, 09 Sep 2026 09:00:00 EST",
                     description="Synthetic: natural gas prices in New England fell."),
            eia_item(4, TITLES["generic"], EIA_LINK.format(98003), pub="Thu, 08 Oct 2026 09:00:00 EST",
                     description="Synthetic: energy prices and markets moved."),
            eia_item(5, TITLES["undated"], EIA_LINK.format(98004), pub=None,
                     description="Synthetic: natural gas production rose.")]))],
        WTO: [(200, wto_rss([wto_item(1, TITLES["trade"], description="Synthetic: members shared updates.")]))],
    }


def tree(folder: Path) -> dict:
    found = {}
    if folder.exists():
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                found[path.relative_to(folder).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(),
                                                             path.stat().st_mtime_ns)
    return found


class Harness(unittest.TestCase):
    library = case_library.LIBRARY_DIR

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.inbox, self.intake = self.root / "inbox", self.root / "intake"
        self.refresh(feeds())
        self.client = self.app()
        self.minute = 0

    def refresh(self, answers: dict) -> None:
        event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock(datetime(2026, 10, 9, 9, tzinfo=timezone.utc)))
        view = event_inbox.inbox_view(self.inbox)
        self.items = {item["title"]: item["id"] for item in view["items"] + view["retained"]}

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.intake, self.root / "attempts", inbox=self.inbox, triage=self.root / "triage",
                                       links=self.root / "links", market=self.root / "market", library=self.library,
                                       related_sources=self.root / "sources", related_records=self.root / "related"),
                            base_url=BASE)
        self.addCleanup(client.close)
        return client

    def capture(self, headline: str, link: str, published: str, text: str = "Synthetic source text.") -> str:
        self.minute += 1
        return event_intake.capture_text(headline, link, published, "synthetic-story", text, "claude-sonnet-5-5",
                                         self.intake, lambda: datetime(2026, 10, 9, 9, self.minute,
                                                                       tzinfo=timezone.utc))["capture_id"]

    def research(self, kind: str, event_id: str) -> dict:
        response = self.client.get(f"/api/related-research/events/{kind}/{event_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def links(self, kind: str, event_id: str) -> list[tuple[str, str]]:
        return [(link["relation"], link["target"]["id"]) for link in self.research(kind, event_id)["links"]]


class AddressAndDateTests(unittest.TestCase):
    def test_only_addresses_that_name_one_document_can_identify_an_event(self):
        address = related_research.event_address
        self.assertEqual(address(EV), EV)
        self.assertEqual(address("https://WWW.EIA.GOV/todayinenergy/detail.php?id=68224"), EV)
        self.assertIsNone(address("https://www.eia.gov/todayinenergy/detail.php"))  # The query names the article.
        self.assertIsNone(address("https://www.eia.gov/todayinenergy/detail.php?id=68224&x=1"))
        self.assertIsNone(address("http://www.eia.gov/todayinenergy/detail.php?id=68224"))
        self.assertIsNone(address(EV + "#chart"))
        for generic in ("https://www.eia.gov/todayinenergy/", "https://www.bls.gov/news.release/empsit.nr0.htm",
                        "https://www.bis.gov/news-updates", "https://www.federalreserve.gov/newsevents/pressreleases.htm"):
            with self.subTest(generic=generic):
                self.assertIsNone(address(generic))
        self.assertEqual(address("https://www.bls.gov/news.release/archives/empsit_04042025.htm"),
                         "https://www.bls.gov/news.release/archives/empsit_04042025.htm")

    def test_dates_are_read_as_stated(self):
        self.assertEqual(related_research.stated_date("Wed, 30 Sep 2026  09:00:00 EST"), date(2026, 9, 30))
        self.assertEqual(related_research.stated_date("Thu, 9 Jul 2026 19:00:00 GMT"), date(2026, 7, 9))
        self.assertEqual(related_research.stated_date("2025-09-17T14:00:00-04:00"), date(2025, 9, 17))
        self.assertIsNone(related_research.stated_date("31 Feb 2026"))
        self.assertIsNone(related_research.stated_date(None))

    def test_a_family_needs_the_documents_title_and_the_publishers_release_path(self):
        family = related_research.family_of
        self.assertEqual(family(STATEMENT, FED_LINK.format("20250917a")), ("fomc", "statement"))
        self.assertEqual(family(TITLES["minutes"], FED_LINK.format("20261007a")), ("fomc", "minutes"))
        self.assertIsNone(family(TITLES["discount"], FED_LINK.format("20260825a")))  # Same publisher, no family.
        self.assertIsNone(family("Notes on the FOMC statement", "https://www.bis.gov/press-release/notes"))
        self.assertEqual(family("The Employment Situation — March 2025", "https://www.bls.gov/news.release/empsit.nr0.htm"),
                         ("employment-situation", "release"))

    def test_every_topic_is_tied_to_its_cases_own_text(self):
        with patch.dict(related_research.TOPICS, {"ev-electricity": {**related_research.TOPICS["ev-electricity"],
                                                                     "case": "h8-2026-09-11"}}):
            with self.assertRaises(related_research.ResearchRefused) as caught:
                related_research._targets(case_library.LIBRARY_DIR, related_cases.CASES_DIR, Path("no-sources"))
        self.assertIn("does not state every term group", str(caught.exception))


class IdentityTests(Harness):
    def test_the_same_address_and_date_is_coverage_of_this_event_and_nothing_weaker_repeats_it(self):
        view = self.research("inbox", self.items[TITLES["ev"]])
        (link,) = view["links"]
        self.assertEqual((link["relation"], link["target"]["id"], link["target"]["href"]),
                         ("same_event", "eia-tie-2026-09-30", "/library/eia-tie-2026-09-30"))
        self.assertIn("not a separate source and not a corroboration", link["explanation"])
        self.assertEqual(link["address"], EV)

    def test_a_recurring_title_never_identifies_an_event(self):
        later = self.capture(STATEMENT, FED_LINK.format("20250917a"), "2025-09-17T14:00:00-04:00")
        self.assertEqual(self.links("capture", later), [("release_family", "fomc-2025-06-18")])
        same = self.capture(STATEMENT, FED_LINK.format("20250129a"), "2025-01-29T14:00:00-05:00")
        self.assertEqual(self.links("capture", same), [("same_event", "fomc-2025-01-29")])
        # The library case's own release title and date, at another address: still not the same event.
        lookalike = self.capture(STATEMENT, FED_LINK.format("20250618b"), "2025-06-18T14:00:00-04:00")
        self.assertEqual(self.links("capture", lookalike), [("release_family", "fomc-2025-06-18")])

    def test_conflicting_dates_prevent_the_exact_event_label_and_hold_the_case_back(self):
        self.refresh(feeds(ev_date="Thu, 01 Oct 2026 09:00:00 EST"))
        view = self.research("inbox", self.items[TITLES["ev"]])
        self.assertEqual(view["links"], [])  # Not even as a topic link.
        self.assertIn("the dates disagree", " ".join(view["notes"]))
        shifted = self.capture(STATEMENT, FED_LINK.format("20250129a"), "2025-01-30T14:00:00-05:00")
        self.assertNotIn("fomc-2025-01-29", [target for _, target in self.links("capture", shifted)])

    def test_an_address_used_by_events_with_different_dates_is_not_an_identity(self):
        self.capture("Electric vehicles electricity note", EV, "2026-10-02T09:00:00-04:00")
        view = self.research("inbox", self.items[TITLES["ev"]])
        self.assertEqual(view["links"], [])
        self.assertIn("events at this address: 2026-09-30, 2026-10-02", " ".join(view["notes"]))

    def test_generic_addresses_cannot_identify_an_event(self):
        current = self.capture("The Employment Situation — March 2025", "https://www.bls.gov/news.release/empsit.nr0.htm",
                               "2025-04-04T08:30:00-04:00")
        view = self.research("capture", current)
        self.assertEqual([(link["relation"], link["target"]["id"]) for link in view["links"]],
                         [("release_family", "empsit-2025-04-04")])
        self.assertIn("does not name one document", " ".join(view["notes"]))
        landing = self.capture("Today in Energy", "https://www.eia.gov/todayinenergy/", "2026-09-30T09:00:00-04:00")
        self.assertEqual(self.links("capture", landing), [])


class ReusedAddressTests(Harness):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.library = Path(folder.name) / "library"
        shutil.copytree(case_library.LIBRARY_DIR, self.library)
        path = self.library / "eia-tie-2026-09-25.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        case["source"]["url"] = EV  # Two cases now cite one address.
        case["provenance"]["sources_read"].append(EV)
        path.write_bytes(json.dumps(case, ensure_ascii=False).encode("utf-8"))
        super().setUp()

    def test_an_address_two_cases_cite_identifies_nothing(self):
        view = self.research("inbox", self.items[TITLES["ev"]])
        self.assertEqual(view["links"], [])
        self.assertIn("More than one case cites this event's address", " ".join(view["notes"]))


class FamilyAndTopicTests(Harness):
    def test_a_family_link_states_the_document_and_date_differences(self):
        view = self.research("inbox", self.items[TITLES["minutes"]])
        (link,) = view["links"]
        self.assertEqual((link["relation"], link["target"]["id"]), ("release_family", "fomc-2025-06-18"))
        self.assertEqual(link["family"], {"slug": "fomc", "label": "FOMC communications", "event_document": "minutes",
                                          "case_document": "statement", "more_earlier": 3})
        self.assertIn("Different documents: this event is FOMC meeting minutes, the case an FOMC statement.",
                      link["differences"])
        self.assertIn("about 16 months earlier", " ".join(link["differences"]))
        self.assertEqual(link["unknown"], ["This entry carries only its title, so what this release says is not compared."])

    def test_a_shared_publisher_is_not_a_family(self):
        for title in (TITLES["discount"], TITLES["taskforce"]):
            with self.subTest(title=title):
                self.assertEqual(self.links("inbox", self.items[title]), [])

    def test_a_topic_needs_every_term_group_in_the_events_own_text(self):
        view = self.research("inbox", self.items[TITLES["winter"]])
        (link,) = view["links"]
        self.assertEqual((link["relation"], link["target"]["id"], link["topic"]["slug"]),
                         ("topic", "eia-tie-2026-09-25", "natural-gas-market"))
        self.assertIn("“natural gas” and “prices” in the feed excerpt", link["explanation"])
        self.assertIn("not the same mechanism", link["explanation"])
        for title in (TITLES["generic"], TITLES["trade"]):
            with self.subTest(title=title):
                self.assertEqual(self.links("inbox", self.items[title]), [])

    def test_later_cases_are_not_suggested_and_undated_events_get_no_family_or_topic(self):
        view = self.research("inbox", self.items[TITLES["new-england"]])
        self.assertEqual(view["links"], [])
        self.assertIn("1 later case is not suggested", " ".join(view["notes"]))
        view = self.research("inbox", self.items[TITLES["undated"]])
        self.assertEqual((view["event"]["date"], view["links"]), (None, []))
        self.assertIn("states no date", " ".join(view["notes"]))

    def test_links_say_what_kind_of_content_they_are_and_when_it_was_written(self):
        (link,) = self.research("inbox", self.items[TITLES["ev"]])["links"]
        status = link["status"]
        self.assertEqual(status["labels"], ["Editorial case", "AI-assisted", "Not human-reviewed", "Not research evidence"])
        self.assertTrue(status["written_after_event"])
        self.assertIn("after this event; it was not available when the event happened", status["timing"])
        self.assertIn("no copy retained", status["source"])

    def test_the_cap_keeps_the_strongest_links(self):
        with patch.object(related_research, "MAX_LINKS", 1):
            view = self.research("capture", self.capture(
                "Natural gas and EV electricity", EV, "2026-09-30T09:00:00-04:00",
                "Synthetic: natural gas production rose; oil and gas producers expanded output."))
        self.assertEqual([link["relation"] for link in view["links"]], ["same_event"])
        self.assertIn("2 weaker links are not shown", " ".join(view["notes"]))


class TradeTopicTests(Harness):
    """SYNTHETIC WTO items against the committed WTO entries: same address and listing date, or the topic."""

    def wto_feeds(self) -> dict:
        news = "https://www.wto.org/english/news_e/news26_e/{}.htm"
        return {**feeds(), WTO: [(200, wto_rss([
            wto_item(1, "Synthetic committee news", news.format("envir_28sep26_501_e"),
                     pub="Mon, 28 Sep 2026 00:00:00 GMT", description="Synthetic: a committee met."),
            wto_item(2, "Co-sponsors of sustainability initiative advance work plan", news.format("tessd_02oct26_507_e"),
                     pub="Fri, 02 Oct 2026 00:00:00 GMT",
                     description="Synthetic: co-sponsors of the Trade and Environmental Sustainability Structured "
                                 "Discussions met."),
            wto_item(3, "Co-sponsors of Plastics Dialogue hold technical discussions", news.format("ppesp_01oct26_504_e"),
                     pub="Thu, 01 Oct 2026 00:00:00 GMT", description="Synthetic: trade-related plastics measures."),
            wto_item(4, "Moot court competition kicks off", news.format("disp_29sep26_500_e"),
                     pub="Tue, 29 Sep 2026 00:00:00 GMT", description="Synthetic: webinars are offered."),
            wto_item(5, "Co-sponsors of an earlier dialogue met", news.format("ppesp_20sep26_490_e"),
                     pub="Sun, 20 Sep 2026 00:00:00 GMT", description="Synthetic: plastics dialogue co-sponsors met."),
        ]))]}

    def setUp(self):
        super().setUp()
        self.refresh(self.wto_feeds())

    def test_wto_items_get_the_same_event_or_the_trade_and_environment_topic_with_the_forum_difference(self):
        self.assertEqual(self.links("inbox", self.items["Synthetic committee news"]),
                         [("same_event", "wto-2026-09-28")])
        for title in ("Co-sponsors of sustainability initiative advance work plan",
                      "Co-sponsors of Plastics Dialogue hold technical discussions"):
            with self.subTest(title=title):
                (link,) = self.research("inbox", self.items[title])["links"]
                self.assertEqual((link["relation"], link["target"]["id"], link["topic"]["slug"]),
                                 ("topic", "wto-2026-09-28", "trade-environment-wto"))
                self.assertIn("Different forums: the case covers a meeting of the Committee on Trade and Environment",
                              " ".join(link["differences"]))
                self.assertIn("not the same mechanism", link["explanation"])
        self.assertEqual(self.links("inbox", self.items["Moot court competition kicks off"]), [])
        earlier = self.research("inbox", self.items["Co-sponsors of an earlier dialogue met"])
        self.assertEqual(earlier["links"], [])  # The committee entry is later than this item.
        self.assertIn("1 later case is not suggested", " ".join(earlier["notes"]))


class HistoricalTests(Harness):
    BIS_URL = ("https://www.bis.gov/press-release/commerce-implements-new-export-controls-advanced-computing-"
               "semiconductor-manufacturing-items-peoples")

    def test_a_historical_case_keeps_its_source_check_and_is_not_repeated_below_the_historical_section(self):
        event = self.capture("Commerce implements new export controls on chips for the PRC", self.BIS_URL,
                             "2022-10-07T12:00:00-04:00", "Synthetic: export controls on semiconductors for China.")
        (link,) = self.research("capture", event)["links"]
        self.assertEqual((link["relation"], link["target"]["collection"], link["target"]["href"]),
                         ("same_event", "historical", "/library/historical/bis-2022-10-07"))
        self.assertEqual((link["status"]["source_check"], link["status"]["source"]),
                         ("absent", "Retained copy not on this machine."))
        found = self.client.post(f"/api/related-cases/events/capture/{event}/matches", headers=RELATED_HEADERS,
                                 content=json.dumps({"find_related_cases": True}))
        self.assertEqual(found.json()["related"], 1)
        view = self.research("capture", event)
        self.assertEqual((view["links"], view["shown_in_historical"]), ([], ["bis-2022-10-07"]))


class LocalReadTests(Harness):
    def test_reads_write_nothing_and_contact_no_network_or_model(self):
        capture = self.capture(STATEMENT, FED_LINK.format("20250917a"), "2025-09-17T14:00:00-04:00")
        before = tree(self.root)
        attempts, original = [], socket.socket.connect

        def local_only(sock, address):  # The event loop's own loopback pair is allowed; nothing else.
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        forbidden = AssertionError("Related research must not call a model or refresh a feed")
        with patch("socket.socket.connect", local_only), \
                patch("socket.getaddrinfo", side_effect=AssertionError("name lookup")), \
                patch("second_order.headline_triage.build_request", side_effect=forbidden), \
                patch("second_order.triage_flow.dispatch", side_effect=forbidden), \
                patch("second_order.event_inbox.refresh", side_effect=forbidden):
            for title in self.items:
                self.research("inbox", self.items[title])
            self.research("capture", capture)
        self.assertEqual((attempts, tree(self.root)), ([], before))

    def test_without_an_installed_library_there_is_nothing_to_link_and_that_is_said(self):
        self.library = self.root / "no-library"
        client = self.app()
        response = client.get(f"/api/related-research/events/inbox/{self.items[TITLES['ev']]}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["links"], [])
        self.assertIn("The case library is not installed here", " ".join(response.json()["notes"]))

    def test_there_is_no_write_route_and_unknown_events_are_404(self):
        self.assertEqual(self.client.post(f"/api/related-research/events/inbox/{self.items[TITLES['ev']]}",
                                          headers=RELATED_HEADERS, content="{}").status_code, 405)
        for path in ("/api/related-research/events/other/x", "/api/related-research/events/inbox/fed-monetary:00",
                     "/api/related-research/events/capture/20990101T000000000000Z-000000000000"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


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
                             "-s tests -p test_related_research.py")

    def test_served_views_match_the_committed_frontend_fixtures(self):
        self.compare("related-research-same-event.json", self.research("inbox", self.items[TITLES["ev"]]))
        self.compare("related-research-family.json", self.research("inbox", self.items[TITLES["minutes"]]))
        self.compare("related-research-topic.json", self.research("inbox", self.items[TITLES["winter"]]))
        self.compare("related-research-none.json", self.research("inbox", self.items[TITLES["new-england"]]))


if __name__ == "__main__":
    unittest.main()

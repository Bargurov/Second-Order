"""User news (user-news-view-0.1, news-interests-0.1, user-news-search-0.1) over a SYNTHETIC inbox refreshed through a
simulated network into temporary folders: the user projection of the shared cache, its freshness, publication-time
states, deterministic interest relevance and search, and that reading or searching contacts nothing and writes nothing.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from second_order import publication_import, user_news
from second_order.accounts import AccountsRefused, Identity
from second_order.event_inbox import RETAIN

from news_fakes import fed_link, refreshed, standard_feeds
from test_event_inbox import EIA, FED, WTO, eia_item, eia_rss, rss, rss_item, wto_item, wto_rss

READER = Identity("u-00000000000000aa", "reader-a", "Reader A", "user")
SOURCE_FIELDS = {"source", "label", "publisher", "interest", "kind", "attribution", "catalogue_url", "terms_url",
                 "state", "last_success_at", "last_attempt", "note", "stale", "entries", "importable"}
ENTRY_FIELDS = {"entry_id", "version_sha256", "source", "title", "title_shortened", "excerpt", "excerpt_shortened",
                "excerpt_repeats_title", "link", "published", "first_retrieved_at", "last_retrieved_at", "listing",
                "stale", "topics", "matches_interests", "import", "story_id"}  # story_id: user-api-0.5.


def fingerprint(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()} if folder.exists() else {}


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.folders = publication_import.Folders(inbox=self.root / "event-inbox", imports=self.root / "imports")

    def view(self, interests: list[str] | None = None, scope: str = "all") -> dict:
        return user_news.view(self.folders, READER, interests or [], scope)

    def entry(self, view: dict, title: str) -> dict:
        return next(entry for entry in view["entries"] if entry["title"] == title)


class Projection(Base):
    def test_an_empty_cache_says_nothing_was_retrieved_and_fills_nothing_in(self):
        shown = self.view()
        self.assertEqual(shown["entries"], [])
        self.assertEqual({source["state"] for source in shown["sources"]}, {"never_refreshed"})
        self.assertIn("No source has been retrieved", shown["notes"][0])
        self.assertFalse(self.folders.inbox.exists())  # Reading created nothing.

    def test_sources_carry_freshness_and_a_user_safe_attempt_detail(self):
        refreshed(self.folders.inbox)
        sources = {source["source"]: source for source in self.view()["sources"]}
        self.assertEqual(set(sources), {"fed-monetary", "bls-empsit", "bls-cpi", "eia-todayinenergy", "wto-news"})
        for source in sources.values():
            self.assertEqual(set(source), SOURCE_FIELDS)
        self.assertEqual((sources["fed-monetary"]["state"], sources["fed-monetary"]["stale"],
                          sources["fed-monetary"]["entries"]), ("ok", False, 2))
        self.assertEqual(sources["fed-monetary"]["last_success_at"], "2026-10-14T09:00:01+00:00")
        self.assertEqual(sources["fed-monetary"]["attribution"],
                         "Source: Board of Governors of the Federal Reserve System")
        self.assertEqual(sources["eia-todayinenergy"]["attribution"], "Source: U.S. Energy Information Administration")
        bls = sources["bls-empsit"]
        self.assertEqual((bls["state"], bls["last_success_at"], bls["entries"], bls["last_attempt"]["outcome"]),
                         ("not_requested", None, 0, "not_requested"))
        self.assertIn("contact", bls["last_attempt"]["detail"])
        self.assertNotIn("SECOND_ORDER", bls["last_attempt"]["detail"])  # No operator configuration words.
        self.assertTrue(sources["fed-monetary"]["importable"])
        self.assertFalse(sources["wto-news"]["importable"])

    def test_entries_state_publication_as_the_feed_does_and_never_from_retrieval(self):
        refreshed(self.folders.inbox)
        shown = self.view()
        for entry in shown["entries"]:
            self.assertEqual(set(entry), ENTRY_FIELDS)
            self.assertEqual(entry["listing"], "current")
        fed = self.entry(shown, "Simulated Committee issues synthetic statement")
        self.assertEqual(fed["published"], {"as_stated": "Wed, 16 Sep 2026 18:00:00 GMT", "element": "RSS pubDate",
                                            "state": "stated", "utc": "2026-09-16T18:00:00+00:00",
                                            "date": "2026-09-16", "note": None})
        self.assertEqual(fed["excerpt"], "The Simulated Committee kept the federal funds rate unchanged.")
        self.assertEqual(fed["link"], fed_link(1))
        self.assertEqual(fed["first_retrieved_at"], "2026-10-14T09:00:01+00:00")
        wto = self.entry(shown, "Synthetic trade forecast update")
        self.assertEqual((wto["published"]["state"], wto["published"]["date"], wto["published"]["utc"]),
                         ("date_only", "2026-10-08", None))
        ambiguous = self.entry(shown, "Synthetic electricity use by vehicles")  # 09:00:00 EST in October.
        self.assertEqual((ambiguous["published"]["state"], ambiguous["published"]["utc"]), ("unstated", None))
        self.assertTrue(ambiguous["published"]["note"])
        stated = self.entry(shown, "Synthetic natural gas storage rises")  # EDT in October: unambiguous.
        self.assertEqual(stated["published"]["utc"], "2026-10-07T13:00:00+00:00")
        # Stated instants first, newest first; then the rest.
        utc = [entry["published"]["utc"] for entry in shown["entries"]]
        known = [moment for moment in utc if moment]
        self.assertEqual(known, sorted(known, reverse=True))
        self.assertEqual(utc[:len(known)], known)

    def test_a_failed_refresh_keeps_earlier_entries_marked_stale(self):
        refreshed(self.folders.inbox)
        refreshed(self.folders.inbox, {FED: [(500, b"down", {"content-type": "text/plain"})],
                                       EIA: [(200, eia_rss([]))], WTO: [(200, wto_rss([]))]},
                  at=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
        shown = self.view()
        fed = next(source for source in shown["sources"] if source["source"] == "fed-monetary")
        self.assertEqual((fed["state"], fed["stale"], fed["last_success_at"], fed["last_attempt"]["outcome"]),
                         ("failed", True, "2026-10-14T09:00:01+00:00", "failed"))
        self.assertIn("earlier successful retrieval", fed["last_attempt"]["detail"])
        self.assertTrue(all(entry["stale"] for entry in shown["entries"] if entry["source"] == "fed-monetary"))

    def test_entries_that_leave_a_feed_are_listed_as_retained_with_their_last_retrieval(self):
        refreshed(self.folders.inbox)
        refreshed(self.folders.inbox, standard_feeds(fed_items=[rss_item(1, title="Simulated Committee issues "
                                                                                 "synthetic statement")]),
                  at=datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc))
        retained = self.entry(self.view(), "Synthetic minutes of the Committee")
        self.assertEqual((retained["listing"], retained["last_retrieved_at"]), ("retained", "2026-10-14T09:00:01+00:00"))

    def test_an_unreadable_source_record_is_reported_and_never_repaired(self):
        refreshed(self.folders.inbox)
        record = self.folders.inbox / "fed-monetary.json"
        record.write_bytes(b"{not json")
        shown = self.view()
        fed = next(source for source in shown["sources"] if source["source"] == "fed-monetary")
        self.assertEqual((fed["state"], fed["entries"]), ("unreadable", 0))
        self.assertIn("administrator", fed["note"])
        self.assertEqual(record.read_bytes(), b"{not json")

    def test_reading_contacts_nothing_and_writes_nothing(self):
        network = refreshed(self.folders.inbox)
        requests = len(network.requests)
        before = fingerprint(self.root)
        self.view(["energy"], "interests")
        self.view()
        user_news.search(self.folders, READER, {"query": "synthetic", "interests": None, "sources": None,
                                                "listing": "all"})
        self.assertEqual((len(network.requests), fingerprint(self.root)), (requests, before))


class Interests(Base):
    def test_the_vocabulary_and_its_rule_are_visible_and_validated(self):
        vocabulary = user_news.vocabulary()
        self.assertEqual([row["interest"] for row in vocabulary["interests"]],
                         ["monetary-policy", "employment", "inflation", "energy", "trade", "markets", "technology",
                          "companies"])
        self.assertEqual(vocabulary["vocabulary_version"], "news-interests-0.2")
        # The three publisher interests have no official feed: they are found only by their terms.
        self.assertEqual([row["sources"] for row in vocabulary["interests"][5:]], [[], [], []])
        self.assertEqual(user_news.validate_interests(["trade", "energy"]), ["energy", "trade"])
        self.assertEqual(user_news.validate_interests([]), [])
        for bad in (["energy", "energy"], ["weather"], "energy", [1], None):
            with self.assertRaises(AccountsRefused) as caught:
                user_news.validate_interests(bad)
            self.assertEqual((caught.exception.status, caught.exception.code), (422, "invalid_request"))

    def test_every_inbox_source_has_one_interest(self):
        from second_order.event_inbox import SOURCES
        self.assertEqual(set(user_news.SOURCE_INTEREST), set(SOURCES))

    def test_an_entry_concerns_its_sources_interest_and_any_interest_whose_terms_it_names(self):
        refreshed(self.folders.inbox)
        shown = self.view(["energy"], "interests")
        titles = {entry["title"] for entry in shown["entries"]}
        self.assertEqual(titles, {"Synthetic natural gas storage rises", "Synthetic electricity use by vehicles",
                                  "Synthetic members discuss energy subsidies and tariffs"})
        wto = self.entry(shown, "Synthetic members discuss energy subsidies and tariffs")
        self.assertEqual(wto["topics"], [
            {"interest": "energy", "basis": "terms", "terms": [{"term": "energy", "field": "title"}]},
            {"interest": "trade", "basis": "source", "terms": [{"term": "trade", "field": "excerpt"},
                                                               {"term": "tariffs", "field": "title"}]}])
        fed = self.entry(self.view(["monetary-policy"]), "Simulated Committee issues synthetic statement")
        self.assertEqual(fed["topics"], [{"interest": "monetary-policy", "basis": "source",
                                          "terms": [{"term": "federal funds", "field": "excerpt"}]}])
        self.assertTrue(fed["matches_interests"])

    def test_terms_match_whole_words_only(self):
        refreshed(self.folders.inbox, standard_feeds(wto_items=[wto_item(1, title="Synthetic oilseed and coalition talks",
                                                                         description="Synthetic excerpt.")]))
        entry = self.entry(self.view(), "Synthetic oilseed and coalition talks")
        self.assertEqual([row["interest"] for row in entry["topics"]], ["trade"])  # No "oil" or "coal".

    def test_no_chosen_interest_selects_nothing_and_says_so(self):
        refreshed(self.folders.inbox)
        shown = self.view([], "interests")
        self.assertEqual(shown["entries"], [])
        self.assertIn("No interests are chosen", shown["notes"][0])
        with self.assertRaises(AccountsRefused):
            self.view([], "everything")


class Search(Base):
    def search(self, query: str, **options) -> dict:
        body = {"query": query, "interests": None, "sources": None, "listing": "all"} | options
        return user_news.search(self.folders, READER, body)

    def test_every_word_must_appear_as_a_whole_word_in_title_or_excerpt(self):
        refreshed(self.folders.inbox)
        self.assertEqual([entry["title"] for entry in self.search("federal FUNDS")["entries"]],
                         ["Simulated Committee issues synthetic statement"])
        self.assertEqual(self.search("fund")["entries"], [])
        found = self.search("synthetic")
        self.assertEqual((found["search"]["matched"], found["search"]["shown"]), (6, 6))
        self.assertEqual(found["search"]["words"], ["synthetic"])

    def test_sources_interests_and_listing_narrow_the_search(self):
        refreshed(self.folders.inbox)
        self.assertEqual({entry["source"] for entry in self.search("synthetic", sources=["wto-news"])["entries"]},
                         {"wto-news"})
        self.assertEqual(len(self.search("synthetic", interests=["energy"])["entries"]), 3)
        refreshed(self.folders.inbox, standard_feeds(fed_items=[]), at=datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertEqual(self.search("minutes", listing="current")["entries"], [])
        self.assertEqual(self.search("minutes")["entries"][0]["listing"], "retained")

    def test_results_are_limited_and_counted(self):
        many = [rss_item(n, title=f"Synthetic common release {n}", link=f"https://www.federalreserve.gov/newsevents/"
                         f"pressreleases/monetary2026{n:04d}a.htm") for n in range(RETAIN)]
        refreshed(self.folders.inbox, standard_feeds(
            fed_items=many, eia_items=[eia_item(n, title=f"Synthetic common article {n}") for n in range(RETAIN)],
            wto_items=[wto_item(n, title=f"Synthetic common news {n}") for n in range(RETAIN)]))
        found = self.search("common")
        self.assertEqual((found["search"]["matched"], found["search"]["shown"], len(found["entries"])),
                         (3 * RETAIN, user_news.MAX_RESULTS, user_news.MAX_RESULTS))

    def test_a_malformed_search_is_refused(self):
        refreshed(self.folders.inbox)
        for body in ({"query": "", "interests": None, "sources": None, "listing": "all"},
                     {"query": "?!", "interests": None, "sources": None, "listing": "all"},
                     {"query": "a b c d e f g h i", "interests": None, "sources": None, "listing": "all"},
                     {"query": "x" * 201, "interests": None, "sources": None, "listing": "all"},
                     {"query": "rate", "interests": None, "sources": ["nowhere"], "listing": "all"},
                     {"query": "rate", "interests": None, "sources": [], "listing": "all"},
                     {"query": "rate", "interests": None, "sources": None, "listing": "some"},
                     {"query": "rate", "interests": None, "sources": None},
                     {"query": "rate", "interests": None, "sources": None, "listing": "all", "user_id": "x"}):
            with self.assertRaises(AccountsRefused) as caught:
                user_news.search(self.folders, READER, body)
            self.assertEqual((caught.exception.status, caught.exception.code), (422, "invalid_request"), body)


if __name__ == "__main__":
    unittest.main()

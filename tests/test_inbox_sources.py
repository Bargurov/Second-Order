"""Event Inbox energy and trade sources: EIA Today in Energy and WTO latest news, beside the three release feeds.

The two feeds are fixed, verified entries in the same allowlist; what is specific to them is narrow and tested here:
EIA alone may declare ISO-8859-1, and WTO alone stamps entries with a 00:00:00 placeholder time (date_only). Zone
names that contradict their date's daylight-saving status are ambiguous for every source. Each source is requested
once per refresh, a failure keeps that source's last good entries without touching the others, entries leaving a feed
stay as retained history, and adding the sources leaves the earlier entries' triage fingerprints and results alone.

SYNTHETIC feed bytes only, shaped like the publishers' real feeds, through an injected MockTransport, in temporary
folders; triage uses the fake provider. Nothing here reaches a network or touches data/.
"""
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit
import unittest

import httpx

from test_event_inbox import (ALL, EIA, WTO, Folder, Network, clock, eia_item, eia_rss, fingerprint, rss, rss_item,
                              standard, wto_item, wto_rss)
from test_headline_triage import Provider, Triage, feeds
from second_order import event_inbox
from second_order.event_inbox import SOURCES, FeedRejected, feed_timestamp, inbox_view, parse_feed, refresh
from second_order.headline_triage import fingerprint as entry_fingerprint, snapshot_item

EIA_SOURCE, WTO_SOURCE, FED_SOURCE = SOURCES["eia-todayinenergy"], SOURCES["wto-news"], SOURCES["fed-monetary"]
DAY_ONE, DAY_TWO, DAY_THREE = (datetime(2026, 10, day, 9, 0, tzinfo=timezone.utc) for day in (8, 9, 10))


class SourceListTests(unittest.TestCase):
    def test_the_allowlist_is_the_five_verified_feeds_with_their_kinds_and_credits(self):
        self.assertEqual(list(SOURCES), ["fed-monetary", "bls-empsit", "bls-cpi", "eia-todayinenergy", "wto-news"])
        self.assertEqual(event_inbox.ALLOWED_URLS, frozenset(ALL))
        self.assertEqual((EIA, WTO), ("https://www.eia.gov/rss/todayinenergy.xml",
                                      "https://www.wto.org/library/rss/latest_news_e.xml"))
        self.assertEqual({key: (source.category, source.kind) for key, source in SOURCES.items()}, {
            "fed-monetary": ("Monetary policy", "Policy announcement"),
            "bls-empsit": ("Employment", "Statistical release"), "bls-cpi": ("Inflation", "Statistical release"),
            "eia-todayinenergy": ("Energy", "Analysis article"), "wto-news": ("International trade", "News announcement")})
        self.assertEqual((EIA_SOURCE.attribution, WTO_SOURCE.attribution),
                         ("Source: U.S. Energy Information Administration", "WTO news"))
        for source in SOURCES.values():
            with self.subTest(source.key):
                for url in (source.feed_url, source.catalogue_url, source.terms_url):
                    self.assertEqual((urlsplit(url).scheme, urlsplit(url).hostname), ("https", source.link_host))
                # A credit is stated only where the publisher's reuse terms were checked and ask for one.
                self.assertEqual(bool(source.attribution), source in (EIA_SOURCE, WTO_SOURCE))
                # Only EIA may declare ISO-8859-1 and only WTO has placeholder times: nothing is relaxed elsewhere.
                self.assertEqual(source.encodings, ("utf-8", "iso-8859-1") if source is EIA_SOURCE else ("utf-8",))
                self.assertEqual(source.date_only, source is WTO_SOURCE)
                self.assertEqual(source.contact_required, source.key.startswith("bls-"))


class EnergyFeedTests(unittest.TestCase):
    def test_an_iso_8859_1_feed_is_read_as_declared_with_its_text_preserved(self):
        parsed = parse_feed(eia_rss([eia_item(1, title="Hydro-Québec exports fell", description="Café &amp; more"),
                                     eia_item(2)]), EIA_SOURCE)
        first, second = parsed["items"]
        self.assertEqual((first["title"], first["excerpt"]), ("Hydro-Québec exports fell", "Café & more"))
        self.assertEqual((first["identity"], first["link"]),  # No guid: the link is the identity, as for the real feed.
                         ("https://www.eia.gov/todayinenergy/detail.php?id=90001",) * 2)
        self.assertTrue(second["id"].startswith("eia-todayinenergy:"))
        self.assertEqual(parse_feed(rss([]), EIA_SOURCE)["items"], [])  # UTF-8 stays accepted for EIA too.

    def test_iso_8859_1_is_accepted_for_eia_alone_and_nothing_else_is_guessed(self):
        latin = eia_rss([eia_item(1, title="Québec")])
        for source in (FED_SOURCE, SOURCES["bls-cpi"], WTO_SOURCE):
            with self.subTest(source.key), self.assertRaisesRegex(FeedRejected, "only UTF-8 is accepted"):
                parse_feed(latin, source)
        refused = {
            "Windows-1252": latin.replace(b"ISO-8859-1", b"windows-1252"),
            "an unknown name": latin.replace(b"ISO-8859-1", b"x-unknown-charset"),
            "UTF-16": latin.replace(b"ISO-8859-1", b"UTF-16"),
            "a UTF-8 byte-order mark with ISO-8859-1": b"\xef\xbb\xbf" + latin,
            "UTF-8 declared, Latin-1 bytes": latin.replace(b"ISO-8859-1", b"UTF-8"),
        }
        for name, data in refused.items():
            with self.subTest(name), self.assertRaises(FeedRejected):
                parse_feed(data, EIA_SOURCE)
        self.assertEqual(parse_feed(latin.replace(b"ISO-8859-1", b"iso-8859-1"), EIA_SOURCE)["items"][0]["title"],
                         "Québec")

    def test_bytes_iso_8859_1_does_not_print_skip_only_that_entry(self):
        """0x92 is a curly apostrophe in Windows-1252 but a control character in ISO-8859-1: the headline is not
        guessed and not silently shortened; the entry is skipped and counted, the others kept."""
        data = eia_rss([eia_item(1), eia_item(2, title="EIA\x92s outlook"), eia_item(3, description="Price \x96 up")])
        parsed = parse_feed(data, EIA_SOURCE)
        self.assertEqual(([item["position"] for item in parsed["items"]], parsed["skipped_count"]), ([1], 2))
        self.assertTrue(all("0x80 to 0x9F" in entry["reason"] for entry in parsed["skipped"]))

    def test_unusable_energy_links_are_skipped_and_counted(self):
        links = ["http://www.eia.gov/todayinenergy/detail.php?id=1", "https://eia.gov/todayinenergy/detail.php?id=2",
                 "https://www.eia.gov/", "https://www.eia.gov.example.org/x.php", "https://www.eia.gov:8443/x.php",
                 "javascript:alert(1)", "https://www.eia.gov/today in energy", "", "/todayinenergy/detail.php?id=3",
                 "https://www.wto.org/english/news_e/x.htm"]
        parsed = parse_feed(eia_rss([eia_item(n, link=link) for n, link in enumerate(links)] + [eia_item(99)]),
                            EIA_SOURCE)
        self.assertEqual(([item["link"] for item in parsed["items"]], parsed["skipped_count"]),
                         (["https://www.eia.gov/todayinenergy/detail.php?id=90099"], len(links)))

    def test_eastern_standard_time_on_a_daylight_saving_date_is_ambiguous(self):
        """The real feed stamps every article 09:00:00 EST, in summer too; EST then contradicts the date."""
        summer = parse_feed(eia_rss([eia_item(1)]), EIA_SOURCE)["items"][0]["feed_timestamp"]
        self.assertEqual((summer["raw"], summer["origin"], summer["instant_utc"], summer["suggestion"]),
                         ("Wed, 07 Oct 2026  09:00:00 EST", "RSS pubDate", None, None))
        self.assertIn("names EST (UTC-05:00), but US Eastern time was UTC-04:00", summer["problem"])
        winter = parse_feed(eia_rss([eia_item(1, pub="Wed, 07 Jan 2026  09:00:00 EST")]), EIA_SOURCE)["items"][0]
        self.assertEqual((winter["feed_timestamp"]["instant_utc"], winter["feed_timestamp"]["suggestion"]),
                         ("2026-01-07T14:00:00+00:00",
                          {"date": "2026-01-07", "time": "09:00:00", "offset": "-05:00", "dropped_fraction": None}))


class TradeFeedTests(unittest.TestCase):
    def test_a_midnight_placeholder_gives_a_date_and_no_time(self):
        item = parse_feed(wto_rss([wto_item(1)]), WTO_SOURCE)["items"][0]
        stamp = item["feed_timestamp"]
        self.assertEqual((stamp["raw"], stamp["origin"], stamp["instant_utc"], stamp["suggestion"]),
                         ("Thu, 08 Oct 2026 00:00:00 GMT", "RSS pubDate", None, None))
        self.assertIn("the date 2026-10-08 with a 00:00:00 placeholder time", stamp["problem"])
        timed = parse_feed(wto_rss([wto_item(1, pub="Thu, 08 Oct 2026 13:01:03 GMT")]), WTO_SOURCE)["items"][0]
        self.assertEqual(timed["feed_timestamp"]["suggestion"],
                         {"date": "2026-10-08", "time": "13:01:03", "offset": "+00:00", "dropped_fraction": None})
        # The placeholder rule is WTO's alone: a midnight time from another source is what that source states.
        fed = parse_feed(rss([rss_item(1, pub="Thu, 08 Oct 2026 00:00:00 GMT")]), FED_SOURCE)["items"][0]
        self.assertEqual(fed["feed_timestamp"]["suggestion"]["time"], "00:00:00")
        self.assertEqual(feed_timestamp("2026-10-08T00:00:00.5Z", "Atom published", False, date_only=True)
                         ["suggestion"]["time"], "00:00:00")  # Not exactly midnight: a stated time.

    def test_only_the_excerpt_is_kept_never_the_full_article_content(self):
        item = parse_feed(wto_rss([wto_item(1, description="<b>Members</b> agreed.", content="<p>SECRET-BODY</p>")]),
                          WTO_SOURCE)["items"][0]
        self.assertEqual((item["title"], item["excerpt"], item["identity"]),
                         ("Synthetic trade news 1", "Members agreed.",
                          "https://www.wto.org/english/news_e/news26_e/synth_01oct26_e.htm"))
        self.assertNotIn("SECRET-BODY", json.dumps(item))
        self.assertIsNone(parse_feed(wto_rss([wto_item(1, description=None)]), WTO_SOURCE)["items"][0]["excerpt"])

    def test_unusable_trade_links_and_ambiguous_timestamps_are_handled_per_entry(self):
        links = ["http://www.wto.org/english/news_e/news26_e/a.htm", "https://wto.org/english/news_e/b.htm",
                 "https://www.wto.org", "https://docs.wto.org/c.htm", "https://www.wto.org/d e.htm"]
        parsed = parse_feed(wto_rss([wto_item(n, link=link, guid=f"g{n}") for n, link in enumerate(links)] +
                                    [wto_item(7, pub="Fri, 08 Oct 2026 00:00:00 GMT"), wto_item(8, pub=None),
                                     wto_item(9, pub="8 October 2026")]), WTO_SOURCE)
        self.assertEqual(parsed["skipped_count"], len(links))
        problems = [item["feed_timestamp"]["problem"] for item in parsed["items"]]
        self.assertEqual([item["feed_timestamp"]["suggestion"] for item in parsed["items"]], [None] * 3)
        self.assertIn("names Fri", problems[0])  # The weekday contradicts the date: not even a date is offered.
        self.assertIn("no timestamp", problems[1])
        self.assertIn("could not be read", problems[2])


class ZoneNameTests(unittest.TestCase):
    def test_us_zone_names_must_match_their_regions_daylight_saving_status(self):
        cases = {
            "Wed, 07 Oct 2026 14:00:00 EDT": "-04:00", "Wed, 07 Jan 2026 14:00:00 EDT": None,
            "Wed, 07 Jan 2026 14:00:00 EST": "-05:00", "Tue, 07 Jul 2026 14:00:00 CST": None,
            "Tue, 07 Jul 2026 14:00:00 CDT": "-05:00", "Tue, 07 Jul 2026 14:00:00 PDT": "-07:00",
            "Wed, 07 Jan 2026 14:00:00 PDT": None, "Wed, 07 Jan 2026 14:00:00 MDT": None,
            "Tue, 07 Jul 2026 14:00:00 MST": "-07:00",  # Arizona keeps MST all year: not a contradiction.
            "Sun, 08 Mar 2026 01:30:00 EST": "-05:00", "Sun, 08 Mar 2026 03:30:00 EST": None,  # The spring change.
            "Sun, 01 Nov 2026 01:30:00 EDT": "-04:00", "Sun, 01 Nov 2026 01:30:00 EST": "-05:00",  # The repeated hour.
            "Wed, 07 Oct 2026 14:00:00 GMT": "+00:00", "Wed, 07 Oct 2026 14:00:00 -0500": "-05:00",  # Not checked.
        }
        for raw, offset in cases.items():
            with self.subTest(raw):
                result = feed_timestamp(raw, "RSS pubDate", rfc822=True)
                self.assertEqual(result["suggestion"]["offset"] if result["suggestion"] else None, offset)
                if offset is None:
                    self.assertEqual(result["instant_utc"], None)
                    self.assertIn("contradicts the date", result["problem"])


class RefreshTests(Folder):
    def answers(self, eia: list[str], wto: list[str] | None, **changes) -> dict:
        return {**standard(), EIA: [(200, eia_rss(eia))], WTO: [(200, wto_rss(wto or []))], **changes}

    def refresh(self, answers: dict, when: datetime) -> tuple[dict, Network]:
        network = Network(answers)
        return refresh(self.inbox, network.fetcher(), clock(when)), network

    def entries(self, view: dict, key: str, history: bool = False) -> dict:
        return {item["title"]: item for item in view["retained" if history else "items"] if item["source"] == key}

    def test_the_view_states_each_sources_kind_and_credit_on_the_source_and_its_entries(self):
        view, _ = self.refresh(self.answers([eia_item(1)], [wto_item(1)]), DAY_ONE)
        sources = {source["key"]: source for source in view["sources"]}
        self.assertEqual((sources["wto-news"]["kind"], sources["wto-news"]["attribution"]), ("News announcement", "WTO news"))
        self.assertEqual({item["source"] for item in view["items"]}, set(SOURCES))
        for item in view["items"]:
            source = SOURCES[item["source"]]
            self.assertEqual((item["publisher"], item["category"], item["kind"], item["attribution"]),
                             (source.publisher, source.category, source.kind, source.attribution))

    def test_each_feed_once_and_a_failed_source_keeps_its_entries_without_blocking_the_others(self):
        first, _ = self.refresh(self.answers([eia_item(1)], [wto_item(1), wto_item(2)]), DAY_ONE)
        before = json.loads((self.inbox / "wto-news.json").read_text(encoding="utf-8"))["last_success"]
        for failure in ((503, b"busy", {"content-type": "text/plain"}), httpx.ConnectTimeout("simulated"),
                        (200, b"<html>blocked</html>", {"content-type": "text/html"}),
                        (302, b"", {"location": "https://www.wto.org/elsewhere.xml"})):
            with self.subTest(failure=failure if isinstance(failure, Exception) else failure[0]):
                view, network = self.refresh(self.answers([eia_item(1), eia_item(3)], None, **{WTO: [failure]}),
                                             DAY_TWO)
                self.assertEqual(network.urls(), ALL)  # Each feed once; the failure was not retried or redirected.
                states = {source["key"]: source["state"] for source in view["sources"]}
                self.assertEqual(states, {"fed-monetary": "ok", "bls-empsit": "ok", "bls-cpi": "ok",
                                          "eia-todayinenergy": "ok", "wto-news": "failed"})
                trade = self.entries(view, "wto-news")
                self.assertEqual((set(trade), {item["stale"] for item in trade.values()}),
                                 ({"Synthetic trade news 1", "Synthetic trade news 2"}, {True}))
                self.assertEqual({item["id"] for item in trade.values()},
                                 {item["id"] for item in first["items"] if item["source"] == "wto-news"})
                self.assertEqual(set(self.entries(view, "eia-todayinenergy")),
                                 {"Synthetic energy article 1", "Synthetic energy article 3"})
                self.assertEqual(json.loads((self.inbox / "wto-news.json").read_text(encoding="utf-8"))["last_success"],
                                 before)

    def test_departed_entries_stay_as_retained_history_and_unchanged_refreshes_add_no_version(self):
        self.refresh(self.answers([eia_item(1), eia_item(2)], [wto_item(1)]), DAY_ONE)
        unchanged, _ = self.refresh(self.answers([eia_item(1), eia_item(2)], [wto_item(1)]), DAY_TWO)
        sources = {source["key"]: source for source in unchanged["sources"]}
        self.assertEqual((sources["eia-todayinenergy"]["archive"]["versions"], sources["wto-news"]["archive"]["versions"]),
                         (2, 1))  # A second retrieval of the same content is not a new version.
        self.assertEqual(self.entries(unchanged, "eia-todayinenergy")["Synthetic energy article 1"]["first_seen_at"],
                         "2026-10-08T09:00:07+00:00")
        later, _ = self.refresh(self.answers([eia_item(2, description="A revised energy excerpt.")], []), DAY_THREE)
        kept = self.entries(later, "eia-todayinenergy", history=True)
        self.assertEqual((set(kept), kept["Synthetic energy article 1"]["last_seen_at"]),
                         ({"Synthetic energy article 1"}, "2026-10-09T09:00:07+00:00"))
        self.assertEqual(set(self.entries(later, "wto-news", history=True)), {"Synthetic trade news 1"})
        sources = {source["key"]: source for source in later["sources"]}
        self.assertEqual(sources["eia-todayinenergy"]["archive"],
                         {"state": "ok", "problem": None, "entries": 2, "versions": 3, "retained": 1})
        self.assertEqual(self.entries(later, "eia-todayinenergy")["Synthetic energy article 2"]["excerpt"],
                         "A revised energy excerpt.")
        before = fingerprint(self.inbox)
        for _ in range(3):  # Reading, as filtering and reopening do, writes nothing and requests nothing.
            self.assertEqual(inbox_view(self.inbox)["retained"], later["retained"])
        self.assertEqual(fingerprint(self.inbox), before)


class EnergyTradeTriageTests(Triage):
    """Triage over the new sources: the earlier entries keep their fingerprints and results; nothing crosses
    publishers; date-only entries follow the existing missing-date rule for their own publisher."""

    def with_sources(self, eia: list[str], wto: list[str], **changes) -> dict:
        return {**feeds(), EIA: [(200, eia_rss(eia))], WTO: [(200, wto_rss(wto))], **changes}

    def test_adding_the_sources_keeps_earlier_fingerprints_and_results(self):
        provider = Provider()
        earlier = [item["id"] for item in self.items]
        prints = {item["id"]: entry_fingerprint(snapshot_item(item)) for item in self.items}
        self.process(*earlier, provider=provider)
        network = self.refresh(self.with_sources([eia_item(1), eia_item(2)], [wto_item(1), wto_item(2)]), DAY_TWO)
        self.assertEqual(network.urls(), ALL)
        now = {item["id"]: entry_fingerprint(snapshot_item(item)) for item in self.items if item["id"] in prints}
        self.assertEqual(now, prints)
        again = self.view(*earlier)
        self.assertEqual(({row["status"] for row in again["items"]}, again["plan"]["requests"], len(provider.requests)),
                         ({"reuse"}, 0, 1))

    def test_pairs_never_cross_publishers_and_date_only_entries_compare_within_their_own(self):
        provider = Provider()
        self.refresh(self.with_sources([eia_item(1)], [wto_item(1), wto_item(2)]), DAY_TWO)
        energy = self.id("Synthetic energy article 1")
        first, second = self.id("Synthetic trade news 1"), self.id("Synthetic trade news 2")
        statement = next(item["id"] for item in self.items if item["source"] == "fed-monetary")
        mixed = self.view(energy, first, statement)
        self.assertEqual((mixed["plan"]["pairs"]["candidates"], mixed["plan"]["context"]), (0, []))
        trade = self.view(first, second)
        self.assertEqual((trade["plan"]["pairs"]["candidates"], len(trade["plan"]["pairs"]["needed"])), (1, 1))
        self.process(first, second, provider=provider)
        self.assertEqual([sorted(ids) for ids in provider.sent_entries()], [sorted([first, second])])
        # A failed trade refresh keeps both entries, so their results are reused with no new work.
        self.refresh(self.with_sources([eia_item(1)], [], **{WTO: [(503, b"busy", {"content-type": "text/plain"})]}),
                     DAY_THREE)
        kept = self.view(first, second)
        self.assertEqual(({row["status"] for row in kept["items"]}, kept["plan"]["requests"],
                          kept["plan"]["pairs"]["compared"]), ({"reuse"}, 0, 1))
        # An entry that leaves the feed is still selectable from retained history, with its result.
        self.refresh(self.with_sources([eia_item(1)], [wto_item(2)]), datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc))
        departed = self.view(first, second)
        self.assertEqual({row["input"]["id"]: (row["status"], row["location"]) for row in departed["items"]},
                         {first: ("reuse", "retained"), second: ("reuse", "current")})
        self.assertEqual((departed["plan"]["requests"], len(provider.requests)), (0, 1))


if __name__ == "__main__":
    unittest.main()

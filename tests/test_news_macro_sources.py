"""The two public macro feeds use the existing bounded explicit refresh. All response content is SYNTHETIC."""
from pathlib import Path
import tempfile
import unittest

from news_desk_fakes import Feeds, START, item, rss
from second_order import event_inbox, news_feeds, news_registry


class MacroSources(unittest.TestCase):
    def test_sources_are_public_official_material_with_a_credit_and_no_implicit_relevance(self):
        for key in ("rba-releases", "census-indicators"):
            source = news_registry.PUBLISHERS[key]
            self.assertEqual((source.role, source.material, source.status), ("official", "permitted", "connected"))
            self.assertIsNone(source.interest)  # A publisher never establishes the economic relevance of an entry.
            self.assertFalse(source.feed.contact_required)
            self.assertFalse(source.feed.keep_raw)
            self.assertTrue(source.material_basis and source.attribution)

    def test_refresh_requests_each_feed_once_keeps_its_dates_and_reads_never_fetch(self):
        sources = [news_registry.PUBLISHERS[key] for key in ("rba-releases", "census-indicators")]
        answers = {source.feed.feed_url: (200, rss([item(source.feed.link_host, source.key,
                    "Synthetic economic release", START, "Synthetic reported output rose 1 percent.")]))
                   for source in sources}
        network = Feeds(answers)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            view = news_feeds.refresh(folder, news_feeds.fetcher_for(sources, network.transport()), sources,
                                      lambda: START)
            self.assertEqual(len(network.requests), 2)
            self.assertEqual(len(view["items"]), 2)
            records = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
            again = news_feeds.feed_view(folder, sources)
            self.assertEqual(len(network.requests), 2)
            self.assertEqual(again["items"], view["items"])
            self.assertEqual({path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}, records)

    def test_an_off_host_link_is_rejected_and_beas_blocked_feed_stays_disconnected(self):
        source = news_registry.RBA_RELEASES
        good = rss([item(source.link_host, "gdp", "Synthetic GDP", START, "Synthetic release.")])
        parsed = event_inbox.parse_feed(good, source)
        self.assertEqual(len(parsed["items"]), 1)
        bad = rss([item("example.invalid", "gdp", "Synthetic GDP", START, "Synthetic release.")])
        self.assertEqual(event_inbox.parse_feed(bad, source)["items"], [])
        self.assertNotIn("bea-releases", news_registry.PUBLISHERS)
        self.assertIsNone(news_registry.PUBLISHERS["bea"].feed)
        self.assertEqual(news_registry.PUBLISHERS["bea"].status, "not_connected")

"""The official publishers of news-registry-0.3 over SYNTHETIC feeds at their registered addresses (answered only by a
simulated network): an RSS 1.0 feed is read, and a feed whose publisher asks for the operator's contact is requested
only with one, which then goes in the User-Agent. Nothing reaches a network."""
import tempfile
import unittest
from pathlib import Path

import httpx

from second_order import event_inbox, news_feeds, news_registry

RSS1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
 <channel rdf:about="https://www.bankofcanada.ca/"><title>SYNTHETIC press releases</title></channel>
 <item rdf:about="https://www.bankofcanada.ca/2026/10/synthetic-rate-decision/">
  <title>SYNTHETIC: Bank holds its policy rate</title>
  <link>https://www.bankofcanada.ca/2026/10/synthetic-rate-decision/</link>
  <description>SYNTHETIC: the Bank held its target for the overnight rate.</description>
  <dc:date>2026-10-22T13:45:00+00:00</dc:date>
 </item>
</rdf:RDF>"""
RSS2 = (b'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>SYNTHETIC</title><item>'
        b"<title>SYNTHETIC: SEC charges a fund adviser</title><link>https://www.sec.gov/newsroom/press-releases/2026-1"
        b"</link><description>SYNTHETIC excerpt.</description><pubDate>Thu, 22 Oct 2026 14:00:00 GMT</pubDate></item>"
        b"</channel></rss>")


class SourcesTest(unittest.TestCase):
    def test_an_rss_1_feed_is_read_with_its_dates_and_links(self):
        source = news_registry.PUBLISHERS["boc-press"].feed
        parsed = event_inbox.parse_feed(RSS1, source)
        self.assertEqual((parsed["format"], len(parsed["items"])), ("rss1", 1))
        entry = parsed["items"][0]
        self.assertEqual(entry["title"], "SYNTHETIC: Bank holds its policy rate")
        self.assertEqual(entry["feed_timestamp"]["instant_utc"], "2026-10-22T13:45:00+00:00")
        self.assertIn("overnight rate", entry["excerpt"])

    def test_a_feed_asking_for_a_contact_is_requested_only_with_one_which_goes_in_the_user_agent(self):
        sec = news_registry.PUBLISHERS["sec-press"]
        self.assertTrue(sec.feed.contact_required)
        self.assertIn(sec, news_registry.connected())
        seen = []

        def answer(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["User-Agent"])
            return httpx.Response(200, content=RSS2, headers={"content-type": "application/rss+xml"})
        with tempfile.TemporaryDirectory() as folder:
            without = news_feeds.fetcher_for([sec], httpx.MockTransport(answer))
            result = news_feeds.refresh(Path(folder), without, [sec])
            self.assertEqual((result["refreshed"][0]["outcome"], seen), ("not_requested", []))
            self.assertIn("SECOND_ORDER_FEED_CONTACT", result["refreshed"][0]["detail"])
            declared = news_feeds.fetcher_for([sec], httpx.MockTransport(answer), contact="ops@example.org")
            result = news_feeds.refresh(Path(folder), declared, [sec])
            self.assertEqual(result["refreshed"][0]["outcome"], "ok")
            self.assertIn("contact: ops@example.org", seen[0])

    def test_the_new_publishers_state_their_terms_and_what_they_allow(self):
        for key in ("doj-antitrust", "boc-press", "sec-press", "ons-publications"):
            publisher = news_registry.PUBLISHERS[key]
            self.assertEqual((publisher.role, publisher.material, publisher.status), ("official", "permitted",
                                                                                     "connected"))
            self.assertTrue(publisher.material_basis and publisher.attribution and publisher.terms_url.startswith(
                "https://"))
        index = news_registry.PUBLISHERS["gdelt-index"]
        self.assertEqual((index.material, index.display, index.feed), ("none", "headline", None))
        self.assertNotIn(index, news_registry.connected())  # Looked up per story, never refreshed as a feed.


if __name__ == "__main__":
    unittest.main()

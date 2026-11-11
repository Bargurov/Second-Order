"""The Federal Reserve press-release extractor (fed-press-release-extract-0.1) on SYNTHETIC pages in the Board's layout:
the release's own words in order, every left-out line listed, and anything else refused whole, never guessed or cut.
"""
import unittest

from second_order import fed_publication
from second_order.fed_publication import Unreadable, extract, printed_instant

from news_fakes import PARAGRAPHS, fed_page

TYPE = "text/html; charset=utf-8"


class Extraction(unittest.TestCase):
    def test_the_release_is_its_date_title_release_time_and_body_in_order(self):
        found = extract(fed_page(), TYPE)
        self.assertEqual(found["text"], "\n\n".join(("September 16, 2026", "Simulated Committee issues synthetic statement",
                                                    "For release at 2:00 p.m. EDT", *PARAGRAPHS)))
        self.assertEqual((found["title"], found["date"], found["paragraphs"], found["characters"]),
                         ("Simulated Committee issues synthetic statement", "2026-09-16", 3, len(found["text"])))
        self.assertEqual(found["release_time"], {"hour": 14, "minute": 0, "zone": "EDT"})
        self.assertEqual(found["extractor"], fed_publication.EXTRACTOR_VERSION)

    def test_left_out_lines_are_listed_and_never_in_the_text(self):
        found = extract(fed_page(), TYPE)
        kinds = [row["kind"] for row in found["left_out"]]
        self.assertEqual(kinds, ["share_controls", "contact_line", "linked_document", "last_update"])
        self.assertEqual(found["linked_documents"], [{
            "title": "Implementation Note issued September 16, 2026",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a1.htm"}])
        for text in ("email", "protected", "Share", "Implementation Note", "Last Update", "Navigation", "Footer",
                     "not text", "color"):
            self.assertNotIn(text, found["text"])

    def test_an_unclosed_paragraph_ends_where_a_browser_ends_it(self):
        """The Board's pages leave p.releaseTime open before the share list (seen on the live page in the controlled
        retrieval of 2026-10-14); the text and parts are the same as with the paragraph closed."""
        unclosed, closed = extract(fed_page(), TYPE), extract(fed_page(release_closed=True), TYPE)
        self.assertEqual(unclosed["release_line"], "For release at 2:00 p.m. EDT")
        self.assertEqual({key: unclosed[key] for key in unclosed}, {key: closed[key] for key in closed})
        found = extract(fed_page(body_extra="<p>First paragraph left open<p>Second paragraph.</p>"), TYPE)
        self.assertIn("First paragraph left open\n\nSecond paragraph.", found["text"])

    def test_an_attached_file_is_a_linked_document_never_text(self):
        found = extract(fed_page(attachment="Minutes of the synthetic meetings (PDF)"), TYPE)
        self.assertEqual(found["linked_documents"][-1], {
            "title": "Minutes of the synthetic meetings (PDF)",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/files/monetary20260916a1.pdf"})
        self.assertEqual([row["kind"] for row in found["left_out"]],
                         ["share_controls", "contact_line", "linked_document", "linked_document", "last_update"])
        self.assertNotIn("PDF", found["text"])
        self.assertEqual(found["paragraphs"], 3)

    def test_a_release_without_a_printed_time_keeps_the_date_only(self):
        found = extract(fed_page(release_line=None), TYPE)
        self.assertIsNone(found["release_time"])
        self.assertIsNone(printed_instant(found))
        self.assertTrue(found["text"].startswith("September 16, 2026\n\nSimulated Committee"))

    def test_list_items_are_kept_as_marked_lines_and_entities_are_decoded(self):
        found = extract(fed_page(paragraphs=("Rates &amp; ranges were set as follows:",),
                                 body_extra="<ul><li>Item  one,\n with a break</li><li>Item two</li></ul>"), TYPE)
        self.assertIn("Rates &amp; ranges", found["text"])  # Escaped once by the builder: the page shows "&amp;".
        self.assertTrue(found["text"].endswith("- Item one, with a break\n\n- Item two"))

    def test_the_printed_time_must_be_the_zone_new_york_uses_that_day(self):
        self.assertEqual(printed_instant(extract(fed_page(), TYPE)).isoformat(), "2026-09-16T14:00:00-04:00")
        self.assertIsNone(printed_instant(extract(fed_page(release_line="For release at 2:00 p.m. EST"), TYPE)))
        winter = extract(fed_page(date_line="January 28, 2026", release_line="For release at 2:00 p.m. EST"), TYPE)
        self.assertEqual(printed_instant(winter).isoformat(), "2026-01-28T14:00:00-05:00")


class Refusals(unittest.TestCase):
    def refused(self, page: bytes, content_type: str = TYPE) -> str:
        with self.assertRaises(Unreadable) as caught:
            extract(page, content_type)
        return str(caught.exception)

    def test_another_layout_or_two_articles_is_refused(self):
        self.assertIn("layout", self.refused(b"<html><body><p>Some page</p></body></html>"))
        self.assertIn("layout", self.refused(fed_page(articles=2)))

    def test_only_utf8_is_read_and_nothing_is_guessed(self):
        self.assertIn("ISO-8859-1", self.refused(fed_page(), "text/html; charset=ISO-8859-1"))
        self.assertIn("windows-1252", self.refused(fed_page().replace(b'<meta charset="utf-8">',
                                                                      b'<meta charset="windows-1252">')))
        self.assertIn("not UTF-8", self.refused(fed_page() + b"\xff"))

    def test_a_missing_date_title_or_unreadable_release_time_is_refused(self):
        self.assertIn("title and date", self.refused(fed_page(date_line="Mid-September 2026")))
        self.assertIn("title and date", self.refused(fed_page(title="")))
        self.assertIn("release time", self.refused(fed_page(release_line="For release at noon")))
        self.assertIn("title and date", self.refused(fed_page(date_line="September 31, 2026")))

    def test_a_table_or_an_empty_body_is_refused(self):
        self.assertIn("table", self.refused(fed_page(body_extra="<table><tr><td>1</td></tr></table>")))
        self.assertIn("no text", self.refused(fed_page(paragraphs=(), contact=False, linked=None)))

    def test_a_release_over_the_source_limit_is_refused_whole_never_cut(self):
        long = ("x" * 9_000,) * 6
        message = self.refused(fed_page(paragraphs=long))
        self.assertIn("never cut", message)
        self.assertEqual(len(extract(fed_page(paragraphs=("y" * 40_000,)), TYPE)["text"].split("\n\n")[-1]), 40_000)


if __name__ == "__main__":
    unittest.main()

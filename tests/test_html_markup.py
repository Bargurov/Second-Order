"""The rule for markup the HTML readers refuse (html_markup): a marked section ("<![") other than CDATA, TEMP, IGNORE,
INCLUDE, RCDATA, IF, ELSE or ENDIF makes the markup unreadable. Every reader applies it to the text before html.parser
reads anything, so the answer is the same under every Python version: 3.12.8's parser refused these sections itself,
while 3.12.16's reads them as HTML5 does and drops their text. All markup here is SYNTHETIC; nothing is written."""
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

import g17_fakes
from news_desk_fakes import FACT_TITLE, WORDS, wh_page
from news_fakes import fed_page
from second_order import (bis_snapshot, event_inbox, fed_publication, g17_evidence, html_markup, page_text,
                          related_cases, thesis_sources)

OTHER = "<![bogus[x]]>"
CONDITIONAL = "<!--[if lt IE 9]><script src='x.js'></script><![endif]--><![if !IE]><![endif]>"


class RuleTests(unittest.TestCase):
    def test_a_marked_section_the_readers_do_not_read_is_unreadable_wherever_it_stands(self):
        for text in ("<p>Synthetic</p><![bogus[x]]>", "<p>Synthetic</p><![ x", "<![", "<![]>", "<![ x ]>", "<![1]>",
                     "<![ifx]>", "<![if-x]>", "<![CDATA.x[", "<![elſe]>",  # The names are whole, and ASCII.
                     "<title><![bogus[x]]></title>", "<script>var a = '<![bogus[';</script>", "<!-- <![ x -->"):
            with self.subTest(text=text):
                self.assertTrue(html_markup.unreadable(text))

    def test_cdata_conditional_and_sgml_sections_and_escaped_text_are_read(self):
        for text in ("<![CDATA[x]]>", "<![cdata[x]]>", CONDITIONAL, "<![ENDIF]>", "<![else]>", "<![temp[x]]>",
                     "<![ignore[x]]>", "<![include[x]]>", "<![rcdata[x]]>",
                     "<script>//<![CDATA[\nvar a;\n//]]></script>", "<p>Synthetic &lt;![bogus[x]]&gt;</p>",
                     "<p>Synthetic</p>", "<! [x>", "<!-- [x] -->", ""):
            with self.subTest(text=text):
                self.assertFalse(html_markup.unreadable(text))


class ReaderTests(unittest.TestCase):
    """Each reader refuses OTHER with its own refusal before html.parser is fed, and reads the same input with the
    sections it does read in OTHER's place."""

    @staticmethod
    def readers() -> dict:
        g17_page = g17_fakes.table1("20260918", g17_fakes.SCENARIO)
        return {  # name: (read, input with a marked section in place of "{}", the reader's refusal)
            "thesis_sources": (thesis_sources.html_paragraphs, lambda s: f"<p>Synthetic</p>{s}".encode(),
                               thesis_sources.Unreadable),
            "event_inbox": (lambda value: event_inbox.plain_text(value, True, 300, "the excerpt"),
                            lambda s: f"Synthetic {s} text", event_inbox.FeedRejected),
            "bis_snapshot": (bis_snapshot.paragraphs, lambda s: f"<p>Synthetic</p>{s}", bis_snapshot.Unreadable),
            "fed_publication": (lambda raw: fed_publication.extract(raw, "text/html; charset=utf-8"),
                                lambda s: fed_page(body_extra=s), fed_publication.Unreadable),
            "related_cases": (related_cases.page_blocks, lambda s: f"<html><body><p>Synthetic</p>{s}</body></html>"
                              .encode(), ValueError),
            "page_text": (lambda raw: page_text.read_page(raw, "text/html", page_text.WHITE_HOUSE),
                          lambda s: wh_page(FACT_TITLE, [WORDS]).replace(b"</main>", f"{s}</main>".encode()),
                          page_text.Unreadable),
            "g17_evidence": (lambda raw: g17_evidence._page(raw, "table1.htm"),
                             lambda s: g17_page.replace("</h2>", f"</h2>{s}").encode(), g17_evidence.EvidenceRefused),
        }

    def test_every_reader_refuses_it_before_html_parser_reads_anything(self):
        fed, feed = [], HTMLParser.feed

        def recorded(parser, data):
            fed.append(data)
            return feed(parser, data)

        with patch.object(HTMLParser, "feed", recorded):
            for name, (read, page, refusal) in self.readers().items():
                with self.subTest(reader=name):
                    fed.clear()
                    self.assertNotEqual(page(OTHER), page(""))  # The marked section is in the input.
                    with self.assertRaises(refusal) as refused:
                        read(page(OTHER))
                    self.assertIn("not be read", str(refused.exception))  # "cannot be read" or "could not be read".
                    self.assertNotIn("html_markup", str(refused.exception))  # The words reach people; the module not.
                    self.assertEqual(fed, [])
                    read(page(CONDITIONAL))  # The sections the readers read pass, and the parser is fed.
                    self.assertTrue(fed)


if __name__ == "__main__":
    unittest.main()

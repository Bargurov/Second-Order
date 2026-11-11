"""Event Inbox: five fixed feeds, refreshed only by an explicit local action into a local cache; reads only read.

Every test serves SYNTHETIC feed bytes through an injected httpx.MockTransport, in temporary folders, and records each
request it receives: nothing here reaches a network. The one live check against the real feeds is a separate,
operator-run step with a temporary cache (see docs/DEVELOPMENT.md, Event inbox).
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from second_order import event_inbox
from second_order.api import create_app
from second_order.event_inbox import (MAX_BYTES, RETAIN, SOURCES, FeedFetcher, FeedRejected, FetchFailed,
                                      feed_timestamp, inbox_view, parse_feed, refresh)

BASE = "http://127.0.0.1:8131"
INBOX_HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Inbox": "1"}
INTAKE_HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
FED, EMPSIT, CPI, EIA, WTO = (SOURCES[key].feed_url for key in ("fed-monetary", "bls-empsit", "bls-cpi",
                                                                "eia-todayinenergy", "wto-news"))
ALL = [FED, EMPSIT, CPI, EIA, WTO]  # The order a refresh requests them in.
CONTACT = "operator@example.invalid"


def rss_item(n: int, title: str | None = None, link: str | None = None, guid: str | None = None,
             pub: str | None = "Wed, 16 Sep 2026 18:00:00 GMT", description: str | None = None) -> str:
    link = f"https://www.federalreserve.gov/newsevents/pressreleases/monetary2026091{n}a.htm" if link is None else link
    parts = [f"<title>{title or f'Synthetic Fed release {n}'}</title>", f"<link><![CDATA[{link}]]></link>"]
    parts.append(f"<guid><![CDATA[{guid if guid is not None else link}]]></guid>")
    if description is not None:
        parts.append(f"<description><![CDATA[{description}]]></description>")
    if pub is not None:
        parts.append(f"<pubDate><![CDATA[{pub}]]></pubDate>")
    return "<item>" + "".join(parts) + "</item>"


def rss(items: list[str]) -> bytes:
    return b"\xef\xbb\xbf" + ('<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel><title>FRB: '
                             'Synthetic</title>' + "".join(items) + "</channel></rss>").encode("utf-8")


def atom_entry(n: int, kind: str = "empsit", title: str | None = None, published: str | None = "2026-10-02T07:51:08.289-04:00",
               updated: str | None = None, content: str | None = "Synthetic excerpt.", link: str | None = None) -> str:
    link = f"https://www.bls.gov/news.release/archives/{kind}_1002202{n}.htm" if link is None else link
    parts = [f"<title>{title or f'Synthetic {kind} release {n}'}</title>", f'<link href="{link}"/>',
             f"<id>{kind}-synthetic-{n}</id>"]
    if content is not None:
        parts.append(f"<content>{content}</content>")
    if published is not None:
        parts.append(f"<published>{published}</published>")
    if updated is not None:
        parts.append(f"<updated>{updated}</updated>")
    return "<entry>" + "".join(parts) + "</entry>"


def atom(entries: list[str]) -> bytes:
    return ("<?xml version='1.0' encoding='UTF-8'?><feed xmlns=\"http://www.w3.org/2005/Atom\"><id>bls.gov:feed</id>"
            "<title>Synthetic</title>" + "".join(entries) + "</feed>").encode("utf-8")


def eia_item(n: int, title: str | None = None, link: str | None = None, pub: str | None = "Wed, 07 Oct 2026  09:00:00 EST",
             description: str | None = "Synthetic energy excerpt.") -> str:
    """An item shaped like EIA's Today in Energy feed: no guid, a fixed 09:00:00 EST time, plain-text description."""
    link = f"https://www.eia.gov/todayinenergy/detail.php?id=9{n:04d}" if link is None else link
    parts = [f"<title>{title or f'Synthetic energy article {n}'}</title>", f"<link>{link}</link>"]
    if pub is not None:
        parts.append(f"<pubDate>{pub}</pubDate>")
    if description is not None:
        parts.append(f"<description>{description}</description>")
    return "<item>" + "".join(parts) + "</item>"


def eia_rss(items: list[str]) -> bytes:
    """Declared and encoded as ISO-8859-1, with a stylesheet instruction, as the EIA feed is."""
    return ('<?xml version="1.0" encoding="ISO-8859-1" ?>\n<?xml-stylesheet href="rss.xsl" type="text/xsl" '
            'media="screen"?>\n<rss version="2.0"><channel><title>Today in Energy</title>' + "".join(items) +
            "</channel></rss>").encode("iso-8859-1")


def wto_item(n: int, title: str | None = None, link: str | None = None, guid: str | None = None,
             pub: str | None = "Thu, 08 Oct 2026 00:00:00 GMT", description: str | None = "Synthetic trade excerpt.",
             content: str | None = "<p>Full synthetic article body.</p>") -> str:
    """An item shaped like the WTO news feed: guid, categories, a full-article content element, a midnight time."""
    link = f"https://www.wto.org/english/news_e/news26_e/synth_{n:02d}oct26_e.htm" if link is None else link
    parts = [f"<title>{title or f'Synthetic trade news {n}'}</title>"]
    if description is not None:
        parts.append(f"<description><![CDATA[{description}]]></description>")
    parts.append('<category domain="SYNT">synthetic category</category>')
    if content is not None:
        parts.append(f"<content><![CDATA[{content}]]></content>")
    parts.append(f"<link>{link}</link><guid>{guid if guid is not None else link}</guid>")
    if pub is not None:
        parts.append(f"<pubDate>{pub}</pubDate>")
    return "<item>" + "".join(parts) + "</item>"


def wto_rss(items: list[str]) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
            "<channel><title>World Trade Organization \u2014 Latest news</title>"
            "<pubDate>Thu, 08 Oct 2026 13:01:03 GMT</pubDate>" + "".join(items) + "</channel></rss>").encode("utf-8")


# The energy and trade feeds answering with no entries, for tests about the other sources.
QUIET = {EIA: [(200, eia_rss([]))], WTO: [(200, wto_rss([]))]}


# Escaped markup that Python's html.parser refuses with AssertionError (an unknown or unnamed marked section).
UNREADABLE = ("&lt;![bogus[ x ]]&gt;", "&lt;![ x")


def unreadable_rss_item(n: int, markup: str) -> str:
    """An RSS item whose escaped HTML description holds markup the HTML parser cannot read."""
    return (f"<item><title>Unreadable Fed release {n}</title>"
            f"<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary2026092{n}a.htm</link>"
            f"<guid>unreadable-{n}</guid><description>Statement {markup} text</description>"
            "<pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item>")


def unreadable_atom_entry(n: int, part: str, markup: str) -> str:
    """An Atom entry whose html-typed title, summary or content holds markup the HTML parser cannot read."""
    title = f'<title type="html">Jobs {markup}</title>' if part == "title" else f"<title>Unreadable entry {n}</title>"
    body = f'<{part} type="html">Excerpt {markup}</{part}>' if part in ("summary", "content") else ""
    return (f'<entry>{title}<link href="https://www.bls.gov/news.release/archives/empsit_unreadable{n}.htm"/>'
            f"<id>empsit-unreadable-{n}</id>{body}<published>2026-10-02T08:30:00-04:00</published></entry>")


class Network:
    """A simulated network: a queue of answers per feed URL, and every request it received."""

    def __init__(self, answers: dict | None = None):
        self.answers = {url: list(queue) for url, queue in (answers or {}).items()}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.answers.get(str(request.url))
        if not queue:
            raise AssertionError(f"Unexpected request to {request.url}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        status, body, headers = answer if len(answer) == 3 else (*answer, {"content-type": "text/xml"})
        return httpx.Response(status, content=body, headers=headers)

    def fetcher(self, contact: str | None = CONTACT) -> FeedFetcher:
        return FeedFetcher(contact, httpx.MockTransport(self))

    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]


def standard() -> dict:
    return {FED: [(200, rss([rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 GMT"),
                             rss_item(2, pub="Wed, 29 Jul 2026 18:00:00 GMT")]))],
            EMPSIT: [(200, atom([atom_entry(1, published="2026-10-02T07:51:08.289-04:00")]))],
            CPI: [(200, atom([atom_entry(1, "cpi", published="2026-09-11T08:30:00-04:00")]))], **QUIET}


def clock(start: datetime = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)):
    moments = iter(start + timedelta(seconds=n) for n in range(10_000))
    return lambda: next(moments)


def fingerprint(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()} if folder.exists() else {}


class Folder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.inbox = self.root / "event-inbox"


class ParsingTests(unittest.TestCase):
    FED_SOURCE, EMPSIT_SOURCE = SOURCES["fed-monetary"], SOURCES["bls-empsit"]

    def test_rss_entries_become_plain_metadata_with_the_raw_timestamp_and_its_origin(self):
        parsed = parse_feed(rss([rss_item(1, title="Rates &amp; balance sheet", description=(
            "<p>Released <b>today</b>.</p><script>alert(1)</script><img src=x onerror=alert(2)>"))]), self.FED_SOURCE)
        item = parsed["items"][0]
        self.assertEqual((parsed["format"], parsed["listed"], item["title"], item["excerpt"]),
                         ("rss", 1, "Rates & balance sheet", "Released today."))
        self.assertEqual(item["feed_timestamp"], {
            "raw": "Wed, 16 Sep 2026 18:00:00 GMT", "origin": "RSS pubDate", "instant_utc": "2026-09-16T18:00:00+00:00",
            "suggestion": {"date": "2026-09-16", "time": "18:00:00", "offset": "+00:00", "dropped_fraction": None},
            "problem": None})
        self.assertTrue(item["id"].startswith("fed-monetary:"))

    def test_atom_entries_prefer_published_and_disclose_fallbacks_and_dropped_fractions(self):
        parsed = parse_feed(atom([
            atom_entry(1, content="&lt;b&gt;bold&lt;/b&gt; text"),
            atom_entry(2, published=None, updated="2026-09-04T08:30:00-04:00"),
            atom_entry(3, published=None, updated=None)]), self.EMPSIT_SOURCE)
        first, second, third = parsed["items"]
        self.assertEqual((first["excerpt"], first["feed_timestamp"]["origin"]), ("<b>bold</b> text", "Atom published"))
        self.assertEqual(first["feed_timestamp"]["suggestion"],
                         {"date": "2026-10-02", "time": "07:51:08", "offset": "-04:00", "dropped_fraction": ".289"})
        self.assertEqual(second["feed_timestamp"]["origin"], "Atom updated (the entry has no published element)")
        self.assertEqual(second["feed_timestamp"]["suggestion"]["time"], "08:30:00")
        self.assertEqual((third["feed_timestamp"]["suggestion"], third["feed_timestamp"]["instant_utc"]), (None, None))
        self.assertIn("no timestamp", third["feed_timestamp"]["problem"])
        html = parse_feed(atom([atom_entry(1).replace("<content>Synthetic excerpt.</content>",
                                                      '<content type="html">&lt;p&gt;One&lt;/p&gt;&lt;p&gt;Two&lt;/p&gt;'
                                                      "</content>")]), self.EMPSIT_SOURCE)
        self.assertEqual(html["items"][0]["excerpt"], "One Two")

    def test_missing_or_ambiguous_timestamps_stay_unknown(self):
        cases = {
            "Wed, 7 Oct 2026 14:00:00 EDT": ("2026-10-07", "14:00:00", "-04:00"),
            "Wed, 7 Oct 2026 14:00 -0400": ("2026-10-07", "14:00:00", "-04:00"),
            "Wed, 7 Oct 2026 18:00:00 -0000": None,  # RFC 5322: no information about the local offset.
            "Wed, 7 Oct 2026 18:00:00 XYZ": None,  # A zone name RFC 822 does not define is not guessed.
            "Thu, 7 Oct 2026 18:00:00 GMT": None,  # The weekday contradicts the date.
            "Wed, 31 Feb 2026 18:00:00 GMT": None,
            "7 Oct 2026": None,
            "": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw):
                suggestion = feed_timestamp(raw, "RSS pubDate", rfc822=True)["suggestion"]
                self.assertEqual(None if suggestion is None else (suggestion["date"], suggestion["time"],
                                                                  suggestion["offset"]), expected)
        self.assertIsNone(feed_timestamp("2026-10-02T07:51:08", "Atom published", False)["suggestion"])  # No offset.
        self.assertEqual(feed_timestamp("2026-10-02T11:51:08Z", "Atom published", False)["suggestion"]["offset"], "+00:00")
        odd = feed_timestamp("2026-10-02T07:51:08+05:17", "Atom published", False)
        self.assertEqual((odd["suggestion"], odd["instant_utc"]), (None, "2026-10-02T02:34:08+00:00"))

    def test_entries_with_unsafe_or_foreign_links_are_skipped_and_counted(self):
        links = ["javascript:alert(1)", "http://www.federalreserve.gov/newsevents/x.htm", "https://example.org/x.htm",
                 "https://user@www.federalreserve.gov/x.htm", "https://www.federalreserve.gov:8443/x.htm",
                 "/newsevents/x.htm", "https://www.federalreserve.gov/", "https://www.federalreserve.gov/a b.htm",
                 "data:text/html,hi", "https://www.federalreserve.gov:abc/x.htm",
                 "https://www.federalreserve.gov:99999/x.htm", "https://[broken/x.htm"]
        parsed = parse_feed(rss([rss_item(n, link=link, guid=f"g{n}") for n, link in enumerate(links)] +
                                [rss_item(9)]), self.FED_SOURCE)
        self.assertEqual(([item["link"] for item in parsed["items"]], parsed["skipped_count"]),
                         (["https://www.federalreserve.gov/newsevents/pressreleases/monetary20260919a.htm"], len(links)))
        self.assertTrue(all(entry["reason"].startswith("Skipped:") for entry in parsed["skipped"]))

    def test_invalid_offsets_and_unrepresentable_utc_instants_stay_unknown(self):
        cases = [
            ("Wed, 16 Sep 2026 18:00:00 +9900", True),
            ("Wed, 16 Sep 2026 18:00:00 +0460", True),
            ("2026-10-02T07:51:08+99:00", False),
            ("2026-10-02T07:51:08+04:60", False),
            ("2026-10-02T07:51:08-00:00", False),
            ("0001-01-01T00:00:00+04:00", False),
            ("9999-12-31T23:59:59-04:00", False),
        ]
        for raw, rfc822 in cases:
            with self.subTest(raw=raw):
                result = feed_timestamp(raw, "Synthetic timestamp", rfc822)
                self.assertEqual((result["raw"], result["instant_utc"], result["suggestion"]), (raw, None, None))
                self.assertTrue(result["problem"])

    def test_unsafe_malformed_or_foreign_documents_are_refused(self):
        bad = {
            "a DTD": b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "x">]><rss version="2.0"><channel/></rss>',
            "an external entity": b'<?xml version="1.0"?><!DOCTYPE r SYSTEM "file:///etc/passwd"><rss/>',
            "malformed XML": b"<rss><channel><item></channel></rss>",
            "not UTF-8": b"\xff\xfe<\x00r\x00s\x00s\x00",
            "another declared encoding": b'<?xml version="1.0" encoding="ISO-8859-1"?><rss version="2.0"><channel/></rss>',
            "an HTML page": b"<html><body>Access Denied</body></html>",
            "too many entries": rss([rss_item(1, guid=f"g{n}") for n in range(event_inbox.MAX_LISTED + 1)]),
        }
        for name, data in bad.items():
            with self.subTest(name), self.assertRaises(FeedRejected):
                parse_feed(data, self.FED_SOURCE)

    def test_valid_empty_feeds_are_results_with_no_entries(self):
        self.assertEqual(parse_feed(rss([]), self.FED_SOURCE)["items"], [])
        self.assertEqual(parse_feed(atom([]), self.EMPSIT_SOURCE)["items"], [])

    def test_identity_not_title_decides_duplicates_and_retention_is_bounded(self):
        same_guid = parse_feed(rss([rss_item(1, guid="one"), rss_item(2, guid="one")]), self.FED_SOURCE)
        self.assertEqual((len(same_guid["items"]), same_guid["duplicates"]), (1, 1))
        alike = parse_feed(rss([rss_item(1, title="Federal Reserve issues FOMC statement"),
                                rss_item(2, title="Federal Reserve issues FOMC statement")]), self.FED_SOURCE)
        self.assertEqual(len(alike["items"]), 2)  # Same title, different releases: kept apart.
        many = parse_feed(rss([rss_item(1, link=f"https://www.federalreserve.gov/n/{n}.htm", guid=f"g{n}")
                               for n in range(RETAIN + 10)]), self.FED_SOURCE)
        self.assertEqual((len(many["items"]), many["not_retained"], many["items"][-1]["position"]), (RETAIN, 10, RETAIN))

    def test_long_or_hostile_text_is_cut_and_cleaned(self):
        parsed = parse_feed(rss([rss_item(1, title="T" * 400, description="E\t\n ​ " + "x" * 2000)]),
                            self.FED_SOURCE)
        item = parsed["items"][0]
        self.assertTrue(item["title_truncated"] and len(item["title"]) == event_inbox.MAX_TITLE)
        self.assertTrue(item["excerpt_truncated"] and len(item["excerpt"]) == event_inbox.MAX_EXCERPT)
        self.assertTrue(item["excerpt"].startswith("E x") and item["excerpt"].isprintable())
        with self.assertRaises(FeedRejected):  # Characters XML itself forbids refuse the whole document.
            parse_feed(rss([rss_item(1, description="E\u0000\u0007")]), self.FED_SOURCE)

    def test_markup_the_html_parser_cannot_read_skips_only_that_entry(self):
        for markup in UNREADABLE:
            feeds = {"an RSS description": (rss([rss_item(1), unreadable_rss_item(2, markup)]), self.FED_SOURCE, "excerpt"),
                     **{f"an Atom html {part}": (atom([atom_entry(1), unreadable_atom_entry(2, part, markup)]),
                                                 self.EMPSIT_SOURCE, "title" if part == "title" else "excerpt")
                        for part in ("title", "summary", "content")}}
            for name, (data, source, field) in feeds.items():
                with self.subTest(markup=markup, entry=name):
                    parsed = parse_feed(data, source)
                    self.assertEqual(([item["position"] for item in parsed["items"]], parsed["skipped_count"]), ([1], 1))
                    self.assertEqual(parsed["skipped"], [{"position": 2, "reason": (
                        f"Skipped: the {field} has markup that cannot be read as plain text")}])


class FetcherTests(unittest.TestCase):
    def test_only_the_listed_feeds_can_be_requested(self):
        network = Network()
        with self.assertRaises(FetchFailed):
            network.fetcher().fetch("https://example.org/feed.xml")
        self.assertEqual(network.requests, [])

    def test_a_request_carries_the_operators_contact_and_no_cookies(self):
        network = Network({FED: [(200, rss([]))]})
        network.fetcher().fetch(FED)
        sent = network.requests[0]
        self.assertIn(f"contact: {CONTACT}", sent.headers["user-agent"])
        self.assertNotIn("cookie", sent.headers)
        self.assertNotIn("Mozilla", sent.headers["user-agent"])  # Never disguised as a browser.
        for bad in ("a\r\nX-Injected: 1", "x" * 201, ""):
            with self.subTest(bad), self.assertRaises(ValueError):
                FeedFetcher(bad)

    def test_redirects_errors_sizes_and_timeouts_fail_without_a_second_request(self):
        cases = {
            "a redirect": (301, b"", {"location": "https://mirror.example.org/feed.xml"}),
            "an error status": (503, b"busy", {"content-type": "text/plain"}),
            "a declared oversize body": (200, b"", {"content-length": str(MAX_BYTES + 1)}),
            "an oversize body": (200, b"x" * (MAX_BYTES + 1), {"content-type": "text/xml"}),
            # Chunked, with no Content-Length: only the cap on what is actually read stops it.
            "an undeclared oversize body": (200, iter([b"x" * (MAX_BYTES // 4)] * 5), {"content-type": "text/xml"}),
            "a timeout": httpx.ReadTimeout("simulated"),
        }
        for name, answer in cases.items():
            with self.subTest(name):
                network = Network({FED: [answer]})
                with self.assertRaises(FetchFailed):
                    network.fetcher().fetch(FED)
                self.assertEqual(network.urls(), [FED])  # Exactly one request; no retry, no redirect followed.


class RefreshTests(Folder):
    def test_an_empty_cache_reads_as_never_refreshed_and_reading_creates_nothing(self):
        view = inbox_view(self.inbox)
        self.assertEqual([source["state"] for source in view["sources"]], ["never_refreshed"] * 5)
        self.assertEqual((view["items"], view["retention"]["per_source"]), ([], RETAIN))
        self.assertFalse(self.inbox.exists())

    def test_a_refresh_stores_each_source_and_orders_items_by_feed_timestamp(self):
        network = Network(standard())
        result = refresh(self.inbox, network.fetcher(), clock())
        self.assertEqual(network.urls(), ALL)
        self.assertEqual([outcome["outcome"] for outcome in result["refreshed"]], ["ok"] * 5)
        self.assertEqual([item["source"] for item in result["items"]],
                         ["bls-empsit", "fed-monetary", "bls-cpi", "fed-monetary"])  # Oct 2, Sep 16, Sep 11, Jul 29.
        self.assertEqual(sorted(path.name for path in self.inbox.iterdir()),
                         ["acquisitions", "archive", "bls-cpi.json", "bls-empsit.json", "eia-todayinenergy.json",
                          "fed-monetary.json", "raw", "wto-news.json"])
        sources = ["bls-cpi", "bls-empsit", "eia-todayinenergy", "fed-monetary", "wto-news"]
        self.assertEqual(sorted(path.name for path in (self.inbox / "raw").iterdir()), sources)  # See test_inbox_raw.
        self.assertEqual(sorted(path.name for path in (self.inbox / "acquisitions").iterdir()),  # test_inbox_acquisitions
                         sources)
        self.assertEqual(sorted(path.name for path in (self.inbox / "archive").iterdir()),  # See test_inbox_archive.
                         ["bls-cpi.json", "bls-empsit.json", "eia-todayinenergy.json", "fed-monetary.json",
                          "wto-news.json"])
        first = result["items"][0]
        self.assertEqual((first["publisher"], first["category"], first["stale"], first["retrieved_at"]),
                         ("U.S. Bureau of Labor Statistics", "Employment", False, "2026-10-08T09:00:03+00:00"))
        self.assertNotIn("identity", first)

    def test_a_failed_source_keeps_its_last_good_items_and_never_touches_another(self):
        network = Network(standard())
        refresh(self.inbox, network.fetcher(), clock())
        before = json.loads((self.inbox / "fed-monetary.json").read_text(encoding="utf-8"))["last_success"]
        failures = Network({FED: [(500, b"down", {"content-type": "text/plain"})],
                            EMPSIT: [(200, b"<html>maintenance</html>", {"content-type": "text/html"})],
                            CPI: [(200, atom([atom_entry(2, "cpi", published="2026-10-08T08:30:00-04:00")]))],
                            **QUIET})
        result = refresh(self.inbox, failures.fetcher(), clock(datetime(2026, 10, 9, tzinfo=timezone.utc)))
        states = {source["key"]: source for source in result["sources"]}
        self.assertEqual([states[key]["state"] for key in ("fed-monetary", "bls-empsit", "bls-cpi")],
                         ["failed", "failed", "ok"])
        self.assertIn("HTTP 500", states["fed-monetary"]["last_attempt"]["detail"])
        self.assertIn("web page", states["bls-empsit"]["last_attempt"]["detail"])
        self.assertEqual(json.loads((self.inbox / "fed-monetary.json").read_text(encoding="utf-8"))["last_success"],
                         before)
        fed_items = [item for item in result["items"] if item["source"] == "fed-monetary"]
        self.assertEqual((len(fed_items), {item["stale"] for item in fed_items}), (2, {True}))
        self.assertEqual([item["title"] for item in result["items"] if item["source"] == "bls-cpi"],
                         ["Synthetic cpi release 2"])  # Items that left the CPI feed left the inbox.

    def test_bls_is_not_requested_without_the_operators_contact(self):
        network = Network(standard())
        result = refresh(self.inbox, network.fetcher(contact=None), clock())
        self.assertEqual(network.urls(), [FED, EIA, WTO])  # Only BLS asks for a contact.
        states = {source["key"]: source for source in result["sources"]}
        self.assertEqual((states["bls-empsit"]["state"], states["bls-cpi"]["state"]), ("not_requested", "not_requested"))
        self.assertIn(event_inbox.CONTACT_ENV, states["bls-cpi"]["last_attempt"]["detail"])

    def test_an_unreadable_record_is_reported_and_left_alone(self):
        refresh(self.inbox, Network(standard()).fetcher(), clock())
        broken = b'{"inbox_version": "event-inbox-0.1", "source": "bls-cpi"'
        (self.inbox / "bls-cpi.json").write_bytes(broken)
        view = inbox_view(self.inbox)
        cpi = next(source for source in view["sources"] if source["key"] == "bls-cpi")
        self.assertEqual((cpi["state"], [item["source"] for item in view["items"]].count("bls-cpi")), ("unreadable", 0))
        network = Network(standard())
        result = refresh(self.inbox, network.fetcher(), clock())
        self.assertEqual(network.urls(), [FED, EMPSIT, EIA, WTO])  # Not refreshed over, not repaired.
        self.assertEqual((self.inbox / "bls-cpi.json").read_bytes(), broken)
        self.assertEqual(result["refreshed"][2]["outcome"], "skipped_unreadable")
        for tampered in ({"items": "not a list"}, {"items": [{"id": "x"}]}):
            record = json.loads((self.inbox / "fed-monetary.json").read_text(encoding="utf-8"))
            record["last_success"].update(tampered)
            (self.inbox / "fed-monetary.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(inbox_view(self.inbox)["sources"][0]["state"], "unreadable")

    def test_first_seen_is_kept_and_items_leaving_a_feed_leave_the_inbox(self):
        refresh(self.inbox, Network(standard()).fetcher(), clock())
        later = Network({**standard(), FED: [(200, rss([rss_item(3, pub="Wed, 7 Oct 2026 18:00:00 GMT"),
                                                        rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 GMT")]))]})
        result = refresh(self.inbox, later.fetcher(), clock(datetime(2026, 10, 9, tzinfo=timezone.utc)))
        fed = {item["title"]: item for item in result["items"] if item["source"] == "fed-monetary"}
        self.assertEqual(set(fed), {"Synthetic Fed release 3", "Synthetic Fed release 1"})
        self.assertEqual(fed["Synthetic Fed release 1"]["first_seen_at"], "2026-10-08T09:00:01+00:00")
        self.assertEqual(fed["Synthetic Fed release 3"]["first_seen_at"], "2026-10-09T00:00:01+00:00")

    def test_items_without_a_timestamp_come_last_in_a_fixed_order(self):
        network = Network({FED: [(200, rss([rss_item(1, pub=None), rss_item(2, pub="Wed, 16 Sep 2026 18:00:00 GMT")]))],
                           EMPSIT: [(200, atom([atom_entry(1, published=None)]))],
                           CPI: [(200, atom([atom_entry(1, "cpi", published="2026-09-16T14:00:00-04:00")]))],
                           **QUIET})
        result = refresh(self.inbox, network.fetcher(), clock())
        self.assertEqual([(item["source"], item["position"]) for item in result["items"]],
                         [("fed-monetary", 2), ("bls-cpi", 1), ("fed-monetary", 1), ("bls-empsit", 1)])


class ApiTests(Folder):
    def app(self, network: Network | None = None, contact: str | None = CONTACT):
        network = network or Network(standard())
        return network, create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                   self.root / "intake", self.root / "attempts", inbox=self.inbox,
                                   feeds=network.fetcher(contact))

    def test_startup_and_reads_make_no_request_and_write_nothing(self):
        network, app = self.app()
        with TestClient(app, base_url=BASE) as client:
            blocked = AssertionError("a read tried to open a network connection")
            with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
                for _ in range(3):
                    self.assertEqual(client.get("/api/inbox").status_code, 200)
                self.assertEqual(client.get("/").status_code, 503)  # No client built here; still nothing fetched.
        self.assertEqual((network.requests, self.inbox.exists()), ([], False))

    def test_bad_entry_metadata_never_aborts_the_remaining_sources(self):
        for name, entry in (
                ("link", rss_item(1, link="https://www.federalreserve.gov:abc/news.htm")),
                ("offset", rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 +9900"))):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                network = Network({**standard(), FED: [(200, rss([entry]))]})
                app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                 self.root / "intake", self.root / "attempts", inbox=Path(folder) / "inbox",
                                 feeds=network.fetcher())
                with TestClient(app, base_url=BASE) as client:
                    response = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(network.urls(), ALL)
                self.assertEqual([item["outcome"] for item in result["refreshed"]], ["ok"] * 5)
                fed = result["sources"][0]
                if name == "link":
                    self.assertEqual((fed["last_success"]["item_count"], fed["last_success"]["skipped_count"]), (0, 1))
                else:
                    item = next(item for item in result["items"] if item["source"] == "fed-monetary")
                    self.assertIsNone(item["feed_timestamp"]["instant_utc"])
                    self.assertIsNone(item["feed_timestamp"]["suggestion"])

    def test_markup_the_html_parser_cannot_read_never_aborts_the_first_or_a_middle_source(self):
        """A first refresh caches every source; the second carries unreadable markup in one source. That entry is
        skipped and counted; the source's good entries, the later sources and the earlier cache all survive."""
        bad_fed = rss([rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 GMT"), unreadable_rss_item(3, UNREADABLE[0]),
                       rss_item(2, pub="Wed, 29 Jul 2026 18:00:00 GMT"), unreadable_rss_item(4, UNREADABLE[1])])
        bad_empsit = atom([atom_entry(1)] + [unreadable_atom_entry(n, part, UNREADABLE[n % 2])
                                             for n, part in enumerate(("title", "summary", "content"), start=2)])
        for name, second, broken, kept_count, skipped in (
                ("first", {**standard(), FED: [(200, bad_fed)]}, "fed-monetary", 2, 2),
                ("middle", {**standard(), EMPSIT: [(200, bad_empsit)], CPI: [(503, b"busy", {"content-type": "text/plain"})]},
                 "bls-empsit", 1, 3)):
            with self.subTest(source=name), tempfile.TemporaryDirectory() as folder:
                inbox = Path(folder) / "inbox"
                network = Network(standard())
                app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                 self.root / "intake", self.root / "attempts", inbox=inbox, feeds=network.fetcher())
                with TestClient(app, base_url=BASE) as client:
                    first = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS).json()
                    network.answers = {url: list(queue) for url, queue in second.items()}
                    response = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
                    reread = client.get("/api/inbox").json()
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(network.urls(), ALL * 2)  # Every later source was still requested.
                outcomes = {item["source"]: item["outcome"] for item in result["refreshed"]}
                self.assertEqual(outcomes, {"fed-monetary": "ok", "bls-empsit": "ok",
                                            "bls-cpi": "failed" if name == "middle" else "ok",
                                            "eia-todayinenergy": "ok", "wto-news": "ok"})
                sources = {source["key"]: source for source in result["sources"]}
                self.assertEqual((sources[broken]["last_success"]["item_count"],
                                  sources[broken]["last_success"]["skipped_count"]), (kept_count, skipped))
                record = json.loads((inbox / f"{broken}.json").read_text(encoding="utf-8"))
                self.assertTrue(all(entry["reason"].endswith("has markup that cannot be read as plain text")
                                    for entry in record["last_success"]["skipped"]))
                earlier = {(item["source"], item["title"]): item["first_seen_at"] for item in first["items"]}
                kept = {(item["source"], item["title"]): item for item in result["items"]}
                for key, seen in earlier.items():  # Each earlier entry survives, first seen as before.
                    self.assertEqual(kept[key]["first_seen_at"], seen)
                    self.assertEqual(kept[key]["stale"], key[0] == "bls-cpi" and name == "middle")
                self.assertEqual(set(kept), set(earlier))  # Nothing unreadable reached the inbox.
                self.assertEqual(reread["items"], result["items"])
                self.assertEqual([source["state"] for source in reread["sources"]],
                                 ["ok", "ok", "failed" if name == "middle" else "ok", "ok", "ok"])

    def test_a_refresh_needs_this_pages_own_local_write_and_takes_no_options(self):
        network, app = self.app()
        with TestClient(app, base_url=BASE) as client:
            refused = [client.post("/api/inbox/refresh", content=b"{}"),
                       client.post("/api/inbox/refresh", content=b"{}", headers={**INBOX_HEADERS, "Origin": "https://evil.example"}),
                       client.post("/api/inbox/refresh", content=b"{}", headers={**INBOX_HEADERS, "Content-Type": "text/plain"}),
                       client.post("/api/inbox/refresh", content=b"{}", headers={**INBOX_HEADERS, "X-Second-Order-Inbox": "0"}),
                       client.post("/api/inbox/refresh", content=b'{"url": "https://example.org/feed"}', headers=INBOX_HEADERS),
                       client.post("/api/inbox/refresh", content=b"[]", headers=INBOX_HEADERS),
                       client.get("/api/inbox/refresh")]
            self.assertEqual([response.status_code for response in refused], [403, 403, 415, 403, 422, 422, 404])
            self.assertEqual(network.requests, [])
        with TestClient(app, base_url="http://attacker.example") as client:
            self.assertEqual(client.post("/api/inbox/refresh", content=b"{}",
                                         headers={**INBOX_HEADERS, "Origin": "http://attacker.example"}).status_code, 403)
        with TestClient(app, base_url=BASE) as client:
            done = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
            self.assertEqual((done.status_code, [o["outcome"] for o in done.json()["refreshed"]]), (200, ["ok"] * 5))
        self.assertEqual(network.urls(), ALL)

    def test_the_cache_survives_a_restart_and_reads_offline(self):
        _, app = self.app()
        with TestClient(app, base_url=BASE) as client:
            client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
            before = client.get("/api/inbox").json()
        offline, restarted = self.app(Network({}))
        with TestClient(restarted, base_url=BASE) as client:
            with patch("socket.create_connection", side_effect=AssertionError), patch("socket.getaddrinfo",
                                                                                       side_effect=AssertionError):
                self.assertEqual(client.get("/api/inbox").json(), before)
        self.assertEqual(offline.requests, [])

    def test_a_second_refresh_is_refused_while_one_is_running(self):
        started, release = threading.Event(), threading.Event()

        def slow(request: httpx.Request) -> httpx.Response:
            started.set()
            release.wait(10)
            return httpx.Response(200, content=rss([]), headers={"content-type": "text/xml"})

        network = Network(standard())
        app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews", self.root / "intake",
                         self.root / "attempts", inbox=self.inbox,
                         feeds=FeedFetcher(CONTACT, httpx.MockTransport(lambda request: slow(request)
                                                                        if str(request.url) == FED else network(request))))
        with TestClient(app, base_url=BASE) as client:
            first: dict = {}
            worker = threading.Thread(target=lambda: first.update(
                response=client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)))
            worker.start()
            self.assertTrue(started.wait(10))
            second = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
            release.set()
            worker.join(10)
        self.assertEqual((second.status_code, first["response"].status_code), (409, 200))
        self.assertIn("already running", second.json()["detail"])

    def test_a_refresh_never_changes_a_capture_already_saved_from_the_inbox(self):
        first = Network(standard())
        _, app = self.app(first)
        with TestClient(app, base_url=BASE) as client:
            client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS)
            item = client.get("/api/inbox").json()["items"][1]  # A Fed entry with a feed timestamp.
            suggestion = item["feed_timestamp"]["suggestion"]
            form = {"headline": item["title"], "source_url": item["link"],
                    "published_at": f"{suggestion['date']}T{suggestion['time']}{suggestion['offset']}",
                    "source_text": "Text the operator pasted from the release itself."}
            captured = client.post("/api/intake", content=json.dumps(form), headers=INTAKE_HEADERS)
            self.assertEqual(captured.status_code, 201)
            preview = captured.json()
        saved = fingerprint(self.root / "intake")
        changed = Network({**standard(), FED: [(200, rss([rss_item(1, title="Edited title in the feed",
                                                                   pub="Thu, 17 Sep 2026 18:00:00 GMT")]))]})
        _, app = self.app(changed)
        with TestClient(app, base_url=BASE) as client:
            refreshed = client.post("/api/inbox/refresh", content=b"{}", headers=INBOX_HEADERS).json()
            self.assertIn("Edited title in the feed", [entry["title"] for entry in refreshed["items"]])
            reopened = client.get(f"/api/intake/{preview['capture_id']}").json()
        self.assertEqual(fingerprint(self.root / "intake"), saved)
        self.assertEqual((reopened["request_sha256"], reopened["times"]), (preview["request_sha256"], preview["times"]))
        self.assertFalse((self.root / "attempts").exists())  # Nothing was sent, mocked or drafted by any of this.


if __name__ == "__main__":
    unittest.main()

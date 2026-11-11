"""Event Inbox: manually refreshed discovery of official releases and articles for the Tracker's Analyze an event form.

Five fixed feeds, each listed in its publisher's own feed catalogue and checked against its documentation, are the only
sources: the Federal Reserve Board's monetary-policy press releases (RSS), the Bureau of Labor Statistics' Employment
Situation and Consumer Price Index releases (Atom, served at .rss addresses), the Energy Information Administration's
Today in Energy articles (RSS) and the World Trade Organization's latest news (RSS). Each source states what kind of
entries it lists (a policy announcement, a statistical release, an analysis article or a news announcement); the two
newest also carry the credit their publishers' reuse terms ask for. Nothing else is ever fetched: no URL comes from a
request or a feed entry, redirects are not followed, and no linked article is downloaded (the WTO feed's full-article
content element is never read).

Two source-specific allowances are narrow and tested. The EIA feed declares ISO-8859-1, which only that source may do
(every other source must be UTF-8). The WTO feed stamps each entry with a date and a 00:00:00 placeholder time, so for
that source a midnight time is not offered as a time (`date_only`).

Reading (`inbox_view`) only reads the local cache: no network, no writes, no repair. Refreshing (`refresh`) is the one
explicit action, started by the operator; it requests each source once, sequentially, with no retry. Each source's
record is written atomically and keeps its last successful result, so a failed source keeps its earlier items and
never touches another source. A record that cannot be read is reported and left exactly as it is; it is neither
repaired nor refreshed over. A successful retrieval is also added to the source's local archive (see inbox_archive),
so entries that leave the feed stay available as retained history and changed entries keep their earlier versions.
Each accepted response's complete body is kept privately as this client received it, after undoing any content
encoding (see inbox_raw; the WTO feed's full-article content element stays in it, unread); nothing reads that copy to
build the inbox, and items and their fingerprints are unchanged by it. Every request a refresh makes, accepted or not, leaves one write-once acquisition record (see
inbox_acquisitions): endpoint, times, status, headers and cache validators, body completeness and SHA-256, parser
version, the entries it held and how they compared with what was held before. Records explicitly imported from a
retained snapshot (see inbox_imports) are listed apart, under "imported"; they are not feed entries and no refresh
touches them.

BLS's robot policy reserves the right to block automated requests that carry no way to contact their owner. The
operator's contact, from SECOND_ORDER_FEED_CONTACT, goes in the User-Agent; without one, the BLS sources are not
requested at all.

Feeds are untrusted. XML with a DTD or entity declarations is refused before parsing; titles and excerpts become
plain text; links must be https addresses on the publisher's own host. Publication information is the feed's own
timestamp, kept raw with the element it came from. It is not the release's verified publication time: a date, time
and offset are suggested only when the timestamp states them unambiguously, and the operator must check them against
the release. A US zone name that contradicts its date's daylight-saving status (EST in July, say) is ambiguous, like a
weekday that contradicts its date. Discovery is not analysis: nothing here captures, drafts, sends, freezes, evaluates
or scores anything.
"""
import codecs
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from email.utils import parsedate_tz
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import httpx

from . import feed_credits, html_markup, inbox_acquisitions, inbox_archive, inbox_imports, inbox_raw

INBOX_VERSION = "event-inbox-0.1"
VIEW_VERSION = "event-inbox-view-0.1"
PARSER_VERSION = "event-inbox-parser-0.1"  # parse_feed as of event-inbox-0.1; named in each acquisition record.
ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "data" / "event-inbox"  # Runtime cache; data/ is ignored by git.
RETAIN = 50  # Items kept per source from its latest successful retrieval, in the order the feed lists them.
MAX_LISTED = 200  # A feed listing more entries than this is refused as malformed.
MAX_BYTES = 1_000_000
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DEADLINE_SECONDS = 30  # The whole response, however slowly it trickles in.
MAX_TITLE = 300
MAX_EXCERPT = 1200
MAX_SKIPPED = 20  # How many skipped entries are described individually in a source's record.
CONTACT_ENV = "SECOND_ORDER_FEED_CONTACT"
USER_AGENT = "SecondOrder/0.1 (local research tool; feeds fetched only on an explicit manual refresh)"
ATOM = "{http://www.w3.org/2005/Atom}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"  # RSS 1.0 (the Bank of Canada's feed).
RSS1 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTACT = re.compile(r"[!-~](?:[ -~]{0,198}[!-~])?")  # Printable ASCII, no line breaks: safe in a header.
RFC3339 = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})")
# RFC 822 as RSS uses it: optional weekday, day, month name, four-digit year, time, and a zone token.
RFC822 = re.compile(r"(?:[A-Za-z]{3},\s*)?\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}(?::\d{2})?\s+([A-Za-z0-9+-]{1,5})")
# The zone names RFC 822 itself defines, in hours from UTC; any other name is ambiguous and is not interpreted.
RFC822_ZONES = {"UT": 0, "UTC": 0, "GMT": 0, "Z": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6,
                "PST": -8, "PDT": -7}
# US zone names checked against their region's daylight-saving rules (IANA zone, region): a name whose offset is not the
# region's offset at that instant contradicts the date. MST is not checked, because Arizona keeps MST all year.
US_ZONE_NAMES = {"EST": ("America/New_York", "Eastern"), "EDT": ("America/New_York", "Eastern"),
                 "CST": ("America/Chicago", "Central"), "CDT": ("America/Chicago", "Central"),
                 "MDT": ("America/Denver", "Mountain"),
                 "PST": ("America/Los_Angeles", "Pacific"), "PDT": ("America/Los_Angeles", "Pacific")}
LATIN_1 = codecs.lookup("iso-8859-1").name
C1_CONTROLS = re.compile("[\x80-\x9f]")  # Bytes 0x80 to 0x9F, decoded as ISO-8859-1.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SOURCE_STATES = ("never_refreshed", "ok", "failed", "not_requested", "unreadable")


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    publisher: str
    category: str  # The topic, shown as the entry's category.
    feed_url: str
    catalogue_url: str
    terms_url: str
    link_host: str
    contact_required: bool
    policy_url: str | None = None
    kind: str = "Statistical release"  # What the feed's entries are; only formal releases are statistical releases.
    attribution: str = ""  # The credit the publisher's reuse terms ask for, as verified; empty when none was checked.
    encodings: tuple[str, ...] = ("utf-8",)  # Declared encodings this source may use.
    date_only: bool = False  # Entries carry a date with a 00:00:00 placeholder time.
    keep_raw: bool = True  # Keep each accepted response's complete bytes privately (inbox_raw); storage only.
    full_text_element: bool = False  # Entries also carry a full-article element, which is never read.
    excerpts: bool = True  # Whether the feed's excerpts are kept; a publisher that allows headlines only says False.
    excluded_credits: tuple[str, ...] = ()  # feed_credits: creators whose entries are other publishers' work.
    excluded_markers: tuple[str, ...] = ()  # feed_credits: marks of another publisher's work in an entry's text.
    credit_creator: bool = False  # feed_credits: keep each entry's creator, as the publisher's licence asks.


SOURCES = {source.key: source for source in (
    Source("fed-monetary", "Federal Reserve: monetary policy press releases",
           "Board of Governors of the Federal Reserve System", "Monetary policy",
           "https://www.federalreserve.gov/feeds/press_monetary.xml", "https://www.federalreserve.gov/feeds/feeds.htm",
           "https://www.federalreserve.gov/disclaimer.htm", "www.federalreserve.gov", False, kind="Policy announcement"),
    Source("bls-empsit", "BLS: The Employment Situation", "U.S. Bureau of Labor Statistics", "Employment",
           "https://www.bls.gov/feed/empsit.rss", "https://www.bls.gov/feed/", "https://www.bls.gov/bls/linksite.htm",
           "www.bls.gov", True, "https://www.bls.gov/bls/pss.htm"),
    Source("bls-cpi", "BLS: Consumer Price Index", "U.S. Bureau of Labor Statistics", "Inflation",
           "https://www.bls.gov/feed/cpi.rss", "https://www.bls.gov/feed/", "https://www.bls.gov/bls/linksite.htm",
           "www.bls.gov", True, "https://www.bls.gov/bls/pss.htm"),
    # Verified 2026-10-08: listed at https://www.eia.gov/tools/rssfeeds/ (relative path on www.eia.gov), public domain
    # under https://www.eia.gov/about/copyrights_reuse.php with the credit "Source: U.S. Energy Information
    # Administration" and no logo. The feed declares ISO-8859-1; item links are https on www.eia.gov.
    Source("eia-todayinenergy", "EIA: Today in Energy", "U.S. Energy Information Administration", "Energy",
           "https://www.eia.gov/rss/todayinenergy.xml", "https://www.eia.gov/tools/rssfeeds/",
           "https://www.eia.gov/about/copyrights_reuse.php", "www.eia.gov", False, kind="Analysis article",
           attribution="Source: U.S. Energy Information Administration", encodings=("utf-8", "iso-8859-1")),
    # Verified 2026-10-08: listed as "All WTO news" at https://www.wto.org/english/res_e/webcas_e/rss_e.htm (the
    # catalogue gives the http address; the same path is served over https on the same host, without a redirect).
    # Dissemination is encouraged with the attribution "WTO news", without the WTO logo. Entries are dated with a
    # 00:00:00 GMT placeholder time; item links are https on www.wto.org.
    Source("wto-news", "WTO: Latest news", "World Trade Organization", "International trade",
           "https://www.wto.org/library/rss/latest_news_e.xml", "https://www.wto.org/english/res_e/webcas_e/rss_e.htm",
           "https://www.wto.org/english/info_e/copyrights_permissions_e.htm", "www.wto.org", False,
           kind="News announcement", attribution="WTO news", date_only=True, full_text_element=True),
)}
ALLOWED_URLS = frozenset(source.feed_url for source in SOURCES.values())
# Every offset the intake form accepts (-12:00 to +14:00 in 15-minute steps); a suggestion uses only these.
ACCEPTED_OFFSETS = frozenset(f"{'-' if minutes < 0 else '+'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
                             for minutes in range(-12 * 60, 14 * 60 + 1, 15))


class InboxRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class FetchFailed(Exception):
    """A source could not be retrieved; the message says why in plain words, with no closing full stop. ``response``
    and ``received`` say what did arrive (see inbox_acquisitions), when anything did."""

    def __init__(self, message: str, status: int | None = None, response: dict | None = None,
                 received: dict | None = None):
        super().__init__(message)
        self.status, self.response, self.received = status, response, received


class FeedRejected(Exception):
    """A response was retrieved but is not a feed this inbox accepts."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- fetching

@dataclass(frozen=True)
class Fetched:
    status: int
    content_type: str
    body: bytes
    response: dict | None = None  # Status line and kept headers (inbox_acquisitions.response_metadata).
    received: dict | None = None  # The body's completeness, size and SHA-256 (inbox_acquisitions.Received).


class FeedFetcher:
    """Requests one allowlisted feed once: no redirects, no retries, a timeout and a size cap.

    ``contact`` is the operator's contact for the User-Agent (BLS requires one); ``transport`` lets tests and the
    test server install a simulated network. It is chosen when the server starts, never through the API. ``allowed``
    is the fixed set of feed addresses it may request: the Event Inbox's five, or another registry's (news_feeds)."""

    def __init__(self, contact: str | None = None, transport: httpx.BaseTransport | None = None,
                 allowed: frozenset[str] = ALLOWED_URLS):
        if contact is not None and not CONTACT.fullmatch(contact):
            raise ValueError(f"{CONTACT_ENV} must be one line of printable text, at most 200 characters")
        self.contact = contact
        self.transport = transport
        self.allowed = allowed

    @classmethod
    def from_environment(cls) -> "FeedFetcher":
        contact = os.environ.get(CONTACT_ENV, "").strip() or None
        return cls(contact)

    def user_agent(self) -> str:
        return f"{USER_AGENT[:-1]}; contact: {self.contact})" if self.contact else USER_AGENT

    def fetch(self, url: str) -> Fetched:
        if url not in self.allowed:
            raise FetchFailed("Only the listed feeds can be requested")
        headers = {"User-Agent": self.user_agent(), "Accept": "application/rss+xml, application/atom+xml, "
                                                              "application/xml;q=0.9, text/xml;q=0.9"}
        seen: dict = {"response": None}
        received = inbox_acquisitions.Received()

        def failed(message: str, status: int | None = None) -> FetchFailed:
            return FetchFailed(message, status, seen["response"], received.summary(seen["response"]))

        try:
            with httpx.Client(transport=self.transport, timeout=TIMEOUT, follow_redirects=False, trust_env=False,
                              max_redirects=0) as client:
                with client.stream("GET", url, headers=headers) as response:
                    status = response.status_code
                    seen["response"], received.state = inbox_acquisitions.response_metadata(response), "not_read"
                    if response.is_redirect:
                        target = response.headers.get("location", "an unstated address")
                        raise failed(f"HTTP {status}: the feed redirects to {target[:200]}; redirects are not "
                                     "followed", status)
                    if status != 200:
                        raise failed(f"HTTP {status} from the publisher", status)
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise failed(f"The response declares {declared} bytes; the limit is {MAX_BYTES}", status)
                    chunks, deadline, received.state = [], time.monotonic() + DEADLINE_SECONDS, "partial"
                    for chunk in response.iter_bytes():
                        received.add(chunk)
                        if received.size > MAX_BYTES:
                            raise failed(f"The response exceeded {MAX_BYTES} bytes and was not read further", status)
                        if time.monotonic() > deadline:
                            raise failed(f"The response took longer than {DEADLINE_SECONDS} seconds to arrive", status)
                        chunks.append(chunk)
                    received.state = "complete"
                    return Fetched(status, response.headers.get("content-type", ""), b"".join(chunks),
                                   seen["response"], received.summary(seen["response"]))
        except httpx.TimeoutException:
            raise failed("The publisher did not answer in time") from None
        except httpx.HTTPError as exc:
            raise failed(f"The request failed ({type(exc).__name__})") from None


# ---------------------------------------------------------------- parsing

class _Text(HTMLParser):
    """Visible text of an HTML fragment; markup, scripts and styles are dropped, entities decoded."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "br", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str | None, html: bool, limit: int, part: str = "the text") -> tuple[str, bool]:
    """One line of plain text, control characters removed, at most `limit` characters (and whether it was cut).

    FeedRejected, naming `part`, if HTML cannot be read: a marked section html_markup does not read, such as `<![bogus[`
    or `<![ x`, checked before the parser, or a refusal html.parser itself still raises (AssertionError)."""
    if not value:
        return "", False
    if html:
        if html_markup.unreadable(value):
            raise FeedRejected(f"{part} has markup that cannot be read as plain text")
        parser = _Text()
        try:
            parser.feed(value)
            parser.close()
        except AssertionError:
            raise FeedRejected(f"{part} has markup that cannot be read as plain text") from None
        value = "".join(parser.parts)
    value = " ".join("".join(char if char.isprintable() else " " for char in value).split())
    return (value[:limit - 1].rstrip() + "…", True) if len(value) > limit else (value, False)


def official_link(value: str | None, source: Source) -> str:
    """The entry's link, if it is an https address on the publisher's own host; otherwise FeedRejected."""
    link = (value or "").strip()
    if not link:
        raise FeedRejected("no link")
    if len(link) > 500 or any(char.isspace() or not char.isprintable() for char in link):
        raise FeedRejected("a malformed link")
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        raise FeedRejected("a malformed link") from None
    if parts.scheme != "https":
        raise FeedRejected(f"a link that is not https ({parts.scheme or 'no scheme'})")
    if parts.hostname != source.link_host or parts.username or parts.password or port not in (None, 443):
        raise FeedRejected(f"a link outside {source.link_host}")
    if not parts.path or parts.path == "/":
        raise FeedRejected("a link to no particular page")
    return link


def feed_timestamp(raw: str | None, origin: str, rfc822: bool, date_only: bool = False) -> dict:
    """The feed's timestamp exactly as given, where it came from, and a suggestion only when it is unambiguous.

    A suggestion repeats the timestamp's own date, time and offset; nothing is converted to another zone. With
    `date_only` (a source that stamps entries with a 00:00:00 placeholder time), a midnight time gives no instant and
    no suggestion: the date is stated in the problem and no time is taken from it."""
    record = {"raw": raw, "origin": origin, "instant_utc": None, "suggestion": None, "problem": None}
    text = (raw or "").strip()
    if not text:
        record["problem"] = "The feed gives no timestamp for this entry."
        return record
    if rfc822:
        shape = RFC822.fullmatch(text)
        parsed = parsedate_tz(text) if shape else None
        if parsed is None:
            record["problem"] = "The feed's timestamp could not be read."
            return record
        year, month, day, hour, minute, second = parsed[:6]
        zone = shape.group(1)
        if re.fullmatch(r"[+-]\d{4}", zone) and zone != "-0000":
            if int(zone[1:3]) > 23 or int(zone[3:5]) > 59:
                record["problem"] = "The feed's timestamp gives an invalid UTC offset."
                return record
            offset = (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60)
        elif zone.upper() in RFC822_ZONES:
            offset = RFC822_ZONES[zone.upper()] * 3600
        else:
            record["problem"] = (f"The feed's timestamp gives the zone {zone}, which states no definite UTC offset, so "
                                 "its time is ambiguous.")
            return record
        try:
            local = datetime(year, month, day, hour, minute, second)
        except ValueError:
            record["problem"] = "The feed's timestamp is not a real date and time."
            return record
        named = re.match(r"\s*([A-Za-z]{3}),", text)
        if named and named.group(1).title() != WEEKDAYS[local.weekday()]:
            record["problem"] = (f"The feed's timestamp names {named.group(1)}, but {local.date()} is a "
                                 f"{WEEKDAYS[local.weekday()]}, so it is ambiguous.")
            return record
        fraction = None
    else:
        match = RFC3339.fullmatch(text)
        if not match:
            record["problem"] = ("The feed's timestamp is not a full date, time and UTC offset, so its time is "
                                 "ambiguous.")
            return record
        try:
            local = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}")
        except ValueError:
            record["problem"] = "The feed's timestamp is not a real date and time."
            return record
        zone = match.group(4)
        if zone == "-00:00":
            record["problem"] = "The feed's timestamp states no definite UTC offset, so its time is ambiguous."
            return record
        if zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
            record["problem"] = "The feed's timestamp gives an invalid UTC offset."
            return record
        offset = 0 if zone == "Z" else (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
        fraction = match.group(3)
    if date_only and local.time() == clock_time(0) and not (fraction or "").strip(".0"):
        record["problem"] = (f"The feed gives the date {local.date()} with a 00:00:00 placeholder time, which this "
                             "publisher puts on every entry, so it states no publication time.")
        return record
    sign = "-" if offset < 0 else "+"
    stated = f"{sign}{abs(offset) // 3600:02d}:{abs(offset) % 3600 // 60:02d}"
    try:
        moment = local.replace(tzinfo=timezone(timedelta(seconds=offset)))
        record["instant_utc"] = stamp(moment)
        region = US_ZONE_NAMES.get(zone.upper()) if rfc822 else None
        actual = moment.astimezone(ZoneInfo(region[0])).utcoffset() if region else None
    except (ValueError, OverflowError):
        record.update(instant_utc=None, problem="The feed's timestamp has no representable UTC instant.")
        return record
    if region and actual != moment.utcoffset():
        minutes = int(actual.total_seconds()) // 60
        record.update(instant_utc=None, problem=(
            f"The feed's timestamp names {zone.upper()} (UTC{stated}), but US {region[1]} time was "
            f"UTC{'-' if minutes < 0 else '+'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d} then, so the zone "
            "contradicts the date and its time is ambiguous."))
        return record
    if stated not in ACCEPTED_OFFSETS or abs(offset) % 60:
        record["problem"] = f"The feed's offset {stated} is not one the intake form accepts."
        return record
    record["suggestion"] = {"date": local.date().isoformat(), "time": local.strftime("%H:%M:%S"), "offset": stated,
                            "dropped_fraction": fraction}
    return record


def _child_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    return None if child is None else "".join(child.itertext())


def decoded(data: bytes, source: Source) -> tuple[str, str]:
    """The response as text, in the encoding its XML declaration names (UTF-8 when it names none), and that codec.

    Only the encodings the source lists are accepted: UTF-8 for every source, ISO-8859-1 for EIA alone. A byte-order
    mark means UTF-8. FeedRejected otherwise; nothing is guessed."""
    marked = data.startswith(codecs.BOM_UTF8)
    body = data[len(codecs.BOM_UTF8):] if marked else data
    declared = re.match(rb"\s*<\?xml[^>]*?encoding\s*=\s*[\"']([^\"']{1,40})[\"']", body)
    name = declared.group(1).decode("ascii", "replace") if declared else "UTF-8"
    accepted = {codecs.lookup(encoding).name: encoding.upper() for encoding in source.encodings}
    try:
        codec = codecs.lookup(name).name
    except LookupError:
        codec = None
    if codec not in accepted or (marked and codec != "utf-8"):
        raise FeedRejected(f"The response declares the {name} encoding; only {' or '.join(accepted.values())} is "
                           "accepted")
    try:
        return body.decode(codec), codec
    except UnicodeDecodeError:
        raise FeedRejected(f"The response is not {accepted[codec]} text") from None


def parser_version(source: Source) -> str:
    """The parser version a source's entries are read by: 0.2 only where the source uses feed_credits' rules."""
    return feed_credits.VERSION if feed_credits.uses_credits(source) else PARSER_VERSION


def parse_feed(data: bytes, source: Source) -> dict:
    """The entries of one feed response, checked and reduced to plain metadata. FeedRejected if it is not a feed."""
    text, codec = decoded(data, source)
    if re.search(r"<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST)", text, re.IGNORECASE):
        raise FeedRejected("The response contains a document type or entity declaration, which is refused")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedRejected(f"The response is not well-formed XML ({exc})") from None
    if root.tag == "rss" and root.find("channel") is not None:
        kind, entries = "rss", root.find("channel").findall("item")
    elif root.tag == f"{ATOM}feed":
        kind, entries = "atom", root.findall(f"{ATOM}entry")
    elif root.tag == f"{RDF}RDF" and root.find(f"{RSS1}channel") is not None:
        kind, entries = "rss1", root.findall(f"{RSS1}item")
    else:
        raise FeedRejected(f"The response is neither RSS 2.0, RSS 1.0 nor Atom (its root is {root.tag[:60]})")
    if len(entries) > MAX_LISTED:
        raise FeedRejected(f"The feed lists {len(entries)} entries; at most {MAX_LISTED} are accepted")
    items, skipped, seen, duplicates = [], [], set(), 0
    for position, entry in enumerate(entries, start=1):
        try:
            if kind == "rss1":
                title_raw, title_html = _child_text(entry, f"{RSS1}title"), False
                link = official_link(_child_text(entry, f"{RSS1}link"), source)
                identity = (entry.get(f"{RDF}about") or "").strip() or link
                excerpt_raw, excerpt_html = _child_text(entry, f"{RSS1}description"), True
                timestamp = feed_timestamp(_child_text(entry, f"{DC}date"), "RSS 1.0 dc:date", rfc822=False,
                                           date_only=source.date_only)
            elif kind == "rss":
                title_raw, title_html = _child_text(entry, "title"), False
                link = official_link(_child_text(entry, "link"), source)
                identity = (_child_text(entry, "guid") or "").strip() or link
                excerpt_raw, excerpt_html = _child_text(entry, "description"), True
                timestamp = feed_timestamp(_child_text(entry, "pubDate"), "RSS pubDate", rfc822=True,
                                           date_only=source.date_only)
            else:
                title_element = entry.find(f"{ATOM}title")
                title_raw = None if title_element is None else "".join(title_element.itertext())
                title_html = title_element is not None and title_element.get("type") == "html"
                links = [element for element in entry.findall(f"{ATOM}link")
                         if element.get("rel") in (None, "alternate")]
                link = official_link(links[0].get("href") if links else None, source)
                identity = (_child_text(entry, f"{ATOM}id") or "").strip() or link
                body = entry.find(f"{ATOM}content")
                body = body if body is not None else entry.find(f"{ATOM}summary")
                excerpt_raw = None if body is None else "".join(body.itertext())
                excerpt_html = body is not None and body.get("type") == "html"
                published = _child_text(entry, f"{ATOM}published")
                timestamp = (feed_timestamp(published, "Atom published", rfc822=False, date_only=source.date_only)
                             if published is not None else
                             feed_timestamp(_child_text(entry, f"{ATOM}updated"), "Atom updated (the entry has no "
                                            "published element)", rfc822=False, date_only=source.date_only))
            if codec == LATIN_1 and any(C1_CONTROLS.search(part or "") for part in (title_raw, excerpt_raw)):
                # Bytes 0x80 to 0x9F are not printable in ISO-8859-1 (they are often Windows-1252 punctuation); rather
                # than guess, or silently drop characters from the headline, the entry is skipped.
                raise FeedRejected("text with bytes 0x80 to 0x9F, which ISO-8859-1 does not print; it is not guessed")
            title, title_cut = plain_text(title_raw, title_html, MAX_TITLE, "the title")
            if not title:
                raise FeedRejected("no title")
            excerpt, excerpt_cut = plain_text(excerpt_raw, excerpt_html, MAX_EXCERPT, "the excerpt")                 if source.excerpts else ("", False)
            if len(identity) > 500:
                raise FeedRejected("an identifier longer than 500 characters")
            creator = feed_credits.creator(entry, kind) if (source.excluded_credits or source.credit_creator) else None
            excluded = feed_credits.excluded(entry, kind, creator, source)
            if excluded:
                raise FeedRejected(excluded)
        except FeedRejected as problem:  # One unusable entry is skipped and counted; the others are still read.
            skipped.append({"position": position, "reason": f"Skipped: {problem}"})
            continue
        if identity in seen:  # The same entry listed twice: the first listing is kept.
            duplicates += 1
            continue
        seen.add(identity)
        items.append({"id": f"{source.key}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}",
                      "identity": identity, "position": position, "title": title, "title_truncated": title_cut,
                      "link": link, "excerpt": excerpt or None, "excerpt_truncated": excerpt_cut,
                      "excerpt_repeats_title": excerpt == title, "feed_timestamp": timestamp,
                      **({"creator": creator} if source.credit_creator else {})})
    return {"format": kind, "listed": len(entries), "items": items[:RETAIN], "not_retained": max(0, len(items) - RETAIN),
            "duplicates": duplicates, "skipped": skipped[:MAX_SKIPPED], "skipped_count": len(skipped)}


# ---------------------------------------------------------------- the local cache

def _record_path(inbox: Path, key: str) -> Path:
    return inbox / f"{key}.json"


def read_record(inbox: Path, key: str, source: Source | None = None) -> tuple[str, dict | None, str | None]:
    """("missing" | "ok" | "unreadable", record, problem). Reads only; an unreadable record is never repaired.
    ``source`` is the record's source when it is not one of the Event Inbox's own (a publisher feed, news_feeds)."""
    path = _record_path(inbox, key)
    if not path.exists():
        return "missing", None, None
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unreadable", None, "The local record is not readable JSON"
    problem = _record_problem(record, key, source or SOURCES[key])
    return ("unreadable", None, problem) if problem else ("ok", record, None)


RECORD_FIELDS = {"inbox_version", "source", "feed_url", "last_success", "last_attempt"}
SUCCESS_FIELDS = {"retrieved_at", "http_status", "content_type", "bytes", "sha256", "format", "listed", "not_retained",
                  "duplicates", "skipped", "skipped_count", "items"}
ITEM_FIELDS = {"id", "identity", "position", "title", "title_truncated", "link", "excerpt", "excerpt_truncated",
               "excerpt_repeats_title", "feed_timestamp", "first_seen_at"}
TIMESTAMP_FIELDS = {"raw", "origin", "instant_utc", "suggestion", "problem"}
ATTEMPT_FIELDS = {"started_at", "finished_at", "outcome", "detail", "http_status"}


def _moment_or_none(value: object) -> bool:
    if value is None:
        return True
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _record_problem(record: object, key: str, source: Source) -> str | None:
    """Why a cached record cannot be trusted, or None. Every field the view uses is checked."""
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        return "The local record does not have the expected fields"
    if (record["inbox_version"], record["source"], record["feed_url"]) != (INBOX_VERSION, key, source.feed_url):
        return "The local record names another version, source or feed"
    success, attempt = record["last_success"], record["last_attempt"]
    if success is not None:
        if not isinstance(success, dict) or set(success) != SUCCESS_FIELDS or not isinstance(success["items"], list) \
                or success["retrieved_at"] is None or not _moment_or_none(success["retrieved_at"]) or \
                len(success["items"]) > RETAIN or success["format"] not in ("rss", "atom", "rss1"):
            return "The local record's last successful result is malformed"
        fields = ITEM_FIELDS | ({"creator"} if source.credit_creator else set())
        for item in success["items"]:
            if not isinstance(item, dict) or set(item) != fields or not all(isinstance(item[field], str) for field in (
                    "id", "identity", "title", "link")) or type(item["position"]) is not int or \
                    item["first_seen_at"] is None or not _moment_or_none(item["first_seen_at"]) or \
                    not (item["excerpt"] is None or isinstance(item["excerpt"], str)) or \
                    not (item.get("creator") is None or isinstance(item["creator"], str)):
                return "The local record holds a malformed item"
            stamp_record = item["feed_timestamp"]
            if not isinstance(stamp_record, dict) or set(stamp_record) != TIMESTAMP_FIELDS or \
                    not _moment_or_none(stamp_record["instant_utc"]) or \
                    not (stamp_record["suggestion"] is None or isinstance(stamp_record["suggestion"], dict)):
                return "The local record holds an item with a malformed timestamp"
            try:
                official_link(item["link"], source)
            except FeedRejected:
                return "The local record holds an item whose link is not an official address"
    if not isinstance(attempt, dict) or set(attempt) != ATTEMPT_FIELDS or \
            attempt["outcome"] not in ("ok", "failed", "not_requested") or attempt["started_at"] is None or \
            not _moment_or_none(attempt["started_at"]) or not _moment_or_none(attempt["finished_at"]):
        return "The local record's last attempt is malformed"
    if attempt["outcome"] == "ok" and success is None:
        return "The local record reports a successful attempt without its result"
    return None


def _write_record(inbox: Path, key: str, record: dict) -> None:
    """Atomically replaces one source's record: the old record stays intact until the new one is complete."""
    inbox.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=f".{key}-", suffix=".tmp", dir=inbox)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, _record_path(inbox, key))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def refresh_source(source: Source, fetcher: FeedFetcher, inbox: Path, clock: Callable[[], datetime] = now) -> dict:
    """One explicit attempt for one source; returns what happened. Its previous good result is kept on any failure.
    A request that was made, accepted or not, leaves one acquisition record (inbox_acquisitions)."""
    state, record, problem = read_record(inbox, source.key, source)
    if state == "unreadable":
        return {"source": source.key, "outcome": "skipped_unreadable", "acquisition": None,
                "detail": f"{problem}; it was left unchanged and not refreshed. Move it aside to refresh this source."}
    previous = record["last_success"] if record else None
    started = stamp(clock())
    attempt = {"started_at": started, "finished_at": None, "outcome": "failed", "detail": None, "http_status": None}
    success, fetched, failure, parsed = previous, None, None, None
    if source.contact_required and not fetcher.contact:
        attempt.update(outcome="not_requested", finished_at=started,
                       detail=(f"Not requested: the {source.publisher} robot policy reserves the right to block "
                               "automated requests that carry no contact for their owner, so this source is "
                               f"requested only with yours. Set {CONTACT_ENV} and restart the server."))
    else:
        try:
            fetched = fetcher.fetch(source.feed_url)
            attempt["http_status"] = fetched.status
            if fetched.content_type.split(";")[0].strip().lower() == "text/html":
                raise FeedRejected("The publisher answered with a web page, not a feed")
            parsed = parse_feed(fetched.body, source)
            retrieved = stamp(clock())
            seen_before = {item["identity"]: item["first_seen_at"] for item in (previous or {}).get("items", [])}
            items = [{**item, "first_seen_at": seen_before.get(item["identity"], retrieved)} for item in parsed["items"]]
            success = {"retrieved_at": retrieved, "http_status": fetched.status, "content_type": fetched.content_type,
                       "bytes": len(fetched.body), "sha256": hashlib.sha256(fetched.body).hexdigest(),
                       **{key: parsed[key] for key in ("format", "listed", "not_retained", "duplicates", "skipped",
                                                       "skipped_count")}, "items": items}
            attempt.update(outcome="ok", finished_at=retrieved)
        except FetchFailed as exc:
            failure = exc
            hint = (f" {source.publisher} may block automated requests under its robot policy; see "
                    f"{source.policy_url}." if source.policy_url and exc.status == 403 else "")
            attempt.update(finished_at=stamp(clock()), detail=f"{exc}.{hint}", http_status=exc.status)
        except FeedRejected as exc:
            attempt.update(finished_at=stamp(clock()), detail=f"The response was not accepted: {exc}")
    _write_record(inbox, source.key, {"inbox_version": INBOX_VERSION, "source": source.key,
                                      "feed_url": source.feed_url, "last_success": success, "last_attempt": attempt})
    if attempt["outcome"] == "not_requested":  # No request was made, so there is nothing to record about one.
        return {"source": source.key, "outcome": "not_requested", "detail": attempt["detail"], "acquisition": None}
    accepted, notes, found, kept = attempt["outcome"] == "ok", [], None, None
    if accepted:  # Only a successful retrieval is archived and kept, after its record is in place.
        note, found = _archive(inbox, source, previous, success["items"], success["retrieved_at"])
        notes.append(note)
        if source.keep_raw:
            kept, note = _keep_raw(inbox, source, fetched.body)
            notes.append(note)
    notes = [note for note in notes if note]
    acquisition, note = _acquisition(inbox, source, fetcher, attempt, fetched, failure, parsed if accepted else None,
                                     success["items"] if accepted else [], found, kept, notes)
    detail = " ".join(part for part in (attempt["detail"], *notes, note) if part) or None
    return {"source": source.key, "outcome": attempt["outcome"], "detail": detail, "acquisition": acquisition}


def _is_official(link: str, source: Source) -> bool:
    try:
        official_link(link, source)
        return True
    except FeedRejected:
        return False


def _keep_raw(inbox: Path, source: Source, body: bytes) -> tuple[str | None, str | None]:
    """Keep the complete response privately: its file name, or a note. A failure is never a failed refresh."""
    try:
        return inbox_raw.keep_bytes(inbox, source.key, body), None
    except OSError as exc:
        return None, (f"The entries were refreshed, but the complete response could not be kept privately "
                      f"({type(exc).__name__}).")


def _archive(inbox: Path, source: Source, previous: dict | None, items: list[dict],
             retrieved_at: str) -> tuple[str | None, dict]:
    """Add one successful retrieval to the source's archive (see inbox_archive): a note if that could not be done, and
    how its entries compare with what was held before (inbox_acquisitions.changes)."""
    state, archive, problem = inbox_archive.read_archive(inbox, source.key, source.feed_url,
                                                         lambda link: _is_official(link, source),
                                                         creator=source.credit_creator)
    found = inbox_acquisitions.changes(archive, previous, items)
    if state == "unreadable":
        return (f"The entries were refreshed, but the local archive of earlier entries cannot be read ({problem}); it "
                "was left unchanged and nothing was added to it."), found
    try:
        inbox_archive.write_archive(inbox, source.key, inbox_archive.updated_archive(
            archive, source.key, source.feed_url, previous, items, retrieved_at))
    except OSError as exc:
        return (f"The entries were refreshed, but the local archive could not be written ({type(exc).__name__}); the "
                "earlier archive, if any, is unchanged."), found
    return None, found


def _acquisition(inbox: Path, source: Source, fetcher: FeedFetcher, attempt: dict, fetched: Fetched | None,
                 failure: FetchFailed | None, parsed: dict | None, items: list[dict], found: dict | None,
                 kept: str | None, notes: list[str]) -> tuple[dict | None, str | None]:
    """Record the request that was made (inbox_acquisitions): its summary, or a note if it could not be recorded."""
    if fetched is not None:
        response, body = fetched.response, fetched.received or {
            "state": "complete", "bytes": len(fetched.body), "sha256": hashlib.sha256(fetched.body).hexdigest(),
            "declared_bytes": None, "content_encoding": None}
    else:
        response = failure.response if failure else None
        body = (failure.received if failure else None) or inbox_acquisitions.Received().summary(response)
    outcome = "accepted" if attempt["outcome"] == "ok" else "refused" if fetched is not None else "failed"
    try:  # Recording never fails a refresh or stops the other sources: a problem here is a note.
        record = inbox_acquisitions.build(source.key, source.feed_url, attempt["started_at"], attempt["finished_at"],
                                          outcome, attempt["detail"], bool(fetcher.contact), response, body, parsed,
                                          parser_version(source), items, found, kept, notes)
        number = inbox_acquisitions.keep(inbox, source.key, record)
        return inbox_acquisitions.summary(inbox, {**record, "number": number}), None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"The request was made, but its retrieval record could not be written ({type(exc).__name__})."


def refresh(inbox: Path, fetcher: FeedFetcher, clock: Callable[[], datetime] = now) -> dict:
    """The explicit refresh: each source once, in order, with no retry. Returns the outcomes and the new view."""
    outcomes = [refresh_source(source, fetcher, inbox, clock) for source in SOURCES.values()]
    return {**inbox_view(inbox), "refreshed": outcomes}


def inbox_view(inbox: Path) -> dict:
    """What the Tracker shows: each source's state and its latest recorded request (inbox_acquisitions), the entries of
    its latest retrieval (newest feed timestamp first), and the retained entries its archive holds that are no longer in
    that retrieval. Each entry says which of its texts the feed supplied and whether they were shortened. Reads only."""
    sources, items, retained = [], [], []
    for order, source in enumerate(SOURCES.values()):
        state, record, problem = read_record(inbox, source.key)
        success = record["last_success"] if record else None
        attempt = record["last_attempt"] if record else None
        shown = ("never_refreshed" if state == "missing" else "unreadable" if state == "unreadable"
                 else {"ok": "ok", "failed": "failed", "not_requested": "not_requested"}[attempt["outcome"]])
        archive_state, archive, archive_problem = inbox_archive.read_archive(
            inbox, source.key, source.feed_url, lambda link, source=source: _is_official(link, source))
        current = (success or {}).get("items", [])
        kept = inbox_archive.retained_items(archive, {item["id"] for item in current})
        sources.append({
            "key": source.key, "label": source.label, "publisher": source.publisher, "category": source.category,
            "kind": source.kind, "attribution": source.attribution, "feed_url": source.feed_url, "catalogue_url": source.catalogue_url, "terms_url": source.terms_url,
            "policy_url": source.policy_url, "contact_required": source.contact_required, "state": shown,
            "problem": problem, "last_attempt": attempt,
            "last_success": None if success is None else {key: success[key] for key in (
                "retrieved_at", "http_status", "format", "listed", "not_retained", "duplicates", "skipped",
                "skipped_count", "sha256", "bytes")} | {"item_count": len(success["items"])},
            "archive": {"state": archive_state, "problem": archive_problem,
                        "entries": len((archive or {}).get("entries", [])),
                        "versions": sum(len(entry["versions"]) for entry in (archive or {}).get("entries", [])),
                        "retained": len(kept)},
            "full_text_element": source.full_text_element,
            "acquisitions": inbox_acquisitions.latest(inbox, source.key, source.feed_url)})
        # content_sha256 is the entry version's identity (inbox_archive): what an explicit capture origin binds to.
        for item in current:
            items.append((order, {**{key: value for key, value in item.items() if key != "identity"},
                                  "source": source.key, "publisher": source.publisher, "category": source.category,
                                  "kind": source.kind, "attribution": source.attribution,
                                  "retrieved_at": success["retrieved_at"], "stale": shown != "ok",
                                  "content_sha256": inbox_archive.content_sha256(item),
                                  "text": inbox_acquisitions.text_parts(item)}))
        for item in kept:  # From the archive: when it was last seen in the feed is its retrieval time.
            retained.append((order, {**item, "content_sha256": inbox_archive.content_sha256(item),
                                     "position": None, "source": source.key, "publisher": source.publisher,
                                     "category": source.category, "kind": source.kind,
                                     "attribution": source.attribution, "retrieved_at": item["last_seen_at"],
                                     "stale": False, "history": True, "text": inbox_acquisitions.text_parts(item)}))
    # Known instants first, newest first; then entries without a usable timestamp; ties by source, then feed order.
    def order_key(pair: tuple[int, dict]) -> tuple:
        instant = pair[1]["feed_timestamp"]["instant_utc"]
        return (instant is None, -datetime.fromisoformat(instant).timestamp() if instant else 0.0, pair[0],
                pair[1]["position"] or 0, pair[1]["id"])

    items.sort(key=order_key)
    retained.sort(key=order_key)
    imported, imports = inbox_imports.items(inbox)
    return {"view_version": VIEW_VERSION, "imported": imported, "imports": imports, "retention": {
        "per_source": RETAIN, "statement": (f"Each source keeps at most {RETAIN} entries from its latest successful "
                                            "refresh, in the order its feed lists them. Entries that leave a feed "
                                            "leave this list but stay in the local archive as retained history; "
                                            "nothing there expires or is deleted.")},
            "sources": sources, "items": [item for _, item in items], "retained": [item for _, item in retained]}

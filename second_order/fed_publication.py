"""The text of one Federal Reserve Board press release page (fed-press-release-extract-0.1).

Reads the bytes of a page retained by publication_import and returns what the release itself says, in its own words
and order: the printed date, the title, the printed release time when there is one, and the body's paragraphs and list
items. Nothing is executed, fetched or guessed. The page must be UTF-8 (the header's and the page's declared charset,
when present, must say so) and must have the press-release layout: a `div#article` with its `p.article__time` date,
`h3.title` title and a body column. Anything else is refused as unreadable, so the user can paste the text instead.

Some lines are left out and listed, never silently dropped: the share controls, a contact line whose address the site
obfuscates (its text would not be the publisher's words), a line that is only a link to another document (named as a
linked document, not retrieved) and the page's "Last Update" line. A body holding a table is refused rather than
flattened. The text is never cut: a release longer than the source limit is refused whole.
"""
from datetime import date, datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

EXTRACTOR_VERSION = "fed-press-release-extract-0.1"
PAGE_HOST = "https://www.federalreserve.gov"
MAX_CHARACTERS = 50_000  # The user source limit (model_draft.MAX_SOURCE_CHARS); a longer release is refused whole.
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
PRINTED_DATE = re.compile(rf"({'|'.join(MONTHS)}) (\d{{1,2}}), (\d{{4}})")
RELEASE_TIME = re.compile(r"For release at (\d{1,2}):(\d{2}) ([ap])\.m\. (EDT|EST)")
BODY_CLASSES = {"col-xs-12", "col-sm-8", "col-md-8"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HIDDEN = {"script", "style", "noscript", "template", "svg"}
# HTML closes an open <p> when one of these starts (its end tag may be omitted), as browsers do; the Board's pages rely on
# it (an unclosed p.releaseTime followed by the share list). html.parser does not, so it is done here.
CLOSES_P = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figcaption", "figure",
            "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
            "p", "pre", "section", "table", "ul"}
P_SCOPE = {"table", "td", "th", "caption", "button", "template", "object", "html"}  # An open p outside these stays.
CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_-]{1,40})", re.IGNORECASE)


class Unreadable(ValueError):
    """The page is not a Federal Reserve press release this extractor reads; the message says why, for the user."""


def _classes(attrs: dict) -> set[str]:
    return set((attrs.get("class") or "").split())


def _clean(text: str) -> str:
    return " ".join("".join(char if char.isprintable() else " " for char in text).split())


class _Page(HTMLParser):
    """Collects the article's parts while tracking which element each piece of text sits in."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.parts: dict[str, list[str]] = {"date": [], "title": [], "release": [], "last_update": []}
        self.blocks: list[dict] = []  # Body paragraphs and list items, in order.
        self.block: dict | None = None
        self.share = False
        self.tables = 0
        self.articles = 0

    def _inside(self, test) -> bool:
        return any(test(tag, attrs) for tag, attrs in self.stack)

    def _in_article(self) -> bool:
        return self._inside(lambda tag, attrs: tag == "div" and attrs.get("id") == "article")

    def _in_body(self) -> bool:
        return self._in_article() and self._inside(
            lambda tag, attrs: tag == "div" and _classes(attrs) == BODY_CLASSES)

    def _hidden(self) -> bool:
        return self._inside(lambda tag, attrs: tag in HIDDEN)

    def _close(self, index: int) -> None:
        """Close the element at `index` and everything opened inside it, finishing the block it ends."""
        if self.block is not None and index == self.block["depth"] - 1 and self.stack[index][0] == self.block["tag"]:
            self.blocks.append(self.block)
            self.block = None
        del self.stack[index:]

    def _implied_ends(self, tag: str) -> None:
        """The end tags HTML lets a page omit: an open p before a block, an open li before the next item."""
        if tag in CLOSES_P:
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] in P_SCOPE:
                    break
                if self.stack[index][0] == "p":
                    self._close(index)
                    break
        if tag == "li":
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] in ("ul", "ol"):
                    break
                if self.stack[index][0] == "li":
                    self._close(index)
                    break

    def handle_starttag(self, tag, attrs):
        attrs = {name: value or "" for name, value in attrs}
        self._implied_ends(tag)
        if tag in VOID:
            if tag == "br" and self.block is not None:
                self.block["text"].append(" ")
            return
        self.stack.append((tag, attrs))
        if tag == "div" and attrs.get("id") == "article":
            self.articles += 1
        if not self._in_article():
            return
        if "share" in _classes(attrs):
            self.share = True
        if self._in_body():
            if tag == "table":
                self.tables += 1
            elif tag in ("p", "li") and self.block is None:
                self.block = {"tag": tag, "text": [], "links": [], "obfuscated": False, "depth": len(self.stack)}
            elif tag == "a" and self.block is not None:
                href = attrs.get("href", "")
                if "email-protection" in href:
                    self.block["obfuscated"] = True
                self.block["links"].append({"href": href, "text": []})
            elif tag == "span" and "__cf_email__" in _classes(attrs) and self.block is not None:
                self.block["obfuscated"] = True

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # Close up to the matching element; stray end tags are ignored, as a browser would.
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self._close(index)
                return

    def handle_data(self, data):
        if self._hidden():
            return
        for tag, attrs in reversed(self.stack):
            if tag == "div" and attrs.get("id") == "lastUpdate":
                self.parts["last_update"].append(data)
                return
        if not self._in_article():
            return
        top = self.stack[-1] if self.stack else ("", {})
        if self._inside(lambda tag, attrs: tag == "p" and "article__time" in _classes(attrs)):
            self.parts["date"].append(data)
        elif self._inside(lambda tag, attrs: tag == "h3" and "title" in _classes(attrs)):
            self.parts["title"].append(data)
        elif self._inside(lambda tag, attrs: tag == "p" and "releaseTime" in _classes(attrs)):
            self.parts["release"].append(data)
        elif self.block is not None:
            self.block["text"].append(data)
            if top[0] == "a" or self._inside(lambda tag, attrs: tag == "a"):
                if self.block["links"]:
                    self.block["links"][-1]["text"].append(data)


def decode(raw: bytes, content_type: str) -> str:
    """The page as text: UTF-8 only, as the header and the page declare it. Unreadable otherwise; nothing is guessed."""
    declared = re.search(r"charset\s*=\s*\"?([A-Za-z0-9_-]{1,40})", content_type or "", re.IGNORECASE)
    if declared and declared.group(1).lower().replace("_", "-") not in ("utf-8", "utf8"):
        raise Unreadable(f"The page declares the {declared.group(1)} encoding; only UTF-8 is read")
    meta = CHARSET.search(raw[:4096])
    if meta and meta.group(1).decode("ascii").lower().replace("_", "-") not in ("utf-8", "utf8"):
        raise Unreadable(f"The page declares the {meta.group(1).decode('ascii')} encoding; only UTF-8 is read")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("The page is not UTF-8 text") from None


def printed_date(text: str) -> date | None:
    match = PRINTED_DATE.fullmatch(text)
    if not match:
        return None
    try:
        return date(int(match.group(3)), MONTHS.index(match.group(1)) + 1, int(match.group(2)))
    except ValueError:
        return None


def release_time(text: str) -> dict | None:
    """A printed release time: hour and minute on a 24-hour clock and the zone name as printed."""
    match = RELEASE_TIME.fullmatch(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (1 <= hour <= 12 and minute < 60):
        return None
    hour = hour % 12 + (12 if match.group(3) == "p" else 0)
    return {"hour": hour, "minute": minute, "zone": match.group(4)}


def extract(raw: bytes, content_type: str) -> dict:
    """The release as printed: its parts, the kept paragraphs, what was left out and the linked documents."""
    page = _Page()
    try:
        page.feed(decode(raw, content_type))
        page.close()
    except AssertionError:  # html.parser refuses some malformed declarations this way (see _markupbase).
        raise Unreadable("The page has markup that cannot be read") from None
    if page.articles != 1:
        raise Unreadable("The page does not have the press-release layout this import reads (one article block)")
    date_line, title = _clean("".join(page.parts["date"])), _clean("".join(page.parts["title"]))
    release_line = _clean("".join(page.parts["release"])) or None
    stated = printed_date(date_line)
    if not title or stated is None:
        raise Unreadable("The page does not print a release title and date in the press-release layout")
    timing = release_time(release_line) if release_line else None
    if release_line and timing is None:
        raise Unreadable(f"The page prints a release time this import does not read ({release_line[:80]})")
    if page.tables:
        raise Unreadable("The release body holds a table, which this import does not flatten into text")
    kept, left_out, linked = [], [], []
    if page.share:
        left_out.append({"kind": "share_controls", "text": "Share"})
    for block in page.blocks:
        text = _clean("".join(block["text"]))
        if not text:
            continue
        link_text = [_clean("".join(link["text"])) for link in block["links"]]
        if block["obfuscated"]:
            left_out.append({"kind": "contact_line", "text": text})
        elif len(block["links"]) == 1 and link_text[0] == text and block["links"][0]["href"]:
            url = urljoin(PAGE_HOST + "/", block["links"][0]["href"])
            linked.append({"title": text, "url": url})
            left_out.append({"kind": "linked_document", "text": text})
        else:
            kept.append(f"- {text}" if block["tag"] == "li" else text)
    if not kept:
        raise Unreadable("The page's release body holds no text")
    last_update = _clean("".join(page.parts["last_update"])) or None
    if last_update:
        left_out.append({"kind": "last_update", "text": last_update})
    lines = [date_line, title, *([release_line] if release_line else []), *kept]
    text = "\n\n".join(lines)
    if len(text) > MAX_CHARACTERS:
        raise Unreadable(f"The release has {len(text):,} characters; a source holds at most {MAX_CHARACTERS:,}, and "
                         "the text is never cut")
    return {"extractor": EXTRACTOR_VERSION, "title": title, "date_line": date_line, "date": stated.isoformat(),
            "release_line": release_line, "release_time": timing, "paragraphs": len(kept), "text": text,
            "characters": len(text), "left_out": left_out, "linked_documents": linked, "last_update": last_update}


def printed_instant(extracted: dict) -> datetime | None:
    """The printed date and release time as an instant in New York, when the page prints a time. The zone name must be
    the one New York uses on that date (EDT in daylight saving, EST otherwise); otherwise None."""
    from zoneinfo import ZoneInfo
    timing = extracted["release_time"]
    if timing is None:
        return None
    local = datetime.combine(date.fromisoformat(extracted["date"]), datetime.min.time()).replace(
        hour=timing["hour"], minute=timing["minute"], tzinfo=ZoneInfo("America/New_York"))
    named = "EDT" if local.dst() else "EST"
    return local if named == timing["zone"] else None

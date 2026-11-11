"""The text of an official publication page, read from its own HTML by a layout checked for its publisher
(official-page-text-0.1).

Each publisher's layout names the element that holds the publication (its container), the parts inside it that are not
the publication (navigation, share buttons, figures and their data notes, the page's own title block), where its title
and printed date are, and nothing else: no script is executed, nothing is fetched, nothing is guessed. The text is the
container's paragraphs, list items and headings, in their order, each a block; a table is left out and named rather than
flattened. A page that is not UTF-8, lacks the layout, or holds too little text is refused as unreadable, with the
reason, so the material says the text could not be read instead of carrying something else. A text longer than
MAX_CHARACTERS is kept to the last whole block that fits and marked partial.

The Federal Reserve Board's press releases are read by fed_publication, the extractor the user import already relies
on; ``fed_release`` adapts its result to the same shape. A European Commission press-corner page is drawn by a script,
so ``ec_document`` reads what its documents service answers for it (JSON holding the title, date and HTML body) with
the same block reader.
"""
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re

from . import fed_publication

TEXT_VERSION = "official-page-text-0.1"
MAX_CHARACTERS = 60_000
MIN_CHARACTERS = 200
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HIDDEN = {"script", "style", "noscript", "template", "svg", "button", "form", "iframe", "select", "nav"}
BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "div", "ul", "ol", "dd", "dt", "section",
          "article", "figure", "header", "footer", "pre", "tr"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SPACE = re.compile(r"\s+")
CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_-]{1,40})", re.IGNORECASE)


class Unreadable(ValueError):
    """The page is not one this layout reads; the message says why."""


@dataclass(frozen=True)
class Match:
    """An element: its tag, and a class token or an id it must carry (either may be None)."""
    tag: str
    css_class: str | None = None
    element_id: str | None = None

    def fits(self, tag: str, attrs: dict) -> bool:
        if tag != self.tag:
            return False
        if self.css_class is not None and self.css_class not in (attrs.get("class") or "").split():
            return False
        return self.element_id is None or attrs.get("id") == self.element_id


@dataclass(frozen=True)
class Layout:
    key: str  # The extractor's version, recorded with every text it read.
    container: Match
    title: Match
    skip: tuple[Match, ...] = ()
    date: Match | None = None
    date_attribute: str | None = None  # Read the printed date from this attribute instead of the element's text.
    title_inside: bool = False  # The title element counts only inside the container (the page has others before it).
    encodings: tuple[str, ...] = ("utf-8",)  # Declared encodings this publisher's pages may use.


class _Reader(HTMLParser):
    def __init__(self, layout: Layout):
        super().__init__(convert_charrefs=True)
        self.layout = layout
        self.stack: list[tuple[str, bool, bool, bool]] = []  # (tag, opens the container, skipped, hidden)
        self.found = False
        self.blocks: list[tuple[str, str]] = []
        self.buffer: list[str] = []
        self.block_tag = "p"
        self.tables = 0
        self.title: list[str] | None = None
        self.title_depth: int | None = None
        self.date: str | None = None
        self.date_text: list[str] | None = None
        self.date_depth: int | None = None

    def _inside(self) -> bool:
        return any(entry[1] for entry in self.stack) and not any(entry[2] or entry[3] for entry in self.stack)

    def _flush(self) -> None:
        text = SPACE.sub(" ", "".join(self.buffer)).strip()
        self.buffer = []
        if text:
            self.blocks.append((self.block_tag, text))

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {name: value or "" for name, value in attrs_list}
        in_container = any(entry[1] for entry in self.stack)
        if self.title is None and self.layout.title.fits(tag, attrs) and (in_container or not self.layout.title_inside):
            self.title, self.title_depth = [], len(self.stack)
        if self.layout.date and self.date is None and self.date_text is None and self.layout.date.fits(tag, attrs):
            if self.layout.date_attribute:
                self.date = attrs.get(self.layout.date_attribute) or None
            else:
                self.date_text, self.date_depth = [], len(self.stack)
        if tag in VOID:
            if tag == "br" and self._inside():
                self.buffer.append(" ")
            return
        opens = not self.found and self.layout.container.fits(tag, attrs)
        if opens:
            self.found = True
        inside_before = self._inside()
        skipped = inside_before and any(match.fits(tag, attrs) for match in self.layout.skip)
        hidden = tag in HIDDEN
        if inside_before and tag == "table":
            self.tables += 1
            skipped = True
        if (inside_before or opens) and tag in BLOCKS:
            self._flush()
            self.block_tag = tag
        self.stack.append((tag, opens, skipped, hidden))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID or not any(entry[0] == tag for entry in self.stack):
            return
        while self.stack:
            if self._inside() and self.stack[-1][0] in BLOCKS:
                self._flush()
            entry = self.stack.pop()
            if self.title_depth is not None and len(self.stack) <= self.title_depth:
                self.title_depth = None
            if self.date_depth is not None and len(self.stack) <= self.date_depth:
                self.date = SPACE.sub(" ", "".join(self.date_text or [])).strip() or None
                self.date_depth = None
            if entry[0] == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.title_depth is not None and self.title is not None:
            self.title.append(data)
        if self.date_depth is not None and self.date_text is not None:
            self.date_text.append(data)
        if self._inside():
            self.buffer.append(data)


LATIN_1 = "iso-8859-1"
C1_CONTROLS = re.compile(rb"[\x80-\x9f]")


def decoded(raw: bytes, content_type: str, encodings: tuple[str, ...] = ("utf-8",)) -> str:
    """The page's text in the encoding it declares, when that is one this publisher's layout reads (UTF-8, or
    ISO-8859-1 for a publisher that uses it); every declaration must agree. ISO-8859-1 bytes 0x80 to 0x9F are refused
    rather than guessed (they are often Windows-1252 punctuation)."""
    declared = re.search(r"charset=([A-Za-z0-9_-]+)", content_type or "", re.IGNORECASE)
    meta = CHARSET.search(raw[:4096])
    names = {name.decode("ascii", "replace").lower().replace("_", "-")
             for name in ([declared.group(1).encode()] if declared else []) + ([meta.group(1)] if meta else [])}
    names = {"utf-8" if name in ("utf8", "utf-8") else LATIN_1 if name in ("latin-1", "latin1", LATIN_1) else name
             for name in names}
    if len(names) > 1 or (names and next(iter(names)) not in encodings):
        raise Unreadable(f"The page declares the encoding {', '.join(sorted(names))}, which is not read for it")
    codec = next(iter(names)) if names else "utf-8"
    if codec == LATIN_1:
        if C1_CONTROLS.search(raw):
            raise Unreadable("The page holds bytes 0x80 to 0x9F, which ISO-8859-1 does not print; they are not guessed")
        return raw.decode(LATIN_1)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("The page is not valid UTF-8") from None


def _kept(blocks: list[tuple[str, str]]) -> tuple[list[str], bool]:
    kept, total = [], 0
    for tag, text in blocks:
        line = f"- {text}" if tag == "li" else text
        if total + len(line) + 2 > MAX_CHARACTERS:
            return kept, True
        kept.append(line)
        total += len(line) + 2
    return kept, False


def read_page(raw: bytes, content_type: str, layout: Layout) -> dict:
    """The publication's text as the page prints it, with what was left out; Unreadable otherwise."""
    reader = _Reader(layout)
    try:
        reader.feed(decoded(raw, content_type, layout.encodings))
        reader.close()
    except Unreadable:
        raise
    except Exception:  # html.parser raises a handful of types on broken markup; the page is refused whole.
        raise Unreadable("The page has markup that cannot be read") from None
    if not reader.found:
        raise Unreadable(f"The page does not have the layout {layout.key} reads")
    title = SPACE.sub(" ", "".join(reader.title or [])).strip()
    blocks = [(tag, text) for tag, text in reader.blocks if text != title]
    kept, cut = _kept(blocks)
    text = "\n\n".join(kept)
    if len(text) < MIN_CHARACTERS:
        raise Unreadable(f"The page holds {len(text)} characters of text where its layout should have the "
                         "publication; too little to be the publication")
    left_out = [{"kind": "table", "text": f"{reader.tables} table{'s' if reader.tables != 1 else ''} not flattened "
                                          "into text"}] if reader.tables else []
    if cut:
        left_out.append({"kind": "length", "text": f"The publication is longer than {MAX_CHARACTERS:,} characters; the "
                                                   "rest was not kept"})
    return {"extractor": layout.key, "title": title or None, "date": reader.date, "text": text,
            "characters": len(text), "left_out": left_out, "partial": bool(left_out),
            "partial_reason": "; ".join(row["text"] for row in left_out) or None}


EC_DOCUMENT_BODY = "ec-document-body"


def ec_document(raw: bytes, content_type: str) -> dict:
    """A European Commission press-corner document as its documents service answers it: the title and publication
    date it records and the text of its HTML body, read by the block reader; its attachments are named, not read."""
    if (content_type or "").split(";")[0].strip().lower() != "application/json":
        raise Unreadable("The documents service did not answer with JSON")
    try:
        found = json.loads(decoded(raw, content_type))
    except json.JSONDecodeError:
        raise Unreadable("The documents service's answer is not valid JSON") from None
    resource = found.get("docuLanguageResource") if isinstance(found, dict) else None
    if not isinstance(resource, dict) or not isinstance(resource.get("htmlContent"), str) or \
            not isinstance(resource.get("title"), str):
        raise Unreadable("The documents service's answer does not hold a document's title and text")
    page = f'<html><body><div id="{EC_DOCUMENT_BODY}">{resource["htmlContent"]}</div></body></html>'
    read = read_page(page.encode("utf-8"), "text/html; charset=utf-8", EC_DOCUMENT)
    attached = [row.get("title") or row.get("fileName") or "untitled" for row in
                resource.get("attachmentResources") or [] if isinstance(row, dict)]
    left_out = read["left_out"] + [{"kind": "attachment", "text": f"Attachment not read: {name}"} for name in attached]
    date = found.get("publishDate") or found.get("eventDate")
    return {**read, "title": SPACE.sub(" ", resource["title"]).strip(), "date": date if isinstance(date, str) else None,
            "left_out": left_out}


def fed_release(raw: bytes, content_type: str) -> dict:
    """A Federal Reserve Board press release, read by fed_publication; its linked documents are named, not read."""
    try:
        found = fed_publication.extract(raw, content_type)
    except fed_publication.Unreadable as exc:
        raise Unreadable(str(exc)) from None
    linked = [row["title"] for row in found["linked_documents"]]
    left_out = [{"kind": "linked_document", "text": f"Linked document not read: {title}"} for title in linked]
    return {"extractor": found["extractor"], "title": found["title"], "date": found["date"], "text": found["text"],
            "characters": found["characters"], "left_out": left_out, "partial": False,
            "partial_reason": None, "linked_documents": linked}


WHITE_HOUSE = Layout("whitehouse-page-text-0.1", Match("div", "wp-block-post-content"),
                     Match("h1", "wp-block-whitehouse-topper__headline"),
                     skip=(Match("div", "wp-block-whitehouse-topper"),), date=Match("time"),
                     date_attribute="datetime")
USTR = Layout("ustr-page-text-0.1", Match("div", "field--name-body"), Match("h1"))
EIA = Layout("eia-tie-text-0.1", Match("div", "tie-article"), Match("h1"),
             skip=(Match("div", "article-type"), Match("span", "date"), Match("div", "source"), Match("h1"),
                   Match("div", "tie-related"), Match("div", "related-links")),
             date=Match("span", "date"), title_inside=True)
ECB = Layout("ecb-page-text-0.1", Match("main"), Match("h1"),
             skip=(Match("div", "title"), Match("p", "ecb-publicationDate"), Match("div", "related-topics"),
                   Match("div", "address-box")),
             date=Match("p", "ecb-publicationDate"), title_inside=True)
WTO = Layout("wto-news-text-0.1", Match("div", element_id="mainContent"), Match("h1", element_id="newsTitle"),
             encodings=("utf-8", LATIN_1))
# The documents service's HTML body, wrapped in a container of this module's own; its title comes from the answer.
EC_DOCUMENT = Layout("ec-presscorner-text-0.1", Match("div", element_id=EC_DOCUMENT_BODY), Match("title"))

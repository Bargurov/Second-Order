"""Credits in a publisher feed (event-inbox-parser-0.2): the entries a feed carries for other publishers, and the
creator a licence asks to be credited.

A newsroom's feed may list work that is not its own: a wire agency's copy (Voice of America's AP, Reuters and AFP
stories, whose terms forbid storing them) or a partner's article republished under a content-sharing agreement (Global
Voices). A source names such creators (``Source.excluded_credits``, compared without case) or the marks such articles
carry in their text (``Source.excluded_markers``, regular expressions); event_inbox.parse_feed skips the entry before
anything of it is kept and records why. To find a mark, the entry's description and full-article element are read here
and never kept. A source whose licence asks for the author to be credited (``Source.credit_creator``, Global Voices'
CC BY) keeps each entry's creator. Every other source is parsed exactly as by event-inbox-parser-0.1.
"""
import re
import xml.etree.ElementTree as ET

VERSION = "event-inbox-parser-0.2"
ATOM = "{http://www.w3.org/2005/Atom}"
RSS1 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
MAX_CREATOR = 120
RSS_AUTHOR = re.compile(r"\S+@\S+\s*\((.+)\)")  # RSS 2.0's author element: "address (Name)".


def uses_credits(source) -> bool:
    return bool(source.excluded_credits or source.excluded_markers or source.credit_creator)


def _text(element: ET.Element | None, tag: str) -> str | None:
    child = None if element is None else element.find(tag)
    return None if child is None else "".join(child.itertext())


def creator(entry: ET.Element, kind: str) -> str | None:
    """The entry's credited creator as plain text (RSS dc:creator or author, RSS 1.0 dc:creator, Atom author name),
    or None."""
    if kind == "atom":
        raw = _text(entry.find(f"{ATOM}author"), f"{ATOM}name")
    elif kind == "rss1":
        raw = _text(entry, f"{DC}creator")
    else:
        raw = _text(entry, f"{DC}creator") or _text(entry, "author")
    raw = " ".join("".join(char if char.isprintable() else " " for char in raw or "").split())
    named = RSS_AUTHOR.fullmatch(raw)
    name = (named.group(1).strip() if named else raw)[:MAX_CREATOR]
    return name or None


def excluded(entry: ET.Element, kind: str, credited: str | None, source) -> str | None:
    """Why the entry is another publisher's work that this source's terms exclude, or None."""
    if credited is not None and credited.casefold() in {name.casefold() for name in source.excluded_credits}:
        return f"credited to {credited}, whose material this publisher's terms exclude"
    if not source.excluded_markers:
        return None
    parts = ([entry.find(f"{ATOM}summary"), entry.find(f"{ATOM}content")] if kind == "atom" else
             [entry.find(f"{RSS1}description" if kind == "rss1" else "description"), entry.find(CONTENT_ENCODED)])
    text = " ".join(" ".join(re.sub(r"<[^>]+>", " ", "".join(part.itertext())).split())
                    for part in parts if part is not None)
    for marker in source.excluded_markers:
        found = re.search(marker, text, re.IGNORECASE)
        if found:
            return f"marked as another publisher's work (\"{found.group(0)[:80]}\")"
    return None

"""Historical cases for Related Cases (related-cases-0.1): committed, curated accounts of official announcements, each
built only from one official page this project retained, with the facts quoted from that page.

The content is committed under content/related-cases/: collection.json (introduction, labels, notes, the coverage not
yet built, and the cases in announcement order) and one <case id>.json per case. Every file is checked strictly and
the whole collection is refused on any problem; nothing is repaired, skipped or partly served.

A case keeps three things apart:
- source facts: each fact is a short statement with one or more passages quoted verbatim from the retained page. Every
  number a fact (or the summary, a date, a scope note, an actor or a comparison point) states must appear in the
  quotes it cites, so a figure cannot be added by paraphrase;
- curated interpretation: channels and a "why read" note, written with an AI assistant, labelled as interpretation and
  free of figures;
- review status: fixed provenance values say the case is AI-assisted, not reviewed by a person, excluded from research
  use and historical (it describes an announcement as of its date, not current law or policy).

The retained pages themselves stay private (data/sector-sources/related-cases/, git-ignored, never served). When a
page is present on this machine, reading a case checks it: its size and SHA-256 must equal the case's record, every
quoted passage must appear within one text block of the page (scripts and styles are skipped and nothing is executed),
and the acquisition record, when present, must agree. A case whose quotes are missing from a page with the recorded
hash is refused. Without the page the case is served and says it could not be checked here. Nothing is fetched.
"""
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

from . import html_markup, related_rules

COLLECTION_VERSION = "related-cases-0.1"
VIEW_VERSION = "related-cases-view-0.1"
ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "content" / "related-cases"
SOURCES_DIR = ROOT / "data" / "sector-sources" / "related-cases"
COLLECTION = "collection.json"
CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FACT_ID = re.compile(r"[a-z][a-z0-9-]{0,39}")
SHA256 = re.compile(r"[a-f0-9]{64}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
DIGITS = re.compile(r"\d+")
SOURCE_HOSTS = ("www.bis.gov", "home.treasury.gov")
APPROVALS = ("related-cases-sources-01",)
SOURCE_FILE = "source.html"
MAX_TEXT, MAX_QUOTE = 1600, 600
INTERPRETATION_LABEL = ("Curated interpretation, written with an AI assistant and not reviewed by a person. It reads "
                        "the quoted facts; it is not stated by the source.")
FACTS_NOTE = ("Each fact restates what the press release says and quotes it from the retained copy. These are the "
              "government's own statements as published on that date, not findings about what followed.")
DATE_KINDS = {"announcement": "Announced", "action": "Action taken", "effective": "Takes effect",
              "publication": "Publication", "deadline": "Deadline"}

COLLECTION_FIELDS = {"collection_version", "title", "introduction", "labels", "historical_note", "coverage_note",
                     "matching_note", "unfinished", "cases"}
UNFINISHED_FIELDS = {"topic", "planned_source", "outcome"}
CASE_FIELDS = {"collection_version", "id", "title", "topic", "summary", "source", "dates", "facts", "scope", "actors",
               "tags", "comparison_points", "interpretation", "unknowns", "provenance"}
SOURCE_FIELDS = {"publisher", "title", "url", "kind", "date_as_stated", "retained"}
RETAINED_FIELDS = {"approval_id", "attempt", "folder", "file", "sha256", "bytes", "media_type", "requested_at",
                   "received_at"}
DATE_FIELDS = {"kind", "label", "date", "as_stated", "facts", "note"}
FACT_FIELDS = {"id", "text", "quotes"}
PROVENANCE_FIELDS = {"prepared_by", "prepared_on", "method", "sources_read", "ai_assisted", "human_review",
                     "research_use", "currency"}
FIXED_PROVENANCE = {"ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded",
                    "currency": "historical"}
ITEMS = {  # Section: (fields, minimum count, text fields held to the quoted figures).
    "scope": ({"text", "facts"}, 2, ("text",)),
    "actors": ({"name", "role", "facts"}, 1, ("name", "role")),
    "comparison_points": ({"label", "case_value", "facts"}, 2, ("label", "case_value")),
}


class RelatedRefused(ValueError):
    """The collection or a requested case cannot be served; ``status`` is the HTTP status that describes why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _invalid(where: str, problem: str) -> RelatedRefused:
    return RelatedRefused(500, f"The historical cases are invalid ({where}: {problem}); nothing is served")


# ---------------------------------------------------------------- the retained page's text

BLOCK_TAGS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure",
              "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
              "pre", "section", "table", "td", "th", "tr", "ul", "time", "body", "html"}
SKIPPED_TAGS = {"script", "style", "noscript", "svg", "template", "title"}


class _PageText(HTMLParser):
    """Text blocks of a page: block-level tags end a block, inline tags do not; skipped tags contribute nothing."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.blocks = 0, [[]]

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.blocks.append([])

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS:
            self.blocks.append([])

    def handle_data(self, data):
        if not self.skip:
            self.blocks[-1].append(data)


def page_blocks(raw: bytes) -> list[str]:
    """The page's visible text as blocks, each with its whitespace collapsed (NFC). Nothing is executed or fetched."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the page could not be read as UTF-8 HTML (UnicodeDecodeError)") from None
    if html_markup.unreadable(text):  # The rule comes before the parser, so every Python version gives one answer.
        raise ValueError("the page could not be read as UTF-8 HTML (an unknown marked section such as <![bogus[)")
    parser = _PageText()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:  # A refusal html.parser itself still raises (none is known once the rule has passed).
        raise ValueError("the page could not be read as UTF-8 HTML (AssertionError)") from None
    blocks = (unicodedata.normalize("NFC", " ".join("".join(parts).split())) for parts in parser.blocks)
    return [block for block in blocks if block]


def quoted(quote: str, blocks: list[str]) -> bool:
    """Whether a quote appears, exactly, within one text block (never across a block boundary)."""
    return any(quote in block for block in blocks)


# ---------------------------------------------------------------- strict reading

def _strict_load(path: Path) -> dict:
    def pairs(items: list) -> dict:
        if len({key for key, _ in items}) != len(items):
            raise _invalid(path.name, "a JSON key is repeated")
        return dict(items)

    def constant(name: str):
        raise _invalid(path.name, f"the non-standard JSON constant {name}")

    try:
        value = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid(path.name, "not readable strict UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise _invalid(path.name, "not a JSON object")
    return value


def _fields(value: object, expected: set[str], where: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        found = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise _invalid(where, f"expected exactly the fields {sorted(expected)}, found {found}")
    return value


def _text(value: object, where: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > limit or \
            any(ord(char) < 32 for char in value) or unicodedata.normalize("NFC", value) != value:
        raise _invalid(where, "expected one line of non-empty, unpadded NFC text")
    return value


def _list(value: object, where: str, minimum: int) -> list:
    if not isinstance(value, list) or len(value) < minimum:
        raise _invalid(where, f"expected a list of at least {minimum}")
    return value


def _day(value: object, where: str) -> date:
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise _invalid(where, "expected a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid(where, "not a calendar date") from None


def _instant(value: object, where: str) -> str:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise _invalid(where, "expected an ISO date and time with an offset")
    return value


def _official_url(value: object, where: str) -> str:
    parts = urlsplit(_text(value, where))
    if parts.scheme != "https" or parts.hostname not in SOURCE_HOSTS or parts.query or parts.fragment:
        raise _invalid(where, f"expected an https address at {' or '.join(SOURCE_HOSTS)}")
    return value


def long_date(day: date) -> str:
    """A date as US press releases print it: "October 7, 2022"."""
    return f"{day:%B} {day.day}, {day.year}"


def _figures(text: str) -> set[str]:
    return set(DIGITS.findall(text))


def _held_to(text: str, quotes: list[str], where: str) -> None:
    extra = _figures(text) - _figures(" ".join(quotes))
    if extra:
        raise _invalid(where, f"states figures its cited quotes do not: {sorted(extra)}")


def _no_figures(text: str, where: str) -> None:
    if DIGITS.search(text):
        raise _invalid(where, "interpretation states no figures; figures belong to quoted facts")


def _cited(value: object, facts: dict, where: str) -> list[str]:
    """The quotes of the facts an item cites; every citation must name a fact of the case."""
    ids = _list(value, where, 1)
    if len(set(map(str, ids))) != len(ids) or not all(isinstance(item, str) and item in facts for item in ids):
        raise _invalid(where, "expected distinct IDs of this case's facts")
    return [quote for item in ids for quote in facts[item]["quotes"]]


def _check_facts(case: dict, where: str) -> dict:
    facts = {}
    for number, fact in enumerate(_list(case["facts"], f"{where}.facts", 4)):
        place = f"{where}.facts[{number}]"
        _fields(fact, FACT_FIELDS, place)
        if not isinstance(fact["id"], str) or not FACT_ID.fullmatch(fact["id"]) or fact["id"] in facts:
            raise _invalid(f"{place}.id", "expected a distinct lower-case fact ID")
        _text(fact["text"], f"{place}.text")
        for index, quote in enumerate(_list(fact["quotes"], f"{place}.quotes", 1)):
            _text(quote, f"{place}.quotes[{index}]", MAX_QUOTE)
            if " ".join(quote.split()) != quote:
                raise _invalid(f"{place}.quotes[{index}]", "a quote keeps single spaces, as the page's text does")
        _held_to(fact["text"], fact["quotes"], f"{place}.text")
        facts[fact["id"]] = fact
    return facts


def _check_dates(case: dict, facts: dict, where: str) -> date:
    announced = None
    for number, item in enumerate(_list(case["dates"], f"{where}.dates", 2)):
        place = f"{where}.dates[{number}]"
        _fields(item, DATE_FIELDS, place)
        if item["kind"] not in DATE_KINDS:
            raise _invalid(f"{place}.kind", f"expected one of {sorted(DATE_KINDS)}")
        _text(item["label"], f"{place}.label")
        quotes = _cited(item["facts"], facts, f"{place}.facts")
        _held_to(item["label"], quotes, f"{place}.label")
        if item["as_stated"] is not None and not any(_text(item["as_stated"], f"{place}.as_stated") in quote
                                                     for quote in quotes):
            raise _invalid(f"{place}.as_stated", "must be part of a quote of the facts it cites")
        if item["note"] is not None:
            _text(item["note"], f"{place}.note")
        if item["date"] is None:
            if item["note"] is None:
                raise _invalid(f"{place}.note", "a date the source does not state needs a note saying so")
            continue
        day = _day(item["date"], f"{place}.date")
        if item["as_stated"] is None or long_date(day) not in item["as_stated"]:
            raise _invalid(f"{place}.date", f"the source's own wording must state {long_date(day)}")
        if item["kind"] == "announcement":
            if announced is not None:
                raise _invalid(place, "a case has one announcement date")
            announced = day
    if announced is None:
        raise _invalid(f"{where}.dates", "expected the announcement date the source states")
    return announced


def _check_tags(tags: object, facts: dict, where: str) -> None:
    _fields(tags, set(related_rules.DIMENSIONS), where)
    for dimension in related_rules.DIMENSIONS:
        items = _list(tags[dimension], f"{where}.{dimension}", 0)
        listed = set()
        for number, item in enumerate(items):
            place = f"{where}.{dimension}[{number}]"
            _fields(item, {"slug", "facts"}, place)
            if item["slug"] not in related_rules.slugs(dimension) or item["slug"] in listed:
                raise _invalid(f"{place}.slug", f"expected a distinct {dimension} of {related_rules.RULES_VERSION}")
            listed.add(item["slug"])
            _cited(item["facts"], facts, f"{place}.facts")
    if not tags["instrument"] or not (tags["sector"] or tags["geography"]) or not tags["agency"]:
        raise _invalid(where, "a case needs an instrument, an agency, and a sector or a country")


def _check_case(case: dict, case_id: str) -> dict:
    where = f"{case_id}.json"
    _fields(case, CASE_FIELDS, where)
    if case["collection_version"] != COLLECTION_VERSION:
        raise _invalid(f"{where}.collection_version", f"must be {COLLECTION_VERSION}")
    if case["id"] != case_id:
        raise _invalid(where, f"its id {case['id']!r} does not match its file name")
    for field in ("title", "topic"):
        _text(case[field], f"{where}.{field}")
    facts = _check_facts(case, where)
    summary = _fields(case["summary"], {"text", "facts"}, f"{where}.summary")
    _held_to(_text(summary["text"], f"{where}.summary.text"), _cited(summary["facts"], facts, f"{where}.summary.facts"),
             f"{where}.summary.text")
    source = _fields(case["source"], SOURCE_FIELDS, f"{where}.source")
    for field in ("publisher", "title", "kind", "date_as_stated"):
        _text(source[field], f"{where}.source.{field}")
    _official_url(source["url"], f"{where}.source.url")
    retained = _fields(source["retained"], RETAINED_FIELDS, f"{where}.source.retained")
    if retained["approval_id"] not in APPROVALS:
        raise _invalid(f"{where}.source.retained.approval_id", f"expected one of {list(APPROVALS)}")
    if not isinstance(retained["folder"], str) or not CASE_ID.fullmatch(retained["folder"]) or \
            retained["file"] != SOURCE_FILE:
        raise _invalid(f"{where}.source.retained", f"expected a lower-case folder and the file {SOURCE_FILE}")
    if not isinstance(retained["sha256"], str) or not SHA256.fullmatch(retained["sha256"]):
        raise _invalid(f"{where}.source.retained.sha256", "expected a SHA-256")
    for field in ("attempt", "bytes"):
        if type(retained[field]) is not int or retained[field] < 1:
            raise _invalid(f"{where}.source.retained.{field}", "expected a positive integer")
    _text(retained["media_type"], f"{where}.source.retained.media_type")
    for field in ("requested_at", "received_at"):
        _instant(retained[field], f"{where}.source.retained.{field}")
    announced = _check_dates(case, facts, where)
    for section, (fields, minimum, held) in ITEMS.items():
        for number, item in enumerate(_list(case[section], f"{where}.{section}", minimum)):
            place = f"{where}.{section}[{number}]"
            _fields(item, fields, place)
            quotes = _cited(item["facts"], facts, f"{place}.facts")
            for field in held:
                _held_to(_text(item[field], f"{place}.{field}"), quotes, f"{place}.{field}")
    _check_tags(case["tags"], facts, f"{where}.tags")
    interpretation = _fields(case["interpretation"], {"channels", "why_read"}, f"{where}.interpretation")
    for number, channel in enumerate(_list(interpretation["channels"], f"{where}.interpretation.channels", 1)):
        place = f"{where}.interpretation.channels[{number}]"
        _fields(channel, {"title", "facts", "text"}, place)
        _cited(channel["facts"], facts, f"{place}.facts")
        for field in ("title", "text"):
            _no_figures(_text(channel[field], f"{place}.{field}"), f"{place}.{field}")
    _no_figures(_text(interpretation["why_read"], f"{where}.interpretation.why_read"),
                f"{where}.interpretation.why_read")
    for number, item in enumerate(_list(case["unknowns"], f"{where}.unknowns", 2)):
        _text(item, f"{where}.unknowns[{number}]")
    provenance = _fields(case["provenance"], PROVENANCE_FIELDS, f"{where}.provenance")
    for field, value in FIXED_PROVENANCE.items():
        if provenance[field] != value or type(provenance[field]) is not type(value):
            raise _invalid(f"{where}.provenance.{field}", f"must be {json.dumps(value)}")
    for field in ("prepared_by", "method"):
        _text(provenance[field], f"{where}.provenance.{field}")
    if _day(provenance["prepared_on"], f"{where}.provenance.prepared_on") <= announced:
        raise _invalid(f"{where}.provenance.prepared_on", "a historical case is prepared after the announcement")
    read = _list(provenance["sources_read"], f"{where}.provenance.sources_read", 1)
    for number, url in enumerate(read):
        _official_url(url, f"{where}.provenance.sources_read[{number}]")
    if read != [source["url"]]:
        raise _invalid(f"{where}.provenance.sources_read", "a case is built from its one retained source")
    return case


def announced(case: dict) -> date:
    return date.fromisoformat(next(item["date"] for item in case["dates"] if item["kind"] == "announcement"))


def case_quotes(case: dict) -> list[str]:
    """Every passage a case claims its retained page states: the fact quotes, the source title and dateline."""
    quotes = [case["source"]["title"], case["source"]["date_as_stated"]]
    quotes += [quote for fact in case["facts"] for quote in fact["quotes"]]
    return list(dict.fromkeys(quotes))


def load(root: Path = CASES_DIR) -> dict:
    """The collection and its cases in announcement order, every file verified. Nothing is written."""
    if not (root / COLLECTION).is_file():
        raise RelatedRefused(503, "The historical cases are not installed; nothing is served")
    collection = _fields(_strict_load(root / COLLECTION), COLLECTION_FIELDS, COLLECTION)
    if collection["collection_version"] != COLLECTION_VERSION:
        raise _invalid(f"{COLLECTION}.collection_version", f"must be {COLLECTION_VERSION}")
    for field in ("title", "introduction", "historical_note", "coverage_note", "matching_note"):
        _text(collection[field], f"{COLLECTION}.{field}")
    for number, label in enumerate(_list(collection["labels"], f"{COLLECTION}.labels", 1)):
        _text(label, f"{COLLECTION}.labels[{number}]")
    for number, item in enumerate(_list(collection["unfinished"], f"{COLLECTION}.unfinished", 0)):
        _fields(item, UNFINISHED_FIELDS, f"{COLLECTION}.unfinished[{number}]")
        for field in sorted(UNFINISHED_FIELDS):
            _text(item[field], f"{COLLECTION}.unfinished[{number}].{field}")
    order = _list(collection["cases"], f"{COLLECTION}.cases", 1)
    if len(set(map(str, order))) != len(order) or not all(isinstance(item, str) and CASE_ID.fullmatch(item)
                                                          for item in order):
        raise _invalid(f"{COLLECTION}.cases", "expected distinct lower-case case IDs")
    files = {path.stem for path in root.glob("*.json") if path.name != COLLECTION}
    if files != set(order):
        raise _invalid(COLLECTION, f"its listed cases {sorted(order)} differ from the case files {sorted(files)}")
    cases = [_check_case(_strict_load(root / f"{case_id}.json"), case_id) for case_id in order]
    keys = [(announced(case), case["id"]) for case in cases]
    if keys != sorted(keys):
        raise _invalid(f"{COLLECTION}.cases", "cases must be listed in announcement order")
    folders = [case["source"]["retained"]["folder"] for case in cases]
    if len(set(folders)) != len(folders):
        raise _invalid(COLLECTION, "two cases name one retained source")
    return {"collection": collection, "cases": cases,
            "digest": hashlib.sha256(json.dumps({"collection": collection, "cases": cases}, sort_keys=True,
                                                ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()}


# ---------------------------------------------------------------- the retained copy, when present

def _acquisition(case: dict, sources: Path) -> str:
    """Whether the acquisition record, if this machine has it, agrees with the case: matches, absent or differs."""
    retained = case["source"]["retained"]
    path = sources / "acquisitions" / retained["approval_id"] / f"outcome-{retained['attempt']}.json"
    if not path.is_file():
        return "absent"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "differs"
    expected = {"outcome": "complete", "http_status": 200, "url": case["source"]["url"],
                "sha256": retained["sha256"], "bytes": retained["bytes"], "approval_id": retained["approval_id"],
                "retained": f"data/sector-sources/related-cases/{retained['folder']}/{retained['file']}",
                "dispatched_at": retained["requested_at"], "body_completed_at": retained["received_at"]}
    agrees = isinstance(record, dict) and all(record.get(key) == value for key, value in expected.items()) and \
        (record.get("named_headers") or {}).get("content-type") == retained["media_type"]
    return "matches" if agrees else "differs"


def source_check(case: dict, sources: Path = SOURCES_DIR) -> dict:
    """The case against its retained page on this machine. Reads only; raises when quotes are missing from it."""
    retained = case["source"]["retained"]
    path = sources / retained["folder"] / retained["file"]
    base = {"sha256": retained["sha256"], "bytes": retained["bytes"], "quotes": len(case_quotes(case))}
    if not path.is_file():
        return {**base, "state": "absent", "acquisition_record": "absent",
                "detail": "The retained copy is not on this machine, so the quotes could not be checked here. The "
                          "case was written from it and records its SHA-256."}
    raw = path.read_bytes()
    if len(raw) != retained["bytes"] or hashlib.sha256(raw).hexdigest() != retained["sha256"]:
        return {**base, "state": "different", "acquisition_record": _acquisition(case, sources),
                "detail": "The file kept on this machine is not the recorded copy (its size or SHA-256 differs), so "
                          "the quotes were not checked against it."}
    try:
        blocks = page_blocks(raw)
    except ValueError as exc:
        raise RelatedRefused(500, f"Case {case['id']}: its retained copy could not be read ({exc})") from None
    missing = [quote for quote in case_quotes(case) if not quoted(quote, blocks)]
    if missing:
        raise RelatedRefused(500, f"Case {case['id']}: {len(missing)} quoted passage(s) do not appear in its retained "
                                  f"copy (first: {missing[0][:80]!r}); the case is not served")
    record = _acquisition(case, sources)
    if record == "differs":
        return {**base, "state": "different", "acquisition_record": record,
                "detail": "The retained copy matches the case, but its acquisition record on this machine does not."}
    return {**base, "state": "verified", "acquisition_record": record,
            "detail": f"The retained copy on this machine has the recorded size and SHA-256, and all {base['quotes']} "
                      "quoted passages appear in it." + ("" if record == "matches" else
                                                         " Its acquisition record is not on this machine.")}


# ---------------------------------------------------------------- views

def match_cases(loaded: dict) -> list[dict]:
    """What the matching rule needs of each case, in collection order."""
    return [{"id": case["id"], "tags": {dimension: [item["slug"] for item in case["tags"][dimension]]
                                        for dimension in related_rules.DIMENSIONS}} for case in loaded["cases"]]


def _row(case: dict) -> dict:
    return {"id": case["id"], "title": case["title"], "topic": case["topic"], "summary": case["summary"]["text"],
            "announced": announced(case).isoformat(), "date_as_stated": case["source"]["date_as_stated"],
            "publisher": case["source"]["publisher"]}


def _header(collection: dict) -> dict:
    return {"view_version": VIEW_VERSION, "collection_version": COLLECTION_VERSION, "title": collection["title"],
            "introduction": collection["introduction"], "labels": collection["labels"],
            "historical_note": collection["historical_note"], "coverage_note": collection["coverage_note"],
            "matching_note": collection["matching_note"], "unfinished": collection["unfinished"]}


def collection_view(root: Path = CASES_DIR) -> dict:
    """What the case library lists: the collection's notes and one row per case. Reads only."""
    loaded = load(root)
    return {**_header(loaded["collection"]), "cases": [_row(case) for case in loaded["cases"]]}


def tag_labels() -> dict:
    return {dimension: {slug: related_rules.label(dimension, slug) for slug in related_rules.VOCABULARY[dimension]}
            for dimension in related_rules.DIMENSIONS}


def case_view(case_id: str, root: Path = CASES_DIR, sources: Path = SOURCES_DIR) -> dict:
    """One case with its neighbours, its labels and the check of its retained copy on this machine. Reads only."""
    loaded = load(root)
    cases = loaded["cases"]
    ids = [case["id"] for case in cases]
    if not CASE_ID.fullmatch(case_id or "") or case_id not in ids:
        raise RelatedRefused(404, "Unknown historical case")
    position = ids.index(case_id)
    case = cases[position]

    def neighbour(index: int) -> dict | None:
        return {"id": cases[index]["id"], "title": cases[index]["title"]} if 0 <= index < len(cases) else None

    return {**_header(loaded["collection"]), "case": case, "announced": announced(case).isoformat(),
            "position": position + 1, "count": len(cases), "previous": neighbour(position - 1),
            "next": neighbour(position + 1), "source_check": source_check(case, sources),
            "interpretation_label": INTERPRETATION_LABEL, "facts_note": FACTS_NOTE, "date_kinds": DATE_KINDS,
            "dimension_labels": related_rules.DIMENSION_LABELS, "tag_labels": tag_labels(),
            "rules_version": related_rules.RULES_VERSION, "provider_called": False}

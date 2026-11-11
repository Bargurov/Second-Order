"""Committed theses (thesis-0.1): strict loading of a thesis's index and version files, the version chain, and the
catalog.

Layout. content/theses/<id>/index.json (thesis-index-0.1) lists the versions in order: {version, file: "v<n>.json",
sha256, published_on}. The SHA-256 is of the loaded file's canonical JSON (bis_snapshot.canonical), so a CRLF checkout
still matches; published_on is a YYYY-MM-DD date, or null for a draft, which only the last version may be, and the dates
do not decrease. published_on lives only in the index (the version file has prepared_on), so publishing a draft never
changes a version file or its hash; a version is not published before the day it was prepared.

A version file holds exactly FIELDS, every one required and none defaulted: its identity and chain position; title,
topic and confidence (author text stating no figures); the sources (entries bound to acquisition records; only their
shape is checked here, and a PDF's transcription lists, ascending and once each, exactly the pages its figures and
passages cite and states one of TRANSCRIPTION_METHODS; a source's edition_date is an ordering key, never shown as a
date: the day the publisher states for that edition, on the retained file or in a publisher record kept in the
acquisition folder, or, where only a month or a year is stated, the first day of it, and never an HTTP Last-Modified,
upload or file-metadata date, which this module cannot check); the figures (each printed value equal to its stated value, each with a locator of its source's
kind, and on a page or a transcribed PDF printed inside its quote); the passages (HTML or PDF only); the view (a
statement); the sections (thesis_sections); not_claimed (the only place claim words and price phrasings may appear);
and the provenance. Locators are checked again against the retained files on every read (thesis_view).

The chain. Version n > 1 is valid only when version n-1 is, with the same opening date; n-1's log is an exact prefix of
n's, with at least one new entry, each dated on or after n-1's publication; a changed view text needs a new view entry
and a changed confidence level a new confidence entry.

Reads content only: nothing here reads a retained source, writes, fetches or calls a model. An id or version that is
malformed or unknown is not found (404); an invalid file refuses the whole thesis (500).
"""
from datetime import datetime
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import bis_snapshot, thesis_sections
from .thesis_arithmetic import decimal_of, shown_value
from .thesis_rules import CONFIDENCE, ThesisRefused, author_text, check, free_text, held_to, invalid, no_figures
from .thesis_sections import ID, PERIOD, YEAR, day, fields, ident, items, shown
from .thesis_sources import CSV_ENCODINGS, KINDS, ORIGINS

THESIS_VERSION = "thesis-0.1"
INDEX_VERSION = "thesis-index-0.1"
CATALOG_VERSION = "thesis-catalog-0.1"
ROOT = Path(__file__).resolve().parent.parent
THESES_DIR = ROOT / "content" / "theses"
INDEX = "index.json"
MAX_FILE_BYTES = 2_000_000
UNITS = ("kt", "million_t", "t", "kg", "kg_per_unit", "usd_per_tonne", "usd_per_lb", "usd_cents_per_lb", "usd",
         "usd_million", "percent", "count")
# Ruling R17: how a PDF's figures and passages were read, stated on the page as it was. A page image was looked at; a
# text layer was read as text where no page image could be rendered. No other method is accepted.
TRANSCRIBED = "transcribed from the page image"
TRANSCRIPTION_METHODS = (TRANSCRIBED, "transcribed from the PDF's text layer")
SHA256 = re.compile(r"[0-9a-f]{64}")
CELL = re.compile(r"[A-Z]{1,3}[1-9]\d{0,6}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")  # One retained file name; never a path.
MIN_QUOTE, MAX_QUOTE, MAX_SHOWN = 8, 320, 40

FIELDS = {"thesis_version", "id", "version", "previous_version", "title", "topic", "opened_on", "prepared_on",
          "confidence", "sources", "figures", "passages", "view", "balance", "differs", "reasons", "risks",
          "conditions", "exposure", "log", "price_record", "plain", "not_claimed", "provenance"}
INDEX_FIELDS = {"index_version", "id", "versions"}
ENTRY_FIELDS = {"version", "file", "sha256", "published_on"}
SOURCE_FIELDS = {"id", "kind", "origin", "publisher", "title", "series", "edition", "edition_date", "url",
                 "approval_id", "attempt", "folder", "name", "sha256", "bytes", "retrieved_at", "terms",
                 "transcription", "encoding"}
TERMS_FIELDS = {"licence", "note"}
TRANSCRIPTION_FIELDS = {"pages", "method"}
FIGURE_FIELDS = {"id", "source", "measure", "unit", "value", "as_shown", "year", "period", "basis", "scenario",
                 "locator"}
PASSAGE_FIELDS = {"id", "source", "locator"}
LOCATOR_FIELDS = {"html": {"paragraph", "quote"}, "pdf": {"page", "quote"},
                  "xlsx": {"sheet", "cell", "label_cell", "label"}, "csv": {"row", "column", "label_column", "label"}}
CONFIDENCE_FIELDS = {"level", "basis"}
PROVENANCE_FIELDS = {"prepared_by", "method", "ai_assisted", "human_review", "research_use"}
FIXED_PROVENANCE = {"ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded"}


# ---------------------------------------------------------------- field checks

def _count(value: object, where: str, minimum: int = 1) -> int:
    check(type(value) is int and value >= minimum, where, f"expected a whole number of at least {minimum}")
    return value


def _moment(value: object, where: str) -> datetime:
    try:
        moment = datetime.fromisoformat(free_text(value, where, 40))
    except ValueError:
        moment = None
    check(moment is not None and moment.utcoffset() is not None, where, "expected an ISO time with an offset")
    return moment


def _url(value: object, where: str) -> str:
    text = free_text(value, where, 500)
    try:
        parts = urlsplit(text)
        valid = (parts.scheme == "https" and bool(parts.hostname) and parts.port is None and " " not in text and
                 "@" not in text)
    except ValueError:
        valid = False
    check(valid, where, "expected an https address without credentials or a port")
    return text


def _quote(value: object, where: str) -> str:
    quote = free_text(value, where, MAX_QUOTE)
    check(len(quote) >= MIN_QUOTE and not quote.startswith("#") and "|" not in quote and "<" not in quote, where,
          f"expected a plain passage of {MIN_QUOTE} to {MAX_QUOTE} characters, without markup")
    return quote


def _source(item: object, number: int, sources: dict, prepared_on: str) -> dict:
    where = f"sources[{number}]"
    fields(item, SOURCE_FIELDS, where)
    ident(item["id"], f"{where}.id", sources)
    where = f"sources[{item['id']}]"
    check(item["kind"] in KINDS, f"{where}.kind", f"expected one of {list(KINDS)}")
    check(item["origin"] in ORIGINS, f"{where}.origin", f"expected one of {list(ORIGINS)}")
    for field, limit in (("publisher", 200), ("title", 400), ("series", 120), ("edition", 60)):
        free_text(item[field], f"{where}.{field}", limit)
    # Ruling R16: an ordering key, never shown as a date. The day the publisher states for the edition (on the retained
    # file or in a publisher record kept in the acquisition folder); where only a month or a year is stated, the first
    # day of it; never an HTTP Last-Modified, upload or file-metadata date. Provenance cannot be checked here.
    day(item["edition_date"], f"{where}.edition_date")
    _url(item["url"], f"{where}.url")
    check(isinstance(item["approval_id"], str) and bool(ID.fullmatch(item["approval_id"])), f"{where}.approval_id",
          "expected a lower-case approval id")
    _count(item["attempt"], f"{where}.attempt")
    check(isinstance(item["folder"], str) and bool(ID.fullmatch(item["folder"])), f"{where}.folder",
          "expected a lower-case folder name")
    check(isinstance(item["name"], str) and bool(NAME.fullmatch(item["name"])) and ".." not in item["name"],
          f"{where}.name", "expected one file name")
    check(isinstance(item["sha256"], str) and bool(SHA256.fullmatch(item["sha256"])), f"{where}.sha256",
          "expected a SHA-256")
    _count(item["bytes"], f"{where}.bytes")
    _moment(item["retrieved_at"], f"{where}.retrieved_at")
    check(item["retrieved_at"][:10] <= prepared_on, f"{where}.retrieved_at",
          "is after the day this version was prepared")
    terms = fields(item["terms"], TERMS_FIELDS, f"{where}.terms")
    free_text(terms["licence"], f"{where}.terms.licence", 200)
    free_text(terms["note"], f"{where}.terms.note", 600)
    if item["kind"] == "pdf":  # A PDF is never read here: its figures and passages are transcribed (R17 methods).
        transcription = fields(item["transcription"], TRANSCRIPTION_FIELDS, f"{where}.transcription")
        pages = transcription["pages"]
        check(isinstance(pages, list) and bool(pages) and all(type(page) is int and page >= 1 for page in pages) and
              pages == sorted(set(pages)), f"{where}.transcription.pages",
              "expected the transcribed pages: whole numbers of at least 1, ascending, each once")
        check(transcription["method"] in TRANSCRIPTION_METHODS, f"{where}.transcription.method",
              f"must be exactly one of {list(TRANSCRIPTION_METHODS)}")
    else:
        check(item["transcription"] is None, f"{where}.transcription", "only a PDF source is transcribed")
    if item["kind"] == "csv":  # A CSV is decoded as declared, never guessed (ruling R13).
        check(item["encoding"] in CSV_ENCODINGS, f"{where}.encoding", f"expected one of {list(CSV_ENCODINGS)}")
    else:
        check(item["encoding"] is None, f"{where}.encoding", "only a CSV source declares an encoding")
    return item


def _sources(value: object, prepared_on: str) -> dict:
    sources = {}
    for number, item in enumerate(items(value, "sources", 1)):
        source = _source(item, number, sources, prepared_on)
        sources[source["id"]] = source
    for key, problem in ((("folder", "name"), "names one retained file twice"),
                         (("approval_id", "attempt"), "names one acquisition attempt twice")):
        found = [tuple(source[part] for part in key) for source in sources.values()]
        check(len(set(found)) == len(found), "sources", problem)
    return sources


def _locator(value: object, where: str, source: dict, as_shown: str | None) -> None:
    """A figure's (``as_shown`` given) or passage's place in its source, in the shape of the source's kind."""
    kind = source["kind"]
    check(isinstance(value, dict) and set(value) == LOCATOR_FIELDS[kind], where,
          f"expected exactly the fields {sorted(LOCATOR_FIELDS[kind])} of a locator in {kind} source {source['id']}")
    if kind in ("html", "pdf"):
        key = "paragraph" if kind == "html" else "page"
        _count(value[key], f"{where}.{key}")
        quote = _quote(value["quote"], f"{where}.quote")
        check(as_shown is None or as_shown in quote, f"{where}.quote",
              f"does not show the figure as printed, {as_shown}")
    elif kind == "xlsx":
        free_text(value["sheet"], f"{where}.sheet", 100)
        for key in ("cell", "label_cell"):
            check(isinstance(value[key], str) and bool(CELL.fullmatch(value[key])), f"{where}.{key}",
                  "expected a cell reference such as B12")
        check(value["cell"] != value["label_cell"], f"{where}.label_cell", "is the figure's own cell")
        free_text(value["label"], f"{where}.label", 200)
    else:
        _count(value["row"], f"{where}.row", 2)
        free_text(value["column"], f"{where}.column", 200)
        free_text(value["label_column"], f"{where}.label_column", 200)
        check(value["column"] != value["label_column"], f"{where}.label_column", "is the figure's own column")
        free_text(value["label"], f"{where}.label", 200)


def _figure(item: object, number: int, figures: dict, sources: dict) -> dict:
    where = f"figures[{number}]"
    fields(item, FIGURE_FIELDS, where)
    ident(item["id"], f"{where}.id", figures)
    where = f"figures[{item['id']}]"
    check(isinstance(item["source"], str) and item["source"] in sources, f"{where}.source", "names no listed source")
    check(item["unit"] in UNITS, f"{where}.unit", f"expected one of {list(UNITS)}")
    try:
        value = decimal_of(item["value"])
    except ValueError:
        raise invalid(f"{where}.value", "expected a plain decimal written as text") from None
    try:
        printed = shown_value(free_text(item["as_shown"], f"{where}.as_shown", MAX_SHOWN))
    except ValueError:
        printed = None
    check(printed is not None and printed == value, f"{where}.as_shown", f"does not print the value {item['value']}")
    year, period = item["year"], item["period"]
    check(year is None or (isinstance(year, str) and bool(YEAR.fullmatch(year))), f"{where}.year",
          "expected a four-digit year or null")
    if period is not None:
        valid = isinstance(period, str) and bool(PERIOD.fullmatch(period)) and period[:4] == year
        if valid and thesis_sections.period_kind(period) == "day":
            valid = day(period, f"{where}.period") == period
        check(valid, f"{where}.period", "expected null, or a month (YYYYMmm), quarter (YYYYQn) or day within the "
                                        "figure's year")
    held_to(author_text(item["measure"], f"{where}.measure", 160), shown(item), f"{where}.measure")
    if item["basis"] is not None:
        held_to(author_text(item["basis"], f"{where}.basis", thesis_sections.MAX_LABEL), shown(item), f"{where}.basis")
    if item["scenario"] is not None:  # The publisher's name for its scenario, as printed.
        free_text(item["scenario"], f"{where}.scenario", thesis_sections.MAX_LABEL)
    _locator(item["locator"], f"{where}.locator", sources[item["source"]], item["as_shown"])
    return item


def _passages(value: object, figures: dict, sources: dict) -> dict:
    passages = {}
    for number, item in enumerate(items(value, "passages")):
        where = f"passages[{number}]"
        fields(item, PASSAGE_FIELDS, where)
        ident(item["id"], f"{where}.id", set(figures) | set(passages))
        where = f"passages[{item['id']}]"
        check(isinstance(item["source"], str) and item["source"] in sources, f"{where}.source",
              "names no listed source")
        check(sources[item["source"]]["kind"] in ("html", "pdf"), f"{where}.source",
              "a passage quotes an HTML page or a PDF")
        _locator(item["locator"], f"{where}.locator", sources[item["source"]], None)
        passages[item["id"]] = item
    return passages


def _transcribed_pages(sources: dict, figures: dict, passages: dict) -> None:
    """A PDF source's transcription lists exactly the pages its figures and passages cite, so the page named beside a
    source is never one the thesis does not use, and no cited page goes unnamed."""
    for source in sources.values():
        if source["kind"] == "pdf":
            cited = sorted({item["locator"]["page"] for item in [*figures.values(), *passages.values()]
                            if item["source"] == source["id"]})
            check(source["transcription"]["pages"] == cited, f"sources[{source['id']}].transcription.pages",
                  f"expected exactly the pages its figures and passages cite: {cited}")


def _check_version(raw: object, thesis_id: str, version: int) -> dict:
    fields(raw, FIELDS, "thesis")
    check(raw["thesis_version"] == THESIS_VERSION, "thesis_version", f"expected {THESIS_VERSION}")
    check(raw["id"] == thesis_id, "id", "does not match its folder")
    check(type(raw["version"]) is int and raw["version"] == version, "version", "does not match its index entry")
    check(raw["previous_version"] is None if version == 1 else
          type(raw["previous_version"]) is int and raw["previous_version"] == version - 1, "previous_version",
          "expected null for version 1, otherwise the version before")
    for field in ("title", "topic"):
        no_figures(author_text(raw[field], field, thesis_sections.MAX_TITLE), field)
    opened_on, prepared_on = day(raw["opened_on"], "opened_on"), day(raw["prepared_on"], "prepared_on")
    check(opened_on <= prepared_on, "prepared_on", "is before the thesis opened")
    confidence = fields(raw["confidence"], CONFIDENCE_FIELDS, "confidence")
    check(confidence["level"] in CONFIDENCE, "confidence.level", f"expected one of {list(CONFIDENCE)}")
    no_figures(author_text(confidence["basis"], "confidence.basis"), "confidence.basis")
    sources = _sources(raw["sources"], prepared_on)
    figures = {}
    for number, item in enumerate(items(raw["figures"], "figures", 1)):
        figures[_figure(item, number, figures, sources)["id"]] = item
    passages = _passages(raw["passages"], figures, sources)
    _transcribed_pages(sources, figures, passages)
    thesis_sections.statement(raw["view"], "view", figures, passages)
    # Ruling R15: the view is an element; one that cites nothing (not_stated) would read "checked" on nothing.
    check(bool(raw["view"]["cites"]), "view", thesis_sections.NOTHING)
    thesis_sections.check_sections(raw, figures, passages, sources)
    for number, claim in enumerate(items(raw["not_claimed"], "not_claimed", 1)):
        free_text(claim, f"not_claimed[{number}]", 300)
    provenance = fields(raw["provenance"], PROVENANCE_FIELDS, "provenance")
    for field, value in FIXED_PROVENANCE.items():
        check(provenance[field] == value and type(provenance[field]) is type(value), f"provenance.{field}",
              f"must be {value!r}")
    no_figures(author_text(provenance["prepared_by"], "provenance.prepared_by", 200), "provenance.prepared_by")
    no_figures(author_text(provenance["method"], "provenance.method"), "provenance.method")
    return raw


def _check_index(raw: object, thesis_id: str) -> dict:
    index = fields(raw, INDEX_FIELDS, "index")
    check(index["index_version"] == INDEX_VERSION, "index.index_version", f"expected {INDEX_VERSION}")
    check(index["id"] == thesis_id, "index.id", "does not match its folder")
    entries = items(index["versions"], "index.versions", 1)
    published = None
    for number, entry in enumerate(entries, start=1):
        where = f"index.versions[{number - 1}]"
        fields(entry, ENTRY_FIELDS, where)
        check(type(entry["version"]) is int and entry["version"] == number, f"{where}.version",
              "expected versions numbered 1, 2, … in order")
        check(entry["file"] == f"v{number}.json", f"{where}.file", f"expected v{number}.json")
        check(isinstance(entry["sha256"], str) and bool(SHA256.fullmatch(entry["sha256"])), f"{where}.sha256",
              "expected a SHA-256")
        if entry["published_on"] is None:
            check(number == len(entries), f"{where}.published_on", "only the last version may be a draft")
        else:
            day(entry["published_on"], f"{where}.published_on")
            check(published is None or entry["published_on"] >= published, f"{where}.published_on",
                  "expected publication dates that do not decrease")
            published = entry["published_on"]
    return index


def _check_chain(previous: dict, published_on: str, current: dict) -> None:
    """Version n against version n-1, published on ``published_on``."""
    check(current["opened_on"] == previous["opened_on"], "opened_on", "differs from the previous version's")
    old, new = previous["log"], current["log"]
    check(bis_snapshot.canonical(new[:len(old)]) == bis_snapshot.canonical(old), "log",
          "does not keep the previous version's log as it was; earlier entries are never rewritten or dropped")
    added = new[len(old):]
    check(bool(added), "log", "adds no entry to the previous version's log")
    for number, entry in enumerate(added, start=len(old)):
        check(entry["date"] >= published_on, f"log[{number}].date", "is before the previous version was published")
    kinds = {entry["kind"] for entry in added}
    check(current["view"]["text"] == previous["view"]["text"] or "view" in kinds, "log",
          "the view changed without a new view entry")
    check(current["confidence"]["level"] == previous["confidence"]["level"] or "confidence" in kinds, "log",
          "the confidence level changed without a new confidence entry")


# ---------------------------------------------------------------- reading

def _read(path: Path, what: str) -> object:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise invalid(what, "larger than a thesis file may be")
    try:
        return bis_snapshot._strict_json(path.read_bytes().decode("utf-8"), f"The thesis file {what}")
    except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        raise invalid(what, "not strict UTF-8 JSON") from None


def load_index(thesis_id: str, root: Path = THESES_DIR) -> dict:
    """A thesis's index, strictly checked. Reads only."""
    if not isinstance(thesis_id, str) or not ID.fullmatch(thesis_id):
        raise ThesisRefused(404, "No thesis has this id")
    path = Path(root) / thesis_id / INDEX
    if not path.is_file():
        raise ThesisRefused(404, "No thesis has this id")
    return _check_index(_read(path, INDEX), thesis_id)


def load_version(thesis_id: str, version: int, root: Path = THESES_DIR) -> dict:
    """One version file, strictly checked, matching its index hash, with its whole chain (versions 1 … n-1) valid.
    Reads only."""
    index = load_index(thesis_id, root)
    if type(version) is not int or not 1 <= version <= len(index["versions"]):
        raise ThesisRefused(404, "This thesis has no such version")
    entry = index["versions"][version - 1]
    path = Path(root) / thesis_id / entry["file"]
    check(path.is_file(), entry["file"], "the index names a version file that is not there")
    loaded = _read(path, entry["file"])
    check(bis_snapshot.sha256(bis_snapshot.canonical(loaded)) == entry["sha256"], entry["file"],
          "does not match the SHA-256 its index records")
    _check_version(loaded, thesis_id, version)
    check(entry["published_on"] is None or entry["published_on"] >= loaded["prepared_on"],
          f"index.versions[{version - 1}].published_on", "is before the day the version was prepared")
    if version > 1:
        _check_chain(load_version(thesis_id, version - 1, root), index["versions"][version - 2]["published_on"],
                     loaded)
    return loaded


def catalog(root: Path = THESES_DIR) -> dict:
    """The committed theses, for listing: each latest version strictly loaded, read as content only, so no retained
    source is read here."""
    theses = []
    root = Path(root)
    if root.is_dir():
        for folder in sorted(path for path in root.iterdir() if path.is_dir() and (path / INDEX).is_file()):
            check(bool(ID.fullmatch(folder.name)), folder.name, "a thesis folder is not named by a lower-case id")
            latest = load_index(folder.name, root)["versions"][-1]
            thesis = load_version(folder.name, latest["version"], root)
            theses.append({"id": thesis["id"], "title": thesis["title"], "topic": thesis["topic"],
                           "latest_version": latest["version"], "published_on": latest["published_on"],
                           "href": f"/theses/{thesis['id']}"})
    return {"view_version": CATALOG_VERSION, "theses": theses, "provider_called": False}

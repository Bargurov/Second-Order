"""Source-grounded research views (policy-research-0.1): committed comparisons of selected official publications, every
statement tied to passages quoted from a retained source and checked against that source on every read.

A view is one committed file, content/research/<id>/research.json. The first, semiconductor-policy, compares ten BIS
press releases read from the retained BIS snapshot (see bis_snapshot): a retrospective comparison of selected retained
publications, not a monitor of current policy and not legal guidance. The file keeps three things apart:
- publisher statements: passages quoted verbatim, each located by its paragraph (1-based) in the record's text;
- curator interpretation: labelled as such and never presented as the publisher's words; which supply-chain stage an
  item belongs to is always interpretation;
- unknowns: what the retained text does not state ("not stated in this source": the matter may be settled in a
  document not read here), documents the source names that were not retained, and what each comparison leaves open.
Every figure a statement, label or observation gives must appear in the passages it cites (or in a cited listing
time), so a number cannot enter by paraphrase; "why this helps" carries no figures at all.

Binding. The file names the snapshot's acquisition, SHA-256 and extractor version, and for each publication its record
key, record SHA-256, paragraph count and listing times. Each read verifies the retained page against its acquisition
record (bis_snapshot.locate), extracts its records (kept in memory per verified SHA-256, never written) and checks
every binding and every quoted passage. A publication whose source is not on this machine is "missing"; one whose
source differs from the bound version, or whose quoted passage is no longer found, is "changed". A comparison is
available only when all its publications verify (and the terms it reports absent are still absent); otherwise it is
unavailable (a source missing) or needs revalidation (a source changed), and its observation and evidence are
withheld. Two publications also name a separately retained release page; when it verifies, its dateline is shown and
the listing's text is checked to appear on it, in order, directly after the dateline. A page that is missing or
changed only withholds that dateline and check.

Reads only: nothing here writes, fetches or calls a model, and the content is never regenerated on read or at
startup. An invalid file refuses the whole view.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

from . import bis_snapshot, case_library, related_cases

RESEARCH_VERSION = "policy-research-0.1"
VIEW_VERSION = "policy-research-view-0.1"
CATALOG_VERSION = "policy-research-catalog-0.1"
ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "content" / "research"
FILE = "research.json"
SNAPSHOT_APPROVAL = bis_snapshot.APPROVAL_ID
# Where each approval's retained copies live, relative to the repository (as their acquisition records state).
RETAINED = {"bis-semis-sources-01": "data/sector-sources/bis",
            "related-cases-sources-01": "data/sector-sources/related-cases"}
DEFAULT_SOURCES = {"bis-semis-sources-01": bis_snapshot.SOURCES_DIR,
                   "related-cases-sources-01": related_cases.SOURCES_DIR}
HOST = "www.bis.gov"
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
KEY = re.compile(r"[0-9a-f]{20}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PRESS_RELEASE = re.compile(r"/press-release/[a-z0-9][a-z0-9.-]{0,280}")
DIGITS = re.compile(r"\d+")
LONG_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December) "
                       r"(\d{1,2}), (\d{4})")
# Curator wording that would turn a comparison into a claim this project does not make. Quotes are the publisher's
# words and are not scanned; the explicit list of claims not made is the one place such words may appear.
BANNED = re.compile(r"\b(confirm(s|ed|ation)?|prove[sdn]?|proof|caus(e|es|ed|al|ation)|buy|sell|signals?|"
                    r"recommend(s|ed|ation)?|repeal(s|ed)?|forecasts?|mispric\w*|does not exist)\b", re.I)
MAX_TEXT, MAX_LABEL, MAX_QUOTE, MIN_QUOTE = 900, 160, 320, 8
MAX_FILE_BYTES = 1_000_000

DIMENSIONS = {"instrument": "Instrument", "relation": "Stated relation to earlier publications",
              "scope": "Technology or product scope", "parties": "Jurisdictions, actors and end uses",
              "supply_chain": "Supply-chain stages named", "timing": "Announcement and effective dates",
              "conditions": "Exceptions, thresholds and conditions"}
STATUSES = {"stated": "Publisher statement", "interpretation": "Curator interpretation",
            "not_stated": "Not stated in this source", "referenced_unread": "In a linked document not retained"}
STAGES = {"design_software": "Chip-design software", "equipment": "Chip-making equipment",
          "fabrication": "Chip fabrication", "memory": "Memory", "chips": "Advanced computing chips",
          "computing_systems": "Supercomputers and data centers", "ai_models": "AI models"}
DATE_KINDS = {"effective": "Takes effect", "compliance": "Compliance date", "comment_deadline": "Comments due",
              "license_deadline": "Licenses needed", "issued": "Issued, as stated", "conduct": "Conduct",
              "designation": "Placed on the Entity List"}
PRECISIONS = {"day": "Day", "year": "Year only", "relative": "Relative to another date"}
COMPARISON_KINDS = {"stated_change": "A change the source states", "instrument": "Rule, clarification or enforcement",
                    "non_equivalent": "Alike, not shown to be the same", "different_subjects": "One name, two subjects",
                    "dates": "Which date, how precise"}
LISTING_FIELDS = {"published": "BIS listing time", "created": "CMS creation time", "changed": "CMS last change"}
PUBLICATION_STATES = {"verified": "Checked against the retained source on this machine",
                      "changed": "The retained source differs from the version this was written against",
                      "missing": "The retained source is not on this machine"}
COMPARISON_STATES = {"available": "Checked against the retained sources",
                     "needs_revalidation": "Needs revalidation: a source changed",
                     "unavailable": "Unavailable: a source is not on this machine"}
CASE_KINDS = {"library": "/library/{id}", "historical": "/library/historical/{id}"}
TEXT_STATES = {"checked": "Checked: the listing's paragraphs appear, in order, directly after the dateline of a "
                          "separately retained release page.",
               "listing_text": "Listing text: as embedded in BIS's News & Updates listing on the retrieval date; not "
                               "checked against a release page."}

FIELDS = {"research_version", "id", "title", "question", "scope_note", "corpus_notes", "method_note", "snapshot",
          "release_pages", "publications", "comparisons", "not_included", "not_claimed", "provenance"}
SNAPSHOT_FIELDS = {"approval_id", "attempt", "url", "sha256", "bytes", "retrieved_at", "extractor_version"}
PAGE_FIELDS = {"id", "approval_id", "attempt", "folder", "url", "sha256", "bytes", "retrieved_at", "dateline"}
PUBLICATION_FIELDS = {"id", "short_title", "title", "url", "record", "listing", "release_page", "why_included",
                      "cases", "dimensions", "references"}
RECORD_FIELDS = {"key", "record_sha256", "paragraphs"}
CASE_FIELDS = {"kind", "id", "note"}
DIMENSION_FIELDS = {"label", "statements"}
STATEMENT_FIELDS = {"status", "text", "excerpts", "reference", "stage", "dates"}
EXCERPT_FIELDS = {"paragraph", "quote"}
DATE_FIELDS = {"kind", "value", "precision", "as_stated"}
REFERENCE_FIELDS = {"id", "description", "excerpts"}
COMPARISON_FIELDS = {"id", "kind", "question", "publications", "observation", "evidence", "why", "unknown",
                     "would_establish"}
EVIDENCE_FIELDS = {"publication", "paragraph", "quote", "field", "value", "absent"}
NOT_INCLUDED_FIELDS = {"title", "url", "key", "record_sha256", "listed", "reason", "case"}
PROVENANCE_FIELDS = {"prepared_by", "prepared_on", "method", "ai_assisted", "human_review", "research_use"}
FIXED_PROVENANCE = {"ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded"}


class PolicyRefused(ValueError):
    """A research view cannot be served; ``status`` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _invalid(where: str, problem: str) -> PolicyRefused:
    return PolicyRefused(500, f"The research file is invalid ({where}: {problem}); nothing is served")


def _check(condition: bool, where: str, problem: str) -> None:
    if not condition:
        raise _invalid(where, problem)


def _fields(value: object, expected: set[str], where: str) -> dict:
    _check(isinstance(value, dict) and set(value) == expected, where, f"expected exactly the fields {sorted(expected)}")
    return value


def _text(value: object, where: str, limit: int = MAX_TEXT, scan: bool = True) -> str:
    _check(isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= limit and
           not any(ord(char) < 32 for char in value), where, f"expected one line of text of at most {limit} characters")
    if scan:
        found = BANNED.search(value)
        _check(found is None, where, f"uses {found.group(0)!r}, which belongs only to the list of claims not made"
               if found else "")
    return value


def _list(value: object, where: str, minimum: int = 0) -> list:
    _check(isinstance(value, list) and len(value) >= minimum, where, f"expected a list of at least {minimum}")
    return value


def _count(value: object, where: str, minimum: int = 1) -> int:
    _check(type(value) is int and value >= minimum, where, f"expected an integer of at least {minimum}")
    return value


def _moment(value: object, where: str) -> datetime:
    try:
        moment = datetime.fromisoformat(_text(value, where, 40, scan=False))
    except ValueError:
        moment = None
    _check(moment is not None and moment.utcoffset() is not None, where, "expected an ISO time with an offset")
    return moment


def _release_url(value: object, where: str) -> str:
    parts = urlsplit(_text(value, where, 400, scan=False))
    _check(parts.scheme == "https" and parts.hostname == HOST and not parts.query and not parts.fragment and
           not parts.port and bool(PRESS_RELEASE.fullmatch(parts.path)) and value == f"https://{HOST}{parts.path}",
           where, f"expected a press-release address at {HOST}")
    return value


def _quote(value: object, where: str) -> str:
    quote = _text(value, where, MAX_QUOTE, scan=False)
    _check(len(quote) >= MIN_QUOTE and not quote.startswith("#") and "|" not in quote and "<" not in quote, where,
           f"expected a plain passage of {MIN_QUOTE} to {MAX_QUOTE} characters, without markup")
    return quote


def long_date(moment: datetime) -> str:
    """A listing time as a release prints a date ("January 13, 2025"), in UTC."""
    return f"{moment:%B} {moment.day}, {moment.year}"


def _figures(text: str) -> set[str]:
    return set(DIGITS.findall(text))


def _held_to(text: str, allowed: str, where: str) -> None:
    extra = _figures(text) - _figures(allowed)
    _check(not extra, where, f"states figures its cited passages do not: {sorted(extra)}")


def _excerpts(value: object, paragraphs: int, where: str, minimum: int) -> list[dict]:
    items = _list(value, where, minimum)
    for number, item in enumerate(items):
        _fields(item, EXCERPT_FIELDS, f"{where}[{number}]")
        _check(type(item["paragraph"]) is int and 1 <= item["paragraph"] <= paragraphs, f"{where}[{number}].paragraph",
               f"expected a paragraph number from 1 to {paragraphs}")
        _quote(item["quote"], f"{where}[{number}].quote")
    return items


def _dates(value: object, quotes: str, where: str) -> list[dict]:
    items = _list(value, where)
    for number, item in enumerate(items):
        place = f"{where}[{number}]"
        _fields(item, DATE_FIELDS, place)
        _check(item["kind"] in DATE_KINDS, f"{place}.kind", f"expected one of {list(DATE_KINDS)}")
        _check(item["precision"] in PRECISIONS, f"{place}.precision", f"expected one of {list(PRECISIONS)}")
        as_stated = _text(item["as_stated"], f"{place}.as_stated", 200, scan=False)
        _check(as_stated in quotes, f"{place}.as_stated", "must be quoted from the statement's own passages")
        if item["precision"] == "relative":
            _check(item["value"] is None, f"{place}.value", "a relative date has no calendar value")
        elif item["precision"] == "year":
            _check(isinstance(item["value"], str) and bool(re.fullmatch(r"\d{4}", item["value"])) and
                   item["value"] in as_stated, f"{place}.value", "expected a year that the passage states")
        else:
            written = LONG_DATE.search(as_stated)
            try:
                stated = datetime.strptime(written.group(0), "%B %d, %Y").date().isoformat() if written else None
            except ValueError:
                stated = None
            _check(isinstance(item["value"], str) and stated == item["value"], f"{place}.value",
                   "expected the YYYY-MM-DD date that the passage states")
    return items


def _check_publication(item: object, number: int, pages: dict, seen: set) -> dict:
    where = f"publications[{number}]"
    _fields(item, PUBLICATION_FIELDS, where)
    _check(isinstance(item["id"], str) and bool(ID.fullmatch(item["id"])) and item["id"] not in seen, f"{where}.id",
           "expected a distinct lower-case id")
    where = f"publications[{item['id']}]"
    _text(item["short_title"], f"{where}.short_title", 120)
    _text(item["title"], f"{where}.title", 400, scan=False)
    _release_url(item["url"], f"{where}.url")
    record = _fields(item["record"], RECORD_FIELDS, f"{where}.record")
    _check(isinstance(record["key"], str) and bool(KEY.fullmatch(record["key"])), f"{where}.record.key",
           "expected a snapshot record key")
    _check(record["key"] == bis_snapshot.sha256(item["url"].encode("utf-8"))[:20], f"{where}.record.key",
           "is not the key of the publication's address")
    _check(isinstance(record["record_sha256"], str) and bool(SHA256.fullmatch(record["record_sha256"])),
           f"{where}.record.record_sha256", "expected a SHA-256")
    paragraphs = _count(record["paragraphs"], f"{where}.record.paragraphs")
    listing = _fields(item["listing"], set(LISTING_FIELDS), f"{where}.listing")
    _moment(listing["published"], f"{where}.listing.published")
    for field in ("created", "changed"):
        if listing[field] is not None:
            _moment(listing[field], f"{where}.listing.{field}")
    _check(item["release_page"] is None or item["release_page"] in pages, f"{where}.release_page",
           "names no declared release page")
    if item["release_page"] is not None:
        _check(pages[item["release_page"]]["url"] == item["url"], f"{where}.release_page",
               "is the page of another address")
    _text(item["why_included"], f"{where}.why_included")
    cases = _list(item["cases"], f"{where}.cases")
    for index, case in enumerate(cases):
        _check_case_link(case, f"{where}.cases[{index}]")

    references = _list(item["references"], f"{where}.references")
    reference_ids = []
    for index, reference in enumerate(references):
        place = f"{where}.references[{index}]"
        _fields(reference, REFERENCE_FIELDS, place)
        _check(isinstance(reference["id"], str) and bool(ID.fullmatch(reference["id"])) and
               reference["id"] not in reference_ids, f"{place}.id", "expected a distinct lower-case id")
        _text(reference["description"], f"{place}.description", 200)
        _excerpts(reference["excerpts"], paragraphs, f"{place}.excerpts", 1)
        reference_ids.append(reference["id"])

    dimensions = _fields(item["dimensions"], set(DIMENSIONS), f"{where}.dimensions")
    listed = long_date(datetime.fromisoformat(listing["published"]))
    for name in DIMENSIONS:
        place = f"{where}.dimensions.{name}"
        dimension = _fields(dimensions[name], DIMENSION_FIELDS, place)
        statements = _list(dimension["statements"], f"{place}.statements", 1)
        cited = []
        for index, statement in enumerate(statements):
            spot = f"{place}.statements[{index}]"
            _fields(statement, STATEMENT_FIELDS, spot)
            status = statement["status"]
            _check(status in STATUSES, f"{spot}.status", f"expected one of {list(STATUSES)}")
            text = _text(statement["text"], f"{spot}.text")
            excerpts = _excerpts(statement["excerpts"], paragraphs, f"{spot}.excerpts",
                                 0 if status == "not_stated" else 1)
            quotes = " ".join(excerpt["quote"] for excerpt in excerpts)
            cited.append(quotes)
            if status == "not_stated":  # Silence is reported as silence: nothing is quoted for it.
                _check(not excerpts, f"{spot}.excerpts", "a statement the source does not make quotes nothing")
            else:
                _held_to(text, quotes, f"{spot}.text")
            _check((statement["reference"] in reference_ids) if status == "referenced_unread"
                   else statement["reference"] is None, f"{spot}.reference",
                   "only a referenced_unread statement names a reference, and it must name a declared one")
            if name == "supply_chain":  # Placing an item in the chain is always the curator's reading.
                _check(status in ("interpretation", "not_stated"), f"{spot}.status",
                       "supply-chain stages are curator interpretation (or not stated)")
                _check((statement["stage"] in STAGES) if status == "interpretation" else statement["stage"] is None,
                       f"{spot}.stage", f"expected one of {list(STAGES)} for an interpretation, otherwise null")
            else:
                _check(statement["stage"] is None, f"{spot}.stage", "only supply-chain statements name a stage")
            dates = _dates(statement["dates"], quotes, f"{spot}.dates")
            _check(not dates or (name == "timing" and status == "stated"), f"{spot}.dates",
                   "only stated timing statements carry dates")
        _text(dimension["label"], f"{place}.label", MAX_LABEL)
        _held_to(dimension["label"], " ".join(cited) + " " + listed, f"{place}.label")
    stages = [statement["stage"] for statement in dimensions["supply_chain"]["statements"] if statement["stage"]]
    _check(len(set(stages)) == len(stages), f"{where}.dimensions.supply_chain", "names a stage twice")
    return item


def _check_case_link(case: object, where: str) -> None:
    _fields(case, CASE_FIELDS, where)
    _check(case["kind"] in CASE_KINDS and isinstance(case["id"], str) and bool(ID.fullmatch(case["id"])), where,
           f"expected a case of kind {list(CASE_KINDS)} with a lower-case id")
    _text(case["note"], f"{where}.note", 300)


def _check_research(raw: object, research_id: str) -> dict:
    _fields(raw, FIELDS, "research")
    _check(raw["research_version"] == RESEARCH_VERSION, "research_version", f"expected {RESEARCH_VERSION}")
    _check(raw["id"] == research_id, "id", "does not match its folder")
    for field, limit in (("title", 120), ("question", 400), ("scope_note", 400), ("method_note", MAX_TEXT)):
        _text(raw[field], field, limit)
    for number, note in enumerate(_list(raw["corpus_notes"], "corpus_notes", 1)):
        _text(note, f"corpus_notes[{number}]")
    snapshot = _fields(raw["snapshot"], SNAPSHOT_FIELDS, "snapshot")
    _check(snapshot["approval_id"] == SNAPSHOT_APPROVAL and snapshot["url"] == bis_snapshot.PAGE_URL, "snapshot",
           f"expected the retained {bis_snapshot.PAGE_URL} of approval {SNAPSHOT_APPROVAL}")
    _count(snapshot["attempt"], "snapshot.attempt")
    _count(snapshot["bytes"], "snapshot.bytes")
    _check(isinstance(snapshot["sha256"], str) and bool(SHA256.fullmatch(snapshot["sha256"])), "snapshot.sha256",
           "expected a SHA-256")
    _moment(snapshot["retrieved_at"], "snapshot.retrieved_at")
    _text(snapshot["extractor_version"], "snapshot.extractor_version", 60, scan=False)

    pages = {}
    for number, page in enumerate(_list(raw["release_pages"], "release_pages")):
        where = f"release_pages[{number}]"
        _fields(page, PAGE_FIELDS, where)
        _check(isinstance(page["id"], str) and bool(ID.fullmatch(page["id"])) and page["id"] not in pages,
               f"{where}.id", "expected a distinct lower-case id")
        _check(page["approval_id"] in RETAINED, f"{where}.approval_id", f"expected one of {list(RETAINED)}")
        _count(page["attempt"], f"{where}.attempt")
        _check(isinstance(page["folder"], str) and bool(ID.fullmatch(page["folder"])), f"{where}.folder",
               "expected a lower-case folder name")
        _release_url(page["url"], f"{where}.url")
        _check(isinstance(page["sha256"], str) and bool(SHA256.fullmatch(page["sha256"])), f"{where}.sha256",
               "expected a SHA-256")
        _count(page["bytes"], f"{where}.bytes")
        _moment(page["retrieved_at"], f"{where}.retrieved_at")
        _check(isinstance(page["dateline"], str) and bool(LONG_DATE.fullmatch(page["dateline"])), f"{where}.dateline",
               "expected a date as the release prints it")
        pages[page["id"]] = page

    publications, seen = {}, set()
    for number, item in enumerate(_list(raw["publications"], "publications", 2)):
        publication = _check_publication(item, number, pages, seen)
        seen.add(publication["id"])
        publications[publication["id"]] = publication
    order = [datetime.fromisoformat(item["listing"]["published"]) for item in raw["publications"]]
    _check(order == sorted(order), "publications", "expected chronological order of listing time")
    keys = [item["record"]["key"] for item in raw["publications"]]
    _check(len(set(keys)) == len(keys), "publications", "lists one record twice")

    comparison_ids = set()
    for number, comparison in enumerate(_list(raw["comparisons"], "comparisons", 1)):
        where = f"comparisons[{number}]"
        _fields(comparison, COMPARISON_FIELDS, where)
        _check(isinstance(comparison["id"], str) and bool(ID.fullmatch(comparison["id"])) and
               comparison["id"] not in comparison_ids, f"{where}.id", "expected a distinct lower-case id")
        where = f"comparisons[{comparison['id']}]"
        _check(comparison["kind"] in COMPARISON_KINDS, f"{where}.kind", f"expected one of {list(COMPARISON_KINDS)}")
        _text(comparison["question"], f"{where}.question", 300)
        compared = _list(comparison["publications"], f"{where}.publications", 2)
        _check(len(set(compared)) == len(compared) and all(item in publications for item in compared),
               f"{where}.publications", "expected distinct ids of selected publications")
        _check(compared == [item for item in publications if item in compared], f"{where}.publications",
               "expected chronological order")
        allowed, cited = [], set()
        for index, evidence in enumerate(_list(comparison["evidence"], f"{where}.evidence", 2)):
            place = f"{where}.evidence[{index}]"
            _fields(evidence, EVIDENCE_FIELDS, place)
            _check(evidence["publication"] in compared, f"{place}.publication", "names no compared publication")
            target = publications[evidence["publication"]]
            forms = [evidence["quote"] is not None, evidence["field"] is not None, evidence["absent"] is not None]
            _check(sum(forms) == 1, place, "expected exactly one of a quote, a listing field or an absent term")
            if forms[0]:
                _check(type(evidence["paragraph"]) is int and
                       1 <= evidence["paragraph"] <= target["record"]["paragraphs"], f"{place}.paragraph",
                       "expected a paragraph number of that publication")
                allowed.append(_quote(evidence["quote"], f"{place}.quote"))
                _check(evidence["value"] is None, place, "a quote carries no listing value")
            elif forms[1]:
                _check(evidence["field"] in LISTING_FIELDS and evidence["paragraph"] is None, f"{place}.field",
                       f"expected one of {list(LISTING_FIELDS)}")
                _check(evidence["value"] == target["listing"][evidence["field"]], f"{place}.value",
                       "is not the publication's listing value")
                allowed.append(long_date(datetime.fromisoformat(evidence["value"])))
            else:
                _check(evidence["paragraph"] is None and evidence["value"] is None, place,
                       "an absent term carries no paragraph or value")
                _text(evidence["absent"], f"{place}.absent", 60, scan=False)
            cited.add(evidence["publication"])
        _check(cited == set(compared), f"{where}.evidence", "expected evidence from every compared publication")
        listed = " ".join(long_date(datetime.fromisoformat(publications[item]["listing"]["published"]))
                          for item in compared)
        observation = _text(comparison["observation"], f"{where}.observation")
        _held_to(observation, " ".join(allowed) + " " + listed, f"{where}.observation")
        why = _text(comparison["why"], f"{where}.why")
        _check(not DIGITS.search(why), f"{where}.why", "why this helps is interpretation and states no figures")
        _text(comparison["unknown"], f"{where}.unknown")
        _text(comparison["would_establish"], f"{where}.would_establish", 400)
        comparison_ids.add(comparison["id"])

    for number, item in enumerate(_list(raw["not_included"], "not_included")):
        where = f"not_included[{number}]"
        _fields(item, NOT_INCLUDED_FIELDS, where)
        _text(item["title"], f"{where}.title", 400, scan=False)
        _release_url(item["url"], f"{where}.url")
        _check(item["key"] == bis_snapshot.sha256(item["url"].encode("utf-8"))[:20] and item["key"] not in keys,
               f"{where}.key", "expected the key of an address that is not selected")
        _check(isinstance(item["record_sha256"], str) and bool(SHA256.fullmatch(item["record_sha256"])),
               f"{where}.record_sha256", "expected a SHA-256")
        _moment(item["listed"], f"{where}.listed")
        _text(item["reason"], f"{where}.reason")
        if item["case"] is not None:
            _check_case_link(item["case"], f"{where}.case")
    for number, claim in enumerate(_list(raw["not_claimed"], "not_claimed", 1)):
        _text(claim, f"not_claimed[{number}]", 300, scan=False)
    provenance = _fields(raw["provenance"], PROVENANCE_FIELDS, "provenance")
    for field, value in FIXED_PROVENANCE.items():
        _check(provenance[field] == value and type(provenance[field]) is type(value), f"provenance.{field}",
               f"must be {json.dumps(value)}")
    _text(provenance["prepared_by"], "provenance.prepared_by", 200)
    _text(provenance["method"], "provenance.method")
    _check(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(provenance["prepared_on"]))) and
           provenance["prepared_on"] >= snapshot["retrieved_at"][:10], "provenance.prepared_on",
           "expected a YYYY-MM-DD date no earlier than the snapshot's retrieval")
    return raw


def load(research_id: str, root: Path = RESEARCH_DIR) -> dict:
    """One research file, strictly checked. Reads only."""
    if not isinstance(research_id, str) or not ID.fullmatch(research_id):
        raise PolicyRefused(404, "No research view has this id")
    path = root / research_id / FILE
    if not path.is_file():
        raise PolicyRefused(404, "No research view has this id")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise _invalid(FILE, "larger than a research file may be")
    try:
        text = raw.decode("utf-8")
        loaded = bis_snapshot._strict_json(text, "The research file")
    except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        raise _invalid(FILE, "not strict UTF-8 JSON") from None
    return _check_research(loaded, research_id)


def catalog(root: Path = RESEARCH_DIR) -> dict:
    """The committed research views, for listing: read as content only, so no retained source is read here."""
    views = []
    if root.is_dir():
        for folder in sorted(path for path in root.iterdir() if path.is_dir() and (path / FILE).is_file()):
            research = load(folder.name, root)
            views.append({"id": research["id"], "title": research["title"], "question": research["question"],
                          "scope_note": research["scope_note"], "publications": len(research["publications"]),
                          "comparisons": len(research["comparisons"]), "href": f"/library/research/{research['id']}"})
    return {"view_version": CATALOG_VERSION, "views": views, "provider_called": False}


# ---------------------------------------------------------------- the retained sources, checked on every read

_MEMO: dict[str, dict] = {}
_MEMO_LOCK = threading.Lock()


def _extracted(package_sha256: str, raw: bytes) -> dict:
    """The snapshot's records by key, for bytes that were just verified; kept in memory for that SHA-256 only."""
    with _MEMO_LOCK:
        held = _MEMO.get(package_sha256)
    if held is None:
        extracted = bis_snapshot.extract(raw)
        held = {"records": {record["key"]: record for record in extracted["records"]},
                "filter_matches": sum(1 for record in extracted["records"]
                                      if record["filters"]["semiconductors"]["matched"])}
        with _MEMO_LOCK:
            _MEMO.clear()
            _MEMO[package_sha256] = held
    return held


def _snapshot(bound: dict, sources: dict) -> tuple[dict, dict | None]:
    """(the snapshot's state, its records when it verifies as the bound version)."""
    try:
        package, raw, _ = bis_snapshot.locate(sources[SNAPSHOT_APPROVAL])
    except bis_snapshot.SnapshotRefused as exc:
        return {"state": "missing" if exc.status == 503 else "changed", "detail": str(exc)}, None
    if {key: package[key] for key in ("attempt", "sha256", "bytes", "retrieved_at")} != \
            {key: bound[key] for key in ("attempt", "sha256", "bytes", "retrieved_at")}:
        return {"state": "changed", "detail": f"The retained snapshot on this machine (SHA-256 {package['sha256'][:16]}…) "
                                              "is not the version this research was written against."}, None
    if bound["extractor_version"] != bis_snapshot.EXTRACTOR_VERSION:
        return {"state": "changed", "detail": f"This research was written with extractor {bound['extractor_version']}; "
                                              f"this machine's is {bis_snapshot.EXTRACTOR_VERSION}."}, None
    held = _extracted(package["sha256"], raw)
    return {"state": "verified", "detail": "The retained snapshot on this machine matches its acquisition record and "
                                           "the version this research was written against."}, held


def _found(record: dict, excerpts) -> list[str]:
    """The problems of quoted passages that are not where the research places them."""
    paragraphs = record["text"]["paragraphs"]
    return [f"Paragraph {item['paragraph']} no longer holds the quoted passage “{item['quote'][:60]}…”"
            for item in excerpts
            if item["paragraph"] > len(paragraphs) or item["quote"] not in paragraphs[item["paragraph"] - 1]]


def _record_problems(item: dict, record: dict | None) -> list[str]:
    if record is None:
        return ["The verified snapshot holds no record with this key."]
    problems = []
    if record["identity"] != item["url"]:
        problems.append("The record's address differs.")
    if record["record_sha256"] != item["record"]["record_sha256"]:
        problems.append("The record's content differs from the version this research was written against.")
    if record["publisher"]["title"] != item["title"]:
        problems.append("The record's title differs.")
    if len(record["text"]["paragraphs"]) != item["record"]["paragraphs"] or record["text"]["truncated"] or \
            record["text"]["state"] != "listing_text":
        problems.append("The record's text is not the complete listing text this research was written against.")
    if any(record["listing"][field]["time"] != item["listing"][field] for field in LISTING_FIELDS):
        problems.append("The record's listing times differ.")
    return problems


def _all_excerpts(item: dict, comparisons: list[dict]) -> list[dict]:
    excerpts = [excerpt for dimension in item["dimensions"].values() for statement in dimension["statements"]
                for excerpt in statement["excerpts"]]
    excerpts += [excerpt for reference in item["references"] for excerpt in reference["excerpts"]]
    excerpts += [{"paragraph": evidence["paragraph"], "quote": evidence["quote"]} for comparison in comparisons
                 for evidence in comparison["evidence"]
                 if evidence["publication"] == item["id"] and evidence["quote"] is not None]
    return excerpts


def _release_page(page: dict, sources: dict) -> tuple[dict, list[str] | None]:
    """(the page's state, its text lines after the dateline when it verifies)."""
    base = {key: page[key] for key in ("id", "url", "approval_id", "sha256", "bytes", "retrieved_at", "dateline")}
    root = sources.get(page["approval_id"])
    path = root / page["folder"] / "source.html" if root else None
    record_path = root / "acquisitions" / page["approval_id"] / f"outcome-{page['attempt']}.json" if root else None
    if path is None or not path.is_file() or not record_path.is_file():
        return {**base, "state": "missing", "detail": "The release page or its acquisition record is not on this "
                                                      "machine; its dateline is not shown."}, None
    raw = path.read_bytes()
    if len(raw) != page["bytes"] or hashlib.sha256(raw).hexdigest() != page["sha256"]:
        return {**base, "state": "changed", "detail": "The release page on this machine is not the recorded copy (its "
                                                      "size or SHA-256 differs); its dateline is not shown."}, None
    try:
        outcome = bis_snapshot._strict_json(record_path.read_text(encoding="utf-8"), "The acquisition record")
    except (OSError, UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        outcome = None
    expected = {"outcome": "complete", "http_status": 200, "url": page["url"], "sha256": page["sha256"],
                "bytes": page["bytes"], "approval_id": page["approval_id"], "hash_kind": "complete_response",
                "retained": f"{RETAINED[page['approval_id']]}/{page['folder']}/source.html",
                "body_completed_at": page["retrieved_at"]}
    headers = (outcome or {}).get("named_headers") if isinstance(outcome, dict) else None
    if not isinstance(outcome, dict) or any(outcome.get(key) != value for key, value in expected.items()) or \
            not isinstance(headers, dict) or headers.get("content-type") != "text/html; charset=utf-8" or \
            headers.get("content-encoding") is not None:
        return {**base, "state": "changed", "detail": "The release page's acquisition record does not agree with it; "
                                                      "its dateline is not shown."}, None
    try:
        lines, _ = bis_snapshot.paragraphs(raw.decode("utf-8"))
    except (UnicodeDecodeError, bis_snapshot.Unreadable):
        return {**base, "state": "changed", "detail": "The release page could not be read as text."}, None
    start = next((index for index, line in enumerate(lines) if line.startswith("FOR IMMEDIATE RELEASE")), None)
    dateline = bis_snapshot.DATELINE.search(lines[start]) if start is not None else None
    if dateline is None or dateline.group(1) != page["dateline"]:
        return {**base, "state": "changed", "detail": "The release page does not carry the recorded dateline."}, None
    return {**base, "state": "verified", "detail": "The release page matches its acquisition record and carries the "
                                                   "recorded dateline."}, lines[start + 1:]


def _text_check(item: dict, record: dict | None, page: dict | None, lines: list[str] | None) -> dict:
    if page is None:
        return {"status": "listing_text", "detail": TEXT_STATES["listing_text"]}
    if lines is None or record is None:
        return {"status": "listing_text", "detail": TEXT_STATES["listing_text"] + " A separately retained release "
                "page exists, but it could not be checked on this machine."}
    body = [line for line in lines if line not in (item["title"], "Download as PDF")]
    paragraphs = record["text"]["paragraphs"]
    if body[:len(paragraphs)] != paragraphs:
        return {"status": "listing_text", "detail": "The listing's text does not appear on the separately retained "
                                                    "release page as recorded; it is shown as listing text."}
    return {"status": "checked", "detail": TEXT_STATES["checked"]}


def _cases(links: list[dict], library_titles: dict, historical_titles: dict) -> list[dict]:
    resolved = []
    for link in links:
        titles = library_titles if link["kind"] == "library" else historical_titles
        if link["id"] not in titles:
            raise _invalid("cases", f"names no {link['kind']} case {link['id']!r}")
        resolved.append({"kind": link["kind"], "id": link["id"], "title": titles[link["id"]],
                         "href": CASE_KINDS[link["kind"]].format(id=link["id"]), "note": link["note"]})
    return resolved


def _evidence(evidence: dict, publication: dict, record: dict) -> dict:
    kind = "quote" if evidence["quote"] is not None else "field" if evidence["field"] is not None else "absence"
    return {"publication": evidence["publication"], "kind": kind, "paragraph": evidence["paragraph"],
            "paragraphs": len(record["text"]["paragraphs"]), "quote": evidence["quote"], "field": evidence["field"],
            "value": evidence["value"], "absent": evidence["absent"]}


def view(research_id: str, root: Path = RESEARCH_DIR, sources: dict | None = None,
         library: Path = case_library.LIBRARY_DIR, related: Path = related_cases.CASES_DIR) -> dict:
    """The research view with every binding checked against the retained sources on this machine. Reads only."""
    sources = {**DEFAULT_SOURCES, **(sources or {})}
    research = load(research_id, root)
    try:
        library_titles = {case["id"]: case["title"] for case in case_library.load_library(library)["cases"]}
        historical_titles = {case["id"]: case["title"] for case in related_cases.load(related)["cases"]}
    except (case_library.LibraryRefused, related_cases.RelatedRefused) as exc:
        raise PolicyRefused(500, f"The case library could not be read, so this view's links to cases cannot be "
                                 f"checked ({exc})") from None
    snapshot, held = _snapshot(research["snapshot"], sources)
    records = held["records"] if held else {}
    pages = {}
    for page in research["release_pages"]:
        pages[page["id"]] = _release_page(page, sources)

    publications, states = [], {}
    for position, item in enumerate(research["publications"], start=1):
        record = records.get(item["record"]["key"]) if held else None
        if held is None:
            state, problems = snapshot["state"], [snapshot["detail"]]
        else:
            problems = _record_problems(item, record)
            if not problems:
                problems = _found(record, _all_excerpts(item, research["comparisons"]))
            state = "changed" if problems else "verified"
        states[item["id"]] = state
        page_state, lines = pages[item["release_page"]] if item["release_page"] else (None, None)
        verified = state == "verified"
        dateline = None
        if page_state is not None:
            dateline = {"page": page_state["id"], "state": page_state["state"],
                        "value": page_state["dateline"] if page_state["state"] == "verified" else None,
                        "detail": page_state["detail"]}
        publications.append({
            "id": item["id"], "position": position, "short_title": item["short_title"], "title": item["title"],
            "url": item["url"], "state": state, "problems": problems, "record": item["record"],
            "listing": item["listing"], "dateline": dateline,
            "text": _text_check(item, record if verified else None, page_state, lines),
            "why_included": item["why_included"], "cases": _cases(item["cases"], library_titles, historical_titles),
            "dimensions": item["dimensions"] if verified else None,
            "stages": [statement["stage"] for statement in item["dimensions"]["supply_chain"]["statements"]
                       if statement["stage"]] if verified else None,
            "references": item["references"] if verified else None})
    by_id = {item["id"]: item for item in research["publications"]}

    comparisons = []
    for comparison in research["comparisons"]:
        compared = comparison["publications"]
        problems = [f"{by_id[item]['short_title']}: {PUBLICATION_STATES[states[item]].lower()}." for item in compared
                    if states[item] != "verified"]
        if any(states[item] == "missing" for item in compared):
            state = "unavailable"
        elif problems:
            state = "needs_revalidation"
        else:
            present = [evidence for evidence in comparison["evidence"] if evidence["absent"] is not None and any(
                evidence["absent"].casefold() in paragraph.casefold()
                for paragraph in records[by_id[evidence["publication"]]["record"]["key"]]["text"]["paragraphs"])]
            problems = [f"{by_id[evidence['publication']]['short_title']}: the text now contains "
                        f"“{evidence['absent']}”, which this comparison reports absent." for evidence in present]
            state = "needs_revalidation" if problems else "available"
        available = state == "available"
        comparisons.append({
            "id": comparison["id"], "kind": comparison["kind"], "question": comparison["question"],
            "publications": compared, "state": state, "problems": problems,
            "observation": comparison["observation"] if available else None,
            "evidence": [_evidence(evidence, by_id[evidence["publication"]],
                                   records[by_id[evidence["publication"]]["record"]["key"]])
                         for evidence in comparison["evidence"]] if available else None,
            "why": comparison["why"] if available else None,
            "unknown": comparison["unknown"] if available else None,
            "would_establish": comparison["would_establish"] if available else None})

    not_included = []
    for item in research["not_included"]:
        record = records.get(item["key"]) if held else None
        if held is None:
            state = snapshot["state"]
        else:
            state = "verified" if record is not None and record["identity"] == item["url"] and \
                record["record_sha256"] == item["record_sha256"] and record["publisher"]["title"] == item["title"] \
                and record["listing"]["published"]["time"] == item["listed"] else "changed"
        not_included.append({"title": item["title"], "url": item["url"], "listed": item["listed"],
                             "reason": item["reason"], "state": state,
                             "case": _cases([item["case"]], library_titles, historical_titles)[0]
                             if item["case"] else None})

    bound = research["snapshot"]
    return {
        "view_version": VIEW_VERSION, "research_version": research["research_version"], "id": research["id"],
        "title": research["title"], "question": research["question"], "scope_note": research["scope_note"],
        "corpus_notes": research["corpus_notes"], "method_note": research["method_note"], "provider_called": False,
        "labels": {"statuses": STATUSES, "dimensions": DIMENSIONS, "stages": STAGES, "date_kinds": DATE_KINDS,
                   "precisions": PRECISIONS, "comparison_kinds": COMPARISON_KINDS, "listing_fields": LISTING_FIELDS,
                   "publication_states": PUBLICATION_STATES, "comparison_states": COMPARISON_STATES},
        "snapshot": {**{key: bound[key] for key in ("approval_id", "url", "sha256", "bytes", "retrieved_at",
                                                    "extractor_version")}, **snapshot,
                     "filter_matches": held["filter_matches"] if held else None},
        "release_pages": [pages[page["id"]][0] for page in research["release_pages"]],
        "counts": {"publications": {name: sum(1 for item in publications if item["state"] == name)
                                    for name in PUBLICATION_STATES},
                   "comparisons": {name: sum(1 for item in comparisons if item["state"] == name)
                                   for name in COMPARISON_STATES}},
        "publications": publications, "comparisons": comparisons, "not_included": not_included,
        "not_claimed": research["not_claimed"], "provenance": research["provenance"]}

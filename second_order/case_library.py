"""The case library: curated, retrospective editorial case studies of official releases, read in the Tracker.

A case is an AI-assisted editorial illustration written after its source was published. It is not a hypothesis: it
has no freeze time, map, legs, observables, evaluation or verdict, and it names no expectations benchmark, so it
never says whether a release was a surprise. This module uses the standard library only; it never reads or writes
the store, prepared Dossiers, runtime records or market data, so a case cannot enter any research summary.

The content is committed under content/case-library/: collection.json (introduction, labels, the selection rules,
the declared sectors and the cases in publication order) and one <case id>.json per case. Every file is checked
strictly and the whole library is refused on any problem; nothing is repaired, skipped or partly served.

Three case versions are read. case-library-0.1 (the twelve macro cases, kept exactly as written) states a publication
time with an explicit UTC offset. case-library-0.2 adds the case's sectors and the source's publication precision:
"time" (a time with an explicit offset, as in 0.1) or "date" (a calendar date only, for a source that states no time,
or no time zone, so none is invented). Sectors are declared once in the collection; a case lists the sectors it
covers, so one case can appear under several sectors without being copied. Sectors are separate from a case's topic
(its category) and from the Event Inbox's topics. case-library-0.3 (the WTO news entries) adds www.wto.org as a source,
an entry kind (a release, a forecast or meeting proceedings; no market channel is invented, so a proceedings entry may
list no channels), the basis of its date (for a page that states none, the listing date its publisher's own feed
gives, never presented as a stated publication time) and the record of the privately retained copy it was written from
(approval, SHA-256, bytes, retrieval time and declared charset; the copy itself is never served). A 0.3 entry may
belong to no sector. Every earlier case file is read exactly as before.
"""
from datetime import date, datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

LIBRARY_VERSION = "case-library-0.1"  # The twelve macro cases, kept exactly as written.
SECTOR_VERSION = "case-library-0.2"  # 0.2: sectors, and date-only publication for sources that state no time.
TRADE_VERSION = "case-library-0.3"  # 0.3: WTO entries: entry kind, date basis, retained copy; channels optional.
VERSIONS = (LIBRARY_VERSION, SECTOR_VERSION, TRADE_VERSION)
VIEW_VERSION = "case-library-view-0.3"  # 0.3: 0.3 entries carry their kind, date basis and retained-copy record.
ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "content" / "case-library"
COLLECTION = "collection.json"
CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
EXPLICIT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SLUG = re.compile(r"[a-z]+(?:-[a-z]+)*")
SOURCE_HOSTS = ("www.federalreserve.gov", "www.bls.gov", "www.eia.gov", "www.bis.gov")  # Publishers cited.
SOURCE_HOSTS_0_3 = SOURCE_HOSTS + ("www.wto.org",)
ENTRY_KINDS = ("release", "forecast", "proceedings")
APPROVALS = ("wto-trade-sources-01",)  # Acquisitions a 0.3 entry's retained copy may come from.
SHA256 = re.compile(r"[a-f0-9]{64}")
MAX_TEXT = 1600

COLLECTION_FIELDS = {"library_version", "title", "introduction", "labels", "selection", "cases", "market_context"}
COLLECTION_FIELDS_0_2 = COLLECTION_FIELDS | {"sectors", "sector_membership"}
SECTOR_FIELDS = {"slug", "label", "coverage", "selection"}
CASE_FIELDS = {"library_version", "id", "title", "category", "summary", "source", "overview", "key_facts",
               "channels", "competing_explanations", "assumptions", "missing_information",
               "weakening_observations", "critique", "source_notes", "expectations_benchmark", "provenance"}
CASE_FIELDS_0_2 = CASE_FIELDS | {"sectors"}
CASE_FIELDS_0_3 = CASE_FIELDS_0_2 | {"entry_kind"}
SOURCE_FIELDS = {"publisher", "title", "url", "document_id", "published_at", "published_as_stated",
                 "timezone_note", "reference_period", "page_last_updated", "retrieved_on"}
SOURCE_FIELDS_0_2 = SOURCE_FIELDS | {"published_precision"}
SOURCE_FIELDS_0_3 = SOURCE_FIELDS_0_2 | {"date_basis", "retained"}
RETAINED_FIELDS = {"approval_id", "sha256", "bytes", "retrieved_at", "charset"}
PRECISIONS = ("time", "date")
PROVENANCE_FIELDS = {"prepared_by", "prepared_on", "method", "sources_read", "ai_assisted", "retrospective",
                     "prepared_after_publication", "human_review", "research_use"}
# Fixed values: these cases were written by an AI assistant after publication, nobody has reviewed them, and they
# are never research evidence. A later human review would need a new library version, not an edited label.
FIXED_PROVENANCE = {"ai_assisted": True, "retrospective": True, "prepared_after_publication": True,
                    "human_review": "not_reviewed", "research_use": "excluded"}
SECTIONS = {  # Section: (item fields, or None for plain paragraphs; minimum number of items).
    "overview": (None, 2),
    "key_facts": ({"label", "value", "basis"}, 4),
    "channels": ({"title", "source_fact", "interpretation"}, 2),
    "competing_explanations": ({"title", "detail"}, 1),
    "assumptions": (None, 2),
    "missing_information": (None, 2),
    "weakening_observations": (None, 2),
    "critique": ({"title", "detail"}, 3),
    "source_notes": ({"title", "detail", "url"}, 1),
}


class LibraryRefused(ValueError):
    """The library or a requested case cannot be served; ``status`` is the HTTP status that describes why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _invalid(where: str, problem: str) -> LibraryRefused:
    return LibraryRefused(500, f"The case library is invalid ({where}: {problem}); nothing is served")


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


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > MAX_TEXT or \
            any(ord(char) < 32 for char in value):
        raise _invalid(where, "expected one line of non-empty, unpadded text")
    return value


def _day(value: object, where: str) -> date:
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise _invalid(where, "expected a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid(where, "not a calendar date") from None


def _official_url(value: object, where: str, hosts: tuple[str, ...] = SOURCE_HOSTS) -> str:
    parts = urlsplit(_text(value, where))
    # One query form is allowed: EIA's Today in Energy articles are addressed as detail.php?id=<number>.
    article = (parts.hostname, parts.path) == ("www.eia.gov", "/todayinenergy/detail.php") and \
        re.fullmatch(r"id=\d+", parts.query) is not None
    if parts.scheme != "https" or parts.hostname not in hosts or (parts.query and not article) or \
            parts.fragment:
        raise _invalid(where, f"expected an https address at {' or '.join(hosts)}")
    return value


def hosts_for(version: str) -> tuple[str, ...]:
    return SOURCE_HOSTS_0_3 if version == TRADE_VERSION else SOURCE_HOSTS


def precision(source: dict) -> str:
    """How exactly the source states its publication: "time" (0.1 sources always do) or "date"."""
    return source.get("published_precision", "time")


def publication(source: dict) -> tuple[date, datetime | None]:
    """The stated publication date (in the publisher's own offset, for a time) and the instant, if one is stated."""
    if precision(source) == "date":
        return date.fromisoformat(source["published_at"]), None
    instant = datetime.fromisoformat(source["published_at"])
    return instant.date(), instant


def _check_retained(retained: object, where: str) -> None:
    """A 0.3 entry's record of the private copy it was written from: public metadata only, never the copy."""
    if retained is None:
        return
    retained = _fields(retained, RETAINED_FIELDS, where)
    if retained["approval_id"] not in APPROVALS:
        raise _invalid(f"{where}.approval_id", f"expected one of {list(APPROVALS)}")
    if not isinstance(retained["sha256"], str) or not SHA256.fullmatch(retained["sha256"]):
        raise _invalid(f"{where}.sha256", "expected a SHA-256")
    if type(retained["bytes"]) is not int or retained["bytes"] < 1:
        raise _invalid(f"{where}.bytes", "expected a positive integer")
    _text(retained["charset"], f"{where}.charset")
    try:
        moment = datetime.fromisoformat(_text(retained["retrieved_at"], f"{where}.retrieved_at"))
    except ValueError:
        moment = None
    if moment is None or moment.utcoffset() is None:
        raise _invalid(f"{where}.retrieved_at", "expected an ISO time with an offset")


def _check_source(source: object, where: str, version: str) -> tuple[date, datetime | None]:
    fields = {LIBRARY_VERSION: SOURCE_FIELDS, SECTOR_VERSION: SOURCE_FIELDS_0_2, TRADE_VERSION: SOURCE_FIELDS_0_3}
    source = _fields(source, fields[version], where)
    for field in ("publisher", "title", "published_as_stated", "timezone_note", "reference_period"):
        _text(source[field], f"{where}.{field}")
    if source["document_id"] is not None:
        _text(source["document_id"], f"{where}.document_id")
    _official_url(source["url"], f"{where}.url", hosts_for(version))
    if version == TRADE_VERSION:
        _text(source["date_basis"], f"{where}.date_basis")
        _check_retained(source["retained"], f"{where}.retained")
    if precision(source) not in PRECISIONS:
        raise _invalid(f"{where}.published_precision", f"expected one of {list(PRECISIONS)}")
    published = source["published_at"]
    if precision(source) == "date":
        day = _day(published, f"{where}.published_at")  # A date the source states, with no time attached to it.
        instant = None
    else:
        if not isinstance(published, str) or not EXPLICIT_TIME.fullmatch(published):
            raise _invalid(f"{where}.published_at", "expected YYYY-MM-DDTHH:MM:SS with an explicit ±HH:MM offset")
        try:
            instant = datetime.fromisoformat(published)
        except ValueError:
            raise _invalid(f"{where}.published_at", "not a real date and time") from None
        day = instant.date()
    if source["page_last_updated"] is not None and \
            _day(source["page_last_updated"], f"{where}.page_last_updated") < day:
        raise _invalid(f"{where}.page_last_updated", "earlier than publication")
    if _day(source["retrieved_on"], f"{where}.retrieved_on") < day:
        raise _invalid(f"{where}.retrieved_on", "earlier than publication")
    return day, instant


def _check_section(case: dict, name: str, where: str) -> None:
    item_fields, minimum = SECTIONS[name]
    if name == "channels" and case.get("entry_kind") == "proceedings":
        minimum = 0  # Meeting proceedings: no market transmission is invented.
    hosts = hosts_for(case["library_version"])
    items = case[name]
    if not isinstance(items, list) or len(items) < minimum:
        raise _invalid(f"{where}.{name}", f"expected a list of at least {minimum}")
    for number, item in enumerate(items):
        place = f"{where}.{name}[{number}]"
        if item_fields is None:
            _text(item, place)
            continue
        _fields(item, item_fields, place)
        for field in sorted(item_fields - {"url"}):
            _text(item[field], f"{place}.{field}")
        if "url" in item_fields and item["url"] is not None:
            _official_url(item["url"], f"{place}.url", hosts)


def _check_case(case: dict, case_id: str, sectors: set[str]) -> dict:
    where = f"{case_id}.json"
    version = case.get("library_version") if isinstance(case, dict) else None
    if version not in VERSIONS:
        raise _invalid(where, f"library_version must be one of {list(VERSIONS)}")
    _fields(case, {LIBRARY_VERSION: CASE_FIELDS, SECTOR_VERSION: CASE_FIELDS_0_2,
                   TRADE_VERSION: CASE_FIELDS_0_3}[version], where)
    if version == TRADE_VERSION and case["entry_kind"] not in ENTRY_KINDS:
        raise _invalid(f"{where}.entry_kind", f"expected one of {list(ENTRY_KINDS)}")
    if case["id"] != case_id:
        raise _invalid(where, f"its id {case['id']!r} does not match its file name")
    for field in ("title", "category", "summary"):
        _text(case[field], f"{where}.{field}")
    if version in (SECTOR_VERSION, TRADE_VERSION):
        listed = case["sectors"]  # A 0.3 entry may belong to no sector; a 0.2 case belongs to at least one.
        if not isinstance(listed, list) or (not listed and version == SECTOR_VERSION) or \
                len(set(map(str, listed))) != len(listed) or \
                not all(isinstance(slug, str) and slug in sectors for slug in listed):
            raise _invalid(f"{where}.sectors", f"expected distinct sectors the collection declares ({sorted(sectors)})")
    published, _ = _check_source(case["source"], f"{where}.source", version)
    for name in SECTIONS:
        _check_section(case, name, where)
    if case["expectations_benchmark"] is not None:
        raise _invalid(f"{where}.expectations_benchmark", "must be null: no sourced benchmark is used")
    provenance = _fields(case["provenance"], PROVENANCE_FIELDS, f"{where}.provenance")
    for field, value in FIXED_PROVENANCE.items():
        if provenance[field] != value or type(provenance[field]) is not type(value):
            raise _invalid(f"{where}.provenance.{field}", f"must be {json.dumps(value)}")
    for field in ("prepared_by", "method"):
        _text(provenance[field], f"{where}.provenance.{field}")
    if _day(provenance["prepared_on"], f"{where}.provenance.prepared_on") <= published:
        raise _invalid(f"{where}.provenance.prepared_on", "a retrospective case is prepared after publication")
    read = provenance["sources_read"]
    if not isinstance(read, list) or not read:
        raise _invalid(f"{where}.provenance.sources_read", "expected the official addresses that were read")
    for number, url in enumerate(read):
        _official_url(url, f"{where}.provenance.sources_read[{number}]", hosts_for(version))
    cited = {case["source"]["url"]} | {note["url"] for note in case["source_notes"] if note["url"] is not None}
    if not cited <= set(read):
        raise _invalid(f"{where}.provenance.sources_read", "every cited source must be listed as read")
    return case


def load_library(root: Path = LIBRARY_DIR) -> dict:
    """The collection and its cases in display order, every file verified. Nothing is written."""
    if not (root / COLLECTION).is_file():
        raise LibraryRefused(503, "The case library is not installed; nothing is served")
    collection = _strict_load(root / COLLECTION)
    version = collection.get("library_version")
    if version not in VERSIONS:
        raise _invalid(COLLECTION, f"library_version must be one of {list(VERSIONS)}")
    _fields(collection, COLLECTION_FIELDS if version == LIBRARY_VERSION else COLLECTION_FIELDS_0_2, COLLECTION)
    for field in ("title", "introduction", "selection"):
        _text(collection[field], f"{COLLECTION}.{field}")
    sectors = _check_sectors(collection) if version != LIBRARY_VERSION else []
    for field in ("labels", "cases"):
        if not isinstance(collection[field], list) or not collection[field]:
            raise _invalid(f"{COLLECTION}.{field}", "expected a non-empty list")
    for number, label in enumerate(collection["labels"]):
        _text(label, f"{COLLECTION}.labels[{number}]")
    order = collection["cases"]
    if len(set(order)) != len(order) or not all(isinstance(item, str) and CASE_ID.fullmatch(item) for item in order):
        raise _invalid(f"{COLLECTION}.cases", "expected distinct lower-case case IDs")
    files = {path.stem for path in root.glob("*.json") if path.name != COLLECTION}
    if files != set(order):
        raise _invalid(COLLECTION, f"its listed cases {sorted(order)} differ from the case files {sorted(files)}")
    slugs = {sector["slug"] for sector in sectors}
    raw = [_strict_load(root / f"{case_id}.json") for case_id in order]
    if any(case.get("library_version") in VERSIONS and VERSIONS.index(case["library_version"]) > VERSIONS.index(version)
           for case in raw):
        raise _invalid(COLLECTION, f"a {version} collection lists no case of a later version")
    cases = [_check_case(case, case_id, slugs) for case, case_id in zip(raw, order)]
    keys = [order_key(case) for case in cases]
    if keys != sorted(keys):  # One deterministic order everywhere (order_key).
        raise _invalid(f"{COLLECTION}.cases", "cases must be listed in publication order")
    context = collection["market_context"]  # The cases meant to show market context (see market_context).
    if not isinstance(context, list) or len(set(context)) != len(context) or not set(context) <= set(order):
        raise _invalid(f"{COLLECTION}.market_context", "expected distinct IDs of listed cases")
    if any(precision(case["source"]) != "time" for case in cases if case["id"] in context):
        raise _invalid(f"{COLLECTION}.market_context", "market context needs a publication time with its offset")
    return {"collection": collection, "cases": cases, "sectors": sectors}


def order_key(case: dict) -> tuple:
    """By stated publication date; on one date, cases with a stated time first, by instant; then by case ID."""
    day, instant = publication(case["source"])
    return day, instant is None, instant.timestamp() if instant else 0.0, case["id"]


def _check_sectors(collection: dict) -> list[dict]:
    _text(collection["sector_membership"], f"{COLLECTION}.sector_membership")
    sectors = collection["sectors"]
    if not isinstance(sectors, list) or not sectors:
        raise _invalid(f"{COLLECTION}.sectors", "expected a non-empty list")
    for number, sector in enumerate(sectors):
        place = f"{COLLECTION}.sectors[{number}]"
        _fields(sector, SECTOR_FIELDS, place)
        for field in sorted(SECTOR_FIELDS):
            _text(sector[field], f"{place}.{field}")
        if not SLUG.fullmatch(sector["slug"]):
            raise _invalid(f"{place}.slug", "expected a lower-case slug")
    if len({sector["slug"] for sector in sectors}) != len(sectors) or \
            len({sector["label"] for sector in sectors}) != len(sectors):
        raise _invalid(f"{COLLECTION}.sectors", "expected distinct slugs and labels")
    return sectors


def _publication_view(case: dict) -> dict:
    day, _ = publication(case["source"])
    return {"precision": precision(case["source"]), "date": day.isoformat(), "at": case["source"]["published_at"]}


def library_view(root: Path = LIBRARY_DIR) -> dict:
    """What the library page lists: the collection's introduction, its sectors and one row per case."""
    library = load_library(root)
    collection = library["collection"]
    return {"view_version": VIEW_VERSION, "title": collection["title"], "introduction": collection["introduction"],
            "labels": collection["labels"], "selection": collection["selection"],
            "sectors": library["sectors"], "sector_membership": collection.get("sector_membership"),
            "cases": [{"id": case["id"], "title": case["title"], "category": case["category"],
                       "summary": case["summary"], "published_at": case["source"]["published_at"],
                       "published_as_stated": case["source"]["published_as_stated"],
                       "publication": _publication_view(case), "publisher": case["source"]["publisher"],
                       "sectors": case.get("sectors", []),
                       "market_context": case["id"] in collection["market_context"]} for case in library["cases"]]}


def case_view(case_id: str, root: Path = LIBRARY_DIR) -> dict:
    """One case, with its place in the collection and its neighbours for navigation."""
    library = load_library(root)
    cases = library["cases"]
    ids = [case["id"] for case in cases]
    if not CASE_ID.fullmatch(case_id or "") or case_id not in ids:
        raise LibraryRefused(404, "Unknown case")
    position = ids.index(case_id)

    def neighbour(index: int) -> dict | None:
        return {"id": cases[index]["id"], "title": cases[index]["title"]} if 0 <= index < len(cases) else None

    labels = {sector["slug"]: sector["label"] for sector in library["sectors"]}
    case = cases[position]
    return {"view_version": VIEW_VERSION, "case": case, "position": position + 1, "count": len(cases),
            "previous": neighbour(position - 1), "next": neighbour(position + 1),
            "publication": _publication_view(case),
            "sectors": [{"slug": slug, "label": labels[slug]} for slug in case.get("sectors", [])],
            "market_context": case_id in library["collection"]["market_context"]}

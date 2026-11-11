"""Retained BIS snapshot (bis-snapshot-index-0.1): BIS's News & Updates page, retained once under approval
bis-semis-sources-01, read as a local snapshot of press-release records. It is not a live feed: nothing here requests,
refreshes or downloads anything, and nothing is classified, summarized or analyzed.

The page is located through its acquisition record and used only when the retained bytes match it (complete-body
SHA-256 and size, address, HTTP 200, text/html; charset=utf-8, no content encoding). Its embedded Next.js data
(`__NEXT_DATA__`, JSON) is parsed as data, within fixed bounds, without executing anything or loading any resource.
Each press-release record becomes plain fields: the publisher's title, topics, country tags, summary and text (HTML
reduced to plain-text paragraphs, scripts and markup dropped), the listing's metadata (its publication timestamp and,
separately, the CMS creation and update times, which are never used as publication times) and application-derived
keyword filters (the Related Cases word lists; never a model classification). A record that cannot be identified (no
usable press-release address or title, or one the listing marks unpublished) is reported as unusable with its reasons.
Records are never merged by headline: the same title on different addresses stays different documents, and an
address listed twice is a duplicate copy only when both copies are identical.

Where the same acquisition retained a record's own release page, the listing's text is compared with it, paragraph
by paragraph, and the page's dateline is kept as the release's stated date. That check covers only those records.

The derived index is written once per retained package and extractor version (data/bis-snapshot/index/, git-ignored)
by the explicit "open" action, and reused on every later read, page load and restart; an index that does not verify is
refused and left as it is. Building an index never touches the Event Inbox (see inbox_imports).
"""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit

from . import related_rules

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "data" / "sector-sources" / "bis"
INDEX_DIR = ROOT / "data" / "bis-snapshot" / "index"
SOURCES_REL = "data/sector-sources/bis"
APPROVAL_ID = "bis-semis-sources-01"
PAGE_URL = "https://www.bis.gov/news-updates"
PAGE_FOLDER = "news-updates"
HOST = "www.bis.gov"
EXTRACTOR_VERSION = "bis-snapshot-extract-0.1"
INDEX_VERSION = "bis-snapshot-index-0.1"
MAX_PAGE_BYTES = 4 * 1024 * 1024  # The acquisition's own cap.
MAX_DATA_CHARS = 4 * 1024 * 1024
MAX_RECORDS = 1000
MAX_TITLE = 300
MAX_SUMMARY = 1200
MAX_NAME = 120
MAX_BODY_HTML = 200_000
MAX_TEXT = 60_000
MAX_PARAGRAPHS = 600
MAX_LINK = 500
PATH = re.compile(r"/press-release/[a-z0-9][a-z0-9.-]{0,280}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NODE_ID = re.compile(r"\d{1,12}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
DATELINE = re.compile(r"FOR IMMEDIATE RELEASE \| ([A-Z][a-z]+ \d{1,2}, \d{4})(?: \||$)")
FILTERS = {  # Application-derived keyword filters: the Related Cases word lists (related_rules), never a model.
    "semiconductors": {"label": "Semiconductors and advanced computing", "dimension": "sector",
                       "slug": "semiconductors"},
    "export_controls": {"label": "Export-control terms", "dimension": "instrument", "slug": "export-controls"},
}
COMPLETENESS = {
    "checked": "The listing's text matches the separately retained release page, paragraph by paragraph (checked).",
    "checked_differs": "The listing's text differs from the separately retained release page (checked).",
    "listing_text": ("Text as embedded in BIS's listing data. Not checked against the release page; where two releases "
                     "were checked, the listing held their full text, without the release's dateline header."),
    "title_only": "No text in the listing data: title and metadata only.",
    "unreadable": "The listing's text could not be read as plain text; title and metadata only.",
}
BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "table",
              "tbody", "thead", "blockquote", "hr", "figure", "figcaption", "section", "article", "pre", "dd", "dt",
              "dl", "header", "footer", "nav", "main", "aside", "form", "address"}
HIDDEN_TAGS = {"script", "style", "template", "noscript", "svg", "iframe", "object", "embed", "head", "title",
               "button", "select", "textarea"}


class SnapshotRefused(ValueError):
    """The snapshot, its index or a request about it cannot be served; ``status`` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Unreadable(ValueError):
    """Markup that cannot be read as plain text."""


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(text: str, what: str):
    def pairs(items):
        if len({key for key, _ in items}) != len(items):
            raise ValueError("a repeated key")
        return dict(items)

    def constant(name):
        raise ValueError(f"the non-standard constant {name}")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise SnapshotRefused(422, f"{what} is not strict JSON ({str(exc)[:80]})") from None


# ---------------------------------------------------------------- the retained package

def _outcomes(sources: Path) -> dict[int, dict]:
    run = sources / "acquisitions" / APPROVAL_ID
    if not run.is_dir():
        raise SnapshotRefused(503, f"The retained BIS snapshot is not on this machine: there is no acquisition record "
                                   f"for approval {APPROVAL_ID}")
    found = {}
    for path in sorted(run.glob("outcome-*.json")):
        try:
            record = _strict_json(path.read_text(encoding="utf-8"), f"Acquisition record {path.name}")
        except (OSError, UnicodeDecodeError):
            raise SnapshotRefused(500, f"Acquisition record {path.name} cannot be read") from None
        if not isinstance(record, dict) or type(record.get("n")) is not int:
            raise SnapshotRefused(500, f"Acquisition record {path.name} is malformed")
        found[record["n"]] = record
    return found


def _verified_copy(record: dict, sources: Path, folder: str) -> bytes:
    """The retained bytes an acquisition record names, only if they match it in full."""
    headers = record.get("named_headers") if isinstance(record.get("named_headers"), dict) else {}
    checks = (record.get("outcome") == "complete", record.get("http_status") == 200,
              record.get("approval_id") == APPROVAL_ID, record.get("hash_kind") == "complete_response",
              record.get("retained") == f"{SOURCES_REL}/{folder}/source.html",
              headers.get("content-type") == "text/html; charset=utf-8", headers.get("content-encoding") is None,
              isinstance(record.get("sha256"), str) and bool(SHA256.fullmatch(record["sha256"])),
              type(record.get("bytes")) is int and 0 < record["bytes"] <= MAX_PAGE_BYTES,
              _utc_or_none(record.get("body_completed_at")) is not None)
    if not all(checks):
        raise SnapshotRefused(409, f"The acquisition record for {record.get('url')} is not a complete, accepted "
                                   "text/html retrieval; the retained copy is not used")
    path = sources / folder / "source.html"
    if not path.is_file():
        raise SnapshotRefused(503, f"The retained copy of {record['url']} is not on this machine")
    if path.stat().st_size != record["bytes"]:
        raise SnapshotRefused(409, f"The retained copy of {record['url']} does not match its acquisition record (its "
                                   "size differs); it is not read")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or sha256(raw) != record["sha256"]:
        raise SnapshotRefused(409, f"The retained copy of {record['url']} does not match its acquisition record (its "
                                   "size or SHA-256 differs); it is not read")
    return raw


def locate(sources: Path = SOURCES_DIR) -> tuple[dict, bytes, dict[str, dict]]:
    """(the package record, its verified bytes, the verified release pages of the same acquisition by address)."""
    outcomes = _outcomes(sources)
    pages = [record for record in outcomes.values() if record.get("url") == PAGE_URL]
    if len(pages) != 1:
        raise SnapshotRefused(409, f"Expected exactly one acquisition record for {PAGE_URL}, found {len(pages)}")
    record = pages[0]
    raw = _verified_copy(record, sources, PAGE_FOLDER)
    package = {"url": PAGE_URL, "approval_id": APPROVAL_ID, "attempt": record["n"], "sha256": record["sha256"],
               "bytes": record["bytes"], "retrieved_at": record["body_completed_at"],
               "content_type": record["named_headers"]["content-type"]}
    releases = {}
    for other in outcomes.values():
        url = other.get("url")
        folder = (other.get("retained") or "").removeprefix(f"{SOURCES_REL}/").removesuffix("/source.html")
        if not isinstance(url, str) or not url.startswith(f"https://{HOST}/press-release/") or "/" in folder:
            continue
        try:
            releases[url] = {"url": url, "attempt": other["n"], "sha256": other["sha256"],
                             "raw": _verified_copy(other, sources, folder)}
        except SnapshotRefused as exc:  # A release page that does not verify is never compared.
            releases[url] = {"url": url, "attempt": other.get("n"), "sha256": other.get("sha256"), "raw": None,
                             "problem": str(exc)}
    return package, raw, releases


def _utc_or_none(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.utcoffset() is not None else None


# ---------------------------------------------------------------- text

class _Paragraphs(HTMLParser):
    """Plain-text paragraphs of an HTML fragment: block elements break, hidden elements and all markup are dropped,
    entities are decoded. Nothing is executed or loaded."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.parts, self.hidden, self.chars, self.cut = [], [], 0, 0, False

    def flush(self):
        text = " ".join("".join(char if char.isprintable() else " " for char in "".join(self.parts)).split())
        self.parts = []
        if not text:
            return
        if len(self.out) >= MAX_PARAGRAPHS or self.chars + len(text) > MAX_TEXT:
            self.cut = True
            return
        self.out.append(text)
        self.chars += len(text)

    def handle_starttag(self, tag, attrs):
        if tag in HIDDEN_TAGS:
            self.hidden += 1
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag in HIDDEN_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def paragraphs(fragment: str) -> tuple[list[str], bool]:
    """(plain-text paragraphs, whether the bounds cut them short). Unreadable if the markup cannot be read."""
    parser = _Paragraphs()
    try:
        parser.feed(fragment)
        parser.close()
    except AssertionError:  # html.parser's refusal of some malformed declarations (see event_inbox.plain_text).
        raise Unreadable("markup that cannot be read as plain text") from None
    parser.flush()
    return parser.out, parser.cut


def plain(value, limit: int, markup: bool = False) -> tuple[str | None, bool]:
    """One line of plain text (markup removed when ``markup``), at most ``limit`` characters, and whether it was cut."""
    if not isinstance(value, str) or not value.strip():
        return None, False
    if markup:
        try:
            parts, _ = paragraphs(value[:MAX_BODY_HTML])
        except Unreadable:
            return None, False
        value = " ".join(parts)
    value = " ".join("".join(char if char.isprintable() else " " for char in value).split())
    if not value:
        return None, False
    return (value[:limit - 1].rstrip() + "…", True) if len(value) > limit else (value, False)


def official_address(path) -> str | None:
    """The record's own address on BIS's site, from its listed press-release path; None if the path is not one."""
    if not isinstance(path, str) or not PATH.fullmatch(path) or ".." in path:
        return None
    return f"https://{HOST}{path}"


def outside_link(value) -> tuple[dict | None, str | None]:
    """The page another publisher hosts for this record (the listing's external link), if it is a plain https address."""
    if value is None:
        return None, None
    url = value.get("url") if isinstance(value, dict) else None
    if not isinstance(url, str) or len(url) > MAX_LINK or any(char.isspace() or not char.isprintable() for char in url):
        return None, "The listing's external link is malformed and is not shown"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None, "The listing's external link is malformed and is not shown"
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or port not in (None, 443):
        return None, "The listing's external link is not a plain https address and is not shown"
    title, _ = plain(value.get("title"), MAX_NAME)
    return {"url": url, "host": parts.hostname, "title": title}, None


# ---------------------------------------------------------------- dates

def listing_time(value, field: str) -> dict:
    """A listing timestamp exactly as given, checked: listed (time, epoch seconds and zone agree), missing or
    ambiguous. Nothing is converted or filled in."""
    if value is None:
        return {"state": "missing", "time": None, "date": None, "field": field,
                "problem": f"The listing data gives no {field} value for this record."}
    keys = {"time", "timestamp", "timezone", "offset"}
    if not isinstance(value, dict) or set(value) != keys:
        return {"state": "ambiguous", "time": None, "date": None, "field": field,
                "problem": f"The listing data's {field} value does not have its expected parts, so it is not used."}
    moment = _utc_or_none(value["time"])
    problems = []
    if moment is None:
        problems.append("its time is not a full date, time and UTC offset")
    else:
        if type(value["timestamp"]) is not int or int(moment.timestamp()) != value["timestamp"]:
            problems.append("its epoch seconds and its time disagree")
        offset = moment.strftime("%z")
        if value["offset"] != f"{offset[:3]}:{offset[3:]}":
            problems.append("its stated offset and its time disagree")
        if value["timezone"] != "UTC" or value["offset"] != "+00:00":
            problems.append(f"its zone is {str(value['timezone'])[:20]}, not UTC")
    if problems:
        return {"state": "ambiguous", "time": None, "date": None, "field": field,
                "problem": f"The listing data's {field} value is inconsistent ({'; '.join(problems)}), so it is not "
                           "used."}
    return {"state": "listed", "time": value["time"], "date": value["time"][:10], "field": field, "problem": None}


# ---------------------------------------------------------------- records

def _names(items, limit: int = 20) -> list[str]:
    names = []
    for item in items if isinstance(items, list) else []:
        name, _ = plain(item.get("name") if isinstance(item, dict) else None, MAX_NAME)
        if name and name not in names:
            names.append(name)
    return names[:limit]


def record_sha256(record: dict) -> str:
    """The identity of a record's source version: what the publisher and the listing state about the document, not
    the CMS's creation or update times, its position in the listing or this application's filters."""
    return sha256(canonical({"identity": record["identity"], "uuid": record["document"]["uuid"],
                             "publisher": record["publisher"], "text": record["text"]["paragraphs"],
                             "published": record["listing"]["published"]["time"]}))


def _record(teaser, position: int) -> tuple[dict | None, dict | None]:
    """(a usable record, None) or (None, an unusable entry with its reasons)."""
    if not isinstance(teaser, dict):
        return None, {"position": position, "key": None, "path": None, "title": None,
                      "reasons": ["The listing entry is not an object"]}
    path = teaser.get("path")
    identity = official_address(path)
    title, title_cut = plain(teaser.get("title"), MAX_TITLE)
    reasons = []
    if teaser.get("__typename") != "NodePressRelease":
        reasons.append("It is not a press-release record")
    if identity is None:
        reasons.append("It has no usable press-release address on www.bis.gov")
    if title is None:
        reasons.append("It has no title")
    if teaser.get("status") is not True:
        reasons.append("The listing data does not mark it as published")
    key = sha256(identity.encode("utf-8"))[:20] if identity else None
    if reasons:
        return None, {"position": position, "key": key, "path": path if isinstance(path, str) else None,
                      "title": title, "reasons": reasons}
    body = teaser.get("body")
    text, cut, state, problem = [], False, "title_only", None
    if body is not None and not isinstance(body, dict):
        state, problem = "unreadable", "The listing's text field is malformed"
    elif isinstance(body, dict) and isinstance(body.get("processed"), str) and body["processed"].strip():
        if len(body["processed"]) > MAX_BODY_HTML:
            state, problem = "unreadable", f"The listing's text is longer than {MAX_BODY_HTML} characters and is not read"
        else:
            try:
                text, cut = paragraphs(body["processed"])
                state = "listing_text" if text else "title_only"
            except Unreadable as exc:
                state, problem = "unreadable", f"The listing's text has {exc}"
    summary, summary_cut = plain((body or {}).get("summary") if isinstance(body, dict) else None, MAX_SUMMARY,
                                 markup=True)
    external, external_problem = outside_link(teaser.get("externalLink"))
    uuid = teaser.get("uuid") if isinstance(teaser.get("uuid"), str) and UUID.fullmatch(teaser["uuid"]) else None
    node = teaser.get("id") if isinstance(teaser.get("id"), str) and NODE_ID.fullmatch(teaser["id"]) else None
    record = {
        "key": key, "id": f"bis-snapshot:{key}", "identity": identity, "position": position,
        "document": {"path": path, "uuid": uuid, "node_id": node},
        "publisher": {"title": title, "title_truncated": title_cut, "topics": _names(teaser.get("newsUpdatesTopic")),
                      "countries": _names(teaser.get("countryTag"), 40), "summary": summary,
                      "summary_truncated": summary_cut, "external_link": external},
        "text": {"paragraphs": text, "chars": sum(map(len, text)), "truncated": cut, "state": state,
                 "problem": problem},
        "listing": {"published": listing_time(teaser.get("publishedOn"), "publication time"),
                    "created": listing_time(teaser.get("created"), "CMS creation time"),
                    "changed": listing_time(teaser.get("changed"), "CMS update time"),
                    "sticky": teaser.get("sticky") is True},
        "notes": [note for note in (external_problem,) if note],
    }
    joined = " ".join(text)
    tags = related_rules.tag({"title": title, "text": joined})
    record["filters"] = {}
    for name, spec in FILTERS.items():
        found = tags[spec["dimension"]].get(spec["slug"], [])
        record["filters"][name] = {"matched": bool(found), "in": sorted({item["field"] for item in found}),
                                   "terms": sorted({item["term"].casefold() for item in found})[:6]}
    record["record_sha256"] = record_sha256(record)
    return record, None


def _relation(first: dict, second: dict) -> str:
    if not first["text"]["paragraphs"] or not second["text"]["paragraphs"]:
        return "one has no text"
    return "identical text" if first["text"]["paragraphs"] == second["text"]["paragraphs"] else "different text"


def _release_check(record: dict, page: dict) -> dict:
    """The listing's text against the record's separately retained release page (same acquisition)."""
    base = {"page_url": page["url"], "page_sha256": page["sha256"], "attempt": page["attempt"], "dateline": None}
    if page.get("raw") is None:
        return {**base, "result": "not_compared", "note": page.get("problem")}
    try:
        lines, _ = paragraphs(page["raw"].decode("utf-8"))
    except (Unreadable, UnicodeDecodeError):
        return {**base, "result": "not_compared", "note": "The release page could not be read as text"}
    start = next((index for index, line in enumerate(lines) if line.startswith("FOR IMMEDIATE RELEASE")), None)
    end = lines.index("###", start) if start is not None and "###" in lines[start:] else None
    if start is None or end is None:
        return {**base, "result": "not_compared", "note": "The release page's text could not be located"}
    dateline = DATELINE.search(lines[start])
    body = [line for line in lines[start + 1:end + 1]
            if line not in (record["publisher"]["title"], "Download as PDF")]
    same = body == record["text"]["paragraphs"]
    return {**base, "dateline": dateline.group(1) if dateline else None, "result": "identical" if same else "differs",
            "note": ("Paragraph for paragraph identical to the release page's text; the listing omits the page's "
                     "dateline header (FOR IMMEDIATE RELEASE | date | media contact).") if same else
                    (f"The listing has {len(record['text']['paragraphs'])} paragraphs and the release page "
                     f"{len(body)}; they are not identical.")}


def extract(raw: bytes, releases: dict[str, dict] | None = None) -> dict:
    """Every record of the snapshot's listing data: usable records (unique addresses) and unusable entries."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SnapshotRefused(422, "The retained page is not UTF-8 text") from None
    blocks = NEXT_DATA.findall(text)
    if len(blocks) != 1:
        raise SnapshotRefused(422, f"The retained page holds {len(blocks)} embedded data blocks, not exactly one")
    if len(blocks[0]) > MAX_DATA_CHARS:
        raise SnapshotRefused(422, "The embedded data is larger than the extractor reads")
    data = _strict_json(blocks[0], "The embedded data")
    props = data.get("props") if isinstance(data, dict) else None
    page = props.get("pageProps") if isinstance(props, dict) else None
    teasers = page.get("pressReleaseTeasers") if isinstance(page, dict) else None
    if not isinstance(teasers, list):
        raise SnapshotRefused(422, "The embedded data holds no list of press-release records")
    if len(teasers) > MAX_RECORDS:
        raise SnapshotRefused(422, f"The embedded data lists {len(teasers)} records; at most {MAX_RECORDS} are read")
    usable, unusable = [], []
    for position, teaser in enumerate(teasers, start=1):
        record, problem = _record(teaser, position)
        (usable.append(record) if record else unusable.append(problem))
    # One address listed twice: an identical copy keeps the first listing; differing copies are both withheld.
    by_key: dict[str, list[dict]] = {}
    for record in usable:
        by_key.setdefault(record["key"], []).append(record)
    kept = []
    for record in usable:
        group = by_key[record["key"]]
        if len(group) == 1:
            kept.append(record)
        elif all(other["record_sha256"] == group[0]["record_sha256"] for other in group):
            if record is group[0]:
                kept.append({**record, "notes": record["notes"] + [
                    f"Listed {len(group)} times with identical content; the first listing is kept."]})
            else:
                unusable.append({"position": record["position"], "key": record["key"],
                                 "path": record["document"]["path"], "title": record["publisher"]["title"],
                                 "reasons": [f"A duplicate copy of the record at position {group[0]['position']} "
                                             "(same address, identical content)"]})
        else:
            unusable.append({"position": record["position"], "key": record["key"],
                             "path": record["document"]["path"], "title": record["publisher"]["title"],
                             "reasons": [f"The same address is listed {len(group)} times with different content; "
                                         "none is offered, since the snapshot does not say which is current"]})
    # The same title on different addresses: separate documents, never merged; each says how their texts relate.
    titles: dict[str, list[dict]] = {}
    for record in kept:
        titles.setdefault(record["publisher"]["title"].casefold(), []).append(record)
    for record in kept:
        record["same_title"] = [{"key": other["key"], "path": other["document"]["path"],
                                 "date": other["listing"]["published"]["date"], "relation": _relation(record, other)}
                                for other in titles[record["publisher"]["title"].casefold()] if other is not record]
        page = (releases or {}).get(record["identity"])
        record["check"] = _release_check(record, page) if page else None
        result = (record["check"] or {}).get("result")
        record["completeness"] = ("checked" if result == "identical" else "checked_differs" if result == "differs"
                                  else record["text"]["state"])
    unusable.sort(key=lambda entry: entry["position"])
    return {"listed": len(teasers), "records": kept, "unusable": unusable}


def counts(extracted: dict) -> dict:
    records = extracted["records"]

    def number(test) -> int:
        return sum(1 for record in records if test(record))
    dates = [record["listing"]["published"]["date"] for record in records if record["listing"]["published"]["date"]]
    hosts: dict[str, int] = {}
    for record in records:
        external = record["publisher"]["external_link"]
        if external:
            hosts[external["host"]] = hosts.get(external["host"], 0) + 1
    topics: dict[str, int] = {}
    for record in records:
        for topic in record["publisher"]["topics"] or ["No topic"]:
            topics[topic] = topics.get(topic, 0) + 1
    return {"listed": extracted["listed"], "usable": len(records), "unusable": len(extracted["unusable"]),
            "completeness": {state: number(lambda r, s=state: r["completeness"] == s) for state in COMPLETENESS},
            "dates": {state: number(lambda r, s=state: r["listing"]["published"]["state"] == s)
                      for state in ("listed", "missing", "ambiguous")},
            "date_range": [min(dates), max(dates)] if dates else None,
            "external_links": number(lambda r: r["publisher"]["external_link"] is not None),
            "external_hosts": dict(sorted(hosts.items(), key=lambda pair: (-pair[1], pair[0]))),
            "topics": dict(sorted(topics.items(), key=lambda pair: (-pair[1], pair[0]))),
            "filters": {name: number(lambda r, n=name: r["filters"][n]["matched"]) for name in FILTERS},
            "same_title_records": number(lambda r: bool(r["same_title"])),
            "duplicate_copies": sum(1 for entry in extracted["unusable"] if "duplicate copy" in " ".join(entry["reasons"]))}


# ---------------------------------------------------------------- the derived index

def index_name(package: dict) -> str:
    return f"{package['sha256'][:16]}-{EXTRACTOR_VERSION}.json"


def _index_content(index: dict) -> bytes:
    return canonical({key: index[key] for key in ("index_version", "extractor_version", "package", "release_pages",
                                                  "records", "unusable", "listed")})


def build(sources: Path = SOURCES_DIR) -> dict:
    """The index for the verified package, in memory. Reads only."""
    package, raw, releases = locate(sources)
    extracted = extract(raw, releases)
    index = {"index_version": INDEX_VERSION, "extractor_version": EXTRACTOR_VERSION, "package": package,
             "release_pages": sorted(({"url": page["url"], "attempt": page["attempt"], "sha256": page["sha256"],
                                       "verified": page["raw"] is not None} for page in releases.values()),
                                      key=lambda page: page["url"]),
             "listed": extracted["listed"], "records": extracted["records"], "unusable": extracted["unusable"]}
    index["content_sha256"] = sha256(_index_content(index))
    return index


def _write_once(path: Path, data: bytes) -> bool:
    """Create ``path`` with ``data`` unless it exists: complete or absent, then read-only. True if written now."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
    finally:
        os.remove(temporary)
    os.chmod(path, stat.S_IREAD)
    return True


def _read_index(path: Path, package: dict) -> dict:
    try:
        index = _strict_json(path.read_text(encoding="utf-8"), f"The local index {path.name}")
    except (OSError, UnicodeDecodeError, SnapshotRefused):
        index = None
    fields = {"index_version", "extractor_version", "package", "release_pages", "listed", "records", "unusable",
              "content_sha256", "built_at"}
    if not isinstance(index, dict) or set(index) != fields or index["index_version"] != INDEX_VERSION or \
            index["extractor_version"] != EXTRACTOR_VERSION or index["package"] != package or \
            index["content_sha256"] != sha256(_index_content(index)):
        raise SnapshotRefused(500, f"The local index {path.name} does not verify against the retained snapshot; it was "
                                   "left as it is. Move it aside to build it again.")
    return index


def read_index(sources: Path = SOURCES_DIR, index_dir: Path = INDEX_DIR) -> tuple[dict, dict | None]:
    """(the verified package, its verified index or None if it has not been built). Reads only."""
    package, _, _ = locate(sources)
    path = index_dir / index_name(package)
    return package, (_read_index(path, package) if path.exists() else None)


def open_index(sources: Path = SOURCES_DIR, index_dir: Path = INDEX_DIR, clock=None) -> tuple[dict, str]:
    """The explicit open: the verified package's index, built once and reused after. ("built" | "reused")."""
    package, _, _ = locate(sources)
    path = index_dir / index_name(package)
    if path.exists():
        return _read_index(path, package), "reused"
    index = build(sources)
    index["built_at"] = (clock() if clock else datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
        timespec="seconds")
    if not _write_once(path, (json.dumps(index, ensure_ascii=False, indent=1) + "\n").encode("utf-8")):
        return _read_index(path, package), "reused"  # Built concurrently: the one written first is used.
    return index, "built"

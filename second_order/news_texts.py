"""Publication texts for the news (news-texts-0.1): the full text of an official release, retrieved on the operator's
explicit request and kept, so a shared brief and a reader's deeper analysis can rest on the publication rather than on
its feed's headline and excerpt.

A feed entry is discovery metadata. For a publisher in SOURCES (official releases whose terms allow reuse, and whose
page layout page_text reads), the operator may ask for the text of the page an entry links to. Retrieval is bounded like
the user import (publication_import.PublicationFetcher): an https address on the publisher's host whose path is a
publication page (or, for the European Commission, whose pages are drawn by a script, the one documents-service address
for that page), GET only, no redirect, no retry, timeouts, 2 MB, and pacing between requests to one host. Every
request leaves a write-once numbered record (address, times, status line and kept headers, body state, size and
SHA-256, the outcome) under data/news-texts/retrievals/, and an accepted answer's bytes are kept once under
raw/<sha256>.html (or .json).

What a page says becomes a text snapshot, write-once, under texts/<source>/<entry>/<text SHA-256>.json (metadata) and
.txt (the text): the entry and its version, the address, retrieval time and record, the page's SHA-256, the extractor
and its version, the title and date the page prints, the text, its length and SHA-256, the attribution, and whether it
is the full text or partial (a table left out, a length cap). A later snapshot of the same entry never replaces an
earlier one; readers use the newest. A page that cannot be read leaves an attempt record beside the entry, so the story
says the text could not be read and why. Nothing is retrieved again when a snapshot exists or a kept copy of the same
address can be read again (a new extractor version reads the kept bytes). Reading (``text_state``) reads files only: no
publisher is contacted. Nothing here bypasses a paywall or an access restriction: only the listed publishers' public
pages are requested, and only where their terms allow reuse.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Callable
from urllib.parse import urlsplit

import httpx

from . import event_inbox, inbox_raw, market_store, page_text, publication_import
from .newsroom_store import stamp

TEXTS_VERSION = "news-texts-0.1"
ROOT = Path(__file__).resolve().parent.parent
TEXTS_DIR = ROOT / "data" / "news-texts"  # Runtime records; data/ is ignored by git.
USER_AGENT = ("SecondOrder/0.1 (local research tool; one official publication fetched on the operator's explicit "
              "request)")
MAX_PER_RUN = 30
STATES = ("full_text", "partial_text", "failed", "not_retrieved", "not_supported")
NUMBER = re.compile(r"(\d{6})\.json")


@dataclass(frozen=True)
class TextSource:
    source: str  # The registry key (news_registry) whose entries' pages may be read.
    host: str
    path: re.Pattern
    read: Callable[[bytes, str], dict]
    basis: str  # Why its pages may be retrieved and their text used (its terms, as read).
    query: re.Pattern | None = None  # The only query an address may carry, when its pages are addressed by one.
    pause_seconds: float = 1.0  # Between two requests to this host in one run (the ECB asks for 5 in robots.txt).
    address: Callable[[str], str] | None = None  # What is requested for a page's link, when not the link itself.
    request: re.Pattern | None = None  # The only full address that may be requested through ``address``.
    media: str = "text/html"  # What the publisher answers with.


SUFFIX = {"text/html": ".html", "application/json": ".json"}  # How a kept answer is named under raw/.


def _layout(layout: page_text.Layout) -> Callable[[bytes, str], dict]:
    return lambda raw, content_type: page_text.read_page(raw, content_type, layout)


EC_LINK = re.compile(r"/commission/presscorner/detail/[a-z]{2}/([a-z]{2,8})_(\d{2})_(\d{1,6})")


def _ec_address(link: str) -> str:
    """The documents service's address for a press-corner page (its page is drawn by a script): the English
    version of the document the page shows."""
    kind, year, number = EC_LINK.fullmatch(urlsplit(link).path).groups()
    return (f"https://ec.europa.eu/commission/presscorner/api/documents?reference={kind.upper()}/{year}/{number}"
            "&language=en")


SOURCES = {source.source: source for source in (
    TextSource("whitehouse-news", "www.whitehouse.gov",
               re.compile(r"/(?:fact-sheets|presidential-actions|briefings-statements|articles|releases|remarks)/"
                          r"\d{4}/\d{2}/[a-z0-9-]+/"), _layout(page_text.WHITE_HOUSE),
               "U.S. government work, not copyright protected (https://www.whitehouse.gov/copyright/); robots.txt "
               "disallows only site search. Read 2026-10-25."),
    TextSource("ustr-press", "ustr.gov",
               re.compile(r"/about(?:-us)?/policy-offices/press-office/[a-z0-9/-]+"), _layout(page_text.USTR),
               "U.S. government work in the public domain (17 U.S.C. 105); robots.txt does not disallow the press "
               "office. Read 2026-10-25."),
    TextSource("eia-todayinenergy", "www.eia.gov", re.compile(r"/todayinenergy/detail\.php"),
               _layout(page_text.EIA),
               "Public domain, credit \"Source: U.S. Energy Information Administration\" "
               "(https://www.eia.gov/about/copyrights_reuse.php); robots.txt allows /todayinenergy/. Read 2026-10-25.",
               query=re.compile(r"id=\d{1,7}")),
    TextSource("ecb-press", "www.ecb.europa.eu",
               re.compile(r"//?press/[a-z0-9_/]+/html/[A-Za-z0-9._~-]+\.en\.html"), _layout(page_text.ECB),
               "Free use with the ECB cited as the source and modifications stated "
               "(https://www.ecb.europa.eu/services/disclaimer/html/index.en.html); robots.txt allows /press/ with a "
               "5-second crawl delay. Read 2026-10-25.", pause_seconds=5.0),
    TextSource("wto-news", "www.wto.org", re.compile(r"/english/news_e/news\d{2}_e/[A-Za-z0-9_]+\.htm"),
               _layout(page_text.WTO),
               "Dissemination encouraged with the attribution \"WTO news\" "
               "(https://www.wto.org/english/info_e/copyrights_permissions_e.htm); robots.txt allows /english/news_e/. "
               "Read 2026-10-25."),
    TextSource("fed-monetary", "www.federalreserve.gov",
               re.compile(r"/newsevents/pressreleases/[a-z]+\d{8}[a-z]\.htm"), page_text.fed_release,
               "Public domain; cite the Board as the source (https://www.federalreserve.gov/disclaimer.htm). The "
               "user import reads the same pages (publication_import). Read 2026-10-14."),
    TextSource("ec-press", "ec.europa.eu", EC_LINK, page_text.ec_document,
               "Content owned by the EU is licensed under CC BY 4.0, with credit given and changes indicated "
               "(https://commission.europa.eu/legal-notice_en); the press corner's documents service answers the "
               "text its pages show, and robots.txt does not disallow /commission/presscorner/. Read 2026-10-25.",
               pause_seconds=2.0, address=_ec_address, media="application/json",
               request=re.compile(r"https://ec\.europa\.eu/commission/presscorner/api/documents\?"
                                  r"reference=[A-Z]{2,8}/\d{2}/\d{1,6}&language=en")),
)}


def request_address(spec: TextSource, link: str) -> str:
    return spec.address(link) if spec.address is not None else link


def supported(source_key: str, link: str) -> TextSource | None:
    """The text source that may read this entry's page, or None (another publisher, or not a publication page)."""
    spec = SOURCES.get(source_key)
    if spec is None:
        return None
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.hostname != spec.host or port not in (None, 443) or parts.username or \
            parts.password or parts.fragment or spec.path.fullmatch(parts.path) is None:
        return None
    if (spec.query is None) != (not parts.query) or (spec.query is not None and not spec.query.fullmatch(parts.query)):
        return None
    return spec


def allowed(url: str) -> bool:
    """A publication page of a listed source, or the one address a source's ``address`` gives for such a page."""
    return any((spec.address is None and supported(key, url) is not None) or
               (spec.request is not None and spec.request.fullmatch(url) is not None) for key, spec in SOURCES.items())


def fetcher(transport: httpx.BaseTransport | None = None) -> publication_import.PublicationFetcher:
    """A fetcher that may request only the listed sources' publication pages (a simulated transport in tests)."""
    return publication_import.PublicationFetcher(transport, allowed=allowed, user_agent=USER_AGENT)


# ---------------------------------------------------------------- the records

def _entry_folder(folder: Path, entry_id: str) -> Path:
    source, _, digest = entry_id.partition(":")
    return folder / "texts" / source / digest


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def snapshots(folder: Path, entry_id: str) -> list[dict]:
    """Every readable text snapshot of an entry (metadata only), oldest first."""
    target = _entry_folder(folder, entry_id)
    found = []
    for path in sorted(target.glob("*.json")) if target.is_dir() else []:
        record = _read_json(path)
        if record and record.get("texts_version") == TEXTS_VERSION and path.name == f"{record.get('text_sha256')}.json":
            found.append(record)
    return sorted(found, key=lambda row: (row["retrieved_at"], row["text_sha256"]))


def attempts(folder: Path, entry_id: str) -> list[dict]:
    target = _entry_folder(folder, entry_id) / "attempts"
    rows = [_read_json(path) for path in sorted(target.glob("*.json"))] if target.is_dir() else []
    return [row for row in rows if row]


def text_of(folder: Path, snapshot: dict) -> str | None:
    """The snapshot's text, only if its bytes still have the recorded SHA-256."""
    path = _entry_folder(folder, snapshot["entry_id"]) / f"{snapshot['text_sha256']}.txt"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data.decode("utf-8") if hashlib.sha256(data).hexdigest() == snapshot["text_sha256"] else None


def text_state(folder: Path | None, report: dict) -> dict:
    """What this server holds of the report's publication text. Reads files only."""
    if folder is None or supported(report["source"], report["link"]) is None:
        return {"state": "not_supported", "detail": "This publisher's pages are not read for their text."}
    kept = snapshots(folder, report["entry_id"])
    if kept:
        newest = kept[-1]
        return {"state": newest["coverage"], "text_sha256": newest["text_sha256"], "characters": newest["characters"],
                "retrieved_at": newest["retrieved_at"], "extractor": newest["extractor"],
                "partial_reason": newest["partial_reason"], "url": newest["url"], "detail": None}
    tried = attempts(folder, report["entry_id"])
    if tried:
        return {"state": "failed", "detail": tried[-1]["detail"], "at": tried[-1]["at"]}
    return {"state": "not_retrieved", "detail": "The publication's text has not been retrieved."}


def _record(folder: Path, record: dict) -> int:
    target = folder / "retrievals"
    for _ in range(5):  # Another process may take a number first; a name is never reused.
        number = max((int(match.group(1)) for path in target.glob("*.json") if (match := NUMBER.fullmatch(path.name))),
                     default=0) + 1 if target.is_dir() else 1
        data = (json.dumps({**record, "number": number}, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
        if inbox_raw.write_once(target / f"{number:06d}.json", data):
            return number
    raise OSError("no free retrieval number")


def _kept_copy(folder: Path, url: str, media: str = "text/html") -> tuple[bytes, str, dict] | None:
    """A complete copy of this address's answer kept by an earlier retrieval, whose bytes still match their SHA-256."""
    target = folder / "retrievals"
    for path in sorted(target.glob("*.json"), reverse=True) if target.is_dir() else []:
        record = _read_json(path)
        if not record or record.get("url") != url or not record.get("kept"):
            continue
        raw_path = folder / "raw" / f"{record['body']['sha256']}{SUFFIX[media]}"
        try:
            raw = raw_path.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(raw).hexdigest() == record["body"]["sha256"]:
            return raw, record["content_type"], record
    return None


def _snapshot(folder: Path, report: dict, spec: TextSource, read: dict, retrieval: dict, attribution: str) -> dict:
    data = read["text"].encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    target = _entry_folder(folder, report["entry_id"])
    target.mkdir(parents=True, exist_ok=True)
    record = {"texts_version": TEXTS_VERSION, "entry_id": report["entry_id"],
              "entry_version_sha256": report["version_sha256"], "source": spec.source, "publisher": report["publisher"],
              "url": report["link"], "retrieval": retrieval["number"], "retrieved_at": retrieval["retrieved_at"],
              "raw_sha256": retrieval["raw_sha256"], "extractor": read["extractor"],
              "text_version": page_text.TEXT_VERSION, "title": read["title"], "date_printed": read["date"],
              "characters": read["characters"], "text_sha256": digest,
              "coverage": "partial_text" if read["partial"] else "full_text", "partial_reason": read["partial_reason"],
              "left_out": read["left_out"], "attribution": attribution, "basis": spec.basis}
    inbox_raw.write_once(target / f"{digest}.txt", data)
    try:
        market_store.write_exclusive(target / f"{digest}.json", record)
    except FileExistsError:
        pass  # The same text was kept before; it stays as it was.
    return record


def _attempt(folder: Path, report: dict, outcome: str, detail: str, number: int | None, moment: datetime) -> None:
    target = _entry_folder(folder, report["entry_id"]) / "attempts"
    target.mkdir(parents=True, exist_ok=True)
    name = f"{number:06d}.json" if number is not None else f"reread-{stamp(moment).replace(':', '')}.json"
    data = json.dumps({"entry_id": report["entry_id"], "url": report["link"], "outcome": outcome, "detail": detail,
                       "retrieval": number, "at": stamp(moment)}, ensure_ascii=False).encode("utf-8")
    inbox_raw.write_once(target / name, data)


def retrieve(folder: Path, report: dict, attribution: str, fetch: publication_import.PublicationFetcher,
             clock: Callable[[], datetime] = event_inbox.now) -> dict:
    """The report's publication text: a snapshot already kept, the kept copy read again, or one request; what
    happened is returned and recorded."""
    spec = supported(report["source"], report["link"])
    if spec is None:
        return {"entry_id": report["entry_id"], "outcome": "not_supported", "requested": False,
                "detail": "This publisher's pages are not read for their text."}
    kept = snapshots(folder, report["entry_id"])
    if kept:
        return {"entry_id": report["entry_id"], "outcome": "reused", "requested": False,
                "text_sha256": kept[-1]["text_sha256"], "detail": "A kept text was used; nothing was requested."}
    address = request_address(spec, report["link"])
    copy = _kept_copy(folder, address, spec.media)
    if copy is not None:
        raw, content_type, record = copy
        retrieval = {"number": record["number"], "retrieved_at": record["finished_at"],
                     "raw_sha256": record["body"]["sha256"]}
        return _read(folder, report, spec, raw, content_type, retrieval, attribution, clock, requested=False)
    started = clock()
    try:
        fetched = fetch.fetch(address, accept=spec.media)
    except event_inbox.FetchFailed as exc:
        number = _record(folder, {"texts_version": TEXTS_VERSION, "entry_id": report["entry_id"],
                                  "url": address, "started_at": stamp(started), "finished_at": stamp(clock()),
                                  "response": exc.response, "body": exc.received, "kept": False, "content_type": None,
                                  "outcome": "failed", "detail": str(exc)})
        _attempt(folder, report, "failed", str(exc), number, clock())
        return {"entry_id": report["entry_id"], "outcome": "failed", "requested": True, "detail": str(exc)}
    raw_sha = hashlib.sha256(fetched.body).hexdigest()
    media = fetched.content_type.split(";")[0].strip().lower()
    raw_path = folder / "raw" / f"{raw_sha}{SUFFIX[spec.media]}"
    kept_raw = media == spec.media and inbox_raw.write_once(raw_path, fetched.body) or raw_path.is_file()
    finished = clock()
    number = _record(folder, {"texts_version": TEXTS_VERSION, "entry_id": report["entry_id"], "url": address,
                              "started_at": stamp(started), "finished_at": stamp(finished),
                              "response": fetched.response, "body": {**(fetched.received or {}), "sha256": raw_sha},
                              "kept": bool(kept_raw), "content_type": fetched.content_type,
                              "outcome": "received", "detail": None})
    retrieval = {"number": number, "retrieved_at": stamp(finished), "raw_sha256": raw_sha}
    if media != spec.media:
        detail = (f"The publisher answered with {media or 'no media type'}, not " +
                  ("a web page" if spec.media == "text/html" else spec.media))
        _attempt(folder, report, "unreadable", detail, number, finished)
        return {"entry_id": report["entry_id"], "outcome": "unreadable", "requested": True, "detail": detail}
    return _read(folder, report, spec, fetched.body, fetched.content_type, retrieval, attribution, clock,
                 requested=True)


def _read(folder: Path, report: dict, spec: TextSource, raw: bytes, content_type: str, retrieval: dict,
          attribution: str, clock: Callable[[], datetime], requested: bool) -> dict:
    try:
        read = spec.read(raw, content_type)
    except page_text.Unreadable as exc:
        _attempt(folder, report, "unreadable", str(exc), retrieval["number"] if requested else None, clock())
        return {"entry_id": report["entry_id"], "outcome": "unreadable", "requested": requested, "detail": str(exc)}
    snapshot = _snapshot(folder, report, spec, read, retrieval, attribution)
    return {"entry_id": report["entry_id"], "outcome": "retrieved" if requested else "reread", "requested": requested,
            "text_sha256": snapshot["text_sha256"], "coverage": snapshot["coverage"],
            "characters": snapshot["characters"], "detail": snapshot["partial_reason"]}


def plan(folder: Path, reports: list[dict]) -> list[dict]:
    """What a retrieval of these reports would do, without doing it: reuse, read a kept copy again, or request."""
    rows = []
    for report in reports:
        spec = supported(report["source"], report["link"])
        if spec is None:
            action = "not_supported"
        elif snapshots(folder, report["entry_id"]):
            action = "reuse"
        elif _kept_copy(folder, request_address(spec, report["link"]), spec.media) is not None:
            action = "reread"
        else:
            action = "request"
        rows.append({"entry_id": report["entry_id"], "publisher": report["publisher"], "title": report["title"],
                     "link": report["link"], "action": action})
    return rows


def retrieve_all(folder: Path, reports: list[dict], attributions: dict[str, str],
                 fetch: publication_import.PublicationFetcher, clock: Callable[[], datetime] = event_inbox.now,
                 limit: int = MAX_PER_RUN, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    """Retrieve each report's text in order, at most ``limit`` requests, pausing between two requests to one host."""
    done, requests, last = [], 0, {}
    for report in reports:
        spec = supported(report["source"], report["link"])
        needs = spec is not None and not snapshots(folder, report["entry_id"]) and \
            _kept_copy(folder, request_address(spec, report["link"]), spec.media) is None
        if needs and requests >= limit:
            done.append({"entry_id": report["entry_id"], "outcome": "not_requested", "requested": False,
                         "detail": f"This run's limit of {limit} requests was reached."})
            continue
        if needs and spec.host in last:
            wait = spec.pause_seconds - (time.monotonic() - last[spec.host])
            if wait > 0:
                sleep(wait)
        outcome = retrieve(folder, report, attributions.get(report["source"], ""), fetch, clock)
        if outcome["requested"]:
            requests += 1
            last[spec.host] = time.monotonic()
        done.append(outcome)
    return done


# ---------------------------------------------------------------- the operator's selection

def story_reports(found: dict, story_ids: list[str] | None, hot: bool, now: datetime) -> list[dict]:
    """The reports whose texts a retrieval would read: those of the named stories, or of the stories in Hot now (in
    their order), whose publishers allow their use; each once."""
    from . import news_rank
    stories = found["stories"]
    if story_ids:
        missing = [story_id for story_id in story_ids if story_id not in stories]
        if missing:
            raise ValueError(f"Not current stories: {', '.join(missing)}")
        chosen = [stories[story_id] for story_id in story_ids]
    elif hot:
        chosen = news_rank.hot(list(stories.values()), now)
    else:
        chosen = []
    seen, rows = set(), []
    for story in chosen:
        for report in story["reports"]:
            if report["material"] == "permitted" and report["entry_id"] not in seen:
                seen.add(report["entry_id"])
                rows.append(report)
    return rows

"""Publication import: from a verified Event Inbox entry to the user's own immutable source (publication-import-0.1).

A feed entry is discovery metadata. When its publisher has a verified extractor, a user may explicitly import the full
publication its link names: the server retrieves that one official page (or reuses the copy it already retained),
keeps its exact bytes, extracts the release's own words and shows a preview with its provenance and publication time;
only an explicit confirmation of that exact text (its SHA-256) saves it, through the existing user source path, as a
source the user owns, with the entry version recorded as its Inbox origin. Nothing is analysed, quoted or sent.

Publishers (PUBLISHERS) are added one at a time after their terms and page layout are checked. The first is the Federal
Reserve Board's monetary-policy press releases: https://www.federalreserve.gov/disclaimer.htm (checked 2026-10-14) puts
the Board's information in the public domain and asks to be cited as the source; the site published no robots.txt when
checked. Pages are read by fed_publication.

Retrieval (publication-retrieval-0.1) is bounded like the feeds: an https address on the publisher's host whose path
is a press-release page, GET only, no redirect, no retry, 10 s to connect, 20 s to read, 30 s for the whole response,
2 MB, text/html in UTF-8. One retrieval runs at a time on a server; another import of any page meanwhile is refused as
in progress, never queued. Every request leaves one write-once numbered record (endpoint, times, status line and kept
headers, body state, size and SHA-256, the kept copy, the extraction's outcome) under data/publication-imports/
retrievals/, and an accepted page's bytes are kept once under raw/<sha256>.html, read-only. A retained copy of the same
address is reused instead of retrieving it again; its retrieval time is shown.

The publication time is never the retrieval time. The feed must state an instant; the page's printed date must be that
instant's New York date, and a printed release time must name the same instant (EDT or EST as New York uses on that
date). A disagreement refuses the import. Unknown layouts, other encodings, tables, empty bodies and texts over the
source limit are refused whole and never cut: the user can paste the text instead with the existing form.

Each preview (previews/<import ID>.json) and confirmation (confirmations/<import ID>.json) is created once and is
read-only, and both belong to one account: another account's import answers like a missing one. A claim file makes a
confirmation exclusive; one that stopped after its claim is reported as interrupted and nothing is created again.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from . import event_inbox, event_links, fed_publication, inbox_acquisitions, inbox_archive, inbox_raw, market_store
from . import user_research
from .accounts import AccountsRefused, Identity
from .user_research import refused

IMPORT_VERSION = "publication-import-0.1"
RETRIEVAL_VERSION = "publication-retrieval-0.1"
ROOT = Path(__file__).resolve().parent.parent
IMPORTS_DIR = ROOT / "data" / "publication-imports"  # Runtime records; data/ is ignored by git.
MAX_BYTES = 2_000_000
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DEADLINE_SECONDS = 30
USER_AGENT = "SecondOrder/0.1 (local research tool; one publication fetched on a user's explicit import)"
IMPORT_ID = re.compile(r"imp-[0-9a-f]{16}")
SHA256 = re.compile(r"[0-9a-f]{64}")
NUMBER = re.compile(r"(\d{6})\.json")
CONFIRM_FIELDS = {"text_sha256", "confirm"}
CLAIM_GRACE = timedelta(minutes=2)  # A claim younger than this without a confirmation is still in progress.
NEW_YORK = ZoneInfo("America/New_York")
PASTE = "You can open the official page and paste its text into a new source instead."
FETCHING = threading.Lock()  # One publication retrieval at a time on this server.


@dataclass(frozen=True)
class Publisher:
    source: str  # The Event Inbox source whose entries may be imported.
    host: str
    path: re.Pattern
    citation: str
    terms_url: str
    terms_checked: str
    extractor_version: str


PUBLISHERS = {publisher.source: publisher for publisher in (
    Publisher("fed-monetary", "www.federalreserve.gov", re.compile(r"/newsevents/pressreleases/[a-z]+\d{8}[a-z]\.htm"),
              "Source: Board of Governors of the Federal Reserve System", "https://www.federalreserve.gov/disclaimer.htm",
              "2026-10-14", fed_publication.EXTRACTOR_VERSION),
)}


@dataclass(frozen=True)
class Folders:
    inbox: Path  # the shared Event Inbox cache, only read
    imports: Path  # this module's records

    @property
    def retrievals(self) -> Path:
        return self.imports / "retrievals"

    @property
    def raw(self) -> Path:
        return self.imports / "raw"

    @property
    def previews(self) -> Path:
        return self.imports / "previews"

    @property
    def claims(self) -> Path:
        return self.imports / "claims"

    @property
    def confirmations(self) -> Path:
        return self.imports / "confirmations"


def now() -> datetime:
    return event_inbox.now()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- what may be imported

def address_allowed(publisher: Publisher, link: str) -> bool:
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and parts.hostname == publisher.host and port in (None, 443) and
            not parts.username and not parts.password and not parts.query and not parts.fragment and
            publisher.path.fullmatch(parts.path) is not None)


def support(source: str, link: str, stamp: dict) -> tuple[str, str | None]:
    """("supported", None) or ("unsupported", why, in user words). Reads nothing."""
    publisher = PUBLISHERS.get(source)
    if publisher is None:
        return "unsupported", f"Importing the full publication is not available for this publisher yet. {PASTE}"
    if not address_allowed(publisher, link):
        return "unsupported", f"This entry's address is not a press-release page this import reads. {PASTE}"
    if stamp.get("instant_utc") is None or stamp.get("suggestion") is None:
        return "unsupported", ("The feed states no usable publication time for this entry, and none is taken from "
                               f"elsewhere. {PASTE}")
    return "supported", None


# ---------------------------------------------------------------- the entry version

def _entry_version(folders: Folders, entry_id: object, version_sha256: object) -> tuple[dict, dict]:
    """(the entry's content at that version, its checked origin) or a refusal. Reads only."""
    if not isinstance(entry_id, str) or not isinstance(version_sha256, str) or not SHA256.fullmatch(version_sha256) \
            or entry_id.split(":", 1)[0] not in event_inbox.SOURCES:
        raise refused(404, "not_found", "No such news entry.")
    try:
        origin = event_links.check_origin({"item_id": entry_id, "content_sha256": version_sha256}, folders.inbox)
    except event_links.LinkRefused:
        raise refused(409, "entry_changed", "This news entry changed or is no longer held at the version shown. "
                                            "Reload the news and choose it again.") from None
    view = event_inbox.inbox_view(folders.inbox)
    for item in view["items"] + view["retained"]:
        if item["id"] == entry_id and inbox_archive.content_sha256(item) == version_sha256:
            return item, origin
    source = event_inbox.SOURCES[origin["source"]]
    state, archive, _ = inbox_archive.read_archive(folders.inbox, source.key, source.feed_url,
                                                   lambda link: event_inbox._is_official(link, source))
    for entry in (archive or {}).get("entries", []) if state == "ok" else []:
        if entry["id"] == entry_id:
            for version in entry["versions"]:
                if version["content_sha256"] == version_sha256:
                    return {"id": entry_id, **version}, origin
    raise refused(409, "entry_changed", "This news entry is no longer held at the version shown. Reload the news.")


def _supported(item: dict, source: str) -> Publisher:
    state, reason = support(source, item["link"], item["feed_timestamp"])
    if state != "supported":
        raise refused(409, "import_unsupported", reason, paste_instead=True)
    return PUBLISHERS[source]


# ---------------------------------------------------------------- retrieval

class PublicationFetcher:
    """Requests one allowlisted publication page once: no redirects, no retries, a timeout and a size cap. The
    transport is chosen when the server starts (a simulated one in tests), never through the API."""

    def __init__(self, transport: httpx.BaseTransport | None = None, allowed: Callable[[str], bool] | None = None,
                 user_agent: str = USER_AGENT):
        self.transport = transport
        self.allowed = allowed  # Another module's allowlist (news_texts); None: this module's publishers.
        self.user_agent = user_agent

    def fetch(self, url: str, accept: str = "text/html") -> event_inbox.Fetched:
        if self.allowed is not None:
            permitted = self.allowed(url)
        else:
            permitted = any(address_allowed(publisher, url) for publisher in PUBLISHERS.values())
        if not permitted:
            raise event_inbox.FetchFailed("Only press-release pages of the listed publishers can be requested")
        headers = {"User-Agent": self.user_agent, "Accept": accept}
        seen: dict = {"response": None}
        received = inbox_acquisitions.Received()

        def failed(message: str, status: int | None = None) -> event_inbox.FetchFailed:
            return event_inbox.FetchFailed(message, status, seen["response"], received.summary(seen["response"]))

        try:
            with httpx.Client(transport=self.transport, timeout=TIMEOUT, follow_redirects=False, trust_env=False,
                              max_redirects=0) as client:
                with client.stream("GET", url, headers=headers) as response:
                    status = response.status_code
                    seen["response"], received.state = inbox_acquisitions.response_metadata(response), "not_read"
                    if response.is_redirect:
                        raise failed(f"HTTP {status}: the page redirects elsewhere; redirects are not followed", status)
                    if status != 200:
                        raise failed(f"HTTP {status} from the publisher", status)
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise failed(f"The page declares {declared} bytes; the limit is {MAX_BYTES}", status)
                    chunks, deadline, received.state = [], time.monotonic() + DEADLINE_SECONDS, "partial"
                    for chunk in response.iter_bytes():
                        received.add(chunk)
                        if received.size > MAX_BYTES:
                            raise failed(f"The page exceeded {MAX_BYTES} bytes and was not read further", status)
                        if time.monotonic() > deadline:
                            raise failed(f"The page took longer than {DEADLINE_SECONDS} seconds to arrive", status)
                        chunks.append(chunk)
                    received.state = "complete"
                    return event_inbox.Fetched(status, response.headers.get("content-type", ""), b"".join(chunks),
                                               seen["response"], received.summary(seen["response"]))
        except httpx.TimeoutException:
            raise failed("The publisher did not answer in time") from None
        except httpx.HTTPError as exc:
            raise failed(f"The request failed ({type(exc).__name__})") from None


def _keep_record(folders: Folders, record: dict) -> int:
    for _ in range(5):  # Another process may take a number first; a name is never reused.
        target = folders.retrievals
        number = max((int(match.group(1)) for path in target.glob("*.json") if (match := NUMBER.fullmatch(path.name))),
                     default=0) + 1 if target.is_dir() else 1
        data = (json.dumps({**record, "number": number}, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
        if inbox_raw.write_once(target / f"{number:06d}.json", data):
            return number
    raise OSError("no free retrieval number")


def retrievals(folders: Folders) -> list[dict]:
    """Every readable retrieval record, oldest first. Reads only; an unreadable one is skipped, never repaired."""
    found = []
    for path in sorted(folders.retrievals.glob("*.json")) if folders.retrievals.is_dir() else []:
        try:
            record = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("retrieval_version") == RETRIEVAL_VERSION and \
                path.name == f"{record.get('number', 0):06d}.json":
            found.append(record)
    return found


def _raw(folders: Folders, digest: str) -> bytes | None:
    path = folders.raw / f"{digest}.html"
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data if sha256(data) == digest else None


def _reusable(folders: Folders, url: str) -> dict | None:
    """The newest retrieval of this address whose page arrived complete as HTML (HTTP 200) and whose kept copy still
    holds its bytes. An earlier refusal to read it does not stop a later reading of the same bytes; its record keeps
    what that earlier reading found, and nothing is requested again."""
    for record in reversed(retrievals(folders)):
        response = record["response"] or {}
        media = (response.get("headers") or {}).get("content-type", "").split(";")[0].strip().lower()
        if record["url"] == url and record["kept"] and record["body"].get("state") == "complete" and \
                response.get("http_status") == 200 and media == "text/html" and \
                _raw(folders, record["body"]["sha256"]) is not None:
            return record
    return None


def needs_fetch(folders: Folders, entry_id: object, version_sha256: object) -> bool:
    """Whether preparing this import would contact the publisher (no retained copy of its page). Reads only."""
    item, origin = _entry_version(folders, entry_id, version_sha256)
    _supported(item, origin["source"])
    return _reusable(folders, item["link"]) is None


def _extract(raw: bytes, content_type: str) -> dict:
    return fed_publication.extract(raw, content_type)


def _retrieve(folders: Folders, publisher: Publisher, item: dict, user_id: str, fetcher: PublicationFetcher,
              clock: Callable[[], datetime], attempt: dict) -> tuple[dict, dict, bool]:
    """(retrieval record, extraction, reused) for the entry's page. A refusal leaves the record of what happened;
    `attempt["requested"]` becomes true once the publisher is contacted."""
    url = item["link"]
    kept = _reusable(folders, url)
    if kept is not None:
        try:
            return kept, _extract(_raw(folders, kept["body"]["sha256"]), kept["response"]["headers"].get(
                "content-type", "")), True
        except fed_publication.Unreadable as exc:
            raise refused(422, "publication_unreadable", f"{exc}. {PASTE}", paste_instead=True) from None
    if not FETCHING.acquire(blocking=False):
        raise refused(409, "import_in_progress", "Another publication is being retrieved on this server now. Try again "
                                                 "in a moment; nothing was retrieved for this import.")
    try:
        started = event_inbox.stamp(clock())
        fetched, failure, extracted, problem, kept_name = None, None, None, None, None
        attempt["requested"] = True
        try:
            fetched = fetcher.fetch(url)
        except event_inbox.FetchFailed as exc:
            failure = exc
        finished = event_inbox.stamp(clock())
        if fetched is not None:
            media = fetched.content_type.split(";")[0].strip().lower()
            if media != "text/html":
                problem = f"The publisher answered with {media or 'no content type'}, not a web page"
            else:
                try:
                    extracted = _extract(fetched.body, fetched.content_type)
                except fed_publication.Unreadable as exc:
                    problem = str(exc)
                name = f"{sha256(fetched.body)}.html"  # Kept as evidence even when it cannot be read.
                try:
                    inbox_raw.write_once(folders.raw / name, fetched.body)
                    kept_name = name if _raw(folders, sha256(fetched.body)) is not None else None
                except OSError:
                    kept_name = None
                if kept_name is None and problem is None:
                    problem = "The page could not be kept on this server"
        outcome = "failed" if fetched is None else "accepted" if problem is None else "refused"
        body = fetched.received if fetched is not None and fetched.received else (
            {"state": "complete", "bytes": len(fetched.body), "sha256": sha256(fetched.body), "declared_bytes": None,
             "content_encoding": None} if fetched is not None else
            (failure.received or inbox_acquisitions.Received().summary(failure.response)))
        detail = str(failure) if failure else problem
        record = {"retrieval_version": RETRIEVAL_VERSION, "url": url, "source": publisher.source,
                  "entry": {"entry_id": item["id"], "version_sha256": inbox_archive.content_sha256(item)},
                  "requested_by": user_id,
                  "request": {"method": "GET", "redirects_followed": False, "retries": 0, "user_agent": USER_AGENT},
                  "started_at": started, "finished_at": finished, "outcome": outcome, "detail": detail,
                  "response": fetched.response if fetched is not None else (failure.response if failure else None),
                  "body": body, "kept": kept_name,
                  "extraction": None if extracted is None else {
                      "extractor": extracted["extractor"], "text_sha256": sha256(extracted["text"].encode("utf-8")),
                      "characters": extracted["characters"], "paragraphs": extracted["paragraphs"]}}
        number = _keep_record(folders, record)
        record["number"] = number
    finally:
        FETCHING.release()
    if outcome == "failed":
        raise refused(409, "publication_unavailable", f"The publication could not be retrieved: {failure}. Nothing was "
                                                      f"imported. {PASTE}", paste_instead=True)
    if outcome == "refused":
        raise refused(422, "publication_unreadable", f"{detail}. Nothing was imported. {PASTE}", paste_instead=True)
    return record, extracted, False


# ---------------------------------------------------------------- the publication time

def _published_at(stamp: dict, extracted: dict) -> tuple[str, str]:
    """The source's publication time (the feed's own stated form) and the statements it rests on; refused when the
    page's printed date or time disagrees."""
    instant = datetime.fromisoformat(stamp["instant_utc"])
    suggestion = stamp["suggestion"]
    stated = instant.astimezone(NEW_YORK).date().isoformat()
    if extracted["date"] != stated:
        raise refused(409, "publication_time_conflict", f"The page prints {extracted['date_line']}, but the feed's time "
                                                        f"({stamp['raw']}) falls on {stated} in Washington. Nothing "
                                                        f"was imported. {PASTE}", paste_instead=True)
    basis = f"The publisher's feed states {stamp['raw']}; the page prints the date {extracted['date_line']}"
    if extracted["release_time"] is not None:
        printed = fed_publication.printed_instant(extracted)
        if printed is None or printed != instant:
            raise refused(409, "publication_time_conflict", f"The page prints \"{extracted['release_line']}\", which "
                                                            f"does not name the feed's time ({stamp['raw']}). Nothing "
                                                            f"was imported. {PASTE}", paste_instead=True)
        basis += f" and \"{extracted['release_line']}\", the same instant"
    else:
        basis += " without a time of day, so the time is the feed's"
    return f"{suggestion['date']}T{suggestion['time']}{suggestion['offset']}", basis + "."


# ---------------------------------------------------------------- previews

def _previews(folders: Folders) -> list[dict]:
    found = []
    for path in sorted(folders.previews.glob("imp-*.json")) if folders.previews.is_dir() else []:
        try:
            record = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("import_id") == path.stem:
            found.append(record)
    return found


def _own(folders: Folders, identity: Identity, import_id: object) -> dict:
    if not isinstance(import_id, str) or not IMPORT_ID.fullmatch(import_id):
        raise refused(404, "not_found", "No such import.")
    path = folders.previews / f"{import_id}.json"
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        raise refused(404, "not_found", "No such import.") from None
    if not isinstance(record, dict) or record.get("user_id") != identity.user_id or record.get("import_id") != import_id:
        raise refused(404, "not_found", "No such import.")
    return record


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _current(folders: Folders, record: dict) -> tuple[dict | None, str | None]:
    """The preview's text extracted again from the kept bytes, or why it cannot be shown."""
    raw = _raw(folders, record["retrieval"]["raw_sha256"])
    if raw is None:
        return None, "The retained page is missing or no longer holds the bytes this import read."
    try:
        extracted = _extract(raw, record["retrieval"]["content_type"])
    except fed_publication.Unreadable as exc:
        return None, f"The retained page can no longer be read ({exc})."
    if sha256(extracted["text"].encode("utf-8")) != record["proposed"]["text_sha256"] or \
            extracted["extractor"] != record["extractor"]:
        return None, "Reading the retained page again gives another text than this import showed."
    return extracted, None


def _state(folders: Folders, record: dict, clock: Callable[[], datetime]) -> tuple[str, dict | None]:
    confirmation = _read_json(folders.confirmations / f"{record['import_id']}.json")
    if isinstance(confirmation, dict) and confirmation.get("import_id") == record["import_id"]:
        return "confirmed", confirmation
    claim = _read_json(folders.claims / f"{record['import_id']}.json")
    if isinstance(claim, dict):
        claimed = datetime.fromisoformat(claim["claimed_at"])
        return ("confirming" if clock() - claimed < CLAIM_GRACE else "interrupted"), None
    return "ready", None


def _view(folders: Folders, record: dict, clock: Callable[[], datetime]) -> dict:
    state, confirmation = _state(folders, record, clock)
    extracted, problem = _current(folders, record)
    if problem:
        state = "unreadable"
    publisher = PUBLISHERS[record["entry"]["source"]]
    proposed = record["proposed"]
    return {"import_version": IMPORT_VERSION, "import_id": record["import_id"], "state": state, "problem": problem,
            "created_at": record["created_at"],
            "entry": {key: record["entry"][key] for key in ("entry_id", "version_sha256", "source", "title", "link")} |
                     {"publisher": event_inbox.SOURCES[record["entry"]["source"]].publisher,
                      "attribution": publisher.citation},
            "publication": {"url": record["retrieval"]["url"], "retrieved_at": record["retrieval"]["retrieved_at"],
                            "retrieval": "reused" if record["retrieval"]["reused"] else "fetched",
                            "bytes": record["retrieval"]["bytes"], "sha256": record["retrieval"]["raw_sha256"],
                            "last_modified": record["retrieval"]["last_modified"], "extractor": record["extractor"],
                            "terms_url": publisher.terms_url},
            "proposed_source": {**{key: proposed[key] for key in (
                "headline", "source_url", "published_at", "published_basis", "characters", "paragraphs",
                "text_sha256")}, "text": extracted["text"] if extracted else None},
            "left_out": extracted["left_out"] if extracted else [],
            "linked_documents": extracted["linked_documents"] if extracted else [],
            "source_id": confirmation["capture_id"] if confirmation else None,
            "statements": [
                (f"The text was read from the official page {record['retrieval']['url']} as this server retrieved it "
                 f"on {record['retrieval']['retrieved_at']}: the release's own words in its order. Lines listed as "
                 "left out are not in it; linked documents were not retrieved."),
                f"Publication time: {proposed['published_basis']}",
                (f"{publisher.citation}. The publisher's terms: {publisher.terms_url}."),
                ("Nothing has been analysed. Confirming saves exactly this text as your source; preparing, quoting "
                 "and running an analysis remain separate steps.")]}


def prepare(folders: Folders, identity: Identity, entry_id: object, version_sha256: object,
            fetcher: PublicationFetcher, clock: Callable[[], datetime] = now) -> tuple[dict, bool]:
    """A preview of the entry's publication for this user: (view, created). The same user's earlier preview of the
    same entry version is returned instead of a new one. At most one page is requested, only without a retained copy.
    Every refusal says in `requested` whether the publisher was contacted for it, so usage can be counted exactly."""
    attempt = {"requested": False}
    try:
        item, origin = _entry_version(folders, entry_id, version_sha256)
        publisher = _supported(item, origin["source"])
        for record in _previews(folders):
            if record.get("user_id") == identity.user_id and record["entry"]["entry_id"] == entry_id and \
                    record["entry"]["version_sha256"] == version_sha256:
                return _view(folders, record, clock), False
        retrieval, extracted, reused = _retrieve(folders, publisher, item, identity.user_id, fetcher, clock, attempt)
        published_at, basis = _published_at(item["feed_timestamp"], extracted)
        if "\n" in extracted["title"] or len(extracted["title"]) > 1_500:
            raise refused(422, "publication_unreadable", f"The page's title cannot be a source headline. {PASTE}",
                          paste_instead=True)
    except AccountsRefused as exc:
        exc.extra["requested"] = attempt["requested"]
        raise
    import_id = f"imp-{secrets.token_hex(8)}"
    record = {"import_version": IMPORT_VERSION, "import_id": import_id, "user_id": identity.user_id,
              "created_at": event_inbox.stamp(clock()),
              "entry": {"entry_id": item["id"], "version_sha256": origin["content_sha256"], "source": origin["source"],
                        "title": item["title"], "link": item["link"], "feed_timestamp": item["feed_timestamp"]},
              "retrieval": {"number": retrieval["number"], "url": retrieval["url"],
                            "retrieved_at": retrieval["finished_at"], "raw_sha256": retrieval["body"]["sha256"],
                            "bytes": retrieval["body"]["bytes"], "reused": reused,
                            "content_type": retrieval["response"]["headers"].get("content-type", ""),
                            "last_modified": retrieval["response"]["headers"].get("last-modified")},
              "extractor": extracted["extractor"],
              "proposed": {"headline": extracted["title"], "source_url": item["link"], "published_at": published_at,
                           "published_basis": basis, "text_sha256": sha256(extracted["text"].encode("utf-8")),
                           "characters": extracted["characters"], "paragraphs": extracted["paragraphs"]}}
    market_store.write_exclusive(folders.previews / f"{import_id}.json", record)
    return _view(folders, record, clock), True


def read(folders: Folders, identity: Identity, import_id: object, clock: Callable[[], datetime] = now) -> dict:
    """One of the user's imports, its text extracted again from the kept bytes. Reads only."""
    return _view(folders, _own(folders, identity, import_id), clock)


def imported_entries(folders: Folders, identity: Identity) -> dict[str, list[str]]:
    """This user's confirmed imports: entry ID -> the source IDs made from it. Reads only."""
    found: dict[str, list[str]] = {}
    for path in sorted(folders.confirmations.glob("imp-*.json")) if folders.confirmations.is_dir() else []:
        record = _read_json(path)
        if isinstance(record, dict) and record.get("user_id") == identity.user_id:
            found.setdefault(record["entry_id"], []).append(record["capture_id"])
    return found


def confirm(folders: Folders, context: user_research.UserResearch, identity: Identity, import_id: object,
            payload: object, clock: Callable[[], datetime] = now) -> tuple[dict, bool]:
    """Save the previewed text as the user's source: ({import, source}, created). Exactly once per import."""
    record = _own(folders, identity, import_id)
    state, confirmation = _state(folders, record, clock)
    if state == "confirmed":
        source = user_research.source_detail(context, identity, confirmation["capture_id"])["source"]
        return {"import": _view(folders, record, clock), "source": source}, False
    if not isinstance(payload, dict) or set(payload) != CONFIRM_FIELDS or payload["confirm"] is not True or \
            not isinstance(payload["text_sha256"], str) or not SHA256.fullmatch(payload["text_sha256"]):
        raise refused(422, "invalid_request", "A confirmation names the text it confirms and sets confirm to true.")
    if state == "confirming":
        raise refused(409, "import_in_progress", "This import is being confirmed now. Reload it in a moment.")
    if state == "interrupted":
        raise refused(409, "import_interrupted", "An earlier confirmation of this import stopped before it finished; "
                                                 "nothing is created again. An administrator can check it.")
    extracted, problem = _current(folders, record)
    if problem or payload["text_sha256"] != record["proposed"]["text_sha256"]:
        raise refused(409, "publication_changed", problem or "The confirmation names another text than this import "
                                                             "showed. Reload the import.")
    entry = record["entry"]
    try:
        origin = event_links.check_origin({"item_id": entry["entry_id"], "content_sha256": entry["version_sha256"]},
                                          folders.inbox)
    except event_links.LinkRefused:
        raise refused(409, "entry_changed", "The news entry this import started from is no longer held at that "
                                            "version, so it cannot be recorded as the source's origin.") from None
    claim = folders.claims / f"{record['import_id']}.json"
    try:
        market_store.write_exclusive(claim, {"import_id": record["import_id"], "user_id": identity.user_id,
                                             "claimed_at": event_inbox.stamp(clock())})
    except FileExistsError:
        raise refused(409, "import_in_progress", "This import is being confirmed now. Reload it in a moment.") from None
    proposed = record["proposed"]
    form = {"headline": proposed["headline"], "source_url": proposed["source_url"],
            "published_at": proposed["published_at"], "source_text": extracted["text"]}
    try:
        saved = user_research.add_source(context, identity, json.dumps(form, ensure_ascii=False).encode("utf-8"))
    except AccountsRefused as exc:
        if exc.status < 500:  # Nothing was written by the refused call, so the claim is released.
            os.chmod(claim, 0o600)
            claim.unlink()
        raise
    capture_id = saved["source"]["source_id"]
    link = event_links.record_origin(context.folders.links, capture_id, context.intake, origin, clock)
    market_store.write_exclusive(folders.confirmations / f"{record['import_id']}.json", {
        "import_version": IMPORT_VERSION, "import_id": record["import_id"], "user_id": identity.user_id,
        "entry_id": entry["entry_id"], "version_sha256": entry["version_sha256"], "capture_id": capture_id,
        "capture_request_sha256": link["capture_request_sha256"], "text_sha256": proposed["text_sha256"],
        "raw_sha256": record["retrieval"]["raw_sha256"], "confirmed_at": event_inbox.stamp(clock())})
    return {"import": _view(folders, record, clock), "source": saved["source"]}, True

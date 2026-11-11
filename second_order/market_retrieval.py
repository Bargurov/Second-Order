"""Planning and sending explicitly approved market-data retrievals for selected events, and the pages that read them.

Planning (`plan`) only reads. For the selected events it lists every expected session in their windows before today's
New York date and finds which ones verified local data already states (market_store: the committed case-library
downloads, earlier private CSV retrievals, and kept H.15 release packages that a validation accepted). When sessions are
missing it plans at most one request: the Board's complete H.15 release package (SOURCE) from its fixed address. That
package is neither date-bounded nor limited to the two series: it holds every series of the release over its full
history, so one request covers every missing session the Board has published, and the plan says so before any
approval. Sessions on or after today are never requested. The plan names its source, series, address, what the
download contains, what is reused and what is missing, the exact number of requests (0 or 1), that no key or charge
applies, the terms, and the Board's announced changes to its downloads.

Sending (`dispatch`) happens only when the operator approves a plan by its SHA-256, the events and the attempt number
it showed, on a server started with market retrieval enabled. Under the store's cross-process write lock (a second
dispatch is refused, never queued) the plan is computed again from the local data immediately before sending; any
difference refuses the approval with nothing sent. The attempt's start is recorded before the request goes out, and
its outcome after; each attempt number can be started once, so repeated clicks, other tabs or other server processes
cannot send the same approved work twice. The fetcher (ReleaseFetcher) requests only the fixed package address (never
an address from a request, a feed or a user) with Accept */*, Accept-Encoding identity and this app's User-Agent; it
sends no cookie, follows no redirect, refuses any content encoding instead of decoding it, keeps no Set-Cookie value,
and streams the raw bytes to a private staging file within size and time limits, never holding the archive in memory.
A reply whose archive passes the safeguards (market_package.check_archive) is kept as acquired but unvalidated; its
data entry is then parsed under the protected-parser policy and the result recorded once as accepted or refused. Only
an accepted package is used; a refused one stays kept and listed, and is never used. There is no retry, timer or
background work: a failed or uncertain attempt stays visible, a new one needs a new approval, and a reply that fails
the safeguards is never kept, so it cannot replace or hide valid data. GET routes only read.

Earlier versions. Plans are versioned, and PLAN_VERSION 0.2 names this source, so an approval of an earlier plan (for
the Data Download Program's two-series CSV) cannot authorize a request here. Earlier CSV retrievals and their attempts
are still read, unchanged.

Validation of a kept package that has no record for the current parser version (validate_packages) is local work under
the same write lock, started only by the operator's command; it fetches nothing.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import httpx

from . import event_context, event_intake, market_context, market_package, market_store
from .market_calendar import expected_sessions
from .market_context import ContextRefused
from .store import canonical

PLAN_VERSION = "market-retrieval-plan-0.2"  # 0.2: the release package replaces the two-series CSV.
PAGE_VERSION = "event-market-context-page-0.2"  # 0.2: kept packages listed.
LIST_VERSION = "event-market-context-list-0.2"
RESULT_VERSION = "market-retrieval-result-0.2"
USER_AGENT = "SecondOrder/0.1 (local research tool; market data requested only on an explicit approved request)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
MAX_EVENTS = 20
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
DEADLINE_SECONDS = 600
MAX_EXCERPT = 4096  # The most read of an error reply's body, kept as an untrusted diagnostic excerpt.
MAX_BODY = 4096
SOURCE = {
    "id": market_package.SOURCE_ID,
    "label": "Federal Reserve Board, H.15 Selected Interest Rates: the release's complete XML data package "
             "(FRB_h15_xml.zip), from which the 2-year and 10-year Treasury constant-maturity series are read",
    "publisher": market_context.SOURCE["publisher"],
    "series": [{"id": series["id"], "label": series["label"]} for series in market_context.SERIES.values()],
    "address": f"{market_package.PACKAGE_URL}, fixed: nothing in it comes from the plan, a request or a user",
    "download": ("One approved request downloads the Board's complete H.15 data package: every series of the release "
                 "(daily, weekly, monthly and annual, current and discontinued) over its full history, as published "
                 "when retrieved. It is not limited to the two series or to the missing dates. The package retained on "
                 "10 October 2026 was 4,285,147 bytes, about 71 MB of XML once decompressed; a reply over 200 MB is "
                 "refused. Only the two series are read from it, and it is kept privately so that later selections "
                 "reuse it without another download."),
    "key": "None: the Board's public website needs no key or account",
    "charge": "None: the download is free",
    "terms": market_context.TERMS,
    "availability": {
        "checked_on": "2026-10-09",
        "statement": ("On 16 July 2026 the Board announced that it will remove the Data Download Program's \"Build "
                      "Your Package\" option the week of 9 November 2026, and later its preformatted packages, before "
                      "retiring the program, and directed users to FRED or to the XML file on each release page. New "
                      "requests here use that release XML file. Earlier two-series CSV retrievals made with Build Your "
                      "Package are still read, unchanged. If the package's address stops working, a request fails "
                      "and is shown as failed; nothing switches to another source."),
        "urls": ["https://www.federalreserve.gov/data/data-download-fred-information.htm",
                 "https://www.federalreserve.gov/releases/h15/"],
    },
    "known_behaviour": ("The package's structure entries (H15_struct.xml and frb_common.xsd) begin with a DOCTYPE "
                        "declaration. They are never parsed or used: only the data entry (H15_data.xml) is read, with "
                        "DTDs, entities and external resources refused. If the data entry itself declared a DOCTYPE, "
                        "the package would be kept but not accepted, and not used."),
    "vintage_note": ("No vintage was requested, and the release package offers none: it holds the values as currently "
                     "published. These are the Board's values when retrieved, which may differ from those available on "
                     "the publication date; whether any of them was revised is not known from this package."),
}


class FetchFailed(Exception):
    def __init__(self, message: str, status: int | None = None, replied: bool = False, content_type: str | None = None,
                 excerpt: dict | None = None, received: int = 0):
        super().__init__(message)
        self.status, self.replied, self.content_type, self.excerpt, self.received = (status, replied, content_type,
                                                                                     excerpt, received)


@dataclass(frozen=True)
class PackageReply:
    status: int
    http_version: str
    headers: dict  # Every response header except Set-Cookie, whose values are never kept.
    set_cookie: dict
    request_headers: dict
    bytes: int
    sha256: str


def _kept_headers(response: httpx.Response) -> tuple[dict, dict]:
    kept, cookies = {}, 0
    for name, value in response.headers.multi_items():
        name = name.lower()
        if name == "set-cookie":
            cookies += 1
            continue
        kept[name] = f"{kept[name]}, {value}" if name in kept else value
    return kept, {"present": cookies > 0, "count": cookies, "values_stored": False}


class ReleaseFetcher:
    """Downloads the Board's H.15 release package once: the fixed address only, the approved headers, no cookie, no
    redirect, no content encoding, raw bytes streamed to a file within the size and time limits.

    ``transport`` lets tests and the test server install a simulated network, and ``label`` says on every record
    which network answered. Both are chosen when the server starts, never through the API."""

    def __init__(self, transport: httpx.BaseTransport | None = None,
                 label: str = "network: the Board's server over HTTPS"):
        self.transport, self.label = transport, label

    def fetch(self, url: str, target: Path) -> PackageReply:
        if url != market_package.PACKAGE_URL:
            raise FetchFailed("Only the Board's H.15 release package can be requested")
        with httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0), timeout=TIMEOUT,
                          follow_redirects=False, trust_env=False) as client:
            request = client.build_request("GET", url, headers=REQUEST_HEADERS)
            sent = dict(request.headers.items())
            if "cookie" in sent or len(client.cookies):
                raise FetchFailed("The request would carry a cookie, so it was not sent")
            try:
                response = client.send(request, stream=True)
            except httpx.TimeoutException:
                raise FetchFailed("The Board's server did not answer in time; whether it received the request is not "
                                  "known") from None
            except httpx.HTTPError as exc:
                raise FetchFailed(f"The request failed ({type(exc).__name__}); no reply was received") from None
            try:
                return self._read(response, target, sent)
            except httpx.TimeoutException:
                raise FetchFailed("The reply stopped arriving in time; nothing of it was kept", response.status_code,
                                  True) from None
            except httpx.HTTPError as exc:
                raise FetchFailed(f"The reply broke off ({type(exc).__name__}); nothing of it was kept",
                                  response.status_code, True) from None
            finally:
                response.close()

    @staticmethod
    def _read(response: httpx.Response, target: Path, sent: dict) -> PackageReply:
        status, deadline = response.status_code, time.monotonic() + DEADLINE_SECONDS
        headers, cookies = _kept_headers(response)
        content_type = headers.get("content-type")
        if response.is_redirect:
            raise FetchFailed(f"HTTP {status}: the Board's server redirects; redirects are not followed", status, True,
                              content_type)
        if status != 200:
            excerpt, complete = b"", True
            for chunk in response.iter_raw(1024):
                excerpt += chunk
                if len(excerpt) >= MAX_EXCERPT or time.monotonic() > deadline:
                    complete = False  # More may follow; it is not read.
                    break
            excerpt = excerpt[:MAX_EXCERPT]
            raise FetchFailed(f"HTTP {status} from the Board's server", status, True, content_type, {
                "untrusted": True, "bytes": len(excerpt), "complete": complete,
                "text": excerpt.decode("utf-8", errors="replace"),
                "note": "Raw reply bytes, not decoded, kept for diagnosis only; nothing in them was followed."},
                len(excerpt))
        encoding = headers.get("content-encoding")
        if encoding not in (None, "identity"):
            raise FetchFailed(f"The reply is {encoding}-encoded although identity was requested; it was not read or "
                              "decoded", status, True, content_type)
        media = (content_type or "").split(";")[0].strip().lower()
        if media not in market_package.ZIP_TYPES:
            what = "a web page" if media == "text/html" else (content_type or "of no stated type")
            raise FetchFailed(f"The reply was {what}, not the ZIP package; it was not read", status, True, content_type)
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > market_package.MAX_TRANSFER:
            raise FetchFailed(f"The reply declares {declared} bytes; the limit is {market_package.MAX_TRANSFER}",
                              status, True, content_type)
        digest, size = hashlib.sha256(), 0
        with target.open("xb") as handle:
            for chunk in response.iter_raw(1024 * 1024):
                size += len(chunk)
                if size > market_package.MAX_TRANSFER:
                    raise FetchFailed(f"The reply exceeded {market_package.MAX_TRANSFER} bytes and was not read "
                                      "further", status, True, content_type, received=size)
                if time.monotonic() > deadline:
                    raise FetchFailed(f"The reply took longer than {DEADLINE_SECONDS} seconds", status, True,
                                      content_type, received=size)
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if declared.isdigit() and int(declared) != size:
            raise FetchFailed(f"The reply declared {declared} bytes and {size} arrived", status, True, content_type,
                              received=size)
        return PackageReply(status, response.http_version, headers, cookies, sent, size, digest.hexdigest())


def now() -> datetime:
    return datetime.now(timezone.utc)


def retrieval_status(fetcher: ReleaseFetcher | None) -> dict:
    if fetcher is None:
        return {"enabled": False, "detail": ("This server was started without market retrieval, so it sends no "
                                             "request. Start it with: python -m second_order serve "
                                             "--enable-market-retrieval")}
    return {"enabled": True, "detail": f"An approved request is sent through: {fetcher.label}."}


def _events(keys: list[str], store: Path, inbox: Path, intake: Path) -> list[dict]:
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_EVENTS or len(set(keys)) != len(keys) or \
            not all(isinstance(key, str) for key in keys):
        raise ContextRefused(422, f"Name between 1 and {MAX_EVENTS} different events")
    events = []
    for key in sorted(keys):
        kind, event_id = event_context.parse_key(key)
        event = event_context.definition(kind, event_id, store, inbox, intake)
        if not event["supported"]:
            raise ContextRefused(422, event["outside"] or "This event is outside this first slice")
        if event["problem"] or event["context"] is None:
            raise ContextRefused(409, f"{event['title'] or key} has no confirmed context date yet; confirm it first")
        events.append(event)
    return events


def _ranges(days: list[date]) -> list[dict]:
    ranges = []
    for day in days:
        if ranges and (day - date.fromisoformat(ranges[-1]["end"])).days <= 4:  # A weekend or holiday apart.
            ranges[-1]["end"] = day.isoformat()
            ranges[-1]["sessions"] += 1
        else:
            ranges.append({"start": day.isoformat(), "end": day.isoformat(), "sessions": 1})
    return ranges


def plan(events: list[dict], found: list, as_of: date, sessions=expected_sessions) -> dict:
    """The missing work of these events and the one request (or none) that covers it. Reads nothing new."""
    need, future, windows = {}, set(), []
    for event in events:
        window = event["context"]["window"]
        start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
        windows.append({"key": event["key"], "title": event["title"], "context_date": event["context"]["date"],
                        "start": window["start"], "end": window["end"]})
        for day in sessions(start, end):
            if not start <= day <= end:
                continue
            if day >= as_of:
                future.add(day)
            else:
                need.setdefault(day, set()).add(event["key"])
    held = {day for day in need if any(retrieval.states(day) for retrieval in found)}
    missing = sorted(set(need) - held)
    reuse = [{"retrieval": retrieval.id, "origin_label": retrieval.provenance["origin_label"],
              "requested_at": retrieval.provenance["requested_at"],
              "sessions": sum(1 for day in held if retrieval.states(day))}
             for retrieval in found if any(retrieval.states(day) for day in held)]
    request = None
    if missing:  # The whole release, whatever is missing: there is no smaller download of this source.
        request = {"url": market_package.PACKAGE_URL, "download": "full_release_package",
                   "missing_sessions": len(missing), "missing_from": missing[0].isoformat(),
                   "missing_to": missing[-1].isoformat()}
    identity = {"plan_version": PLAN_VERSION, "source": SOURCE["id"],
                "events": [{"key": item["key"], "context_date": item["context_date"]} for item in windows],
                "missing": [day.isoformat() for day in missing], "url": request["url"] if request else None}
    plan_sha = hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()
    return {"plan_version": PLAN_VERSION, "plan_sha256": plan_sha, "as_of": as_of.isoformat(), "source": SOURCE,
            "events": windows, "needed_sessions": len(need), "held_sessions": len(held),
            "missing_sessions": [day.isoformat() for day in missing], "missing_ranges": _ranges(missing),
            "future_sessions": sorted(day.isoformat() for day in future), "reuse": reuse,
            "requests": 1 if request else 0, "request": request}


def _attempts_for(store: Path, keys: set[str]) -> list[dict]:
    return [attempt for attempt in market_store.read_attempts(store)
            if keys & set((attempt["started"] or {}).get("events", []))]


def _not_used(packages: list[dict]) -> list[dict]:
    """Kept packages that are not used: not yet validated, or refused. A plan names them, so that a package already
    held is validated locally rather than downloaded again unnoticed."""
    return [package for package in packages if package["status"] != "accepted"]


def plan_view(keys: list[str], store: Path, bundle: Path | None, inbox: Path, intake: Path,
              fetcher: ReleaseFetcher | None, clock=now) -> dict:
    events = _events(keys, store, inbox, intake)
    found, problems, packages = market_store.local_data(store, bundle)
    result = plan(events, found, event_context.today(clock))
    return {**result, "next_attempt": len(market_store.numbers_used(store, result["plan_sha256"])) + 1,
            "attempts": _attempts_for(store, set(keys)), "retrieval": retrieval_status(fetcher),
            "store_problems": problems, "packages_not_used": _not_used(packages)}


def _approval(body: bytes) -> dict:
    try:
        approval = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        approval = None
    if not isinstance(approval, dict) or set(approval) != {"plan_sha256", "events", "attempt"} or \
            not isinstance(approval["plan_sha256"], str) or not market_store.PLAN_SHA.fullmatch(approval["plan_sha256"]) \
            or type(approval["attempt"]) is not int or approval["attempt"] < 1:
        raise ContextRefused(422, "An approval names exactly the plan's SHA-256, its events and the attempt number")
    return approval


def dispatch(body: bytes, store: Path, bundle: Path | None, inbox: Path, intake: Path, fetcher: ReleaseFetcher | None,
             clock=now) -> dict:
    """Send one approved request, at most once per attempt number, after checking the plan again under the lock."""
    approval = _approval(body)
    if fetcher is None:
        raise ContextRefused(409, retrieval_status(None)["detail"])
    events = _events(approval["events"], store, inbox, intake)
    store.mkdir(parents=True, exist_ok=True)
    with market_store.write_lock(store):
        found, _ = market_store.retrievals(store, bundle)  # The local data immediately before sending.
        current = plan(events, found, event_context.today(clock))
        if current["plan_sha256"] != approval["plan_sha256"]:
            raise ContextRefused(409, "The local data or the plan changed since the preview, so nothing was requested; "
                                      "preview the retrieval again")
        if current["requests"] == 0:
            raise ContextRefused(409, "Nothing is missing: every session these events need before today is already "
                                      "held, so nothing was requested")
        used = market_store.numbers_used(store, current["plan_sha256"])
        if approval["attempt"] != len(used) + 1:
            raise ContextRefused(409, f"Attempt {approval['attempt']} of this work was already started; nothing was "
                                      "requested again. Read its outcome on the page; another attempt needs its own "
                                      "approval")
        request = current["request"]
        number, plan_sha = approval["attempt"], current["plan_sha256"]
        started_at = clock()
        client = {"user_agent": USER_AGENT, "transport": fetcher.label, "request_headers": REQUEST_HEADERS}
        try:
            market_store.write_exclusive(market_store.started_path(store, plan_sha, number), {
                "attempt_version": market_store.ATTEMPT_VERSION, "plan_sha256": plan_sha, "number": number,
                "events": [event["key"] for event in events], "source": SOURCE["id"], "url": request["url"],
                "download": request["download"], "missing_sessions": request["missing_sessions"],
                "missing_from": request["missing_from"], "missing_to": request["missing_to"],
                "started_at": _precise(started_at), "client": client, "note": "Recorded before the request was sent."})
        except FileExistsError:
            raise ContextRefused(409, f"Attempt {number} of this work was already started; nothing was requested "
                                      "again") from None
        approval = {"plan_sha256": plan_sha, "attempt": number, "events": [event["key"] for event in events]}
        method = (f"Approved in this app: attempt {number} of plan {plan_sha}, sent by its market retrieval (httpx; TLS "
                  "verified, no redirect, no retry, no cookie).")
        outcome = _send(fetcher, store, plan_sha, number, approval, method, started_at, client, clock)
        market_store.write_exclusive(market_store.outcome_path(store, plan_sha, number), outcome)
    return {"result_version": RESULT_VERSION, "plan_sha256": plan_sha, "attempt": number,
            "outcome": outcome["outcome"], "detail": outcome["detail"], "package_id": outcome["package_id"],
            "validation": outcome["validation"], "provider_called": True, "retries": 0}


def _precise(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _send(fetcher: ReleaseFetcher, store: Path, plan_sha: str, number: int, approval: dict, method: str,
          started_at: datetime, client: dict, clock) -> dict:
    """The one request, and what became of it. Only a reply whose archive passes the safeguards is kept, and only a
    kept package whose data is accepted is used. ``approval`` and ``method`` say in the kept package's record which
    approved work sent it (an event plan here, or a lifecycle plan: see outcome_retrieval)."""
    outcome = {"attempt_version": market_store.ATTEMPT_VERSION, "plan_sha256": plan_sha, "number": number,
               "outcome": "no_reply", "detail": None, "http_status": None, "content_type": None, "bytes": None,
               "sha256": None, "response_date": None, "set_cookie": None, "error_excerpt": None,
               "requested_at": _precise(started_at), "received_at": None, "finished_at": None, "package_id": None,
               "validation": None, "retries": 0}
    staging = market_store.package_staging(store)
    try:
        try:
            reply = fetcher.fetch(market_package.PACKAGE_URL, staging / market_package.PACKAGE_FILE)
        except FetchFailed as exc:
            outcome.update(outcome="refused_reply" if exc.replied else "no_reply", detail=f"{exc}.",
                           http_status=exc.status, content_type=exc.content_type, error_excerpt=exc.excerpt,
                           bytes=exc.received if exc.replied else None, finished_at=_precise(clock()))
            return outcome
        received = clock()
        outcome.update(http_status=reply.status, content_type=reply.headers.get("content-type"), bytes=reply.bytes,
                       sha256=reply.sha256, response_date=reply.headers.get("date"), set_cookie=reply.set_cookie,
                       received_at=_precise(received))
        package_id = f"p{started_at.astimezone(timezone.utc):%Y%m%dT%H%M%S%f}Z-{reply.sha256[:12]}"
        record = {
            "package_record_version": market_package.PACKAGE_RECORD_VERSION, "package_id": package_id,
            "source": SOURCE["id"], "url": market_package.PACKAGE_URL,
            "acquisition_method": method, "approval": approval,
            "requested_at": outcome["requested_at"], "received_at": outcome["received_at"],
            "http_status": reply.status, "http_version": reply.http_version, "response_headers": reply.headers,
            "set_cookie": reply.set_cookie,
            "headers": {name: reply.headers.get(name) for name in ("content-type", "content-length",
                                                                   "content-encoding", "date", "last-modified",
                                                                   "etag")},
            "redirect_followed": False, "bytes": reply.bytes, "sha256": reply.sha256,
            "client": {**client, "library": f"httpx {httpx.__version__}", "retries": 0, "follow_redirects": False,
                       "cookies_sent": False, "request_headers_sent": reply.request_headers},
            "archive": None, "marker_findings": None, "validation_status": "acquired_unvalidated",
            "note": ("Acquired but unvalidated: the Board's release as published when retrieved, not a historical "
                     "vintage. Its validation is recorded separately; only an accepted package is used.")}
        try:
            entries, findings = market_package.check_archive(staging / market_package.PACKAGE_FILE)
            record.update(archive={"entries": entries, "entry_count": len(entries), "extracted_to_disk": False},
                          marker_findings=findings)
            market_package.check_acquisition(record, package_id, reply.bytes, reply.sha256)
        except market_package.ArchiveRefused as exc:
            outcome.update(outcome="refused_reply", finished_at=_precise(clock()),
                           detail=f"The reply was not kept: {exc} ({exc.outcome}).")
            return outcome
        except market_package.RecordRefused as exc:
            outcome.update(outcome="refused_reply", finished_at=_precise(clock()),
                           detail=f"The reply was not kept: {exc}.")
            return outcome
        try:
            market_store.write_package(store, staging, record)
        except (OSError, market_store.StoreRefused) as exc:
            outcome.update(outcome="not_saved", finished_at=_precise(clock()),
                           detail=f"The package passed the safeguards but could not be kept ({type(exc).__name__}).")
            return outcome
        folder = store / market_store.PACKAGES / package_id
        outcome["package_id"] = package_id
        try:
            validation = market_package.validate(folder / market_package.PACKAGE_FILE, package_id, reply.sha256,
                                                 clock(), market_store.new_york_day(started_at))
            market_store.write_validation(store, validation)
        except OSError as exc:
            outcome.update(outcome="retained_not_accepted", finished_at=_precise(clock()), detail=(
                f"The package was kept privately, but its validation could not be recorded ({type(exc).__name__}). "
                "It is not used until a validation accepts it."))
            return outcome
        outcome.update(validation=validation["status"], finished_at=_precise(clock()))
        if validation["status"] == "accepted":
            outcome.update(outcome="saved", detail=(
                "The package passed the safeguards and was kept, and its two series were read and accepted "
                f"({validation['coverage']['first']} to {validation['coverage']['last']}); nothing kept earlier was "
                "changed."))
        else:
            outcome.update(outcome="retained_not_accepted", detail=(
                f"The package was kept privately, but its data was not accepted: {validation['detail']}. It is not "
                "used."))
        return outcome
    finally:
        market_store.discard(staging)


# ---------------------------------------------------------------- pages (reads only)

def _summary(event: dict, found: list, as_of: date) -> dict:
    """What the list shows for one event: its date and how much of its window is held."""
    row = {key: event[key] for key in ("key", "kind", "id", "title", "link", "family", "family_label", "supported",
                                       "outside", "problem")}
    row["context"] = event["context"]
    row["suggestion"] = event["suggestion"]
    if event["supported"] and event["context"] and not event["problem"]:
        view = event_context.build_view(event, found, [], as_of)
        work = plan([event], found, as_of)
        row.update(complete=view["complete"], missing_sessions=len(work["missing_sessions"]),
                   future_sessions=len(work["future_sessions"]), conflicts=len(view["conflicts"]),
                   changes=[{key: change[key] for key in ("series", "short_label", "horizon", "change_bp", "unavailable")}
                            for change in view["endpoints"]["changes"]])
    return row


def _saved_events(store: Path, inbox: Path, intake: Path) -> list[dict]:
    events = []
    for key in event_context.saved_inbox_keys(store):
        try:
            kind, event_id = event_context.parse_key(key)
            events.append(event_context.definition(kind, event_id, store, inbox, intake))
        except ContextRefused as exc:
            events.append({"key": key, "kind": "inbox", "id": None, "title": None, "link": None, "family": None,
                           "family_label": None, "supported": False, "outside": None, "problem": str(exc),
                           "context": None, "suggestion": None})
    for row in event_intake.listing(intake) if intake.is_dir() else []:
        if row["state"].startswith("verified"):
            try:
                events.append(event_context.definition("capture", row["capture_id"], store, inbox, intake))
            except ContextRefused:
                continue  # A capture that stopped verifying is listed by the Tracker, with its reason.
    return events


def listing(store: Path, bundle: Path | None, inbox: Path, intake: Path, fetcher: ReleaseFetcher | None,
            clock=now) -> dict:
    """Saved Inbox contexts and saved captures, the local retrievals, every kept package and every attempt. Reads
    only."""
    as_of = event_context.today(clock)
    found, problems, packages = market_store.local_data(store, bundle)
    rows = [_summary(event, found, as_of) for event in _saved_events(store, inbox, intake)]
    return {"list_version": LIST_VERSION, "as_of": as_of.isoformat(), "retrieval": retrieval_status(fetcher),
            "events": [row for row in rows if row["supported"] or row["problem"]],
            "outside": [row for row in rows if not row["supported"] and not row["problem"]],
            "retrievals": [retrieval.provenance for retrieval in found], "packages": packages,
            "store_problems": problems,
            "attempts": market_store.read_attempts(store), "source": SOURCE, "outside_note": event_context.OUTSIDE_NOTE}


def event_page(kind: str, event_id: str, store: Path, bundle: Path | None, inbox: Path, intake: Path,
               fetcher: ReleaseFetcher | None, clock=now) -> dict:
    """One event: its definition, its view and plan when it has a context date, its attempts, and the other saved
    events that still miss data (they can share one request). Reads only."""
    event = event_context.definition(kind, event_id, store, inbox, intake)
    as_of = event_context.today(clock)
    found, problems, packages = market_store.local_data(store, bundle)
    view = work = None
    if event["supported"] and event["context"] and not event["problem"]:
        view = event_context.build_view(event, found, problems, as_of)
        work = plan([event], found, as_of)
        work = {**work, "next_attempt": len(market_store.numbers_used(store, work["plan_sha256"])) + 1}
    others = []
    if work is not None:
        for other in _saved_events(store, inbox, intake):
            if other["key"] != event["key"] and other["supported"] and other["context"] and not other["problem"]:
                missing = plan([other], found, as_of)["missing_sessions"]
                if missing:
                    others.append({"key": other["key"], "title": other["title"], "family_label": other["family_label"],
                                   "context_date": other["context"]["date"], "missing_sessions": len(missing)})
    return {"page_version": PAGE_VERSION, "as_of": as_of.isoformat(), "event": event, "view": view, "plan": work,
            "others": others, "attempts": _attempts_for(store, {event["key"]}), "retrieval": retrieval_status(fetcher),
            "store_problems": problems, "packages_not_used": _not_used(packages),
            "convention": event_context.CONVENTION, "rule": event_context.RULE}


# ---------------------------------------------------------------- local validation (the operator's command)

def validate_packages(store: Path, clock=now) -> list[dict]:
    """Validates every kept package that has no validation record for the current parser version: its archive is
    checked again and its data entry parsed under the protected-parser policy, and the result is recorded once as
    accepted or refused. Local work only, under the store's write lock: nothing is fetched, and no package, record or
    earlier validation is changed. A package whose acquisition record does not verify is reported and left alone."""
    folder = store / market_store.PACKAGES
    if not folder.is_dir():
        return []
    results = []
    with market_store.write_lock(store):
        for path in sorted(folder.iterdir()):
            if path.name.startswith(".") or not path.is_dir():
                continue
            try:
                summary, _ = market_store.package_state(path)
            except market_store.StoreRefused as exc:
                results.append({"package": path.name, "result": "not_verified", "detail": str(exc), "coverage": None})
                continue
            if summary["status"] != "acquired_unvalidated":
                results.append({"package": path.name, "result": f"already_{summary['status']}",
                                "detail": summary["detail"], "coverage": summary["coverage"]})
                continue
            requested_on = market_store.new_york_day(market_package.moment(summary["requested_at"], "requested_at"))
            record = market_package.validate(path / market_package.PACKAGE_FILE, path.name, summary["sha256"],
                                             clock(), requested_on)
            market_store.write_validation(store, record)
            results.append({"package": path.name, "result": record["status"], "detail": record["detail"],
                            "coverage": record["coverage"]})
    return results

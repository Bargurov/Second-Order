"""SYNTHETIC Board downloads and release packages, a counting fake of the Board's server, and event fixtures for the
market-context tests and the browser launcher. Not a test module.

Every value here is invented: a plain pattern derived from the date (synthetic_pair), the same in every reply, so
overlapping retrievals agree unless a test revises a value on purpose. The release packages follow the format of the
Board's H.15 XML package as inspected in October 2026 (SDMX-ML MessageGroup, CRLF line ends, an H15 dataset with other
series beside the two, a discontinued dataset, and structure entries that begin with a DOCTYPE declaration), with
invented values and a header that says so. Nothing reaches the network: the fake answers through an
httpx.MockTransport and records each address and its request headers, so tests can count requests exactly.
"""
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import io
from pathlib import Path
import zipfile

import httpx

from second_order import event_inbox, event_intake, market_context, market_package, market_store
from second_order.market_calendar import expected_sessions
from second_order.market_retrieval import ReleaseFetcher
from test_event_inbox import (CONTACT, CPI, EIA, EMPSIT, FED, WTO, Network, atom, atom_entry, eia_item, eia_rss, rss,
                              rss_item, wto_item, wto_rss)

SYNTHETIC_LABEL = ("SYNTHETIC: an in-process fake of the Board's server (tests/market_fakes.py) answered with a release "
                   "package of invented values; nothing reached the Board")
PACKAGE_START = date(2026, 1, 2)  # The fake's packages begin here, after every committed case-library window.
MODEL = "claude-sonnet-5-5"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, moment: datetime):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta) -> None:
        self.moment += timedelta(**delta)


def synthetic_pair(day: date) -> tuple[str, str]:
    """Invented 2-year and 10-year values for a date: a pattern, not an H.15 observation."""
    number = day.toordinal()
    return f"{3 + (number % 50) / 100:.2f}", f"{4 + (number % 40) / 100:.2f}"


def board_csv(start: date, end: date, overrides: dict | None = None) -> bytes:
    """Rows in the Board's CSV format: one per weekday from start to end, ND on SIFMA holidays, as the Board's
    download shows them. ``overrides`` maps a date to (2-year, 10-year) text, or to None for no row."""
    series = list(market_context.SERIES.values())
    header = [["Series Description", *(s["description"] for s in series)], ["Unit:", *(s["unit"] for s in series)],
              ["Multiplier:", *(s["multiplier"] for s in series)], ["Currency:", *(s["currency"] for s in series)],
              ["Unique Identifier: ", *(s["unique_identifier"] for s in series)],
              ["Time Period", *(s["id"] for s in series)]]
    sessions = expected_sessions(start, end)
    lines, day = [",".join(f'"{cell}"' for cell in cells) for cells in header], start
    while day <= end:
        if day.weekday() < 5:
            pair = (overrides or {}).get(day, ("ND", "ND") if day not in sessions else synthetic_pair(day))
            if pair is not None:
                lines.append(f"{day.isoformat()},{pair[0]},{pair[1]}")
        day += timedelta(days=1)
    return "\r\n".join(lines).encode("ascii")


MESSAGE_OPEN = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\r\n'
    f'<message:MessageGroup xmlns:message="{market_package.MESSAGE}" xmlns:common="{market_package.COMMON}" '
    f'xmlns:frb="{market_package.FRB}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    f'xsi:schemaLocation="{market_package.MESSAGE} SDMXMessage.xsd {market_package.FRB} frb_common.xsd">\r\n'
    f'  <message:Header xmlns:message="{market_package.MESSAGE}">\r\n'
    '    <message:ID>H15</message:ID>\r\n    <message:Test>false</message:Test>\r\n'
    '    <message:Name>H.15 Selected Interest Rates</message:Name>\r\n'
    '    <message:Prepared>{prepared}</message:Prepared>\r\n'
    '    <message:Sender id="FRB">\r\n      <message:Name>Federal Reserve Board</message:Name>\r\n'
    '    </message:Sender>\r\n'
    "    <message:Source>SYNTHETIC package (tests/market_fakes.py): invented values in the Board's format."
    "</message:Source>\r\n"
    '  </message:Header>\r\n')
DATASET_OPEN = (f'  <frb:DataSet id="H15" xmlns:kf="{market_package.DATASET}" '
                f'xsi:schemaLocation="{market_package.DATASET} H15_H15.xsd">\r\n')
DISCONTINUED_OPEN = ('  <frb:DataSet id="discontinued" '
                     'xmlns:kf="http://www.federalreserve.gov/structure/compact/H15_discontinued" '
                     'xsi:schemaLocation="http://www.federalreserve.gov/structure/compact/H15_discontinued '
                     'H15_discontinued.xsd">\r\n')
STRUCTURE = (b'<?xml version="1.0"?>\n<!DOCTYPE message:Structure>\n<message:Structure '
             b'xmlns:message="http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message"><!-- SYNTHETIC -->'
             b'</message:Structure>\n')
COMMON_XSD = (b'<?xml version="1.0"?>\n<!DOCTYPE xs:schema>\n<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
              b'<!-- SYNTHETIC --></xs:schema>\n')
DATASET_XSD = (b'<?xml version="1.0"?>\n<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
               b'targetNamespace="http://www.federalreserve.gov/structure/compact/H15_H15"><!-- SYNTHETIC -->'
               b'</xs:schema>\n')
ZIP_ENTRY_TIME = (2026, 1, 2, 0, 0, 0)  # Every package entry's time: fixed, so equal data makes equal bytes.


def series_xml(name: str, rows, attributes: dict | None = None, short: str | None = None, long: str | None = None,
               tag: str = "kf:Series") -> str:
    """One series in the data entry's format; ``rows`` are (ISO date, status, value) triples."""
    attributes = attributes or {"CURRENCY": "NA", "FREQ": "9", "INSTRUMENT": "FF", "MATURITY": "O",
                                "SERIES_NAME": name, "UNIT": "Percent:_Per_Year", "UNIT_MULT": "1"}
    head = " ".join(f'{key}="{value}"' for key, value in attributes.items())
    lines = [f"    <{tag} {head}>", "      <frb:Annotations>"]
    for kind, text in (("Short Description", short or name), ("Long Description", long or name)):
        lines += ["        <common:Annotation>", f"          <common:AnnotationType>{kind}</common:AnnotationType>",
                  f"          <common:AnnotationText>{text}</common:AnnotationText>", "        </common:Annotation>"]
    lines.append("      </frb:Annotations>")
    lines += [f'      <frb:Obs OBS_STATUS="{status}" OBS_VALUE="{value}" TIME_PERIOD="{period}" />'
              for period, status, value in rows]
    lines.append(f"    </{tag}>")
    return "\r\n".join(lines) + "\r\n"


def target_xml(series_id: str, rows, attributes: dict | None = None, short: str | None = None,
               long: str | None = None, tag: str = "kf:Series") -> str:
    """A target series with the Board's attributes and descriptions (two spaces, as in the XML), or with changes."""
    maturity = int(series_id[8:10])
    merged = dict(sorted({**market_package.EXPECTED[series_id], **(attributes or {})}.items()))
    return series_xml(series_id, rows, merged, short or f"{maturity}-year Treasury constant maturity",
                      long or f"Market yield on U.S. Treasury securities at {maturity}-year  constant maturity, "
                              "quoted on investment basis", tag)


def release_rows(start: date, end: date, overrides: dict | None = None, revise: bool = False) -> dict:
    """Both series' (ISO date, status, value) rows, one per weekday from start to end, ND on SIFMA holidays, as the
    Board's package lists them. ``overrides`` maps a date to (2-year, 10-year) text ("ND" for no value, None for no
    observation of that series) or to None (no observation of either)."""
    sessions, rows, day = expected_sessions(start, end), {series_id: [] for series_id in market_context.SERIES}, start
    while day <= end:
        if day.weekday() < 5:
            pair = (overrides or {}).get(day, ("ND", "ND") if day not in sessions else synthetic_pair(day))
            for series_id, text in zip(market_context.SERIES, pair or (None, None)):
                if text is None:
                    continue
                if revise and text != "ND":
                    text = f"{float(text) + 1:.2f}"
                rows[series_id].append((day.isoformat(), "ND", "-9999") if text == "ND" else
                                       (day.isoformat(), "A", text))
        day += timedelta(days=1)
    return rows


def release_data(start: date, end: date, overrides: dict | None = None, revise: bool = False,
                 prepared: str = "2026-10-08T15:40:02", rows: dict | None = None) -> bytes:
    """The data entry: an H15 dataset with a federal funds series, both targets and a weekly decoy of the 2-year
    series, then a discontinued dataset. ``rows`` replaces the targets' rows."""
    rows = rows or release_rows(start, end, overrides, revise)
    funds = [(period, "A", "4.33") for period, status, _ in rows["RIFLGFCY02_N.B"][:3] if status == "A"]
    weekly = dict(market_package.EXPECTED["RIFLGFCY02_N.B"], FREQ="21", SERIES_NAME="RIFLGFCY02_N.WF")
    text = (MESSAGE_OPEN.format(prepared=prepared) + DATASET_OPEN + series_xml("RIFSPFF_N.B", funds) +
            "".join(target_xml(series_id, series_rows) for series_id, series_rows in rows.items()) +
            series_xml("RIFLGFCY02_N.WF", [("2026-01-09", "A", "3.50")], weekly) + "  </frb:DataSet>\r\n" +
            DISCONTINUED_OPEN + series_xml("H0.RIFSPDCNSM01_N.B", [("2000-01-03", "A", "5.80")]) +
            "  </frb:DataSet>\r\n</message:MessageGroup>")
    return text.encode("utf-8")


def release_zip(data: bytes, entries: dict | None = None) -> bytes:
    """A package in the Board's layout: the data entry and four structure entries, two of which begin with a DOCTYPE
    declaration. ``entries`` adds or replaces entries (None removes one). Entries carry a fixed time, not the clock's,
    so the same data always makes the same bytes."""
    files = {"H15_discontinued.xsd": DATASET_XSD, "H15_H15.xsd": DATASET_XSD, "H15_data.xml": data,
             "H15_struct.xml": STRUCTURE, "frb_common.xsd": COMMON_XSD, **(entries or {})}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            if content is not None:
                info = zipfile.ZipInfo(name, date_time=ZIP_ENTRY_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16  # As writestr sets for a named file.
                info.create_system = 0  # zipfile takes it from the machine (3 off Windows); the fixtures hold 0.
                archive.writestr(info, content)
    return buffer.getvalue()


class Chunks(httpx.SyncByteStream):
    """A streamed body, as the network delivers one: never pre-read."""

    def __init__(self, data: bytes, size: int = 65536):
        self.data, self.size = data, size

    def __iter__(self):
        for start in range(0, len(self.data), self.size):
            yield self.data[start:start + self.size]


def package_reply(data: bytes, moment: datetime, extra: dict | None = None) -> httpx.Response:
    """A 200 reply with the package and the headers the Board's server sent (cookies SYNTHETIC)."""
    headers = [("content-type", "application/x-zip-compressed"), ("content-length", str(len(data))),
               ("date", format_datetime(moment.astimezone(timezone.utc), usegmt=True)),
               ("last-modified", "Thu, 08 Oct 2026 20:15:08 GMT"), ("etag", '"synthetic"'),
               ("set-cookie", "__synthetic_a=SYNTHETIC-COOKIE-VALUE-1; Path=/; HttpOnly"),
               ("set-cookie", "__synthetic_b=SYNTHETIC-COOKIE-VALUE-2; Path=/; HttpOnly")]
    for name, value in (extra or {}).items():
        headers = [(key, item) for key, item in headers if key != name] + ([(name, value)] if value is not None else [])
    return httpx.Response(200, headers=headers, stream=Chunks(data))


class FakeRelease:
    """Answers the Board's package address with a SYNTHETIC release package whose observations run from ``start`` to
    the day before the request (a day's value is not published before it ends). ``script`` queues other answers for
    the next requests: "html" (an empty web page with HTTP 200), an int status, "timeout", "revise" (every value one
    point higher), "gzip" (a gzip-encoded reply), or a callable(request) -> httpx.Response. ``before`` runs at each
    request, before it is answered. Every request's address and headers are recorded."""

    def __init__(self, clock, script=None, before=None, overrides: dict | None = None, start: date = PACKAGE_START):
        self.clock, self.script, self.before = clock, list(script or []), before
        self.overrides, self.start = overrides or {}, start
        self.calls: list[str] = []
        self.headers: list[dict] = []

    def package(self, revise: bool = False) -> bytes:
        last = self.clock().astimezone(market_context.NEW_YORK).date() - timedelta(days=1)
        return release_zip(release_data(self.start, last, self.overrides, revise))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        self.headers.append(dict(request.headers.items()))
        if self.before:
            self.before(request)
        action = self.script.pop(0) if self.script else "ok"
        moment = self.clock()
        if callable(action):
            return action(request)
        if action == "timeout":
            raise httpx.ReadTimeout("simulated: no reply arrived", request=request)
        if action == "html":
            return httpx.Response(200, stream=Chunks(b""), headers={
                "content-type": "text/html; charset=utf-8", "date": format_datetime(moment, usegmt=True)})
        if isinstance(action, int):
            return httpx.Response(action, stream=Chunks(b"<html>unavailable</html>" * 400), headers={
                "content-type": "text/html", "date": format_datetime(moment, usegmt=True)})
        if action == "gzip":
            return package_reply(b"\x1f\x8b compressed", moment, {"content-encoding": "gzip"})
        return package_reply(self.package(revise=action == "revise"), moment)

    def fetcher(self) -> ReleaseFetcher:
        return ReleaseFetcher(httpx.MockTransport(self), SYNTHETIC_LABEL)


def keep_package(store: Path, package: bytes, requested: datetime, approval_id: str = "synthetic-one-off") -> str:
    """A package kept directly, as an operator's one-off acquisition outside the app records one: acquired but
    unvalidated, labelled SYNTHETIC. Returns its ID."""
    digest = market_context.sha256(package)
    requested = requested.astimezone(timezone.utc)
    package_id = f"p{requested:%Y%m%dT%H%M%S%f}Z-{digest[:12]}"
    staging = market_store.package_staging(store)
    (staging / market_package.PACKAGE_FILE).write_bytes(package)
    entries, findings = market_package.check_archive(staging / market_package.PACKAGE_FILE)
    headers = {"content-type": "application/x-zip-compressed", "content-length": str(len(package)),
               "content-encoding": None, "date": format_datetime(requested, usegmt=True), "last-modified": None,
               "etag": None}
    market_store.write_package(store, staging, {
        "package_record_version": market_package.PACKAGE_RECORD_VERSION, "package_id": package_id,
        "source": market_package.SOURCE_ID, "url": market_package.PACKAGE_URL,
        "acquisition_method": "SYNTHETIC: written directly by the test, as an operator's one-off acquisition records it",
        "approval": {"approval_id": approval_id, "requests": 1}, "requested_at": requested.isoformat(timespec="microseconds"),
        "received_at": (requested + timedelta(seconds=1)).isoformat(timespec="microseconds"), "http_status": 200,
        "http_version": "HTTP/1.1", "response_headers": {key: value for key, value in headers.items() if value},
        "set_cookie": {"present": False, "count": 0, "values_stored": False}, "headers": headers,
        "redirect_followed": False, "bytes": len(package), "sha256": digest,
        "client": {"library": "SYNTHETIC", "transport": "SYNTHETIC: written directly by the test",
                   "request_headers_sent": {"user-agent": "SYNTHETIC test"}},
        "archive": {"entries": entries, "entry_count": len(entries), "extracted_to_disk": False},
        "marker_findings": findings, "validation_status": "acquired_unvalidated", "note": "SYNTHETIC"})
    return package_id


def inbox_feeds(fed: list[tuple[str, str]] = (), empsit: list[tuple[str, str]] = (),
                cpi: list[tuple[str, str]] = (), eia: list[tuple[str, str]] = (), wto: list[tuple[str, str]] = ()) -> dict:
    """SYNTHETIC feeds, one entry per (title, timestamp) pair: RFC 822 for the RSS feeds, RFC 3339 for BLS."""
    return {
        FED: [(200, rss([rss_item(n, title, f"https://www.federalreserve.gov/newsevents/pressreleases/monetary2026{n:04d}a.htm",
                                  pub=stamp) for n, (title, stamp) in enumerate(fed, start=1)]))],
        EMPSIT: [(200, atom([atom_entry(n, "empsit", title, published=stamp,
                                        link=f"https://www.bls.gov/news.release/archives/empsit_{n:02d}012026.htm")
                             for n, (title, stamp) in enumerate(empsit, start=1)]))],
        CPI: [(200, atom([atom_entry(n, "cpi", title, published=stamp,
                                     link=f"https://www.bls.gov/news.release/archives/cpi_{n:02d}012026.htm")
                          for n, (title, stamp) in enumerate(cpi, start=1)]))],
        EIA: [(200, eia_rss([eia_item(n, title, pub=stamp) for n, (title, stamp) in enumerate(eia, start=1)]))],
        WTO: [(200, wto_rss([wto_item(n, title, pub=stamp) for n, (title, stamp) in enumerate(wto, start=1)]))],
    }


def fill_inbox(inbox: Path, feeds: dict, clock) -> dict:
    """One refresh of the inbox cache from SYNTHETIC feeds; returns the inbox view."""
    event_inbox.refresh(inbox, Network(feeds).fetcher(CONTACT), clock)
    return event_inbox.inbox_view(inbox)


def item_id(view: dict, title: str) -> str:
    return next(item["id"] for item in view["items"] + view["retained"] if item["title"] == title)


def capture(intake: Path, headline: str, link: str, published_at: str, captured: datetime) -> str:
    """A saved Tracker capture with an operator-supplied publication time."""
    record = event_intake.capture_text(headline, link, published_at, "synthetic-story", "Synthetic source text.",
                                       MODEL, intake, lambda: captured)
    return record["capture_id"]

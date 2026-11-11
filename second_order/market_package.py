"""The Federal Reserve Board's H.15 release package (FRB_h15_xml.zip): checked, parsed and verified without trusting it.

The package is the release's complete data: every H.15 series over its full history, as SDMX-ML XML, with schema and
structure entries beside the data entry (H15_data.xml). This module only reads bytes it is given and builds records;
it never fetches anything, extracts anything to disk or writes (market_store writes; market_retrieval fetches).

Archive safeguards (check_archive), on the actual bytes: 1 to MAX_ENTRIES entries with unique, relative names (no
drive, absolute path, backslash, parent reference or control character), no symbolic link, no encryption, only stored
or deflated entries, at most MAX_ENTRY bytes per entry and MAX_TOTAL in all when decompressed, at most MAX_RATIO:1
expansion, and every entry's CRC. Each entry is also scanned for DOCTYPE or ENTITY byte patterns; a hit is recorded as a
bounded finding (entry, marker, offset, up to 200 bytes of untrusted context), not acted on: a byte pattern does not
show what the text is, and the parser, not the scan, is the protection.

Protected parsing (parse_data): only the data entry is parsed, as a stream through expat, with DOCTYPE, entity,
notation and unparsed-entity declarations refused by handler, parameter entities never parsed and every external
entity reference refused, so no DTD is read, no entity is expanded and no schema, DTD or other resource is fetched or
opened, local files included. Nothing is stripped or bypassed. The other entries are never parsed: the structure
entries (H15_struct.xml, frb_common.xsd) begin with a DOCTYPE declaration, which this policy refuses, and nothing here
needs them.

What is accepted. The data entry must be one SDMX MessageGroup whose header names the H15 release, with each of the two
series exactly once, in the H15 dataset, with exactly the expected attributes (EXPECTED: currency, frequency code,
instrument, maturity, unit, multiplier), the expected short description and the long description of the Board's CSV
download (whitespace aside). Observations carry exactly a status, a value and an ISO date; dates strictly increase and
fall on weekdays; status A carries a plain decimal, kept as its exact text; status ND carries -9999 and is stated as ND,
the CSV download's no-value marker; any other status refuses the package. FREQ code 9 is checked as a code: its label is
defined in the structure entries, which are not parsed, so the business-day frequency is checked from the observations
themselves (weekdays only, in order) and from the series names' .B suffix.

The derived index (validation record) is tied to the package's SHA-256 and to PARSER_VERSION, and is verified again on
every read: its versions, package identity, every row's text and date, the counts and coverage recomputed from the rows,
and the rows' SHA-256. A record for another parser version, another package or with any difference is not used.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import pyexpat
import re
import xml.parsers.expat as expat
import zipfile
import zlib

from .market_context import DECIMAL, NO_VALUE, SERIES
from .store import canonical

SOURCE_ID = "board-h15-release-xml"
PACKAGE_URL = "https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip"
PACKAGE_RECORD_VERSION = "market-package-0.1"  # acquisition.json, written once when a package is kept.
VALIDATION_VERSION = "market-package-validation-0.1"  # validation-<parser version>.json: status and derived index.
PARSER_VERSION = "h15-release-xml-parser-0.1"
PACKAGE_FILE, ACQUISITION_FILE = "package.zip", "acquisition.json"
PACKAGE_ID = re.compile(r"p(\d{8}T\d{12})Z-([0-9a-f]{12})")
ZIP_TYPES = ("application/zip", "application/x-zip-compressed")
MAX_TRANSFER = 200 * 1024 * 1024
MAX_ENTRIES = 50
MAX_ENTRY = 512 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_RATIO = 200
MAX_FINDINGS = 20
MAX_OBSERVATIONS = 100_000  # Per series; the 10-year series had 16,898 in October 2026.
MAX_TEXT = 4096
MAX_DEPTH = 32
CHUNK = 1024 * 1024
CONTEXT_BEFORE, CONTEXT_AFTER = 80, 120  # A finding's context: at most 200 bytes, the marker included.
MARKERS = re.compile(rb"<!(?:DOCTYPE|ENTITY)")
CLOCK_SKEW_SECONDS = 300
DATA_ENTRY = "H15_data.xml"
MESSAGE = "http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message"
COMMON = "http://www.SDMX.org/resources/SDMXML/schemas/v1_0/common"
FRB = "http://www.federalreserve.gov/structure/compact/common"
DATASET = "http://www.federalreserve.gov/structure/compact/H15_H15"
DATASET_ID = "H15"
FREQUENCY_CODE = "9"
MISSING = ("ND", "-9999")  # The data entry's status and value for a listed date without a value.
OBS_FIELDS = {"OBS_STATUS", "OBS_VALUE", "TIME_PERIOD"}
EXPECTED = {series_id: {"CURRENCY": series["currency"], "FREQ": FREQUENCY_CODE, "INSTRUMENT": "TCMNOM",
                        "MATURITY": f"Y{int(series_id[8:10])}", "SERIES_NAME": series_id, "UNIT": series["unit"],
                        "UNIT_MULT": series["multiplier"]}
            for series_id, series in SERIES.items()}
SHORT_DESCRIPTION = {series_id: f"{int(series_id[8:10])}-year Treasury constant maturity" for series_id in SERIES}
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?[+-]\d{2}:\d{2}")
PROTECTIONS = ("DOCTYPE declarations refused", "entity declarations refused", "notation declarations refused",
               "unparsed entity declarations refused", "parameter entities never parsed",
               "external entity references refused; nothing is fetched or opened",
               "only the data entry is parsed, as a stream")
PARSER = {"version": PARSER_VERSION, "library": f"expat {pyexpat.EXPAT_VERSION}", "protections": list(PROTECTIONS)}
FINDINGS_NOTE = ("Byte-pattern hits only, for ASCII-compatible encodings. A hit does not establish malicious content and "
                 "does not distinguish a declaration from text inside a comment or CDATA; the parser's refusals, not this "
                 "scan, are the protection. Context is untrusted, decoded with replacement characters.")


class ArchiveRefused(ValueError):
    """The archive itself failed a safeguard; ``outcome`` names which kind (unsafe_archive, archive_limit,
    malformed_archive)."""

    def __init__(self, outcome: str, detail: str):
        super().__init__(detail)
        self.outcome = outcome


class DataRefused(ValueError):
    """The data entry could not be parsed under the policy, or does not state the two series as expected."""


class RecordRefused(ValueError):
    """A stored acquisition or validation record that does not verify."""


# ---------------------------------------------------------------- the archive

def _entry_name_safe(name: str) -> bool:
    parts = name.split("/")
    return bool(name) and not name.startswith(("/", "\\")) and "\\" not in name and ".." not in parts and \
        not (len(name) > 1 and name[1] == ":") and not any(ord(character) < 32 for character in name)


def _checked_infos(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise ArchiveRefused("archive_limit", f"The archive has {len(infos)} entries; 1 to {MAX_ENTRIES} are allowed")
    names = [info.filename for info in infos]
    if len(set(names)) != len(names):
        raise ArchiveRefused("unsafe_archive", "The archive holds two entries with the same name")
    for info in infos:
        name = info.filename
        if not _entry_name_safe(name):
            raise ArchiveRefused("unsafe_archive", f"Unsafe entry path {name!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ArchiveRefused("unsafe_archive", f"Entry {name!r} is a symbolic link")
        if info.flag_bits & 0x1:
            raise ArchiveRefused("unsafe_archive", f"Entry {name!r} is encrypted")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ArchiveRefused("unsafe_archive", f"Entry {name!r} uses unsupported compression {info.compress_type}")
        if not info.is_dir() and info.file_size > MAX_ENTRY:
            raise ArchiveRefused("archive_limit", f"Entry {name!r} declares {info.file_size} bytes; the limit is "
                                                  f"{MAX_ENTRY}")
    return infos


def _stream(archive: zipfile.ZipFile, info: zipfile.ZipInfo, total: list[int]):
    """An entry's decompressed bytes, chunk by chunk, with the size, total and ratio limits applied as they arrive."""
    actual = 0
    with archive.open(info) as stream:
        while chunk := stream.read(CHUNK):
            actual += len(chunk)
            total[0] += len(chunk)
            if actual > MAX_ENTRY or total[0] > MAX_TOTAL:
                raise ArchiveRefused("archive_limit", f"Decompressed bytes passed the limit in {info.filename!r}")
            if actual > MAX_RATIO * max(info.compress_size, 1):
                raise ArchiveRefused("archive_limit", f"Entry {info.filename!r} expands more than {MAX_RATIO}:1")
            yield chunk
    if actual != info.file_size:
        raise ArchiveRefused("malformed_archive", f"Entry {info.filename!r} declared {info.file_size} bytes and held "
                                                  f"{actual}")


def check_archive(path: Path) -> tuple[list[dict], dict]:
    """Every entry checked and inventoried, with the DOCTYPE/ENTITY findings. Raises ArchiveRefused."""
    try:
        return _check_archive(path)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError, OSError) as exc:
        if isinstance(exc, ArchiveRefused):
            raise
        raise ArchiveRefused("malformed_archive", f"The archive could not be read ({type(exc).__name__}: {exc})") \
            from None


def _check_archive(path: Path) -> tuple[list[dict], dict]:
    findings = {"recorded": [], "total": 0, "omitted": 0, "max_recorded": MAX_FINDINGS,
                "context_bytes": {"before": CONTEXT_BEFORE, "after_marker_start": CONTEXT_AFTER},
                "note": FINDINGS_NOTE}
    entries, total = [], [0]
    with zipfile.ZipFile(path) as archive:
        for info in _checked_infos(archive):
            if info.is_dir():
                entries.append({"name": info.filename, "directory": True})
                continue
            digest, hits = hashlib.sha256(), {"<!DOCTYPE": 0, "<!ENTITY": 0}
            carry, scanned, size = b"", 0, 0

            def scan(window: bytes, start: int, final: bool) -> int:
                """Record markers that begin at or after `scanned`; near the window's end they wait for more bytes."""
                limit = start + len(window) if final else start + len(window) - CONTEXT_AFTER
                for match in MARKERS.finditer(window):
                    offset = start + match.start()
                    if offset < scanned or offset >= limit:
                        continue
                    marker = match.group().decode("ascii")
                    hits[marker] += 1
                    findings["total"] += 1
                    if len(findings["recorded"]) < MAX_FINDINGS:
                        low = max(match.start() - CONTEXT_BEFORE, 0)
                        context = window[low:match.start() + CONTEXT_AFTER]
                        findings["recorded"].append({
                            "entry": info.filename, "marker": marker, "uncompressed_offset": offset,
                            "context_offset": start + low, "context_bytes": len(context),
                            "context_untrusted": context.decode("utf-8", errors="replace")})
                    else:
                        findings["omitted"] += 1
                return max(limit, scanned)

            for chunk in _stream(archive, info, total):
                size += len(chunk)
                digest.update(chunk)
                window = carry + chunk
                scanned = scan(window, size - len(window), final=False)
                carry = window[-512:]
            scan(carry, size - len(carry), final=True)
            entries.append({"name": info.filename, "directory": False, "compressed_bytes": info.compress_size,
                            "uncompressed_bytes": size, "crc32": f"{info.CRC:08x}", "crc_checked": True,
                            "sha256": digest.hexdigest(), "compress_type": info.compress_type,
                            "modified": "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time, "marker_hits": hits})
    return entries, findings


# ---------------------------------------------------------------- the data entry

class _Reader:
    """expat handlers that keep only the header, the dataset names and the two series."""

    def __init__(self):
        self.stack: list[tuple[str, str]] = []
        self.header: dict = {"id": None, "name": None, "prepared": None}
        self.datasets: list[str | None] = []
        self.dataset: str | None = None
        self.series_elements = 0
        self.found: dict = {}
        self.current: dict | None = None
        self.collect: list[str] | None = None
        self.annotation: dict = {}

    def refuse(self, problem: str):
        raise DataRefused(problem)

    def start(self, tag: str, attrs: dict) -> None:
        space, _, local = tag.rpartition("|")
        parent = self.stack[-1] if self.stack else None
        if len(self.stack) >= MAX_DEPTH:
            self.refuse(f"{DATA_ENTRY} nests elements more than {MAX_DEPTH} deep")
        if parent is None and (space, local) != (MESSAGE, "MessageGroup"):
            self.refuse(f"{DATA_ENTRY} is not an SDMX message group")
        self.stack.append((space, local))
        if parent == (MESSAGE, "Header") and space == MESSAGE and local in ("ID", "Name", "Prepared"):
            self.collect = []
        elif (space, local) == (FRB, "DataSet"):
            self.dataset = attrs.get("id")
            self.datasets.append(self.dataset)
        elif local == "Series" and parent == (FRB, "DataSet"):
            self.series_elements += 1
            name = attrs.get("SERIES_NAME")
            if name in SERIES:
                if space != DATASET or self.dataset != DATASET_ID:
                    self.refuse(f"{name} appears outside the {DATASET_ID} dataset")
                if name in self.found:
                    self.refuse(f"{name} appears more than once")
                self.current = {"attributes": dict(attrs), "annotations": {}, "rows": {}, "last": None,
                                "values": 0, "no_value": 0}
                self.found[name] = self.current
        elif (space, local) == (FRB, "Obs"):
            if parent is None or parent[1] != "Series":
                self.refuse(f"{DATA_ENTRY} has an observation outside a series")
            if self.current is not None:
                self.observation(attrs)
        elif self.current is not None and (space, local) in ((COMMON, "AnnotationType"), (COMMON, "AnnotationText")):
            self.collect = []

    def observation(self, attrs: dict) -> None:
        name = self.current["attributes"]["SERIES_NAME"]
        if set(attrs) != OBS_FIELDS:
            self.refuse(f"An observation of {name} has the attributes {sorted(attrs)}, not {sorted(OBS_FIELDS)}")
        period, status, value = attrs["TIME_PERIOD"], attrs["OBS_STATUS"], attrs["OBS_VALUE"]
        try:
            day = date.fromisoformat(period) if DAY.fullmatch(period) else None
        except ValueError:
            day = None
        if day is None:
            self.refuse(f"{name} has an observation dated {period!r}, not a calendar date")
        last = self.current["last"]
        if last is not None and day <= last:
            self.refuse(f"{name} has {'a duplicate observation' if day == last else 'observations out of order'} "
                        f"on {period}")
        if day.weekday() >= 5:
            self.refuse(f"{name} has an observation on a weekend ({period}), which a business-day series does not")
        if status == "A":
            if not DECIMAL.fullmatch(value):
                self.refuse(f"{name} has the value {value!r} on {period}, not a plain decimal")
            text = value
            self.current["values"] += 1
        elif (status, value) == MISSING:
            text = NO_VALUE
            self.current["no_value"] += 1
        else:
            self.refuse(f"{name} has the status {status!r} with value {value!r} on {period}; only A with a decimal "
                        f"and ND with -9999 are accepted")
        if len(self.current["rows"]) >= MAX_OBSERVATIONS:
            self.refuse(f"{name} has more than {MAX_OBSERVATIONS} observations")
        self.current["rows"][period] = text
        self.current["last"] = day

    def end(self, tag: str) -> None:
        space, local = self.stack.pop()
        if self.collect is not None and (local in ("ID", "Name", "Prepared") and space == MESSAGE or
                                         space == COMMON and local in ("AnnotationType", "AnnotationText")):
            text = "".join(self.collect)
            self.collect = None
            if space == MESSAGE and self.stack == [(MESSAGE, "MessageGroup"), (MESSAGE, "Header")]:
                self.header[{"ID": "id", "Name": "name", "Prepared": "prepared"}[local]] = text
            elif self.current is not None:
                self.annotation[local] = text
        elif self.current is not None and (space, local) == (COMMON, "Annotation"):
            kind, text = self.annotation.get("AnnotationType"), self.annotation.get("AnnotationText")
            self.annotation = {}
            if kind in self.current["annotations"]:
                self.refuse(f"{self.current['attributes']['SERIES_NAME']} repeats its {kind!r} annotation")
            self.current["annotations"][kind] = text
        elif local == "Series" and self.current is not None and len(self.stack) == 2:
            self.current = None
        elif (space, local) == (FRB, "DataSet"):
            self.dataset = None

    def text(self, data: str) -> None:
        if self.collect is not None:
            self.collect.append(data)
            if sum(len(part) for part in self.collect) > MAX_TEXT:
                self.refuse(f"{DATA_ENTRY} has a header or annotation text longer than {MAX_TEXT} characters")


def _refuse_declaration(kind: str):
    def handler(*_):
        raise DataRefused(f"{DATA_ENTRY} has a {kind}, which the parser policy refuses")
    return handler


def protected_parser(reader) -> "expat.XMLParserType":
    """An expat parser that reads no DTD, expands no entity and resolves no external resource."""
    parser = expat.ParserCreate(namespace_separator="|")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse_declaration("DOCTYPE declaration")
    parser.EntityDeclHandler = _refuse_declaration("entity declaration")
    parser.UnparsedEntityDeclHandler = _refuse_declaration("unparsed entity declaration")
    parser.NotationDeclHandler = _refuse_declaration("notation declaration")
    parser.ExternalEntityRefHandler = _refuse_declaration("external entity reference")
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.text
    return parser


def _missing_weekdays(rows: dict) -> int:
    days = [date.fromisoformat(period) for period in rows]
    span = (days[-1] - days[0]).days + 1
    weekdays = sum(1 for offset in range(span) if (days[0] + timedelta(days=offset)).weekday() < 5)
    return weekdays - len(days)


def _normalized(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_data(path: Path) -> dict:
    """The data entry's header, its two series and their rows. Raises DataRefused (or ArchiveRefused for an archive
    problem met while reading)."""
    reader = _Reader()
    parser = protected_parser(reader)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = {info.filename: info for info in _checked_infos(archive)}
            if DATA_ENTRY not in infos or infos[DATA_ENTRY].is_dir():
                raise DataRefused(f"The package has no {DATA_ENTRY} entry")
            for chunk in _stream(archive, infos[DATA_ENTRY], [0]):
                parser.Parse(chunk, False)
            parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise DataRefused(f"{DATA_ENTRY} is not well-formed XML ({exc})") from None
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, OSError) as exc:
        raise ArchiveRefused("malformed_archive", f"The archive could not be read ({type(exc).__name__}: {exc})") \
            from None
    if reader.header["id"] != DATASET_ID:
        raise DataRefused(f"{DATA_ENTRY}'s header does not name the {DATASET_ID} release")
    series, rows = {}, {}
    for series_id, expected in EXPECTED.items():
        found = reader.found.get(series_id)
        if found is None:
            raise DataRefused(f"{DATA_ENTRY} does not contain {series_id}")
        if found["attributes"] != expected:
            raise DataRefused(f"{series_id} has the attributes {found['attributes']}, not {expected}")
        short, long = found["annotations"].get("Short Description"), found["annotations"].get("Long Description")
        if short != SHORT_DESCRIPTION[series_id]:
            raise DataRefused(f"{series_id}'s short description is {short!r}, not {SHORT_DESCRIPTION[series_id]!r}")
        if _normalized(long) != _normalized(SERIES[series_id]["description"]):
            raise DataRefused(f"{series_id}'s long description is {long!r}, not the expected series")
        if not found["rows"]:
            raise DataRefused(f"{series_id} has no observations")
        rows[series_id] = found["rows"]
        series[series_id] = _series_summary(found["attributes"], short, long, found["rows"])
    coverage = _coverage(series)
    if coverage is None:
        raise DataRefused("The two series have no dates in common")
    return {"header": reader.header, "datasets": reader.datasets, "series_elements": reader.series_elements,
            "series": series, "coverage": coverage, "rows": rows}


def _series_summary(attributes: dict, short: str, long: str, rows: dict) -> dict:
    periods = list(rows)
    return {"dataset": DATASET_ID, "attributes": attributes, "short_description": short, "long_description": long,
            "first": periods[0], "last": periods[-1], "observations": len(rows),
            "values": sum(1 for text in rows.values() if text != NO_VALUE),
            "no_value": sum(1 for text in rows.values() if text == NO_VALUE), "missing_weekdays": _missing_weekdays(rows)}


def _coverage(series: dict) -> dict | None:
    first, last = max(item["first"] for item in series.values()), min(item["last"] for item in series.values())
    return {"first": first, "last": last} if first <= last else None


# ---------------------------------------------------------------- records

def validation_name(parser_version: str = PARSER_VERSION) -> str:
    return f"validation-{parser_version}.json"


def validate(path: Path, package_id: str, package_sha256: str, validated_at: datetime, requested_on: date) -> dict:
    """The validation record for one kept package: accepted with its derived index, or refused with the blocker.
    ``requested_on`` is the New York date of the package's request: no observation may be dated after it."""
    record = {"validation_version": VALIDATION_VERSION, "parser_version": PARSER_VERSION, "package_id": package_id,
              "package_sha256": package_sha256, "validated_at": validated_at.astimezone(timezone.utc).isoformat(
                  timespec="seconds"), "parser": PARSER, "status": "refused", "detail": None, "archive": None,
              "data_entry": None, "header": None, "series": None, "coverage": None, "rows": None, "rows_sha256": None}
    try:
        entries, findings = check_archive(path)
        record["archive"] = {"entries": entries, "marker_findings": findings}
        parsed = parse_data(path)
    except (ArchiveRefused, DataRefused) as exc:
        record["detail"] = str(exc)
        return record
    latest = max(item["last"] for item in parsed["series"].values())
    if latest > requested_on.isoformat():
        record["detail"] = (f"{DATA_ENTRY} has observations dated up to {latest}, after the day the package was "
                            f"requested ({requested_on.isoformat()})")
        return record
    entry = next(item for item in entries if item["name"] == DATA_ENTRY)
    record.update(status="accepted", data_entry={key: entry[key] for key in ("name", "uncompressed_bytes", "sha256",
                                                                             "crc32")},
                  header=parsed["header"], series=parsed["series"], coverage=parsed["coverage"], rows=parsed["rows"],
                  rows_sha256=hashlib.sha256(canonical(parsed["rows"]).encode("utf-8")).hexdigest())
    return record


def moment(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not TIME.fullmatch(value):
        raise RecordRefused(f"{label} must be an ISO date and time with an explicit UTC offset")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise RecordRefused(f"{label} is not a real date and time") from None


def check_acquisition(record: object, package_id: str, size: int, digest: str) -> dict:
    """A kept package's acquisition record against its folder and bytes: the identity, source, address, a ZIP reply
    with HTTP 200 and no content encoding, times that agree, the size and SHA-256, and the status it was kept with."""
    label = f"Package {package_id}'s acquisition record"
    match = PACKAGE_ID.fullmatch(package_id)
    if not isinstance(record, dict) or not match:
        raise RecordRefused(f"{label} is not a JSON object in a package folder")
    headers = record.get("headers")
    if record.get("package_record_version") != PACKAGE_RECORD_VERSION or record.get("package_id") != package_id or \
            record.get("source") != SOURCE_ID or record.get("url") != PACKAGE_URL or \
            record.get("validation_status") != "acquired_unvalidated" or not isinstance(headers, dict) or \
            not isinstance(record.get("client"), dict) or not isinstance(record.get("approval"), dict) or \
            not isinstance(record.get("acquisition_method"), str) or record.get("redirect_followed") is not False:
        raise RecordRefused(f"{label} does not have the expected fields and values")
    if type(record.get("http_status")) is not int or record["http_status"] != 200 or \
            str(headers.get("content-type")).split(";")[0].strip().lower() not in ZIP_TYPES or \
            headers.get("content-encoding") not in (None, "identity"):
        raise RecordRefused(f"{label} is not a ZIP reply with HTTP status 200 and no content encoding")
    requested = moment(record.get("requested_at"), f"{label}'s requested_at")
    received = moment(record.get("received_at"), f"{label}'s received_at")
    if received < requested or f"{requested.astimezone(timezone.utc):%Y%m%dT%H%M%S%f}" != match[1]:
        raise RecordRefused(f"{label} has request and receipt times that disagree with each other or its ID")
    if headers.get("date") is not None:
        try:
            server = parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError):
            raise RecordRefused(f"{label} has an HTTP Date that cannot be read") from None
        if server.utcoffset() is None or abs((server - requested).total_seconds()) > CLOCK_SKEW_SECONDS or \
                abs((server - received).total_seconds()) > CLOCK_SKEW_SECONDS:
            raise RecordRefused(f"{label} has request, receipt and server times that disagree")
    if (record.get("bytes"), record.get("sha256")) != (size, digest) or match[2] != digest[:12]:
        raise RecordRefused(f"{label} does not match its package's size and SHA-256")
    return record


def _check_rows(rows: object, label: str) -> None:
    if not isinstance(rows, dict) or set(rows) != set(SERIES):
        raise RecordRefused(f"{label} does not hold exactly the two series")
    for series_id, series_rows in rows.items():
        if not isinstance(series_rows, dict) or not series_rows:
            raise RecordRefused(f"{label} has no rows for {series_id}")
        last = None
        for period, text in series_rows.items():
            try:
                day = date.fromisoformat(period) if DAY.fullmatch(period) else None
            except ValueError:
                day = None
            if day is None or (last is not None and day <= last) or day.weekday() >= 5 or \
                    not isinstance(text, str) or not (text == NO_VALUE or DECIMAL.fullmatch(text)):
                raise RecordRefused(f"{label} has an invalid row for {series_id} ({period!r})")
            last = day


def check_validation(record: object, package_id: str, digest: str) -> dict:
    """A validation record for the current parser version, against its package: versions, identity, and for an
    accepted record every row and every count recomputed. Returns the record, or raises RecordRefused."""
    label = f"Package {package_id}'s validation record"
    fields = {"validation_version", "parser_version", "package_id", "package_sha256", "validated_at", "parser",
              "status", "detail", "archive", "data_entry", "header", "series", "coverage", "rows", "rows_sha256"}
    if not isinstance(record, dict) or set(record) != fields or record["validation_version"] != VALIDATION_VERSION or \
            record["parser_version"] != PARSER_VERSION:
        raise RecordRefused(f"{label} does not have the expected fields and versions")
    if record["package_id"] != package_id:
        raise RecordRefused(f"{label} belongs to another package ({record['package_id']})")
    if record["package_sha256"] != digest:
        raise RecordRefused(f"{label} was derived from other package bytes (SHA-256 {record['package_sha256']})")
    moment(record["validated_at"], f"{label}'s validated_at")
    if record["status"] == "refused":
        if not isinstance(record["detail"], str) or not record["detail"] or record["rows"] is not None:
            raise RecordRefused(f"{label} is a refusal without its reason")
        return record
    if record["status"] != "accepted" or record["detail"] is not None:
        raise RecordRefused(f"{label} has an unknown status")
    rows = record["rows"]
    _check_rows(rows, label)
    if record["rows_sha256"] != hashlib.sha256(canonical(rows).encode("utf-8")).hexdigest():
        raise RecordRefused(f"{label}'s rows do not match their SHA-256")
    series = record["series"]
    if not isinstance(series, dict) or set(series) != set(SERIES):
        raise RecordRefused(f"{label} does not describe exactly the two series")
    for series_id, summary in series.items():
        expected = _series_summary(EXPECTED[series_id], SHORT_DESCRIPTION[series_id],
                                   summary.get("long_description") if isinstance(summary, dict) else None,
                                   rows[series_id])
        if summary != expected or _normalized(summary["long_description"]) != \
                _normalized(SERIES[series_id]["description"]):
            raise RecordRefused(f"{label}'s description of {series_id} does not match its rows or the expected series")
    if record["coverage"] != _coverage(series) or not isinstance(record["header"], dict) or \
            record["header"].get("id") != DATASET_ID or not isinstance(record["data_entry"], dict) or \
            record["data_entry"].get("name") != DATA_ENTRY:
        raise RecordRefused(f"{label}'s coverage, header or data entry does not match")
    return record


def strict_json(data: bytes, label: str) -> dict:
    """UTF-8 JSON with no repeated key and no non-standard constant, as an object."""
    def pairs(items: list) -> dict:
        if len({key for key, _ in items}) != len(items):
            raise RecordRefused(f"{label} repeats a JSON key")
        return dict(items)

    def constant(name: str):
        raise RecordRefused(f"{label} contains the non-standard JSON constant {name}")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RecordRefused(f"{label} is not strict UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise RecordRefused(f"{label} is not a JSON object")
    return value


@dataclass(frozen=True)
class Held:
    """What a verified, accepted package states: rows by series and date, and the dates it covers."""
    first: date
    last: date
    rows: dict  # series id -> {date: exact text, ND included}


def held(record: dict) -> Held:
    rows = {series_id: {date.fromisoformat(period): text for period, text in series_rows.items()}
            for series_id, series_rows in record["rows"].items()}
    return Held(date.fromisoformat(record["coverage"]["first"]), date.fromisoformat(record["coverage"]["last"]), rows)


def file_sha256(path: Path) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


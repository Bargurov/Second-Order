"""Market context for the case library: daily Treasury yields around a publication date, shown as description only.

Context is not a hypothesis, an event study, a reaction measure or a score. It shows the Federal Reserve Board's H.15
2-year and 10-year Treasury constant-maturity yields (series RIFLGFCY02_N.B and RIFLGFCY10_N.B, which FRED republishes
as DGS2 and DGS10) from 14 calendar days before to 14 calendar days after a case's New York publication date, beside
the editorial case, with their provenance and limits. Nothing here touches the store, scoring, snapshots or the FRED
import, and no read contacts a provider.

Preparation is an explicit, offline step. The operator downloads the Board's Data Download Program CSV for each
case's exact window (see `urls`) into a staging folder, with an acquisition record of every download
(acquisition.json: address, request and receipt times, HTTP status, content type, the server's Date header, size and
SHA-256, and optionally the replies that were discarded). Preparation keeps those bytes unchanged under sources/,
classifies every calendar date with the SIFMA bond-market calendar used by the research import (market_calendar), and
writes one prepared view per case plus a manifest that binds the views and the acquisition record to their hashes.
Nothing is interpolated, filled or moved: a missing value stays missing, and a date is an observed session, an expected
session without a value, a calendar holiday, or not a session.

Each staging folder is one acquisition run with its own manifest. `prepare` starts a bundle with run 1
(manifest.json); `append` adds the next run (manifest-N.json, sources/acquisition-N.json) for cases not yet in the
bundle, copying every existing file byte for byte and changing none. index.json lists the runs in order with each
manifest's SHA-256, so runs made at different times stay separate and each remains verifiable on its own. Both write
under the bundle's cross-process lock and publish through context_publish: two directory renames, not crash-atomic.

Reading (`load_context`) verifies everything again before serving: the index and every manifest's hash, that each case
belongs to exactly one run, the run's acquisition record and the view's hashes, the source file's hash, size and
download record, the window (re-derived from the case's own publication time), the series' units and identifiers in
the source's own header, and finally every observation and status, re-derived from the raw source rows and the
recorded sessions. Any disagreement refuses the context; the editorial case is still served on its own.

These are the Board's values as published when retrieved. The Data Download Program serves no earlier vintages, so
retrieval does not establish what was available on the publication date.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

from . import case_library
from .context_lock import BundleBusy, bundle_write_lock
from .context_publish import PublicationFailed, owned_copies, publish, recovery_report
from .market_calendar import calendar_identity, expected_sessions, load_exceptions, reconcile

BUNDLE_VERSION = "market-context-0.1"  # The manifest and view format; unchanged since the first run.
INDEX_VERSION = "market-context-index-0.1"
VIEW_VERSION = "market-context-view-0.2"  # The served view; 0.2 adds the acquisition run and the index hash.
PREPARATION_VERSION = "market-context-prep-0.1"
ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = ROOT / "content" / "market-context"
INDEX = "index.json"
MANIFEST = "manifest.json"
ACQUISITION = "acquisition.json"
NEW_YORK = ZoneInfo("America/New_York")
WINDOW_DAYS = 14
EDGE_SLACK_DAYS = 3  # A source must begin and end within this many calendar days of its window's edges.
CONTEXT_CASES = ("fomc-2025-01-29", "fomc-2025-03-19", "empsit-2025-04-04", "cpi-2025-04-10", "empsit-2025-05-02",
                 "fomc-2025-05-07", "cpi-2025-05-13", "empsit-2025-06-06", "cpi-2025-06-11", "fomc-2025-06-18",
                 "empsit-2025-07-03", "cpi-2025-07-15")  # Every macro library case, in publication order.
DDP_PACKAGE = "aa2b841a39cf82a8a04208d30ba16c2e"  # The Board's Data Download Program package of the two series below.
EXPORT_URL = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series=" + DDP_PACKAGE +
              "&lastobs=&from={start:%m/%d/%Y}&to={end:%m/%d/%Y}&filetype=csv&label=include&layout=seriescolumn")
HEADER = ("Series Description", "Unit:", "Multiplier:", "Currency:", "Unique Identifier: ", "Time Period")
NO_VALUE = "ND"  # What the source shows in place of a value on a date it lists.
DECIMAL = re.compile(r"-?\d+\.\d+")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
EXPLICIT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
SOURCE = {
    "publisher": "Board of Governors of the Federal Reserve System",
    "release": "H.15 Selected Interest Rates",
    "release_url": "https://www.federalreserve.gov/releases/h15/",
    "data_download_url": "https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15",
    "help_url": "https://www.federalreserve.gov/datadownload/help/default.htm",
    "crosswalk_url": "https://www.federalreserve.gov/data/documents/DDP-FRED%20Data%20Series%20Crosswalk.csv",
    "underlying_source": "U.S. Treasury",
}
TERMS = {
    "url": "https://www.federalreserve.gov/disclaimer.htm",
    "statement": ("Unless otherwise indicated, information on Board's website is in the public domain and may be "
                  "copied and distributed without permission. Please cite to the Board as the source of the "
                  "information."),
}
VINTAGE_NOTE = ("No vintage was requested, and the Data Download Program offers none: its help page says data are "
                "only available as currently published and that pre-revision or real-time data are not available. "
                "These are the Board's values when retrieved, which may differ from those available on the "
                "publication date; whether any of them was revised is not known from this download.")


def _series(maturity: int, fred_id: str) -> dict:
    series_id = f"RIFLGFCY{maturity:02d}_N.B"
    return {"id": series_id, "unique_identifier": f"H15/H15/{series_id}", "label": f"{maturity}-year Treasury yield",
            "short_label": f"{maturity}-year",
            # Exactly as in the source's header, including its run of spaces.
            "description": f"Market yield on U.S. Treasury securities at {maturity}-year   constant maturity, "
                           "quoted on investment basis",
            "unit": "Percent:_Per_Year", "units_label": "Percent per year", "multiplier": "1", "currency": "NA",
            "frequency": "Business day",
            # The Board's DDP-FRED crosswalk maps the series to these FRED IDs; nothing here was obtained from FRED.
            # The research import's calendar exceptions use the same IDs.
            "fred_equivalent": fred_id, "fred_page": f"https://fred.stlouisfed.org/series/{fred_id}"}


SERIES = {series["id"]: series for series in (_series(2, "DGS2"), _series(10, "DGS10"))}
# Statuses whose source value is shown as an observation; every other status shows no value.
VALUE_STATUSES = {"session_value", "issuer_observation_on_calendar_holiday"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # Fixed names; never the system locale's.
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
DOWNLOAD_FIELDS = {"case", "file", "url", "requested_at", "received_at", "http_status", "content_type",
                   "response_date", "bytes", "sha256"}
# A reply that was not kept: what was received and why it was refused. Nothing from it is retained or served as data.
DISCARDED_FIELDS = {"case", "url", "requested_at", "received_at", "http_status", "content_type", "response_date",
                    "bytes", "sha256", "reason"}
SHA256 = re.compile(r"[0-9a-f]{64}")


def manifest_name(run: int) -> str:
    """Run 1 keeps the bundle's original manifest name; later runs are numbered."""
    return MANIFEST if run == 1 else f"manifest-{run}.json"


def record_name(run: int) -> str:
    return f"sources/{ACQUISITION}" if run == 1 else f"sources/acquisition-{run}.json"


class ContextRefused(ValueError):
    """Context cannot be served or prepared; ``status`` is the HTTP status that describes why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _invalid(problem: str) -> ContextRefused:
    return ContextRefused(500, f"The market context is invalid: {problem}; no context is shown")


def event_window(published_at: str) -> tuple[date, date, date]:
    """The publication's New York date and the window of 14 calendar days either side of it."""
    if not isinstance(published_at, str) or not case_library.EXPLICIT_TIME.fullmatch(published_at):
        raise ContextRefused(500, f"The publication time {published_at!r} has no explicit UTC offset")
    day = datetime.fromisoformat(published_at).astimezone(NEW_YORK).date()
    return day, day - timedelta(days=WINDOW_DAYS), day + timedelta(days=WINDOW_DAYS)


def export_url(start: date, end: date) -> str:
    """The Board's documented direct-download address for the two series over [start, end]."""
    return EXPORT_URL.format(start=start, end=end)


def parse_h15_csv(data: bytes) -> dict[str, list[tuple[date, str, float | None]]]:
    """The Board's Data Download Program CSV (series in columns, labels included), read strictly.

    Six labelled header rows must describe exactly the two expected series with their expected description, unit,
    multiplier, currency and column name; then one row per date, dates strictly increasing. ND stays missing; every
    other value must be a plain decimal number. Rows keep their exact text."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ContextRefused(500, "The H.15 source is not UTF-8 text") from None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if len(rows) <= len(HEADER) or any(len(row) != 3 for row in rows):
        raise ContextRefused(500, "The source is not a two-series H.15 download with labelled header rows")
    if tuple(row[0] for row in rows[:len(HEADER)]) != HEADER:
        raise ContextRefused(500, "The source's header rows are not the Data Download Program's labels")
    expected = {series["unique_identifier"]: series for series in SERIES.values()}
    identifiers = rows[4][1:]
    if sorted(identifiers) != sorted(expected):
        raise ContextRefused(500, "The source does not hold exactly the 2-year and 10-year H.15 constant-maturity series")
    columns = []
    for index, identifier in enumerate(identifiers, start=1):
        series = expected[identifier]
        stated = [rows[0][index], rows[1][index], rows[2][index], rows[3][index], rows[5][index]]
        if stated != [series["description"], series["unit"], series["multiplier"], series["currency"], series["id"]]:
            raise ContextRefused(500, f"The source describes {series['id']} differently (description, unit, "
                                      f"multiplier, currency or column): {stated}")
        columns.append(series["id"])
    parsed: dict[str, list] = {series_id: [] for series_id in columns}
    previous = None
    for row in rows[len(HEADER):]:
        if not DAY.fullmatch(row[0]):
            raise ContextRefused(500, f"A source row has an invalid date {row[0]!r}")
        try:
            day = date.fromisoformat(row[0])
        except ValueError:
            raise ContextRefused(500, f"A source row has an invalid date {row[0]!r}") from None
        if previous is not None and day <= previous:
            raise ContextRefused(500, "Source dates are not strictly increasing")
        previous = day
        for series_id, raw in zip(columns, row[1:]):
            if raw == NO_VALUE:
                value = None
            elif DECIMAL.fullmatch(raw):
                value = float(raw)
            else:
                raise ContextRefused(500, f"{series_id} has a value that is neither a decimal nor ND on {day}")
            parsed[series_id].append((day, raw, value))
    return {series_id: parsed[series_id] for series_id in SERIES}


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _check_coverage(rows: list, start: date, end: date, label: str) -> None:
    first, last = rows[0][0], rows[-1][0]
    if first < start or last > end:
        raise ContextRefused(500, f"{label} has rows outside the window {start} to {end}")
    if (first - start).days > EDGE_SLACK_DAYS or (end - last).days > EDGE_SLACK_DAYS:
        raise ContextRefused(500, f"{label} covers {first} to {last}, not the whole window {start} to {end}")


def derive_days(rows_by_series: dict[str, list], start: date, end: date, sessions: set[date],
                exceptions: dict) -> list[dict]:
    """Every calendar date in the window, with each series' value and status. Nothing is filled or moved."""
    classified = {}
    for series_id, rows in rows_by_series.items():
        reconciled = reconcile(SERIES[series_id]["fred_equivalent"], [(day, value) for day, _, value in rows],
                               sessions, exceptions, start)
        statuses = {day: status for day, _, status in reconciled}
        provided = {day: (raw, value) for day, raw, value in rows}
        per_day = {}
        for day in _dates(start, end):
            status = statuses.get(day) or ("session_absent" if day in sessions else "not_a_session")
            if status == "calendar_holiday" and day.weekday() >= 5:
                status = "not_a_session"  # A weekend row without a value is a weekend, not a holiday.
            raw, value = provided.get(day, (None, None))
            per_day[day] = {"raw": raw, "value": value if status in VALUE_STATUSES else None, "status": status}
        classified[series_id] = per_day
    return [{"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "session": day in sessions,
             "observations": {series_id: classified[series_id][day] for series_id in SERIES}}
            for day in _dates(start, end)]


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _cases(case_ids, library: Path) -> dict:
    cases = {case["id"]: case for case in case_library.load_library(library)["cases"]}
    unknown = [case_id for case_id in case_ids if case_id not in cases]
    if unknown:
        raise ContextRefused(422, f"Unknown cases {unknown}")
    return cases


def urls(case_ids=CONTEXT_CASES, library: Path = case_library.LIBRARY_DIR) -> list[dict]:
    """The exact downloads preparation expects: one per case, both series, for that case's window."""
    cases = _cases(case_ids, library)
    listed = []
    for case_id in case_ids:
        _, start, end = event_window(cases[case_id]["source"]["published_at"])
        listed.append({"case": case_id, "file": f"{case_id}.csv", "start": start.isoformat(), "end": end.isoformat(),
                       "url": export_url(start, end)})
    return listed


def _moment(value: object, label: str, status: int) -> datetime:
    if not isinstance(value, str) or not EXPLICIT_TIME.fullmatch(value):
        raise ContextRefused(status, f"{label} must be an ISO date and time with an explicit UTC offset")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ContextRefused(status, f"{label} is not a real date and time") from None


def check_download(record: object, case_id: str, url: str, data: bytes, status: int) -> dict:
    """One acquisition record: exact fields, the expected address, a plain CSV 200, times that agree, and the bytes."""
    label = f"The download record for {case_id}"
    if not isinstance(record, dict) or set(record) != DOWNLOAD_FIELDS:
        raise ContextRefused(status, f"{label} does not have exactly the fields {sorted(DOWNLOAD_FIELDS)}")
    if (record["case"], record["file"], record["url"]) != (case_id, f"{case_id}.csv", url):
        raise ContextRefused(status, f"{label} names another case, file or address")
    if type(record["http_status"]) is not int or record["http_status"] != 200 or record["content_type"] != "text/csv":
        raise ContextRefused(status, f"{label} is not a text/csv response with HTTP status 200")
    requested = _moment(record["requested_at"], f"{label}'s requested_at", status)
    received = _moment(record["received_at"], f"{label}'s received_at", status)
    try:
        server = parsedate_to_datetime(record["response_date"])
    except (TypeError, ValueError):
        raise ContextRefused(status, f"{label} has no valid HTTP Date") from None
    if received < requested or server.utcoffset() is None or \
            abs((server - requested).total_seconds()) > 300 or abs((server - received).total_seconds()) > 300:
        raise ContextRefused(status, f"{label} has request, receipt and server times that disagree")
    if (record["bytes"], record["sha256"]) != (len(data), sha256(data)):
        raise ContextRefused(status, f"{label} does not match the downloaded file's size and SHA-256")
    return record


def _strict_json(data: bytes, label: str, status: int) -> dict:
    def refuse(problem: str) -> ContextRefused:
        return ContextRefused(status, f"{label} {problem}")

    def pairs(items: list) -> dict:
        if len({key for key, _ in items}) != len(items):
            raise refuse("repeats a JSON key")
        return dict(items)

    def constant(name: str):
        raise refuse(f"contains the non-standard JSON constant {name}")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise refuse("is not strict UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise refuse("is not a JSON object")
    return value


def _acquisition(data: bytes, status: int) -> tuple[dict, dict]:
    """The acquisition record and its downloads by case; each case may be recorded once.

    An optional "discarded" list records replies that were refused, with what was received and why; each names a case
    of this record and its expected address, and none can stand in for a kept download."""
    record = _strict_json(data, ACQUISITION, status)
    if set(record) - {"discarded"} != {"tool", "downloads"} or not isinstance(record["tool"], str) or \
            not record["tool"].strip() or not isinstance(record["downloads"], list) or \
            not all(isinstance(item, dict) and isinstance(item.get("case"), str) for item in record["downloads"]):
        raise ContextRefused(status, f"{ACQUISITION} must hold exactly a tool and a list of download records")
    downloads = {item.get("case"): item for item in record["downloads"]}
    if len(downloads) != len(record["downloads"]):
        raise ContextRefused(status, f"{ACQUISITION} records a case more than once")
    for item in record.get("discarded", []) if isinstance(record.get("discarded", []), list) else [None]:
        if not isinstance(item, dict) or set(item) != DISCARDED_FIELDS or not isinstance(item["case"], str) or \
                item["case"] not in downloads or \
                item["url"] != downloads[item["case"]].get("url") or not isinstance(item["reason"], str) or \
                not item["reason"].strip() or not isinstance(item["bytes"], int) or \
                not (isinstance(item["sha256"], str) and SHA256.fullmatch(item["sha256"])):
            raise ContextRefused(status, f"{ACQUISITION} has a discarded reply that is not a complete record of a "
                                         "refused download of one of its cases")
        _moment(item["requested_at"], "a discarded reply's requested_at", status)
        _moment(item["received_at"], "a discarded reply's received_at", status)
    return record, downloads


def _retrieved_on(downloads: dict, status: int) -> date:
    """The UTC date of the first request: the retrieval date cited for the series."""
    moments = [_moment(item.get("requested_at"), "requested_at", status) for item in downloads.values()]
    return min(moments).astimezone(ZoneInfo("UTC")).date()


def _citation(series: dict, retrieved: date) -> str:
    description = " ".join(series["description"].split())
    return (f"{SOURCE['publisher']}, {SOURCE['release']}: {description} [{series['unique_identifier']}], source "
            f"{SOURCE['underlying_source']}; Data Download Program, {SOURCE['data_download_url']}, retrieved "
            f"{MONTHS[retrieved.month - 1]} {retrieved.day}, {retrieved.year} (UTC).")


def _staged(staging: Path, case_ids) -> tuple[bytes, dict, dict]:
    """A staging folder: acquisition.json with exactly one kept download per case, and exactly one <case>.csv each."""
    if not (staging / ACQUISITION).is_file():
        raise ContextRefused(422, f"The staging folder has no {ACQUISITION}")
    acquisition_bytes = (staging / ACQUISITION).read_bytes()
    acquisition, records = _acquisition(acquisition_bytes, 422)
    if set(records) != set(case_ids):
        raise ContextRefused(422, f"{ACQUISITION} must record exactly one download for each of {list(case_ids)}")
    staged = {path.name for path in staging.glob("*.csv")}
    if staged != {f"{case_id}.csv" for case_id in case_ids}:
        raise ContextRefused(422, f"The staging folder must hold exactly one <case>.csv per case, not {sorted(staged)}")
    return acquisition_bytes, acquisition, records


def _write_run(work: Path, run: int, staging: Path, case_ids, method: str, sessions, cases: dict) -> bytes:
    """Writes one acquisition run into the bundle folder `work`, never over an existing file; returns its manifest."""
    acquisition_bytes, acquisition, records = _staged(staging, case_ids)
    exceptions = load_exceptions()

    def write(relative: str, data: bytes) -> None:
        path = work / relative
        if path.exists():
            raise ContextRefused(409, f"{relative} already exists in the bundle; nothing is overwritten")
        path.write_bytes(data)

    (work / "sources").mkdir(exist_ok=True)
    write(record_name(run), acquisition_bytes)
    contexts = {}
    for case_id in case_ids:
        published_day, start, end = event_window(cases[case_id]["source"]["published_at"])
        data = (staging / f"{case_id}.csv").read_bytes()
        record = check_download(records[case_id], case_id, export_url(start, end), data, 422)
        try:
            rows_by_series = parse_h15_csv(data)
            for rows in rows_by_series.values():
                _check_coverage(rows, start, end, f"{case_id}.csv")
        except ContextRefused as exc:
            raise ContextRefused(422, str(exc)) from None
        rows = next(iter(rows_by_series.values()))
        window_sessions = {day for day in sessions(start, end) if start <= day <= end}
        file = f"sources/{case_id}.csv"
        write(file, data)
        view = {"context_version": BUNDLE_VERSION, "case_id": case_id,
                "publication": {"published_at": cases[case_id]["source"]["published_at"],
                                "new_york_date": published_day.isoformat()},
                "window": {"start": start.isoformat(), "end": end.isoformat(),
                           "days_before": WINDOW_DAYS, "days_after": WINDOW_DAYS},
                "source": {"file": file, "sha256": sha256(data), "bytes": len(data), "url": record["url"],
                           "requested_start": start.isoformat(), "requested_end": end.isoformat(),
                           "returned_first": rows[0][0].isoformat(), "returned_last": rows[-1][0].isoformat(),
                           "rows": len(rows), "requested_at": record["requested_at"],
                           "received_at": record["received_at"], "http_status": record["http_status"],
                           "content_type": record["content_type"], "response_date": record["response_date"]},
                "sessions": sorted(day.isoformat() for day in window_sessions),
                "days": derive_days(rows_by_series, start, end, window_sessions, exceptions)}
        view_bytes = _json_bytes(view)
        write(f"{case_id}.json", view_bytes)
        contexts[case_id] = {"view": f"{case_id}.json", "view_sha256": sha256(view_bytes)}
    retrieved_on = _retrieved_on(records, 422)
    manifest = {"bundle_version": BUNDLE_VERSION, "preparation_version": PREPARATION_VERSION,
                "source": SOURCE, "terms": TERMS,
                "series": {series_id: {**series, "citation": _citation(series, retrieved_on)}
                           for series_id, series in SERIES.items()},
                "acquisition": {"method": method.strip(), "tool": acquisition["tool"],
                                "record": record_name(run), "record_sha256": sha256(acquisition_bytes),
                                "vintage": None, "vintage_note": VINTAGE_NOTE},
                "calendar": calendar_identity(exceptions), "contexts": contexts}
    manifest_bytes = _json_bytes(manifest)
    write(manifest_name(run), manifest_bytes)
    return manifest_bytes


def _index_bytes(runs: list[dict]) -> bytes:
    return _json_bytes({"index_version": INDEX_VERSION, "runs": runs})


def _locked(bundle: Path, write) -> dict:
    """Runs one bundle write under the bundle's cross-process lock, from its first read through publication. A
    concurrent writer is refused, never queued or retried; an expected filesystem error becomes a refusal that says
    what happened, never a traceback. Ctrl-C is not caught."""
    taken = False
    try:
        with bundle_write_lock(bundle):
            taken = True
            try:
                return write()
            except PublicationFailed as exc:
                raise ContextRefused(500, str(exc)) from None
            except OSError as exc:  # Before publication: everything so far was written to a temporary folder.
                raise ContextRefused(500, f"Nothing was published: a filesystem error stopped the work before "
                                          f"publication ({type(exc).__name__}: {exc}); the bundle is unchanged") from None
    except BundleBusy as exc:
        raise ContextRefused(409, str(exc)) from None
    except OSError as exc:
        if taken:  # Releasing the lock failed after the work ended: unexpected, so shown as it is.
            raise
        raise ContextRefused(500, f"Nothing was published: the bundle's write lock could not be taken "
                                  f"({type(exc).__name__}: {exc})") from None


def _missing(bundle: Path) -> bool:
    return not bundle.is_dir() or not any(bundle.iterdir())


def _verifies(folder: Path, library: Path) -> tuple[bool, str]:
    """Whether a folder holds a whole bundle whose every case verifies, and that in words. Reads only."""
    try:
        held = bundle_cases(folder)
        if not held:
            return False, f"its files do not verify: it holds no {INDEX} or no case"
        for case_id in held:
            load_context(case_id, folder, library)
    except (ContextRefused, OSError) as exc:
        return False, f"its files do not verify: {exc}"
    cases, runs = len(held), len(set(held.values()))
    return True, (f"its files verify ({cases} case{'s' if cases != 1 else ''} in {runs} acquisition "
                  f"run{'s' if runs != 1 else ''})")


def _describe(folder: Path, library: Path) -> tuple[bool, str]:
    """A moved-aside folder as its own index and manifests state it (each run's cases and acquisition method), then
    whether its files verify. Reads only; it describes a folder and never decides which one is restored."""
    try:
        runs = (_read_index((folder / INDEX).read_bytes(), 500) if (folder / INDEX).is_file()
                else [{"run": 1, "manifest": MANIFEST}] if (folder / MANIFEST).is_file() else [])
        stated = []
        for run in runs:
            manifest = _read_json((folder / run["manifest"]).read_bytes(), run["manifest"])
            contexts, acquisition = manifest.get("contexts"), manifest.get("acquisition")
            method = acquisition.get("method") if isinstance(acquisition, dict) else None
            stated.append(f"{run['run']} ({', '.join(contexts) if isinstance(contexts, dict) and contexts else 'no case'}"
                          f"; method: {' '.join(method.split()) if isinstance(method, str) and method.strip() else 'none'})")
        contents = f"its runs: {', '.join(stated)}" if stated else f"it holds no {INDEX} or {MANIFEST}"
    except (ContextRefused, OSError) as exc:
        contents = f"its runs cannot be read ({exc})"
    verifies, verdict = _verifies(folder, library)
    return verifies, f"{contents}; {verdict}"


def _recovery(bundle: Path, library: Path) -> tuple[bool, str | None]:
    """(whether moved-aside copies recorded as `bundle`'s own exist, the operator's recovery report or None)."""
    return recovery_report(bundle, lambda folder: _describe(folder, library))


def _prepare_checks(staging: Path, out: Path, case_ids, method: str, library: Path, replace: bool) -> dict:
    """prepare's refusals, all made by reading only: before the lock is taken, and again under it. Only copies
    recorded as this destination's own block it; other bundles' folders, or folders of unknown owner, never do."""
    if not isinstance(method, str) or not method.strip():
        raise ContextRefused(422, "Describe how the sources were obtained")
    if out.exists() and any(out.iterdir()) and not replace:
        raise ContextRefused(409, f"{out} already holds a bundle; pass replace to rebuild it, or append a run")
    owned, recovery = _recovery(out, library) if _missing(out) else (False, None)
    if owned:
        raise ContextRefused(409, recovery)
    cases = _cases(case_ids, library)
    _staged(staging, case_ids)
    return cases


def prepare(staging: Path, out: Path, case_ids=CONTEXT_CASES, method: str = "", sessions=expected_sessions,
            library: Path = case_library.LIBRARY_DIR, replace: bool = False) -> dict:
    """Prepare a bundle under its cross-process write lock; a concurrent writer is refused, never queued."""
    _prepare_checks(staging, out, case_ids, method, library, replace)  # A refusal here takes no lock, creates nothing.
    return _locked(out, lambda: _prepare(staging, out, case_ids, method, sessions, library, replace))


def _prepare(staging: Path, out: Path, case_ids, method: str, sessions, library: Path, replace: bool) -> dict:
    """Start a bundle with acquisition run 1 from one staging folder. Offline; the whole bundle, or nothing.

    The staging folder must hold acquisition.json and exactly one <case>.csv per case, each recorded as downloaded
    from that case's expected address; a missing, extra, mismatched or incomplete file refuses the preparation."""
    cases = _prepare_checks(staging, out, case_ids, method, library, replace)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".market-context-", dir=out.parent))
    try:
        manifest_bytes = _write_run(work, 1, staging, case_ids, method, sessions, cases)
        (work / INDEX).write_bytes(_index_bytes([{"run": 1, "manifest": MANIFEST,
                                                  "manifest_sha256": sha256(manifest_bytes)}]))
        if not replace and not _missing(out):  # Filled meanwhile by a writer that ignores the lock: keep its content.
            raise ContextRefused(409, f"{out} was filled by another process while the bundle was prepared; nothing was "
                                      "published, and what is there was left unchanged")
        warning = publish(out, work)
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    return {"bundle": str(out), "run": 1, "contexts": list(case_ids)} | ({"cleanup_warning": warning} if warning else {})


def _run_cases(bundle: Path, runs: list[dict]) -> dict[str, int]:
    owners: dict[str, int] = {}
    for run in runs:
        for case_id in _read_json((bundle / run["manifest"]).read_bytes(), run["manifest"]).get("contexts", {}):
            owners[case_id] = run["run"]
    return owners


def bundle_cases(bundle: Path = BUNDLE_DIR) -> dict[str, int]:
    """Each case in the bundle and its acquisition run, read from the index and each manifest's contexts. Reads only;
    load_context verifies a case in full."""
    return _run_cases(bundle, _read_index((bundle / INDEX).read_bytes(), 500) if (bundle / INDEX).is_file() else [])


def _append_checks(bundle: Path, method: str, library: Path) -> None:
    """append's first refusals, made by reading only: before the lock is taken, and again under it."""
    if not isinstance(method, str) or not method.strip():
        raise ContextRefused(422, "Describe how the sources were obtained")
    if not (bundle / INDEX).is_file() and not (bundle / MANIFEST).is_file():
        owned, recovery = _recovery(bundle, library) if _missing(bundle) else (False, None)
        if owned:  # Copies recorded as this bundle's own: recovery, not a new bundle, comes first.
            raise ContextRefused(409, recovery)
        raise ContextRefused(422, f"{bundle} holds no bundle to append to; use prepare"
                                  + (f". {recovery}" if recovery else ""))  # Folders of unknown owner, described.


def append(staging: Path, bundle: Path = BUNDLE_DIR, case_ids=None, method: str = "", sessions=expected_sessions,
           library: Path = case_library.LIBRARY_DIR) -> dict:
    """Append under the same lock as prepare, from the initial read through publication. No waiting or retry."""
    _append_checks(bundle, method, library)  # A missing or mistyped bundle is refused before any folder or lock exists.
    return _locked(bundle, lambda: _append(staging, bundle, case_ids, method, sessions, library))


def _append(staging: Path, bundle: Path, case_ids, method: str, sessions, library: Path) -> dict:
    """Add the next acquisition run to an existing bundle, for declared cases it does not hold yet. Offline.

    The bundle is copied byte for byte to a temporary folder and verified there in full before anything is added; the
    new run's files are written beside the existing ones, never over them; the index gains one entry. A bundle from
    before the index (manifest.json alone) is indexed as run 1, its manifest unchanged. The result is verified again,
    every existing file is checked to be byte-identical, and only then does it replace the bundle."""
    _append_checks(bundle, method, library)
    declared = list(case_library.load_library(library)["collection"]["market_context"])
    existing = {path.relative_to(bundle).as_posix(): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
    work = Path(tempfile.mkdtemp(prefix=".market-context-", dir=bundle.parent))
    try:
        shutil.copytree(bundle, work, dirs_exist_ok=True, copy_function=shutil.copy2)
        if (work / INDEX).is_file():
            runs = _read_index((work / INDEX).read_bytes(), 422)
        else:
            runs = [{"run": 1, "manifest": MANIFEST, "manifest_sha256": sha256((work / MANIFEST).read_bytes())}]
            (work / INDEX).write_bytes(_index_bytes(runs))
        present = _run_cases(work, runs)  # From the runs' own manifests, so no existing case can be skipped.
        for case_id in present:
            try:
                load_context(case_id, work, library)
            except ContextRefused as exc:
                raise ContextRefused(422, f"The existing bundle does not verify ({case_id}): {exc}") from None
        case_ids = list(case_ids) if case_ids is not None else [case_id for case_id in declared if case_id not in present]
        if not case_ids:
            raise ContextRefused(422, "Every declared case already has market context; nothing to append")
        if any(case_id in present for case_id in case_ids) or any(case_id not in declared for case_id in case_ids):
            raise ContextRefused(422, "Append only declared cases that the bundle does not hold yet")
        run = len(runs) + 1
        manifest_bytes = _write_run(work, run, staging, case_ids, method, sessions, _cases(case_ids, library))
        runs.append({"run": run, "manifest": manifest_name(run), "manifest_sha256": sha256(manifest_bytes)})
        (work / INDEX).write_bytes(_index_bytes(runs))
        held = bundle_cases(work)
        if set(held) != set(present) | set(case_ids):
            raise ContextRefused(500, "The appended bundle does not hold exactly its earlier and new cases")
        for case_id in held:  # Every case of every run, verified again in the result.
            load_context(case_id, work, library)
        for relative, data in existing.items():
            if relative != INDEX and (work / relative).read_bytes() != data:
                raise ContextRefused(500, f"{relative} changed while appending; nothing was replaced")
        current = {path.relative_to(bundle).as_posix(): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
        if current != existing:
            raise ContextRefused(409, "The live bundle changed while appending; nothing was replaced")
        warning = publish(bundle, work)
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    return {"bundle": str(bundle), "run": run, "contexts": case_ids} | ({"cleanup_warning": warning} if warning else {})


def _field(record: object, key: str, label: str):
    if not isinstance(record, dict) or key not in record:
        raise _invalid(f"{label} has no {key}")
    return record[key]


def _read_json(data: bytes, label: str) -> dict:
    try:
        return _strict_json(data, label, 500)
    except ContextRefused as exc:
        raise _invalid(str(exc)) from None


def _in_bundle(bundle: Path, relative: object, label: str) -> Path:
    path = bundle / str(relative)
    if path.resolve().parent != (bundle / "sources").resolve() or not path.is_file():
        raise _invalid(f"{label} is missing")
    return path


def _read_index(data: bytes, status: int) -> list[dict]:
    """The runs, numbered from 1 in order, each naming its manifest (by the fixed run name) and its SHA-256."""
    index = _strict_json(data, INDEX, status)
    runs = index.get("runs")
    if set(index) != {"index_version", "runs"} or index["index_version"] != INDEX_VERSION or \
            not isinstance(runs, list) or not runs:
        raise ContextRefused(status, f"{INDEX} is not a {INDEX_VERSION} list of acquisition runs")
    for number, run in enumerate(runs, start=1):
        if not isinstance(run, dict) or set(run) != {"run", "manifest", "manifest_sha256"} or \
                type(run["run"]) is not int or run["run"] != number or run["manifest"] != manifest_name(number) or \
                not isinstance(run["manifest_sha256"], str) or not SHA256.fullmatch(run["manifest_sha256"]):
            raise ContextRefused(status, f"{INDEX} entry {number} is not run {number} with {manifest_name(number)} "
                                         "and its SHA-256")
    return runs


def load_context(case_id: str, bundle: Path = BUNDLE_DIR, library: Path = case_library.LIBRARY_DIR) -> dict:
    """One case's verified context. Reads only: nothing is fetched, written, repaired or substituted."""
    try:
        loaded = case_library.load_library(library)
    except case_library.LibraryRefused as exc:
        raise ContextRefused(exc.status, str(exc)) from None
    cases = {case["id"]: case for case in loaded["cases"]}
    if case_id not in cases or case_id not in loaded["collection"]["market_context"]:
        raise ContextRefused(404, "No market context is prepared for this case")
    index_path = bundle / INDEX
    if not index_path.is_file():
        if not bundle.exists() and owned_copies(bundle):  # Only its own copies; said without paths: this is served.
            raise ContextRefused(503, "Market context is unavailable: its bundle folder is missing and a moved-aside "
                                      "copy is beside it, so a publication may have been interrupted. The operator can "
                                      "run `python -m second_order.market_context check` for recovery details")
        raise ContextRefused(503, "Market context has not been prepared for the case library")
    index_bytes = index_path.read_bytes()
    try:
        runs = _read_index(index_bytes, 500)
    except ContextRefused as exc:
        raise _invalid(str(exc)) from None
    owners, manifests = {}, {}  # Every manifest is checked against the index, and each case may belong to one run.
    for run in runs:
        path = bundle / run["manifest"]
        if not path.is_file():
            raise _invalid(f"{run['manifest']}, the manifest of acquisition run {run['run']}, is missing")
        data = path.read_bytes()
        if sha256(data) != run["manifest_sha256"]:
            raise _invalid(f"{run['manifest']} does not match the SHA-256 recorded in {INDEX}")
        listed = _field(_read_json(data, run["manifest"]), "contexts", run["manifest"])
        if not isinstance(listed, dict):
            raise _invalid(f"{run['manifest']} has no contexts")
        for listed_case in listed:
            if listed_case in owners:
                raise _invalid(f"{listed_case} is listed by two acquisition runs")
            owners[listed_case] = run["run"]
        manifests[run["run"]] = data
    if case_id not in owners:
        raise ContextRefused(404, "No market context is prepared for this case")
    run_number = owners[case_id]
    label = manifest_name(run_number)
    manifest_bytes = manifests[run_number]
    manifest = _read_json(manifest_bytes, label)
    if (manifest.get("bundle_version"), manifest.get("preparation_version")) != (BUNDLE_VERSION, PREPARATION_VERSION):
        raise _invalid(f"the bundle is not version {BUNDLE_VERSION} prepared by {PREPARATION_VERSION}")
    if (manifest.get("source"), manifest.get("terms")) != (SOURCE, TERMS):
        raise _invalid("the manifest names another source or other terms")
    exceptions = load_exceptions()
    calendar = _field(manifest, "calendar", label)
    if _field(calendar, "exceptions_version", "calendar") != exceptions["version"]:
        raise _invalid("it was classified with other calendar exceptions; prepare it again")
    series_records = _field(manifest, "series", label)
    if not isinstance(series_records, dict) or list(series_records) != list(SERIES) or any(
            not isinstance(record, dict) or set(record) != set(SERIES[series_id]) | {"citation"} or
            {key: value for key, value in record.items() if key != "citation"} != SERIES[series_id]
            for series_id, record in series_records.items()):
        raise _invalid("the manifest does not describe exactly the two H.15 series, in percent per year, as declared")
    acquisition_info = _field(manifest, "acquisition", label)
    if _field(acquisition_info, "record", "acquisition") != record_name(run_number):
        raise _invalid(f"{label} does not name run {run_number}'s own acquisition record")
    acquisition_path = _in_bundle(bundle, acquisition_info["record"], "the acquisition record")
    acquisition_bytes = acquisition_path.read_bytes()
    if sha256(acquisition_bytes) != acquisition_info.get("record_sha256"):
        raise _invalid("the acquisition record does not match its recorded SHA-256")
    if acquisition_info.get("vintage") is not None or acquisition_info.get("vintage_note") != VINTAGE_NOTE:
        raise _invalid("the acquisition claims a vintage")
    try:
        acquisition, downloads = _acquisition(acquisition_bytes, 500)
        retrieved_on = _retrieved_on(downloads, 500)
    except ContextRefused as exc:
        raise _invalid(str(exc)) from None
    if acquisition_info.get("tool") != acquisition["tool"] or any(
            record["citation"] != _citation(SERIES[series_id], retrieved_on)
            for series_id, record in series_records.items()):
        raise _invalid("the manifest's tool or citations do not match its acquisition record")
    contexts = _field(manifest, "contexts", label)
    if not isinstance(contexts, dict) or case_id not in contexts:
        raise ContextRefused(404, "No market context is prepared for this case")
    entry = contexts[case_id]
    view_path = bundle / f"{case_id}.json"
    if _field(entry, "view", "context") != view_path.name or not view_path.is_file():
        raise _invalid(f"the view for {case_id} is missing")
    view_bytes = view_path.read_bytes()
    if sha256(view_bytes) != _field(entry, "view_sha256", "context"):
        raise _invalid(f"the view for {case_id} does not match its recorded SHA-256")
    view = _read_json(view_bytes, view_path.name)
    published_at = cases[case_id]["source"]["published_at"]
    published_day, start, end = event_window(published_at)
    expected_window = {"start": start.isoformat(), "end": end.isoformat(), "days_before": WINDOW_DAYS,
                       "days_after": WINDOW_DAYS}
    if (view.get("context_version"), view.get("case_id"), view.get("window")) != (BUNDLE_VERSION, case_id,
                                                                                   expected_window):
        raise _invalid(f"the view for {case_id} is not this case's {WINDOW_DAYS}-day window")
    if view.get("publication") != {"published_at": published_at, "new_york_date": published_day.isoformat()}:
        raise _invalid(f"the view for {case_id} names another publication time")
    try:
        sessions = {date.fromisoformat(day) for day in view["sessions"]}
    except (KeyError, TypeError, ValueError):
        raise _invalid(f"the view for {case_id} has no valid session list") from None
    if any(not start <= day <= end for day in sessions):
        raise _invalid(f"the view for {case_id} lists sessions outside its window")
    source = _field(view, "source", view_path.name)
    data = _in_bundle(bundle, _field(source, "file", "source"), f"the source for {case_id}").read_bytes()
    if (source.get("sha256"), source.get("bytes")) != (sha256(data), len(data)):
        raise _invalid(f"the source for {case_id} does not match its recorded SHA-256 and size")
    try:
        record = check_download(downloads.get(case_id), case_id, export_url(start, end), data, 500)
        rows_by_series = parse_h15_csv(data)
        for rows in rows_by_series.values():
            _check_coverage(rows, start, end, "the source")
    except ContextRefused as exc:
        raise _invalid(str(exc)) from None
    rows = next(iter(rows_by_series.values()))
    expected_source = {"file": f"sources/{case_id}.csv", "sha256": sha256(data), "bytes": len(data),
                       "url": record["url"], "requested_start": start.isoformat(), "requested_end": end.isoformat(),
                       "returned_first": rows[0][0].isoformat(), "returned_last": rows[-1][0].isoformat(),
                       "rows": len(rows), **{key: record[key] for key in (
                           "requested_at", "received_at", "http_status", "content_type", "response_date")}}
    if source != expected_source:
        raise _invalid(f"the source record for {case_id} does not match its file and download record")
    if derive_days(rows_by_series, start, end, sessions, exceptions) != view.get("days"):
        raise _invalid(f"the view for {case_id} does not match its source rows")
    series = [{**series_records[series_id],
               "values": sum(value is not None for _, _, value in rows_by_series[series_id]),
               "no_value_rows": sum(value is None for _, _, value in rows_by_series[series_id])}
              for series_id in SERIES]
    return {"view_version": VIEW_VERSION, "case_id": case_id, "publication": view["publication"],
            "window": view["window"], "series": series, "source": source, "days": view["days"],
            "provenance": {**SOURCE, "terms": TERMS, "method": acquisition_info["method"],
                           "tool": acquisition_info["tool"], "vintage": None, "vintage_note": VINTAGE_NOTE,
                           "calendar": calendar, "bundle_version": BUNDLE_VERSION,
                           "preparation_version": PREPARATION_VERSION, "view_sha256": sha256(view_bytes),
                           "manifest": label, "manifest_sha256": sha256(manifest_bytes),
                           "acquisition_record": acquisition_info["record"],
                           "acquisition_sha256": sha256(acquisition_bytes),
                           "index_version": INDEX_VERSION, "index_sha256": sha256(index_bytes),
                           # Which run this case's download belongs to, and the other cases downloaded in it.
                           "run": run_number, "runs": len(runs), "run_cases": list(contexts),
                           "discarded": [{key: item[key] for key in ("requested_at", "http_status", "content_type",
                                                                     "bytes", "reason")}
                                         for item in acquisition.get("discarded", []) if item["case"] == case_id]}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m second_order.market_context", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("urls", help="Print the exact H.15 downloads to make; nothing is fetched")
    listing.add_argument("--missing", action="store_true", help="Only declared cases the bundle does not hold yet")
    build = commands.add_parser("prepare", help="Start a bundle with acquisition run 1 from staged downloads, offline")
    more = commands.add_parser("append", help="Add the next acquisition run for cases not in the bundle, offline")
    for command in (build, more):
        command.add_argument("--staging", type=Path, required=True,
                             help="Folder holding acquisition.json and one <case>.csv per case")
        command.add_argument("--method", required=True, help="How the sources were obtained, in a few sentences")
        command.add_argument("--case", action="append", dest="cases", metavar="CASE",
                             help="A case to include (repeatable); default: every declared case not in the bundle")
    build.add_argument("--out", type=Path, default=BUNDLE_DIR)
    build.add_argument("--replace", action="store_true", help="Rebuild an existing bundle")
    commands.add_parser("check", help="Verify every declared case's context; reads only")
    args = parser.parse_args(argv)
    try:
        if args.command == "urls":
            held = bundle_cases() if args.missing else {}
            result = urls([case_id for case_id in CONTEXT_CASES if case_id not in held])
        elif args.command == "prepare":
            result = prepare(args.staging, args.out, args.cases or CONTEXT_CASES, args.method, replace=args.replace)
        elif args.command == "append":
            result = append(args.staging, BUNDLE_DIR, args.cases, args.method)
        else:
            _, recovery = _recovery(BUNDLE_DIR, case_library.LIBRARY_DIR) if _missing(BUNDLE_DIR) else (False, None)
            if recovery:  # The operator's report: its own copies, or folders of unknown owner, described.
                raise ContextRefused(503, recovery)
            result = {case_id: {"run": view["provenance"]["run"], "days": len(view["days"]),
                                "view_sha256": view["provenance"]["view_sha256"]}
                      for case_id in CONTEXT_CASES for view in [load_context(case_id)]}
    except ContextRefused as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    if "cleanup_warning" in result:  # Published; what is left of the replaced bundle is named, not hidden.
        print(json.dumps({"warning": result["cleanup_warning"]}), file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

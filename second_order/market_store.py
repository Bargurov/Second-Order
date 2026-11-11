"""Private market observations for selected macro events: the Federal Reserve Board's daily H.15 2-year and 10-year
Treasury constant-maturity yields, held as retrievals and kept apart from any event.

A retrieval is one download exactly as received, with its acquisition record. Three kinds are read:
- the downloads of the committed case-library bundle (content/market-context/, see market_context), read in place and
  never copied or changed. They are the same Board series from the Data Download Program's two-series CSV address,
  retrieved earlier for the editorial cases, so they are reused rather than requested again;
- private CSV retrievals, under data/market-context/retrievals/<id>/ (source.csv and retrieval.json), written by
  approved requests for that two-series CSV before requests moved to the release package. They are still read,
  unchanged; nothing writes new ones;
- kept H.15 release packages, under data/market-context/packages/<id>/: package.zip as received, acquisition.json, and
  one validation record per parser version (see market_package). Only an approved request (market_retrieval) or an
  operator's one-off acquisition writes a package, once, read-only; a validation record is added once and never
  rewritten. A package is used only when the validation record for the current parser version verifies and accepted
  it; a package that is not yet validated, or that a validation refused, is listed with its status and never used.

Every read verifies each retrieval again. For a CSV: its record's fields, the address it names (the Board's fixed
two-series download, see market_context.export_url), the HTTP reply it records, the file's size and SHA-256, the series
and units in the file's own header (market_context.parse_h15_csv) and that its rows lie in the requested range and not
after the day it was requested. For a package: its acquisition record against its folder and the package's size and
SHA-256, and its validation record's versions, package identity and every row and count (market_package); its dates
must not be after the day it was requested. A retrieval that does not verify is listed with the reason and not used;
nothing is repaired, refetched or replaced.

What a retrieval states. From its requested start to the last date it returned, a retrieval states, for every date and
each series, a value, ND (the source's no-value marker) or no row. After its last returned date it states nothing:
those dates were not in the reply. A package has no requested range: it states the dates both series cover, from the
later of their first observations to the earlier of their last, and nothing after them up to the day before it was
requested. Retrievals made at different times are separate versions and stay separate on disk; event views
(event_context) combine their statements for a date only when they are identical, so a package and a CSV that disagree
on a date are shown as disagreeing.

Retrieval attempts are recorded under attempts/<plan SHA-256>/: <n>.started.json is written before a request is sent
and <n>.outcome.json after it; both are created exclusively and never rewritten. An attempt without an outcome stopped
before its outcome was recorded. Reads never take the write lock, create a folder or write anything.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile

from . import market_context, market_package
from .context_lock import BundleBusy, bundle_write_lock

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "data" / "market-context"  # Runtime records; data/ is ignored by git.
RETRIEVALS, ATTEMPTS, EVENTS, PACKAGES = "retrievals", "attempts", "events", "packages"
LIFECYCLE_ATTEMPTS = "lifecycle-attempts"  # Outcome-data downloads approved from the Hypotheses page (lifecycle plans).
RETRIEVAL_VERSION = "market-retrieval-0.1"
ATTEMPT_VERSION = "market-retrieval-attempt-0.2"  # 0.2: attempts to download the release package.
ATTEMPT_VERSIONS = ("market-retrieval-attempt-0.1", ATTEMPT_VERSION)  # 0.1: the two-series CSV, still read.
SOURCE_ID = "board-h15-ddp-two-series"  # The Board's direct download of exactly the two series (one CSV).
SOURCE_FILE, RECORD_FILE = "source.csv", "retrieval.json"
RECORD_FIELDS = {"retrieval_version", "retrieval_id", "source", "url", "requested_start", "requested_end",
                 "requested_at", "received_at", "http_status", "content_type", "response_date", "bytes", "sha256",
                 "plan_sha256", "attempt", "client"}
RETRIEVAL_ID = re.compile(r"r\d{8}T\d{12}Z-[0-9a-f]{12}")
PLAN_SHA = re.compile(r"[0-9a-f]{64}")
ADDRESS_RANGE = re.compile(r"&from=(\d{2})/(\d{2})/(\d{4})&to=(\d{2})/(\d{2})/(\d{4})&")
CLOCK_SKEW_SECONDS = 300  # As for the bundle's downloads: request, receipt and the server's Date must agree.


class StoreRefused(ValueError):
    """A record that does not verify, or a write that is not allowed; ``status`` is the HTTP status that says why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class StoreBusy(StoreRefused):
    def __init__(self):
        super().__init__(409, "Another market-data retrieval is running; nothing was requested. Wait for it to finish "
                              "and preview again")


@dataclass(frozen=True)
class Retrieval:
    """One verified download: what it states for each series and date, and its provenance."""
    id: str
    origin: str  # "private", "bundle" or "package"
    requested_start: date
    requested_end: date
    requested_on: date  # The New York date of the request.
    first_row: date
    last_row: date
    rows: dict = field(repr=False)  # series id -> {date: the source's exact text, "ND" included}
    provenance: dict = field(repr=False)

    def states(self, day: date) -> bool:
        return self.requested_start <= day <= self.last_row

    def pending(self, day: date) -> bool:
        """After the last date it returned, inside its requested range: it says nothing about these dates."""
        return self.last_row < day <= self.requested_end


def requested_range(url: str) -> tuple[date, date]:
    """The range a download address names, refused unless the address is exactly the Board's two-series download."""
    match = ADDRESS_RANGE.search(url) if isinstance(url, str) else None
    try:
        start = date(int(match[3]), int(match[1]), int(match[2])) if match else None
        end = date(int(match[6]), int(match[4]), int(match[5])) if match else None
    except ValueError:
        start = end = None
    if start is None or end < start or market_context.export_url(start, end) != url:
        raise StoreRefused(500, "The download address is not the Board's two-series H.15 download")
    return start, end


def new_york_day(moment: datetime) -> date:
    return moment.astimezone(market_context.NEW_YORK).date()


def check_reply(record: dict, data: bytes, label: str) -> tuple[date, date, date, dict]:
    """A recorded reply and its bytes: the address, a plain CSV 200, times that agree, the size and SHA-256, and rows
    of exactly the two series inside the requested range and not after the day of the request. Returns (requested
    start, end, the request's New York date, the parsed rows)."""
    start, end = requested_range(record["url"])
    if type(record["http_status"]) is not int or record["http_status"] != 200 or \
            str(record["content_type"]).split(";")[0].strip().lower() != "text/csv":
        raise StoreRefused(500, f"{label} is not a text/csv reply with HTTP status 200")
    requested = market_context._moment(record["requested_at"], f"{label}'s requested_at", 500)
    received = market_context._moment(record["received_at"], f"{label}'s received_at", 500)
    try:
        server = parsedate_to_datetime(record["response_date"])
    except (TypeError, ValueError):
        raise StoreRefused(500, f"{label} has no valid HTTP Date") from None
    if received < requested or server.utcoffset() is None or \
            abs((server - requested).total_seconds()) > CLOCK_SKEW_SECONDS or \
            abs((server - received).total_seconds()) > CLOCK_SKEW_SECONDS:
        raise StoreRefused(500, f"{label} has request, receipt and server times that disagree")
    if (record["bytes"], record["sha256"]) != (len(data), market_context.sha256(data)):
        raise StoreRefused(500, f"{label} does not match its file's size and SHA-256")
    rows = market_context.parse_h15_csv(data)
    first, last = next(iter(rows.values()))[0][0], next(iter(rows.values()))[-1][0]
    requested_on = new_york_day(requested)
    if first < start or last > end:
        raise StoreRefused(500, f"{label} has rows outside its requested range {start} to {end}")
    if last > requested_on:
        raise StoreRefused(500, f"{label} has a row dated {last}, after the day it was requested ({requested_on})")
    return start, end, requested_on, {series_id: {day: raw for day, raw, _ in series_rows}
                                      for series_id, series_rows in rows.items()}


def _retrieval(identifier: str, origin: str, record: dict, data: bytes, label: str, provenance: dict) -> Retrieval:
    try:
        start, end, requested_on, rows = check_reply(record, data, label)
    except market_context.ContextRefused as exc:
        raise StoreRefused(500, f"{label}: {exc}") from None
    days = sorted(next(iter(rows.values())))
    return Retrieval(identifier, origin, start, end, requested_on, days[0], days[-1], rows,
                     {**provenance, "requested_start": start.isoformat(), "requested_end": end.isoformat(),
                      "returned_first": days[0].isoformat(), "returned_last": days[-1].isoformat(), "rows": len(days),
                      **{key: record[key] for key in ("url", "requested_at", "received_at", "http_status",
                                                      "content_type", "response_date", "bytes", "sha256")}})


def _private(folder: Path) -> Retrieval:
    label = f"Private retrieval {folder.name}"
    if not RETRIEVAL_ID.fullmatch(folder.name):
        raise StoreRefused(500, f"{label} has a folder name that is not a retrieval ID")
    try:
        record = market_context._strict_json((folder / RECORD_FILE).read_bytes(), f"{label}'s record", 500)
        data = (folder / SOURCE_FILE).read_bytes()
    except OSError as exc:
        raise StoreRefused(500, f"{label} cannot be read ({type(exc).__name__})") from None
    except market_context.ContextRefused as exc:
        raise StoreRefused(500, str(exc)) from None
    client = record.get("client")
    if set(record) != RECORD_FIELDS or record["retrieval_version"] != RETRIEVAL_VERSION or \
            record["retrieval_id"] != folder.name or record["source"] != SOURCE_ID or \
            not isinstance(record["plan_sha256"], str) or not PLAN_SHA.fullmatch(record["plan_sha256"]) or \
            type(record["attempt"]) is not int or record["attempt"] < 1 or not isinstance(client, dict) or \
            set(client) != {"user_agent", "transport"} or not all(isinstance(value, str) for value in client.values()):
        raise StoreRefused(500, f"{label}'s record does not have exactly the expected fields and values")
    if (record["requested_start"], record["requested_end"]) != tuple(
            day.isoformat() for day in requested_range(record["url"])):
        raise StoreRefused(500, f"{label}'s requested range does not match its address")
    return _retrieval(f"private:{folder.name}", "private", record, data, label, {
        "id": f"private:{folder.name}", "origin": "private", "origin_label": "Private retrieval, approved in this app",
        "file": f"{RETRIEVALS}/{folder.name}/{SOURCE_FILE}", "plan_sha256": record["plan_sha256"],
        "attempt": record["attempt"], "client": client})


def _bundle(bundle: Path) -> tuple[list[Retrieval], list[dict]]:
    """The committed bundle's downloads, verified in place: the index and each run's manifest and acquisition record
    by their SHA-256, then each download's file and record. Nothing is copied or written."""
    if not (bundle / market_context.INDEX).is_file():
        return [], []
    found, problems = [], []
    try:
        runs = market_context._read_index((bundle / market_context.INDEX).read_bytes(), 500)
    except (market_context.ContextRefused, OSError) as exc:
        return [], [{"retrieval": "bundle", "problem": f"The case-library bundle's index does not verify: {exc}"}]
    for run in runs:
        name = run["manifest"]
        try:
            manifest_bytes = (bundle / name).read_bytes()
            if market_context.sha256(manifest_bytes) != run["manifest_sha256"]:
                raise StoreRefused(500, f"{name} does not match the SHA-256 in the index")
            manifest = market_context._strict_json(manifest_bytes, name, 500)
            acquisition = manifest.get("acquisition") if isinstance(manifest.get("acquisition"), dict) else {}
            if acquisition.get("record") != market_context.record_name(run["run"]) or \
                    (manifest.get("source"), manifest.get("terms")) != (market_context.SOURCE, market_context.TERMS):
                raise StoreRefused(500, f"{name} names another acquisition record, source or terms")
            record_bytes = (bundle / acquisition["record"]).read_bytes()
            if market_context.sha256(record_bytes) != acquisition.get("record_sha256"):
                raise StoreRefused(500, f"{acquisition['record']} does not match its SHA-256 in {name}")
            parsed, downloads = market_context._acquisition(record_bytes, 500)
            contexts = manifest.get("contexts") if isinstance(manifest.get("contexts"), dict) else {}
        except (market_context.ContextRefused, StoreRefused, OSError) as exc:
            problems.append({"retrieval": f"bundle run {run['run']}",
                             "problem": f"Run {run['run']} of the case-library bundle does not verify: {exc}"})
            continue
        for case_id in contexts:
            identifier = f"bundle:run-{run['run']}:{case_id}"
            label = f"The case-library download for {case_id}"
            try:
                record = downloads.get(case_id)
                if not isinstance(record, dict) or set(record) != market_context.DOWNLOAD_FIELDS or \
                        record["file"] != f"{case_id}.csv":
                    raise StoreRefused(500, f"{label} has no complete download record")
                data = (bundle / "sources" / record["file"]).read_bytes()
                found.append(_retrieval(identifier, "bundle", record, data, label, {
                    "id": identifier, "origin": "bundle",
                    "origin_label": "Committed case-library download, read in place (never copied)",
                    "file": f"content/market-context/sources/{record['file']}", "run": run["run"], "case": case_id,
                    "manifest": name, "tool": parsed["tool"], "method": acquisition.get("method")}))
            except (StoreRefused, OSError) as exc:
                problems.append({"retrieval": identifier, "problem": str(exc)})
    return found, problems


def _client(record: dict) -> dict:
    """Who sent a package's request and through which network, as its record states it."""
    client, approval = record["client"], record["approval"]
    sent = client.get("request_headers_sent") if isinstance(client.get("request_headers_sent"), dict) else {}
    transport = client.get("transport")
    if not isinstance(transport, str):
        transport = ("network: the Board's server over HTTPS, by a one-off operator-approved download outside this app "
                     f"(approval {approval.get('approval_id')})") if approval.get("approval_id") else "not recorded"
    agent = client.get("user_agent") if isinstance(client.get("user_agent"), str) else sent.get("user-agent")
    return {"user_agent": agent if isinstance(agent, str) else "not recorded", "transport": transport}


def package_state(folder: Path) -> tuple[dict, Retrieval | None]:
    """One kept package: its summary, and its retrieval when the current parser version's validation accepted it.
    Raises StoreRefused for a package or validation record that does not verify. Reads only."""
    package_id = folder.name
    label = f"Package {package_id}"
    if not market_package.PACKAGE_ID.fullmatch(package_id):
        raise StoreRefused(500, f"{label} has a folder name that is not a package ID")
    try:
        record = market_package.strict_json((folder / market_package.ACQUISITION_FILE).read_bytes(),
                                            f"{label}'s acquisition record")
        size, digest = market_package.file_sha256(folder / market_package.PACKAGE_FILE)
        market_package.check_acquisition(record, package_id, size, digest)
        names = sorted(path.name for path in folder.iterdir() if path.name.startswith("validation-"))
        current = market_package.validation_name()
        validation = None
        if current in names:
            validation = market_package.check_validation(
                market_package.strict_json((folder / current).read_bytes(), f"{label}'s validation record"),
                package_id, digest)
    except OSError as exc:
        raise StoreRefused(500, f"{label} cannot be read ({type(exc).__name__})") from None
    except market_package.RecordRefused as exc:
        raise StoreRefused(500, str(exc)) from None
    summary = {"id": f"package:{package_id}", "package_id": package_id, "status": "acquired_unvalidated",
               "detail": None, "file": f"{PACKAGES}/{package_id}/{market_package.PACKAGE_FILE}", "url": record["url"],
               "requested_at": record["requested_at"], "received_at": record["received_at"], "bytes": size,
               "sha256": digest, "last_modified": record["headers"].get("last-modified"),
               "acquisition_method": record["acquisition_method"], "client": _client(record),
               "parser_version": market_package.PARSER_VERSION, "validated_at": None, "release_prepared": None,
               "coverage": None, "series": None, "other_validations": [name for name in names if name != current],
               "marker_findings": (record.get("marker_findings") or {}).get("total")}
    if validation is None:
        return summary, None
    summary["validated_at"] = validation["validated_at"]
    if validation["status"] == "refused":
        return {**summary, "status": "refused", "detail": validation["detail"]}, None
    held = market_package.held(validation)
    requested_on = new_york_day(market_package.moment(record["requested_at"], "requested_at"))
    latest = max(date.fromisoformat(item["last"]) for item in validation["series"].values())
    if latest > requested_on:
        raise StoreRefused(500, f"{label} states {latest}, after the day it was requested ({requested_on})")
    dates = {day for rows in held.rows.values() for day in rows if held.first <= day <= held.last}
    summary.update(status="accepted", release_prepared=validation["header"].get("prepared"),
                   coverage=validation["coverage"],
                   series={series_id: {key: item[key] for key in ("first", "last", "observations", "no_value",
                                                                   "missing_weekdays")}
                           for series_id, item in validation["series"].items()})
    end = max(held.last, requested_on - timedelta(days=1))
    provenance = {**summary, "origin": "package",
                  "origin_label": "H.15 release package (XML), kept privately and validated locally",
                  "requested_start": held.first.isoformat(), "requested_end": end.isoformat(),
                  "returned_first": held.first.isoformat(), "returned_last": held.last.isoformat(), "rows": len(dates),
                  "http_status": record["http_status"], "content_type": record["headers"].get("content-type"),
                  "response_date": record["headers"].get("date"), "data_entry": validation["data_entry"],
                  "validation_version": validation["validation_version"]}
    return summary, Retrieval(f"package:{package_id}", "package", held.first, end, requested_on, held.first, held.last,
                              held.rows, provenance)


def local_data(store: Path, bundle: Path | None = market_context.BUNDLE_DIR) -> tuple[list[Retrieval], list[dict],
                                                                                      list[dict]]:
    """Every retrieval that verifies (committed bundle first, then private CSVs by ID, then accepted packages by ID, so
    each kind by request time), the problems of those that do not, and every kept package's summary. Reads only."""
    found, problems = _bundle(bundle) if bundle is not None else ([], [])
    folder = store / RETRIEVALS
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name.startswith("."):
            continue  # Staging folders of a write in progress, or one that stopped; never retrievals.
        try:
            found.append(_private(path))
        except StoreRefused as exc:
            problems.append({"retrieval": f"private:{path.name}", "problem": str(exc)})
    packages = []
    folder = store / PACKAGES
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name.startswith(".") or not path.is_dir():
            continue  # Staging folders, and the one-off acquisition's attempt records; never packages.
        try:
            summary, retrieval = package_state(path)
        except StoreRefused as exc:
            problems.append({"retrieval": f"package:{path.name}", "problem": str(exc)})
            continue
        packages.append(summary)
        if retrieval is not None:
            found.append(retrieval)
    return found, problems, packages


def retrievals(store: Path, bundle: Path | None = market_context.BUNDLE_DIR) -> tuple[list[Retrieval], list[dict]]:
    """Every retrieval that verifies and the problems of those that do not (see local_data). Reads only."""
    found, problems, _ = local_data(store, bundle)
    return found, problems


# ---------------------------------------------------------------- writing (only under the store's write lock)

@contextmanager
def write_lock(store: Path):
    """The store's cross-process write lock, never waited for: a second writer is refused (StoreBusy)."""
    try:
        with bundle_write_lock(store):
            yield
    except BundleBusy:
        raise StoreBusy() from None


def _read_only(path: Path) -> None:
    path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def write_exclusive(path: Path, value: dict) -> None:
    """Creates a JSON record that must not exist yet (FileExistsError otherwise), complete or absent, read-only.

    The bytes are written to a hidden temporary file and then hard-linked to the record's name, which fails if the
    name exists; readers skip hidden names. Only a filesystem without hard links falls back to an exclusive create."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError:  # No hard links here: an exclusive create is the closest equivalent.
            with path.open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
    finally:
        os.remove(temporary)
    _read_only(path)


def write_retrieval(store: Path, record: dict, data: bytes) -> str:
    """Writes one new retrieval: a staging folder, then one rename into place, so it is complete or absent. An existing
    retrieval is never replaced."""
    folder = store / RETRIEVALS
    folder.mkdir(parents=True, exist_ok=True)
    staging = folder / f".staging-{secrets.token_hex(8)}"
    staging.mkdir()
    try:
        (staging / SOURCE_FILE).write_bytes(data)
        (staging / RECORD_FILE).write_bytes((json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        for name in (SOURCE_FILE, RECORD_FILE):
            _read_only(staging / name)
        target = folder / record["retrieval_id"]
        if target.exists():
            raise StoreRefused(409, f"Retrieval {record['retrieval_id']} already exists; nothing was replaced")
        staging.rename(target)
    finally:
        if staging.exists():
            for path in staging.iterdir():
                path.chmod(stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(staging, ignore_errors=True)
    return record["retrieval_id"]


def package_staging(store: Path) -> Path:
    """A new, hidden folder for one package download; readers skip it."""
    folder = store / PACKAGES
    folder.mkdir(parents=True, exist_ok=True)
    staging = folder / f".staging-{secrets.token_hex(8)}"
    staging.mkdir()
    return staging


def discard(staging: Path) -> None:
    if staging.exists():
        for path in staging.iterdir():
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
        shutil.rmtree(staging, ignore_errors=True)


def write_package(store: Path, staging: Path, record: dict) -> str:
    """Keeps one downloaded package: its acquisition record beside the staged package.zip, both read-only, then one
    rename into packages/<id>, so it is complete or absent. An existing package is never replaced."""
    (staging / market_package.ACQUISITION_FILE).write_bytes(
        (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    for name in (market_package.PACKAGE_FILE, market_package.ACQUISITION_FILE):
        _read_only(staging / name)
    target = store / PACKAGES / record["package_id"]
    if target.exists():
        raise StoreRefused(409, f"Package {record['package_id']} already exists; nothing was replaced")
    staging.rename(target)
    return record["package_id"]


def write_validation(store: Path, record: dict) -> None:
    """A package's validation record for one parser version, created once (FileExistsError if it exists)."""
    write_exclusive(store / PACKAGES / record["package_id"] / market_package.validation_name(record["parser_version"]),
                    record)


def started_path(store: Path, plan_sha: str, number: int, folder: str = ATTEMPTS) -> Path:
    return store / folder / plan_sha / f"{number}.started.json"


def outcome_path(store: Path, plan_sha: str, number: int, folder: str = ATTEMPTS) -> Path:
    return store / folder / plan_sha / f"{number}.outcome.json"


ATTEMPT_NAME = re.compile(r"([1-9]\d{0,3})\.(started|outcome)\.json")


def read_attempts(store: Path, folder: str = ATTEMPTS, versions: tuple = ATTEMPT_VERSIONS) -> list[dict]:
    """Every recorded attempt, oldest first: what was started, and its outcome or that none was recorded. A record
    that cannot be read is shown as such, never repaired. Reads only."""
    attempts = []
    root = store / folder
    for plan_dir in sorted(root.iterdir()) if root.is_dir() else []:
        if not plan_dir.is_dir() or not PLAN_SHA.fullmatch(plan_dir.name):
            continue
        numbers = sorted({int(match[1]) for path in plan_dir.iterdir() if (match := ATTEMPT_NAME.fullmatch(path.name))})
        for number in numbers:
            entry = {"plan_sha256": plan_dir.name, "number": number, "started": None, "outcome": None, "problem": None}
            for part in ("started", "outcome"):
                path = plan_dir / f"{number}.{part}.json"
                if not path.exists():
                    continue
                try:
                    value = market_context._strict_json(path.read_bytes(), path.name, 500)
                except (market_context.ContextRefused, OSError) as exc:
                    entry["problem"] = f"{path.name} cannot be read: {exc}"
                    continue
                if value.get("attempt_version") not in versions or value.get("plan_sha256") != plan_dir.name or \
                        value.get("number") != number:
                    entry["problem"] = f"{path.name} does not describe attempt {number} of this work"
                    continue
                entry[part] = value
            if entry["started"] is None and entry["problem"] is None:
                entry["problem"] = "An outcome was recorded without the record of its start"
            attempts.append(entry)
    return sorted(attempts, key=lambda entry: ((entry["started"] or {}).get("started_at") or "", entry["number"]))


def numbers_used(store: Path, plan_sha: str, folder: str = ATTEMPTS) -> list[int]:
    folder = store / folder / plan_sha
    return sorted({int(match[1]) for path in folder.iterdir() if (match := ATTEMPT_NAME.fullmatch(path.name))}) \
        if folder.is_dir() else []

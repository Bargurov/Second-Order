"""Market-implied rate path for a saved Federal Reserve monetary-policy event: a separate, private event record derived
from a retained Atlanta Fed Market Probability Tracker workbook (rate_workbook), and the verified view the event
overview and the research page show.

What it shows (MEASURE): for one observation date before the statement, the first four three-month SOFR reference
windows the workbook lists, each with the mean and the 25th and 75th percentiles of the estimated distribution of
average SOFR over that window, converted from basis points to percent by an exact decimal shift. The observation date
follows RULE. The workbook gives no meeting-specific pricing, so that measurement is stated as unavailable (MEETING);
its cut and hike probabilities describe average SOFR against the target range over a window, never read as decision
probabilities, and are not kept. Nothing is compared with the decision, differenced or scored.

Records, under data/rate-context/ (ignored by git), each created once, read-only and never rewritten:
- sources/<source ID>/: workbook.xlsx, the exact bytes of a workbook the operator already holds; acquisition.json, what
  is known about how and when it was obtained (no HTTP status, headers, server time or publication time were recorded,
  and they stay unknown); validation-<parser version>.json, the checked description (license paragraphs, definitions,
  header, row count and every observation date). ``retain`` writes them only after the workbook matches the SHA-256
  the operator names and passes the reader; it never downloads.
- events/capture-<capture ID>/<n>.json: one saved event's context, bound to the capture (its request and source
  SHA-256, event fields and supplied publication time), its recorded Inbox origin (the link file's SHA-256 and the entry
  version it names) or the absence of one, and the source (workbook and validation-record SHA-256). ``prepare`` derives
  it from the workbook; run again it derives it again and compares, and writes a new version only for another source.

The context is not part of any model request: requests are built from the capture's own fields and text only, and
nothing here is sent, frozen, evaluated or scored. Reads (view) never fetch, prepare or write. They verify the
workbook's bytes against their SHA-256, the acquisition and validation records, the capture and origin bindings, the
selection against the recorded observation dates and the supplied publication time, and every value's form; a read does
not parse the workbook again, which is what ``prepare`` does.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import secrets

from . import event_context, event_intake, event_links, market_context, market_store, rate_workbook
from .market_context import NEW_YORK, ContextRefused

ROOT = Path(__file__).resolve().parent.parent
RATE_DIR = ROOT / "data" / "rate-context"  # Runtime records; data/ is ignored by git.
SOURCES, EVENTS = "sources", "events"
WORKBOOK_FILE, ACQUISITION_FILE = "workbook.xlsx", "acquisition.json"
ACQUISITION_VERSION = "rate-source-acquisition-0.1"
VALIDATION_VERSION = "rate-source-validation-0.1"
CONTEXT_VERSION = "rate-path-context-0.1"
VIEW_VERSION = "rate-path-view-0.1"
WINDOWS = 4
FAMILY = "fed-monetary"
SOURCE_ID = re.compile(r"mpt-[0-9a-f]{16}")
SHA256 = re.compile(r"[0-9a-f]{64}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_METHOD = 500
SOURCE = {
    "publisher": "Federal Reserve Bank of Atlanta", "product": "Market Probability Tracker",
    "file": "MPT historical data (mpt_histdata.xlsx)",
    "page_url": "https://www.atlantafed.org/research-and-data/data/market-probability-tracker",
    "file_url": ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/"
                 "market-probability-tracker/mpt_histdata.xlsx"),
    "attribution": "Federal Reserve Bank of Atlanta, Market Probability Tracker, estimated from CME 3-month SOFR options",
}
UNKNOWN_NOTE = ("Supplied as an already downloaded file. Its HTTP status, response headers, server time and original "
                "publication time were not recorded and are unknown; the date it was obtained is the operator's "
                "statement.")
MEASURE = {
    "id": "mpt-average-sofr-window-1",
    "statement": ("For each three-month reference window: the mean and the 25th and 75th percentiles of the "
                  "distribution of average SOFR over that window, as the tracker estimated it from CME 3-month SOFR "
                  "options on the observation date. The workbook states them in basis points; they are shown in percent "
                  "by an exact decimal shift (100 bp = 1 percentage point), without rounding."),
}
RULE = {
    "id": "latest-observation-before-publication-date-1",
    "statement": ("The observation is the latest date in the workbook strictly before the statement's publication date "
                  "in New York. An observation dated the publication date itself is never used: the workbook gives "
                  "dates without a time of day, so it cannot show whether that day's estimate came before or after the "
                  "release. A selection is made only when the workbook also holds an observation dated on or after the "
                  "publication date, so the chosen date is not merely the end of the file's coverage. The windows are "
                  "the first four the workbook lists for that observation, in order of their start dates and labelled "
                  "as the workbook labels them; a value the workbook does not list is shown as unavailable, and no "
                  "later window takes its place."),
}
MEETING = {
    "state": "unavailable",
    "statement": ("This workbook gives no market-implied pricing for the policy decision announced in this statement. "
                  "Its distributions describe average SOFR over three-month windows, not that meeting's decision."),
}
SEPARATE = ("A separate event record, prepared by an explicit local command. Saved model requests for this event are "
            "built from its headline, address, publication time and captured text only; this context was not part of "
            "any of them, and no model received it.")
LIMITS = (
    "A window's start date begins a three-month averaging period for SOFR; it is not an FOMC meeting date.",
    "Average SOFR over a window is not the federal funds target range, or any rate on a particular date.",
    "No probability of a meeting decision is shown or derived. The workbook's cut and hike probabilities describe "
    "average SOFR over a window against the target range; they are not kept or shown.",
    "No surprise measure, change or score is computed from these averages, and they are not compared with the decision.",
    "The workbook was obtained after the event. It gives observation dates without a time of day, original publication "
    "time or retained vintage, so it does not show what was available before the announcement; values may have been "
    "revised since.",
    "Descriptive context only: not a forecast, a causal attribution, a trading signal or a research score. Nothing here "
    "is frozen, scored, attached to a draft or analysis, or added to research summaries.",
    "A different measure from the Treasury yields under Market context; the two are kept apart and never combined.",
)
STATEMENT = ("Derived from a retained workbook by an explicit local command; the capture, its request, its origin record "
             "and every analysis record were only read.")
DEFINITIONS_SHOWN = ("reference_start", "target_range", "Rate: mean", "Rate: 25th percentile", "Rate: 75th percentile",
                     "Prob: cut", "Prob: hike")
ACQUISITION_FIELDS = {"acquisition_version", "source_id", "file", "bytes", "sha256", "source", "obtained_on", "method",
                      "supplied_name", "retained_at", "http_status", "response_headers", "publication_time", "note"}
VALIDATION_FIELDS = {"validation_version", "source_id", "sha256", "bytes", "parser", "validated_at", "entries", "sheets",
                     "date_system", "license", "dictionary", "data"}
RECORD_FIELDS = {"context_version", "key", "version", "capture", "origin", "source", "rule", "selection", "observation",
                 "prepared_at", "supersedes", "statement"}
SELECTION_FIELDS = {"state", "publication_new_york_date", "observation_date", "calendar_days_before",
                    "same_day_observation", "first_observation", "last_observation", "reason"}
REASONS = ("none_before", "none_on_or_after")


class RateRefused(ValueError):
    """A request or record that does not verify; ``status`` is the HTTP status that says why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    rate: Path  # sources/ and events/ of this context
    intake: Path  # the saved captures, only read
    links: Path  # their recorded Inbox origins, only read


def folders_in(data: Path) -> Folders:
    return Folders(data / RATE_DIR.name, data / "intake", data / "event-links")


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plain(raw: str) -> str:
    """A value cell's decimal without its padding (rate_workbook.decimal_text), refused when it is not one."""
    text = rate_workbook.decimal_text(raw)
    if text is None:
        raise RateRefused(500, f"{raw!r} is not a plain decimal")
    return text


def percent(bp: str | int) -> str:
    """Basis points to percent by moving the decimal point two places: exact, never rounded."""
    return format(Decimal(bp).scaleb(-2), "f")


def _json(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _strict(data: bytes, label: str) -> dict:
    try:
        return market_context._strict_json(data, label, 500)
    except ContextRefused as exc:
        raise RateRefused(500, str(exc)) from None


def _day(value: object) -> bool:
    try:
        return isinstance(value, str) and rate_workbook.DAY.fullmatch(value) is not None and \
            date.fromisoformat(value) is not None
    except ValueError:
        return False


# ---------------------------------------------------------------- the capture and its origin

def _capture(folders: Folders, capture_id: object) -> dict:
    """What a context is bound to: the verified capture's identity, event fields and supplied publication time."""
    if not isinstance(capture_id, str) or not event_intake.CAPTURE_ID.fullmatch(capture_id):
        raise RateRefused(404, "Unknown capture ID")
    try:
        record = event_intake.verified(folders.intake, capture_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        raise RateRefused(404, f"This saved event cannot be read: {exc}") from None
    supplied = record["times"]["published_at_as_supplied"]
    moment = datetime.fromisoformat(supplied)
    if moment.utcoffset() is None:
        raise RateRefused(422, "This saved event's publication time has no explicit UTC offset")
    local = moment.astimezone(NEW_YORK)
    offset = local.strftime("%z")
    return {"capture_id": capture_id, "request_sha256": record["request"]["sha256"],
            "source_sha256": record["source"]["sha256"], "event": record["event"],
            "family": event_context.capture_family(record["event"]["source_url"]),
            "published_at_as_supplied": supplied, "published_at": record["times"]["published_at"],
            "new_york_date": local.date().isoformat(), "new_york_time": local.strftime("%H:%M"),
            "new_york_offset": f"{offset[:3]}:{offset[3:]}"}


def _origin(folders: Folders, capture_id: str) -> dict:
    """The capture's recorded Inbox origin as it stands now, or that it has none. Raises when it does not verify."""
    path = event_links.path_for(folders.links, capture_id)
    if not path.exists():
        return {"state": "none"}
    try:
        link = event_links.verified_link(folders.links, capture_id, folders.intake)
        data = path.read_bytes()
    except event_links.UNVERIFIED as exc:
        raise RateRefused(409, f"The capture's recorded Inbox origin does not verify ({exc})") from None
    inbox = link["inbox"]
    return {"state": "verified", "link_sha256": sha256(data), "item_id": inbox["item_id"],
            "content_sha256": inbox["content_sha256"], "version": inbox["version"], "versions": inbox["versions"],
            "title": inbox["title"]}


# ---------------------------------------------------------------- retained sources

def validation_name() -> str:
    return f"validation-{rate_workbook.PARSER_VERSION}.json"


def retained_ids(rate: Path) -> list[str]:
    folder = rate / SOURCES
    return sorted(path.name for path in folder.iterdir() if path.is_dir() and SOURCE_ID.fullmatch(path.name)) \
        if folder.is_dir() else []


def retain(workbook: Path, expected_sha256: str, obtained_on: date, method: str, rate: Path, clock=now) -> dict:
    """Keep a workbook the operator already holds: exact bytes, acquisition and validation records, created once and
    read-only, only after it matches the named SHA-256 and passes the reader. Never downloads anything."""
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise RateRefused(422, "Name the expected SHA-256 as 64 lowercase hexadecimal characters")
    if not isinstance(method, str) or not method.strip() or len(method) > MAX_METHOD or CONTROL.search(method):
        raise RateRefused(422, f"Say how the workbook was obtained in at most {MAX_METHOD} characters on one line")
    data = workbook.read_bytes()
    digest = sha256(data)
    if digest != expected_sha256:
        raise RateRefused(409, f"The workbook's SHA-256 is {digest}, not the {expected_sha256} you named; nothing was "
                               "retained")
    source_id = f"mpt-{digest[:16]}"
    if (rate / SOURCES / source_id).exists():
        source = verified_source(rate, source_id)
        recorded = source["acquisition"]
        if (recorded["obtained_on"], recorded["method"]) != (obtained_on.isoformat(), method.strip()):
            raise RateRefused(409, f"This workbook is already retained as obtained on {recorded['obtained_on']} "
                                   f"({recorded['method']}); its record is never rewritten, and nothing was changed")
        return {"retained_now": False, "source_id": source_id, "sha256": digest,
                "rows": source["validation"]["data"]["rows"], "note": "Already retained; it verifies unchanged."}
    (rate / SOURCES).mkdir(parents=True, exist_ok=True)
    staging = rate / SOURCES / f".staging-{secrets.token_hex(8)}"
    staging.mkdir()
    try:
        (staging / WORKBOOK_FILE).write_bytes(data)
        try:
            summary, _ = rate_workbook.read(staging / WORKBOOK_FILE)
        except rate_workbook.WorkbookRefused as exc:
            raise RateRefused(422, f"The workbook was refused, so nothing was retained: {exc}") from None
        if obtained_on.isoformat() < summary["data"]["last"]:
            raise RateRefused(422, f"The workbook holds observations up to {summary['data']['last']}, after the "
                                   f"{obtained_on.isoformat()} it was said to be obtained; nothing was retained")
        moment = stamp(clock())
        acquisition = {"acquisition_version": ACQUISITION_VERSION, "source_id": source_id, "file": WORKBOOK_FILE,
                       "bytes": len(data), "sha256": digest, "source": SOURCE, "obtained_on": obtained_on.isoformat(),
                       "method": method.strip(), "supplied_name": workbook.name, "retained_at": moment,
                       "http_status": None, "response_headers": None, "publication_time": None, "note": UNKNOWN_NOTE}
        validation = {"validation_version": VALIDATION_VERSION, "source_id": source_id, "sha256": digest,
                      "bytes": len(data), "validated_at": moment, **summary}
        (staging / ACQUISITION_FILE).write_bytes(_json(acquisition))
        (staging / validation_name()).write_bytes(_json(validation))
        for name in (WORKBOOK_FILE, ACQUISITION_FILE, validation_name()):
            market_store._read_only(staging / name)
        staging.rename(rate / SOURCES / source_id)
    finally:
        market_store.discard(staging)
    return {"retained_now": True, "source_id": source_id, "sha256": digest, "rows": summary["data"]["rows"],
            "first_observation": summary["data"]["first"], "last_observation": summary["data"]["last"],
            "note": "Local work only: nothing was fetched."}


def verified_source(rate: Path, source_id: str) -> dict:
    """A retained workbook with its acquisition and current validation record, all checked again. Reads only."""
    folder = rate / SOURCES / source_id if isinstance(source_id, str) and SOURCE_ID.fullmatch(source_id) else None
    if folder is None or not folder.is_dir():
        raise RateRefused(404, f"No retained workbook {source_id!r}")
    label = f"Retained workbook {source_id}"
    names = {path.name for path in folder.iterdir()}
    required = {WORKBOOK_FILE, ACQUISITION_FILE, validation_name()}
    if not required <= names or any(name not in required and not name.startswith("validation-") for name in names):
        raise RateRefused(500, f"{label}'s folder does not hold exactly its workbook, acquisition record and a "
                               f"validation record for {rate_workbook.PARSER_VERSION}")
    data = (folder / WORKBOOK_FILE).read_bytes()
    digest = sha256(data)
    acquisition = _strict((folder / ACQUISITION_FILE).read_bytes(), f"{label}'s acquisition record")
    if set(acquisition) != ACQUISITION_FIELDS or acquisition["acquisition_version"] != ACQUISITION_VERSION or \
            (acquisition["source_id"], acquisition["file"], acquisition["source"]) != (source_id, WORKBOOK_FILE, SOURCE) or \
            (acquisition["bytes"], acquisition["sha256"]) != (len(data), digest) or source_id != f"mpt-{digest[:16]}" or \
            not _day(acquisition["obtained_on"]) or not isinstance(acquisition["method"], str) or \
            (acquisition["http_status"], acquisition["response_headers"], acquisition["publication_time"]) != \
            (None, None, None):
        raise RateRefused(500, f"{label} does not match its acquisition record")
    validation_bytes = (folder / validation_name()).read_bytes()
    validation = _strict(validation_bytes, f"{label}'s validation record")
    try:
        dates = validation["data"]["observation_dates"]
        ordered = isinstance(dates, list) and len(dates) > 0 and all(_day(day) for day in dates) and \
            all(earlier < later for earlier, later in zip(dates, dates[1:]))
        ok = set(validation) == VALIDATION_FIELDS and validation["validation_version"] == VALIDATION_VERSION and \
            (validation["source_id"], validation["sha256"], validation["bytes"]) == (source_id, digest, len(data)) and \
            validation["parser"]["version"] == rate_workbook.PARSER_VERSION and \
            validation["sheets"] == list(rate_workbook.SHEETS) and validation["date_system"] == "1900" and \
            validation["license"]["statement"] == rate_workbook.LICENSE_STATEMENT and \
            rate_workbook.LICENSE_STATEMENT in validation["license"]["paragraphs"] and \
            validation["dictionary"]["description"] == rate_workbook.DESCRIPTION and \
            all(validation["dictionary"]["definitions"].get(name) == text
                for name, text in rate_workbook.DEFINITIONS.items()) and \
            validation["data"]["header"] == list(rate_workbook.HEADER) and ordered and \
            (validation["data"]["first"], validation["data"]["last"]) == (dates[0], dates[-1]) and \
            type(validation["data"]["rows"]) is int and validation["data"]["rows"] >= len(dates)
    except (KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise RateRefused(500, f"{label}'s validation record does not verify")
    return {"source_id": source_id, "path": folder / WORKBOOK_FILE, "sha256": digest, "bytes": len(data),
            "acquisition": acquisition, "validation": validation, "validation_sha256": sha256(validation_bytes)}


# ---------------------------------------------------------------- deriving one event's context

def select(dates: list[str], publication_day: str) -> dict:
    """RULE: the latest observation strictly before the publication date, given coverage on or after it."""
    before = [day for day in dates if day < publication_day]
    covered = any(day >= publication_day for day in dates)
    selection = {"state": "no_coverage", "publication_new_york_date": publication_day, "observation_date": None,
                 "calendar_days_before": None, "same_day_observation": publication_day in dates,
                 "first_observation": dates[0], "last_observation": dates[-1], "reason": None}
    if not before:
        return {**selection, "reason": "none_before"}
    if not covered:
        return {**selection, "reason": "none_on_or_after"}
    days = (date.fromisoformat(publication_day) - date.fromisoformat(before[-1])).days
    return {**selection, "state": "selected", "observation_date": before[-1], "calendar_days_before": days}


def _observation(groups: dict, day: str) -> dict:
    """The first WINDOWS reference windows the workbook lists for one observation, with the three statistics' rows."""
    targets = {item["target_range"] for group in groups.values() for item in group.values()}
    if len(targets) != 1:
        raise RateRefused(422, f"The rows of observation {day} state {len(targets)} different target ranges")
    target = targets.pop()
    windows = []
    for start in sorted(groups)[:WINDOWS]:
        group = groups[start]
        statistics = {key: ({"row": group[name]["row"], "raw": group[name]["raw"]} if name in group else None)
                      for key, name in rate_workbook.STATISTICS.items()}
        low, high = statistics["p25"], statistics["p75"]
        if low and high and Decimal(plain(low["raw"])) > Decimal(plain(high["raw"])):
            raise RateRefused(422, f"For observation {day}, window {start}, the 25th percentile is above the 75th")
        windows.append({"reference_start": start, "reference_start_serial": next(iter(group.values()))["serial"],
                        "statistics": statistics})
    return {"target_range": {"raw": target, "bps": list(rate_workbook.target_range(target))},
            "windows_listed": len(groups), "windows": windows}


def _derive(capture: dict, origin: dict, source: dict) -> dict:
    selection = select(source["validation"]["data"]["observation_dates"], capture["new_york_date"])
    observation = None
    if selection["state"] == "selected":
        day = selection["observation_date"]
        try:
            summary, collected = rate_workbook.read(source["path"], frozenset({day}))
        except rate_workbook.WorkbookRefused as exc:
            raise RateRefused(500, f"The retained workbook no longer reads: {exc}") from None
        if {key: summary[key] for key in ("license", "dictionary", "data")} != \
                {key: source["validation"][key] for key in ("license", "dictionary", "data")}:
            raise RateRefused(500, "The retained workbook reads differently from its validation record")
        observation = _observation(collected[day], day)
    return {"capture": capture, "origin": origin, "rule": RULE, "selection": selection, "observation": observation,
            "source": {"source_id": source["source_id"], "sha256": source["sha256"], "bytes": source["bytes"],
                       "validation_sha256": source["validation_sha256"], "parser_version": rate_workbook.PARSER_VERSION}}


def _content(record: dict) -> dict:
    return {key: record[key] for key in ("capture", "origin", "source", "rule", "selection", "observation")}


def prepare(capture_id: str, folders: Folders, source_id: str | None = None, clock=now) -> dict:
    """Derive one saved event's context from a retained workbook and save it as a new version, or confirm that the
    latest version is exactly what the same workbook gives again. Local work only; nothing is fetched or sent."""
    capture = _capture(folders, capture_id)
    if capture["family"] != FAMILY:
        raise RateRefused(422, "A market-implied rate path is prepared only for Federal Reserve monetary-policy press "
                               "releases; nothing was written")
    origin = _origin(folders, capture_id)
    retained = retained_ids(folders.rate)
    if source_id is None:
        if len(retained) != 1:
            raise RateRefused(409, "No workbook is retained; run rate-context retain first" if not retained else
                              f"{len(retained)} workbooks are retained; name one with --source")
        source_id = retained[0]
    source = verified_source(folders.rate, source_id)
    records = _records(folders.rate, capture_id)
    derived = _derive(capture, origin, source)
    key = f"capture-{capture_id}"
    if records and records[-1]["source"]["sha256"] == source["sha256"]:
        if _content(records[-1]) != _content(derived):
            raise RateRefused(409, f"Saved version {len(records)} differs from what the same workbook gives again; it "
                                   "was left unchanged")
        return {"saved_now": False, "version": len(records), **_summary(derived),
                "note": "Derived again from the same workbook: identical to the saved version. Nothing was written."}
    record = {"context_version": CONTEXT_VERSION, "key": key, "version": len(records) + 1, **derived,
              "prepared_at": stamp(clock()), "supersedes": len(records) or None, "statement": STATEMENT}
    try:
        market_store.write_exclusive(folders.rate / EVENTS / key / f"{record['version']}.json", record)
    except FileExistsError:
        raise RateRefused(409, "Another version was saved at the same moment; nothing was replaced") from None
    return {"saved_now": True, "version": record["version"], **_summary(derived),
            "note": "Local work only: nothing was fetched or sent."}


def _summary(derived: dict) -> dict:
    observation = derived["observation"] or {}
    return {"capture_id": derived["capture"]["capture_id"], "source_id": derived["source"]["source_id"],
            "state": derived["selection"]["state"], "observation_date": derived["selection"]["observation_date"],
            "windows": [window["reference_start"] for window in observation.get("windows", [])]}


# ---------------------------------------------------------------- reading

def _check_selection(selection: object) -> bool:
    if not isinstance(selection, dict) or set(selection) != SELECTION_FIELDS:
        return False
    if selection["state"] == "selected":
        return _day(selection["observation_date"]) and selection["reason"] is None and \
            type(selection["calendar_days_before"]) is int and selection["calendar_days_before"] >= 1
    return selection["state"] == "no_coverage" and selection["reason"] in REASONS and \
        selection["observation_date"] is None and selection["calendar_days_before"] is None


def _check_observation(observation: object, selected: bool) -> bool:
    if not selected:
        return observation is None
    if not isinstance(observation, dict) or set(observation) != {"target_range", "windows_listed", "windows"}:
        return False
    target, windows = observation["target_range"], observation["windows"]
    if not isinstance(target, dict) or set(target) != {"raw", "bps"} or \
            list(rate_workbook.target_range(target["raw"]) or ()) != target["bps"] or \
            type(observation["windows_listed"]) is not int or not isinstance(windows, list) or \
            len(windows) != min(WINDOWS, observation["windows_listed"]) or not windows:
        return False
    starts = []
    for window in windows:
        if not isinstance(window, dict) or set(window) != {"reference_start", "reference_start_serial", "statistics"} \
                or type(window["reference_start_serial"]) is not int or \
                rate_workbook.serial_day(window["reference_start_serial"]).isoformat() != window["reference_start"] or \
                not isinstance(window["statistics"], dict) or set(window["statistics"]) != set(rate_workbook.STATISTICS):
            return False
        for item in window["statistics"].values():
            if item is not None and (not isinstance(item, dict) or set(item) != {"row", "raw"} or
                                     type(item["row"]) is not int or item["row"] < 2 or
                                     rate_workbook.decimal_text(item["raw"]) is None):
                return False
        low, high = window["statistics"]["p25"], window["statistics"]["p75"]
        if low and high and Decimal(plain(low["raw"])) > Decimal(plain(high["raw"])):
            return False
        starts.append(window["reference_start"])
    return all(earlier < later for earlier, later in zip(starts, starts[1:]))


def _records(rate: Path, capture_id: str) -> list[dict]:
    """Every saved version for one capture, oldest first, each checked. Raises RateRefused when any does not."""
    key = f"capture-{capture_id}"
    folder = rate / EVENTS / key
    if not folder.is_dir():
        return []
    names = sorted((path.name for path in folder.iterdir() if not path.name.startswith(".")),
                   key=lambda name: (len(name), name))
    records = []
    for number, name in enumerate(names, start=1):
        if name != f"{number}.json":
            raise RateRefused(500, f"The saved rate-path versions are not numbered 1 to {len(names)} ({name})")
        record = _strict((folder / name).read_bytes(), f"Saved rate-path version {name}")
        try:
            ok = set(record) == RECORD_FIELDS and record["context_version"] == CONTEXT_VERSION and \
                record["key"] == key and record["version"] == number and \
                record["supersedes"] == (number - 1 if number > 1 else None) and record["rule"] == RULE and \
                record["statement"] == STATEMENT and record["capture"].get("capture_id") == capture_id and \
                isinstance(record["origin"], dict) and isinstance(record["source"], dict) and \
                _check_selection(record["selection"]) and \
                _check_observation(record["observation"], record["selection"]["state"] == "selected")
            market_context._moment(record["prepared_at"], "prepared_at", 500)
        except (KeyError, TypeError, AttributeError, RateRefused, ContextRefused, ArithmeticError):
            ok = False
        if not ok:
            raise RateRefused(500, f"Saved rate-path version {name} does not have the expected fields and values")
        records.append(record)
    return records


def _window_view(window: dict) -> dict:
    statistics = {}
    for key, item in window["statistics"].items():
        statistics[key] = None if item is None else {"bp": plain(item["raw"]), "percent": percent(plain(item["raw"])),
                                                     "raw": item["raw"], "row": item["row"]}
    return {"reference_start": window["reference_start"], "statistics": statistics}


def view(capture_id: str, folders: Folders) -> dict:
    """The rate path one saved event's pages show, verified on every read, or an explicit state: unsupported,
    not_prepared, unreadable (with the problem) or no_coverage. Reads only: nothing is fetched, prepared or written."""
    capture = _capture(folders, capture_id)
    base = {"view_version": VIEW_VERSION, "capture_id": capture_id, "state": "unsupported", "problem": None,
            "provider_called": False, "written": False,
            "publication": {key: capture[key] for key in ("published_at_as_supplied", "published_at", "new_york_date",
                                                          "new_york_time", "new_york_offset")},
            "measure": MEASURE, "rule": RULE, "meeting_specific": MEETING, "separate": SEPARATE, "limits": list(LIMITS),
            "source": SOURCE, "selection": None, "target_range": None, "windows": [], "windows_listed": None,
            "origin": None, "provenance": None, "license": None, "definitions": None, "versions": []}
    if capture["family"] != FAMILY:
        return base
    try:
        records = _records(folders.rate, capture_id)
    except (RateRefused, OSError) as exc:
        return {**base, "state": "unreadable", "problem": str(exc)}
    if not records:
        return {**base, "state": "not_prepared"}
    latest = records[-1]
    versions = [{"version": record["version"], "prepared_at": record["prepared_at"],
                 "source_id": record["source"].get("source_id")} for record in records]
    try:
        if latest["capture"] != capture:
            raise RateRefused(409, "The saved event's capture differs from the one this context was prepared for")
        if latest["origin"] != _origin(folders, capture_id):
            raise RateRefused(409, "The capture's Inbox origin differs from the one this context was prepared with")
        source = verified_source(folders.rate, latest["source"]["source_id"])
        if latest["source"] != {"source_id": source["source_id"], "sha256": source["sha256"], "bytes": source["bytes"],
                                "validation_sha256": source["validation_sha256"],
                                "parser_version": rate_workbook.PARSER_VERSION}:
            raise RateRefused(409, "The retained workbook or its validation record differs from the one this context "
                                   "was prepared from")
        validation = source["validation"]
        if latest["selection"] != select(validation["data"]["observation_dates"], capture["new_york_date"]):
            raise RateRefused(409, "The saved selection does not follow the rule for this workbook and publication date")
        observation = latest["observation"]
        windows = [_window_view(window) for window in observation["windows"]] if observation else []
    except (RateRefused, OSError) as exc:
        return {**base, "state": "unreadable", "problem": str(exc), "versions": versions}
    acquisition = source["acquisition"]
    definitions = validation["dictionary"]["definitions"]
    return {
        **base, "state": "available" if observation else "no_coverage", "selection": latest["selection"],
        "target_range": None if observation is None else {
            **observation["target_range"], "percent": [percent(bound) for bound in observation["target_range"]["bps"]]},
        "windows": windows, "windows_listed": observation["windows_listed"] if observation else None,
        "origin": latest["origin"], "versions": versions,
        "license": {"statement": rate_workbook.LICENSE_STATEMENT, "paragraphs": validation["license"]["paragraphs"]},
        "definitions": {"description": validation["dictionary"]["description"],
                        "fields": {name: definitions[name] for name in DEFINITIONS_SHOWN}},
        "provenance": {"source_id": source["source_id"], "sha256": source["sha256"], "bytes": source["bytes"],
                       "obtained_on": acquisition["obtained_on"], "method": acquisition["method"],
                       "supplied_name": acquisition["supplied_name"], "retained_at": acquisition["retained_at"],
                       "http_status": None, "response_headers": None, "publication_time": None,
                       "unknown": acquisition["note"], "parser_version": rate_workbook.PARSER_VERSION,
                       "validated_at": validation["validated_at"], "validation_sha256": source["validation_sha256"],
                       "workbook_rows": validation["data"]["rows"], "first_observation": validation["data"]["first"],
                       "last_observation": validation["data"]["last"], "record_version": latest["version"],
                       "prepared_at": latest["prepared_at"]},
    }

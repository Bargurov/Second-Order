"""Selected macro events and their private market context: which events this slice supports, the context date and its
convention, and the descriptive view of daily Treasury yields around that date.

Supported events. Entries of three Event Inbox feeds (Federal Reserve monetary-policy press releases, BLS Employment
Situation, BLS Consumer Price Index), current or retained, and saved Tracker captures whose official link is one of
those publishers' releases of the same kind. Energy and international-trade entries are outside this first slice: the
2-year and 10-year yields are not attached to them, and the page says so.

The context date is a New York calendar date (CONVENTION). A capture keeps the publication time and explicit UTC
offset its operator supplied; its context date is that instant's New York date, with nothing to confirm. A feed
timestamp is metadata, not a verified publication instant, so an Inbox entry has no context date until the user
confirms one and the convention: the page suggests the New York date of the feed's timestamp when it states an instant,
and nothing when it does not. No time or offset is invented. A confirmation is saved under
data/market-context/events/<event key>/<version>.json, created exclusively and never rewritten; a new date is a new
version, and earlier versions stay. A confirmation is bound to the entry version it was made for (the entry's content
fingerprint, inbox_archive.content_sha256): when the entry's content changes, the earlier confirmation is shown as being
for another version and no context date applies until the user confirms one for the version held now.

The view (build_view) is derived on every read from the saved event and the verified retrievals (market_store); it is
not stored. It shows each calendar date from 14 days before to 14 days after the context date with each series' value
or the reason there is none (a weekend, a SIFMA holiday, ND or no row in the source, not yet in the local data, a
future date, or retrieval versions that disagree), and descriptive changes in basis points from the expected session
before the context date to the first and fifth expected sessions after it (RULE). Nothing is interpolated, carried
forward or moved to another date. Reads contact no provider and write nothing.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import event_inbox, event_intake, inbox_archive, inbox_imports, market_context, market_store
from .market_calendar import calendar_identity, expected_sessions, load_exceptions
from .market_context import NEW_YORK, SERIES, VALUE_STATUSES, WEEKDAYS, WINDOW_DAYS, ContextRefused

CONTEXT_VERSION = "event-market-context-0.2"  # A confirmation of one entry version's context date (0.2: bound).
VIEW_VERSION = "event-market-context-view-0.1"
FAMILIES = {"fed-monetary": "Federal Reserve monetary policy", "bls-empsit": "BLS employment",
            "bls-cpi": "BLS inflation"}
OUTSIDE_NOTE = ("Energy and international-trade entries are outside this first slice. It pairs daily 2-year and "
                "10-year Treasury yields only with Federal Reserve monetary-policy and BLS employment and inflation "
                "releases, and does not attach them to other topics.")
UNSUPPORTED_CAPTURE = ("This saved event's official link is not a Federal Reserve monetary-policy press release or a "
                       "BLS Employment Situation or Consumer Price Index release, so it is outside this first slice.")
# A capture's family, from its official link: the publisher's own host and the path of that kind of release.
CAPTURE_LINKS = (
    ("fed-monetary", "www.federalreserve.gov", re.compile(r"/newsevents/pressreleases/monetary\d{8}[a-z]\.htm")),
    ("bls-empsit", "www.bls.gov", re.compile(r"/news\.release/(?:empsit\.(?:nr0|toc)|archives/empsit_\d{8})\.htm")),
    ("bls-cpi", "www.bls.gov", re.compile(r"/news\.release/(?:cpi\.(?:nr0|toc)|archives/cpi_\d{8})\.htm")),
)
CONVENTION = {
    "id": "new-york-calendar-date-1",
    "statement": ("The context date is a calendar date in New York (America/New_York). For a saved event it is the New "
                  "York date of the publication time and UTC offset its operator supplied; for an Event Inbox entry it "
                  "is the date the user confirmed. Daily H.15 values carry a date and no time of day, so dates are "
                  "compared as calendar dates and never converted through the reader's time zone."),
}
RULE = {
    "id": "endpoint-rule-1",
    "statement": ("Changes run from the expected session immediately before the context date to the first and to the "
                  "fifth expected sessions strictly after it, on the SIFMA US bond-market calendar; the context date's "
                  "own session is not an endpoint. Yields are quoted in percent, so each change is a difference in "
                  "basis points (1 bp = 0.01 percentage point), not a bond return. A missing endpoint stays "
                  "unavailable: no other date is selected, and nothing is interpolated or carried forward."),
}
LIMITS = (
    "These are descriptive observations: not an intraday reaction, a causal attribution, a hypothesis confirmation, a "
    "trading signal or a research score. Daily data cannot separate the release from other news on the same or nearby "
    "days.",
    "Each value carries a date only; the source gives no time of day, so nothing here shows whether a value came "
    "before or after the release.",
    "These are the Board's values as published when retrieved, not historical vintages; what was available on the "
    "context date could have differed.",
    "Nothing here is saved to research summaries, frozen, scored or attached to a draft or its review.",
)
INBOX_ID = re.compile(r"([a-z-]{1,40}):([0-9a-f]{20})")
CAPTURE_ID = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{12}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
KINDS = ("inbox", "capture")
EVENT_FIELDS = {"kind", "item_id", "source", "family", "publisher", "title", "link", "category", "source_kind",
                "attribution", "feed_timestamp", "retrieved_at", "history", "content_sha256"}
SHA256 = re.compile(r"[0-9a-f]{64}")
RECORD_FIELDS = {"context_version", "key", "version", "event", "context_date", "convention", "suggestion",
                 "confirmed_at", "supersedes"}
STATUS_WORDS = {
    "session_value": "observed", "session_missing": "the source gives no value (ND)",
    "session_absent": "the source has no row", "issuer_no_observation": "no observation, documented by the issuer",
    "not_held": "not in the local data", "after_retrieval": "after the last date its retrieval returned",
    "future": "today or later", "conflict": "retrieval versions disagree",
}


def today(clock) -> date:
    return clock().astimezone(NEW_YORK).date()


def event_key(kind: str, event_id: str) -> str:
    """A folder-safe key: inbox-<source>-<hex> or capture-<capture ID>. Refuses anything else."""
    if kind == "inbox":
        match = INBOX_ID.fullmatch(event_id) if isinstance(event_id, str) else None
        if not match or (match[1] not in event_inbox.SOURCES and match[1] not in inbox_imports.SOURCES):
            raise ContextRefused(404, "No Event Inbox entry has this identifier")
        return f"inbox-{match[1]}-{match[2]}"
    if kind == "capture" and isinstance(event_id, str) and CAPTURE_ID.fullmatch(event_id):
        return f"capture-{event_id}"
    raise ContextRefused(404, "No saved event has this identifier")


def parse_key(key: str) -> tuple[str, str]:
    if key.startswith("capture-") and CAPTURE_ID.fullmatch(key[8:]):
        return "capture", key[8:]
    match = re.fullmatch(r"inbox-([a-z-]{1,40})-([0-9a-f]{20})", key)
    if match and (match[1] in event_inbox.SOURCES or match[1] in inbox_imports.SOURCES):
        return "inbox", f"{match[1]}:{match[2]}"
    raise ContextRefused(422, f"{key!r} is not an event key")


def capture_family(link: str) -> str | None:
    parts = urlsplit(link)
    if parts.scheme != "https" or parts.query or parts.fragment:
        return None
    return next((family for family, host, path in CAPTURE_LINKS
                 if parts.hostname == host and parts.port is None and path.fullmatch(parts.path)), None)


def _suggestion(timestamp: dict) -> tuple[dict | None, str | None]:
    """The New York date of the feed's instant, offered for confirmation; or why there is none."""
    instant = timestamp.get("instant_utc")
    if not instant:
        return None, timestamp.get("problem") or "The feed's timestamp states no instant."
    moment = datetime.fromisoformat(instant).astimezone(NEW_YORK)
    return {"date": moment.date().isoformat(), "new_york_time": moment.strftime("%H:%M"),
            "utc_offset": moment.strftime("%z")[:3] + ":" + moment.strftime("%z")[3:], "feed_raw": timestamp.get("raw"),
            "basis": "The New York date of the feed's timestamp, which is metadata, not a verified publication "
                     "instant: check the date against the release before confirming it."}, None


def _inbox_item(item_id: str, inbox: Path) -> dict | None:
    view = event_inbox.inbox_view(inbox)
    return next((item for item in view["items"] + view["retained"] + view["imported"] if item["id"] == item_id), None)


def _snapshot(item: dict) -> dict:
    """What a confirmation keeps of its entry, so it can be reopened after the entry leaves the inbox."""
    return {"kind": "inbox", "item_id": item["id"], "source": item["source"], "family": item["source"],
            "publisher": item["publisher"], "title": item["title"], "link": item["link"], "category": item["category"],
            "source_kind": item["kind"], "attribution": item["attribution"], "feed_timestamp": item["feed_timestamp"],
            "retrieved_at": item["retrieved_at"], "history": bool(item.get("history")),
            "content_sha256": inbox_archive.content_sha256(item)}


def _confirmations(store: Path, key: str) -> tuple[list[dict], str | None]:
    """Every saved version for an event, oldest first, or the reason they cannot be used. Reads only."""
    folder = store / market_store.EVENTS / key
    if not folder.is_dir():
        return [], None
    names = sorted((path.name for path in folder.iterdir() if not path.name.startswith(".")),
                   key=lambda name: (len(name), name))
    records = []
    for number, name in enumerate(names, start=1):
        if name != f"{number}.json":
            return [], f"The saved confirmations are not numbered 1 to {len(names)} ({name})"
        try:
            record = market_context._strict_json((folder / name).read_bytes(), name, 500)
        except (ContextRefused, OSError) as exc:
            return [], f"Saved confirmation {name} cannot be read: {exc}"
        snapshot = record.get("event")
        try:
            own = isinstance(snapshot, dict) and event_key("inbox", snapshot.get("item_id")) == key
        except ContextRefused:
            own = False
        if not own or set(record) != RECORD_FIELDS or record["context_version"] != CONTEXT_VERSION or \
                record["key"] != key or record["version"] != number or record["convention"] != CONVENTION or \
                record["supersedes"] != (number - 1 if number > 1 else None) or \
                set(snapshot) != EVENT_FIELDS or snapshot["family"] not in FAMILIES or \
                not isinstance(snapshot["content_sha256"], str) or not SHA256.fullmatch(snapshot["content_sha256"]) or \
                not isinstance(record["context_date"], str) or not DATE.fullmatch(record["context_date"]):
            return [], f"Saved confirmation {name} does not have the expected fields and values"
        try:
            date.fromisoformat(record["context_date"])
            market_context._moment(record["confirmed_at"], "confirmed_at", 500)
        except (ValueError, ContextRefused):
            return [], f"Saved confirmation {name} has an invalid date or time"
        records.append(record)
    return records, None


def _window(day: date) -> dict:
    return {"start": (day - timedelta(days=WINDOW_DAYS)).isoformat(), "end": (day + timedelta(days=WINDOW_DAYS)).isoformat(),
            "days_before": WINDOW_DAYS, "days_after": WINDOW_DAYS}


def definition(kind: str, event_id: str, store: Path, inbox: Path, intake: Path) -> dict:
    """One event as the page shows it: what it is, whether this slice supports it, and its context date if it has
    one (a capture's supplied time, or an Inbox entry's latest confirmation). Reads only."""
    key = event_key(kind, event_id)
    base = {"key": key, "kind": kind, "id": event_id, "supported": False, "family": None, "family_label": None,
            "outside": None, "title": None, "link": None, "publisher": None, "timestamp": None, "supplied": None,
            "suggestion": None, "suggestion_problem": None, "in_inbox": None, "confirmations": [], "context": None,
            "confirmation_stale": None, "problem": None}
    if kind == "capture":
        try:
            record = event_intake.verified(intake, event_id)
        except (event_intake.IntakeRefused, OSError) as exc:
            raise ContextRefused(404, f"This saved event cannot be read: {exc}") from None
        family = capture_family(record["event"]["source_url"])
        supplied = record["times"]["published_at_as_supplied"]
        moment = datetime.fromisoformat(supplied)
        if moment.utcoffset() is None:
            raise ContextRefused(422, "This saved event's publication time has no explicit UTC offset")
        local = moment.astimezone(NEW_YORK)
        base.update(title=record["event"]["headline"], link=record["event"]["source_url"],
                    publisher=event_inbox.SOURCES[family].publisher if family else None, supported=family is not None, family=family, family_label=FAMILIES.get(family),
                    outside=None if family else UNSUPPORTED_CAPTURE,
                    supplied={"published_at_as_supplied": supplied, "published_at": record["times"]["published_at"],
                              "new_york_time": local.strftime("%H:%M"),
                              "new_york_offset": local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:],
                              "note": event_intake.PUBLISHED_NOTE})
        if family:
            base["context"] = {"date": local.date().isoformat(), "basis": "supplied", "convention": CONVENTION,
                               "window": _window(local.date())}
        return base
    item = _inbox_item(event_id, inbox)
    records, problem = _confirmations(store, key)
    if item is None and not records and problem is None:
        raise ContextRefused(404, "No Event Inbox entry has this identifier; it may not have been refreshed yet")
    snapshot = _snapshot(item) if item else records[-1]["event"] if records else None
    if snapshot is None:  # Unreadable confirmations of an entry that has left the inbox.
        base.update(problem=problem)
        return base
    family = snapshot["source"]
    suggestion, missing = _suggestion(snapshot["feed_timestamp"])
    base.update(title=snapshot["title"], link=snapshot["link"], publisher=snapshot["publisher"],
                supported=family in FAMILIES, family=family if family in FAMILIES else None,
                family_label=FAMILIES.get(family), outside=None if family in FAMILIES else OUTSIDE_NOTE,
                timestamp=snapshot["feed_timestamp"], in_inbox=item is not None, problem=problem,
                suggestion=suggestion if family in FAMILIES else None,
                suggestion_problem=missing if family in FAMILIES else None,
                confirmations=[{key_: record[key_] for key_ in ("version", "context_date", "confirmed_at")}
                               for record in records])
    if records and family in FAMILIES and item is not None and \
            records[-1]["event"]["content_sha256"] != inbox_archive.content_sha256(item):
        latest = records[-1]  # Confirmed for another version of the entry: it does not carry over to this one.
        base["confirmation_stale"] = {"version": latest["version"], "context_date": latest["context_date"],
                                      "title": latest["event"]["title"],
                                      "content_sha256": latest["event"]["content_sha256"],
                                      "current_content_sha256": inbox_archive.content_sha256(item)}
    elif records and family in FAMILIES:
        latest = records[-1]
        day = date.fromisoformat(latest["context_date"])
        base["context"] = {"date": latest["context_date"], "basis": "confirmed", "convention": CONVENTION,
                           "version": latest["version"], "confirmed_at": latest["confirmed_at"],
                           "suggested": latest["suggestion"], "window": _window(day)}
    return base


def confirm(item_id: str, body: bytes, store: Path, inbox: Path, clock) -> dict:
    """Save the user's confirmation of an Inbox entry's context date as a new version. The request names the date,
    the convention and the version it expects to create; a repeat of the current date writes nothing."""
    key = event_key("inbox", item_id)
    try:
        request = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        request = None
    if not isinstance(request, dict) or set(request) != {"context_date", "convention", "version"} or \
            not isinstance(request["context_date"], str) or not DATE.fullmatch(request["context_date"]) or \
            type(request["version"]) is not int:
        raise ContextRefused(422, "A confirmation names exactly a context date (YYYY-MM-DD), the convention and the "
                                  "version it creates")
    if request["convention"] != CONVENTION["id"]:
        raise ContextRefused(422, f"Confirm the convention {CONVENTION['id']}: a New York calendar date")
    try:
        day = date.fromisoformat(request["context_date"])
    except ValueError:
        raise ContextRefused(422, f"{request['context_date']} is not a calendar date") from None
    if day > today(clock):
        raise ContextRefused(422, "A context date cannot be after today's New York date")
    item = _inbox_item(item_id, inbox)
    records, problem = _confirmations(store, key)
    if problem:
        raise ContextRefused(409, f"{problem}; it was left unchanged, so no new date can be saved")
    if item is None and not records:
        raise ContextRefused(404, "No Event Inbox entry has this identifier")
    snapshot = _snapshot(item) if item else records[-1]["event"]
    if snapshot["source"] not in FAMILIES:
        raise ContextRefused(422, OUTSIDE_NOTE)
    if records and records[-1]["context_date"] == request["context_date"] and \
            records[-1]["event"]["content_sha256"] == snapshot["content_sha256"]:
        return {"saved_now": False, "version": len(records)}  # This date, for this version, is already saved.
    if request["version"] != len(records) + 1:
        raise ContextRefused(409, f"The page expected to save version {request['version']}, but {len(records)} "
                                  "versions are saved; reload the event before confirming")
    suggestion, _ = _suggestion(snapshot["feed_timestamp"])
    record = {"context_version": CONTEXT_VERSION, "key": key, "version": len(records) + 1, "event": snapshot,
              "context_date": request["context_date"], "convention": CONVENTION,
              "suggestion": suggestion["date"] if suggestion else None,
              "confirmed_at": event_inbox.stamp(clock()), "supersedes": len(records) or None}
    try:
        market_store.write_exclusive(store / market_store.EVENTS / key / f"{record['version']}.json", record)
    except FileExistsError:
        raise ContextRefused(409, "Another confirmation was saved at the same moment; reload the event") from None
    return {"saved_now": True, "version": record["version"]}


def saved_inbox_keys(store: Path) -> list[str]:
    folder = store / market_store.EVENTS
    return sorted(path.name for path in folder.iterdir() if path.is_dir() and path.name.startswith("inbox-")) \
        if folder.is_dir() else []


# ---------------------------------------------------------------- the view

def _exception_kinds(exceptions: dict) -> dict:
    return {(entry["series"], entry["date"]): entry["kind"] for entry in exceptions["exceptions"]}


def _classify(raw: str | None, day: date, session: bool, series_id: str, documented: dict) -> str:
    """A statement's status, as market_calendar.reconcile classifies a provider row (weekends named apart)."""
    fred = SERIES[series_id]["fred_equivalent"]
    exception = documented.get((fred, day.isoformat())) or documented.get(("*", day.isoformat()))
    has_value = raw is not None and raw != market_context.NO_VALUE
    if session:
        if has_value:
            return "session_value"
        if exception == "issuer_no_observation":
            return "issuer_no_observation"
        return "session_missing" if raw is not None else "session_absent"
    if not has_value:
        return "weekend" if day.weekday() >= 5 else "calendar_holiday"
    return ("issuer_observation_on_calendar_holiday" if exception == "issuer_observation_on_calendar_holiday"
            else "unreconciled_value_on_calendar_holiday")


def _bp(base: str, end: str) -> str:
    change = (Decimal(end) - Decimal(base)) * 100
    text = format(change.normalize(), "f") if change else "0"
    return text if text.startswith("-") or text == "0" else f"+{text}"


def build_view(event: dict, found: list, problems: list[dict], as_of: date, sessions=expected_sessions) -> dict:
    """The event's window, every date's statuses, the descriptive changes and the provenance of every value shown."""
    day0 = date.fromisoformat(event["context"]["date"])
    start, end = day0 - timedelta(days=WINDOW_DAYS), day0 + timedelta(days=WINDOW_DAYS)
    window_sessions = {day for day in sessions(start, end) if start <= day <= end}
    exceptions = load_exceptions()
    documented = _exception_kinds(exceptions)
    used, conflicts, days = set(), [], []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        session = day in window_sessions
        stating = [retrieval for retrieval in found if retrieval.states(day)]
        observations = {}
        for series_id in SERIES:
            versions: dict = {}
            for retrieval in stating:
                versions.setdefault(retrieval.rows[series_id].get(day), []).append(retrieval.id)
            if len(versions) > 1:
                status, raw = "conflict", None
                conflicts.append({"date": day.isoformat(), "series": series_id,
                                  "versions": [{"raw": text, "retrievals": ids} for text, ids in versions.items()]})
            elif versions:
                raw = next(iter(versions))
                status = _classify(raw, day, session, series_id, documented)
            else:
                raw = None
                status = ("weekend" if day.weekday() >= 5 else "calendar_holiday") if not session else \
                    "future" if day >= as_of else \
                    "after_retrieval" if any(retrieval.pending(day) for retrieval in found) else "not_held"
            sources = sorted(id_ for ids in versions.values() for id_ in ids)
            used.update(sources)
            observations[series_id] = {"raw": raw, "value": float(raw) if status in VALUE_STATUSES else None,
                                       "status": status, "retrievals": sources}
        days.append({"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "session": session,
                     "observations": observations})
    by_date = {row["date"]: row for row in days}
    ordered = sorted(window_sessions)
    before = [day for day in ordered if day < day0]
    after = [day for day in ordered if day > day0]
    base = before[-1] if before else None
    endpoints = {"rule": RULE, "base": base.isoformat() if base else None,
                 "after_1": after[0].isoformat() if after else None,
                 "after_5": after[4].isoformat() if len(after) >= 5 else None, "changes": []}
    for series_id, series in SERIES.items():
        start_obs = by_date[base.isoformat()]["observations"][series_id] if base else None
        for horizon, key in ((1, "after_1"), (5, "after_5")):
            target = endpoints[key]
            end_obs = by_date[target]["observations"][series_id] if target else None
            change = {"series": series_id, "short_label": series["short_label"], "horizon": horizon,
                      "from": endpoints["base"], "to": target, "from_raw": None, "to_raw": None, "change_bp": None,
                      "unavailable": None}
            reasons = []
            for label, observation, when in (("start", start_obs, endpoints["base"]), ("end", end_obs, target)):
                if observation is None:
                    reasons.append(f"the {label} session is outside the window")
                elif observation["status"] != "session_value":
                    reasons.append(f"the {label} session ({when}): {STATUS_WORDS.get(observation['status'], observation['status'])}")
            if reasons:
                change["unavailable"] = "; ".join(reasons)
            else:
                change.update(from_raw=start_obs["raw"], to_raw=end_obs["raw"],
                              change_bp=_bp(start_obs["raw"], end_obs["raw"]))
            endpoints["changes"].append(change)
    counts: dict = {}
    for row in days:
        for observation in row["observations"].values():
            counts[observation["status"]] = counts.get(observation["status"], 0) + 1
    pending = {"future", "after_retrieval", "not_held", "conflict"}
    return {"view_version": VIEW_VERSION, "key": event["key"], "as_of": as_of.isoformat(),
            "context": event["context"], "publication": {"new_york_date": event["context"]["date"]},
            "window": event["context"]["window"],
            "series": [{**series} for series in SERIES.values()], "sessions": [day.isoformat() for day in ordered],
            "days": days, "endpoints": endpoints, "conflicts": conflicts, "status_counts": counts,
            "complete": not any(observation["status"] in pending for row in days
                                for observation in row["observations"].values()),
            "retrievals": [retrieval.provenance for retrieval in found if retrieval.id in used],
            "store_problems": problems, "calendar": calendar_identity(exceptions),
            "source": {**market_context.SOURCE, "terms": market_context.TERMS,
                       "vintage_note": market_context.VINTAGE_NOTE}, "limits": list(LIMITS)}

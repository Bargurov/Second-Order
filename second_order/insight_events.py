"""Retained events for the Treasury findings pilot: every record, one event per published release, one occasion per
date. Reads only.

Records come from three kinds of source, kept apart and labelled:
- capture: a saved Tracker event with the source text the operator pasted ("captured source text"); its date is the
  New York date of the publication time and UTC offset the operator supplied;
- inbox: an Event Inbox entry ("official feed metadata": title, link, feed timestamp); its date is the user's
  confirmation when one applies to the entry version held, otherwise the New York date of the feed's own timestamp,
  shown as unconfirmed metadata; a timestamp that states no unambiguous instant leaves the date missing;
- library: a case-library case ("editorial metadata"); its date is the publication time an editor recorded from the
  official page, not independently verified here.

Records are the same published release only when they name the same official address (https, no query or fragment,
host compared case-insensitively) and agree on its New York date. Titles are never compared: recurring titles such as
"Federal Reserve issues FOMC statement" name different releases. Records with one address and different dates are a
conflict, kept visible, and not measured. Every originating record stays listed with its event.

Supported events are those of the market-context slice's families: Federal Reserve monetary-policy press releases and
BLS Employment Situation and CPI releases (event_context.capture_family). Others are listed as outside this pilot.
An occasion is one New York date: every supported event dated that day shares its measurement, which cannot tell them
apart.
"""
from datetime import datetime
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from . import case_library, event_context, event_inbox, event_intake
from .market_context import NEW_YORK, ContextRefused

ORIGIN_LABELS = {"capture": "Saved event with captured source text",
                 "inbox": "Event Inbox entry (official feed metadata)",
                 "library": "Case-library case (editorial metadata)"}
BASES = {
    "supplied": "the publication time and UTC offset supplied when the event was captured",
    "confirmed": "the date the user confirmed for this Inbox entry",
    "feed_timestamp": "the New York date of the publisher's feed timestamp: unconfirmed metadata, not a verified "
                      "publication time",
    "editorial": "the publication time an editor recorded from the official page (case library); not independently "
                 "verified here",
}
OUTSIDE = ("Outside this pilot, which measures Treasury yields only around Federal Reserve monetary-policy releases "
           "and BLS employment and inflation releases.")


def canonical_url(link: str | None) -> str | None:
    """An official address in comparable form, or None when it cannot be compared reliably."""
    if not isinstance(link, str):
        return None
    parts = urlsplit(link)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.port is not None:
        return None
    return f"https://{parts.hostname.lower()}{parts.path}"


def _ny_date(moment: str) -> str:
    return datetime.fromisoformat(moment).astimezone(NEW_YORK).date().isoformat()


def capture_records(intake: Path, market: Path, inbox: Path) -> list[dict]:
    records = []
    for row in event_intake.listing(intake) if intake.is_dir() else []:
        if not row["state"].startswith("verified"):
            continue
        try:
            event = event_context.definition("capture", row["capture_id"], market, inbox, intake)
        except ContextRefused:
            continue
        supplied = event["supplied"] or {}
        records.append({"origin": "capture", "origin_id": row["capture_id"], "title": event["title"],
                        "link": event["link"], "publisher": event["publisher"], "family": event["family"],
                        "date": event["context"]["date"] if event["context"] else None,
                        "basis": "supplied" if event["context"] else None,
                        "as_stated": supplied.get("published_at_as_supplied"), "problem": None,
                        "href": f"/events/capture/{row['capture_id']}"})
    return records


def inbox_records(inbox: Path, market: Path, intake: Path) -> list[dict]:
    view = event_inbox.inbox_view(inbox)
    records = []
    for item in view["items"] + view["retained"]:
        try:
            event = event_context.definition("inbox", item["id"], market, inbox, intake)
        except ContextRefused:
            continue
        record = {"origin": "inbox", "origin_id": item["id"], "title": event["title"], "link": event["link"],
                  "publisher": event["publisher"], "family": event["family"], "date": None, "basis": None,
                  "as_stated": (event["timestamp"] or {}).get("raw"), "problem": None,
                  "href": f"/events/inbox/{item['id']}"}
        if event["context"]:
            record.update(date=event["context"]["date"], basis="confirmed")
        elif event["suggestion"]:
            record.update(date=event["suggestion"]["date"], basis="feed_timestamp")
        elif event["family"]:
            record["problem"] = event["suggestion_problem"] or "The feed's timestamp states no usable date."
        if event["confirmation_stale"]:
            record["note"] = "An earlier confirmation was made for another version of this entry and does not apply."
        records.append(record)
    return records


def library_records(library: Path) -> list[dict]:
    try:
        loaded = case_library.load_library(library)
    except case_library.LibraryRefused:
        return []
    records = []
    for case in loaded["cases"]:
        source = case["source"]
        family = event_context.capture_family(source["url"])
        day = (source["published_at"] if case_library.precision(source) == "date"
               else _ny_date(source["published_at"]))
        records.append({"origin": "library", "origin_id": case["id"], "title": case["title"], "link": source["url"],
                        "publisher": source["publisher"], "family": family, "date": day, "basis": "editorial",
                        "as_stated": source["published_as_stated"], "problem": None, "href": f"/library/{case['id']}"})
    return records


def event_key(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def events(intake: Path, market: Path, inbox: Path, library: Path) -> list[dict]:
    """Every retained record grouped into events, oldest date first. Reads only."""
    records = capture_records(intake, market, inbox) + inbox_records(inbox, market, intake) + library_records(library)
    groups: dict[str, list[dict]] = {}
    for record in records:
        url = canonical_url(record["link"])
        identity = f"url:{url}" if url else f"{record['origin']}:{record['origin_id']}"
        groups.setdefault(identity, []).append(record)
    found = []
    for identity, members in groups.items():
        members.sort(key=lambda record: (record["origin"], record["origin_id"]))
        family = next((record["family"] for record in members if record["family"]), None)
        dates = sorted({record["date"] for record in members if record["date"]})
        event = {"key": event_key(identity), "identity": identity, "title": members[0]["title"],
                 "link": members[0]["link"], "publisher": members[0]["publisher"], "family": family,
                 "family_label": event_context.FAMILIES.get(family), "records": members, "date": None,
                 "state": None, "detail": None}
        if family is None:
            event.update(state="unsupported", detail=OUTSIDE)
        elif len(dates) > 1:
            event.update(state="date_conflict", detail="Records of this release state different dates (" +
                         ", ".join(f"{record['date']} from {ORIGIN_LABELS[record['origin']].lower()}"
                                   for record in members if record["date"]) + "); it is not measured.")
        elif not dates:
            event.update(state="no_date", detail=next((record["problem"] for record in members if record["problem"]),
                                                      "No record states a usable date."))
        else:
            event.update(state="dated", date=dates[0])
        found.append(event)
    return sorted(found, key=lambda event: (event["date"] or "9999", event["key"]))


def occasions(found: list[dict]) -> dict[str, list[dict]]:
    """Supported, dated events grouped by their New York date."""
    grouped: dict[str, list[dict]] = {}
    for event in found:
        if event["state"] == "dated":
            grouped.setdefault(event["date"], []).append(event)
    return grouped

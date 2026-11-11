"""Related Cases for one event (related-match-0.1): one explicit local check, write-once records under
data/related-cases/matches/, and reads that verify without computing anything new or writing.

An event is an Event Inbox entry (its current version, or its latest archived one) or a saved capture. Its inputs are
its own text only: the entry's title and feed excerpt, or the capture's headline, supplied source text and source
address. A saved headline classification is added as a hint only when it is a paid model result accepted for exactly
that entry version (for a capture: the Inbox entry version it recorded as its origin); simulated results are fixtures
and are never used. Nothing is classified, fetched, summarised or sent: matching is related_rules over the historical
cases (related_cases).

The check (POST, local, $0) stores the result once as matches/<id>.json, where id = SHA-256 of the match, rules and
collection versions, the collection's content digest, the event's identity (entry ID and content fingerprint, or
capture ID with its request and source hashes) and the hint's identity. Retrieval times, display order and page state
are not part of it. A stored record with that ID is reused when it verifies and is never overwritten. A read recomputes
the record in memory and shows the stored one only when it is exactly that, apart from its computation time; records
made under other versions, other case content or an earlier version of the entry are kept and not shown. Headline
triage records are only read, so a change to the cases never touches them.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from . import (event_context, event_inbox, event_intake, event_links, event_overview, headline_triage, inbox_archive,
               inbox_imports, market_store, related_cases, related_rules, triage_flow, triage_plan)
from .market_context import ContextRefused
from .store import digest

MATCH_VERSION = "related-match-0.1"
VIEW_VERSION = "related-match-view-0.1"
RECORDS_DIR = related_cases.ROOT / "data" / "related-cases"
REQUEST = {"find_related_cases": True}
MAX_BODY = 200
HINT_MODE = "paid"  # Simulated triage results are fixtures, not classifications: never a hint.
NOT_CHECKED = ("Not checked yet. Finding related cases is an explicit local action: it compares this event's own text "
               "with the historical cases using a fixed word list. No model, network or score is involved, and the "
               "result is saved once for this version of the event.")
HINT_NOTE = ("A saved model classification of this entry version. It is used only as a hint: terms found in it are "
             "marked, and a related case that rests on it says so.")
NOT_COMPARED = ("Not compared by this check. The event's text is scanned only for the instrument, sector, country and "
                "agency; read the case to compare these yourself.")


class MatchRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    cases: Path = related_cases.CASES_DIR
    records: Path = RECORDS_DIR
    inbox: Path = event_inbox.INBOX_DIR
    intake: Path = event_intake.INTAKE_DIR
    triage: Path = triage_flow.TRIAGE_DIR
    links: Path = event_links.LINKS_DIR


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- the event's inputs

def _hint(entry: dict, triage: Path) -> dict | None:
    """The accepted paid classification of exactly this entry version, current configuration first."""
    index = triage_plan.build_index(triage)
    fp = headline_triage.fingerprint(headline_triage.snapshot_item(entry))
    saved = index["results"].get((HINT_MODE, fp), [])
    if not saved:
        return None
    current = headline_triage.config_key(headline_triage.config())
    chosen = next((row for row in saved if row["config_key"] == current), saved[0])
    provenance, result = chosen["provenance"], chosen["result"]
    return {"entry_id": entry["id"], "fingerprint": fp, "mode": HINT_MODE, "triage_id": provenance["triage_id"],
            "config_key": chosen["config_key"], "current_config": chosen["config_key"] == current,
            "received_at": provenance["received_at"], "category": result["category"],
            "event_type": result["event_type"], "summary": result["summary"]}


def _origin_entry(capture_id: str, folders: Folders) -> dict | None:
    """The Inbox entry version a capture recorded as its origin, when the link verifies and the version is held."""
    origin = event_links.read_origin(folders.links, capture_id, folders.intake, folders.inbox)
    if origin["state"] != "verified":
        return None
    linked = origin["link"]["inbox"]
    item, _, versions = event_links._versions(folders.inbox, linked["item_id"])
    if item is not None and inbox_archive.content_sha256(item) == linked["content_sha256"]:
        return item
    version = next((version for version in versions if version["content_sha256"] == linked["content_sha256"]), None)
    return event_overview._version_item(linked["item_id"], version) if version else None


def subject(kind: str, event_id: str, folders: Folders) -> dict:
    """The event's identity, its own text by field, the context shown beside a match, and the hint, if any."""
    if kind not in ("inbox", "capture"):
        raise MatchRefused(404, "Unknown kind of event")
    try:
        event_context.event_key(kind, event_id)
    except ContextRefused as exc:
        raise MatchRefused(404, str(exc)) from None
    if kind == "inbox":
        item, location, versions = event_links._versions(folders.inbox, event_id)
        if item is None and not versions:
            raise MatchRefused(404, "No Event Inbox entry with this identifier is held locally")
        entry = item if item is not None else event_overview._version_item(event_id, versions[-1])
        excerpt = None if entry["excerpt_repeats_title"] or not entry["excerpt"] else entry["excerpt"]
        stamp = entry["feed_timestamp"]
        return {"identity": {"kind": "inbox", "id": event_id, "content_sha256": inbox_archive.content_sha256(entry)},
                "fields": {"title": entry["title"], "excerpt": excerpt},
                "context": {"title": entry["title"], "publisher": entry["publisher"], "source": entry["source"],
                            "link": entry["link"],
                            "date_label": "Listing timestamp (retained snapshot metadata, not a verified publication "
                                          "time)" if entry["source"] in inbox_imports.SOURCES else
                                          "Feed timestamp (feed metadata, not a verified publication time)",
                            "date_short": "listing timestamp" if entry["source"] in inbox_imports.SOURCES
                                          else "feed timestamp",
                            "date_value": stamp["raw"], "held": location or "archived"},
                "hint": _hint(entry, folders.triage)}
    try:
        record = event_intake.verified(folders.intake, event_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        raise MatchRefused(404, f"This saved event cannot be read: {exc}") from None
    event = record["event"]
    origin = _origin_entry(event_id, folders)
    return {"identity": {"kind": "capture", "id": event_id, "request_sha256": record["request"]["sha256"],
                         "source_sha256": record["source"]["sha256"]},
            "fields": {"headline": event["headline"], "source_text": record["source_text"],
                       "source_host": related_rules.source_host(event["source_url"])},
            "context": {"title": event["headline"], "publisher": None, "source": None, "link": event["source_url"],
                        "date_label": "Publication time as supplied by the operator (not verified)",
                        "date_short": "operator-supplied publication time",
                        "date_value": record["times"]["published_at_as_supplied"],
                        "held": "capture"},
            "hint": _origin_hint(origin, folders)}


def _origin_hint(origin: dict | None, folders: Folders) -> dict | None:
    return _hint(origin, folders.triage) if origin is not None else None


def _hint_fields(hint: dict | None) -> dict:
    return {"hint_event_type": hint["event_type"], "hint_summary": hint["summary"]} if hint else {}


def _hint_identity(hint: dict | None) -> dict | None:
    return None if hint is None else {key: hint[key] for key in ("entry_id", "fingerprint", "mode", "triage_id",
                                                                "config_key", "event_type", "summary")}


# ---------------------------------------------------------------- the result

def match_id(loaded: dict, found: dict) -> str:
    return digest({"match_version": MATCH_VERSION, "rules_version": related_rules.RULES_VERSION,
                   "collection_version": related_cases.COLLECTION_VERSION, "collection_sha256": loaded["digest"],
                   "subject": found["identity"], "hint": _hint_identity(found["hint"])})


def _expected(loaded: dict, found: dict) -> dict:
    fields = {**found["fields"], **_hint_fields(found["hint"])}
    tags = related_rules.tag(fields)
    return json.loads(json.dumps({
        "match_version": MATCH_VERSION, "match_id": match_id(loaded, found),
        "rules_version": related_rules.RULES_VERSION, "collection_version": related_cases.COLLECTION_VERSION,
        "collection_sha256": loaded["digest"], "subject": found["identity"], "hint": _hint_identity(found["hint"]),
        "inputs": [{"field": field, "present": bool(text)} for field, text in fields.items()],
        "tags": tags, "result": related_rules.match(tags, related_cases.match_cases(loaded))}))


def _path(folders: Folders, identifier: str) -> Path:
    return folders.records / "matches" / f"{identifier}.json"


def _stored(folders: Folders, identifier: str) -> dict | None:
    path = _path(folders, identifier)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise MatchRefused(409, f"The stored match {identifier[:12]} cannot be read; it is kept and not shown") \
            from None


def _verifies(stored: dict, expected: dict) -> bool:
    return isinstance(stored, dict) and isinstance(stored.get("computed_at"), str) and \
        {key: value for key, value in stored.items() if key != "computed_at"} == expected


def _load_cases(folders: Folders) -> dict:
    try:
        return related_cases.load(folders.cases)
    except related_cases.RelatedRefused as exc:
        raise MatchRefused(exc.status, str(exc)) from None


# ---------------------------------------------------------------- the explicit action

def check(kind: str, event_id: str, body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if payload != REQUEST or not isinstance(payload.get("find_related_cases"), bool):
        raise MatchRefused(422, 'Related cases are found with {"find_related_cases": true}')
    loaded = _load_cases(folders)
    expected = _expected(loaded, subject(kind, event_id, folders))
    identifier = expected["match_id"]
    stored = _stored(folders, identifier)
    created = False
    if stored is None:
        try:
            market_store.write_exclusive(_path(folders, identifier),
                                         {**expected, "computed_at": clock().astimezone(timezone.utc).isoformat()})
            created = True
        except FileExistsError:  # A concurrent check stored the same result first.
            stored = _stored(folders, identifier)
    if stored is not None and not _verifies(stored, expected):
        raise MatchRefused(409, f"A stored match with ID {identifier[:12]} does not match what this event and these "
                                "cases give; it is kept, not overwritten and not shown")
    return {"view_version": VIEW_VERSION, "match_id": identifier, "created": created,
            "related": len(expected["result"]["related"]), "overlaps": len(expected["result"]["overlaps"]),
            "provider_called": False}


# ---------------------------------------------------------------- reads (verify only)

def _kept(folders: Folders, identity: dict) -> tuple[int, int]:
    """Stored matches for this event under other bindings, and stored files that cannot be read."""
    folder = folders.records / "matches"
    same, unreadable = 0, 0
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable += 1
            continue
        found = record.get("subject") if isinstance(record, dict) else None
        if isinstance(found, dict) and (found.get("kind"), found.get("id")) == (identity["kind"], identity["id"]):
            same += 1
    return same, unreadable


def _join(values: list[str]) -> str:
    return " and ".join(values) if len(values) < 3 else ", ".join(values[:-1]) + " and " + values[-1]


def _where(found: list[dict]) -> str:
    parts = [f"“{item['term']}” in {related_rules.FIELD_LABELS[item['field']]}" for item in found]
    return "; ".join(parts)


def _explain_related(row: dict, case: dict, found: dict) -> dict:
    shared = [{**item, "text": f"{related_rules.DIMENSION_LABELS[item['dimension']].capitalize()}: {item['label']} "
                               f"({_where(item['found'])})."} for item in row["shared"]]
    differs = []
    for item in row["differs"]:
        noun, theirs = related_rules.DIMENSION_LABELS[item["dimension"]], _join(item["case"])
        clause = f"the case's {noun} is {theirs}" if item["dimension"] == "agency" else f"the case concerns {theirs}"
        if item["kind"] == "different":
            text = f"This event names {_join(item['event'])} as its {noun}; {clause}."
        else:
            text = f"This event also names {_join(item['event'])}; {clause.replace('concerns', 'concerns only')}."
        differs.append({**item, "text": text})
    unknown = []
    for item in row["unknown"]:
        theirs = _join(item["case"])
        question = (f"whether {theirs} is involved, as in the case," if item["dimension"] == "agency"
                    else f"whether it concerns {theirs}, as the case does,")
        unknown.append({**item, "text": f"This event's text names no {related_rules.DIMENSION_LABELS[item['dimension']]}"
                                        f"; {question} is unknown."})
    context = found["context"]
    timing = (f"The case was announced on {related_cases.long_date(related_cases.announced(case))}. "
              + (f"This event's {context['date_short']} is {context['date_value']}." if context["date_value"]
                 else "This event's date is not recorded."))
    return {"case_id": case["id"], "title": case["title"], "topic": case["topic"],
            "announced": related_cases.announced(case).isoformat(), "date_as_stated": case["source"]["date_as_stated"],
            "publisher": case["source"]["publisher"], "shared_dimensions": row["shared_dimensions"],
            "shared": shared, "differs": differs, "unknown": unknown, "timing": timing,
            "not_compared": [{"label": point["label"], "case_value": point["case_value"]}
                             for point in case["comparison_points"]],
            "why_read": case["interpretation"]["why_read"], "rests_on_hint": row["rests_on_hint"],
            "hint_note": "This match rests partly on a saved model classification, which is a hint, not a fact."
            if row["rests_on_hint"] else None}


def _explain_overlap(row: dict, case: dict) -> dict:
    shared = "; ".join(f"{item['label']} ({_where(item['found'])})" for item in row["shared"])
    if row["missing"] == "instrument":
        reason = (f"it names none of the case's policy instruments ({_join(row['case_instruments'])}), so it is "
                  "not presented as related")
    else:
        reason = (f"it names neither the case's sector nor its country ({_join(row['case_sectors_and_countries'])}),"
                  " so it is not presented as related")
    return {"case_id": case["id"], "title": case["title"], "missing": row["missing"], "shared": row["shared"],
            "text": f"Shares {shared} with this case, but {reason}."}


def _context(found: dict) -> dict:
    fields = {**found["fields"], **_hint_fields(found["hint"])}
    return {**found["context"], "identity": found["identity"],
            "inputs": [{"field": field, "label": related_rules.FIELD_LABELS[field], "present": bool(text)}
                       for field, text in fields.items()],
            "hint": None if found["hint"] is None else {**found["hint"], "note": HINT_NOTE}}


def _base(loaded: dict, found: dict) -> dict:
    collection = loaded["collection"]
    return {"view_version": VIEW_VERSION, "kind": found["identity"]["kind"], "id": found["identity"]["id"],
            "event": _context(found), "cases_available": len(loaded["cases"]),
            "coverage_note": collection["coverage_note"], "matching_note": collection["matching_note"],
            "historical_note": collection["historical_note"], "not_compared_note": NOT_COMPARED,
            "rules_version": related_rules.RULES_VERSION, "written": False, "provider_called": False}


def view(kind: str, event_id: str, folders: Folders) -> dict:
    """This event's stored match under the current versions and inputs, verified. Reads only."""
    loaded = _load_cases(folders)
    found = subject(kind, event_id, folders)
    expected = _expected(loaded, found)
    base = _base(loaded, found)
    try:
        stored = _stored(folders, expected["match_id"])
    except MatchRefused as exc:
        return {**base, "state": "problem", "detail": str(exc), "match": None, "kept_records": None}
    kept, unreadable = _kept(folders, found["identity"])
    if stored is None:
        detail = NOT_CHECKED
        if kept:
            detail += (f" {kept} earlier check{' is' if kept == 1 else 's are'} kept for this event under other "
                       "versions of its text, the rules or the cases; not shown.")
        return {**base, "state": "not_checked", "detail": detail, "match": None, "kept_records": kept,
                "unreadable_records": unreadable}
    if not _verifies(stored, expected):
        return {**base, "state": "problem", "match": None, "kept_records": kept, "unreadable_records": unreadable,
                "detail": f"The stored match {expected['match_id'][:12]} does not match what this event and the "
                          "cases give now; it is not shown."}
    cases = {case["id"]: case for case in loaded["cases"]}
    result = stored["result"]
    return {**base, "state": "checked", "detail": None, "kept_records": kept, "unreadable_records": unreadable,
            "match": {"match_id": stored["match_id"], "computed_at": stored["computed_at"],
                      "rules_version": stored["rules_version"], "collection_version": stored["collection_version"],
                      "related": [_explain_related(row, cases[row["case_id"]], found) for row in result["related"]],
                      "overlaps": [_explain_overlap(row, cases[row["case_id"]]) for row in result["overlaps"]],
                      "tags": {dimension: {slug: {"label": related_rules.label(dimension, slug), "found": items}
                                           for slug, items in stored["tags"][dimension].items()}
                               for dimension in related_rules.DIMENSIONS}}}


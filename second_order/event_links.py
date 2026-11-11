"""Explicit links from a saved capture to the Event Inbox entry version that filled its form.

When the operator chooses Analyze this event on an Inbox entry and then captures the form, the capture action names
that entry and the exact version it showed (`content_sha256`, inbox_archive's fingerprint of the entry's meaningful
content). The link is checked before anything is captured: the entry must be held locally (in the latest retrieval or
the archive) at that exact version, or nothing is captured. It is then recorded once, in
data/event-links/<capture ID>.json, created exclusively and read-only, beside the capture and never inside it: the
capture's files, its request bytes and any approval are unchanged, and a capture made without an origin is identical to
one made with it. A capture made before links existed, or typed by hand, has no link, and nothing infers one.

A link states only that the form was started from that entry version, and whether the captured headline and source
address still matched it. It does not say the captured text is the entry's article, and it is never made from a title,
a date or a similarity. Reading verifies the record against the capture it names (its request SHA-256) and finds the
entry version among what the inbox holds now; a record that does not verify is reported, never repaired or dropped.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from . import event_inbox, event_intake, inbox_archive, inbox_imports, market_context, market_store

ROOT = Path(__file__).resolve().parent.parent
LINKS_DIR = ROOT / "data" / "event-links"  # Runtime records; data/ is ignored by git.
LINK_VERSION = "event-link-0.1"
RECORD_FIELDS = {"link_version", "capture_id", "capture_request_sha256", "inbox", "form", "recorded_at", "statement"}
INBOX_FIELDS = {"item_id", "source", "content_sha256", "version", "versions", "location", "title", "link",
                "feed_timestamp_raw"}
STATEMENT = ("The capture's form was filled from this Event Inbox entry version by Analyze this event. This records "
             "where the form started; it does not say that the captured text is the entry's article.")
SHA256 = re.compile(r"[0-9a-f]{64}")


class LinkRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _versions(inbox: Path, item_id: str) -> tuple[dict | None, str | None, list[dict]]:
    """(the entry as the inbox view shows it now or None, "current"/"retained"/None, its archived versions)."""
    view = event_inbox.inbox_view(inbox)
    location = next(((item, "current") for item in view["items"] if item["id"] == item_id), None) or \
        next(((item, "retained") for item in view["retained"] if item["id"] == item_id), None) or \
        next(((item, "imported") for item in view["imported"] if item["id"] == item_id), (None, None))
    source = item_id.split(":", 1)[0]
    versions = []
    if source in event_inbox.SOURCES:
        state, archive, _ = inbox_archive.read_archive(
            inbox, source, event_inbox.SOURCES[source].feed_url,
            lambda link, source=source: event_inbox._is_official(link, event_inbox.SOURCES[source]))
        if state == "ok":
            versions = next((entry["versions"] for entry in archive["entries"] if entry["id"] == item_id), [])
    elif source in inbox_imports.SOURCES:  # An imported snapshot record: its versions are its entry files.
        versions = inbox_imports.versions(inbox, item_id)
    return location[0], location[1], versions


def check_origin(origin: object, inbox: Path) -> dict:
    """The entry version an origin names, found among what the inbox holds; refused before anything is captured."""
    if not isinstance(origin, dict) or set(origin) != {"item_id", "content_sha256"} or \
            not all(isinstance(value, str) for value in origin.values()) or \
            not SHA256.fullmatch(origin["content_sha256"]):
        raise LinkRefused(422, "An origin names exactly an Inbox entry ID and the content SHA-256 of the version shown")
    item, location, versions = _versions(inbox, origin["item_id"])
    if item is None and not versions:
        raise LinkRefused(409, "The Inbox entry that filled the form is not held locally; nothing was captured. Choose "
                               "the entry again, or clear the form")
    numbered = [index for index, version in enumerate(versions, start=1)
                if version["content_sha256"] == origin["content_sha256"]]
    if item is not None and inbox_archive.content_sha256(item) == origin["content_sha256"]:
        shown = {"title": item["title"], "link": item["link"], "raw": item["feed_timestamp"]["raw"]}
    elif numbered:
        version = versions[numbered[-1] - 1]
        location = "archived"
        shown = {"title": version["title"], "link": version["link"], "raw": version["feed_timestamp"]["raw"]}
    else:
        raise LinkRefused(409, "The Inbox entry changed after it filled the form, so the version you started from is "
                               "not held; nothing was captured. Choose the entry again to start from its current "
                               "version")
    return {"item_id": origin["item_id"], "source": origin["item_id"].split(":", 1)[0],
            "content_sha256": origin["content_sha256"], "version": numbered[-1] if numbered else None,
            "versions": len(versions), "location": location, "title": shown["title"], "link": shown["link"],
            "feed_timestamp_raw": shown["raw"]}


def path_for(links: Path, capture_id: str) -> Path:
    return links / f"{capture_id}.json"


def record_origin(links: Path, capture_id: str, intake: Path, origin: dict, clock) -> dict:
    """Records the checked origin of a capture that was just saved. Never replaces a record."""
    record = event_intake.verified(intake, capture_id)
    link = {"link_version": LINK_VERSION, "capture_id": capture_id,
            "capture_request_sha256": record["request"]["sha256"], "inbox": origin,
            "form": {"headline_matches": record["event"]["headline"] == origin["title"],
                     "source_url_matches": record["event"]["source_url"] == origin["link"]},
            "recorded_at": event_inbox.stamp(clock()), "statement": STATEMENT}
    market_store.write_exclusive(path_for(links, capture_id), link)
    return link


def verified_link(links: Path, capture_id: str, intake: Path) -> dict:
    """One link record, checked against its own shape and the capture's request SHA-256. Raises LinkRefused (or the
    reader's own error) when it does not verify; reads only."""
    path = path_for(links, capture_id)
    link = market_context._strict_json(path.read_bytes(), path.name, 500)
    inbox_record = link.get("inbox")
    if set(link) != RECORD_FIELDS or link["link_version"] != LINK_VERSION or link["capture_id"] != capture_id or \
            not isinstance(inbox_record, dict) or set(inbox_record) != INBOX_FIELDS or \
            not SHA256.fullmatch(str(inbox_record["content_sha256"])) or \
            not isinstance(link["form"], dict) or set(link["form"]) != {"headline_matches", "source_url_matches"}:
        raise LinkRefused(500, "the link record does not have the expected fields")
    datetime.fromisoformat(link["recorded_at"])
    record = event_intake.verified(intake, capture_id)
    if record["request"]["sha256"] != link["capture_request_sha256"]:
        raise LinkRefused(500, "the link names another request than the capture's")
    return link


UNVERIFIED = (LinkRefused, market_context.ContextRefused, event_intake.IntakeRefused, OSError, ValueError, TypeError)


def read_origin(links: Path, capture_id: str, intake: Path, inbox: Path) -> dict:
    """A capture's recorded origin, verified, with where that entry version is now. Reads only.

    state: "none" (no link: the capture predates links or was typed by hand), "verified", or "unreadable"."""
    if not path_for(links, capture_id).exists():
        return {"state": "none", "link": None, "problem": None, "entry": None}
    try:
        link = verified_link(links, capture_id, intake)
    except UNVERIFIED as exc:
        return {"state": "unreadable", "link": None, "entry": None,
                "problem": f"The recorded Inbox origin of this capture cannot be used: {exc}. It was left unchanged"}
    inbox_record = link["inbox"]
    item, location, versions = _versions(inbox, inbox_record["item_id"])
    current = inbox_archive.content_sha256(item) if item is not None else None
    held = current == inbox_record["content_sha256"] or any(
        version["content_sha256"] == inbox_record["content_sha256"] for version in versions)
    return {"state": "verified", "link": link, "problem": None,
            "entry": {"held": held, "location": location, "current_content_sha256": current,
                      "same_version_as_current": current == inbox_record["content_sha256"],
                      "title_now": item["title"] if item else None}}


def captures_from(links: Path, item_id: str) -> list[dict]:
    """Every link record naming this Inbox entry, unverified (read_origin verifies each), oldest first. Reads only."""
    found = []
    for path in sorted(links.glob("*.json")) if links.is_dir() else []:
        try:
            link = json.loads(path.read_bytes())
            named = link["inbox"]["item_id"] if isinstance(link, dict) and isinstance(link.get("inbox"), dict) else None
        except (OSError, ValueError):
            named = None
        if named == item_id:
            found.append({"capture_id": path.stem, "recorded_at": link.get("recorded_at")})
    return sorted(found, key=lambda row: (str(row["recorded_at"]), row["capture_id"]))


def unreadable_links(links: Path) -> list[str]:
    """Link files whose entry cannot be read at all, so no overview can name them; listed, never repaired."""
    bad = []
    for path in sorted(links.glob("*.json")) if links.is_dir() else []:
        try:
            link = json.loads(path.read_bytes())
            if not isinstance(link, dict) or not isinstance(link.get("inbox"), dict):
                bad.append(path.name)
        except (OSError, ValueError):
            bad.append(path.name)
    return bad


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

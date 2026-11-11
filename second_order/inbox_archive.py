"""Event Inbox archive: every validated version of every entry the explicit refreshes retrieved, kept locally after
the entry leaves its feed.

The inbox keeps each source's latest retrieval (event_inbox). This archive is written only by a successful refresh of
that source, right after its record, in `archive/<source>.json` inside the inbox cache (under data/, ignored by git).
An entry keeps its stable source identity (GUID or Atom id, else link). When its meaningful content (title, link,
excerpt, feed timestamp and their truncation marks) is unchanged, only its last-seen time moves; when the content
changes, a new version is appended and the earlier one is kept. Retrieval time alone never makes a version. Nothing is
fetched for the archive: it holds only what refreshes already retrieved and validated. A missing archive starts from
the source's existing record, whose entries were retrieved by an earlier refresh.

Reading only reads. An archive that cannot be read is reported and left exactly as it is; a refresh never writes over
it, and nothing is repaired or re-fetched. Nothing expires or is deleted: a retained entry is shown with when it was
last seen in its feed.
"""
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

ARCHIVE_VERSION = "event-inbox-archive-0.1"
CONTENT_FIELDS = ("title", "title_truncated", "link", "excerpt", "excerpt_truncated", "excerpt_repeats_title",
                  "feed_timestamp")
RECORD_FIELDS = {"archive_version", "source", "feed_url", "entries"}
ENTRY_FIELDS = {"id", "identity", "versions"}
VERSION_FIELDS = set(CONTENT_FIELDS) | {"content_sha256", "first_seen_at", "last_seen_at"}
# A publisher feed whose licence asks for its creator to be credited (event_inbox.Source.credit_creator) also keeps
# ``creator`` with each entry; it is part of the content then. Entries without it are fingerprinted exactly as before.
CREATOR = "creator"
TIMESTAMP_FIELDS = {"raw", "origin", "instant_utc", "suggestion", "problem"}


def entry_id(key: str, identity: str) -> str:
    """The inbox's stable entry ID: its source and a hash of the feed's own identity, never of the title."""
    return f"{key}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def content_sha256(item: dict) -> str:
    """The fingerprint of an entry's meaningful content; retrieval and first-seen times are not part of it."""
    content = {field: item[field] for field in CONTENT_FIELDS}
    if CREATOR in item:
        content[CREATOR] = item[CREATOR]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def archive_path(inbox: Path, key: str) -> Path:
    return inbox / "archive" / f"{key}.json"


def _moment(value: object) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _problem(record: object, key: str, feed_url: str, valid_link: Callable[[str], bool],
             creator: bool = False) -> str | None:
    """Why an archive cannot be trusted, or None. Every field a reader uses is checked. ``creator``: the source keeps
    each entry's creator."""
    fields = VERSION_FIELDS | ({CREATOR} if creator else set())
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS or not isinstance(record["entries"], list):
        return "The local archive does not have the expected fields"
    if (record["archive_version"], record["source"], record["feed_url"]) != (ARCHIVE_VERSION, key, feed_url):
        return "The local archive names another version, source or feed"
    seen = set()
    for entry in record["entries"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS or not isinstance(entry["identity"], str) or \
                entry["id"] != entry_id(key, entry["identity"]) or entry["id"] in seen or \
                not isinstance(entry["versions"], list) or not entry["versions"]:
            return "The local archive holds a malformed entry"
        seen.add(entry["id"])
        previous = None
        for version in entry["versions"]:
            if not isinstance(version, dict) or set(version) != fields or                     not (version.get(CREATOR) is None or isinstance(version[CREATOR], str)) or \
                    not all(isinstance(version[field], str) for field in ("title", "link", "content_sha256")) or \
                    not (version["excerpt"] is None or isinstance(version["excerpt"], str)) or \
                    not isinstance(version["feed_timestamp"], dict) or \
                    set(version["feed_timestamp"]) != TIMESTAMP_FIELDS or not valid_link(version["link"]) or \
                    not _moment(version["first_seen_at"]) or not _moment(version["last_seen_at"]):
                return "The local archive holds a malformed version"
            if version["content_sha256"] != content_sha256(version) or version["content_sha256"] == previous:
                return "The local archive holds a version whose content does not match its fingerprint"
            previous = version["content_sha256"]
    return None


def read_archive(inbox: Path, key: str, feed_url: str, valid_link: Callable[[str], bool],
                 creator: bool = False) -> tuple[str, dict | None, str | None]:
    """("missing" | "ok" | "unreadable", archive, problem). Reads only; an unreadable archive is never repaired."""
    path = archive_path(inbox, key)
    if not path.exists():
        return "missing", None, None
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return "unreadable", None, "The local archive is not readable JSON"
    problem = _problem(record, key, feed_url, valid_link, creator)
    return ("unreadable", None, problem) if problem else ("ok", record, None)


def updated_archive(archive: dict | None, key: str, feed_url: str, previous: dict | None, items: list[dict],
                    retrieved_at: str) -> dict:
    """The archive after one successful retrieval of these items. A missing archive starts from the source's previous
    successful retrieval. Unchanged content only moves its last-seen time; changed content appends a version."""
    if archive is None:
        archive = {"archive_version": ARCHIVE_VERSION, "source": key, "feed_url": feed_url, "entries": []}
        observed = [(item, item["first_seen_at"], previous["retrieved_at"]) for item in (previous or {}).get("items", [])]
    else:
        archive, observed = copy.deepcopy(archive), []
    entries = {entry["identity"]: entry for entry in archive["entries"]}
    for item, first_seen, last_seen in observed + [(item, retrieved_at, retrieved_at) for item in items]:
        entry = entries.get(item["identity"])
        if entry is None:
            entry = entries[item["identity"]] = {"id": item["id"], "identity": item["identity"], "versions": []}
            archive["entries"].append(entry)
        fingerprint = content_sha256(item)
        latest = entry["versions"][-1] if entry["versions"] else None
        if latest is not None and latest["content_sha256"] == fingerprint:
            latest["last_seen_at"] = max(latest["last_seen_at"], last_seen)  # Both are UTC stamps of one form.
        else:
            entry["versions"].append({**{field: item[field] for field in CONTENT_FIELDS},
                                      **({CREATOR: item[CREATOR]} if CREATOR in item else {}),
                                      "content_sha256": fingerprint, "first_seen_at": first_seen,
                                      "last_seen_at": last_seen})
    return archive


def write_archive(inbox: Path, key: str, archive: dict) -> None:
    """Atomically replace one source's archive: the old file stays intact until the new one is complete."""
    folder = archive_path(inbox, key).parent
    folder.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(archive, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=f".{key}-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, archive_path(inbox, key))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def retained_items(archive: dict | None, current_ids: set[str]) -> list[dict]:
    """Archived entries that are not in the source's latest retrieval, each at its latest version. Reads only."""
    retained = []
    for entry in (archive or {}).get("entries", []):
        if entry["id"] in current_ids:
            continue
        latest = entry["versions"][-1]
        retained.append({"id": entry["id"], **{field: latest[field] for field in CONTENT_FIELDS},
                         **({CREATOR: latest[CREATOR]} if CREATOR in latest else {}),
                         "first_seen_at": latest["first_seen_at"], "last_seen_at": latest["last_seen_at"],
                         "versions": len(entry["versions"])})
    return retained


def earlier_versions(archive: dict | None, item: dict) -> int:
    """How many archived versions of this entry differ from its current content."""
    fingerprint = content_sha256(item)
    for entry in (archive or {}).get("entries", []):
        if entry["id"] == item["id"]:
            return sum(version["content_sha256"] != fingerprint for version in entry["versions"])
    return 0

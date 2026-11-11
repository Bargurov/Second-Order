"""Event Inbox imports (inbox-import-0.1): records of the retained BIS snapshot (see bis_snapshot) that the operator
explicitly chose to add to the Event Inbox. Local and free: nothing is requested, and nothing is classified,
summarized or analyzed on import. An imported record is a snapshot record, not a live-feed entry, and importing it
does not verify its claims.

Under <inbox>/imports/bis-snapshot/ (git-ignored with the inbox): entries/<key>/<n>.json, one write-once, read-only
file per version of a document, and records/<import id>.json, one write-once record per import that added anything.
A document's identity is its press-release address on www.bis.gov; its key is the first 20 hex digits of that
address's SHA-256, and its Inbox entry ID is bis-snapshot:<key>. A preview sorts the selection into new records (to
be added), existing ones (reused: their source version is already held), changed ones (the snapshot's source version
differs from the one held; nothing changes without an explicit decision, and the only change is to add a new
version beside the old) and unusable ones, with reasons. An import repeats that sorting under one lock, writes each
version with an atomic create that never overwrites, and writes nothing when everything is reused: repeated clicks,
concurrent submissions and restarts never duplicate an entry. An entry file that does not verify is reported and
left as it is.

Imported entries appear in the Inbox view beside the feeds' entries, never among them: headline triage, whose prompt
names the five feeds, does not offer them, so no saved triage result or fingerprint changes. Their Inbox content (the
fields an entry version is identified by, see inbox_archive) has a bounded excerpt of the listing's text; the full
text and every extracted source field stay in the entry file. The listing's publication timestamp is shown as listing
metadata and never as a suggested publication time.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Callable
from urllib.parse import urlsplit

from . import bis_snapshot, inbox_archive

SOURCE_KEY = "bis-snapshot"
ENTRY_VERSION = "inbox-import-entry-0.1"
IMPORT_VERSION = "inbox-import-0.1"
MAX_SELECTION = 25  # As many as one headline triage may name (headline_triage.MAX_SELECTION).
MAX_EXCERPT = 1200  # The Inbox's excerpt bound (event_inbox.MAX_EXCERPT); a test keeps them equal.
DECISIONS = ("keep", "add_version")
KEY = re.compile(r"[0-9a-f]{20}")
ORIGIN = "BIS News & Updates listing data (publishedOn, UTC) in the retained snapshot"
LISTING_NOTE = ("Listing metadata from a retained snapshot, not the release's dateline: no publication date or time is "
                "suggested from it.")


@dataclass(frozen=True)
class SnapshotSource:
    key: str
    label: str
    publisher: str
    category: str
    kind: str
    host: str
    page_url: str


SOURCES = {SOURCE_KEY: SnapshotSource(
    SOURCE_KEY, "BIS News & Updates (retained snapshot)",
    "U.S. Department of Commerce, Bureau of Industry and Security (BIS)", "Export controls", "Press release",
    bis_snapshot.HOST, bis_snapshot.PAGE_URL)}
_lock = threading.Lock()  # One import at a time in this process; atomic creates guard across processes.


class ImportRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def now() -> datetime:
    return datetime.now(timezone.utc)


def folder(inbox: Path) -> Path:
    return inbox / "imports" / SOURCE_KEY


# ---------------------------------------------------------------- what an imported record holds

def feed_timestamp(record: dict) -> dict:
    """The Inbox's timestamp fields for a snapshot record: the listing's publication timestamp, raw, as listing
    metadata; never a suggestion."""
    published = record["listing"]["published"]
    if published["state"] == "listed":
        moment = datetime.fromisoformat(published["time"]).astimezone(timezone.utc).isoformat(timespec="seconds")
        return {"raw": published["time"], "origin": ORIGIN, "instant_utc": moment, "suggestion": None,
                "problem": LISTING_NOTE}
    reason = ("The listing data gives no publication time for this record; its CMS creation and update times are not "
              "publication times and are not used." if published["state"] == "missing" else published["problem"])
    return {"raw": None, "origin": ORIGIN, "instant_utc": None, "suggestion": None, "problem": reason}


def inbox_content(record: dict) -> dict:
    """The Inbox content fields (inbox_archive.CONTENT_FIELDS) of a snapshot record."""
    title = record["publisher"]["title"]
    text = " ".join(record["text"]["paragraphs"])
    excerpt, cut = ((text[:MAX_EXCERPT - 1].rstrip() + "…", True) if len(text) > MAX_EXCERPT
                    else (text or None, False))
    return {"title": title, "title_truncated": record["publisher"]["title_truncated"], "link": record["identity"],
            "excerpt": excerpt, "excerpt_truncated": cut, "excerpt_repeats_title": excerpt == title,
            "feed_timestamp": feed_timestamp(record)}


def official(link) -> bool:
    try:
        parts = urlsplit(link)
        return parts.scheme == "https" and parts.hostname == bis_snapshot.HOST and parts.port is None and \
            bis_snapshot.official_address(parts.path) == link
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- the store

ENTRY_FIELDS = {"entry_version", "source", "id", "identity", "version", "import_id", "imported_at", "content",
                "content_sha256", "record", "record_sha256", "snapshot"}
SNAPSHOT_FIELDS = {"package", "extractor_version", "index_version", "index_sha256"}


def _entry_problem(entry, key: str, number: int) -> str | None:
    if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
        return "it does not have the expected fields"
    if (entry["entry_version"], entry["source"], entry["id"], entry["version"]) != \
            (ENTRY_VERSION, SOURCE_KEY, f"{SOURCE_KEY}:{key}", number):
        return "it names another version, source, entry or version number"
    record = entry["record"]
    if not isinstance(record, dict) or record.get("key") != key or record.get("identity") != entry["identity"] or \
            not official(entry["identity"]):
        return "its record is not the one its name and address give"
    content = entry["content"]
    try:  # Each stored hash is checked against what it covers; wording added later never invalidates an entry.
        if bis_snapshot.record_sha256(record) != entry["record_sha256"] or \
                not isinstance(content, dict) or set(content) != set(inbox_archive.CONTENT_FIELDS) or \
                inbox_archive.content_sha256(content) != entry["content_sha256"] or \
                content["title"] != record["publisher"]["title"] or content["link"] != entry["identity"]:
            return "its content does not match its recorded SHA-256 values or its record"
    except (KeyError, TypeError, ValueError, AttributeError):
        return "its record is malformed"
    if not isinstance(entry["snapshot"], dict) or set(entry["snapshot"]) != SNAPSHOT_FIELDS or \
            bis_snapshot._utc_or_none(entry["imported_at"]) is None:
        return "its snapshot provenance or import time is malformed"
    return None


def read_entries(inbox: Path) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """({key: versions in order}, {key: why it cannot be read}). Reads only; nothing unreadable is repaired."""
    root = folder(inbox) / "entries"
    entries, unreadable = {}, {}
    if not root.is_dir():
        return entries, unreadable
    for directory in sorted(root.iterdir()):
        key = directory.name
        if not directory.is_dir() or not KEY.fullmatch(key):
            continue
        names = sorted((path for path in directory.glob("*.json")), key=lambda path: (len(path.stem), path.stem))
        versions = []
        for expected, path in enumerate(names, start=1):
            problem = None if path.stem == str(expected) else "its versions are not numbered 1, 2, 3 …"
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                entry, problem = None, "a version is not readable JSON"
            problem = problem or _entry_problem(entry, key, expected)
            if problem:
                unreadable[key] = f"The imported entry {SOURCE_KEY}:{key} cannot be used: {problem}. It was left as it is."
                break
            versions.append(entry)
        if key not in unreadable and versions:
            entries[key] = versions
    return entries, unreadable


def versions(inbox: Path, item_id: str) -> list[dict]:
    """An imported entry's versions as the archive presents its versions (content, content SHA-256, times)."""
    key = item_id.split(":", 1)[1] if item_id.startswith(f"{SOURCE_KEY}:") else ""
    found = read_entries(inbox)[0].get(key, [])
    return [{**entry["content"], "content_sha256": entry["content_sha256"], "first_seen_at": entry["imported_at"],
             "last_seen_at": entry["imported_at"]} for entry in found]


def fixed_fields() -> dict:
    source = SOURCES[SOURCE_KEY]
    return {"source": source.key, "publisher": source.publisher, "category": source.category, "kind": source.kind,
            "attribution": ""}


def items(inbox: Path) -> tuple[list[dict], dict]:
    """The imported entries as the Inbox shows them (latest version of each), and what the store holds. Reads only."""
    entries, unreadable = read_entries(inbox)
    shown = []
    for key, found in entries.items():
        latest = found[-1]
        record = latest["record"]
        shown.append({
            "id": latest["id"], **latest["content"], "position": None, "first_seen_at": found[0]["imported_at"],
            **fixed_fields(), "retrieved_at": latest["snapshot"]["package"]["retrieved_at"], "stale": False,
            "content_sha256": latest["content_sha256"],
            "imported": {"label": "Imported from a retained BIS snapshot, not a live feed",
                         "import_id": latest["import_id"], "imported_at": latest["imported_at"],
                         "version": latest["version"], "versions": len(found), "record_sha256": latest["record_sha256"],
                         "snapshot": latest["snapshot"], "record": record,
                         "completeness": bis_snapshot.COMPLETENESS[record["completeness"]]}})
    shown.sort(key=lambda item: (item["feed_timestamp"]["instant_utc"] is None,
                                 -datetime.fromisoformat(item["feed_timestamp"]["instant_utc"]).timestamp()
                                 if item["feed_timestamp"]["instant_utc"] else 0.0, item["id"]))
    summary = {"source": SOURCE_KEY, "label": SOURCES[SOURCE_KEY].label, "entries": len(entries),
               "versions": sum(len(found) for found in entries.values()),
               "unreadable": [{"key": key, "problem": problem} for key, problem in sorted(unreadable.items())],
               "statement": ("Records explicitly imported from the retained BIS News & Updates snapshot (one page "
                             "retained on approval, not a live feed). They are listed apart from the feeds' entries "
                             "and are not offered for headline triage.")}
    return shown, summary


def states(inbox: Path) -> dict[str, dict]:
    """{key: {"state": "imported"|"unreadable", "record_sha256", "versions"}} for the snapshot page. Reads only."""
    entries, unreadable = read_entries(inbox)
    found = {key: {"state": "imported", "record_sha256": versions_[-1]["record_sha256"], "versions": len(versions_)}
             for key, versions_ in entries.items()}
    found.update({key: {"state": "unreadable", "record_sha256": None, "versions": None} for key in unreadable})
    return found


# ---------------------------------------------------------------- preview and import

def _changes(held: dict, record: dict) -> list[str]:
    labels = {"title": "title", "text": "text", "published": "listing publication time", "summary": "summary",
              "topics": "topics", "countries": "country tags", "external_link": "external link", "uuid": "document ID"}
    old = held["record"]
    pairs = {"title": (old["publisher"]["title"], record["publisher"]["title"]),
             "text": (old["text"]["paragraphs"], record["text"]["paragraphs"]),
             "published": (old["listing"]["published"]["time"], record["listing"]["published"]["time"]),
             "summary": (old["publisher"]["summary"], record["publisher"]["summary"]),
             "topics": (old["publisher"]["topics"], record["publisher"]["topics"]),
             "countries": (old["publisher"]["countries"], record["publisher"]["countries"]),
             "external_link": (old["publisher"]["external_link"], record["publisher"]["external_link"]),
             "uuid": (old["document"]["uuid"], record["document"]["uuid"])}
    return [labels[name] for name, (before, after) in pairs.items() if before != after] or ["other source fields"]


def _selection(keys) -> list[str]:
    if not isinstance(keys, list) or not keys or len(keys) > MAX_SELECTION or \
            not all(isinstance(key, str) and KEY.fullmatch(key) for key in keys) or len(set(keys)) != len(keys):
        raise ImportRefused(422, f"Select between 1 and {MAX_SELECTION} distinct records of the snapshot")
    return keys


def classify(index: dict, keys: list[str], inbox: Path) -> list[dict]:
    """Each selected record: new, existing (reused), changed (a decision is needed) or unusable, with reasons."""
    records = {record["key"]: record for record in index["records"]}
    unusable = {entry["key"]: entry for entry in index["unusable"] if entry.get("key")}
    entries, unreadable = read_entries(inbox)
    rows = []
    for key in _selection(keys):
        record = records.get(key)
        base = {"key": key, "id": f"{SOURCE_KEY}:{key}", "title": record["publisher"]["title"] if record else
                (unusable.get(key) or {}).get("title")}
        if record is None:
            reasons = unusable[key]["reasons"] if key in unusable else ["It is not a record of this snapshot"]
            rows.append({**base, "state": "unusable", "reasons": reasons})
        elif key in unreadable:
            rows.append({**base, "state": "unusable", "reasons": [unreadable[key]]})
        elif key not in entries:
            rows.append({**base, "state": "new", "reasons": []})
        elif entries[key][-1]["record_sha256"] == record["record_sha256"]:
            rows.append({**base, "state": "existing", "version": entries[key][-1]["version"], "reasons": [
                "This source version is already in the Event Inbox; it will be reused and nothing is written."]})
        else:
            rows.append({**base, "state": "changed", "version": entries[key][-1]["version"],
                         "changed": _changes(entries[key][-1], record), "reasons": [
                "The snapshot's source version differs from the one already imported. Keep the existing version, "
                "or add this one as a new version beside it; nothing is replaced."]})
    return rows


def preview(index: dict, body: dict, inbox: Path) -> dict:
    if not isinstance(body, dict) or set(body) != {"keys"}:
        raise ImportRefused(422, "A preview names exactly the selected record keys")
    rows = classify(index, body["keys"], inbox)
    counts = {state: sum(row["state"] == state for row in rows) for state in ("new", "existing", "changed", "unusable")}
    return {"rows": rows, "counts": counts, "cost": "Local and free: nothing is requested, sent or classified.",
            "writes": counts["new"] > 0 or counts["changed"] > 0}


def _write_once(path: Path, data: bytes) -> bool:
    return bis_snapshot._write_once(path, data)


def _entry(record: dict, index: dict, version: int, import_id: str, imported_at: str) -> dict:
    content = inbox_content(record)
    return {"entry_version": ENTRY_VERSION, "source": SOURCE_KEY, "id": f"{SOURCE_KEY}:{record['key']}",
            "identity": record["identity"], "version": version, "import_id": import_id, "imported_at": imported_at,
            "content": content, "content_sha256": inbox_archive.content_sha256(content), "record": record,
            "record_sha256": record["record_sha256"],
            "snapshot": {"package": index["package"], "extractor_version": index["extractor_version"],
                         "index_version": index["index_version"], "index_sha256": index["content_sha256"]}}


def run_import(index: dict, body: dict, inbox: Path, clock: Callable[[], datetime] = now) -> dict:
    """The explicit import: new records added, existing ones reused, changed ones kept or given a new version as
    decided. Writes nothing when nothing is added."""
    if not isinstance(body, dict) or set(body) != {"keys", "decisions"} or not isinstance(body["decisions"], dict):
        raise ImportRefused(422, "An import names the selected record keys and a decision for each changed record")
    keys, decisions = _selection(body["keys"]), body["decisions"]
    if not set(decisions) <= set(keys) or not all(value in DECISIONS for value in decisions.values()):
        raise ImportRefused(422, f"Decisions name selected records and are one of {list(DECISIONS)}")
    with _lock:
        rows = classify(index, keys, inbox)
        undecided = [row["id"] for row in rows if row["state"] == "changed" and row["key"] not in decisions]
        if undecided:
            raise ImportRefused(409, f"{len(undecided)} selected record(s) changed since they were imported and need "
                                     f"an explicit decision: {', '.join(undecided)}. Nothing was written.")
        moment = clock().astimezone(timezone.utc)
        imported_at = moment.isoformat(timespec="seconds")
        import_id = f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:8]}"
        records = {record["key"]: record for record in index["records"]}
        results = []
        for row in rows:
            key, state = row["key"], row["state"]
            if state in ("unusable", "existing") or (state == "changed" and decisions[key] == "keep"):
                outcome = {"unusable": "unusable", "existing": "reused", "changed": "kept"}[state]
                results.append({**row, "outcome": outcome})
                continue
            number = 1 if state == "new" else row["version"] + 1
            path = folder(inbox) / "entries" / key / f"{number}.json"
            entry = _entry(records[key], index, number, import_id, imported_at)
            if _write_once(path, (json.dumps(entry, ensure_ascii=False, indent=1) + "\n").encode("utf-8")):
                results.append({**row, "outcome": "added" if state == "new" else "version_added", "version": number})
                continue
            # Another import created this version first: the same source version is reused, anything else is reported.
            held = json.loads(path.read_text(encoding="utf-8"))
            same = held.get("record_sha256") == records[key]["record_sha256"]
            results.append({**row, "outcome": "reused" if same else "conflict", "version": number,
                            "reasons": row["reasons"] + ([] if same else [
                                "Another import wrote a different version first; nothing was replaced."])})
        written = [row for row in results if row["outcome"] in ("added", "version_added")]
        if written:
            _write_once(folder(inbox) / "records" / f"{import_id}.json", (json.dumps({
                "import_version": IMPORT_VERSION, "import_id": import_id, "imported_at": imported_at,
                "snapshot": {"package": index["package"], "extractor_version": index["extractor_version"],
                             "index_sha256": index["content_sha256"]},
                "selection": keys, "decisions": decisions,
                "results": [{key_: row.get(key_) for key_ in ("key", "id", "outcome", "version")} for row in results]},
                ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    counts = {outcome: sum(row["outcome"] == outcome for row in results)
              for outcome in ("added", "version_added", "reused", "kept", "unusable", "conflict")}
    return {"import_id": import_id if written else None, "imported_at": imported_at if written else None,
            "rows": results, "counts": counts, "written": bool(written),
            "cost": "Local and free: nothing was requested, sent or classified."}

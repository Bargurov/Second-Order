"""Event Inbox acquisitions (inbox-acquisition-0.1): one write-once record of every feed request an explicit refresh
made, accepted or not, kept privately beside the inbox cache in data/event-inbox/acquisitions/<source>/<n>.json.

A record states what was asked and what came back, as far as this client saw it:

- the request: the exact endpoint, GET, whether the operator's contact was in the User-Agent, and that it carried no
  cache validators (no conditional request is made), followed no redirect and was never retried;
- when it started and finished;
- the response: the HTTP status and version, a fixed list of headers (the cache validators ETag and Last-Modified
  among them), the names of the other headers without their values, and how many Set-Cookie headers came (never
  their values);
- the body: complete (the HTTP message ended as its framing said), partial (it stopped early: the count and SHA-256 of
  the bytes that did arrive), not_read (an error status or a redirect) or none (no response). The SHA-256 is of the
  body as this client decoded it, and any content encoding the server applied is named. An accepted response's bytes
  are kept by inbox_raw, and the record names the file;
- for an accepted response: the parser version and the counts it reported (listed, retained, beyond retention,
  repeated, skipped with reasons), each retained entry with its stable ID, content fingerprint
  (inbox_archive.content_sha256), feed position and which of its texts were shortened, and how the entries compared
  with what was held before the request (changes): new, changed or unchanged by stable identity and content, never by
  title, and which entries of the previous retrieval the feed no longer lists.

Records are numbered, created exclusively and made read-only; nothing rewrites, repairs or deletes one. A record that
cannot be read is reported, never used. Requests made before records existed have none, and none is reconstructed.
Nothing here requests anything: it records what event_inbox's refresh already did. A feed's text is described by what
it is: the headline and the feed's excerpt (the description it supplies, not the article). No article is fetched.
"""
import hashlib
import json
from pathlib import Path
import re

import httpx

from . import inbox_raw
from .inbox_archive import content_sha256

ACQUISITION_VERSION = "inbox-acquisition-0.1"
OUTCOMES = ("accepted", "refused", "failed")
BODY_STATES = ("complete", "partial", "not_read", "none")
KEPT_HEADERS = ("age", "cache-control", "content-encoding", "content-length", "content-type", "date", "etag", "expires",
                "last-modified", "location", "retry-after", "vary")
MAX_HEADER_VALUE = 300
MAX_OTHER_NAMES = 40
NUMBER = re.compile(r"(\d{6})\.json")
RECORD_FIELDS = {"acquisition_version", "number", "source", "endpoint", "request", "started_at", "finished_at",
                 "outcome", "detail", "response", "body", "parser", "items", "changes", "notes"}
ITEM_FIELDS = {"id", "content_sha256", "position", "text"}
REQUEST = {"method": "GET", "conditional": False, "redirects_followed": False, "retries": 0}


def folder(inbox: Path, key: str) -> Path:
    return inbox / "acquisitions" / key


def _one_line(value: str) -> str:
    text = "".join(char if char.isprintable() else " " for char in value).strip()
    return text if len(text) <= MAX_HEADER_VALUE else text[:MAX_HEADER_VALUE - 1] + "…"


def response_metadata(response: httpx.Response) -> dict:
    """What a record keeps of a response's status line and headers. Set-Cookie values are never kept."""
    kept: dict[str, str] = {}
    others, cookies = set(), 0
    for name, value in response.headers.multi_items():
        name = name.lower()
        if name == "set-cookie":
            cookies += 1
        elif name in KEPT_HEADERS:
            kept[name] = _one_line(f"{kept[name]}, {value}" if name in kept else value)
        else:
            others.add(name[:60])
    return {"http_status": response.status_code, "http_version": response.http_version, "headers": kept,
            "other_header_names": sorted(others)[:MAX_OTHER_NAMES], "set_cookie_count": cookies,
            "validators": {"etag": kept.get("etag"), "last_modified": kept.get("last-modified")}}


class Received:
    """What arrived of one response body, as it arrived: its state, byte count and running SHA-256."""

    def __init__(self):
        self.state, self.size, self._hash = "none", 0, hashlib.sha256()

    def add(self, chunk: bytes) -> None:
        self.size += len(chunk)
        self._hash.update(chunk)

    def summary(self, response: dict | None) -> dict:
        headers = (response or {}).get("headers", {})
        declared = headers.get("content-length", "")
        return {"state": self.state, "bytes": self.size,
                "sha256": self._hash.hexdigest() if self.state in ("complete", "partial") else None,
                "declared_bytes": int(declared) if declared.isdigit() else None,
                "content_encoding": headers.get("content-encoding")}


def text_parts(item: dict) -> dict:
    """Which of an entry's texts the feed supplied and whether this inbox shortened them. The excerpt is the feed's own
    description, never the article."""
    excerpt = ("none" if not item["excerpt"] else "repeats_title" if item["excerpt_repeats_title"]
               else "shortened" if item["excerpt_truncated"] else "as_supplied")
    return {"title": "shortened" if item["title_truncated"] else "as_supplied", "excerpt": excerpt}


def changes(archive: dict | None, previous: dict | None, items: list[dict]) -> dict:
    """How one accepted retrieval's entries compare with what was held before it, by stable identity and then content
    fingerprint. The basis is the archive's latest versions when it is readable, else the previous retrieval."""
    if archive is not None:
        known = {entry["identity"]: entry["versions"][-1]["content_sha256"] for entry in archive["entries"]}
        basis = "archive"
    else:
        known = {item["identity"]: content_sha256(item) for item in (previous or {}).get("items", [])}
        basis = "latest_retrieval" if previous else "none"
    rows: dict[str, list[str]] = {"new": [], "changed": [], "unchanged": []}
    for item in items:
        before = known.get(item["identity"])
        kind = "new" if before is None else "unchanged" if before == content_sha256(item) else "changed"
        rows[kind].append(item["id"])
    listed = {item["identity"] for item in items}
    gone = [item["id"] for item in (previous or {}).get("items", []) if item["identity"] not in listed]
    return {"basis": basis, **rows, "no_longer_listed": gone}


def build(key: str, endpoint: str, started_at: str, finished_at: str | None, outcome: str, detail: str | None,
          contact_sent: bool, response: dict | None, body: dict, parsed: dict | None, parser_version: str,
          items: list[dict], found: dict | None, kept: str | None, notes: list[str]) -> dict:
    """One acquisition record, before it is numbered."""
    return {
        "acquisition_version": ACQUISITION_VERSION, "number": None, "source": key, "endpoint": endpoint,
        "request": {**REQUEST, "contact_sent": contact_sent}, "started_at": started_at, "finished_at": finished_at,
        "outcome": outcome, "detail": detail, "response": response, "body": {**body, "kept": kept},
        "parser": None if parsed is None else {
            "version": parser_version, "format": parsed["format"], "listed": parsed["listed"],
            "retained": len(items), "not_retained": parsed["not_retained"], "duplicates": parsed["duplicates"],
            "skipped_count": parsed["skipped_count"], "skipped": parsed["skipped"]},
        "items": [{"id": item["id"], "content_sha256": content_sha256(item), "position": item["position"],
                   "text": text_parts(item)} for item in items],
        "changes": found, "notes": notes}


def keep(inbox: Path, key: str, record: dict) -> int:
    """Write one record under the next free number, exclusively and read-only; returns the number."""
    target = folder(inbox, key)
    for _ in range(5):  # Another process may take a number between listing and creating; a name is never reused.
        number = max((int(match.group(1)) for path in target.glob("*.json") if (match := NUMBER.fullmatch(path.name))),
                     default=0) + 1 if target.is_dir() else 1
        data = (json.dumps({**record, "number": number}, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
        if inbox_raw.write_once(target / f"{number:06d}.json", data):
            return number
    raise OSError("no free acquisition number")


def _problem(record: object, number: int, key: str, endpoint: str) -> str | None:
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        return "it does not have the expected fields"
    if (record["acquisition_version"], record["number"], record["source"], record["endpoint"]) != \
            (ACQUISITION_VERSION, number, key, endpoint):
        return "it names another version, number, source or endpoint"
    body, response = record["body"], record["response"]
    if record["outcome"] not in OUTCOMES or not isinstance(body, dict) or body.get("state") not in BODY_STATES or \
            not isinstance(record["started_at"], str) or not (response is None or isinstance(response, dict)):
        return "its outcome, times, response or body are malformed"
    if not isinstance(record["items"], list) or any(not isinstance(item, dict) or set(item) != ITEM_FIELDS or
                                                    not isinstance(item["id"], str) for item in record["items"]):
        return "it lists a malformed entry"
    if record["outcome"] == "accepted" and (body["state"] != "complete" or not isinstance(record["parser"], dict)):
        return "an accepted record without a complete body or parser counts"
    return None


def records(inbox: Path, key: str, endpoint: str) -> tuple[list[dict], list[dict]]:
    """Every record of one source that verifies, oldest first, and every file that does not (with why). Reads only."""
    target = folder(inbox, key)
    good, bad = [], []
    for path in sorted(target.glob("*.json")) if target.is_dir() else []:
        match = NUMBER.fullmatch(path.name)
        if not match:
            continue
        try:
            record = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            record = None
        problem = _problem(record, int(match.group(1)), key, endpoint) if record is not None else "it is not JSON"
        if problem:
            bad.append({"file": path.name, "problem": f"Retrieval record {path.name} cannot be used: {problem}"})
        else:
            good.append(record)
    return good, bad


def counts(record: dict) -> dict | None:
    """What one accepted retrieval added, reused, changed and refused; None for a request that was not accepted."""
    if record["outcome"] != "accepted":
        return None
    found, parser = record["changes"] or {}, record["parser"]
    return {"new": len(found.get("new", [])), "changed": len(found.get("changed", [])),
            "unchanged": len(found.get("unchanged", [])), "no_longer_listed": len(found.get("no_longer_listed", [])),
            "skipped": parser["skipped_count"], "duplicates": parser["duplicates"],
            "not_retained": parser["not_retained"], "basis": found.get("basis")}


def summary(inbox: Path, record: dict) -> dict:
    """One record as the inbox shows it, with its kept copy checked against the bytes it names."""
    response, body = record["response"] or {}, record["body"]
    return {"number": record["number"], "started_at": record["started_at"], "finished_at": record["finished_at"],
            "outcome": record["outcome"], "detail": record["detail"], "endpoint": record["endpoint"],
            "http_status": response.get("http_status"), "headers": response.get("headers", {}),
            "validators": response.get("validators"), "body": body,
            "kept_copy": inbox_raw.kept_state(inbox, record["source"], body.get("kept"), body.get("sha256")),
            "parser_version": (record["parser"] or {}).get("version"), "counts": counts(record),
            "notes": record["notes"]}


def latest(inbox: Path, key: str, endpoint: str) -> dict:
    """The source's newest readable record, summarised, and how many records it has. Reads only the newest files."""
    target = folder(inbox, key)
    names = sorted((path.name for path in target.glob("*.json") if NUMBER.fullmatch(path.name)), reverse=True) \
        if target.is_dir() else []
    skipped = []
    for name in names:
        try:
            record = json.loads((target / name).read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            record = None
        problem = _problem(record, int(name[:6]), key, endpoint) if record is not None else "it is not JSON"
        if problem is None:
            return {"count": len(names), "latest": summary(inbox, record), "unreadable_newer": skipped}
        skipped.append(f"Retrieval record {name} cannot be used: {problem}")
    return {"count": len(names), "latest": None, "unreadable_newer": skipped}

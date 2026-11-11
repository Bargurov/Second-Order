"""Raw feed copies: the complete response body of each accepted feed retrieval, kept privately during an explicit
refresh, as this client received it (after undoing any content encoding, such as gzip, that the server applied; the
retrieval record names the encoding).

Storage only. The bytes are the ones the refresh already received within its own limits; nothing is requested, parsed,
summarised or sent here, and no linked article is fetched. Items, their fingerprints, the source record and its archive
are unchanged by this, and nothing reads these copies to build the inbox. Under data/event-inbox/raw/<source>/ (git
ignored), <sha256>.xml holds the bytes, written once and read-only, shared by retrievals that received identical bytes.
Each retrieval is described by its acquisition record (inbox_acquisitions), which names the file. Retrievals made
before copies existed have none, and none is reconstructed.

Under inbox-raw-0.1 (the WTO feed only) each retrieval also had a <retrieved_at>-<sha256 prefix>.json record beside the
bytes; such records are still read (records), and no new ones are written.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

RAW_VERSION = "inbox-raw-0.1"


def raw_dir(inbox: Path, key: str) -> Path:
    return inbox / "raw" / key


def write_once(path: Path, data: bytes) -> bool:
    """Create ``path`` with ``data`` unless it exists; complete or absent, then read-only. True if written now."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
    finally:
        os.remove(temporary)
    os.chmod(path, stat.S_IREAD)
    return True


def keep_bytes(inbox: Path, key: str, body: bytes) -> str:
    """Keep one response body; returns its file name. Identical bytes share one file; a file of that name holding other
    bytes is refused (OSError), never replaced."""
    digest = hashlib.sha256(body).hexdigest()
    data_file = raw_dir(inbox, key) / f"{digest}.xml"
    if not write_once(data_file, body) and hashlib.sha256(data_file.read_bytes()).hexdigest() != digest:
        raise OSError(f"{data_file.name} exists with other bytes")
    return data_file.name


def kept_state(inbox: Path, key: str, name: str | None, sha256: str | None) -> str | None:
    """Whether a named copy is held and still holds the bytes its name and record state: "verified", "missing" or
    "differs"; None when no copy was named. Reads only."""
    if not name:
        return None
    path = raw_dir(inbox, key) / name
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "verified" if digest == sha256 and name == f"{digest}.xml" else "differs"


def records(inbox: Path, key: str) -> list[dict]:
    """The inbox-raw-0.1 retrieval records of one source, oldest first (reads only)."""
    folder = raw_dir(inbox, key)
    if not folder.is_dir():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]

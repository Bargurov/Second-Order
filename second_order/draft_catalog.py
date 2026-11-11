"""Where draft review views come from, and which action owns each source.

``prepare-drafts`` owns ``prepared-drafts/``: it writes the views it is given and replaces that folder's index with
exactly those views, as it always has. The Tracker owns ``tracker-drafts/``, beside it: each view it publishes is
one file, written under a unique temporary name, linked into place exclusively and never replaced. There is no
Tracker index file. The folder's listing is the index, so concurrent publications cannot lose an entry or collide
on a shared temporary name, and ``prepare-drafts`` never removes a Tracker draft.

Reads merge both sources and never write. A draft ID found in both is served only when the two views are
byte-identical; otherwise the drafts are reported as inconsistent rather than one being chosen.
"""
import json
import os
from pathlib import Path
import re
import uuid

from .draft_views import DRAFT_VIEW_VERSION, INDEX_NAME, index_entry
from .model_draft import DraftRefused, strict_json
from .store import canonical

TRACKER_FOLDER = "tracker-drafts"
ID = re.compile(r"[a-f0-9]{64}")
VIEW_FILE = re.compile(r"draft-([a-f0-9]{64})\.json")
NOT_PREPARED = ("Drafts for review have not been prepared. Run: python -m second_order prepare-drafts "
                "--attempt <saved attempt directory>, or analyze an event from the Tracker")


class CatalogRefused(ValueError):
    """A refused read or publication, with the HTTP status that describes it."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def tracker_dir(prepared_dir: Path) -> Path:
    """The Tracker's own folder, beside the folder prepare-drafts writes."""
    return prepared_dir.parent / TRACKER_FOLDER


def view_bytes(view: dict) -> bytes:
    """The serialization prepare-drafts also writes, so a draft has one fingerprint wherever it is stored."""
    return canonical(view).encode("utf-8")


def prepared_rows(prepared_dir: Path) -> list[dict] | None:
    index_path = prepared_dir / INDEX_NAME
    if not index_path.is_file():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))["drafts"]


def tracker_files(published_dir: Path) -> dict[str, Path]:
    """Published Tracker views by draft ID. Temporary names never match, so a write in progress is not listed."""
    if not published_dir.is_dir():
        return {}
    return {match.group(1): path for path in sorted(published_dir.iterdir())
            if (match := VIEW_FILE.fullmatch(path.name))}


def tracker_row(draft_id: str, path: Path) -> dict:
    try:
        view = strict_json(path.read_bytes())
        if not isinstance(view, dict) or view.get("id") != draft_id or view.get("view_version") != DRAFT_VIEW_VERSION:
            raise ValueError
        return index_entry(view)
    except (DraftRefused, ValueError, KeyError, TypeError):
        raise CatalogRefused(500, f"The Tracker draft {path.name} is inconsistent; it is reported, never repaired") \
            from None


def listing(prepared_dir: Path, published_dir: Path) -> dict | None:
    """Every listed draft from both sources, oldest first; None when neither source holds anything."""
    prepared, tracker = prepared_rows(prepared_dir), tracker_files(published_dir)
    if prepared is None and not tracker:
        return None
    rows = {row["id"]: row for row in prepared or []}
    for draft_id, path in tracker.items():
        if draft_id in rows:
            locate(prepared_dir, published_dir, draft_id)  # Refuses unless the two copies are byte-identical.
        else:
            rows[draft_id] = tracker_row(draft_id, path)
    return {"view_version": DRAFT_VIEW_VERSION,
            "drafts": sorted(rows.values(), key=lambda row: (row["sent_at"], row["id"]))}


def locate(prepared_dir: Path, published_dir: Path, draft_id: str) -> bytes:
    """The stored bytes of one listed draft view. An unknown ID is 404; no draft source at all is 503."""
    prepared, tracker = prepared_rows(prepared_dir), tracker_files(published_dir)
    if prepared is None and not tracker:
        raise CatalogRefused(503, NOT_PREPARED)
    if not ID.fullmatch(draft_id or ""):
        raise CatalogRefused(404, "Unknown draft ID")
    found = None
    if prepared is not None and draft_id in {row["id"] for row in prepared}:
        path = prepared_dir / f"draft-{draft_id}.json"
        if not path.is_file():
            raise CatalogRefused(503, NOT_PREPARED)
        found = path.read_bytes()
    if draft_id in tracker:
        published = tracker[draft_id].read_bytes()
        if found is not None and published != found:
            raise CatalogRefused(500, f"Draft {draft_id} is stored by prepare-drafts and by the Tracker with "
                                      "different content; it is reported, never repaired")
        found = published
    if found is None:
        raise CatalogRefused(404, "Unknown draft ID")
    return found


def publish_view(view: dict, published_dir: Path, prepared_dir: Path) -> bool:
    """Create the Tracker file for a view exactly once. Returns False when an identical file already exists.

    Nothing is ever replaced: a different view under the same ID, in either source, is refused."""
    data = view_bytes(view)
    try:
        existing = locate(prepared_dir, published_dir, view["id"])
    except CatalogRefused as exc:
        if exc.status not in (404, 503):
            raise
        existing = None
    if existing is not None and existing != data:
        raise CatalogRefused(409, "A different prepared view already uses this draft ID; nothing was published")
    published_dir.mkdir(parents=True, exist_ok=True)
    target = published_dir / f"draft-{view['id']}.json"
    temporary = published_dir / f".tmp-{uuid.uuid4().hex}"
    try:
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)  # Atomic, and fails if the name already exists.
        except FileExistsError:
            if target.read_bytes() != data:
                raise CatalogRefused(409, "A different Tracker view already uses this draft ID; nothing was "
                                          "published") from None
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)

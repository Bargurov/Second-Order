"""Persistent human review of prepared draft views: append-only local records of a person's judgment.

A review records what a person concluded about one prepared draft: notes, an optional status and, for a
draft outcome only, corrections to the summary and to each leg's rationale, falsifier and
headline_reports_move flag. The graph, observable IDs, directions, horizons and primary leg cannot be
changed here. A status ("needs_revision" or "human_reviewed") describes human judgment: it does not verify
the model's reasoning, make a draft eligible for research, freeze it or evaluate it. Notes on a decline or a
failure never become a draft.

Every save appends one immutable version under data/draft-reviews/<draft id>/ (git-ignored). The version's
file is created exclusively and never rewritten; its ID is the hash of its content. It carries a
server-stamped time, its parent version's ID, and the hashes that bind it to what was reviewed: the prepared
view file, the recorded request (prompt hash) and the recorded response. A save names the fingerprint (the
SHA-256 of the exact bytes) of the view the page loaded; if it is not the current view's, or if the parent is
not the latest version, the save is refused and nothing is written. History is read back verified, with the
current view's fingerprint, so a page can tell versions saved against an earlier view from current ones. It
is never repaired.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable
import uuid
from . import draft_catalog
from .draft_views import DRAFT_VIEW_VERSION, PILOT_ROOT, ROOT
from .model_draft import DraftRefused, strict_json
from .store import digest

RECORD_VERSION = "draft-human-review-0.1"
HISTORY_VERSION = "draft-review-history-0.2"
REVIEWS_DIR = ROOT / "data" / "draft-reviews"
STATUSES = ("needs_revision", "human_reviewed")
ATTRIBUTION = "local human reviewer"
MAX_BODY = 65_536
MAX_NOTES = 20_000
MAX_TEXT = 4_000
ID = re.compile(r"[a-f0-9]{64}")
VERSION_FILE = re.compile(r"(\d{6})\.json")
PAYLOAD_FIELDS = {"parent_review_id", "binding", "status", "notes", "corrections"}
LEG_FIELDS = {"rationale", "falsifier", "headline_reports_move"}
BINDING_FIELDS = {"draft_view_sha256", "prompt_hash", "response_sha256"}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ReviewRefused(ValueError):
    """A refused read or save, with the HTTP status that describes it."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def prepared_view(drafts_dir: Path, draft_id: str, published_dir: Path | None = None) -> tuple[bytes, dict]:
    """The prepared view a review is about, read only from the listed draft sources (see draft_catalog):
    prepare-drafts' folder and the Tracker's folder beside it."""
    try:
        data = draft_catalog.locate(drafts_dir, published_dir or draft_catalog.tracker_dir(drafts_dir), draft_id)
    except draft_catalog.CatalogRefused as exc:
        raise ReviewRefused(exc.status, str(exc)) from None
    view = json.loads(data)
    if view.get("id") != draft_id or view.get("view_version") != DRAFT_VIEW_VERSION:
        raise ReviewRefused(409, "The prepared draft view does not match its ID or version; prepare it again")
    return data, view


def fingerprint(view_bytes: bytes) -> str:
    """What identifies a prepared view: the SHA-256 of its exact bytes, as served."""
    return hashlib.sha256(view_bytes).hexdigest()


def review_id(record: dict) -> str:
    return digest({key: value for key, value in record.items() if key != "review_id"})


def history(reviews_dir: Path, draft_id: str) -> list[dict]:
    """Every saved version, oldest first, verified: contiguous numbering, content IDs and parent chain."""
    folder = reviews_dir / draft_id
    if not folder.is_dir():
        return []
    names = sorted(path.name for path in folder.iterdir() if not path.name.startswith(".tmp-"))
    records = []
    for position, name in enumerate(names, start=1):
        match = VERSION_FILE.fullmatch(name)
        if not match or int(match.group(1)) != position:
            raise ReviewRefused(500, f"The saved review history is inconsistent: unexpected file {name}")
        try:
            record = strict_json((folder / name).read_bytes())
        except DraftRefused:
            raise ReviewRefused(500, f"The saved review history is inconsistent: {name} is not strict JSON") from None
        parent = records[-1]["review_id"] if records else None
        if not isinstance(record, dict) or record.get("record_version") != RECORD_VERSION \
                or record.get("draft_id") != draft_id or record.get("sequence") != position \
                or record.get("parent_review_id") != parent or record.get("review_id") != review_id(record):
            raise ReviewRefused(500, f"The saved review history is inconsistent at version {position}")
        records.append(record)
    return records


def checked_text(value: object, field: str, limit: int, required: bool) -> str:
    if not isinstance(value, str) or len(value) > limit or CONTROL.search(value):
        raise ReviewRefused(422, f"{field} must be text of at most {limit} characters without control characters")
    if required and (not value.strip() or value != value.strip()):
        raise ReviewRefused(422, f"{field} must be non-empty and must not start or end with spaces")
    return value


def checked_corrections(value: object, view: dict) -> dict:
    """Only real changes to the editable fields of a model draft; anything else is refused, not dropped."""
    if not isinstance(value, dict) or set(value) != {"summary", "legs"} or not isinstance(value["legs"], dict):
        raise ReviewRefused(422, "corrections must hold exactly summary and legs")
    draft = view["draft"]
    if draft is None:
        if value["summary"] is not None or value["legs"]:
            raise ReviewRefused(422, "Corrections apply only to a model draft; this attempt has none, so only notes "
                                     "and a status can be saved")
        return {"summary": None, "legs": {}}
    summary = value["summary"]
    if summary is not None:
        checked_text(summary, "The corrected summary", MAX_TEXT, required=True)
        if summary == draft["summary"]:
            raise ReviewRefused(422, "The corrected summary is unchanged from the model's proposal")
    originals = {leg["id"]: leg for leg in draft["legs"]}
    legs = {}
    for leg_id, fields in value["legs"].items():
        if leg_id not in originals:
            raise ReviewRefused(422, f"The draft has no leg {leg_id!r}")
        if not isinstance(fields, dict) or not fields or not set(fields) <= LEG_FIELDS:
            raise ReviewRefused(422, f"Leg {leg_id!r} corrections may change only its rationale, falsifier and "
                                     "headline_reports_move flag")
        for field, corrected in fields.items():
            if field == "headline_reports_move":
                if not isinstance(corrected, bool):
                    raise ReviewRefused(422, f"Leg {leg_id!r} headline_reports_move must be true or false")
            else:
                checked_text(corrected, f"Leg {leg_id!r} {field}", MAX_TEXT, required=True)
            if corrected == originals[leg_id][field]:
                raise ReviewRefused(422, f"Leg {leg_id!r} {field} is unchanged from the model's proposal")
        legs[leg_id] = dict(fields)
    return {"summary": summary, "legs": legs}


def checked_payload(body: bytes, view: dict) -> dict:
    try:
        payload = strict_json(body)
    except DraftRefused:
        raise ReviewRefused(422, "The review must be strict JSON") from None
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        raise ReviewRefused(422, f"A review holds exactly {', '.join(sorted(PAYLOAD_FIELDS))}")
    parent = payload["parent_review_id"]
    if parent is not None and not (isinstance(parent, str) and ID.fullmatch(parent)):
        raise ReviewRefused(422, "parent_review_id must be a review ID or null")
    binding = payload["binding"]
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
        raise ReviewRefused(422, f"binding must hold exactly {', '.join(sorted(BINDING_FIELDS))}")
    if not (isinstance(binding["draft_view_sha256"], str) and ID.fullmatch(binding["draft_view_sha256"])):
        raise ReviewRefused(422, "binding.draft_view_sha256 must be the fingerprint of the loaded view")
    if payload["status"] is not None and payload["status"] not in STATUSES:
        raise ReviewRefused(422, f"status must be null or one of {', '.join(STATUSES)}")
    notes = checked_text(payload["notes"], "notes", MAX_NOTES, required=False)
    corrections = checked_corrections(payload["corrections"], view)
    if not notes.strip() and payload["status"] is None and corrections["summary"] is None and not corrections["legs"]:
        raise ReviewRefused(422, "A review needs notes, a status or a correction")
    return {"parent_review_id": parent, "binding": binding, "status": payload["status"], "notes": notes,
            "corrections": corrections}


def write_exclusively(folder: Path, name: str, data: bytes) -> None:
    """Write a complete file under a name that must not exist yet; a racing writer loses, nothing is replaced."""
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".tmp-{uuid.uuid4().hex}"
    try:
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, folder / name)  # Atomic, and fails if the name already exists.
    except FileExistsError:
        raise ReviewRefused(409, "Another review version was saved at the same time; reload to see it") from None
    finally:
        temporary.unlink(missing_ok=True)


def save_review(drafts_dir: Path, reviews_dir: Path, draft_id: str, body: bytes,
                clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                published_dir: Path | None = None) -> dict:
    """Append one verified version. Pilot records and prepared views are only read."""
    target = reviews_dir.resolve()
    published_dir = published_dir or draft_catalog.tracker_dir(drafts_dir)
    for protected in (drafts_dir, published_dir, PILOT_ROOT):
        if target == protected.resolve() or protected.resolve() in target.parents:
            raise ReviewRefused(500, "The review directory is inside prepared or pilot records; nothing was saved")
    if len(body) > MAX_BODY:
        raise ReviewRefused(413, f"A review is limited to {MAX_BODY} bytes")
    view_bytes, view = prepared_view(drafts_dir, draft_id, published_dir)
    payload = checked_payload(body, view)
    provenance, current = view["provenance"], fingerprint(view_bytes)
    if payload["binding"] != {"draft_view_sha256": current, "prompt_hash": provenance["prompt_hash"],
                              "response_sha256": provenance["response_sha256"]}:
        raise ReviewRefused(409, "The prepared draft has changed since it was loaded; reload it before saving")
    records = history(reviews_dir, draft_id)
    latest = records[-1] if records else None
    if payload["parent_review_id"] != (latest["review_id"] if latest else None):
        raise ReviewRefused(409, "Another review version was saved since this draft was loaded; reload to see it")
    content = {key: payload[key] for key in ("status", "notes", "corrections")}
    same_view = latest is not None and latest["binding"]["draft_view_sha256"] == current
    if same_view and content == {key: latest[key] for key in content}:
        raise ReviewRefused(422, "Nothing changed since the last saved version")
    record = {
        "record_version": RECORD_VERSION, "draft_id": draft_id, "sequence": len(records) + 1,
        "parent_review_id": payload["parent_review_id"], "saved_at": clock().astimezone(timezone.utc).isoformat(),
        "attributed_to": ATTRIBUTION, **content,
        "binding": {"draft_view_sha256": current, "draft_view_version": view["view_version"],
                    "outcome": view["outcome"],
                    **{key: provenance[key] for key in ("prompt_hash", "response_sha256", "request_id", "pilot",
                                                        "case")}},
    }
    record["review_id"] = review_id(record)
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    write_exclusively(reviews_dir / draft_id, f"{record['sequence']:06d}.json", data)
    return record


def history_view(drafts_dir: Path, reviews_dir: Path, draft_id: str, published_dir: Path | None = None) -> dict:
    """Saved versions with the current view's fingerprint. A version bound to another fingerprint was saved
    against an earlier prepared view: its corrections and judgment are not about the view served now."""
    view_bytes, _ = prepared_view(drafts_dir, draft_id, published_dir)  # Only listed drafts have a history.
    return {"view_version": HISTORY_VERSION, "draft_id": draft_id, "draft_view_sha256": fingerprint(view_bytes),
            "reviews": history(reviews_dir, draft_id)}

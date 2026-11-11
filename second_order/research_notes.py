"""The owner's research notes (research-note-0.1): append-only personal records on the copper research.

A note is the owner's own view: not a source's wording, not the assistant's draft, and never part of a research score.
By the owner's decision of 2026-11-10 it may hold an expectation, a price's direction included. It is about one
subject (a publication comparison, an event chain or the thesis) and binds what that subject rested on when it was
saved: the subject's version, its evidence and each retained document's pinned acquisition record.

Fields: the note; optionally an expectation (text and an optional check-by date, never before the saving day);
optionally a question for the next check; optionally the earlier note about the same subject that it follows. A
change of mind is a new note; nothing is edited or deleted. The saving time is this server's clock, never a date from
the request, so an expectation cannot be dated back.

One numbered file per note under the notes folder, created exclusively and never rewritten. A note's id is the digest
of the record without the id, and each note names the note before it. The history is verified on every read and every
save (numbering, ids, the parent chain, each record's shape, and that a followed note is an earlier one about the same
subject); an inconsistent history refuses saves and nothing is repaired. Text rules (event_chain_text.owner_text):
length, no control character but a line break, the digits 0 to 9 and no six consecutive words of a source. No word
list applies. Nothing here fetches or calls a model.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import TypedDict

from .analysis_flow import FlowRefused, strict_object
from .event_chain_records import RecordRefused
from .event_chain_schema import REF, SHA256, acquisition_shaped
from .event_chain_text import TextRefused, owner_text
from .human_review import ReviewRefused, write_exclusively
from .model_draft import DraftRefused, strict_json
from .store import digest

NOTE_VERSION = "research-note-0.1"
KINDS = ("comparison", "chain", "thesis")
REQUEST_FIELDS = ("parent_note_id", "about", "subject_sha256", "follows", "text", "expectation", "question")
RECORD_FIELDS = {"record_version", "note_id", "parent_note_id", "sequence", "about", "follows", "text", "expectation",
                 "question", "basis", "account", "saved_at"}
BASIS_FIELDS = {"comparison": ("comparison", "evidence_sha256", "documents"),
                "chain": ("chain", "evidence_sha256", "thesis", "documents"),
                "thesis": ("thesis", "documents")}
MAX_TEXT, MAX_EXPECTATION, MAX_QUESTION = 2000, 500, 280
VERSION_FILE = re.compile(r"(\d{6})\.json")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
INCONSISTENT = "The saved notes are inconsistent: {why}"
UNVERIFIABLE = "The saved notes cannot be verified: note {position} {why}"


class Subject(TypedDict):
    """What a note on a subject is checked against and binds, as computed now."""
    kind: str
    id: str
    sha256: str
    basis: dict
    state: str
    reasons: list[str]
    quotes: list[str]


def note_id(record: dict) -> str:
    return digest({key: value for key, value in record.items() if key != "note_id"})


def _fields(value: object, keys) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _versioned(value: object) -> bool:
    return (_fields(value, ("id", "version", "sha256")) and isinstance(value["id"], str) and value["id"] != ""
            and type(value["version"]) is int and value["version"] >= 1 and _sha(value["sha256"]))


def _day(value: object) -> bool:
    if not (isinstance(value, str) and DAY.fullmatch(value)):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _words(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _moment(value: object) -> bool:
    """Whether value is a saving time as this code writes one: an ISO date and time with its offset."""
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def shaped(record: dict) -> bool:
    """Whether a saved note holds exactly the fields this code writes, each of the type and form the view and the
    page's reader expect (a text that is not empty, a saving time with its offset), so that a file edited by hand makes
    the history unverifiable instead of a reply the page refuses whole. Never raises on any JSON value."""
    if not _fields(record, RECORD_FIELDS) or type(record["sequence"]) is not int:
        return False
    about, basis, account = record["about"], record["basis"], record["account"]
    if not (_fields(about, ("kind", "id")) and about["kind"] in KINDS and isinstance(about["id"], str)
            and ID.fullmatch(about["id"]) and _fields(basis, BASIS_FIELDS[about["kind"]])
            and _fields(account, ("user_id", "username"))):
        return False
    named = basis[about["kind"]]
    if not (_versioned(named) and named["id"] == about["id"] and isinstance(basis["documents"], list)
            and basis["documents"] and all(isinstance(account[key], str) and account[key] for key in account)
            and _moment(record["saved_at"]) and _words(record["text"])
            and (record["follows"] is None or _sha(record["follows"]))
            and (record["question"] is None or _words(record["question"]))):
        return False
    if "evidence_sha256" in basis and not _sha(basis["evidence_sha256"]):
        return False
    if about["kind"] == "chain" and not _versioned(basis["thesis"]):
        return False
    for document in basis["documents"]:
        if not (_fields(document, ("ref", "acquisition")) and isinstance(document["ref"], str)
                and REF.fullmatch(document["ref"])
                and acquisition_shaped(document["acquisition"], document["ref"].split(":")[0])):
            return False
    expectation = record["expectation"]
    return expectation is None or (_fields(expectation, ("text", "check_by")) and _words(expectation["text"])
                                   and (expectation["check_by"] is None or _day(expectation["check_by"])))


def history(notes: Path) -> list[dict]:
    """Every saved note, oldest first, verified (see the module docstring). Any failure refuses with 500 and nothing is
    repaired; an absent folder holds no note."""
    notes = Path(notes)
    if not notes.is_dir():
        return []
    names = sorted(path.name for path in notes.iterdir() if not path.name.startswith(".tmp-"))
    found: list[dict] = []
    for position, name in enumerate(names, start=1):
        match = VERSION_FILE.fullmatch(name)
        if not match or int(match.group(1)) != position:
            # The name is not echoed: it is whatever was put in the folder, and the page shows this sentence.
            raise RecordRefused(500, INCONSISTENT.format(why=f"an unexpected file stands where note {position} would"))
        try:
            record = strict_json((notes / name).read_bytes())
        except DraftRefused:
            raise RecordRefused(500, INCONSISTENT.format(why=f"{name} is not strict JSON")) from None
        parent = found[-1]["note_id"] if found else None
        if not isinstance(record, dict) or record.get("record_version") != NOTE_VERSION \
                or record.get("sequence") != position or record.get("parent_note_id") != parent \
                or record.get("note_id") != note_id(record):
            raise RecordRefused(500, INCONSISTENT.format(why=f"note {position} does not follow the one before it"))
        if not shaped(record):
            raise RecordRefused(500, UNVERIFIABLE.format(position=position, why="is not the shape this version reads"))
        followed = next((item for item in found if item["note_id"] == record["follows"]), None)
        if record["follows"] is not None and (followed is None or followed["about"] != record["about"]):
            raise RecordRefused(500, UNVERIFIABLE.format(
                position=position, why="follows a note that is not an earlier one about the same subject"))
        found.append(record)
    return found


def parse(body: bytes) -> dict:
    """The request as one strict JSON object with exactly the documented fields and a well-formed subject. Raises
    RecordRefused (413 or 422)."""
    try:
        payload = strict_object(body, REQUEST_FIELDS, "note")
    except FlowRefused as error:
        raise RecordRefused(error.status, str(error)) from None
    about = payload["about"]
    if not (_fields(about, ("kind", "id")) and about["kind"] in KINDS and isinstance(about["id"], str)
            and ID.fullmatch(about["id"])):
        raise RecordRefused(422, f"about must name a subject: a kind ({', '.join(KINDS)}) and its id")
    return payload


def _text(value: object, quotes: list[str], limit: int, name: str) -> str:
    try:
        return owner_text(value, quotes=quotes, limit=limit, name=name)
    except TextRefused as error:
        raise RecordRefused(error.status, error.message) from None


def _expectation(value: object, quotes: list[str], today: str) -> dict | None:
    if value is None:
        return None
    if not _fields(value, ("text", "check_by")):
        raise RecordRefused(422, "the expectation must be null, or a text and a check-by date (or null)")
    check_by = value["check_by"]
    if check_by is not None and (not _day(check_by) or check_by < today):
        raise RecordRefused(422, f"the check-by date must be a date, YYYY-MM-DD, not before today ({today})")
    return {"text": _text(value["text"], quotes, MAX_EXPECTATION, "the expectation"), "check_by": check_by}


def save(notes: Path, subject: Subject, payload: dict, account: dict, clock) -> dict:
    """Append one note about ``subject`` (the subject payload["about"] names, as computed now). Raises RecordRefused:
    409 with the latest note's id for a stale parent, a subject that changed or is not available now; 422 for a text,
    date or followed note that breaks a rule; 500 for an inconsistent history. Writes one file, or nothing."""
    notes = Path(notes)
    past = history(notes)
    latest = past[-1]["note_id"] if past else None
    kind = subject["kind"]
    if payload["parent_note_id"] != latest:
        raise RecordRefused(409, "The parent is not the latest note; reload to see it", latest)
    if payload["subject_sha256"] != subject["sha256"]:
        raise RecordRefused(409, f"The {kind} changed since this page was loaded; reload to see its latest version",
                            latest)
    if subject["state"] != "available":
        raise RecordRefused(409, f"The {kind} is not available: " + "; ".join(subject["reasons"]), latest)
    now = clock().astimezone(timezone.utc)
    quotes = subject["quotes"]
    text = _text(payload["text"], quotes, MAX_TEXT, "the note")
    expectation = _expectation(payload["expectation"], quotes, now.date().isoformat())
    question = None if payload["question"] is None else _text(payload["question"], quotes, MAX_QUESTION,
                                                              "the question")
    follows = payload["follows"]
    about = {"kind": kind, "id": subject["id"]}
    if follows is not None and not any(item["note_id"] == follows and item["about"] == about for item in past):
        raise RecordRefused(422, "follows must name an earlier note about the same subject")
    record = {"record_version": NOTE_VERSION, "sequence": len(past) + 1, "parent_note_id": latest, "about": about,
              "follows": follows, "text": text, "expectation": expectation, "question": question,
              "basis": subject["basis"],
              "account": {"user_id": account["user_id"], "username": account["username"]},
              "saved_at": now.isoformat()}
    record["note_id"] = note_id(record)
    data = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    try:
        write_exclusively(notes, f"{record['sequence']:06d}.json", data)
    except ReviewRefused as error:
        if error.status != 409:
            raise RecordRefused(error.status, str(error)) from None
        try:
            newest = history(notes)[-1]["note_id"]
        except (RecordRefused, IndexError):
            newest = None
        raise RecordRefused(409, "Another note was saved at the same time; reload to see it", newest) from None
    return record

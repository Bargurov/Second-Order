"""Append-only owner records for event chains: reviews and readings, each bound to a chain version's basis.

A record is one new file, written exclusively and never rewritten. Its id is the digest of the record without the id.
The history is verified on every read and every save (numbering, ids, the parent chain and each record's shape, the one
check the view relies on too); an inconsistent history refuses saves and nothing is repaired."""
import json
import re
from datetime import timezone
from pathlib import Path
from typing import Callable, Literal, TypedDict

from .analysis_flow import FlowRefused, strict_object
from .event_chain_schema import REF, SHA256, THESIS, acquisition_shaped
from .event_chain_text import TextRefused, owner_line, owner_notes
from .human_review import ReviewRefused, write_exclusively
from .model_draft import DraftRefused, strict_json
from .store import digest

REVIEW_VERSION = "event-chain-review-0.1"
READING_VERSION = "event-chain-reading-0.1"
STATUSES = ("approved", "needs_revision")
JUDGMENTS = ("supports", "refutes", "neither", "not_sure")
REVIEW_FIELDS = ("parent_review_id", "chain_sha256", "status", "notes")
READING_FIELDS = ("parent_reading_id", "chain_sha256", "approval_id", "short_term", "long_term", "line")
VERSION_FILE = re.compile(r"(\d{6})\.json")
KINDS = {
    "reviews": {"version": REVIEW_VERSION, "id": "review_id", "parent": "parent_review_id"},
    "readings": {"version": READING_VERSION, "id": "reading_id", "parent": "parent_reading_id"},
}
COMMON_FIELDS = {"record_version", "chain_id", "sequence", "basis", "account", "saved_at"}
RECORD_FIELDS = {
    "reviews": COMMON_FIELDS | {"review_id", "parent_review_id", "status", "notes"},
    "readings": COMMON_FIELDS | {"reading_id", "parent_reading_id", "approval_id", "target", "short_term", "long_term",
                                 "line"},
}
UNVERIFIABLE = "The saved {kind} history cannot be verified: record {position} {why}"
NOT_SHAPED = "is not the shape this version reads"
NO_VERSION = "names chain version {version}, which is not in the chain's history"


class RecordRefused(ValueError):
    def __init__(self, status: int, message: str, latest: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.latest = latest


class Current(TypedDict):
    id: str
    version: int
    sha256: str
    basis: dict
    target: dict
    state: str
    reasons: list[str]
    approval_id: str | None
    steps: int
    quotes: list[str]
    allowed: str


def record_id(kind: str, record: dict) -> str:
    return digest({key: value for key, value in record.items() if key != KINDS[kind]["id"]})


def _fields(value: object, keys) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _count(value: object) -> bool:
    return type(value) is int and value >= 1


def _name(value: object) -> bool:
    return isinstance(value, str) and value != ""


def shaped(record: dict, kind: str, chain_id: str) -> bool:
    """Whether a saved record holds exactly the fields this code writes for its kind, each of the type the view reads:
    the basis (this chain's version, the evidence digest, the copper thesis version, and at least one document with a
    copper: or fcx: reference and its pinned acquisition record, field by field), the account, the time, the owner's
    text and the status, or a reading's approval id, target and two judgments. Never raises on any JSON value."""
    if not _fields(record, RECORD_FIELDS[kind]) or type(record["sequence"]) is not int:
        return False
    basis, account = record["basis"], record["account"]
    if not (_fields(basis, ("chain", "evidence_sha256", "thesis", "documents"))
            and _fields(basis["chain"], ("id", "version", "sha256"))
            and _fields(basis["thesis"], ("id", "version", "sha256")) and _fields(account, ("user_id", "username"))):
        return False
    chain, thesis, documents = basis["chain"], basis["thesis"], basis["documents"]
    if not (chain["id"] == chain_id and _count(chain["version"]) and _sha(chain["sha256"])
            and _sha(basis["evidence_sha256"]) and thesis["id"] == THESIS and _count(thesis["version"])
            and _sha(thesis["sha256"]) and _name(account["user_id"]) and _name(account["username"])
            and isinstance(record["saved_at"], str) and isinstance(documents, list) and documents):
        return False
    for document in documents:
        if not (_fields(document, ("ref", "acquisition")) and isinstance(document["ref"], str)
                and REF.fullmatch(document["ref"])
                and acquisition_shaped(document["acquisition"], document["ref"].split(":")[0])):
            return False
    if kind == "reviews":
        return record["status"] in STATUSES and isinstance(record["notes"], str)
    target = record["target"]
    return (_sha(record["approval_id"]) and record["short_term"] in JUDGMENTS and record["long_term"] in JUDGMENTS
            and isinstance(record["line"], str) and _fields(target, ("kind", "id")) and _name(target["kind"])
            and _name(target["id"]))


def history(records: Path, kind: Literal["reviews", "readings"], chain_id: str, versions: int | None = None) \
        -> list[dict]:
    """Every saved record of one kind, oldest first, verified: numbering, content ids, the parent chain and each
    record's shape (shaped). With ``versions``, the number of published versions of the chain, each record must also
    name one of them. Any failure refuses with 500 and nothing is repaired."""
    spec = KINDS[kind]
    folder = records / kind / chain_id
    if not folder.is_dir():
        return []
    names = sorted(path.name for path in folder.iterdir() if not path.name.startswith(".tmp-"))
    found: list[dict] = []
    for position, name in enumerate(names, start=1):
        match = VERSION_FILE.fullmatch(name)
        if not match or int(match.group(1)) != position:
            raise RecordRefused(500, f"The saved {kind} history is inconsistent: unexpected file {name}")
        try:
            record = strict_json((folder / name).read_bytes())
        except DraftRefused:
            raise RecordRefused(500, f"The saved {kind} history is inconsistent: {name} is not strict JSON") from None
        parent = found[-1][spec["id"]] if found else None
        if not isinstance(record, dict) or record.get("record_version") != spec["version"] \
                or record.get("chain_id") != chain_id or record.get("sequence") != position \
                or record.get(spec["parent"]) != parent or record.get(spec["id"]) != record_id(kind, record):
            raise RecordRefused(500, f"The saved {kind} history is inconsistent at record {position}")
        if not shaped(record, kind, chain_id):
            raise RecordRefused(500, UNVERIFIABLE.format(kind=kind, position=position, why=NOT_SHAPED))
        version = record["basis"]["chain"]["version"]
        if versions is not None and version > versions:
            raise RecordRefused(500, UNVERIFIABLE.format(kind=kind, position=position,
                                                         why=NO_VERSION.format(version=version)))
        found.append(record)
    return found


def _body(body: bytes, fields: tuple[str, ...], label: str) -> dict:
    try:
        return strict_object(body, fields, label)
    except FlowRefused as error:
        raise RecordRefused(error.status, str(error)) from None


def _latest(past: list[dict], kind: str) -> str | None:
    return past[-1][KINDS[kind]["id"]] if past else None


def _checked(records: Path, kind: str, current: Current, payload: dict) -> list[dict]:
    """Steps 2 to 5, shared by both kinds: a valid history, the parent, the chain version, availability."""
    past = history(records, kind, current["id"], current["version"])
    latest = _latest(past, kind)
    if payload[KINDS[kind]["parent"]] != latest:
        raise RecordRefused(409, f"The parent is not the latest {kind[:-1]}; reload to see it", latest)
    if payload["chain_sha256"] != current["sha256"]:
        raise RecordRefused(409, "The chain changed since this page was loaded; reload to see its latest version",
                            latest)
    if current["state"] != "available":
        raise RecordRefused(409, "The chain is not available: " + "; ".join(current["reasons"]), latest)
    return past


def _text(check: Callable[[], str]) -> str:
    try:
        return check()
    except TextRefused as error:
        raise RecordRefused(error.status, error.message) from None


def _judgment(value: object, name: str) -> str:
    if value not in JUDGMENTS:
        raise RecordRefused(422, f"{name} must be one of {', '.join(JUDGMENTS)}")
    return value


def _store(records: Path, kind: str, current: Current, record: dict) -> dict:
    spec = KINDS[kind]
    record[spec["id"]] = record_id(kind, record)
    data = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    try:
        write_exclusively(records / kind / current["id"], f"{record['sequence']:06d}.json", data)
    except ReviewRefused as error:
        if error.status != 409:
            raise RecordRefused(error.status, str(error)) from None
        try:
            latest = _latest(history(records, kind, current["id"]), kind)
        except RecordRefused:
            latest = None
        raise RecordRefused(409, "Another record was saved at the same time; reload to see it", latest) from None
    return record


def _common(kind: str, current: Current, past: list[dict], account: dict, clock) -> dict:
    return {
        "record_version": KINDS[kind]["version"], "chain_id": current["id"], "sequence": len(past) + 1,
        KINDS[kind]["parent"]: _latest(past, kind),
        "basis": current["basis"],
        "account": {"user_id": account["user_id"], "username": account["username"]},
        "saved_at": clock().astimezone(timezone.utc).isoformat(),
    }


def save_review(records: Path, current: Current, body: bytes, account: dict, clock) -> dict:
    payload = _body(body, REVIEW_FIELDS, "review")
    past = _checked(records, "reviews", current, payload)
    if payload["status"] not in STATUSES:
        raise RecordRefused(422, f"status must be one of {', '.join(STATUSES)}")
    notes = _text(lambda: owner_notes(payload["notes"], quotes=current["quotes"], steps=current["steps"]))
    if past and past[-1]["status"] == payload["status"] and past[-1]["notes"] == notes \
            and past[-1]["basis"]["chain"]["sha256"] == current["sha256"]:
        raise RecordRefused(422, "This review is identical to the latest one")
    record = _common("reviews", current, past, account, clock)
    record.update(status=payload["status"], notes=notes)
    return _store(records, "reviews", current, record)


def save_reading(records: Path, current: Current, body: bytes, account: dict, clock) -> dict:
    payload = _body(body, READING_FIELDS, "reading")
    past = _checked(records, "readings", current, payload)
    approval = payload["approval_id"]
    if current["approval_id"] is None or approval != current["approval_id"]:
        raise RecordRefused(409, "The chain has no current approval, or it is not this one; reload to see it",
                            _latest(past, "readings"))
    short_term = _judgment(payload["short_term"], "short_term")
    long_term = _judgment(payload["long_term"], "long_term")
    line = _text(lambda: owner_line(payload["line"], quotes=current["quotes"], allowed=current["allowed"],
                                    steps=current["steps"]))
    if past:
        last = past[-1]
        if (last["short_term"], last["long_term"], last["line"], last["approval_id"]) \
                == (short_term, long_term, line, approval) \
                and last["basis"]["chain"]["sha256"] == current["sha256"]:
            raise RecordRefused(422, "This reading is identical to the latest one")
    record = _common("readings", current, past, account, clock)
    record.update(approval_id=approval, target=current["target"], short_term=short_term, long_term=long_term,
                  line=line)
    return _store(records, "readings", current, record)

"""Write-once records of copper coverage scenarios (copper-scenario-0.1): what was assumed, on which published figures,
and what the engine computed, kept so that a scenario can be reproduced and checked later. A record holds a short label
and no free-text commentary: it is a tool's output, never a view, and a future authored thesis version may cite its id.

A record is {"record_version", "engine_version", "definitions_sha256", "catalog": {"version", "sha256"}, "label",
"baseline": {"scenario", "year"}, "assumptions", "figures": [{"id", "value", "source", "source_sha256"}], "result"}:
every figure any output or perturbation uses, with the value and the source SHA-256 it had, and the engine's whole
result (copper_coverage.assess) without the assumptions it repeats. Its id is the SHA-256 of the record's canonical JSON
(bis_snapshot.canonical); the file is data/scenarios/copper/<id>.json, {"id", "created_at", "record"}, written once
with exclusive creation. Saving a record that exists writes nothing (200); a new one is 201; an existing file that does
not match its id is refused (409) and is never overwritten. A record whose result has a withheld output is not saved.

Reading checks every record again. Its id must be the SHA-256 of its record. Each of its figures must still be verified
in the catalogue with the same value and the same source SHA-256, and the engine run again on today's verified values
must reproduce its result exactly: then it is verified. A figure whose source is missing makes it unavailable; any other
difference makes it need revalidation, with the reasons named. Records of another record or engine version are kept and
counted, not shown. Nothing here fetches or calls a model; only save writes.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from . import bis_snapshot, copper_coverage as cc, copper_inputs
from .thesis_rules import BANNED, PRICE_DIRECTION, ThesisRefused

RECORD_VERSION = "copper-scenario-0.1"
ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT / "data" / "scenarios" / "copper"
MAX_LABEL = 80
MAX_RECORD_BYTES = 1_000_000
RECORD_FIELDS = {"record_version", "engine_version", "definitions_sha256", "catalog", "label", "baseline",
                 "assumptions", "figures", "result"}
ENVELOPE_FIELDS = {"id", "created_at", "record"}
SHA = re.compile(r"[0-9a-f]{64}")
STATES = {"verified": "Verified: its figures still match the retained sources and the engine reproduces its result",
          "needs_revalidation": "Needs revalidation: a figure it used changed, is no longer verified, or the engine "
                                "no longer reproduces its result",
          "unavailable": "Unavailable: a source it used is not on this machine",
          "invalid": "Invalid: the file does not match its id or cannot be read; it is kept and never used"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def definitions_sha256() -> str:
    return bis_snapshot.sha256(bis_snapshot.canonical(cc.DEFINITIONS))


def record_id(record: dict) -> str:
    return bis_snapshot.sha256(bis_snapshot.canonical(record))


def check_label(value: object) -> str:
    """A short label: one line of 1 to 80 characters with no claim word and no view on a price's direction."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > MAX_LABEL or \
            any(ord(char) < 32 for char in value):
        raise ThesisRefused(422, f"A label is one line of 1 to {MAX_LABEL} characters")
    for pattern, why in ((BANNED, "a claim word this project does not use"),
                         (PRICE_DIRECTION, "a view on a price's direction")):
        found = pattern.search(value)
        if found:
            raise ThesisRefused(422, f"The label uses {found.group(0)!r}, {why}")
    return value


def _uses(node) -> list[str]:
    """Every figure id an engine result names, in first-seen order."""
    found: dict[str, None] = {}

    def walk(item):
        if isinstance(item, dict):
            for figure in item.get("uses", []) if "equation" in item else []:
                found.setdefault(figure, None)
            if isinstance(item.get("figure"), str):
                found.setdefault(item["figure"], None)
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)
    walk(node)
    return list(found)


def _withheld(node) -> bool:
    if isinstance(node, dict):
        if node.get("withheld"):
            return True
        return any(_withheld(value) for value in node.values())
    if isinstance(node, list):
        return any(_withheld(value) for value in node)
    return False


def build(catalog: dict, catalog_sha: str, values: dict, scenario: object, year: object, assumptions: object,
          label: object) -> dict:
    """The record for a scenario, built in memory (a preview writes nothing). Raises ThesisRefused (422) for an
    invalid request."""
    label = check_label(label)
    result = cc.assess(values, scenario, year, assumptions)
    entries = {item["id"]: item for item in catalog["figures"]}
    sources = copper_inputs.source_of(catalog)
    figures = []
    for figure in sorted(_uses(result)):
        entry = entries[figure]
        figures.append({"id": figure, "value": entry["value"] if figure in values else None, "source": entry["source"],
                        "source_sha256": sources[entry["source"]]["sha256"]})
    return {"record_version": RECORD_VERSION, "engine_version": cc.ENGINE_VERSION,
            "definitions_sha256": definitions_sha256(),
            "catalog": {"version": catalog["catalog_version"], "sha256": catalog_sha}, "label": label,
            "baseline": {"scenario": scenario, "year": year}, "assumptions": result["assumptions"],
            "figures": figures, "result": {key: value for key, value in result.items() if key != "assumptions"}}


def complete(record: dict) -> bool:
    return not _withheld(record["result"]) and all(figure["value"] is not None for figure in record["figures"])


def _envelope_bytes(envelope: dict) -> bytes:
    return (json.dumps(envelope, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _read(path: Path) -> dict | None:
    """The envelope of a record file, or None when it cannot be read as one strict JSON object of the right shape."""
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return None
        envelope = bis_snapshot._strict_json(path.read_bytes().decode("utf-8"), "A copper scenario record")
    except (OSError, UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        return None
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_FIELDS or not isinstance(envelope["record"], dict):
        return None
    return envelope


def save(folder: Path, record: dict, clock=now) -> tuple[int, dict]:
    """(201, the new envelope) or (200, the existing one): written once with exclusive creation, never overwritten.
    Raises ThesisRefused: 409 for a record with a withheld output or an existing file that does not match its id."""
    if not complete(record):
        raise ThesisRefused(409, "This scenario has an output withheld because a figure it needs is not verified; "
                                 "it is not saved")
    identity = record_id(record)
    folder = Path(folder)
    path = folder / f"{identity}.json"
    if path.exists():
        existing = _read(path)
        if existing is None or existing["id"] != identity or record_id(existing["record"]) != identity:
            raise ThesisRefused(409, "A file with this record's id exists and does not match it; nothing was written")
        return 200, existing
    envelope = {"id": identity, "created_at": clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
                "record": record}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        return save(folder, record, clock)  # Written meanwhile: read it as an existing record.
    with os.fdopen(handle, "wb") as out:
        out.write(_envelope_bytes(envelope))
    return 201, envelope


def check(envelope: dict, catalog: dict, values: dict, states: dict, source_states: dict) -> dict:
    """One record's state on today's verified sources (see the module docstring)."""
    record = envelope["record"]
    reasons, unavailable = [], False
    entries = {item["id"]: item for item in catalog["figures"]}
    sources = copper_inputs.source_of(catalog)
    for figure in record.get("figures", []):
        entry, state = entries.get(figure.get("id")), states.get(figure.get("id"), {}).get("state")
        if entry is None:
            reasons.append(f"{figure.get('id')} is no longer in the inputs catalogue")
        elif state == "source_missing":
            unavailable = True
            reasons.append(f"The source of {figure['id']} is not on this machine")
        elif state != "verified":
            reasons.append(f"{figure['id']} is not verified today")
        elif entry["value"] != figure.get("value") or sources[entry["source"]]["sha256"] != figure.get("source_sha256"):
            reasons.append(f"{figure['id']} differs from the value or source it was saved with")
    if record.get("definitions_sha256") != definitions_sha256():
        reasons.append("The engine's definitions differ from those it was saved with")
    if not reasons:
        try:
            again = build(catalog, record["catalog"]["sha256"], values, record["baseline"]["scenario"],
                          record["baseline"]["year"], record["assumptions"], record["label"])
        except (ThesisRefused, KeyError, TypeError):
            again = None
        if again is None or bis_snapshot.canonical(again["result"]) != bis_snapshot.canonical(record["result"]):
            reasons.append("The engine does not reproduce its result from today's verified figures")
    state = "unavailable" if unavailable else "needs_revalidation" if reasons else "verified"
    return {"id": envelope["id"], "created_at": envelope["created_at"], "label": record.get("label"),
            "baseline": record.get("baseline"), "assumptions": record.get("assumptions"), "state": state,
            "problems": reasons, "result": record.get("result") if state == "verified" else None,
            "catalog_current": record.get("catalog", {}).get("sha256") is not None}


def read_all(folder: Path, catalog: dict, catalog_sha: str, values: dict, states: dict, source_states: dict) -> dict:
    """Every record in ``folder``, newest first, each checked; records of another version counted, not shown."""
    records, other_versions = [], 0
    folder = Path(folder)
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in paths:
        envelope = _read(path)
        stem = path.stem
        if envelope is None or not SHA.fullmatch(stem) or envelope["id"] != stem or \
                record_id(envelope["record"]) != stem:
            records.append({"id": stem, "created_at": None, "label": None, "baseline": None, "assumptions": None,
                            "state": "invalid", "problems": ["The file does not match its id or cannot be read"],
                            "result": None, "catalog_current": False})
            continue
        record = envelope["record"]
        if record.get("record_version") != RECORD_VERSION or record.get("engine_version") != cc.ENGINE_VERSION:
            other_versions += 1
            continue
        if set(record) != RECORD_FIELDS:
            records.append({"id": stem, "created_at": envelope["created_at"], "label": None, "baseline": None,
                            "assumptions": None, "state": "invalid", "problems": ["The record's fields are not the "
                                                                                 "fields of this version"],
                            "result": None, "catalog_current": False})
            continue
        item = check(envelope, catalog, values, states, source_states)
        item["catalog_current"] = record["catalog"]["sha256"] == catalog_sha
        records.append(item)
    records.sort(key=lambda item: (item["created_at"] or "", item["id"]), reverse=True)
    return {"record_version": RECORD_VERSION, "records": records, "other_versions": other_versions,
            "labels": STATES}

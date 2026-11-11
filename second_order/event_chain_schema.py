"""Copper event chains (event-chain-0.1): strict loading of the mechanism list and of chain versions.

Content only. The mechanism list is content/metals/mechanisms/ (index.json plus v<n>.json, event-mechanisms-0.1); a
chain is content/theses/copper/event-chains/<chain id>/ (index.json plus v<n>.json, event-chain-0.1). Each index lists
versions 1..n as {version, file, sha256, published_on}; the SHA-256 is over the loaded file's canonical JSON, so a CRLF
checkout still matches. A version never changes once published.

A chain version pins what it rests on (evidence): the register event, each cited passage's wording and location, each
retained document's acquisition record, the thesis version and the mechanism list version. Here only the shape of that
pin is checked, and the chain's own text rules. Comparing the pin with live records is done elsewhere. Reads only; any
invalid file refuses with ChainRefused(500, "<place>: <rule>").
"""
from datetime import datetime
from pathlib import Path
import re

from . import bis_snapshot
from .event_chain_text import figure_runs, one_line, overlap, rule_problem

CHAIN_VERSION = "event-chain-0.1"
CHAIN_INDEX_VERSION = "event-chain-index-0.1"
MECHANISMS_VERSION = "event-mechanisms-0.1"
MECHANISMS_INDEX_VERSION = "event-mechanisms-index-0.1"
THESIS = "copper"
INDEX = "index.json"
MAX_FILE_BYTES = 1_000_000
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REF = re.compile(r"(?:copper|fcx):[a-z0-9]+(?:-[a-z0-9]+)*")
SHA256 = re.compile(r"[0-9a-f]{64}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
DIGIT = re.compile(r"\d")
NOT_STATED = "No retained source states "
MAX_TITLE, MAX_LABEL, MAX_MECHANISM, MAX_NOT_STATED, MAX_NOTE = 100, 80, 240, 160, 1000
ACQUISITION_FIELDS = {
    "copper": ("approval_id", "attempt", "origin", "url", "folder", "name", "sha256", "bytes", "retrieved_at"),
    "fcx": ("approval_id", "attempt", "url", "folder", "name", "sha256", "bytes", "retrieved_at"),
}
FIELDS = {"chain_version", "id", "version", "previous_version", "title", "event", "target", "steps", "evidence",
          "change", "provenance"}


class ChainRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def chains_dir(theses: Path) -> Path:
    return Path(theses) / THESIS / "event-chains"


def mechanisms_dir(metals: Path) -> Path:
    return Path(metals) / "mechanisms"


def _refuse(where: str, rule: str) -> ChainRefused:
    return ChainRefused(500, f"{where}: {rule}")


def _check(condition: bool, where: str, rule: str) -> None:
    if not condition:
        raise _refuse(where, rule)


def _object(value: object, where: str, keys: set | tuple) -> dict:
    _check(isinstance(value, dict), where, "expected an object")
    _check(set(value) == set(keys), where, f"expected exactly the fields {sorted(keys)}")
    return value


def _line(value: object, where: str, limit: int = 1000) -> str:
    _check(isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= limit and
           one_line(value), where, f"expected one line of text of at most {limit} characters")
    return value


def _count(value: object, where: str, minimum: int = 1) -> int:
    _check(type(value) is int and value >= minimum, where, f"expected a whole number of at least {minimum}")
    return value


def _digest(value: object, where: str) -> str:
    _check(isinstance(value, str) and bool(SHA256.fullmatch(value)), where, "expected 64 lowercase hex characters")
    return value


def _day(value: object, where: str) -> str:
    _check(isinstance(value, str) and bool(DAY.fullmatch(value)), where, "expected a date, YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise _refuse(where, "expected a real date") from None
    return value


def _ident(value: object, where: str) -> str:
    _check(isinstance(value, str) and bool(ID.fullmatch(value)), where, "expected a lowercase id")
    return value


def _ref(value: object, where: str) -> str:
    _check(isinstance(value, str) and bool(REF.fullmatch(value)), where, "expected a copper: or fcx: reference")
    return value


def _owned_text(value: object, where: str, limit: int, *, figures: bool = False) -> str:
    """Assistant text: one line, no claim word, no view on a price's direction, and no digits unless figures."""
    text = _line(value, where, limit)
    problem = rule_problem(text)
    _check(problem is None, where, problem or "")
    _check(figures or not DIGIT.search(text), where, "states no figures")
    return text


def _read(path: Path, what: str) -> object:
    _check(path.is_file(), what, "the file is not there")
    _check(path.stat().st_size <= MAX_FILE_BYTES, what, "larger than a content file may be")
    try:
        return bis_snapshot._strict_json(path.read_bytes().decode("utf-8"), f"The file {what}")
    except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        raise _refuse(what, "not strict UTF-8 JSON") from None


def _index(folder: Path, index_version: str, ident: str | None, what: str) -> dict:
    raw = _read(folder / INDEX, f"{what}/{INDEX}")
    where = f"{what}/{INDEX}"
    _object(raw, where, {"index_version", "id", "versions"})
    _check(raw["index_version"] == index_version, f"{where}.index_version", f"expected {index_version}")
    _ident(raw["id"], f"{where}.id")
    if ident is not None:
        _check(raw["id"] == ident, f"{where}.id", f"expected {ident}")
    _check(isinstance(raw["versions"], list) and bool(raw["versions"]), f"{where}.versions", "expected a list")
    for number, entry in enumerate(raw["versions"], start=1):
        at = f"{where}.versions[{number - 1}]"
        _object(entry, at, {"version", "file", "sha256", "published_on"})
        _check(entry["version"] == number and type(entry["version"]) is int, f"{at}.version",
               f"expected {number}")
        _check(entry["file"] == f"v{number}.json", f"{at}.file", f"expected v{number}.json")
        _digest(entry["sha256"], f"{at}.sha256")
        _day(entry["published_on"], f"{at}.published_on")
    return raw


def _version_file(folder: Path, entry: dict, what: str) -> dict:
    name = f"{what}/{entry['file']}"
    loaded = _read(folder / entry["file"], name)
    _check(bis_snapshot.sha256(bis_snapshot.canonical(loaded)) == entry["sha256"], name,
           "does not match the SHA-256 its index records")
    return loaded


# ---------------------------------------------------------------- the mechanism list

def _mechanism_text(text: object, where: str) -> str:
    _owned_text(text, where, MAX_MECHANISM)
    _check(text.startswith(("When ", "If ")), where, 'expected a condition starting with "When " or "If "')
    return text


def load_mechanisms(folder: Path) -> dict[int, dict]:
    """version -> {"sha256", "published_on", "entries": {id: text}}, every file strictly checked."""
    folder = Path(folder)
    what = "mechanisms"
    index = _index(folder, MECHANISMS_INDEX_VERSION, "mechanisms", what)
    found = {}
    for entry in index["versions"]:
        number = entry["version"]
        name = f"{what}/{entry['file']}"
        loaded = _version_file(folder, entry, what)
        _object(loaded, name, {"mechanisms_version", "version", "entries"})
        _check(loaded["mechanisms_version"] == MECHANISMS_VERSION, f"{name}.mechanisms_version",
               f"expected {MECHANISMS_VERSION}")
        _check(loaded["version"] == number and type(loaded["version"]) is int, f"{name}.version",
               f"expected {number}")
        _check(isinstance(loaded["entries"], list) and bool(loaded["entries"]), f"{name}.entries",
               "expected a list of mechanisms")
        entries = {}
        for at, item in enumerate(loaded["entries"]):
            place = f"{name}.entries[{at}]"
            _object(item, place, {"id", "text"})
            _ident(item["id"], f"{place}.id")
            _check(item["id"] not in entries, f"{place}.id", "repeats an earlier mechanism")
            entries[item["id"]] = _mechanism_text(item["text"], f"{place}.text")
        found[number] = {"sha256": entry["sha256"], "published_on": entry["published_on"], "entries": entries}
    return found


# ---------------------------------------------------------------- the pinned evidence

def _acquisition(value: object, where: str, kind: str) -> None:
    _object(value, where, ACQUISITION_FIELDS[kind])
    _count(value["attempt"], f"{where}.attempt")
    _count(value["bytes"], f"{where}.bytes", 0)
    _digest(value["sha256"], f"{where}.sha256")
    for key in ACQUISITION_FIELDS[kind]:
        if key not in ("attempt", "bytes", "sha256"):
            _line(value[key], f"{where}.{key}")


def acquisition_shaped(value: object, kind: str) -> bool:
    """Whether a pinned acquisition record of a copper or fcx document holds exactly its kind's fields, each of the type
    a chain version's evidence requires (the same check as there)."""
    try:
        _acquisition(value, "acquisition", kind)
    except ChainRefused:
        return False
    return True


def _evidence(value: object, where: str, chain: dict, mechanisms: dict[int, dict]) -> dict[str, str]:
    """Check the evidence shape against the chain; returns the pinned quotes by passage reference."""
    _object(value, where, {"event", "passages", "documents", "thesis", "mechanisms"})
    event = _object(value["event"], f"{where}.event", {"passage", "kind", "when"})
    _ref(event["passage"], f"{where}.event.passage")
    _check(event["passage"] == chain["event"], f"{where}.event.passage", "differs from the chain's event")
    _line(event["kind"], f"{where}.event.kind")
    _line(event["when"], f"{where}.event.when")
    _check(isinstance(value["passages"], list), f"{where}.passages", "expected a list")
    quotes, order = {}, []
    for number, item in enumerate(value["passages"]):
        at = f"{where}.passages[{number}]"
        _object(item, at, {"ref", "source", "location", "quote"})
        order.append(_ref(item["ref"], f"{at}.ref"))
        _ident(item["source"], f"{at}.source")
        _check(isinstance(item["location"], dict) and bool(item["location"]), f"{at}.location",
               "expected an object")
        quotes[item["ref"]] = _line(item["quote"], f"{at}.quote")
    expected = []
    for step in chain["steps"]:
        if step["kind"] == "stated" and step["passage"] not in expected:
            expected.append(step["passage"])
    _check(order == expected, f"{where}.passages", "expected exactly the stated steps' passages, in step order")
    _check(isinstance(value["documents"], list), f"{where}.documents", "expected a list")
    refs = []
    for number, item in enumerate(value["documents"]):
        at = f"{where}.documents[{number}]"
        _object(item, at, {"ref", "acquisition"})
        refs.append(_ref(item["ref"], f"{at}.ref"))
        _acquisition(item["acquisition"], f"{at}.acquisition", item["ref"].split(":")[0])
    _check(refs == sorted(set(refs)), f"{where}.documents", "expected documents sorted by ref, each once")
    thesis = _object(value["thesis"], f"{where}.thesis", {"id", "version", "sha256"})
    _check(thesis["id"] == THESIS, f"{where}.thesis.id", f"expected {THESIS}")
    _count(thesis["version"], f"{where}.thesis.version")
    _digest(thesis["sha256"], f"{where}.thesis.sha256")
    pinned = _object(value["mechanisms"], f"{where}.mechanisms", {"version", "sha256"})
    _check(type(pinned["version"]) is int and pinned["version"] in mechanisms, f"{where}.mechanisms.version",
           "names a mechanisms version that is not published")
    _check(pinned["sha256"] == mechanisms[pinned["version"]]["sha256"], f"{where}.mechanisms.sha256",
           "differs from the SHA-256 its mechanisms index records")
    return quotes


# ---------------------------------------------------------------- a chain version

def _steps(value: object, where: str) -> list[dict]:
    _check(isinstance(value, list) and bool(value), where, "expected a list of steps")
    phase = 0  # 0 stated, 1 not_stated, 2 mechanism
    for number, step in enumerate(value):
        at = f"{where}[{number}]"
        _check(isinstance(step, dict), at, "expected an object")
        kind = step.get("kind")
        _check(kind in ("stated", "not_stated", "mechanism"), f"{at}.kind",
               "expected stated, not_stated or mechanism")
        keys = {"stated": {"kind", "passage", "label"}, "not_stated": {"kind", "text"},
                "mechanism": {"kind", "id"}}[kind]
        _object(step, at, keys)
        rank = ("stated", "not_stated", "mechanism").index(kind)
        _check(rank >= phase, at, f"a {kind} step may not follow a later kind of step")
        _check(number > 0 or kind == "stated", at, "the first step must be the event, a stated step")
        phase = rank
        if kind == "stated":
            _ref(step["passage"], f"{at}.passage")
        elif kind == "mechanism":
            _ident(step["id"], f"{at}.id")
    _check(phase == 2, where, "expected at least one mechanism step, after the others")
    return value


def _check_labels_and_text(chain: dict, quotes: dict[str, str], mechanisms: dict, where: str) -> None:
    steps = chain["steps"]
    for number, step in enumerate(steps):
        at = f"{where}.steps[{number}]"
        if step["kind"] == "stated":
            quote = quotes[step["passage"]]
            label = _owned_text(step["label"], f"{at}.label", MAX_LABEL, figures=True)
            extra = figure_runs(label, len(steps)) - set(re.findall(r"\d+", quote))
            _check(not extra, f"{at}.label", f"holds figures its quote does not: {sorted(extra)}")
            run = overlap(label, [quote])
            _check(run is None, f"{at}.label", f"repeats six words of its quote: {run!r}")
        elif step["kind"] == "not_stated":
            text = _owned_text(step["text"], f"{at}.text", MAX_NOT_STATED)
            _check(text.startswith(NOT_STATED), f"{at}.text", f'expected to start "{NOT_STATED}"')
        else:
            _check(step["id"] in mechanisms, f"{at}.id", "names a mechanism the pinned mechanisms version lacks")


def _check_chain(raw: object, chain_id: str, number: int, where: str, mechanisms: dict[int, dict]) -> dict:
    _object(raw, where, FIELDS)
    _check(raw["chain_version"] == CHAIN_VERSION, f"{where}.chain_version", f"expected {CHAIN_VERSION}")
    _check(raw["id"] == chain_id, f"{where}.id", f"expected {chain_id}")
    _check(raw["version"] == number and type(raw["version"]) is int, f"{where}.version", f"expected {number}")
    _check(raw["previous_version"] == (number - 1 or None) and type(raw["previous_version"]) in (int, type(None)),
           f"{where}.previous_version", f"expected {number - 1 or None}")
    _owned_text(raw["title"], f"{where}.title", MAX_TITLE)
    _ref(raw["event"], f"{where}.event")
    target = _object(raw["target"], f"{where}.target", {"kind", "id"})
    _check(target["kind"] in ("reason", "risk"), f"{where}.target.kind", "expected reason or risk")
    _ident(target["id"], f"{where}.target.id")
    _steps(raw["steps"], f"{where}.steps")
    _check(raw["steps"][0]["passage"] == raw["event"], f"{where}.steps[0].passage", "differs from the chain's event")
    change = raw["change"]
    if number == 1:
        _check(change is None, f"{where}.change", "expected null in version 1")
    else:
        _object(change, f"{where}.change", {"answers_review", "note"})
        if change["answers_review"] is not None:
            _digest(change["answers_review"], f"{where}.change.answers_review")
        _owned_text(change["note"], f"{where}.change.note", MAX_NOTE)
    provenance = _object(raw["provenance"], f"{where}.provenance", {"prepared_by", "ai_assisted", "research_use"})
    _line(provenance["prepared_by"], f"{where}.provenance.prepared_by")
    _check(provenance["ai_assisted"] is True, f"{where}.provenance.ai_assisted", "expected true")
    _check(provenance["research_use"] == "excluded", f"{where}.provenance.research_use", 'expected "excluded"')
    quotes = _evidence(raw["evidence"], f"{where}.evidence", raw, mechanisms)
    pinned = mechanisms[raw["evidence"]["mechanisms"]["version"]]["entries"]
    _check_labels_and_text(raw, quotes, pinned, where)
    return raw


def load_chains(folder: Path, mechanisms: dict[int, dict]) -> dict[str, dict]:
    """chain id -> {"id", "versions": [version + "sha256" + "published_on", ...]}, every file strictly checked."""
    folder = Path(folder)
    chains = {}
    if not folder.is_dir():
        return chains
    for sub in sorted(path for path in folder.iterdir() if path.is_dir()):
        chain_id = sub.name
        _ident(chain_id, f"event-chains/{chain_id}")
        index = _index(sub, CHAIN_INDEX_VERSION, chain_id, f"event-chains/{chain_id}")
        versions = []
        for entry in index["versions"]:
            what = f"event-chains/{chain_id}/{entry['file']}"
            loaded = _check_chain(_version_file(sub, entry, f"event-chains/{chain_id}"), chain_id,
                                  entry["version"], what, mechanisms)
            versions.append(dict(loaded, sha256=entry["sha256"], published_on=entry["published_on"]))
        chains[chain_id] = {"id": chain_id, "versions": versions}
    return chains

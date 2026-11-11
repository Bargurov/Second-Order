"""Copper event chains: the evidence a chain version rests on, pinned from the live records and compared with them.

A chain version pins (spec 5.4) its register event {passage, kind, when}; each cited passage once, as {ref, source,
location, quote}; each retained document of the cited passages and of the target element, as {ref, acquisition}; the
thesis version; and the mechanism list version. live() projects the same items from the raw files: the thesis's latest
published version file (a draft is never the basis: not pinned, compared or counted as newer), facts.json, the register
and the source entries (that version's sources and sources.json). It never reads a served view that withholds, so
withholding a source never changes a projection, and a pin taken with a document missing equals the pin with it
present. Only the verifiers decide states: thesis_sources.verify and company_research_view.verify for documents, and
thesis_view's own check (the one thesis_view.passages makes, here for the published version) for whether a copper
quote is found where cited. A thesis with no published version cannot be pinned, and leaves the target unavailable.

compare() reads each pinned item as same, changed or gone, and each pinned document as verified, changed, missing,
superseded (its live source entry records another acquisition) or unreadable (facts.json or sources.json cannot be
read, which makes every fcx: item and document unreadable). The chain's state is the first that applies of
unavailable, needs_revalidation, evidence_changed and thesis_newer, else available, and every reason that applies is
listed. A record the chain does not cite is never compared.

verify_pinned() checks a pinned document through its pinned acquisition with the same verifier, never through the
current source entry, so a record on an older basis stays verifiable while its file and acquisition record are kept.
Reads only: nothing here writes, fetches or calls a model.
"""
from dataclasses import dataclass
from pathlib import Path

from . import bis_snapshot, company_research_view, metals_research, thesis_schema, thesis_sources, thesis_view
from .event_chain_schema import ACQUISITION_FIELDS, THESIS, ChainRefused, load_mechanisms, mechanisms_dir

STATES = ("unavailable", "needs_revalidation", "evidence_changed", "thesis_newer")
DOCUMENT_REASONS = {
    "missing": "The document {ref} is not on this machine, or its acquisition record or source entry is not",
    "unreadable": "The FCX research cannot be read, so the document {ref} is not checked",
    "changed": "The document {ref} differs from its acquisition record",
    "superseded": "The source entry of {ref} now records another acquisition than the pinned one",
}
ITEM_REASONS = {
    ("event", "changed"): "The register event {ref} differs from the pinned one",
    ("event", "gone"): "The register no longer holds the copper event {ref}",
    ("passage", "changed"): "The passage {ref} differs from its pinned wording or location",
    ("passage", "gone"): "No record holds the passage {ref} any more",
}
TARGET_REASONS = {  # By the target element's state (missing: the latest published version has no such element).
    "unavailable": ("unavailable", "The target element is unavailable: a source of it is not on this machine"),
    "missing": ("unavailable", "The target element is not in the thesis's latest published version"),
    "needs_revalidation": ("needs_revalidation", "The target element needs revalidation: a source of it differs from "
                                                 "its acquisition record, or an item of it is not found where cited"),
}


@dataclass(frozen=True)
class Folders:
    theses: Path
    thesis_sources: Path
    metals: Path
    metals_sources: Path
    research: Path
    company_sources: Path
    records: Path


# ---------------------------------------------------------------- projections from raw records

def project_copper(passage: dict) -> dict:
    """A copper thesis passage {id, source, locator} as pinned: its locator without the quote is its location."""
    locator = passage["locator"]
    return {"ref": f"copper:{passage['id']}", "source": passage["source"],
            "location": {key: value for key, value in locator.items() if key != "quote"}, "quote": locator["quote"]}


def project_fcx(passage: dict) -> dict:
    """An FCX facts.json passage as pinned; its topic and added_by are not part of the evidence."""
    return {"ref": f"fcx:{passage['id']}", "source": passage["source"],
            "location": {"page": passage["page"], "printed_page": passage.get("printed_page"),
                         "location": passage.get("location")}, "quote": passage["quote"]}


def _acquisition(entry: dict, kind: str) -> dict:
    return {key: entry[key] for key in ACQUISITION_FIELDS[kind]}


def _cited(chain_version: dict) -> list[str]:
    """The stated steps' passage references, each once, in step order (the event's first)."""
    return list(dict.fromkeys(step["passage"] for step in chain_version["steps"] if step["kind"] == "stated"))


def _fcx(research: Path) -> tuple[dict | None, dict | None]:
    """(facts.json passages by id, sources.json entries by id); either is None when its file cannot be read."""
    try:
        held = {item["id"]: item for item in company_research_view.facts_passages(research)}
    except company_research_view.CompanyRefused:
        held = None
    try:
        entries = {item["id"]: item for item in company_research_view.load_sources(research)}
    except company_research_view.CompanyRefused:
        entries = None
    return held, entries


def _event(chain_version: dict, metals: Path) -> dict | None:
    content = metals_research.load(metals)
    for event in content["metals"].get("copper", {}).get("events", []):
        if event["passage"] == chain_version["event"]:
            return {"passage": event["passage"], "kind": event["kind"], "when": event["when"]}
    return None


def latest_published(theses: Path) -> dict | None:
    """The index entry of the thesis's latest published version (only the last version may be a draft), or None.
    Raises thesis_rules.ThesisRefused for an unreadable index."""
    versions = thesis_schema.load_index(THESIS, theses)["versions"]
    return next((entry for entry in reversed(versions) if entry["published_on"] is not None), None)


def _quote_states(thesis: dict, ids: list[str], sources_root: Path) -> dict[str, str]:
    """{passage id: "verified" | "changed" | "missing" | "not_found"} for passages of ``thesis`` (any version), decided
    by thesis_view's check exactly as thesis_view.passages decides it for the latest version."""
    asked = [item for item in thesis["passages"] if item["id"] in ids]
    used = {item["source"] for item in asked}
    states, problems = thesis_view._checked({"sources": [item for item in thesis["sources"] if item["id"] in used],
                                             "figures": [], "passages": asked}, Path(sources_root))
    found = {}
    for item in asked:
        source = states[item["source"]]["state"]
        found[item["id"]] = source if source != "verified" else "not_found" if problems[item["id"]] else "verified"
    return found


def _target(chain_version: dict, version: int | None, folders: Folders, shown: dict | None) -> dict:
    if version is None:
        return {"state": "unavailable", "sources": [], "element": None}
    if shown is None:
        shown = thesis_view.view(THESIS, version, folders.theses, folders.thesis_sources)
    target = chain_version["target"]
    group = shown["reasons"] if target["kind"] == "reason" else shown["risks"]
    element = next((item for item in group if item["id"] == target["id"]), None)
    if element is None:
        return {"state": "missing", "sources": [], "element": None}
    return {"state": element["state"], "sources": list(element["sources"]), "element": element}


def _document(ref: str, copper: dict, fcx: dict | None, fcx_readable: bool, folders: Folders) -> dict:
    """A document's live acquisition (its source entry restricted to the pinned fields) and its verifier's state."""
    kind, ident = ref.split(":", 1)
    if kind == "copper":
        entry = copper.get(ident)
        state = thesis_sources.verify(entry, folders.thesis_sources)[0]["state"] if entry else "missing"
    else:
        entry = (fcx or {}).get(ident)
        if not fcx_readable:
            state = "unreadable"
        elif entry is None:
            state = "missing"
        else:
            state = company_research_view.verify(entry, folders.research, folders.company_sources)["state"]
    return {"acquisition": _acquisition(entry, kind) if entry else None, "state": state}


def live(chain_version: dict, folders: Folders, shown: dict | None = None) -> dict:
    """The live projections of the chain's pinned items, its documents' live acquisitions and states (the documents of
    the live records, and those its evidence pins, if any), the thesis's latest published version (version and sha256
    None when none is published) and the target element in it. ``shown`` is thesis_view.view of that latest published
    version when the caller has it already (one read serves several chains); otherwise it is computed here. Raises
    thesis_rules.ThesisRefused for an unreadable thesis and metals_research.ResearchRefused for an unreadable register.
    Reads only."""
    refs = _cited(chain_version)
    published = latest_published(folders.theses)
    thesis = thesis_schema.load_version(THESIS, published["version"], folders.theses) if published else None
    copper_held = {item["id"]: item for item in thesis["passages"]} if thesis else {}
    copper_entries = {item["id"]: item for item in thesis["sources"]} if thesis else {}
    fcx_held, fcx_entries = _fcx(folders.research)
    fcx_readable = fcx_held is not None and fcx_entries is not None

    passages = {}
    for ref in refs:
        kind, ident = ref.split(":", 1)
        if kind == "copper":
            passages[ref] = project_copper(copper_held[ident]) if ident in copper_held else None
        else:
            passages[ref] = project_fcx(fcx_held[ident]) if fcx_readable and ident in fcx_held else None
    target = _target(chain_version, published["version"] if published else None, folders, shown)

    named = [f"{ref.split(':', 1)[0]}:{item['source']}" for ref, item in passages.items() if item is not None]
    named += [f"copper:{source}" for source in target["sources"]]
    named += [item["ref"] for item in (chain_version.get("evidence") or {}).get("documents", [])]
    documents = {ref: _document(ref, copper_entries, fcx_entries, fcx_readable, folders) for ref in sorted(set(named))}

    copper_ids = [ref.split(":", 1)[1] for ref in refs if ref.startswith("copper:") and passages[ref] is not None]
    found = _quote_states(thesis, copper_ids, folders.thesis_sources) if copper_ids else {}
    quote_states = {}
    for ref in refs:
        kind, ident = ref.split(":", 1)
        if kind == "fcx" and not fcx_readable:
            quote_states[ref] = "unreadable"
        elif passages[ref] is None:
            quote_states[ref] = "gone"
        elif kind == "copper":
            quote_states[ref] = found[ident]
        else:
            quote_states[ref] = documents[f"fcx:{passages[ref]['source']}"]["state"]
    return {"event": _event(chain_version, folders.metals), "passages": passages, "quote_states": quote_states,
            "documents": documents, "thesis": {"version": published["version"] if published else None,
                                               "sha256": published["sha256"] if published else None},
            "target": target}


# ---------------------------------------------------------------- the pin

def pin(chain_version: dict, folders: Folders) -> dict:
    """The evidence block for ``chain_version`` (its own evidence, which may be None, is ignored), copied from the raw
    records. Raises ChainRefused(422) when the thesis has no published version, or when the event, a cited record, the
    target or a document's entry is not there."""
    current = live({**chain_version, "evidence": None}, folders)
    if current["thesis"]["version"] is None:
        raise ChainRefused(422, f"thesis: the {THESIS} thesis has no published version to pin on")
    if current["event"] is None:
        raise ChainRefused(422, f"event: {chain_version['event']} is not a copper event on the register")
    for ref, item in current["passages"].items():
        if item is None:
            raise ChainRefused(422, f"passages: {ref} is not a record that can be read now")
    if current["target"]["element"] is None:
        target = chain_version["target"]
        raise ChainRefused(422, f"target: the {target['kind']} {target['id']} is not in the thesis's latest published "
                                "version")
    for ref, item in current["documents"].items():
        if item["acquisition"] is None:
            raise ChainRefused(422, f"documents: {ref} has no source entry that can be read now")
    mechanisms = load_mechanisms(mechanisms_dir(folders.metals))
    version = max(mechanisms)
    return {"event": current["event"],
            "passages": [current["passages"][ref] for ref in _cited(chain_version)],
            "documents": [{"ref": ref, "acquisition": item["acquisition"]}
                          for ref, item in sorted(current["documents"].items())],
            "thesis": {"id": THESIS, **current["thesis"]},
            "mechanisms": {"version": version, "sha256": mechanisms[version]["sha256"]}}


def evidence_sha256(evidence: dict) -> str:
    return bis_snapshot.sha256(bis_snapshot.canonical(evidence))


def verify_pinned(document: dict, folders: Folders) -> dict:
    """{"state": "verified" | "changed" | "missing", "detail"} for a pinned document, checked through its pinned
    acquisition (never the current source entry) with the verifier of its kind. Reads only."""
    kind = document["ref"].split(":", 1)[0]
    acquisition = document["acquisition"]
    malformed = {"state": "changed", "detail": "The pinned acquisition does not name one retained file."}
    if kind == "copper":
        try:
            return thesis_sources.verify(acquisition, folders.thesis_sources)[0]
        except ValueError:
            return malformed
    if not all(isinstance(acquisition[key], str) and company_research_view.SEGMENT.match(acquisition[key])
               and acquisition[key] not in (".", "..") for key in ("approval_id", "folder", "name")):
        return malformed
    return company_research_view.verify(acquisition, folders.research, folders.company_sources)


# ---------------------------------------------------------------- the comparison

def _document_state(pinned: dict, current: dict | None) -> str:
    if current is not None and current["state"] == "unreadable":
        return "unreadable"
    if current is None or current["acquisition"] is None:
        return "missing"
    if current["acquisition"] != pinned["acquisition"]:
        return "superseded"
    return current["state"]


def _item(kind: str, ref: str, pinned: dict, current: dict | None, unreadable: bool) -> dict:
    state = "unreadable" if unreadable else "gone" if current is None else "same" if current == pinned else "changed"
    return {"ref": ref, "kind": kind, "state": state, "pinned": pinned, "current": current}


def compare(evidence: dict, current: dict) -> dict:
    """The pinned evidence against live(): each item's and document's state, every reason that applies and the first
    state in order (see the module docstring)."""
    found = {name: [] for name in STATES}
    event = evidence["event"]
    items = [_item("event", event["passage"], event, current["event"], False)]
    for pinned in evidence["passages"]:
        ref = pinned["ref"]
        quote = current["quote_states"].get(ref)
        items.append(_item("passage", ref, pinned, current["passages"].get(ref), quote == "unreadable"))
        if quote == "not_found":
            found["needs_revalidation"].append(f"The passage {ref} is not found where it is cited")
    for item in items:
        if item["state"] in ("changed", "gone"):
            found["evidence_changed"].append(ITEM_REASONS[item["kind"], item["state"]].format(ref=item["ref"]))
    documents = []
    for pinned in evidence["documents"]:
        state = _document_state(pinned, current["documents"].get(pinned["ref"]))
        documents.append({"ref": pinned["ref"], "state": state})
        if state != "verified":
            group = "unavailable" if state in ("missing", "unreadable") else "needs_revalidation"
            found[group].append(DOCUMENT_REASONS[state].format(ref=pinned["ref"]))
    pinned, latest = evidence["thesis"], current["thesis"]
    if latest["version"] is None:  # Nothing published: no passage, source entry or target element can be read.
        found["unavailable"].append("The thesis has no published version")
    else:
        if current["target"]["state"] in TARGET_REASONS:
            group, reason = TARGET_REASONS[current["target"]["state"]]
            found[group].append(reason)
        if pinned["version"] < latest["version"]:
            found["thesis_newer"].append(f"The thesis has a newer published version ({latest['version']}) than the "
                                         f"one this chain was pinned on ({pinned['version']})")
        elif (pinned["version"], pinned["sha256"]) != (latest["version"], latest["sha256"]):
            found["evidence_changed"].append("The thesis version this chain was pinned on differs from its index")
    state = next((name for name in STATES if found[name]), "available")
    return {"state": state, "reasons": [reason for name in STATES for reason in found[name]], "items": items,
            "documents": documents}

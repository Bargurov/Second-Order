"""Copper event chains as served (event-chains-view-0.1), and the binding a write rests on (current).

One read computes, once: the copper thesis's latest published version and its served view (thesis_view), the mechanism
list and the chain versions (event_chain_schema, which refuses invalid content with 500), the price series, document
names and each pinned document's verification. A thesis that has no published version, or cannot be read, refuses the
read with 503. Each chain's latest version is compared with the live records (event_chain_evidence), which gives its
state and every reason that applies.

Withholding (spec 6). A stated step's quote is withheld whole while its document does not verify with the pinned
SHA-256 (any document state but verified) or the quote is not found where cited, and its label too when the label holds
a digit; places, titles, not-stated lines and mechanisms are always shown. A changed record shows its pinned wording and
its current wording side by side, and a gone record its pinned wording, both only while the document verifies. The
history shows each version's pinned wording only while its document passes verify_pinned through the pinned
acquisition, so a record on an older acquisition stays readable while that file and its record are kept.

The owner's words (review notes, reading lines) are always shown with their state, their basis and each basis
document's state now. While any document of a record's basis fails verify_pinned, every figure in its text is masked
(event_chain_text.masked), except step references. Approval states: awaiting_review, needs_revision, approved,
approved_earlier_basis; reading states: current, earlier_basis; each record names what differs now. A record's figures
are masked by the step count of the version it names (each history version serves its count). A record history that
cannot be verified (event_chain_records.history: numbering, ids, the parent chain, each record's shape, and a version
that is in the chain's history) is shown as invalid with its reason and no records, never repaired, and the read goes
on; so is a chain whose records fail in any other way, so one chain's records never break the read. Invalid content
still refuses the whole read (event_chain_schema). Withheld fields are null, never left out. Reads only: nothing here
writes, fetches or calls a model.
"""
import re
from pathlib import Path

from . import bis_snapshot, company_research_view, event_chain_text, metals_research, thesis_view
from .event_chain_evidence import Folders, compare, evidence_sha256, latest_published, live, verify_pinned
from .event_chain_price import measure, series
from .event_chain_records import KINDS, Current, RecordRefused, history
from .event_chain_schema import THESIS, ChainRefused, chains_dir, load_chains, load_mechanisms, mechanisms_dir
from .thesis_rules import ThesisRefused
from .thesis_sections import shown

VIEW_VERSION = "event-chains-view-0.1"
TARGET_NOTE = "The thesis's own measure of this {kind}. It does not measure this event."
ABSENT_REVIEW = "names a review that is not on this machine"
DIGIT = re.compile(r"\d")
WITHHELD = {
    "changed": "Withheld: {name} no longer matches its acquisition record",
    "missing": "Withheld: {name} is not on this machine, or its acquisition record or source entry is not",
    "superseded": "Withheld: {name} now has another acquisition than the one this version pinned",
    "unreadable": "Withheld: the FCX research cannot be read, so {name} is not checked",
}
NOT_FOUND = "Withheld: the passage {ref} is not found where it is cited ({where})"
GONE = "No record holds the passage {ref} any more; its pinned wording is in the history"
CHANGED = "{ref}: its {what} {verb} from the pinned version"
MASK_REASON = "Figures are withheld while a document it rested on does not match its pinned acquisition: {refs}"
NEWER = "The chain has a newer version ({latest}) than version {version}, which this {noun} was saved on"
OTHER_VERSION = "The chain version this {noun} names differs from the published version {version}"
NO_APPROVAL = "The chain has no current approval"
OTHER_APPROVAL = "It was given under another approval than the chain's current one"
LATER = "A later {noun} followed it"
UNREADABLE = "The saved records of this chain could not be read ({error})"
INVALID_APPROVAL = {"state": None, "review_id": None, "saved_at": None, "account": None, "notes": None, "masked": None,
                    "differs": []}
FIELDS = {"reviews": ("review_id", "parent_review_id", "sequence", "status", "notes", "account", "saved_at"),
          "readings": ("reading_id", "parent_reading_id", "sequence", "approval_id", "target", "short_term",
                       "long_term", "line", "account", "saved_at")}
TEXT = {"reviews": "notes", "readings": "line"}
NOUN = {"reviews": "review", "readings": "reading"}


class _Read:
    """What one read computes once (see the module docstring)."""

    def __init__(self, folders: Folders):
        self.folders = folders
        try:
            published = latest_published(folders.theses)
            if published is None:
                raise ChainRefused(503, f"The {THESIS} thesis has no published version; no event chain is served")
            self.shown = thesis_view.view(THESIS, published["version"], folders.theses, folders.thesis_sources)
        except ThesisRefused as exc:
            raise ChainRefused(503, f"The {THESIS} thesis cannot be read ({exc}); no event chain is served") from None
        self.version = published["version"]
        self.names = {f"copper:{item['id']}": item["title"] for item in self.shown["sources"]}
        try:
            self.names.update({f"fcx:{item['id']}": f"the FCX {item['form']}"
                               for item in company_research_view.load_sources(folders.research)})
        except company_research_view.CompanyRefused:
            pass
        self._verified: dict[str, dict] = {}
        self._series: dict | None = None

    def name(self, ref: str) -> str:
        return self.names.get(ref, ref)

    def verified(self, document: dict) -> dict:
        """{"ref", "name", "state", "detail"}: verify_pinned through the pinned acquisition, once per read."""
        key = bis_snapshot.canonical(document)
        if key not in self._verified:
            self._verified[key] = verify_pinned(document, self.folders)
        return {"ref": document["ref"], "name": self.name(document["ref"]), **self._verified[key]}

    def price(self, when: str) -> dict:
        if self._series is None:
            self._series = series(self.folders)
        return measure(when, self._series)

    def compared(self, version: dict) -> tuple[dict, dict]:
        try:
            now = live(version, self.folders, self.shown)
        except metals_research.ResearchRefused as exc:
            raise ChainRefused(500, f"The metals register cannot be read: {exc}") from None
        except ThesisRefused as exc:
            raise ChainRefused(503, f"The {THESIS} thesis cannot be read ({exc}); no event chain is served") from None
        return now, compare(version["evidence"], now)


def _content(folders: Folders) -> tuple[dict, dict]:
    """(mechanism versions, chains); both empty when no chain folder exists."""
    folder = chains_dir(folders.theses)
    if not folder.is_dir():
        return {}, {}
    mechanisms = load_mechanisms(mechanisms_dir(folders.metals))
    return mechanisms, load_chains(folder, mechanisms)


# ---------------------------------------------------------------- the owner's records

def _histories(records: Path, chain: dict) -> tuple[list[dict], list[dict], str | None]:
    """(reviews, readings, None), or ([], [], why) when either history cannot be verified: history checks numbering,
    ids, the parent chain and each record's shape, and that each names one of the chain's published versions."""
    try:
        found = {kind: history(records, kind, chain["id"], len(chain["versions"])) for kind in KINDS}
    except RecordRefused as exc:
        return [], [], exc.message
    return found["reviews"], found["readings"], None


def _approval_id(latest: dict, compared: dict, reviews: list[dict]) -> str | None:
    last = reviews[-1] if reviews else None
    if last is not None and last["basis"]["chain"]["sha256"] == latest["sha256"] and last["status"] == "approved" \
            and compared["state"] == "available":
        return last["review_id"]
    return None


class _Records:
    """One chain's records as served: each with its state, what differs now, its basis and its masked text."""

    def __init__(self, read: _Read, chain: dict, compared: dict, approval_id: str | None):
        self.read, self.chain, self.compared, self.approval_id = read, chain, compared, approval_id
        self.latest = chain["versions"][-1]

    def _version(self, basis_chain: dict) -> dict | None:
        number = basis_chain["version"]
        return self.chain["versions"][number - 1] if 1 <= number <= len(self.chain["versions"]) else None

    def differs(self, record: dict, kind: str, later: bool) -> list[str]:
        noun, basis_chain = NOUN[kind], record["basis"]["chain"]
        version = self._version(basis_chain)
        found = []
        if version is None or version["sha256"] != basis_chain["sha256"]:
            found.append(OTHER_VERSION.format(noun=noun, version=basis_chain["version"]))
        if basis_chain["sha256"] != self.latest["sha256"]:
            found.append(NEWER.format(latest=self.latest["version"], version=basis_chain["version"], noun=noun))
        else:
            found += self.compared["reasons"]
        if kind == "readings" and record["approval_id"] != self.approval_id:
            found.append(NO_APPROVAL if self.approval_id is None else OTHER_APPROVAL)
        if later:
            found.append(LATER.format(noun=noun))
        return found

    def shown(self, record: dict, kind: str, state: str, differs: list[str]) -> dict:
        basis = record["basis"]
        version = self._version(basis["chain"])  # Its own version (history verified that it is one), never the latest.
        documents = [self.read.verified(item) for item in basis["documents"]]
        failing = [item["ref"] for item in documents if item["state"] != "verified"]
        text = record[TEXT[kind]]
        return {**{key: record.get(key) for key in FIELDS[kind]},
                TEXT[kind]: event_chain_text.masked(text, len(version["steps"])) if failing else text,
                "basis": {"chain": basis["chain"], "evidence_sha256": basis.get("evidence_sha256"),
                          "thesis": basis["thesis"]},
                "basis_documents": documents, "masked": bool(failing),
                "mask_reason": MASK_REASON.format(refs=", ".join(failing)) if failing else None,
                "state": state, "differs": differs}

    def reviews(self, saved: list[dict]) -> list[dict]:
        shown = []
        for number, record in enumerate(saved, start=1):
            if record["status"] == "needs_revision":
                state = "needs_revision"
            else:
                state = "approved" if record["review_id"] == self.approval_id else "approved_earlier_basis"
            later = number < len(saved)
            shown.append(self.shown(record, "reviews", state, [] if state == "approved" else
                                    self.differs(record, "reviews", later)))
        return shown

    def readings(self, saved: list[dict]) -> list[dict]:
        shown = []
        for number, record in enumerate(saved, start=1):
            later = number < len(saved)
            current = not later and self.approval_id is not None and record["approval_id"] == self.approval_id \
                and record["basis"]["chain"]["sha256"] == self.latest["sha256"]
            shown.append(self.shown(record, "readings", "current" if current else "earlier_basis",
                                    [] if current else self.differs(record, "readings", later)))
        return shown

    def approval(self, reviews: list[dict]) -> dict:
        last = reviews[-1] if reviews else None
        if last is None or last["basis"]["chain"]["sha256"] != self.latest["sha256"]:
            return {"state": "awaiting_review", "review_id": None, "saved_at": None, "account": None, "notes": None,
                    "masked": False, "differs": []}
        state = last["state"]
        return {"state": state, "review_id": last["review_id"], "saved_at": last["saved_at"],
                "account": last["account"], "notes": last["notes"], "masked": last["masked"],
                "differs": list(self.compared["reasons"]) if state == "approved_earlier_basis" else []}


# ---------------------------------------------------------------- the chain

def _where(ref: str, location: dict) -> str:
    if ref.startswith("fcx:"):
        text = f"page {location['page']}"
        if location.get("printed_page") is not None:
            text += f" (printed page {location['printed_page']})"
        return text + (f", {location['location']}" if location.get("location") else "")
    if "paragraph" in location:
        return f"paragraph {location['paragraph']}"
    if "page" in location:
        return f"page {location['page']} (transcribed from the PDF)"
    return ", ".join(f"{key} {value}" for key, value in sorted(location.items()))


def _what(pinned: dict, current: dict) -> tuple[str, str]:
    parts = [name for name, key in (("document", "source"), ("wording", "quote"), ("location", "location"))
             if pinned[key] != current[key]]
    return " and ".join(parts), "differs" if len(parts) == 1 else "differ"


def _stated(read: _Read, step: dict, item: dict, documents: dict, quote_state: str | None) -> dict:
    ref = step["passage"]
    pinned, current = item["pinned"], item["current"]
    document = f"{ref.split(':', 1)[0]}:{pinned['source']}"
    state, name = documents.get(document, "missing"), read.name(document)
    where = _where(ref, (current or pinned)["location"])
    shown = {"kind": "stated", "label": step["label"], "ref": ref, "quote": None, "pinned_quote": None,
             "current_quote": None, "where": where, "pinned_where": None, "current_where": None,
             "document": {"ref": document, "name": name, "state": state}, "state": state, "problem": None}
    if state != "verified":
        shown["problem"] = WITHHELD[state].format(name=name)
    elif quote_state == "not_found":
        shown.update(state="not_found", problem=NOT_FOUND.format(ref=ref, where=where))
    elif item["state"] == "gone":
        shown.update(state="record_gone", problem=GONE.format(ref=ref), pinned_where=_where(ref, pinned["location"]))
    elif item["state"] == "changed":
        what, verb = _what(pinned, current)
        shown.update(state="record_changed", problem=CHANGED.format(ref=ref, what=what, verb=verb),
                     pinned_quote=pinned["quote"], pinned_where=_where(ref, pinned["location"]),
                     current_quote=current["quote"] if current["source"] == pinned["source"] else None,
                     current_where=_where(ref, current["location"]))
    else:
        shown.update(state="verified", quote=current["quote"])
    if shown["state"] not in ("verified", "record_changed", "record_gone") and DIGIT.search(step["label"]):
        shown["label"] = None  # A label holding a digit is withheld with its source's quote.
    return shown


def _steps(read: _Read, latest: dict, now: dict, compared: dict, texts: dict) -> list[dict]:
    items = {(item["kind"], item["ref"]): item for item in compared["items"]}
    documents = {item["ref"]: item["state"] for item in compared["documents"]}
    steps = []
    for step in latest["steps"]:
        if step["kind"] == "stated":
            steps.append(_stated(read, step, items["passage", step["passage"]], documents,
                                 now["quote_states"].get(step["passage"])))
        elif step["kind"] == "not_stated":
            steps.append({"kind": "not_stated", "text": step["text"]})
        else:
            steps.append({"kind": "mechanism", "id": step["id"], "text": texts[step["id"]]})
    return steps


def _target(latest: dict, now: dict) -> dict:
    element = now["target"]["element"] or {}
    return {"kind": latest["target"]["kind"], "id": latest["target"]["id"], "title": element.get("title"),
            "statement": element.get("statement"), "status": element.get("status"),
            "change_pct": element.get("change_pct"), "measure": element.get("measure"),
            "state": now["target"]["state"]}


def _event(evidence: dict, compared: dict) -> dict:
    item = next(item for item in compared["items"] if item["kind"] == "event")
    pick = (lambda event: {"kind": event["kind"], "when": event["when"]} if event else None)
    return {"passage": evidence["event"]["passage"], "state": item["state"], "pinned": pick(item["pinned"]),
            "current": pick(item["current"])}


def _versions(read: _Read, chain: dict, review_ids: list[str] | None, not_found: set[str]) -> list[dict]:
    """Each version with its step count, its change note and its pinned wording, shown only while its document passes
    verify_pinned (and, in the latest version, while the quote is found where cited: ``not_found`` names those that are
    not). ``review_ids`` is None when the history cannot be verified: whether a named review is here is then not
    said."""
    ids = set(review_ids or [])
    shown = []
    for version in chain["versions"]:
        latest = version is chain["versions"][-1]
        evidence = version["evidence"]
        documents = {item["ref"]: read.verified(item) for item in evidence["documents"]}
        passages = []
        for item in evidence["passages"]:
            ref = f"{item['ref'].split(':', 1)[0]}:{item['source']}"
            state = documents[ref]["state"] if ref in documents else "missing"
            if state == "verified" and latest and item["ref"] in not_found:
                state = "not_found"
            passages.append({"ref": item["ref"], "where": _where(item["ref"], item["location"]),
                             "document": {"ref": ref, "name": read.name(ref), "state": state},
                             "quote": item["quote"] if state == "verified" else None, "state": state})
        change = version["change"]
        if change is not None:
            answers = change["answers_review"]
            absent = review_ids is not None and answers is not None and answers not in ids
            change = {"answers_review": answers, "note": change["note"],
                      "review_note": ABSENT_REVIEW if absent else None}
        shown.append({"version": version["version"], "sha256": version["sha256"],
                      "published_on": version["published_on"], "title": version["title"],
                      "target": dict(version["target"]), "thesis": dict(evidence["thesis"]), "change": change,
                      "passages": passages, "basis_documents": list(documents.values()),
                      "steps": len(version["steps"]), "state": "latest" if latest else "earlier"})
    return shown


def _owned(read: _Read, chain: dict, compared: dict) -> tuple[dict, str | None]:
    """The chain's owner records as served, and None; or, when their history cannot be verified or they fail in any
    other way, the invalid form (no records, a null approval and no parents) and why. Whatever one chain's records
    hold, the read of the other chains and of this chain's evidence goes on."""
    try:
        reviews, readings, problem = _histories(read.folders.records, chain)
        if problem is None:
            latest = chain["versions"][-1]
            approval_id = _approval_id(latest, compared, reviews)
            owned = _Records(read, chain, compared, approval_id)
            shown_reviews, shown_readings = owned.reviews(reviews), owned.readings(readings)
            current = shown_readings[-1] if shown_readings and shown_readings[-1]["state"] == "current" else None
            return {"approval": owned.approval(shown_reviews), "reading": current,
                    "reviews": shown_reviews, "readings": shown_readings,
                    "review_ids": [item["review_id"] for item in reviews],
                    "binding": {"approval_id": approval_id,
                                "parent_review_id": reviews[-1]["review_id"] if reviews else None,
                                "parent_reading_id": readings[-1]["reading_id"] if readings else None}}, None
    except Exception as exc:  # noqa: BLE001 - the records are files on disk: they never break the read
        problem = UNREADABLE.format(error=type(exc).__name__)
    return {"approval": dict(INVALID_APPROVAL), "reading": None, "reviews": [], "readings": [], "review_ids": None,
            "binding": {"approval_id": None, "parent_review_id": None, "parent_reading_id": None}}, problem


def _chain(read: _Read, chain: dict, mechanisms: dict) -> dict:
    latest = chain["versions"][-1]
    evidence = latest["evidence"]
    now, compared = read.compared(latest)
    owned, problem = _owned(read, chain, compared)
    return {
        "id": chain["id"], "title": latest["title"], "latest_version": latest["version"],
        "published_on": latest["published_on"], "state": compared["state"], "reasons": compared["reasons"],
        "event": _event(evidence, compared),
        "items": [{"ref": item["ref"], "kind": item["kind"], "state": item["state"]} for item in compared["items"]],
        "documents": [{"ref": item["ref"], "name": read.name(item["ref"]), "state": item["state"]}
                      for item in compared["documents"]],
        "steps": _steps(read, latest, now, compared, mechanisms[evidence["mechanisms"]["version"]]["entries"]),
        "target": _target(latest, now),
        "measured": {"target_note": TARGET_NOTE.format(kind=latest["target"]["kind"]),
                     "price": read.price(evidence["event"]["when"])},
        "approval": owned["approval"], "reading": owned["reading"],
        "history": {"state": "valid" if problem is None else "invalid", "problem": problem,
                    "versions": _versions(read, chain, owned["review_ids"],
                                          {ref for ref, state in now["quote_states"].items() if state == "not_found"}),
                    "reviews": owned["reviews"], "readings": owned["readings"]},
        "binding": {"chain_sha256": latest["sha256"], **owned["binding"]},
    }


# ---------------------------------------------------------------- the reply and the write binding

def view(folders: Folders) -> dict:
    """{"view_version", "provider_called": False, "thesis": {"id", "latest_version"}, "chains": [chain view]}. Raises
    ChainRefused: 503 when the copper thesis has no published version or cannot be read, 500 for invalid content.
    Reads only."""
    read = _Read(folders)
    mechanisms, chains = _content(folders)
    return {"view_version": VIEW_VERSION, "provider_called": False,
            "thesis": {"id": THESIS, "latest_version": read.version},
            "chains": [_chain(read, chain, mechanisms) for chain in chains.values()]}


def current(folders: Folders, chain_id: str) -> Current:
    """What a write on ``chain_id`` is checked against and binds: its latest version, the basis copied into a record,
    the target, the state and reasons, the current approval (None unless the latest review, on the latest version, is
    approved and the chain is available), the step count, every pinned and live quote of its items and of the target
    element's cited passages, and, for the digit rule, those quotes with what the thesis lets its own author text state
    about the target element (thesis_sections): each served figure's printed and plain value, year and period, and the
    measure's computed change, all of which the card shows. Raises ChainRefused as view does, and 404 for an unknown
    chain. Reads only."""
    read = _Read(folders)
    _mechanisms, chains = _content(folders)
    if chain_id not in chains:
        raise ChainRefused(404, "No event chain has this id")
    latest = chains[chain_id]["versions"][-1]
    evidence = latest["evidence"]
    now, compared = read.compared(latest)
    reviews, _readings, _problem = _histories(folders.records, chains[chain_id])
    quotes = [side["quote"] for item in compared["items"] if item["kind"] == "passage"
              for side in (item["pinned"], item["current"]) if side is not None]
    element = now["target"]["element"] or {}
    statement, measured = element.get("statement"), element.get("measure")
    quotes += [item["quote"] for item in statement["passages"]] if statement else []
    figures = (statement["figures"] if statement else []) + ([measured["latest"], measured["previous"]]
                                                               if measured else [])
    quotes = list(dict.fromkeys(quotes))
    stated = [shown(figure) for figure in figures] + ([element["change_pct"]] if element.get("change_pct") else [])
    return Current(
        id=chain_id, version=latest["version"], sha256=latest["sha256"],
        basis={"chain": {"id": chain_id, "version": latest["version"], "sha256": latest["sha256"]},
               "evidence_sha256": evidence_sha256(evidence), "thesis": dict(evidence["thesis"]),
               "documents": [{"ref": item["ref"], "acquisition": item["acquisition"]}
                             for item in evidence["documents"]]},
        target=dict(latest["target"]), state=compared["state"], reasons=list(compared["reasons"]),
        approval_id=_approval_id(latest, compared, reviews), steps=len(latest["steps"]), quotes=quotes,
        allowed=" ".join(quotes + stated))

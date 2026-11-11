"""The copper research view (copper-research-view-0.1), and the subject a note is saved on (subject).

One read serves the copper desk, the publication comparisons and the owner's research notes:

- desk.pages: the five existing copper pages, each with what it is and one status line taken from the view that page
  already serves (the thesis's published version, the FCX documents, the event chains' review states). A line that
  cannot be read is null with a fixed problem; the other lines are still served.
- comparisons: each comparison's latest version against the live research files (publication_comparison). A row shows
  its two lines side by side in the source's words, with document, place and state; a line is withheld whole while its
  document does not verify or its record changed, and the assistant's note on a row, which says what each line
  states, is withheld with it. The fixed sentence of a row says whether the two lines are the same measure. No change
  is computed between two lines (the owner's clarification of 2026-11-10). Beside the rows, the retained price
  figures: FCX's
  realized-price records as company_research_view.resolved() serves them now, and the last two years of the USGS
  annual series (event_chain_price.series), each with the period it covers, then the last covered day and that no
  retained price covers a later date.
- subjects: what a note can be about now (the thesis, each chain, each comparison), with the version and SHA-256 a
  save binds and the state that decides whether a save is accepted.
- notes: the saved notes, oldest first, each with its state now (current, or earlier_basis with what differs), its
  basis documents verified through their pinned acquisitions, and its figures masked while one of them does not
  verify (step references in a chain note are exempt, by the step count of the version the note names, served as
  `steps`; 0 for other subjects). A note on a
  comparison saved on or after the later publication's date says that it was written after both were known. An
  expectation reads "not yet checked": nothing here settles one. A history that cannot be verified is shown as
  invalid, with no notes, and the rest of the read goes on.

Invalid content, or a thesis that cannot be read, refuses the whole read (ChainRefused). Reads only: nothing here
writes, fetches or calls a model.
"""
from datetime import timezone
from pathlib import Path

from . import (company_research_view, event_chain_evidence as evidence, event_chain_price, event_chain_text,
               event_chain_view, metals_view, publication_comparison as comparison, research_notes, thesis_schema)
from .bis_snapshot import canonical
from .copper_linked import PACKAGE_ERRORS
from .event_chain_records import RecordRefused
from .event_chain_schema import THESIS, ChainRefused
from .thesis_rules import ThesisRefused

VIEW_VERSION = "copper-research-view-0.1"
PAGES = (
    ("thesis", "Copper thesis", "/theses/copper", "The physical balance, its reasons and risks, with their sources."),
    ("tools", "Copper tools", "/theses/copper/tools", "The coverage calculator and the producer comparison."),
    ("fcx", "FCX company page", "/companies/fcx", "How the copper price reaches Freeport-McMoRan's cash flow."),
    ("metals", "Metals comparison", "/metals", "Production, reserves and their concentration, metal by metal."),
    ("events", "Event chains", "/theses/copper/events",
     "Past events, the sources' own words, and your reviews and readings."),
)
NO_LINE = "This page's line could not be read on this machine."
# A chain's review state (None: its records cannot be verified) and how the desk counts it, with no verb to agree.
CHAIN_REVIEWS = (("approved", "approved"), ("approved_earlier_basis", "approved on an earlier basis"),
                 ("needs_revision", "with a revision asked"), ("awaiting_review", "awaiting your review"),
                 (None, "with records that cannot be verified"))
HISTORICAL = "Historical: both publications were already retained when this comparison was prepared."
SAME_MEASURE = {
    "not_applicable": "Two statements, each shown as written.",
    "not_established": "No retained source establishes that the two lines measure the same thing. No change is "
                       "computed between them.",
    "no": "The two lines are not the same measure. No change is computed between them.",
}
SIDE_PROBLEMS = {"changed": "Withheld: the record's wording or place changed since it was pinned",
                 "gone": "Withheld: no record holds this passage any more",
                 "unreadable": "Withheld: the FCX research cannot be read"}
NOT_CHECKED = "Not yet checked: nothing retained after this note was saved has been compared with it."
PASSED = " Its check-by date has passed."
HINDSIGHT = "Written after both publications were known: saved on {saved}, the later publication is dated {later}."
PRICES_TO = "Retained prices cover up to {day}. No retained price covers a later date."
NO_PRICES = "No retained price can be shown on this machine."
NO_RECORD = "Not shown: the FCX research holds no such price record"
NO_RESEARCH = "Not shown: the FCX research cannot be read"
OTHER_DOCUMENT = "Not shown: the record is not from one of the two publications"
NOT_DATED = "Not shown: the record names no dated period"
MASK_REASON = event_chain_view.MASK_REASON
NEWER = "The {kind} has a newer version ({latest}) than version {version}, which this note was saved on"
GONE = "The {kind} {ident} is no longer published"
NOUN = {"comparison": "comparison", "chain": "chain", "thesis": "thesis"}


def _published_thesis(folders: evidence.Folders) -> tuple[dict, dict]:
    """(the index entry of the latest published thesis version, that version's file). Raises ChainRefused(503)."""
    try:
        published = evidence.latest_published(folders.theses)
        if published is None:
            raise ChainRefused(503, f"The {THESIS} thesis has no published version; the copper research is not served")
        return published, thesis_schema.load_version(THESIS, published["version"], folders.theses)
    except ThesisRefused as exc:
        raise ChainRefused(503, f"The {THESIS} thesis cannot be read ({exc}); the copper research is not served") \
            from None


def _thesis_documents(thesis: dict) -> list[dict]:
    return [{"ref": f"copper:{item['id']}", "acquisition": evidence._acquisition(item, "copper")}
            for item in thesis["sources"]]


def _document_state(documents: list[dict]) -> tuple[str, list[str]]:
    """(available | needs_revalidation | unavailable, every reason) from verified pinned documents."""
    reasons = {"unavailable": [], "needs_revalidation": []}
    for item in documents:
        if item["state"] != "verified":
            group = "unavailable" if item["state"] in ("missing", "unreadable") else "needs_revalidation"
            reasons[group].append(evidence.DOCUMENT_REASONS[item["state"]].format(ref=item["ref"]))
    state = "unavailable" if reasons["unavailable"] else "needs_revalidation" if reasons["needs_revalidation"] \
        else "available"
    return state, reasons["unavailable"] + reasons["needs_revalidation"]


class _Read:
    """What one read computes once."""

    def __init__(self, folders: evidence.Folders):
        self.folders = folders
        self.published, self.thesis = _published_thesis(folders)
        self.chains = event_chain_view.view(folders)["chains"]
        self.comparisons = comparison.load_comparisons(comparison.comparisons_dir(folders.theses))
        self.names = {f"copper:{item['id']}": item["title"] for item in self.thesis["sources"]}
        try:  # The price series' file is a metals source; it is named as that sources file names it.
            for item in metals_view.load_sources(folders.metals):
                self.names.setdefault(f"copper:{item['id']}", item["title"])
        except (ThesisRefused, KeyError, TypeError):
            pass
        try:
            self.sources, self.records, _ = company_research_view.resolved(folders.research, folders.company_sources)
            self.names.update({f"fcx:{key}": f"the FCX {item['form']}" for key, item in self.sources.items()})
        except (company_research_view.CompanyRefused, *PACKAGE_ERRORS):
            self.sources, self.records = None, None
        self._verified: dict[str, dict] = {}
        self._compared: dict[str, tuple[dict, dict]] = {}
        self._series: dict | None = None

    def name(self, ref: str) -> str:
        return self.names.get(ref, ref)

    def verified(self, document: dict) -> dict:
        """{"ref", "name", "state", "detail"}: verify_pinned through the pinned acquisition, once per read."""
        key = canonical(document)
        if key not in self._verified:
            self._verified[key] = evidence.verify_pinned(document, self.folders)
        return {"ref": document["ref"], "name": self.name(document["ref"]), **self._verified[key]}

    def compared(self, ident: str) -> tuple[dict, dict]:
        if ident not in self._compared:
            latest = self.comparisons[ident]["versions"][-1]
            self._compared[ident] = (latest, comparison.compare(latest["evidence"],
                                                                comparison.live(latest, self.folders)))
        return self._compared[ident]

    # ------------------------------------------------------------ the desk

    def _status(self, ident: str) -> str | None:
        if ident == "thesis":
            return f"Version {self.published['version']}, published {self.published['published_on']}."
        if ident == "fcx":
            if self.sources is None:
                raise ValueError(NO_LINE)
            held = sum(item["state"] == "verified" for item in self.sources.values())
            latest = max(item["date"] for item in self.sources.values())
            return f"{len(self.sources)} documents, {held} verified on this machine; the latest is dated {latest}."
        if ident == "events":
            states = [item["approval"]["state"] for item in self.chains]
            parts = [f"{states.count(state)} {words}" for state, words in CHAIN_REVIEWS if states.count(state)]
            closed = sum(item["state"] != "available" for item in self.chains)
            count = len(self.chains)
            text = f"{count} {'chain' if count == 1 else 'chains'}" + (f": {', '.join(parts)}." if parts else ".")
            return text + (f" {closed} not available now." if closed else "")
        return None

    def pages(self) -> list[dict]:
        shown = []
        for ident, title, path, what in PAGES:
            try:
                status, problem = self._status(ident), None
            except (KeyError, ValueError, TypeError):
                status, problem = None, NO_LINE
            shown.append({"id": ident, "title": title, "path": path, "what": what, "status": status,
                          "problem": problem})
        return shown

    # ------------------------------------------------------------ a comparison

    def _side(self, ref: str, item: dict, documents: dict[str, str]) -> dict:
        pinned = item["pinned"]
        document = f"fcx:{pinned['source']}"
        state = documents.get(document, "missing")
        side = {"ref": ref, "quote": None, "where": event_chain_view._where(ref, pinned["location"]),
                "document": {"ref": document, "name": self.name(document), "state": state}, "state": state,
                "problem": None}
        if state != "verified":
            side["problem"] = event_chain_view.WITHHELD[state].format(name=self.name(document))
        elif item["state"] != "same":
            side.update(state=f"record_{item['state']}", problem=SIDE_PROBLEMS[item["state"]])
        else:
            side["quote"] = pinned["quote"]
        return side

    def _prices(self, version: dict) -> dict:
        figures = []
        named = {version[side]["document"] for side in comparison.SIDES}
        for ident in version["prices"]:
            record = (self.records or {}).get(ident)
            shown = {"id": ident, "label": None, "period": None, "display": None, "unit": None, "source": None,
                     "state": "withheld", "problem": NO_RESEARCH if self.records is None else NO_RECORD}
            if record is not None and record.get("kind") == "published":
                source = f"fcx:{record['rests_on'][0]}"
                shown.update(label=record.get("metric"), unit=record.get("unit"),
                             source={"ref": source, "name": self.name(source)}, problem=record.get("problem"))
                if source not in named:  # A note's basis pins the two publications only.
                    shown["problem"] = OTHER_DOCUMENT
                elif record["state"] == "available" and comparison.dated_figure(record):
                    shown.update(state="available", display=record["display"], problem=None,
                                 period={key: record["period"][key] for key in ("label", "start", "end")})
                elif record["state"] == "available":
                    shown["problem"] = NOT_DATED
            figures.append(shown)
        if self._series is None:
            self._series = event_chain_price.series(self.folders)
        source = f"copper:{event_chain_price.SERIES['source']}"
        base = {"label": event_chain_price.SERIES["label"], "unit": event_chain_price.SERIES["unit"],
                "source": {"ref": source, "name": self.name(source)}}
        rows = self._series["rows"]
        if rows is None:
            figures.append({"id": "usgs-annual", **base, "period": None, "display": None, "state": "withheld",
                            "problem": f"Not shown: {self._series['problem']}"})
        else:
            for year in sorted(rows)[-2:]:
                estimate = " (estimate)" if rows[year][1] == event_chain_price.ESTIMATED else ""
                figures.append({"id": f"usgs-annual-{year}", **base, "display": str(rows[year][0]),
                                "period": {"label": f"{year}{estimate}", "start": f"{year}-01-01",
                                           "end": f"{year}-12-31"}, "state": "available", "problem": None})
        ends = [item["period"]["end"] for item in figures if item["state"] == "available"]
        covered = max(ends) if ends else None
        return {"figures": figures, "covered_to": covered,
                "text": PRICES_TO.format(day=covered) if covered else NO_PRICES}

    def comparison(self, ident: str) -> dict:
        latest, compared = self.compared(ident)
        items = {(item["kind"], item["ref"]): item for item in compared["items"]}
        documents = {item["ref"]: item["state"] for item in compared["documents"]}
        publications = {}
        for side, pinned in zip(comparison.SIDES, latest["evidence"]["publications"], strict=True):
            publications[side] = {"ref": pinned["ref"], "name": self.name(pinned["ref"]), "title": pinned["title"],
                                  "form": pinned["form"], "dated": pinned["date"],
                                  "dated_as": pinned["date_kind"].split(" (")[0],
                                  "state": documents.get(pinned["ref"], "missing"),
                                  "record": items["publication", pinned["ref"]]["state"]}
        rows = []
        for row in latest["rows"]:
            sides = {side: self._side(row[side], items["passage", row[side]], documents) for side in comparison.SIDES}
            shown = all(side["state"] == "verified" for side in sides.values())
            held = row["note"] is not None and not shown  # The note says what a line states: withheld with it.
            rows.append({"id": row["id"], "label": row["label"], "same_measure": row["same_measure"],
                         "sentence": SAME_MEASURE[row["same_measure"]], "note": None if held else row["note"],
                         "note_withheld": held, **sides})
        return {"id": ident, "title": latest["title"], "latest_version": latest["version"],
                "published_on": latest["published_on"], "sha256": latest["sha256"],
                "historical": latest["historical"], "historical_note": HISTORICAL if latest["historical"] else None,
                "prepared_by": latest["provenance"]["prepared_by"],
                "ai_assisted": latest["provenance"]["ai_assisted"], "state": compared["state"],
                "reasons": compared["reasons"], **publications, "rows": rows, "prices": self._prices(latest),
                "documents": [{"ref": item["ref"], "name": self.name(item["ref"]), "state": item["state"]}
                              for item in compared["documents"]]}

    # ------------------------------------------------------------ subjects

    def subjects(self) -> list[dict]:
        state, reasons = _document_state([self.verified(item) for item in _thesis_documents(self.thesis)])
        found = [{"kind": "thesis", "id": THESIS, "title": self.thesis["title"], "version": self.published["version"],
                  "sha256": self.published["sha256"], "state": state, "reasons": reasons}]
        found += [{"kind": "chain", "id": item["id"], "title": item["title"], "version": item["latest_version"],
                   "sha256": item["binding"]["chain_sha256"], "state": item["state"], "reasons": item["reasons"]}
                  for item in self.chains]
        for ident in self.comparisons:
            latest, compared = self.compared(ident)
            found.append({"kind": "comparison", "id": ident, "title": latest["title"], "version": latest["version"],
                          "sha256": latest["sha256"], "state": compared["state"], "reasons": compared["reasons"]})
        return found

    # ------------------------------------------------------------ the notes

    def _steps(self, about: dict, version: int) -> int:
        if about["kind"] != "chain":
            return 0
        chain = next((item for item in self.chains if item["id"] == about["id"]), None)
        versions = chain["history"]["versions"] if chain else []
        return versions[version - 1]["steps"] if 1 <= version <= len(versions) else 0

    def _hindsight(self, record: dict) -> str | None:
        about, named = record["about"], record["basis"][record["about"]["kind"]]
        versions = self.comparisons.get(about["id"], {}).get("versions", []) if about["kind"] == "comparison" else []
        version = versions[named["version"] - 1] if 1 <= named["version"] <= len(versions) else None
        if version is None or version["sha256"] != named["sha256"]:
            return None
        later, saved = version["evidence"]["publications"][1]["date"], record["saved_at"][:10]
        return HINDSIGHT.format(saved=saved, later=later) if saved >= later else None

    def _note(self, record: dict, followed_by: str | None, subjects: dict, today: str) -> dict:
        about, basis = record["about"], record["basis"]
        kind = about["kind"]
        named = basis[kind]
        documents = [self.verified(item) for item in basis["documents"]]
        failing = [item["ref"] for item in documents if item["state"] != "verified"]
        steps = self._steps(about, named["version"])

        def shown(text: str | None) -> str | None:
            return event_chain_text.masked(text, steps) if text is not None and failing else text

        now = subjects.get((kind, about["id"]))
        if now is None:
            differs = [GONE.format(kind=NOUN[kind], ident=about["id"])]
        elif named["sha256"] != now["sha256"]:
            differs = [NEWER.format(kind=NOUN[kind], latest=now["version"], version=named["version"])]
        else:
            differs = list(now["reasons"])
        expectation = record["expectation"]
        if expectation is not None:
            passed = expectation["check_by"] is not None and expectation["check_by"] < today
            expectation = {"text": shown(expectation["text"]), "check_by": expectation["check_by"],
                           "state": "not_yet_checked", "status": NOT_CHECKED + (PASSED if passed else "")}
        return {"note_id": record["note_id"], "parent_note_id": record["parent_note_id"],
                "sequence": record["sequence"], "about": about, "subject_title": now["title"] if now else None,
                "follows": record["follows"], "followed_by": followed_by, "text": shown(record["text"]),
                "expectation": expectation, "question": shown(record["question"]), "account": record["account"],
                "saved_at": record["saved_at"],
                "basis": {key: value for key, value in basis.items() if key != "documents"},
                "basis_documents": documents, "masked": bool(failing), "steps": steps,
                "mask_reason": MASK_REASON.format(refs=", ".join(failing)) if failing else None,
                "state": "earlier_basis" if differs else "current", "differs": differs,
                "hindsight": self._hindsight(record)}

    def notes(self, folder: Path, subjects: list[dict], today: str) -> dict:
        try:
            saved = research_notes.history(folder)
        except RecordRefused as exc:
            return {"state": "invalid", "problem": exc.message, "latest": None, "items": []}
        except OSError as exc:
            return {"state": "invalid", "problem": f"The saved notes could not be read ({type(exc).__name__})",
                    "latest": None, "items": []}
        followed = {item["follows"]: item["note_id"] for item in saved if item["follows"] is not None}
        by_subject = {(item["kind"], item["id"]): item for item in subjects}
        return {"state": "valid", "problem": None, "latest": saved[-1]["note_id"] if saved else None,
                "items": [self._note(item, followed.get(item["note_id"]), by_subject, today) for item in saved]}


# ---------------------------------------------------------------- the reply and the write binding

def view(folders: evidence.Folders, notes: Path, clock) -> dict:
    """{"view_version", "provider_called": False, "desk": {"pages"}, "comparisons", "subjects", "notes"} (see the
    module docstring). Raises ChainRefused: 503 when the copper thesis has no published version or cannot be read, 500
    for invalid content. Reads only."""
    read = _Read(folders)
    subjects = read.subjects()
    today = clock().astimezone(timezone.utc).date().isoformat()
    return {"view_version": VIEW_VERSION, "provider_called": False, "desk": {"pages": read.pages()},
            "comparisons": [read.comparison(ident) for ident in read.comparisons], "subjects": subjects,
            "notes": read.notes(notes, subjects, today)}


def subject(folders: evidence.Folders, kind: str, ident: str) -> research_notes.Subject:
    """What a note about (kind, ident) is checked against and binds now: the subject's version SHA-256, the basis
    copied into the record (its version, its evidence digest and each document's pinned acquisition), its state and
    reasons, and every quote the overlap rule compares the owner's text with. Raises ChainRefused: 404 for an unknown
    subject, and as view does. Reads only."""
    if kind == "chain":
        current = event_chain_view.current(folders, ident)
        return research_notes.Subject(kind=kind, id=ident, sha256=current["sha256"], basis=current["basis"],
                                      state=current["state"], reasons=current["reasons"], quotes=current["quotes"])
    if kind == "comparison":
        held = comparison.load_comparisons(comparison.comparisons_dir(folders.theses))
        if ident not in held:
            raise ChainRefused(404, "No comparison has this id")
        latest = held[ident]["versions"][-1]
        now = comparison.live(latest, folders)
        compared = comparison.compare(latest["evidence"], now)
        quotes = [item["quote"] for item in latest["evidence"]["passages"]]
        quotes += [item["quote"] for item in now["passages"].values() if item is not None]
        # And every recorded passage of the two publications, cited by a row or not: a note quotes none of them.
        named = {item["ref"].split(":", 1)[1] for item in latest["evidence"]["publications"]}
        recorded, _entries = evidence._fcx(folders.research)
        quotes += [item["quote"] for item in (recorded or {}).values() if item["source"] in named]
        basis = {"comparison": {"id": ident, "version": latest["version"], "sha256": latest["sha256"]},
                 "evidence_sha256": evidence.evidence_sha256(latest["evidence"]),
                 "documents": latest["evidence"]["documents"]}
        return research_notes.Subject(kind=kind, id=ident, sha256=latest["sha256"], basis=basis,
                                      state=compared["state"], reasons=compared["reasons"],
                                      quotes=list(dict.fromkeys(quotes)))
    if kind != "thesis" or ident != THESIS:
        raise ChainRefused(404, "No such subject")
    published, thesis = _published_thesis(folders)
    documents = _thesis_documents(thesis)
    state, reasons = _document_state([{"ref": item["ref"], **evidence.verify_pinned(item, folders)}
                                      for item in documents])
    basis = {"thesis": {"id": THESIS, "version": published["version"], "sha256": published["sha256"]},
             "documents": documents}
    return research_notes.Subject(kind=kind, id=ident, sha256=published["sha256"], basis=basis, state=state,
                                  reasons=reasons, quotes=[item["locator"]["quote"] for item in thesis["passages"]])

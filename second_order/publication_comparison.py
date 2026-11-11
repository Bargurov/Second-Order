"""Comparisons of two retained publications (publication-comparison-0.1): strict loading, the pinned evidence and its
comparison with the live records.

Content only, written by the assistant: content/theses/copper/comparisons/<comparison id>/ (index.json plus v<n>.json,
indexed as the event chains are). A version names an earlier and a later retained FCX document and holds rows. A row
pairs one passage of the earlier document with one of the later under a short label. It says whether the two lines are
the same measure (not_applicable for two statements with nothing to measure, not_established, or no) and, unless that
does not apply, carries the assistant's short note on what each line measures and when.

No row holds or computes a change. Comparing numbers needs matching units and a matching basis of measurement (the
owner's clarification of 2026-11-10), so two lines are shown with their own wording, places and dates, and an
arithmetic fall or rise between them is never derived: a row has no field for one.

A version pins what it rests on (evidence): the two publications as the research lists them {ref, title, form, date,
date_kind}, each cited passage once {ref, source, location, quote}, and each document's acquisition record. live()
projects the same items from the raw research files; compare() reads each pinned item as same, changed, gone or
unreadable and each document as verified, changed, missing, superseded or unreadable, with the event-chain evidence
code. The state is the first of unavailable, needs_revalidation and evidence_changed that applies, else available.
The assistant's text keeps the claim-word and price-direction rules; a label holds no figure, and a title or a note
holds only figures of the publications' titles or of the row's two quotes. Reads only: nothing here writes, fetches or
calls a model.
"""
from pathlib import Path
import re

from . import company_research_view, event_chain_evidence as evidence, event_chain_schema as schema
from .event_chain_schema import ChainRefused
from .event_chain_text import figure_runs, overlap

COMPARISON_VERSION = "publication-comparison-0.1"
INDEX_VERSION = "publication-comparison-index-0.1"
REF = re.compile(r"fcx:[a-z0-9]+(?:-[a-z0-9]+)*")
SAME_MEASURE = ("not_applicable", "not_established", "no")
SIDES = ("earlier", "later")
FIELDS = {"comparison_version", "id", "version", "previous_version", "title", "earlier", "later", "historical", "rows",
          "prices", "evidence", "change", "provenance"}
ROW_FIELDS = {"id", "label", "earlier", "later", "same_measure", "note"}
PUBLICATION_FIELDS = ("ref", "title", "form", "date", "date_kind")
MAX_ROWS, MAX_ROW_NOTE, MAX_PRICES = 12, 300, 12
STATES = ("unavailable", "needs_revalidation", "evidence_changed")
ITEM_REASONS = {
    **evidence.ITEM_REASONS,
    ("publication", "changed"): "The publication {ref} differs from its pinned title, form or date",
    ("publication", "gone"): "The FCX research no longer lists the publication {ref}",
}
DIGITS = re.compile(r"\d+")
# The assistant's own words on a comparison never state a change between two lines either: no arrow and no word of a
# rise or a fall. "up" and "down" count only as words of their own, so a name such as "ramp-up" passes.
ARROW = re.compile(r"→|⟶|->")
CHANGE = re.compile(
    r"\b(?:fell|falls?|fallen|falling|rose|rises?|risen|rising|drop(?:s|ped|ping)?|declin\w*|decreas\w*|increas\w*|"
    r"lower(?:ed|s|ing)?|higher|cuts?|cutting|reduc\w*|shr[aiu]nk\w*|grew|grow(?:s|n|ing)?|slip(?:s|ped|ping)?|"
    r"gain(?:s|ed|ing)?|points?)\b|(?<![\w-])(?:up|down)(?![\w-])", re.I)


def _no_change(text: str, where: str) -> None:
    found = ARROW.search(text) or CHANGE.search(text)
    schema._check(found is None, where, f"states a change between the two lines ({found.group(0)!r}); a comparison "
                                        "shows each line as written" if found else "")


def dated_figure(record: dict) -> bool:
    """Whether a research record can stand beside a comparison as a price: it names its measure, and its period has
    a label and a first and a last day (real dates, in order), which is what the page's reader requires of one."""
    period = record.get("period")
    if not (isinstance(record.get("metric"), str) and record["metric"] and isinstance(period, dict)
            and isinstance(period.get("label"), str) and period["label"]):
        return False
    try:
        for key in ("start", "end"):
            schema._day(period.get(key), key)
    except ChainRefused:
        return False
    return period["start"] <= period["end"]


def comparisons_dir(theses: Path) -> Path:
    return Path(theses) / schema.THESIS / "comparisons"


def _fcx_ref(value: object, where: str) -> str:
    schema._check(isinstance(value, str) and bool(REF.fullmatch(value)), where, "expected an fcx: reference")
    return value


def cited(version: dict) -> list[str]:
    """The rows' passage references, each once, in row order (a row's earlier line before its later one)."""
    return list(dict.fromkeys(row[side] for row in version["rows"] for side in SIDES))


# ---------------------------------------------------------------- the pinned evidence

def _evidence(value: object, where: str, version: dict) -> dict[str, str]:
    """Check the evidence shape against the version; returns the pinned quotes by passage reference."""
    schema._object(value, where, {"publications", "passages", "documents"})
    named = [version[side]["document"] for side in SIDES]
    schema._check(isinstance(value["publications"], list) and len(value["publications"]) == 2,
                  f"{where}.publications", "expected the earlier and the later publication")
    for number, item in enumerate(value["publications"]):
        at = f"{where}.publications[{number}]"
        schema._object(item, at, PUBLICATION_FIELDS)
        schema._check(item["ref"] == named[number], f"{at}.ref", f"expected {named[number]}")
        for key in ("title", "form", "date_kind"):
            schema._line(item[key], f"{at}.{key}")
        schema._day(item["date"], f"{at}.date")
    schema._check(isinstance(value["passages"], list), f"{where}.passages", "expected a list")
    quotes, sources, order = {}, {}, []
    for number, item in enumerate(value["passages"]):
        at = f"{where}.passages[{number}]"
        schema._object(item, at, {"ref", "source", "location", "quote"})
        order.append(_fcx_ref(item["ref"], f"{at}.ref"))
        sources[item["ref"]] = schema._ident(item["source"], f"{at}.source")
        schema._check(isinstance(item["location"], dict) and bool(item["location"]), f"{at}.location",
                      "expected an object")
        quotes[item["ref"]] = schema._line(item["quote"], f"{at}.quote")
    schema._check(order == cited(version), f"{where}.passages", "expected exactly the rows' passages, in row order")
    for number, row in enumerate(version["rows"]):
        for side in SIDES:
            schema._check(f"fcx:{sources[row[side]]}" == version[side]["document"], f"rows[{number}].{side}",
                          f"is not a passage of the {side} publication")
    schema._check(isinstance(value["documents"], list), f"{where}.documents", "expected a list")
    refs = []
    for number, item in enumerate(value["documents"]):
        at = f"{where}.documents[{number}]"
        schema._object(item, at, {"ref", "acquisition"})
        refs.append(_fcx_ref(item["ref"], f"{at}.ref"))
        schema._acquisition(item["acquisition"], f"{at}.acquisition", "fcx")
    schema._check(refs == sorted(set(named)), f"{where}.documents", "expected the two publications' documents, sorted")
    return quotes


# ---------------------------------------------------------------- a comparison version

def _rows(value: object, where: str) -> None:
    schema._check(isinstance(value, list) and 1 <= len(value) <= MAX_ROWS, where,
                  f"expected a list of 1 to {MAX_ROWS} rows")
    seen = set()
    for number, row in enumerate(value):
        at = f"{where}[{number}]"
        schema._object(row, at, ROW_FIELDS)
        schema._ident(row["id"], f"{at}.id")
        schema._check(row["id"] not in seen, f"{at}.id", "repeats an earlier row")
        seen.add(row["id"])
        _no_change(schema._owned_text(row["label"], f"{at}.label", schema.MAX_LABEL), f"{at}.label")
        for side in SIDES:
            _fcx_ref(row[side], f"{at}.{side}")
        schema._check(row["earlier"] != row["later"], f"{at}.later", "is the row's earlier passage")
        schema._check(row["same_measure"] in SAME_MEASURE, f"{at}.same_measure",
                      f"expected one of {', '.join(SAME_MEASURE)}")
        if row["note"] is None:
            schema._check(row["same_measure"] == "not_applicable", f"{at}.note",
                          "expected the assistant's note on what each line measures and when")
        else:
            _no_change(schema._owned_text(row["note"], f"{at}.note", MAX_ROW_NOTE, figures=True), f"{at}.note")


def _held_to(text: str, allowed: list[str], where: str, what: str) -> None:
    extra = figure_runs(text, 0) - set(DIGITS.findall(" ".join(allowed)))
    schema._check(not extra, where, f"holds figures its {what} do not: {sorted(extra)}")


def _check_version(raw: object, comparison_id: str, number: int, where: str) -> dict:
    schema._object(raw, where, FIELDS)
    schema._check(raw["comparison_version"] == COMPARISON_VERSION, f"{where}.comparison_version",
                  f"expected {COMPARISON_VERSION}")
    schema._check(raw["id"] == comparison_id, f"{where}.id", f"expected {comparison_id}")
    schema._check(raw["version"] == number and type(raw["version"]) is int, f"{where}.version", f"expected {number}")
    schema._check(raw["previous_version"] == (number - 1 or None)
                  and type(raw["previous_version"]) in (int, type(None)), f"{where}.previous_version",
                  f"expected {number - 1 or None}")
    _no_change(schema._owned_text(raw["title"], f"{where}.title", schema.MAX_TITLE, figures=True), f"{where}.title")
    for side in SIDES:
        schema._object(raw[side], f"{where}.{side}", {"document"})
        _fcx_ref(raw[side]["document"], f"{where}.{side}.document")
    schema._check(raw["earlier"]["document"] != raw["later"]["document"], f"{where}.later.document",
                  "is the earlier publication")
    schema._check(type(raw["historical"]) is bool, f"{where}.historical", "expected true or false")
    _rows(raw["rows"], f"{where}.rows")
    schema._check(isinstance(raw["prices"], list) and len(raw["prices"]) <= MAX_PRICES
                  and len(set(map(str, raw["prices"]))) == len(raw["prices"]), f"{where}.prices",
                  f"expected a list of at most {MAX_PRICES} record ids, each once")
    for at, record in enumerate(raw["prices"]):
        schema._ident(record, f"{where}.prices[{at}]")
    if number == 1:
        schema._check(raw["change"] is None, f"{where}.change", "expected null in version 1")
    else:
        schema._object(raw["change"], f"{where}.change", {"note"})
        schema._owned_text(raw["change"]["note"], f"{where}.change.note", schema.MAX_NOTE)
    provenance = schema._object(raw["provenance"], f"{where}.provenance",
                                {"prepared_by", "ai_assisted", "research_use"})
    schema._line(provenance["prepared_by"], f"{where}.provenance.prepared_by")
    schema._check(provenance["ai_assisted"] is True, f"{where}.provenance.ai_assisted", "expected true")
    schema._check(provenance["research_use"] == "excluded", f"{where}.provenance.research_use", 'expected "excluded"')
    quotes = _evidence(raw["evidence"], f"{where}.evidence", raw)
    _held_to(raw["title"], [item["title"] for item in raw["evidence"]["publications"]], f"{where}.title",
             "publications' titles")
    for at, row in enumerate(raw["rows"]):
        pair = [quotes[row["earlier"]], quotes[row["later"]]]
        for key in ("label", "note"):
            if row[key] is None:
                continue
            _held_to(row[key], pair, f"{where}.rows[{at}].{key}", "quotes")
            run = overlap(row[key], pair)
            schema._check(run is None, f"{where}.rows[{at}].{key}", f"repeats six words of a quote: {run!r}")
    return raw


def load_comparisons(folder: Path) -> dict[str, dict]:
    """comparison id -> {"id", "versions": [version + "sha256" + "published_on", ...]}, every file strictly checked.
    Raises ChainRefused(500, "<place>: <rule>") for any invalid file; an absent folder holds no comparison."""
    folder = Path(folder)
    found = {}
    if not folder.is_dir():
        return found
    for sub in sorted(path for path in folder.iterdir() if path.is_dir()):
        comparison_id = sub.name
        what = f"comparisons/{comparison_id}"
        schema._ident(comparison_id, what)
        index = schema._index(sub, INDEX_VERSION, comparison_id, what)
        versions = []
        for entry in index["versions"]:
            loaded = _check_version(schema._version_file(sub, entry, what), comparison_id, entry["version"],
                                    f"{what}/{entry['file']}")
            versions.append(dict(loaded, sha256=entry["sha256"], published_on=entry["published_on"]))
        found[comparison_id] = {"id": comparison_id, "versions": versions}
    return found


# ---------------------------------------------------------------- live records, the pin and the comparison

def live(version: dict, folders: evidence.Folders) -> dict:
    """The live projections of the version's publications and passages, and its documents' live acquisitions and
    states (those of the live records and those its evidence pins, if any). Reads only."""
    held, entries = evidence._fcx(folders.research)
    readable = held is not None and entries is not None
    passages = {}
    for ref in cited(version):
        ident = ref.split(":", 1)[1]
        passages[ref] = evidence.project_fcx(held[ident]) if readable and ident in held else None
    publications = {}
    for side in SIDES:
        ref = version[side]["document"]
        entry = (entries or {}).get(ref.split(":", 1)[1])
        publications[ref] = {"ref": ref, **{key: entry[key] for key in PUBLICATION_FIELDS[1:]}} if entry else None
    named = [f"fcx:{item['source']}" for item in passages.values() if item is not None] + list(publications)
    named += [item["ref"] for item in (version.get("evidence") or {}).get("documents", [])]
    documents = {ref: evidence._document(ref, {}, entries, readable, folders) for ref in sorted(set(named))}
    quote_states = {}
    for ref, item in passages.items():
        quote_states[ref] = "unreadable" if not readable else "gone" if item is None \
            else documents[f"fcx:{item['source']}"]["state"]
    return {"readable": readable, "publications": publications, "passages": passages, "quote_states": quote_states,
            "documents": documents}


def pin(version: dict, folders: evidence.Folders) -> dict:
    """The evidence block for ``version`` (its own evidence, which may be None, is ignored), copied from the raw
    research files. Raises ChainRefused(422) when the research cannot be read, a publication or a cited record is not
    there, or a row's line is not a passage of the publication it is filed under."""
    current = live({**version, "evidence": None}, folders)
    if not current["readable"]:
        raise ChainRefused(422, "research: the FCX research cannot be read")
    for side in SIDES:
        ref = version[side]["document"]
        if current["publications"][ref] is None:
            raise ChainRefused(422, f"{side}: {ref} is not a document of the FCX research")
        if current["documents"][ref]["acquisition"] is None:
            raise ChainRefused(422, f"documents: {ref} has no source entry that can be read now")
    for number, row in enumerate(version["rows"]):
        for side in SIDES:
            item = current["passages"][row[side]]
            if item is None:
                raise ChainRefused(422, f"rows[{number}].{side}: {row[side]} is not a record that can be read now")
            if f"fcx:{item['source']}" != version[side]["document"]:
                raise ChainRefused(422, f"rows[{number}].{side}: {row[side]} is not a passage of the {side} "
                                        "publication")
    named = sorted({version[side]["document"] for side in SIDES})
    try:  # A listed price is a published, dated figure of one of the two publications (which a note's basis pins).
        held = {item.get("id"): item for item in company_research_view._load(folders.research, "facts.json")["records"]
                if isinstance(item, dict)}
    except (company_research_view.CompanyRefused, KeyError, TypeError):
        raise ChainRefused(422, "research: the FCX research cannot be read") from None
    for number, ident in enumerate(version.get("prices", [])):
        record = held.get(ident)
        if not (record and record.get("kind") == "published" and f"fcx:{record.get('source')}" in named
                and dated_figure(record)):
            raise ChainRefused(422, f"prices[{number}]: {ident} is not a published, dated figure of one of the two "
                                    "publications")
    return {"publications": [current["publications"][version[side]["document"]] for side in SIDES],
            "passages": [current["passages"][ref] for ref in cited(version)],
            "documents": [{"ref": ref, "acquisition": current["documents"][ref]["acquisition"]} for ref in named]}


def compare(pinned: dict, current: dict) -> dict:
    """The pinned evidence against live(): {"state", "reasons", "items": [{"ref", "kind": "publication" | "passage",
    "state", "pinned", "current"}], "documents": [{"ref", "state"}]}."""
    found = {name: [] for name in STATES}
    unreadable = not current["readable"]
    items = [evidence._item("publication", item["ref"], item, current["publications"].get(item["ref"]), unreadable)
             for item in pinned["publications"]]
    items += [evidence._item("passage", item["ref"], item, current["passages"].get(item["ref"]), unreadable)
              for item in pinned["passages"]]
    for item in items:
        if item["state"] in ("changed", "gone"):
            found["evidence_changed"].append(ITEM_REASONS[item["kind"], item["state"]].format(ref=item["ref"]))
    documents = []
    for item in pinned["documents"]:
        state = evidence._document_state(item, current["documents"].get(item["ref"]))
        documents.append({"ref": item["ref"], "state": state})
        if state != "verified":
            group = "unavailable" if state in ("missing", "unreadable") else "needs_revalidation"
            found[group].append(evidence.DOCUMENT_REASONS[state].format(ref=item["ref"]))
    state = next((name for name in STATES if found[name]), "available")
    return {"state": state, "reasons": [reason for name in STATES for reason in found[name]], "items": items,
            "documents": documents}

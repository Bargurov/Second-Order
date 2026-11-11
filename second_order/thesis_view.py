"""The committed thesis as served (thesis-view-0.1): one version loaded, every retained source verified on this machine,
every figure and passage located, each element given a state, what is not available withheld, the numbers computed and
everything counted.

Sources. Each source entry is checked against its acquisition record once per read (thesis_sources.verify): verified,
changed or missing. A verified file is read once (thesis_sources.content; a workbook one named sheet at a time, so a
sheet that cannot be read leaves the others usable) and each figure and passage from it is located once
(thesis_sources.locate). A verified file that cannot be read keeps its state; each figure or passage from it has a
problem naming the refusal (ruling R7). A figure or passage that is not found has one problem naming its place only
("not found where cited (sheet Copper, cell E3)"), never the value or quote looked for, which is withheld.

Elements. The view; each balance table, differs entry, reason, risk and condition; each company that moves the thesis
("mover-<n>") and each company the thesis moves ("moved-<n>"), numbered from 1 in file order (ruling R5); and the price
record. An element's items are its figures and passages as {id, source}, each once, in the order its version-file
element names them; its sources are the sorted ids of their sources; not_found lists, sorted, those items that a
verified source does not hold where their locator says (or that cannot be read). The element is unavailable when any
of its sources is missing; it needs revalidation when any is changed or not_found is not empty; otherwise it is
available, and only then are its problems empty. An element that is not available shows its frame only (id, title,
plain note, the table's gap mode, company, side, the reason it moves, the price series, its items), with a title or
series that contains a digit withheld too (ruling R9); every other field (texts, figures, a condition's threshold as
written and as shown, computed values, statuses) is null, and its problems say why.

Numbers. Statuses compare exact Decimals (thesis_arithmetic). Computed values are displayed exactly as thesis_sections
holds author text to them, so a number in the text and the same number in the reply always agree: a balance gap at
the precision of its figures, weeks of demand to one decimal, a change in percent to one decimal, a condition's
threshold at the precision it is written with (threshold; threshold_value is the plain decimal), a cost per unit in
whole dollars and its share of the unit price to one decimal (computed from the whole-dollar cost). All are
ROUND_HALF_EVEN, comma-grouped strings.

Reads only: nothing here writes, fetches or calls a model, and every reply carries "provider_called": false.
"""
from pathlib import Path

from . import thesis_schema, thesis_sources
from .thesis_arithmetic import (balance, change_pct, condition_state, decimal_of, display, per_unit_cost, reason_state,
                                risk_state, share_pct)
from .thesis_rules import DIGITS, ELEMENT_STATES, SOURCE_STATES, STATEMENT_STATUSES
from .thesis_schema import THESES_DIR
from .thesis_sections import places

VIEW_VERSION = "thesis-view-0.1"
VIEW_ID, PRICE_RECORD_ID = "view", "price-record"
NAMING = ("title", "series")  # Frame text withheld from an element that is not available when it contains a digit.

ELEMENT_LABELS = {
    "available": "Checked: every figure and passage it cites was found where cited in retained sources that match "
                 "their acquisition records; a figure or passage transcribed from a PDF is bound to the PDF by its "
                 "SHA-256 only.",
    "needs_revalidation": "Needs revalidation: a source differs from its acquisition record, or a figure or passage is "
                          "not found where it is cited (or its file cannot be read)",
    "unavailable": "Unavailable: a source is not on this machine"}
# A measure's two figures come from two editions of one series or, by ruling R12, from two years of one edition, so the
# state labels name the latest and previous figures, never editions.
REASON_LABELS = {
    "strengthening": "Strengthening: the latest figure differs from the previous one by at least the material "
                     "change, in the direction this reason needs",
    "weakening": "Weakening: the latest figure differs from the previous one by at least the material change, in the "
                 "other direction",
    "unchanged": "Unchanged: the latest figure differs from the previous one by less than the material change"}
RISK_LABELS = {
    "materialising": "Materialising: the latest figure differs from the previous one by at least the material "
                     "change, in the direction in which this risk grows",
    "receding": "Receding: the latest figure differs from the previous one by at least the material change, in the "
                "other direction",
    "unchanged": "Unchanged: the latest figure differs from the previous one by less than the material change",
    "not_tracked": "Not tracked: no retained figure measures this risk"}
CONDITION_LABELS = {
    "happened": "Happened: the figure it names is past the threshold in the stated direction (a figure equal to the "
                "threshold is not past it)",
    "not_happened": "Not happened: the figure it names is not past the threshold in the stated direction (a figure "
                    "equal to the threshold is not past it)"}
SIDE_LABELS = {"producer": "Producer: supplies the metal", "consumer": "Consumer: uses the metal in what it makes"}
UNIT_LABELS = {"kt": "thousand tonnes", "million_t": "million tonnes", "t": "tonnes", "kg": "kilograms",
               "kg_per_unit": "kilograms per unit", "usd_per_tonne": "US dollars per tonne",
               "usd_per_lb": "US dollars per pound", "usd_cents_per_lb": "US cents per pound", "usd": "US dollars",
               "usd_million": "million US dollars", "percent": "percent", "count": "count"}
LABELS = {"statuses": STATEMENT_STATUSES, "source_states": SOURCE_STATES, "element_states": ELEMENT_LABELS,
          "reason_states": REASON_LABELS, "risk_states": RISK_LABELS, "condition_states": CONDITION_LABELS,
          "sides": SIDE_LABELS, "units": UNIT_LABELS}
SOURCE_SHOWN = ("id", "publisher", "title", "edition", "edition_date", "url", "kind", "origin", "terms", "transcription",
                "retrieved_at", "sha256")
# The source fields passages() gives each passage beside its source id.
PASSAGE_SOURCE_SHOWN = ("title", "publisher", "edition", "edition_date")


# ---------------------------------------------------------------- the retained sources, checked on every read

def _unreadable(source: dict, refusal: str) -> str:
    return f"The retained file of {source['id']} matches its acquisition record but cannot be read ({refusal})"


def _located(item: dict, source: dict, held: object) -> list[str]:
    """[] when the item is where its locator says, else one problem naming the place only. locate's own wording
    carries the value or the quote it looked for, which is withheld with the element, so it is not shown."""
    return [f"not found where cited ({_where(item, source['kind'])})"] if thesis_sources.locate(item, source, held) \
        else []


def _problems(source: dict, raw: bytes, items: list[dict]) -> dict[str, list[str]]:
    """{figure or passage id: [] or its one problem} for the figures and passages of one verified source: its file read
    once (a workbook one named sheet at a time, so one refused sheet leaves the others usable) and each item located
    once. A refusal to read the file, or the sheet an item names, is that item's problem (ruling R7); the refusals of
    thesis_sources and thesis_workbook name limits, parts and cells, never a figure's value or a quote."""
    if source["kind"] == "xlsx":  # Only figures come from a workbook (thesis_schema), and each names its sheet.
        held, refused = {}, {}
        for sheet in dict.fromkeys(item["locator"]["sheet"] for item in items):
            try:
                held.update(thesis_sources.content(source, raw, (sheet,)))
            except thesis_sources.Unreadable as exc:
                refused[sheet] = str(exc)
        return {item["id"]: [_unreadable(source, refused[item["locator"]["sheet"]])]
                if item["locator"]["sheet"] in refused else _located(item, source, held) for item in items}
    try:
        held = thesis_sources.content(source, raw)
    except thesis_sources.Unreadable as exc:
        return {item["id"]: [_unreadable(source, str(exc))] for item in items}
    return {item["id"]: _located(item, source, held) for item in items}


def _checked(thesis: dict, sources_root: Path) -> tuple[dict, dict]:
    """({source id: {"state", "detail"}}, {figure or passage id of a verified source: its problems}): each source
    verified once and each of its figures and passages located once."""
    states, problems = {}, {}
    items = [*thesis["figures"], *thesis["passages"]]
    for source in thesis["sources"]:
        state, raw = thesis_sources.verify(source, sources_root)
        states[source["id"]] = state
        if state["state"] == "verified":
            problems.update(_problems(source, raw, [item for item in items if item["source"] == source["id"]]))
    return states, problems


# ---------------------------------------------------------------- the elements

def _where(item: dict, kind: str) -> str:
    locator = item["locator"]
    if kind == "html":
        return f"paragraph {locator['paragraph']}"
    if kind == "pdf":
        return f"page {locator['page']} (transcribed from the PDF)"
    if kind == "xlsx":
        return f"sheet {locator['sheet']}, cell {locator['cell']}"
    return f"row {locator['row']}, column {locator['column']}"


class _Elements:
    """A version's sources, figures and passages, their checks, and the shapes the reply shows them in."""

    def __init__(self, thesis: dict, states: dict, problems: dict):
        self.sources = {source["id"]: source for source in thesis["sources"]}
        self.items = {item["id"]: item for item in [*thesis["figures"], *thesis["passages"]]}
        self.states, self.problems = states, problems

    def is_figure(self, item_id: str) -> bool:
        return "value" in self.items[item_id]

    def value(self, figure_id: str):
        return decimal_of(self.items[figure_id]["value"])

    def figure(self, figure_id: str) -> dict:
        figure = self.items[figure_id]
        kind = self.sources[figure["source"]]["kind"]
        return {"id": figure["id"], "value": figure["value"], "as_shown": figure["as_shown"], "unit": figure["unit"],
                "year": figure["year"], "period": figure["period"], "basis": figure["basis"],
                "scenario": figure["scenario"], "source": figure["source"], "where": _where(figure, kind),
                "measure": figure["measure"], "quote": figure["locator"]["quote"] if kind in ("html", "pdf") else None}

    def passage(self, passage_id: str) -> dict:
        passage = self.items[passage_id]
        return {"id": passage["id"], "source": passage["source"], "quote": passage["locator"]["quote"],
                "where": _where(passage, self.sources[passage["source"]]["kind"])}

    def cited(self, cites: list[str]) -> dict:
        """The cited ids, and the figures and the passages among them, each in citation order."""
        return {"cites": list(cites), "figures": [self.figure(name) for name in cites if self.is_figure(name)],
                "passages": [self.passage(name) for name in cites if not self.is_figure(name)]}

    def statement(self, statement: dict) -> dict:
        return {"status": statement["status"], "text": statement["text"], **self.cited(statement["cites"])}

    def element(self, frame: dict, used: list[str], content: dict) -> dict:
        """One element: its frame, what it was checked against, and its content when it is available (each content
        field null otherwise). ``used`` names every figure and passage it shows."""
        used = list(dict.fromkeys(used))
        sources = sorted({self.items[name]["source"] for name in used})
        found = {self.states[name]["state"] for name in sources}
        problems = [f"{name}: {self.states[name]['detail']}" for name in sources
                    if self.states[name]["state"] != "verified"]
        problems += [f"{name}: {problem}" for name in used for problem in self.problems.get(name, [])]
        not_found = sorted(name for name in used if self.problems.get(name))
        state = "unavailable" if "missing" in found else "needs_revalidation" if problems else "available"
        shown = state == "available"
        frame = dict(frame)
        for key in NAMING:  # A title or series may state the element's figures, which are withheld with it (R9).
            if not shown and key in frame and DIGITS.search(frame[key]):
                frame[key] = None
        return {**frame, "items": [{"id": name, "source": self.items[name]["source"]} for name in used],
                "sources": sources, "state": state, "problems": problems, "not_found": not_found,
                **{key: value if shown else None for key, value in content.items()}}


def _view(e: _Elements, thesis: dict) -> dict:
    statement = thesis["view"]
    return e.element({"id": VIEW_ID}, statement["cites"], {"statement": e.statement(statement)})


def _tables(e: _Elements, thesis: dict) -> list[dict]:
    tables = []
    for table in thesis["balance"]["tables"]:
        used, rows = [], []
        for row in table["rows"]:
            used += [row["demand_total"], row["supply_total"], *(line["figure"] for line in row["lines"])]
            gap = balance(e.value(row["supply_total"]), e.value(row["demand_total"])) \
                if table["gap"] == "computed" else None
            rows.append({"year": row["year"], "kind": row["kind"], "demand_total": e.figure(row["demand_total"]),
                         "supply_total": e.figure(row["supply_total"]),
                         "lines": [{"label": line["label"], "figure": e.figure(line["figure"])} for line in row["lines"]],
                         "gap": display(gap["gap"], places(gap["gap"])) if gap else None,
                         "label": gap["label"] if gap else None,
                         "weeks": display(gap["weeks"], 1) if gap else None})
        tables.append(e.element({"id": table["id"], "title": table["title"], "gap": table["gap"]}, used,
                                {"why_not": table["why_not"], "rows": rows}))
    return tables


def _differs(e: _Elements, thesis: dict) -> list[dict]:
    differs = []
    for item in thesis["differs"]:
        others = [{"cite": other["cite"], "label": other["label"],
                   "figure": e.figure(other["cite"]) if e.is_figure(other["cite"]) else None,
                   "passage": None if e.is_figure(other["cite"]) else e.passage(other["cite"])}
                  for other in item["others"]]
        differs.append(e.element({"id": item["id"]},
                                 [*item["about"]["cites"], *(other["cite"] for other in item["others"])],
                                 {"about": e.statement(item["about"]), "others": others, "differs": item["differs"]}))
    return differs


def _claims(e: _Elements, values: list[dict], direction: str, rule) -> list[dict]:
    """Reasons (``supports_when``, reason_state) or risks (``grows_when``, risk_state; a null measure is not
    tracked): each latest figure against the previous one, from two editions or (ruling R12) two years of one edition,
    which the reply shows by the two figures' sources and ``compare``; moved_by is the latest figure's source."""
    claims = []
    for item in values:
        measure, used = item["measure"], list(item["statement"]["cites"])
        content = {"statement": e.statement(item["statement"]), "measure": None, "status": "not_tracked",
                   "change_pct": None, "moved_by": None}
        if measure is not None:
            used += [measure["latest"], measure["previous"]]
            latest, previous = e.value(measure["latest"]), e.value(measure["previous"])
            source = e.sources[e.items[measure["latest"]]["source"]]
            content.update({
                "measure": {"latest": e.figure(measure["latest"]), "previous": e.figure(measure["previous"]),
                            "compare": measure["compare"], direction: measure[direction],
                            "material_change_pct": measure["material_change_pct"]},
                "status": rule(previous, latest, measure[direction], decimal_of(measure["material_change_pct"])),
                "change_pct": display(change_pct(previous, latest), 1),
                "moved_by": {"source": source["id"], "publisher": source["publisher"], "edition": source["edition"],
                             "edition_date": source["edition_date"]}})
        claims.append(e.element({"id": item["id"], "title": item["title"], "plain": item["plain"]}, used, content))
    return claims


def _conditions(e: _Elements, thesis: dict) -> list[dict]:
    conditions = []
    for item in thesis["conditions"]:
        threshold = decimal_of(item["threshold"])
        # The threshold is withheld with the condition (final review M4, as ruling R9 withholds a figured title): it may
        # be a cited figure's value (in copper v1, the IEA 2035 demand figure both conditions compare with).
        conditions.append(e.element({"id": item["id"]}, [item["figure"]], {
            "threshold_value": item["threshold"], "comparator": item["comparator"], "text": item["text"],
            "figure": e.figure(item["figure"]), "threshold": display(threshold, places(threshold)),
            "status": condition_state(e.value(item["figure"]), item["comparator"], threshold)}))
    return conditions


def _movers(e: _Elements, thesis: dict) -> list[dict]:
    return [e.element({"id": f"mover-{number}", "company": mover["company"], "moves": mover["moves"]}, mover["cites"],
                      {"through": mover["through"], **e.cited(mover["cites"])})
            for number, mover in enumerate(thesis["exposure"]["movers"], start=1)]


def _moved(e: _Elements, thesis: dict) -> list[dict]:
    moved = []
    for number, item in enumerate(thesis["exposure"]["moved"], start=1):
        amount, used = item["amount"], list(item["how"]["cites"])
        cost = share = None
        if amount["kind"] == "stated":
            used.append(amount["figure"])
            shown = {"kind": "stated", "figure": e.figure(amount["figure"])}
        else:
            unit_price = amount["unit_price"]
            used += [amount["per_unit"], amount["price"], *([unit_price] if unit_price is not None else [])]
            cost = per_unit_cost(e.value(amount["per_unit"]), e.value(amount["price"]))
            if unit_price is not None:  # The share is of the cost as displayed, in whole dollars (thesis_sections).
                share = display(share_pct(cost, e.value(unit_price)), 1)
            shown = {"kind": "computed", "per_unit": e.figure(amount["per_unit"]), "price": e.figure(amount["price"]),
                     "unit_price": e.figure(unit_price) if unit_price is not None else None}
        moved.append(e.element({"id": f"moved-{number}", "company": item["company"], "side": item["side"]}, used, {
            "how": e.statement(item["how"]), "amount": shown,
            "usd_per_unit": display(cost, 0) if cost is not None else None, "share_pct": share}))
    return moved


def _price_record(e: _Elements, thesis: dict) -> dict:
    record = thesis["price_record"]
    return e.element({"id": PRICE_RECORD_ID, "series": record["series"]}, [record["opening"], record["latest"]],
                     {"opening": e.figure(record["opening"]), "latest": e.figure(record["latest"])})


# ---------------------------------------------------------------- the reply

def view(thesis_id: str, version: int | None = None, root: Path = THESES_DIR,
         sources_root: Path = thesis_sources.SOURCES_DIR) -> dict:
    """One version of a thesis (None: the latest) with every source verified on this machine and every element's
    state, content and computed numbers. Raises thesis_rules.ThesisRefused: 404 for an unknown or malformed id or
    version, 500 for an invalid thesis. Reads only."""
    index = thesis_schema.load_index(thesis_id, root)
    thesis = thesis_schema.load_version(thesis_id, len(index["versions"]) if version is None else version, root)
    entry = index["versions"][thesis["version"] - 1]
    states, problems = _checked(thesis, Path(sources_root))
    e = _Elements(thesis, states, problems)
    shown = {"view": _view(e, thesis), "balance": {"tables": _tables(e, thesis)}, "differs": _differs(e, thesis),
             "reasons": _claims(e, thesis["reasons"], "supports_when", reason_state),
             "risks": _claims(e, thesis["risks"], "grows_when", risk_state), "conditions": _conditions(e, thesis),
             "exposure": {"movers": _movers(e, thesis), "moved": _moved(e, thesis)},
             "price_record": _price_record(e, thesis)}
    every = [shown["view"], *shown["balance"]["tables"], *shown["differs"], *shown["reasons"], *shown["risks"],
             *shown["conditions"], *shown["exposure"]["movers"], *shown["exposure"]["moved"], shown["price_record"]]
    sources = [{**{key: source[key] for key in SOURCE_SHOWN}, **states[source["id"]]} for source in thesis["sources"]]
    return {
        "view_version": VIEW_VERSION, "thesis_version": thesis["thesis_version"], "id": thesis["id"],
        "version": thesis["version"],
        "versions": [{"version": item["version"], "published_on": item["published_on"]} for item in index["versions"]],
        "draft": entry["published_on"] is None, "title": thesis["title"], "topic": thesis["topic"],
        "opened_on": thesis["opened_on"], "prepared_on": thesis["prepared_on"], "published_on": entry["published_on"],
        "confidence": thesis["confidence"], "provider_called": False,
        "labels": {name: dict(labels) for name, labels in LABELS.items()},
        "sources": sources, **shown,
        "log": thesis["log"], "plain": thesis["plain"], "not_claimed": thesis["not_claimed"],
        "provenance": thesis["provenance"],
        "counts": {"sources": {name: sum(1 for item in sources if item["state"] == name) for name in SOURCE_STATES},
                   "elements": {name: sum(1 for item in every if item["state"] == name) for name in ELEMENT_STATES}}}


def passages(thesis_id: str, ids, root: Path = THESES_DIR,
             sources_root: Path = thesis_sources.SOURCES_DIR) -> dict:
    """{passage id: {"id", "source", "title", "publisher", "edition", "edition_date", "quote", "where", "state",
    "problem"}} for those of ``ids`` that are passages of the thesis's latest version, in the order asked; any other id
    (a figure, or no item at all) is left out. title, publisher, edition and edition_date are those of the passage's
    source entry, so another page can name the source rather than its id (edition_date stays an ordering key: a page
    shows the edition). Each is checked as view checks it, with only the sources these passages come from verified:
    "verified" when its source verified and it was found where cited (problem null); otherwise its source's state
    ("changed", "missing") or "not_found" (not where cited, or its file cannot be read), with the quote withheld (null)
    and the one problem view gives it. Raises thesis_rules.ThesisRefused as view does. Reads only."""
    index = thesis_schema.load_index(thesis_id, root)
    thesis = thesis_schema.load_version(thesis_id, len(index["versions"]), root)
    held = {item["id"]: item for item in thesis["passages"]}
    asked = [held[name] for name in dict.fromkeys(ids) if name in held]
    used = {item["source"] for item in asked}
    states, problems = _checked({"sources": [source for source in thesis["sources"] if source["id"] in used],
                                 "figures": [], "passages": asked}, Path(sources_root))
    e = _Elements(thesis, states, problems)
    entries = {source["id"]: source for source in thesis["sources"]}
    found = {}
    for item in asked:
        source = states[item["source"]]
        if source["state"] != "verified":
            state, problem = source["state"], f"{item['source']}: {source['detail']}"
        elif problems[item["id"]]:
            state, problem = "not_found", f"{item['id']}: {problems[item['id']][0]}"
        else:
            state, problem = "verified", None
        shown = e.passage(item["id"])
        entry = entries[item["source"]]
        found[item["id"]] = {"id": shown["id"], "source": shown["source"],
                             **{key: entry[key] for key in PASSAGE_SOURCE_SHOWN},
                             "quote": shown["quote"] if state == "verified" else None, "where": shown["where"],
                             "state": state, "problem": problem}
    return found

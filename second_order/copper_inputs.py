"""Retained inputs of the copper tools (copper-inputs-0.1): the coverage calculator's IEA figures and the producer
comparison's 10-K figures and passages, each bound to a retained source and checked against it on every read.

The catalogue is committed content, content/tools/copper-coverage/inputs.json, holding exactly CATALOG_FIELDS. Its
sources are entries in the thesis source shape (thesis_schema), each bound to an acquisition record and checked by
thesis_sources.verify; its figures and passages are located in their verified files with the project's own readers.
Nothing here writes, fetches or calls a model, and no value is ever filled in: an item that is not verified has no
value, and every output that depends on it is withheld by the code that uses it.

Figures. A figure holds the thesis figure fields plus ``checks``. Its locator has the shape of its source's kind:
- an XLSX figure names a sheet, a cell, a label cell and its label (as in a thesis), and ``checks`` names further cells
  of the same sheet that must read as stated (the year above the column, the scenario above it, the block the row sits
  in), so a figure is never taken from the right row of the wrong column or block;
- an HTML figure in running text names a paragraph and a quote that prints it (as in a thesis);
- an HTML figure in a table names the paragraph of its cell, the paragraph and text of its row label, its column (the
  n-th number cell after the label) and the paragraph and text of a column header before the label. The project's
  HTML reader makes every table cell its own paragraph (bis_snapshot.BLOCK_TAGS), so a cell holds only its figure; the
  cell must read exactly as the figure is printed, and an amount in parentheses is negative, as accounts print it.
Passages quote an HTML paragraph (as in a thesis) or the whole text of one workbook cell.

States. Each source is verified, changed or missing (thesis_sources.verify). Each figure or passage is verified (its
source is verified and it is found where its locator says), not_found, unreadable (its verified file, or the sheet it
names, cannot be read), source_changed or source_missing. A problem names the place only, never the value or the
quote looked for.
"""
from decimal import Decimal
from pathlib import Path
import re

from . import bis_snapshot, thesis_schema, thesis_sources
from .thesis_arithmetic import decimal_of, shown_value
from .thesis_rules import ThesisRefused, author_text, check, free_text, invalid
from .thesis_sections import ID, YEAR, day, fields, ident, items

CATALOG_VERSION = "copper-inputs-0.1"
ROOT = Path(__file__).resolve().parent.parent
INPUTS_DIR = ROOT / "content" / "tools" / "copper-coverage"
INPUTS_FILE = "inputs.json"
MAX_FILE_BYTES = 2_000_000
CATALOG_FIELDS = {"catalog_version", "id", "prepared_on", "sources", "figures", "passages"}
FIGURE_FIELDS = {"id", "source", "measure", "unit", "value", "as_shown", "year", "basis", "scenario", "locator",
                 "checks"}
PASSAGE_FIELDS = {"id", "source", "locator"}
CELL_LOCATOR = {"paragraph", "label_paragraph", "label", "column", "header_paragraph", "header"}
TEXT_LOCATOR = {"sheet", "cell", "text"}
CHECK_FIELDS = {"cell", "text"}
UNITS = {"kt": "thousand tonnes", "t": "tonnes", "t_per_year": "tonnes per year", "mlb": "million pounds",
         "mlb_per_year": "million pounds per year", "blb": "billion pounds", "usd_per_lb": "US dollars per pound",
         "usd_million": "million US dollars", "usd_billion": "billion US dollars", "percent": "percent"}
ITEM_STATES = {"verified": "Found where cited in a retained source that matches its acquisition record",
               "not_found": "Not found where cited in its retained source",
               "unreadable": "Its retained file matches its acquisition record but cannot be read",
               "source_changed": "Its retained source differs from its acquisition record",
               "source_missing": "Its retained source is not on this machine"}
MAX_CELL_SPAN = 40  # A table cell lies at most this many paragraphs after its row label.
MAX_MEASURE = 200
_ACCOUNTS = re.compile(r"\((\d[\d,]*(?:\.\d+)?)\)")  # "(0.59)": a negative amount, as accounts print it.


# ---------------------------------------------------------------- reading values as printed

def cell_value(text: str) -> Decimal:
    """A table cell's figure: a printed figure (thesis_arithmetic.shown_value), or one in parentheses, which is
    negative. Raises ValueError for anything else."""
    if not isinstance(text, str):
        raise ValueError("a cell value is text")
    match = _ACCOUNTS.fullmatch(text)
    return -shown_value(match.group(1)) if match else shown_value(text)


def _is_cell_figure(text: str) -> bool:
    try:
        cell_value(text)
    except ValueError:
        return False
    return True


def _plain(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- the committed catalogue

def _count(value: object, where: str, minimum: int = 1) -> int:
    check(type(value) is int and value >= minimum, where, f"expected a whole number of at least {minimum}")
    return value


def _cell_ref(value: object, where: str) -> str:
    check(isinstance(value, str) and bool(thesis_schema.CELL.fullmatch(value)), where,
          "expected a cell reference such as B12")
    return value


def _figure(item: object, number: int, figures: dict, sources: dict) -> dict:
    where = f"figures[{number}]"
    fields(item, FIGURE_FIELDS, where)
    ident(item["id"], f"{where}.id", figures)
    where = f"figures[{item['id']}]"
    check(isinstance(item["source"], str) and item["source"] in sources, f"{where}.source", "names no listed source")
    source = sources[item["source"]]
    check(item["unit"] in UNITS, f"{where}.unit", f"expected one of {sorted(UNITS)}")
    try:
        value = decimal_of(item["value"])
    except ValueError:
        raise invalid(f"{where}.value", "expected a plain decimal written as text") from None
    as_shown = free_text(item["as_shown"], f"{where}.as_shown", thesis_schema.MAX_SHOWN)
    check(item["year"] is None or (isinstance(item["year"], str) and bool(YEAR.fullmatch(item["year"]))),
          f"{where}.year", "expected a four-digit year or null")
    author_text(item["measure"], f"{where}.measure", MAX_MEASURE)
    for key in ("basis", "scenario"):
        if item[key] is not None:
            free_text(item[key], f"{where}.{key}", 120)
    locator, checks = item["locator"], items(item["checks"], f"{where}.checks")
    cell = source["kind"] == "html" and isinstance(locator, dict) and set(locator) == CELL_LOCATOR
    try:
        printed = cell_value(as_shown) if cell else shown_value(as_shown)
    except ValueError:
        printed = None
    check(printed is not None and printed == value, f"{where}.as_shown", f"does not print the value {item['value']}")
    if cell:
        for key in ("paragraph", "label_paragraph", "header_paragraph", "column"):
            _count(locator[key], f"{where}.locator.{key}")
        free_text(locator["label"], f"{where}.locator.label", 200)
        free_text(locator["header"], f"{where}.locator.header", 200)
        check(locator["header_paragraph"] < locator["label_paragraph"] < locator["paragraph"] <=
              locator["label_paragraph"] + MAX_CELL_SPAN, f"{where}.locator",
              f"expected a header before the row label and the cell at most {MAX_CELL_SPAN} paragraphs after it")
    else:
        check(source["kind"] in ("xlsx", "html"), f"{where}.source", "a figure comes from a workbook or an HTML page")
        thesis_schema._locator(locator, f"{where}.locator", source, as_shown)
    check(source["kind"] == "xlsx" or not checks, f"{where}.checks", "only a workbook figure names further cells")
    for index, entry in enumerate(checks):
        fields(entry, CHECK_FIELDS, f"{where}.checks[{index}]")
        _cell_ref(entry["cell"], f"{where}.checks[{index}].cell")
        free_text(entry["text"], f"{where}.checks[{index}].text", 200)
        check(entry["cell"] not in (locator["cell"], locator["label_cell"]), f"{where}.checks[{index}].cell",
              "is the figure's own cell or its label cell")
    return item


def _passage(item: object, number: int, taken: set, sources: dict) -> dict:
    where = f"passages[{number}]"
    fields(item, PASSAGE_FIELDS, where)
    ident(item["id"], f"{where}.id", taken)
    where = f"passages[{item['id']}]"
    check(isinstance(item["source"], str) and item["source"] in sources, f"{where}.source", "names no listed source")
    source, locator = sources[item["source"]], item["locator"]
    if source["kind"] == "xlsx":
        fields(locator, TEXT_LOCATOR, f"{where}.locator")
        free_text(locator["sheet"], f"{where}.locator.sheet", 100)
        _cell_ref(locator["cell"], f"{where}.locator.cell")
        free_text(locator["text"], f"{where}.locator.text", 600)
    else:
        check(source["kind"] == "html", f"{where}.source", "a passage quotes an HTML page or a workbook cell")
        thesis_schema._locator(locator, f"{where}.locator", source, None)
    return item


def _catalogue_wording(exc: ThesisRefused) -> ThesisRefused:
    """The shared thesis checks word their refusals for a thesis file; here the file is the catalogue."""
    return ThesisRefused(exc.status, str(exc).replace("The thesis file is invalid",
                                                      "The copper inputs catalogue is invalid"))


def check_catalog(raw: object) -> dict:
    """The catalogue, strictly checked as content (no retained file is read). Raises ThesisRefused (500)."""
    try:
        return _check_catalog(raw)
    except ThesisRefused as exc:
        raise _catalogue_wording(exc) from None


def _check_catalog(raw: object) -> dict:
    fields(raw, CATALOG_FIELDS, "catalog")
    check(raw["catalog_version"] == CATALOG_VERSION, "catalog_version", f"expected {CATALOG_VERSION}")
    check(isinstance(raw["id"], str) and bool(ID.fullmatch(raw["id"])), "id", "expected a lower-case id")
    prepared_on = day(raw["prepared_on"], "prepared_on")
    sources = thesis_schema._sources(raw["sources"], prepared_on)
    figures = {}
    for number, item in enumerate(items(raw["figures"], "figures", 1)):
        figures[_figure(item, number, figures, sources)["id"]] = item
    passages = {}
    for number, item in enumerate(items(raw["passages"], "passages")):
        passages[_passage(item, number, set(figures) | set(passages), sources)["id"]] = item
    used = {item["source"] for item in [*figures.values(), *passages.values()]}
    check(used == set(sources), "sources", "every listed source is cited by a figure or a passage")
    return raw


def load_catalog(folder: Path = INPUTS_DIR) -> tuple[dict, str]:
    """(the checked catalogue, the SHA-256 of its canonical JSON). Reads only. A missing catalogue is a 503: the tools
    have nothing to read."""
    path = Path(folder) / INPUTS_FILE
    if not path.is_file():
        raise ThesisRefused(503, "The copper tools' inputs catalogue is not on this machine")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise _catalogue_wording(invalid(INPUTS_FILE, "larger than the catalogue may be"))
    try:
        raw = bis_snapshot._strict_json(path.read_bytes().decode("utf-8"), "The copper inputs catalogue")
    except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        raise _catalogue_wording(invalid(INPUTS_FILE, "not strict UTF-8 JSON")) from None
    return check_catalog(raw), bis_snapshot.sha256(bis_snapshot.canonical(raw))


# ---------------------------------------------------------------- locating, against the verified files

def place(item: dict, kind: str) -> str:
    """Where an item is cited, for display: never its value or quote."""
    locator = item["locator"]
    if kind == "xlsx":
        return f"sheet {locator['sheet']}, cell {locator['cell']}"
    if set(locator) == CELL_LOCATOR:
        return f"paragraph {locator['paragraph']} (a table cell)"
    return f"paragraph {locator['paragraph']}"


def _in_cell(item: dict, paragraphs: list[str]) -> bool:
    """Whether an HTML table figure is where its cell locator says (see the module docstring)."""
    locator = item["locator"]
    first, label, cell = locator["header_paragraph"], locator["label_paragraph"], locator["paragraph"]
    if cell > len(paragraphs):
        return False
    text = lambda number: _plain(paragraphs[number - 1])  # noqa: E731
    if text(first) != _plain(locator["header"]) or text(label) != _plain(locator["label"]):
        return False
    numbers = [number for number in range(label + 1, cell + 1) if _is_cell_figure(text(number))]
    if len(numbers) != locator["column"] or numbers[-1] != cell:
        return False
    return text(cell) == item["as_shown"] and cell_value(text(cell)) == decimal_of(item["value"])


def _found(item: dict, source: dict, held: object) -> bool:
    locator, kind = item["locator"], source["kind"]
    try:
        if kind == "xlsx" and "value" not in item:
            cells = held.get(locator["sheet"]) if isinstance(held, dict) else None
            return cells is not None and not thesis_sources._label("", cells.get(locator["cell"]), locator["text"])
        if kind == "xlsx":
            cells = held.get(locator["sheet"]) if isinstance(held, dict) else None
            if cells is None or thesis_sources.locate({key: item[key] for key in ("id", "value", "locator")}, source,
                                                      held):
                return False
            return not any(thesis_sources._label("", cells.get(entry["cell"]), entry["text"])
                           for entry in item["checks"])
        if "value" in item and set(locator) == CELL_LOCATOR:
            return _in_cell(item, held)
        probe = {key: item[key] for key in ("id", "value", "as_shown", "locator") if key in item}
        return not thesis_sources.locate(probe, source, held)
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        return False


def _sheets(entries: list[dict]) -> list[str]:
    return list(dict.fromkeys(entry["locator"]["sheet"] for entry in entries))


def check_items(catalog: dict, sources_root: Path) -> tuple[dict, dict]:
    """({source id: {"state", "detail"}}, {figure or passage id: {"state", "problem"}}): each source verified once
    against its acquisition record, its file read once (a workbook one named sheet at a time) and each of its items
    located once. Reads only."""
    sources, states = {}, {}
    by_source: dict[str, list[dict]] = {}
    for entry in [*catalog["figures"], *catalog["passages"]]:
        by_source.setdefault(entry["source"], []).append(entry)
    for source in catalog["sources"]:
        state, raw = thesis_sources.verify(source, Path(sources_root))
        sources[source["id"]] = state
        entries = by_source.get(source["id"], [])
        if state["state"] != "verified":
            name = "source_missing" if state["state"] == "missing" else "source_changed"
            for entry in entries:
                states[entry["id"]] = {"state": name,
                                       "problem": f"{state['detail']} ({place(entry, source['kind'])})"}
            continue
        held, refused = {}, {}
        if source["kind"] == "xlsx":
            for sheet in _sheets(entries):
                try:
                    held.update(thesis_sources.content(source, raw, (sheet,)))
                except thesis_sources.Unreadable as exc:
                    refused[sheet] = str(exc)
        else:
            try:
                held = thesis_sources.content(source, raw)
            except thesis_sources.Unreadable as exc:
                refused[None] = str(exc)
        for entry in entries:
            key = entry["locator"]["sheet"] if source["kind"] == "xlsx" else None
            if key in refused:
                states[entry["id"]] = {"state": "unreadable", "problem": f"The retained file of {source['id']} "
                                       f"cannot be read ({refused[key]})"}
            elif _found(entry, source, held):
                states[entry["id"]] = {"state": "verified", "problem": None}
            else:
                states[entry["id"]] = {"state": "not_found",
                                       "problem": f"not found where cited ({place(entry, source['kind'])})"}
    return sources, states


def verified_values(catalog: dict, states: dict) -> dict[str, Decimal]:
    """{figure id: its exact value} for the verified figures only; nothing else is ever given a value."""
    return {item["id"]: decimal_of(item["value"]) for item in catalog["figures"]
            if states.get(item["id"], {}).get("state") == "verified"}


def source_of(catalog: dict) -> dict[str, dict]:
    return {source["id"]: source for source in catalog["sources"]}

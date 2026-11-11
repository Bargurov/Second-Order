"""Retained G.17 evidence for the industry findings (g17-extract-0.1): Table 1 and the release summary of each retained
release, read from the bytes kept by acquisitions g17-release-tables-01 and g17-industry-tables-01.

Sources. Only files named by those approvals' outcome records are used. A record must report a complete HTTP 200
response with a complete-response hash; the file must still have that SHA-256, at most 2 MiB, under the release's own
folder and archive address. Table 2 is retained but not read here. Inspection reports and notes are never read.

Parsing. The Board's tables carry `id` and `headers` attributes, and rows and columns are resolved through them, never by
position: a row's path is its section and ancestor row headers; a value's column is the set of header cells it names.
A page or table is refused when:
- the G.17 identity is missing, or its release-date statement differs from its archive folder;
- its last-update statement differs from the release date (an archived page changed after its release);
- the table heading, title or unit differs from the expected text (Table 1: percent change, seasonally adjusted);
- its monthly columns are not six consecutive monthly rates marked [r], with the last one [p];
- a row's indent class contradicts its header path, a path or id repeats, or a value cell does not name its own row;
- a value is anything other than a one-decimal printed rate or a blank, which stays missing;
- the page holds a marked section html_markup does not read.
Consistency. Table 1's Total IP, Manufacturing, Mining and Utilities must equal the release summary's Total index,
Manufacturing (see note below), Mining and Utilities in every month, with the same months and markers.

The extract's ID covers its meaningful content and source hashes; retrieval times and server headers are kept apart, as
provenance, and never change it.
"""
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from . import html_markup
from .store import digest

EXTRACT_VERSION = "g17-extract-0.1"
ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "data" / "sector-sources" / "g17"
APPROVALS = {"release.html": "g17-release-tables-01", "table1.htm": "g17-industry-tables-01"}
ROLES = {"release.html": "release summary", "table1.htm": "Table 1"}
MAX_BYTES = 2 * 1024 * 1024
IDENTITY = "Industrial Production and Capacity Utilization - G.17"
TABLE1_TITLE = "Table 1 Industrial Production: Market and Industry Group Summary"
TABLE1_UNIT = "Percent change, seasonally adjusted"
SUMMARY_TITLE = "Industrial Production and Capacity Utilization: Summary"
SUMMARY_UNIT = "Seasonally adjusted"
MONTHS = {"Jan.": 1, "Feb.": 2, "Mar.": 3, "Apr.": 4, "May": 5, "June": 6, "July": 7, "Aug.": 8, "Sept.": 9,
          "Oct.": 10, "Nov.": 11, "Dec.": 12}
MONTH_HEADER = re.compile(r"(" + "|".join(re.escape(name) for name in MONTHS) + r")\[(r|p)\]")
RATE = re.compile(r"-?\d*\.\d")
PROPORTION = re.compile(r"\d*\.\d\d")
# Table 1 row path -> the release summary row it must equal.
SUMMARY_ROWS = {"Total IP": "Total index",
                "INDUSTRY GROUP / Manufacturing": "Major industry groups / Manufacturing (see note below)",
                "INDUSTRY GROUP / Mining": "Major industry groups / Mining",
                "INDUSTRY GROUP / Utilities": "Major industry groups / Utilities"}


class EvidenceRefused(ValueError):
    pass


def source_url(release: str, name: str) -> str:
    base = f"https://www.federalreserve.gov/releases/g17/{release}/"
    return base if name == "release.html" else base + name


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


class _Page(HTMLParser):
    """Page markers and every titled table's rows, with each cell's id, headers, class and text."""

    MARKS = {("div", "class", "dates"): "dates", ("div", "id", "lastUpdate"): "last_update",
             ("h5", "class", "tablehead"): "tablehead", ("span", "class", "tableunit"): "tableunit"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: dict[str, list[list[dict]]] = {}
        self.marks: dict[str, list[str]] = {name: [] for name in self.MARKS.values()} | {"h2": []}
        self.text: list[str] = []
        self._table, self._row, self._cell, self._open = None, None, None, []

    def handle_starttag(self, tag, attrs):
        values = {key: value or "" for key, value in attrs}
        if tag == "table":
            if self._table is not None:
                raise EvidenceRefused("A table is nested in another table")
            self._table = _clean(values.get("title", ""))
            if self._table in self.tables:
                raise EvidenceRefused(f"Two tables are titled {self._table!r}")
            self.tables[self._table] = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = {"tag": tag, "id": values.get("id", "").strip() or None,
                          "headers": values.get("headers", "").split(), "class": values.get("class") or None,
                          "text": ""}
        elif tag == "br":
            self._data(" ")
        for item in self._open:  # Same-tag nesting inside an open marker.
            if item[1] == tag:
                item[2] += 1
        for (name, attribute, wanted), mark in self.MARKS.items():
            if tag == name and wanted in values.get(attribute, "").split():
                self._open.append([mark, tag, 1, ""])
        if tag == "h2":
            self._open.append(["h2", tag, 1, ""])

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cell is not None:
            self._cell["text"] = _clean(self._cell["text"])
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[self._table].append(self._row)
            self._row = None
        elif tag == "table":
            self._table = None
        for item in list(self._open):
            if item[1] == tag:
                item[2] -= 1
                if item[2] == 0:
                    self.marks[item[0]].append(_clean(item[3]))
                    self._open.remove(item)

    def handle_data(self, data):
        self._data(data)

    def _data(self, data):
        if self._cell is not None:
            self._cell["text"] += data
        for item in self._open:
            item[3] += data
        self.text.append(data)


def _page(data: bytes, where: str) -> _Page:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceRefused(f"{where} is not UTF-8") from None
    if html_markup.unreadable(decoded):  # The rule comes before the parser, so every Python version gives one answer.
        raise EvidenceRefused(f"{where} has markup that cannot be read (an unknown marked section such as <![bogus[)")
    page = _Page()
    page.feed(decoded)
    page.close()
    return page


def _dated(page: _Page, release: str, where: str) -> dict:
    """The page's G.17 identity and its release-date and last-update statements, which must match its folder."""
    if not any(IDENTITY in text for text in page.marks["h2"]):
        raise EvidenceRefused(f"{where} does not carry the G.17 release identity")
    stated = [text for text in page.marks["dates"] if text.startswith("Release Date:")]
    if len(stated) != 1:
        raise EvidenceRefused(f"{where} has {len(stated)} release-date statements, not one")
    as_stated = stated[0].removeprefix("Release Date:").strip()
    try:
        day = datetime.strptime(as_stated, "%B %d, %Y").date()
    except ValueError:
        raise EvidenceRefused(f"{where} states an unreadable release date {as_stated!r}") from None
    if day.strftime("%Y%m%d") != release:
        raise EvidenceRefused(f"{where} states release date {as_stated}, not that of its folder {release}")
    updates = [text.removeprefix("Last Update:").strip() for text in page.marks["last_update"]]
    if len(updates) != 1 or updates[0] != as_stated:
        raise EvidenceRefused(f"{where} states last update {updates}, not its release date {as_stated}; an archived "
                              "page changed after its release is not used as that release's version")
    return {"release_date": day.isoformat(), "release_date_as_stated": as_stated, "last_update_as_stated": updates[0]}


def _grid(page: _Page, title: str, unit: str, item_header: str, group: str, where: str) -> dict:
    """Rows (path, depth, section, cells) and the monthly columns under the header `group`, resolved by id."""
    if title not in page.marks["tablehead"]:
        raise EvidenceRefused(f"{where}: the heading {title!r} is missing")
    if unit not in page.marks["tableunit"]:
        raise EvidenceRefused(f"{where}: the unit statement {unit!r} is missing")
    rows = page.tables.get(title)
    if not rows:
        raise EvidenceRefused(f"{where}: no table titled {title!r}")
    columns, sections, row_headers, ids = {}, {}, {}, set()
    for row in rows:
        for cell in row:
            if cell["id"]:
                if cell["id"] in ids:
                    raise EvidenceRefused(f"{where}: the id {cell['id']} repeats")
                ids.add(cell["id"])
            if cell["tag"] == "th" and cell["id"] and not cell["headers"]:
                (sections if cell["class"] == "subhead" else columns)[cell["id"]] = cell["text"]
    item = [key for key, text in columns.items() if text == item_header]
    groups = [key for key, text in columns.items() if text == group]
    if len(item) != 1 or len(groups) != 1:
        raise EvidenceRefused(f"{where}: the column headers {item_header!r} and {group!r} are not each present once")
    item, group_id = item[0], groups[0]
    out, paths, months = [], set(), {}
    for row in rows:
        heads = [cell for cell in row if cell["tag"] == "th" and cell["headers"]]
        if not heads:
            continue
        if len(heads) != 1 or row[0] is not heads[0]:
            raise EvidenceRefused(f"{where}: a row does not start with exactly one row header")
        head = heads[0]
        if not head["id"] or head["headers"][0] != item:
            raise EvidenceRefused(f"{where}: the row {head['text']!r} is not under the {item_header!r} column")
        section, ancestors = None, []
        for key in head["headers"][1:]:
            if key in sections and section is None and not ancestors:
                section = sections[key]
            elif key in row_headers:
                ancestors.append(key)
            else:
                raise EvidenceRefused(f"{where}: the row {head['text']!r} names an unknown header {key}")
        depth = len(ancestors)
        expected = None if depth == 0 else f"indent{depth}"
        if head["class"] != expected:
            raise EvidenceRefused(f"{where}: the row {head['text']!r} has class {head['class']} at depth {depth}")
        labels = [row_headers[key]["label"] for key in ancestors]
        if ancestors and row_headers[ancestors[-1]]["ancestors"] != ancestors[:-1]:
            raise EvidenceRefused(f"{where}: the row {head['text']!r} skips a level of its hierarchy")
        path = " / ".join(([section] if section else []) + labels + [head["text"]])
        if path in paths:
            raise EvidenceRefused(f"{where}: the row path {path!r} repeats")
        paths.add(path)
        row_headers[head["id"]] = {"label": head["text"], "ancestors": ancestors}
        own = set(head["headers"][1:]) | {head["id"]}
        cells = []
        for cell in row[1:]:
            if cell["tag"] != "td" or not own <= set(cell["headers"]):
                raise EvidenceRefused(f"{where}: a value in the row {path!r} does not name that row")
            names = [key for key in cell["headers"] if key in columns]
            cells.append({"columns": names, "text": cell["text"]})
            month = [key for key in names if MONTH_HEADER.fullmatch(columns[key])]
            if group_id in names and month:  # A monthly value; the group's 12-month column names no month.
                years = [key for key in names if re.fullmatch(r"\d{4}", columns[key])]
                if len(month) != 1 or len(years) != 1 or len(names) != 3:
                    raise EvidenceRefused(f"{where}: a monthly value in {path!r} does not name one year and one month")
                months.setdefault(month[0], years[0])
                if months[month[0]] != years[0]:
                    raise EvidenceRefused(f"{where}: the month column {columns[month[0]]} has two years")
        out.append({"path": path, "label": head["text"], "section": section, "depth": depth, "cells": cells})
    order = [key for key in columns if key in months]
    labelled = []
    for key in order:
        name, marker = MONTH_HEADER.fullmatch(columns[key]).groups()
        year = int(columns[months[key]])
        labelled.append({"id": key, "key": f"{year:04d}-{MONTHS[name]:02d}", "label": name, "year": str(year),
                         "marker": marker, "column": f"{group} / {year} / {columns[key]}"})
    keys = [date(int(item_["key"][:4]), int(item_["key"][5:]), 1) for item_ in labelled]
    consecutive = all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in zip(keys, keys[1:]))
    markers = [item_["marker"] for item_ in labelled]
    if len(labelled) != 6 or not consecutive or markers != ["r"] * 5 + ["p"]:
        raise EvidenceRefused(f"{where}: the {group!r} columns are {[c['column'] for c in labelled]}, not six "
                              "consecutive months marked [r] with the last one [p]")
    return {"columns": columns, "rows": out, "months": labelled}


def _rate(text: str, where: str) -> str | None:
    if text == "":
        return None  # A blank: no observation printed. It stays missing.
    if not RATE.fullmatch(text):
        raise EvidenceRefused(f"{where}: {text!r} is not a printed one-decimal rate")
    return text


def _monthly(row: dict, months: list[dict], group_id: str, where: str) -> dict:
    found = {}
    for cell in row["cells"]:
        month = next((item for item in months if item["id"] in cell["columns"]), None)
        if group_id in cell["columns"] and month is not None:
            if month["key"] in found:
                raise EvidenceRefused(f"{where}: the row {row['path']!r} has two values for {month['column']}")
            found[month["key"]] = _rate(cell["text"], f"{where}, {row['path']}, {month['column']}")
    if len(found) != len(months):
        raise EvidenceRefused(f"{where}: the row {row['path']!r} has {len(found)} monthly values, not {len(months)}")
    return found


def parse_table1(data: bytes, release: str) -> dict:
    where = f"Table 1 of the {release} release"
    page = _page(data, where)
    dated = _dated(page, release, where)
    if TABLE1_TITLE not in page.tables:
        raise EvidenceRefused(f"{where}: no table titled {TABLE1_TITLE!r}")
    grid = _grid(page, TABLE1_TITLE, TABLE1_UNIT, "Item", "Monthly rate", where)
    columns = grid["columns"]
    group_id = next(key for key, text in columns.items() if text == "Monthly rate")
    naics_id = [key for key, text in columns.items() if text == "NAICS"]
    weight = [(key, text) for key, text in columns.items() if re.fullmatch(r"\d{4} Proportion\[1\]", text)]
    if len(naics_id) != 1 or len(weight) != 1:
        raise EvidenceRefused(f"{where}: the NAICS and proportion columns are not each present once")
    rows = []
    for row in grid["rows"]:
        naics = [c["text"] for c in row["cells"] if naics_id[0] in c["columns"]]
        share = [c["text"] for c in row["cells"] if weight[0][0] in c["columns"]]
        if len(naics) != 1 or len(share) != 1 or not PROPORTION.fullmatch(share[0]):
            raise EvidenceRefused(f"{where}: the row {row['path']!r} has no single NAICS cell and proportion")
        rows.append({"path": row["path"], "label": row["label"], "section": row["section"], "depth": row["depth"],
                     "naics": naics[0] or None, "proportion": share[0],
                     "rates": _monthly(row, grid["months"], group_id, where)})
    text = _clean("".join(page.text))
    footnote = re.search(r"\[1\] (The proportion data are .+?\.)(?= Note\.)", text)
    note = re.search(r"(Note\. Under industry groups, .+? denotes part of a NAICS code\.)", text)
    if not footnote or not note:
        raise EvidenceRefused(f"{where}: the proportion footnote or the NAICS note is missing")
    return {**dated, "title": TABLE1_TITLE, "unit": TABLE1_UNIT, "proportion_label": weight[0][1].removesuffix("[1]"),
            "proportion_note": footnote.group(1), "naics_note": note.group(1),
            "months": [{key: value for key, value in m.items() if key != "id"} for m in grid["months"]], "rows": rows}


def parse_summary(data: bytes, release: str) -> dict:
    where = f"the release summary of the {release} release"
    page = _page(data, where)
    dated = _dated(page, release, where)
    grid = _grid(page, SUMMARY_TITLE, SUMMARY_UNIT, "Industrial production", "Percent change", where)
    group_id = next(key for key, text in grid["columns"].items() if text == "Percent change")
    rates = {row["path"]: _monthly(row, grid["months"], group_id, where) for row in grid["rows"]
             if row["path"] in SUMMARY_ROWS.values()}
    if set(rates) != set(SUMMARY_ROWS.values()):
        raise EvidenceRefused(f"{where}: missing summary rows {sorted(set(SUMMARY_ROWS.values()) - set(rates))}")
    return {**dated, "title": SUMMARY_TITLE, "unit": SUMMARY_UNIT,
            "months": [{key: value for key, value in m.items() if key not in ("id", "column")} for m in grid["months"]],
            "rates": rates}


def retained(root: Path = SOURCES_DIR) -> dict[str, dict[str, dict]]:
    """Release -> {file name: its outcome record}, from the two approvals' records only. Reads only."""
    found: dict[str, dict[str, dict]] = {}
    for name, approval in APPROVALS.items():
        folder = root / "acquisitions" / approval
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("outcome-*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # An unreadable record names nothing; its release is not offered.
            if not isinstance(record, dict):
                continue
            match = re.fullmatch(r"data/sector-sources/g17/(\d{8})/" + re.escape(name), record.get("retained") or "")
            if record.get("approval_id") == approval and match:
                found.setdefault(match.group(1), {})[name] = record
    return {release: files for release, files in sorted(found.items()) if set(files) == set(APPROVALS)}


def _source(root: Path, release: str, name: str, record: dict) -> tuple[bytes, dict]:
    where = f"{release}/{name}"
    url = source_url(release, name)
    if (record.get("outcome"), record.get("hash_kind"), record.get("http_status"), record.get("url")) != \
            ("complete", "complete_response", 200, url):
        raise EvidenceRefused(f"{where}: its acquisition record does not report a complete response from {url}")
    path = root / release / name
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise EvidenceRefused(f"{where}: the retained file is missing or larger than {MAX_BYTES} bytes")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != record.get("sha256") or sha != record.get("retained_sha256"):
        raise EvidenceRefused(f"{where}: the retained file no longer has its recorded SHA-256")
    return data, {"role": ROLES[name], "file": f"{release}/{name}", "url": url, "sha256": sha, "bytes": len(data),
                  "approval_id": record["approval_id"]}


def extract(root: Path, release: str, records: dict[str, dict]) -> dict:
    """One release's verified extract: Table 1 rows, months and notes, checked against its release summary."""
    table_bytes, table_source = _source(root, release, "table1.htm", records["table1.htm"])
    summary_bytes, summary_source = _source(root, release, "release.html", records["release.html"])
    table, summary = parse_table1(table_bytes, release), parse_summary(summary_bytes, release)
    if table["release_date"] != summary["release_date"]:
        raise EvidenceRefused(f"{release}: Table 1 and the release summary state different release dates")
    if [{k: m[k] for k in ("key", "label", "year", "marker")} for m in table["months"]] != summary["months"]:
        raise EvidenceRefused(f"{release}: Table 1 and the release summary show different months or markers")
    by_path = {row["path"]: row for row in table["rows"]}
    checks = []
    for path, summary_path in SUMMARY_ROWS.items():
        if path not in by_path:
            raise EvidenceRefused(f"{release}: Table 1 has no row {path!r}")
        equal = by_path[path]["rates"] == summary["rates"][summary_path]
        if not equal:
            raise EvidenceRefused(f"{release}: Table 1 {path!r} differs from the release summary {summary_path!r}")
        checks.append({"table1_row": path, "summary_row": summary_path, "months": len(table["months"]), "equal": True})
    content = {"extract_version": EXTRACT_VERSION, "release": release,
               "release_date": table["release_date"], "release_date_as_stated": table["release_date_as_stated"],
               "last_update_as_stated": table["last_update_as_stated"],
               "sources": [table_source, summary_source],
               "table": {key: table[key] for key in ("title", "unit", "proportion_label", "proportion_note",
                                                     "naics_note")},
               "months": table["months"], "rows": table["rows"], "consistency": checks}
    provenance = [{"file": source["file"], "retrieved_at": records[name].get("dispatched_at"),
                   "last_modified_header": (records[name].get("named_headers") or {}).get("last-modified")}
                  for source, name in ((table_source, "table1.htm"), (summary_source, "release.html"))]
    return {**content, "extract_id": digest(content), "provenance": provenance}


def verify_extract(record: dict) -> bool:
    content = {key: value for key, value in record.items() if key not in ("extract_id", "provenance")}
    return record.get("extract_version") == EXTRACT_VERSION and record.get("extract_id") == digest(content)

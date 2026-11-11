"""The Atlanta Fed Market Probability Tracker's historical workbook (mpt_histdata.xlsx), read without trusting it.

The workbook is an Office Open XML archive with three sheets: LICENSE (its text is a drawing's text box, not cells),
DICTIONARY (the definitions of every column and statistic) and DATA (one statistic per row: observation date,
reference-window start, the FOMC target range on the observation date, the statistic's name and its value). This
module only reads bytes it is given; it never fetches, extracts to disk or writes (rate_context keeps and records).

Archive safeguards are market_package's: entry count, safe names, no links or encryption, stored or deflated entries,
size, total and expansion limits, and every entry read through once so its CRC and declared size are checked. Each XML
part is parsed as a stream through expat with DOCTYPE, entity, notation and unparsed-entity declarations refused,
parameter entities never parsed and external references refused, so nothing is expanded, fetched or opened.

What is accepted. The sheets are exactly LICENSE, DICTIONARY and DATA, the workbook uses the 1900 date system, and the
reference-window column carries a built-in date format. LICENSE holds LICENSE_STATEMENT as one paragraph (paragraphs are
read at the drawing's own paragraph boundaries, runs joined, never split on punctuation). DICTIONARY states DESCRIPTION
and, for every column and statistic this project reads or explains, exactly the definition in DEFINITIONS; a definition
listed twice must say the same both times. DATA starts with exactly HEADER, and every row has the five cells: a
YYYY-MM-DD observation date (text), a whole-number date serial for the reference start, a target range "<n>bps - <m>bps",
a statistic name, and a plain decimal value (no exponent, sign other than "-", NaN or infinity), with no observation
date, reference start and statistic repeated. Any failure refuses the whole workbook (WorkbookRefused); nothing is
repaired, skipped or guessed. Values keep their exact text; rates are basis points and probabilities percent, as the
dictionary states, and nothing here converts them.
"""
from datetime import date, timedelta
import pyexpat
from pathlib import Path
import posixpath
import re
import xml.parsers.expat as expat
import zipfile
import zlib

from .market_package import ArchiveRefused, _checked_infos, _stream

PARSER_VERSION = "mpt-workbook-parser-0.1"
PARSER = {"version": PARSER_VERSION, "library": f"expat {pyexpat.EXPAT_VERSION}",
          "protections": ["DOCTYPE, entity, notation and unparsed-entity declarations refused",
                          "parameter entities never parsed", "external references refused; nothing is fetched or opened",
                          "archive limits and every entry's CRC checked"]}
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_TEXT = "http://schemas.openxmlformats.org/drawingml/2006/main"
SHEETS = ("LICENSE", "DICTIONARY", "DATA")
HEADER = ("date", "reference_start", "target_range", "field", "value")
COLUMNS = ("A", "B", "C", "D", "E")
STATISTICS = {"mean": "Rate: mean", "p25": "Rate: 25th percentile", "p75": "Rate: 75th percentile"}
DESCRIPTION = ("The Market Probability Tracker uses Chicago Mercantile Exchange (CME) 3-month SOFR options to estimate "
               "the probability ditributions implied by their prices and specified reference window.   Below are a "
               "selection of statistics generated from those distributions, organized by date and reference window.")
DEFINITIONS = {  # Exactly as the workbook's DICTIONARY states them, its spelling included.
    "date": "Observation date",
    "reference_start": "Start date of the 3-month window referenced by CME 3-month SOFR contracts",
    "target_range": "FOMC federal funds rate target range on the indicated observation date",
    "field": "Statistics generated from the distributions estimated by the Market Probability Tracker",
    "value": "The value of the indicated statistic",
    "Rate: mean": ("The rate, in basis points, associated with the mean of the estimated distribution for a given "
                   "reference window"),
    "Rate: 25th percentile": ("The rate, in basis points, associated with the 25th percentile of the estimated "
                              "distribution for a given reference window"),
    "Rate: 75th percentile": ("The average, in basis points, associated with the 75th percentile of the distribution "
                              "for a given reference window"),
    "Prob: cut": ("The probability, in percent, average SOFR over the reference window will be below the FOMC's "
                  "target range"),
    "Prob: hike": ("The probability, in percent, average SOFR over the reference window will be above the FOMC's "
                   "target range"),
}
LICENSE_STATEMENT = ("Atlanta Fed Market Probability Tracker is not an official forecast of the Federal Reserve Bank of "
                     "Atlanta, its president, the Federal Reserve System, or the FOMC. Use of this data is permitted for "
                     "personal and educational purposes only. Copyright (c) 2024, Federal Reserve Bank of Atlanta. All "
                     "rights reserved.")
DATE_FORMATS = {14, 15, 16, 17, 22}  # The built-in spreadsheet number formats that show a date.
EPOCH = date(1899, 12, 30)  # Serial day 0 of the 1900 date system, for serials of 1 March 1900 (61) and later.
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SERIAL = re.compile(r"[1-9]\d{1,5}")
TARGET = re.compile(r"(\d{1,4})bps - (\d{1,4})bps")
DECIMAL = re.compile(r"\s*(-?\d{1,6}(?:\.\d{1,6})?)\s*")
MAX_STRINGS = 1_000_000
MAX_ROWS = 5_000_000


class WorkbookRefused(ValueError):
    """The workbook failed a check; nothing derived from it may be used."""


def decimal_text(raw: str) -> str | None:
    """The plain decimal a value cell states, without its padding, or None when it is not one."""
    match = DECIMAL.fullmatch(raw) if isinstance(raw, str) else None
    return match.group(1) if match else None


def target_range(raw: str) -> tuple[int, int] | None:
    match = TARGET.fullmatch(raw) if isinstance(raw, str) else None
    return (int(match[1]), int(match[2])) if match and int(match[1]) <= int(match[2]) else None


def serial_day(serial: int) -> date:
    return EPOCH + timedelta(days=serial)


# ---------------------------------------------------------------- protected XML

def _refuse(part: str, kind: str):
    def handler(*_):
        raise WorkbookRefused(f"{part} has a {kind}, which the parser policy refuses")
    return handler


def _parse(archive: zipfile.ZipFile, infos: dict, part: str, start, end, text) -> None:
    """Stream one XML part through a protected expat parser. Raises WorkbookRefused."""
    info = infos.get(part)
    if info is None or info.is_dir():
        raise WorkbookRefused(f"The workbook has no {part} part")
    parser = expat.ParserCreate(namespace_separator="|")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse(part, "DOCTYPE declaration")
    parser.EntityDeclHandler = _refuse(part, "entity declaration")
    parser.UnparsedEntityDeclHandler = _refuse(part, "unparsed entity declaration")
    parser.NotationDeclHandler = _refuse(part, "notation declaration")
    parser.ExternalEntityRefHandler = _refuse(part, "external entity reference")
    parser.buffer_text = True
    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, text
    try:
        for chunk in _stream(archive, info, [0]):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise WorkbookRefused(f"{part} is not well-formed XML ({exc})") from None


def _relationships(archive: zipfile.ZipFile, infos: dict, part: str) -> dict:
    """A relationships part as {id: (type's last segment, target resolved against the part's folder)}."""
    folder = posixpath.dirname(posixpath.dirname(part))
    found = {}

    def start(name, attrs):
        if name == f"{PACKAGE_RELS}|Relationship":
            found[attrs.get("Id")] = (str(attrs.get("Type", "")).rsplit("/", 1)[-1],
                                      posixpath.normpath(posixpath.join(folder, attrs.get("Target", ""))))
    _parse(archive, infos, part, start, lambda name: None, lambda value: None)
    return found


def _rels_part(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


class _Strings:
    """Shared strings: each <si> is its <t> texts joined (rich-text runs included, phonetic runs left out)."""

    def __init__(self):
        self.values, self.parts, self.depth, self.phonetic = [], [], 0, 0

    def start(self, name, attrs):
        if name == f"{MAIN}|si":
            self.parts = []
        elif name == f"{MAIN}|rPh":
            self.phonetic += 1
        elif name == f"{MAIN}|t":
            self.depth += 1

    def end(self, name):
        if name == f"{MAIN}|si":
            self.values.append("".join(self.parts))
            if len(self.values) > MAX_STRINGS:
                raise WorkbookRefused("The workbook has more shared strings than this reader accepts")
        elif name == f"{MAIN}|rPh":
            self.phonetic -= 1
        elif name == f"{MAIN}|t":
            self.depth -= 1

    def text(self, value):
        if self.depth and not self.phonetic:
            self.parts.append(value)


class _Sheet:
    """A worksheet as rows of {column: (cell type, style index, raw text)}, handed to ``on_row`` one at a time."""

    def __init__(self, on_row):
        self.on_row, self.row, self.cell, self.value, self.inside, self.last = on_row, None, None, [], 0, 0

    def start(self, name, attrs):
        if name == f"{MAIN}|row":
            number = attrs.get("r", "")
            if not number.isdigit() or int(number) <= self.last:
                raise WorkbookRefused(f"A worksheet row is numbered {number!r} after row {self.last}")
            self.last = int(number)
            self.row = {}
        elif name == f"{MAIN}|c" and self.row is not None:
            reference = attrs.get("r", "")
            column = reference.rstrip("0123456789")
            if reference[len(column):] != str(self.last) or column in self.row:
                raise WorkbookRefused(f"Cell {reference!r} does not belong to row {self.last} or repeats a column")
            self.cell, self.value = (column, attrs.get("t"), attrs.get("s")), []
        elif name in (f"{MAIN}|v", f"{MAIN}|t", f"{MAIN}|is"):
            self.inside += 1

    def end(self, name):
        if name == f"{MAIN}|c" and self.cell is not None:
            column, kind, style = self.cell
            self.row[column] = (kind, style, "".join(self.value) if self.value else None)
            self.cell = None
        elif name in (f"{MAIN}|v", f"{MAIN}|t", f"{MAIN}|is"):
            self.inside -= 1
        elif name == f"{MAIN}|row":
            self.on_row(self.last, self.row)
            self.row = None

    def text(self, value):
        if self.inside and self.cell is not None:
            self.value.append(value)


# ---------------------------------------------------------------- the workbook

def read(path: Path, wanted: frozenset[str] = frozenset()) -> tuple[dict, dict]:
    """The workbook's checked description and, for each observation date in ``wanted``, its rows grouped by reference
    start and statistic: {date: {reference start: {statistic: {"row", "raw", "target_range"}}}}. Raises
    WorkbookRefused."""
    try:
        with zipfile.ZipFile(path) as archive:
            return _read(archive, wanted)
    except ArchiveRefused as exc:
        raise WorkbookRefused(f"The workbook archive was refused ({exc.outcome}): {exc}") from None
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, OSError) as exc:
        raise WorkbookRefused(f"The workbook archive could not be read ({type(exc).__name__}: {exc})") from None


def _read(archive: zipfile.ZipFile, wanted: frozenset[str]) -> tuple[dict, dict]:
    infos = {info.filename: info for info in _checked_infos(archive)}
    entries = []
    for name, info in sorted(infos.items()):
        if not info.is_dir():
            for _ in _stream(archive, info, [0]):  # Read through: size, expansion and CRC are checked.
                pass
            entries.append({"name": name, "compressed_bytes": info.compress_size, "bytes": info.file_size,
                            "crc32": f"{info.CRC:08x}"})
    sheets, properties = [], {}

    def book(name, attrs):
        if name == f"{MAIN}|sheet":
            sheets.append((attrs.get("name"), attrs.get(f"{OFFICE_RELS}|id")))
        elif name == f"{MAIN}|workbookPr":
            properties.update(attrs)
    _parse(archive, infos, "xl/workbook.xml", book, lambda name: None, lambda value: None)
    if tuple(name for name, _ in sheets) != SHEETS:
        raise WorkbookRefused(f"The workbook's sheets are {[name for name, _ in sheets]}, not {list(SHEETS)}")
    if properties.get("date1904") in ("1", "true"):
        raise WorkbookRefused("The workbook uses the 1904 date system; this reader reads 1900 serials only")
    relations = _relationships(archive, infos, "xl/_rels/workbook.xml.rels")
    parts = {}
    for name, identifier in sheets:
        kind, target = relations.get(identifier, (None, None))
        if kind != "worksheet":
            raise WorkbookRefused(f"Sheet {name} does not point to a worksheet")
        parts[name] = target
    shared = [target for kind, target in relations.values() if kind == "sharedStrings"]
    styles = [target for kind, target in relations.values() if kind == "styles"]
    if len(shared) != 1 or len(styles) != 1:
        raise WorkbookRefused("The workbook does not name exactly one shared-strings part and one styles part")
    strings = _Strings()
    _parse(archive, infos, shared[0], strings.start, strings.end, strings.text)
    formats, inside = [], [False]

    def style(name, attrs):
        if name == f"{MAIN}|cellXfs":
            inside[0] = True
        elif name == f"{MAIN}|xf" and inside[0]:
            formats.append(attrs.get("numFmtId", "0"))

    def style_end(name):
        if name == f"{MAIN}|cellXfs":
            inside[0] = False
    _parse(archive, infos, styles[0], style, style_end, lambda value: None)

    def text_of(cell, where: str) -> str:
        kind, _, raw = cell
        if kind != "s" or raw is None or not raw.isdigit() or int(raw) >= len(strings.values):
            raise WorkbookRefused(f"{where} is not a shared-string text cell")
        return strings.values[int(raw)]

    license_paragraphs = _license(archive, infos, parts["LICENSE"])
    if LICENSE_STATEMENT not in license_paragraphs:
        raise WorkbookRefused("The LICENSE sheet does not state the expected use and attribution terms")
    description, definitions = _dictionary(archive, infos, parts["DICTIONARY"], text_of)
    data, collected = _data(archive, infos, parts["DATA"], text_of, formats, wanted)
    return {"parser": PARSER, "entries": entries, "sheets": list(SHEETS), "date_system": "1900",
            "license": {"paragraphs": license_paragraphs, "statement": LICENSE_STATEMENT},
            "dictionary": {"description": description, "definitions": definitions}, "data": data}, collected


def _license(archive: zipfile.ZipFile, infos: dict, sheet: str) -> list[str]:
    """The LICENSE sheet's text box: its drawing's paragraphs, each with its runs joined; empty paragraphs left out."""
    drawings = [target for kind, target in _relationships(archive, infos, _rels_part(sheet)).values()
                if kind == "drawing"]
    if len(drawings) != 1:
        raise WorkbookRefused("The LICENSE sheet does not have exactly one drawing")
    paragraphs, current, inside = [], [], [0]

    def start(name, attrs):
        if name == f"{DRAWING_TEXT}|p":
            current.clear()
        elif name == f"{DRAWING_TEXT}|t":
            inside[0] += 1

    def end(name):
        if name == f"{DRAWING_TEXT}|p":
            paragraphs.append("".join(current))
        elif name == f"{DRAWING_TEXT}|t":
            inside[0] -= 1
    _parse(archive, infos, drawings[0], start, end, lambda value: current.append(value) if inside[0] else None)
    return [paragraph for paragraph in paragraphs if paragraph.strip()]


def _dictionary(archive: zipfile.ZipFile, infos: dict, sheet: str, text_of) -> tuple[str, dict]:
    """The DICTIONARY sheet: its description (B2) and every name in column B with its definition in column C."""
    texts, definitions = {}, {}

    def on_row(number, cells):
        for column, cell in cells.items():
            if cell[2] is not None:
                texts[(number, column)] = text_of(cell, f"DICTIONARY cell {column}{number}")
    reader = _Sheet(on_row)
    _parse(archive, infos, sheet, reader.start, reader.end, reader.text)
    description = texts.get((2, "B"))
    for (number, column), name in sorted(texts.items()):
        if column != "B" or number == 2:
            continue
        meaning = texts.get((number, "C"))
        if meaning is None:
            raise WorkbookRefused(f"DICTIONARY row {number} names {name!r} without a definition")
        if definitions.setdefault(name, meaning) != meaning:
            raise WorkbookRefused(f"DICTIONARY defines {name!r} twice, differently")
    if description != DESCRIPTION:
        raise WorkbookRefused("The DICTIONARY sheet's description differs from the one this reader was written for")
    for name, meaning in DEFINITIONS.items():
        if definitions.get(name) != meaning:
            raise WorkbookRefused(f"The DICTIONARY definition of {name!r} differs from the one this reader was written "
                                  "for; nothing is read under another meaning")
    return description, definitions


def _data(archive: zipfile.ZipFile, infos: dict, sheet: str, text_of, formats: list, wanted: frozenset) -> tuple:
    seen, dates, collected, count, header = set(), set(), {}, [0], [False]

    def on_row(number, cells):
        if not header[0]:
            if number != 1 or set(cells) != set(COLUMNS) or \
                    tuple(text_of(cells[c], f"DATA header {c}1") for c in COLUMNS) != HEADER:
                raise WorkbookRefused(f"The DATA sheet does not start with exactly the header {list(HEADER)}")
            header[0] = True
            return
        if set(cells) != set(COLUMNS):
            raise WorkbookRefused(f"DATA row {number} does not hold exactly the five columns")
        count[0] += 1
        if count[0] > MAX_ROWS:
            raise WorkbookRefused("The DATA sheet has more rows than this reader accepts")
        observed = text_of(cells["A"], f"DATA cell A{number}")
        kind, style, serial = cells["B"]
        target, field = text_of(cells["C"], f"DATA cell C{number}"), text_of(cells["D"], f"DATA cell D{number}")
        raw = text_of(cells["E"], f"DATA cell E{number}")
        if not DAY.fullmatch(observed):
            raise WorkbookRefused(f"DATA row {number} has observation date {observed!r}, not YYYY-MM-DD")
        try:
            date.fromisoformat(observed)
        except ValueError:
            raise WorkbookRefused(f"DATA row {number} has observation date {observed!r}, not a calendar date") from None
        if kind not in (None, "n") or serial is None or not SERIAL.fullmatch(serial) or int(serial) < 61 or \
                style is None or not style.isdigit() or int(style) >= len(formats) or \
                not formats[int(style)].isdigit() or int(formats[int(style)]) not in DATE_FORMATS:
            raise WorkbookRefused(f"DATA row {number}'s reference start is not a whole date serial shown as a date")
        if target_range(target) is None:
            raise WorkbookRefused(f"DATA row {number} has target range {target!r}, not '<n>bps - <m>bps'")
        if not field.strip():
            raise WorkbookRefused(f"DATA row {number} names no statistic")
        if decimal_text(raw) is None:
            raise WorkbookRefused(f"DATA row {number} has value {raw!r}, not a plain decimal")
        key = (observed, serial, field)
        if key in seen:
            raise WorkbookRefused(f"DATA row {number} repeats {field!r} for observation {observed} and reference "
                                  f"start {serial_day(int(serial)).isoformat()}")
        seen.add(key)
        dates.add(observed)
        if observed in wanted:
            start = serial_day(int(serial)).isoformat()
            collected.setdefault(observed, {}).setdefault(start, {})[field] = {
                "row": number, "raw": raw, "target_range": target, "serial": int(serial)}
    reader = _Sheet(on_row)
    _parse(archive, infos, sheet, reader.start, reader.end, reader.text)
    if not header[0] or not count[0]:
        raise WorkbookRefused("The DATA sheet has no header or no rows after it")
    ordered = sorted(dates)
    return {"header": list(HEADER), "rows": count[0], "observation_dates": ordered, "first": ordered[0],
            "last": ordered[-1]}, collected

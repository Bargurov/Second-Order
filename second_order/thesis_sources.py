"""Retained copper-thesis sources (thesis-sources): each retained file checked against its acquisition record, read as
text or cells, and the place a figure or passage cites found in it. Reads only: nothing here fetches, writes or
classifies anything.

A source entry names an acquisition record, <root>/acquisitions/<approval_id>/outcome-<attempt>.json, and a retained
file, <root>/<folder>/<name>. The file is used only when the record states a complete acquisition with the entry's
approval, attempt (the record's n), address, SHA-256, size and retained path (data/sector-sources/copper/<folder>/
<name>); for a GET, HTTP 200, a complete-response hash, no other origin and body_completed_at equal to the entry's
retrieved_at; for a file the owner downloaded, origin owner_download, no HTTP status, an owner-file hash and
recorded_at equal to the entry's retrieved_at; and when the file's size and SHA-256 match. The source is otherwise
missing (the record or the file is absent) or changed (anything differs).

Readers. HTML becomes plain-text paragraphs: strict UTF-8 (a byte-order mark allowed), block elements break, hidden
elements and all markup are dropped, entities are decoded and whitespace is collapsed; a marked section html_markup
does not read makes the page unreadable. CSV becomes rows, decoded with
the source entry's declared encoding (ruling R13): strict UTF-8 (a byte-order mark allowed) or strict Windows-1252 (a
UTF-8 byte-order mark refused), never guessed; strict quoting. XLSX becomes {sheet: {cell: text}} for the sheets asked for
(thesis_workbook). A PDF is not read at all: a figure or passage from a PDF is a transcription, bound to the PDF by its
verified SHA-256. A reader that meets a limit refuses the whole file (Unreadable); content is never cut short and then
searched. Content is kept in memory for each retained file's current SHA-256 only.

Locating. An HTML figure or passage names a paragraph that holds its quote (and a figure's shown value lies in that
quote); an XLSX figure names a sheet, a cell and a label cell; a CSV figure names a data row, a column and a label
column of the header row. A label must read as stated; surrounding and repeated whitespace is not part of the
comparison. A text cell must print the figure's value exactly (thesis_arithmetic.shown_value, no exponent form); a
workbook's number cell must store a number that, rounded ROUND_HALF_EVEN to the exponent of the figure's value, equals
it (ruling R3: a stored "9123.4500000000007" or "1.2E-3" holds 9123.45 or 0.0012). A PDF figure or passage is not
checked against anything but the PDF's hash. A figure value that is not a plain decimal or a locator that cannot be
read is a problem, not an exception.
"""
import csv
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import io
from pathlib import Path
import re
import threading

from . import bis_snapshot, html_markup, thesis_rules, thesis_workbook
from .bis_snapshot import BLOCK_TAGS, HIDDEN_TAGS, sha256
from .thesis_arithmetic import _quantize, decimal_of, shown_value

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "data" / "sector-sources" / "copper"
SOURCES_REL = "data/sector-sources/copper"
KINDS = ("html", "xlsx", "csv", "pdf")
UTF8_BOM = bytes((0xEF, 0xBB, 0xBF))
CSV_ENCODINGS = ("utf-8", "windows-1252")  # What a CSV source entry may declare (ruling R13).
ORIGINS = ("get", "owner_download")
COMPLETED_AT = {"get": "body_completed_at", "owner_download": "recorded_at"}  # The record's retrieval-time field.
STORED_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")  # A finite number as a workbook stores it.
MAX_PARAGRAPHS = 60_000
MAX_CHARS = 8_000_000
MAX_SEGMENT = 200
QUOTE_SHOWN = 60


class Unreadable(ValueError):
    """A retained file that cannot be read whole as its kind; nothing in it is searched."""


# ---------------------------------------------------------------- verification against the acquisition record

def _segment(value: object, field: str) -> str:
    """One path segment: a plain folder or file name, never a path, "." or ".." (the thesis schema refuses others)."""
    if not isinstance(value, str) or not value or len(value) > MAX_SEGMENT or value in (".", "..") or \
            value != value.strip() or any(char in '/\\:' or ord(char) < 32 for char in value):
        raise ValueError(f"The source entry's {field} is not a single file or folder name")
    return value


def _state(name: str, detail: str) -> dict:
    if name not in thesis_rules.SOURCE_STATES:
        raise ValueError(f"unknown source state {name!r}")
    return {"state": name, "detail": detail}


def _same(found: object, expected: object) -> bool:
    return type(found) is type(expected) and found == expected


def verify(source: dict, root: Path) -> tuple[dict, bytes | None]:
    """({"state": "verified" | "changed" | "missing", "detail"}, the retained bytes when verified). Raises ValueError
    for an entry that does not name one retained file (the thesis schema refuses those first)."""
    folder, name = _segment(source["folder"], "folder"), _segment(source["name"], "name")
    approval, attempt = _segment(source["approval_id"], "approval_id"), source["attempt"]
    if type(attempt) is not int or attempt < 1:
        raise ValueError("The source entry's attempt is not a whole number of at least 1")
    if source["origin"] not in ORIGINS:
        raise ValueError(f"The source entry's origin is not one of {', '.join(ORIGINS)}")
    record_path = Path(root) / "acquisitions" / approval / f"outcome-{attempt}.json"
    path = Path(root) / folder / name
    if not record_path.is_file():
        return _state("missing", f"The acquisition record (approval {approval}, attempt {attempt}) is not on this "
                                 "machine; the retained file is not read."), None
    if not path.is_file():
        return _state("missing", f"The retained file {folder}/{name} is not on this machine."), None
    try:
        record = bis_snapshot._strict_json(record_path.read_text(encoding="utf-8"), "The acquisition record")
    except (OSError, UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        record = None
    if not isinstance(record, dict):
        return _state("changed", "The acquisition record cannot be read as one strict JSON object; the retained file "
                                 "is not used."), None
    expected = {"outcome": "complete", "approval_id": source["approval_id"], "n": attempt, "url": source["url"],
                "sha256": source["sha256"], "bytes": source["bytes"], "retained": f"{SOURCES_REL}/{folder}/{name}"}
    if source["origin"] == "get":
        expected.update({"http_status": 200, "hash_kind": "complete_response",
                         COMPLETED_AT["get"]: source["retrieved_at"]})
    else:
        expected.update({"origin": "owner_download", "http_status": None, "hash_kind": "owner_file",
                         COMPLETED_AT["owner_download"]: source["retrieved_at"]})
    disagree = [field for field, value in expected.items() if not _same(record.get(field), value)]
    if source["origin"] == "get" and record.get("origin", "get") != "get":
        disagree.append("origin")
    if disagree:
        return _state("changed", f"The acquisition record disagrees with this source on {', '.join(disagree)}; the "
                                 "retained file is not used."), None
    if path.stat().st_size != source["bytes"]:
        return _state("changed", "The retained file's size differs from its acquisition record; it is not read."), \
            None
    raw = path.read_bytes()
    if len(raw) != source["bytes"] or sha256(raw) != source["sha256"]:
        return _state("changed", "The retained file's size or SHA-256 differs from its acquisition record; it is not "
                                 "used."), None
    return _state("verified", "The retained file matches its acquisition record: attempt, address, retrieval time, "
                              "size and SHA-256."), raw


# ---------------------------------------------------------------- the readers

def _collapsed(text: str) -> str:
    """Whitespace runs and non-printable characters become one space; the ends are trimmed."""
    text = " ".join(text.split())
    if not text.isprintable():
        text = " ".join("".join(char if char.isprintable() else " " for char in text).split())
    return text


class _Paragraphs(HTMLParser):
    """Plain-text paragraphs of a whole HTML document, refusing (never cutting) past MAX_PARAGRAPHS or MAX_CHARS.
    Nothing is executed or loaded."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.parts, self.hidden, self.chars = [], [], 0, 0

    def flush(self):
        text = _collapsed("".join(self.parts))
        self.parts = []
        if not text:
            return
        if len(self.out) >= MAX_PARAGRAPHS:
            raise Unreadable(f"The page has more than {MAX_PARAGRAPHS} paragraphs; it is not read in part")
        if self.chars + len(text) > MAX_CHARS:
            raise Unreadable(f"The page's text is longer than {MAX_CHARS} characters; it is not read in part")
        self.out.append(text)
        self.chars += len(text)

    def handle_starttag(self, tag, attrs):
        if tag in HIDDEN_TAGS:
            self.hidden += 1
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag in HIDDEN_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_paragraphs(raw: bytes) -> list[str]:
    """Every plain-text paragraph of a retained HTML page. Raises Unreadable; never returns part of a page."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unreadable("The page is not UTF-8 text") from None
    if html_markup.unreadable(text):  # The rule comes before the parser, so every Python version gives one answer.
        raise Unreadable("The page has markup that cannot be read as plain text")
    parser = _Paragraphs()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:  # A refusal html.parser itself still raises (none is known once the rule has passed).
        raise Unreadable("The page has markup that cannot be read as plain text") from None
    parser.flush()
    return parser.out


def csv_rows(raw: bytes, encoding: str = "utf-8") -> list[list[str]]:
    """Every row of a retained CSV file (row 1 is the header), decoded with the declared ``encoding`` (CSV_ENCODINGS):
    strict UTF-8 with a byte-order mark allowed, or strict Windows-1252 (the codec refuses its five undefined bytes) with
    a UTF-8 byte-order mark refused rather than read as "ï»¿". Never guessed, never falls back. Raises Unreadable; an
    encoding not in CSV_ENCODINGS is a ValueError (the thesis schema refuses it first)."""
    if encoding not in CSV_ENCODINGS:
        raise ValueError(f"The CSV encoding {encoding!r} is not one of {', '.join(CSV_ENCODINGS)}")
    if encoding == "windows-1252" and raw.startswith(UTF8_BOM):
        raise Unreadable("The file starts with a UTF-8 byte-order mark but is declared Windows-1252 text")
    try:
        text = raw.decode("utf-8-sig" if encoding == "utf-8" else "cp1252")
    except UnicodeDecodeError:
        raise Unreadable(f"The file is not {'UTF-8' if encoding == 'utf-8' else 'Windows-1252'} text") from None
    try:
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise Unreadable(f"The file cannot be read as CSV ({exc})") from None


# ---------------------------------------------------------------- content, memoized per SHA-256

# retained folder/name -> {"sha256", "kind", "encoding" (a CSV's declared encoding, else None), "refused": why the
# bytes as a whole cannot be read (or None), "held": the paragraphs or rows (for a workbook, True once the checks shared
# by all its sheets passed), "sheets": {sheet: cells, or None when the workbook has no such sheet}, "sheet_refused":
# {sheet: why that sheet's own part cannot be read}}. Every stored outcome is a function of the bytes, the kind and the
# declared encoding (and, per sheet, of that sheet) alone, so no read depends on which reads came before it.
_MEMO: dict[str, dict] = {}
_MEMO_LOCK = threading.Lock()


def _unknown(entry: dict, wanted: list[str]) -> list[str]:
    return [sheet for sheet in wanted if sheet not in entry["sheets"] and sheet not in entry["sheet_refused"]]


def _filled(entry: dict, kind: str, raw: bytes, wanted: list[str], encoding: str | None = None) -> dict:
    """A new memo entry with this read's outcomes added, refusals included."""
    entry = {**entry, "sheets": dict(entry["sheets"]), "sheet_refused": dict(entry["sheet_refused"])}
    try:
        if kind == "html":
            entry["held"] = html_paragraphs(raw)
        elif kind == "csv":
            entry["held"] = csv_rows(raw, encoding)
        else:
            missing = _unknown(entry, wanted)
            found, refused = thesis_workbook.read_sheets(raw, missing)
            entry["held"] = True
            entry["sheets"].update({sheet: found.get(sheet) for sheet in missing if sheet not in refused})
            entry["sheet_refused"].update(refused)
    except Unreadable as exc:
        entry["refused"] = str(exc)
    except thesis_workbook.WorkbookRefused as exc:
        entry["refused"] = f"The workbook cannot be read: {exc}"
    return entry


def content(source: dict, raw: bytes, sheets=()) -> object:
    """What a verified file holds: HTML paragraphs, CSV rows, {sheet: cells} for the named ``sheets`` the workbook has
    (the sheets its figures name; number cells are thesis_workbook.Number), or None for a PDF. Kept per retained file
    for its current SHA-256 only; a new SHA-256 replaces the old. Raises Unreadable when the bytes cannot be read as a
    whole (a workbook's archive-wide checks run whatever sheets are named) or a named sheet's own part cannot be read;
    refusals are kept like content, per SHA-256 and, for one sheet, per sheet."""
    kind = source["kind"]
    if kind not in KINDS:
        raise ValueError(f"The source kind {kind!r} is not one of {', '.join(KINDS)}")
    if kind == "pdf":
        return None
    digest, slot = sha256(raw), f"{source['folder']}/{source['name']}"
    encoding = source["encoding"] if kind == "csv" else None
    wanted = list(dict.fromkeys(sheets)) if kind == "xlsx" else []
    with _MEMO_LOCK:
        entry = _MEMO.get(slot)
    if entry is None or (entry["sha256"], entry["kind"], entry["encoding"]) != (digest, kind, encoding):
        entry = {"sha256": digest, "kind": kind, "encoding": encoding, "refused": None, "held": None, "sheets": {},
                 "sheet_refused": {}}
    if entry["refused"] is None and (entry["held"] is None or _unknown(entry, wanted)):
        entry = _filled(entry, kind, raw, wanted, encoding)
        with _MEMO_LOCK:
            _MEMO[slot] = entry
    if entry["refused"] is not None:
        raise Unreadable(entry["refused"])
    if kind != "xlsx":
        return entry["held"]
    for sheet in wanted:
        if sheet in entry["sheet_refused"]:
            raise Unreadable(f"Sheet “{sheet}” cannot be read: {entry['sheet_refused'][sheet]}")
    return {sheet: entry["sheets"][sheet] for sheet in wanted if entry["sheets"][sheet] is not None}


# ---------------------------------------------------------------- locating a figure or passage

def _plain(text: str) -> str:
    return " ".join(text.split())


def _shortened(quote: str) -> str:
    return quote if len(quote) <= QUOTE_SHOWN else quote[:QUOTE_SHOWN] + "…"


def _label(place: str, text: str | None, label: str) -> list[str]:
    if text is None or not text.strip():
        return [f"{place} is empty; it should read “{label}”"]
    return [] if _plain(text) == _plain(label) else [f"{place} no longer reads “{label}”"]


def _stored(text: str, target: Decimal) -> Decimal | None:
    """A workbook's stored number at the figure's precision: Decimal(stored text) rounded ROUND_HALF_EVEN to the
    exponent of the figure's value, so a binary-float artefact ("9123.4500000000007") or exponent form ("1.2E-3")
    reads as the number it stores. None when the text is not a finite stored number."""
    if not STORED_NUMBER.fullmatch(text):
        return None
    try:
        return _quantize(Decimal(text), Decimal(1).scaleb(target.as_tuple().exponent))
    except InvalidOperation:
        return None


def _value(place: str, text: str | None, value: str) -> list[str]:
    """A number cell (thesis_workbook.Number) is read as a stored number; any other text as a printed figure
    (thesis_arithmetic.shown_value: no exponent form). The figure's value is a plain decimal (locate checks it)."""
    if text is None or not text.strip():
        return [f"{place} is empty; it should hold {value}"]
    target = decimal_of(value)
    if isinstance(text, thesis_workbook.Number):
        found = _stored(text.strip(), target)
    else:
        try:
            found = shown_value(text.strip())
        except ValueError:
            found = None
    if found is None:
        return [f"{place} no longer holds a number"]
    return [] if found == target else [f"{place} no longer holds {value}"]


def _in_page(item: dict, paragraphs: list[str]) -> list[str]:
    number, quote = item["locator"]["paragraph"], item["locator"]["quote"]
    if type(number) is not int or not 1 <= number <= len(paragraphs):
        return [f"Paragraph {number} is not in the retained page, which has {len(paragraphs)} paragraphs"]
    problems = []
    if quote not in paragraphs[number - 1]:
        problems.append(f"Paragraph {number} no longer holds the quoted passage “{_shortened(quote)}”")
    if "value" in item and item["as_shown"] not in quote:
        problems.append(f"The quoted passage does not show “{item['as_shown']}”")
    return problems


def _in_workbook(item: dict, sheets: dict) -> list[str]:
    where = item["locator"]
    sheet = where["sheet"]
    cells = sheets.get(sheet) if isinstance(sheets, dict) else None
    if cells is None:
        return [f"Sheet “{sheet}” is not in the retained workbook"]
    return (_label(f"Cell {where['label_cell']} on sheet {sheet}", cells.get(where["label_cell"]), where["label"])
            + _value(f"Cell {where['cell']} on sheet {sheet}", cells.get(where["cell"]), item["value"]))


def _in_rows(item: dict, rows: list[list[str]]) -> list[str]:
    where = item["locator"]
    if not rows:
        return ["The retained file has no header row"]
    header = [_plain(name) for name in rows[0]]
    problems = []
    for name in (where["label_column"], where["column"]):
        count = header.count(_plain(name))
        if count == 0:
            problems.append(f"Row 1 does not name the column “{name}”")
        elif count > 1:
            problems.append(f"Row 1 names the column “{name}” {count} times")
    if problems:
        return problems
    number = where["row"]
    if type(number) is not int or number < 2:
        return [f"Row {number} is not a data row"]
    if number > len(rows):
        return [f"Row {number} is not in the retained file, which has {len(rows)} rows"]
    values = rows[number - 1]

    def at(name: str) -> str | None:
        index = header.index(_plain(name))
        return values[index] if index < len(values) else None
    return (_label(f"Row {number}, column {where['label_column']}", at(where["label_column"]), where["label"])
            + _value(f"Row {number}, column {where['column']}", at(where["column"]), item["value"]))


def locate(item: dict, source: dict, held: object) -> list[str]:
    """The problems of one figure (it has a "value") or passage in its verified source's content: one string for
    each thing not found where the locator places it; empty when everything is found. Fail-closed on its own: a figure
    value that is not a plain decimal, or a locator that cannot be read, is a problem, never an exception."""
    kind = source["kind"]
    if kind not in KINDS:
        raise ValueError(f"The source kind {kind!r} is not one of {', '.join(KINDS)}")
    if "value" in item:
        try:
            decimal_of(item["value"])
        except ValueError:
            return [f"The figure's value “{item['value']}” is not a plain decimal"]
    elif kind not in ("html", "pdf"):
        return [f"A passage quotes an HTML page or a PDF; {source['id']} is neither"]
    if kind == "pdf":
        return []  # A transcription: bound to the PDF by its verified SHA-256; nothing here reads the PDF.
    try:
        if kind == "html":
            return _in_page(item, held)
        if kind == "xlsx":
            return _in_workbook(item, held)
        return _in_rows(item, held)
    except (KeyError, TypeError, AttributeError):
        return [f"The locator of “{item.get('id')}” cannot be read"]

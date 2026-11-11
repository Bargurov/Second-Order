"""SYNTHETIC workbooks in the shape of the Atlanta Fed Market Probability Tracker's historical data (mpt_histdata.xlsx),
for the rate-path tests and browser checks.

The structure follows the real workbook so the reader is exercised as it will be used: LICENSE with its text in a
drawing's text box, DICTIONARY with a description and one definition per row (a statistic listed twice, as in the real
one), DATA with one statistic per row, text cells as shared strings, value cells padded with spaces and reference starts
as date serials. Every number is made up: no row is a market estimate, and the dates only stand around a synthetic
statement published on 16 September 2026.
"""
from datetime import date
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from second_order import rate_workbook  # noqa: E402

OBSERVATIONS = ("2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17")
STARTS = (date(2026, 12, 16), date(2027, 3, 17), date(2027, 6, 16), date(2027, 9, 15), date(2027, 12, 15))
FIELDS = ("Rate: 25th percentile", "Rate: mean", "Rate: mode", "Rate: 75th percentile", "Prob: cut", "Prob: hike")
DICTIONARY_ORDER = ("date", "reference_start", "target_range", "field", "Rate: 25th percentile", "Rate: mean",
                    "Rate: mode", "Rate: mean", "Rate: 75th percentile", "Prob: cut", "Prob: hike",
                    "Prob: various 25bps ranges", "value")
EXTRA_DEFINITIONS = {
    "Rate: mode": "SYNTHETIC definition of the mode statistic.",
    "Prob: various 25bps ranges": "SYNTHETIC definition of the 25bps-range probabilities.",
}
LICENSE = ("SYNTHETIC: market data notice for a test workbook.", rate_workbook.LICENSE_STATEMENT, "",
           "SYNTHETIC: warranty disclaimer for a test workbook.")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
MAIN = rate_workbook.MAIN


def value_text(value: Decimal) -> str:
    return f"{value:>7.2f}"  # Padded on the left, as the real workbook's value cells are.


def statistics(day_index: int, window: int) -> dict:
    """SYNTHETIC values for one observation and window: a made-up mean, percentiles around it, probabilities."""
    mean = Decimal("312.50") + 9 * window + day_index
    return {"Rate: 25th percentile": mean - Decimal("18.75"), "Rate: mean": mean, "Rate: mode": mean - 2,
            "Rate: 75th percentile": mean + Decimal("21.25"), "Prob: cut": Decimal("4.00") + window,
            "Prob: hike": Decimal("61.50") - window}


def standard_rows(observations=OBSERVATIONS, starts=STARTS, skip=(), changes=None) -> list[tuple]:
    """DATA rows for every observation and window. ``skip`` leaves out (date, start ISO, field) rows; ``changes``
    replaces the value text of (date, start ISO, field)."""
    rows = []
    for day_index, day in enumerate(observations):
        target = "300bps - 325bps" if day < "2026-09-16" else "325bps - 350bps"
        for window, start in enumerate(starts):
            for field, value in statistics(day_index, window).items():
                key = (day, start.isoformat(), field)
                if key not in skip:
                    rows.append((day, start, target, field, (changes or {}).get(key, value_text(value))))
            rows.append((day, start, target, "Prob: 300bps - 325bps", "  20.00"))
    return rows


def _cell(reference: str, value, strings) -> str:
    if isinstance(value, date):
        return f'<c r="{reference}" s="1" t="n"><v>{(value - rate_workbook.EPOCH).days}</v></c>'
    if isinstance(value, int):
        return f'<c r="{reference}" s="1" t="n"><v>{value}</v></c>'
    return f'<c r="{reference}" t="s"><v>{strings(value)}</v></c>'


def dictionary_entries(definitions: dict | None = None) -> list[tuple[str, str | None]]:
    """The DICTIONARY's (name, definition) rows in the real workbook's order; ``definitions`` replaces (or, with None,
    drops) some of them."""
    meanings = {**rate_workbook.DEFINITIONS, **EXTRA_DEFINITIONS, **(definitions or {})}
    return [(name, meanings.get(name)) for name in DICTIONARY_ORDER]


def workbook(rows: list[tuple], *, header=rate_workbook.HEADER, definitions: dict | None = None,
             entries: list[tuple[str, str | None]] | None = None, description: str = rate_workbook.DESCRIPTION,
             license: tuple = LICENSE, sheets=rate_workbook.SHEETS, date1904: bool = False,
             reference_format: int = 14, doctype: bool = False, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """The bytes of one SYNTHETIC workbook. ``definitions`` replaces (or, with None, drops) dictionary definitions;
    ``entries`` gives the dictionary rows outright."""
    table, index = [], {}

    def strings(text: str) -> int:
        if text not in index:
            index[text] = len(table)
            table.append(text)
        return index[text]

    data = []
    for number, row in enumerate([tuple(header)] + list(rows), start=1):
        cells = "".join(_cell(f"{column}{number}", value, strings)
                        for column, value in zip(rate_workbook.COLUMNS, row) if value is not ...)
        data.append(f'<row r="{number}">{cells}</row>')
    dictionary = [f'<row r="2"><c r="B2" t="s"><v>{strings(description)}</v></c><c r="C2" s="0"/></row>']
    for number, (name, meaning) in enumerate(entries or dictionary_entries(definitions), start=7):
        if meaning is ...:  # A name without its definition cell.
            dictionary.append(f'<row r="{number}"><c r="B{number}" t="s"><v>{strings(name)}</v></c></row>')
        elif meaning is not None:
            dictionary.append(f'<row r="{number}"><c r="B{number}" t="s"><v>{strings(name)}</v></c>'
                              f'<c r="C{number}" t="s"><v>{strings(meaning)}</v></c></row>')

    def sheet(rows_xml: list[str], drawing: bool = False) -> str:
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{MAIN}" '
                f'xmlns:r="{rate_workbook.OFFICE_RELS}"><dimension ref="A1"/><sheetData>{"".join(rows_xml)}</sheetData>'
                f'{"<drawing r:id=" + chr(34) + "rId1" + chr(34) + "/>" if drawing else ""}</worksheet>')

    paragraphs = []
    for text in license:  # The statement in two runs: the reader joins runs within a paragraph.
        half = len(text) // 2
        runs = [text[:half], text[half:]] if text else []
        paragraphs.append("<a:p>" + "".join(f"<a:r><a:t>{escape(run)}</a:t></a:r>" for run in runs) + "</a:p>")
    shared = "".join(f'<si><t xml:space="preserve">{escape(text)}</t></si>' for text in table)
    prolog = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    doctype_text = '<!DOCTYPE sst [<!ENTITY x "synthetic">]>' if doctype else ""
    parts = {
        "[Content_Types].xml": f'{prolog}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": f'{prolog}<Relationships xmlns="{rate_workbook.PACKAGE_RELS}"/>',
        "xl/workbook.xml": (f'{prolog}<workbook xmlns="{MAIN}" xmlns:r="{rate_workbook.OFFICE_RELS}">'
                            f'<workbookPr{" date1904=" + chr(34) + "1" + chr(34) if date1904 else ""}/><sheets>'
                            + "".join(f'<sheet name="{name}" sheetId="{n + 2}" r:id="rId{n + 1}"/>'
                                      for n, name in enumerate(sheets)) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            f'{prolog}<Relationships xmlns="{rate_workbook.PACKAGE_RELS}">'
            + "".join(f'<Relationship Id="rId{n}" Type="{rate_workbook.OFFICE_RELS}/worksheet" '
                      f'Target="worksheets/sheet{n}.xml"/>' for n in (1, 2, 3))
            + f'<Relationship Id="rId4" Type="{rate_workbook.OFFICE_RELS}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rId5" Type="{rate_workbook.OFFICE_RELS}/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"),
        "xl/styles.xml": (f'{prolog}<styleSheet xmlns="{MAIN}"><cellXfs count="2"><xf numFmtId="0"/>'
                          f'<xf numFmtId="{reference_format}" applyNumberFormat="1"/></cellXfs></styleSheet>'),
        "xl/sharedStrings.xml": f'{prolog}{doctype_text}<sst xmlns="{MAIN}" count="{len(table)}">{shared}</sst>',
        "xl/worksheets/sheet1.xml": sheet(['<row r="1"><c r="A1" s="0"/></row>'], drawing=True),
        "xl/worksheets/_rels/sheet1.xml.rels": (
            f'{prolog}<Relationships xmlns="{rate_workbook.PACKAGE_RELS}"><Relationship Id="rId1" '
            f'Type="{rate_workbook.OFFICE_RELS}/drawing" Target="../drawings/drawing1.xml"/></Relationships>'),
        "xl/drawings/drawing1.xml": (
            f'{prolog}<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            f'xmlns:a="{rate_workbook.DRAWING_TEXT}"><xdr:twoCellAnchor><xdr:sp><xdr:txBody>'
            + "".join(paragraphs) + "</xdr:txBody></xdr:sp></xdr:twoCellAnchor></xdr:wsDr>"),
        "xl/worksheets/sheet2.xml": sheet(dictionary),
        "xl/worksheets/sheet3.xml": sheet(data),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            archive.writestr(zipfile.ZipInfo(name, FIXED_TIME), text.encode("utf-8"), compress_type=compression)
    return buffer.getvalue()


def write(path: Path, rows: list[tuple] | None = None, **options) -> str:
    """Write a SYNTHETIC workbook (the standard rows unless given) and return its SHA-256."""
    data = workbook(standard_rows() if rows is None else rows, **options)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()

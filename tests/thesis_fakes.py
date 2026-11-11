"""SYNTHETIC copper-thesis sources for the thesis tests: retained files and the acquisition records that describe them
exactly, in the shape thesis_sources reads. Every file says "Synthetic" and every number in it is made up; no file is a
copy of, or stands for, any publication. Addresses are under example.org.

Sources part (Task 4): one retained file per folder, so each source id equals its folder name. GET-origin files are
recorded under approval synthetic-copper-01 and the two dataset editions the owner downloads under
synthetic-copper-owner-01, attempts numbered 1..n within each approval.

Thesis part (Task 5): a SYNTHETIC thesis, synthetic-copper, in two versions whose every figure and passage is found in
the synthetic sources above, and a writer for its index and version files.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from second_order import rate_workbook  # noqa: E402

RETAINED = "data/sector-sources/copper"  # Stated here, not imported: the fakes state the contract independently.
GET_APPROVAL = "synthetic-copper-01"
OWNER_APPROVAL = "synthetic-copper-owner-01"
TERMS = {"licence": "Synthetic test terms", "note": "Synthetic: made-up terms for tests; no real source."}
# The PDF's transcribed pages: exactly the pages the synthetic thesis cites from it (ruling R6), the figure on page 1 and
# the passage on page 2.
TRANSCRIBED_PAGES = (1, 2)
TRANSCRIBED = "transcribed from the page image"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
PROLOG = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")  # Written as a number cell, exponent form included.
SOURCE_FIELDS = ("id", "kind", "origin", "publisher", "title", "series", "edition", "edition_date", "url",
                 "approval_id", "attempt", "folder", "name", "sha256", "bytes", "retrieved_at", "terms",
                 "transcription", "encoding")


# ---------------------------------------------------------------- a minimal XLSX

def _position(reference: str) -> tuple[int, int]:
    """(row, column number) of a cell reference such as "AB12"."""
    letters = reference.rstrip("0123456789")
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - 64
    return int(reference[len(letters):]), column


def workbook(sheets: dict[str, dict[str, str]], *, doctype: bool = False, inline: bool = False) -> bytes:
    """The bytes of a minimal SYNTHETIC workbook: one worksheet per entry, in order. A value that is a plain decimal
    (or a decimal in exponent form, as workbooks store some numbers) is a number cell (<v>); any other text is a shared
    string, or an inline string with ``inline``. ``doctype`` puts a
    DOCTYPE with an entity declaration into the shared-strings part."""
    table, index = [], {}

    def shared(text: str) -> int:
        if text not in index:
            index[text] = len(table)
            table.append(text)
        return index[text]

    def cell(reference: str, text: str) -> str:
        if NUMBER.fullmatch(text):
            return f'<c r="{reference}"><v>{text}</v></c>'
        if inline:
            return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
        return f'<c r="{reference}" t="s"><v>{shared(text)}</v></c>'

    worksheets = {}
    for number, cells in enumerate(sheets.values(), start=1):
        rows: dict[int, list[str]] = {}
        for reference in sorted(cells, key=_position):
            rows.setdefault(_position(reference)[0], []).append(cell(reference, cells[reference]))
        data = "".join(f'<row r="{row}">{"".join(items)}</row>' for row, items in sorted(rows.items()))
        worksheets[f"xl/worksheets/sheet{number}.xml"] = (f'{PROLOG}<worksheet xmlns="{rate_workbook.MAIN}">'
                                                          f'<sheetData>{data}</sheetData></worksheet>')
    office, package = rate_workbook.OFFICE_RELS, rate_workbook.PACKAGE_RELS
    strings = "".join(f'<si><t xml:space="preserve">{escape(text)}</t></si>' for text in table)
    declaration = '<!DOCTYPE sst [<!ENTITY x "synthetic">]>' if doctype else ""
    parts = {
        "[Content_Types].xml": f'{PROLOG}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": (f'{PROLOG}<Relationships xmlns="{package}"><Relationship Id="rId1" '
                        f'Type="{office}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (f'{PROLOG}<workbook xmlns="{rate_workbook.MAIN}" xmlns:r="{office}"><sheets>'
                            + "".join(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>'
                                      for n, name in enumerate(sheets, start=1)) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            f'{PROLOG}<Relationships xmlns="{package}">'
            + "".join(f'<Relationship Id="rId{n}" Type="{office}/worksheet" Target="worksheets/sheet{n}.xml"/>'
                      for n in range(1, len(sheets) + 1))
            + f'<Relationship Id="rIdStrings" Type="{office}/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"),
        "xl/sharedStrings.xml": (f'{PROLOG}{declaration}<sst xmlns="{rate_workbook.MAIN}" count="{len(table)}">'
                                 f'{strings}</sst>'),
        **worksheets,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            archive.writestr(zip_entry(name), text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def zip_entry(name: str, when: tuple = FIXED_TIME) -> zipfile.ZipInfo:
    """An entry whose header bytes are the same on every platform. zipfile takes the "made by" system from the machine
    (0, MS-DOS, on Windows; 3, Unix, elsewhere); it is fixed at 0, the value the committed fixtures and records hold."""
    info = zipfile.ZipInfo(name, when)
    info.create_system = 0
    return info


# ---------------------------------------------------------------- the synthetic files

USGS_COLUMNS = ("Source", "Commodity", "Year", "World mine production (kt)", "World refinery production (kt)")
USGS = {  # Edition -> (year, world mine production, world refinery production), all made up.
    2026: (("2021", "21,200", "24,700"), ("2022", "21,900", "25,500"), ("2023", "22,400", "26,600"),
           ("2024", "22,900", "27,300"), ("2025", "23,300", "28,000")),
    2025: (("2020", "20,600", "24,500"), ("2021", "21,100", "24,800"), ("2022", "21,900", "25,400"),
           ("2023", "22,300", "26,500"), ("2024", "22,700", "27,100")),
}
IEA_LINES = (("Demand", "Synthetic clean technologies"), ("Demand", "Synthetic other uses"), ("Demand", "Total demand"),
             ("Supply", "Synthetic primary supply"), ("Supply", "Synthetic secondary supply"),
             ("Supply", "Total supply"))
IEA = {  # Edition -> (years, one value per line and year in kt), all made up; each total is the sum of its lines.
    2026: (("2025", "2030", "2035"), (("7300", "10100", "12300"), ("19200", "19400", "19500"),
                                      ("26500", "29500", "31800"), ("21900", "23900", "24600"),
                                      ("4100", "4800", "5600"), ("26000", "28700", "30200"))),
    2025: (("2024", "2030", "2035"), (("6900", "9400", "11800"), ("19100", "19350", "19600"),
                                      ("26000", "28750", "31400"), ("21500", "24800", "25100"),
                                      ("4000", "4300", "5000"), ("25500", "29100", "30100"))),
}
IEA_SCENARIO = "Synthetic STEPS"
PINK = (("2026M08", "9180.25", "2410.5"), ("2026M09", "9342.5", "2455"), ("2026M10", "9500", "2498.75"))
PRODUCER = {2025: ("2026", "4,120", "410"), 2024: ("2025", "3,980", "380")}  # Year -> (next year, pounds, $ million).
PDF = b"%PDF-1.7 Synthetic\n"


def usgs_csv(edition: int) -> bytes:
    """A SYNTHETIC copper data release: one row per year, grouped figures quoted, CRLF line endings."""
    lines = [",".join(USGS_COLUMNS)]
    for year, mine, refinery in USGS[edition]:
        lines.append(f'Synthetic USGS Mineral Commodity Summaries {edition},Copper,{year},"{mine}","{refinery}"')
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def iea_sheets(edition: int) -> dict[str, dict[str, str]]:
    """The SYNTHETIC dataset edition's sheets: Copper (one scenario, demand and supply lines and totals) and Notes."""
    years, values = IEA[edition]
    copper = {"A1": f"Synthetic Critical Minerals Dataset {edition}: copper, thousand tonnes (kt)",
              "A2": "Scenario", "B2": "Category", "C2": "Line", "D2": years[0], "E2": years[1], "F2": years[2]}
    for row, ((category, line), numbers) in enumerate(zip(IEA_LINES, values), start=3):
        copper.update({f"A{row}": IEA_SCENARIO, f"B{row}": category, f"C{row}": line})
        copper.update({f"{column}{row}": number for column, number in zip("DEF", numbers)})
    return {"Copper": copper, "Notes": {"A1": "Synthetic: every number in this workbook is made up."}}


def pink_sheets() -> dict[str, dict[str, str]]:
    """The SYNTHETIC monthly price workbook: months in column A, copper in column B, aluminum in column C."""
    prices = {"A1": "Synthetic World Bank Commodity Price Data (The Pink Sheet)",
              "A2": "Synthetic: monthly prices in nominal US dollars, all made up",
              "B4": "Synthetic Copper", "C4": "Synthetic Aluminum", "B5": "($/mt)", "C5": "($/mt)"}
    for row, (month, copper, aluminum) in enumerate(PINK, start=6):
        prices.update({f"A{row}": month, f"B{row}": copper, f"C{row}": aluminum})
    return {"Monthly Prices": prices}


def producer_html(year: int) -> bytes:
    """A SYNTHETIC producer annual report that states a sensitivity per ten cents a pound."""
    following, pounds, effect = PRODUCER[year]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">\n'
        f"<head><title>Synthetic Producer Corp. Form 10-K {year}</title><style>p {{ margin: 0; }}</style>"
        '<script>var synthetic = "hidden";</script></head>\n<body>\n'
        "<div><p>Synthetic Producer Corp.</p>\n"
        f"<p>Annual report on Form 10-K for the fiscal year ended December 31, {year}. Synthetic: every number in "
        "this document is made up.</p></div>\n"
        f'<p>Synthetic copper sales were <span><ix:nonFraction name="synthetic:CopperSales" scale="6">{pounds}'
        f"</ix:nonFraction></span> million pounds in {year}.</p>\n"
        f"<p>Based on projected copper sales volumes for {following}, a change of $0.10&#160;per pound in copper "
        f"prices would have an approximate <b>${effect}</b> million effect on our annual operating cash flows.</p>\n"
        "<table><tr><td>Synthetic sensitivity</td><td>Change</td><td>Effect</td></tr>"
        f"<tr><td>Copper</td><td>$0.10 per pound</td><td>${effect} million</td></tr></table>\n"
        "</body>\n</html>\n").encode("utf-8")


def maker_html() -> bytes:
    """A SYNTHETIC vehicle maker's annual report that states an average selling price."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head><title>Synthetic Maker Inc. Form 10-K 2025</title></head>\n<body>\n"
        "<p>Synthetic Maker Inc.</p>\n"
        "<p>Annual report on Form 10-K for the fiscal year ended December 31, 2025. Synthetic: every number in this "
        "document is made up.</p>\n"
        "<p>The average selling price of our Synthetic vehicles was $45,000 in 2025.</p>\n"
        "<p>Our purchases of copper and copper products were approximately $95 million in 2025.</p>\n"
        "<p>We delivered 210,000 Synthetic vehicles in 2025.</p>\n"
        "</body>\n</html>\n").encode("utf-8")


# ---------------------------------------------------------------- the retained sources

SOURCES = {  # folder -> the entry's descriptive fields; one file per folder, in the order source_entries lists them.
    "usgs-2026": {"name": "copper.csv", "kind": "csv", "origin": "get", "attempt": 1, "publisher": "Synthetic USGS",
                  "title": "Synthetic Mineral Commodity Summaries 2026: copper data release",
                  "series": "synthetic-usgs-mcs", "edition": "2026", "edition_date": "2026-01-30"},
    "usgs-2025": {"name": "copper.csv", "kind": "csv", "origin": "get", "attempt": 2, "publisher": "Synthetic USGS",
                  "title": "Synthetic Mineral Commodity Summaries 2025: copper data release",
                  "series": "synthetic-usgs-mcs", "edition": "2025", "edition_date": "2025-01-31"},
    "iea-2026": {"name": "dataset.xlsx", "kind": "xlsx", "origin": "owner_download", "attempt": 1,
                 "publisher": "Synthetic IEA", "title": "Synthetic Critical Minerals Dataset 2026",
                 "series": "synthetic-iea-dataset", "edition": "2026", "edition_date": "2026-07-15"},
    "iea-2025": {"name": "dataset.xlsx", "kind": "xlsx", "origin": "owner_download", "attempt": 2,
                 "publisher": "Synthetic IEA", "title": "Synthetic Critical Minerals Dataset 2025",
                 "series": "synthetic-iea-dataset", "edition": "2025", "edition_date": "2025-05-21"},
    "worldbank": {"name": "pink.xlsx", "kind": "xlsx", "origin": "get", "attempt": 3,
                  "publisher": "Synthetic World Bank", "title": "Synthetic Commodity Price Data (The Pink Sheet)",
                  "series": "synthetic-worldbank-pink", "edition": "November 2026", "edition_date": "2026-11-02"},
    "iea-2021": {"name": "report.pdf", "kind": "pdf", "origin": "get", "attempt": 4, "publisher": "Synthetic IEA",
                 "title": "Synthetic report on minerals in clean energy transitions",
                 "series": "synthetic-iea-2021-report", "edition": "2021", "edition_date": "2021-05-05"},
    "sec-producer-2025": {"name": "10k.htm", "kind": "html", "origin": "get", "attempt": 5,
                          "publisher": "Synthetic Producer Corp.",
                          "title": "Synthetic annual report on Form 10-K, fiscal 2025",
                          "series": "synthetic-producer-10k", "edition": "Fiscal 2025", "edition_date": "2026-02-13"},
    "sec-producer-2024": {"name": "10k.htm", "kind": "html", "origin": "get", "attempt": 6,
                          "publisher": "Synthetic Producer Corp.",
                          "title": "Synthetic annual report on Form 10-K, fiscal 2024",
                          "series": "synthetic-producer-10k", "edition": "Fiscal 2024", "edition_date": "2025-02-14"},
    "sec-maker-2025": {"name": "10k.htm", "kind": "html", "origin": "get", "attempt": 7,
                       "publisher": "Synthetic Maker Inc.", "title": "Synthetic annual report on Form 10-K, fiscal 2025",
                       "series": "synthetic-maker-10k", "edition": "Fiscal 2025", "edition_date": "2026-01-29"},
}


def source_bytes(folder: str) -> bytes:
    """The SYNTHETIC file a folder retains, as write_sources writes it."""
    return {"usgs-2026": lambda: usgs_csv(2026), "usgs-2025": lambda: usgs_csv(2025),
            "iea-2026": lambda: workbook(iea_sheets(2026)), "iea-2025": lambda: workbook(iea_sheets(2025)),
            "worldbank": lambda: workbook(pink_sheets()), "iea-2021": lambda: PDF,
            "sec-producer-2025": lambda: producer_html(2025), "sec-producer-2024": lambda: producer_html(2024),
            "sec-maker-2025": maker_html}[folder]()


def url(folder: str) -> str:
    """The made-up address of a source; the two dataset editions share the page the owner downloads them from."""
    if SOURCES[folder]["origin"] == "owner_download":
        return "https://example.org/synthetic/iea-critical-minerals-dataset"
    return f"https://example.org/synthetic/{folder}/{SOURCES[folder]['name']}"


def retrieved_at(folder: str) -> str:
    spec = SOURCES[folder]
    return f"2026-11-02T{8 if spec['origin'] == 'owner_download' else 9:02d}:{spec['attempt']:02d}:00+00:00"


def approval(folder: str) -> str:
    return OWNER_APPROVAL if SOURCES[folder]["origin"] == "owner_download" else GET_APPROVAL


def record_path(root: Path, folder: str) -> Path:
    return root / "acquisitions" / approval(folder) / f"outcome-{SOURCES[folder]['attempt']}.json"


def outcome(folder: str, data: bytes) -> dict:
    """The acquisition record that describes ``data`` retained in ``folder`` exactly."""
    spec = SOURCES[folder]
    record = {"approval_id": approval(folder), "n": spec["attempt"], "url": url(folder), "kind": spec["kind"],
              "outcome": "complete", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "retained": f"{RETAINED}/{folder}/{spec['name']}"}
    if spec["origin"] == "owner_download":
        return {**record, "origin": "owner_download", "http_status": None, "hash_kind": "owner_file",
                "recorded_at": retrieved_at(folder)}
    return {**record, "http_status": 200, "body_state": "fully_read", "hash_kind": "complete_response",
            "body_completed_at": retrieved_at(folder)}


def write_record(root: Path, folder: str, record: dict) -> None:
    path = record_path(root, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")


def retain(root: Path, folder: str, data: bytes) -> None:
    """Retain ``data`` as ``folder``'s file and record it (a re-recorded file verifies under its new SHA-256)."""
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / SOURCES[folder]["name"]).write_bytes(data)
    write_record(root, folder, outcome(folder, data))


def write_sources(root: Path) -> Path:
    """Every SYNTHETIC retained file under ``root/<folder>/<name>`` with its acquisition record; returns ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    for folder in SOURCES:
        retain(root, folder, source_bytes(folder))
    return root


def source_entries(root: Path) -> list[dict]:
    """The thesis file's ``sources[]`` entries for the files under ``root``, bound to their acquisition records."""
    entries = []
    for folder, spec in SOURCES.items():
        record = json.loads(record_path(root, folder).read_text(encoding="utf-8"))
        entries.append({
            "id": folder, "kind": spec["kind"], "origin": spec["origin"], "publisher": spec["publisher"],
            "title": spec["title"], "series": spec["series"], "edition": spec["edition"],
            "edition_date": spec["edition_date"], "url": url(folder), "approval_id": approval(folder),
            "attempt": spec["attempt"], "folder": folder, "name": spec["name"], "sha256": record["sha256"],
            "bytes": record["bytes"], "retrieved_at": retrieved_at(folder), "terms": dict(TERMS),
            "transcription": {"pages": list(TRANSCRIBED_PAGES), "method": TRANSCRIBED} if spec["kind"] == "pdf"
            else None, "encoding": "utf-8" if spec["kind"] == "csv" else None})
    return entries


# ---------------------------------------------------------------- the synthetic thesis

THESIS_ID = "synthetic-copper"
INDEX_VERSION = "thesis-index-0.1"  # Stated here, not imported, like RETAINED.
OPENED_ON = "2026-11-02"
V2_ON = "2026-11-16"
IEA_KEYS = ("clean", "other", "demand", "primary", "secondary", "supply")  # In the order of IEA_LINES.
IEA_MEASURES = ("Synthetic clean-technology demand", "Synthetic demand for other uses", "Synthetic total demand",
                "Synthetic primary supply", "Synthetic secondary supply", "Synthetic total supply")
USGS_KEYS = {"mine": (3, "Synthetic world mine production", "Synthetic mine output"),
             "refinery": (4, "Synthetic world refinery production", "Synthetic refined output")}
SENSITIVITY_QUOTE = ("Based on projected copper sales volumes for 2026, a change of $0.10 per pound in copper prices "
                     "would have an approximate $410 million effect on our annual operating cash flows.")


def _grouped(number: str) -> str:
    """A plain decimal as the synthetic sources print it: comma thousands ("9180.25" -> "9,180.25")."""
    whole, _, fraction = number.partition(".")
    return f"{int(whole):,}" + (f".{fraction}" if fraction else "")


def _figure(figure_id: str, source: str, measure: str, unit: str, value: str, as_shown: str, year: str | None,
            locator: dict, *, period: str | None = None, basis: str | None = None,
            scenario: str | None = None) -> dict:
    return {"id": figure_id, "source": source, "measure": measure, "unit": unit, "value": value, "as_shown": as_shown,
            "year": year, "period": period, "basis": basis, "scenario": scenario, "locator": locator}


def iea_figure(edition: int, key: str, year: str) -> dict:
    """One kt figure of a synthetic dataset edition's Copper sheet, e.g. iea26-demand-2025 (cell D5, "26,500")."""
    years, values = IEA[edition]
    line, column = IEA_KEYS.index(key), years.index(year)
    number = values[line][column]
    return _figure(f"iea{edition % 100}-{key}-{year}", f"iea-{edition}", IEA_MEASURES[line], "kt", number,
                   _grouped(number), year, {"sheet": "Copper", "cell": f"{'DEF'[column]}{line + 3}",
                                            "label_cell": f"C{line + 3}", "label": IEA_LINES[line][1]},
                   scenario=IEA_SCENARIO)


def usgs_figure(edition: int, key: str, year: str) -> dict:
    """One kt figure of a synthetic data release, e.g. usgs26-mine-2024 (row 5, "22,900")."""
    column, measure, basis = USGS_KEYS[key]
    years = [row[0] for row in USGS[edition]]
    shown = USGS[edition][years.index(year)][column - 2]
    return _figure(f"usgs{edition % 100}-{key}-{year}", f"usgs-{edition}", measure, "kt", shown.replace(",", ""),
                   shown, year, {"row": years.index(year) + 2, "column": USGS_COLUMNS[column], "label_column": "Year",
                                 "label": year}, basis=basis)


def price_figure(month: str) -> dict:
    """The synthetic monthly copper price of one month, e.g. wb-copper-2026m10 (cell B8, "9,500")."""
    months = [row[0] for row in PINK]
    value = PINK[months.index(month)][1]
    row = months.index(month) + 6
    return _figure(f"wb-copper-{month.lower()}", "worldbank", "Synthetic monthly copper price", "usd_per_tonne", value,
                   _grouped(value), month[:4], {"sheet": "Monthly Prices", "cell": f"B{row}", "label_cell": f"A{row}",
                                                "label": month}, period=month)


def _passage(passage_id: str, source: str, locator: dict) -> dict:
    return {"id": passage_id, "source": source, "locator": locator}


def _statement(status: str, text: str, *cites: str) -> dict:
    return {"status": status, "text": text, "cites": list(cites)}


def _claim(claim_id: str, title: str, text: str, plain: str, measure: dict | None, *cites: str) -> dict:
    return {"id": claim_id, "title": title, "statement": _statement("interpretation", text, *cites), "plain": plain,
            "measure": measure}


def _measure(latest: str, previous: str, compare: str, direction: str, way: str, material: str) -> dict:
    return {"latest": latest, "previous": previous, "compare": compare, direction: way, "material_change_pct": material}


def thesis_v1(root: Path) -> dict:
    """The SYNTHETIC version 1, bound to the synthetic sources retained under ``root`` (write_sources). It has 18
    elements, every one found in those sources: the view, a computed balance table (first row 26,500 kt demand and
    26,000 kt supply) and a side-by-side table, one differs entry, four reasons (strengthening, unchanged, weakening,
    strengthening, in that order; the first three compare two dataset or data-release editions, the fourth two years
    within the 2026 dataset edition, ruling R12), three risks (the last untracked), one condition, two movers, three
    moved entries (a stated producer, a stated consumer, a computed EV maker: 53.2 kg at 9,500 USD per tonne of a
    45,000 USD vehicle) and the price record."""
    steps = IEA[2026][0]
    figures = [iea_figure(2026, key, year) for year in steps for key in IEA_KEYS]
    figures += [iea_figure(2025, key, year) for key, year in (("demand", "2024"), ("clean", "2030"), ("demand", "2030"),
                                                               ("secondary", "2030"), ("supply", "2030"),
                                                               ("primary", "2035"))]
    figures += [usgs_figure(2026, "mine", "2024"), usgs_figure(2026, "mine", "2025"),
                usgs_figure(2026, "refinery", "2024"), usgs_figure(2026, "refinery", "2025"),
                usgs_figure(2025, "mine", "2024"), price_figure("2026M08"), price_figure("2026M10")]
    figures += [
        _figure("iea21-ev-copper", "iea-2021", "Synthetic copper in one electric car", "kg_per_unit", "53.2", "53.2",
                None, {"page": 1, "quote": "Synthetic: an electric car uses 53.2 kg of copper"}),
        _figure("maker-price-2025", "sec-maker-2025", "Synthetic average selling price of a vehicle", "usd", "45000",
                "$45,000", "2025", {"paragraph": 3, "quote": "The average selling price of our Synthetic vehicles was "
                                                            "$45,000 in 2025."}),
        _figure("maker-purchases-2025", "sec-maker-2025", "Synthetic purchases of copper and copper products",
                "usd_million", "95", "$95", "2025", {"paragraph": 4, "quote": "Our purchases of copper and copper "
                                                                             "products were approximately $95 million "
                                                                             "in 2025."}),
        _figure("producer-sensitivity-2025", "sec-producer-2025",
                "Synthetic cash-flow effect of a change of ten cents a pound", "usd_million", "410", "$410", "2026",
                {"paragraph": 4, "quote": SENSITIVITY_QUOTE})]
    passages = [
        _passage("producer-sales-2025", "sec-producer-2025",
                 {"paragraph": 3, "quote": "Synthetic copper sales were 4,120 million pounds in 2025."}),
        _passage("producer-sales-2024", "sec-producer-2024",
                 {"paragraph": 3, "quote": "Synthetic copper sales were 3,980 million pounds in 2024."}),
        _passage("maker-deliveries-2025", "sec-maker-2025",
                 {"paragraph": 5, "quote": "We delivered 210,000 Synthetic vehicles in 2025."}),
        _passage("iea21-construction", "iea-2021",
                 {"page": 2, "quote": "Synthetic: building construction remains the largest single use of copper."})]

    def step_row(year: str) -> dict:
        return {"year": year, "kind": "historical" if year == steps[0] else "projection",
                "demand_total": f"iea26-demand-{year}", "supply_total": f"iea26-supply-{year}",
                "lines": [{"label": IEA_LINES[IEA_KEYS.index(key)][1], "figure": f"iea26-{key}-{year}"}
                          for key in ("clean", "other", "primary", "secondary")]}

    side_by_side = [{"year": year, "kind": "historical", "demand_total": demand,
                     "supply_total": f"usgs26-refinery-{year}",
                     "lines": [{"label": "Synthetic world mine production", "figure": f"usgs26-mine-{year}"}]}
                    for year, demand in (("2024", "iea25-demand-2024"), ("2025", "iea26-demand-2025"))]
    return {
        "thesis_version": "thesis-0.1", "id": THESIS_ID, "version": 1, "previous_version": None,
        "title": "Synthetic copper: technology demand and the physical balance", "topic": "Synthetic copper",
        "opened_on": OPENED_ON, "prepared_on": OPENED_ON,
        "confidence": {"level": "medium",
                       "basis": "Synthetic: three of four reasons hold against their latest figures."},
        "sources": source_entries(root), "figures": figures, "passages": passages,
        "view": _statement("interpretation", "Synthetic reading: in the Synthetic STEPS projection, total demand of "
                                             "29,500 kt in 2030 exceeds total supply of 28,700 kt, so the physical "
                                             "balance runs short.", "iea26-demand-2030", "iea26-supply-2030"),
        "balance": {"tables": [
            {"id": "balance-steps", "title": "Synthetic balance in the Synthetic STEPS projection", "gap": "computed",
             "why_not": None, "rows": [step_row(year) for year in steps]},
            {"id": "balance-side-by-side", "title": "Synthetic dataset demand beside data-release output",
             "gap": "not_computed", "why_not": "Synthetic: demand and supply come from two publications on different "
                                               "bases, so no gap is computed.", "rows": side_by_side}]},
        "differs": [{
            "id": "differs-earlier-edition",
            "about": _statement("interpretation",
                                "Synthetic reading: the earlier edition put supply of 29,100 kt above demand of 28,750 "
                                "kt in 2030; the newer edition puts demand of 29,500 kt above supply of 28,700 kt.",
                                "iea25-supply-2030", "iea25-demand-2030", "iea26-demand-2030", "iea26-supply-2030"),
            "others": [{"cite": "iea25-supply-2030", "label": "Synthetic earlier dataset edition, supply"},
                       {"cite": "iea25-demand-2030", "label": "Synthetic earlier dataset edition, demand"}],
            "differs": True}],
        "reasons": [
            _claim("clean-tech-demand", "Synthetic clean-technology demand keeps growing",
                   "Synthetic reading: the newer edition puts clean-technology demand in 2030 at 10,100 kt, against "
                   "9,400 kt in the earlier edition.",
                   "Synthetic: more demand from clean technologies would widen the gap the view describes.",
                   _measure("iea26-clean-2030", "iea25-clean-2030", "revision", "supports_when", "higher", "5"),
                   "iea26-clean-2030", "iea25-clean-2030"),
            _claim("mine-supply-slow", "Synthetic mine supply responds slowly",
                   "Synthetic reading: the newer release puts world mine production in 2024 at 22,900 kt, against "
                   "22,700 kt in the earlier release.",
                   "Synthetic: if mines add output slowly, supply stays behind demand for longer.",
                   _measure("usgs26-mine-2024", "usgs25-mine-2024", "revision", "supports_when", "lower", "2"),
                   "usgs26-mine-2024", "usgs25-mine-2024"),
            _claim("recycling-limited", "Synthetic recycling adds little supply",
                   "Synthetic reading: the newer edition puts secondary supply in 2030 at 4,800 kt, against 4,300 kt "
                   "in the earlier edition.",
                   "Synthetic: recycled metal is supply too, and more of it narrows the gap.",
                   _measure("iea26-secondary-2030", "iea25-secondary-2030", "revision", "supports_when", "lower", "5"),
                   "iea26-secondary-2030", "iea25-secondary-2030"),
            _claim("total-demand-rising", "Synthetic total demand keeps rising through the projection",
                   "Synthetic reading: the same edition puts total demand at 29,500 kt in 2030 and at 31,800 kt in "
                   "2035.",
                   "Synthetic: demand that keeps rising within one edition's projection widens the gap the view "
                   "describes.",
                   _measure("iea26-demand-2035", "iea26-demand-2030", "period", "supports_when", "higher", "5"),
                   "iea26-demand-2030", "iea26-demand-2035")],
        "risks": [
            _claim("mine-output-rising", "Synthetic mine output grows faster",
                   "Synthetic reading: world mine production was 23,300 kt in 2025, against 22,700 kt in 2024.",
                   "Synthetic: faster mine growth would close the gap sooner.",
                   _measure("usgs26-mine-2025", "usgs25-mine-2024", "period", "grows_when", "higher", "2"),
                   "usgs26-mine-2025", "usgs25-mine-2024"),
            _claim("primary-supply-projections", "Synthetic primary supply projections move up",
                   "Synthetic reading: the newer edition puts primary supply in 2035 at 24,600 kt, against 25,100 kt "
                   "in the earlier edition.",
                   "Synthetic: more projected primary supply would weaken the view.",
                   _measure("iea26-primary-2035", "iea25-primary-2035", "revision", "grows_when", "higher", "1"),
                   "iea26-primary-2035", "iea25-primary-2035"),
            _claim("construction-slowdown", "Synthetic construction slows",
                   "Synthetic reading: construction is the largest use the report names, and no retained series "
                   "tracks it.", "Synthetic: slower building would mean less demand, and no retained measure tracks "
                                 "it.", None, "iea21-construction")],
        "conditions": [{
            "id": "supply-above", "figure": "iea26-supply-2030", "comparator": "above", "threshold": "29500",
            "text": "Synthetic: the view would change if projected total supply for 2030 went above 29,500 kt, against "
                    "28,700 kt in the newer edition."}],
        "exposure": {
            "movers": [
                {"company": "Synthetic Producer Corp.", "moves": "mine-supply-slow",
                 "through": "Synthetic: its stated copper sales of 4,120 million pounds in 2025, against 3,980 million "
                            "pounds in 2024, feed mine supply.",
                 "cites": ["producer-sales-2025", "producer-sales-2024"]},
                {"company": "Synthetic Maker Inc.", "moves": "clean-tech-demand",
                 "through": "Synthetic: its stated deliveries of 210,000 vehicles in 2025 feed clean-technology "
                            "demand.", "cites": ["maker-deliveries-2025"]}],
            "moved": [
                {"company": "Synthetic Producer Corp.", "side": "producer",
                 "how": _statement("stated", "Synthetic: the producer states an approximate $410 million effect on its "
                                             "annual operating cash flows for a change of ten cents a pound.",
                                   "producer-sensitivity-2025"),
                 "amount": {"kind": "stated", "figure": "producer-sensitivity-2025"}},
                {"company": "Synthetic Maker Inc.", "side": "consumer",
                 "how": _statement("stated", "Synthetic: the maker states copper purchases of approximately $95 million "
                                             "in 2025.", "maker-purchases-2025"),
                 "amount": {"kind": "stated", "figure": "maker-purchases-2025"}},
                {"company": "Synthetic Maker Inc.", "side": "consumer",
                 "how": _statement("interpretation", "Synthetic reading: at 53.2 kg of copper per vehicle and 9,500 USD "
                                                     "per tonne, copper is about 505 USD of a $45,000 vehicle.",
                                   "iea21-ev-copper", "wb-copper-2026m10", "maker-price-2025"),
                 "amount": {"kind": "computed", "per_unit": "iea21-ev-copper", "price": "wb-copper-2026m10",
                            "unit_price": "maker-price-2025"}}]},
        "log": [{"date": OPENED_ON, "kind": "opened",
                 "text": "Synthetic: the thesis opened with four reasons, three risks and one condition.", "refs": []}],
        "price_record": {"series": "Synthetic monthly copper price, nominal US dollars per tonne",
                         "opening": "wb-copper-2026m08", "latest": "wb-copper-2026m10"},
        "plain": {
            "view": "Synthetic: the view reads stated projections of the physical balance.",
            "balance": "Synthetic: a gap is computed only when both sides come from one publication, basis and "
                       "scenario.",
            "differs": "Synthetic: this compares the reading with what an earlier edition expected.",
            "reasons": "Synthetic: each reason compares its latest figure with a previous one, from an earlier "
                       "edition or from an earlier year of the same edition.",
            "risks": "Synthetic: risks use the same comparison, and one risk has no retained measure.",
            "conditions": "Synthetic: a condition states what would change the view.",
            "exposure": "Synthetic: exposure is read from company filings, not assumed.",
            "log": "Synthetic: the log only grows, and earlier entries are never rewritten.",
            "price": "Synthetic: the monthly price is shown as a record beside the view, not as evidence that the view "
                     "is right."},
        "not_claimed": ["Synthetic: no price target, price forecast or trade is stated or implied.",
                        "Synthetic: nothing here is proof that prices will rise or fall.",
                        "Synthetic: the balance is a reading of stated projections, not a cause of any price change."],
        "provenance": {"prepared_by": "Synthetic test author",
                       "method": "Synthetic: written by hand from the synthetic retained sources for the thesis tests.",
                       "ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded"}}


def thesis_v2(v1: dict, root: Path) -> dict:
    """The SYNTHETIC version 2: version 1 with the confidence level raised from medium to high, and a status entry and
    a confidence entry appended to the log; its source entries are re-read from the records under ``root``."""
    v2 = copy.deepcopy(v1)
    v2.update({"version": 2, "previous_version": 1, "prepared_on": V2_ON, "sources": source_entries(root),
               "confidence": {"level": "high",
                              "basis": "Synthetic: the reasons were read again against their latest figures and hold."}})
    v2["log"] += [{"date": V2_ON, "kind": "status", "refs": ["clean-tech-demand"],
                   "text": "Synthetic: the clean-technology reason was read again against its newer edition."},
                  {"date": V2_ON, "kind": "confidence", "refs": [],
                   "text": "Synthetic: confidence moved from medium to high after the review."}]
    return v2


def write_theses(content: Path, versions: list[dict], published: list[str | None],
                 thesis_id: str = THESIS_ID) -> Path:
    """Write ``content/synthetic-copper/``: v1.json … vN.json as committed JSON (LF line endings) and index.json, whose
    entries pin each version's SHA-256 of canonical JSON and its publication date (None for a draft). Returns
    ``content``."""
    folder = content / thesis_id
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for number, (version, published_on) in enumerate(zip(versions, published, strict=True), start=1):
        name = f"v{number}.json"
        (folder / name).write_text(json.dumps(version, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                   newline="\n")
        canonical = json.dumps(version, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        entries.append({"version": number, "file": name, "sha256": hashlib.sha256(canonical).hexdigest(),
                        "published_on": published_on})
    index = {"index_version": INDEX_VERSION, "id": thesis_id, "versions": entries}
    (folder / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8", newline="\n")
    return content


def changed(body, change) -> dict:
    """A deep copy of ``body`` after ``change(copy)`` has edited it in place; ``body`` itself is untouched."""
    edited = copy.deepcopy(body)
    change(edited)
    return edited

"""Retained EIA Monthly Energy Review Table 7.6 for the electricity findings (eia-t76-extract-0.1): the CSV, the
printed table (PDF) and the MER landing page, read from the bytes kept by acquisitions eia-mer-table76-01 and
eia-mer-inspection-01.

Sources. Only the files named by those approvals' outcome records are used. A record must report a complete HTTP 200
response from the expected address with a complete-response hash (and, for the two Table 7.6 files, a passed format
check); the file must still have that SHA-256 and stay within its size limit. Inspection reports are never read.

The CSV is the only source of values. It is refused unless it has exactly the six published columns; exactly the eight
series below, each with its published code, column order, description and unit (million kilowatthours); one row per
series and YYYYMM, where MM 01-12 is a month and 13 an annual total (kept apart, never used as a month); and every value
a plain decimal or "Not Available" (a missing value). Exponents, NaN, infinities, blanks or any other token are refused.
The CSV states no edition, geography or estimate status.

The PDF is the source of the definitions (TABLE_DEFINITIONS): they were transcribed from its page image at inspection
and are bound to its SHA-256 (TABLE_DEFINITIONS["transcribed_from"]["sha256"], read at each load); a retained PDF with
any other hash is refused, because the transcription would not be known to describe it. Its printed edition is part of that transcription. The landing page's release-date
statements are read from its bytes; they describe the page at its retrieval, not the CSV.

The extract's ID covers its content and source hashes; retrieval times and server headers are kept apart, as provenance.
"""
from decimal import Decimal
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import re

from .store import digest

EXTRACT_VERSION = "eia-t76-extract-0.1"
ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "data" / "sector-sources" / "eia-mer"
MIB = 1024 * 1024
CSV_URL = "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T07.06"
PDF_URL = "https://www.eia.gov/totalenergy/data/monthly/pdf/sec7_19.pdf"
LANDING_URL = "https://www.eia.gov/totalenergy/data/monthly/"
FILES = {
    "csv": {"approval": "eia-mer-table76-01", "folder": "table76", "name": "T07.06.csv", "url": CSV_URL,
            "max_bytes": 8 * MIB, "format_checked": True, "role": "Table 7.6 data (CSV)"},
    "pdf": {"approval": "eia-mer-table76-01", "folder": "table76", "name": "sec7_19.pdf", "url": PDF_URL,
            "max_bytes": 4 * MIB, "format_checked": True, "role": "Table 7.6 as printed (PDF)"},
    "landing": {"approval": "eia-mer-inspection-01", "folder": "inspection", "name": "landing.html",
                "url": LANDING_URL, "max_bytes": 2 * MIB, "format_checked": False,
                "role": "Monthly Energy Review page"},
}
HEADER = ["MSN", "YYYYMM", "Value", "Column_Order", "Description", "Unit"]
UNIT = "Million Kilowatthours"
NOT_AVAILABLE = "Not Available"
NUMBER = re.compile(r"-?\d+(\.\d+)?")
PERIOD = re.compile(r"(\d{4})(0[1-9]|1[0-3])")
# Code -> (column order, description) exactly as published in the CSV.
SERIES = {
    "ESRCPUS": ("1", "Electricity Sales to Ultimate Customers, Residential"),
    "ESCCPUS": ("2", "Electricity Sales to Ultimate Customers, Commercial"),
    "ESICPUS": ("3", "Electricity Sales to Ultimate Customers, Industrial"),
    "ESACPUS": ("4", "Electricity Sales to Ultimate Customers, Transportation"),
    "ESTCPUS": ("5", "Electricity Sales to Ultimate Customers, Total"),
    "ELDUPUS": ("6", "Electricity Direct Use"),
    "ELTCPUS": ("7", "Electricity End Use, Total"),
    "ESVHPUS": ("8", "Electric Vehicle Use"),
}
# The retained PDF the definitions below were transcribed from (eia-mer-table76-01, outcome 2).
PDF_SHA256 = "48bd0b1f5bbed922ee8418e1d3c5efba2e870473031b54d5a9da1360d0e61834"
TABLE_DEFINITIONS = {
    "transcribed_from": {"url": PDF_URL, "sha256": PDF_SHA256,
                         "how": "Transcribed from the PDF's page image at inspection; its text layer is OCR."},
    "title": "Table 7.6 Electricity End Use and Electric Vehicle Use",
    "unit": "Million Kilowatthours",
    "edition_printed": "U.S. Energy Information Administration / Monthly Energy Review September 2026",
    "page": "149",
    "columns": {
        "ESRCPUS": "Sales to Ultimate Customers (a): Residential (b)",
        "ESCCPUS": "Sales to Ultimate Customers (a): Commercial (b, c)",
        "ESICPUS": "Sales to Ultimate Customers (a): Industrial (b, d)",
        "ESACPUS": "Sales to Ultimate Customers (a): Transportation (e)",
        "ESTCPUS": "Sales to Ultimate Customers (a): Total Sales (f)",
        "ELDUPUS": "Direct Use (g)",
        "ELTCPUS": "Total End Use (h)",
        "ESVHPUS": "Electric Vehicle Use (b, i, j)",
    },
    "footnotes": {
        "a": "Electricity sales to ultimate customers based on classes of service reported by electric utilities and, "
             "beginning in 1996, other energy service providers.",
        "b": "Electricity sales to the residential, commercial, and industrial sectors, based on class of service, "
             "including sales of electricity to operate and move electric vehicles. See Note 4, \"Estimates of "
             "Electric Vehicle Use,\" at end of section.",
        "c": "Commercial sector, including public street and highway lighting, interdepartmental sales, and other "
             "sales to public authorities.",
        "d": "Industrial sector. Through 2002, excludes agriculture and irrigation; beginning in 2003, includes "
             "agriculture and irrigation.",
        "e": "Sales to public railroads and railway systems only. Excludes the estimated amount of electricity used "
             "to operate and move electric vehicles.",
        "f": "The sum of \"Residential,\" \"Commercial,\" \"Industrial,\" and \"Transportation.\"",
        "g": "Use of electricity that is 1) self-generated, 2) produced by either the same entity that consumes the "
             "power or an affiliate, and 3) used in direct support of a service or industrial process located within "
             "the same facility or group of facilities that house the generating equipment. Direct use is exclusive "
             "of station use.",
        "h": "The sum of \"Total Sales to Ultimate Customers\" and \"Direct Use.\"",
        "i": "Electricity used to operate and move on-road light-duty electric vehicles (less than or equal to 8,500 "
             "pounds). Excludes motor gasoline consumption by plug-in hybrid electric vehicles. Electric vehicle use "
             "is estimated independently and should not be added to the sales or total end use columns as it will "
             "result in double counting. See Note 4, \"Estimates of Electric Vehicle Use,\" at end of section.",
        "j": "Beginning in 2023, the estimates are not strictly comparable with earlier years due to a change in the "
             "estimation methodology for vehicle miles traveled. For details see Table 1.9 footnote f.",
    },
    "markers": "E=Estimate. NA=Not available.",
    "notes": [
        "See Note 1, \"Coverage of Electricity Statistics,\" at end of section.",
        "See Note 4, \"Estimates of Electric Vehicle Use,\" at end of section.",
        "Totals may not equal sum of components due to independent rounding.",
        "Geographic coverage is the 50 states and the District of Columbia.",
    ],
    "web_page": "See http://www.eia.gov/totalenergy/data/monthly/#electricity (Excel and CSV files) for all available "
                "annual data beginning in 1949 and monthly data beginning in 1973.",
    "sources": "Sources: See end of section.",
    "not_retained": "The section notes (Note 1, Note 4) and the end-of-section sources were not acquired; nothing here "
                    "relies on them.",
}
DATES = re.compile(r'<span class="label">\s*([^<]+?)\s*</span>\s*<span class="date">\s*([^<]+?)\s*</span>')


class EvidenceRefused(ValueError):
    pass


def _record(root: Path, kind: str) -> dict | None:
    """The approval's outcome record naming this file, or None. Unreadable records name nothing."""
    spec = FILES[kind]
    folder = root / "acquisitions" / spec["approval"]
    retained = f"data/sector-sources/eia-mer/{spec['folder']}/{spec['name']}"
    found = []
    for path in sorted(folder.glob("outcome-*.json")) if folder.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("approval_id") == spec["approval"] and \
                record.get("retained") == retained:
            found.append(record)
    return found[0] if len(found) == 1 else None


def _source(root: Path, kind: str) -> tuple[bytes, dict, dict]:
    """A retained file's bytes, its identity (hashed into the extract) and its provenance (kept apart)."""
    spec = FILES[kind]
    where = f"{spec['folder']}/{spec['name']}"
    record = _record(root, kind)
    if record is None:
        raise EvidenceRefused(f"{where}: no single acquisition record of {spec['approval']} names this file")
    if (record.get("outcome"), record.get("hash_kind"), record.get("http_status"), record.get("url")) != \
            ("complete", "complete_response", 200, spec["url"]):
        raise EvidenceRefused(f"{where}: its acquisition record does not report a complete response from "
                              f"{spec['url']}")
    if spec["format_checked"] and (record.get("content_check") or {}).get("state") != "format_ok":
        raise EvidenceRefused(f"{where}: its acquisition record does not report a passed format check")
    path = root / spec["folder"] / spec["name"]
    if not path.is_file() or path.stat().st_size > spec["max_bytes"]:
        raise EvidenceRefused(f"{where}: the retained file is missing or larger than {spec['max_bytes']} bytes")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != record.get("sha256") or sha != record.get("retained_sha256"):
        raise EvidenceRefused(f"{where}: the retained file no longer has its recorded SHA-256")
    named = record.get("named_headers") or {}
    identity = {"kind": kind, "role": spec["role"], "file": where, "url": spec["url"], "sha256": sha,
                "bytes": len(data), "approval_id": spec["approval"]}
    provenance = {"kind": kind, "retrieved_at": record.get("dispatched_at"),
                  "completed_at": record.get("body_completed_at"), "content_type": named.get("content-type"),
                  "last_modified_header": named.get("last-modified"), "etag_header": named.get("etag"),
                  "content_disposition": named.get("content-disposition")}
    return data, identity, provenance


def parse_csv(data: bytes) -> dict:
    """Code -> {"monthly": {YYYY-MM: text | "Not Available"}, "annual": {YYYY: ...}}, validated (see the module notes)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise EvidenceRefused("The CSV is not UTF-8") from None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    while rows and not rows[-1]:
        rows.pop()
    if not rows or rows[0] != HEADER:
        raise EvidenceRefused(f"The CSV columns are {rows[0] if rows else []}, not {HEADER}")
    series = {code: {"monthly": {}, "annual": {}} for code in SERIES}
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(HEADER):
            raise EvidenceRefused(f"CSV line {number} has {len(row)} fields, not {len(HEADER)}")
        code, period, value, order, description, unit = row
        if code not in SERIES:
            raise EvidenceRefused(f"CSV line {number}: unexpected series {code!r}")
        if (order, description) != SERIES[code] or unit != UNIT:
            raise EvidenceRefused(f"CSV line {number}: {code} is described as {order!r}, {description!r}, {unit!r}, "
                                  f"not as published ({SERIES[code][0]!r}, {SERIES[code][1]!r}, {UNIT!r})")
        match = PERIOD.fullmatch(period)
        if not match:
            raise EvidenceRefused(f"CSV line {number}: {period!r} is not a YYYYMM month or YYYY13 annual total")
        if value != NOT_AVAILABLE and not NUMBER.fullmatch(value):
            raise EvidenceRefused(f"CSV line {number}: {code} {period} has the value {value!r}, which is neither a "
                                  "finite decimal nor \"Not Available\"")
        year, month = match.groups()
        frequency, key = ("annual", year) if month == "13" else ("monthly", f"{year}-{month}")
        if key in series[code][frequency]:
            raise EvidenceRefused(f"CSV line {number}: {code} has a second row for {period}")
        series[code][frequency][key] = value
    empty = [code for code, found in series.items() if not found["monthly"]]
    if empty:
        raise EvidenceRefused(f"The CSV has no monthly rows for {', '.join(empty)}")
    return series


def _month_index(key: str) -> int:
    return int(key[:4]) * 12 + int(key[5:]) - 1


def coverage(series: dict) -> dict:
    """What the file covers, per series: monthly and annual ranges, gaps and values not available."""
    out = {}
    for code, found in series.items():
        months = sorted(found["monthly"])
        indexes = {_month_index(key) for key in months}
        years = sorted(found["annual"])
        out[code] = {"monthly_first": months[0], "monthly_last": months[-1], "monthly_rows": len(months),
                     "monthly_gaps": (_month_index(months[-1]) - _month_index(months[0]) + 1) - len(indexes),
                     "monthly_not_available": sum(1 for v in found["monthly"].values() if v == NOT_AVAILABLE),
                     "annual_first": years[0] if years else None, "annual_last": years[-1] if years else None,
                     "annual_rows": len(years),
                     "annual_not_available": sum(1 for v in found["annual"].values() if v == NOT_AVAILABLE)}
    return out


def landing_statements(data: bytes) -> dict:
    """The landing page's release-date statements as published, read from its label/date spans."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"release_date_as_stated": None, "next_release_as_stated": None, "readable": False}
    pairs = [(html.unescape(label), " ".join(html.unescape(value).split())) for label, value in DATES.findall(text)]
    release = [value for label, value in pairs if label == "Release Date:"]
    following = [value for label, value in pairs if label == "Next Release Date:"]
    return {"release_date_as_stated": release[0] if len(release) == 1 else None,
            "next_release_as_stated": following[0] if len(following) == 1 else None,
            "readable": len(release) == 1}


def load(root: Path, months: list[str], codes: tuple[str, ...]) -> dict:
    """The verified extract: the CSV values of `codes` for `months` (a month without a row is None), the file's
    coverage, every series identity, the sources and the definitions they rest on."""
    csv_bytes, csv_source, csv_provenance = _source(root, "csv")
    pdf_bytes, pdf_source, pdf_provenance = _source(root, "pdf")
    bound = TABLE_DEFINITIONS["transcribed_from"]["sha256"]
    if pdf_source["sha256"] != bound:
        raise EvidenceRefused("The retained PDF is not the one the Table 7.6 definitions were transcribed from "
                              f"({bound[:12]}); its definitions are not known to apply")
    try:
        landing_bytes, landing_source, landing_provenance = _source(root, "landing")
        landing = {**landing_source, "statements": landing_statements(landing_bytes)}
    except EvidenceRefused as exc:  # Context only: the findings never depend on it.
        landing, landing_provenance = {"kind": "landing", "role": FILES["landing"]["role"], "unavailable": str(exc)}, \
            {"kind": "landing"}
    series = parse_csv(csv_bytes)
    values = {code: {key: series[code]["monthly"].get(key) for key in months} for code in codes}
    content = {
        "extract_version": EXTRACT_VERSION,
        "sources": [csv_source, {**pdf_source, "edition_printed": TABLE_DEFINITIONS["edition_printed"]}, landing],
        "definitions_sha256": digest(TABLE_DEFINITIONS),
        "series": [{"code": code, "column_order": order, "description": description, "unit": UNIT}
                   for code, (order, description) in SERIES.items()],
        "coverage": coverage(series), "months": list(months), "values": values,
    }
    provenance = [csv_provenance, pdf_provenance, landing_provenance]
    return {**content, "extract_id": digest(content), "provenance": provenance}


def verify_extract(record: dict) -> bool:
    content = {key: value for key, value in record.items() if key not in ("extract_id", "provenance")}
    return record.get("extract_version") == EXTRACT_VERSION and record.get("extract_id") == digest(content)


def as_decimal(text: str | None) -> Decimal | None:
    """A CSV value as an exact decimal; None for a missing row or "Not Available"."""
    return None if text is None or text == NOT_AVAILABLE else Decimal(text)

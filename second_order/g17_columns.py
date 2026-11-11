"""Two more Table 1 columns for the cross-source comparisons (g17-columns-0.1): "Fourth quarter to fourth quarter" and the
12-month change, for two rows only: Manufacturing (NAICS) 31-33 and Utilities / Electric 2211.

It reads the same retained Table 1 pages as the industry findings and validates them the same way (g17_evidence: the
acquisition record and SHA-256, the G.17 identity, release and last-update dates, title, unit, and the id/headers
structure with six consecutive monthly columns), then resolves every value through the header cells it names:
- a fourth-quarter value names the "Fourth quarter to fourth quarter" group and one year column (a four-digit year);
- a 12-month value names the one column whose heading reads "<month> 'YY to <month> 'YY", which must be the release's
  own latest monthly column (the same month, one year apart);
- each row is found by its full path and must carry its NAICS code.
Values are one-decimal rates as printed or a blank (missing). Anything else refuses the release. The existing G.17
extract (g17-extract-0.1), its records and IDs are not changed; this extract has its own version and ID.
"""
import re
from pathlib import Path

from . import g17_evidence as evidence
from .store import digest

COLUMNS_VERSION = "g17-columns-0.1"
Q4_GROUP = "Fourth quarter to fourth quarter"
ROWS = {"manufacturing": ("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)", "31-33"),
        "electric": ("INDUSTRY GROUP / Utilities / Electric", "2211")}
TWELVE = re.compile(r"(?P<name>" + "|".join(re.escape(name) for name in evidence.MONTHS) +
                    r") ['’](?P<from>\d\d) to (?P<again>" + "|".join(re.escape(name) for name in evidence.MONTHS) +
                    r") ['’](?P<to>\d\d)")
YEAR = re.compile(r"\d{4}")


class ColumnsRefused(ValueError):
    pass


def _only(found: list, what: str, where: str):
    if len(found) != 1:
        raise ColumnsRefused(f"{where}: {len(found)} {what}, not one")
    return found[0]


def _printed(text: str, where: str) -> str | None:
    """A printed one-decimal rate, or None for a blank; anything else refuses the release."""
    try:
        return evidence._rate(text, where)
    except evidence.EvidenceRefused as exc:
        raise ColumnsRefused(str(exc)) from None


def release_columns(root: Path, release: str, record: dict) -> dict:
    """One release's fourth-quarter and 12-month values for the two rows, each with its column as printed."""
    where = f"Table 1 of the {release} release"
    try:
        data, source = evidence._source(root, release, "table1.htm", record)
        page = evidence._page(data, where)
        dated = evidence._dated(page, release, where)
        grid = evidence._grid(page, evidence.TABLE1_TITLE, evidence.TABLE1_UNIT, "Item", "Monthly rate", where)
    except evidence.EvidenceRefused as exc:
        raise ColumnsRefused(str(exc)) from None
    columns = grid["columns"]
    group = _only([key for key, text in columns.items() if text == Q4_GROUP], f"{Q4_GROUP!r} columns", where)
    naics = _only([key for key, text in columns.items() if text == "NAICS"], "NAICS columns", where)
    twelve = _only([key for key, text in columns.items() if TWELVE.fullmatch(text)], "12-month columns", where)
    stated = TWELVE.fullmatch(columns[twelve])
    latest = grid["months"][-1]
    year = int(latest["year"])
    if stated["name"] != stated["again"] or evidence.MONTHS[stated["name"]] != int(latest["key"][5:]) or \
            (int(stated["from"]), int(stated["to"])) != ((year - 1) % 100, year % 100):
        raise ColumnsRefused(f"{where}: the 12-month column {columns[twelve]!r} is not the release's latest month "
                             f"({latest['column']}) against a year earlier")
    by_path = {row["path"]: row for row in grid["rows"]}
    rows = {}
    for name, (path, code) in ROWS.items():
        row = by_path.get(path)
        if row is None:
            raise ColumnsRefused(f"{where}: no row {path!r}")
        printed = [cell["text"] for cell in row["cells"] if cell["columns"] == [naics]]
        if printed != [code]:
            raise ColumnsRefused(f"{where}: the row {path!r} is coded {printed}, not [{code!r}]")
        fourth, months12 = {}, []
        for cell in row["cells"]:
            names = cell["columns"]
            if group in names:
                years = [key for key in names if key != group]
                if len(years) != 1 or not YEAR.fullmatch(columns[years[0]]):
                    raise ColumnsRefused(f"{where}: a {Q4_GROUP!r} value in {path!r} does not name one year")
                label = columns[years[0]]
                if label in fourth:
                    raise ColumnsRefused(f"{where}: {path!r} has two {Q4_GROUP!r} values for {label}")
                fourth[label] = {"value": _printed(cell["text"], f"{where}, {path}, {label}"),
                                 "column": f"{Q4_GROUP} / {label}"}
            elif names == [twelve]:
                months12.append(_printed(cell["text"], f"{where}, {path}, {columns[twelve]}"))
        if not fourth:
            raise ColumnsRefused(f"{where}: the row {path!r} has no {Q4_GROUP!r} values")
        rows[name] = {"path": path, "naics": code, "fourth_quarter": dict(sorted(fourth.items())),
                      "twelve_month": {"value": _only(months12, "12-month values", f"{where}, {path}"),
                                       "period": latest["key"], "marker": latest["marker"],
                                       "column": columns[twelve]}}
    content = {"columns_version": COLUMNS_VERSION, "release": release, "release_date": dated["release_date"],
               "release_date_as_stated": dated["release_date_as_stated"], "source": source, "rows": rows}
    return {**content, "extract_id": digest(content),
            "provenance": {"retrieved_at": record.get("dispatched_at"),
                           "last_modified_header": (record.get("named_headers") or {}).get("last-modified")}}


def load(root: Path) -> list[dict]:
    """Every retained release's columns, oldest release first. Refused when none is retained or any is invalid."""
    available = evidence.retained(root)
    if not available:
        raise ColumnsRefused("No retained G.17 release with its Table 1 and release summary is kept")
    extracts = [release_columns(root, release, files["table1.htm"]) for release, files in sorted(available.items())]
    return sorted(extracts, key=lambda item: item["release_date"])


def verify(record: dict) -> bool:
    content = {key: value for key, value in record.items() if key not in ("extract_id", "provenance")}
    return record.get("columns_version") == COLUMNS_VERSION and record.get("extract_id") == digest(content)

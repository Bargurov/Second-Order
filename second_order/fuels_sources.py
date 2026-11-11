"""The committed source-terms record of the fuels page (fuels-sources-0.2).

content/fuels/sources.json names each EIA series the page may read (its API route, and the description and units EIA
must give it), the terms it was read under, the data vendor where EIA names one, and the scope of use (personal and
private demonstration). It is checked strictly on every read. A refusal names the field, never a value. Nothing here
fetches. (0.1 named FRED series; the page no longer reads FRED.)
"""
from datetime import date
from pathlib import Path

from . import bis_snapshot, store

SOURCES_VERSION = "fuels-sources-0.2"
ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content" / "fuels"
SOURCES_FILE = "sources.json"
MAX_FILE_BYTES = 200_000
ROLES = ("brent", "wti", "gasoline", "diesel", "henry_hub")
# Each role's EIA series (the API's series facet), its API route and EIA's page for it: fixed here, so the record can
# never point a role at a futures contract or a series of another definition.
SERIES = {"brent": "RBRTE", "wti": "RWTC", "gasoline": "EER_EPMRU_PF4_Y35NY_DPG",
          "diesel": "EER_EPD2DXL0_PF4_Y35NY_DPG", "henry_hub": "RNGWHHD"}
ROUTES = {"brent": "petroleum/pri/spt", "wti": "petroleum/pri/spt", "gasoline": "petroleum/pri/spt",
          "diesel": "petroleum/pri/spt", "henry_hub": "natural-gas/pri/fut"}
PAGES = {"brent": "https://www.eia.gov/dnav/pet/hist/RBRTED.htm", "wti": "https://www.eia.gov/dnav/pet/hist/RWTCD.htm",
         "gasoline": "https://www.eia.gov/dnav/pet/hist/EER_EPMRU_PF4_Y35NY_DPGD.htm",
         "diesel": "https://www.eia.gov/dnav/pet/hist/EER_EPD2DXL0_PF4_Y35NY_DPGD.htm",
         "henry_hub": "https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm"}
SCOPE = "personal_and_private_demo"
PAGE_LABEL = "Personal and educational use. Not for redistribution."
CREDIT = ("Spot prices from the U.S. Energy Information Administration (EIA), retrieved through its open data API. "
          "EIA does not endorse this page.")
UNITS = {"usd_per_bbl": 2, "usd_per_gal": 3, "usd_per_mmbtu": 2}
TOP_FIELDS = {"sources_version", "prepared_on", "page_label", "credit", "terms", "series"}
TERM_FIELDS = {"id", "title", "url", "read_on"}
SERIES_FIELDS = {"series_id", "role", "label", "unit", "eia_route", "eia_description", "eia_units", "cadence",
                 "publication", "publisher", "url", "data_vendor", "scope", "basis", "public", "terms"}
VENDOR_FIELDS = {"name", "term"}
MAX_LABEL = 120
MAX_TEXT = 600
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


class FuelsRefused(Exception):
    """A fuels read that cannot be served: status 503 when something is missing, 500 when it is invalid."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _bad(where: str, rule: str) -> FuelsRefused:
    return FuelsRefused(500, f"{where}: {rule}")


def _check(ok: bool, where: str, rule: str) -> None:
    if not ok:
        raise _bad(where, rule)


def _fields(value: object, names: set, where: str) -> dict:
    _check(isinstance(value, dict), where, "expected an object")
    _check(set(value) == names, where, "expected exactly the listed fields")
    return value


def _text(value: object, where: str) -> str:
    _check(isinstance(value, str) and 0 < len(value) <= MAX_TEXT, where, "expected non-empty text of limited length")
    return value


def _day(value: object, where: str) -> date:
    try:
        _check(isinstance(value, str) and len(value) == 10, where, "expected a date as YYYY-MM-DD")
        return date.fromisoformat(value)
    except ValueError:
        raise _bad(where, "expected a date as YYYY-MM-DD") from None


def _https(value: object, where: str) -> str:
    _check(isinstance(value, str) and value.startswith("https://") and len(value) <= 300 and value.isascii()
           and " " not in value, where, "expected an https URL")
    return value


def check_sources(raw: object) -> dict:
    """The record, if it is exactly the committed shape; otherwise FuelsRefused(500) naming the field."""
    record = _fields(raw, TOP_FIELDS, "sources")
    _check(record["sources_version"] == SOURCES_VERSION, "sources_version", "expected the supported version")
    _day(record["prepared_on"], "prepared_on")
    _check(record["page_label"] == PAGE_LABEL, "page_label", "expected the fixed page label")
    _check(record["credit"] == CREDIT, "credit", "expected the fixed EIA credit")
    terms = record["terms"]
    _check(isinstance(terms, list) and 0 < len(terms) <= 20, "terms", "expected a short list")
    term_ids: set = set()
    for number, term in enumerate(terms):
        where = f"terms[{number}]"
        _fields(term, TERM_FIELDS, where)
        _check(isinstance(term["id"], str) and 0 < len(term["id"]) <= 60, f"{where}.id", "expected an identifier")
        _check(term["id"] not in term_ids, f"{where}.id", "expected a unique identifier")
        term_ids.add(term["id"])
        _text(term["title"], f"{where}.title")
        _https(term["url"], f"{where}.url")
        _day(term["read_on"], f"{where}.read_on")
    series = record["series"]
    _check(isinstance(series, list) and len(series) == len(ROLES), "series", "expected one entry per role")
    for number, (entry, role) in enumerate(zip(series, ROLES)):
        where = f"series[{number}]"
        _fields(entry, SERIES_FIELDS, where)
        _check(entry["role"] == role, f"{where}.role", "expected the roles in their fixed order")
        _check(entry["series_id"] == SERIES[role], f"{where}.series_id", "expected the series fixed for its role")
        _text(entry["label"], f"{where}.label")
        _check(isinstance(entry["unit"], str) and entry["unit"] in UNITS, f"{where}.unit", "expected a listed unit")
        _check(entry["eia_route"] == ROUTES[role], f"{where}.eia_route", "expected the route fixed for its role")
        _text(entry["eia_description"], f"{where}.eia_description")
        _check(isinstance(entry["eia_units"], str) and 0 < len(entry["eia_units"]) <= 20 and entry["eia_units"].isascii()
               and " " not in entry["eia_units"], f"{where}.eia_units", "expected a short units text")
        _check(entry["cadence"] == "daily", f"{where}.cadence", "expected daily")
        _check(entry["publication"] == "weekly", f"{where}.publication", "expected weekly")
        _text(entry["publisher"], f"{where}.publisher")
        _https(entry["url"], f"{where}.url")
        _check(entry["url"] == PAGES[role], f"{where}.url", "expected EIA's page for the series")
        _check(entry["scope"] == SCOPE, f"{where}.scope", "expected the personal and private demonstration scope")
        _text(entry["basis"], f"{where}.basis")
        _check(entry["public"] == "not_assessed", f"{where}.public", "expected not_assessed")
        listed = entry["terms"]
        _check(isinstance(listed, list) and bool(listed) and all(isinstance(t, str) for t in listed)
               and len(set(listed)) == len(listed) and set(listed) <= term_ids, f"{where}.terms",
               "expected unique ids of listed terms")
        vendor = entry["data_vendor"]
        if vendor is not None:  # Named only where EIA names it, with the listed page that says so.
            _fields(vendor, VENDOR_FIELDS, f"{where}.data_vendor")
            _check(isinstance(vendor["name"], str) and 0 < len(vendor["name"]) <= MAX_LABEL,
                   f"{where}.data_vendor.name", "expected a short name")
            _check(vendor["term"] in listed, f"{where}.data_vendor.term", "expected one of the series' listed terms")
    return record


def load_sources(folder: Path = CONTENT_DIR) -> tuple[dict, str]:
    """The checked record and the SHA-256 of its canonical JSON. A missing file is a 503."""
    path = Path(folder) / SOURCES_FILE
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise _bad("sources", "the file is larger than the limit")
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise FuelsRefused(503, "sources: the source-terms record is not on this machine") from None
    except (OSError, UnicodeDecodeError):
        raise _bad("sources", "the file cannot be read") from None
    try:
        raw = bis_snapshot._strict_json(text, "sources")
    except bis_snapshot.SnapshotRefused:
        raise _bad("sources", "the file is not strict JSON") from None
    record = check_sources(raw)
    return record, store.digest(record)


def record_for(sources: dict, series_id: str) -> dict:
    for entry in sources["series"]:
        if entry["series_id"] == series_id:
            return entry
    raise FuelsRefused(500, "series: no source record for the series")


def attribution(record: dict, retrieved_on: date | None) -> str:
    """EIA's acknowledgment for one series: the source, EIA's description and series id, the retrieval date (EIA's API
    gives no publication date, so the date shown is the day we retrieved it, said so), EIA's page, and the data vendor
    where EIA names one. Without a date the date is left out."""
    text = f"Source: U.S. Energy Information Administration, {record['eia_description']} [{record['series_id']}]"
    if retrieved_on is not None:
        text += f", retrieved {MONTHS[retrieved_on.month - 1]} {retrieved_on.day}, {retrieved_on.year}"
    text += f"; {record['url']}."
    if record["data_vendor"] is not None:
        text += f" Data: {record['data_vendor']['name']}, as EIA states."
    return text

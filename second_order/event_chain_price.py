"""What the price did after an event (spec 5.8): a rule fixed in advance, beside a chain and never inside it.

The series is the USGS annual average U.S. producer cathode price (COMEX + premium), in US cents per pound, from the
retained Mineral Commodity Summaries 2026 data release (the metals sources file's entry with the id SERIES names): the
thesis price record's series. A sources file without that entry withholds the block. The file is verified against its
acquisition record on every read and its rows are read by header name (Statistics_detail, Year, Value, Notes); a file
that does not verify, cannot be read, or whose price rows are not the layout read here withholds the whole block, with
fixed wording that never echoes the file.

The event year is the four-digit year in the event's `when`. For each later year the block gives the change from the
event year, (later - event) / event * 100 in exact decimals, ROUND_HALF_EVEN to one decimal; beside them, the series'
year-on-year changes up to the event year. With no later year it reads "Not yet measured: the retained series ends at
{year}", plus " (estimate)" when that row's Notes reads "Estimated.". The short term is never measured: no monthly or
daily price source is retained. Reads only: nothing here writes, fetches or calls a model.
"""
import re
from decimal import Decimal

from . import metals_view, thesis_sources
from .thesis_arithmetic import change_pct, decimal_of, display
from .thesis_rules import ThesisRefused

DETAIL = "Price, annual average, cents per pound: U.S. producer, cathode (COMEX + premium)"
SERIES = {"source": metals_view.SOURCE_IDS[0], "label": DETAIL, "unit": "US cents per pound"}
COLUMNS = ("Statistics_detail", "Year", "Value", "Notes")
ESTIMATED = "Estimated."
YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
SHORT_TERM = "Not measured: no monthly or daily price source is retained"
NOT_YET = "Not yet measured: the retained series ends at {year}"
MEASURED = "What the price did after: the change from {year} to each later year, to {last}"
ESTIMATE = " (estimate)"
WITHHELD = "Withheld: the price series cannot be measured on this machine; the problem names why"
LAYOUT = "The price rows are not the layout this version reads"
NO_ROWS = "The retained file holds no row of this price series"
NO_YEAR = "The event's date names no four-digit year"
NO_BASE = "The retained series holds no figure for the event year {year}"
ZERO = "A price of zero in the series has no percentage change"
NO_ENTRY = "The metals sources file names no entry {source}"


def _rows(rows: list[list[str]]) -> dict[int, tuple[Decimal, str]]:
    """{year: (value, Notes)} of the price rows; ValueError(LAYOUT or NO_ROWS) when they are not one series."""
    if not rows or any(name not in rows[0] for name in COLUMNS):
        raise ValueError(LAYOUT)
    detail, year, value, notes = (rows[0].index(name) for name in COLUMNS)
    found = {}
    for row in rows[1:]:
        if len(row) != len(rows[0]):
            raise ValueError(LAYOUT)
        if row[detail] != DETAIL:
            continue
        if not re.fullmatch(r"\d{4}", row[year]) or int(row[year]) in found:
            raise ValueError(LAYOUT)
        try:
            found[int(row[year])] = (decimal_of(row[value]), row[notes])
        except ValueError:
            raise ValueError(LAYOUT) from None
    if not found:
        raise ValueError(NO_ROWS)
    return found


def series(folders) -> dict:
    """{"rows": {year: (value, Notes)} | None, "problem": None | why the series is withheld}. Reads only."""
    try:
        entry = next((item for item in metals_view.load_sources(folders.metals)
                      if item.get("id") == SERIES["source"]), None)
        if entry is None:
            return {"rows": None, "problem": NO_ENTRY.format(source=SERIES["source"])}
        state, raw = thesis_sources.verify(entry, folders.metals_sources)
    except ThesisRefused as exc:
        return {"rows": None, "problem": str(exc)}
    except ValueError:
        return {"rows": None, "problem": "The metals sources file does not name one retained file"}
    if state["state"] != "verified":
        return {"rows": None, "problem": state["detail"]}
    try:
        return {"rows": _rows(thesis_sources.content(entry, raw)), "problem": None}
    except thesis_sources.Unreadable as exc:
        return {"rows": None, "problem": f"The file cannot be read: {exc}"}
    except ValueError as exc:
        return {"rows": None, "problem": str(exc)}


def _pct(previous: Decimal, latest: Decimal) -> str:
    return display(change_pct(previous, latest), 1)


def measure(when: str, held: dict) -> dict:
    """The block for an event dated ``when`` on a series read by series()."""
    found = YEAR.search(when)
    event_year = int(found.group(1)) if found else None
    block = {"series": dict(SERIES), "event_year": event_year, "state": "withheld", "changes": [], "context": [],
             "last_year": None, "last_estimated": None, "text": WITHHELD, "short_term": SHORT_TERM,
             "problem": held["problem"]}
    rows = held["rows"]
    if rows is None:
        return block
    if event_year is None:
        return dict(block, problem=NO_YEAR)
    years = sorted(rows)
    last = years[-1]
    estimate = ESTIMATE if rows[last][1] == ESTIMATED else ""
    later = [year for year in years if year > event_year]
    if later and event_year not in rows:
        return dict(block, problem=NO_BASE.format(year=event_year))
    if any(rows[year][0] == 0 for year in years):
        return dict(block, problem=ZERO)
    context = [{"from": a, "to": b, "change_pct": _pct(rows[a][0], rows[b][0])}
               for a, b in zip(years, years[1:]) if b == a + 1 and b <= event_year]
    block.update(context=context, last_year=last, last_estimated=bool(estimate), problem=None)
    if not later:
        return dict(block, state="not_yet_measured", text=NOT_YET.format(year=last) + estimate)
    changes = [{"year": year, "change_pct": _pct(rows[event_year][0], rows[year][0])} for year in later]
    return dict(block, state="measured", changes=changes, text=MEASURED.format(year=event_year, last=last) + estimate)


def price_after(when: str, folders) -> dict:
    """{"series", "event_year", "state": "measured" | "not_yet_measured" | "withheld", "changes": [{"year",
    "change_pct"}], "context": [{"from", "to", "change_pct"}], "last_year", "last_estimated", "text", "short_term",
    "problem"} for an event dated ``when`` (see the module docstring). Reads only."""
    return measure(when, series(folders))

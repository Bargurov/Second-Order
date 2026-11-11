"""The Treasury findings pilot's evidence: seven daily series read from one kept, accepted H.15 release package.

The package is verified as every read of it is (market_store.package_state: acquisition record, size and SHA-256, and
an accepted validation of the current parser version) before its data entry is read. The data entry is read with the
same protected parser (no DTD, entity or external resource; the structure entries, which begin with a DOCTYPE, are
never opened) and the same row rules as market_package: each series must carry exactly the attributes and descriptions
stated below, as the retained package states them; each observation is a weekday, in order, with status A and a plain
decimal or ND with -9999. Anything else refuses the whole extraction.

What the series are (from the data entry itself): Treasury constant-maturity yields at 3 months and 2, 5 and 10 years
and inflation-indexed constant-maturity yields at 5 and 10 years, all "quoted on investment basis" in percent per year,
business-day frequency (FREQ 9); and the discount (primary credit) rate, in percent per year. They come from one
publication, the Board's H.15; the nominal and inflation-indexed yields are points of the Treasury's own yield curves
that the Board republishes, and FRED republishes them again. They are one lineage: comparing them with each other or
with FRED is a calculation within one source, never independent corroboration.

Each series is classified against the SIFMA calendar (market_calendar.reconcile, with the versioned exceptions) from
its first to its last row, exactly as store snapshots are: explained gaps leave the grid; a session the source states
without a value, a session with no row, and a value on a calendar holiday stay in the grid as missing. Nothing is
interpolated or filled. An optional cutoff drops every row dated after it while the data entry is read.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
import zipfile
import zlib
from xml.parsers import expat

from . import market_package as mp
from . import market_store
from .market_calendar import expected_sessions, load_exceptions, observation_grid, reconcile

EXTRACT_VERSION = "insight-evidence-0.1"
NOMINAL = "Market yield on U.S. Treasury securities at {} constant maturity, quoted on investment basis"
INDEXED = NOMINAL + ",  inflation-indexed"


def _yield(name: str, instrument: str, maturity: str, label: str, short: str, long: str) -> dict:
    return {"attributes": {"CURRENCY": "NA", "FREQ": "9", "INSTRUMENT": instrument, "MATURITY": maturity,
                           "SERIES_NAME": name, "UNIT": "Percent:_Per_Year", "UNIT_MULT": "1"},
            "short": short, "long": long, "label": label}


# Series ID -> what the data entry must state for it. Long descriptions are compared with whitespace normalized.
SERIES = {
    "RIFLGFCM03_N.B": _yield("RIFLGFCM03_N.B", "TCMNOM", "M3", "3-month Treasury yield",
                             "3-month Treasury constant maturity", NOMINAL.format("3-month ")),
    "RIFLGFCY02_N.B": _yield("RIFLGFCY02_N.B", "TCMNOM", "Y2", "2-year Treasury yield",
                             "2-year Treasury constant maturity", NOMINAL.format("2-year ")),
    "RIFLGFCY05_N.B": _yield("RIFLGFCY05_N.B", "TCMNOM", "Y5", "5-year Treasury yield",
                             "5-year Treasury constant maturity", NOMINAL.format("5-year ")),
    "RIFLGFCY10_N.B": _yield("RIFLGFCY10_N.B", "TCMNOM", "Y10", "10-year Treasury yield",
                             "10-year Treasury constant maturity", NOMINAL.format("10-year ")),
    "RIFLGFCY05_XII_N.B": _yield("RIFLGFCY05_XII_N.B", "TCMII", "Y5", "5-year inflation-indexed yield",
                                 "5-year inflation indexed Treasury constant maturity", INDEXED.format("5-year ")),
    "RIFLGFCY10_XII_N.B": _yield("RIFLGFCY10_XII_N.B", "TCMII", "Y10", "10-year inflation-indexed yield",
                                 "10-year inflation indexed Treasury constant maturity", INDEXED.format("10-year ")),
    "RIFSRP_F02_N.B": _yield("RIFSRP_F02_N.B", "DWPC", "NA", "Discount (primary credit) rate", "Discount rate",
                             "The rate charged for primary credit under  amendment to the Board's Regulation A"),
}
UNIT_NOTE = ("Percent per year as the data entry states it (UNIT Percent:_Per_Year, UNIT_MULT 1); the Treasury yields are "
             "quoted on an investment basis. Changes are shown in basis points (1 bp = 0.01 percentage point).")


class EvidenceRefused(ValueError):
    pass


@dataclass(frozen=True)
class Evidence:
    """The classified grid of each series and the package it came from."""
    package: dict  # package_id, sha256, received_at, requested_at, release_prepared, coverage
    cutoff: str | None
    grids: dict = field(repr=False)  # series ID -> list of (date, source text or None, status)
    descriptions: dict = field(repr=False)  # series ID -> {"short", "long", "attributes"}


class _Reader:
    """expat handlers that keep only the seven series, with market_package's row rules."""

    def __init__(self, cutoff: str | None):
        self.stack: list[tuple[str, str]] = []
        self.dataset = None
        self.header_id = None
        self.collect: list[str] | None = None
        self.annotation: dict = {}
        self.current: dict | None = None
        self.found: dict = {}
        self.cutoff = cutoff

    def refuse(self, problem: str):
        raise EvidenceRefused(problem)

    def start(self, tag: str, attrs: dict) -> None:
        space, _, local = tag.rpartition("|")
        parent = self.stack[-1] if self.stack else None
        if len(self.stack) >= mp.MAX_DEPTH:
            self.refuse(f"{mp.DATA_ENTRY} nests elements more than {mp.MAX_DEPTH} deep")
        if parent is None and (space, local) != (mp.MESSAGE, "MessageGroup"):
            self.refuse(f"{mp.DATA_ENTRY} is not an SDMX message group")
        self.stack.append((space, local))
        if parent == (mp.MESSAGE, "Header") and (space, local) == (mp.MESSAGE, "ID"):
            self.collect = []
        elif (space, local) == (mp.FRB, "DataSet"):
            self.dataset = attrs.get("id")
        elif local == "Series" and parent == (mp.FRB, "DataSet"):
            name = attrs.get("SERIES_NAME")
            if name in SERIES:
                if space != mp.DATASET or self.dataset != mp.DATASET_ID:
                    self.refuse(f"{name} appears outside the {mp.DATASET_ID} dataset")
                if name in self.found:
                    self.refuse(f"{name} appears more than once")
                self.current = {"attributes": dict(attrs), "annotations": {}, "rows": {}, "last": None}
                self.found[name] = self.current
        elif (space, local) == (mp.FRB, "Obs"):
            if parent is None or parent[1] != "Series":
                self.refuse(f"{mp.DATA_ENTRY} has an observation outside a series")
            if self.current is not None:
                self.observation(attrs)
        elif self.current is not None and (space, local) in ((mp.COMMON, "AnnotationType"),
                                                              (mp.COMMON, "AnnotationText")):
            self.collect = []

    def observation(self, attrs: dict) -> None:
        name = self.current["attributes"]["SERIES_NAME"]
        if set(attrs) != mp.OBS_FIELDS:
            self.refuse(f"An observation of {name} has the attributes {sorted(attrs)}")
        period, status, value = attrs["TIME_PERIOD"], attrs["OBS_STATUS"], attrs["OBS_VALUE"]
        try:
            day = date.fromisoformat(period) if mp.DAY.fullmatch(period) else None
        except ValueError:
            day = None
        if day is None:
            self.refuse(f"{name} has an observation dated {period!r}, not a calendar date")
        last = self.current["last"]
        if last is not None and day <= last:
            self.refuse(f"{name} has {'a duplicate observation' if day == last else 'observations out of order'} "
                        f"on {period}")
        if day.weekday() >= 5:
            self.refuse(f"{name} has an observation on a weekend ({period})")
        if status == "A":
            if not mp.DECIMAL.fullmatch(value):
                self.refuse(f"{name} has the value {value!r} on {period}, not a plain decimal")
            text = value
        elif (status, value) == mp.MISSING:
            text = mp.NO_VALUE
        else:
            self.refuse(f"{name} has the status {status!r} with value {value!r} on {period}")
        if len(self.current["rows"]) >= mp.MAX_OBSERVATIONS:
            self.refuse(f"{name} has more than {mp.MAX_OBSERVATIONS} observations")
        self.current["last"] = day
        if self.cutoff is None or period <= self.cutoff:
            self.current["rows"][period] = text

    def end(self, tag: str) -> None:
        space, local = self.stack.pop()
        if self.collect is not None and space in (mp.MESSAGE, mp.COMMON):
            text = "".join(self.collect)
            self.collect = None
            if (space, local) == (mp.MESSAGE, "ID"):
                self.header_id = text
            else:
                self.annotation[local] = text
        elif self.current is not None and (space, local) == (mp.COMMON, "Annotation"):
            kind, text = self.annotation.get("AnnotationType"), self.annotation.get("AnnotationText")
            self.annotation = {}
            if kind in self.current["annotations"]:
                self.refuse(f"{self.current['attributes']['SERIES_NAME']} repeats its {kind!r} annotation")
            self.current["annotations"][kind] = text
        elif local == "Series" and self.current is not None and len(self.stack) == 2:
            self.current = None
        elif (space, local) == (mp.FRB, "DataSet"):
            self.dataset = None

    def text(self, data: str) -> None:
        if self.collect is not None:
            self.collect.append(data)
            if sum(len(part) for part in self.collect) > mp.MAX_TEXT:
                self.refuse(f"{mp.DATA_ENTRY} has a header or annotation text longer than {mp.MAX_TEXT} characters")


def _normalized(text: str | None) -> str:
    return " ".join((text or "").split())


def newest_accepted(market: Path) -> Path | None:
    """The accepted kept package received last (by its recorded receipt time); None when there is none."""
    _, _, packages = market_store.local_data(market, None)
    accepted = [package for package in packages if package["status"] == "accepted"]
    if not accepted:
        return None
    chosen = max(accepted, key=lambda package: (package["received_at"], package["package_id"]))
    return market / market_store.PACKAGES / chosen["package_id"]


def extract(folder: Path, cutoff: date | None = None) -> Evidence:
    """The seven series of one kept, accepted package, classified on the SIFMA calendar. Reads only."""
    try:
        summary, retrieval = market_store.package_state(folder)
    except market_store.StoreRefused as exc:
        raise EvidenceRefused(str(exc)) from None
    if summary["status"] != "accepted" or retrieval is None:
        raise EvidenceRefused(f"Package {folder.name} is {summary['status']}; only an accepted package is used")
    reader = _Reader(cutoff.isoformat() if cutoff else None)
    parser = mp.protected_parser(reader)
    try:
        with zipfile.ZipFile(folder / mp.PACKAGE_FILE) as archive:
            infos = {info.filename: info for info in mp._checked_infos(archive)}
            if mp.DATA_ENTRY not in infos or infos[mp.DATA_ENTRY].is_dir():
                raise EvidenceRefused(f"The package has no {mp.DATA_ENTRY} entry")
            for chunk in mp._stream(archive, infos[mp.DATA_ENTRY], [0]):
                parser.Parse(chunk, False)
            parser.Parse(b"", True)
    except (mp.DataRefused, mp.ArchiveRefused) as exc:
        raise EvidenceRefused(str(exc)) from None
    except expat.ExpatError as exc:
        raise EvidenceRefused(f"{mp.DATA_ENTRY} is not well-formed XML ({exc})") from None
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, OSError) as exc:
        raise EvidenceRefused(f"The package could not be read ({type(exc).__name__})") from None
    if reader.header_id != mp.DATASET_ID:
        raise EvidenceRefused(f"{mp.DATA_ENTRY}'s header does not name the {mp.DATASET_ID} release")
    exceptions = load_exceptions()
    grids, descriptions = {}, {}
    for series_id, expected in SERIES.items():
        found = reader.found.get(series_id)
        if found is None:
            raise EvidenceRefused(f"{mp.DATA_ENTRY} does not contain {series_id}")
        if found["attributes"] != expected["attributes"]:
            raise EvidenceRefused(f"{series_id} has the attributes {found['attributes']}, not "
                                  f"{expected['attributes']}")
        short, long = found["annotations"].get("Short Description"), found["annotations"].get("Long Description")
        if short != expected["short"] or _normalized(long) != _normalized(expected["long"]):
            raise EvidenceRefused(f"{series_id}'s descriptions are not the expected series")
        if not found["rows"]:
            raise EvidenceRefused(f"{series_id} has no observations")
        rows = [(date.fromisoformat(period), None if text == mp.NO_VALUE else Decimal(text))
                for period, text in found["rows"].items()]
        text_of = dict(found["rows"])
        sessions = expected_sessions(rows[0][0], rows[-1][0])
        classified = reconcile(series_id, rows, sessions, exceptions)
        grids[series_id] = [(day, text_of.get(day.isoformat()), status) for day, _, status in classified]
        descriptions[series_id] = {"short": short, "long": _normalized(long), "attributes": found["attributes"]}
    package = {"package_id": summary["package_id"], "sha256": summary["sha256"], "received_at": summary["received_at"],
               "requested_at": summary["requested_at"], "release_prepared": summary["release_prepared"]}
    return Evidence(package, cutoff.isoformat() if cutoff else None, grids, descriptions)


def grid_values(evidence: Evidence, series_id: str) -> list[tuple[date, str | None]]:
    """The series' observation grid: (date, source text or None for a missing value), explained gaps removed."""
    entries = [(day, Decimal(text) if text not in (None, mp.NO_VALUE) else None, status)
               for day, text, status in evidence.grids[series_id]]
    texts = {day: text for day, text, _ in evidence.grids[series_id]}
    return [(day, texts[day] if value is not None else None) for day, value in observation_grid(entries)]

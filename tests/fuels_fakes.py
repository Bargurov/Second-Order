"""Synthetic EIA API v2 replies for the fuels importer. Every value here is synthetic; no network is reached.

The reply shape follows EIA's API v2 documentation (https://www.eia.gov/opendata/documentation.php), read for shape
only: `response` holds `total`, `frequency`, `dateFormat` and `data[]` (each row with `period`, `series`,
`series-description`, `units` and `value`), `request.params` echoes the request, the API key included, and
`apiVersion` names the API's version. EIA returns at most 5,000 rows per reply and pages with `offset` and `length`.
What a real reply holds exactly (the description and units texts, whether `total` and `value` are numbers or text) is
not known from a real request; the importer accepts both forms and compares the texts with the committed record.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import math
import shutil
import sys
import httpx
from keyring.backend import KeyringBackend
from keyring.backends.Windows import WinVaultKeyring
from keyring.errors import PasswordDeleteError
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script: import the project from the repo root
from second_order import fuels_key, fuels_sources
from second_order.fuels_eia import refresh

FAKE_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCD"  # 40 characters, like an EIA key; synthetic


class MemoryKeyStore:
    """fuels_key's store (get, put, delete) in memory, so no test uses the real Windows Credential Manager."""

    def __init__(self, key=None):
        self.key = key

    def get(self):
        return self.key

    def put(self, key):
        self.key = key

    def delete(self):
        had, self.key = self.key is not None, None
        return had


class FakeVault(WinVaultKeyring):
    """Windows Credential Manager's backend with its three operations kept in a dict, so the real one is never used."""
    priority = -1  # never picked by keyring's own backend detection

    def __init__(self, key=None, keep=True):
        super().__init__()
        self.entries, self.keep = {}, keep
        if key is not None:
            self.entries[(fuels_key.SERVICE, fuels_key.ACCOUNT)] = key

    def get_password(self, service, username):
        return self.entries.get((service, username))

    def set_password(self, service, username, password):
        if self.keep:
            self.entries[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.entries:
            raise PasswordDeleteError("not found")
        del self.entries[(service, username)]


class OtherKeyring(KeyringBackend):
    """A keyring backend that is not Windows Credential Manager's (a plain-text file, say) and holds a key. It records
    every call made on it, so a test can show the store refused it before using it."""
    priority = -1  # never picked by keyring's own backend detection

    def __init__(self, key=FAKE_KEY):
        super().__init__()
        self.key, self.calls = key, []

    def get_password(self, service, username):
        self.calls.append("get")
        return self.key

    def set_password(self, service, username, password):
        self.calls.append("set")
        self.key = password

    def delete_password(self, service, username):
        self.calls.append("delete")
        self.key = None


RETRIEVED_ON = date(2026, 11, 6)
RETRIEVED = datetime(2026, 11, 6, 14, tzinfo=timezone.utc)
FIRST, LAST = date(2025, 9, 1), date(2026, 11, 3)
BASES = {"RBRTE": 80.0, "RWTC": 76.0, "EER_EPMRU_PF4_Y35NY_DPG": 2.4, "EER_EPD2DXL0_PF4_Y35NY_DPG": 2.9,
         "RNGWHHD": 3.1}
DECIMALS = {"EER_EPMRU_PF4_Y35NY_DPG": 3, "EER_EPD2DXL0_PF4_Y35NY_DPG": 3}
_ALL = ("positive", "zero", "negative", "subcent")
FINAL = {  # per series: the 2 Nov value (the same in every variant), then the 3 Nov value by variant.
    "RBRTE": ("79.04", {"positive": "80.00", "zero": "112.00", "negative": "115.00", "subcent": "79.10"}),
    "EER_EPMRU_PF4_Y35NY_DPG": ("2.501", {"positive": "2.500", "zero": "2.500", "negative": "2.500",
                                          "subcent": "2.503"}),
    "EER_EPD2DXL0_PF4_Y35NY_DPG": ("3.001", {"positive": "3.000", "zero": "3.000", "negative": "3.000",
                                             "subcent": "3.001"}),
}
# subcent: Brent +$0.06 and the basket +$0.056 a barrel since 2 Nov, so the crack moves -$0.004: shown as $0.00, yet
# the parts move in opposite directions (offsetting). 27 Oct repeats 2 Nov, so the week window shows the same split.
SUBCENT_WEEK_START = date(2026, 10, 27)
YEAR_BEHIND = LAST - timedelta(days=365)  # 3 Nov 2025: a series whose replies stop here is a year behind the others
SERIES_OF = {"brent": "RBRTE", "wti": "RWTC", "gasoline": "EER_EPMRU_PF4_Y35NY_DPG",
             "diesel": "EER_EPD2DXL0_PF4_Y35NY_DPG", "henry_hub": "RNGWHHD"}
SYNTHETIC_API = "SYNTHETIC-2.1"  # the fake's apiVersion: a snapshot from this fake is marked as test data


def datasets(variant: str = "positive",
             behind: dict[str, date] | None = None) -> dict[str, list[tuple[date, str | None]]]:
    """Weekday values for each series from FIRST to LAST; `behind` ends the named series (by series id) on its date, as
    if EIA's file held nothing newer for it."""
    out = {}
    for series, base in BASES.items():
        places, rows, day = DECIMALS.get(series, 2), [], FIRST
        while day <= (behind or {}).get(series, LAST):
            if day.weekday() < 5:
                raw = f"{base * (1 + .05 * math.sin(day.toordinal() / 11)):.{places}f}"
                if series in FINAL and (day == date(2026, 11, 2)
                                        or (variant == "subcent" and day == SUBCENT_WEEK_START)):
                    raw = FINAL[series][0]
                if series in FINAL and day == date(2026, 11, 3):
                    raw = FINAL[series][1][variant]
                rows.append((day, raw))
            day += timedelta(days=1)
        out[series] = rows
    return out


class FakeEia:
    """MockTransport handler: synthetic EIA API v2 replies, paged by offset and length, recording each request's
    parameters without the key. Options bend one series' replies into the shapes the importer must refuse."""

    def __init__(self, data, *, page_cap=5000, status=None, raise_for=None, warn=None, truncate=None, overlap=None,
                 total=None, rows=None, extra=None, numbers=False, total_as_number=False, api_version=SYNTHETIC_API,
                 frequency="daily", key_in_params=True, raw=None):
        self.data, self.page_cap = data, page_cap
        self.status, self.raise_for, self.warn = status or {}, raise_for, warn or set()
        self.truncate, self.overlap, self.total = truncate or set(), overlap or set(), total or {}
        self.rows, self.extra, self.numbers, self.total_as_number = rows or {}, extra or {}, numbers, total_as_number
        self.api_version, self.frequency, self.key_in_params = api_version, frequency, key_in_params
        self.raw = raw or {}  # series -> a 200 reply's raw text ({KEY} becomes the key)
        self.sources, _ = fuels_sources.load_sources()
        self.calls, self.keys, self.urls = [], [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        key = params.pop("api_key", None)
        self.keys.append(key)
        self.urls.append(str(request.url))
        path = request.url.path
        assert path.startswith("/v2/") and path.endswith("/data/"), path
        route = path[len("/v2/"):-len("/data/")]
        series = params["facets[series][]"]
        self.calls.append((route, series, params))
        if self.raise_for == series:
            raise httpx.ConnectError(f"connection failed for {request.url}", request=request)
        if series in self.raw:
            return httpx.Response(200, text=self.raw[series].replace("{KEY}", key or ""))
        if series in self.status:
            code, body = self.status[series]
            return httpx.Response(code, text=json.dumps(body).replace("{KEY}", key or ""))
        record = next(r for r in self.sources["series"] if r["series_id"] == series)
        start, end = date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
        offset, length = int(params["offset"]), min(int(params["length"]), 5000, self.page_cap)
        window = [(d, raw) for d, raw in self.data.get(series, []) if start <= d <= end]
        total = self.total.get(series, len(window))
        if series in self.overlap and offset > 0:
            offset -= 1
        page = [] if series in self.truncate and offset > 0 else window[offset:offset + length]
        data = [{"period": d.isoformat(), "duoarea": "SYNTHETIC", "series": series,
                 "series-description": record["eia_description"], "units": record["eia_units"],
                 "value": (None if raw is None else (float(raw) if self.numbers else raw))}
                | self.rows.get(series, {}) for d, raw in page]
        echoed = {"frequency": params["frequency"], "data": [params["data[0]"]], "facets": {"series": [series]},
                  "start": params["start"], "end": params["end"],
                  "sort": [{"column": params["sort[0][column]"], "direction": params["sort[0][direction]"]}],
                  "offset": int(params["offset"]), "length": int(params["length"])}
        if self.key_in_params:
            echoed["api_key"] = key
        payload = {"response": {"total": total if self.total_as_number else str(total), "dateFormat": "YYYY-MM-DD",
                                "frequency": self.frequency, "data": data,
                                "description": f"SYNTHETIC {record['label']} replies"},
                   "request": {"command": f"/v2/{route}/data/", "params": echoed}, "apiVersion": self.api_version}
        if series in self.warn:
            payload["warnings"] = [{"warning": "parameter out of range",
                                    "description": "The API can only return 5000 rows in JSON format."}]
        for field, value in self.extra.get(series, {}).items():
            payload["response"][field] = value.replace("{KEY}", key or "") if isinstance(value, str) else value
        return httpx.Response(200, text=json.dumps(payload))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def write_snapshot(folder: Path, variant: str = "positive", retrieved: datetime = RETRIEVED,
                   start: date | None = None, behind: dict[str, date] | None = None, **fake_options) -> str:
    """One SYNTHETIC snapshot; `behind` maps a role ("diesel", "wti", ...) to the last date its replies hold."""
    ends = {SERIES_OF[role]: day for role, day in (behind or {}).items()}
    fake = FakeEia(datasets(variant, ends), **fake_options)
    report = refresh(folder, fuels_sources.CONTENT_DIR, FAKE_KEY, start, fake.client(), lambda: retrieved)
    return report["snapshot_id"]


def write_world(root: Path) -> dict:
    """root/fuels-content (the committed sources, drivers and transmission files and one SYNTHETIC note bound to the
    positive snapshot) and root/fuels-snapshots (the positive snapshot). Returns both paths and the snapshot id."""
    from second_order import fuels_notes
    content, snapshots = Path(root) / "fuels-content", Path(root) / "fuels-snapshots"
    (content / "notes").mkdir(parents=True)
    for name in (fuels_sources.SOURCES_FILE, "drivers.json", "transmission.json"):
        shutil.copyfile(fuels_sources.CONTENT_DIR / name, content / name)
    snapshot_id = write_snapshot(snapshots)
    note = {"note_version": fuels_notes.NOTE_VERSION, "number": 1, "written_on": "2026-11-06",
            "covers_through": "2026-11-05", "snapshot_id": snapshot_id, "observation_date": "2026-11-03",
            "author": "Claude (AI-drafted)", "review": {"state": "unreviewed", "reviewed_on": None},
            "headline": "SYNTHETIC headline for a test note",
            "lede": "SYNTHETIC lede: Brent at {brent}, {brent_change}; the crack is {crack}.",
            "columns": {"supply": "SYNTHETIC supply column", "demand": "SYNTHETIC demand column",
                        "stocks": "SYNTHETIC stocks column"},
            "sources": [{"title": "SYNTHETIC source", "publisher": "Example publisher", "date": "2026-11-05",
                         "url": "https://example.org/synthetic", "locator": "SYNTHETIC locator"}]}
    fuels_notes.check_note(note, 1)
    (content / "notes" / "situation-0001.json").write_bytes((json.dumps(note, indent=2) + "\n").encode("utf-8"))
    return {"content": content, "snapshots": snapshots, "snapshot_id": snapshot_id}


def _item(kind: str, text: str, sources=(), mechanism=None) -> dict:
    return {"kind": kind, "text": text, "sources": list(sources), "mechanism": mechanism}


def analysis_note(snapshot_id: str, observation_date: str = "2026-11-03", number: int = 1,
                  written_on: str = "2026-11-06") -> dict:
    """A SYNTHETIC fuels-note-0.2: the shape of the committed analysis, with made-up prose and sources; every figure,
    date and direction is a placeholder the page fills from the bound snapshot."""
    from second_order import fuels_notes
    source = lambda n: {"title": f"SYNTHETIC source {n}", "publisher": "Example publisher", "date": "2026-11-05",  # noqa: E731
                        "url": f"https://example.org/synthetic-{n}", "locator": f"SYNTHETIC locator {n}"}
    return {
        "note_version": fuels_notes.ANALYSIS_VERSION, "number": number, "written_on": written_on,
        "covers_through": "2026-11-05", "snapshot_id": snapshot_id, "observation_date": observation_date,
        "author": "Claude (AI-drafted)", "review": {"state": "unreviewed", "reviewed_on": None},
        "headline": "SYNTHETIC: Brent {week_brent_move} over the week while the crack {week_crack_move}",
        "lede": ("SYNTHETIC summary. From {week_from} to {week_to}, Brent {week_brent_move} {week_brent_change} "
                 "({week_brent_pct}) while the crack {week_crack_move} {week_crack_change}, and the product basket "
                 "{week_basket_move} {week_basket_change}. As an accounting split, {week_split}. A SYNTHETIC source "
                 "says stocks of one product fell; that fits one reading but does not explain the move."),
        "analysis": {
            "what_happened": [
                _item("computed", "From {week_from} to {week_to}, Brent {week_brent_move} {week_brent_change} "
                                  "({week_brent_pct}), gasoline {week_gasoline_move} {week_gasoline_change} and diesel "
                                  "{week_diesel_move} {week_diesel_change}."),
                _item("computed", "Over the month from {month_from} to {month_to}, Brent {month_brent_move} "
                                  "{month_brent_change} and the crack {month_crack_move} {month_crack_change}."),
                _item("observation", "On {week_to}, Brent spot was {brent} a barrel in this SYNTHETIC snapshot.")],
            "meaning": [
                _item("computed", "The basket {week_basket_move} {week_basket_change}, and {week_split}."),
                _item("computed", "Gasoline's part was {week_gasoline_part} and diesel's part {week_diesel_part}."),
                _item("hypothesis", "SYNTHETIC possible reading, a general mechanism and not a finding.",
                      mechanism="drivers:inventories"),
                _item("sourced", "A SYNTHETIC source says stocks of one product fell.", [0])],
            "relevance": [
                _item("hypothesis", "SYNTHETIC refiners statement: the crack is a benchmark gross margin.",
                      mechanism="transmission:refiners_energy"),
                _item("hypothesis", "SYNTHETIC freight statement: diesel {week_diesel_move} while Brent "
                                    "{week_brent_move}.", mechanism="transmission:shipping_logistics")],
            "watch": [
                _item("hypothesis", "SYNTHETIC next report: if stocks keep falling, the reading gains weight.", [0],
                      "drivers:inventories"),
                _item("source_projection", "A SYNTHETIC source projected a path for spreads; a revision would test it.",
                      [1])],
            "caveats": ["SYNTHETIC caveat: the crack is not a refinery's profit.",
                        "SYNTHETIC caveat: prices alone do not show that stocks changed."]},
        "sources": [source(1), source(2)]}


def write_analysis_note(content: Path, snapshots: Path) -> str:
    """The next note under content/notes: a SYNTHETIC analysis bound to the latest snapshot and its barrel date."""
    from second_order import fuels_notes, fuels_view
    page = fuels_view.view(content, snapshots)
    number = len(fuels_notes.load_notes(content)) + 1
    note = analysis_note(page["snapshot"]["id"], page["barrel"]["date"], number)
    fuels_notes.check_note(note, number)
    (Path(content) / "notes" / f"situation-{number:04d}.json").write_bytes(
        (json.dumps(note, indent=2) + "\n").encode("utf-8"))
    return page["snapshot"]["id"]


def write_fred_snapshot(folder: Path) -> str:
    """A SYNTHETIC snapshot in the shape the FRED importer (fuels-fred-0.1) wrote before the page moved to EIA, as one
    could still be on a machine: hash-named and valid, so it verifies, but from a provider the page no longer reads."""
    from second_order import fuels_snapshots
    entry = {"state": "stored", "problem": None, "terms": {"series_id": "DCOILBRENTEU"},
             "metadata": {"id": "DCOILBRENTEU", "title": "SYNTHETIC Brent series", "last_updated": "2026-11-04"},
             "copyright_tags": ["public domain: citation requested"], "release": {"id": 1},
             "release_dates": ["2026-11-04"], "observations": [["2026-11-03", "80.00"]], "responses_sha256": {}}
    payload = {"snapshot_version": "fuels-snapshot-0.1", "adapter_version": "fuels-fred-0.1", "provider": "fred",
               "semantics": {"observation_date": "SYNTHETIC"}, "vintage_date": "2026-11-05",
               "observation_start": "2025-10-01", "retrieved_at": "2026-11-05T14:00:00+00:00",
               "sources_sha256": "0" * 64, "series": {"DCOILBRENTEU": entry}}
    return fuels_snapshots.write(folder, payload)[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write a SYNTHETIC fuels snapshot (browser check).")
    parser.add_argument("command", choices=("snapshot", "fred-snapshot", "refused-snapshot", "analysis-note",
                                            "behind-snapshot"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("snapshots", type=Path, nargs="?", help="analysis-note: the snapshots folder to bind to")
    parser.add_argument("--variant", choices=_ALL, default="positive")
    parser.add_argument("--retrieved", type=datetime.fromisoformat, default=RETRIEVED)
    parser.add_argument("--behind", choices=tuple(SERIES_OF), default="diesel",
                        help="behind-snapshot: the series whose replies stop a year before the others'")
    arguments = parser.parse_args()
    if arguments.command == "analysis-note":  # folder is the content folder
        print(write_analysis_note(arguments.folder, arguments.snapshots))
    elif arguments.command == "behind-snapshot":
        print(write_snapshot(arguments.folder, arguments.variant, arguments.retrieved,
                             behind={arguments.behind: YEAR_BEHIND}))
    elif arguments.command == "fred-snapshot":
        print(write_fred_snapshot(arguments.folder))
    elif arguments.command == "refused-snapshot":  # gasoline's units differ from the record: that series is refused
        print(write_snapshot(arguments.folder, arguments.variant, arguments.retrieved,
                             rows={"EER_EPMRU_PF4_Y35NY_DPG": {"units": "$/BBL"}}))
    else:
        print(write_snapshot(arguments.folder, arguments.variant, arguments.retrieved))

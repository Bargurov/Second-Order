"""Store snapshots built from a kept H.15 release package: the explicit local `market import-package` action.

A package kept under data/market-context/packages/<id>/ (market_store, market_package) holds the Federal Reserve
Board's H.15 release as received. This module copies the two Treasury constant-maturity series (RIFLGFCY02_N.B and
RIFLGFCY10_N.B) from a stated start date into one append-only store snapshot of provider "board-h15", so hypotheses
bound to the registry's H.15 entries (yield:ust2y_cmt_h15, yield:ust10y_cmt_h15) can be pinned like the FRED
snapshots. It runs only when invoked, reads the package folder and writes only the store: it never fetches, validates
or changes a package.

Before anything is written the package is verified as every read of it is: its acquisition record against the folder,
the package's size and SHA-256, and the validation record of the current parser version, which must have accepted the
package and must recompute exactly (rows, counts, coverage, rows SHA-256); no observation may be dated after the day the
package was requested. A package that is not validated, was refused or does not verify is refused, and nothing is
written. The store's tables are written in one transaction: the whole snapshot, or nothing.

What a snapshot records, kept apart (SEMANTICS):
- possession: retrieved_at is the package's receipt time from its acquisition record. It shows the values were held
  then, not when they first became public.
- no vintage: the package holds the Board's values as published when it was received, not a historical vintage. The
  payload's vintage_date is null; the store's NOT NULL vintage_date column holds the token "none", never a date.
- dates only: each observation is the data entry's TIME_PERIOD, an America/New_York calendar date. No time of day is
  stated or observed; the daily date convention orders a date-only value at the end of its date, which is a
  placeholder, never an observed time.
- the source's prepared time: the data entry header's "prepared" value exactly as stated. It names no time zone and is
  neither an observation nor a possession time.
- created_at: when this snapshot was built here.
Rows keep the exact decimal text or ND, the source's no-value marker; nothing is interpolated, filled or invented.
Each copied series is also kept as a gzip of its canonical rows with their SHA-256, so the snapshot stands without the
package folder.

Classification is the FRED import's (market_calendar.reconcile): every date from the start to each series' last row
against SIFMA's schedule and the versioned exceptions, which name series by their FRED crosswalk IDs, as event_context
reads them. The start must not precede either series' first observation in the package, so every expected session from
the start is stated by the package.

Repeating the import of one package with the same validation record, start and calendar finds the stored snapshot and
writes nothing. Another package, even with identical bytes, is another acquisition with its own receipt time, and so a
separate snapshot.
"""
from collections import Counter
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from . import market_package, market_store
from .market_calendar import calendar_identity, expected_sessions, load_exceptions, reconcile
from .market_context import NO_VALUE, SERIES, SOURCE, TERMS
from .registry import BOARD_H15, source_bound
from .schema import utc
from .snapshots import has_market_tables, load_snapshot
from .store import canonical, digest

ADAPTER_VERSION = "board-h15-package-import-0.1"
VINTAGE_COLUMN = "none"  # Stored in the NOT NULL vintage_date column; a token, never a date. The payload holds null.
SEMANTICS = {
    "observation_date": "TIME_PERIOD of the Board's H.15 data entry: an America/New_York calendar date with no time of "
                        "day. Treasury quotes are taken 'at or near 3:30 PM' with no documented bound; no time is "
                        "observed or claimed",
    "vintage_date": "none: the release package holds the Board's values as published when it was received; it is "
                    "not a historical vintage, and earlier values cannot be recovered from it",
    "retrieved_at": "the package's receipt time (its acquisition record): shows possession, not first public "
                    "availability",
    "source_prepared": "the data entry header's prepared time, exactly as stated; no time zone is given, and it is not "
                       "an observation or possession time",
    "created_at": "when this snapshot was built locally from the kept package",
}


class PackageImportRefused(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_package(folder: Path) -> tuple[dict, dict, dict]:
    """A kept package's acquisition record, its accepted validation record and the hashes of the files read, after
    every check a read of the package makes. Raises PackageImportRefused; reads only."""
    package_id = folder.name
    label = f"Package {package_id}"
    if not market_package.PACKAGE_ID.fullmatch(package_id):
        raise PackageImportRefused(f"{package_id!r} is not a package ID (p<request time>Z-<12 hex>)")
    if not folder.is_dir():
        raise PackageImportRefused(f"No kept package {package_id} under {folder.parent}")
    current = market_package.validation_name()
    try:
        acquisition_bytes = (folder / market_package.ACQUISITION_FILE).read_bytes()
        acquisition = market_package.strict_json(acquisition_bytes, f"{label}'s acquisition record")
        size, package_sha256 = market_package.file_sha256(folder / market_package.PACKAGE_FILE)
        market_package.check_acquisition(acquisition, package_id, size, package_sha256)
        if not (folder / current).is_file():
            raise PackageImportRefused(
                f"{label} has no validation record for parser {market_package.PARSER_VERSION}; it is acquired but not "
                "validated, so it is not used (validate it locally with `python -m second_order market-packages "
                "validate`)")
        validation_bytes = (folder / current).read_bytes()
        validation = market_package.check_validation(
            market_package.strict_json(validation_bytes, f"{label}'s validation record"), package_id, package_sha256)
    except OSError as exc:
        raise PackageImportRefused(f"{label} cannot be read ({type(exc).__name__})") from None
    except market_package.RecordRefused as exc:
        raise PackageImportRefused(str(exc)) from None
    if validation["status"] != "accepted":
        raise PackageImportRefused(f"{label} was refused by its validation: {validation['detail']}")
    requested_on = market_store.new_york_day(market_package.moment(acquisition["requested_at"], "requested_at"))
    latest = max(date.fromisoformat(item["last"]) for item in validation["series"].values())
    if latest > requested_on:
        raise PackageImportRefused(f"{label} states {latest}, after the day it was requested ({requested_on})")
    files = {"package_bytes": size, "package_sha256": package_sha256,
             "acquisition_sha256": _sha256(acquisition_bytes), "validation_sha256": _sha256(validation_bytes)}
    return acquisition, validation, files


def _existing(connection: sqlite3.Connection, import_key: str) -> str | None:
    """The snapshot an earlier import of exactly this package, validation, start and calendar stored, if any."""
    if not has_market_tables(connection):
        return None
    for snapshot_id, payload in connection.execute("SELECT id, payload FROM market_snapshots WHERE provider=?",
                                                   (BOARD_H15,)):
        if json.loads(payload).get("import_key") == import_key:
            return snapshot_id
    return None


def import_package(connection: sqlite3.Connection, package_id: str, observation_start: date,
                   store: Path = market_store.STORE_DIR,
                   clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Copy the two series of a kept, validated package into one store snapshot; reuse it when already imported."""
    acquisition, validation, files = verified_package(store / market_store.PACKAGES / package_id)
    targets = dict(sorted(source_bound(BOARD_H15).items(), key=lambda item: item[1]))  # observable -> series ID
    if set(targets.values()) != set(SERIES) or set(validation["rows"]) != set(SERIES):
        raise PackageImportRefused("The registry's H.15 entries and the package's series do not match")
    for series_id in targets.values():
        first = date.fromisoformat(validation["series"][series_id]["first"])
        if observation_start < first:
            raise PackageImportRefused(f"The package states {series_id} from {first.isoformat()}; a start before that "
                                       "would leave the sessions before it unstated")
    common_last = date.fromisoformat(validation["coverage"]["last"])
    if observation_start > common_last:
        raise PackageImportRefused(f"The package states both series only through {common_last.isoformat()}; choose a "
                                   "start on or before it")
    exceptions = load_exceptions()
    calendar = calendar_identity(exceptions)
    import_key = digest({"adapter_version": ADAPTER_VERSION, "package_id": package_id,
                         "package_sha256": files["package_sha256"], "validation_sha256": files["validation_sha256"],
                         "parser_version": validation["parser_version"], "observation_start": observation_start.isoformat(),
                         "calendar": calendar})
    existing = _existing(connection, import_key)
    if existing is not None:
        return _report(connection, existing, created=False)

    received = utc(market_package.moment(acquisition["received_at"], "received_at"))
    created = utc(clock())
    if created < received:
        raise PackageImportRefused("The clock is earlier than the package's receipt; nothing was written")
    copied = {series_id: {period: text for period, text in validation["rows"][series_id].items()
                          if date.fromisoformat(period) >= observation_start}
              for series_id in targets.values()}
    last = max(date.fromisoformat(next(reversed(rows))) for rows in copied.values())
    sessions = expected_sessions(observation_start, last)
    classified, summary, metadata = {}, {}, {}
    for observable_id, series_id in targets.items():
        rows = [(date.fromisoformat(period), None if text == NO_VALUE else float(text))
                for period, text in copied[series_id].items()]
        # Calendar exceptions name series by their FRED crosswalk IDs (see market_calendar and event_context).
        classified[series_id] = reconcile(SERIES[series_id]["fred_equivalent"], rows, sessions, exceptions,
                                          coverage_start=observation_start)
        described = validation["series"][series_id]
        metadata[series_id] = {
            "series_id": series_id, "unique_identifier": SERIES[series_id]["unique_identifier"],
            "dataset": described["dataset"], "attributes": described["attributes"],
            "short_description": described["short_description"], "long_description": described["long_description"],
            "unit": described["attributes"]["UNIT"], "multiplier": described["attributes"]["UNIT_MULT"],
            "frequency": "Business day (FREQ code 9, checked from the observations)",
            "fred_equivalent": SERIES[series_id]["fred_equivalent"],
            "fred_equivalent_note": "The Board's DDP-FRED crosswalk lists this FRED ID; nothing here came from FRED."}
        periods = list(copied[series_id])
        summary[series_id] = {
            "observable_id": observable_id, "metadata": metadata[series_id], "rows": len(periods),
            "first_date": periods[0], "last_date": periods[-1],
            "classified_from": observation_start.isoformat(),
            "classified_through": classified[series_id][-1][0].isoformat(),
            "first_classified_date": classified[series_id][0][0].isoformat(),
            "package_coverage": {key: described[key] for key in ("first", "last", "observations", "values", "no_value",
                                                                 "missing_weekdays")},
            "metadata_sha256": _sha256(canonical(metadata[series_id]).encode("utf-8")),
            "observations_sha256": _sha256(canonical(copied[series_id]).encode("utf-8")),
            "statuses": dict(sorted(Counter(status for _, _, status in classified[series_id]).items())),
        }
    header = validation["header"]
    payload = {
        "provider": BOARD_H15, "adapter_version": ADAPTER_VERSION, "semantics": SEMANTICS,
        "request": {"local_copy": True, "observation_start": observation_start.isoformat(),
                    "series": list(targets.values())},
        "vintage_date": None, "retrieved_at": received.isoformat(), "created_at": created.isoformat(),
        "source": {"source_id": market_package.SOURCE_ID, "publisher": SOURCE["publisher"], "release": SOURCE["release"],
                   "url": acquisition["url"], "package_id": package_id, "package_record_version":
                   acquisition["package_record_version"], "requested_at": acquisition["requested_at"],
                   "received_at": acquisition["received_at"], "package_bytes": files["package_bytes"],
                   "package_sha256": files["package_sha256"], "acquisition_sha256": files["acquisition_sha256"],
                   "acquisition_method": acquisition["acquisition_method"],
                   "approval_id": acquisition["approval"].get("approval_id"), "terms": TERMS},
        "validation": {"validation_version": validation["validation_version"],
                       "parser_version": validation["parser_version"], "validated_at": validation["validated_at"],
                       "record_sha256": files["validation_sha256"], "rows_sha256": validation["rows_sha256"],
                       "data_entry": validation["data_entry"], "coverage": validation["coverage"],
                       "header": {"id": header.get("id"), "name": header.get("name"),
                                  "prepared_as_stated": header.get("prepared")}},
        "calendar": calendar, "series": summary, "import_key": import_key,
    }
    snapshot_id = digest(payload)
    with connection:  # One transaction: the snapshot, both series and every classified date, or nothing.
        connection.execute("INSERT INTO market_snapshots VALUES (?,?,?,?,?)",
                           (snapshot_id, BOARD_H15, VINTAGE_COLUMN, received.isoformat(), canonical(payload)))
        for series_id in targets.values():
            connection.execute("INSERT INTO market_series VALUES (?,?,?,?,?)",
                               (snapshot_id, series_id, canonical(metadata[series_id]),
                                gzip.compress(canonical(metadata[series_id]).encode("utf-8"), mtime=0),
                                gzip.compress(canonical(copied[series_id]).encode("utf-8"), mtime=0)))
            stated = copied[series_id]
            connection.executemany(
                "INSERT INTO market_observations VALUES (?,?,?,?,?,?,?,?)",
                [(snapshot_id, series_id, day.isoformat(), value, stated.get(day.isoformat()), status, None, None)
                 for day, value, status in classified[series_id]])
    return _report(connection, snapshot_id, created=True)


def _report(connection: sqlite3.Connection, snapshot_id: str, created: bool) -> dict:
    payload = load_snapshot(connection, snapshot_id).payload
    return {"snapshot_id": snapshot_id, "created": created, "provider": payload["provider"],
            "vintage_date": payload["vintage_date"], "retrieved_at": payload["retrieved_at"],
            "created_at": payload["created_at"], "semantics": payload["semantics"],
            "source": {key: payload["source"][key] for key in ("package_id", "package_sha256", "received_at", "url")},
            "validation": {key: payload["validation"][key] for key in ("parser_version", "record_sha256",
                                                                       "rows_sha256")},
            "source_prepared_as_stated": payload["validation"]["header"]["prepared_as_stated"],
            "series": {series_id: {key: entry[key] for key in ("observable_id", "rows", "first_date", "last_date",
                                                               "classified_from", "classified_through", "statuses")}
                       for series_id, entry in payload["series"].items()}}

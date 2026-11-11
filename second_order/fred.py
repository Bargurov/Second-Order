"""FRED import: the only network path, run only by the explicit `market import` command.

Every snapshot keeps three different facts apart:
- observation date: FRED's `date` for each row;
- vintage date: the requested FRED real-time period (realtime_start = realtime_end = vintage).
  Values are what FRED reports for that period. A row's realtime_start/realtime_end describe
  FRED's real-time period; they are not the issuer's first publication date, and FRED may not
  retain past vintages for every daily series, so an older vintage is not assumed to be one;
- retrieved_at: our clock after every response arrived. It shows we possessed these values
  by then; it does not establish when they first became public.
The API key is passed in by the caller, sent only as a request parameter, and never stored,
logged or included in an error message.
"""
from collections import Counter
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import math
import sqlite3
from typing import Callable
import httpx
from .data import ny_date
from .market_calendar import calendar_identity, expected_sessions, load_exceptions, reconcile
from .registry import FRED, source_bound
from .schema import utc
from .snapshots import list_snapshots, load_snapshot, snapshot_readiness, snapshot_revisions
from .store import canonical, digest

FRED_API = "https://api.stlouisfed.org/fred"
ADAPTER_VERSION = "fred-3"  # fred-2: classification starts at observation_start; fred-3: boundary stored explicitly.
SEMANTICS = {
    "observation_date": "FRED row date; Treasury quotes are taken 'at or near 3:30 PM' with no documented bound",
    "vintage_date": "requested FRED real-time period; not the issuer's first publication date",
    "retrieved_at": "our clock after every response arrived; shows possession, not first public availability",
}


class ImportRefused(ValueError):
    pass


def fetch(client: httpx.Client, endpoint: str, params: dict, api_key: str) -> bytes:
    try:
        response = client.get(f"{FRED_API}/{endpoint}", params={**params, "api_key": api_key, "file_type": "json"})
    except httpx.HTTPError as exc:
        # The exception text can contain the request URL, which carries the key: never surface it.
        raise ImportRefused(f"FRED request to {endpoint} failed ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise ImportRefused(f"FRED request to {endpoint} returned HTTP {response.status_code}")
    if api_key.encode() in response.content:
        raise ImportRefused(f"FRED response from {endpoint} contained the credential; nothing was stored")
    return response.content


def parse_metadata(body: bytes, series_id: str) -> dict:
    try:
        entries = json.loads(body)["seriess"]
    except (ValueError, KeyError, TypeError):
        raise ImportRefused(f"Unreadable FRED metadata for {series_id}") from None
    if len(entries) != 1 or entries[0].get("id") != series_id:
        raise ImportRefused(f"FRED metadata does not describe {series_id}")
    entry = entries[0]
    if entry.get("units") != "Percent" or entry.get("frequency_short") != "D":
        raise ImportRefused(f"{series_id} is not a daily series in percent; the registry measures bp changes")
    notes = str(entry.get("notes") or "")
    if "copyright" in notes.lower():
        raise ImportRefused(f"FRED marks {series_id} as copyrighted; stop and review its terms")
    kept = ("id", "title", "units", "frequency_short", "seasonal_adjustment_short", "last_updated",
            "realtime_start", "realtime_end")
    return {key: entry.get(key) for key in kept} | {"notes_sha256": hashlib.sha256(notes.encode()).hexdigest()}


def parse_observations(body: bytes, series_id: str, vintage: date) -> list[tuple[date, str, float | None, str, str]]:
    try:
        payload = json.loads(body)
        items = payload["observations"]
    except (ValueError, KeyError, TypeError):
        raise ImportRefused(f"Unreadable FRED observations for {series_id}") from None
    pinned = vintage.isoformat()
    if payload.get("realtime_start") != pinned or payload.get("realtime_end") != pinned:
        raise ImportRefused(f"{series_id} observations are not pinned to vintage {pinned}")
    rows, previous = [], None
    for item in items:
        try:
            day, raw = date.fromisoformat(item["date"]), item["value"]
            start, end = item["realtime_start"], item["realtime_end"]
        except (KeyError, TypeError, ValueError):
            raise ImportRefused(f"Malformed FRED observation for {series_id}") from None
        if previous is not None and day <= previous:
            raise ImportRefused(f"{series_id} observation dates are not strictly increasing")
        if not start <= pinned <= end:
            raise ImportRefused(f"{series_id} returned a row outside the requested real-time period")
        if raw == ".":
            value = None
        else:
            try:
                value = float(raw)
            except ValueError:
                raise ImportRefused(f"{series_id} has a non-numeric value on {day}") from None
            if not math.isfinite(value):
                raise ImportRefused(f"{series_id} has a non-finite value on {day}")
        rows.append((day, raw, value, start, end))
        previous = day
    if not rows:
        raise ImportRefused(f"FRED returned no observations for {series_id}")
    return rows


def import_snapshot(connection: sqlite3.Connection, api_key: str, observation_start: date,
                    vintage: date | None = None, client: httpx.Client | None = None,
                    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Fetch every source-bound series at one pinned vintage and append one snapshot atomically."""
    if not api_key:
        raise ImportRefused("FRED_API_KEY is not set; only the import command reads it")
    today = ny_date(utc(clock()))
    vintage = vintage or today
    if vintage > today or observation_start >= vintage:
        raise ImportRefused("The vintage must not be in the future and must follow the observation start")
    pinned = {"realtime_start": vintage.isoformat(), "realtime_end": vintage.isoformat()}
    series = dict(sorted(source_bound(FRED).items(), key=lambda item: item[1]))  # FRED's series only.
    responses, own_client = {}, client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        for observable_id, series_id in series.items():
            metadata = fetch(client, "series", {"series_id": series_id, **pinned}, api_key)
            observations = fetch(client, "series/observations", {
                "series_id": series_id, **pinned, "observation_start": observation_start.isoformat(),
                "sort_order": "asc"}, api_key)
            responses[series_id] = (observable_id, metadata, observations)
    finally:
        if own_client:
            client.close()
    retrieved_at = utc(clock())
    exceptions = load_exceptions()
    parsed = {series_id: (observable_id, parse_metadata(metadata, series_id),
                          parse_observations(observations, series_id, vintage), metadata, observations)
              for series_id, (observable_id, metadata, observations) in responses.items()}
    # Classification covers the requested range, not just the rows FRED happened to return.
    first = min(observation_start, *(rows[0][0] for _, _, rows, _, _ in parsed.values()))
    last = max(rows[-1][0] for _, _, rows, _, _ in parsed.values())
    sessions = expected_sessions(first, last)
    classified, summary = {}, {}
    for series_id, (observable_id, metadata, rows, raw_metadata, raw_observations) in parsed.items():
        classified[series_id] = reconcile(series_id, [(day, value) for day, _, value, _, _ in rows],
                                          sessions, exceptions, coverage_start=observation_start)
        summary[series_id] = {
            "observable_id": observable_id, "metadata": metadata, "rows": len(rows),
            "first_date": rows[0][0].isoformat(), "last_date": rows[-1][0].isoformat(),
            # Boundary, not first observation: every expected session from this date on is classified,
            # so a weekend or holiday at the start legitimately has nothing to classify.
            "classified_from": observation_start.isoformat(),
            "classified_through": classified[series_id][-1][0].isoformat(),
            "first_classified_date": classified[series_id][0][0].isoformat(),
            "metadata_sha256": hashlib.sha256(raw_metadata).hexdigest(),
            "observations_sha256": hashlib.sha256(raw_observations).hexdigest(),
            "statuses": dict(sorted(Counter(status for _, _, status in classified[series_id]).items())),
        }
    payload = {
        "provider": "fred", "adapter_version": ADAPTER_VERSION, "semantics": SEMANTICS,
        "request": {"endpoint": FRED_API, "file_type": "json", "sort_order": "asc", **pinned,
                    "observation_start": observation_start.isoformat(), "series": list(series.values())},
        "vintage_date": vintage.isoformat(), "retrieved_at": retrieved_at.isoformat(),
        "calendar": calendar_identity(exceptions), "series": summary,
    }
    snapshot_id = digest(payload)
    with connection:
        connection.execute("INSERT INTO market_snapshots VALUES (?,?,?,?,?)",
                           (snapshot_id, "fred", vintage.isoformat(), retrieved_at.isoformat(), canonical(payload)))
        for series_id, (_, metadata, rows, raw_metadata, raw_observations) in parsed.items():
            connection.execute("INSERT INTO market_series VALUES (?,?,?,?,?)",
                               (snapshot_id, series_id, canonical(metadata), gzip.compress(raw_metadata, mtime=0),
                                gzip.compress(raw_observations, mtime=0)))
            provided = {day: (raw, start, end) for day, raw, _, start, end in rows}
            stored = []
            for day, value, status in classified[series_id]:
                raw, start, end = provided.get(day, (None, None, None))  # An absent session has no FRED row.
                stored.append((snapshot_id, series_id, day.isoformat(), value, raw, status, start, end))
            connection.executemany("INSERT INTO market_observations VALUES (?,?,?,?,?,?,?,?)", stored)
    return {"snapshot_id": snapshot_id, **{key: payload[key] for key in ("vintage_date", "retrieved_at", "semantics")},
            "series": {series_id: {key: value for key, value in entry.items() if key != "metadata"}
                       for series_id, entry in summary.items()}}


def import_and_report(connection: sqlite3.Connection, api_key: str, observation_start: date,
                      vintage: date | None = None, client: httpx.Client | None = None,
                      clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Store one snapshot, then report separately whether it holds enough history to evaluate."""
    previous = [row for row in list_snapshots(connection) if row["provider"] == FRED]  # Revisions within FRED only.
    stored = import_snapshot(connection, api_key, observation_start, vintage, client, clock)
    snapshot = load_snapshot(connection, stored["snapshot_id"])
    result = {"stored": stored, "readiness": snapshot_readiness(snapshot)}
    if previous:
        result["revisions_since"] = previous[-1]["snapshot_id"]
        result["revisions"] = snapshot_revisions(load_snapshot(connection, previous[-1]["snapshot_id"]), snapshot)
    return result

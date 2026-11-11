"""Calendar cross-check for daily Treasury yields.

SIFMA's recommended US bond-market schedule (through pandas_market_calendars) is documentation
used to explain gaps; it is not Treasury's observation or publication calendar. Every provider
date is classified. Only gaps explained by that schedule or by a versioned exception citing
issuer documentation leave the observation grid; unexplained missing values stay in the grid as
missing, so horizons are never compressed. Classification happens at import and is stored.
"""
from datetime import date
import importlib.metadata
import json
from pathlib import Path

CALENDAR = "SIFMAUS"
EXCEPTIONS_PATH = Path(__file__).with_name("calendar_exceptions.json")
EXCEPTION_KINDS = {"issuer_no_observation", "issuer_observation_on_calendar_holiday"}
# Status -> whether the provider value is kept. Statuses absent here leave the grid (explained gaps).
GRID_STATUSES = {
    "session_value": True,
    "session_missing": False,  # Calendar session with no provider value: missing, never dropped.
    "session_absent": False,  # Calendar session with no provider row at all.
    "unreconciled_value_on_calendar_holiday": False,  # Unexplained disagreement: kept as missing.
    "issuer_observation_on_calendar_holiday": True,
}
EXPLAINED_GAPS = {"calendar_holiday", "issuer_no_observation"}


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("version"), str) or not payload["version"]:
        raise ValueError("Calendar exceptions need a version")
    seen = set()
    for entry in payload.get("exceptions", []):
        if entry.get("kind") not in EXCEPTION_KINDS or not entry.get("series"):
            raise ValueError("Unknown calendar exception kind or series")
        date.fromisoformat(entry["date"])
        if not str(entry.get("source", "")).startswith("https://"):
            raise ValueError("Each calendar exception must cite issuer documentation")
        key = (entry["series"], entry["date"])
        if key in seen:
            raise ValueError("Duplicate calendar exception")
        seen.add(key)
    return payload


def calendar_identity(exceptions: dict) -> dict:
    return {"calendar": CALENDAR, "library": "pandas_market_calendars",
            "library_version": importlib.metadata.version("pandas_market_calendars"),
            "exceptions_version": exceptions["version"]}


def expected_sessions(start: date, end: date) -> set[date]:
    import pandas_market_calendars as calendars  # Needed only by the explicit import action.
    return {day.date() for day in calendars.get_calendar(CALENDAR).valid_days(start.isoformat(), end.isoformat())}


def reconcile(series_id: str, rows: list[tuple[date, float | None]], sessions: set[date],
              exceptions: dict, coverage_start: date | None = None) -> list[tuple[date, float | None, str]]:
    """Classify every date from coverage_start (the requested start) to the last provider row.

    Expected sessions a response omitted at its start are recorded as absent, so they can never
    silently move an anchor or shorten a horizon.
    """
    provided = dict(rows)
    if len(provided) != len(rows):
        raise ValueError("Duplicate provider dates")
    documented = {entry["date"]: entry["kind"] for entry in exceptions["exceptions"]
                  if entry["series"] in (series_id, "*")}
    first, last = min(provided), max(provided)
    if coverage_start is not None:
        first = min(first, coverage_start)
    classified = []
    for day in sorted(set(provided) | {day for day in sessions if first <= day <= last}):
        exception = documented.get(day.isoformat())
        value = provided.get(day)
        if day in sessions:
            if value is not None:
                status = "session_value"
            elif exception == "issuer_no_observation":
                status = "issuer_no_observation"
            else:
                status = "session_missing" if day in provided else "session_absent"
        elif value is None:
            status = "calendar_holiday"
        elif exception == "issuer_observation_on_calendar_holiday":
            status = "issuer_observation_on_calendar_holiday"
        else:
            status = "unreconciled_value_on_calendar_holiday"
        classified.append((day, value, status))
    return classified


def observation_grid(classified: list[tuple[date, float | None, str]]) -> list[tuple[date, float | None]]:
    """Dates that stay in the grid; explained gaps leave it, everything else is kept (possibly missing)."""
    return [(day, value if GRID_STATUSES[status] else None)
            for day, value, status in classified if status in GRID_STATUSES]

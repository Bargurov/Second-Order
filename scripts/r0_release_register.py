"""R0 normalized macro-release record contract (``r0-release-register-v1``).

The smallest durable normalized representation of one scheduled U.S.
macro release observation (CPI, Employment Situation) that preserves
point-in-time meaning for a possible future release-surprise event
study.  Three prior layers stay permanently distinct:

* ``prior``          — the previous reference month as ORIGINALLY
                       published (the first vintage that ever contained
                       it, strictly before this release);
* ``revised_prior``  — the previous reference month as shown in the
                       release-day vintage of THIS release;
* the latest revised historical value is deliberately NOT a field of
  this record: it is not point-in-time information and may never
  populate one.

Missing research meaning is never conveyed by a bare null: every value
cell carries an explicit status and, when not available, a reason.

This module is pure normalization: no network access, no storage
layer, no clock reads — every timestamp is an input.  Fail-closed
rules: a vintage after the release date, a malformed number, an
invalid reference period, or a duplicate release identity raise
``ValueError``; data-level gaps (missing consensus, missing prior,
unresolved timestamps, incompatible units) stay in the record as
explicit availability states.
"""

from __future__ import annotations

import copy
import json
import math
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

R0_CONTRACT = "r0-release-register-v1"

FAMILIES = ("cpi", "employment")

RELEASE_NAMES = {
    "cpi": "Consumer Price Index",
    "employment": "Employment Situation",
}

RELEASE_TIMEZONE = "America/New_York"
FREQUENCY = "monthly"

# Source-pinned measurement series per family.  One record exists per
# (release, series); the register never mixes units, measure kinds, or
# seasonal-adjustment bases inside a record.
SERIES: dict[str, tuple[dict[str, str], ...]] = {
    "cpi": (
        {"series_id": "CPIAUCSL",
         "measure": "cpi_u_all_items_sa_index",
         "unit": "index_1982_1984_100",
         "seasonal_adjustment": "SA",
         "measure_kind": "monthly_level"},
        {"series_id": "CPIAUCNS",
         "measure": "cpi_u_all_items_nsa_index",
         "unit": "index_1982_1984_100",
         "seasonal_adjustment": "NSA",
         "measure_kind": "monthly_level"},
    ),
    "employment": (
        {"series_id": "PAYEMS",
         "measure": "total_nonfarm_payrolls_sa_level",
         "unit": "thousands_of_persons",
         "seasonal_adjustment": "SA",
         "measure_kind": "monthly_level"},
        {"series_id": "UNRATE",
         "measure": "unemployment_rate_sa",
         "unit": "percent_of_labor_force",
         "seasonal_adjustment": "SA",
         "measure_kind": "monthly_level"},
    ),
}

# Record-level availability vocabulary (frozen; exact tokens).
AVAILABILITY_STATES = (
    "available", "missing_consensus", "missing_prior", "missing_actual",
    "timestamp_unresolved", "unit_incompatible", "revision_ambiguous",
    "source_unavailable", "not_applicable")

# Most-severe-first precedence used to pick the single record-level
# status; every contributing reason is still preserved in
# ``missing_reason``.
_AVAILABILITY_PRECEDENCE = (
    "source_unavailable", "timestamp_unresolved", "unit_incompatible",
    "missing_actual", "missing_prior", "missing_consensus",
    "revision_ambiguous")

# Per-field cell statuses.
CELL_STATUSES = ("available", "missing", "not_applicable",
                 "source_unavailable", "unit_incompatible")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _require_iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date string")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO date: {value!r}"
                         ) from exc
    return value


def value_cell(*, value: Any = None, status: str = "available", unit: str,
               seasonal_adjustment: str, measure_kind: str,
               vintage_date: Optional[str] = None,
               reason: Optional[str] = None) -> dict[str, Any]:
    """Build one validated value cell.

    ``available`` cells carry a finite number and no reason; every
    other status carries no value and a mandatory reason, so missing
    research meaning is always explicit, never a bare null.
    """
    if status not in CELL_STATUSES:
        raise ValueError(f"unknown cell status: {status!r}")
    for label, text in (("unit", unit),
                        ("seasonal_adjustment", seasonal_adjustment),
                        ("measure_kind", measure_kind)):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"cell {label} must be a non-empty string")
    if status == "available":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"available cell requires a numeric value, got {value!r}")
        if not math.isfinite(float(value)):
            raise ValueError(
                f"available cell requires a finite value, got {value!r}")
        if reason is not None:
            raise ValueError("available cell must not carry a reason")
        if vintage_date is not None:
            _require_iso_date(vintage_date, "vintage_date")
        value = float(value)
    else:
        if value is not None:
            raise ValueError(f"{status} cell must not carry a value")
        if vintage_date is not None:
            raise ValueError(f"{status} cell must not carry a vintage")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{status} cell requires an explicit reason")
    return {
        "value": value,
        "status": status,
        "unit": unit,
        "seasonal_adjustment": seasonal_adjustment,
        "measure_kind": measure_kind,
        "vintage_date": vintage_date,
        "reason": reason,
    }


def _validate_cell(cell: Any, label: str) -> dict[str, Any]:
    if not isinstance(cell, Mapping):
        raise ValueError(f"{label} must be a value cell mapping")
    return value_cell(
        value=cell.get("value"), status=cell.get("status", ""),
        unit=cell.get("unit", ""),
        seasonal_adjustment=cell.get("seasonal_adjustment", ""),
        measure_kind=cell.get("measure_kind", ""),
        vintage_date=cell.get("vintage_date"),
        reason=cell.get("reason"))


def _validate_reference_period(reference_period: Any,
                               release_date: str) -> str:
    if not isinstance(reference_period, str) or \
            not _PERIOD_RE.match(reference_period):
        raise ValueError(
            f"reference_period must be YYYY-MM, got {reference_period!r}")
    year, month = int(reference_period[:4]), int(reference_period[5:7])
    period_end = date(year, month, monthrange(year, month)[1])
    if period_end >= date.fromisoformat(release_date):
        raise ValueError(
            f"reference period {reference_period} is not fully elapsed "
            f"before the release date {release_date}")
    return reference_period


def _guard_point_in_time(label: str, cell: Mapping[str, Any],
                         release_date: str) -> None:
    """No future revision may populate a point-in-time field."""
    if cell["status"] != "available":
        return
    vintage = cell["vintage_date"]
    if vintage is None:
        raise ValueError(f"{label} requires vintage provenance")
    if vintage > release_date:
        raise ValueError(
            f"{label} vintage {vintage} postdates the release date "
            f"{release_date}; a future revision may never populate a "
            f"point-in-time field")
    if label in ("actual", "revised_prior") and vintage != release_date:
        raise ValueError(
            f"{label} must come from the release-day vintage "
            f"{release_date}, got {vintage}")
    if label == "prior" and vintage >= release_date:
        raise ValueError(
            f"prior must come from a vintage strictly before the release "
            f"date {release_date}, got {vintage}")


def _resolve_timestamp(schedule_entry: Mapping[str, Any],
                       release_date: str
                       ) -> tuple[Optional[str], list[str]]:
    """Resolve the scheduled timestamp; ambiguity fails closed."""
    problems: list[str] = []
    conflicts = schedule_entry.get("schedule_conflicts") or []
    if conflicts:
        attested = sorted({str(c.get("release_date"))
                           for c in conflicts})
        problems.append("conflicting schedule attestations: "
                        + ", ".join(attested))
    raw_time = schedule_entry.get("release_time_local")
    parsed: Optional[str] = None
    if isinstance(raw_time, str) and _TIME_RE.match(raw_time.strip()):
        parsed = raw_time.strip()
    else:
        problems.append(
            f"release time missing or unparseable: {raw_time!r}")
    if problems:
        return None, problems
    hour, minute = int(parsed[:2]), int(parsed[3:5])
    d = date.fromisoformat(release_date)
    stamped = datetime(d.year, d.month, d.day, hour, minute,
                       tzinfo=ZoneInfo(RELEASE_TIMEZONE))
    return stamped.isoformat(), []


def normalize_release(*, family: str, series: Mapping[str, str],
                      schedule_entry: Mapping[str, Any],
                      actual: Mapping[str, Any],
                      prior: Mapping[str, Any],
                      revised_prior: Mapping[str, Any],
                      consensus: Mapping[str, Any],
                      source_reference: Mapping[str, str],
                      source_timestamp: str,
                      retrieval_method: str) -> dict[str, Any]:
    """Normalize one (release, series) observation into the frozen
    contract record.  Construction-contract violations raise; data-level
    gaps become explicit availability states."""
    if family not in FAMILIES:
        raise ValueError(f"unknown family: {family!r}")
    registered = {s["series_id"]: s for s in SERIES[family]}
    series_id = series.get("series_id") if isinstance(series, Mapping) \
        else None
    if series_id not in registered or dict(series) != \
            registered[series_id]:
        raise ValueError(
            f"series {series_id!r} is not registered for family "
            f"{family!r}")
    meta = registered[series_id]

    release_date = _require_iso_date(
        schedule_entry.get("release_date"), "release_date")
    reference_period = _validate_reference_period(
        schedule_entry.get("reference_period"), release_date)

    if not isinstance(source_reference, Mapping) or not source_reference:
        raise ValueError("source_reference must be a non-empty mapping")
    if not isinstance(source_timestamp, str) or not \
            source_timestamp.strip():
        raise ValueError("source_timestamp must be a non-empty string")
    if not isinstance(retrieval_method, str) or not \
            retrieval_method.strip():
        raise ValueError("retrieval_method must be a non-empty string")

    cells = {
        "actual": _validate_cell(actual, "actual"),
        "prior": _validate_cell(prior, "prior"),
        "revised_prior": _validate_cell(revised_prior, "revised_prior"),
        "consensus": _validate_cell(consensus, "consensus"),
    }
    for label, cell in cells.items():
        _guard_point_in_time(label, cell, release_date)

    reasons: list[str] = []
    flags: set[str] = set()

    # --- units: one basis end-to-end, never silently mixed -----------------
    unit_problems = []
    for label, cell in cells.items():
        for key in ("unit", "seasonal_adjustment", "measure_kind"):
            if cell[key] != meta[key]:
                unit_problems.append(
                    f"{label} {key} {cell[key]!r} differs from the series "
                    f"declaration {meta[key]!r}")
    if unit_problems:
        flags.add("unit_incompatible")
        reasons.append("incompatible measurement bases: "
                       + "; ".join(unit_problems))
        demoted = {}
        for label, cell in cells.items():
            demoted[label] = value_cell(
                value=None, status="unit_incompatible",
                unit=meta["unit"],
                seasonal_adjustment=meta["seasonal_adjustment"],
                measure_kind=meta["measure_kind"], vintage_date=None,
                reason="demoted: incompatible measurement bases within "
                       "the record")
        cells = demoted

    # --- scheduled timestamp ----------------------------------------------
    scheduled_timestamp, timestamp_problems = _resolve_timestamp(
        schedule_entry, release_date)
    if timestamp_problems:
        flags.add("timestamp_unresolved")
        reasons.extend(timestamp_problems)

    # --- per-field availability -------------------------------------------
    field_state = {"actual": "missing_actual", "prior": "missing_prior",
                   "consensus": "missing_consensus"}
    for label, state in field_state.items():
        cell = cells[label]
        if cell["status"] == "available":
            continue
        if label == "actual" and cell["status"] == "source_unavailable":
            flags.add("source_unavailable")
        flags.add(state)
        reasons.append(f"{label}: {cell['reason']}")
    if cells["revised_prior"]["status"] != "available" and \
            "unit_incompatible" not in flags:
        reasons.append(
            f"revised_prior: {cells['revised_prior']['reason']}")

    # --- revision relation -------------------------------------------------
    prior_ok = cells["prior"]["status"] == "available"
    revised_ok = cells["revised_prior"]["status"] == "available"
    if prior_ok and revised_ok:
        revision_status = ("prior_unrevised"
                           if cells["prior"]["value"] ==
                           cells["revised_prior"]["value"]
                           else "prior_revised")
    elif prior_ok or revised_ok:
        revision_status = "revision_ambiguous"
        flags.add("revision_ambiguous")
        reasons.append("revision relation not assessable: only one of "
                       "prior / revised_prior is available")
    else:
        revision_status = "not_applicable"

    availability_status = "available"
    for state in _AVAILABILITY_PRECEDENCE:
        if state in flags:
            availability_status = state
            break

    record = {
        "contract": R0_CONTRACT,
        "release_id": f"{family}:{release_date}",
        "family": family,
        "release_name": RELEASE_NAMES[family],
        "series_id": meta["series_id"],
        "measure": meta["measure"],
        "reference_period": reference_period,
        "release_date": release_date,
        "scheduled_timestamp": scheduled_timestamp,
        "scheduled_timezone": RELEASE_TIMEZONE,
        "actual": cells["actual"],
        "prior": cells["prior"],
        "revised_prior": cells["revised_prior"],
        "consensus": cells["consensus"],
        "unit": meta["unit"],
        "seasonal_adjustment": meta["seasonal_adjustment"],
        "measure_kind": meta["measure_kind"],
        "frequency": FREQUENCY,
        "source_reference": dict(source_reference),
        "source_timestamp": source_timestamp,
        "retrieval_method": retrieval_method,
        "revision_status": revision_status,
        "availability_status": availability_status,
        "missing_reason": "; ".join(reasons) if reasons else None,
        "schedule_attestation": {
            "source_snapshots": list(
                schedule_entry.get("source_snapshots") or []),
            "schedule_conflicts": copy.deepcopy(
                list(schedule_entry.get("schedule_conflicts") or [])),
        },
    }
    return copy.deepcopy(record)


def build_register(records: Sequence[Mapping[str, Any]]
                   ) -> list[dict[str, Any]]:
    """Deterministically ordered register; duplicate identities fail
    closed."""
    seen_release: set[tuple[str, str, str]] = set()
    seen_period: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping) or \
                record.get("contract") != R0_CONTRACT:
            raise ValueError("register accepts only r0 contract records")
        release_key = (record["family"], record["series_id"],
                       record["release_date"])
        period_key = (record["family"], record["series_id"],
                      record["reference_period"])
        if release_key in seen_release:
            raise ValueError(
                f"duplicate release identity: {release_key}")
        if period_key in seen_period:
            raise ValueError(
                f"duplicate reference period for one series: "
                f"{period_key}")
        seen_release.add(release_key)
        seen_period.add(period_key)
        out.append(copy.deepcopy(dict(record)))
    out.sort(key=lambda r: (r["release_date"], r["family"],
                            r["series_id"], r["reference_period"]))
    return out


def canonical_json(obj: Any) -> str:
    """Stable canonical serialization for determinism proofs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)

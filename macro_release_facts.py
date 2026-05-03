"""Cached store of official macro-release facts.

One row per official print, keyed by ``release_key`` — a synthetic
string like ``"CPI:2026-04-10"`` that pairs a ``macro_calendar`` entry
(indicator name + scheduled date) with the values the issuing agency
actually publishes.  Distinct from ``macro_surprises.py``: that store
keeps z-scored surprise classifications keyed on internal series ids
like ``us_cpi_yoy`` and the rich category enum needed for downstream
research; this one is a thin write target a future feed can plug into
to surface ``actual`` / ``prior`` / ``revised_prior`` / ``consensus``
on the calendar without rewriting history.

Stable schema (see ``db.init_db`` for SQL):

    release_key    TEXT PRIMARY KEY      ``"<indicator>:<release_date>"``
    release_time   TEXT NOT NULL         ISO-8601 timestamp of the print
    actual         REAL                  published headline value
    prior          REAL                  prior period as published before
    revised_prior  REAL                  revised prior, when issued
    consensus      REAL                  pre-release consensus expectation
    source         TEXT NOT NULL DEFAULT '' provenance label (e.g. ``BLS``)
    created_at     TEXT NOT NULL
    updated_at     TEXT NOT NULL

All numeric fields are optional so a feed can land partial rows
without blocking; readers must tolerate ``None`` for any of them.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from db import DB_FILE


def make_release_key(indicator: str, release_date: str) -> str:
    """Compose the canonical release_key for an indicator/date pair.

    Both inputs are required and must be non-empty strings.  No
    additional normalisation is applied — callers are expected to pass
    the same indicator name (``"CPI"``, ``"NFP"``, …) and ISO date
    (``"2026-04-10"``) used by ``macro_calendar``.
    """
    if not isinstance(indicator, str) or not indicator.strip():
        raise ValueError("indicator must be a non-empty string")
    if not isinstance(release_date, str) or not release_date.strip():
        raise ValueError("release_date must be a non-empty string")
    return f"{indicator.strip()}:{release_date.strip()}"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SELECT_COLUMNS = (
    "release_key, release_time, actual, prior, revised_prior, "
    "consensus, source, created_at, updated_at"
)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "release_key":   row[0],
        "release_time":  row[1],
        "actual":        row[2],
        "prior":         row[3],
        "revised_prior": row[4],
        "consensus":     row[5],
        "source":        row[6] or "",
        "created_at":    row[7],
        "updated_at":    row[8],
    }


def _check_number(value: Any, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number or None")
    if not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite; got {value!r}")


def upsert_release_facts(
    *,
    release_key: str,
    release_time: str,
    actual: Optional[float] = None,
    prior: Optional[float] = None,
    revised_prior: Optional[float] = None,
    consensus: Optional[float] = None,
    source: str = "",
) -> dict[str, Any]:
    """Insert or update one row of release facts.

    Returns the stored row as a dict.  Re-upserting an existing
    ``release_key`` rewrites every supplied field and bumps
    ``updated_at`` while preserving ``created_at``.
    """
    if not isinstance(release_key, str) or not release_key.strip():
        raise ValueError("release_key must be a non-empty string")
    if not isinstance(release_time, str) or not release_time.strip():
        raise ValueError("release_time must be a non-empty string")
    if not isinstance(source, str):
        raise ValueError("source must be a string")
    for value, label in (
        (actual, "actual"), (prior, "prior"),
        (revised_prior, "revised_prior"), (consensus, "consensus"),
    ):
        _check_number(value, label)

    release_key = release_key.strip()
    release_time = release_time.strip()
    now = _utcnow_iso()

    with sqlite3.connect(DB_FILE) as conn:
        existing = conn.execute(
            "SELECT created_at FROM macro_release_facts "
            "WHERE release_key = ?",
            (release_key,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO macro_release_facts "
                "(release_key, release_time, actual, prior, "
                " revised_prior, consensus, source, "
                " created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    release_key, release_time, actual, prior,
                    revised_prior, consensus, source, now, now,
                ),
            )
        else:
            conn.execute(
                "UPDATE macro_release_facts SET "
                "release_time = ?, actual = ?, prior = ?, "
                "revised_prior = ?, consensus = ?, source = ?, "
                "updated_at = ? WHERE release_key = ?",
                (
                    release_time, actual, prior, revised_prior,
                    consensus, source, now, release_key,
                ),
            )

    row = get_release_facts(release_key)
    assert row is not None  # just wrote it
    return row


def get_release_facts(release_key: str) -> Optional[dict[str, Any]]:
    """Return the row for ``release_key`` or ``None`` when missing."""
    if not isinstance(release_key, str) or not release_key.strip():
        raise ValueError("release_key must be a non-empty string")
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM macro_release_facts "
            f"WHERE release_key = ?",
            (release_key.strip(),),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_release_facts_map(
    release_keys: list[str],
) -> dict[str, dict[str, Any]]:
    """Return ``{release_key: row}`` for every key that exists.

    Missing keys are simply omitted from the result so the caller can
    detect "no facts" without an extra null check per entry.
    """
    if not release_keys:
        return {}
    keys = [
        k.strip() for k in release_keys
        if isinstance(k, str) and k.strip()
    ]
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM macro_release_facts "
            f"WHERE release_key IN ({placeholders})",
            keys,
        ).fetchall()
    return {r[0]: _row_to_dict(r) for r in rows}


def delete_release_facts(release_key: str) -> bool:
    """Delete one row.  Returns True when a row was removed."""
    if not isinstance(release_key, str) or not release_key.strip():
        raise ValueError("release_key must be a non-empty string")
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "DELETE FROM macro_release_facts WHERE release_key = ?",
            (release_key.strip(),),
        )
        return cur.rowcount > 0

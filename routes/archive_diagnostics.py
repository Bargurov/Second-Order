"""Archive consistency diagnostics — read-only audit of ``events``.

Surfaces seven anomaly categories that an operator would otherwise have
to discover via ad-hoc SQL when hydration / mover backfills / archive
exports start producing surprising output.

Pure read.  Issues only ``SELECT`` statements directly against the
local SQLite ``events`` table.  Never imports ``price_cache`` /
``market_data`` / ``market_check``, never touches ``yfinance``, never
calls the LLM, never writes to the DB.

The router exposes ``GET /diagnostics/archive-consistency``; wiring
into the FastAPI app is intentionally left to ``api.py`` so this module
stays self-contained.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from fastapi import APIRouter

router = APIRouter()


_EXAMPLE_LIMIT = 10

_CATEGORY_KEYS: tuple[str, ...] = (
    "malformed_market_tickers_json",
    "missing_headline",
    "missing_timestamp",
    "missing_event_date",
    "malformed_event_date",
    "missing_market_tickers",
    "duplicate_headline_event_date_clusters",
)


def _empty_response() -> dict[str, dict[str, Any]]:
    return {key: {"count": 0, "examples": []} for key in _CATEGORY_KEYS}


def _is_blank_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_iso_date(value: Any) -> bool:
    """True when ``value`` parses as ISO ``YYYY-MM-DD`` (date prefix)."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return False
    return True


def _is_malformed_market_tickers(value: Any) -> bool:
    """True when ``market_tickers`` is present but unusable.

    NULL / empty / whitespace are classified as *missing* (not
    malformed).  A JSON parse failure or a parseable non-list value is
    malformed because every downstream consumer expects a list.
    """
    if _is_blank_string(value):
        return False
    if not isinstance(value, str):
        # Non-string non-NULL value (e.g. int from a corrupted row) —
        # cannot be a JSON-encoded ticker list.
        return True
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return True
    return not isinstance(parsed, list)


def compute_archive_consistency(
    *, db_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the consistency audit and return per-category counts + examples.

    Parameters
    ----------
    db_path
        Optional path to a SQLite ``events.db`` file.  When omitted,
        reads ``db.DB_FILE``.

    Returns
    -------
    dict
        One entry per category in :data:`_CATEGORY_KEYS`.  Each value is
        ``{"count": int, "examples": list[dict]}`` capped at
        :data:`_EXAMPLE_LIMIT` examples.
    """
    import db as _db

    path = db_path if db_path is not None else _db.DB_FILE

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return _empty_response()

    try:
        try:
            rows = conn.execute(
                "SELECT id, headline, timestamp, market_tickers, event_date "
                "FROM events ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            return _empty_response()

        per_row = _scan_per_row(rows)

        try:
            dup_rows = conn.execute(
                "SELECT headline, event_date, COUNT(*) AS cnt, "
                "       GROUP_CONCAT(id, ',') AS ids "
                "FROM events "
                "WHERE headline   IS NOT NULL AND TRIM(headline)   != '' "
                "  AND event_date IS NOT NULL AND TRIM(event_date) != '' "
                "GROUP BY headline, event_date "
                "HAVING cnt >= 2 "
                "ORDER BY cnt DESC, headline ASC, event_date ASC"
            ).fetchall()
        except sqlite3.Error:
            dup_rows = []
    finally:
        conn.close()

    duplicates: list[dict[str, Any]] = []
    for headline, event_date_str, cnt, ids_csv in dup_rows:
        ids = sorted(int(x) for x in (ids_csv or "").split(",") if x)
        duplicates.append({
            "headline":   headline,
            "event_date": event_date_str,
            "count":      int(cnt),
            "event_ids":  ids,
        })

    response = _empty_response()
    for key in _CATEGORY_KEYS:
        if key == "duplicate_headline_event_date_clusters":
            response[key] = {
                "count":    len(duplicates),
                "examples": duplicates[:_EXAMPLE_LIMIT],
            }
        else:
            bucket = per_row[key]
            response[key] = {
                "count":    len(bucket),
                "examples": bucket[:_EXAMPLE_LIMIT],
            }
    return response


def _scan_per_row(rows: list[tuple]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "malformed_market_tickers_json": [],
        "missing_headline":              [],
        "missing_timestamp":             [],
        "missing_event_date":            [],
        "malformed_event_date":          [],
        "missing_market_tickers":        [],
    }

    for event_id, headline, timestamp, market_tickers, event_date_str in rows:
        common = {
            "event_id":   event_id,
            "headline":   headline,
            "timestamp":  timestamp,
            "event_date": event_date_str,
        }

        if _is_blank_string(headline):
            buckets["missing_headline"].append(dict(common))

        if _is_blank_string(timestamp):
            buckets["missing_timestamp"].append(dict(common))

        if _is_blank_string(event_date_str):
            buckets["missing_event_date"].append(dict(common))
        elif not _is_iso_date(event_date_str):
            buckets["malformed_event_date"].append(dict(common))

        if _is_blank_string(market_tickers):
            buckets["missing_market_tickers"].append(dict(common))
        elif _is_malformed_market_tickers(market_tickers):
            example = dict(common)
            example["market_tickers"] = market_tickers
            buckets["malformed_market_tickers_json"].append(example)

    return buckets


@router.get("/diagnostics/archive-consistency")
def archive_consistency() -> dict[str, dict[str, Any]]:
    """Read-only consistency audit of the events table.

    Pure SQL ``SELECT``s against the local archive.  No LLM call, no
    ``yfinance`` fetch, no ``market_data`` / ``market_check`` /
    ``price_cache`` import, no DB write.

    Top-level keys (each carries ``count`` and capped ``examples``):

      * ``malformed_market_tickers_json``        — ``market_tickers``
        is present but does not decode as a JSON list.
      * ``missing_headline``                      — ``headline`` is
        NULL, empty, or whitespace-only.
      * ``missing_timestamp``                     — ``timestamp`` is
        NULL, empty, or whitespace-only.
      * ``missing_event_date``                    — ``event_date`` is
        NULL, empty, or whitespace-only.
      * ``malformed_event_date``                  — ``event_date`` is
        present but does not parse as ISO ``YYYY-MM-DD``.
      * ``missing_market_tickers``                — ``market_tickers``
        is NULL or empty (an empty list ``[]`` is *not* counted).
      * ``duplicate_headline_event_date_clusters`` — groups of ≥ 2 rows
        sharing the same ``(headline, event_date)`` pair (rows whose
        headline or event_date is blank are excluded so duplicates do
        not double-count with the missing categories).
    """
    return compute_archive_consistency()

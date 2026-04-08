"""
events_export.py
================

Pure, deterministic serializers for the saved event archive.

This module is intentionally I/O-light: it reuses :func:`db.load_recent_events`
for loading and exposes two serializers — ``build_json_export`` and
``build_csv_export`` — that take an already-loaded list of event dicts and
render a stable, research-friendly payload.

Design rules
------------
* No background jobs.  The endpoint calls these functions synchronously.
* Deterministic column order.  Reviewers should be able to diff two exports.
* Reuses :func:`db.load_recent_events` so any future schema additions flow
  through automatically.
* Empty archives produce a well-formed empty export (never an error).
* Nested lists/dicts (tickers, if_persists, etc.) are rendered as JSON
  strings in CSV so nothing is lost and downstream tools can re-parse them.
* A derived ``follow_through`` block exposes the best-by-magnitude 5d / 20d
  returns already stored in ``market_tickers``.  No new market pipeline.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from db import load_recent_events


# ---------------------------------------------------------------------------
# CSV column order — kept stable for reproducible diffs across exports.
# ---------------------------------------------------------------------------

CSV_COLUMNS: tuple[str, ...] = (
    # Identifiers
    "id",
    "timestamp",
    "event_date",
    # Core classification
    "headline",
    "stage",
    "persistence",
    "confidence",
    # Stored labels / review state
    "rating",
    "model",
    "low_signal",
    "notes",
    # Analysis text
    "what_changed",
    "mechanism_summary",
    "market_note",
    # Serialized JSON lists / dicts
    "beneficiaries",
    "losers",
    "assets_to_watch",
    "transmission_chain",
    "if_persists",
    "currency_channel",
    "policy_sensitivity",
    "inventory_context",
    "market_tickers",
    # Derived follow-through (best return by magnitude from stored tickers)
    "followthrough_best_5d",
    "followthrough_best_20d",
    "followthrough_direction",
)


# ---------------------------------------------------------------------------
# Derived follow-through helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Drop NaN / inf silently — they should never appear in the export.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _best_follow_through(
    tickers: list[dict] | None,
) -> tuple[float | None, float | None, str | None]:
    """Pick the best 5d and 20d returns (by magnitude) and the direction of
    the ticker that carries the best 5d number.

    Returns ``(best_5d, best_20d, direction)``.  Any component can be ``None``.
    """
    if not tickers:
        return None, None, None

    best_5d: float | None = None
    best_20d: float | None = None
    direction: str | None = None

    for t in tickers:
        r5 = _coerce_float(t.get("return_5d"))
        r20 = _coerce_float(t.get("return_20d"))
        if r5 is not None and (best_5d is None or abs(r5) > abs(best_5d)):
            best_5d = r5
            direction = t.get("direction") or direction
        if r20 is not None and (best_20d is None or abs(r20) > abs(best_20d)):
            best_20d = r20

    return best_5d, best_20d, direction


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def build_json_export(events: list[dict]) -> dict:
    """Return a JSON-serialisable payload capturing every export field.

    Shape::

        {
            "count": N,
            "events": [ {<event>, "follow_through": {...}}, ... ]
        }

    ``events`` should already be dicts with lists/dicts deserialised (the
    shape produced by :func:`db.load_recent_events`).
    """
    enriched: list[dict] = []
    for ev in events:
        best_5d, best_20d, direction = _best_follow_through(ev.get("market_tickers"))
        out = dict(ev)  # shallow copy; inner list/dict refs are fine for JSON
        out["follow_through"] = {
            "best_return_5d": best_5d,
            "best_return_20d": best_20d,
            "best_direction": direction,
        }
        enriched.append(out)
    return {"count": len(enriched), "events": enriched}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    """Render any value as a deterministic CSV cell.

    - ``None`` → empty string
    - list / dict → compact JSON (sorted keys, UTF-8 safe)
    - float → plain repr (the csv writer quotes if needed)
    - everything else → ``str(value)``
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        # Render as 0/1 to match the way low_signal is stored in SQLite.
        return "1" if value else "0"
    return str(value)


def build_csv_export(events: list[dict]) -> str:
    """Render events as a CSV string with a stable column order.

    Returns a string with the header row even when ``events`` is empty so
    downstream readers never have to handle two shapes.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)

    for ev in events:
        best_5d, best_20d, direction = _best_follow_through(ev.get("market_tickers"))
        derived = {
            "followthrough_best_5d": best_5d,
            "followthrough_best_20d": best_20d,
            "followthrough_direction": direction,
        }
        row = [_csv_cell(derived.get(col, ev.get(col))) for col in CSV_COLUMNS]
        writer.writerow(row)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Loader wrapper (keeps the endpoint thin)
# ---------------------------------------------------------------------------


def load_events_for_export(limit: int | None = None) -> list[dict]:
    """Load events for export in a deterministic newest-first order.

    Reuses :func:`db.load_recent_events` with a generous default cap so the
    caller does not have to think about pagination.  ``limit`` can be
    overridden by the API layer to bound very large archives.
    """
    cap = limit if (limit is not None and limit > 0) else 10_000
    return load_recent_events(limit=cap)

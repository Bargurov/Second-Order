#!/usr/bin/env python3
"""Read-only export of no_forward_20d ``cache_window_gap`` rows.

One row per (event, ticker) pair the targeted price-cache refresh would
actually fix — i.e. tickers whose ``price_cache`` window doesn't yet
reach ``event_date + 20 business days``.  Output is CSV by default;
``--json`` switches to a structured envelope.  Both modes carry the same
8 fields per row::

    event_id, event_date, symbol, diagnostic_reason,
    cache_max_date, horizon_20d_date, gap_days, source

Out of scope (deliberately)
---------------------------
* No write mode, no refresh execution.  This script never invokes
  ``yfinance``, ``market_check``, ``market_data``,
  ``price_cache.fetch_daily_cached``, the LLM, or any provider seam.
  The single SQLite open is read-only (``mode=ro`` URI).
* No archive mutation.  ``db.save_event`` / ``update_review`` /
  ``append_revisit_snapshot`` are never called.

Usage::

    python scripts/no_forward_20d_refreshability_export.py
    python scripts/no_forward_20d_refreshability_export.py --json
    python scripts/no_forward_20d_refreshability_export.py --json --limit 5
    python scripts/no_forward_20d_refreshability_export.py --csv --limit 50
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Sub-reason produced by ``routes.diagnostics._classify_no_forward_20d_subreason``
# for the only bucket a targeted refresh actually fixes.
_REFRESHABLE_DIAG_REASON = "cache_max_before_20d_horizon"

# Default export size — generous enough to be useful as a worklist but
# small enough to keep CSV pipes manageable.  ``--limit`` overrides.
_DEFAULT_LIMIT = 100

# Field order pinned by the task brief.  CSV header and JSON ``fields``
# both use this tuple — adding a new field = one entry here + one
# population line in :func:`_load_export_rows`.
_FIELD_NAMES: tuple[str, ...] = (
    "event_id",
    "event_date",
    "symbol",
    "diagnostic_reason",
    "cache_max_date",
    "horizon_20d_date",
    "gap_days",
    "source",
)

# Source label embedded in every row so a downstream consumer can tell
# which diagnostic this export originated from when multiple gap reports
# are merged.
_SOURCE_LABEL = "no_forward_20d_blockers"


# ---------------------------------------------------------------------------
# Production seam — read-only SQLite scan + reuse of the diagnostic
# classifiers.  Tests patch this attribute directly to inject synthetic
# rows; the patched-seam path never opens SQLite.
# ---------------------------------------------------------------------------


def _load_export_rows() -> list[dict]:
    """Return every (event, ticker) pair that lands in the
    ``cache_max_before_20d_horizon`` bucket, populated with the eight
    export fields.

    Pure read.  Opens ``events.db`` with ``mode=ro`` (a writable journal
    file is never created), reads ``events`` once and ``price_cache``
    once for ``MAX(date) GROUP BY (ticker, auto_adjust)``, and reuses
    the diagnostic classifiers so the universe stays in lockstep with
    ``/diagnostics/no-forward-20d-blockers``.

    ``gap_days`` is calendar days — ``(horizon_20d_date - cache_max_date).days``
    on plain :class:`datetime.date` objects.  Business-day gap could
    diverge from the documented field name in unintuitive ways (a
    Monday horizon over a Friday cache_max would read as 1 business
    day but 3 calendar days); calendar matches the field's plain
    reading.
    """
    # ``api`` first — ``routes.diagnostics`` imports ``api`` at module
    # top, and ``api`` in turn imports ``routes.diagnostics``.  Loading
    # ``api`` first lets the cycle resolve cleanly.  Mirrors the
    # bootstrap dance in ``no_forward_20d_gap_report._compute_breakdown``.
    import api  # noqa: F401
    import db as _db
    from routes.diagnostics import (
        _business_day_offset,
        _classify_blocker_for_ticker,
        _classify_no_forward_20d_subreason,
    )

    if not _db._db_ready:
        _db.init_db()

    db_uri = f"file:{_db.DB_FILE}?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()
        try:
            cache_max_rows = conn.execute(
                "SELECT ticker, auto_adjust, MAX(date) "
                "FROM price_cache GROUP BY ticker, auto_adjust"
            ).fetchall()
        except sqlite3.Error:
            cache_max_rows = []

    cache_max: dict[tuple[str, int], date] = {}
    for ticker, flag, max_d in cache_max_rows:
        if not isinstance(ticker, str) or not isinstance(max_d, str):
            continue
        try:
            cache_max[(ticker.upper(), int(flag))] = date.fromisoformat(
                max_d[:10],
            )
        except (ValueError, TypeError):
            continue

    today = date.today()
    out: list[dict] = []

    for raw in rows:
        try:
            event = _db._decode_event_row(raw)
        except Exception:
            event = dict(raw)

        event_id = event.get("id")
        event_date_str = event.get("event_date")
        if not isinstance(event_date_str, str) or not event_date_str:
            continue
        try:
            event_d = date.fromisoformat(event_date_str[:10])
        except (ValueError, TypeError):
            continue

        tickers = event.get("market_tickers") or []
        if not isinstance(tickers, list):
            continue

        for t in tickers:
            try:
                blocker = _classify_blocker_for_ticker(t, event_date_str)
            except Exception:
                continue
            if blocker != "no_forward_20d_close":
                continue

            sym_raw = t.get("symbol") if isinstance(t, dict) else None
            sym_upper = sym_raw.upper() if isinstance(sym_raw, str) else ""
            if not sym_upper:
                continue

            aa_false_max = cache_max.get((sym_upper, 0))
            aa_true_max  = cache_max.get((sym_upper, 1))
            sub = _classify_no_forward_20d_subreason(
                event_d=event_d, today=today,
                aa_false_max=aa_false_max, aa_true_max=aa_true_max,
            )
            if sub != _REFRESHABLE_DIAG_REASON:
                continue

            horizon = _business_day_offset(event_d, 20)
            newest: date | None = None
            for d in (aa_false_max, aa_true_max):
                if d is not None and (newest is None or d > newest):
                    newest = d
            # ``cache_max_before_20d_horizon`` implies ``newest is not None``;
            # the safety check below is defensive against a future shift in
            # the classifier's contract.
            if newest is None:
                continue
            # Diagnostic-bucket corner case: when one auto_adjust flag's
            # cache already reaches the horizon but the hydrator still
            # can't produce return_20d (typically interior cache gaps,
            # not a window-end deficit), the SubReason classifier still
            # routes the row into ``cache_max_before_20d_horizon``.  A
            # window-extending refresh wouldn't close such rows — the
            # export drops them so consumers see only true refreshable
            # window gaps (gap_days > 0).
            gap_days = (horizon - newest).days
            if gap_days <= 0:
                continue

            out.append({
                "event_id":          event_id,
                "event_date":        event_date_str[:10],
                "symbol":            sym_upper,
                "diagnostic_reason": sub,
                "cache_max_date":    newest.isoformat(),
                "horizon_20d_date":  horizon.isoformat(),
                "gap_days":          gap_days,
                "source":            _SOURCE_LABEL,
            })

    return out


# ---------------------------------------------------------------------------
# Defense-in-depth filter — the production seam already filters to
# ``cache_max_before_20d_horizon``, but a future seam (or a mocked test
# input) might not.  Keeping the filter at the script level guarantees
# the brief's "include only cache_window_gap rows by default" invariant.
# ---------------------------------------------------------------------------


def _filter_to_cache_window_gap(rows: Sequence[dict]) -> list[dict]:
    return [
        r for r in rows
        if isinstance(r, dict)
        and r.get("diagnostic_reason") == _REFRESHABLE_DIAG_REASON
    ]


# ---------------------------------------------------------------------------
# Live validation — defense-in-depth on the gap_days contract.  The seam
# already drops rows with ``gap_days <= 0`` (the interior-gap exclusion at
# the seam-level filter), so under normal operation this validator is a
# no-op.  It exists so a future change that loosens the seam filter or a
# mocked test input that smuggles in a non-positive row trips loudly at
# the export boundary instead of leaking into a downstream consumer.
# ---------------------------------------------------------------------------


def _validate_gap_days_positive(rows: Sequence[dict]) -> None:
    """Raise ``AssertionError`` if any row has non-positive ``gap_days``.

    The export contract is "every emitted row represents a real,
    refreshable window deficit"; a window of zero or negative days
    cannot be closed by a window-extending refresh.  A row with
    ``gap_days <= 0`` is therefore semantically invalid as an export
    row and must never reach the renderer.

    ``gap_days`` must also be a real ``int`` — booleans (a Python
    ``int`` subclass) and string-encoded numbers are rejected so a
    serialiser regression that quotes the field cannot smuggle a
    non-positive value past this check.
    """
    for r in rows:
        gap = r.get("gap_days") if isinstance(r, dict) else None
        if (
            not isinstance(gap, int)
            or isinstance(gap, bool)
            or gap <= 0
        ):
            raise AssertionError(
                "refreshability export must never emit non-positive "
                "gap_days; offending row: "
                f"event_id={r.get('event_id') if isinstance(r, dict) else None!r}, "
                f"symbol={r.get('symbol') if isinstance(r, dict) else None!r}, "
                f"gap_days={gap!r}"
            )


# ---------------------------------------------------------------------------
# Row normalisation + rendering
# ---------------------------------------------------------------------------


def _normalise_row(row: dict) -> dict:
    """Flatten one seam row down to the 8-field export shape.

    Missing keys collapse to ``None`` so the CSV / JSON columns stay
    populated even when the upstream seam returns a partial row.
    """
    return {field: row.get(field) for field in _FIELD_NAMES}


def _render_json(rows: Sequence[dict]) -> str:
    payload = {
        "ok":     True,
        "count":  len(rows),
        "fields": list(_FIELD_NAMES),
        "rows":   [_normalise_row(r) for r in rows],
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_csv(rows: Sequence[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(_FIELD_NAMES),
        lineterminator="\n",
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(_normalise_row(r))
    # ``print`` adds the trailing newline; rstrip avoids a double newline
    # on the last data row when the renderer is piped through ``print``.
    return buf.getvalue().rstrip("\n")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only export of no_forward_20d cache_window_gap rows.  "
            "One row per (event, ticker) pair a targeted refresh would "
            "close.  No provider calls, no DB writes, no LLM."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--csv",
        action="store_true",
        help="Emit CSV (default).",
    )
    fmt.add_argument(
        "--json",
        action="store_true",
        help="Emit a structured JSON envelope instead of CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Maximum number of rows to emit.  Default: {_DEFAULT_LIMIT}.  "
            "Applied AFTER the cache_window_gap filter."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    limit = max(int(args.limit), 0)

    raw_rows = _load_export_rows()
    filtered = _filter_to_cache_window_gap(raw_rows)
    # Validate the full filtered set (before --limit truncation) so a
    # regression cannot hide a non-positive row past the cap.
    _validate_gap_days_positive(filtered)
    rows = filtered[:limit]

    if args.json:
        print(_render_json(rows), file=output)
    else:
        print(_render_csv(rows), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

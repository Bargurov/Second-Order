#!/usr/bin/env python3
"""Read-only preview tool for the ``auto_adjust_mismatch_for_20d``
flag-fix repair.

The hydrator's ``no_forward_20d`` blocker classifier surfaces a small
sub-bucket — ``auto_adjust_mismatch_for_20d`` — where the price cache
already holds the rows the hydrator needs but at the *wrong*
``auto_adjust`` flag (cache has ``aa=1`` data, hydrator reads ``aa=0``).
The fix is uniform: re-fetch the ticker at the hydrator-visible flag so
the cache lines up with what the hydrator can see (action label
``refresh_unadjusted_cache_to_align_hydrator``).

This script *previews* that repair without ever doing it.  For each
mismatch row it lists the exact dates inside the ``[event_date,
event_date + 20bd]`` window where ``aa=1`` already has a row but
``aa=0`` does not — those are the dates a flag-fix re-fetch would add
to the cache.  Each row carries an explicit ``repair_status`` plus a
plain-language ``repair_reason`` so an operator can tell at a glance
whether the row is a clean flag-fix or a paranoid edge case the
classifier let through (``aa=1`` max past the horizon but no ``aa=1``
rows actually inside the window).

Output keys
-----------
``total_mismatches``         — count of every mismatch row the loader
                               surfaced.
``repairable_count``         — rows that the flag-fix would actually
                               unblock.
``non_repairable_count``     — rows the flag-fix wouldn't help (paranoid
                               edge cases).
``counts_by_status``         — full per-status breakdown.
``proposed_rows``            — capped per-row preview, each carrying
                               ``event_id``, ``event_date``, ``symbol``,
                               ``target_20d``, ``cache_max_per_flag``,
                               ``available_auto_adjust_flags``,
                               ``aa1_in_window_dates``,
                               ``aa0_in_window_dates``,
                               ``proposed_row_dates``,
                               ``proposed_row_count``,
                               ``repair_status``, ``repair_reason``,
                               and ``recommended_action``.
``recommended_next_action``  — single label drawn from a fixed
                               vocabulary (see ``_NEXT_ACTIONS``).

Out of scope (deliberately)
---------------------------
* No write mode.  No ``--apply`` / ``--write`` / ``--repair`` /
  ``--commit`` flag; the argparse parser rejects any of them so the
  read-only contract can never quietly regress.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``, no
  ``market_data``, no ``price_cache.fetch_daily_cached``, no network.
* No FastAPI route surface — the script reuses
  :func:`scripts.no_forward_20d_gap_report._load_auto_adjust_mismatch_details`
  via a lazy seam so the diagnostics ↔ FastAPI cycle resolves only at
  call time and tests can swap it cheaply.

Usage::

    python scripts/auto_adjust_mismatch_repair_preview.py
    python scripts/auto_adjust_mismatch_repair_preview.py --json
    python scripts/auto_adjust_mismatch_repair_preview.py --json --limit 5
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_RECOMMENDED_ACTION = "refresh_unadjusted_cache_to_align_hydrator"

_STATUS_REPAIRABLE          = "repairable_flag_fix"
_STATUS_NO_IN_WINDOW_DATA   = "not_repairable_no_in_window_data"
_STATUS_INVALID_EVENT_DATE  = "not_repairable_invalid_event_date"

_REPAIRABLE_STATUSES = frozenset({_STATUS_REPAIRABLE})

_DEFAULT_LIMIT = 10

_NEXT_ACTIONS = (
    "no_action_needed_no_mismatches",
    "fix_auto_adjust_flag_mismatch",
    "investigate_non_repairable_rows",
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly.
# ---------------------------------------------------------------------------


def _load_auto_adjust_mismatch_details() -> list[dict[str, Any]]:
    """Reuse the existing loader from ``no_forward_20d_gap_report``.

    Lazy-imports the sibling script to avoid pulling the diagnostics
    import graph at module load.  Tests patch this attribute directly,
    so the import only resolves on the un-patched path.
    """
    from scripts.no_forward_20d_gap_report import (
        _load_auto_adjust_mismatch_details as _impl,
    )
    return _impl()


def _load_in_window_cache_rows(
    specs: Iterable[tuple[str, date, date]],
) -> dict[tuple[str, int], set[str]]:
    """Bulk read of ``price_cache`` rows that fall in any of the per-symbol
    ``[start, end]`` windows.

    Returns ``{(symbol_upper, flag_int): {iso_date, …}}``.

    Issues a single ``SELECT`` against ``price_cache`` filtered to the
    union of every requested ticker; in-window filtering is done in
    Python because each ticker has its own window.  Read-only.
    """
    spec_list = list(specs)
    if not spec_list:
        return {}

    import sqlite3
    import db as _db

    if not _db._db_ready:
        try:
            _db.init_db()
        except Exception:
            return {}

    tickers = sorted({s.upper() for s, _, _ in spec_list if isinstance(s, str) and s})
    if not tickers:
        return {}

    placeholders = ",".join("?" for _ in tickers)
    sql = (
        f"SELECT ticker, date, auto_adjust FROM price_cache "
        f"WHERE ticker IN ({placeholders}) AND auto_adjust IN (0, 1)"
    )

    try:
        conn = sqlite3.connect(_db.DB_FILE)
    except sqlite3.Error:
        return {}

    try:
        try:
            rows = conn.execute(sql, tickers).fetchall()
        except sqlite3.Error:
            return {}
    finally:
        conn.close()

    windows: dict[str, list[tuple[date, date]]] = {}
    for sym, start, end in spec_list:
        if not isinstance(sym, str) or not sym:
            continue
        if not isinstance(start, date) or not isinstance(end, date):
            continue
        windows.setdefault(sym.upper(), []).append((start, end))

    out: dict[tuple[str, int], set[str]] = {}
    for raw_ticker, raw_date, raw_flag in rows:
        if not isinstance(raw_ticker, str) or not isinstance(raw_date, str):
            continue
        try:
            d = date.fromisoformat(raw_date[:10])
        except (ValueError, TypeError):
            continue
        try:
            flag = int(raw_flag)
        except (ValueError, TypeError):
            continue
        if flag not in (0, 1):
            continue
        sym = raw_ticker.upper()
        for start, end in windows.get(sym, ()):
            if start <= d <= end:
                out.setdefault((sym, flag), set()).add(d.isoformat())
                break

    return out


# ---------------------------------------------------------------------------
# Core compute — pure functions over the loader output + cache map
# ---------------------------------------------------------------------------


def _business_day_offset(start: date, n: int) -> date:
    """Match :func:`routes.diagnostics._business_day_offset` exactly.

    Inlined here so this script never imports ``routes.diagnostics``
    (the loader does, lazily, but the compute path stays decoupled).
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _in_window(
    iso_dates: Iterable[str], start: date, end: date,
) -> set[str]:
    """Narrow a set of ISO-date strings to ``[start, end]``.

    The bulk in-window cache map is keyed by ``(symbol, flag)`` and
    contains the union across every per-event window for that symbol.
    Each per-event row must re-filter back to its own window so events
    that share a ticker don't inherit each other's dates.
    """
    out: set[str] = set()
    for iso in iso_dates:
        try:
            d = date.fromisoformat(iso[:10])
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            out.add(d.isoformat())
    return out


def _parse_event_date(detail: dict) -> date | None:
    raw = detail.get("event_date")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return None


def _windows_for_details(
    details: Sequence[dict],
) -> list[tuple[str, date, date]]:
    """Map valid loader rows to (symbol, event_d, target_20d) triples.

    Rows with an invalid event_date or missing symbol are skipped — they
    are surfaced as ``not_repairable_invalid_event_date`` later in the
    enrichment step.
    """
    out: list[tuple[str, date, date]] = []
    for d in details:
        sym = d.get("symbol")
        if not isinstance(sym, str) or not sym:
            continue
        ed = _parse_event_date(d)
        if ed is None:
            continue
        out.append((sym.upper(), ed, _business_day_offset(ed, 20)))
    return out


def _classify(
    *,
    aa1_dates: list[str],
    proposed_dates: list[str],
) -> tuple[str, str]:
    if not aa1_dates:
        return (
            _STATUS_NO_IN_WINDOW_DATA,
            "aa=1 cache has no rows inside the [event_date, "
            "event_date + 20bd] window — the flag-fix re-fetch has no "
            "source data to copy.  Investigate the ticker's source "
            "history before refreshing.",
        )
    if not proposed_dates:
        return (
            _STATUS_REPAIRABLE,
            "aa=0 already has every aa=1 in-window date; the flag-fix "
            "re-fetch would be a no-op for this row.  The classifier "
            "still flags it as a mismatch because aa=0's MAX is below "
            "target_20d.",
        )
    return (
        _STATUS_REPAIRABLE,
        f"flag-fix re-fetch would populate aa=0 with "
        f"{len(proposed_dates)} cache row(s) already present at aa=1 in "
        f"the [event_date, event_date + 20bd] window.",
    )


def _build_proposed_row(
    detail: dict,
    cache_rows: dict[tuple[str, int], set[str]],
) -> dict:
    sym_raw = detail.get("symbol")
    sym = sym_raw.upper() if isinstance(sym_raw, str) and sym_raw else None
    event_d = _parse_event_date(detail)

    base = {
        "event_id":                    detail.get("event_id"),
        "event_date":                  detail.get("event_date"),
        "symbol":                      sym,
        "available_auto_adjust_flags":
            list(detail.get("available_auto_adjust_flags") or []),
        "cache_max_per_flag":
            dict(detail.get("cache_max_per_flag") or {}),
        "recommended_action":          _RECOMMENDED_ACTION,
    }

    if event_d is None or sym is None:
        base.update({
            "target_20d":          None,
            "aa1_in_window_dates": [],
            "aa0_in_window_dates": [],
            "proposed_row_dates":  [],
            "proposed_row_count":  0,
            "repair_status":       _STATUS_INVALID_EVENT_DATE,
            "repair_reason":
                "event_date or symbol missing/invalid — the [event_date, "
                "event_date + 20bd] window cannot be computed; the row "
                "is unrepairable until the underlying event metadata is "
                "fixed.",
        })
        return base

    target = _business_day_offset(event_d, 20)
    # Re-filter to this event's [event_d, target_20d] window even if the
    # cache map was keyed only by ``(symbol, flag)`` — the same symbol
    # can appear in multiple loader rows with different windows, and a
    # symbol-keyed map is the union across all of them.  Without this
    # narrowing, an earlier event would inherit later events' dates.
    aa1 = sorted(_in_window(cache_rows.get((sym, 1), set()), event_d, target))
    aa0 = sorted(_in_window(cache_rows.get((sym, 0), set()), event_d, target))
    proposed = sorted(set(aa1) - set(aa0))
    status, reason = _classify(aa1_dates=aa1, proposed_dates=proposed)

    base.update({
        "target_20d":          target.isoformat(),
        "aa1_in_window_dates": aa1,
        "aa0_in_window_dates": aa0,
        "proposed_row_dates":  proposed,
        "proposed_row_count":  len(proposed),
        "repair_status":       status,
        "repair_reason":       reason,
    })
    return base


def _recommend_next_action(rows: Sequence[dict]) -> str:
    if not rows:
        return "no_action_needed_no_mismatches"
    if any(r["repair_status"] in _REPAIRABLE_STATUSES for r in rows):
        return "fix_auto_adjust_flag_mismatch"
    return "investigate_non_repairable_rows"


def _build_payload(
    details: Sequence[dict],
    cache_rows: dict[tuple[str, int], set[str]],
    *,
    limit: int,
) -> dict:
    full_rows = [_build_proposed_row(d, cache_rows) for d in details]

    counts_by_status: dict[str, int] = {}
    repairable = 0
    non_repairable = 0
    for r in full_rows:
        status = r["repair_status"]
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        if status in _REPAIRABLE_STATUSES:
            repairable += 1
        else:
            non_repairable += 1

    truncated = full_rows[:limit] if limit >= 0 else full_rows

    return {
        "total_mismatches":        len(full_rows),
        "repairable_count":        repairable,
        "non_repairable_count":    non_repairable,
        "counts_by_status":        counts_by_status,
        "proposed_rows":           truncated,
        "recommended_next_action": _recommend_next_action(full_rows),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict) -> str:
    lines: list[str] = ["Auto-adjust mismatch repair preview", ""]
    lines.append(f"Total mismatches:        {payload['total_mismatches']}")
    lines.append(f"  Repairable:            {payload['repairable_count']}")
    lines.append(f"  Non-repairable:        {payload['non_repairable_count']}")
    counts = payload.get("counts_by_status") or {}
    if counts:
        lines.append("  By status:")
        for status in sorted(counts.keys()):
            lines.append(f"    {status}: {counts[status]}")
    lines.append("")

    rows = payload.get("proposed_rows") or []
    lines.append(f"Proposed rows ({len(rows)}):")
    if rows:
        for index, row in enumerate(rows, start=1):
            lines.append(_format_row_lines(index, row))
    else:
        lines.append("  -")
    lines.append("")

    lines.append(
        f"Recommended next action: {payload['recommended_next_action']}"
    )
    return "\n".join(lines)


def _format_row_lines(index: int, row: dict) -> str:
    event_id   = row.get("event_id")
    event_date = row.get("event_date") or "-"
    symbol     = row.get("symbol")     or "-"
    target     = row.get("target_20d") or "-"
    status     = row.get("repair_status") or "-"
    reason     = row.get("repair_reason") or "-"
    proposed   = row.get("proposed_row_dates") or []
    proposed_str = ", ".join(proposed) if proposed else "-"
    cache_max  = row.get("cache_max_per_flag") or {}
    if cache_max:
        cache_str = " ".join(
            f"aa={flag}->{cache_max[flag]}"
            for flag in sorted(cache_max.keys())
        )
    else:
        cache_str = "-"
    return (
        f"  {index:>2}. id={event_id} symbol={symbol} "
        f"event_date={event_date} target_20d={target}\n"
        f"      status: {status}\n"
        f"      cache_max: {cache_str}\n"
        f"      proposed_dates: {proposed_str}\n"
        f"      reason: {reason}"
    )


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CSV rendering — flat, spreadsheet-friendly view of ``proposed_rows``.
# Stable column order is part of the contract; downstream consumers
# (operator runbooks, spreadsheet imports) pin against this list.
# ---------------------------------------------------------------------------


_CSV_FIELDNAMES: tuple[str, ...] = (
    "event_id",
    "event_date",
    "symbol",
    "target_20d",
    "available_auto_adjust_flags",
    "cache_max_aa0",
    "cache_max_aa1",
    "aa1_in_window_dates",
    "aa0_in_window_dates",
    "proposed_row_dates",
    "proposed_row_count",
    "repair_status",
    "repair_reason",
    "recommended_action",
)


def _csv_cell(value: Any) -> str:
    """Encode a single payload field for the CSV cell.

    * ``None`` → empty string (never the literal ``"None"``).
    * ``list`` → pipe-joined values; empty list → empty string.
    * Everything else → ``str(value)``.

    The CSV summary intentionally drops the top-level counts/payload —
    ``proposed_rows`` is the row source.  The dict-valued
    ``cache_max_per_flag`` is flattened by the row builder, not here.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return str(value)


def _csv_row_for(row: dict) -> list[str]:
    cache_max = row.get("cache_max_per_flag") or {}
    flat = {
        "event_id":                    row.get("event_id"),
        "event_date":                  row.get("event_date"),
        "symbol":                      row.get("symbol"),
        "target_20d":                  row.get("target_20d"),
        "available_auto_adjust_flags": row.get("available_auto_adjust_flags"),
        "cache_max_aa0":               cache_max.get("0"),
        "cache_max_aa1":               cache_max.get("1"),
        "aa1_in_window_dates":         row.get("aa1_in_window_dates"),
        "aa0_in_window_dates":         row.get("aa0_in_window_dates"),
        "proposed_row_dates":          row.get("proposed_row_dates"),
        "proposed_row_count":          row.get("proposed_row_count"),
        "repair_status":               row.get("repair_status"),
        "repair_reason":               row.get("repair_reason"),
        "recommended_action":          row.get("recommended_action"),
    }
    return [_csv_cell(flat[name]) for name in _CSV_FIELDNAMES]


def _render_csv(payload: dict) -> str:
    # ``lineterminator='\n'`` keeps the output diff/test-friendly.
    # Default ``csv.writer`` emits ``\r\n``, which combined with text-
    # mode writes on Windows can yield ``\r\r\n``.
    buf = io.StringIO()
    writer = csv.writer(
        buf,
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerow(_CSV_FIELDNAMES)
    for row in payload.get("proposed_rows") or []:
        writer.writerow(_csv_row_for(row))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only preview of the auto_adjust_mismatch_for_20d "
            "flag-fix repair.  Lists the exact cache rows the repair "
            "would propose per event and explains repairability.  "
            "Never writes."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    fmt.add_argument(
        "--csv",
        action="store_true",
        help=(
            "Emit one CSV row per proposed-rows entry with a stable "
            "column order: see ``_CSV_FIELDNAMES``.  Header is always "
            "emitted, even with zero mismatches.  List columns are "
            "pipe-separated; ``None`` values render as empty cells."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            "Cap the proposed-rows display list at N rows (default 10). "
            "The top-level counts always reflect every mismatch."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    limit = max(int(args.limit), 0)

    details = _load_auto_adjust_mismatch_details() or []
    specs = _windows_for_details(details)
    cache_rows = _load_in_window_cache_rows(specs) if specs else {}
    payload = _build_payload(details, cache_rows, limit=limit)

    if args.json:
        print(_render_json(payload), file=output)
    elif args.csv:
        # ``end=""`` so the trailing ``\n`` from csv.writer's last row
        # isn't doubled by ``print``'s default newline.
        print(_render_csv(payload), file=output, end="")
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

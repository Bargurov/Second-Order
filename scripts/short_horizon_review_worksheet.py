#!/usr/bin/env python3
"""Read-only short-horizon operator review worksheet export.

Builds an operator-facing worksheet from the existing short-horizon
``run_short_horizon_review_queue`` output.  The worksheet preserves
every row the queue surfaces — including the closed-vocabulary
``operator_decision_needed`` and human-readable ``reason_for_review``
already assigned upstream — and layers seven blank columns the
operator hand-fills to expand the next short-horizon validation
cohort beyond the current 5 repaired events:

  * ``proposed_primary_ticker``
  * ``proposed_benchmark_ticker``
  * ``proposed_mechanism_family``
  * ``predicted_direction``
  * ``include_in_short_horizon_validation``
  * ``exclude_reason``
  * ``operator_notes``

Read-only by construction
-------------------------

* Wraps ``scripts.short_horizon_review_queue`` through a single
  patchable seam — tests inject synthetic queue payloads, the live
  path delegates to the real review-queue builder.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, no ``price_cache.fetch_daily_cached``, no
  provider call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never proposes tickers or mechanism families; the seven operator
  columns are always emitted as empty strings.
* The on-disk ``short_horizon_repair_packet.csv`` is NEVER written
  or rewritten by this script.

Output contract (JSON)::

    {
      "ok":                       bool,
      "worksheet_count":          int,    # = len(worksheet)
      "total_review_queue_count": int,    # full upstream count
      "high_priority_count":      int,
      "medium_priority_count":    int,
      "low_priority_count":       int,
      "worksheet": [                       # capped at --limit
        {
          "event_id":                              int,
          "headline":                              str | None,
          "event_date":                            str | None,
          "current_primary_ticker":                str | None,
          "current_mechanism_family":              str | None,
          "repair_type":                           str,
          "repair_priority":         "high" | "medium" | "low",
          "operator_decision_needed":              str,
          "reason_for_review":                     str,
          "proposed_primary_ticker":               "",
          "proposed_benchmark_ticker":             "",
          "proposed_mechanism_family":             "",
          "predicted_direction":                   "",
          "include_in_short_horizon_validation":   "",
          "exclude_reason":                        "",
          "operator_notes":                        "",
        },
        ...
      ],
      "excluded_or_deferred": [           # already-reviewed or
                                          # deferred event_ids with
                                          # human-readable reason
        {"event_id": int, "reason": str},
        ...
      ],
      "recommended_next_action": str,
    }

The CSV output uses the same 16 column names as the JSON per-row
keys, in the same order.  Lines terminate with ``\n`` (no Windows
CRLF).

Conservative wording — banned tokens (``proof``, ``proves``,
``validated``, ``alpha``, ``guaranteed``).

Usage::

    python scripts/short_horizon_review_worksheet.py
    python scripts/short_horizon_review_worksheet.py --json --limit 10
    python scripts/short_horizon_review_worksheet.py --csv  --limit 10
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 10


# Priority rank for the defensive worksheet-level sort.  The upstream
# review queue already orders rows by ``(priority_rank, event_id)``
# ascending, but the worksheet re-sorts so this contract is pinned
# independently of the upstream guarantee.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


# Field order matches the JSON per-row schema documented in the
# module docstring and is reused as the CSV header.
_WORKSHEET_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# Columns the operator hand-fills.  The script always emits these as
# empty strings — it never assigns or proposes a value.
_BLANK_OPERATOR_COLUMNS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# Columns inherited verbatim from the upstream review-queue row.
_INHERITED_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
)


_RECOMMENDED_EMPTY: str = (
    "No short-horizon review worksheet rows surfaced.  Refreshing "
    "the upstream short-horizon review queue or expanding the "
    "fully-ready cohort may surface more rows."
)
_RECOMMENDED_HAS_ITEMS: str = (
    "{n} worksheet row(s) ready for operator review.  Inspect each "
    "headline and hand-fill proposed_primary_ticker, "
    "proposed_benchmark_ticker, proposed_mechanism_family, "
    "predicted_direction, and include_in_short_horizon_validation to "
    "expand the next short-horizon validation cohort.  Surfaced rows "
    "are review candidates only — not claims about repairability or "
    "significance."
)


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


def _run_short_horizon_review_queue(
    *, db_path: str | None, limit: int,
) -> dict[str, Any]:
    """Wrap ``run_short_horizon_review_queue`` so tests patch a single
    surface.  Lazy import keeps the worksheet module's import graph
    free of the upstream packet/report dependencies until the
    un-patched path fires."""
    from scripts.short_horizon_review_queue import (
        run_short_horizon_review_queue,
    )

    return run_short_horizon_review_queue(db_path=db_path, limit=limit)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_short_horizon_review_worksheet(
    *, db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Build the worksheet payload from the upstream review queue.

    ``--offset`` pages the surfaced worksheet through the sorted
    review queue: ``offset=0`` returns the first ``limit`` rows
    (matching the historical top-N behaviour), ``offset=N`` skips the
    first N rows and surfaces the next ``limit``.  The aggregate
    counts always reflect the full upstream queue regardless of
    offset.
    """
    capped_limit = max(int(limit), 0)
    capped_offset = max(int(offset), 0)

    # Always ask the upstream queue for an effectively unlimited cohort
    # so our --limit only truncates the surfaced worksheet, not the
    # aggregate counts.
    queue = _safe_dict(_run_short_horizon_review_queue(
        db_path=db_path, limit=10**9,
    ))

    raw_rows = queue.get("review_queue")
    if not isinstance(raw_rows, list):
        raw_rows = []

    worksheet_rows: list[dict[str, Any]] = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        worksheet_row = _build_worksheet_row(r)
        if worksheet_row is not None:
            worksheet_rows.append(worksheet_row)

    # Defensive sort: high priority first, then by event_id ascending.
    # The upstream queue already sorts this way, but pinning the order
    # here keeps the worksheet contract independent.
    worksheet_rows.sort(
        key=lambda r: (
            _PRIORITY_RANK.get(r.get("repair_priority"), 99),
            _coerce_event_id_for_sort(r.get("event_id")),
        )
    )

    # When --limit is non-positive, emit an empty worksheet but keep
    # the aggregate counts intact.  Otherwise slice the sorted list
    # at ``[offset : offset + limit]`` — an offset past the end of the
    # list yields an empty worksheet (Python slice semantics) without
    # changing total_review_queue_count.
    if capped_limit <= 0:
        truncated: list[dict[str, Any]] = []
    else:
        truncated = worksheet_rows[capped_offset : capped_offset + capped_limit]

    excluded_or_deferred = _build_excluded_or_deferred(queue)

    if worksheet_rows:
        recommended = _RECOMMENDED_HAS_ITEMS.format(n=len(worksheet_rows))
    else:
        recommended = _RECOMMENDED_EMPTY

    return {
        "ok":                       True,
        "worksheet_count":          len(truncated),
        "total_review_queue_count": len(worksheet_rows),
        "limit":                    capped_limit,
        "offset":                   capped_offset,
        "high_priority_count":      _safe_int(queue.get("high_priority_count")),
        "medium_priority_count":    _safe_int(queue.get("medium_priority_count")),
        "low_priority_count":       _safe_int(queue.get("low_priority_count")),
        "worksheet":                truncated,
        "excluded_or_deferred":     excluded_or_deferred,
        "recommended_next_action":  recommended,
    }


# ---------------------------------------------------------------------------
# Per-row construction
# ---------------------------------------------------------------------------


def _build_worksheet_row(queue_row: dict[str, Any]) -> dict[str, Any] | None:
    ev_id = queue_row.get("event_id")
    if not isinstance(ev_id, int):
        return None
    row: dict[str, Any] = {}
    for key in _INHERITED_COLUMNS:
        row[key] = queue_row.get(key)
    for key in _BLANK_OPERATOR_COLUMNS:
        row[key] = ""
    return row


def _build_excluded_or_deferred(
    queue: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = queue.get("excluded_or_deferred") or []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ev_id = entry.get("event_id")
        reason = entry.get("reason")
        if not isinstance(ev_id, int) or not isinstance(reason, str):
            continue
        out.append({"event_id": ev_id, "reason": reason})
    out.sort(key=lambda r: r["event_id"])
    return out


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _coerce_event_id_for_sort(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _render_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    # ``lineterminator='\n'`` avoids the default ``\r\n`` so the file
    # carries LF line endings regardless of platform.
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_WORKSHEET_COLUMNS)
    for row in report.get("worksheet") or []:
        writer.writerow([_csv_cell(row.get(k)) for k in _WORKSHEET_COLUMNS])
    return buf.getvalue()


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only short-horizon operator review worksheet "
            "export.  Builds a worksheet from the existing "
            "short_horizon_review_queue output so the operator can "
            "hand-pick candidates for the next short-horizon "
            "validation cohort.  No DB writes, no provider calls, no "
            "LLM, no FastAPI.  Conservative wording: review "
            "candidates, not validated."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON (this is also the default).",
    )
    fmt.add_argument(
        "--csv", action="store_true",
        help=(
            "Emit a CSV worksheet with the 16 worksheet columns.  "
            "Rows terminate with \\n."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced worksheet at N entries (default "
            f"{_DEFAULT_LIMIT}).  total_review_queue_count and the "
            f"priority counts always reflect the full upstream queue."
        ),
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help=(
            "Skip the first N rows of the sorted review queue before "
            "applying --limit (default 0).  --limit 10 --offset 10 "
            "surfaces rows 11-20 of the same sort order."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help="Optional events DB path.  Read-only.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_short_horizon_review_worksheet(
        db_path=args.db_path,
        limit=int(args.limit),
        offset=int(args.offset),
    )
    if args.csv:
        # CSV writer already emits a trailing newline per row; write
        # without an extra blank line.
        output.write(_render_csv(report))
    else:
        # JSON is the default; ``--json`` is accepted for ergonomics.
        print(_render_json(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

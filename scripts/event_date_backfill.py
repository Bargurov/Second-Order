#!/usr/bin/env python3
"""Event-date backfill CLI — dry-run by default, guarded write mode.

Composes :func:`event_date_backfill.plan_event_date_backfill` to preview
events whose ``event_date`` is missing while a parseable ``timestamp``
exists.  Emits a compact text report by default; ``--json`` switches to
structured output.

Write mode
----------
``--write --confirm`` invokes
:func:`event_date_backfill.apply_event_date_backfill` with
``confirm=True``.  Both flags are required together; either alone exits
non-zero with a guidance message and writes nothing.  ``--apply`` is a
permanent typo guard — argparse rejects it so an operator cannot
trigger a write by mistyping the documented combo.

Out of scope (deliberately)
---------------------------
* No LLM, no ``yfinance``, no ``market_check``, no ``market_data``, no
  ``price_cache``, no network — the writer issues a single guarded SQL
  UPDATE behind ``BEGIN IMMEDIATE``.
* No FastAPI route surface — the CLI never imports ``api`` or
  ``routes.*``.

The seams tests patch are ``plan_event_date_backfill`` and the writer
re-bound at module level under private names so a unit test can drive
the CLI without a real archive.

Usage::

    python scripts/event_date_backfill.py
    python scripts/event_date_backfill.py --json
    python scripts/event_date_backfill.py --db-path /path/to/snapshot.db --json
    python scripts/event_date_backfill.py --write --confirm
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The writer is bound to a leading-underscore alias so the CLI module's
# public surface stays free of any ``apply``/``write``/``persist``/
# ``commit`` callable.  ``test_cli_module_exposes_no_write_helper`` in
# ``tests/test_event_date_backfill_write_contract.py`` is *not* one of
# the four CURRENT-STATE GUARD tests — it must keep passing once write
# mode lands.
from event_date_backfill import (  # noqa: E402
    apply_event_date_backfill as _apply_event_date_backfill,
    plan_event_date_backfill,
)


_TEXT_EXAMPLE_LIMIT = 5


# ---------------------------------------------------------------------------
# Payload composition
# ---------------------------------------------------------------------------


def _build_payload(plan: dict) -> dict:
    proposed = plan.get("proposed_updates") or []
    payload: dict[str, Any] = {
        "total_candidates":           plan.get("total_candidates", 0),
        "events_with_market_tickers": plan.get("events_with_market_tickers", 0),
        "ticker_rows_blocked":        plan.get("ticker_rows_blocked", 0),
        "proposed_updates_count":     len(proposed),
        "proposed_updates":           list(proposed),
        "skipped_counts":             dict(plan.get("skipped_counts") or {}),
        "confidence_note":            plan.get("confidence_note", ""),
    }
    if "applied_count" in plan or "applied_updates" in plan:
        payload["applied_count"]   = plan.get("applied_count", 0)
        payload["applied_updates"] = list(plan.get("applied_updates") or [])
    return payload


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict) -> str:
    is_write_run = "applied_count" in payload
    title = (
        "Event-date backfill write" if is_write_run
        else "Event-date backfill dry-run"
    )
    lines: list[str] = [title, ""]
    lines.append(f"Total candidates:             {payload['total_candidates']}")
    lines.append(
        f"Events with market tickers:   {payload['events_with_market_tickers']}"
    )
    lines.append(f"Ticker rows blocked:          {payload['ticker_rows_blocked']}")
    lines.append(f"Proposed updates:             {payload['proposed_updates_count']}")
    if is_write_run:
        lines.append(f"Applied updates:              {payload['applied_count']}")
    lines.append("")

    lines.append("Skipped counts:")
    skipped = payload["skipped_counts"]
    if skipped:
        for key in sorted(skipped):
            lines.append(f"  {key}: {skipped[key]}")
    else:
        lines.append("  -")
    lines.append("")

    proposed = payload["proposed_updates"]
    if proposed:
        shown = proposed[:_TEXT_EXAMPLE_LIMIT]
        lines.append(
            f"First {len(shown)} of {len(proposed)} proposed updates:"
        )
        for index, prop in enumerate(shown, start=1):
            event_id  = prop.get("event_id")
            head      = prop.get("headline")
            ts        = prop.get("timestamp")
            proposed_d = prop.get("proposed_event_date")
            tcount    = prop.get("ticker_count")
            tickers   = prop.get("tickers") or []
            tickers_text = ",".join(tickers) if tickers else "-"
            lines.append(
                f"  {index:>2}. id={event_id} ts={ts} "
                f"-> event_date={proposed_d} "
                f"tickers({tcount})={tickers_text}"
            )
            lines.append(f"      {head}")
    else:
        lines.append("No proposed updates.")

    lines.append("")
    lines.append(f"Confidence note: {payload['confidence_note']}")
    return "\n".join(lines)


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


_WRITE_GUIDANCE = (
    "Refusing to run: --write and --confirm must be supplied together.\n"
    "Dry-run is the safe default — invoke write mode with the full pair:\n"
    "  python scripts/event_date_backfill.py --write --confirm "
    "[--db-path PATH]\n"
    "See docs/event_date_backfill_write_design.md for the full safety "
    "contract."
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview (default) or guarded write of events whose "
            "event_date can be backfilled from the headline timestamp.  "
            "Write mode requires --write and --confirm together."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file (e.g., a backup "
            "snapshot).  Defaults to the live db.DB_FILE."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Persist proposed event_date values.  Requires --confirm; "
            "either flag alone exits non-zero with no writes."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Confirm an explicit --write run.  Required together with "
            "--write; either flag alone exits non-zero with no writes."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    if args.write != args.confirm:
        print(_WRITE_GUIDANCE, file=sys.stderr)
        return 2

    if args.write and args.confirm:
        plan = _apply_event_date_backfill(db_path=args.db_path, confirm=True)
    else:
        plan = plan_event_date_backfill(db_path=args.db_path)

    payload = _build_payload(plan)

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

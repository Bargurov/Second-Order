#!/usr/bin/env python3
"""Focused report on remaining ``no_forward_20d`` hydration gaps.

Reuses the diagnostics breakdown
(:func:`routes.diagnostics._compute_no_forward_20d_breakdown`) and
reshapes its output into a compact operator report.  Emits a text
summary by default; ``--json`` switches to structured output suitable
for piping into a runbook.

Output keys
-----------
``total_no_forward_20d``       — total ticker rows the headline blocker
                                  is reporting as ``no_forward_20d_close``.
``too_recent``                 — ``event_too_recent_for_20d`` count;
                                  the event_date + 20 business days is
                                  still in the future.  No fetch helps.
``auto_adjust_mismatch``       — ``auto_adjust_mismatch_for_20d`` count;
                                  cache HAS the data but at the wrong
                                  ``auto_adjust`` flag.  An ingestion-
                                  flag fix unblocks these without any
                                  network call.
``cache_window_gap``           — ``cache_max_before_20d_horizon`` count;
                                  cache exists but the per-ticker window
                                  doesn't reach the 20d horizon.  A
                                  targeted refresh closes these.
``likely_delisted_or_sparse``  — newest cached row is more than the
                                  diagnostic threshold behind today.
                                  Source no longer publishes; backfill
                                  cannot help.
``refreshable_gap_examples``   — examples whose diagnostic_reason is
                                  ``cache_max_before_20d_horizon``.
                                  These rows are the only ones a
                                  refresh re-fetch would actually fix.
``non_refreshable_examples``   — examples whose diagnostic_reason is
                                  one of the other three.  Listing them
                                  separately keeps the operator from
                                  burning quota refreshing tickers a
                                  refresh cannot help.
``recommended_next_action``    — single string drawn from a fixed
                                  vocabulary (see ``_NEXT_ACTIONS``)
                                  ranking the actionable buckets:
                                  flag-fix > targeted-refresh >
                                  wait/accept > no-action.

Out of scope (deliberately)
---------------------------
* No write mode.  This script never refreshes the price cache,
  re-flags rows, or persists anything.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``, no
  ``market_data``, no ``price_cache.fetch_daily_cached``, no network.
* No FastAPI route surface — the script never imports ``api`` or
  ``routes.*`` outside the single ``_compute_breakdown`` indirection
  below, and that indirection only resolves the lazy import at call
  time so unit tests can swap the seam without paying the heavy
  diagnostics import cost.

Usage::

    python scripts/no_forward_20d_gap_report.py
    python scripts/no_forward_20d_gap_report.py --json
    python scripts/no_forward_20d_gap_report.py --json --limit 5
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Diagnostic-reason key produced by the breakdown for the only bucket a
# refresh re-fetch would actually fix.
_REFRESHABLE_DIAG_REASON = "cache_max_before_20d_horizon"

_DEFAULT_EXAMPLE_LIMIT = 10

# Recommendation vocabulary — pin every legal value so consumers can
# branch on it deterministically.
_NEXT_ACTIONS = (
    "no_action_needed_no_gaps",
    "fix_auto_adjust_flag_mismatch",
    "run_targeted_refresh_for_cache_window_gap",
    "wait_or_accept_no_refreshable_gaps",
)


# ---------------------------------------------------------------------------
# Breakdown seam — lazy-imports the diagnostics module so the script's
# top-level surface stays light.  Tests patch this attribute directly to
# inject synthetic breakdowns; the production path resolves to
# :func:`routes.diagnostics._compute_no_forward_20d_breakdown`.
# ---------------------------------------------------------------------------


def _compute_breakdown() -> dict[str, Any]:
    # ``api`` first — ``routes.diagnostics`` imports ``api`` at module
    # top, and ``api`` in turn imports ``routes.diagnostics``.  When the
    # CLI is the first thing in the process to touch
    # ``routes.diagnostics``, the inner ``import api`` re-enters
    # ``routes.diagnostics`` mid-load and fails with a circular-import
    # error.  Loading ``api`` first lets the cycle resolve cleanly: the
    # ``from routes.diagnostics import router`` line inside ``api`` is
    # the closing edge, not the opening one.
    import api  # noqa: F401
    import db as _db
    from routes.diagnostics import _compute_no_forward_20d_breakdown

    # The breakdown gates on ``db._db_ready`` and returns an empty
    # ``available=False`` shape when the DB has not been initialised in
    # the current process.  ``init_db`` is idempotent on a current
    # archive (``CREATE TABLE IF NOT EXISTS`` + version-match check —
    # byte-neutral) and is the project's canonical bootstrap; call it
    # only when the flag is unset so tests that already ran ``init_db``
    # in setUp aren't disturbed.
    if not _db._db_ready:
        _db.init_db()

    return _compute_no_forward_20d_breakdown()


# ---------------------------------------------------------------------------
# Payload composition
# ---------------------------------------------------------------------------


def _build_payload(breakdown: dict, *, limit: int) -> dict:
    counts = breakdown.get("counts") or {}
    examples = breakdown.get("examples") or []

    refreshable: list[dict] = []
    non_refreshable: list[dict] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        if ex.get("diagnostic_reason") == _REFRESHABLE_DIAG_REASON:
            refreshable.append(ex)
        else:
            non_refreshable.append(ex)

    return {
        "total_no_forward_20d":
            int(breakdown.get("total_no_forward_20d") or 0),
        "too_recent":
            int(counts.get("event_too_recent_for_20d") or 0),
        "auto_adjust_mismatch":
            int(counts.get("auto_adjust_mismatch_for_20d") or 0),
        "cache_window_gap":
            int(counts.get("cache_max_before_20d_horizon") or 0),
        "likely_delisted_or_sparse":
            int(counts.get("likely_delisted_or_sparse") or 0),
        "refreshable_gap_examples":  refreshable[:limit],
        "non_refreshable_examples":  non_refreshable[:limit],
        "recommended_next_action":   _recommend_next_action(counts),
    }


def _recommend_next_action(counts: dict) -> str:
    """Pure decision tree over the breakdown's count map.

    Priority order — actionability + cost:
      1. ``auto_adjust_mismatch_for_20d`` — cache already has the data;
         a flag fix is the cheapest unblock.
      2. ``cache_max_before_20d_horizon`` — refreshable; a targeted
         re-fetch closes the gap.
      3. otherwise (only ``event_too_recent_for_20d`` /
         ``likely_delisted_or_sparse`` are nonzero) — no refresh helps;
         wait or accept.
      4. all-zero — no action needed.
    """
    too_recent  = int(counts.get("event_too_recent_for_20d")     or 0)
    auto_adj    = int(counts.get("auto_adjust_mismatch_for_20d") or 0)
    cache_gap   = int(counts.get("cache_max_before_20d_horizon") or 0)
    delisted    = int(counts.get("likely_delisted_or_sparse")    or 0)

    if too_recent + auto_adj + cache_gap + delisted == 0:
        return "no_action_needed_no_gaps"
    if auto_adj > 0:
        return "fix_auto_adjust_flag_mismatch"
    if cache_gap > 0:
        return "run_targeted_refresh_for_cache_window_gap"
    return "wait_or_accept_no_refreshable_gaps"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict) -> str:
    lines: list[str] = ["No-forward-20d gap report", ""]
    lines.append(
        f"Total no_forward_20d:            {payload['total_no_forward_20d']}"
    )
    lines.append(
        f"  Too recent:                    {payload['too_recent']}"
    )
    lines.append(
        f"  Auto-adjust mismatch:          {payload['auto_adjust_mismatch']}"
    )
    lines.append(
        f"  Cache window gap:              {payload['cache_window_gap']}"
    )
    lines.append(
        f"  Likely delisted or sparse:     {payload['likely_delisted_or_sparse']}"
    )
    lines.append("")

    refreshable = payload["refreshable_gap_examples"]
    lines.append(f"Refreshable examples ({len(refreshable)}):")
    if refreshable:
        for index, ex in enumerate(refreshable, start=1):
            lines.append(_format_example_line(index, ex))
    else:
        lines.append("  -")
    lines.append("")

    non_refreshable = payload["non_refreshable_examples"]
    lines.append(f"Non-refreshable examples ({len(non_refreshable)}):")
    if non_refreshable:
        for index, ex in enumerate(non_refreshable, start=1):
            lines.append(_format_example_line(index, ex))
    else:
        lines.append("  -")
    lines.append("")

    lines.append(
        f"Recommended next action: {payload['recommended_next_action']}"
    )
    return "\n".join(lines)


def _format_example_line(index: int, ex: dict) -> str:
    event_id = ex.get("event_id")
    ticker   = ex.get("ticker") or "-"
    reason   = ex.get("diagnostic_reason") or "-"
    headline = ex.get("headline") or ""
    return (
        f"  {index:>2}. id={event_id} ticker={ticker} reason={reason}\n"
        f"      {headline}"
    )


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Focused read-only report on remaining no_forward_20d "
            "hydration gaps.  Reuses the diagnostics breakdown — no "
            "writes, no provider calls, no LLM."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_EXAMPLE_LIMIT,
        help=(
            "Cap each example partition at N rows (default 10).  The "
            "diagnostics breakdown internally caps examples at 10, so "
            "values above 10 cannot deliver more than the breakdown's "
            "supply."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    limit = max(int(args.limit), 0)

    breakdown = _compute_breakdown()
    payload = _build_payload(breakdown, limit=limit)

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

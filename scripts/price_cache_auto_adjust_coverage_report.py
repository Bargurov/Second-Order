#!/usr/bin/env python3
"""Read-only per-ticker coverage report for the ``price_cache``
``auto_adjust`` flag split.

The price cache is keyed by ``(ticker, date, auto_adjust)`` so the same
symbol carries two parallel histories: the unadjusted (``aa=0``) raw
bars and the adjusted (``aa=1``) bars.  When the two histories drift —
one flag has rows the other doesn't, or one flag's trailing edge has
fallen behind — downstream features that assume the cache is uniformly
backfilled (notably the no_forward_20d hydrator) start surfacing
``auto_adjust_mismatch`` blockers.

This report walks ``price_cache`` once with a single read-only
``SELECT`` and emits, per ticker, six fields that quantify the drift:

  * ``aa0_row_count``                 — total cached rows at ``aa=0``.
  * ``aa1_row_count``                 — total cached rows at ``aa=1``.
  * ``aa0_max_date``                  — latest cached date at ``aa=0``
                                        (``None`` when no rows exist).
  * ``aa1_max_date``                  — latest cached date at ``aa=1``
                                        (``None`` when no rows exist).
  * ``aa1_only_dates_count``          — distinct dates where ``aa=1``
                                        has a row but ``aa=0`` does
                                        not.  Pure set difference over
                                        the full history.
  * ``aa0_missing_after_aa1_count``   — distinct dates strictly after
                                        ``aa0_max_date`` where ``aa=1``
                                        has a row.  Surfaces the
                                        trailing-edge drift a
                                        flag-fix re-fetch would close.
                                        When ``aa0_max_date is None``
                                        this equals ``aa1_row_count``.

Top-level aggregates are computed across every ticker before any
``--limit`` truncation, so an operator running ``--limit 1`` never
mistakes the listed sample for the full population.

Output contract::

    {
      "total_tickers":                 int,
      "tickers_with_aa0_only":         int,
      "tickers_with_aa1_only":         int,
      "tickers_with_both_flags":       int,
      "tickers_with_aa1_only_dates":   int,
      "tickers_with_trailing_aa0_gap": int,
      "tickers": [                     # capped at --limit; sorted by
                                       # aa1_only_dates_count desc, then
                                       # aa0_missing_after_aa1_count desc,
                                       # then ticker asc
        {
          "ticker":                      str,
          "aa0_row_count":               int,
          "aa1_row_count":               int,
          "aa0_max_date":                str | None,
          "aa1_max_date":                str | None,
          "aa1_only_dates_count":        int,
          "aa0_missing_after_aa1_count": int,
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues a single ``SELECT`` against ``price_cache``;
  never INSERT / UPDATE / DELETE, never calls ``_ensure_table``,
  never writes ``fetched_at``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.

Usage::

    python scripts/price_cache_auto_adjust_coverage_report.py
    python scripts/price_cache_auto_adjust_coverage_report.py --json
    python scripts/price_cache_auto_adjust_coverage_report.py --json --limit 20
    python scripts/price_cache_auto_adjust_coverage_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25


_RECOMMENDED_OK = (
    "No auto_adjust flag drift detected — every cached ticker carries "
    "matching aa=0 and aa=1 coverage."
)
_RECOMMENDED_DRIFT = (
    "auto_adjust flag drift detected — review per-ticker "
    "aa1_only_dates_count and aa0_missing_after_aa1_count, then run "
    "the auto_adjust_mismatch_repair_preview to confirm the flag-fix "
    "re-fetch would close the gap."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_coverage(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the per-ticker auto_adjust coverage report dict.

    Parameters
    ----------
    db_path
        Optional path to a SQLite ``events.db`` file carrying the
        ``price_cache`` table.  When omitted, reads ``db.DB_FILE`` so
        the report aligns with whichever DB the caller's process is
        bound to.
    limit
        Maximum number of per-ticker entries surfaced under
        ``tickers``.  The aggregate counts always reflect every
        ticker — only the listed examples are truncated.  Negative
        values are clamped to ``0``.
    """
    capped_limit = max(int(limit), 0)
    empty: dict[str, Any] = {
        "total_tickers":                 0,
        "tickers_with_aa0_only":         0,
        "tickers_with_aa1_only":         0,
        "tickers_with_both_flags":       0,
        "tickers_with_aa1_only_dates":   0,
        "tickers_with_trailing_aa0_gap": 0,
        "tickers":                       [],
        "recommended_next_action":       _RECOMMENDED_OK,
    }

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty

    try:
        try:
            rows = conn.execute(
                "SELECT ticker, date, auto_adjust "
                "FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date IS NOT NULL AND date != '' "
                "  AND auto_adjust IN (0, 1)"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    by_ticker: dict[str, dict[int, set[str]]] = {}
    for raw_ticker, raw_date, raw_flag in rows:
        if not isinstance(raw_ticker, str) or not raw_ticker:
            continue
        if not isinstance(raw_date, str) or not raw_date:
            continue
        try:
            flag_int = int(raw_flag)
        except (TypeError, ValueError):
            continue
        if flag_int not in (0, 1):
            continue
        per_flag = by_ticker.setdefault(raw_ticker, {0: set(), 1: set()})
        per_flag[flag_int].add(raw_date)

    summaries: list[dict[str, Any]] = []
    for ticker, per_flag in by_ticker.items():
        aa0 = per_flag.get(0, set())
        aa1 = per_flag.get(1, set())
        aa0_max = max(aa0) if aa0 else None
        aa1_max = max(aa1) if aa1 else None
        aa1_only = aa1 - aa0
        if aa0_max is None:
            # aa=0 has no rows at all — every aa=1 date is "after" the
            # (non-existent) aa=0 max.
            aa0_missing_after_aa1 = len(aa1)
        else:
            aa0_missing_after_aa1 = sum(1 for d in aa1 if d > aa0_max)
        summaries.append({
            "ticker":                      ticker,
            "aa0_row_count":               len(aa0),
            "aa1_row_count":               len(aa1),
            "aa0_max_date":                aa0_max,
            "aa1_max_date":                aa1_max,
            "aa1_only_dates_count":        len(aa1_only),
            "aa0_missing_after_aa1_count": aa0_missing_after_aa1,
        })

    # Worst-drift tickers float to the top so an operator running
    # ``--limit 20`` sees the population that needs attention first.
    summaries.sort(key=lambda s: (
        -s["aa1_only_dates_count"],
        -s["aa0_missing_after_aa1_count"],
        s["ticker"],
    ))

    total_tickers           = len(summaries)
    aa0_only                = sum(
        1 for s in summaries
        if s["aa0_row_count"] > 0 and s["aa1_row_count"] == 0
    )
    aa1_only                = sum(
        1 for s in summaries
        if s["aa1_row_count"] > 0 and s["aa0_row_count"] == 0
    )
    both_flags              = sum(
        1 for s in summaries
        if s["aa0_row_count"] > 0 and s["aa1_row_count"] > 0
    )
    with_aa1_only_dates     = sum(
        1 for s in summaries if s["aa1_only_dates_count"] > 0
    )
    with_trailing_aa0_gap   = sum(
        1 for s in summaries if s["aa0_missing_after_aa1_count"] > 0
    )

    return {
        "total_tickers":                 total_tickers,
        "tickers_with_aa0_only":         aa0_only,
        "tickers_with_aa1_only":         aa1_only,
        "tickers_with_both_flags":       both_flags,
        "tickers_with_aa1_only_dates":   with_aa1_only_dates,
        "tickers_with_trailing_aa0_gap": with_trailing_aa0_gap,
        "tickers":                       summaries[:capped_limit],
        "recommended_next_action": (
            _RECOMMENDED_OK
            if with_aa1_only_dates == 0 and with_trailing_aa0_gap == 0
            else _RECOMMENDED_DRIFT
        ),
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Price-cache auto_adjust coverage report", ""]
    lines.append(f"Total tickers:                  {report['total_tickers']}")
    lines.append(f"  aa=0 only:                    {report['tickers_with_aa0_only']}")
    lines.append(f"  aa=1 only:                    {report['tickers_with_aa1_only']}")
    lines.append(f"  Both flags:                   {report['tickers_with_both_flags']}")
    lines.append(f"  With aa=1-only dates:         {report['tickers_with_aa1_only_dates']}")
    lines.append(f"  With trailing aa=0 gap:       {report['tickers_with_trailing_aa0_gap']}")
    lines.append("")

    tickers = report["tickers"]
    lines.append(f"Tickers listed ({len(tickers)}):")
    if tickers:
        for index, entry in enumerate(tickers, start=1):
            aa0_max = entry.get("aa0_max_date") or "-"
            aa1_max = entry.get("aa1_max_date") or "-"
            lines.append(
                f"  {index:>3}. {entry.get('ticker') or '-'} "
                f"aa0={entry.get('aa0_row_count')} (max={aa0_max}) "
                f"aa1={entry.get('aa1_row_count')} (max={aa1_max})"
            )
            lines.append(
                f"       aa1_only_dates={entry.get('aa1_only_dates_count')} "
                f"aa0_missing_after_aa1="
                f"{entry.get('aa0_missing_after_aa1_count')}"
            )
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only per-ticker coverage report for the price_cache "
            "auto_adjust flag split.  Issues a single SELECT against "
            "price_cache; never imports a provider, yfinance, the LLM, "
            "or the FastAPI app."
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
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced ticker list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every ticker."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_coverage(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

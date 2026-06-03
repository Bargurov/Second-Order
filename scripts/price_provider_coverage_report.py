#!/usr/bin/env python3
"""Read-only provider-provenance coverage report for ``price_cache``.

D2C taught the canonical ``price_cache.fetch_daily_cached`` path to stamp
``price_cache.source_provider`` with the market-data provider that served
each bar.  Rows written before that (and by the backfill/repair/promote
writers, which do not stamp yet) carry NULL — which
``db.derive_price_provider`` reads back as ``legacy_unknown``.

This report walks ``price_cache`` once with a single read-only ``SELECT``
and groups every row by ``db.derive_price_provider(source_provider)`` — the
SAME helper the rest of the codebase reads through, so the buckets here
match what every consumer sees.  Per provider it reports:

  * ``row_count``        — cached bars attributed to this provider.
  * ``ticker_count``     — distinct symbols.
  * ``raw_rows``         — bars at ``auto_adjust=0`` (unadjusted).
  * ``adjusted_rows``    — bars at ``auto_adjust=1`` (split/div-adjusted).
  * ``other_basis_rows`` — bars whose ``auto_adjust`` is neither 0 nor 1
                           (defensive; normally 0).
  * ``min_date`` / ``max_date`` — cheap date range over the bucket.

Top-level: ``total_rows`` (== ``COUNT(*)`` == sum of per-provider
``row_count``), ``total_tickers`` (distinct across the whole table),
``provider_count``, the ``providers`` map, and an explicit ``caveat``.

Caveat (surfaced in every payload)
----------------------------------
``legacy_unknown`` means the provider was **not recorded at write time** —
it is a provenance gap, NOT a claim that the data is invalid.  These rows
are real cached bars; they simply predate provider stamping or came from a
writer that does not stamp yet.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues a single ``SELECT`` against ``price_cache``; never
  INSERT / UPDATE / DELETE, never calls ``_ensure_table`` / ``init_db``,
  never writes ``fetched_at``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check`` /
  ``market_data`` / ``price_cache.fetch_daily_cached``, no provider call,
  no network, no cache refresh.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.

Usage::

    python scripts/price_provider_coverage_report.py
    python scripts/price_provider_coverage_report.py --json
    python scripts/price_provider_coverage_report.py --db-path ./events.db --json
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


_CAVEAT = (
    "legacy_unknown means provider was not recorded at write time, "
    "not that data is invalid."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def _empty_report() -> dict[str, Any]:
    return {
        "total_rows":     0,
        "total_tickers":  0,
        "provider_count": 0,
        "providers":      {},
        "caveat":         _CAVEAT,
    }


def summarize_provider_coverage(*, db_path: str | None = None) -> dict[str, Any]:
    """Return the provider-provenance coverage report dict.

    Parameters
    ----------
    db_path
        Optional path to a SQLite ``events.db`` carrying ``price_cache``.
        When omitted, reads ``db.DB_FILE`` so the report follows whichever
        archive the caller's process is bound to.

    Read-only and defensive: a missing file, a missing ``price_cache``
    table, or any ``sqlite3.Error`` returns the honest empty shape rather
    than raising.
    """
    path = _resolve_db_path(db_path)
    if path is None:
        return _empty_report()

    try:
        # Read-only / no-create (matches data_hygiene_report.py): a missing
        # file raises sqlite3.Error here instead of creating a stray events.db.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return _empty_report()

    try:
        try:
            rows = conn.execute(
                "SELECT source_provider, auto_adjust, ticker, date "
                "FROM price_cache"
            ).fetchall()
        except sqlite3.Error:
            return _empty_report()
    finally:
        conn.close()

    # Group by the canonical read helper so the buckets match every
    # consumer's view of provenance.
    from db import derive_price_provider

    providers: dict[str, dict[str, Any]] = {}
    all_tickers: set[str] = set()

    for raw_provider, raw_flag, raw_ticker, raw_date in rows:
        provider = derive_price_provider(raw_provider)
        bucket = providers.get(provider)
        if bucket is None:
            bucket = {
                "row_count":        0,
                "_tickers":         set(),
                "raw_rows":         0,
                "adjusted_rows":    0,
                "other_basis_rows": 0,
                "min_date":         None,
                "max_date":         None,
            }
            providers[provider] = bucket

        bucket["row_count"] += 1

        try:
            flag_int = int(raw_flag)
        except (TypeError, ValueError):
            flag_int = None
        if flag_int == 0:
            bucket["raw_rows"] += 1
        elif flag_int == 1:
            bucket["adjusted_rows"] += 1
        else:
            bucket["other_basis_rows"] += 1

        if isinstance(raw_ticker, str) and raw_ticker.strip():
            t = raw_ticker.strip()
            bucket["_tickers"].add(t)
            all_tickers.add(t)

        if isinstance(raw_date, str) and raw_date.strip():
            d = raw_date.strip()
            if bucket["min_date"] is None or d < bucket["min_date"]:
                bucket["min_date"] = d
            if bucket["max_date"] is None or d > bucket["max_date"]:
                bucket["max_date"] = d

    # Finalize: replace the working ticker set with its cardinality.
    for bucket in providers.values():
        bucket["ticker_count"] = len(bucket.pop("_tickers"))

    return {
        "total_rows":     len(rows),
        "total_tickers":  len(all_tickers),
        "provider_count": len(providers),
        "providers":      providers,
        "caveat":         _CAVEAT,
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
    lines: list[str] = ["Price-cache provider-provenance coverage", ""]
    lines.append(f"Total cached bars:  {report['total_rows']}")
    lines.append(f"Distinct tickers:   {report['total_tickers']}")
    lines.append(f"Providers seen:     {report['provider_count']}")
    lines.append("")

    providers = report["providers"]
    if providers:
        # Largest bucket first; ties broken by provider name for stability.
        ordered = sorted(
            providers.items(),
            key=lambda kv: (-kv[1]["row_count"], kv[0]),
        )
        for name, p in ordered:
            lines.append(f"  {name}")
            lines.append(
                f"      rows={p['row_count']}  tickers={p['ticker_count']}  "
                f"raw(aa0)={p['raw_rows']}  adjusted(aa1)={p['adjusted_rows']}"
                + (
                    f"  other_basis={p['other_basis_rows']}"
                    if p["other_basis_rows"]
                    else ""
                )
            )
            lines.append(
                f"      dates={p.get('min_date') or '-'} .. "
                f"{p.get('max_date') or '-'}"
            )
    else:
        lines.append("  (no cached bars)")
    lines.append("")
    lines.append(f"Caveat: {report['caveat']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only provider-provenance coverage report for "
            "price_cache.  Groups every cached bar by "
            "db.derive_price_provider(source_provider).  Issues a single "
            "SELECT; never imports a provider, yfinance, the LLM, or the "
            "FastAPI app, and never mutates the database."
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
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's configured "
            "archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_provider_coverage(db_path=args.db_path)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

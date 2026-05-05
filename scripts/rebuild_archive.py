"""CLI entry point for reproducible archive rebuilds.

Usage examples::

    # Dry-run: preview which events would be refreshed and what changes.
    python scripts/rebuild_archive.py

    # Dry-run a narrower slice (last 90 days, tariff family only).
    python scripts/rebuild_archive.py --family tariff --max-age 90

    # Actually write back after reviewing the dry-run report.
    python scripts/rebuild_archive.py --write --limit 50

    # Write the markdown report to disk alongside stdout.
    python scripts/rebuild_archive.py --out rebuild_report.md

See ``archive_rebuild.py`` for the composer contract.  This script
is intentionally thin: argument parsing → event load → composer
call → report rendering.  All decision logic lives in the composer
so tests can exercise it without spawning subprocesses.

Safety model (audited)
----------------------
The defaults are deliberately conservative; running the script with
no flags is a *report-only* operation.  Specifically:

* **DB writes** — gated behind ``--write``.  The default invocation
  (``python scripts/rebuild_archive.py``) runs in dry-run mode:
  ``archive_rebuild.execute_rebuild`` short-circuits the persist loop
  unless the caller passes ``write=True``.  No row is mutated, no
  ``update_event_overlays`` call fires.  Dry-run is the only mode CI
  and casual operators should use; ``--write`` is for an operator
  who has already reviewed the dry-run report.

* **LLM / paid analysis** — never called.  The script invokes
  ``frozen_overlay_refresh.refresh_overlays_for_event``, whose
  composers are pure macro/credit/stress math over already-fetched
  market data.  No path reaches ``analyze_event``, ``anthropic``,
  or ``openai``.  ``ENABLE_PAID_ANALYSIS`` has no effect here.

* **Network / yfinance / provider** — *not* fully isolated.  The
  overlay composer needs today's macro tape (``^TNX``, ``^FVX``,
  ``^TYX``, ``TIP``, ``HYG``, ``LQD``, ``SHY``) to recompute
  rates / credit / stress overlays, and pulls those bars through
  ``market_check._fetch`` → ``price_cache.fetch_daily_cached``.
  On a *warm* cache the bars are served from SQLite and no provider
  call fires; on a *cold* cache the price-cache layer reaches the
  active ``MarketDataProvider`` (yfinance by default) for the missing
  trailing window.  This applies to both dry-run and ``--write``
  modes — the validation pass exercises the same composer with
  ``persist=False`` to produce the report.

  If you need a strictly network-isolated dry-run, point the price
  cache at a populated DB ahead of time, or run after a recent
  market-context refresh has warmed the cache.

* **Exit code** — ``0`` on dry-run, ``0`` on a successful ``--write``
  with zero composer errors, ``1`` only when ``--write`` ran and at
  least one event errored.  CI and shell wrappers can branch on the
  exit code without parsing the markdown report.

Tests at ``tests/test_rebuild_archive_cli.py`` pin the safety model:
``--help`` exits cleanly, the default invocation never invokes
``update_event_overlays``, and ``--write`` is required for the
persist seam to fire.  Network seams are patched out, so the test
suite is hermetic and runs offline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make sibling modules importable when the script is invoked via
# ``python scripts/rebuild_archive.py`` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from archive_rebuild import (   # noqa: E402
    SUPPORTED_OPERATIONS,
    format_rebuild_report,
    run_archive_rebuild,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reproducible archive rebuild tooling.",
    )
    p.add_argument(
        "--operation", default="overlays",
        choices=list(SUPPORTED_OPERATIONS),
        help="Which rebuild operation to run (default: overlays).",
    )
    p.add_argument(
        "--write", action="store_true",
        help="Persist changes to the DB.  Default is dry-run.",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of events after filtering.",
    )
    p.add_argument(
        "--archive-limit", type=int, default=2000,
        help="Max events to load from the archive before filtering.",
    )
    p.add_argument(
        "--family", action="append", default=None,
        help="Filter by mechanism family (repeat for multiple).",
    )
    p.add_argument(
        "--event-id", type=int, action="append", default=None,
        help="Restrict to explicit event ids (repeat for multiple).",
    )
    p.add_argument("--date-start", default=None, help="YYYY-MM-DD lower bound.")
    p.add_argument("--date-end",   default=None, help="YYYY-MM-DD upper bound.")
    p.add_argument("--min-age",    type=int, default=None)
    p.add_argument("--max-age",    type=int, default=None)
    p.add_argument(
        "--low-signal", choices=("yes", "no"), default=None,
        help="Filter to low-signal events (yes) or exclude them (no).",
    )
    p.add_argument(
        "--out", default=None,
        help="Write the markdown report to this path "
             "(stdout also gets a copy).",
    )
    p.add_argument(
        "--json-out", default=None,
        help="Write the full structured report to this JSON path.",
    )
    return p.parse_args(argv)


def _load_events(limit: int) -> list[dict]:
    """Load events from the archive.  Isolated so tests can monkeypatch."""
    from db import dedup_events, load_recent_events
    return dedup_events(load_recent_events(limit=limit))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    events = _load_events(args.archive_limit)

    low_signal = None
    if args.low_signal == "yes":
        low_signal = True
    elif args.low_signal == "no":
        low_signal = False

    date_range = None
    if args.date_start or args.date_end:
        date_range = (args.date_start, args.date_end)

    report = run_archive_rebuild(
        events,
        operation=args.operation,
        write=bool(args.write),
        event_ids=args.event_id,
        date_range=date_range,
        mechanism_family=args.family,
        min_age_days=args.min_age,
        max_age_days=args.max_age,
        low_signal=low_signal,
        limit=args.limit,
    )

    md = format_rebuild_report(report)
    print(md)

    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"[rebuild_archive] markdown written to {args.out}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[rebuild_archive] json written to {args.json_out}")

    # Exit non-zero when a write ran and some events errored — gives CI
    # and shell scripts a clear signal to investigate.
    if not report["dry_run"]:
        if report["write"].get("errored", 0) > 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""X1A CLI — print the read-only archive event-date placebo / negative-control.

Compares observed event-date AR-sign support against random non-event-date
windows for the same tickers / roles / horizons / benchmark. Read-only and
zero-cost: no provider, no network, no DB/cache write, no committed artifact.

Usage:
  python scripts/archive_placebo_report.py --draws 1000 --seed 20260608
"""
import argparse
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from stats.archive_placebo import build_report, summarize


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Archive event-date placebo / negative-control (read-only).")
    p.add_argument("--db", default="events.db", help="Source DB path (opened read-only).")
    p.add_argument("--draws", type=int, default=1000)
    p.add_argument("--seed", type=int, default=20260608)
    args = p.parse_args(argv)
    print(summarize(build_report(args.db, draws=args.draws, seed=args.seed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""V2A CLI — print a DRY-RUN exposed-name AR coverage repair plan.

Read-only and zero-cost: reproduces the coverage snapshot, enumerates missing
exposed/loser AR units, classifies fixability, and prints bounded backfill
windows for a FUTURE gated V2B step.  It NEVER fetches, writes, or mutates
anything.  Any request to write/fetch/backfill/execute (or pass confirm_paid)
is refused with a nonzero exit — that work belongs to the separate, gated V2B
step (DB copy + explicit operator confirm_paid).

Usage:
  python scripts/ar_coverage_repair_plan.py --dry-run --scenario scored
"""
import argparse
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from stats.ar_coverage_repair_planner import SCENARIOS, build_repair_plan, summarize


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dry-run exposed-name AR coverage repair planner (read-only).")
    p.add_argument("--db", default="events.db", help="Source DB path (opened read-only).")
    p.add_argument("--scenario", choices=list(SCENARIOS), default="scored")
    p.add_argument("--dry-run", action="store_true", help="The only supported mode (default).")
    # Refused mutation flags — V2A is dry-run only.
    p.add_argument("--write", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--fetch", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--backfill", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--execute", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--confirm-paid", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if args.write or args.fetch or args.backfill or args.execute or args.confirm_paid:
        print(
            "ERROR: this is a DRY-RUN planner only. write/fetch/backfill/execute "
            "and confirm_paid are NOT available here. Provider fetch + cache "
            "write is the separate, gated V2B step (DB copy + explicit operator "
            "confirm_paid). Refusing.",
            file=sys.stderr,
        )
        return 2

    plan = build_repair_plan(args.db, scenario=args.scenario)
    print(summarize(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

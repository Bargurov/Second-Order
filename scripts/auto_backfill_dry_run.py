#!/usr/bin/env python3
"""Auto-backfill dry-run CLI.

Composes the four already-built pure pieces — config loader, ledger,
state, planner — through ``auto_backfill_runner.run_auto_backfill_dry_run``
to preview what one scheduler tick would do.  Emits a compact text
report by default; ``--json`` for structured output.

Out of scope (deliberately)
---------------------------
* No scheduler.  This is a one-shot CLI; it never starts APScheduler.
* No paid execution.  ``execute_paid_candidate`` is never called and
  the runner records ``spent_calls=0`` on every path.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``, no
  network.  The default candidate source reads
  ``/registry/candidate-queue`` data in-process via the existing
  helper, which is itself a pure read.
* No FastAPI startup wiring.

Two seams keep tests cheap:

* :func:`load_candidates` — the candidate source.  Lazily imports
  ``routes.diagnostics`` so a disabled-config invocation never pays
  the import cost.
* ``run_auto_backfill_dry_run`` — the runner.  Re-bound at module
  level so tests can patch ``scripts.auto_backfill_dry_run.run_auto_backfill_dry_run``.

Usage:
    python scripts/auto_backfill_dry_run.py
    python scripts/auto_backfill_dry_run.py --json
    python scripts/auto_backfill_dry_run.py --limit 10 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_backfill_config import (                              # noqa: E402
    AutoBackfillConfig,
    load_auto_backfill_config,
)
from auto_backfill_ledger import AutoBackfillLedger             # noqa: E402
from auto_backfill_runner import (                              # noqa: E402
    RunResult,
    run_auto_backfill_dry_run,
)
from auto_backfill_state import AutoBackfillState               # noqa: E402


_DEFAULT_LIMIT:        int = 25
_DEFAULT_SINCE_HOURS:  int = 72
_DEFAULT_TTL_SECONDS:  int = 3600


# ---------------------------------------------------------------------------
# Candidate source seam
# ---------------------------------------------------------------------------


def load_candidates(
    *,
    limit: int = _DEFAULT_LIMIT,
    since_hours: int = _DEFAULT_SINCE_HOURS,
) -> list[dict]:
    """Default candidate source — calls ``registry_candidate_queue`` in-process.

    Pure read of cached news + registry state; no LLM, no ``yfinance``,
    no ``market_check``, no network, no DB writes.  Imported lazily so
    a disabled-config invocation never pulls in ``routes.diagnostics``
    or the FastAPI app it imports.

    Tests should patch ``scripts.auto_backfill_dry_run.load_candidates``
    rather than mocking the route helper directly.
    """
    from routes.diagnostics import registry_candidate_queue
    payload = registry_candidate_queue(
        limit=limit,
        since_hours=since_hours,
        include_low_signal=False,
    )
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    return list(items) if items else []


# ---------------------------------------------------------------------------
# Payload composition
# ---------------------------------------------------------------------------


def _summarise_candidate(candidate: Any) -> dict:
    if not isinstance(candidate, dict):
        return {}
    return {
        "headline":       candidate.get("headline"),
        "rank_score":     candidate.get("rank_score"),
        "source_count":   candidate.get("source_count"),
        "published_at":   candidate.get("published_at"),
        "registry_state": candidate.get("registry_state"),
        "skip_reason":    candidate.get("skip_reason"),
    }


def _build_payload(
    *,
    cfg: AutoBackfillConfig,
    ledger_remaining: int,
    candidates_input_size: int,
    result: RunResult,
) -> dict:
    plan = result.plan
    if plan is not None:
        effective_cap = plan.effective_call_cap
        considered    = plan.considered_count
        eligible      = plan.eligible_count
        skip_counts   = dict(plan.skip_counts)
        skip_reasons  = dict(plan.skip_reasons)
        selected      = [_summarise_candidate(c) for c in plan.selected]
    else:
        effective_cap = min(cfg.max_calls_per_run, ledger_remaining)
        considered    = candidates_input_size
        eligible      = 0
        skip_counts   = {}
        skip_reasons  = {}
        selected      = []

    return {
        "ok":                    True,
        "decision_reason":       result.decision_reason,
        "skip_reason":           result.skip_reason,
        "effective_status":      cfg.effective_status,
        "effective_per_run_cap": effective_cap,
        "daily_remaining":       ledger_remaining,
        "considered_count":      considered,
        "eligible_count":        eligible,
        "selected_count":        result.selected_count,
        "selected":              selected,
        "skip_counts":           skip_counts,
        "skip_reasons":          skip_reasons,
        "config": {
            "enabled":               cfg.enabled,
            "paid_analysis_enabled": cfg.paid_analysis_enabled,
            "max_calls_per_run":     cfg.max_calls_per_run,
            "max_calls_per_day":     cfg.max_calls_per_day,
            "interval_hours":        cfg.interval_hours,
            "model":                 cfg.model,
            "effective_status":      cfg.effective_status,
        },
        "now":                   result.now,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict) -> str:
    lines: list[str] = ["Auto-backfill dry-run", ""]
    lines.append(f"Effective status: {payload['effective_status']}")
    lines.append(f"Decision reason:  {payload['decision_reason']}")
    lines.append(f"Skip reason:      {payload['skip_reason'] or '-'}")
    lines.append("")
    lines.append(f"Effective per-run cap: {payload['effective_per_run_cap']}")
    lines.append(f"Daily remaining:       {payload['daily_remaining']}")
    lines.append("")

    if payload["skip_reason"]:
        lines.append("(skipped before planning)")
        return "\n".join(lines)

    lines.append(f"Considered: {payload['considered_count']}")
    lines.append(f"Eligible:   {payload['eligible_count']}")
    lines.append(f"Selected:   {payload['selected_count']}")

    if payload["selected"]:
        lines.append("")
        lines.append("Selected candidates:")
        for index, candidate in enumerate(payload["selected"], start=1):
            rank    = candidate.get("rank_score")
            sources = candidate.get("source_count")
            head    = candidate.get("headline")
            rank_text = (
                f"{float(rank):.2f}"
                if isinstance(rank, (int, float)) and not isinstance(rank, bool)
                else str(rank)
            )
            lines.append(
                f"  {index:>2}. [rank={rank_text} sources={sources}] {head}"
            )

    lines.append("")
    lines.append("Skip counts:")
    for key, value in payload["skip_counts"].items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run preview of one auto-backfill scheduler tick.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            "Maximum number of candidates to fetch from the registry "
            "candidate queue.  Independent of the per-run LLM cap."
        ),
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=_DEFAULT_SINCE_HOURS,
        help="Recency window passed to the candidate-queue helper.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _will_attempt_run(cfg: AutoBackfillConfig) -> bool:
    """A tick is worth fetching candidates for only when both gates are
    on.  Disabled / paid-blocked configurations short-circuit before
    any I/O so the CLI stays zero-cost in the off state.
    """
    return cfg.enabled and cfg.paid_analysis_enabled


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    cfg = load_auto_backfill_config()
    ledger = AutoBackfillLedger(daily_cap=cfg.max_calls_per_day)
    state  = AutoBackfillState(ttl_seconds=_DEFAULT_TTL_SECONDS)

    if _will_attempt_run(cfg):
        candidates: Iterable[dict] = load_candidates(
            limit=args.limit, since_hours=args.since_hours,
        )
    else:
        candidates = []
    candidate_list = list(candidates)

    result = run_auto_backfill_dry_run(
        candidates=candidate_list,
        config=cfg,
        state=state,
        ledger=ledger,
    )

    ledger_remaining = ledger.snapshot().remaining
    payload = _build_payload(
        cfg=cfg,
        ledger_remaining=ledger_remaining,
        candidates_input_size=len(candidate_list),
        result=result,
    )

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

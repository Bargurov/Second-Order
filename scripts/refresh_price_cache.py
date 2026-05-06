#!/usr/bin/env python3
"""Price-cache refresh dry-run CLI.

Composes :func:`price_cache_refresh.plan_refresh` with the read-only
input loader to preview which event x ticker windows a refresh would
warm.  Emits a compact text report by default; ``--json`` for tooling
/ CI.

Out of scope (deliberately)
---------------------------
* **No write mode.**  The planner is pure; no executor is invoked.
  ``--write`` / ``--confirm`` are deliberately absent on this CLI
  iteration; the design at ``docs/price_cache_refresh_design.md``
  pins the future write-mode contract.
* **No provider call.**  Neither :func:`price_cache_refresh.load_inputs`
  nor :func:`price_cache_refresh.plan_refresh` reach the network or
  the market-data provider.
* **No DB write.**  ``load_inputs`` opens SQLite in ``mode=ro``; this
  CLI never invokes ``db.save_event`` / ``update_review`` /
  ``append_revisit_snapshot``.
* **No LLM, no analyze_event, no auto-backfill paid path.**  The
  refresh planner is independent of the paid-execution graph; the
  test suite pins these invariants.

Two seams keep the CLI hermetic for tests:

* :data:`plan_refresh` — the planner seam.  Tests patch
  ``scripts.refresh_price_cache.plan_refresh`` directly.
* :data:`load_inputs` — the events + cached-dates loader.  Tests
  patch with a stub returning ``([], {})`` so the hermetic path
  never touches SQLite.

Usage::

    python scripts/refresh_price_cache.py
    python scripts/refresh_price_cache.py --json
    python scripts/refresh_price_cache.py --max-events 25 --max-provider-calls 20 --json
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from price_cache_refresh import (                              # noqa: E402
    RefreshConfig,
    load_inputs,
    plan_refresh,
)


# Defaults pinned by ``docs/price_cache_refresh_design.md`` §5.3.
# Tightening them is low-risk, loosening requires a doc + test update.
_DEFAULT_MAX_EVENTS:         int = RefreshConfig.__dataclass_fields__[
    "max_events"
].default
_DEFAULT_MAX_PROVIDER_CALLS: int = RefreshConfig.__dataclass_fields__[
    "max_provider_calls"
].default


# ---------------------------------------------------------------------------
# DB-path resolution — kept lazy so ``--help`` does not import ``db``.
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    """Resolve the SQLite path used by ``load_inputs``.

    Lazy import of :mod:`db` keeps a no-arg ``--help`` invocation
    free of ``api`` / FastAPI side-effects.  Tests patch
    :data:`load_inputs` directly so this helper never runs in the
    hermetic suite.
    """
    from db import DB_FILE
    return DB_FILE


# ---------------------------------------------------------------------------
# Plan -> dict normalisation + payload composition
# ---------------------------------------------------------------------------


def _group_jobs_by_event(refresh_jobs: Sequence[Any]) -> list[dict]:
    """Collapse the planner's flat ``(event, ticker)`` job list into the
    per-event view the report renders.

    Deterministic order: events appear in the order their first job is
    encountered (the planner already orders events by
    ``event_date desc, id desc``); tickers within an event preserve the
    planner's encounter order too.
    """
    grouped: dict[int, dict] = {}
    order: list[int] = []
    for job in refresh_jobs:
        event_id = job.event_id
        if event_id not in grouped:
            grouped[event_id] = {
                "event_id":   event_id,
                "event_date": job.event_date,
                "tickers":    [],
            }
            order.append(event_id)
        grouped[event_id]["tickers"].append({
            "symbol":        job.symbol,
            "intervals":     [list(iv) for iv in job.intervals],
            "interval_count":job.provider_calls,
            "business_days": job.business_days,
            "auto_adjust":   job.auto_adjust,
        })
    return [grouped[eid] for eid in order]


def _plan_to_dict(plan: Any) -> dict:
    """Normalise a ``RefreshPlan`` dataclass (or a dict-shaped stub
    from a test) into a JSON-friendly view.
    """
    if isinstance(plan, dict):
        return plan
    if dataclasses.is_dataclass(plan):
        refresh_jobs = list(getattr(plan, "refresh_jobs", ()) or ())
        skip_counts = dict(getattr(plan, "skipped_counts", {}) or {})
        return {
            "decision_reason":         getattr(plan, "decision_reason", "no_work"),
            "events_considered":       int(getattr(plan, "events_considered", 0)),
            "tickers_considered":      int(getattr(plan, "tickers_considered", 0)),
            "events_planned":          len({j.event_id for j in refresh_jobs}),
            "unique_tickers":          len({j.symbol for j in refresh_jobs}),
            "total_business_days":     sum(j.business_days for j in refresh_jobs),
            "provider_calls_estimate": int(getattr(plan, "provider_calls_estimate", 0)),
            "max_provider_calls":      int(getattr(plan, "max_provider_calls", 0)),
            "cap_applied":             bool(getattr(plan, "cap_applied", False)),
            "skipped_counts":          skip_counts,
            "events":                  _group_jobs_by_event(refresh_jobs),
        }
    if hasattr(plan, "to_dict"):
        try:
            out = plan.to_dict()
        except Exception:
            out = {}
        return out if isinstance(out, dict) else {}
    return {}


def _compose_payload(*, plan_dict: dict, caps: dict, now_iso: str) -> dict:
    """Wrap the normalised plan in the CLI's outer envelope."""
    return {
        "ok":                      True,
        "now":                     now_iso,
        "decision_reason":         plan_dict.get("decision_reason", "no_work"),
        "caps":                    caps,
        "events_considered":       plan_dict.get("events_considered",       0),
        "tickers_considered":      plan_dict.get("tickers_considered",      0),
        "events_planned":          plan_dict.get("events_planned",          0),
        "unique_tickers":          plan_dict.get("unique_tickers",          0),
        "total_business_days":     plan_dict.get("total_business_days",     0),
        "provider_calls_estimate": plan_dict.get("provider_calls_estimate", 0),
        "max_provider_calls":      plan_dict.get("max_provider_calls",      caps["max_provider_calls"]),
        "cap_applied":             plan_dict.get("cap_applied",             False),
        "skipped_counts":          plan_dict.get("skipped_counts",          {}),
        "events":                  plan_dict.get("events",                  []),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_text(payload: dict) -> str:
    lines: list[str] = ["Price-cache refresh dry-run", ""]
    lines.append(f"Decision reason: {payload.get('decision_reason', '-')}")
    caps = payload.get("caps", {})
    lines.append(
        f"Caps: max_events={caps.get('max_events')!s} "
        f"max_provider_calls={caps.get('max_provider_calls')!s}"
    )
    if payload.get("cap_applied"):
        lines.append("(cap applied - some events were dropped)")
    lines.append("")

    lines.append("Selection:")
    for key in (
        "events_considered",
        "tickers_considered",
        "events_planned",
        "unique_tickers",
        "total_business_days",
        "provider_calls_estimate",
    ):
        lines.append(f"  {key:<28} {payload.get(key, 0)}")

    lines.append("")
    lines.append("Skip counts:")
    skipped = payload.get("skipped_counts", {}) or {}
    if not skipped:
        lines.append("  (none)")
    else:
        for reason, count in skipped.items():
            lines.append(f"  {reason:<28} {count}")

    events = payload.get("events", []) or []
    if events:
        lines.append("")
        lines.append(f"Planned events ({len(events)}):")
        for index, event in enumerate(events, start=1):
            event_id   = event.get("event_id")
            event_date = event.get("event_date")
            tickers    = event.get("tickers") or []
            lines.append(
                f"  {index:>3}. event_id={event_id} event_date={event_date}"
            )
            for ticker in tickers:
                symbol         = ticker.get("symbol")
                interval_count = ticker.get("interval_count", 0)
                bdays          = ticker.get("business_days",  0)
                intervals      = ticker.get("intervals")      or []
                window_str = (
                    f"{intervals[0][0]}..{intervals[-1][-1]}"
                    if intervals
                    else "-"
                )
                lines.append(
                    f"        - {symbol:<10} intervals={interval_count} "
                    f"business_days={bdays} window={window_str}"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run preview of the price-cache refresh planner.  "
            "Reports which event x ticker windows a refresh would warm "
            "without invoking any provider, LLM, or paid path."
        ),
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=_DEFAULT_MAX_EVENTS,
        help=(
            "Maximum number of events the planner is allowed to "
            f"include after filtering.  Default: {_DEFAULT_MAX_EVENTS}."
        ),
    )
    parser.add_argument(
        "--max-provider-calls",
        type=int,
        default=_DEFAULT_MAX_PROVIDER_CALLS,
        help=(
            "Run-level cap on the planner's provider-call estimate.  "
            f"Default: {_DEFAULT_MAX_PROVIDER_CALLS}."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    caps = {
        "max_events":         int(args.max_events),
        "max_provider_calls": int(args.max_provider_calls),
    }
    cfg = RefreshConfig(
        max_events=caps["max_events"],
        max_provider_calls=caps["max_provider_calls"],
    )

    try:
        events, cached_by_ticker = load_inputs(_default_db_path())
    except Exception:
        # Read-only loader degrades to empty inputs on any DB failure
        # so the dry-run still produces a stable report.
        events, cached_by_ticker = [], {}

    plan = plan_refresh(events, cached_by_ticker, config=cfg)
    plan_dict = _plan_to_dict(plan)
    payload = _compose_payload(
        plan_dict=plan_dict,
        caps=caps,
        now_iso=_now_iso(),
    )

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

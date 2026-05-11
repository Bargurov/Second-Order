#!/usr/bin/env python3
"""Read-only short-horizon candidate review queue.

Turns the existing ``short_horizon_repair_packet`` output into a
cleaner operator review queue.  Every row carries the candidate
itself plus two synthesised columns —
``operator_decision_needed`` (closed vocabulary) and
``reason_for_review`` (human-readable).  The queue is intended to
help an operator pick the next batch of events to expand the
repaired validation cohort beyond the current 5.

Read-only by construction
-------------------------

* Wraps ``scripts.short_horizon_repair_packet`` through a single
  patchable seam — tests inject synthetic payloads, the live path
  delegates to the real packet builder.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, no ``price_cache.fetch_daily_cached``, no
  provider call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never proposes tickers or mechanism families; surfaces the
  decision the operator must make, not the answer.
* The CSV ``short_horizon_repair_packet.csv`` on disk is NEVER
  written or rewritten by this script.

Output contract::

    {
      "ok":                    bool,
      "candidate_count":       int,
      "high_priority_count":   int,
      "medium_priority_count": int,
      "low_priority_count":    int,
      "review_queue": [                 # capped at --limit
        {
          "event_id":                int,
          "headline":                str | None,
          "event_date":              str | None,
          "current_primary_ticker":  str | None,
          "current_mechanism_family": str | None,
          "repair_type":             str,
          "repair_priority":         "high" | "medium" | "low",
          "operator_decision_needed": str,    # closed vocabulary
          "reason_for_review":        str,    # human-readable
        },
        ...
      ],
      "excluded_or_deferred": [          # already-reviewed event_ids
        {"event_id": int, "reason": str},
        ...
      ],
      "recommended_next_action": str,
    }

``operator_decision_needed`` vocabulary
---------------------------------------

* ``supply_primary_ticker``         — off-topic flag present, family OK
* ``supply_mechanism_family``       — only mechanism_family_none
* ``supply_ticker_and_family``      — both off-topic AND family_none
* ``exclude_or_promote_duplicate``  — duplicate-only flag set
* ``review_headline_for_relevance`` — fallback (no specific signal)

Conservative wording — banned tokens (``proof``, ``proves``,
``validated``, ``alpha``, ``guaranteed``).

Usage::

    python scripts/short_horizon_review_queue.py
    python scripts/short_horizon_review_queue.py --json --limit 50
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


_DEFAULT_LIMIT: int = 50

_FLAG_DRIV:    str = "driv_lit_off_topic"
_FLAG_LOCAL:   str = "local_off_topic_headline"
_FLAG_FAMILY:  str = "mechanism_family_none"
_FLAG_DUP:     str = "duplicate_date_ticker"

_OFF_TOPIC_FLAGS: frozenset[str] = frozenset({_FLAG_DRIV, _FLAG_LOCAL})

_DECISION_TICKER:        str = "supply_primary_ticker"
_DECISION_FAMILY:        str = "supply_mechanism_family"
_DECISION_BOTH:          str = "supply_ticker_and_family"
_DECISION_DUPLICATE:     str = "exclude_or_promote_duplicate"
_DECISION_REVIEW:        str = "review_headline_for_relevance"


_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


_RECOMMENDED_EMPTY: str = (
    "No short-horizon review candidates surfaced.  Refreshing the "
    "upstream short-horizon contamination report or expanding the "
    "fully-ready cohort may surface more rows."
)
_RECOMMENDED_HAS_ITEMS: str = (
    "{n} candidate(s) queued for operator review.  Inspect each "
    "headline and supply the indicated operator_decision_needed "
    "input by hand.  Surfaced rows are review candidates only — not "
    "claims about repairability or significance."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_short_horizon_repair_packet(
    *, db_path: str | None, limit: int,
) -> dict[str, Any]:
    """Wrap ``summarize_short_horizon_repair_packet`` so tests patch a
    single surface.  Lazy import keeps the module's import graph free
    of the upstream report dependencies until the un-patched path
    fires."""
    from scripts.short_horizon_repair_packet import (
        summarize_short_horizon_repair_packet,
    )

    return summarize_short_horizon_repair_packet(
        db_path=db_path, limit=limit,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_short_horizon_review_queue(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the review queue payload."""
    capped_limit = max(int(limit), 0)

    # We always ask the upstream packet for an effectively unlimited
    # cohort so our --limit only truncates the surfaced queue, not
    # the priority counts.
    packet = _safe_dict(_run_short_horizon_repair_packet(
        db_path=db_path, limit=10**9,
    ))

    raw_candidates = packet.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    rows: list[dict[str, Any]] = []
    for cand in raw_candidates:
        if not isinstance(cand, dict):
            continue
        row = _build_review_row(cand)
        if row is not None:
            rows.append(row)

    rows.sort(
        key=lambda r: (
            _PRIORITY_RANK.get(r.get("repair_priority"), 99),
            r.get("event_id", 0),
        )
    )

    high   = sum(1 for r in rows if r.get("repair_priority") == "high")
    medium = sum(1 for r in rows if r.get("repair_priority") == "medium")
    low    = sum(1 for r in rows if r.get("repair_priority") == "low")

    review_queue = rows[:capped_limit] if capped_limit else rows

    excluded_or_deferred = _build_excluded_or_deferred(packet)

    if rows:
        recommended = _RECOMMENDED_HAS_ITEMS.format(n=len(rows))
    else:
        recommended = _RECOMMENDED_EMPTY

    return {
        "ok":                       True,
        "candidate_count":          len(rows),
        "high_priority_count":      high,
        "medium_priority_count":    medium,
        "low_priority_count":       low,
        "review_queue":             review_queue,
        "excluded_or_deferred":     excluded_or_deferred,
        "recommended_next_action":  recommended,
    }


# ---------------------------------------------------------------------------
# Per-row construction
# ---------------------------------------------------------------------------


def _build_review_row(cand: dict[str, Any]) -> dict[str, Any] | None:
    ev_id = cand.get("event_id")
    if not isinstance(ev_id, int):
        return None
    flags_raw = cand.get("flags") or []
    flags = [f for f in flags_raw if isinstance(f, str)]
    repair_type = _coerce_str(cand.get("repair_type")) or "needs_review"
    priority = _coerce_str(cand.get("repair_priority")) or "low"
    if priority not in _PRIORITY_RANK:
        priority = "low"
    return {
        "event_id":                  ev_id,
        "headline":                  _coerce_str(cand.get("headline")),
        "event_date":                _coerce_str(cand.get("event_date")),
        "current_primary_ticker":    _coerce_str(
            cand.get("current_primary_ticker")
        ),
        "current_mechanism_family":  _derive_family(flags),
        "repair_type":               repair_type,
        "repair_priority":           priority,
        "operator_decision_needed":  _decide_action(
            repair_type=repair_type, flags=flags,
        ),
        "reason_for_review":         _build_reason(
            repair_type=repair_type, flags=flags,
        ),
    }


def _derive_family(flags: list[str]) -> str | None:
    """Surface the candidate's current mechanism_family STATE without
    inferring a value the packet doesn't carry.  When
    ``mechanism_family_none`` is in the flag set the family is
    explicitly empty (return ``"none"``); otherwise the packet does
    not surface the actual value, so return ``None`` so the row reads
    as "not the blocking issue, look elsewhere".
    """
    if _FLAG_FAMILY in flags:
        return "none"
    return None


def _decide_action(*, repair_type: str, flags: list[str]) -> str:
    has_off_topic = bool(set(flags) & _OFF_TOPIC_FLAGS)
    has_family    = _FLAG_FAMILY in flags
    has_dup_only  = (
        _FLAG_DUP in flags and not has_off_topic and not has_family
    )
    if has_off_topic and has_family:
        return _DECISION_BOTH
    if has_off_topic:
        return _DECISION_TICKER
    if has_family:
        return _DECISION_FAMILY
    if has_dup_only or repair_type == "duplicate_only":
        return _DECISION_DUPLICATE
    return _DECISION_REVIEW


def _build_reason(*, repair_type: str, flags: list[str]) -> str:
    """Plain-English reason listing the flag set + repair_type
    classification.  Conservative — never claims the candidate is
    "validated" or "repairable", only reviewable."""
    parts: list[str] = []
    if flags:
        parts.append("flags: " + ", ".join(flags))
    parts.append(f"repair_type={repair_type}")
    parts.append(
        "manual operator review required to decide the next action"
    )
    return "; ".join(parts)


def _build_excluded_or_deferred(
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = packet.get("excluded_reviewed_event_ids") or []
    if not isinstance(raw, list):
        return out
    seen: set[int] = set()
    for ev_id in raw:
        if not isinstance(ev_id, int) or ev_id in seen:
            continue
        seen.add(ev_id)
        out.append({
            "event_id": ev_id,
            "reason":   "already manually reviewed in prior batch",
        })
    out.sort(key=lambda r: r["event_id"])
    return out


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    return str(v)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Short-horizon review queue", ""]
    lines.append(f"OK:                    {report['ok']}")
    lines.append(f"Candidate count:       {report['candidate_count']}")
    lines.append(f"High priority:         {report['high_priority_count']}")
    lines.append(f"Medium priority:       {report['medium_priority_count']}")
    lines.append(f"Low priority:          {report['low_priority_count']}")
    queue = report.get("review_queue") or []
    if queue:
        lines.append("")
        lines.append(f"Queue ({len(queue)}):")
        for r in queue:
            head = (r.get("headline") or "").strip() or "-"
            if len(head) > 70:
                head = head[:67] + "..."
            lines.append(
                f"  id={r.get('event_id'):<5} "
                f"prio={r.get('repair_priority'):<6} "
                f"type={r.get('repair_type'):<22} "
                f"ticker={r.get('current_primary_ticker') or '-':<6} "
                f"family={r.get('current_mechanism_family') or '-'}"
            )
            lines.append(
                f"      decision={r.get('operator_decision_needed')}"
            )
            lines.append(f"      reason={r.get('reason_for_review')}")
            lines.append(f"      headline: {head}")

    excluded = report.get("excluded_or_deferred") or []
    if excluded:
        lines.append("")
        lines.append(f"Excluded / deferred ({len(excluded)}):")
        for e in excluded:
            lines.append(
                f"  id={e.get('event_id'):<5} reason={e.get('reason')}"
            )

    lines.append("")
    lines.append(
        f"Recommended next action: {report.get('recommended_next_action')}"
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only short-horizon candidate review queue.  Turns "
            "the existing short_horizon_repair_packet into a cleaner "
            "operator review queue surfacing the decision required "
            "and the reason each row is reviewable.  No DB writes, "
            "no provider calls, no LLM, no FastAPI.  Conservative "
            "wording: review candidates, not validated."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help="Optional events DB path.  Read-only.",
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced review_queue at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every candidate."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_short_horizon_review_queue(
        db_path=args.db_path, limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

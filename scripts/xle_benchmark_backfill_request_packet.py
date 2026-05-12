#!/usr/bin/env python3
"""XLE benchmark backfill request packet.

Read-only packet that surfaces the *exact* XLE business-day dates
needed to unblock the ``XLE`` benchmark-sensitivity preflight for the
manual-review backlog's two open candidates — events ``60`` and ``73``.
The packet is a structured **request** for operator action; it never
performs the action.

Why this exists
---------------

The ``xle_benchmark_sensitivity_backfill_smoke`` already demonstrated
that the existing local ``price_cache`` carries no XLE rows for the
estimation-window dates the preflight flags as missing — therefore
the local-cache lookup it performs cannot close the gap.  Unblocking
the preflight requires fetching those XLE rows from an outside source.
That fetch is out of scope for both the smoke and this packet — the
packet only enumerates *what* dates would be needed so an operator can
decide whether to authorise an online backfill.

Read-only by construction
-------------------------

* Only calls
  :func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`,
  which itself issues only ``SELECT`` statements.  No INSERT / UPDATE /
  DELETE.
* No DB writes anywhere — neither against the live DB nor a temp copy.
* No call to ``yfinance``, ``market_data``, ``price_cache.fetch_*``, an
  LLM, or any paid provider.  No network at all.
* No FastAPI surface — never imports ``api`` or ``routes.*``.
* No fabricated prices — the packet emits *dates*, never close /
  volume / return values.  A consumer can act on the packet only by
  going through the operator-approval flow for a real fetch.
* No SPY-vs-XLE conclusion is implied or asserted.  The packet
  describes cache geometry only.

Output contract (JSON)::

    {
      "ok":                     bool,         # packet built ok
      "benchmark_ticker":       str,
      "blocked_events": [
        {
          "event_id":          int,
          "event_date":        str | None,
          "primary_ticker":    str | None,
          "benchmark_ticker":  str,
          "blocker_reason":    str,
        },
        ...
      ],
      "required_dates":         [str, ...],   # sorted ISO, union
      "date_ranges": [
        {
          "event_id":  int,
          "start":     str,
          "end":       str,
          "reason":    str,
        },
        ...
      ],
      "reason":                 str,          # canonical reason token
                                              # ("estimation_window_short"
                                              # when all ranges agree,
                                              # "mixed" otherwise)
      "why_local_backfill_failed": str,       # one-line explanation
      "allowed_next_step":      str,          # request, not approval
      "not_allowed":            [str, ...],   # what this packet is NOT
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

``ok`` is True iff the packet was *built* without error.  It does NOT
mean the events are unblocked — a successful build with
``len(blocked_events) > 0`` is the normal state for this packet and is
the entire reason it exists.

Conservative wording
--------------------

The packet is a request, never an authorisation.  Banned tokens in
any text the packet emits: ``proof``, ``proven``, ``validated``,
``automatically``, ``alpha generated``, ``correct ticker``,
``guaranteed``, ``approved``, ``approves``.

Usage::

    python scripts/xle_benchmark_backfill_request_packet.py --json
    python scripts/xle_benchmark_backfill_request_packet.py --json \\
        --event-ids 60,73 --benchmark XLE
    python scripts/xle_benchmark_backfill_request_packet.py --json \\
        --output artifacts/xle_backfill_request_packet.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts import benchmark_sensitivity_preflight as _preflight  # noqa: E402


_DEFAULT_EVENT_IDS: tuple[int, ...] = (60, 73)
_DEFAULT_BENCHMARK: str             = "XLE"
_DEFAULT_HORIZONS:  tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int     = 60


_REASON_MIXED: str = "mixed"


# Canonical ``not_allowed`` items — surfaced as a list rather than
# prose so a downstream verification harness can pin each one as a
# substring assertion without parsing English.
_NOT_ALLOWED: tuple[str, ...] = (
    "online fetch of price data without explicit operator approval",
    "writes to the live DB or any temp copy",
    "fabricated XLE prices, close values, or returns",
    "SPY-vs-XLE sensitivity inference before the missing rows exist",
    "interpretation of benchmark sensitivity until the required dates "
    "are present in price_cache",
)


_WHY_LOCAL_BACKFILL_FAILED: str = (
    "the existing local price_cache has no XLE rows for the dates "
    "listed in 'required_dates'; the preflight surfaces those dates "
    "as missing benchmark coverage, and the read-only local-cache "
    "lookup performed by xle_benchmark_sensitivity_backfill_smoke "
    "therefore returns zero candidate rows"
)


_ALLOWED_NEXT_STEP: str = (
    "request explicit operator approval before invoking an online XLE "
    "backfill for the listed dates; this packet is a request, not an "
    "authorisation, and benchmark sensitivity cannot be interpreted "
    "until those rows exist in the local price_cache"
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_xle_benchmark_backfill_request_packet(
    *,
    db_path:    str | None      = None,
    event_ids:  Sequence[int]   = _DEFAULT_EVENT_IDS,
    benchmark:  str             = _DEFAULT_BENCHMARK,
    horizons:   Sequence[int]   = _DEFAULT_HORIZONS,
    estimation_window: int      = _DEFAULT_ESTIMATION_WINDOW,
    output_path: str | None     = None,
) -> dict[str, Any]:
    """Build the XLE benchmark backfill request packet.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    benchmark_upper = (benchmark or _DEFAULT_BENCHMARK).strip().upper()
    horizons_clean = tuple(
        int(h) for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_clean:
        horizons_clean = _DEFAULT_HORIZONS

    event_ids_clean: list[int] = []
    seen: set[int] = set()
    for ev in event_ids:
        if isinstance(ev, int) and ev not in seen:
            event_ids_clean.append(ev)
            seen.add(ev)

    preflight_report: dict[str, Any]
    try:
        preflight_report = _preflight.summarize_benchmark_sensitivity_preflight(
            db_path=db_path,
            event_ids=event_ids_clean,
            benchmark=benchmark_upper,
            horizons=horizons_clean,
            estimation_window=int(estimation_window),
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"preflight raised: {type(exc).__name__}: {exc}"
        )
        preflight_report = {}

    if not preflight_report.get("ok", False) and not errors:
        warnings.append(
            "preflight returned ok=False; the packet may be partial"
        )

    blocked_events: list[dict[str, Any]] = []
    date_ranges:    list[dict[str, Any]] = []
    required_dates_set: set[str]         = set()
    reasons_seen:   set[str]             = set()

    for row in preflight_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("can_run_sensitivity"):
            # Already unblocked — nothing to request for this event.
            continue
        ev_id = row.get("event_id")
        if not isinstance(ev_id, int):
            continue
        blocked_events.append({
            "event_id":         ev_id,
            "event_date":       _maybe_str(row.get("event_date")),
            "primary_ticker":   _maybe_str(row.get("primary_ticker")),
            "benchmark_ticker": _maybe_str(row.get("benchmark_ticker"))
                                or benchmark_upper,
            "blocker_reason":   _maybe_str(row.get("blocker_reason")) or "",
        })
        for rg in row.get("missing_benchmark_ranges") or []:
            if not isinstance(rg, dict):
                continue
            start = _maybe_str(rg.get("start"))
            end   = _maybe_str(rg.get("end"))
            reason = _maybe_str(rg.get("reason")) or ""
            if start is None or end is None:
                continue
            date_ranges.append({
                "event_id": ev_id,
                "start":    start,
                "end":      end,
                "reason":   reason,
            })
            if reason:
                reasons_seen.add(reason)
            for d in _business_days_inclusive(start, end):
                required_dates_set.add(d.isoformat())

    # ``reason`` collapses to the single token when every range agrees;
    # otherwise emit "mixed" so consumers don't false-positive on a
    # single-token field.
    if not reasons_seen:
        reason_token = ""
    elif len(reasons_seen) == 1:
        reason_token = next(iter(reasons_seen))
    else:
        reason_token = _REASON_MIXED

    blocked_events.sort(key=lambda e: e["event_id"])
    date_ranges.sort(key=lambda r: (r["event_id"], r["start"], r["end"]))
    required_dates = sorted(required_dates_set)

    if blocked_events and not required_dates:
        warnings.append(
            "preflight reported blocked events but emitted no "
            "missing_benchmark_ranges; the packet has nothing concrete "
            "to request"
        )

    envelope: dict[str, Any] = {
        "ok":                        not errors,
        "benchmark_ticker":          benchmark_upper,
        "blocked_events":            blocked_events,
        "required_dates":            required_dates,
        "date_ranges":               date_ranges,
        "reason":                    reason_token,
        "why_local_backfill_failed": _WHY_LOCAL_BACKFILL_FAILED,
        "allowed_next_step":         _ALLOWED_NEXT_STEP,
        "not_allowed":               list(_NOT_ALLOWED),
        "warnings":                  warnings,
        "errors":                    errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _business_days_inclusive(
    start_iso: str, end_iso: str,
) -> list[_date]:
    """Inclusive ``[start, end]`` weekday-only iterator (Mon-Fri).

    Mirrors the preflight's own date-math: weekday-only, no NYSE
    holiday filter.  Holiday-closed days such as ``2026-01-01`` are
    therefore retained in ``required_dates``; the operator-approval
    flow that ultimately fetches the rows is responsible for skipping
    them, not this packet.
    """
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)
    if s is None or e is None or s > e:
        return []
    out: list[_date] = []
    cur = s
    one = _timedelta(days=1)
    while cur <= e:
        if cur.weekday() < 5:
            out.append(cur)
        cur = cur + one
    return out


def _parse_iso(value: Any) -> _date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(packet: dict[str, Any]) -> str:
    lines: list[str] = [
        "XLE benchmark backfill request packet", "",
    ]
    lines.append(f"OK:                  {packet['ok']}")
    lines.append(f"Benchmark ticker:    {packet['benchmark_ticker']}")
    lines.append(
        f"Blocked events:      {len(packet['blocked_events'])}"
    )
    for ev in packet["blocked_events"]:
        lines.append(
            f"  - event_id={ev['event_id']} "
            f"event_date={ev['event_date']} "
            f"primary={ev['primary_ticker']} "
            f"blocker={ev['blocker_reason']!r}"
        )
    lines.append(f"Reason:              {packet['reason']!r}")
    lines.append(
        f"Required dates:      {len(packet['required_dates'])}"
    )
    for d in packet["required_dates"]:
        lines.append(f"  - {d}")
    lines.append(f"Date ranges:         {len(packet['date_ranges'])}")
    for rg in packet["date_ranges"]:
        lines.append(
            f"  - event_id={rg['event_id']} {rg['start']} → "
            f"{rg['end']} ({rg['reason']})"
        )
    lines.append("")
    lines.append(
        f"Why local backfill failed:\n  {packet['why_local_backfill_failed']}"
    )
    lines.append("")
    lines.append(f"Allowed next step:\n  {packet['allowed_next_step']}")
    lines.append("")
    lines.append("Not allowed:")
    for item in packet["not_allowed"]:
        lines.append(f"  - {item}")
    if packet.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in packet["warnings"]:
            lines.append(f"  - {w}")
    if packet.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in packet["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(packet: dict[str, Any]) -> str:
    return json.dumps(packet, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_int_csv(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for tok in (value or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(out)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only XLE benchmark backfill request packet.  Lists "
            "the exact XLE dates needed to unblock the benchmark-"
            "sensitivity preflight for events 60 and 73 (by default), "
            "without fetching or fabricating prices.  This is a "
            "request packet, not a backfill; no DB writes, no "
            "provider, no LLM, no FastAPI."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text packet.",
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids to request backfill for "
            f"(default {','.join(str(i) for i in _DEFAULT_EVENT_IDS)})."
        ),
    )
    parser.add_argument(
        "--benchmark", dest="benchmark", default=_DEFAULT_BENCHMARK,
        help=f"Benchmark ticker symbol (default {_DEFAULT_BENCHMARK!r}).",
    )
    parser.add_argument(
        "--horizons", dest="horizons",
        default=",".join(str(h) for h in _DEFAULT_HORIZONS),
        help=(
            f"Comma-separated forward horizons in business days "
            f"(default {','.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--estimation-window", dest="estimation_window",
        type=int, default=_DEFAULT_ESTIMATION_WINDOW,
        help=(
            f"Pre-event cache dates required for estimation (default "
            f"{_DEFAULT_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the live events DB.  Defaults to "
            "db.DB_FILE.  Read-only by construction."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON packet to.  When omitted, "
            "the packet has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    packet = build_xle_benchmark_backfill_request_packet(
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        benchmark=args.benchmark,
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(packet), file=output)
    else:
        print(_render_text(packet), file=output)
    return 0 if packet.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_xle_benchmark_backfill_request_packet",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

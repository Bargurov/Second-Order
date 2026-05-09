#!/usr/bin/env python3
"""Read-only next manual ticker repair batch selector.

Selects the next batch of candidate events for manual ticker repair
review.  Wraps two upstream reports through patchable seams::

    _run_repair_packet
        :func:`scripts.manual_ticker_repair_packet.summarize_repair_packet`
        with ``priority="medium"`` and ``production_like_only=True`` —
        the medium / production-like cohort is the deepest pool of
        recoverable rows once seed-/template-headline rows are dropped.

    _run_sector_benchmark_suggestions
        :func:`scripts.sector_benchmark_suggestion_report
        .summarize_sector_benchmark_suggestions` — supplies a per-event
        ``suggested_benchmark`` hint and ``confidence`` tier.

The selector joins the two payloads by ``event_id``, drops events
already manually reviewed (see :data:`_EXCLUDED_EVENT_IDS`), sorts by
``(-fast_to_clean_score, event_id)``, assigns a 1-based
``candidate_rank``, and truncates to ``--limit`` (default 10).

This is a triage *selector*.  It does NOT propose replacement tickers
or benchmarks; the operator-input columns
(``proposed_primary_ticker``, ``proposed_benchmark``,
``proposed_mechanism_family``, ``ticker_rationale``,
``exclude_reason``) are emitted as blank strings — operator must fill
them in by hand.

Output contract (JSON)::

    {
      "ok":                              bool,
      "limit":                           int,
      "excluded_event_ids":              list[int],   # sorted ascending
      "reviewed_exclusion_set_count":    int,
      "excluded_from_current_packet_count": int,
      "upstream_packet_candidate_count": int,
      "candidates_after_exclusion":      int,
      "candidates": [                                # capped at --limit,
                                                     # ranked 1..N
        {
          "candidate_rank":             int,         # 1-based
          "event_id":                   int,
          "headline":                   str | None,
          "event_date":                 str | None,
          "suggested_benchmark":        str,         # e.g. "XLE", "SPY"
          "benchmark_confidence":       "high" | "medium" | "low" | "none",
          "fast_to_clean_score":        int,         # in [0, 10]
          "proposed_primary_ticker":    "",          # operator-input
          "proposed_benchmark":         "",
          "proposed_mechanism_family":  "",
          "ticker_rationale":           "",
          "exclude_reason":             "",
        },
        ...
      ],
      "recommended_next_action":         str,
    }

CSV output uses the same 12 column names as the JSON per-row keys, in
the same order.  Lines terminate with ``\n`` (no Windows CRLF).

Out of scope (deliberately)
---------------------------
* Read-only.  The selector issues no SQL of its own; every DB read
  flows through the upstream packet's SELECT-only path.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI surface — never imports ``api`` or ``routes.*``.
* Never assigns tickers or benchmarks; ``suggested_benchmark`` is a
  hint, ``proposed_*`` columns stay blank.

Usage::

    python scripts/next_manual_repair_batch_selector.py
    python scripts/next_manual_repair_batch_selector.py --json --limit 10
    python scripts/next_manual_repair_batch_selector.py --csv  --limit 10
    python scripts/next_manual_repair_batch_selector.py --json --db-path ./events.db
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 10

# Effectively unlimited per-event cap when delegating to the upstream
# reports.  We need every shortlisted row in the archive to apply the
# exclusion filter and aggregate counts correctly — operator
# ``--limit`` only truncates the emitted candidates list.
_UPSTREAM_FETCH_ALL: int = 10**12


# Twenty-four event_ids known to be already manually reviewed.  Hardcoded
# as a frozenset; tests pin both the count (24) and the membership.
# Future operator review batches should grow this set explicitly so
# reviewers notice the cohort change.
_EXCLUDED_EVENT_IDS: frozenset[int] = frozenset({
    4, 6, 8, 9,
    46, 47, 49, 51,
    60, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
})


# Per-row column order — pinned in tests; do not reorder.
_BATCH_COLUMNS: tuple[str, ...] = (
    "candidate_rank",
    "event_id",
    "headline",
    "event_date",
    "suggested_benchmark",
    "benchmark_confidence",
    "fast_to_clean_score",
    "proposed_primary_ticker",
    "proposed_benchmark",
    "proposed_mechanism_family",
    "ticker_rationale",
    "exclude_reason",
)

_BLANK_OPERATOR_FIELDS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_benchmark",
    "proposed_mechanism_family",
    "ticker_rationale",
    "exclude_reason",
)


# Defensive fallback when the sector report has no entry for a packet
# event_id.  Should not fire on live data (the sector report runs the
# packet with ``priority="all"``, a superset of our medium / production
# slice), but the selector degrades cleanly when it does.
_SUGGESTED_BENCHMARK_FALLBACK: str = "SPY"
_BENCHMARK_CONFIDENCE_FALLBACK: str = "none"


_RECOMMENDED_EMPTY = (
    "No production-like medium candidates remain after exclusion — "
    "the next manual review batch is empty for this slice."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} candidate(s) ready for the next manual review batch, ranked "
    "by estimated fast-to-clean potential.  Operator must inspect each "
    "headline by hand and fill in the primary ticker / benchmark / "
    "mechanism family / rationale columns; the suggested_benchmark "
    "column is a hint only."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_repair_packet(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the manual ticker repair packet with
    ``priority="medium"`` and ``production_like_only=True``.  The
    medium / production-like cohort is the deepest pool of recoverable
    rows.  Tests patch this attribute directly so the import only
    resolves on the un-patched path.
    """
    from scripts.manual_ticker_repair_packet import (
        summarize_repair_packet,
    )

    return summarize_repair_packet(
        db_path=db_path,
        limit=_UPSTREAM_FETCH_ALL,
        priority="medium",
        production_like_only=True,
    )


def _run_sector_benchmark_suggestions(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the sector benchmark suggestion report with an
    effectively unlimited per-row cap.  Tests patch this attribute
    directly so the import only resolves on the un-patched path.
    """
    from scripts.sector_benchmark_suggestion_report import (
        summarize_sector_benchmark_suggestions,
    )

    return summarize_sector_benchmark_suggestions(
        db_path=db_path, limit=_UPSTREAM_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_next_manual_repair_batch(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the next manual ticker repair batch payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    packet = _safe_dict(_run_repair_packet(db_path=db_path))
    sector = _safe_dict(_run_sector_benchmark_suggestions(db_path=db_path))

    raw_candidates = packet.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    suggestion_lookup = _build_suggestion_lookup(sector.get("suggestions"))

    upstream_count = 0
    excluded_from_current_packet_count = 0
    eligible: list[dict[str, Any]] = []

    for c in raw_candidates:
        if not isinstance(c, dict):
            continue
        ev_id = c.get("event_id")
        if not isinstance(ev_id, int):
            continue
        upstream_count += 1
        if ev_id in _EXCLUDED_EVENT_IDS:
            excluded_from_current_packet_count += 1
            continue
        eligible.append(c)

    # Exclude → sort → truncate.  Sorting after exclusion keeps the
    # ranking stable when the upstream reorders or when an excluded id
    # would otherwise consume a top slot.
    eligible.sort(
        key=lambda c: (-_safe_int(c.get("fast_to_clean_score")),
                       _safe_int(c.get("event_id"))),
    )

    truncated = eligible[:capped_limit]

    candidates: list[dict[str, Any]] = []
    for rank, c in enumerate(truncated, start=1):
        ev_id = int(c["event_id"])
        benchmark, confidence = suggestion_lookup.get(
            ev_id,
            (_SUGGESTED_BENCHMARK_FALLBACK, _BENCHMARK_CONFIDENCE_FALLBACK),
        )
        candidates.append({
            "candidate_rank":             rank,
            "event_id":                   ev_id,
            "headline":                   c.get("headline"),
            "event_date":                 c.get("event_date"),
            "suggested_benchmark":        benchmark,
            "benchmark_confidence":       confidence,
            "fast_to_clean_score":        _safe_int(c.get("fast_to_clean_score")),
            # Operator-input columns: always blank.  The selector does
            # NOT propagate any proposed_* values that may leak from the
            # upstream packet — those columns belong to the operator.
            "proposed_primary_ticker":    "",
            "proposed_benchmark":         "",
            "proposed_mechanism_family":  "",
            "ticker_rationale":           "",
            "exclude_reason":             "",
        })

    candidates_after_exclusion = len(eligible)

    return {
        "ok":                              True,
        "limit":                           capped_limit,
        "excluded_event_ids":              sorted(_EXCLUDED_EVENT_IDS),
        "reviewed_exclusion_set_count":    len(_EXCLUDED_EVENT_IDS),
        "excluded_from_current_packet_count":
            excluded_from_current_packet_count,
        "upstream_packet_candidate_count": upstream_count,
        "candidates_after_exclusion":      candidates_after_exclusion,
        "candidates":                      candidates,
        "recommended_next_action":         _recommend(len(candidates)),
    }


def _build_suggestion_lookup(
    raw_suggestions: Any,
) -> dict[int, tuple[str, str]]:
    """Return ``{event_id: (suggested_benchmark, confidence)}`` from the
    sector report payload.  Tolerant of malformed entries — bad rows
    are skipped silently rather than poisoning the lookup.
    """
    out: dict[int, tuple[str, str]] = {}
    if not isinstance(raw_suggestions, list):
        return out
    for s in raw_suggestions:
        if not isinstance(s, dict):
            continue
        ev_id = s.get("event_id")
        if not isinstance(ev_id, int):
            continue
        benchmark = s.get("suggested_benchmark")
        confidence = s.get("confidence")
        if not isinstance(benchmark, str) or not benchmark:
            benchmark = _SUGGESTED_BENCHMARK_FALLBACK
        if not isinstance(confidence, str) or not confidence:
            confidence = _BENCHMARK_CONFIDENCE_FALLBACK
        out[ev_id] = (benchmark, confidence)
    return out


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recommend(n_candidates: int) -> str:
    if n_candidates <= 0:
        return _RECOMMENDED_EMPTY
    return _RECOMMENDED_HAS_CANDIDATES.format(n=n_candidates)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _render_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    # ``lineterminator='\n'`` avoids the default ``\r\n`` so the file
    # doesn't carry Windows-style CRLF line endings on this platform.
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_BATCH_COLUMNS)
    for entry in report.get("candidates") or []:
        writer.writerow([_csv_cell(entry.get(k)) for k in _BATCH_COLUMNS])
    return buf.getvalue()


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Next manual ticker repair batch", ""]
    lines.append(f"Limit:                              {report['limit']}")
    lines.append(
        f"Upstream packet candidate count:    "
        f"{report['upstream_packet_candidate_count']}"
    )
    lines.append(
        f"Reviewed exclusion set count:     "
        f"{report['reviewed_exclusion_set_count']}"
    )
    lines.append(
        f"Excluded from current packet:     "
        f"{report['excluded_from_current_packet_count']}"
    )
    lines.append(
        f"Candidates after exclusion:         "
        f"{report['candidates_after_exclusion']}"
    )
    lines.append("")
    candidates = report.get("candidates") or []
    lines.append(f"Candidates listed ({len(candidates)}):")
    if candidates:
        for entry in candidates:
            headline = entry.get("headline") or "-"
            lines.append(
                f"  rank={entry.get('candidate_rank')} "
                f"id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"score={entry.get('fast_to_clean_score')}/10 "
                f"benchmark={entry.get('suggested_benchmark')} "
                f"({entry.get('benchmark_confidence')})"
            )
            lines.append(f"      headline: {headline[:120]}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only next manual ticker repair batch selector.  "
            "Joins the manual ticker repair packet (priority=medium, "
            "production-like-only) with the sector benchmark "
            "suggestion report, drops already-reviewed event_ids, "
            "ranks the remainder by estimated fast-to-clean potential, "
            "and emits the next batch (default 10) as JSON or CSV.  "
            "Read-only: never assigns tickers or benchmarks, never "
            "edits the archive, no provider, no LLM, no FastAPI "
            "surface."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    fmt.add_argument(
        "--csv", action="store_true",
        help=(
            "Emit a CSV worksheet with the 12 batch columns.  "
            "Operator-input columns are blank; rows terminate with \\n."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced candidates list at N entries (default "
            f"{_DEFAULT_LIMIT}).  ``candidates_after_exclusion`` "
            f"reflects every eligible row before truncation."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path", default=None,
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

    report = summarize_next_manual_repair_batch(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    elif args.csv:
        # CSV already carries its own trailing newline per row; print
        # without an extra empty line.
        output.write(_render_csv(report))
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

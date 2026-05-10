#!/usr/bin/env python3
"""Read-only mechanism-family-only repair packet builder.

Surfaces already-tickered, fully-ready events that are blocked from
joining a clean mechanism-family validation cohort *only* because
their ``mechanism_family`` is null/"none" — the kind of row a human
operator can move into the cohort by supplying a family label by
hand, with no ticker retagging required.

Wraps :func:`scripts.stat_validation_ticker_contamination_report
.summarize_contamination` through the patchable seam
``_run_contamination_report`` so unit tests can drive the packet with
synthetic contamination payloads (no DB access on the test path).

Filter rule
-----------

A row from the contamination report is a candidate iff:

    * ``mechanism_family_none`` is in its flags AND
    * No off-topic flag is present
      (``local_off_topic_headline``, ``driv_lit_off_topic``).

The only allowed extra flag is ``duplicate_date_ticker`` — a
low-risk signal that downgrades ``repair_priority`` to ``"low"`` but
does not exclude the row.

Twenty-four already-reviewed event_ids (:data:`_EXCLUDED_EVENT_IDS`)
are dropped before ranking.

Because the upstream contamination report only enriches *fully-ready*
events (the AND of has_event_date, has_market_tickers, 1d/5d/20d
forward cache, SPY benchmark proxy, and a sufficient estimation
window — see :mod:`scripts.stat_validation_readiness_report`), every
candidate this packet surfaces is, by construction, already
price-cache-ready and already carries an event_date and a primary
ticker.  No per-row readiness re-check is needed.

This is a triage worksheet builder — conservative wording only.
The packet does NOT assign mechanism families and never touches the
archive.  ``proposed_mechanism_family``, ``mechanism_rationale``, and
``exclude_reason`` are emitted as blank strings for the operator to
fill in by hand.

Output contract (JSON)::

    {
      "ok":                              bool,
      "excluded_reviewed_event_ids":     list[int],   # sorted ascending
      "reviewed_exclusion_set_count":    int,
      "excluded_reviewed_count":         int,         # in-packet drop count
      "total_candidates_after_filter":   int,
      "candidates": [                                  # capped at --limit,
                                                       # sorted by
                                                       # (priority_rank,
                                                       #  event_id) asc
        {
          "event_id":                   int,
          "headline":                   str | None,
          "event_date":                 str | None,
          "current_primary_ticker":     str | None,
          "current_benchmark":          str,           # always "SPY"
          "flags":                      list[str],
          "repair_priority":            "high" | "medium" | "low",
          "reason":                     str,
          "proposed_mechanism_family":  "",
          "mechanism_rationale":        "",
          "exclude_reason":             "",
        },
        ...
      ],
      "recommended_next_action":         str,
    }

CSV output uses the same 11 column names as the JSON per-row keys,
in the same order.  ``flags`` is pipe-separated (``a|b``) inside a
single column.  Lines terminate with ``\n`` (no Windows CRLF).

Out of scope (deliberately)
---------------------------
* Read-only.  All DB reads flow through the upstream contamination
  report's SELECT-only path.  No INSERT / UPDATE / DELETE.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns mechanism families; the surfaced rows are "manual
  review candidates," not proof of repairability.

Usage::

    python scripts/mechanism_family_repair_packet.py
    python scripts/mechanism_family_repair_packet.py --json --limit 20
    python scripts/mechanism_family_repair_packet.py --csv  --limit 20
    python scripts/mechanism_family_repair_packet.py --json --db-path ./events.db
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


_DEFAULT_LIMIT: int = 25

# Effectively unlimited per-event cap when delegating to the upstream
# contamination report — we need every flagged fully-ready row in the
# archive to apply the mechanism-family filter and aggregate counts
# correctly.  Operator ``--limit`` only truncates the emitted
# candidates list.
_CONTAMINATION_FETCH_ALL: int = 10**12


# Twenty-four event_ids already manually reviewed.  Pinned locally;
# tests pin both the count (24) and the membership.  Future operator
# review batches should grow this set explicitly so reviewers notice
# the cohort change.
_EXCLUDED_EVENT_IDS: frozenset[int] = frozenset({
    4, 6, 8, 9,
    46, 47, 49, 51,
    60, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
})


# Universal benchmark proxy used by the readiness report's
# ``benchmark_proxy_available`` check.  Every fully-ready event has
# cache for this ticker, so it's the implicit current_benchmark for
# every candidate the contamination report surfaces.
_UNIVERSAL_BENCHMARK: str = "SPY"


# Column order — pinned in tests; do not reorder.
_PACKET_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_benchmark",
    "flags",
    "repair_priority",
    "reason",
    "proposed_mechanism_family",
    "mechanism_rationale",
    "exclude_reason",
)


_REQUIRED_FLAG: str = "mechanism_family_none"
_DISQUALIFYING_FLAGS: frozenset[str] = frozenset({
    "local_off_topic_headline",
    "driv_lit_off_topic",
})
_LOW_RISK_EXTRA_FLAG: str = "duplicate_date_ticker"


_PLAUSIBLE_HEADLINE_MIN_CHARS: int = 20


# Reason strings — short tokens kept conservative; banned words
# (delete, auto-correct, automatic, assign, fix the, replace,
# correct) avoided by construction.
_REASON_ONLY_FAMILY_GAP = (
    "Manual review candidate — only mechanism_family is missing; "
    "ticker and price-cache readiness already in place."
)
_REASON_FAMILY_GAP_WITH_DUP = (
    "Manual review candidate — mechanism_family missing alongside a "
    "duplicate (event_date, primary_ticker) signal that warrants a "
    "second look before joining the cohort."
)


_RECOMMENDED_EMPTY = (
    "No mechanism-family-only manual review candidates in this "
    "slice.  This is not proof that no repairable rows exist — "
    "expanding the upstream contamination cohort may surface more."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} manual review candidate(s) surfaced — events that already "
    "have a primary ticker, an event_date, and price-cache "
    "readiness, blocked only by a missing mechanism_family label.  "
    "These rows are manual review candidates, not proof of "
    "repairability; an operator must inspect each headline and "
    "supply the mechanism family by hand."
)


# Repair-priority sort weights.  Lower number = higher priority in
# ``sort(key=...)`` ascending.
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the topical ticker-contamination report with an
    effectively unlimited per-row cap and return the parsed payload.

    Tests patch this attribute directly so the import only resolves
    on the un-patched path.
    """
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(
        db_path=db_path, limit=_CONTAMINATION_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_mechanism_family_repair_packet(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the mechanism-family-only repair packet payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    contamination = _safe_dict(_run_contamination_report(db_path=db_path))
    raw_examples = contamination.get("examples")
    if not isinstance(raw_examples, list):
        raw_examples = []

    eligible: list[dict[str, Any]] = []
    excluded_reviewed_count = 0

    for example in raw_examples:
        if not isinstance(example, dict):
            continue
        ev_id = example.get("event_id")
        if not isinstance(ev_id, int):
            continue

        flags_raw = example.get("flags")
        flags = [
            f for f in flags_raw if isinstance(f, str)
        ] if isinstance(flags_raw, list) else []

        if not _passes_mechanism_family_filter(flags):
            continue

        # Mechanism-family filter passes; only NOW does the reviewed
        # exclusion drop count get incremented — we want the count to
        # reflect "rows that would have been candidates if not already
        # reviewed," not "every reviewed event in the contamination
        # report."
        if ev_id in _EXCLUDED_EVENT_IDS:
            excluded_reviewed_count += 1
            continue

        priority = _classify_repair_priority(flags, example.get("headline"))
        reason = _build_reason(flags)

        eligible.append({
            "event_id":                  ev_id,
            "headline":                  example.get("headline"),
            "event_date":                example.get("event_date"),
            "current_primary_ticker":    example.get("primary_ticker"),
            "current_benchmark":         _UNIVERSAL_BENCHMARK,
            "flags":                     flags,
            "repair_priority":           priority,
            "reason":                    reason,
            "proposed_mechanism_family": "",
            "mechanism_rationale":       "",
            "exclude_reason":            "",
        })

    eligible.sort(key=lambda c: (
        _PRIORITY_RANK.get(c["repair_priority"], 99),
        c["event_id"],
    ))

    total_after_filter = len(eligible)
    truncated = eligible[:capped_limit]

    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   sorted(_EXCLUDED_EVENT_IDS),
        "reviewed_exclusion_set_count":  len(_EXCLUDED_EVENT_IDS),
        "excluded_reviewed_count":       excluded_reviewed_count,
        "total_candidates_after_filter": total_after_filter,
        "candidates":                    truncated,
        "recommended_next_action":       _recommend(total_after_filter),
    }


def _passes_mechanism_family_filter(flags: list[str]) -> bool:
    """Return True iff the row carries ``mechanism_family_none`` and
    no disqualifying off-topic flag.  ``duplicate_date_ticker`` is the
    only allowed extra; any other flag (defensive future-proofing) is
    treated as disqualifying so the packet stays mechanism-family-only.
    """
    flag_set = set(flags)
    if _REQUIRED_FLAG not in flag_set:
        return False
    if flag_set & _DISQUALIFYING_FLAGS:
        return False
    extra = flag_set - {_REQUIRED_FLAG, _LOW_RISK_EXTRA_FLAG}
    if extra:
        return False
    return True


def _classify_repair_priority(
    flags: list[str], headline: Any,
) -> str:
    """Assign a coarse triage tier:

      * ``"high"``   — only ``mechanism_family_none``, with a plausible
                       headline (>= ``_PLAUSIBLE_HEADLINE_MIN_CHARS``
                       chars).  Cleanest path: operator just supplies a
                       family label.
      * ``"medium"`` — only ``mechanism_family_none``, but headline is
                       short or missing — operator may need extra
                       context before labelling.
      * ``"low"``    — ``mechanism_family_none`` plus
                       ``duplicate_date_ticker``.  Worth surfacing but
                       deserves a second look.
    """
    flag_set = set(flags)
    if _LOW_RISK_EXTRA_FLAG in flag_set:
        return "low"
    if (
        isinstance(headline, str)
        and len(headline.strip()) >= _PLAUSIBLE_HEADLINE_MIN_CHARS
    ):
        return "high"
    return "medium"


def _build_reason(flags: list[str]) -> str:
    if _LOW_RISK_EXTRA_FLAG in set(flags):
        return _REASON_FAMILY_GAP_WITH_DUP
    return _REASON_ONLY_FAMILY_GAP


def _recommend(total_after_filter: int) -> str:
    if total_after_filter <= 0:
        return _RECOMMENDED_EMPTY
    return _RECOMMENDED_HAS_CANDIDATES.format(n=total_after_filter)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _csv_cell(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key == "flags":
        if isinstance(value, list):
            return "|".join(v for v in value if isinstance(v, str))
        return ""
    return str(value)


def _render_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    # ``lineterminator='\n'`` avoids the default ``\r\n`` so the file
    # doesn't carry Windows-style CRLF line endings on this platform.
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_PACKET_COLUMNS)
    for entry in report.get("candidates") or []:
        writer.writerow([_csv_cell(k, entry.get(k)) for k in _PACKET_COLUMNS])
    return buf.getvalue()


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Mechanism-family-only repair packet", ""]
    lines.append(
        f"Reviewed exclusion set count:    "
        f"{report['reviewed_exclusion_set_count']}"
    )
    lines.append(
        f"Excluded reviewed in this slice: "
        f"{report['excluded_reviewed_count']}"
    )
    lines.append(
        f"Candidates after filter:         "
        f"{report['total_candidates_after_filter']}"
    )
    lines.append("")
    candidates = report.get("candidates") or []
    lines.append(f"Candidates listed ({len(candidates)}):")
    if candidates:
        for entry in candidates:
            flags_str = "|".join(entry.get("flags") or []) or "-"
            headline = entry.get("headline") or "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('current_primary_ticker') or '-'} "
                f"benchmark={entry.get('current_benchmark')} "
                f"priority={entry.get('repair_priority')}"
            )
            lines.append(f"      flags: {flags_str}")
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
            "Read-only mechanism-family-only repair packet builder.  "
            "Wraps the topical ticker-contamination report and surfaces "
            "fully-ready events blocked only by a missing "
            "mechanism_family label.  Drops 24 already-reviewed "
            "event_ids before ranking.  Read-only: never assigns "
            "mechanism families, never edits the archive, no provider, "
            "no LLM, no FastAPI surface."
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
            "Emit a CSV worksheet with the 11 packet columns.  "
            "``flags`` is pipe-separated; rows terminate with \\n."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced candidates list at N entries (default "
            f"{_DEFAULT_LIMIT}).  ``total_candidates_after_filter`` "
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

    report = summarize_mechanism_family_repair_packet(
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

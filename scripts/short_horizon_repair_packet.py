#!/usr/bin/env python3
"""Read-only short-horizon repair packet builder.

Surfaces 1d/5d-ready events that are not yet manually reviewed and
that could expand a clean short-horizon repaired cohort once an
operator supplies a primary ticker / mechanism family by hand.

Wraps two upstream reports through patchable seams so unit tests can
drive the packet with synthetic payloads (no DB access on the test
path):

  * ``_run_short_horizon_readiness_report`` — pulls the short-horizon
    (1d/5d) readiness coverage report.  Used here for cohort context
    only (``total_short_ready``, ``delta_vs_full_ready``); the
    candidate list itself is sourced from the contamination report
    below.
  * ``_run_short_horizon_contamination_report`` — pulls the topical
    contamination report scoped to the short-horizon-ready cohort.
    By construction every example surfaced is short-horizon-ready
    AND carries at least one heuristic flag, which is the exact
    "needs repair" signal this packet wants.

Twenty-four already-reviewed event_ids (:data:`_EXCLUDED_EVENT_IDS`)
are dropped before ranking — the same set pinned by the prior manual
review batch.  Tests pin both the count (24) and membership.

Each surfaced row is classified by:

  * ``repair_type`` — coarse repair-path tag derived from the flag
    set (``ticker_off_topic``, ``mechanism_family_only``,
    ``ticker_and_family``, ``duplicate_only``, ``needs_review``).
  * ``repair_priority`` — triage tier (``high`` | ``medium`` |
    ``low``) derived from the flag combo and headline plausibility.

Four operator-input columns (``proposed_primary_ticker``,
``proposed_mechanism_family``, ``rationale``, ``exclude_reason``)
are emitted as blank strings.  The packet does NOT propose
replacement tickers, does NOT label mechanism families, and never
edits the archive.

Output contract (JSON)::

    {
      "ok":                              bool,
      "excluded_reviewed_event_ids":     list[int],   # sorted ascending
      "reviewed_exclusion_set_count":    int,         # = 24
      "excluded_reviewed_count":         int,         # in-packet drop count
      "total_short_ready":               int,         # from readiness
      "delta_vs_full_ready":             int,         # from readiness
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
          "flags":                      list[str],
          "repair_type":                str,
          "repair_priority":            "high" | "medium" | "low",
          "proposed_primary_ticker":    "",
          "proposed_mechanism_family":  "",
          "rationale":                  "",
          "exclude_reason":             "",
        },
        ...
      ],
      "export_summary": {              # quote-friendly subset of the
                                       # post-limit candidates list,
                                       # surfacing exactly what an
                                       # operator needs to triage by
                                       # eye (headline, ticker, date,
                                       # repair_type, repair_priority).
                                       # Decoupled from the full
                                       # per-row schema so review
                                       # tooling can stay stable as
                                       # the per-row contract grows.
        "candidate_count":              int,    # = len(candidates)
        "reviewed_exclusion_set_count": int,    # = 24
        "top_candidates": [                     # same order as ``candidates``
          {
            "event_id":               int,
            "headline":               str | None,
            "event_date":             str | None,
            "current_primary_ticker": str | None,
            "repair_type":            str,
            "repair_priority":        "high" | "medium" | "low",
          },
          ...
        ],
      },
      "recommended_next_action":         str,
    }

CSV output uses the same 11 column names as the JSON per-row keys,
in the same order.  ``flags`` is pipe-separated (``a|b``) inside a
single column.  Lines terminate with ``\n`` (no Windows CRLF).

Out of scope (deliberately)
---------------------------
* Read-only.  All DB reads flow through the upstream reports' SELECT-
  only paths.  No INSERT / UPDATE / DELETE.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or proposes replacement tickers / mechanism families;
  surfaced rows are manual review candidates, not proof of
  repairability.

Usage::

    python scripts/short_horizon_repair_packet.py
    python scripts/short_horizon_repair_packet.py --json --limit 50
    python scripts/short_horizon_repair_packet.py --csv  --limit 50
    python scripts/short_horizon_repair_packet.py --json --db-path ./events.db
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
# reports — we need every short-horizon-ready row (and every flagged
# row) so the operator's ``--limit`` only truncates the emitted
# candidates list, not the underlying cohort.
_SHORT_HORIZON_FETCH_ALL: int = 10**12


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


# Column order — pinned in tests; do not reorder.
_PACKET_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "flags",
    "repair_type",
    "repair_priority",
    "proposed_primary_ticker",
    "proposed_mechanism_family",
    "rationale",
    "exclude_reason",
)


_BLANK_OPERATOR_FIELDS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_mechanism_family",
    "rationale",
    "exclude_reason",
)


# Heuristic flag tokens (mirroring the upstream contamination report).
_FLAG_DRIV:    str = "driv_lit_off_topic"
_FLAG_LOCAL:   str = "local_off_topic_headline"
_FLAG_FAMILY:  str = "mechanism_family_none"
_FLAG_DUP:     str = "duplicate_date_ticker"

_OFF_TOPIC_FLAGS: frozenset[str] = frozenset({_FLAG_DRIV, _FLAG_LOCAL})


_PLAUSIBLE_HEADLINE_MIN_CHARS: int = 20


# Repair-priority sort weights.  Lower number = higher priority in
# ``sort(key=...)`` ascending.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


_RECOMMENDED_EMPTY = (
    "No 1d/5d-ready manual review candidates surfaced in this slice.  "
    "This is not proof that no repairable rows exist — refreshing the "
    "price cache or expanding the upstream short-horizon contamination "
    "cohort may surface more."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} manual review candidate(s) surfaced — short-horizon (1d/5d) "
    "ready events blocked from a clean repaired cohort by topical "
    "contamination signals.  These rows are manual review candidates, "
    "not proof of repairability; an operator must inspect each headline "
    "and supply the primary ticker / mechanism family by hand."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_short_horizon_readiness_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon readiness report with an effectively
    unlimited per-event cap and return the parsed payload.

    Tests patch this attribute directly so the import only resolves on
    the un-patched path.
    """
    from scripts.stat_validation_short_horizon_readiness_report import (
        summarize_short_horizon_readiness,
    )

    return summarize_short_horizon_readiness(
        db_path=db_path, limit=_SHORT_HORIZON_FETCH_ALL,
    )


def _run_short_horizon_contamination_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon topical contamination report with an
    effectively unlimited per-event cap and return the parsed payload.

    Tests patch this attribute directly so the import only resolves on
    the un-patched path.
    """
    from scripts.stat_validation_short_horizon_contamination_report import (
        summarize_short_horizon_contamination,
    )

    return summarize_short_horizon_contamination(
        db_path=db_path, limit=_SHORT_HORIZON_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_short_horizon_repair_packet(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the short-horizon repair packet payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    readiness = _safe_dict(
        _run_short_horizon_readiness_report(db_path=db_path),
    )
    contamination = _safe_dict(
        _run_short_horizon_contamination_report(db_path=db_path),
    )

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
        if not flags:
            # Defensive: contamination examples are flagged by
            # construction.  If a future refactor surfaces non-flagged
            # rows here, treat them as out of scope — this packet only
            # surfaces rows that need repair.
            continue

        if ev_id in _EXCLUDED_EVENT_IDS:
            excluded_reviewed_count += 1
            continue

        repair_type = _classify_repair_type(flags)
        repair_priority = _classify_repair_priority(
            flags, example.get("headline"),
        )

        eligible.append({
            "event_id":                  ev_id,
            "headline":                  example.get("headline"),
            "event_date":                example.get("event_date"),
            "current_primary_ticker":    example.get("primary_ticker"),
            "flags":                     flags,
            "repair_type":               repair_type,
            "repair_priority":           repair_priority,
            "proposed_primary_ticker":   "",
            "proposed_mechanism_family": "",
            "rationale":                 "",
            "exclude_reason":            "",
        })

    eligible.sort(key=lambda c: (
        _PRIORITY_RANK.get(c["repair_priority"], 99),
        c["event_id"],
    ))

    total_after_filter = len(eligible)
    truncated = eligible[:capped_limit]

    export_summary = {
        "candidate_count":              len(truncated),
        "reviewed_exclusion_set_count": len(_EXCLUDED_EVENT_IDS),
        "top_candidates": [
            {
                "event_id":               c["event_id"],
                "headline":               c["headline"],
                "event_date":             c["event_date"],
                "current_primary_ticker": c["current_primary_ticker"],
                "repair_type":            c["repair_type"],
                "repair_priority":        c["repair_priority"],
            }
            for c in truncated
        ],
    }

    total_short_ready = _coerce_int(readiness.get("events_ready_1d5d"))
    if total_short_ready is None:
        total_short_ready = _coerce_int(contamination.get("total_short_ready"))
    if total_short_ready is None:
        total_short_ready = 0

    delta_vs_full_ready = _coerce_int(readiness.get("delta_vs_full_ready"))
    if delta_vs_full_ready is None:
        delta_vs_full_ready = 0

    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   sorted(_EXCLUDED_EVENT_IDS),
        "reviewed_exclusion_set_count":  len(_EXCLUDED_EVENT_IDS),
        "excluded_reviewed_count":       excluded_reviewed_count,
        "total_short_ready":             total_short_ready,
        "delta_vs_full_ready":           delta_vs_full_ready,
        "total_candidates_after_filter": total_after_filter,
        "candidates":                    truncated,
        "export_summary":                export_summary,
        "recommended_next_action":       _recommend(total_after_filter),
    }


def _classify_repair_type(flags: list[str]) -> str:
    """Map the flag set to a coarse repair-path tag.

    Order of precedence:

      * Off-topic + ``mechanism_family_none``  → ``ticker_and_family``
      * Off-topic alone                        → ``ticker_off_topic``
      * ``mechanism_family_none`` alone        → ``mechanism_family_only``
      * ``duplicate_date_ticker`` alone        → ``duplicate_only``
      * Anything else                          → ``needs_review``
    """
    flag_set = set(flags)
    has_off_topic = bool(flag_set & _OFF_TOPIC_FLAGS)
    has_family = _FLAG_FAMILY in flag_set
    has_dup_only = flag_set == {_FLAG_DUP}

    if has_off_topic and has_family:
        return "ticker_and_family"
    if has_off_topic:
        return "ticker_off_topic"
    if has_family:
        return "mechanism_family_only"
    if has_dup_only:
        return "duplicate_only"
    return "needs_review"


def _classify_repair_priority(
    flags: list[str], headline: Any,
) -> str:
    """Assign a coarse triage tier (``high`` / ``medium`` / ``low``).

    Rules (first match wins):

      * ``low`` — a ``local_off_topic_headline`` is present (topic
        signal is already weak; the cleanest path is exclusion or a
        careful ticker review).
      * ``low`` — multi-fix combo: off-topic flag plus
        ``mechanism_family_none``.
      * ``low`` — ``duplicate_date_ticker`` is present (deserves a
        second look regardless of headline length).
      * ``high`` — single-flag ``mechanism_family_none`` or single-flag
        ``driv_lit_off_topic`` with a plausible headline
        (``>= _PLAUSIBLE_HEADLINE_MIN_CHARS`` chars).
      * ``medium`` — same as ``high`` but with a short or missing
        headline.
      * ``low`` — fallback for any other combo.
    """
    flag_set = set(flags)
    has_local = _FLAG_LOCAL in flag_set
    has_driv = _FLAG_DRIV in flag_set
    has_family = _FLAG_FAMILY in flag_set
    has_dup = _FLAG_DUP in flag_set

    plausible = (
        isinstance(headline, str)
        and len(headline.strip()) >= _PLAUSIBLE_HEADLINE_MIN_CHARS
    )

    if has_local:
        return "low"
    if has_dup:
        return "low"
    if has_driv and has_family:
        return "low"

    if has_family and not has_driv:
        return "high" if plausible else "medium"
    if has_driv and not has_family:
        return "high" if plausible else "medium"

    return "low"


def _recommend(total_after_filter: int) -> str:
    if total_after_filter <= 0:
        return _RECOMMENDED_EMPTY
    return _RECOMMENDED_HAS_CANDIDATES.format(n=total_after_filter)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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
    lines: list[str] = ["Short-horizon (1d/5d) repair packet", ""]
    lines.append(
        f"Reviewed exclusion set count:    "
        f"{report['reviewed_exclusion_set_count']}"
    )
    lines.append(
        f"Excluded reviewed in this slice: "
        f"{report['excluded_reviewed_count']}"
    )
    lines.append(
        f"Total short-horizon ready:       {report['total_short_ready']}"
    )
    lines.append(
        f"Delta vs. full readiness:        {report['delta_vs_full_ready']}"
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
                f"type={entry.get('repair_type')} "
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
            "Read-only short-horizon (1d/5d) repair packet builder.  "
            "Wraps the short-horizon readiness and contamination reports "
            "through patchable seams and surfaces 1d/5d-ready events "
            "that need manual review before they can join a clean "
            "short-horizon repaired cohort.  Drops 24 already-reviewed "
            "event_ids before ranking.  Read-only: never assigns "
            "tickers or mechanism families, never edits the archive, "
            "no provider, no LLM, no FastAPI surface."
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

    report = summarize_short_horizon_repair_packet(
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

#!/usr/bin/env python3
"""Read-only manual ticker repair packet builder.

Produces an operator triage packet on top of the manual ticker
repair shortlist.  Each row is enriched with:

* The event's ``event_date`` (SELECT-only lookup against the
  events archive — the upstream shortlist does not surface it).
* An estimated ``fast_to_clean_score`` in ``[0, 10]`` plus a
  ``fast_to_clean_reason`` token list summarising which signals
  drove the score.
* Five blank operator-input columns (``proposed_primary_ticker``,
  ``proposed_benchmark``, ``proposed_mechanism_family``,
  ``ticker_rationale``, ``exclude_reason``) for hand review.

Default behavior surfaces ``--priority medium`` candidates ranked
by ``fast_to_clean_score`` descending — the medium bucket is the
deepest pool of potentially recoverable rows; the score points the
operator at the highest-leverage candidates first (events with an
``event_date``, a plausible headline, and a clear mechanism /
ticker repair path).  Local off-topic headlines, duplicate-date
collisions, and ``mechanism_family_none``-only rows are
deprioritised.  Operators can switch with ``--priority high`` /
``low`` / ``all``.

This is a triage worksheet builder.  It does NOT propose
replacement tickers, does NOT touch the archive, and never calls a
provider, an LLM, ``yfinance``, or any FastAPI surface.  Every
ticker / benchmark / mechanism family / rationale / exclusion
column is a blank string — those columns are placeholders for the
operator to fill in by hand.

Output contract (JSON)::

    {
      "ok":                          bool,
      "priority_filter":             "high" | "medium" | "low" | "all",
      "total_candidates_in_filter":  int,
      "candidates": [                # capped at --limit, sorted by
                                     # (-fast_to_clean_score,
                                     #  event_id) ascending
        {
          "event_id":                int,
          "headline":                str | None,
          "event_date":              str | None,
          "current_primary_ticker":  str | None,
          "flags":                   list[str],
          "reason":                  str,
          "manual_review_priority":  "high" | "medium" | "low",
          "fast_to_clean_score":     int,           # in [0, 10]
          "fast_to_clean_reason":    str,           # pipe-joined tokens
          "proposed_primary_ticker": "",
          "proposed_benchmark":      "",
          "proposed_mechanism_family": "",
          "ticker_rationale":        "",
          "exclude_reason":          "",
        },
        ...
      ],
      "export_summary": {            # quote-friendly subset of the
                                     # post-limit candidates list — keep
                                     # the operator review summary
                                     # stable and decoupled from the
                                     # full per-row schema.
        "candidate_count":                  int,    # = len(candidates)
        "rows_filtered_from_review_packet": int,    # mirrored
        "top_candidates": [                         # same order as
                                                    # ``candidates``
          {"event_id": int, "headline": str | None},
          ...
        ],
      },
      "recommended_next_action":     str,
    }

CSV output uses the same 14 column names as the JSON per-row keys,
in the same order.  ``flags`` is pipe-separated (``a|b``) inside a
single column.  Lines terminate with ``\n`` (no Windows CRLF).
``total_candidates_in_filter`` reflects how many shortlist rows
match the chosen priority filter; ``--limit`` truncates only the
emitted candidates list.

Patchable seams
---------------

  * ``_run_repair_shortlist`` — wraps
    :func:`scripts.manual_ticker_repair_shortlist.summarize_repair_shortlist`
    with an effectively unlimited per-event cap.
  * ``_fetch_event_dates`` — SELECT-only ``event_date`` lookup
    keyed by event_id.  Issued AFTER the priority filter so we
    don't read event_date for candidates we'll discard.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or proposes replacement tickers; the packet only
  surfaces rows for a human to review.

Usage::

    python scripts/manual_ticker_repair_packet.py
    python scripts/manual_ticker_repair_packet.py --json --priority high --limit 20
    python scripts/manual_ticker_repair_packet.py --csv --priority high --limit 20
    python scripts/manual_ticker_repair_packet.py --json --priority all
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 25
_DEFAULT_PRIORITY: str = "medium"

# Effectively unlimited per-event cap when delegating to the upstream
# shortlist.  We need every shortlisted row in the archive to apply
# the priority filter and aggregate counts correctly — operator
# ``--limit`` only truncates the emitted candidates list.
_SHORTLIST_FETCH_ALL: int = 10**12

_VALID_PRIORITIES: tuple[str, ...] = ("high", "medium", "low", "all")


# Column order — pinned in tests; do not reorder.
_PACKET_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "flags",
    "reason",
    "manual_review_priority",
    "fast_to_clean_score",
    "fast_to_clean_reason",
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


# Fast-to-clean scoring config.  Bonuses are applied additively to a
# fixed base; the final score is clamped to ``[0, 10]``.  The actual
# numeric values are an interpretation; tests pin signal-by-signal
# ordering (presence vs absence) rather than exact integer levels so
# the heuristic can be tuned without test churn.
_FAST_TO_CLEAN_BASE: int = 5
_FAST_TO_CLEAN_MIN:  int = 0
_FAST_TO_CLEAN_MAX:  int = 10
_PLAUSIBLE_HEADLINE_MIN_CHARS: int = 20

_FLAG_BONUS_DRIV:    int = 2
_FLAG_BONUS_MISSING: int = 2
_FLAG_PENALTY_LOCAL: int = 3
_FLAG_PENALTY_DUP:   int = 2
_FLAG_PENALTY_MECH_ONLY: int = 3

_BONUS_EVENT_DATE_PRESENT: int = 2
_PENALTY_EVENT_DATE_MISSING: int = 2
_BONUS_PLAUSIBLE_HEADLINE: int = 1
_BONUS_TICKER_LEAD: int = 1


_RECOMMENDED_EMPTY = (
    "No candidates match the chosen priority filter — manual review "
    "is not required for this slice."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} candidate(s) require manual review, ranked by estimated "
    "fast-to-clean potential.  Operator must inspect each headline "
    "and supply the primary ticker / benchmark / mechanism family / "
    "rationale by hand."
)
_RECOMMENDED_HAS_CANDIDATES_FILTERED = (
    "{n} candidate(s) require manual review, ranked by estimated "
    "fast-to-clean potential.  {f} row(s) filtered from review packet "
    "as seed-like / template headlines.  Operator must inspect each "
    "headline and supply the primary ticker / benchmark / mechanism "
    "family / rationale by hand."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_repair_shortlist(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the manual ticker repair shortlist with an effectively
    unlimited per-row cap and return the parsed payload.  Tests patch
    this attribute directly so the import only resolves on the
    un-patched path.
    """
    from scripts.manual_ticker_repair_shortlist import (
        summarize_repair_shortlist,
    )

    return summarize_repair_shortlist(
        db_path=db_path, limit=_SHORTLIST_FETCH_ALL,
    )


def _get_seed_like_phrases() -> tuple[str, ...]:
    """Return the canonical seed-/template-headline pattern list.

    Re-exports the lowercase substring patterns owned by
    :mod:`scripts.archive_cleanup_candidate_report` so the
    ``--production-like-only`` filter stays aligned with the cleanup
    report's signal.  Tests patch this seam directly so unit coverage
    doesn't depend on the canonical list contents.

    Lazy import keeps the dependency off the un-patched path's import
    cost and ensures default packet runs do not pull the cleanup
    report module unless the filter is actually active (the import
    is cheap pure-stdlib Python — no DB / network — but isolating it
    documents the read-only / no-FastAPI / no-yfinance contract).
    """
    from scripts.archive_cleanup_candidate_report import (
        _ROTATING_MACRO_TEMPLATES,
        _TEST_FIXTURE_PHRASES,
    )

    combined = tuple(_TEST_FIXTURE_PHRASES) + tuple(_ROTATING_MACRO_TEMPLATES)
    return tuple(p.lower() for p in combined if isinstance(p, str))


def _fetch_event_dates(
    *, db_path: str | None, event_ids: Sequence[int],
) -> dict[int, str | None]:
    """Return ``{event_id: event_date | None}`` for the requested ids.

    Read-only SELECT against the events archive.  When ``db_path`` is
    None and the project's ``db.DB_FILE`` cannot be resolved, returns
    an empty mapping — callers degrade gracefully to ``None`` event
    dates.  Never raises on a missing or unreadable DB; tests patch
    this seam directly.
    """
    if not event_ids:
        return {}
    path = _resolve_db_path(db_path)
    if path is None:
        return {}
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return {}
    out: dict[int, str | None] = {}
    try:
        # SQLite has a per-statement variable cap (default 999).
        # Chunk the IN-list defensively so very large packets work.
        ids_list = [int(i) for i in event_ids if isinstance(i, int)]
        for i in range(0, len(ids_list), 500):
            chunk = ids_list[i : i + 500]
            placeholders = ",".join(["?"] * len(chunk))
            try:
                rows = conn.execute(
                    "SELECT id, event_date FROM events "
                    f"WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall()
            except sqlite3.Error:
                continue
            for ev_id, ev_date in rows:
                if not isinstance(ev_id, int):
                    continue
                out[ev_id] = ev_date if isinstance(ev_date, str) else None
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_repair_packet(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    priority: str = _DEFAULT_PRIORITY,
    production_like_only: bool = False,
) -> dict[str, Any]:
    """Build the manual ticker repair packet payload.

    See module docstring for the full output contract.

    When ``production_like_only`` is ``True``, rows whose headline
    matches any canonical seed-/template-headline phrase (sourced from
    :func:`_get_seed_like_phrases`) are filtered from the review
    packet before scoring.  ``rows_filtered_from_review_packet``
    reports the count removed; ``total_candidates_in_filter`` reflects
    the post-filter count.  Conservative wording: rows are described
    as "filtered from review packet," never deleted from the archive.
    """
    capped_limit = max(int(limit), 0)
    priority_filter = priority if priority in _VALID_PRIORITIES else _DEFAULT_PRIORITY

    shortlist = _safe_dict(_run_repair_shortlist(db_path=db_path))
    raw_candidates = shortlist.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    filtered = _filter_by_priority(raw_candidates, priority_filter)

    rows_filtered_from_review_packet = 0
    if production_like_only:
        seed_phrases = _get_seed_like_phrases()
        kept: list[dict[str, Any]] = []
        for c in filtered:
            if _matches_seed_phrase(c.get("headline"), seed_phrases):
                rows_filtered_from_review_packet += 1
                continue
            kept.append(c)
        filtered = kept

    total_in_filter = len(filtered)

    # Score-based sort needs ``event_date`` for every filtered row, so
    # the seam call happens BEFORE truncation.  Rows we discard by
    # priority filter (or by the production-likeness filter above) are
    # still spared the lookup.
    event_id_lookup = [
        c["event_id"] for c in filtered
        if isinstance(c.get("event_id"), int)
    ]
    event_dates = _fetch_event_dates(
        db_path=db_path, event_ids=event_id_lookup,
    )
    if not isinstance(event_dates, dict):
        event_dates = {}

    scored: list[tuple[int, int, dict[str, Any], list[str], str | None,
                       int, str]] = []
    for c in filtered:
        ev_id = c.get("event_id")
        if not isinstance(ev_id, int):
            continue
        flags_raw = c.get("flags") or []
        flags = [f for f in flags_raw if isinstance(f, str)] \
            if isinstance(flags_raw, list) else []
        ev_date = event_dates.get(ev_id)
        score, reason = _compute_fast_to_clean(
            flags=flags,
            event_date=ev_date,
            headline=c.get("headline"),
            primary_ticker=c.get("primary_ticker"),
        )
        scored.append((score, ev_id, c, flags, ev_date, score, reason))

    # Sort by ``-score`` then ``event_id`` ascending — higher-scoring
    # rows surface first, ties broken stably by id.
    scored.sort(key=lambda t: (-t[0], t[1]))
    truncated_scored = scored[:capped_limit]

    candidates: list[dict[str, Any]] = []
    for _key_score, ev_id, c, flags, ev_date, score, reason in truncated_scored:
        candidates.append({
            "event_id":                  ev_id,
            "headline":                  c.get("headline"),
            "event_date":                ev_date,
            "current_primary_ticker":    c.get("primary_ticker"),
            "flags":                     flags,
            "reason":                    c.get("reason"),
            "manual_review_priority":    c.get("manual_review_priority"),
            "fast_to_clean_score":       score,
            "fast_to_clean_reason":      reason,
            "proposed_primary_ticker":   "",
            "proposed_benchmark":        "",
            "proposed_mechanism_family": "",
            "ticker_rationale":          "",
            "exclude_reason":            "",
        })

    export_summary = {
        "candidate_count":                  len(candidates),
        "rows_filtered_from_review_packet": rows_filtered_from_review_packet,
        "top_candidates": [
            {"event_id": c["event_id"], "headline": c["headline"]}
            for c in candidates
        ],
    }

    return {
        "ok":                              True,
        "priority_filter":                 priority_filter,
        "production_like_only_active":     bool(production_like_only),
        "rows_filtered_from_review_packet": rows_filtered_from_review_packet,
        "total_candidates_in_filter":      total_in_filter,
        "candidates":                      candidates,
        "export_summary":                  export_summary,
        "recommended_next_action":         _recommend(
            total_in_filter,
            rows_filtered_from_review_packet,
        ),
    }


def _filter_by_priority(
    candidates: list[Any], priority_filter: str,
) -> list[dict[str, Any]]:
    """Keep candidates whose ``manual_review_priority`` matches the
    filter.  ``all`` keeps everything.
    """
    out: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        p = c.get("manual_review_priority")
        if priority_filter == "all":
            out.append(c)
        elif p == priority_filter:
            out.append(c)
    return out


def _matches_seed_phrase(
    headline: Any, seed_phrases: tuple[str, ...],
) -> bool:
    """Return True iff the headline contains any seed-phrase substring
    (case-insensitive).  Blank / non-string headlines never match —
    a missing headline is not seed leakage by itself; the operator
    should still see those rows.
    """
    if not isinstance(headline, str):
        return False
    text = headline.strip().lower()
    if not text:
        return False
    for phrase in seed_phrases:
        if isinstance(phrase, str) and phrase and phrase in text:
            return True
    return False


def _compute_fast_to_clean(
    *,
    flags: list[str],
    event_date: str | None,
    headline: Any,
    primary_ticker: Any,
) -> tuple[int, str]:
    """Estimate fast-to-clean potential for a single shortlist row.

    Returns ``(score, reason_tokens)`` where ``score`` is an integer in
    ``[_FAST_TO_CLEAN_MIN, _FAST_TO_CLEAN_MAX]`` and ``reason_tokens``
    is a pipe-joined list of which signals fired (e.g.
    ``has_event_date|bonus_missing_market_tickers``).  All token
    spellings are pre-screened to avoid the conservative-wording
    deny-list (no ``correct``, ``replace``, ``propose``, ``assign``,
    ``fix the``, ``automatic``, ``delete``, ``auto-correct``, ``auto
    fix``).
    """
    score = _FAST_TO_CLEAN_BASE
    tokens: list[str] = []

    if isinstance(event_date, str) and event_date.strip():
        score += _BONUS_EVENT_DATE_PRESENT
        tokens.append("has_event_date")
    else:
        score -= _PENALTY_EVENT_DATE_MISSING
        tokens.append("missing_event_date")

    if (
        isinstance(headline, str)
        and len(headline.strip()) >= _PLAUSIBLE_HEADLINE_MIN_CHARS
    ):
        score += _BONUS_PLAUSIBLE_HEADLINE
        tokens.append("plausible_headline")
    else:
        tokens.append("short_or_missing_headline")

    if isinstance(primary_ticker, str) and primary_ticker.strip():
        score += _BONUS_TICKER_LEAD
        tokens.append("has_ticker_lead")

    flag_set = {f for f in flags if isinstance(f, str)}

    if "driv_lit_off_topic" in flag_set:
        score += _FLAG_BONUS_DRIV
        tokens.append("bonus_driv_lit_off_topic")
    if "missing_market_tickers" in flag_set:
        score += _FLAG_BONUS_MISSING
        tokens.append("bonus_missing_market_tickers")
    if "local_off_topic_headline" in flag_set:
        score -= _FLAG_PENALTY_LOCAL
        tokens.append("penalty_local_off_topic_headline")
    if "duplicate_date_ticker" in flag_set:
        score -= _FLAG_PENALTY_DUP
        tokens.append("penalty_duplicate_date_ticker")

    # Penalise ``mechanism_family_none`` only when it is the SOLE flag
    # — accompanied rows still get whatever bonus the actionable flag
    # carries.  Operator can't fix a mechanism-family gap by retagging
    # a ticker, so a row whose only signal is mechanism_family_none is
    # genuinely low leverage.
    if flag_set == {"mechanism_family_none"}:
        score -= _FLAG_PENALTY_MECH_ONLY
        tokens.append("low_signal_only_flag")

    score = max(_FAST_TO_CLEAN_MIN, min(score, _FAST_TO_CLEAN_MAX))
    return score, "|".join(tokens)


def _recommend(
    total_in_filter: int,
    rows_filtered_from_review_packet: int = 0,
) -> str:
    if total_in_filter <= 0:
        return _RECOMMENDED_EMPTY
    if rows_filtered_from_review_packet > 0:
        return _RECOMMENDED_HAS_CANDIDATES_FILTERED.format(
            n=total_in_filter, f=rows_filtered_from_review_packet,
        )
    return _RECOMMENDED_HAS_CANDIDATES.format(n=total_in_filter)


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _csv_cell(key: str, value: Any) -> str:
    """Coerce a per-row value into a CSV cell string.

    ``flags`` becomes pipe-joined; ``None`` becomes empty string;
    everything else is ``str(value)``.  Operator-input fields are
    already empty strings from the compute layer.
    """
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
    lines: list[str] = ["Manual ticker repair packet", ""]
    lines.append(f"Priority filter:               {report['priority_filter']}")
    lines.append(
        f"Production-like-only filter:   "
        f"{'on' if report.get('production_like_only_active') else 'off'}"
    )
    if report.get("rows_filtered_from_review_packet", 0) > 0:
        lines.append(
            f"Rows filtered from review packet: "
            f"{report['rows_filtered_from_review_packet']}"
        )
    lines.append(
        f"Total candidates in filter:    {report['total_candidates_in_filter']}"
    )
    lines.append("")
    candidates = report.get("candidates") or []
    lines.append(f"Candidates listed ({len(candidates)}):")
    if candidates:
        for entry in candidates:
            flags_str = "|".join(entry.get("flags") or []) or "-"
            headline = entry.get("headline") or "-"
            score = entry.get("fast_to_clean_score")
            score_str = f"{score}/10" if isinstance(score, int) else "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"priority={entry.get('manual_review_priority')} "
                f"score={score_str} "
                f"reason={entry.get('reason')} "
                f"ticker={entry.get('current_primary_ticker') or '-'}"
            )
            lines.append(f"      flags: {flags_str}")
            lines.append(f"      headline: {headline[:120]}")
            f2c_reason = entry.get("fast_to_clean_reason") or "-"
            lines.append(f"      fast-to-clean: {f2c_reason}")
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
            "Read-only manual ticker repair packet builder.  Wraps "
            "the manual ticker repair shortlist and emits a per-row "
            "worksheet (JSON or CSV) with five blank operator-input "
            "columns (proposed_primary_ticker, proposed_benchmark, "
            "proposed_mechanism_family, ticker_rationale, "
            "exclude_reason).  Default surfaces --priority medium "
            "candidates ranked by an estimated fast_to_clean_score.  "
            "Read-only: never assigns tickers, never edits the "
            "archive, no provider, no LLM, no FastAPI surface."
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
            "Emit a CSV worksheet with the 14 packet columns.  "
            "``flags`` is pipe-separated; rows terminate with \\n."
        ),
    )
    parser.add_argument(
        "--priority",
        choices=list(_VALID_PRIORITIES),
        default=_DEFAULT_PRIORITY,
        help=(
            f"Priority filter.  Default {_DEFAULT_PRIORITY!r} surfaces "
            f"the medium bucket — the deepest pool of recoverable "
            f"rows, ranked by estimated fast-to-clean potential.  "
            f"``all`` includes every shortlisted row."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced candidates list at N entries (default "
            f"{_DEFAULT_LIMIT}).  ``total_candidates_in_filter`` "
            f"reflects every row matching the active filter set "
            f"(--priority and, when on, --production-like-only)."
        ),
    )
    parser.add_argument(
        "--production-like-only",
        dest="production_like_only",
        action="store_true",
        help=(
            "Filter out shortlist rows whose headline matches a "
            "canonical seed-/template-headline phrase (sourced from "
            "scripts.archive_cleanup_candidate_report — e.g. ``Macro "
            "shock test event``, ``OPEC slashes output``, ``Fed "
            "speakers rotate``, ``Tech CEO steps down``, ``Turkey "
            "lira weakens``).  Excluded rows are reported as "
            "``rows_filtered_from_review_packet`` — the rows are "
            "filtered from the review packet, not from the archive."
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

    report = summarize_repair_packet(
        db_path=args.db_path,
        limit=args.limit,
        priority=args.priority,
        production_like_only=bool(args.production_like_only),
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

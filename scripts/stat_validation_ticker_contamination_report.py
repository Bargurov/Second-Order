#!/usr/bin/env python3
"""Read-only topical ticker-contamination report for fully-ready events.

Walks the archive's *fully-ready* statistical-validation cohort (the
events that already cleared the readiness gate in
:mod:`scripts.stat_validation_readiness_report`) and applies four
heuristic flags to surface assignments that need a human eye before
they are fed into FDR-controlled aggregate claims:

  * ``driv_lit_off_topic``       — primary ticker is ``DRIV`` or
                                   ``LIT`` (auto-driving / lithium
                                   thematics) but the headline carries
                                   no auto / EV / lithium / battery /
                                   tesla keyword.  Catches the default
                                   first-beneficiary fallback the
                                   archive picks up for unrelated
                                   stories.
  * ``mechanism_family_none``    — ``mechanism_family`` is null,
                                   empty, or the literal string
                                   "none".  These rows lack a transmis-
                                   sion-channel label and cannot be
                                   pooled into a family-level claim.
  * ``duplicate_date_ticker``    — the ``(event_date, primary_ticker)``
                                   pair appears in two or more
                                   fully-ready events.  Such rows
                                   share the same event-window data
                                   and will produce identical
                                   abnormal-return numerics, which
                                   inflates the BH-FDR multiplicity
                                   without adding statistical power.
  * ``local_off_topic_headline`` — headline matches a small allow-list
                                   of local-news or non-financial
                                   topic patterns ("arrested",
                                   "collision", "Artemis", etc.).
                                   Conservative — only flags clear
                                   non-financial content.

A single fully-ready event can carry zero, one, or up to four flags.
``suspicious_count`` counts events with at least one flag (not flag
occurrences); the ``by_flag`` map carries the per-flag occurrence
counts.

The report does NOT propose replacement tickers, and never edits the
archive.  The recommended next action is always conservative —
"manual review" / "needs review" — never "delete" or "auto-correct".

Output contract::

    {
      "ok":                          bool,
      "total_fully_ready":           int,
      "suspicious_count":            int,
      "duplicate_date_ticker_count": int,
      "by_flag": {
        "driv_lit_off_topic":       int,
        "mechanism_family_none":    int,
        "duplicate_date_ticker":    int,
        "local_off_topic_headline": int,
      },
      "examples": [                  # only suspicious events, id asc,
                                     # capped at --limit
        {
          "event_id":         int,
          "event_date":       str | None,
          "primary_ticker":   str | None,
          "headline":         str | None,
          "mechanism_family": str | None,
          "flags":            list[str],   # subset of by_flag keys
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; this is a flagging tool only.

Usage::

    python scripts/stat_validation_ticker_contamination_report.py
    python scripts/stat_validation_ticker_contamination_report.py --json
    python scripts/stat_validation_ticker_contamination_report.py --json --limit 50
    python scripts/stat_validation_ticker_contamination_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25


# Effectively unlimited per-event cap when delegating to the readiness
# report — we need every fully-ready row to flag, not the readiness
# report's truncated sample.
_READINESS_FETCH_ALL: int = 10**12


# Tickers whose first-beneficiary assignment is a known fallback in
# the archive (auto-driving / lithium thematic ETFs) and so warrants
# a topical sanity check against the headline.
_THEMATIC_TICKERS: frozenset[str] = frozenset({"DRIV", "LIT"})

# Substrings that, if present in the headline (case-insensitive),
# indicate the DRIV/LIT thematic primary is plausibly on-topic.
# Conservative on purpose — false positives here mean the flag is
# silently dropped on a real off-topic row, but false negatives only
# add noise to manual review.
_AUTO_LITHIUM_KEYWORDS: tuple[str, ...] = (
    "auto", "drive", "tesla", "lithium", "battery",
    "self-driving", "autonomous", "rivian", "byd",
    "electric vehicle", "ev sales", "ev market", "evtol",
    "li-ion", "li auto", "general motors",
)

# Substrings that, if present in the headline (case-insensitive),
# indicate the row is local-news / non-financial topical content
# and therefore unlikely to carry a real market-mechanism signal.
# Kept tight on purpose to avoid flagging legitimate market stories
# that happen to share a word with this list.
_LOCAL_OFF_TOPIC_KEYWORDS: tuple[str, ...] = (
    "arrested", "murder", "pedestrian", "collision",
    "stage queens", "halfway to moon", "artemis",
    "rescue team",
)


_RECOMMENDED_NO_FULLY_READY = (
    "Archive has no fully-ready events to validate.  Seed events and "
    "refresh the price cache before running contamination checks."
)
_RECOMMENDED_OK = (
    "Every fully-ready event passes the topical heuristic checks.  "
    "No suspicious assignments to surface for manual review."
)
_RECOMMENDED_GAPS = (
    "Some fully-ready events have primary tickers that look "
    "topically suspicious.  These need manual review by a human "
    "operator before being included in any FDR-controlled claim — "
    "this report does not propose replacement tickers."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly with
# synthetic fixtures.  The lazy imports resolve only on the un-patched
# path so unit tests can swap these seams without paying the upstream
# import cost.
# ---------------------------------------------------------------------------


def _run_readiness_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the readiness report with an effectively unlimited
    per-event cap and return the parsed payload.

    Tests patch this attribute directly, so the import only resolves
    on the un-patched path.
    """
    from scripts.stat_validation_readiness_report import summarize_readiness

    return summarize_readiness(
        db_path=db_path, limit=_READINESS_FETCH_ALL,
    )


def _load_event_metadata(
    *, db_path: str | None, event_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """Return ``{event_id: {headline, mechanism_family}}`` for the
    given ids, read straight from the events table.

    Read-only — issues a single ``SELECT`` and tolerates a missing or
    unreadable DB by returning an empty dict.  Tests patch this
    attribute directly with a synthetic mapping.
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

    out: dict[int, dict[str, Any]] = {}
    try:
        try:
            placeholders = ",".join("?" * len(event_ids))
            rows = conn.execute(
                f"SELECT id, headline, mechanism_family "
                f"FROM events WHERE id IN ({placeholders})",
                list(event_ids),
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    for raw_id, raw_headline, raw_family in rows:
        try:
            ev_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        out[ev_id] = {
            "headline":         raw_headline if isinstance(raw_headline, str) else None,
            "mechanism_family": raw_family   if isinstance(raw_family,   str) else None,
        }
    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure compute over the readiness payload + metadata map
# ---------------------------------------------------------------------------


def summarize_contamination(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Apply the four heuristic flags to the fully-ready cohort.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    readiness = _run_readiness_report(db_path=db_path)
    if not isinstance(readiness, dict):
        readiness = {}

    raw_events = readiness.get("events") or []
    if not isinstance(raw_events, list):
        raw_events = []

    fully_ready: list[dict[str, Any]] = [
        e for e in raw_events
        if isinstance(e, dict) and e.get("fully_ready", False)
    ]
    total_fully_ready = len(fully_ready)

    metadata = _load_event_metadata(
        db_path=db_path,
        event_ids=[
            int(e["event_id"]) for e in fully_ready
            if isinstance(e.get("event_id"), int)
        ],
    )
    if not isinstance(metadata, dict):
        metadata = {}

    # ---- duplicate (event_date, primary_ticker) detection ---------------
    pair_counts: Counter[tuple[str, str]] = Counter()
    for e in fully_ready:
        pair = _date_ticker_pair(e)
        if pair is not None:
            pair_counts[pair] += 1
    duplicate_pairs: set[tuple[str, str]] = {
        pair for pair, n in pair_counts.items() if n >= 2
    }

    # ---- per-event flag application -------------------------------------
    enriched: list[dict[str, Any]] = []
    for e in fully_ready:
        ev_id          = e.get("event_id")
        event_date     = e.get("event_date")
        primary_ticker = e.get("primary_ticker")

        meta = metadata.get(ev_id) if isinstance(ev_id, int) else None
        if not isinstance(meta, dict):
            meta = {}
        headline         = meta.get("headline")
        mechanism_family = meta.get("mechanism_family")

        flags: list[str] = []
        if _is_driv_lit_off_topic(primary_ticker, headline):
            flags.append("driv_lit_off_topic")
        if _is_mechanism_family_none(mechanism_family):
            flags.append("mechanism_family_none")
        pair = _date_ticker_pair(e)
        if pair is not None and pair in duplicate_pairs:
            flags.append("duplicate_date_ticker")
        if _is_local_off_topic_headline(headline):
            flags.append("local_off_topic_headline")

        enriched.append({
            "event_id":         ev_id,
            "event_date":       event_date,
            "primary_ticker":   primary_ticker,
            "headline":         headline,
            "mechanism_family": mechanism_family,
            "flags":            flags,
        })

    # ---- aggregates ----------------------------------------------------
    by_flag = {
        "driv_lit_off_topic":      sum(1 for e in enriched if "driv_lit_off_topic"      in e["flags"]),
        "mechanism_family_none":   sum(1 for e in enriched if "mechanism_family_none"   in e["flags"]),
        "duplicate_date_ticker":   sum(1 for e in enriched if "duplicate_date_ticker"   in e["flags"]),
        "local_off_topic_headline":sum(1 for e in enriched if "local_off_topic_headline"in e["flags"]),
    }
    suspicious = [e for e in enriched if e["flags"]]
    suspicious_sorted = sorted(
        suspicious,
        key=lambda e: (e["event_id"] if isinstance(e["event_id"], int) else 0),
    )

    return {
        "ok":                          True,
        "total_fully_ready":           total_fully_ready,
        "suspicious_count":            len(suspicious),
        "duplicate_date_ticker_count": by_flag["duplicate_date_ticker"],
        "by_flag":                     by_flag,
        "examples":                    suspicious_sorted[:capped_limit],
        "recommended_next_action":
            _recommend(total_fully_ready, len(suspicious)),
    }


def _date_ticker_pair(event: dict[str, Any]) -> tuple[str, str] | None:
    """Return the ``(event_date, primary_ticker)`` pair for duplicate
    detection, or ``None`` when either component is missing.

    Ticker is upper-cased to match the price_cache convention; date is
    used verbatim (the readiness report already normalises empty
    strings to ``None``).
    """
    date_val = event.get("event_date")
    ticker   = event.get("primary_ticker")
    if not isinstance(date_val, str) or not date_val:
        return None
    if not isinstance(ticker, str) or not ticker:
        return None
    return (date_val, ticker.strip().upper())


# ---------------------------------------------------------------------------
# Pure heuristic helpers — small, isolated, unit-testable on their own.
# ---------------------------------------------------------------------------


def _is_driv_lit_off_topic(
    primary_ticker: Any, headline: Any,
) -> bool:
    """True iff the primary ticker is DRIV or LIT and the headline has
    no auto / EV / lithium / battery / tesla keyword.

    Returns ``False`` when the headline is missing — a None or empty
    headline cannot be judged off-topic, so this flag conservatively
    abstains rather than firing on partial data.
    """
    if not isinstance(primary_ticker, str):
        return False
    tk = primary_ticker.strip().upper()
    if tk not in _THEMATIC_TICKERS:
        return False
    if not isinstance(headline, str) or not headline:
        return False
    lowered = headline.lower()
    return not any(kw in lowered for kw in _AUTO_LITHIUM_KEYWORDS)


def _is_local_off_topic_headline(headline: Any) -> bool:
    """True iff the headline matches a local-news / off-topic pattern.

    Returns ``False`` for missing / empty / non-string headlines —
    we cannot judge content we do not have.
    """
    if not isinstance(headline, str) or not headline:
        return False
    lowered = headline.lower()
    return any(kw in lowered for kw in _LOCAL_OFF_TOPIC_KEYWORDS)


def _is_mechanism_family_none(value: Any) -> bool:
    """True iff ``value`` is null, empty, or the literal "none".

    The archive stores the literal string ``"none"`` for unclassified
    events (see ``archive_stat_validation_run.by_mechanism_family``);
    treat null, "", whitespace, and "none" as equivalent.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in ("", "none")


def _recommend(total_fully_ready: int, suspicious_count: int) -> str:
    if total_fully_ready <= 0:
        return _RECOMMENDED_NO_FULLY_READY
    if suspicious_count == 0:
        return _RECOMMENDED_OK
    return _RECOMMENDED_GAPS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Topical ticker-contamination report (fully-ready)", ""]
    lines.append(f"Total fully-ready events:       {report['total_fully_ready']}")
    lines.append(f"  suspicious (>=1 flag):        {report['suspicious_count']}")
    lines.append(f"  duplicate (date,ticker) rows: {report['duplicate_date_ticker_count']}")
    lines.append("")
    lines.append("Flag occurrences:")
    for k, v in report.get("by_flag", {}).items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    examples = report.get("examples") or []
    lines.append(f"Suspicious examples listed ({len(examples)}):")
    if examples:
        for entry in examples:
            flags = ",".join(entry.get("flags") or []) or "-"
            headline = entry.get("headline") or "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"family={entry.get('mechanism_family') or '-'}"
            )
            lines.append(f"      flags: {flags}")
            lines.append(f"      headline: {headline[:120]}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only topical ticker-contamination report for the "
            "fully-ready statistical-validation cohort.  Flags "
            "DRIV/LIT-style suspicious assignments, mechanism_family "
            "none, duplicate (event_date, primary_ticker) rows, and "
            "local/off-topic headlines.  Read-only: never assigns "
            "tickers, never deletes or edits archive rows, no "
            "provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced examples list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every fully-ready event."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
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

    report = summarize_contamination(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

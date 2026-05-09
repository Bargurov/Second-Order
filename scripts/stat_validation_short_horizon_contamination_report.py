#!/usr/bin/env python3
"""Read-only topical contamination report for the short-horizon cohort.

Sibling of :mod:`scripts.stat_validation_ticker_contamination_report`.
Where that report walks the *fully-ready* cohort (events that clear
the full readiness gate, including the 20d horizon), this report
walks the *short-horizon-ready* cohort surfaced by
:mod:`scripts.stat_validation_short_horizon_readiness_report` — i.e.
events with 1d and 5d forward cache for the primary ticker, SPY at
+5bd, and a sufficient estimation window.

The motivation is sequencing: short-horizon (1d/5d) results land
earlier than 20d results, so the temptation is to publish them
ahead of the full-cohort claim.  Before that happens, every
contamination heuristic the full-cohort report applies should also
be applied here — otherwise we risk treating short-horizon results
as evidence on rows whose primary ticker is a DRIV/LIT fallback,
whose ``mechanism_family`` is ``"none"``, or whose
``(event_date, primary_ticker)`` pair is duplicated.

Same four heuristic flags as the full-cohort report:

  * ``driv_lit_off_topic``       — primary ticker is ``DRIV`` / ``LIT``
                                   but the headline carries no
                                   auto / EV / lithium / battery /
                                   tesla keyword.
  * ``mechanism_family_none``    — ``mechanism_family`` is null,
                                   empty, or the literal "none".
  * ``duplicate_date_ticker``    — the ``(event_date, primary_ticker)``
                                   pair appears in two or more
                                   short-horizon-ready events.
  * ``local_off_topic_headline`` — headline matches a small allow-list
                                   of local-news / non-financial
                                   topic patterns.

The flag heuristics + metadata loader are imported from the
fully-ready contamination report so the two reports stay aligned by
construction; only the readiness-source seam differs.

A single short-horizon-ready event can carry zero, one, or up to
four flags.  ``suspicious_count`` counts events with at least one
flag (not flag occurrences); ``clean_short_ready_count`` is the
complement (``total_short_ready - suspicious_count``); the
``by_flag`` map carries the per-flag occurrence counts.

The report does NOT propose replacement tickers, and never edits
the archive.  The recommended next action is always conservative —
"manual review" / "needs review" — never "delete" or "auto-correct".

Output contract::

    {
      "ok":                          bool,
      "total_short_ready":           int,
      "suspicious_count":            int,
      "clean_short_ready_count":     int,
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
* Read-only.  Issues only ``SELECT`` statements via the metadata
  loader; never INSERT / UPDATE / DELETE; never calls
  ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; this is a flagging tool only.

Usage::

    python scripts/stat_validation_short_horizon_contamination_report.py
    python scripts/stat_validation_short_horizon_contamination_report.py --json
    python scripts/stat_validation_short_horizon_contamination_report.py --json --limit 80
    python scripts/stat_validation_short_horizon_contamination_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Reuse pure heuristic helpers + the metadata loader from the
# fully-ready contamination report.  Importing the module-level names
# here means tests can ``patch.object(cli, "_load_event_metadata", ...)``
# on THIS module to swap the loader without affecting the sibling
# report.  The heuristic helpers are pure functions and need no
# patching; they're aliased in for clarity at the call site.
from scripts.stat_validation_ticker_contamination_report import (  # noqa: E402
    _date_ticker_pair,
    _is_driv_lit_off_topic,
    _is_local_off_topic_headline,
    _is_mechanism_family_none,
    _load_event_metadata,
)


_DEFAULT_LIMIT = 25

# Effectively unlimited per-event cap when delegating to the
# short-horizon readiness report — we need every short-horizon-ready
# row to flag, not the readiness report's truncated sample.
_READINESS_FETCH_ALL: int = 10**12


_RECOMMENDED_NO_SHORT_READY = (
    "Archive has no short-horizon (1d/5d) ready events to validate.  "
    "Refresh the price cache for primary tickers + SPY at +5bd and "
    "re-run the short-horizon readiness report before applying "
    "contamination checks."
)
_RECOMMENDED_OK = (
    "Every short-horizon-ready event passes the topical heuristic "
    "checks.  No suspicious assignments to surface for manual review "
    "before treating short-horizon results as evidence."
)
_RECOMMENDED_GAPS = (
    "Some short-horizon-ready events have primary tickers that look "
    "topically suspicious.  These need manual review by a human "
    "operator before short-horizon results are treated as evidence — "
    "this report does not propose replacement tickers."
)


# ---------------------------------------------------------------------------
# Lazy seam — module-level so tests can patch with synthetic fixtures.
# Lazy imports resolve only on the un-patched path so unit tests can
# swap this seam without paying the upstream import cost.
# ---------------------------------------------------------------------------


def _run_short_horizon_readiness_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon readiness report with an effectively
    unlimited per-event cap and return the parsed payload.

    Tests patch this attribute directly, so the import only resolves
    on the un-patched path.
    """
    from scripts.stat_validation_short_horizon_readiness_report import (
        summarize_short_horizon_readiness,
    )

    return summarize_short_horizon_readiness(
        db_path=db_path, limit=_READINESS_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute over the short-horizon readiness payload + metadata map
# ---------------------------------------------------------------------------


def summarize_short_horizon_contamination(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Apply the four heuristic flags to the short-horizon-ready cohort.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    readiness = _run_short_horizon_readiness_report(db_path=db_path)
    if not isinstance(readiness, dict):
        readiness = {}

    # The short-horizon readiness report puts the per-event list under
    # ``examples`` (not ``events`` like the full readiness report); the
    # caller above passes _READINESS_FETCH_ALL as the limit so every
    # event lands in that list.
    raw_events = readiness.get("examples") or []
    if not isinstance(raw_events, list):
        raw_events = []

    short_ready: list[dict[str, Any]] = [
        e for e in raw_events
        if isinstance(e, dict) and e.get("ready_1d5d", False)
    ]
    total_short_ready = len(short_ready)

    metadata = _load_event_metadata(
        db_path=db_path,
        event_ids=[
            int(e["event_id"]) for e in short_ready
            if isinstance(e.get("event_id"), int)
        ],
    )
    if not isinstance(metadata, dict):
        metadata = {}

    # ---- duplicate (event_date, primary_ticker) detection ---------------
    pair_counts: Counter[tuple[str, str]] = Counter()
    for e in short_ready:
        pair = _date_ticker_pair(e)
        if pair is not None:
            pair_counts[pair] += 1
    duplicate_pairs: set[tuple[str, str]] = {
        pair for pair, n in pair_counts.items() if n >= 2
    }

    # ---- per-event flag application -------------------------------------
    enriched: list[dict[str, Any]] = []
    for e in short_ready:
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
        "ok":                       True,
        "total_short_ready":        total_short_ready,
        "suspicious_count":         len(suspicious),
        "clean_short_ready_count":  total_short_ready - len(suspicious),
        "by_flag":                  by_flag,
        "examples":                 suspicious_sorted[:capped_limit],
        "recommended_next_action":
            _recommend(total_short_ready, len(suspicious)),
    }


def _recommend(total_short_ready: int, suspicious_count: int) -> str:
    if total_short_ready <= 0:
        return _RECOMMENDED_NO_SHORT_READY
    if suspicious_count == 0:
        return _RECOMMENDED_OK
    return _RECOMMENDED_GAPS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Short-horizon (1d/5d) topical contamination report",
        "",
    ]
    lines.append(f"Total short-horizon-ready events: {report['total_short_ready']}")
    lines.append(f"  suspicious (>=1 flag):          {report['suspicious_count']}")
    lines.append(f"  clean short-ready:              {report['clean_short_ready_count']}")
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
            "short-horizon (1d/5d) statistical-validation cohort.  "
            "Flags DRIV/LIT-style suspicious assignments, "
            "mechanism_family none, duplicate (event_date, "
            "primary_ticker) rows, and local/off-topic headlines.  "
            "Read-only: never assigns tickers, never deletes or edits "
            "archive rows, no provider, no LLM, no FastAPI surface."
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
            f"every short-horizon-ready event."
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

    report = summarize_short_horizon_contamination(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

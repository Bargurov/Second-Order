#!/usr/bin/env python3
"""Weekly Market duplicate-cluster diagnostic — read-only.

Scans the events table for repeated stories inside the
"Weekly Market" window (the trailing N days, default 7 — the same
slice the ``/movers/weekly`` surface aggregates from), groups them by
two orthogonal axes, and surfaces *suggested* canonical groupings.
No dedup logic is applied; the diagnostic is purely a study report.

Read-only contract
------------------
* The events DB is opened with the SQLite URI ``mode=ro`` flag so the
  read-only contract is enforced at the connection level.  No
  ``INSERT`` / ``UPDATE`` / ``DELETE`` / ``REPLACE`` statement is
  issued by this module under any code path.
* No DB other than the events table is touched; no clusters / archive
  / news / cache file is read or rewritten.
* No paid surface is imported: no ``yfinance`` / ``market_data`` /
  provider; no LLM; no FastAPI surface; no network call.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.

Detection axes
--------------
1. ``repeated_date_ticker_groups`` — events that share the same
   ``(event_date, frozenset(market_tickers))`` and carry at least one
   ticker.  Empty-ticker rows are excluded from this axis because they
   would over-fire (every empty-ticker row on a given date would
   group together).
2. ``repeated_headline_groups`` — events whose normalised headlines
   are equal OR one is a token-prefix of another within the same
   ``event_date``.  Normalisation lowercases, drops surrounding
   punctuation, collapses whitespace.  Both equality and prefix
   relations are reported together so the operator sees the full
   cluster, not a fragment.

A third surface — ``mechanism_theme_candidates`` — counts events by
``mechanism_family`` over the window and surfaces families recurring
``--theme-threshold`` times or more.  It is NOT a duplicate axis;
it is a thematic-cluster hint.

Suggested canonical
-------------------
For each duplicate group, the diagnostic *suggests* a canonical
event_id using a simple, documented rule: pick the event whose
headline (after normalisation) is the longest; ties break to the
lowest event_id.  This is a hint, not a directive — the field is
named ``suggested_canonical_event_id`` and the
``recommended_weekly_filter_rules`` block describes what a future
dedup rule might look like.  Nothing is mutated.

Conservative wording
--------------------
Banned tokens in any surfaced prose: ``proof``, ``proven``,
``automatically``, ``alpha generated``, ``guaranteed``,
``correct ticker``.  The diagnostic never claims a canonical
event_id is *the* correct event_id; it claims a suggestion.

Usage::

    python scripts/section_c_weekly_duplicate_diagnostic.py --json
    python scripts/section_c_weekly_duplicate_diagnostic.py --text
    python scripts/section_c_weekly_duplicate_diagnostic.py --json \\
        --db-path events.db --window-days 7 \\
        --output artifacts/section_c_weekly_duplicate_diagnostic.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_DB_PATH:        str = "events.db"
_DEFAULT_WINDOW_DAYS:    int = 7
_DEFAULT_THEME_THRESHOLD: int = 3

_BANNED_TOKENS: tuple[str, ...] = (
    "proof", "proven", "automatically", "alpha generated",
    "guaranteed", "correct ticker",
)


_RECOMMENDED_RULES: tuple[str, ...] = (
    "suggested rule: treat events with identical "
    "(event_date, normalized_headline) as one cluster before they "
    "reach the weekly mover surface; surface the longest headline as "
    "the cluster representative and the rest as 'see also'.",
    "suggested rule: when one normalised headline is a strict token-"
    "prefix of another within the same event_date, treat the shorter "
    "headline as a partial echo of the longer story rather than a "
    "distinct event.",
    "suggested rule: when several events share the same "
    "(event_date, market_tickers) set, flag the second and subsequent "
    "rows for operator review before they enter the weekly mover "
    "ranking.",
    "suggested rule: do not auto-merge — every grouping above is a "
    "candidate the operator should confirm in a worksheet before any "
    "dedup logic is applied downstream.",
)


# ---------------------------------------------------------------------------
# Patchable seam — tests inject a synthetic loader.
# ---------------------------------------------------------------------------


def _load_events(
    *,
    db_path:        str,
    window_days:    int,
    reference_date: str,
    warnings:       list[str],
    errors:         list[str],
) -> list[dict[str, Any]]:
    """Load events whose ``event_date`` falls inside the
    ``[reference_date - window_days, reference_date]`` window.

    The connection is opened in SQLite URI ``mode=ro`` form so the
    contract is enforced at the driver level.  Missing DB returns an
    empty list and surfaces a warning, not an error.
    """
    p = Path(db_path)
    if not p.exists():
        warnings.append(f"events DB missing: {db_path}")
        return []

    # ``mode=ro`` enforces read-only at the connection level.  Forward-
    # slash the path inside the URI so Windows paths survive intact.
    uri = "file:" + p.as_posix() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        errors.append(f"failed to open events DB read-only: {exc}")
        return []

    try:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, event_date, headline, market_tickers, "
                "       mechanism_family "
                "FROM events "
                "WHERE event_date IS NOT NULL "
                "  AND event_date >= ? "
                "  AND event_date <= ? "
                "ORDER BY event_date ASC, id ASC",
                (_window_start(reference_date, window_days), reference_date),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            errors.append(f"events DB query failed: {exc}")
            return []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        ev_id          = _safe_int(row[0])
        event_date     = _safe_str(row[1])
        headline       = _safe_str(row[2]) or ""
        market_tickers = _parse_tickers(row[3])
        mech_family    = _safe_str(row[4])
        if ev_id is None or event_date is None:
            continue
        out.append({
            "event_id":         ev_id,
            "event_date":       event_date,
            "headline":         headline,
            "tickers":          market_tickers,
            "mechanism_family": mech_family,
        })
    return out


def _window_start(reference_date: str, window_days: int) -> str:
    """Compute the ISO-date string ``reference_date - window_days``."""
    try:
        ref = _dt.date.fromisoformat(reference_date)
    except ValueError:
        return reference_date
    start = ref - _dt.timedelta(days=max(0, int(window_days)))
    return start.isoformat()


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_diagnostic(
    *,
    db_path:        str = _DEFAULT_DB_PATH,
    window_days:    int = _DEFAULT_WINDOW_DAYS,
    reference_date: str | None = None,
    theme_threshold: int = _DEFAULT_THEME_THRESHOLD,
    output_path:    str | None = None,
) -> dict[str, Any]:
    """Build the read-only Weekly Market duplicate-cluster diagnostic.

    See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    ref_date = reference_date or _dt.date.today().isoformat()

    events = _load_events(
        db_path=db_path,
        window_days=window_days,
        reference_date=ref_date,
        warnings=warnings,
        errors=errors,
    )

    # Pre-compute normalised headlines once.
    for ev in events:
        ev["_norm_headline"] = _normalise_headline(ev["headline"])

    # ---- Axis 1: (date, tickers) duplicates --------------------------------
    repeated_date_ticker = _group_by_date_ticker(events)
    repeated_date_ticker_dicts = [
        _group_to_dict(
            group, idx=i, axis="date_ticker",
            reason=(
                "events share the same event_date and the same "
                "market_tickers set; suggest operator review before "
                "they enter the weekly mover ranking."
            ),
        )
        for i, group in enumerate(repeated_date_ticker)
    ]

    # ---- Axis 2: headline equality + prefix --------------------------------
    repeated_headline = _group_by_headline_prefix(events)
    repeated_headline_dicts = [
        _group_to_dict(
            group, idx=i, axis="headline",
            reason=(
                "events share an identical normalised headline or one "
                "is a token-prefix of another within the same "
                "event_date; suggest the longest headline as the "
                "cluster representative."
            ),
        )
        for i, group in enumerate(repeated_headline)
    ]

    # ---- Master union ------------------------------------------------------
    duplicate_groups: list[dict[str, Any]] = (
        list(repeated_date_ticker_dicts) + list(repeated_headline_dicts)
    )

    # ---- Canonical-headline suggestions -----------------------------------
    canonical_headline_suggestions = [
        {
            "group_id":           group["duplicate_group_id"],
            "canonical_headline": _longest_headline(group["headlines"]),
            "event_ids":          list(group["event_ids"]),
        }
        for group in repeated_headline_dicts
    ]

    # ---- Mechanism-theme thematic clusters --------------------------------
    mechanism_theme_candidates = _mechanism_theme_candidates(
        events, threshold=theme_threshold,
    )

    envelope = {
        "ok":                            not errors,
        "candidates_checked":            len(events),
        "duplicate_groups":              duplicate_groups,
        "repeated_date_ticker_groups":   repeated_date_ticker_dicts,
        "repeated_headline_groups":      repeated_headline_dicts,
        "mechanism_theme_candidates":    mechanism_theme_candidates,
        "canonical_headline_suggestions": canonical_headline_suggestions,
        "recommended_weekly_filter_rules": list(_RECOMMENDED_RULES),
        "window": {
            "reference_date": ref_date,
            "window_days":    int(window_days),
            "window_start":   _window_start(ref_date, window_days),
        },
        "warnings": warnings,
        "errors":   errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _group_by_date_ticker(
    events: Iterable[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for ev in events:
        tickers = ev.get("tickers") or ()
        if not tickers:
            # Skip empty-ticker rows on this axis to avoid grouping
            # every untagged row on a date into one giant bucket.
            continue
        key = (ev["event_date"], tuple(tickers))
        buckets[key].append(ev)
    return [group for group in buckets.values() if len(group) >= 2]


def _group_by_headline_prefix(
    events: Iterable[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group events whose normalised headlines are equal OR one is a
    token-prefix of another, within the same ``event_date``.

    Implementation: for each event_date bucket, sort by normalised
    headline length ascending so shorter (potential prefix) anchors
    come first; greedily attach later events that match or extend the
    anchor exactly.  Each event lands in at most one group.
    """
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if ev.get("_norm_headline"):
            by_date[ev["event_date"]].append(ev)

    groups: list[list[dict[str, Any]]] = []
    for _date, evs in by_date.items():
        evs_sorted = sorted(evs, key=lambda e: (len(e["_norm_headline"]),
                                                e["event_id"]))
        consumed: set[int] = set()
        for i, anchor in enumerate(evs_sorted):
            if anchor["event_id"] in consumed:
                continue
            anchor_norm = anchor["_norm_headline"]
            cluster: list[dict[str, Any]] = [anchor]
            consumed.add(anchor["event_id"])
            for other in evs_sorted[i + 1:]:
                if other["event_id"] in consumed:
                    continue
                other_norm = other["_norm_headline"]
                if (
                    other_norm == anchor_norm
                    or other_norm.startswith(anchor_norm + " ")
                ):
                    cluster.append(other)
                    consumed.add(other["event_id"])
            if len(cluster) >= 2:
                groups.append(cluster)
    return groups


def _mechanism_theme_candidates(
    events: Iterable[dict[str, Any]],
    *,
    threshold: int,
) -> list[dict[str, Any]]:
    """Surface mechanism_family values that recur at or above the
    threshold over the window.  Skips the literal placeholder
    ``"none"`` so the report does not flood with the default value.
    """
    counts: dict[str, list[int]] = defaultdict(list)
    for ev in events:
        family = ev.get("mechanism_family")
        if not isinstance(family, str) or not family or family == "none":
            continue
        counts[family].append(ev["event_id"])
    out: list[dict[str, Any]] = []
    for family in sorted(counts.keys()):
        ev_ids = counts[family]
        if len(ev_ids) >= max(1, int(threshold)):
            out.append({
                "mechanism_family":  family,
                "event_ids":         sorted(ev_ids),
                "event_count":       len(ev_ids),
            })
    return out


def _group_to_dict(
    group: list[dict[str, Any]], *, idx: int, axis: str, reason: str,
) -> dict[str, Any]:
    """Project an internal grouping into the documented duplicate-
    group dict shape, with a stable ``duplicate_group_id``."""
    sorted_group = sorted(group, key=lambda e: e["event_id"])
    event_ids   = [ev["event_id"] for ev in sorted_group]
    headlines   = [ev["headline"] for ev in sorted_group]
    dates       = sorted({ev["event_date"] for ev in sorted_group})
    tickers     = sorted({
        t for ev in sorted_group for t in (ev.get("tickers") or ())
    })
    mech_fams   = sorted({
        ev["mechanism_family"] for ev in sorted_group
        if isinstance(ev.get("mechanism_family"), str)
        and ev["mechanism_family"]
    })
    canonical_id = _suggest_canonical_event_id(sorted_group)
    return {
        "duplicate_group_id":          f"{axis}_{idx:03d}",
        "event_ids":                   event_ids,
        "headlines":                   headlines,
        "dates":                       dates,
        "tickers":                     tickers,
        "mechanism_families":          mech_fams,
        "suggested_canonical_event_id": canonical_id,
        "reason":                      reason,
    }


def _suggest_canonical_event_id(
    group: list[dict[str, Any]],
) -> int | None:
    """Pick the longest-headline event as the suggested canonical;
    tie-break on lowest event_id so the choice is deterministic."""
    if not group:
        return None
    pick = max(
        group,
        key=lambda e: (len(e.get("headline") or ""), -int(e["event_id"])),
    )
    return _safe_int(pick.get("event_id"))


def _longest_headline(headlines: Sequence[str]) -> str:
    if not headlines:
        return ""
    return max(headlines, key=len)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalise_headline(headline: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    The result is a space-joined sequence of word tokens — that shape
    is what the prefix check at axis 2 relies on (``startswith(anchor
    + ' ')`` only triggers on a true token boundary)."""
    if not isinstance(headline, str):
        return ""
    return " ".join(_WORD_RE.findall(headline.lower()))


def _parse_tickers(raw: Any) -> tuple[str, ...]:
    """Parse the JSON-string ``market_tickers`` column into a sorted
    tuple of uppercase symbols.  Empty / malformed payloads degrade
    silently to ``()``."""
    if raw in (None, ""):
        return ()
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return ()
    else:
        data = raw
    if not isinstance(data, list):
        return ()
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            sym = item.get("symbol")
            if isinstance(sym, str) and sym:
                out.append(sym.upper())
        elif isinstance(item, str) and item:
            out.append(item.upper())
    return tuple(sorted(set(out)))


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Weekly Market duplicate-cluster diagnostic",
        "",
        f"OK:                  {report['ok']}",
        f"candidates_checked:  {report['candidates_checked']}",
    ]
    w = report.get("window") or {}
    lines.append(
        f"window:              {w.get('window_start')} .. "
        f"{w.get('reference_date')} "
        f"({w.get('window_days')}d)"
    )
    lines.append("")
    lines.append(
        f"duplicate_groups (total):           "
        f"{len(report.get('duplicate_groups') or [])}"
    )
    lines.append(
        f"  - repeated_date_ticker_groups:    "
        f"{len(report.get('repeated_date_ticker_groups') or [])}"
    )
    lines.append(
        f"  - repeated_headline_groups:       "
        f"{len(report.get('repeated_headline_groups') or [])}"
    )
    lines.append(
        f"mechanism_theme_candidates:         "
        f"{len(report.get('mechanism_theme_candidates') or [])}"
    )
    lines.append("")
    for group in report.get("duplicate_groups") or []:
        lines.append(
            f"  [{group['duplicate_group_id']}] "
            f"event_ids={group['event_ids']} "
            f"suggested_canonical={group['suggested_canonical_event_id']}"
        )
        for h in group["headlines"]:
            lines.append(f"      - {h}")
        lines.append(f"      reason: {group['reason']}")
    if report.get("mechanism_theme_candidates"):
        lines.append("")
        lines.append("Mechanism theme candidates:")
        for entry in report["mechanism_theme_candidates"]:
            lines.append(
                f"  - {entry['mechanism_family']:<35} "
                f"count={entry['event_count']:>3}  "
                f"event_ids={entry['event_ids']}"
            )
    lines.append("")
    lines.append("Recommended weekly filter rules (suggestions only):")
    for rule in report.get("recommended_weekly_filter_rules") or []:
        lines.append(f"  - {rule}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Weekly Market duplicate-cluster diagnostic.  "
            "Scans recent events for repeated stories, suggests "
            "canonical groupings, and emits a JSON envelope; no DB "
            "writes, no mutation, no paid surface.  Conservative "
            "wording — every grouping is a suggestion the operator "
            "must confirm before downstream dedup logic is changed."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit JSON (default if neither flag is passed).",
    )
    fmt.add_argument(
        "--text", action="store_true",
        help="Emit the compact text layout.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=_DEFAULT_DB_PATH,
        help=(
            f"Path to the read-only events DB (default "
            f"{_DEFAULT_DB_PATH})."
        ),
    )
    parser.add_argument(
        "--window-days", dest="window_days", type=int,
        default=_DEFAULT_WINDOW_DAYS,
        help=(
            f"Trailing-day window the 'weekly' slice represents "
            f"(default {_DEFAULT_WINDOW_DAYS})."
        ),
    )
    parser.add_argument(
        "--reference-date", dest="reference_date", default=None,
        help=(
            "End of the window, ISO date (default = today).  Tests "
            "pass an explicit date so the window is deterministic."
        ),
    )
    parser.add_argument(
        "--theme-threshold", dest="theme_threshold", type=int,
        default=_DEFAULT_THEME_THRESHOLD,
        help=(
            f"Minimum recurrence count for a mechanism_family to "
            f"appear in mechanism_theme_candidates (default "
            f"{_DEFAULT_THEME_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the diagnostic has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_diagnostic(
        db_path=args.db_path,
        window_days=int(args.window_days),
        reference_date=args.reference_date,
        theme_threshold=int(args.theme_threshold),
        output_path=args.output_path,
    )

    if args.text:
        print(_render_text(report), file=output)
    else:
        print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Section C Daily mechanism-enrichment diagnostic.

Read-only diagnostic that answers a single, narrow question:

    "If I want each Daily Market candidate (sourced from
    ``news_inbox.json``) to carry a ``mechanism_family`` BEFORE it is
    promoted into Section C, can I plausibly enrich it from data
    this repository already holds — and if so, by what concrete
    match path?"

The diagnostic does NOT assign mechanism_family to any inbox row.
It only surfaces:

  * which inbox headlines plausibly match an existing event whose
    ``mechanism_family`` is already set (exact or normalized
    headline match — no fuzzy / LLM matching);
  * which inbox headlines have no reliable match, which are the
    *enrichment_gaps* the operator must close upstream;
  * which enrichment sources exist in the DB today.

Read-only by construction
-------------------------

* Reads ``news_inbox.json`` (default at ``./news_inbox.json``) and
  the SQLite events DB via ``SELECT`` only.  No INSERT / UPDATE /
  DELETE.
* No mutation of ``news_inbox``, ``events``, ``curated_candidates``,
  or any artifact file.
* No provider call (no ``yfinance`` / ``market_data`` / paid path),
  no LLM, no FastAPI surface (never imports ``api`` / ``routes.*``).
* No fuzzy headline matching — the diagnostic uses two narrow
  comparisons only: exact raw string equality and a minimal
  normalization (case-fold + collapse internal whitespace + strip
  leading/trailing whitespace + strip a single trailing period).
  Anything beyond that lands in ``enrichment_gaps``.
* Never assigns a new mechanism_family.  The constraint "Do not
  change Daily filters yet" is respected by construction.

Output contract (JSON)::

    {
      "ok":                              bool,
      "daily_candidates_checked":        int,
      "candidates_without_mechanism_family": int,
      "possible_event_matches": [
        {
          "inbox_headline":          str,
          "matched_event_id":        int,
          "event_headline":          str,
          "match_type":              "exact" | "normalized",
          "event_mechanism_family":  str,
          "event_primary_ticker":    str | None,
          "confidence_label":        str,
          "caution":                 str,
        },
        ...
      ],
      "enrichment_sources_available": [
        {"source": str, "present": bool, "rows_with_value": int},
        ...
      ],
      "enrichment_gaps": [
        {"inbox_headline": str, "gap_reason": str},
        ...
      ],
      "recommended_enrichment_path":     str,
      "warnings":                        [str, ...],
      "errors":                          [str, ...],
    }

Conservative wording — the diagnostic reports plausibility only.
Banned tokens in any text the script emits: ``proof``, ``proven``,
``broken``, ``wrong``, ``must fix``, ``guaranteed``,
``automatically``, ``definitely``, ``causes``, ``causation``.  The
diagnostic never asserts that a matched event is the "correct"
event for an inbox row — every match carries an explicit
``caution`` reminding the operator that review is required before
promotion.

Usage::

    python scripts/section_c_daily_mechanism_enrichment_diagnostic.py --json
    python scripts/section_c_daily_mechanism_enrichment_diagnostic.py --json \\
        --inbox-path news_inbox.json --db-path events.db
    python scripts/section_c_daily_mechanism_enrichment_diagnostic.py --json \\
        --output artifacts/section_c_daily_mechanism_enrichment.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_INBOX_PATH: str = "news_inbox.json"

# Sentinels treated as "no usable mechanism_family value" — both the
# default the events column lays down for legacy rows and the empty
# string variants the operator might supply.
_NO_MECHANISM_SENTINELS: frozenset[str] = frozenset({"", "none", "None"})

_CONFIDENCE_EXACT:      str = "exact_headline_match"
_CONFIDENCE_NORMALIZED: str = "normalized_headline_match"

_MATCH_CAUTION: str = (
    "Operator review required before promoting this match — the "
    "diagnostic surfaces a headline correspondence only and does not "
    "assign mechanism_family."
)

_GAP_REASON_NO_MATCH: str = (
    "no exact or normalized headline match was found among events "
    "carrying a usable mechanism_family; the diagnostic does not "
    "perform fuzzy matching and reports this as an enrichment gap"
)
_GAP_REASON_EMPTY_TITLE: str = (
    "inbox row carried an empty or missing title; the diagnostic "
    "does not synthesise a headline from other fields"
)

_RECOMMENDED_NO_CANDIDATES: str = (
    "No daily candidates were checked — confirm the inbox file path "
    "or supply --inbox-path."
)
_RECOMMENDED_ALL_MATCHED: str = (
    "All {n} daily candidate(s) align with an existing event "
    "headline ({exact} exact, {normalized} normalized).  Operator "
    "review is required before any of these correspondences is "
    "promoted; the diagnostic surfaces matches and does not assign "
    "mechanism_family."
)
_RECOMMENDED_PARTIAL: str = (
    "{matched} of {n} daily candidate(s) align with an existing "
    "event headline ({exact} exact, {normalized} normalized); "
    "{gaps} candidate(s) appear in 'enrichment_gaps' with no "
    "reliable headline match.  Operator review is required for the "
    "matched set; the gaps would need an upstream enrichment source "
    "the diagnostic did not find."
)
_RECOMMENDED_NONE_MATCHED: str = (
    "0 of {n} daily candidate(s) align with an existing event "
    "headline by exact or normalized match; every candidate appears "
    "in 'enrichment_gaps'.  The diagnostic surfaces gaps only and "
    "does not propose an assignment."
)
_RECOMMENDED_NO_SOURCES: str = (
    "No enrichment source carries a usable mechanism_family value "
    "(events.mechanism_family and curated_candidates.mechanism_family "
    "are both empty or set to 'none').  Every daily candidate lands "
    "in 'enrichment_gaps' by construction; the diagnostic does not "
    "synthesise a mechanism_family."
)
_RECOMMENDED_ERRORED: str = (
    "Diagnostic surfaced errors before the match counts settled.  "
    "Inspect 'errors' before relying on 'possible_event_matches' "
    "or 'enrichment_gaps'."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _load_inbox(*, path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Read ``path`` and return ``(inbox_rows, warnings)``.

    The inbox is a JSON array of small dicts; each is expected to
    carry at least a ``title`` field.  Returns an empty list with a
    descriptive warning when the file is missing, unparseable, or
    not a JSON array.  Read-only.
    """
    warnings: list[str] = []
    p = Path(path)
    if not p.is_file():
        warnings.append(
            f"inbox file not found at {path!r}; the diagnostic "
            f"reports zero candidates checked"
        )
        return [], warnings
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(
            f"failed to parse inbox file {path!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return [], warnings
    if not isinstance(data, list):
        warnings.append(
            f"inbox file {path!r} did not parse as a JSON array; "
            f"the diagnostic reports zero candidates checked"
        )
        return [], warnings
    rows: list[dict[str, Any]] = [r for r in data if isinstance(r, dict)]
    return rows, warnings


def _load_events_with_mechanism(
    *, db_path: str | None,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Load events whose ``mechanism_family`` is set to a usable
    value.  Returns ``(rows, sources_summary, warnings)``.

    ``rows`` is a list of small dicts ``{event_id, headline,
    primary_ticker, mechanism_family}`` with empty/"none" filtered out
    upstream in the SQL.

    ``sources_summary`` is keyed by source name (``events.mechanism_family``
    and ``curated_candidates.mechanism_family``) and reports the
    row count seen for each.  A missing table yields ``0`` rather
    than a crash.

    Read-only by construction — issues only ``SELECT``.
    """
    warnings: list[str] = []
    out_rows:      list[dict[str, Any]] = []
    sources: dict[str, int] = {
        "events.mechanism_family":              0,
        "curated_candidates.mechanism_family":  0,
    }

    resolved = _resolve_db_path(db_path)
    if resolved is None or not Path(resolved).exists():
        warnings.append(
            f"events DB not found at {resolved!r}; the diagnostic "
            f"reports zero enrichment-source rows"
        )
        return out_rows, sources, warnings

    try:
        conn = sqlite3.connect(resolved)
    except sqlite3.Error as exc:
        warnings.append(
            f"events DB at {resolved!r} could not be opened "
            f"read-only: {type(exc).__name__}: {exc}"
        )
        return out_rows, sources, warnings

    try:
        # events table
        try:
            rows = conn.execute(
                "SELECT id, headline, market_tickers, mechanism_family "
                "FROM events "
                "WHERE mechanism_family IS NOT NULL "
                "AND mechanism_family != '' "
                "AND mechanism_family != 'none'"
            ).fetchall()
        except sqlite3.Error as exc:
            warnings.append(
                f"events.mechanism_family query raised: "
                f"{type(exc).__name__}: {exc}"
            )
            rows = []
        for r in rows:
            ev_id, headline, market_tickers, family = r
            if not isinstance(ev_id, int):
                continue
            if not isinstance(headline, str) or not headline:
                continue
            if not isinstance(family, str) or family in _NO_MECHANISM_SENTINELS:
                continue
            out_rows.append({
                "event_id":         ev_id,
                "headline":         headline,
                "primary_ticker":   _primary_ticker(market_tickers),
                "mechanism_family": family,
                "source":           "events.mechanism_family",
            })
        sources["events.mechanism_family"] = len(out_rows)

        # curated_candidates table (auxiliary enrichment source).
        # Recorded as a count only; the diagnostic does not propose
        # cross-table matching since the spec restricts the match
        # surface to events.mechanism_family.
        try:
            curated_rows = conn.execute(
                "SELECT COUNT(*) FROM curated_candidates "
                "WHERE mechanism_family IS NOT NULL "
                "AND mechanism_family != '' "
                "AND mechanism_family != 'none'"
            ).fetchone()
        except sqlite3.Error:
            curated_rows = (0,)
        sources["curated_candidates.mechanism_family"] = int(
            curated_rows[0] if curated_rows and isinstance(curated_rows[0], int)
            else 0
        )
    finally:
        conn.close()

    return out_rows, sources, warnings


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_daily_mechanism_enrichment_diagnostic(
    *,
    inbox_path:  str = _DEFAULT_INBOX_PATH,
    db_path:     str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Run the Daily mechanism-enrichment diagnostic.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    inbox_rows, inbox_warnings = _load_inbox(path=inbox_path)
    warnings.extend(inbox_warnings)

    enrichment_rows, sources_summary, db_warnings = (
        _load_events_with_mechanism(db_path=db_path)
    )
    warnings.extend(db_warnings)

    # Build the lookup tables from enrichment rows.
    exact_map:      dict[str, dict[str, Any]] = {}
    normalized_map: dict[str, list[dict[str, Any]]] = {}
    for er in enrichment_rows:
        headline = er["headline"]
        if headline in exact_map:
            warnings.append(
                f"duplicate event headline {headline!r}; the "
                f"diagnostic keeps the first occurrence "
                f"(event_id={exact_map[headline]['event_id']}) and "
                f"surfaces this ambiguity for operator audit"
            )
            continue
        exact_map[headline] = er
    for er in enrichment_rows:
        norm = _normalize_headline(er["headline"])
        normalized_map.setdefault(norm, []).append(er)

    daily_candidates_checked = 0
    candidates_without_mechanism_family = 0
    possible_matches: list[dict[str, Any]] = []
    enrichment_gaps:   list[dict[str, Any]] = []

    for row in inbox_rows:
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            warnings.append(
                f"inbox row skipped — {_GAP_REASON_EMPTY_TITLE}: "
                f"{row!r}"
            )
            continue
        daily_candidates_checked += 1
        # Every inbox row lacks mechanism_family by construction —
        # the field is not part of the inbox schema.  Pin this in the
        # envelope for the operator's audit even though the count
        # equals daily_candidates_checked.
        candidates_without_mechanism_family += 1

        # Exact match first.
        exact_hit = exact_map.get(title)
        if exact_hit is not None:
            possible_matches.append(_match_record(
                inbox_title=title, event_row=exact_hit,
                match_type="exact",
            ))
            continue

        # Normalized match next.
        norm_title = _normalize_headline(title)
        norm_hits = normalized_map.get(norm_title)
        if norm_hits:
            chosen = norm_hits[0]
            if len(norm_hits) > 1:
                warnings.append(
                    f"normalized headline {norm_title!r} matched "
                    f"{len(norm_hits)} events; the diagnostic surfaces "
                    f"the first (event_id={chosen['event_id']}) and "
                    f"records the ambiguity here for operator audit"
                )
            possible_matches.append(_match_record(
                inbox_title=title, event_row=chosen,
                match_type="normalized",
            ))
            continue

        # No reliable match → enrichment gap.
        enrichment_gaps.append({
            "inbox_headline": title,
            "gap_reason":     _GAP_REASON_NO_MATCH,
        })

    enrichment_sources_available = _format_sources(
        sources_summary=sources_summary,
    )

    exact_count = sum(
        1 for m in possible_matches if m["match_type"] == "exact"
    )
    normalized_count = sum(
        1 for m in possible_matches if m["match_type"] == "normalized"
    )

    recommended = _recommend(
        checked=daily_candidates_checked,
        matched=len(possible_matches),
        gaps=len(enrichment_gaps),
        exact=exact_count,
        normalized=normalized_count,
        no_sources=all(
            s["rows_with_value"] == 0
            for s in enrichment_sources_available
        ),
        has_errors=bool(errors),
    )

    return _finalize(
        envelope={
            "ok":                          not errors,
            "daily_candidates_checked":    daily_candidates_checked,
            "candidates_without_mechanism_family": (
                candidates_without_mechanism_family
            ),
            "possible_event_matches":      possible_matches,
            "enrichment_sources_available": enrichment_sources_available,
            "enrichment_gaps":             enrichment_gaps,
            "recommended_enrichment_path": recommended,
            "warnings":                    warnings,
            "errors":                      errors,
        },
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_headline(value: str) -> str:
    """Minimal normalization the spec authorises: case-fold,
    collapse internal whitespace, strip leading/trailing whitespace,
    strip a single trailing period.

    Deliberately narrow.  Anything more aggressive (punctuation
    stripping, token reordering, stemming) drifts toward fuzzy
    matching and would violate the diagnostic's contract.
    """
    if not isinstance(value, str):
        return ""
    s = value.strip().casefold()
    s = _WHITESPACE_RE.sub(" ", s)
    if s.endswith("."):
        s = s[:-1].rstrip()
    return s


def _primary_ticker(value: Any) -> str | None:
    """Pull the first ticker from a JSON-encoded ``market_tickers``
    column.  Mirrors the canonical convention used by the events
    table and the benchmark-sensitivity preflight.
    """
    if value is None:
        return None
    if isinstance(value, list):
        for t in value:
            if isinstance(t, str) and t.strip():
                return t.strip()
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        for t in parsed:
            if isinstance(t, str) and t.strip():
                return t.strip()
    return None


def _match_record(
    *,
    inbox_title: str,
    event_row:   dict[str, Any],
    match_type:  str,
) -> dict[str, Any]:
    confidence = (
        _CONFIDENCE_EXACT if match_type == "exact"
        else _CONFIDENCE_NORMALIZED
    )
    return {
        "inbox_headline":         inbox_title,
        "matched_event_id":       int(event_row["event_id"]),
        "event_headline":         str(event_row["headline"]),
        "match_type":             match_type,
        "event_mechanism_family": str(event_row["mechanism_family"]),
        "event_primary_ticker":   event_row.get("primary_ticker"),
        "confidence_label":       confidence,
        "caution":                _MATCH_CAUTION,
    }


def _format_sources(
    *, sources_summary: dict[str, int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in (
        "events.mechanism_family",
        "curated_candidates.mechanism_family",
    ):
        count = int(sources_summary.get(name, 0))
        out.append({
            "source":          name,
            "present":         count > 0,
            "rows_with_value": count,
        })
    return out


def _recommend(
    *,
    checked:    int,
    matched:    int,
    gaps:       int,
    exact:      int,
    normalized: int,
    no_sources: bool,
    has_errors: bool,
) -> str:
    if has_errors:
        return _RECOMMENDED_ERRORED
    if checked <= 0:
        return _RECOMMENDED_NO_CANDIDATES
    if no_sources:
        return _RECOMMENDED_NO_SOURCES
    if gaps <= 0 and matched > 0:
        return _RECOMMENDED_ALL_MATCHED.format(
            n=checked, exact=exact, normalized=normalized,
        )
    if matched <= 0:
        return _RECOMMENDED_NONE_MATCHED.format(n=checked)
    return _RECOMMENDED_PARTIAL.format(
        matched=matched, n=checked,
        exact=exact, normalized=normalized, gaps=gaps,
    )


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


def _finalize(
    *, envelope: dict[str, Any], output_path: str | None,
) -> dict[str, Any]:
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
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Daily mechanism-enrichment diagnostic.  For "
            "each inbox row in news_inbox.json, asks whether an "
            "existing event headline matches (exact or normalized) "
            "and, if so, surfaces the event's mechanism_family as a "
            "candidate enrichment.  Never assigns mechanism_family, "
            "never calls an LLM, never mutates the DB or any "
            "artifact file.  Conservative wording: reports headline "
            "correspondence only, with an explicit caution that "
            "operator review is required before promotion."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    parser.add_argument(
        "--inbox-path", dest="inbox_path",
        default=_DEFAULT_INBOX_PATH,
        help=(
            f"Path to the inbox file (default "
            f"{_DEFAULT_INBOX_PATH!r}).  Read-only."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the events DB.  Defaults to "
            "db.DB_FILE.  Read-only by construction."
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
    report = run_section_c_daily_mechanism_enrichment_diagnostic(
        inbox_path=args.inbox_path,
        db_path=args.db_path,
        output_path=args.output_path,
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_daily_mechanism_enrichment_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

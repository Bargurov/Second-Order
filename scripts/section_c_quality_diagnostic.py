#!/usr/bin/env python3
"""Section C headline quality diagnostic.

Diagnoses what is currently entering the project's three Section C
surfaces — Daily, Weekly, and Still Moving Market — and why.  This
script is **diagnostic only**: it never applies a filter, never
mutates an artifact, never drops a row, and never claims any
recommendation is the right fix.  The output is an inspectable
report the operator reads before deciding which filters (if any) to
change.

Read-only by construction
-------------------------

* Opens the SQLite at ``--db-path`` (default ``events.db``) via the
  ``file:...?mode=ro`` URI form so the connection literally cannot
  write.  Issues ``SELECT`` only.
* Never imports ``api``, ``routes.*``, ``movers_cache``, or any
  production filter surface — the diagnostic must be able to find
  bugs in the live filter without re-applying that filter's logic.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM, or
  paid provider call.  No network access.
* Existing archive / news / cache / artifacts files are never read
  or rewritten.

Diagnose-before-fix policy
--------------------------

* ``recommended_filter_rules`` is a *suggestion* list: each entry
  starts with a suggestion verb (``Consider``, ``Operators may``,
  ``Investigate``).  Nothing in this list is applied.
* Candidates are tagged with the issues they exhibit but never
  excluded — the operator inspects every row that would land on a
  Section C surface, including the ones the live filter already
  drops.
* Missing source files (DB missing, table missing) surface as a
  warning and continue with empty results; only real errors
  (sqlite raises, JSON in a payload column does not parse) set
  ``ok=False``.

Output JSON shape::

    {
      "ok":                       bool,
      "generated_at":             str,        # ISO-8601 UTC
      "sources_checked": [
        {"name": str, "path": str, "present": bool,
         "row_count": int | None, "note": str},
        ...
      ],
      "daily_candidates":         [candidate, ...],
      "weekly_candidates":        [candidate, ...],
      "still_moving_candidates":  [candidate, ...],
      "junk_headlines":           [candidate, ...],
      "duplicate_groups":         [duplicate_group, ...],
      "weak_ticker_cases":        [candidate, ...],
      "missing_mechanism_cases":  [candidate, ...],
      "bad_proxy_cases":          [candidate, ...],
      "recommended_filter_rules": [str, ...],   # suggestions only
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
    }

Each candidate carries the 14 spec fields plus ``diagnostic_tags``::

    {
      "event_id":               int,
      "headline":               str | None,
      "event_date":             str | None,
      "source_section":         "daily" | "weekly" | "still_moving",
      "mechanism_family":       str | None,
      "primary_ticker":         str | None,
      "benchmark_ticker":       str | None,
      "inclusion_reason":       str,
      "exclusion_reason":       str,
      "duplicate_group_id":     str | None,
      "ticker_quality":         "ok" | "missing_primary" |
                                "proxy_only" | "no_cache" | "unknown",
      "market_relevance_score": float,   # 0.0-1.0 in 0.1 steps
      "evidence_available":     bool,
      "diagnostic_tags":        list[str],   # closed vocabulary
    }

Closed diagnostic-tag vocabulary
--------------------------------

  * ``off_topic``
  * ``raw_legal_text``
  * ``duplicate_headline``
  * ``duplicate_date_ticker``
  * ``weak_proxy``
  * ``missing_mechanism_family``
  * ``vague_diplomacy``
  * ``no_price_cache``
  * ``low_market_relevance``
  * ``accepted_candidate``
  * ``needs_operator_review``

Tags are partitioned into ``_EXCLUSION_WORTHY_TAGS`` (off_topic,
raw_legal_text, missing_mechanism_family, no_price_cache) and
``_OBSERVATIONAL_TAGS`` (duplicate_headline, duplicate_date_ticker,
weak_proxy, vague_diplomacy, low_market_relevance).  Invariant:
``accepted_candidate`` co-occurs only with zero exclusion-worthy
tags, and is mutually exclusive with every entry in
``_EXCLUSION_WORTHY_TAGS``.  ``needs_operator_review`` fires when an
accepted candidate carries ≥1 observational tag, or when a
non-accepted candidate carries ≥2 exclusion-worthy tags.

Conservative wording — banned tokens in any prose the diagnostic
emits: ``proof``, ``proven``, ``validated``, ``automatically``,
``alpha generated``, ``guaranteed``, ``correct ticker``.

Usage::

    python scripts/section_c_quality_diagnostic.py --json
    python scripts/section_c_quality_diagnostic.py --json \\
        --db-path events.db --limit-per-section 50
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ARTIFACT_TYPE: str = "section_c_quality_diagnostic"


# ---------------------------------------------------------------------------
# Window tunables — kept conservative.  The diagnostic samples the
# candidate pool wider than the production filter so the operator can
# see what the filter drops.
# ---------------------------------------------------------------------------

_DEFAULT_DAILY_HOURS:         int = 24
_DEFAULT_WEEKLY_DAYS:         int = 7
_DEFAULT_PERSISTENT_DAYS_MIN: int = 7
_DEFAULT_PERSISTENT_DAYS_MAX: int = 60
_DEFAULT_LIMIT_PER_SECTION:   int = 200


# ---------------------------------------------------------------------------
# Section identifiers
# ---------------------------------------------------------------------------

_SECTION_DAILY:        str = "daily"
_SECTION_WEEKLY:       str = "weekly"
_SECTION_STILL_MOVING: str = "still_moving"


# ---------------------------------------------------------------------------
# Closed diagnostic-tag vocabulary
# ---------------------------------------------------------------------------

_TAG_OFF_TOPIC:                str = "off_topic"
_TAG_RAW_LEGAL_TEXT:           str = "raw_legal_text"
_TAG_DUPLICATE_HEADLINE:       str = "duplicate_headline"
_TAG_DUPLICATE_DATE_TICKER:    str = "duplicate_date_ticker"
_TAG_WEAK_PROXY:               str = "weak_proxy"
_TAG_MISSING_MECHANISM_FAMILY: str = "missing_mechanism_family"
_TAG_VAGUE_DIPLOMACY:          str = "vague_diplomacy"
_TAG_NO_PRICE_CACHE:           str = "no_price_cache"
_TAG_LOW_MARKET_RELEVANCE:     str = "low_market_relevance"
_TAG_ACCEPTED_CANDIDATE:       str = "accepted_candidate"
_TAG_NEEDS_OPERATOR_REVIEW:    str = "needs_operator_review"


# Tags that, on their own, would make the live Section C surface
# drop a row.  Used to derive ``accepted_candidate`` and to drive
# ``needs_operator_review`` arithmetic.
_EXCLUSION_WORTHY_TAGS: frozenset[str] = frozenset({
    _TAG_OFF_TOPIC,
    _TAG_RAW_LEGAL_TEXT,
    _TAG_MISSING_MECHANISM_FAMILY,
    _TAG_NO_PRICE_CACHE,
})

# Tags that are a concern but do not on their own justify exclusion
# — they need operator judgment.
_OBSERVATIONAL_TAGS: frozenset[str] = frozenset({
    _TAG_DUPLICATE_HEADLINE,
    _TAG_DUPLICATE_DATE_TICKER,
    _TAG_WEAK_PROXY,
    _TAG_VAGUE_DIPLOMACY,
    _TAG_LOW_MARKET_RELEVANCE,
})


_LOW_RELEVANCE_THRESHOLD: float = 0.7


# ---------------------------------------------------------------------------
# Pattern banks — narrow on purpose.  ``vague_diplomacy`` only catches
# explicit hedge phrases (not bare modals like "may" or "could", which
# legitimately appear in real news headlines).
# ---------------------------------------------------------------------------

_RAW_LEGAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^\s*§",
        r"^\s*sec\.\s*\d",
        r"^\s*section\s+\d+(\.\d+)*",
        r"\bc\.?f\.?r\.?\b",
        r"\bu\.?s\.?c\.?\b",
        r"\bsubparagraph\b",
        r"\bsubsection\b",
        r"\bpursuant to\b",
        r"\bpromulgated\b",
        r"\bshall be deemed\b",
    )
)

_OFF_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bcelebrit(y|ies)\b",
        r"\bweather forecast\b",
        r"\brecipe\b",
        r"\bobituary\b",
        r"\bcooking\b",
        r"\bfashion\s+(week|trend|show)\b",
        r"\bsuper\s*bowl\b",
        r"\btv\s+(show|series|drama)\b",
        r"\bmovie\s+review\b",
        r"\bbox\s+office\b",
        r"\bhoroscope\b",
        r"\bcrossword\b",
    )
)

_VAGUE_DIPLOMACY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bexpresses?\s+concern\b",
        r"\bcalls?\s+for\s+dialogue\b",
        r"\bsignals?\s+openness\b",
        r"\bencourages?\s+dialogue\b",
        r"\burges?\s+restraint\b",
        r"\bvows?\s+to\s+consider\b",
        r"\breiterates?\s+(its\s+)?commitment\b",
        r"\bcondemns?\b.*\b(in the strongest|in the strongest terms)\b",
    )
)


# ---------------------------------------------------------------------------
# Broad-proxy ETFs — ticker symbols that, when set as the primary,
# usually indicate the upstream pipeline could not pick a specific
# equity.  Diagnostic only — does NOT exclude.
# ---------------------------------------------------------------------------

_BROAD_PROXY_TICKERS: frozenset[str] = frozenset({
    # Whole-market index ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "VXUS",
    # SPDR sector ETFs (broad sector proxies)
    "XLE", "XLF", "XLP", "XLK", "XLV", "XLI", "XLY",
    "XLU", "XLB", "XLRE", "XLC",
})


# ---------------------------------------------------------------------------
# Suggestion-only filter rules.  Every entry must start with one of
# the suggestion verbs in ``_SUGGESTION_VERBS`` so a downstream
# reader (and the contract test) can confirm the diagnostic never
# tells the system what to do.
# ---------------------------------------------------------------------------

_SUGGESTION_VERBS: tuple[str, ...] = (
    "Consider",
    "Operators may",
    "Investigate",
)

_RECOMMENDED_FILTER_RULES: tuple[str, ...] = (
    "Consider deprioritising headlines that match the raw-legal-text "
    "pattern set (§, Sec. N, Section N.N, CFR, USC, "
    "subparagraph/subsection, pursuant to, promulgated) for Section "
    "C surfaces — these are observational diagnostics, not applied "
    "exclusions.",
    "Consider collapsing events that share an exact-match normalised "
    "headline within the same time window into a single row before "
    "Section C ranking; the diagnostic groups duplicates but does "
    "not collapse them.",
    "Operators may want to gate Section C admission on a non-null "
    "mechanism_family; the diagnostic surfaces events whose "
    "mechanism_family is null, empty, or 'none' under the "
    "missing_mechanism_family tag.",
    "Operators may want to downweight events whose primary_ticker is "
    "a broad-market or sector-broad ETF (SPY, QQQ, XLE, etc.) — the "
    "diagnostic flags these as weak_proxy but does not exclude them.",
    "Investigate events flagged with no_price_cache before letting "
    "them onto a Section C surface; without local price-cache rows "
    "no descriptive sensitivity can be computed for that ticker.",
    "Investigate events whose market_relevance_score sits below "
    "0.7; the score is a coarse 10-feature heuristic and a value "
    "below 0.7 indicates four or more weakness tags coinciding.",
)


# ---------------------------------------------------------------------------
# Patchable seam — tests inject synthetic state to drive the
# diagnostic without touching a real sqlite file.
# ---------------------------------------------------------------------------


def _load_section_c_state(*, db_path: str | None) -> dict[str, Any]:
    """Read the local archive read-only and return raw rows.

    Output shape::

        {
          "events":              [event_dict, ...],
          "price_cache_tickers": {ticker_upper: int row count},
          "sources_checked":     [{"name", "path", "present",
                                    "row_count", "note"}, ...],
          "warnings":            [str, ...],
          "errors":              [str, ...],
        }

    Missing DB / missing table → ``warnings`` entry + empty results
    (the seam returns ``ok``-shaped data).  Real sqlite errors
    surface in ``errors``; the caller decides what to do with them.

    Tests patch this attribute directly so the import only resolves
    on the un-patched path.
    """
    warnings: list[str] = []
    errors:   list[str] = []
    sources:  list[dict[str, Any]] = []

    if not isinstance(db_path, str) or not db_path:
        warnings.append(
            "no --db-path supplied; diagnostic has nothing to read"
        )
        return _empty_state(sources, warnings, errors)

    target = Path(db_path)
    if not target.exists():
        warnings.append(
            f"--db-path does not exist on disk: {db_path!r}; the "
            f"diagnostic returns an empty report"
        )
        sources.append({
            "name":      "events_db",
            "path":      db_path,
            "present":   False,
            "row_count": None,
            "note":      "file missing",
        })
        return _empty_state(sources, warnings, errors)

    try:
        # Read-only URI form: the connection literally cannot write.
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True,
        )
    except sqlite3.Error as exc:
        errors.append(
            f"failed to open {db_path!r} read-only: {exc}"
        )
        sources.append({
            "name":      "events_db",
            "path":      db_path,
            "present":   True,
            "row_count": None,
            "note":      "sqlite open failed",
        })
        return {
            "events":              [],
            "price_cache_tickers": {},
            "sources_checked":     sources,
            "warnings":            warnings,
            "errors":              errors,
        }

    events:      list[dict[str, Any]] = []
    cache_counts: dict[str, int]      = {}

    try:
        # events table -----------------------------------------------------
        events, events_present, events_rows, evt_note = _read_events(
            conn, warnings=warnings, errors=errors,
        )
        sources.append({
            "name":      "events_table",
            "path":      db_path,
            "present":   events_present,
            "row_count": events_rows,
            "note":      evt_note,
        })

        # price_cache table ----------------------------------------------
        cache_counts, cache_present, cache_rows, cache_note = _read_price_cache(
            conn, warnings=warnings, errors=errors,
        )
        sources.append({
            "name":      "price_cache_table",
            "path":      db_path,
            "present":   cache_present,
            "row_count": cache_rows,
            "note":      cache_note,
        })
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    return {
        "events":              events,
        "price_cache_tickers": cache_counts,
        "sources_checked":     sources,
        "warnings":            warnings,
        "errors":              errors,
    }


def _empty_state(
    sources: list[dict[str, Any]],
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "events":              [],
        "price_cache_tickers": {},
        "sources_checked":     sources,
        "warnings":            warnings,
        "errors":              errors,
    }


def _read_events(
    conn: sqlite3.Connection,
    *,
    warnings: list[str],
    errors:   list[str],
) -> tuple[list[dict[str, Any]], bool, int | None, str]:
    """Read the events table into a list of normalised dicts."""
    try:
        rows = conn.execute(
            "SELECT id, headline, event_date, timestamp, "
            "market_tickers, mechanism_family, low_signal, "
            "mechanism_summary "
            "FROM events"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "no such table" in msg or "no such column" in msg:
            warnings.append(
                f"events table missing or schema-shifted ({exc}); "
                f"diagnostic returns an empty report"
            )
            return [], False, None, "events table missing or schema-shifted"
        errors.append(f"events read failed: {exc}")
        return [], True, None, f"sqlite error: {exc}"
    except sqlite3.Error as exc:
        errors.append(f"events read failed: {exc}")
        return [], True, None, f"sqlite error: {exc}"

    out: list[dict[str, Any]] = []
    for raw in rows:
        ev_id, headline, event_date, timestamp, mt, mf, low_sig, mech_summary = raw
        if not isinstance(ev_id, int):
            continue
        out.append({
            "event_id":            ev_id,
            "headline":            headline if isinstance(headline, str) else None,
            "event_date":          event_date if isinstance(event_date, str) else None,
            "timestamp":           timestamp if isinstance(timestamp, str) else None,
            "market_tickers":      _parse_market_tickers(mt),
            "mechanism_family":    mf if isinstance(mf, str) else None,
            "low_signal":          int(low_sig) if isinstance(low_sig, int) else 0,
            "mechanism_summary":   mech_summary if isinstance(mech_summary, str) else None,
        })
    return out, True, len(out), ""


def _read_price_cache(
    conn: sqlite3.Connection,
    *,
    warnings: list[str],
    errors:   list[str],
) -> tuple[dict[str, int], bool, int | None, str]:
    """Read the price_cache table into ``{ticker_upper: row_count}``."""
    try:
        rows = conn.execute(
            "SELECT ticker, COUNT(*) FROM price_cache "
            "WHERE ticker IS NOT NULL AND ticker != '' "
            "GROUP BY ticker"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "no such table" in msg or "no such column" in msg:
            warnings.append(
                f"price_cache table missing or schema-shifted ({exc}); "
                f"no_price_cache tag will fire for every event"
            )
            return {}, False, None, "price_cache table missing"
        errors.append(f"price_cache read failed: {exc}")
        return {}, True, None, f"sqlite error: {exc}"
    except sqlite3.Error as exc:
        errors.append(f"price_cache read failed: {exc}")
        return {}, True, None, f"sqlite error: {exc}"

    out: dict[str, int] = {}
    total = 0
    for t, n in rows:
        if isinstance(t, str) and t and isinstance(n, int):
            out[t.strip().upper()] = n
            total += n
    return out, True, total, ""


def _parse_market_tickers(value: Any) -> list[dict[str, Any]]:
    """Parse the JSON-encoded ``market_tickers`` column defensively.

    Returns the parsed list when it's a list of dicts; otherwise an
    empty list (the caller falls back to no-primary-ticker)."""
    parsed: Any = value
    if isinstance(parsed, str):
        if not parsed:
            return []
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return []
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in parsed:
        if isinstance(entry, dict):
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Other patchable seam — UTC clock.
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_quality_diagnostic(
    *,
    db_path:             str | None = None,
    generated_at:        str | None = None,
    daily_hours:         int        = _DEFAULT_DAILY_HOURS,
    weekly_days:         int        = _DEFAULT_WEEKLY_DAYS,
    persistent_days_min: int        = _DEFAULT_PERSISTENT_DAYS_MIN,
    persistent_days_max: int        = _DEFAULT_PERSISTENT_DAYS_MAX,
    limit_per_section:   int        = _DEFAULT_LIMIT_PER_SECTION,
) -> dict[str, Any]:
    """Run the read-only Section C quality diagnostic.

    See module docstring for the full output contract.
    """
    state = _load_section_c_state(db_path=db_path)
    events = state.get("events") or []
    cache: dict[str, int] = state.get("price_cache_tickers") or {}
    sources_checked = state.get("sources_checked") or []
    warnings = list(state.get("warnings") or [])
    errors   = list(state.get("errors") or [])

    now_dt = _parse_iso_timestamp(generated_at) or _dt.datetime.now(
        tz=_dt.timezone.utc,
    )

    # Step 1: partition events into per-section pools by timestamp / event_date.
    daily_pool, weekly_pool, persistent_pool = _partition_events_into_pools(
        events=events, now_dt=now_dt,
        daily_hours=daily_hours,
        weekly_days=weekly_days,
        persistent_days_min=persistent_days_min,
        persistent_days_max=persistent_days_max,
    )

    # Step 2: precompute duplicate groups across ALL pooled events.
    pooled_union = _dedupe_event_list(
        daily_pool + weekly_pool + persistent_pool,
    )
    duplicate_groups = _build_duplicate_groups(pooled_union)
    dup_headline_ids: set[int] = set()
    dup_date_ticker_ids: set[int] = set()
    headline_group_map: dict[int, str] = {}
    date_ticker_group_map: dict[int, str] = {}
    for grp in duplicate_groups:
        if grp["duplicate_type"] == "headline":
            for ev_id in grp["event_ids"]:
                dup_headline_ids.add(ev_id)
                headline_group_map[ev_id] = grp["group_id"]
        else:
            for ev_id in grp["event_ids"]:
                dup_date_ticker_ids.add(ev_id)
                date_ticker_group_map.setdefault(ev_id, grp["group_id"])

    # Step 3: build candidate rows per section.
    daily_candidates = _build_candidate_list(
        events=daily_pool, section=_SECTION_DAILY,
        cache=cache,
        dup_headline_ids=dup_headline_ids,
        dup_date_ticker_ids=dup_date_ticker_ids,
        headline_group_map=headline_group_map,
        date_ticker_group_map=date_ticker_group_map,
        limit=limit_per_section,
    )
    weekly_candidates = _build_candidate_list(
        events=weekly_pool, section=_SECTION_WEEKLY,
        cache=cache,
        dup_headline_ids=dup_headline_ids,
        dup_date_ticker_ids=dup_date_ticker_ids,
        headline_group_map=headline_group_map,
        date_ticker_group_map=date_ticker_group_map,
        limit=limit_per_section,
    )
    still_moving_candidates = _build_candidate_list(
        events=persistent_pool, section=_SECTION_STILL_MOVING,
        cache=cache,
        dup_headline_ids=dup_headline_ids,
        dup_date_ticker_ids=dup_date_ticker_ids,
        headline_group_map=headline_group_map,
        date_ticker_group_map=date_ticker_group_map,
        limit=limit_per_section,
    )

    # Step 4: derive issue-slice lists from a de-duplicated view of
    # the per-section candidates.  A single event can appear in
    # multiple per-section lists (it's in the daily AND weekly pool,
    # etc.); the issue lists report each event at most once so an
    # operator counts events, not surface occurrences.  weak_ticker
    # and bad_proxy are disjoint by construction.
    unique_by_id: dict[int, dict[str, Any]] = {}
    for c in (
        daily_candidates + weekly_candidates + still_moving_candidates
    ):
        ev_id = c.get("event_id")
        if isinstance(ev_id, int) and ev_id not in unique_by_id:
            unique_by_id[ev_id] = c
    unique_candidates = list(unique_by_id.values())

    junk_headlines = [
        c for c in unique_candidates
        if _TAG_OFF_TOPIC in c["diagnostic_tags"]
        or _TAG_RAW_LEGAL_TEXT in c["diagnostic_tags"]
    ]
    weak_ticker_cases = [
        c for c in unique_candidates
        if c["ticker_quality"] in {"missing_primary", "no_cache"}
    ]
    bad_proxy_cases = [
        c for c in unique_candidates
        if _TAG_WEAK_PROXY in c["diagnostic_tags"]
    ]
    missing_mechanism_cases = [
        c for c in unique_candidates
        if _TAG_MISSING_MECHANISM_FAMILY in c["diagnostic_tags"]
    ]

    envelope: dict[str, Any] = {
        "ok":                       not errors,
        "generated_at":             generated_at or _utcnow_iso(),
        "sources_checked":          sources_checked,
        "daily_candidates":         daily_candidates,
        "weekly_candidates":        weekly_candidates,
        "still_moving_candidates":  still_moving_candidates,
        "junk_headlines":           junk_headlines,
        "duplicate_groups":         duplicate_groups,
        "weak_ticker_cases":        weak_ticker_cases,
        "missing_mechanism_cases":  missing_mechanism_cases,
        "bad_proxy_cases":          bad_proxy_cases,
        "recommended_filter_rules": list(_RECOMMENDED_FILTER_RULES),
        "warnings":                 warnings,
        "errors":                   errors,
    }
    return envelope


# ---------------------------------------------------------------------------
# Window partitioning
# ---------------------------------------------------------------------------


def _partition_events_into_pools(
    *,
    events:              list[dict[str, Any]],
    now_dt:              _dt.datetime,
    daily_hours:         int,
    weekly_days:         int,
    persistent_days_min: int,
    persistent_days_max: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    daily:      list[dict[str, Any]] = []
    weekly:     list[dict[str, Any]] = []
    persistent: list[dict[str, Any]] = []

    for ev in events:
        anchor = _event_anchor_dt(ev)
        if anchor is None:
            continue
        age_h = (now_dt - anchor).total_seconds() / 3600.0
        if age_h < 0:
            # Future-dated event — skip from all windows (unparseable
            # in spirit).  Surface count via the warnings later if
            # this becomes common.
            continue
        if age_h <= daily_hours:
            daily.append(ev)
        if age_h <= weekly_days * 24:
            weekly.append(ev)
        if persistent_days_min * 24 <= age_h <= persistent_days_max * 24:
            persistent.append(ev)
    return daily, weekly, persistent


def _event_anchor_dt(ev: dict[str, Any]) -> _dt.datetime | None:
    """Pick the best timestamp anchor.  Prefers ``timestamp``,
    falls back to ``event_date``."""
    anchor = _parse_iso_timestamp(ev.get("timestamp"))
    if anchor is not None:
        return anchor
    ed = ev.get("event_date")
    if isinstance(ed, str) and ed:
        try:
            return _dt.datetime.fromisoformat(ed[:10]).replace(
                tzinfo=_dt.timezone.utc,
            )
        except ValueError:
            return None
    return None


def _parse_iso_timestamp(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    # Accept either "Z" suffix or explicit offset.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        out = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=_dt.timezone.utc)
    return out


# ---------------------------------------------------------------------------
# Duplicate-group detection
# ---------------------------------------------------------------------------


def _dedupe_event_list(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return events with unique event_id, preserving first
    appearance."""
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        ev_id = ev.get("event_id")
        if not isinstance(ev_id, int) or ev_id in seen:
            continue
        seen.add(ev_id)
        out.append(ev)
    return out


def _build_duplicate_groups(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group events by (a) normalised headline and (b) (event_date,
    primary_ticker).  Returns one entry per group with ≥2 members,
    sorted deterministically."""
    by_headline: dict[str, list[int]] = {}
    by_date_ticker: dict[tuple[str, str], list[int]] = {}
    seen_normalised: dict[int, str] = {}

    for ev in events:
        ev_id = ev.get("event_id")
        if not isinstance(ev_id, int):
            continue
        norm = _normalise_headline(ev.get("headline"))
        seen_normalised[ev_id] = norm
        if norm:
            by_headline.setdefault(norm, []).append(ev_id)
        date_iso = ev.get("event_date")
        pt = _primary_ticker_symbol(ev.get("market_tickers"))
        if isinstance(date_iso, str) and date_iso and pt:
            by_date_ticker.setdefault((date_iso, pt), []).append(ev_id)

    groups: list[dict[str, Any]] = []
    for norm, ids in by_headline.items():
        if len(ids) < 2:
            continue
        ids_sorted = sorted(set(ids))
        groups.append({
            "group_id":       f"headline:{norm[:96]}",
            "duplicate_type": "headline",
            "event_ids":      ids_sorted,
            "headline_normalised": norm,
        })
    for (date_iso, ticker), ids in by_date_ticker.items():
        # Only emit a date_ticker group when the IDs are NOT already
        # captured by an identical-headline group (avoids double
        # counting).
        ids_sorted = sorted(set(ids))
        if len(ids_sorted) < 2:
            continue
        # If all of these IDs already share the same normalised
        # headline, skip — the headline group already covers them.
        norms = {seen_normalised.get(i, "") for i in ids_sorted}
        if len(norms) == 1 and "" not in norms:
            continue
        groups.append({
            "group_id":       f"date_ticker:{date_iso}:{ticker}",
            "duplicate_type": "date_ticker",
            "event_ids":      ids_sorted,
            "event_date":     date_iso,
            "primary_ticker": ticker,
        })

    groups.sort(key=lambda g: (g["duplicate_type"], g["group_id"]))
    return groups


def _normalise_headline(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    s = value.strip().lower()
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s)
    return s


def _primary_ticker_symbol(market_tickers: Any) -> str | None:
    if not isinstance(market_tickers, list):
        return None
    for entry in market_tickers:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            return sym.strip().upper()
    return None


# ---------------------------------------------------------------------------
# Per-candidate annotation
# ---------------------------------------------------------------------------


def _build_candidate_list(
    *,
    events:                list[dict[str, Any]],
    section:               str,
    cache:                 dict[str, int],
    dup_headline_ids:      set[int],
    dup_date_ticker_ids:   set[int],
    headline_group_map:    dict[int, str],
    date_ticker_group_map: dict[int, str],
    limit:                 int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cap = max(0, int(limit)) if isinstance(limit, int) else _DEFAULT_LIMIT_PER_SECTION
    for ev in events[:cap]:
        out.append(_annotate_candidate(
            event=ev, section=section, cache=cache,
            dup_headline_ids=dup_headline_ids,
            dup_date_ticker_ids=dup_date_ticker_ids,
            headline_group_map=headline_group_map,
            date_ticker_group_map=date_ticker_group_map,
        ))
    return out


def _annotate_candidate(
    *,
    event:                 dict[str, Any],
    section:               str,
    cache:                 dict[str, int],
    dup_headline_ids:      set[int],
    dup_date_ticker_ids:   set[int],
    headline_group_map:    dict[int, str],
    date_ticker_group_map: dict[int, str],
) -> dict[str, Any]:
    ev_id   = event.get("event_id")
    headline = event.get("headline")
    event_date = event.get("event_date")

    primary_ticker = _primary_ticker_symbol(event.get("market_tickers"))
    benchmark_ticker = _benchmark_ticker_symbol(event.get("market_tickers"))

    mech_family = event.get("mechanism_family")
    mech_summary = event.get("mechanism_summary")
    mechanism_missing = _mechanism_family_missing(mech_family, mech_summary)

    cache_rows = cache.get(primary_ticker, 0) if primary_ticker else 0

    # Ticker quality.
    ticker_quality: str
    if primary_ticker is None:
        ticker_quality = "missing_primary"
    elif cache_rows <= 0:
        ticker_quality = "no_cache"
    elif primary_ticker in _BROAD_PROXY_TICKERS:
        ticker_quality = "proxy_only"
    else:
        ticker_quality = "ok"

    diagnostic_tags: list[str] = []

    # Headline-pattern tags.
    if _matches_any(_OFF_TOPIC_PATTERNS, headline):
        diagnostic_tags.append(_TAG_OFF_TOPIC)
    if _matches_any(_RAW_LEGAL_PATTERNS, headline):
        diagnostic_tags.append(_TAG_RAW_LEGAL_TEXT)
    if _matches_any(_VAGUE_DIPLOMACY_PATTERNS, headline):
        diagnostic_tags.append(_TAG_VAGUE_DIPLOMACY)

    if mechanism_missing:
        diagnostic_tags.append(_TAG_MISSING_MECHANISM_FAMILY)

    if ticker_quality == "no_cache" or ticker_quality == "missing_primary":
        diagnostic_tags.append(_TAG_NO_PRICE_CACHE)
    if ticker_quality == "proxy_only":
        diagnostic_tags.append(_TAG_WEAK_PROXY)

    if isinstance(ev_id, int):
        if ev_id in dup_headline_ids:
            diagnostic_tags.append(_TAG_DUPLICATE_HEADLINE)
        if ev_id in dup_date_ticker_ids and \
                ev_id not in dup_headline_ids:
            # Avoid both tags on the same row when the headline
            # group already captures it.
            diagnostic_tags.append(_TAG_DUPLICATE_DATE_TICKER)

    market_relevance_score = _market_relevance_score(
        headline=headline,
        has_mechanism=not mechanism_missing,
        primary_ticker=primary_ticker,
        has_cache=cache_rows > 0,
        diagnostic_tags=diagnostic_tags,
    )
    if market_relevance_score < _LOW_RELEVANCE_THRESHOLD:
        diagnostic_tags.append(_TAG_LOW_MARKET_RELEVANCE)

    # Accepted-candidate / needs-review logic.  Mutual-exclusion
    # invariant: accepted_candidate co-occurs only with zero
    # exclusion-worthy tags.
    exclusion_count = sum(
        1 for t in diagnostic_tags if t in _EXCLUSION_WORTHY_TAGS
    )
    observational_count = sum(
        1 for t in diagnostic_tags if t in _OBSERVATIONAL_TAGS
    )
    accepted = exclusion_count == 0
    if accepted:
        diagnostic_tags.append(_TAG_ACCEPTED_CANDIDATE)
        if observational_count > 0:
            diagnostic_tags.append(_TAG_NEEDS_OPERATOR_REVIEW)
    else:
        if exclusion_count >= 2:
            diagnostic_tags.append(_TAG_NEEDS_OPERATOR_REVIEW)

    # Inclusion / exclusion reasons (descriptive strings).
    inclusion_reason = _inclusion_reason(section=section, event=event)
    exclusion_reason = _exclusion_reason(diagnostic_tags=diagnostic_tags)

    # Duplicate-group id is either the headline group or the
    # date_ticker group (preferring the headline one when both).
    duplicate_group_id: str | None = None
    if isinstance(ev_id, int):
        duplicate_group_id = headline_group_map.get(ev_id) or \
            date_ticker_group_map.get(ev_id)

    evidence_available = (
        primary_ticker is not None and cache_rows > 0
    )

    return {
        "event_id":               ev_id,
        "headline":               headline,
        "event_date":             event_date,
        "source_section":         section,
        "mechanism_family":       mech_family if isinstance(mech_family, str) else None,
        "primary_ticker":         primary_ticker,
        "benchmark_ticker":       benchmark_ticker,
        "inclusion_reason":       inclusion_reason,
        "exclusion_reason":       exclusion_reason,
        "duplicate_group_id":     duplicate_group_id,
        "ticker_quality":         ticker_quality,
        "market_relevance_score": market_relevance_score,
        "evidence_available":     evidence_available,
        "diagnostic_tags":        diagnostic_tags,
    }


def _benchmark_ticker_symbol(market_tickers: Any) -> str | None:
    """Try to pick a benchmark ticker.  Convention: the second
    distinct symbol in ``market_tickers``, if any.  Otherwise None
    — the diagnostic does not guess a benchmark."""
    if not isinstance(market_tickers, list):
        return None
    seen: list[str] = []
    for entry in market_tickers:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if isinstance(sym, str) and sym.strip():
            s = sym.strip().upper()
            if s not in seen:
                seen.append(s)
        if len(seen) >= 2:
            return seen[1]
    return None


def _mechanism_family_missing(family: Any, summary: Any) -> bool:
    if not isinstance(family, str):
        return True
    f = family.strip().lower()
    if not f or f == "none":
        return True
    if isinstance(summary, str) and \
            summary.strip().lower().startswith("insufficient evidence"):
        return True
    return False


def _matches_any(
    patterns: tuple[re.Pattern[str], ...], headline: Any,
) -> bool:
    if not isinstance(headline, str):
        return False
    for pat in patterns:
        if pat.search(headline):
            return True
    return False


def _market_relevance_score(
    *,
    headline:        Any,
    has_mechanism:   bool,
    primary_ticker:  str | None,
    has_cache:       bool,
    diagnostic_tags: list[str],
) -> float:
    """Coarse 0.0-1.0 relevance score in 0.1 steps.  Sum of 10
    independent +0.1 features so tests can pin the exact step
    behavior."""
    pts = 0
    if has_mechanism:
        pts += 1
    if isinstance(primary_ticker, str) and primary_ticker:
        pts += 1
    if isinstance(primary_ticker, str) and primary_ticker \
            and primary_ticker not in _BROAD_PROXY_TICKERS:
        pts += 1
    if has_cache:
        pts += 1
    if isinstance(headline, str) and headline:
        pts += 1
    if isinstance(headline, str) and 30 <= len(headline) <= 300:
        pts += 1
    if _TAG_OFF_TOPIC not in diagnostic_tags:
        pts += 1
    if _TAG_RAW_LEGAL_TEXT not in diagnostic_tags:
        pts += 1
    if _TAG_VAGUE_DIPLOMACY not in diagnostic_tags:
        pts += 1
    if _TAG_DUPLICATE_HEADLINE not in diagnostic_tags \
            and _TAG_DUPLICATE_DATE_TICKER not in diagnostic_tags:
        pts += 1
    # Pts is an int in [0, 10].  Round to 1dp to dodge float drift.
    return round(pts / 10.0, 1)


def _inclusion_reason(*, section: str, event: dict[str, Any]) -> str:
    if section == _SECTION_DAILY:
        return (
            f"appears in daily window: event timestamp within the "
            f"last {_DEFAULT_DAILY_HOURS} hours"
        )
    if section == _SECTION_WEEKLY:
        return (
            f"appears in weekly window: event timestamp within the "
            f"last {_DEFAULT_WEEKLY_DAYS} days"
        )
    return (
        f"appears in still-moving window: event timestamp between "
        f"{_DEFAULT_PERSISTENT_DAYS_MIN} and "
        f"{_DEFAULT_PERSISTENT_DAYS_MAX} days old"
    )


def _exclusion_reason(*, diagnostic_tags: list[str]) -> str:
    """Describe which proposed filters WOULD reject this candidate.
    Empty string when no exclusion-worthy tag fires.  This is a
    descriptive note, not an applied exclusion."""
    fired = [t for t in diagnostic_tags if t in _EXCLUSION_WORTHY_TAGS]
    if not fired:
        return ""
    return (
        "candidate would be flagged by the proposed "
        + ", ".join(sorted(fired))
        + " rule(s); the diagnostic does not apply any exclusion"
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Section C headline quality diagnostic", "",
    ]
    lines.append(f"OK:                            {report['ok']}")
    lines.append(f"generated_at:                  {report['generated_at']}")
    lines.append(
        f"daily_candidates:              {len(report['daily_candidates'])}"
    )
    lines.append(
        f"weekly_candidates:             {len(report['weekly_candidates'])}"
    )
    lines.append(
        f"still_moving_candidates:       {len(report['still_moving_candidates'])}"
    )
    lines.append(
        f"junk_headlines:                {len(report['junk_headlines'])}"
    )
    lines.append(
        f"duplicate_groups:              {len(report['duplicate_groups'])}"
    )
    lines.append(
        f"weak_ticker_cases:             {len(report['weak_ticker_cases'])}"
    )
    lines.append(
        f"missing_mechanism_cases:       {len(report['missing_mechanism_cases'])}"
    )
    lines.append(
        f"bad_proxy_cases:               {len(report['bad_proxy_cases'])}"
    )
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
    lines.append("")
    lines.append("Suggested filter rules (NOT applied):")
    for r in report.get("recommended_filter_rules") or []:
        lines.append(f"  - {r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C headline quality diagnostic.  "
            "Inspects what is currently entering the Daily / Weekly "
            "/ Still Moving Market surfaces and annotates each "
            "candidate with closed-vocab diagnostic tags.  Does not "
            "apply a filter, does not mutate anything.  No DB "
            "writes, no provider call, no LLM, no FastAPI."
        ),
    )
    parser.add_argument(
        "--json", dest="json_flag", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default="events.db",
        help=(
            "Path to the events SQLite DB.  Opened read-only via the "
            "file:?mode=ro URI form (default events.db).  Missing "
            "file → warning, not error."
        ),
    )
    parser.add_argument(
        "--limit-per-section", dest="limit_per_section",
        type=int, default=_DEFAULT_LIMIT_PER_SECTION,
        help=(
            f"Cap each per-section candidate list at N entries "
            f"(default {_DEFAULT_LIMIT_PER_SECTION}).  The flagged "
            f"issue lists (junk_headlines etc.) are not capped — "
            f"they always surface every flagged candidate from the "
            f"per-section pools."
        ),
    )
    parser.add_argument(
        "--daily-hours", dest="daily_hours",
        type=int, default=_DEFAULT_DAILY_HOURS,
        help=f"Daily-window size in hours (default {_DEFAULT_DAILY_HOURS}).",
    )
    parser.add_argument(
        "--weekly-days", dest="weekly_days",
        type=int, default=_DEFAULT_WEEKLY_DAYS,
        help=f"Weekly-window size in days (default {_DEFAULT_WEEKLY_DAYS}).",
    )
    parser.add_argument(
        "--persistent-days-min", dest="persistent_days_min",
        type=int, default=_DEFAULT_PERSISTENT_DAYS_MIN,
        help=(
            f"Minimum age in days for the still-moving window "
            f"(default {_DEFAULT_PERSISTENT_DAYS_MIN})."
        ),
    )
    parser.add_argument(
        "--persistent-days-max", dest="persistent_days_max",
        type=int, default=_DEFAULT_PERSISTENT_DAYS_MAX,
        help=(
            f"Maximum age in days for the still-moving window "
            f"(default {_DEFAULT_PERSISTENT_DAYS_MAX})."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = run_section_c_quality_diagnostic(
        db_path=args.db_path,
        daily_hours=int(args.daily_hours),
        weekly_days=int(args.weekly_days),
        persistent_days_min=int(args.persistent_days_min),
        persistent_days_max=int(args.persistent_days_max),
        limit_per_section=int(args.limit_per_section),
    )
    if args.json_flag:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_quality_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

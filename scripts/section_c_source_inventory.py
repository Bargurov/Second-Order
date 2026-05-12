#!/usr/bin/env python3
"""Section C source inventory — Daily / Weekly / Still Moving Market.

Read-only inventory tool that maps WHERE the three candidate streams
surfaced by ``/movers/today``, ``/movers/weekly``, and
``/movers/persistent`` currently come from in this repository.  The
inventory is hand-curated (the source map is hard-coded below) and
the script presence-checks every file path it names so a path that
no longer exists surfaces as a *warning*, not a crash.

What this script is
-------------------

* A documentation artifact: it tells an operator which scripts,
  routes, DB tables, cache tables, artifact files, and ranking /
  filter modules contribute to each of the three candidate streams.
* A read-only audit: it issues no DB queries, opens no provider,
  imports no FastAPI surface, and mutates no files.  The only
  filesystem operation is ``Path.is_file()`` to verify the recorded
  paths still exist.

What this script is NOT
-----------------------

* A filter fix — the ``suspected_quality_gaps`` field surfaces
  *observations* the inventory noticed, never prescriptions or
  remediation steps.  The constraint "Do not fix filtering yet"
  is respected by construction.
* A live status check — the script never opens the live DB, never
  calls a route, never instantiates the FastAPI app.  It cites
  paths as strings.

Output contract (JSON)::

    {
      "ok":                        bool,
      "daily_sources":             { ...per-stream block... },
      "weekly_sources":            { ...per-stream block... },
      "still_moving_sources":      { ...per-stream block... },
      "db_tables_used":            [ {"table": str, "purpose": str}, ... ],
      "scripts_used":              [ {"path": str, "purpose": str,
                                      "exists": bool}, ... ],
      "routes_used":               [ {"method": str, "path": str,
                                      "handler": str, "stream": str}, ... ],
      "ranking_fields":            [ {"module": str, "name": str,
                                      "role": str}, ... ],
      "filter_fields":             [ {"module": str, "name": str,
                                      "role": str, "stream": str}, ... ],
      "suspected_quality_gaps":    [ {"id": str, "summary": str,
                                      "streams_affected": [str, ...]}, ... ],
      "warnings":                  [str, ...],
      "errors":                    [str, ...],
    }

Each per-stream block carries::

    {
      "name":            str,            # "Daily" / "Weekly" / "Still Moving Market"
      "route":           {"method": str, "path": str, "handler": str},
      "cache_slice":     str,            # movers_cache slice key
      "window":          str,            # "24h" / "7d" / ">7d"
      "compute_fn":      str,            # "module.py:func"
      "filters_applied": [str, ...],     # function names in order
      "ranking_module":  str,            # repo-relative path
      "artifact_files":  [str, ...],     # repo-relative paths
    }

``ok`` is True iff the script ran without internal errors.  Missing
files appear in ``warnings``; a clean run with non-empty warnings is
the normal state when a referenced file has been moved.

Conservative wording — the inventory describes cache and source
geometry only.  Banned tokens in any text the script emits:
``proof``, ``proven``, ``broken``, ``wrong``, ``must fix``,
``guaranteed``, ``automatically``, ``definitely``.  Note that
``invalidated`` is intentionally NOT banned — it describes cache
invalidation, not a correctness claim.
``suspected_quality_gaps`` uses observational language only
("noticed", "may", "appears", "relies on").

Usage::

    python scripts/section_c_source_inventory.py --json
    python scripts/section_c_source_inventory.py --json \\
        --output artifacts/section_c_source_inventory.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Hard-coded source map.  Paths are repo-relative; the presence-check
# pass resolves them against ``ROOT`` and warns on misses.
# ---------------------------------------------------------------------------


_DAILY_SOURCES: dict[str, Any] = {
    "name": "Daily",
    "route": {
        "method":  "GET",
        "path":    "/movers/today",
        "handler": "routes/movers.py:2336",
    },
    "cache_slice": "market_movers",
    "window":      "24h",
    "compute_fn":  "api.py:_movers_today_compute",
    "filters_applied": [
        "movers_cache._suppress_duplicate_tickers",
        "movers_cache._is_mover_event",
        "movers_cache._dedupe_by_headline",
        "headline_registry.filter_expired_low_impact",
        "mover_card_normalizer.apply_diversity_guardrails",
    ],
    "ranking_module": "movers_ranking.py",
    "artifact_files": [],
}


_WEEKLY_SOURCES: dict[str, Any] = {
    "name": "Weekly",
    "route": {
        "method":  "GET",
        "path":    "/movers/weekly",
        "handler": "routes/movers.py:2384",
    },
    "cache_slice": "weekly",
    "window":      "7d",
    "compute_fn":  "movers_cache.py:_compute_time_slice",
    "filters_applied": [
        "movers_cache._suppress_duplicate_tickers",
        "movers_cache._is_mover_event",
        "movers_cache._dedupe_by_headline",
        "mover_card_normalizer.apply_diversity_guardrails",
    ],
    "ranking_module": "movers_ranking.py",
    "artifact_files": [],
}


_STILL_MOVING_SOURCES: dict[str, Any] = {
    "name": "Still Moving Market",
    "route": {
        "method":  "GET",
        "path":    "/movers/persistent",
        "handler": "routes/movers.py:2414",
    },
    "cache_slice": "persistent",
    "window":      ">7d",
    "compute_fn":  "movers_cache.py:_compute_persistent_slice",
    "filters_applied": [
        "movers_cache._suppress_duplicate_tickers",
        "movers_cache._is_mover_event",
        "movers_cache._dedupe_by_headline",
        "mover_card_normalizer.is_high_conviction_persistent",
    ],
    "ranking_module": "movers_ranking.py",
    "artifact_files": [],
}


_DB_TABLES_USED: list[dict[str, str]] = [
    {"table": "events",
     "purpose": "Primary event archive — source of headline, timestamp, "
                "market_tickers, persistence_signal, rating"},
    {"table": "movers_cache",
     "purpose": "Precomputed slices for /movers/* endpoints "
                "(market_movers, weekly, persistent); TTL- and "
                "fingerprint-invalidated"},
    {"table": "price_cache",
     "purpose": "Daily OHLCV + computed returns used by _is_mover_event "
                "to qualify a ticker move"},
    {"table": "headline_registry",
     "purpose": "Per-headline ingestion lifecycle (expired_at, state, "
                "last_skip_reason) read by filter_expired_low_impact"},
    {"table": "news_clusters",
     "purpose": "Clustered headlines feeding the dedupe pass; "
                "associative-only for the candidate flow"},
    {"table": "news_headline_assignments",
     "purpose": "Maps headline title_key to its cluster_id; supports "
                "the dedupe pass"},
    {"table": "curated_candidates",
     "purpose": "Operator-staged candidates referenced by short-horizon "
                "review worksheets"},
]


_SCRIPTS_USED: list[dict[str, str]] = [
    {"path": "scripts/manual_event_intake_worksheet.py",
     "purpose": "Blank intake template — produces operator worksheet "
                "rows without touching the live DB"},
    {"path": "scripts/short_horizon_review_worksheet.py",
     "purpose": "Curated short-horizon review worksheet generator "
                "consumed downstream of the candidate streams"},
    {"path": "scripts/short_horizon_review_validate_smoke.py",
     "purpose": "Validation driver for curated short-horizon review "
                "rows"},
    {"path": "scripts/showcase_candidate_shortlist.py",
     "purpose": "Read-only archive showcase query, used to inspect the "
                "candidate archive offline"},
]


_ROUTES_USED: list[dict[str, str]] = [
    {"method": "GET", "path": "/movers/today",
     "handler": "routes/movers.py:2336", "stream": "Daily"},
    {"method": "GET", "path": "/movers/weekly",
     "handler": "routes/movers.py:2384", "stream": "Weekly"},
    {"method": "GET", "path": "/movers/persistent",
     "handler": "routes/movers.py:2414",
     "stream": "Still Moving Market"},
]


_RANKING_FIELDS: list[dict[str, str]] = [
    {"module": "movers_ranking.py", "name": "compute_rank_score",
     "role": "Maps agreement tier + max move + persistence signal to "
             "the final rank score for a candidate"},
    {"module": "movers_ranking.py", "name": "classify_tier",
     "role": "Verdict-to-tier mapping (e.g., confirmed → "
             "strong_confirmation)"},
    {"module": "movers_ranking.py", "name": "_TIER_WEIGHT",
     "role": "Numeric weights per agreement tier feeding "
             "compute_rank_score"},
    {"module": "movers_ranking.py", "name": "_PERSISTENCE_BONUS",
     "role": "Per-persistence-signal additive adjustment applied "
             "after the tier weight"},
]


_FILTER_FIELDS: list[dict[str, str]] = [
    {"module": "movers_cache.py", "name": "_is_mover_event",
     "role": "Requires at least one ticker with a non-null return_5d; "
             "drops events without populated price_cache rows",
     "stream": "all"},
    {"module": "movers_cache.py", "name": "_dedupe_by_headline",
     "role": "Keeps the first occurrence per headline cluster across "
             "the slice window",
     "stream": "all"},
    {"module": "movers_cache.py", "name": "_suppress_duplicate_tickers",
     "role": "Suppresses yfinance race signatures that would surface "
             "the same ticker twice in one event",
     "stream": "all"},
    {"module": "headline_registry.py",
     "name": "filter_expired_low_impact",
     "role": "Drops rows the registry marks as expired or low-impact",
     "stream": "Daily"},
    {"module": "mover_card_normalizer.py",
     "name": "apply_diversity_guardrails",
     "role": "Limits the count of any single ticker/cluster so the "
             "slice does not become single-name-dominated",
     "stream": "Daily, Weekly"},
    {"module": "mover_card_normalizer.py",
     "name": "is_high_conviction_persistent",
     "role": "Hard filter for the persistent slice — keeps only "
             "Accelerating / Holding signals at the top",
     "stream": "Still Moving Market"},
]


# Observational, never prescriptive.  Each entry describes what the
# inventory noticed; the constraint "Do not fix filtering yet" forbids
# remediation language here.
_SUSPECTED_QUALITY_GAPS: list[dict[str, Any]] = [
    {
        "id": "shared_return_5d_dependency",
        "summary": (
            "All three streams rely on _is_mover_event, which requires "
            "a non-null return_5d in price_cache.  Events whose tickers "
            "are not present in price_cache may drop silently from the "
            "slice; the inventory noticed this shared dependency and "
            "does not recommend a change here."
        ),
        "streams_affected": ["Daily", "Weekly", "Still Moving Market"],
    },
    {
        "id": "headline_dedupe_first_occurrence",
        "summary": (
            "_dedupe_by_headline keeps the first occurrence per cluster "
            "across the slice window.  The inventory noticed this; a "
            "later headline with stronger evidence on the same cluster "
            "may not surface unless the first occurrence is suppressed "
            "upstream."
        ),
        "streams_affected": ["Daily", "Weekly", "Still Moving Market"],
    },
    {
        "id": "persistent_overfetch_fallback",
        "summary": (
            "_compute_persistent_slice over-fetches before applying "
            "is_high_conviction_persistent and falls back to any mover "
            "when the strict Accelerating/Holding set is empty.  The "
            "inventory noticed this fallback path."
        ),
        "streams_affected": ["Still Moving Market"],
    },
    {
        "id": "diversity_guardrail_scope",
        "summary": (
            "apply_diversity_guardrails runs on the Daily and Weekly "
            "slices but not on the persistent slice; the inventory "
            "noticed the scope difference."
        ),
        "streams_affected": ["Daily", "Weekly"],
    },
    {
        "id": "daily_low_impact_filter_only",
        "summary": (
            "headline_registry.filter_expired_low_impact is applied on "
            "the Daily slice but is not in the Weekly or persistent "
            "filter chains the inventory recorded.  Operator may want "
            "to confirm whether this scope difference is intentional."
        ),
        "streams_affected": ["Daily"],
    },
]


# ---------------------------------------------------------------------------
# Patchable seam — filesystem existence check
# ---------------------------------------------------------------------------


def _path_exists(*, relative_path: str) -> bool:
    """Return True if ``relative_path`` resolves to an existing
    regular file under ``ROOT``.  Patched in tests to drive the
    missing-file warning path without touching real files.
    """
    if not relative_path:
        return False
    # ``relative_path`` carries a "file:line" suffix for route
    # handlers; the existence check uses only the file half.
    base = relative_path.split(":", 1)[0]
    return (ROOT / base).is_file()


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_section_c_source_inventory(
    *, output_path: str | None = None,
) -> dict[str, Any]:
    """Build the Section C source inventory.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    daily      = _annotate_stream(_DAILY_SOURCES,        warnings)
    weekly     = _annotate_stream(_WEEKLY_SOURCES,       warnings)
    persistent = _annotate_stream(_STILL_MOVING_SOURCES, warnings)

    scripts_used = [
        {
            "path":    item["path"],
            "purpose": item["purpose"],
            "exists":  _check_and_warn(
                relative_path=item["path"],
                description=f"script {item['path']}",
                warnings=warnings,
            ),
        }
        for item in _SCRIPTS_USED
    ]

    routes_used = []
    for item in _ROUTES_USED:
        exists = _check_and_warn(
            relative_path=item["handler"],
            description=f"route handler {item['handler']}",
            warnings=warnings,
        )
        routes_used.append({
            "method":  item["method"],
            "path":    item["path"],
            "handler": item["handler"],
            "stream":  item["stream"],
            "exists":  exists,
        })

    ranking_fields = [dict(item) for item in _RANKING_FIELDS]
    for entry in ranking_fields:
        _check_and_warn(
            relative_path=entry["module"],
            description=f"ranking module {entry['module']}",
            warnings=warnings,
        )

    filter_fields = [dict(item) for item in _FILTER_FIELDS]
    for entry in filter_fields:
        _check_and_warn(
            relative_path=entry["module"],
            description=f"filter module {entry['module']}",
            warnings=warnings,
        )

    return _finalize(
        envelope={
            "ok":                     not errors,
            "daily_sources":          daily,
            "weekly_sources":         weekly,
            "still_moving_sources":   persistent,
            "db_tables_used":         [dict(t) for t in _DB_TABLES_USED],
            "scripts_used":           scripts_used,
            "routes_used":            routes_used,
            "ranking_fields":         ranking_fields,
            "filter_fields":          filter_fields,
            "suspected_quality_gaps": [dict(g) for g in _SUSPECTED_QUALITY_GAPS],
            "warnings":               warnings,
            "errors":                 errors,
        },
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _annotate_stream(
    block: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    """Return a copy of ``block`` with each referenced path
    presence-checked.  The block itself is not mutated.
    """
    out = dict(block)
    route = dict(block.get("route") or {})
    out["route"] = route
    _check_and_warn(
        relative_path=route.get("handler", ""),
        description=(
            f"route handler {route.get('handler', '')} for "
            f"stream {block.get('name')!r}"
        ),
        warnings=warnings,
    )
    ranking = block.get("ranking_module")
    if isinstance(ranking, str) and ranking:
        _check_and_warn(
            relative_path=ranking,
            description=(
                f"ranking module {ranking} for stream "
                f"{block.get('name')!r}"
            ),
            warnings=warnings,
        )
    compute = block.get("compute_fn")
    if isinstance(compute, str) and compute:
        _check_and_warn(
            relative_path=compute,
            description=(
                f"compute_fn host {compute} for stream "
                f"{block.get('name')!r}"
            ),
            warnings=warnings,
        )
    artifact_files = list(block.get("artifact_files") or [])
    for af in artifact_files:
        _check_and_warn(
            relative_path=af,
            description=(
                f"artifact file {af} for stream {block.get('name')!r}"
            ),
            warnings=warnings,
        )
    out["artifact_files"] = artifact_files
    out["filters_applied"] = list(block.get("filters_applied") or [])
    return out


def _check_and_warn(
    *, relative_path: str, description: str, warnings: list[str],
) -> bool:
    if not relative_path:
        return False
    if _path_exists(relative_path=relative_path):
        return True
    warnings.append(
        f"missing source: {description} resolved to a path that no "
        f"longer exists ({relative_path})"
    )
    return False


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
            "Read-only Section C source inventory.  Reports where the "
            "Daily, Weekly, and Still Moving Market candidate streams "
            "currently come from (scripts, routes, DB tables, cache "
            "tables, artifacts, ranking and filter modules).  Issues "
            "no DB queries, opens no provider, imports no FastAPI "
            "surface, and mutates no files.  Missing paths surface "
            "as warnings, never as crashes."
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
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON inventory to.  When "
            "omitted, the inventory has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = build_section_c_source_inventory(
        output_path=args.output_path,
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_section_c_source_inventory",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

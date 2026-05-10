#!/usr/bin/env python3
"""Read-only repaired-cohort expansion candidate discovery report.

Joins five existing read-only archive reports — contamination,
missing-tickers, short-horizon readiness, clean-cohort, and
cleanup-candidate — through patchable seams to surface the next
realistic candidates for growing ``repaired_clean_event_ids`` from 5
toward 10–15.

The report does NOT propose tickers, NOT assign mechanism families,
and NOT touch the archive.  Every event surfaced is a "manual review
candidate" — operator inspection still required.  The estimated
repair yield is an *estimate*, not a forecast or an alpha claim.

Buckets (mutually exclusive)
----------------------------

  1. ``mechanism_family_only_ready`` — fully-ready contamination
     examples whose flag set is exactly ``{mechanism_family_none}``
     or ``{mechanism_family_none, duplicate_date_ticker}``.  These
     are the cleanest expansion path: a manual mechanism-family
     label moves the event into the repaired cohort with no ticker
     work.
  2. ``ticker_repair_needed`` — contamination flag includes
     ``driv_lit_off_topic`` (DRIV/LIT thematic mismatch) OR the
     event surfaces in the missing-tickers report (no usable
     primary symbol).  Repair requires an operator-supplied ticker.
  3. ``duplicate_only_review`` — fully-ready contamination flag set
     is exactly ``{duplicate_date_ticker}``.  Manual-aware promotion
     candidate when the operator excludes the duplicate partner.
  4. ``short_horizon_only`` — short-horizon-ready (1d/5d) but NOT
     fully-ready (20d).  Belongs to the short-horizon repaired
     cohort, not the full one.
  5. ``likely_junk`` — cleanup-candidate match (test fixture phrase,
     rotating macro template, fixture timestamp cluster, duplicate
     headline) OR contamination flag ``local_off_topic_headline``.
     Surfaced for visibility but excluded from the actionable
     ``candidate_count`` and ``top_candidates``.

Group priority on conflict
--------------------------

When an event matches multiple sources, the assignment rule is::

    likely_junk          (filter-first; never overridden)
    mechanism_family_only_ready
    duplicate_only_review
    ticker_repair_needed
    short_horizon_only

Reviewed-id exclusion
---------------------

Twenty-eight already-reviewed event_ids are dropped before bucketing
and before any aggregate count.  The set lives in
:data:`_EXCLUDED_EVENT_IDS`; tests pin both its size (28) and its
membership.

Output contract::

    {
      "candidate_count":         int,    # total in actionable groups
                                          # (excludes likely_junk)
      "groups": {
        "mechanism_family_only_ready": {"count": int, "event_ids": [int, ...]},
        "ticker_repair_needed":        {"count": int, "event_ids": [int, ...]},
        "duplicate_only_review":       {"count": int, "event_ids": [int, ...]},
        "short_horizon_only":          {"count": int, "event_ids": [int, ...]},
        "likely_junk":                 {"count": int, "event_ids": [int, ...]},
      },
      "top_candidates": [                 # capped at --limit, priority-
                                          # ordered, likely_junk excluded
        {
          "event_id": int,
          "headline": str | None,
          "group":    str,                # one of the four actionable groups
          "reason":   str,
        },
        ...
      ],
      "estimated_repair_yield": {
        "conservative_estimate": int,     # mechanism_family_only_ready only
        "optimistic_estimate":   int,     # all four actionable groups
        "estimate_basis":        str,
      },
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  All DB reads flow through the upstream reports'
  SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never proposes tickers or mechanism families; surfaced rows are
  manual review candidates only.

Conservative wording — banned tokens (``proof``, ``automatically``,
``deletes``, ``replaces``, ``correct ticker``) never appear in any
text the report emits.

Usage::

    python scripts/repaired_cohort_expansion_candidate_report.py
    python scripts/repaired_cohort_expansion_candidate_report.py --json
    python scripts/repaired_cohort_expansion_candidate_report.py --json --limit 50
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


_DEFAULT_LIMIT: int = 25

# Effectively unlimited per-row cap when delegating to upstream
# reports — we need every row to bucket correctly.  The operator's
# ``--limit`` only truncates the emitted top_candidates list.
_UPSTREAM_FETCH_ALL: int = 10**12


# Twenty-eight already-reviewed event_ids — pinned in tests by both
# count and membership.  Future review batches should grow this set
# explicitly so reviewers notice the cohort change.
_EXCLUDED_EVENT_IDS: frozenset[int] = frozenset({
    4, 6, 8, 9,
    30, 40, 44, 46, 47, 49, 51,
    60, 63, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
})


_GROUP_NAMES: tuple[str, ...] = (
    "mechanism_family_only_ready",
    "ticker_repair_needed",
    "duplicate_only_review",
    "short_horizon_only",
    "likely_junk",
)


_ACTIONABLE_GROUPS: tuple[str, ...] = (
    "mechanism_family_only_ready",
    "duplicate_only_review",
    "ticker_repair_needed",
    "short_horizon_only",
)


# Group priority for top_candidates ordering — lower number wins.
_GROUP_PRIORITY: dict[str, int] = {
    "mechanism_family_only_ready": 0,
    "duplicate_only_review":       1,
    "ticker_repair_needed":        2,
    "short_horizon_only":          3,
    "likely_junk":                 99,  # never surfaced in top_candidates
}


# Per-group reason tokens — short, conservative, banned-word-free.
_GROUP_REASONS: dict[str, str] = {
    "mechanism_family_only_ready":
        "Fully-ready event blocked only by missing mechanism_family; "
        "manual review candidate, no ticker work needed.",
    "ticker_repair_needed":
        "Manual review candidate — primary ticker is missing or "
        "thematically mismatched; operator must supply a ticker by hand.",
    "duplicate_only_review":
        "Manual review candidate — flagged solely as a duplicate "
        "(event_date, primary_ticker) row; manual-aware promotion is "
        "possible if the partner is excluded.",
    "short_horizon_only":
        "Short-horizon (1d/5d) candidate; not eligible for the 20d "
        "fully-ready cohort.",
    "likely_junk":
        "Cleanup-candidate match (seed-like / test-fixture / off-topic "
        "headline); not surfaced as an actionable repair target.",
}


_RECOMMENDED_EMPTY = (
    "No actionable repair candidates surfaced — re-run after the next "
    "archive ingestion or expand the upstream contamination scan."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} actionable manual review candidate(s) surfaced across "
    "{g} groups.  Estimated repair yield is conservative ({c}) to "
    "optimistic ({o}); operator must inspect each headline by hand "
    "before assigning tickers or mechanism families.  Repaired cohort "
    "evidence only — not an aggregate validation claim."
)


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  The lazy imports resolve only on the un-patched path so
# default-run import isolation is preserved.
# ---------------------------------------------------------------------------


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(
        db_path=db_path, limit=_UPSTREAM_FETCH_ALL,
    )


def _run_missing_tickers_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_missing_tickers_report import (
        summarize_missing_tickers,
    )

    return summarize_missing_tickers(
        db_path=db_path, limit=_UPSTREAM_FETCH_ALL,
    )


def _run_short_horizon_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_short_horizon_readiness_report import (
        summarize_short_horizon_readiness,
    )

    return summarize_short_horizon_readiness(
        db_path=db_path, limit=_UPSTREAM_FETCH_ALL,
    )


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(db_path=db_path, limit=_UPSTREAM_FETCH_ALL)


def _run_cleanup_candidate_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.archive_cleanup_candidate_report import (
        summarize_cleanup_candidates,
    )

    return summarize_cleanup_candidates(
        db_path=db_path, limit=_UPSTREAM_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_expansion_candidates(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the expansion-candidate discovery payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    contamination     = _safe_dict(_run_contamination_report(db_path=db_path))
    missing_tickers   = _safe_dict(_run_missing_tickers_report(db_path=db_path))
    short_horizon     = _safe_dict(_run_short_horizon_report(db_path=db_path))
    clean_cohort      = _safe_dict(_run_clean_cohort_report(db_path=db_path))
    cleanup_candidates = _safe_dict(
        _run_cleanup_candidate_report(db_path=db_path)
    )

    # Pre-compute the junk set first; it filters every other bucket.
    junk_ids, junk_meta = _collect_junk(contamination, cleanup_candidates)

    already_clean_ids = _event_ids_from_clean_cohort(clean_cohort)

    # Per-event metadata cache — first writer wins, so contamination
    # examples (richer headline) take precedence over the missing-
    # tickers report's lighter projection.
    metadata: dict[int, dict[str, Any]] = {}

    def _record_meta(ev_id: int, headline: Any) -> None:
        if ev_id not in metadata:
            metadata[ev_id] = {"headline": headline}

    # ---- bucket assignment ---------------------------------------------
    buckets: dict[str, list[int]] = {name: [] for name in _GROUP_NAMES}
    seen: set[int] = set()

    def _try_assign(ev_id: int, group: str) -> bool:
        if ev_id in _EXCLUDED_EVENT_IDS:
            return False
        if ev_id in already_clean_ids:
            # Already in repaired cohort — no point surfacing.
            return False
        if ev_id in seen:
            return False
        if group != "likely_junk" and ev_id in junk_ids:
            # Junk wins: skip non-junk assignments for junk events.
            return False
        buckets[group].append(ev_id)
        seen.add(ev_id)
        return True

    # 1. likely_junk first — a junk event must NEVER land in a
    # downstream bucket.
    for ev_id in sorted(junk_ids):
        if ev_id in _EXCLUDED_EVENT_IDS or ev_id in already_clean_ids:
            continue
        if ev_id in seen:
            continue
        buckets["likely_junk"].append(ev_id)
        seen.add(ev_id)
        meta = junk_meta.get(ev_id) or {}
        _record_meta(ev_id, meta.get("headline"))

    # 2-4. contamination-driven buckets.
    for example in contamination.get("examples") or []:
        if not isinstance(example, dict):
            continue
        ev_id = example.get("event_id")
        if not isinstance(ev_id, int):
            continue
        flags_raw = example.get("flags")
        flag_set = (
            {f for f in flags_raw if isinstance(f, str)}
            if isinstance(flags_raw, list) else set()
        )

        # mechanism_family_only_ready
        if (
            "mechanism_family_none" in flag_set
            and not (flag_set & {"local_off_topic_headline",
                                 "driv_lit_off_topic"})
            and (flag_set - {"mechanism_family_none",
                             "duplicate_date_ticker"} == set())
        ):
            if _try_assign(ev_id, "mechanism_family_only_ready"):
                _record_meta(ev_id, example.get("headline"))
                continue

        # duplicate_only_review — exactly {duplicate_date_ticker}.
        if flag_set == {"duplicate_date_ticker"}:
            if _try_assign(ev_id, "duplicate_only_review"):
                _record_meta(ev_id, example.get("headline"))
                continue

        # ticker_repair_needed — driv_lit_off_topic anywhere in flags.
        if "driv_lit_off_topic" in flag_set:
            if _try_assign(ev_id, "ticker_repair_needed"):
                _record_meta(ev_id, example.get("headline"))
                continue

    # ticker_repair_needed (continued) — events surfaced by
    # missing_tickers that didn't already land in another bucket.
    for event in missing_tickers.get("events") or []:
        if not isinstance(event, dict):
            continue
        ev_id = event.get("event_id")
        if not isinstance(ev_id, int):
            continue
        if _try_assign(ev_id, "ticker_repair_needed"):
            _record_meta(ev_id, event.get("headline"))

    # 5. short_horizon_only — delta_eligible rows from short-horizon
    # readiness that didn't already land elsewhere.
    for example in short_horizon.get("examples") or []:
        if not isinstance(example, dict):
            continue
        if not example.get("delta_eligible"):
            continue
        ev_id = example.get("event_id")
        if not isinstance(ev_id, int):
            continue
        if _try_assign(ev_id, "short_horizon_only"):
            _record_meta(ev_id, example.get("headline"))

    # ---- aggregates -----------------------------------------------------
    groups_payload: dict[str, dict[str, Any]] = {
        name: {
            "count":     len(buckets[name]),
            "event_ids": sorted(buckets[name]),
        }
        for name in _GROUP_NAMES
    }

    candidate_count = sum(
        groups_payload[name]["count"] for name in _ACTIONABLE_GROUPS
    )

    top_candidates = _build_top_candidates(
        buckets=buckets, metadata=metadata, limit=capped_limit,
    )

    yield_block = _estimate_repair_yield(groups_payload)

    if candidate_count <= 0:
        recommended = _RECOMMENDED_EMPTY
    else:
        active_groups = sum(
            1 for name in _ACTIONABLE_GROUPS
            if groups_payload[name]["count"] > 0
        )
        recommended = _RECOMMENDED_HAS_CANDIDATES.format(
            n=candidate_count, g=active_groups,
            c=yield_block["conservative_estimate"],
            o=yield_block["optimistic_estimate"],
        )

    return {
        "candidate_count":         candidate_count,
        "groups":                  groups_payload,
        "top_candidates":          top_candidates,
        "estimated_repair_yield":  yield_block,
        "recommended_next_action": recommended,
    }


def _collect_junk(
    contamination: dict[str, Any], cleanup_candidates: dict[str, Any],
) -> tuple[set[int], dict[int, dict[str, Any]]]:
    """Return (junk_ids, junk_metadata).  An event is junk if it
    matches the cleanup-candidate report (any reason) OR carries a
    contamination flag of ``local_off_topic_headline``.
    """
    junk_ids: set[int] = set()
    meta: dict[int, dict[str, Any]] = {}

    for example in cleanup_candidates.get("examples") or []:
        if not isinstance(example, dict):
            continue
        ev_id = example.get("event_id")
        if isinstance(ev_id, int):
            junk_ids.add(ev_id)
            meta[ev_id] = {"headline": example.get("headline")}

    for example in contamination.get("examples") or []:
        if not isinstance(example, dict):
            continue
        ev_id = example.get("event_id")
        if not isinstance(ev_id, int):
            continue
        flags_raw = example.get("flags")
        flag_set = (
            {f for f in flags_raw if isinstance(f, str)}
            if isinstance(flags_raw, list) else set()
        )
        if "local_off_topic_headline" in flag_set:
            junk_ids.add(ev_id)
            meta.setdefault(ev_id, {"headline": example.get("headline")})

    return junk_ids, meta


def _event_ids_from_clean_cohort(payload: dict[str, Any]) -> set[int]:
    raw = payload.get("clean_fully_ready_event_ids")
    out: set[int] = set()
    if isinstance(raw, list):
        for i in raw:
            if isinstance(i, int):
                out.add(i)
    return out


def _build_top_candidates(
    *, buckets: dict[str, list[int]],
    metadata: dict[int, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Compose the priority-ordered top_candidates list.  Junk is
    excluded; remaining groups appear in priority order; within each
    group, event_ids ascend.  Capped at ``limit``."""
    out: list[dict[str, Any]] = []
    ordered_groups = sorted(
        _ACTIONABLE_GROUPS, key=lambda g: _GROUP_PRIORITY.get(g, 99),
    )
    for group in ordered_groups:
        for ev_id in sorted(buckets.get(group, [])):
            if len(out) >= limit:
                return out
            meta = metadata.get(ev_id) or {}
            out.append({
                "event_id": ev_id,
                "headline": meta.get("headline"),
                "group":    group,
                "reason":   _GROUP_REASONS.get(group, ""),
            })
    return out


def _estimate_repair_yield(
    groups_payload: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Conservative repair-yield estimate.

    * conservative = ``mechanism_family_only_ready`` count alone
      (cleanest path: no ticker work).
    * optimistic   = sum of every actionable group's count
      (best-case where every surfaced candidate clears manual review).
    """
    conservative = int(
        groups_payload["mechanism_family_only_ready"]["count"]
    )
    optimistic = sum(
        int(groups_payload[g]["count"]) for g in _ACTIONABLE_GROUPS
    )
    return {
        "conservative_estimate": conservative,
        "optimistic_estimate":   optimistic,
        "estimate_basis": (
            "Conservative estimate counts the mechanism-family-only "
            "ready bucket; optimistic estimate sums every actionable "
            "group.  Both are repair-yield estimates, not aggregate "
            "validation claims."
        ),
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Repaired-cohort expansion candidate report", ""]
    lines.append(f"Candidate count (actionable):   {report['candidate_count']}")
    yld = report.get("estimated_repair_yield") or {}
    lines.append(
        f"Conservative repair-yield estimate: "
        f"{yld.get('conservative_estimate', 0)}"
    )
    lines.append(
        f"Optimistic repair-yield estimate:   "
        f"{yld.get('optimistic_estimate', 0)}"
    )
    lines.append("")
    lines.append("Per-group counts:")
    for name in _GROUP_NAMES:
        block = report["groups"].get(name) or {}
        lines.append(
            f"  {name:<30} count={block.get('count', 0):>4}"
        )
    lines.append("")
    top = report.get("top_candidates") or []
    lines.append(f"Top candidates ({len(top)}):")
    for rec in top:
        headline = (rec.get("headline") or "-")
        if len(headline) > 100:
            headline = headline[:97] + "..."
        lines.append(
            f"  id={rec.get('event_id')}  "
            f"group={rec.get('group')}"
        )
        lines.append(f"      headline: {headline}")
    lines.append("")
    lines.append(
        f"Recommended next action: {report['recommended_next_action']}"
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only repaired-cohort expansion candidate discovery "
            "report.  Joins five upstream reports through patchable "
            "seams and buckets archive events into five mutually-"
            "exclusive groups (mechanism_family_only_ready, "
            "ticker_repair_needed, duplicate_only_review, "
            "short_horizon_only, likely_junk).  Drops 28 already-"
            "reviewed event_ids before bucketing.  Read-only — never "
            "assigns tickers or mechanism families, never edits the "
            "archive, no provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced top_candidates list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every bucketed event."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
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

    report = summarize_expansion_candidates(
        db_path=args.db_path, limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

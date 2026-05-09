#!/usr/bin/env python3
"""Read-only showcase candidate shortlist.

Answers the operator question, "given today's archive, which events
are the strongest demo candidates after we exclude every contaminated
fully-ready row?"

The shortlist starts from the per-event signal records produced by
the event-study run and filters them down by (a) excluding any
contaminated event_id and (b) projecting the readiness state onto
each remaining record.  Each surviving event is scored by combining
its signal magnitude with its readiness state — clean fully-ready
candidates outrank events of equal magnitude that still carry a
mechanical or manual blocker.

Three patchable seams compose the shortlist:

  * ``_run_archive_stat_validation``       — per-event/horizon signal
                                              records (event_id,
                                              ticker, headline,
                                              abnormal_return,
                                              interpretation).
  * ``_run_ticker_contamination_report``   — list of contaminated
                                              event_ids whose primary
                                              ticker looks topically
                                              suspicious.
  * ``_run_clean_cohort_report``           — clean fully-ready
                                              event_ids and the
                                              ``next_salvage_candidates``
                                              buckets used to derive
                                              ``current_blocker``.

Score model
-----------

For each (un-contaminated) event::

    max_abs_ar       = max |abnormal_return| across the horizons we
                       have records for, on this event_id
    significance_bonus = 0.50 if any horizon's interpretation is
                       "significant", else 0.00
    readiness_factor =
       1.0  if event_id is in the clean fully-ready cohort,
       0.4  if event_id is blocked by a mechanical bucket
            (price-cache backfill / benchmark proxy /
             estimation-window gap),
       0.2  if event_id is blocked by a manual-review bucket,
       0.0  otherwise.

    showcase_score   = (max_abs_ar + significance_bonus) * readiness_factor

The score is rounded to four decimals.  Candidates are returned in
``showcase_score`` descending order; ties resolve by ``event_id``
ascending so the surfaced sample is deterministic.

Output contract::

    {
      "ok":                      bool,
      "candidate_count":         int,           # full population
      "candidates": [                            # capped at --limit
        {
          "event_id":       int,
          "headline":       str | None,
          "reason":         str,
          "current_blocker": str | None,
          "ticker_status":   "primary_ticker_set" | "missing",
          "showcase_score":  float,
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own.
* No DB writes, no LLM, no ``yfinance``, no provider call, no
  network.
* No FastAPI app surface.
* Never proposes ticker assignments; never refreshes prices; never
  ranks contaminated events — exclusion is hard, not a low-score
  nudge.

Usage::

    python scripts/showcase_candidate_shortlist.py
    python scripts/showcase_candidate_shortlist.py --json
    python scripts/showcase_candidate_shortlist.py --json --limit 20
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

_REPORT_FETCH_ALL: int = 10**12


_MECHANICAL_BLOCKERS: frozenset[str] = frozenset({
    "missing_forward_cache_1d",
    "missing_forward_cache_5d",
    "missing_forward_cache_20d",
    "missing_benchmark_proxy",
    "insufficient_estimation_window",
})


_RECOMMENDED_NO_RECORDS = (
    "Archive carries no per-event signal records — no showcase "
    "candidates can be ranked until the event-study compute has "
    "produced records for at least one event."
)
_RECOMMENDED_ALL_CONTAMINATED = (
    "Every event with signal records appears contaminated.  The "
    "candidate shortlist is empty until those events undergo manual "
    "ticker review or new clean events accumulate signal."
)
_RECOMMENDED_HAVE_CANDIDATES = (
    "{n} candidate events surfaced, ranked by signal magnitude × "
    "readiness factor.  Treat showcase_score as a relative ranking, "
    "not a causal claim — significance still depends on FDR-controlled "
    "interpretation per horizon."
)


# ---------------------------------------------------------------------------
# Lazy seams
# ---------------------------------------------------------------------------


def _run_archive_stat_validation(*, db_path: str | None) -> dict[str, Any]:
    from scripts.archive_stat_validation_run import (
        run_archive_stat_validation,
    )

    return run_archive_stat_validation(db_path=db_path)


def _run_ticker_contamination_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_showcase_candidates(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the showcase candidate shortlist payload.

    See module docstring for the full contract.
    """
    capped_limit = max(int(limit), 0)

    archive       = _safe_dict(_run_archive_stat_validation(db_path=db_path))
    contamination = _safe_dict(
        _run_ticker_contamination_report(db_path=db_path))
    cohort        = _safe_dict(_run_clean_cohort_report(db_path=db_path))

    contaminated_ids = _collect_contaminated_ids(
        contamination=contamination, cohort=cohort,
    )
    clean_ids = _collect_clean_ids(cohort)
    blocker_map = _build_blocker_map(cohort)

    by_event = _aggregate_signal_per_event(
        archive_records=archive.get("examples") or [],
        contaminated_ids=contaminated_ids,
    )

    candidates: list[dict[str, Any]] = []
    for eid, slot in by_event.items():
        readiness, blocker = _resolve_readiness(
            event_id=eid, clean_ids=clean_ids, blocker_map=blocker_map,
        )
        sig_bonus = 0.5 if slot["any_significant"] else 0.0
        score = round(
            (slot["max_abs_ar"] + sig_bonus) * readiness, 4
        )
        ticker = slot.get("ticker")
        ticker_status = (
            "primary_ticker_set"
            if isinstance(ticker, str) and ticker
            else "missing"
        )
        candidates.append({
            "event_id":        eid,
            "headline":        slot.get("headline"),
            "reason":          _build_reason(slot),
            "current_blocker": blocker,
            "ticker_status":   ticker_status,
            "showcase_score":  score,
        })

    # Sort: score desc, then id asc on ties.
    candidates.sort(key=lambda c: (-_safe_float(c["showcase_score"]),
                                    _safe_int(c["event_id"])))

    recommended = _recommend(
        records_count=_safe_int(archive.get("records_count")),
        candidate_count=len(candidates),
        contaminated_count=len(contaminated_ids),
    )

    return {
        "ok":                       True,
        "candidate_count":          len(candidates),
        "candidates":               candidates[:capped_limit],
        "recommended_next_action":  recommended,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _collect_contaminated_ids(
    *, contamination: dict[str, Any], cohort: dict[str, Any],
) -> set[int]:
    out: set[int] = set()
    for source_key, host in (
        ("examples", contamination),
        ("excluded_fully_ready_examples", cohort),
    ):
        for entry in host.get(source_key) or []:
            if not isinstance(entry, dict):
                continue
            eid = entry.get("event_id")
            if isinstance(eid, int):
                out.add(eid)
    return out


def _collect_clean_ids(cohort: dict[str, Any]) -> set[int]:
    return {
        int(i) for i in (cohort.get("clean_fully_ready_event_ids") or [])
        if isinstance(i, int)
    }


def _build_blocker_map(cohort: dict[str, Any]) -> dict[int, str]:
    """Project the cohort's ``next_salvage_candidates`` dict into
    ``{event_id: bucket_name}``.  An event present in multiple
    buckets keeps the FIRST bucket encountered — the iteration order
    follows the upstream report's order, which is itself the stable
    preference order (mechanical buckets first).
    """
    out: dict[int, str] = {}
    salvage = cohort.get("next_salvage_candidates") or {}
    if not isinstance(salvage, dict):
        return out
    for bucket_name, bucket in salvage.items():
        if not isinstance(bucket, dict):
            continue
        for c in bucket.get("candidates") or []:
            if not isinstance(c, dict):
                continue
            eid = c.get("event_id")
            if isinstance(eid, int) and eid not in out:
                out[eid] = str(bucket_name)
    return out


def _aggregate_signal_per_event(
    *,
    archive_records: Sequence[Any],
    contaminated_ids: set[int],
) -> dict[int, dict[str, Any]]:
    by_event: dict[int, dict[str, Any]] = {}
    for r in archive_records:
        if not isinstance(r, dict):
            continue
        eid = r.get("event_id")
        if not isinstance(eid, int):
            continue
        if eid in contaminated_ids:
            continue
        slot = by_event.get(eid)
        if slot is None:
            slot = {
                "event_id":           eid,
                "headline":           r.get("headline"),
                "ticker":             r.get("ticker"),
                "max_abs_ar":         0.0,
                "max_abs_ar_horizon": None,
                "any_significant":    False,
            }
            by_event[eid] = slot
        ar = r.get("abnormal_return")
        if isinstance(ar, (int, float)):
            mag = abs(float(ar))
            if mag > slot["max_abs_ar"]:
                slot["max_abs_ar"]         = mag
                slot["max_abs_ar_horizon"] = r.get("horizon")
        if r.get("interpretation") == "significant":
            slot["any_significant"] = True
        # Backfill headline / ticker if the first record had None for them.
        if not slot.get("headline") and r.get("headline"):
            slot["headline"] = r.get("headline")
        if not slot.get("ticker") and r.get("ticker"):
            slot["ticker"] = r.get("ticker")
    return by_event


def _resolve_readiness(
    *,
    event_id: int, clean_ids: set[int],
    blocker_map: dict[int, str],
) -> tuple[float, str | None]:
    if event_id in clean_ids:
        return 1.0, None
    blocker = blocker_map.get(event_id)
    if blocker is None:
        return 0.0, None
    if blocker in _MECHANICAL_BLOCKERS:
        return 0.4, blocker
    return 0.2, blocker


def _build_reason(slot: dict[str, Any]) -> str:
    mag = slot.get("max_abs_ar") or 0.0
    horizon = slot.get("max_abs_ar_horizon")
    sig = " (significant at one or more horizons)" \
        if slot.get("any_significant") else ""
    if horizon is None:
        return f"|abnormal_return|={mag:.4f}{sig}"
    return f"|abnormal_return|={mag:.4f} at horizon {horizon}{sig}"


def _recommend(
    *,
    records_count: int, candidate_count: int, contaminated_count: int,
) -> str:
    if records_count <= 0:
        return _RECOMMENDED_NO_RECORDS
    if candidate_count <= 0 and contaminated_count > 0:
        return _RECOMMENDED_ALL_CONTAMINATED
    if candidate_count <= 0:
        return _RECOMMENDED_NO_RECORDS
    return _RECOMMENDED_HAVE_CANDIDATES.format(n=candidate_count)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Showcase candidate shortlist", ""]
    lines.append(
        f"Candidate count:  {report['candidate_count']}"
    )
    candidates = report.get("candidates") or []
    lines.append(f"Listed ({len(candidates)}):")
    if candidates:
        for c in candidates:
            lines.append(
                f"  id={c.get('event_id')} "
                f"score={c.get('showcase_score')} "
                f"blocker={c.get('current_blocker') or '-'} "
                f"ticker={c.get('ticker_status')} "
                f"headline={(c.get('headline') or '-')[:60]!r}"
            )
    else:
        lines.append("  -")
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
            "Read-only showcase candidate shortlist.  Ranks events "
            "by signal magnitude × readiness factor, after excluding "
            "every contaminated fully-ready row.  Read-only: no "
            "INSERT/UPDATE/DELETE, no provider, no LLM, no FastAPI "
            "surface, no fetch."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced ``candidates`` list at N entries "
            f"(default {_DEFAULT_LIMIT}).  ``candidate_count`` always "
            f"reflects the full filtered population."
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

    report = summarize_showcase_candidates(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

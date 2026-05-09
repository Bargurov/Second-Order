#!/usr/bin/env python3
"""Read-only short-horizon (1d / 5d) showcase candidate shortlist.

Sibling of :mod:`scripts.showcase_candidate_shortlist`, scoped to the
short-horizon stat-validation surface.  Answers the operator question,
"do any 1d / 5d short-horizon events qualify as demo showcase
candidates after we exclude every contaminated row?"

The shortlist starts from the per-event-per-horizon signal records
produced by the short-horizon event-study run (1d and 5d only) and
filters them down by excluding any contaminated event_id.  Each
remaining event is aggregated to a single representative horizon —
the one with the largest absolute ``sar`` — and scored as

    showcase_score = round(|sar| + (0.5 if any_significant else 0.0),
                           4)

Two patchable seams compose the shortlist:

  * ``_run_archive_stat_validation_short_horizon`` — short-horizon
    per-event-per-horizon signal records.
  * ``_run_short_horizon_contamination_report``    — contaminated
    event_ids (mirroring the full-horizon contamination report
    contract — i.e. an ``examples`` list of dicts with ``event_id``).

Both upstream modules may not exist yet; this script depends only on
the *seam protocol* (a callable returning a dict).  Tests patch the
seam attributes directly with synthetic fixtures so the shortlist can
be developed before the upstream modules ship.

Output contract::

    {
      "ok":                          bool,
      "candidate_count":             int,           # post-exclusion
      "candidates": [                                # capped at --limit
        {
          "event_id":       int,
          "headline":       str | None,
          "ticker":         str | None,
          "horizon":        int,                 # 1 or 5
          "sar":            float | None,
          "p_value":        float | None,
          "fdr_q":          float | None,
          "reason":         str,
          "showcase_score": float,
        },
        ...
      ],
      "excluded_contaminated_count": int,         # only event_ids
                                                  # present in archive
                                                  # records that ALSO
                                                  # appear in the
                                                  # contamination set
      "top_abs_sar":                 float | None,
      "recommended_next_action":     str,
    }

Conservative language
---------------------
Surfaced events are **short-horizon candidates** carrying
**short-horizon evidence**, not "validated" results.  When every
record is contaminated the recommendation explicitly demands
**manual review required** before any showcase promotion.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own; every read flows through the
  upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no provider call, no
  network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never proposes ticker assignments; never refreshes prices; never
  ranks contaminated events.

Usage::

    python scripts/short_horizon_showcase_candidate_shortlist.py
    python scripts/short_horizon_showcase_candidate_shortlist.py --json
    python scripts/short_horizon_showcase_candidate_shortlist.py \
        --json --limit 20
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

# Short-horizon scope: 1d and 5d only.  Records with any other horizon
# are ignored defensively even if upstream leaks them.
_ALLOWED_HORIZONS: frozenset[int] = frozenset({1, 5})

_SIGNIFICANCE_BONUS: float = 0.5
_SCORE_DECIMALS: int = 4


_RECOMMENDED_NO_RECORDS = (
    "Archive carries no short-horizon (1d / 5d) records — no "
    "showcase candidates can be ranked until the short-horizon "
    "event-study compute has produced records for at least one "
    "event."
)
_RECOMMENDED_ALL_CONTAMINATED = (
    "Every short-horizon record event appears contaminated.  Manual "
    "review required before short-horizon showcase candidates can be "
    "surfaced."
)
_RECOMMENDED_HAVE_CANDIDATES = (
    "{n} short-horizon candidate(s) surfaced, ranked by |sar| + "
    "significance bonus.  Treat showcase_score as short-horizon "
    "evidence — manual review required before promoting any "
    "candidate."
)


# ---------------------------------------------------------------------------
# Patchable seams (lazy upstream imports)
# ---------------------------------------------------------------------------


def _run_archive_stat_validation_short_horizon(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon archive stat-validation runner.

    Lazy import so unit tests can patch this module attribute without
    paying the upstream import cost — and so this script remains
    importable before the upstream module ships.  The seam returns
    the upstream payload verbatim; this script only inspects
    ``examples`` and ``records_count``.
    """
    from scripts.archive_stat_validation_short_horizon_run import (  # noqa: I001
        run_archive_short_horizon_stat_validation,
    )

    return run_archive_short_horizon_stat_validation(db_path=db_path)


def _run_short_horizon_contamination_report(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the short-horizon ticker-contamination report.

    Lazy import — see ``_run_archive_stat_validation_short_horizon``.
    """
    from scripts.stat_validation_short_horizon_contamination_report import (  # noqa: I001
        summarize_short_horizon_contamination,
    )

    return summarize_short_horizon_contamination(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_short_horizon_showcase(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the short-horizon showcase shortlist payload.

    See module docstring for the full contract.
    """
    capped_limit = max(int(limit), 0)

    archive = _safe_dict(
        _run_archive_stat_validation_short_horizon(db_path=db_path))
    contamination = _safe_dict(
        _run_short_horizon_contamination_report(db_path=db_path))

    contaminated_ids = _collect_contaminated_ids(contamination)
    raw_records = archive.get("examples")
    if not isinstance(raw_records, list):
        raw_records = []

    # Restrict to allowed horizons up front so the aggregation never
    # sees a horizon-20 record even if upstream leaks one.
    horizon_records = [
        r for r in raw_records
        if isinstance(r, dict) and r.get("horizon") in _ALLOWED_HORIZONS
    ]

    event_ids_in_archive: set[int] = {
        r.get("event_id") for r in horizon_records  # type: ignore[misc]
        if isinstance(r.get("event_id"), int)
    }
    excluded_contaminated_count = len(
        event_ids_in_archive & contaminated_ids
    )

    by_event = _aggregate_signal_per_event(
        records=horizon_records,
        contaminated_ids=contaminated_ids,
    )

    candidates: list[dict[str, Any]] = []
    for eid, slot in by_event.items():
        if slot.get("rep_sar") is None:
            # Event had records but no usable sar magnitude.
            continue
        score = round(
            slot["abs_sar"]
            + (_SIGNIFICANCE_BONUS if slot["any_significant"] else 0.0),
            _SCORE_DECIMALS,
        )
        candidates.append({
            "event_id":       eid,
            "headline":       slot.get("headline"),
            "ticker":         slot.get("ticker"),
            "horizon":        slot["rep_horizon"],
            "sar":            slot["rep_sar"],
            "p_value":        slot.get("rep_p_value"),
            "fdr_q":          slot.get("rep_fdr_q"),
            "reason":         _build_reason(slot),
            "showcase_score": score,
        })

    candidates.sort(key=lambda c: (
        -_safe_float(c["showcase_score"]),
        _safe_int(c["event_id"]),
    ))

    top_abs_sar: float | None = None
    if candidates:
        top_abs_sar = max(abs(_safe_float(c["sar"])) for c in candidates)

    recommended = _recommend(
        records_count=_safe_int(archive.get("records_count")),
        candidate_count=len(candidates),
        excluded_contaminated_count=excluded_contaminated_count,
    )

    return {
        "ok":                          True,
        "candidate_count":             len(candidates),
        "candidates":                  candidates[:capped_limit],
        "excluded_contaminated_count": excluded_contaminated_count,
        "top_abs_sar":                 top_abs_sar,
        "recommended_next_action":     recommended,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _collect_contaminated_ids(
    contamination: dict[str, Any],
) -> set[int]:
    out: set[int] = set()
    for entry in contamination.get("examples") or []:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("event_id")
        if isinstance(eid, int):
            out.add(eid)
    return out


def _aggregate_signal_per_event(
    *,
    records: Sequence[dict[str, Any]],
    contaminated_ids: set[int],
) -> dict[int, dict[str, Any]]:
    """Aggregate per-event-per-horizon records into a per-event slot.

    Picks the horizon with the largest ``|sar|`` as the representative;
    ``p_value`` / ``fdr_q`` / ``interpretation`` are carried forward
    from that representative record.  ``any_significant`` is true if
    ANY horizon's interpretation was ``"significant"``.
    """
    by_event: dict[int, dict[str, Any]] = {}
    for r in records:
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
                "abs_sar":            0.0,
                "rep_sar":            None,
                "rep_horizon":        None,
                "rep_p_value":        None,
                "rep_fdr_q":          None,
                "rep_interpretation": None,
                "any_significant":    False,
            }
            by_event[eid] = slot

        sar = r.get("sar")
        if isinstance(sar, (int, float)):
            mag = abs(float(sar))
            if slot["rep_sar"] is None or mag > slot["abs_sar"]:
                slot["abs_sar"]            = mag
                slot["rep_sar"]            = float(sar)
                slot["rep_horizon"]        = r.get("horizon")
                slot["rep_p_value"]        = _safe_optional_float(
                    r.get("p_value"))
                slot["rep_fdr_q"]          = _safe_optional_float(
                    r.get("fdr_q"))
                slot["rep_interpretation"] = r.get("interpretation")

        if r.get("interpretation") == "significant":
            slot["any_significant"] = True

        if not slot.get("headline") and r.get("headline"):
            slot["headline"] = r.get("headline")
        if not slot.get("ticker") and r.get("ticker"):
            slot["ticker"] = r.get("ticker")
    return by_event


def _build_reason(slot: dict[str, Any]) -> str:
    mag     = slot.get("abs_sar") or 0.0
    horizon = slot.get("rep_horizon")
    sig = " (significant at one or more horizons)" \
        if slot.get("any_significant") else ""
    if horizon is None:
        return f"|sar|={mag:.4f}{sig}"
    return f"|sar|={mag:.4f} at horizon {horizon}d{sig}"


def _recommend(
    *,
    records_count: int,
    candidate_count: int,
    excluded_contaminated_count: int,
) -> str:
    if records_count <= 0:
        return _RECOMMENDED_NO_RECORDS
    if candidate_count <= 0 and excluded_contaminated_count > 0:
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


def _safe_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Short-horizon (1d / 5d) showcase shortlist", ""]
    lines.append(
        f"Candidate count:               {report['candidate_count']}"
    )
    lines.append(
        f"Excluded contaminated events:  "
        f"{report['excluded_contaminated_count']}"
    )
    top = report.get("top_abs_sar")
    lines.append(
        f"Top |sar|:                     "
        f"{top if top is not None else '-'}"
    )
    lines.append("")
    candidates = report.get("candidates") or []
    lines.append(f"Listed ({len(candidates)}):")
    if candidates:
        for c in candidates:
            lines.append(
                f"  id={c.get('event_id')} "
                f"score={c.get('showcase_score')} "
                f"horizon={c.get('horizon')}d "
                f"sar={c.get('sar')} "
                f"ticker={c.get('ticker') or '-'}"
            )
            lines.append(
                f"      headline: "
                f"{(c.get('headline') or '-')[:120]}"
            )
            lines.append(f"      reason: {c.get('reason')}")
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
            "Read-only short-horizon (1d / 5d) showcase candidate "
            "shortlist.  Ranks events by |sar| + significance bonus, "
            "after excluding every contaminated event_id from the "
            "short-horizon contamination report.  Read-only: no "
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

    report = summarize_short_horizon_showcase(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

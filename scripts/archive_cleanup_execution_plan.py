#!/usr/bin/env python3
"""Read-only archive cleanup execution plan.

Wraps ``archive_cleanup_candidate_report.summarize_cleanup_candidates``
and reorganizes its flat candidate list into batches grouped by
reason, with risk notes, required confirmation flags, and an explicit
no-auto-delete contract.  The "execution plan" name is descriptive:
this script produces a batched *review* plan an operator can follow
to drive a manual deletion pass via the operator path.

Strictly read-only by construction:

* Issues no SQL of its own.  The only DB access is the upstream
  candidate-report's read-only SELECT against ``events``.
* Source contains no INSERT / UPDATE / DELETE / DROP / TRUNCATE /
  ALTER, no provider call (yfinance, market_check, market_data,
  price_cache), no LLM seam (anthropic, openai), no FastAPI surface
  (api, routes.*), no analyze_event, and no filesystem destructor
  (os.remove / os.unlink / shutil.rmtree / Path.unlink).
* No deletion path.  Per-row deletion stays in the operator surface;
  this script only surfaces *batched candidates* and explicitly
  disclaims writes via ``risk_notes`` and
  ``recommended_next_action``.

Output contract::

    {
      "candidate_count":              int,
      "batches": [                                 # sorted alphabetically
        {                                          # by reason key
          "reason":                              str,
          "size":                                int,
          "event_ids":                           list[int],
          "examples":                            list[dict],
          "manual_review_required_before_delete": True,
          "description":                         str,
        },
        ...
      ],
      "risk_notes":                  list[str],
      "required_confirmation_flags": list[str],
      "recommended_next_action":     str,    # closed two-string vocabulary
    }

Batches are emitted only for reasons with >= 1 flagged event.  An
event matching N reasons appears in N batches, so the per-batch
``size`` totals may exceed ``candidate_count``.  ``--limit`` truncates
each batch's ``examples`` list only; ``size`` and ``event_ids``
always reflect the full cluster.

Patchable seam.  ``build_execution_plan`` reads
``summarize_cleanup_candidates`` through the imported module attribute
``_candidate_report`` and also accepts an optional ``candidate_report=``
kwarg for direct injection.  Tests and offline callers can patch
either the attribute or pass a pre-fetched dict.

Usage::

    python scripts/archive_cleanup_execution_plan.py
    python scripts/archive_cleanup_execution_plan.py --json
    python scripts/archive_cleanup_execution_plan.py --json --limit 20
    python scripts/archive_cleanup_execution_plan.py --json \\
                                                     --db-path ./events.db
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

from scripts import archive_cleanup_candidate_report as _candidate_report  # noqa: E402


_DEFAULT_LIMIT: int = 25
_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD: int = 3

# Internal "fetch all" sentinel for the upstream candidate-report
# call.  We need every flagged event so per-reason batches reflect
# true cluster sizes; the upstream's ``--limit`` caps surfaced
# examples and would otherwise hide rows from our batches.
_INTERNAL_FETCH_ALL: int = 10 ** 9


_REASON_KEYS: tuple[str, ...] = (
    "test_fixture_phrase",
    "rotating_macro_template",
    "fixture_timestamp_cluster",
    "duplicate_headline_event_date",
)


# Per-reason narrative description.  Each line is evidence-based and
# explicitly tells the operator how to reason about false positives,
# because the batches drive a manual deletion pass.
_REASON_DESCRIPTIONS: dict[str, str] = {
    "test_fixture_phrase": (
        "Headlines containing literal test-fixture substrings "
        "(e.g. 'Macro shock test event', 'Insufficient evidence.'). "
        "High-confidence test leakage; review each row before "
        "deleting via the operator path."
    ),
    "rotating_macro_template": (
        "Headlines matching scraper-noise / synthetic-feed templates "
        "observed many times in the live archive (e.g. "
        "'Fed speakers rotate', 'Turkey lira weakens'). Likely seed "
        "or demo data; confirm no human-curated rows share the "
        "template before deleting."
    ),
    "fixture_timestamp_cluster": (
        "Multiple events share the exact same timestamp string -- "
        "the smoking-gun signature of a test-seed leak. Review "
        "per-event before treating the cluster as test leakage; a "
        "real batch ingest could legitimately share a wall-clock "
        "stamp."
    ),
    "duplicate_headline_event_date": (
        "Multiple events share an identical (headline, event_date) "
        "pair. May be benign re-ingestion; review the cluster and "
        "decide whether to keep one or delete all but the canonical "
        "row."
    ),
}


# Closed risk-note vocabulary -- always emitted, even on a clean
# archive, so downstream consumers see a stable shape.
_RISK_NOTES: tuple[str, ...] = (
    "This script is read-only and makes no DB writes; deletion of "
    "any flagged event remains a manual operator task.",
    "An event matching multiple reasons appears in multiple batches; "
    "deduplicate by event_id before issuing any DELETE statement.",
    "The candidate detector is allow-list based; expanding the "
    "allow-list in archive_cleanup_candidate_report changes which "
    "rows surface here.",
    "fixture_timestamp_cluster can flag legitimate batch-ingested "
    "events that share a wall-clock stamp; review per-event before "
    "treating the cluster as test leakage.",
)


# Required confirmation flags an operator should tick before driving
# any deletion off this plan.  Always present, even on a clean
# archive, for stable shape.
_REQUIRED_CONFIRMATION_FLAGS: tuple[str, ...] = (
    "backup_taken",
    "per_event_manual_review_complete",
    "acknowledged_no_db_writes_from_this_script",
)


# Closed two-string vocabulary for ``recommended_next_action``.  The
# "plan ready" string explicitly disclaims writes so an operator
# cannot mistake the report for a deletion tool.
_RECOMMENDED_OK = (
    "No archive cleanup candidates detected; no execution plan "
    "required."
)
_RECOMMENDED_PLAN = (
    "Execution plan ready.  Take a fresh backup, review every event "
    "in every batch, then delete via the operator path.  This "
    "script makes no DB writes."
)


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_execution_plan(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    fixture_timestamp_threshold: int = _DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
    candidate_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the execution plan dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Forwarded to ``summarize_cleanup_candidates`` when
        ``candidate_report`` is not supplied.
    limit
        Per-batch cap on the surfaced ``examples`` list.  Aggregate
        ``size`` and ``event_ids`` are unaffected.  Negative values
        clamp to ``0``.
    fixture_timestamp_threshold
        Forwarded to ``summarize_cleanup_candidates``.
    candidate_report
        Optional pre-fetched candidate-report dict.  When supplied,
        bypasses the underlying ``summarize_cleanup_candidates`` call
        entirely -- the direct-injection seam for tests and for
        callers that have already paid the SELECT cost.
    """
    capped_limit = max(int(limit), 0)

    if candidate_report is None:
        candidate_report = _candidate_report.summarize_cleanup_candidates(
            db_path=db_path,
            limit=_INTERNAL_FETCH_ALL,
            fixture_timestamp_threshold=fixture_timestamp_threshold,
        )

    # Pivot the flat ``examples`` list into per-reason buckets.  An
    # event with N reasons lands in N buckets -- intentional, so each
    # batch is a complete view of the events flagged for that reason.
    examples_by_reason: dict[str, list[dict[str, Any]]] = {
        key: [] for key in _REASON_KEYS
    }
    for example in candidate_report.get("examples") or []:
        if not isinstance(example, dict):
            continue
        for reason in example.get("reasons") or ():
            if reason in examples_by_reason:
                examples_by_reason[reason].append(example)

    batches: list[dict[str, Any]] = []
    for reason in sorted(_REASON_KEYS):  # alphabetical, stable across runs
        flagged = examples_by_reason[reason]
        if not flagged:
            continue
        event_ids: list[int] = []
        for ex in flagged:
            try:
                event_ids.append(int(ex["event_id"]))
            except (KeyError, TypeError, ValueError):
                continue
        batches.append({
            "reason":                               reason,
            "size":                                 len(event_ids),
            "event_ids":                            event_ids,
            "examples":                             flagged[:capped_limit],
            "manual_review_required_before_delete": True,
            "description":                          _REASON_DESCRIPTIONS[reason],
        })

    candidate_count = int(candidate_report.get("candidate_count", 0) or 0)
    return {
        "candidate_count":              candidate_count,
        "batches":                      batches,
        "risk_notes":                   list(_RISK_NOTES),
        "required_confirmation_flags":  list(_REQUIRED_CONFIRMATION_FLAGS),
        "recommended_next_action": (
            _RECOMMENDED_OK if candidate_count == 0 else _RECOMMENDED_PLAN
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Archive cleanup execution plan", ""]
    lines.append(
        f"Candidate events flagged:                 {report['candidate_count']}"
    )
    lines.append(
        f"Batches:                                  {len(report['batches'])}"
    )
    lines.append("")

    if report["batches"]:
        for batch in report["batches"]:
            lines.append(f"  reason: {batch['reason']}")
            lines.append(f"    size:                                  {batch['size']}")
            lines.append(
                f"    manual_review_required_before_delete:  "
                f"{batch['manual_review_required_before_delete']}"
            )
            preview = batch["event_ids"][:10]
            tail = " ..." if len(batch["event_ids"]) > 10 else ""
            lines.append(f"    event_ids (first 10):                  {preview}{tail}")
            lines.append(f"    examples shown:                        {len(batch['examples'])}")
            lines.append(f"    description: {batch['description']}")
            lines.append("")
    else:
        lines.append("  (no batches)")
        lines.append("")

    lines.append("Risk notes:")
    for note in report["risk_notes"]:
        lines.append(f"  - {note}")
    lines.append("")

    lines.append("Required confirmation flags:")
    for flag in report["required_confirmation_flags"]:
        lines.append(f"  - {flag}")
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
            "Read-only archive cleanup execution plan.  Reorganizes "
            "the cleanup-candidate report into batches grouped by "
            "reason, with risk notes, required confirmation flags, "
            "and an explicit no-auto-delete contract.  Read-only: "
            "issues no SQL of its own; this script makes no DB "
            "writes."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text plan.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-batch examples list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Per-batch size and "
            f"event_ids are unaffected."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Forwarded to "
            "summarize_cleanup_candidates; defaults to db.DB_FILE so "
            "the plan follows the project's configured archive."
        ),
    )
    parser.add_argument(
        "--fixture-timestamp-threshold",
        dest="fixture_timestamp_threshold",
        type=int,
        default=_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
        help=(
            f"Forwarded to summarize_cleanup_candidates "
            f"(default {_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD}).  "
            f"Values < 2 are clamped to 2 by the upstream."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_execution_plan(
        db_path=args.db_path,
        limit=args.limit,
        fixture_timestamp_threshold=args.fixture_timestamp_threshold,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

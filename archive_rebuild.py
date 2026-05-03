"""Reproducible archive rebuild + backfill tooling.

Problem
-------
Large research refreshes — e.g. recomputing every archived event's
macro overlays after an upstream composer fix — used to mean ad-hoc
scripts that did ``load → transform → write`` in one pass with no
preview and no audit trail.  That's fine for a dev iteration but
dangerous for operations on the production archive.

This module formalises the pattern:

1. **Select** events deterministically from a declarative filter
   (id list, date range, mechanism family, age bucket, limit).
2. **Validate** each candidate via the composer's own eligibility
   contract + emit a per-reason summary report.
3. **Plan**: list what would change for every eligible event,
   grouped by operation (``overlays`` today, extensible to future
   ops like ``revisit_snapshot_sync``).
4. **Execute**: either ``dry_run=True`` (default) to print the
   report only, or ``dry_run=False`` to write back via the
   composer's documented persist path.
5. **Report**: a structured dict + a markdown formatter suitable for
   printing to stdout or posting into a change-review comment.

Design discipline
-----------------
* Pure composer: no top-level I/O.  Events are passed in.  Tests can
  call the same entry point that production uses.
* Defaults to dry-run.  The caller must explicitly pass
  ``dry_run=False`` to persist.  ``write=True`` is an alias for the
  CLI layer so ``--write`` reads naturally.
* Every rebuild entry point returns a structured report — the
  markdown formatter is a view on that report, not a parallel path.
* Single-operation scope today: ``overlays``, which wraps
  ``frozen_overlay_refresh.refresh_overlays_for_event`` (the already-
  shipped safe-on-frozen-rows composer).  The operation-dispatch
  layer is extensible — add a new operation by registering its
  runner in ``_OPERATION_RUNNERS``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Optional


# ---------------------------------------------------------------------------
# Supported operations — extensible registry.  Each runner is called per
# candidate event with signature ``(event, *, persist, now) -> dict``.
# The returned dict must carry ``{event_id, refreshed: list, skipped: list,
# eligibility: dict, written: bool, error?: str}`` so the aggregator can
# produce uniform reports across operations.
# ---------------------------------------------------------------------------

SUPPORTED_OPERATIONS: tuple[str, ...] = ("overlays",)


def _run_overlay_rebuild(
    event: dict, *, persist: bool, now: Optional[datetime],
) -> dict[str, Any]:
    """Adapter over ``frozen_overlay_refresh.refresh_overlays_for_event``.

    Captures composer exceptions so one bad event never aborts a
    batch — this is the backfill discipline: report + continue.
    """
    try:
        from frozen_overlay_refresh import refresh_overlays_for_event
        return refresh_overlays_for_event(event, now=now, persist=persist)
    except Exception as exc:  # noqa: BLE001 — narrow catch adds no value here
        return {
            "event_id":    event.get("id"),
            "refreshed":   [],
            "skipped":     [],
            "eligibility": {"eligible": False, "reason": "composer_error"},
            "written":     False,
            "error":       f"{type(exc).__name__}: {exc}",
        }


_OPERATION_RUNNERS: dict[str, Callable[..., dict]] = {
    "overlays": _run_overlay_rebuild,
}


# ---------------------------------------------------------------------------
# Filter + selection
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _event_age_days(event: dict, *, now: date) -> Optional[int]:
    d = _parse_date(event.get("event_date"))
    if d is None:
        return None
    return (now - d).days


def _event_matches_filter(
    event: dict,
    *,
    event_ids: Optional[set[int]],
    date_range: Optional[tuple[Optional[str], Optional[str]]],
    mechanism_family: Optional[set[str]],
    min_age_days: Optional[int],
    max_age_days: Optional[int],
    low_signal: Optional[bool],
    now: date,
) -> bool:
    if event_ids is not None and event.get("id") not in event_ids:
        return False
    if mechanism_family is not None:
        fam = event.get("mechanism_family") or "none"
        if fam not in mechanism_family:
            return False
    if date_range:
        start, end = date_range
        d = (event.get("event_date") or "")[:10]
        if start and d < start:
            return False
        if end and d > end:
            return False
    if min_age_days is not None or max_age_days is not None:
        age = _event_age_days(event, now=now)
        if age is None:
            return False
        if min_age_days is not None and age < min_age_days:
            return False
        if max_age_days is not None and age > max_age_days:
            return False
    if low_signal is not None:
        if bool(event.get("low_signal")) != low_signal:
            return False
    return True


def select_events(
    events: Optional[list[dict]],
    *,
    event_ids: Optional[Iterable[int]] = None,
    date_range: Optional[tuple[Optional[str], Optional[str]]] = None,
    mechanism_family: Optional[Iterable[str]] = None,
    min_age_days: Optional[int] = None,
    max_age_days: Optional[int] = None,
    low_signal: Optional[bool] = None,
    limit: Optional[int] = None,
    now: Optional[date] = None,
) -> dict[str, Any]:
    """Select a deterministic subset of events using declarative filters.

    Returns ``{filter, candidates, total_considered}``.  ``candidates``
    is a list; callers pass it into ``plan_rebuild`` or
    ``execute_rebuild``.
    """
    events = events or []
    ids_set = {int(i) for i in event_ids} if event_ids else None
    fam_set = {str(f) for f in mechanism_family} if mechanism_family else None
    anchor = now or datetime.now(timezone.utc).date()

    total = 0
    out: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        total += 1
        if not _event_matches_filter(
            ev,
            event_ids=ids_set,
            date_range=date_range,
            mechanism_family=fam_set,
            min_age_days=min_age_days,
            max_age_days=max_age_days,
            low_signal=low_signal,
            now=anchor,
        ):
            continue
        out.append(ev)

    # Deterministic order: event_date desc (recent first), then id asc.
    out.sort(key=lambda e: (
        -(int(e.get("id") or 0)),
    ))
    out.sort(key=lambda e: (e.get("event_date") or ""), reverse=True)

    if limit is not None and limit >= 0:
        out = out[:limit]

    applied: dict[str, Any] = {}
    if ids_set:
        applied["event_ids"] = sorted(ids_set)
    if date_range:
        applied["date_range"] = {"start": date_range[0], "end": date_range[1]}
    if fam_set:
        applied["mechanism_family"] = sorted(fam_set)
    if min_age_days is not None:
        applied["min_age_days"] = min_age_days
    if max_age_days is not None:
        applied["max_age_days"] = max_age_days
    if low_signal is not None:
        applied["low_signal"] = low_signal
    if limit is not None:
        applied["limit"] = limit
    applied["anchor_date"] = anchor.isoformat()

    return {
        "filter":           applied,
        "candidates":       out,
        "total_considered": total,
    }


# ---------------------------------------------------------------------------
# Validation + plan
# ---------------------------------------------------------------------------

def validate_rebuild(
    candidates: list[dict],
    *,
    operation: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Dry-inspect each candidate via the composer's eligibility path.

    Runs the operation with ``persist=False`` so no DB writes occur.
    The returned dict is the pre-write validation report: per-reason
    counts + a sample of 5 preview rows per status bucket so reviewers
    can eyeball what would change.
    """
    if operation not in _OPERATION_RUNNERS:
        raise ValueError(
            f"archive_rebuild: unknown operation {operation!r}; "
            f"allowed: {list(SUPPORTED_OPERATIONS)}"
        )
    runner = _OPERATION_RUNNERS[operation]
    counts: dict[str, int] = {
        "eligible": 0, "ineligible": 0, "errored": 0,
    }
    by_reason: dict[str, int] = {}
    samples: dict[str, list[dict]] = {
        "eligible": [], "ineligible": [], "errored": [],
    }

    eligibility_rows: list[dict] = []
    for ev in candidates:
        result = runner(ev, persist=False, now=now)
        elig = result.get("eligibility") or {}
        eligible = bool(elig.get("eligible"))
        errored = bool(result.get("error"))
        bucket = "errored" if errored else ("eligible" if eligible else "ineligible")
        counts[bucket] += 1
        reason = elig.get("reason") or ("eligible" if eligible else "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1

        row = {
            "event_id":      ev.get("id"),
            "headline":      ev.get("headline"),
            "event_date":    ev.get("event_date"),
            "bucket":        bucket,
            "reason":        reason,
            "would_refresh": list(result.get("refreshed") or []),
            "would_skip":    list(result.get("skipped") or []),
            "error":         result.get("error"),
        }
        eligibility_rows.append(row)
        if len(samples[bucket]) < 5:
            samples[bucket].append(row)

    return {
        "operation":       operation,
        "candidate_count": len(candidates),
        "counts":          counts,
        "by_reason":       by_reason,
        "samples":         samples,
        "rows":            eligibility_rows,
    }


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute_rebuild(
    candidates: list[dict],
    *,
    operation: str,
    dry_run: bool = True,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run the rebuild.  ``dry_run=True`` (default) never writes.

    The validation report is always produced first; when ``dry_run``
    is True, the same composer calls already ran with ``persist=False``
    so we reuse the validation output.  In write mode, eligible rows
    are re-run with ``persist=True``.
    """
    if operation not in _OPERATION_RUNNERS:
        raise ValueError(
            f"archive_rebuild: unknown operation {operation!r}"
        )
    runner = _OPERATION_RUNNERS[operation]
    validation = validate_rebuild(
        candidates, operation=operation, now=now,
    )

    write_results: list[dict[str, Any]] = []
    written = 0
    errored = 0

    if not dry_run:
        for ev, row in zip(candidates, validation["rows"]):
            if row["bucket"] != "eligible":
                continue
            result = runner(ev, persist=True, now=now)
            wrote = bool(result.get("written"))
            err = result.get("error")
            if err:
                errored += 1
            elif wrote:
                written += 1
            write_results.append({
                "event_id":  ev.get("id"),
                "written":   wrote,
                "refreshed": list(result.get("refreshed") or []),
                "skipped":   list(result.get("skipped") or []),
                "error":     err,
            })

    return {
        "operation":  operation,
        "dry_run":    bool(dry_run),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation": validation,
        "write": {
            "attempted": len(write_results),
            "written":   written,
            "errored":   errored,
            "results":   write_results,
        },
    }


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def format_rebuild_report(report: Optional[dict]) -> str:
    """Render a rebuild report as markdown for stdout / review comment.

    Never raises on malformed input — returns an empty string so CLI
    code doesn't need try/except around the formatter.
    """
    if not isinstance(report, dict):
        return ""

    validation = report.get("validation") or {}
    counts = validation.get("counts") or {}
    by_reason = validation.get("by_reason") or {}
    samples = validation.get("samples") or {}
    write = report.get("write") or {}
    dry = report.get("dry_run", True)
    mode = "dry-run" if dry else "write"

    lines: list[str] = [
        f"# Archive Rebuild Report — {mode}",
        "",
        f"_operation_: `{report.get('operation', '?')}`  ·  "
        f"_generated_at_: `{report.get('generated_at', '?')}`",
        "",
        f"Candidates: **{validation.get('candidate_count', 0)}** "
        f"(eligible={counts.get('eligible', 0)}, "
        f"ineligible={counts.get('ineligible', 0)}, "
        f"errored={counts.get('errored', 0)})",
        "",
    ]
    if by_reason:
        lines.append("## Eligibility by reason")
        for reason in sorted(by_reason):
            lines.append(f"- `{reason}`: {by_reason[reason]}")
        lines.append("")

    for bucket in ("eligible", "ineligible", "errored"):
        rows = samples.get(bucket) or []
        if not rows:
            continue
        lines.append(f"## Sample — {bucket}")
        for r in rows:
            pieces = [
                f"`{r.get('event_id')}`",
                f"{r.get('event_date') or '?'}",
                f"{r.get('headline') or ''}",
                f"reason={r.get('reason')}",
            ]
            if r.get("would_refresh"):
                pieces.append(f"would_refresh={len(r['would_refresh'])}")
            if r.get("error"):
                pieces.append(f"error={r['error']}")
            lines.append("- " + " · ".join(pieces))
        lines.append("")

    lines.append("## Write summary")
    if dry:
        lines.append(
            "_Dry-run: no events written.  Re-run with `--write` to persist._"
        )
    else:
        lines.append(
            f"attempted={write.get('attempted', 0)} · "
            f"written={write.get('written', 0)} · "
            f"errored={write.get('errored', 0)}"
        )
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# One-shot orchestrator used by CLI.  Keeps the CLI layer tiny.
# ---------------------------------------------------------------------------

def run_archive_rebuild(
    events: Optional[list[dict]],
    *,
    operation: str = "overlays",
    write: bool = False,
    event_ids: Optional[Iterable[int]] = None,
    date_range: Optional[tuple[Optional[str], Optional[str]]] = None,
    mechanism_family: Optional[Iterable[str]] = None,
    min_age_days: Optional[int] = None,
    max_age_days: Optional[int] = None,
    low_signal: Optional[bool] = None,
    limit: Optional[int] = None,
    now: Optional[date] = None,
    composer_now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Select → validate → (optionally) write, returning the full report.

    The CLI wraps this; tests call it directly with a fixed event list.
    ``write=False`` is the safe default — callers must be explicit to
    mutate the archive.
    """
    selection = select_events(
        events,
        event_ids=event_ids,
        date_range=date_range,
        mechanism_family=mechanism_family,
        min_age_days=min_age_days,
        max_age_days=max_age_days,
        low_signal=low_signal,
        limit=limit,
        now=now,
    )
    report = execute_rebuild(
        selection["candidates"],
        operation=operation,
        dry_run=(not write),
        now=composer_now,
    )
    report["selection"] = {
        "filter":           selection["filter"],
        "total_considered": selection["total_considered"],
        "candidate_count":  len(selection["candidates"]),
    }
    return report

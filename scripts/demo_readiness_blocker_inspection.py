#!/usr/bin/env python3
"""Demo-readiness blocker inspection report.

A read-only narrator that wraps
:mod:`scripts.section_c_demo_readiness_checklist`.  It re-uses the
checklist's verdicts verbatim and reorganises them into an
inspection-style envelope answering three questions:

1. What is blocking the 2-month demo right now?
2. What is already solved (per the checklist)?
3. What should be implemented next, without applying it?

The inspection never re-derives a verdict; it never overrides the
checklist; it never claims demo readiness.  Its job is to surface
what the checklist already says, in language the operator can act
on.

Read-only by construction
-------------------------

* Single source of truth: the checklist's structured envelope, read
  through a lazy seam (:func:`_run_demo_readiness_checklist`) so
  tests can patch it directly.
* No DB connection.  No ``yfinance`` / ``market_data`` / paid
  provider / LLM call.  No FastAPI surface (never imports ``api``
  or ``routes.*``).  No mutation of any artifact.
* Optional artifact peek: when the freeze-candidate evidence
  artifact is present on disk, the inspection reads it once
  (read-only) to surface
  ``benchmark_sensitivity_status.status == 'comparison_available'``
  as a separate ``comparison_available`` signal.  The peek never
  changes a check verdict — it is an observability field for the
  operator narrative.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.

Conservative wording
--------------------

Banned tokens in any emitted prose: ``proof``, ``proven``,
``guaranteed``, ``automatically``, ``validated``,
``alpha generated``, ``correct ticker``, ``definitely``,
``approved``, ``production ready``, ``production-ready``,
``demo_ready``, ``demo-ready``.  The inspection's strongest claim
about the overall state is whatever the checklist returns — the
final demo decision stays with the operator.

Output contract (JSON)::

    {
      "ok":                    bool,
      "readiness_status":      "blocked"
                               | "required_checks_pending"
                               | "required_checks_passed",
      "blockers":              [ {item_dict}, ... ],
      "solved_items":          [ {item_dict}, ... ],
      "partial_items":         [ {item_dict}, ... ],
      "next_required_actions": [str, ...],
      "not_required_yet":      [str, ...],
      "warnings":              [str, ...],
      "errors":                [str, ...],
    }

Each ``item_dict`` carries::

    {
      "check_id":    str,
      "status":      "passed" | "partial" | "blocked",
      "explanation": str,
      "evidence":    [str, ...],
      "next_action": str,
    }

In addition, the envelope carries a top-level
``comparison_available`` boolean derived from the freeze-candidate
artifact when available, and a top-level
``recommended_next_implementation_target`` describing the next
implementation target the operator could pick up — without applying
it.

Usage::

    python scripts/demo_readiness_blocker_inspection.py --json
    python scripts/demo_readiness_blocker_inspection.py --json \\
        --repo-root . \\
        --freeze-artifact artifacts/freeze_candidate_evidence.json \\
        --output artifacts/demo_readiness_blocker_inspection.json
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
# Check identifiers — pinned by the checklist.  Re-declared here so
# the inspection does not import the checklist module at the top
# level (the lazy seam below holds that import).
# ---------------------------------------------------------------------------


_CHECK_WEEKLY:       str = "weekly_duplicate_canonicalization_landed"
_CHECK_SECTOR_ETF:   str = "still_moving_sector_etf_primary_gate_landed"
_CHECK_DAILY_ENRICH: str = "daily_mechanism_family_enrichment_resolved"
_CHECK_FREEZE_OK:    str = "freeze_candidate_evidence_artifact_validates"
_CHECK_EVENT_60:     str = "benchmark_sensitivity_event_60_honest_representation"
_CHECK_NO_PAID:      str = "no_paid_smoke_available"


_STATUS_PASSED:  str = "passed"
_STATUS_PARTIAL: str = "partial"
_STATUS_BLOCKED: str = "blocked"


_DEFAULT_FREEZE_ARTIFACT: str = "artifacts/freeze_candidate_evidence.json"


# Implementation-target ordering — narrowest first.  The inspection
# recommends the highest-priority unresolved check; partials only
# surface when no blocker is present.
_IMPLEMENTATION_PRIORITY: tuple[str, ...] = (
    _CHECK_DAILY_ENRICH,
    _CHECK_FREEZE_OK,
    _CHECK_EVENT_60,
    _CHECK_WEEKLY,
    _CHECK_SECTOR_ETF,
    _CHECK_NO_PAID,
)


# ---------------------------------------------------------------------------
# Per-check narrative prose — keyed by (check_id, status).  Kept
# short so the rendered envelope stays scannable.  No banned tokens.
# ---------------------------------------------------------------------------


_EXPLANATIONS: dict[tuple[str, str], str] = {
    (_CHECK_WEEKLY, _STATUS_PASSED): (
        "Weekly duplicate canonicalization is reported solved: the "
        "production weekly route imports and calls "
        "collapse_weekly_duplicates so a duplicate cluster lands as "
        "one canonical card."
    ),
    (_CHECK_WEEKLY, _STATUS_PARTIAL): (
        "Weekly duplicate canonicalization is reported partial — the "
        "helper exists but the production wiring is not fully in "
        "place per the checklist."
    ),
    (_CHECK_WEEKLY, _STATUS_BLOCKED): (
        "Weekly duplicate canonicalization is reported blocked — the "
        "helper or its import/call site in routes/movers.py is "
        "missing on this run."
    ),
    (_CHECK_SECTOR_ETF, _STATUS_PASSED): (
        "Still Moving sector-ETF primary gate is reported solved: "
        "primary_is_sector_etf is defined and referenced inside "
        "mover_card_normalizer.py so the persistent gate would refuse "
        "a card whose top mover is a sector ETF."
    ),
    (_CHECK_SECTOR_ETF, _STATUS_PARTIAL): (
        "Still Moving sector-ETF primary gate is reported partial — "
        "the helper exists but the persistent gate wiring is not "
        "fully in place per the checklist."
    ),
    (_CHECK_SECTOR_ETF, _STATUS_BLOCKED): (
        "Still Moving sector-ETF primary gate is reported blocked — "
        "primary_is_sector_etf is not defined and called inside "
        "mover_card_normalizer.py on this run."
    ),
    (_CHECK_DAILY_ENRICH, _STATUS_PASSED): (
        "Daily mechanism-family enrichment is reported solved: the "
        "Section C boundary gate is wired and a complete set of "
        "analyzed-event artifacts is present per the checklist."
    ),
    (_CHECK_DAILY_ENRICH, _STATUS_PARTIAL): (
        "Daily mechanism-family enrichment is reported partial — one "
        "half of the gate is in place (either the analyzed-event "
        "artifacts under artifacts/ or the boundary gate in routes/) "
        "but not both."
    ),
    (_CHECK_DAILY_ENRICH, _STATUS_BLOCKED): (
        "Daily mechanism-family enrichment is reported blocked: the "
        "Section C boundary gate "
        "(require_analyzed_event_artifact_before_section_c_inclusion) "
        "is not yet wired in and no analyzed-event artifacts are "
        "present under artifacts/.  Until one path lands, Daily "
        "candidates would reach Section C without a reliable "
        "mechanism_family handle."
    ),
    (_CHECK_FREEZE_OK, _STATUS_PASSED): (
        "Freeze-candidate evidence artifact is reported as schema-"
        "passing on this run."
    ),
    (_CHECK_FREEZE_OK, _STATUS_PARTIAL): (
        "Freeze-candidate evidence artifact is reported partial per "
        "the checklist."
    ),
    (_CHECK_FREEZE_OK, _STATUS_BLOCKED): (
        "Freeze-candidate evidence artifact is reported blocked — "
        "the validator surfaced errors or could not settle a verdict "
        "on this run."
    ),
    (_CHECK_EVENT_60, _STATUS_PASSED): (
        "Benchmark sensitivity is reported as honestly represented "
        "for event 60: the event appears in changed_event_ids with a "
        "non-zero changed_interpretation_count, every event-60 "
        "record carries fdr_significant == False, and the no-FDR "
        "caveat is present in limitations."
    ),
    (_CHECK_EVENT_60, _STATUS_PARTIAL): (
        "Benchmark sensitivity representation for event 60 is "
        "reported partial — at least one of the four honesty signals "
        "is missing on this run."
    ),
    (_CHECK_EVENT_60, _STATUS_BLOCKED): (
        "Benchmark sensitivity representation for event 60 is "
        "reported blocked — none of the four honesty signals line "
        "up on this run, or the artifact could not be parsed."
    ),
    (_CHECK_NO_PAID, _STATUS_PASSED): (
        "no_paid_smoke is reported present and confirmed by the "
        "checklist."
    ),
    (_CHECK_NO_PAID, _STATUS_PARTIAL): (
        "no_paid_smoke script is present on disk but the checklist "
        "does not run it — the operator would run "
        "`python scripts/no_paid_smoke.py --json` separately before "
        "the demo and confirm summary.failed == 0."
    ),
    (_CHECK_NO_PAID, _STATUS_BLOCKED): (
        "no_paid_smoke script is missing on disk — the no-paid "
        "in-process smoke gate cannot be exercised before the demo."
    ),
}


_RECOMMENDATION_BY_CHECK: dict[str, str] = {
    _CHECK_DAILY_ENRICH: (
        "next implementation target the operator could pick up: wire "
        "the require_analyzed_event_artifact_before_section_c_"
        "inclusion gate per scripts/section_c_daily_artifact_gate_plan.py "
        "and produce one analyzed-event artifact per Daily candidate"
    ),
    _CHECK_FREEZE_OK: (
        "next implementation target the operator could pick up: "
        "address the freeze-candidate validator errors before the "
        "demo backend is allowed to consume artifacts/freeze_candidate_"
        "evidence.json"
    ),
    _CHECK_EVENT_60: (
        "next implementation target the operator could pick up: "
        "regenerate artifacts/freeze_candidate_evidence.json so the "
        "four event-60 honesty signals line up"
    ),
    _CHECK_WEEKLY: (
        "next implementation target the operator could pick up: wire "
        "routes.weekly_canonicalization.collapse_weekly_duplicates "
        "into routes/movers.py"
    ),
    _CHECK_SECTOR_ETF: (
        "next implementation target the operator could pick up: wire "
        "primary_is_sector_etf into is_high_conviction_persistent in "
        "mover_card_normalizer.py"
    ),
    _CHECK_NO_PAID: (
        "next implementation target the operator could pick up: "
        "restore scripts/no_paid_smoke.py before the demo"
    ),
}


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_demo_readiness_checklist(
    *,
    repo_root:       str | None,
    freeze_artifact: str | None,
) -> dict[str, Any]:
    """Run the Section C demo-readiness checklist.

    Lazy import so the inspection's top-level surface stays narrow.
    Tests patch this seam so they never hit the on-disk checklist
    behaviour they do not need.
    """
    from scripts.section_c_demo_readiness_checklist import (
        run_section_c_demo_readiness_checklist,
    )
    return run_section_c_demo_readiness_checklist(
        repo_root=repo_root,
        freeze_artifact=freeze_artifact,
    )


def _read_freeze_artifact_status(
    *,
    artifact_path: str,
    warnings:      list[str],
) -> str | None:
    """Return ``benchmark_sensitivity_status.status`` from the
    freeze-candidate artifact if it can be read; otherwise ``None``.

    Read-only.  Failures land as warnings, never as a check verdict.
    """
    path = Path(artifact_path)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(
            f"freeze artifact at {artifact_path!r} could not be read: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
    if not isinstance(data, dict):
        return None
    bench = data.get("benchmark_sensitivity_status")
    if not isinstance(bench, dict):
        return None
    status = bench.get("status")
    if isinstance(status, str):
        return status
    return None


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_demo_readiness_blocker_inspection(
    *,
    repo_root:       str | None = None,
    freeze_artifact: str | None = None,
    output_path:     str | None = None,
) -> dict[str, Any]:
    """Build the demo-readiness blocker inspection report.

    See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    root = Path(repo_root) if repo_root else ROOT
    freeze_path = freeze_artifact or str(root / _DEFAULT_FREEZE_ARTIFACT)

    try:
        checklist = _run_demo_readiness_checklist(
            repo_root=repo_root,
            freeze_artifact=freeze_artifact,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"demo-readiness checklist raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "ok":                    False,
            "readiness_status":      "blocked",
            "blockers":              [],
            "solved_items":          [],
            "partial_items":         [],
            "next_required_actions": [],
            "not_required_yet":      [],
            "comparison_available":  False,
            "recommended_next_implementation_target": "",
            "warnings":              warnings,
            "errors":                errors,
        }

    # Re-shape the checklist's verdicts into the inspection envelope.
    blockers_in:  list[dict[str, Any]] = list(
        checklist.get("blockers") or []
    )
    partials_in:  list[dict[str, Any]] = list(
        checklist.get("partial_checks") or []
    )
    passed_in:    list[dict[str, Any]] = list(
        checklist.get("passed_checks") or []
    )

    blockers      = [_to_item(c) for c in blockers_in]
    partial_items = [_to_item(c) for c in partials_in]
    solved_items  = [_to_item(c) for c in passed_in]

    next_required_actions: list[str] = list(
        checklist.get("required_before_demo") or []
    )
    not_required_yet:      list[str] = list(
        checklist.get("optional_before_demo") or []
    )

    # Surface comparison_available signal from the freeze artifact.
    # Failures here are warnings, never blockers (the checklist
    # already owns the artifact validity verdict).
    bench_status = _read_freeze_artifact_status(
        artifact_path=freeze_path, warnings=warnings,
    )
    comparison_available = bench_status == "comparison_available"

    # Recommend the next implementation target without applying it.
    recommended = _pick_next_implementation_target(
        blockers=blockers, partial_items=partial_items,
    )

    # Propagate checklist warnings/errors into our envelope so the
    # operator sees the full picture from one place.
    for w in checklist.get("warnings") or []:
        if isinstance(w, str) and w:
            warnings.append(w)
    for e in checklist.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(e)

    readiness = checklist.get("readiness_status") or "blocked"
    ok = bool(checklist.get("ok")) and not errors

    envelope: dict[str, Any] = {
        "ok":                    ok,
        "readiness_status":      readiness,
        "blockers":              blockers,
        "solved_items":          solved_items,
        "partial_items":         partial_items,
        "next_required_actions": next_required_actions,
        "not_required_yet":      not_required_yet,
        "comparison_available":  comparison_available,
        "recommended_next_implementation_target": recommended,
        "warnings":              warnings,
        "errors":                errors,
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
# Helpers
# ---------------------------------------------------------------------------


def _to_item(check: dict[str, Any]) -> dict[str, Any]:
    """Re-shape a single checklist verdict into an inspection item."""
    check_id    = check.get("check_id") or ""
    status      = check.get("status") or ""
    evidence    = check.get("evidence") or []
    next_action = check.get("next_action") or ""

    explanation = _EXPLANATIONS.get(
        (check_id, status),
        f"check {check_id!r} reported status {status!r} by the checklist.",
    )
    return {
        "check_id":    check_id,
        "status":      status,
        "explanation": explanation,
        "evidence":    [
            str(e) for e in evidence if isinstance(e, (str, int, float))
        ],
        "next_action": next_action if isinstance(next_action, str) else "",
    }


def _pick_next_implementation_target(
    *,
    blockers:      list[dict[str, Any]],
    partial_items: list[dict[str, Any]],
) -> str:
    """Pick the highest-priority unresolved check.

    Blockers come first.  Within blockers, the priority order in
    ``_IMPLEMENTATION_PRIORITY`` decides which one is surfaced.
    Partials are only considered when no blocker is present.
    """
    blocker_ids: set[str] = {
        c.get("check_id") for c in blockers if isinstance(c, dict)
    } - {None, ""}
    partial_ids: set[str] = {
        c.get("check_id") for c in partial_items if isinstance(c, dict)
    } - {None, ""}

    for check_id in _IMPLEMENTATION_PRIORITY:
        if check_id in blocker_ids:
            return _RECOMMENDATION_BY_CHECK.get(check_id, "")
    for check_id in _IMPLEMENTATION_PRIORITY:
        if check_id in partial_ids:
            return _RECOMMENDATION_BY_CHECK.get(check_id, "")
    return ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Demo-readiness blocker inspection", ""]
    lines.append(f"OK:                {report['ok']}")
    lines.append(f"Readiness status:  {report['readiness_status']}")
    lines.append(
        f"Comparison available (freeze artifact): "
        f"{report.get('comparison_available')}"
    )
    lines.append("")
    lines.append(f"Blockers ({len(report['blockers'])}):")
    for item in report["blockers"]:
        if isinstance(item, dict):
            lines.append(f"  - {item.get('check_id')}")
            lines.append(f"      {item.get('explanation')}")
            if item.get("next_action"):
                lines.append(f"      next_action: {item['next_action']}")
    lines.append("")
    lines.append(f"Solved   ({len(report['solved_items'])}):")
    for item in report["solved_items"]:
        if isinstance(item, dict):
            lines.append(f"  - {item.get('check_id')}")
            lines.append(f"      {item.get('explanation')}")
    lines.append("")
    lines.append(f"Partial  ({len(report['partial_items'])}):")
    for item in report["partial_items"]:
        if isinstance(item, dict):
            lines.append(f"  - {item.get('check_id')}")
            lines.append(f"      {item.get('explanation')}")
            if item.get("next_action"):
                lines.append(f"      next_action: {item['next_action']}")
    if report.get("recommended_next_implementation_target"):
        lines.append("")
        lines.append(
            "Recommended next implementation target:"
        )
        lines.append(
            f"  - {report['recommended_next_implementation_target']}"
        )
    if report.get("next_required_actions"):
        lines.append("")
        lines.append("Next required actions before demo:")
        for a in report["next_required_actions"]:
            lines.append(f"  - {a}")
    if report.get("not_required_yet"):
        lines.append("")
        lines.append("Not required yet:")
        for a in report["not_required_yet"]:
            lines.append(f"  - {a}")
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


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only demo-readiness blocker inspection.  Re-uses the "
            "Section C demo-readiness checklist's verdicts and "
            "reorganises them into blockers / solved / partial / "
            "next-required-action narrative.  Never mutates an "
            "artifact; never connects to a DB; never imports "
            "FastAPI; never claims demo readiness on its own — the "
            "operator owns the final decision."
        ),
    )
    parser.add_argument(
        "--repo-root", dest="repo_root", default=None,
        help=(
            "Path to the repository root.  Forwarded to the "
            "underlying checklist.  Read-only."
        ),
    )
    parser.add_argument(
        "--freeze-artifact", dest="freeze_artifact", default=None,
        help=(
            f"Path to the freeze-candidate evidence artifact.  "
            f"Defaults to {_DEFAULT_FREEZE_ARTIFACT!r} under the "
            f"repo root.  Read-only."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text view.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the inspection has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_demo_readiness_blocker_inspection(
        repo_root=args.repo_root,
        freeze_artifact=args.freeze_artifact,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_demo_readiness_blocker_inspection",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Local cleanup guard for untracked demo/project debris.

A read-only guard that walks the current ``git status --porcelain``
output and classifies each untracked path into EXACTLY one of four
operator-decision categories:

1. ``keep_local`` — leave the file on disk; the guard recommends
   neither committing nor deleting it.  Covers generated artifacts,
   demo scripts, and the local review log.
2. ``future_commit_candidate`` — the operator may decide to commit
   this later.  Currently scoped to the curated event loader /
   validator / archive-status surface and their companion tests.
3. ``safe_to_delete_manually`` — the operator may delete this
   manually if it is not actively needed.  Covers planning / audit
   scratch and generated CSV packets.
4. ``risky_or_unknown`` — needs operator inspection before any
   decision.  The guard refuses to take a stance.

This guard is intentionally narrower than the grouping report: it
produces a per-path decision list, not a commit plan.

Read-only by construction
-------------------------

* No ``git add`` / ``git commit`` / ``git push`` — the CLI runs
  ``git status --porcelain`` only, which is a read-only inspection.
* No DB connection.  No ``yfinance`` / ``market_data`` / paid
  provider / LLM call.  No FastAPI surface imported at module load.
* No file deleted, renamed, or otherwise mutated.  ``--output`` is
  the only filesystem side effect, and only when explicitly passed.
* Classification rules are declared as data inside this module;
  the tool merely walks untracked paths against those rules.

Conservative wording
--------------------

Banned tokens in every emitted prose: ``proof``, ``proven``,
``guaranteed``, ``automatically``, ``validated``, ``approved``,
``production ready``, ``production-ready``, ``definitely``,
``staged automatically``, ``committed automatically``,
``deleted automatically``.  The guard proposes; the operator
decides.

Output contract (JSON)::

    {
      "ok":                          bool,
      "repo_status_summary":         { ... counts ... },
      "decisions":                   [ {decision_dict}, ... ],
      "by_category": {
        "keep_local":               [str, ...],
        "future_commit_candidate":  [str, ...],
        "safe_to_delete_manually":  [str, ...],
        "risky_or_unknown":         [str, ...],
      },
      "recommended_next_action":     str,
      "generated_at_marker":         str,
      "warnings":                    [str, ...],
      "errors":                      [str, ...],
    }

Each ``decision_dict`` carries::

    {
      "path":             str,
      "category":         str,   # one of the four canonical values
      "rationale":        str,
      "operator_action":  str,
    }

Usage::

    python scripts/local_untracked_cleanup_guard.py --json
    python scripts/local_untracked_cleanup_guard.py --json \\
        --output artifacts/local_untracked_cleanup_guard.json
    python scripts/local_untracked_cleanup_guard.py --json \\
        --status-file path/to/captured_status.txt
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Category constants
# ---------------------------------------------------------------------------


CAT_KEEP_LOCAL:    str = "keep_local"
CAT_FUTURE_COMMIT: str = "future_commit_candidate"
CAT_DELETE:        str = "safe_to_delete_manually"
CAT_RISKY:         str = "risky_or_unknown"


_CATEGORY_ORDER: tuple[str, ...] = (
    CAT_KEEP_LOCAL,
    CAT_FUTURE_COMMIT,
    CAT_DELETE,
    CAT_RISKY,
)


# ---------------------------------------------------------------------------
# Classification rules — declarative data, walked by `_classify_path`.
# ---------------------------------------------------------------------------


# Per-path rule: (category, rationale, operator_action).  Exact match.
_EXACT_RULES: dict[str, tuple[str, str, str]] = {
    # --- keep local --------------------------------------------------------
    "DEMO_SCRIPT_SECTION_C.md": (
        CAT_KEEP_LOCAL,
        (
            "Section C demo narration script — meant to live on the "
            "operator's machine as a reference, not in source control."
        ),
        (
            "Leave on disk; do not stage or commit.  No manual action "
            "required unless the operator wants to remove it locally."
        ),
    ),
    "ULTRA_REVIEW.md": (
        CAT_KEEP_LOCAL,
        (
            "Local review log; kept out of source control by convention "
            "and surfaced here so the operator does not commit it by "
            "accident."
        ),
        (
            "Leave on disk, or delete manually if the review is no "
            "longer needed.  Either choice is safe."
        ),
    ),
    "short_horizon_repair_packet.csv": (
        CAT_DELETE,
        (
            "Generated short-horizon repair packet CSV; regenerated on "
            "demand by the repair surface and not source-controlled."
        ),
        (
            "Delete manually if no longer referenced, or archive "
            "manually outside the repo if the operator needs to keep a "
            "snapshot.  Do not commit."
        ),
    ),

    # --- future commit candidate (curated event tooling) -------------------
    "scripts/curated_event_loader.py": (
        CAT_FUTURE_COMMIT,
        (
            "Curated event loader script — part of the curated event "
            "tooling surface the operator has indicated may be ready "
            "to commit as a single group."
        ),
        (
            "The operator may decide to commit this alongside the "
            "curated validator and archive-status scripts; run their "
            "tests first."
        ),
    ),
    "scripts/curated_event_validator.py": (
        CAT_FUTURE_COMMIT,
        (
            "Curated event validator script — part of the curated "
            "event tooling surface."
        ),
        (
            "The operator may decide to commit this alongside the "
            "curated loader and archive-status scripts; run their "
            "tests first."
        ),
    ),
    "scripts/curated_archive_status.py": (
        CAT_FUTURE_COMMIT,
        (
            "Curated archive-status reporter script — part of the "
            "curated event tooling surface."
        ),
        (
            "The operator may decide to commit this alongside the "
            "curated loader and validator scripts; run their tests "
            "first."
        ),
    ),
    "tests/test_curated_event_loader.py": (
        CAT_FUTURE_COMMIT,
        (
            "Companion test for the curated event loader; part of the "
            "curated event tooling surface."
        ),
        (
            "The operator may decide to commit this with the curated "
            "loader script."
        ),
    ),
    "tests/test_curated_event_validator.py": (
        CAT_FUTURE_COMMIT,
        (
            "Companion test for the curated event validator; part of "
            "the curated event tooling surface."
        ),
        (
            "The operator may decide to commit this with the curated "
            "validator script."
        ),
    ),
    "tests/test_curated_archive_status.py": (
        CAT_FUTURE_COMMIT,
        (
            "Companion test for the curated archive-status reporter; "
            "part of the curated event tooling surface."
        ),
        (
            "The operator may decide to commit this with the curated "
            "archive-status script."
        ),
    ),

    # --- planning / audit scratch — delete manually unless actively needed
    "scripts/daily_artifact_gate_implementation_plan.py": (
        CAT_DELETE,
        (
            "Planning script for the daily artifact gate; a one-shot "
            "narrative tool, not part of the runtime surface."
        ),
        (
            "Delete manually unless actively referenced for the next "
            "planning cycle.  Do not commit without operator review."
        ),
    ),
    "scripts/demo_readiness_blocker_inspection.py": (
        CAT_DELETE,
        (
            "Demo-readiness blocker inspection script; an audit tool "
            "used to walk current blockers, not part of the runtime "
            "surface."
        ),
        (
            "Delete manually unless actively needed for the next "
            "demo-readiness review.  Do not commit without operator "
            "review."
        ),
    ),
    "scripts/section_c_daily_artifact_gate_plan.py": (
        CAT_DELETE,
        (
            "Section C daily artifact gate planning script; a "
            "narrative planning surface, not part of the runtime "
            "surface."
        ),
        (
            "Delete manually unless actively referenced for the next "
            "Section C gate cycle.  Do not commit without operator "
            "review."
        ),
    ),
    "scripts/section_c_demo_readiness_checklist.py": (
        CAT_DELETE,
        (
            "Section C demo-readiness checklist planner; a narrative "
            "planning surface, not part of the runtime surface."
        ),
        (
            "Delete manually unless actively referenced for the next "
            "Section C demo-readiness review.  Do not commit without "
            "operator review."
        ),
    ),
    "scripts/untracked_tool_grouping_report.py": (
        CAT_DELETE,
        (
            "Untracked tool grouping audit report; a meta-tool that "
            "proposes commit groups for other untracked scripts."
        ),
        (
            "Delete manually unless actively needed.  Do not commit "
            "without operator review — this guard is a more focused "
            "successor."
        ),
    ),
    "tests/test_daily_artifact_gate_implementation_plan.py": (
        CAT_DELETE,
        (
            "Companion test for a planning-only script; not part of "
            "the runtime test surface."
        ),
        (
            "Delete manually alongside its planning script unless "
            "actively needed.  Do not commit without operator review."
        ),
    ),
    "tests/test_demo_readiness_blocker_inspection.py": (
        CAT_DELETE,
        (
            "Companion test for a planning-only script; not part of "
            "the runtime test surface."
        ),
        (
            "Delete manually alongside its planning script unless "
            "actively needed.  Do not commit without operator review."
        ),
    ),
    "tests/test_section_c_daily_artifact_gate_plan.py": (
        CAT_DELETE,
        (
            "Companion test for a Section C planning-only script; not "
            "part of the runtime test surface."
        ),
        (
            "Delete manually alongside its planning script unless "
            "actively needed.  Do not commit without operator review."
        ),
    ),
    "tests/test_section_c_demo_readiness_checklist.py": (
        CAT_DELETE,
        (
            "Companion test for a Section C planning-only script; not "
            "part of the runtime test surface."
        ),
        (
            "Delete manually alongside its planning script unless "
            "actively needed.  Do not commit without operator review."
        ),
    ),
    "tests/test_untracked_tool_grouping_report.py": (
        CAT_DELETE,
        (
            "Companion test for the untracked-tool grouping audit "
            "report; not part of the runtime test surface."
        ),
        (
            "Delete manually alongside its audit script unless "
            "actively needed.  Do not commit without operator review."
        ),
    ),

    # --- explicitly risky / unknown ---------------------------------------
    # Scripts and tests that touch smoke / freeze-validation surfaces but
    # are not part of the spec's commit-ready set — flagged for inspection
    # rather than silently grouped.
    "scripts/short_horizon_repair_apply_smoke.py": (
        CAT_RISKY,
        (
            "Short-horizon repair apply smoke script — not explicitly "
            "addressed in the cleanup spec.  The operator should "
            "inspect before deciding."
        ),
        (
            "Inspect manually and decide: keep local, commit alongside "
            "a wider repair-smoke surface, or delete.  The guard does "
            "not recommend an action here."
        ),
    ),
    "scripts/validate_freeze_candidate_artifact.py": (
        CAT_RISKY,
        (
            "Freeze-candidate artifact validator — not explicitly "
            "addressed in the cleanup spec.  Touches freeze artifact "
            "evidence so the operator should inspect before deciding."
        ),
        (
            "Inspect manually and decide: keep local, commit alongside "
            "the freeze-artifact surface, or delete.  The guard does "
            "not recommend an action here."
        ),
    ),
    "scripts/xle_benchmark_sensitivity_compare_smoke.py": (
        CAT_RISKY,
        (
            "XLE benchmark sensitivity smoke — not explicitly addressed "
            "in the cleanup spec.  The operator should inspect before "
            "deciding."
        ),
        (
            "Inspect manually and decide: keep local, commit alongside "
            "the XLE benchmark surface, or delete.  The guard does not "
            "recommend an action here."
        ),
    ),
    "tests/test_manual_event_intake_worksheet.py": (
        CAT_RISKY,
        (
            "Companion test for a manual event intake worksheet whose "
            "script is not present in the current untracked set — an "
            "orphan test the operator should inspect before deciding."
        ),
        (
            "Inspect manually and decide: locate the intake worksheet "
            "script, delete the orphan test, or commit both together."
        ),
    ),
    "tests/test_short_horizon_repair_apply_smoke.py": (
        CAT_RISKY,
        (
            "Companion test for a smoke surface not explicitly "
            "addressed in the cleanup spec — the operator should "
            "inspect before deciding."
        ),
        (
            "Inspect manually and decide alongside its companion "
            "script.  The guard does not recommend an action here."
        ),
    ),
    "tests/test_validate_freeze_candidate_artifact.py": (
        CAT_RISKY,
        (
            "Companion test for the freeze-candidate validator — not "
            "explicitly addressed in the cleanup spec.  The operator "
            "should inspect before deciding."
        ),
        (
            "Inspect manually and decide alongside its companion "
            "script.  The guard does not recommend an action here."
        ),
    ),
    "tests/test_xle_benchmark_sensitivity_compare_smoke.py": (
        CAT_RISKY,
        (
            "Companion test for the XLE benchmark sensitivity smoke — "
            "not explicitly addressed in the cleanup spec.  The "
            "operator should inspect before deciding."
        ),
        (
            "Inspect manually and decide alongside its companion "
            "script.  The guard does not recommend an action here."
        ),
    ),
}


# Prefix rule: (prefix, category, rationale, operator_action).  Matches
# any path equal to ``prefix`` or starting with ``prefix``.  Used for
# directories that surface as a single porcelain entry (``artifacts/``,
# ``examples/``) and also catches any nested files if the porcelain
# output expands the directory.
_PREFIX_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "artifacts/",
        CAT_KEEP_LOCAL,
        (
            "Generated evidence artifacts directory; regenerated on "
            "demand and kept local unless the operator explicitly "
            "promotes a specific artifact."
        ),
        (
            "Leave on disk.  Do not stage or commit unless the "
            "operator explicitly promotes a single artifact."
        ),
    ),
    (
        "examples/",
        CAT_KEEP_LOCAL,
        (
            "Local exploration scratchpad; defer unless tied to the "
            "curated event loader commit, in which case the operator "
            "should review each example before promoting."
        ),
        (
            "Leave on disk and defer.  If a future curated-loader "
            "commit needs an example, the operator should promote "
            "that file manually."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_local_untracked_cleanup_guard(
    *,
    status_lines: Sequence[str] | None = None,
    output_path:  str | None = None,
) -> dict[str, Any]:
    """Build the cleanup-guard report.

    Parameters
    ----------
    status_lines : sequence of porcelain ``git status`` lines.  When
        ``None``, an empty list is assumed; tests feed lines directly
        and the CLI fills them in from a file or from a read-only
        ``git status --porcelain`` invocation.
    output_path : optional path to write the JSON envelope to.

    Returns
    -------
    dict
        The JSON envelope.  See module docstring for the contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    lines = list(status_lines) if status_lines is not None else []
    untracked = _collect_untracked_paths(lines)

    decisions: list[dict[str, Any]] = []
    by_category: dict[str, list[str]] = {c: [] for c in _CATEGORY_ORDER}

    for path in untracked:
        category, rationale, action = _classify_path(path)
        decisions.append({
            "path":            path,
            "category":        category,
            "rationale":       rationale,
            "operator_action": action,
        })
        by_category[category].append(path)

    for cat in _CATEGORY_ORDER:
        by_category[cat] = sorted(by_category[cat])

    summary: dict[str, Any] = {
        "untracked_line_count":          len(untracked),
        "keep_local_count":              len(by_category[CAT_KEEP_LOCAL]),
        "future_commit_candidate_count": len(by_category[CAT_FUTURE_COMMIT]),
        "safe_to_delete_manually_count": len(by_category[CAT_DELETE]),
        "risky_or_unknown_count":        len(by_category[CAT_RISKY]),
    }

    recommended = _build_recommended_next_action(
        summary=summary, by_category=by_category,
    )

    envelope: dict[str, Any] = {
        "ok":                      not errors,
        "repo_status_summary":     summary,
        "decisions":               decisions,
        "by_category":             by_category,
        "recommended_next_action": recommended,
        "generated_at_marker":     "local_untracked_cleanup_guard/v1",
        "warnings":                warnings,
        "errors":                  errors,
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
# Parsing & classification
# ---------------------------------------------------------------------------


def _collect_untracked_paths(status_lines: Sequence[str]) -> list[str]:
    """Return the list of untracked paths from porcelain output.

    Only ``??`` lines are treated as untracked.  Modified (``M ``,
    `` M``, ``MM``) or other status codes are ignored — the operator
    handles those separately.
    """
    out: list[str] = []
    for raw in status_lines:
        if not isinstance(raw, str):
            continue
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if not line.startswith("?? "):
            continue
        path = line[3:]
        if not path:
            continue
        out.append(path)
    return out


def _classify_path(path: str) -> tuple[str, str, str]:
    """Return (category, rationale, operator_action) for ``path``.

    Exact-match rules win first; prefix rules cover directories; the
    fallback is :data:`CAT_RISKY` with an operator-review rationale.
    """
    if path in _EXACT_RULES:
        return _EXACT_RULES[path]
    for prefix, category, rationale, action in _PREFIX_RULES:
        if path == prefix or path.startswith(prefix):
            return (category, rationale, action)
    return (
        CAT_RISKY,
        (
            "Path is not addressed by any cleanup-guard rule — the "
            "operator should inspect it before deciding whether to "
            "keep, commit, or delete it."
        ),
        (
            "Inspect manually and decide.  The guard does not "
            "recommend an action for unknown paths."
        ),
    )


def _build_recommended_next_action(
    *,
    summary:     dict[str, Any],
    by_category: dict[str, list[str]],
) -> str:
    if summary.get("untracked_line_count", 0) == 0:
        return (
            "No untracked paths to review on this run; the operator "
            "can move on."
        )
    parts = [
        f"The operator should review the {summary['untracked_line_count']} "
        f"untracked path(s) below:",
        f"  - {summary['keep_local_count']} keep_local (leave on disk).",
        f"  - {summary['future_commit_candidate_count']} "
        f"future_commit_candidate (consider committing as a group).",
        f"  - {summary['safe_to_delete_manually_count']} "
        f"safe_to_delete_manually (delete by hand if not needed).",
        f"  - {summary['risky_or_unknown_count']} risky_or_unknown "
        f"(inspect each before deciding).",
    ]
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Git seam — read-only inspection only.
# ---------------------------------------------------------------------------


def _git_status_lines(*, repo_root: str | None = None) -> list[str]:
    """Return ``git status --porcelain`` lines for ``repo_root``.

    Read-only.  The guard never invokes any mutating git verb.  Tests
    bypass this seam by feeding ``status_lines`` directly to
    :func:`run_local_untracked_cleanup_guard`.
    """
    cwd = repo_root or str(ROOT)
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return proc.stdout.splitlines()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Local untracked cleanup guard", ""]
    lines.append(f"OK: {report['ok']}")
    summary = report["repo_status_summary"]
    lines.append(
        f"Untracked lines: {summary.get('untracked_line_count')}  "
        f"(keep_local: {summary.get('keep_local_count')}, "
        f"future_commit_candidate: "
        f"{summary.get('future_commit_candidate_count')}, "
        f"safe_to_delete_manually: "
        f"{summary.get('safe_to_delete_manually_count')}, "
        f"risky_or_unknown: {summary.get('risky_or_unknown_count')})"
    )
    lines.append("")
    bc = report["by_category"]
    for cat in _CATEGORY_ORDER:
        paths = bc.get(cat, [])
        lines.append(f"[{cat}]  ({len(paths)} path(s))")
        if not paths:
            lines.append("  (none)")
        for p in paths:
            entry = next(
                (d for d in report["decisions"] if d["path"] == p),
                None,
            )
            if entry is None:
                lines.append(f"  - {p}")
                continue
            lines.append(f"  - {p}")
            lines.append(f"      rationale: {entry['rationale']}")
            lines.append(f"      action:    {entry['operator_action']}")
        lines.append("")
    lines.append(
        "Recommended next action: " + report["recommended_next_action"]
    )
    if report["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report["errors"]:
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
            "Read-only guard that walks `git status --porcelain` "
            "and classifies each untracked path into one of four "
            "operator-decision categories.  Never stages, commits, "
            "pushes, deletes, or mutates anything on its own — the "
            "operator owns every action."
        ),
    )
    parser.add_argument(
        "--repo-root", dest="repo_root", default=None,
        help=(
            "Path to the repository root.  Defaults to the parent of "
            "this script.  Read-only."
        ),
    )
    parser.add_argument(
        "--status-file", dest="status_file", default=None,
        help=(
            "Optional path to a file containing pre-captured "
            "`git status --porcelain` output, one line per entry.  "
            "When omitted, the CLI runs `git status --porcelain` "
            "against --repo-root in read-only mode."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the guard has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    status_lines: list[str]
    if args.status_file:
        try:
            status_lines = Path(args.status_file).read_text(
                encoding="utf-8",
            ).splitlines()
        except OSError as exc:
            envelope = {
                "ok": False,
                "repo_status_summary": {},
                "decisions": [],
                "by_category": {c: [] for c in _CATEGORY_ORDER},
                "recommended_next_action": (
                    "Inspect the --status-file path; the guard could "
                    "not read it."
                ),
                "generated_at_marker": "local_untracked_cleanup_guard/v1",
                "warnings": [],
                "errors": [
                    f"could not read --status-file {args.status_file!r}: "
                    f"{type(exc).__name__}: {exc}"
                ],
            }
            print(_render_json(envelope), file=output)
            return 1
    else:
        status_lines = _git_status_lines(repo_root=args.repo_root)

    report = run_local_untracked_cleanup_guard(
        status_lines=status_lines,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_local_untracked_cleanup_guard",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

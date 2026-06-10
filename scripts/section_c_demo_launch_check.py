#!/usr/bin/env python3
"""Section C demo launch helper — local pre-launch wrapper.

Tells the operator whether the Section C demo is ready to open and
rehearse.  Combines two read-only inspections:

1. **Demo artifact bundle** — verifies that
   ``evidence_artifacts/section_c_v1/`` exists and contains the five
   tracked bundle files (three Daily demo artifacts, the freeze-
   candidate evidence artifact, and the reviewed-candidate CSV).
2. **Local acceptance checks** — delegates to
   :func:`scripts.run_section_c_demo_checks.run_section_c_demo_checks`,
   which runs six commands (two Python smokes plus four frontend
   commands) and reports which exited zero.

Read-only by construction
-------------------------

* No DB connection, no ``yfinance`` / ``market_data`` / paid
  provider / LLM, no FastAPI surface imported at module load.
* No server is started.  The inner runbook uses an in-process
  FastAPI ``TestClient``; this helper itself does not import
  ``TestClient`` either — it shells out only via the inner
  runner's seam.
* No artifact mutation.  The helper inspects the bundle directory
  on disk; it never copies, moves, deletes, or rewrites any file.
* The seam :func:`run_section_c_demo_launch_check` accepts an
  optional ``demo_check_runner`` callable so tests can stub the
  inner check pipeline without spawning real subprocesses.

Conservative wording
--------------------

The helper checks readiness for a *rehearsal*.  It never claims
the demo is final research evidence, production-ready, or fit to
ship.  Banned tokens in every emitted string: ``proof``,
``proven``, ``guaranteed``, ``automatically``, ``validated``,
``approved``, ``production ready``, ``production-ready``,
``definitely``, ``final research evidence``, ``research truth``,
``ready to ship``, ``fit to ship``.

Output contract (JSON)::

    {
      "ok":                          bool,
      "demo_artifact_bundle_status": {
        "ok":             bool,
        "bundle_path":    str,
        "expected_files": [str, ...],
        "present_files":  [str, ...],
        "missing_files":  [str, ...],
        "reason":         str,
      },
      "checks":                      [ {check_dict}, ... ],
      "failed_checks":               [str, ...],
      "warnings":                    [str, ...],
      "errors":                      [str, ...],
      "recommended_next_action":     str,
    }

The envelope ``ok`` is ``True`` iff the bundle is present *and*
every inner check exited zero.

Usage::

    python scripts/section_c_demo_launch_check.py
    python scripts/section_c_demo_launch_check.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Bundle catalogue
# ---------------------------------------------------------------------------


_BUNDLE_DIR_RELATIVE: tuple[str, ...] = ("evidence_artifacts", "section_c_v1")


_REQUIRED_BUNDLE_FILES: tuple[str, ...] = (
    "analyzed_event_artifact_daily-demo-001.json",
    "analyzed_event_artifact_daily-demo-002.json",
    "analyzed_event_artifact_daily-demo-003.json",
    "freeze_candidate_evidence.json",
    "daily_reviewed_candidates.csv",
)


# ---------------------------------------------------------------------------
# Bundle inspection — pure read-only
# ---------------------------------------------------------------------------


def _inspect_demo_artifact_bundle(*, repo_root: Path) -> dict[str, Any]:
    """Return the demo-artifact bundle status dict.

    Read-only: walks the bundle directory and checks each expected
    file exists.  Never creates, mutates, or deletes anything.
    """
    bundle_dir = repo_root.joinpath(*_BUNDLE_DIR_RELATIVE)
    expected = sorted(_REQUIRED_BUNDLE_FILES)

    present: list[str] = []
    missing: list[str] = []

    bundle_exists = bundle_dir.is_dir()
    if bundle_exists:
        for name in expected:
            if (bundle_dir / name).is_file():
                present.append(name)
            else:
                missing.append(name)
    else:
        missing = list(expected)

    if not missing and bundle_exists:
        reason = (
            "Stable demo artifact bundle is present with all expected "
            "files; the demo backend can read from it."
        )
        ok = True
    elif not bundle_exists:
        reason = (
            f"Stable demo artifact bundle directory is not present at "
            f"{bundle_dir.as_posix()!r}; the operator should promote "
            f"the bundle (see scripts/promote_demo_artifacts_preview.py) "
            f"or clone a tracked copy before rehearsing."
        )
        ok = False
    else:
        reason = (
            f"Stable demo artifact bundle is incomplete at "
            f"{bundle_dir.as_posix()!r}; "
            f"{len(missing)} file(s) missing — restore them before "
            f"rehearsing."
        )
        ok = False

    return {
        "ok":             ok,
        "bundle_path":    bundle_dir.as_posix(),
        "expected_files": expected,
        "present_files":  sorted(present),
        "missing_files":  sorted(missing),
        "reason":         reason,
    }


# ---------------------------------------------------------------------------
# Inner check runner — patchable seam
# ---------------------------------------------------------------------------


def _default_demo_check_runner(*, repo_root: Path) -> dict[str, Any]:
    """Default seam: delegate to the existing Section C runbook.

    The inner runner shells out to the six acceptance checks (two
    Python smokes plus four frontend commands) and reports their
    exit codes.  Tests pass an alternative callable to avoid
    spawning real subprocesses.
    """
    from scripts.run_section_c_demo_checks import (  # noqa: WPS433 — local seam
        run_section_c_demo_checks,
    )
    return run_section_c_demo_checks(repo_root=repo_root)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def run_section_c_demo_launch_check(
    *,
    repo_root:         str | Path | None = None,
    demo_check_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the launch-check envelope.

    Parameters
    ----------
    repo_root : path to the repository root.  Defaults to the parent
        of this script.
    demo_check_runner : optional callable returning the inner-runner
        envelope.  Tests use this to inject a deterministic envelope
        without spawning subprocesses.  Defaults to
        :func:`_default_demo_check_runner`.

    Returns
    -------
    dict
        The JSON envelope.  See module docstring for the contract.
    """
    root = Path(repo_root) if repo_root else ROOT
    runner = demo_check_runner or _default_demo_check_runner

    warnings: list[str] = []
    errors:   list[str] = []

    bundle_status = _inspect_demo_artifact_bundle(repo_root=root)

    try:
        inner_envelope = runner(repo_root=root)
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"inner demo-check runner raised {type(exc).__name__}: {exc}"
        )
        inner_envelope = {
            "ok":            False,
            "checks":        [],
            "failed_checks": [],
            "warnings":      [],
            "errors":        [str(exc)],
        }

    checks:        list[dict[str, Any]] = list(inner_envelope.get("checks") or [])
    failed_checks: list[str] = list(inner_envelope.get("failed_checks") or [])
    inner_warns    = list(inner_envelope.get("warnings") or [])
    inner_errs     = list(inner_envelope.get("errors") or [])
    warnings.extend(inner_warns)
    errors.extend(inner_errs)

    ok = (
        bundle_status["ok"]
        and bool(inner_envelope.get("ok"))
        and not errors
        and not failed_checks
    )

    recommended = _build_recommended_next_action(
        bundle_ok=bundle_status["ok"],
        bundle_path=bundle_status["bundle_path"],
        missing_files=bundle_status["missing_files"],
        failed_checks=failed_checks,
        all_ok=ok,
    )

    return {
        "ok":                          ok,
        "demo_artifact_bundle_status": bundle_status,
        "checks":                      checks,
        "failed_checks":               failed_checks,
        "warnings":                    warnings,
        "errors":                      errors,
        "recommended_next_action":     recommended,
    }


def _build_recommended_next_action(
    *,
    bundle_ok:     bool,
    bundle_path:   str,
    missing_files: Sequence[str],
    failed_checks: Sequence[str],
    all_ok:        bool,
) -> str:
    if all_ok:
        return (
            "Every pre-launch check passed and the demo artifact "
            "bundle is present.  The operator may now start the "
            "backend (uvicorn) and the frontend (vite) and rehearse "
            "the Section C demo against the local bundle.  Reminder: "
            "the bundle is a demo input for rehearsal — keep that "
            "framing in the walkthrough and do not present it as a "
            "research claim."
        )

    parts: list[str] = []
    if not bundle_ok:
        if missing_files:
            parts.append(
                f"Restore the stable demo artifact bundle at "
                f"{bundle_path!r} — "
                f"{len(missing_files)} file(s) missing: "
                f"{', '.join(missing_files)}.  See "
                f"scripts/promote_demo_artifacts_preview.py for "
                f"the promotion workflow."
            )
        else:
            parts.append(
                f"Inspect the demo artifact bundle path "
                f"{bundle_path!r}; the helper could not confirm it is "
                f"ready."
            )
    if failed_checks:
        parts.append(
            f"Re-run and fix the failed pre-launch check(s): "
            f"{', '.join(failed_checks)}.  The operator should not "
            f"rehearse until each one exits zero."
        )
    if not parts:
        parts.append(
            "The launch helper reported an error — inspect the "
            "errors list before rehearsing."
        )
    parts.append(
        "Reminder: the Section C demo is a rehearsal aid — do not "
        "present it as a research claim."
    )
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def _render_text(envelope: dict[str, Any]) -> str:
    lines: list[str] = ["Section C demo launch helper", ""]
    lines.append(f"OK: {envelope['ok']}")
    bundle = envelope["demo_artifact_bundle_status"]
    lines.append("")
    lines.append("Demo artifact bundle:")
    lines.append(f"  path:    {bundle['bundle_path']}")
    lines.append(f"  ok:      {bundle['ok']}")
    lines.append(f"  present: {len(bundle['present_files'])}")
    lines.append(f"  missing: {len(bundle['missing_files'])}")
    if bundle["missing_files"]:
        for name in bundle["missing_files"]:
            lines.append(f"    - {name}")
    lines.append(f"  reason:  {bundle['reason']}")
    lines.append("")
    lines.append("Local acceptance checks:")
    for c in envelope["checks"]:
        status = "PASS" if c.get("ok") else "FAIL"
        rc = c.get("returncode")
        rc_part = f"rc={rc}" if rc is not None else "rc=-"
        duration = c.get("duration_seconds", 0.0)
        lines.append(
            f"  [{status}] {c.get('check_id', '?'):<42} "
            f"{rc_part}  ({duration:.2f}s)"
        )
        err = c.get("error")
        if err:
            lines.append(f"      error: {err}")
    if envelope["failed_checks"]:
        lines.append("")
        lines.append("Failed checks:")
        for cid in envelope["failed_checks"]:
            lines.append(f"  - {cid}")
    if envelope["warnings"]:
        lines.append("")
        lines.append("Warnings:")
        for w in envelope["warnings"]:
            lines.append(f"  - {w}")
    if envelope["errors"]:
        lines.append("")
        lines.append("Errors:")
        for e in envelope["errors"]:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append(
        "Recommended next action: " + envelope["recommended_next_action"]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local Section C demo launch helper.  Verifies the stable "
            "demo artifact bundle is present, then runs the six "
            "pre-launch acceptance checks (two Python smokes plus "
            "four frontend commands).  Read-only: does not write to "
            "the DB, does not mutate artifacts, does not start a "
            "server, and does not import any paid provider or LLM "
            "surface."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--repo-root", dest="repo_root", default=None,
        help=(
            "Path to the repository root.  Defaults to the parent of "
            "this script."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(
    argv:              Sequence[str] | None = None,
    *,
    out:               Any = None,
    demo_check_runner: Callable[..., dict[str, Any]] | None = None,
) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    envelope = run_section_c_demo_launch_check(
        repo_root=args.repo_root,
        demo_check_runner=demo_check_runner,
    )

    if args.json:
        print(_render_json(envelope), file=output)
    else:
        print(_render_text(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_demo_launch_check",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Section C demo runbook — local operator script.

Runs the six local acceptance checks an operator should clear before
the Section C demo rehearsal:

* ``demo_api_smoke``                          —
  ``python scripts/demo_api_smoke.py --json``
* ``no_paid_smoke``                           —
  ``python scripts/no_paid_smoke.py --json``
* ``frontend_typecheck``                      — ``npm run typecheck``
* ``frontend_build``                          — ``npm run build``
* ``frontend_evidence_summary_panel_test``    — vitest filter for the
  evidence-summary-panel test file
* ``frontend_section_c_demo_test``            — vitest filter for the
  section-c-demo page test file

Local operator script only — read-only by construction
------------------------------------------------------

* No DB connection; no write to ``events.db``, ``backups/``,
  ``artifacts/``, ``news_inbox.json``, or any cache.
* No paid provider, ``yfinance``, ``market_data``, or LLM seam
  imported at module load.  The Python sub-commands the runbook
  invokes own their own read-only contracts and are documented as
  such — the runbook itself never imports the FastAPI app.
* No server is started.  The Python sub-commands use FastAPI's
  in-process ``TestClient``; ``npm run build`` produces a bundle
  but never binds a port.
* The runbook shells out — it never modifies the repository, the
  artifact directory, or the git index.  Sub-command output is
  captured to memory and surfaced to the operator; it is never
  written back to disk by this script.

Wording is conservative.  The runbook reports which sub-commands
exited zero.  It does not claim the demo is ready, fit to ship, or
otherwise blessed — the operator owns that judgement.

Output contract (JSON)::

    {
      "ok":             bool,
      "checks": [
        {
          "check_id":         str,
          "description":      str,
          "command":          [str, ...],
          "ok":               bool,
          "returncode":       int | null,
          "duration_seconds": float,
          "stdout_tail":      str,
          "stderr_tail":      str,
          "error":            str | null,
        },
        ...
      ],
      "failed_checks":  [str, ...],
      "warnings":       [str, ...],
      "errors":         [str, ...],
    }

The envelope ``ok`` is ``True`` iff every check exited zero and
emitted no seam-level error.  ``failed_checks`` lists the
``check_id`` of each check that did not pass.  Process exit code
matches ``ok`` (``0`` on pass, ``1`` otherwise) so the runbook can
be wired into a pre-rehearsal shell session and fail loud.

Usage::

    python scripts/run_section_c_demo_checks.py
    python scripts/run_section_c_demo_checks.py --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Check catalogue
# ---------------------------------------------------------------------------


_FRONTEND_DIR_NAME: str = "frontend"


_CHECK_DEMO_API_SMOKE:       str = "demo_api_smoke"
_CHECK_NO_PAID_SMOKE:        str = "no_paid_smoke"
_CHECK_FRONTEND_TYPECHECK:   str = "frontend_typecheck"
_CHECK_FRONTEND_BUILD:       str = "frontend_build"
_CHECK_EVIDENCE_PANEL_TEST:  str = "frontend_evidence_summary_panel_test"
_CHECK_SECTION_C_DEMO_TEST:  str = "frontend_section_c_demo_test"


# Tail size kept narrow so the JSON envelope stays readable even when
# ``npm run build`` floods stdout with bundler chatter.
_STDOUT_TAIL_BYTES:  int = 4_000
_STDERR_TAIL_BYTES:  int = 4_000

# Per-check timeout — generous enough for the slowest local step
# (``npm run build``) but bounded so a wedged sub-command does not
# stall the rehearsal indefinitely.
_PER_CHECK_TIMEOUT_SECONDS: float = 600.0


def _check_specs(*, repo_root: Path) -> tuple[dict[str, Any], ...]:
    """Return the per-check command catalogue.

    Each entry carries the ``check_id``, a one-line description, the
    command to run, and the working directory.  Built from
    ``repo_root`` so tests can drive the runbook against a synthetic
    tree if needed.
    """
    frontend_dir = repo_root / _FRONTEND_DIR_NAME
    return (
        {
            "check_id":    _CHECK_DEMO_API_SMOKE,
            "description": (
                "Demo API smoke — exercises the four /demo/* endpoints "
                "in-process via FastAPI TestClient and reports response "
                "shape only."
            ),
            "command":     [
                sys.executable, "scripts/demo_api_smoke.py", "--json",
            ],
            "cwd":         repo_root,
            "shell":       False,
        },
        {
            "check_id":    _CHECK_NO_PAID_SMOKE,
            "description": (
                "No-paid in-process smoke — guards the demo-critical "
                "zero-cost endpoints against LLM / yfinance / provider "
                "regressions."
            ),
            "command":     [
                sys.executable, "scripts/no_paid_smoke.py", "--json",
            ],
            "cwd":         repo_root,
            "shell":       False,
        },
        {
            "check_id":    _CHECK_FRONTEND_TYPECHECK,
            "description": (
                "Frontend typecheck — runs `tsc -b` over the demo "
                "frontend project."
            ),
            "command":     ["npm", "run", "typecheck"],
            "cwd":         frontend_dir,
            "shell":       True,
        },
        {
            "check_id":    _CHECK_FRONTEND_BUILD,
            "description": (
                "Frontend build — runs `tsc -b && vite build`; "
                "produces a bundle but binds no port."
            ),
            "command":     ["npm", "run", "build"],
            "cwd":         frontend_dir,
            "shell":       True,
        },
        {
            "check_id":    _CHECK_EVIDENCE_PANEL_TEST,
            "description": (
                "Frontend test — vitest filter on the evidence-"
                "summary-panel test file."
            ),
            "command":     [
                "npm", "test", "--", "evidence-summary-panel",
            ],
            "cwd":         frontend_dir,
            "shell":       True,
        },
        {
            "check_id":    _CHECK_SECTION_C_DEMO_TEST,
            "description": (
                "Frontend test — vitest filter on the section-c-demo "
                "page test file."
            ),
            "command":     [
                "npm", "test", "--", "section-c-demo",
            ],
            "cwd":         frontend_dir,
            "shell":       True,
        },
    )


# ---------------------------------------------------------------------------
# Patchable subprocess seam
# ---------------------------------------------------------------------------


def _run_command(
    *,
    check_id: str,
    command:  Sequence[str],
    cwd:      Path,
    shell:    bool,
    timeout:  float = _PER_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a sub-command and return a result dict.

    Tests patch this seam directly so the runbook never has to spawn
    a real subprocess under unittest.  The return dict matches the
    check-entry contract (minus ``check_id``, ``description``,
    ``command`` which the aggregator owns):

        {
          "ok":               bool,
          "returncode":       int | None,
          "duration_seconds": float,
          "stdout_tail":      str,
          "stderr_tail":      str,
          "error":            str | None,
        }

    A missing executable, a launcher error, or a timeout all land as
    ``ok=False`` with a populated ``error`` and ``returncode=None``.
    """
    if not cwd.is_dir():
        return {
            "ok":               False,
            "returncode":       None,
            "duration_seconds": 0.0,
            "stdout_tail":      "",
            "stderr_tail":      "",
            "error":            f"working directory missing: {cwd.as_posix()}",
        }

    started = time.monotonic()
    try:
        # ``shell=True`` on Windows lets us invoke ``npm`` without
        # discovering ``npm.cmd`` by hand.  When ``shell=True``, a
        # list-form command is joined into a shell string; we quote
        # nothing because every argument we pass is a static literal.
        if shell:
            proc = subprocess.run(
                " ".join(command),
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        else:
            proc = subprocess.run(
                list(command),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
    except FileNotFoundError as exc:
        duration = time.monotonic() - started
        return {
            "ok":               False,
            "returncode":       None,
            "duration_seconds": round(duration, 3),
            "stdout_tail":      "",
            "stderr_tail":      "",
            "error":            (
                f"{check_id}: command not found: "
                f"{type(exc).__name__}: {exc}"
            ),
        }
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        return {
            "ok":               False,
            "returncode":       None,
            "duration_seconds": round(duration, 3),
            "stdout_tail":      _tail(exc.stdout, _STDOUT_TAIL_BYTES),
            "stderr_tail":      _tail(exc.stderr, _STDERR_TAIL_BYTES),
            "error":            (
                f"{check_id}: timed out after {timeout:.0f}s"
            ),
        }
    except OSError as exc:
        duration = time.monotonic() - started
        return {
            "ok":               False,
            "returncode":       None,
            "duration_seconds": round(duration, 3),
            "stdout_tail":      "",
            "stderr_tail":      "",
            "error":            (
                f"{check_id}: launcher error: "
                f"{type(exc).__name__}: {exc}"
            ),
        }

    duration = time.monotonic() - started
    return {
        "ok":               proc.returncode == 0,
        "returncode":       int(proc.returncode),
        "duration_seconds": round(duration, 3),
        "stdout_tail":      _tail(proc.stdout, _STDOUT_TAIL_BYTES),
        "stderr_tail":      _tail(proc.stderr, _STDERR_TAIL_BYTES),
        "error":            None,
    }


def _tail(text: str | bytes | None, max_bytes: int) -> str:
    """Return the last ``max_bytes`` of ``text`` as a string."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = repr(text)
    if len(text) <= max_bytes:
        return text
    return text[-max_bytes:]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def run_section_c_demo_checks(
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run every Section C demo check and return the envelope.

    See the module docstring for the full output contract.
    """
    root = Path(repo_root) if repo_root else ROOT

    warnings: list[str] = []
    errors:   list[str] = []
    checks:   list[dict[str, Any]] = []

    for spec in _check_specs(repo_root=root):
        check_id = spec["check_id"]
        try:
            result = _run_command(
                check_id=check_id,
                command=spec["command"],
                cwd=spec["cwd"],
                shell=spec["shell"],
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            result = {
                "ok":               False,
                "returncode":       None,
                "duration_seconds": 0.0,
                "stdout_tail":      "",
                "stderr_tail":      "",
                "error":            (
                    f"{check_id}: seam raised {type(exc).__name__}: {exc}"
                ),
            }

        entry: dict[str, Any] = {
            "check_id":         check_id,
            "description":      spec["description"],
            "command":          list(spec["command"]),
            "ok":               bool(result.get("ok")),
            "returncode":       result.get("returncode"),
            "duration_seconds": float(result.get("duration_seconds") or 0.0),
            "stdout_tail":      str(result.get("stdout_tail") or ""),
            "stderr_tail":      str(result.get("stderr_tail") or ""),
            "error":            result.get("error"),
        }
        checks.append(entry)

    failed_checks = [c["check_id"] for c in checks if not c["ok"]]
    ok = (len(failed_checks) == 0) and not errors

    return {
        "ok":            ok,
        "checks":        checks,
        "failed_checks": failed_checks,
        "warnings":      warnings,
        "errors":        errors,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def _render_text(envelope: dict[str, Any]) -> str:
    lines: list[str] = ["Section C demo runbook", ""]
    lines.append(f"OK:             {envelope['ok']}")
    lines.append(f"Checks:         {len(envelope['checks'])}")
    lines.append(f"Failed checks:  {len(envelope['failed_checks'])}")
    lines.append("")
    for c in envelope["checks"]:
        status = "PASS" if c.get("ok") else "FAIL"
        rc = c.get("returncode")
        rc_part = f"rc={rc}" if rc is not None else "rc=-"
        duration = c.get("duration_seconds", 0.0)
        lines.append(
            f"  [{status}] {c['check_id']:<42} {rc_part}  "
            f"({duration:.2f}s)"
        )
        err = c.get("error")
        if err:
            lines.append(f"      error: {err}")
        if not c.get("ok"):
            tail = (c.get("stderr_tail") or c.get("stdout_tail") or "").strip()
            if tail:
                short = tail.splitlines()[-3:]
                for ln in short:
                    lines.append(f"      | {ln}")
    if envelope.get("failed_checks"):
        lines.append("")
        lines.append("Failed checks:")
        for cid in envelope["failed_checks"]:
            lines.append(f"  - {cid}")
    if envelope.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in envelope["warnings"]:
            lines.append(f"  - {w}")
    if envelope.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in envelope["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local Section C demo runbook.  Runs six acceptance "
            "checks (two Python smokes, frontend typecheck, build, "
            "and two vitest filters) and reports which exited zero.  "
            "Does not write to the DB, does not mutate artifacts, "
            "does not start a server, does not import any paid "
            "provider or LLM seam."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--repo-root", dest="repo_root", default=None,
        help=(
            "Path to the repository root.  Defaults to the parent "
            "of this script."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    envelope = run_section_c_demo_checks(repo_root=args.repo_root)
    if args.json:
        print(_render_json(envelope), file=output)
    else:
        print(_render_text(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_demo_checks",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

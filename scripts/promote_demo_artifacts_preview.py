#!/usr/bin/env python3
"""Demo-artifact promotion preview helper.

Surveys the local ``artifacts/`` directory and previews which files
should be promoted to a stable demo-artifacts/ path so the demo
backend can be wired against the same inputs across runs.  By
default the helper is **preview-only**: it lists what *would* be
copied and where, but performs no filesystem writes.

Whitelisted demo inputs
-----------------------

The helper considers exactly three classes of files and never
promotes anything else:

* ``artifacts/analyzed_event_artifact_daily-demo-*.json`` — every
  match of the Daily section-C demo artifact glob.
* ``artifacts/freeze_candidate_evidence.json`` — the freeze-
  candidate evidence artifact validated by
  ``validate_freeze_candidate_artifact.py``.
* ``artifacts/daily_reviewed_candidates.csv`` — the operator's
  reviewed-candidate worksheet for the Daily cohort.

Anything else under ``artifacts/`` is deliberately ignored.  The
helper does **not** copy the directory wholesale; promotion is an
explicit, named-file operation.

Modes
-----

* **Preview (default)** — no ``--output-dir`` supplied.  The
  helper lists ``source_files`` and ``proposed_output_files`` but
  performs no writes.
* **Write** — ``--output-dir <path>`` supplied.  The helper
  creates the directory if it does not already exist, then copies
  each whitelisted source file into it.  An existing destination
  file is **refused** unless ``--overwrite`` is also supplied; the
  refusal is fail-closed and surfaced as an error.

Out of scope (deliberately)
---------------------------

* No DB reads, no provider (``yfinance``), no LLM, no FastAPI
  surface — the helper never imports ``api`` / ``routes.*``.
* No git side-effects.  Promotion is a file copy; staging or
  committing the destination is the operator's separate decision.

Conservative wording
--------------------

The artifacts surfaced here are **demo inputs**, not research
truth.  The preview always carries a disclaimer to that effect in
its ``warnings`` list so a downstream consumer cannot mistake a
promotion for a research claim.  The helper's own emitted text
avoids the overclaim vocabulary (``proven``, ``guaranteed``,
``alpha generated``).

Output contract (JSON)::

    {
      "ok":                      bool,    # True iff errors is empty
      "source_files":            list[ {"path": str, "kind": str} ],
      "proposed_output_files":   list[ {"source": str, "destination": str} ],
      "missing_required_files":  list[str],
      "warnings":                list[str],
      "errors":                  list[str],
    }

Usage::

    python scripts/promote_demo_artifacts_preview.py --json
    python scripts/promote_demo_artifacts_preview.py \\
        --output-dir demo_artifacts/
    python scripts/promote_demo_artifacts_preview.py \\
        --output-dir demo_artifacts/ --overwrite
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Whitelist — the three classes of demo inputs the helper recognises.
_DAILY_ARTIFACT_GLOB:   str = "analyzed_event_artifact_daily-demo-*.json"
_FREEZE_CANDIDATE_NAME: str = "freeze_candidate_evidence.json"
_REVIEWED_CSV_NAME:     str = "daily_reviewed_candidates.csv"


# Conservative disclaimer surfaced on every preview run.
_DEMO_INPUT_DISCLAIMER: str = (
    "These files are demo inputs only — they are wired into the demo "
    "backend for reproducible walkthroughs and are not research truth."
)


# Default destination shown when --output-dir is not supplied.  The
# preview uses this so an operator can see the conceptual layout
# without having to invoke the write path.
_DEFAULT_PREVIEW_DIR: str = "demo_artifacts"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_promote_demo_artifacts_preview(
    *,
    artifacts_dir: str | None = None,
    output_dir:    str | None = None,
    overwrite:     bool = False,
) -> dict[str, Any]:
    """Preview (and optionally execute) the demo-artifact promotion.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    warnings.append(_DEMO_INPUT_DISCLAIMER)

    art_root = Path(artifacts_dir) if artifacts_dir else (ROOT / "artifacts")

    source_files, missing = _discover_source_files(art_root)

    dest_root = Path(output_dir) if output_dir else Path(_DEFAULT_PREVIEW_DIR)
    proposed = [
        {
            "source":      entry["path"],
            "destination": str(dest_root / Path(entry["path"]).name),
        }
        for entry in source_files
    ]

    if output_dir is not None:
        _execute_writes(
            source_files=source_files,
            output_dir=Path(output_dir),
            overwrite=overwrite,
            errors=errors, warnings=warnings,
        )

    return {
        "ok":                      not errors,
        "source_files":            source_files,
        "proposed_output_files":   proposed,
        "missing_required_files":  missing,
        "warnings":                warnings,
        "errors":                  errors,
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_source_files(
    art_root: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    """Walk the whitelist; return ``(source_files, missing)``.

    ``source_files`` is a list of ``{"path": str, "kind": str}``
    entries in a stable order: daily artifacts first (sorted by
    filename), then freeze-candidate, then reviewed-candidate CSV.
    ``missing`` is a list of human-readable strings naming the
    whitelisted inputs that were NOT found.
    """
    source_files: list[dict[str, str]] = []
    missing:      list[str]            = []

    if not art_root.exists():
        # Whole tree absent — every whitelisted input is missing.
        missing.append(
            f"{art_root / _DAILY_ARTIFACT_GLOB} (no matching files)"
        )
        missing.append(str(art_root / _FREEZE_CANDIDATE_NAME))
        missing.append(str(art_root / _REVIEWED_CSV_NAME))
        return source_files, missing

    daily_matches = sorted(
        p for p in art_root.glob(_DAILY_ARTIFACT_GLOB) if p.is_file()
    )
    if daily_matches:
        for p in daily_matches:
            source_files.append({"path": str(p), "kind": "daily_artifact"})
    else:
        missing.append(
            f"{art_root / _DAILY_ARTIFACT_GLOB} (no matching files)"
        )

    freeze = art_root / _FREEZE_CANDIDATE_NAME
    if freeze.is_file():
        source_files.append({
            "path": str(freeze),
            "kind": "freeze_candidate_evidence",
        })
    else:
        missing.append(str(freeze))

    csv = art_root / _REVIEWED_CSV_NAME
    if csv.is_file():
        source_files.append({
            "path": str(csv),
            "kind": "daily_reviewed_candidates",
        })
    else:
        missing.append(str(csv))

    return source_files, missing


# ---------------------------------------------------------------------------
# Write mode
# ---------------------------------------------------------------------------


def _execute_writes(
    *,
    source_files: list[dict[str, str]],
    output_dir:   Path,
    overwrite:    bool,
    errors:       list[str],
    warnings:     list[str],
) -> None:
    """Copy each source file into ``output_dir``.

    Refuses to overwrite an existing destination unless
    ``overwrite`` is True; the refusal is reported as an error and
    the copy is skipped so no partial state is left on disk for
    that file.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        errors.append(
            f"failed to create output directory {output_dir!s}: "
            f"{type(e).__name__}: {e}"
        )
        return

    for entry in source_files:
        src = Path(entry["path"])
        dst = output_dir / src.name
        if dst.exists() and not overwrite:
            errors.append(
                f"refusing to overwrite existing destination "
                f"{dst!s}; rerun with --overwrite to replace it"
            )
            continue
        try:
            shutil.copy2(src, dst)
            warnings.append(f"copied {src!s} -> {dst!s}")
        except OSError as e:
            errors.append(
                f"failed to copy {src!s} -> {dst!s}: "
                f"{type(e).__name__}: {e}"
            )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Demo-artifact promotion preview", ""]
    lines.append(f"OK:                          {report['ok']}")
    lines.append(f"Source files found:          {len(report['source_files'])}")
    lines.append(
        f"Proposed output files:       "
        f"{len(report['proposed_output_files'])}"
    )
    lines.append(
        f"Missing required files:      "
        f"{len(report['missing_required_files'])}"
    )

    if report["source_files"]:
        lines.append("")
        lines.append("Source files:")
        for entry in report["source_files"]:
            lines.append(f"  - [{entry['kind']}] {entry['path']}")

    if report["proposed_output_files"]:
        lines.append("")
        lines.append("Proposed output files:")
        for entry in report["proposed_output_files"]:
            lines.append(
                f"  - {entry['source']} -> {entry['destination']}"
            )

    if report["missing_required_files"]:
        lines.append("")
        lines.append("Missing required files:")
        for m in report["missing_required_files"]:
            lines.append(f"  - {m}")

    if report.get("warnings"):
        lines.append("")
        lines.append("Notes:")
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
            "Preview which local artifacts should be promoted to a "
            "stable demo-artifacts/ path for reproducible demos.  "
            "Read-only by default — supply --output-dir to copy the "
            "whitelisted files and --overwrite to replace existing "
            "destinations.  These files are demo inputs only and are "
            "not research truth."
        ),
    )
    parser.add_argument(
        "--artifacts-dir", dest="artifacts_dir", default=None,
        help=(
            "Source directory to scan (default: <repo>/artifacts).  "
            "Only whitelisted demo-input filenames are considered."
        ),
    )
    parser.add_argument(
        "--output-dir", dest="output_dir", default=None,
        help=(
            "Destination directory.  When supplied, the helper copies "
            "the whitelisted source files into this directory.  When "
            "omitted, the helper runs in preview-only mode and "
            "performs no filesystem writes."
        ),
    )
    parser.add_argument(
        "--overwrite", dest="overwrite", action="store_true",
        help=(
            "Allow overwriting an existing destination file.  Without "
            "this flag the helper refuses to replace pre-existing "
            "files at the destination."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = run_promote_demo_artifacts_preview(
        artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
        overwrite=bool(args.overwrite),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_promote_demo_artifacts_preview",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())

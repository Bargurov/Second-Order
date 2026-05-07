#!/usr/bin/env python3
"""Tracked-generated-artifact guard.

Reads the git index via ``git ls-files`` and reports any tracked path
matching a generated/local-artifact pattern (databases, build info,
frontend dist output, archive backups).  Read-only — never modifies
the repo, never globs the filesystem.  Exits non-zero when violations
exist so the script can be wired into pre-commit / CI.

Out of scope (deliberately)
---------------------------
* No DB writes.  No filesystem-recursive scan.
* No provider, ``yfinance``, LLM, ``market_check``, or FastAPI seam.
* No write/quarantine mode — the script reports; the operator unstages.

Usage::

    python scripts/repo_hygiene_check.py
    python scripts/repo_hygiene_check.py --json
    python scripts/repo_hygiene_check.py --repo-path /path/to/checkout --json
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


CHECKED_PATTERNS: tuple[str, ...] = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.tsbuildinfo",
    "frontend/dist/*",
    "backups/*",
)


def list_tracked_generated(
    *,
    repo_path: str | Path | None = None,
    patterns: Sequence[str] = CHECKED_PATTERNS,
) -> list[str]:
    """Return tracked paths matching any generated-artifact pattern.

    Read-only.  Shells out to ``git ls-files -z`` once and matches each
    line against ``patterns`` with ``fnmatch.fnmatchcase`` — never
    globs the filesystem and never invokes a provider/yfinance/LLM/
    FastAPI seam.  Returns ``[]`` when ``repo_path`` is not a git
    checkout (``git ls-files`` exits non-zero) or when the index is
    empty.  Output is sorted ascending for determinism.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repo_path) if repo_path is not None else None,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    raw = proc.stdout.decode("utf-8", errors="replace")
    tracked = [p for p in raw.split("\0") if p]
    matched: list[str] = []
    for path in tracked:
        for pattern in patterns:
            if fnmatch.fnmatchcase(path, pattern):
                matched.append(path)
                break
    matched.sort()
    return matched


# ---------------------------------------------------------------------------
# Payload + rendering
# ---------------------------------------------------------------------------


def _build_payload(matched: list[str]) -> dict[str, Any]:
    return {
        "ok":                       len(matched) == 0,
        "tracked_generated_count":  len(matched),
        "tracked_generated_paths":  list(matched),
        "checked_patterns":         list(CHECKED_PATTERNS),
    }


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = ["Tracked-generated-artifact guard", ""]
    lines.append(
        "Checked patterns:        " + ", ".join(payload["checked_patterns"])
    )
    lines.append(
        f"Tracked generated count: {payload['tracked_generated_count']}"
    )
    lines.append(
        f"Status:                  {'OK' if payload['ok'] else 'VIOLATIONS'}"
    )
    if payload["tracked_generated_paths"]:
        lines.append("")
        lines.append("Tracked generated paths:")
        for p in payload["tracked_generated_paths"]:
            lines.append(f"  {p}")
    return "\n".join(lines)


def _render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when generated/local artifacts (databases, build "
            "info, frontend/dist, backups) are tracked by git."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--repo-path",
        dest="repo_path",
        default=None,
        help=(
            "Optional path to a git checkout.  Defaults to the current "
            "working directory."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    matched = list_tracked_generated(repo_path=args.repo_path)
    payload = _build_payload(matched)

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

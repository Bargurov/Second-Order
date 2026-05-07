#!/usr/bin/env python3
"""Read-only consistency check for the
``auto_adjust_mismatch_for_20d`` count.

Two independent SQL traversals classify rows into the
``auto_adjust_mismatch_for_20d`` bucket:

  * ``no_forward_20d_gap_report.auto_adjust_mismatch`` — derived from
    :func:`routes.diagnostics._compute_no_forward_20d_breakdown`.
  * ``auto_adjust_mismatch_repair_preview.total_mismatches`` — derived
    from :func:`scripts.no_forward_20d_gap_report._load_auto_adjust_mismatch_details`.

These two paths walk the events archive independently with the same
classifiers; their counts must agree.  This script invokes both
upstream CLIs in-process, parses their JSON output, and emits a small
audit envelope so a runbook (or CI hook) can branch deterministically
on the result.  Future "simplification" that collapses both upstream
counts into the same loader would defeat the audit — the value of this
check is precisely that it covers two independent paths.

Output keys
-----------
``ok``                — bool.  True iff both counts extracted, both
                        counts matched, and no errors accumulated.
``mismatch_count``    — int | None.  ``auto_adjust_mismatch`` from the
                        gap report; ``None`` when the upstream output
                        could not be parsed or the field was missing /
                        malformed.
``preview_count``     — int | None.  ``total_mismatches`` from the
                        repair preview; ``None`` on extraction failure.
``repairable_count``  — int | None.  ``repairable_count`` from the
                        repair preview; ``None`` on extraction failure.
``errors``            — list[str].  Human-readable error strings.
                        Empty on a clean run.

Exit code
---------
``0`` when ``ok`` is True; ``1`` otherwise so a CI hook can branch on
the exit code without parsing JSON.

Out of scope (deliberately)
---------------------------
* No write mode.  This script never refreshes the price cache,
  re-flags rows, or persists anything.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``, no
  ``market_data``, no ``price_cache.fetch_daily_cached``, no network.
* No FastAPI route surface — the upstream CLIs are invoked in-process
  via ``main(['--json'], out=...)``; FastAPI's TestClient is never
  constructed.

Usage::

    python scripts/auto_adjust_mismatch_consistency_check.py
    python scripts/auto_adjust_mismatch_consistency_check.py --json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Upstream runner seams — kept module-level so tests can patch them
# directly with synthetic dicts.
# ---------------------------------------------------------------------------


def _run_gap_report() -> dict:
    """Invoke ``no_forward_20d_gap_report.main(['--json'])`` in-process
    against an in-memory buffer and return the parsed JSON dict.

    The lazy import resolves only on the un-patched path so unit tests
    can swap this seam without paying the diagnostics import cost.
    """
    from scripts import no_forward_20d_gap_report as _mod

    buf = io.StringIO()
    rc = _mod.main(["--json"], out=buf)
    if rc != 0:
        raise RuntimeError(f"gap report exited with code {rc}")
    return json.loads(buf.getvalue())


def _run_repair_preview() -> dict:
    """Invoke ``auto_adjust_mismatch_repair_preview.main(['--json'])``
    in-process against an in-memory buffer and return the parsed JSON
    dict.
    """
    from scripts import auto_adjust_mismatch_repair_preview as _mod

    buf = io.StringIO()
    rc = _mod.main(["--json"], out=buf)
    if rc != 0:
        raise RuntimeError(f"repair preview exited with code {rc}")
    return json.loads(buf.getvalue())


# ---------------------------------------------------------------------------
# Pure compare logic
# ---------------------------------------------------------------------------


def _extract_non_negative_int(
    body: dict | None,
    key: str,
    label: str,
    errors: list[str],
) -> int | None:
    """Return the field value if it's a non-negative int, else None.

    A bool is rejected even though ``isinstance(True, int)`` is True —
    booleans must never silently flow through count math.  Every
    rejection path appends a human-readable string to ``errors`` so the
    operator can diagnose the upstream regression.
    """
    if body is None:
        errors.append(
            f"{label} body unavailable; {key!r} could not be extracted"
        )
        return None
    value = body.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(
            f"{label} field {key!r} is not a non-negative int: {value!r}"
        )
        return None
    return value


def _compare(
    gap_body: dict | None,
    preview_body: dict | None,
    errors_pre: Sequence[str] | None = None,
) -> dict:
    """Reconcile the two upstream count payloads into the audit envelope.

    Returns ``{ok, mismatch_count, preview_count, repairable_count,
    errors}``.  Counts are nullable: ``None`` signals "extraction
    failed", an int signals "actually-extracted value".  ``ok`` is True
    iff every extraction succeeded, the gap-report count equals the
    preview total, and ``errors_pre`` carries no entries.
    """
    errors: list[str] = list(errors_pre or [])

    mismatch_count = _extract_non_negative_int(
        gap_body, "auto_adjust_mismatch", "gap report", errors,
    )
    preview_count = _extract_non_negative_int(
        preview_body, "total_mismatches", "repair preview", errors,
    )
    repairable_count = _extract_non_negative_int(
        preview_body, "repairable_count", "repair preview", errors,
    )

    if (
        mismatch_count is not None
        and preview_count is not None
        and mismatch_count != preview_count
    ):
        errors.append(
            f"count divergence: gap report auto_adjust_mismatch="
            f"{mismatch_count} != repair preview total_mismatches="
            f"{preview_count}"
        )

    if (
        repairable_count is not None
        and preview_count is not None
        and repairable_count > preview_count
    ):
        # Production preview never emits this — repairable_count is a
        # partition of total_mismatches.  Pinned defensively so a future
        # bug that breaks the partition tripwires here.
        errors.append(
            f"impossible: repairable_count={repairable_count} > "
            f"total_mismatches={preview_count}"
        )

    return {
        "ok":               not errors,
        "mismatch_count":   mismatch_count,
        "preview_count":    preview_count,
        "repairable_count": repairable_count,
        "errors":           errors,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(payload: dict) -> str:
    status = "OK" if payload.get("ok") else "FAIL"
    lines = ["Auto-adjust mismatch consistency check", ""]
    lines.append(f"Status: {status}")
    lines.append(f"  mismatch_count:   {payload.get('mismatch_count')!s}")
    lines.append(f"  preview_count:    {payload.get('preview_count')!s}")
    lines.append(f"  repairable_count: {payload.get('repairable_count')!s}")
    lines.append("")
    errors = payload.get("errors") or []
    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"  - {err}")
    else:
        lines.append("Errors: -")
    return "\n".join(lines)


def _render_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only consistency check that reconciles the "
            "auto_adjust_mismatch_for_20d count between the gap report "
            "and the repair preview.  No writes, no provider calls, no "
            "LLM."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    errors_pre: list[str] = []
    gap_body: dict | None = None
    preview_body: dict | None = None

    try:
        gap_body = _run_gap_report()
    except Exception as exc:
        errors_pre.append(
            f"gap report failed: {type(exc).__name__}: {exc}"
        )

    try:
        preview_body = _run_repair_preview()
    except Exception as exc:
        errors_pre.append(
            f"repair preview failed: {type(exc).__name__}: {exc}"
        )

    payload = _compare(gap_body, preview_body, errors_pre=errors_pre)

    if args.json:
        print(_render_json(payload), file=output)
    else:
        print(_render_text(payload), file=output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

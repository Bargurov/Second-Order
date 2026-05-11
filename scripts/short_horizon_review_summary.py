#!/usr/bin/env python3
"""Compact operator-facing summary of a short-horizon review worksheet.

Reads a manually-reviewed short-horizon worksheet CSV (the canonical
artifact emitted by :mod:`scripts.short_horizon_review_worksheet`)
and produces a JSON checklist an operator can scan at a glance:

  * yes / no / pending counts of the
    ``include_in_short_horizon_validation`` gate column,
  * the top pending rows the operator should look at next,
  * a recommended manual-review order sorted by repair_priority
    (high → medium → low) then event_id ascending.

Read-only by construction
-------------------------

* Pure builder + CLI — no patchable seam, no provider call, no LLM,
  no FastAPI surface, no DB open.  The worksheet CSV is read from
  disk and immediately closed; bytes are never rewritten.
* Output is JSON only.  The ``--json`` flag is accepted for
  ergonomic parity with sibling scripts but the script has no
  text-mode rendering.

Gate vocabulary
---------------

The ``include_in_short_horizon_validation`` cell is normalised by
stripping whitespace and lower-casing before dispatch:

  * ``yes``           → ``yes_count``,
  * ``no``            → ``no_count``,
  * blank / whitespace-only → ``pending_count``, no warning,
  * any other value   → ``pending_count`` + one warning per row.

Both top_pending_rows and recommended_manual_review_order surface
pending rows (blank + unrecognized) — never yes / no rows.

Output contract::

    {
      "ok":               bool,
      "worksheet_path":   str | None,
      "total_rows":       int,
      "yes_count":        int,
      "no_count":         int,
      "pending_count":    int,
      "top_pending_rows": [          # capped at --limit
        {
          "event_id":                  int,
          "headline":                  str | None,
          "event_date":                str | None,
          "current_primary_ticker":    str | None,
          "repair_priority":           str,
          "operator_decision_needed":  str | None,
        },
        ...
      ],
      "recommended_manual_review_order": [  # capped at --limit
        {
          "event_id":          int,
          "repair_priority":   str,
          "reason":            str,   # operator_decision_needed,
                                      # fallback "manual_review_required"
        },
        ...
      ],
      "warnings":         [str, ...],
      "errors":           [str, ...],
    }

Both pending lists are sorted by ``(priority_rank, event_id)``
ascending (high → medium → low → unknown), then by event_id, and
truncated at ``--limit`` (default 10) — the same cap applies to both.

Conservative wording — banned tokens in any surfaced text
(``proof``, ``proves``, ``validated``, ``alpha``, ``guaranteed``)
never appear in this script's errors / warnings.

Usage::

    python scripts/short_horizon_review_summary.py \\
        --worksheet artifacts/short_horizon_review_top10.csv --json
    python scripts/short_horizon_review_summary.py \\
        --worksheet artifacts/short_horizon_review_top10.csv \\
        --limit 25 --json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 10

# Canonical gate column — same name used by the worksheet emitter,
# the validator, the apply smoke and the validate smoke.  Keeping the
# column name pinned here means future renames break loudly via
# missing-column structural errors.
_GATE_COLUMN: str = "include_in_short_horizon_validation"

_GATE_YES: str = "yes"
_GATE_NO:  str = "no"

# Required CSV columns.  ``event_id`` is mandatory so every surfaced
# row has a stable identifier; the gate column is mandatory because
# the entire purpose of the summary is to bucket against it.  Other
# columns (headline, repair_priority, operator_decision_needed) are
# read when present and treated as blank when absent.
_REQUIRED_COLUMNS: tuple[str, ...] = ("event_id", _GATE_COLUMN)


# Priority rank for the sort order.  Higher-priority rows come first
# in both top_pending_rows and recommended_manual_review_order.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
_UNKNOWN_PRIORITY_RANK: int = 99


_REASON_FALLBACK: str = "manual_review_required"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_review_summary(
    *, worksheet_path: str | None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the JSON checklist for a reviewed short-horizon worksheet.

    See the module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)
    errors:   list[str] = []
    warnings: list[str] = []

    if worksheet_path is None or not str(worksheet_path).strip():
        errors.append("--worksheet path is required")
        return _empty_envelope(worksheet_path, errors, warnings)

    path = Path(worksheet_path)
    if not path.exists():
        errors.append(f"worksheet does not exist: {worksheet_path}")
        return _empty_envelope(worksheet_path, errors, warnings)

    try:
        with open(path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
            if missing:
                errors.append(
                    f"worksheet missing required columns: "
                    f"{', '.join(missing)}"
                )
                return _empty_envelope(worksheet_path, errors, warnings)
            rows = [dict(r) for r in reader]
    except OSError as exc:
        errors.append(
            f"failed to read worksheet {worksheet_path}: {exc}"
        )
        return _empty_envelope(worksheet_path, errors, warnings)

    yes_count    = 0
    no_count     = 0
    pending_count = 0
    pending_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        gate_raw = row.get(_GATE_COLUMN, "")
        gate     = _normalise_gate(gate_raw)
        ev_id    = _coerce_event_id(row.get("event_id"))

        if gate == _GATE_YES:
            yes_count += 1
            continue
        if gate == _GATE_NO:
            no_count += 1
            continue

        # Pending bucket — either blank or unrecognised.
        pending_count += 1
        if gate != "" and ev_id is not None:
            # Unrecognised non-blank value → conservative warning,
            # one per row.  Use the raw cell text so the operator
            # can spot the typo.
            warnings.append(
                f"row {idx} event_id={ev_id}: unrecognised "
                f"include_in_short_horizon_validation value "
                f"{_coerce_str(gate_raw)!r}; counted as pending"
            )
        elif gate != "":
            warnings.append(
                f"row {idx}: unrecognised "
                f"include_in_short_horizon_validation value "
                f"{_coerce_str(gate_raw)!r}; counted as pending"
            )

        if ev_id is None:
            # Without an integer event_id we cannot surface this row
            # in the operator-facing lists; the row still counts
            # toward pending_count so totals stay consistent.
            continue
        pending_rows.append(_build_pending_row(ev_id, row))

    pending_rows.sort(
        key=lambda r: (
            _PRIORITY_RANK.get(r["repair_priority"], _UNKNOWN_PRIORITY_RANK),
            r["event_id"],
        )
    )

    top_pending_rows = pending_rows[:capped_limit]
    recommended_order = [
        _build_recommended_entry(r) for r in pending_rows[:capped_limit]
    ]

    return {
        "ok":              not errors,
        "worksheet_path":  str(worksheet_path),
        "total_rows":      len(rows),
        "yes_count":       yes_count,
        "no_count":        no_count,
        "pending_count":   pending_count,
        "top_pending_rows": top_pending_rows,
        "recommended_manual_review_order": recommended_order,
        "warnings":        warnings,
        "errors":          errors,
    }


# ---------------------------------------------------------------------------
# Per-row construction
# ---------------------------------------------------------------------------


def _build_pending_row(event_id: int, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id":                 event_id,
        "headline":                 _coerce_str(row.get("headline")),
        "event_date":               _coerce_str(row.get("event_date")),
        "current_primary_ticker":   _coerce_str(
            row.get("current_primary_ticker")
        ),
        "repair_priority":          _coerce_priority(
            row.get("repair_priority")
        ),
        "operator_decision_needed": _coerce_str(
            row.get("operator_decision_needed")
        ),
    }


def _build_recommended_entry(
    pending_row: dict[str, Any],
) -> dict[str, Any]:
    """Build a recommended_manual_review_order entry from a pending
    row.  Exactly three fields per spec; ``reason`` falls back to
    the literal ``manual_review_required`` when operator_decision_needed
    is blank.
    """
    reason = pending_row.get("operator_decision_needed")
    if not isinstance(reason, str) or not reason.strip():
        reason = _REASON_FALLBACK
    return {
        "event_id":        pending_row["event_id"],
        "repair_priority": pending_row["repair_priority"],
        "reason":          reason,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_gate(raw: Any) -> str:
    """Return ``yes`` / ``no`` / ``""`` / raw-lowercased.

    Anything that isn't recognised yes/no comes back as the
    lower-cased / whitespace-stripped form so the caller can decide
    between "blank pending" (``""``) and "unrecognised pending" (non-
    empty string).
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        s = raw.strip().lower()
    else:
        s = str(raw).strip().lower()
    if s in (_GATE_YES, _GATE_NO):
        return s
    return s  # caller distinguishes empty vs non-empty for warnings.


def _coerce_event_id(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _coerce_str(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    return str(raw)


def _coerce_priority(raw: Any) -> str:
    """Return the priority string verbatim when it's a known value;
    otherwise the literal ``"unknown"`` so callers always carry a
    plain string (never ``None``) on the worksheet checklist.
    """
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in _PRIORITY_RANK:
            return s
    return "unknown"


def _empty_envelope(
    worksheet_path: str | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok":              False,
        "worksheet_path":  (
            str(worksheet_path) if worksheet_path is not None else None
        ),
        "total_rows":      0,
        "yes_count":       0,
        "no_count":        0,
        "pending_count":   0,
        "top_pending_rows": [],
        "recommended_manual_review_order": [],
        "warnings":        warnings,
        "errors":          errors,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compact operator-facing summary of a reviewed short-"
            "horizon worksheet CSV.  Counts the yes/no/pending split "
            "of the include_in_short_horizon_validation gate column "
            "and surfaces a sorted manual-review order capped at "
            "--limit.  Read-only — no DB, no provider, no LLM, no "
            "FastAPI.  JSON output only."
        ),
    )
    parser.add_argument(
        "--worksheet", dest="worksheet", default=None,
        help=(
            "Path to a reviewed short-horizon worksheet CSV.  Read-"
            "only; bytes are never rewritten."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap both top_pending_rows and "
            f"recommended_manual_review_order at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every worksheet row."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_review_summary(
        worksheet_path=args.worksheet, limit=int(args.limit),
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

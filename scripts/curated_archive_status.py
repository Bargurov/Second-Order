#!/usr/bin/env python3
"""Read-only status report for the curated-event YAML archive.

Aggregates the curated archive into a stable 9-key status payload
suitable for demo / review.  Consumes the loader through a single
patchable seam (``_load_curated_events``) and drives the validator
in-process for the per-event valid/invalid breakdown.

Output contract::

    {
      "total_events":          int,
      "valid_count":           int,
      "invalid_count":         int,
      "by_mechanism_family":   {family: count, ...},
      "date_range": {
        "min_event_date":      str | None,    # ISO YYYY-MM-DD
        "max_event_date":      str | None,
      },
      "ticker_coverage": {
        "primary_tickers":     [str, ...],    # sorted, deduplicated
        "benchmark_tickers":   [str, ...],
        "primary_ticker_count": int,
      },
      "missing_fields": {field: count, ...},  # required-field gaps
      "errors":                [str, ...],
      "warnings":              [str, ...],
    }

* ``by_mechanism_family`` counts every event (valid OR invalid) that
  has a non-blank ``mechanism_family``.
* ``date_range`` only consults events whose ``event_date`` parses as
  ISO YYYY-MM-DD; invalid dates are excluded.
* ``ticker_coverage`` lists every non-blank ticker appearing in any
  event (deduplicated, sorted).  Blank tickers are skipped.
* ``missing_fields`` aggregates required-field gaps across the whole
  archive — keys appear only when the count is > 0.

Out of scope (deliberately)
---------------------------

* No DB writes, no provider, no LLM, no FastAPI surface.
* No mutation of the input YAML.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_date",
    "headline",
    "source_url",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "mechanism_description",
    "predicted_direction",
    "prediction_rationale",
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _load_curated_events(
    yaml_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from scripts.curated_event_loader import load_curated_events

    return load_curated_events(yaml_path)


def _validate_curated_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts.curated_event_validator import validate_curated_events

    return validate_curated_events(events)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_curated_archive(
    *, yaml_path: str | None = None,
) -> dict[str, Any]:
    """Build the 9-key status report.  See module docstring for the
    full contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    events, load_errors = _load_curated_events(yaml_path)
    errors.extend(load_errors)

    validation = _validate_curated_events(events)
    valid_count   = _coerce_int(validation.get("valid_count"))
    invalid_count = _coerce_int(validation.get("invalid_count"))
    # Keep the validator's own errors visible to the operator.
    for e in validation.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(e)

    by_mechanism_family = _group_by_mechanism_family(events)
    date_range          = _compute_date_range(events)
    ticker_coverage     = _ticker_coverage(events)
    missing_fields      = _aggregate_missing_fields(events)

    return {
        "total_events":         len(events),
        "valid_count":          valid_count,
        "invalid_count":        invalid_count,
        "by_mechanism_family":  by_mechanism_family,
        "date_range":           date_range,
        "ticker_coverage":      ticker_coverage,
        "missing_fields":       missing_fields,
        "errors":               errors,
        "warnings":             warnings,
    }


def _group_by_mechanism_family(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        family = e.get("mechanism_family")
        if not isinstance(family, str) or not family.strip():
            continue
        family = family.strip()
        out[family] = out.get(family, 0) + 1
    return out


def _compute_date_range(
    events: list[dict[str, Any]],
) -> dict[str, str | None]:
    parsed_dates: list[_dt.date] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        d = _parse_iso_date(e.get("event_date"))
        if d is not None:
            parsed_dates.append(d)
    if not parsed_dates:
        return {"min_event_date": None, "max_event_date": None}
    return {
        "min_event_date": min(parsed_dates).isoformat(),
        "max_event_date": max(parsed_dates).isoformat(),
    }


def _ticker_coverage(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    primary: set[str] = set()
    benchmark: set[str] = set()
    for e in events:
        if not isinstance(e, dict):
            continue
        p = e.get("primary_ticker")
        if isinstance(p, str) and p.strip():
            primary.add(p.strip().upper())
        b = e.get("benchmark_ticker")
        if isinstance(b, str) and b.strip():
            benchmark.add(b.strip().upper())
    return {
        "primary_tickers":      sorted(primary),
        "benchmark_tickers":    sorted(benchmark),
        "primary_ticker_count": len(primary),
    }


def _aggregate_missing_fields(
    events: list[dict[str, Any]],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        for field in _REQUIRED_FIELDS:
            value = e.get(field)
            if _is_missing(value):
                out[field] = out.get(field, 0) + 1
    return out


def _is_missing(value: Any) -> bool:
    """A required field is "missing" when it is absent (``None``) or
    a blank / whitespace-only string.  Numeric zero, ``False``, and
    other non-empty values are considered present."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _parse_iso_date(value: Any) -> _dt.date | None:
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return _dt.date.fromisoformat(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated archive status", ""]
    lines.append(f"Total events:    {report['total_events']}")
    lines.append(f"Valid:           {report['valid_count']}")
    lines.append(f"Invalid:         {report['invalid_count']}")
    dr = report["date_range"]
    lines.append(
        f"Date range:      {dr['min_event_date']} → {dr['max_event_date']}"
    )
    tc = report["ticker_coverage"]
    lines.append(f"Primary tickers ({tc['primary_ticker_count']}): "
                 f"{', '.join(tc['primary_tickers']) or '-'}")
    lines.append(f"Benchmark tickers: "
                 f"{', '.join(tc['benchmark_tickers']) or '-'}")
    lines.append("")
    lines.append("By mechanism_family:")
    if report["by_mechanism_family"]:
        for family in sorted(report["by_mechanism_family"].keys()):
            lines.append(
                f"  {family:<40} count={report['by_mechanism_family'][family]}"
            )
    else:
        lines.append("  -")
    if report["missing_fields"]:
        lines.append("")
        lines.append("Missing-field gaps:")
        for field in sorted(report["missing_fields"].keys()):
            lines.append(
                f"  {field:<25} {report['missing_fields'][field]}"
            )
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
            "Read-only status report for the curated-event YAML "
            "archive.  Aggregates the loaded events into a stable "
            "9-key payload (counts by mechanism_family, date range, "
            "ticker coverage, missing-field gaps).  Conservative "
            "language only."
        ),
    )
    parser.add_argument(
        "--yaml", dest="yaml_path", required=True,
        help="Path to the curated-event YAML file.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of compact text.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = summarize_curated_archive(yaml_path=args.yaml_path)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

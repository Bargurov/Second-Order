#!/usr/bin/env python3
"""Read-only validator for the curated-event YAML archive.

Consumes the parsed events from :mod:`scripts.curated_event_loader`
through a single patchable seam (``_load_curated_events``) and runs
field-level validation against the curated-event contract.

Required fields per event (every one must be present and non-blank):

  * ``event_id``
  * ``event_date`` (ISO YYYY-MM-DD string OR ``datetime.date``)
  * ``headline``
  * ``source_url``
  * ``primary_ticker``
  * ``benchmark_ticker``
  * ``mechanism_family``
  * ``mechanism_description``
  * ``predicted_direction`` (must be one of ``{"up", "down", "flat"}``)
  * ``prediction_rationale``

Optional:

  * ``curator_notes`` — operator free-form string.

Output contract (JSON / dict)::

    {
      "ok":               bool,
      "valid_count":      int,
      "invalid_count":    int,
      "validated_events": [dict, ...],
      "errors_by_event_id": {"<id>": [str, ...], ...},
      "errors":           [str, ...],
    }

Conservative wording: per-field error strings describe ONLY the
missing or invalid field — they never claim "proof", "alpha", or
"automatic".

Out of scope (deliberately)
---------------------------

* No DB writes, no provider, no LLM, no FastAPI surface.
* No mutation of inputs — every event in ``validated_events`` is
  the unmodified dict the loader produced.
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


_BLANK_GUARDED_STRING_FIELDS: tuple[str, ...] = (
    "headline",
    "source_url",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "mechanism_description",
    "prediction_rationale",
)


_VALID_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "flat"})


# ---------------------------------------------------------------------------
# Patchable seam — tests patch this directly.
# ---------------------------------------------------------------------------


def _load_curated_events(
    yaml_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Wrap :func:`scripts.curated_event_loader.load_curated_events`.

    Lazy import keeps the loader off the un-patched path's import
    cost when callers patch this seam.
    """
    from scripts.curated_event_loader import load_curated_events

    return load_curated_events(yaml_path)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def validate_curated_events(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a list of curated event dicts.  See module docstring
    for the output contract.
    """
    errors: list[str] = []
    errors_by_event_id: dict[str, list[str]] = {}
    validated_events: list[dict[str, Any]] = []

    if not events:
        errors.append(
            "curated archive is empty — no events to validate"
        )

    for i, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(
                f"curated entry at index {i} is not a mapping; skipping"
            )
            continue
        per_event_errors = _validate_one(event)
        ev_id_raw = event.get("event_id")
        ev_id_key = _coerce_event_id_key(ev_id_raw)
        if ev_id_key is None:
            # Missing event_id is a structural problem — the caller
            # has nothing to key the error list off, so it lands in
            # the top-level errors bucket.
            for err in per_event_errors:
                errors.append(
                    f"curated entry at index {i}: {err}"
                )
            continue
        if per_event_errors:
            errors_by_event_id.setdefault(ev_id_key, []).extend(
                per_event_errors,
            )
        else:
            validated_events.append(dict(event))

    invalid_event_ids = set(errors_by_event_id.keys())
    structural_failures = sum(
        1 for e in events
        if not isinstance(e, dict) or e.get("event_id") in (None, "")
    )
    valid_count = len(validated_events)
    invalid_count = len(invalid_event_ids) + structural_failures

    ok = (not errors) and (invalid_count == 0) and (valid_count > 0)

    return {
        "ok":                  ok,
        "valid_count":         valid_count,
        "invalid_count":       invalid_count,
        "validated_events":    validated_events,
        "errors_by_event_id":  errors_by_event_id,
        "errors":              errors,
    }


def _validate_one(event: dict[str, Any]) -> list[str]:
    """Run field-level validation on a single event dict; return the
    list of conservative error strings (empty if the event is valid).
    """
    errs: list[str] = []

    # 1. Required-field presence.
    for field in _REQUIRED_FIELDS:
        if field not in event:
            errs.append(f"missing required field: {field}")
            continue

    # 2. Blank-guarded string fields.
    for field in _BLANK_GUARDED_STRING_FIELDS:
        if field not in event:
            continue  # already reported above
        value = event.get(field)
        if not isinstance(value, str) or not value.strip():
            errs.append(f"field {field!r} must be a non-blank string")

    # 3. event_id non-empty.
    if "event_id" in event:
        ev_id = event.get("event_id")
        if isinstance(ev_id, bool):
            errs.append("field 'event_id' must be an integer or non-blank string")
        elif ev_id is None:
            errs.append("field 'event_id' must be present and non-blank")
        elif isinstance(ev_id, str) and not ev_id.strip():
            errs.append("field 'event_id' must be a non-blank string")

    # 4. event_date — ISO date string OR datetime.date.
    if "event_date" in event:
        date_val = event.get("event_date")
        if not _is_iso_date(date_val):
            errs.append(
                "field 'event_date' must be an ISO date "
                "(YYYY-MM-DD) string or a datetime.date"
            )

    # 5. predicted_direction vocabulary.
    if "predicted_direction" in event:
        direction = event.get("predicted_direction")
        if not isinstance(direction, str) or direction not in _VALID_DIRECTIONS:
            errs.append(
                f"field 'predicted_direction' must be one of "
                f"{sorted(_VALID_DIRECTIONS)} — got {direction!r}"
            )

    return errs


def _is_iso_date(value: Any) -> bool:
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return True
    if isinstance(value, _dt.datetime):
        # datetime is not preferred but is acceptable; project elsewhere
        # treats it as a date.  Keep strict: only ``date`` is valid.
        return False
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        _dt.date.fromisoformat(value.strip())
        return True
    except (TypeError, ValueError):
        return False


def _coerce_event_id_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated event validator", ""]
    lines.append(f"OK:             {report['ok']}")
    lines.append(f"Valid count:    {report['valid_count']}")
    lines.append(f"Invalid count:  {report['invalid_count']}")
    if report.get("errors_by_event_id"):
        lines.append("")
        lines.append("Per-event errors:")
        for ev_id_str in sorted(report["errors_by_event_id"].keys()):
            lines.append(f"  event_id={ev_id_str}:")
            for err in report["errors_by_event_id"][ev_id_str]:
                lines.append(f"    - {err}")
    if report.get("errors"):
        lines.append("")
        lines.append("Structural errors:")
        for err in report["errors"]:
            lines.append(f"  - {err}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validator for the curated-event YAML archive.  "
            "Parses the YAML via the loader seam and runs field-level "
            "validation.  Returns a non-zero exit code when any event "
            "fails validation.  Conservative wording — error strings "
            "describe missing or invalid fields only."
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

    events, load_errors = _load_curated_events(args.yaml_path)
    report = validate_curated_events(events)
    # Prepend loader errors so they surface alongside validation
    # errors — operator sees both.
    if load_errors:
        report = dict(report)
        report["errors"] = list(load_errors) + list(report.get("errors", []))
        report["ok"] = False

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

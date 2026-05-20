#!/usr/bin/env python3
"""Read-only YAML loader for the curated-event archive.

Parses a small operator-curated YAML worksheet (``examples/
curated_events.example.yaml``) into a list of plain dicts so the
sibling validator and status-report scripts can consume the events
without re-implementing YAML parsing.

The loader is deliberately tolerant:

* A missing path returns an empty list with a single error string —
  callers (the validator, the status report) decide whether to treat
  that as a hard failure.
* Malformed YAML returns an empty list and a parse error — never an
  uncaught exception.
* The top level may be either a YAML list (``- event_id: 1`` ...) or
  a mapping with an ``events:`` key (``events: [ ... ]``).  Anything
  else surfaces a structural error.
* Field values are NOT coerced at this layer — ``event_date`` may be
  returned as a ``datetime.date`` (PyYAML's default) or as a string,
  whichever the YAML produced; the validator handles both.

Out of scope (deliberately)
---------------------------

* No DB writes, no provider, no LLM, no FastAPI surface.
* No field validation — that lives in
  :mod:`scripts.curated_event_validator`.
* No mutation of inputs — every value round-trips verbatim.

Output contract::

    load_curated_events(yaml_path: str | None) -> tuple[list[dict], list[str]]

Returns ``(events, errors)``.  ``errors`` is empty on a successful
load; on failure it carries one or more conservative error strings
the validator surfaces under its own ``errors`` envelope.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_curated_events(
    yaml_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load a curated-event YAML file into ``(events, errors)``.

    See module docstring for the full contract.
    """
    errors: list[str] = []
    if yaml_path is None:
        errors.append("curated YAML path is None — refusing to load")
        return [], errors

    p = Path(yaml_path)
    if not p.exists():
        errors.append(f"curated YAML file does not exist: {yaml_path}")
        return [], errors

    try:
        import yaml as _yaml
    except ImportError:
        errors.append(
            "PyYAML is not installed; cannot parse curated YAML"
        )
        return [], errors

    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh)
    except _yaml.YAMLError as e:
        errors.append(f"failed to parse curated YAML {yaml_path}: {e}")
        return [], errors
    except OSError as e:
        errors.append(f"failed to read curated YAML {yaml_path}: {e}")
        return [], errors

    # Empty file → ``yaml.safe_load`` returns ``None``.  That's an
    # empty archive, not a parse error.
    if raw is None:
        return [], errors

    # Top level may be a list or a mapping with an ``events:`` key.
    if isinstance(raw, list):
        events_raw = raw
    elif isinstance(raw, dict):
        events_raw = raw.get("events")
        if events_raw is None:
            errors.append(
                "curated YAML mapping has no 'events:' key; expected "
                "either a top-level list or {events: [...]}"
            )
            return [], errors
        if not isinstance(events_raw, list):
            errors.append(
                f"curated YAML 'events' is not a list "
                f"(got {type(events_raw).__name__})"
            )
            return [], errors
    else:
        errors.append(
            f"curated YAML top level is not a list or mapping "
            f"(got {type(raw).__name__})"
        )
        return [], errors

    events: list[dict[str, Any]] = []
    for i, entry in enumerate(events_raw):
        if not isinstance(entry, dict):
            errors.append(
                f"curated YAML entry {i} is not a mapping "
                f"(got {type(entry).__name__})"
            )
            continue
        events.append(dict(entry))

    return events, errors


# ---------------------------------------------------------------------------
# CLI plumbing — minimal: print loaded count + errors.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, out: Any = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Read-only loader for the curated-event YAML archive.  "
            "Parses the file and reports the loaded event count plus "
            "any structural errors.  Does NOT validate field values "
            "(use scripts/curated_event_validator.py for that)."
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
    args = parser.parse_args(argv)

    output = out if out is not None else sys.stdout
    events, errors = load_curated_events(args.yaml_path)
    payload = {
        "loaded_count": len(events),
        "errors":       errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str),
              file=output)
    else:
        print(f"Loaded {len(events)} curated event(s).", file=output)
        if errors:
            print("Errors:", file=output)
            for e in errors:
                print(f"  - {e}", file=output)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
